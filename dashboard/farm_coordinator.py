#!/usr/bin/env python3
"""
Farm Coordinator — autonomous task queue, dispatcher, and reporter.
Sits between Natasha (CTO) and the local Ollama task farm.

Usage:
    from farm_coordinator import ResultStore, Dispatcher, Reporter, ResourceMonitor
    store = ResultStore()
    dispatcher = Dispatcher(store)
    dispatcher.start()
"""

import csv
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psutil

# ── Paths ──────────────────────────────────────────────────────────
FARM_SCRIPT = os.path.expanduser(
    "~/.hermes/profiles/fluidity/scripts/local_farm.py"
)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "farm_tasks.db")
QUEUE_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_depth.csv")

# ── Model timeout registry (mirrors local_farm.py MODELS) ──────────
MODEL_TIMEOUTS = {
    "qwen2.5:32b": 900,
    "qwen2.5:14b": 900,
    "qwen2.5-coder:7b": 400,
    "qwen2.5:7b": 300,
    "llama3.2:3b": 240,
}

# ── Task-type timeout overrides — content tasks need more time ──────
TASK_TYPE_TIMEOUTS = {
    "blog-post": 600,
    "landing-page": 600,
    "press-release": 600,
    "social-twitter": 300,
    "social-instagram": 300,
    "social-linkedin": 300,
    "social-facebook": 300,
    "social-tiktok": 300,
    "social-reddit": 300,
    "web-page": 600,
    "email-template": 300,
    "investor-doc": 600,
}

# ── Per-model concurrency limits ──────────────────────────────────
# 14b: solo queue — only dispatched when no other models have work
# 32b: solo slot — cannot run concurrently with any other model
# Fast models (7b, coder, 3b): share remaining slots
GLOBAL_MAX_CONCURRENT = 3

MODEL_SLOTS = {
    "qwen2.5:14b": 1,
    "qwen2.5:7b": 1,
    "qwen2.5-coder:7b": 1,
    "llama3.2:3b": 2,
}
MODEL_SLOTS_DEFAULT = 1

# ── 32b: no longer disabled, but gets solo slot ──────────────────
# Removed from MODEL_DISABLED. When 32b dispatches, global cap drops to 1.

# ── Models that should never be auto-loaded (too large) ────────────
MODEL_NO_AUTOLOAD = {"qwen2.5:32b"}

# ── Model fallback chain: when a model times out, try a faster one ──
MODEL_FALLBACK = {
    "qwen2.5:32b": "qwen2.5:14b",
    "qwen2.5:14b": "qwen2.5:7b",
    "qwen2.5-coder:7b": "qwen2.5:7b",
}

# ── Models that should never be loaded automatically (too large / blacklisted) ──
MODEL_NO_AUTOLOAD = {"qwen2.5:32b"}

# ── Log file for structured JSON events ──
import logging
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "farm_events.jsonl")
_log_lock = threading.Lock()

def _log_event(event_type: str, **kwargs):
    """Write a structured JSON event to farm_events.jsonl."""
    try:
        entry = {"ts": datetime.now().isoformat(), "event": event_type, **kwargs}
        with _log_lock:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# TASK DATA MODEL
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Task:
    id: Optional[int] = None
    prompt: str = ""
    model: str = "qwen2.5:7b"
    task_type: str = ""
    priority: int = 0
    status: str = "submitted"
    result: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_per_second: float = 0.0
    elapsed_seconds: float = 0.0
    error: str = ""
    retry_count: int = 0
    max_retries: int = 0
    submitted_at: str = ""
    started_at: str = ""
    completed_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# RESULT STORE (SQLite persistence)
# ═══════════════════════════════════════════════════════════════════

class ResultStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        """Create a thread-safe connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    task_type TEXT DEFAULT '',
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'submitted',
                    result TEXT DEFAULT '',
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    tokens_per_second REAL DEFAULT 0.0,
                    elapsed_seconds REAL DEFAULT 0.0,
                    error TEXT DEFAULT '',
                    submitted_at TEXT DEFAULT '',
                    started_at TEXT DEFAULT '',
                    completed_at TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_submitted ON tasks(submitted_at)")
            # Add retry columns if missing (migration from earlier schema)
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
                conn.execute("ALTER TABLE tasks ADD COLUMN max_retries INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # columns already exist
            conn.commit()
        finally:
            conn.close()

    def find_duplicate(self, prompt: str, model: str) -> int | None:
        """Return task_id if an identical prompt+model is queued or running, else None."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id FROM tasks WHERE prompt = ? AND model = ? AND status IN ('queued', 'running', 'dispatching') LIMIT 1",
                (prompt, model)
            )
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def add(self, task: Task) -> int:
        task.submitted_at = datetime.now().isoformat()
        task.status = "submitted"
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO tasks (prompt, model, task_type, priority, status,
                   retry_count, max_retries, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task.prompt, task.model, task.task_type, task.priority,
                 task.status, task.retry_count, task.max_retries, task.submitted_at)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update(self, task: Task):
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE tasks SET status=?, result=?, prompt_tokens=?,
                   completion_tokens=?, tokens_per_second=?, elapsed_seconds=?,
                   error=?, retry_count=?, max_retries=?, started_at=?, completed_at=?
                   WHERE id=?""",
                (task.status, task.result, task.prompt_tokens,
                 task.completion_tokens, task.tokens_per_second,
                 task.elapsed_seconds, task.error, task.retry_count,
                 task.max_retries, task.started_at,
                 task.completed_at, task.id)
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, task_id: int) -> Optional[Task]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                return Task(**dict(row))
            return None
        finally:
            conn.close()

    def list_by_status(self, status: str, limit: int = 50) -> list[Task]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY priority DESC, id ASC LIMIT ?",
                (status, limit)
            ).fetchall()
            return [Task(**dict(r)) for r in rows]
        finally:
            conn.close()

    def list_recent(self, limit: int = 50) -> list[Task]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [Task(**dict(r)) for r in rows]
        finally:
            conn.close()

    def list_since(self, since_iso: str) -> list[Task]:
        """Return tasks completed since a given ISO timestamp."""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE completed_at >= ? ORDER BY id DESC",
                (since_iso,)
            ).fetchall()
            return [Task(**dict(r)) for r in rows]
        finally:
            conn.close()

    def count_by_status(self, status: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status=?", (status,)
            ).fetchone()
            return row[0]
        finally:
            conn.close()

    def get_stats(self) -> dict:
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            completed = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='completed'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='failed'"
            ).fetchone()[0]
            running = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='running'"
            ).fetchone()[0]
            queued = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='queued'"
            ).fetchone()[0]
            avg_tps = conn.execute(
                "SELECT AVG(tokens_per_second) FROM tasks WHERE status='completed'"
            ).fetchone()[0] or 0.0
            total_tokens = conn.execute(
                "SELECT SUM(completion_tokens) FROM tasks WHERE status='completed'"
            ).fetchone()[0] or 0
            return {
                "total": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "queued": queued,
                "avg_tps": round(avg_tps, 1),
                "total_tokens": total_tokens,
            }
        finally:
            conn.close()

    def per_model_stats(self, since_hours: int = 24) -> list[dict]:
        """Return per-model stats: completed, failed, error rate, avg tps."""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT
                    model,
                    COUNT(*) as total,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                    ROUND(AVG(CASE WHEN status='completed' THEN tokens_per_second END), 1) as avg_tps,
                    ROUND(AVG(CASE WHEN status='completed' THEN elapsed_seconds END), 1) as avg_elapsed
                FROM tasks
                WHERE completed_at >= datetime('now', ?)
                GROUP BY model
                ORDER BY total DESC
            """, (f'-{since_hours} hours',)).fetchall()
            result = []
            for r in rows:
                total = r["total"]
                failed = r["failed"] or 0
                result.append({
                    "model": r["model"],
                    "total": total,
                    "completed": r["completed"] or 0,
                    "failed": failed,
                    "error_rate": round(failed / max(total, 1) * 100, 1),
                    "avg_tps": r["avg_tps"] or 0.0,
                    "avg_elapsed": r["avg_elapsed"] or 0.0,
                })
            return result
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════
# RESOURCE MONITOR
# ═══════════════════════════════════════════════════════════════════

class ResourceMonitor:
    @staticmethod
    def get_loaded_models() -> list[str]:
        """Return list of model names currently loaded in Ollama."""
        try:
            raw = subprocess.check_output(["ollama", "ps"], text=True).strip()
            lines = raw.split("\n")[1:]
            return [line.split()[0] for line in lines if len(line.strip()) > 1]
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

    @staticmethod
    def model_available(model_name: str) -> bool:
        """Check if a model is installed in Ollama (available, not necessarily loaded)."""
        try:
            result = subprocess.check_output(
                ["ollama", "list"], text=True, timeout=10
            ).strip()
            for line in result.split("\n")[1:]:
                if line.startswith(model_name):
                    return True
            return False
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def get_active_request_count() -> int:
        """Count local_farm.py processes currently running."""
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", "local_farm.py"], text=True
            ).strip()
            return len(out.split("\n")) if out else 0
        except subprocess.CalledProcessError:
            return 0

    @staticmethod
    def get_system_stats() -> dict:
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": psutil.cpu_percent(),
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
        }

    @staticmethod
    def can_dispatch(target_model: str, max_concurrent: int = 4) -> tuple[bool, str]:
        active = ResourceMonitor.get_active_request_count()
        loaded = ResourceMonitor.get_loaded_models()

        # 1. Global concurrency ceiling
        if active >= max_concurrent:
            return False, f"At global concurrency limit ({active}/{max_concurrent})"

        # 2. Per-model slot check — count active local_farm.py processes for this model
        try:
            result = subprocess.check_output(
                ["ps", "-eo", "args"], text=True
            )
            model_specific = sum(1 for line in result.split("\n") if target_model in line and "local_farm.py" in line)
        except subprocess.CalledProcessError:
            model_specific = 0

        allowed = MODEL_SLOTS.get(target_model, MODEL_SLOTS_DEFAULT)
        if model_specific >= allowed:
            return False, f"Model '{target_model}' at its slot limit ({model_specific}/{allowed})"

        return True, "ok"


# ═══════════════════════════════════════════════════════════════════
# DISPATCHER (background thread)
# ═══════════════════════════════════════════════════════════════════

class Dispatcher(threading.Thread):
    def __init__(self, store: ResultStore, poll_interval: float = 5.0,
                 max_concurrent: int = 3, stagger_seconds: float = 5.0):
        super().__init__(daemon=True, name="farm-dispatcher")
        self.store = store
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.stagger_seconds = stagger_seconds
        self._running = True
        self._last_dispatch_time = 0.0
        # pid → (Popen, task_id)
        self._active: dict[int, tuple[subprocess.Popen, int]] = {}
        self._lock = threading.Lock()

    def run(self):
        print("[dispatcher] Started", flush=True)
        # Startup: reap any orphaned tasks from a previous dashboard restart.
        self._reap_orphans()
        self._zombie_tick_counter = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[dispatcher] Error: {e}", flush=True)
            time.sleep(self.poll_interval)
        print("[dispatcher] Stopped", flush=True)

    def stop(self):
        self._running = False

    def _tick(self):
        # 0. Periodic zombie detection (every 10th tick ≈ 50s)
        self._zombie_tick_counter += 1
        if self._zombie_tick_counter % 10 == 0:
            self._reap_zombies()

        # 1. Reap completed processes
        self._reap_completed()

        # 2. Periodic model cache management (every 20th tick ≈ 100s)
        if self._zombie_tick_counter % 20 == 0:
            self._manage_model_cache()

        # 3. Determine effective concurrency limit
        # If 14b or 32b is running, reduce global cap to preserve CPU / enforce solo
        with self._lock:
            active_count = len(self._active)
            active_models = set()
            for _, tid in self._active.values():
                t = self.store.get(tid)
                if t:
                    active_models.add(t.model)

        effective_max = GLOBAL_MAX_CONCURRENT
        if "qwen2.5:32b" in active_models:
            effective_max = 1  # 32b cannot run concurrently with anything
        elif "qwen2.5:14b" in active_models:
            effective_max = 2  # 14b hogs CPU, reduce to 2

        if active_count >= effective_max:
            return

        # 4. Check stagger delay
        if time.monotonic() - self._last_dispatch_time < self.stagger_seconds:
            return

        # 5. Pick next task — tiered dispatch:
        #    Tier 1: Fast models (3b, 7b, coder) — always dispatch first
        #    Tier 2: 14b — only when no fast-model tasks remain
        #    Tier 3: 32b — only when queue is otherwise empty
        monitor = ResourceMonitor()
        queued = self.store.list_by_status("queued", limit=100)

        # Separate into tiers
        tier_fast = []   # 3b, 7b, coder
        tier_14b = []    # 14b
        tier_32b = []    # 32b

        for task in queued:
            can, _ = monitor.can_dispatch(task.model, effective_max)
            if not can:
                continue
            if task.model == "qwen2.5:14b":
                tier_14b.append(task)
            elif task.model == "qwen2.5:32b":
                tier_32b.append(task)
            else:
                tier_fast.append(task)

        # Dispatch as many fast tasks as slots allow (up to effective_max)
        dispatched = 0
        while tier_fast and (active_count + dispatched) < effective_max:
            self._dispatch(tier_fast.pop(0))
            dispatched += 1

        if dispatched > 0:
            return

        if tier_14b:
            # Only dispatch 14b if no fast tasks are queued at all
            fast_queued = any(
                t.model != "qwen2.5:14b" and t.model != "qwen2.5:32b"
                for t in queued
            )
            if not fast_queued:
                self._dispatch(tier_14b[0])
                return

        if tier_32b:
            # Only dispatch 32b if nothing else is queued
            if len(queued) <= len(tier_32b):
                self._dispatch(tier_32b[0])
                return

        # 6. Dead-queue detection
        if queued:
            models_in_queue = set(t.model for t in queued[:20])
            print(f"[dispatcher] Queue stalled: {len(queued)} queued, models: {models_in_queue} "
                  f"(active={active_count}, effective_max={effective_max})", flush=True)

        # 7. Log queue depth to time-series CSV
        self._log_queue_depth()

    def _log_queue_depth(self):
        """Append current queue depth + running count to CSV."""
        try:
            queued_n = self.store.count_by_status("queued")
            running_n = len(self._active)
            now = datetime.now().isoformat()
            write_header = not os.path.exists(QUEUE_LOG_PATH) or os.path.getsize(QUEUE_LOG_PATH) == 0
            with open(QUEUE_LOG_PATH, "a", newline="") as f:
                w = csv.writer(f)
                if write_header:
                    w.writerow(["timestamp", "queued", "running"])
                w.writerow([now, queued_n, running_n])
        except Exception:
            pass  # non-critical — don't break dispatcher

    def _manage_model_cache(self):
        """Periodic model cache management: unload idle models, preload backlogged ones.
        
        Strategy:
        - Unload 32b if it's loaded and has no queued/running tasks (frees 23GB RAM)
        - If any installed model has 10+ queued tasks but is NOT loaded, preload it
        - Skip models in MODEL_NO_AUTOLOAD
        """
        try:
            loaded = ResourceMonitor.get_loaded_models()

            # --- Unload idle models ---
            for model in list(loaded):
                if model in MODEL_NO_AUTOLOAD:
                    # Check: does this model actually have any work?
                    conn = self.store._connect()
                    try:
                        active = conn.execute(
                            "SELECT COUNT(*) FROM tasks WHERE model=? AND status IN ('queued','running','dispatching')",
                            (model,)
                        ).fetchone()[0]
                    finally:
                        conn.close()
                    if active == 0:
                        # Unload via Ollama API (keep_alive=0)
                        import urllib.request
                        req = urllib.request.Request(
                            "http://localhost:11434/api/generate",
                            data=json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode(),
                            headers={"Content-Type": "application/json"}
                        )
                        try:
                            urllib.request.urlopen(req, timeout=5)
                            _log_event("model_unloaded", model=model, reason="idle_no_tasks")
                            print(f"[cache] Unloaded idle model: {model}", flush=True)
                        except Exception:
                            pass

            # --- Preload backlogged models ---
            installed = set()
            try:
                out = subprocess.check_output(["ollama", "list"], text=True, timeout=5).strip()
                for line in out.split("\n")[1:]:
                    name = line.split()[0] if line.strip() else ""
                    if name:
                        installed.add(name)
            except Exception:
                pass

            for model in installed:
                if model in loaded or model in MODEL_NO_AUTOLOAD:
                    continue
                conn = self.store._connect()
                try:
                    queued_for = conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE model=? AND status='queued'",
                        (model,)
                    ).fetchone()[0]
                finally:
                    conn.close()
                if queued_for >= 10:
                    # Preload by sending a minimal warmup request
                    import urllib.request
                    req = urllib.request.Request(
                        "http://localhost:11434/api/generate",
                        data=json.dumps({"model": model, "prompt": "warmup", "stream": False}).encode(),
                        headers={"Content-Type": "application/json"}
                    )
                    try:
                        urllib.request.urlopen(req, timeout=30)
                        _log_event("model_preloaded", model=model, queued=queued_for)
                        print(f"[cache] Preloaded model: {model} ({queued_for} queued)", flush=True)
                    except Exception:
                        pass

        except Exception:
            pass  # non-critical

    def _dispatch(self, task: Task):
        # Pre-dispatch: verify model exists in Ollama
        if not ResourceMonitor.model_available(task.model):
            task.status = "failed"
            task.error = f"model '{task.model}' not installed in Ollama"
            task.completed_at = datetime.now().isoformat()
            self.store.update(task)
            print(f"[dispatcher] Task #{task.id} → FAILED: model '{task.model}' not available", flush=True)
            return

        task.status = "dispatching"
        task.started_at = datetime.now().isoformat()
        self.store.update(task)

        # Determine timeout: task-type override > model default
        timeout = TASK_TYPE_TIMEOUTS.get(task.task_type, MODEL_TIMEOUTS.get(task.model, 300))
        cmd = [
            "python3", FARM_SCRIPT, "task", task.prompt,
            "--model", task.model,
            "--timeout", str(timeout),
        ]
        if task.task_type:
            cmd.extend(["--type", task.task_type])

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with self._lock:
            self._active[proc.pid] = (proc, task.id)

        task.status = "running"
        self.store.update(task)
        self._last_dispatch_time = time.monotonic()
        print(f"[dispatcher] Task #{task.id} → {task.model} (pid={proc.pid})", flush=True)
        _log_event("task_dispatched", task_id=task.id, model=task.model, task_type=task.task_type, pid=proc.pid)

    def _reap_completed(self):
        with self._lock:
            pids = list(self._active.keys())

        for pid in pids:
            with self._lock:
                entry = self._active.get(pid)
                if entry is None:
                    continue
                proc, task_id = entry

            # Check if process finished
            ret = proc.poll()
            if ret is None:
                continue  # still running

            # Process exited — collect output
            stdout, stderr = proc.communicate(timeout=5)
            task = self.store.get(task_id)

            if task is None:
                with self._lock:
                    self._active.pop(pid, None)
                continue

            if ret == 0:
                # Parse stderr for metadata: ── model | N tokens | Xs | Y t/s ──
                meta = self._parse_metadata(stderr)
                task.status = "completed"
                task.result = stdout.strip()
                task.prompt_tokens = meta.get("prompt_tokens", 0)
                task.completion_tokens = meta.get("completion_tokens", 0)
                task.tokens_per_second = meta.get("tokens_per_second", 0.0)
                task.elapsed_seconds = meta.get("elapsed_seconds", 0.0)
                task.completed_at = datetime.now().isoformat()
            else:
                # Auto-retry: re-queue if under max_retries.
                # But skip retry on timeout — the task is too big for this model.
                error_text = stderr.strip()[:200] if stderr else f"Exit code {ret}"
                if task.retry_count < task.max_retries and "timed out" not in error_text:
                    task.retry_count += 1
                    task.status = "queued"
                    task.error = error_text
                    task.result = ""
                    task.completed_at = ""
                    task.started_at = ""
                else:
                    task.status = "failed"
                    task.error = stderr.strip()[:500] if stderr else f"Exit code {ret}"
                    task.completed_at = datetime.now().isoformat()
                    if "timed out" in error_text:
                        task.error = task.error[:200] + " (timeout — not retried)"
            self.store.update(task)
            with self._lock:
                self._active.pop(pid, None)
            print(f"[dispatcher] Task #{task_id} → {task.status} ({task.tokens_per_second} t/s)", flush=True)
            _log_event("task_completed" if ret == 0 else "task_failed",
                       task_id=task_id, status=task.status, model=task.model,
                       tokens_per_second=task.tokens_per_second,
                       elapsed_seconds=task.elapsed_seconds,
                       error=task.error[:100] if task.error else None)

    def _reap_orphans(self):
        """On startup: kill all orphaned local_farm.py processes and re-queue
        any running/dispatching tasks from the previous dashboard instance with
        incremented retry_count. Tasks that exceed max_retries are marked failed."""
        # Kill all lingering local_farm.py processes — they belong to old dashboard
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", "local_farm.py"], text=True
            ).strip()
            pids = out.split("\n")
            for pid_str in pids:
                if pid_str:
                    try:
                        os.kill(int(pid_str), 9)
                    except (ProcessLookupError, PermissionError):
                        pass
            if pids and pids[0]:
                print(f"[dispatcher] Killed {len(pids)} orphaned local_farm.py processes", flush=True)
        except subprocess.CalledProcessError:
            pass  # no orphaned processes found

        orphaned = self.store.list_by_status("running", limit=500) + \
                   self.store.list_by_status("dispatching", limit=500)
        if not orphaned:
            return
        requeued = 0
        failed = 0
        for task in orphaned:
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = "queued"
                task.error = f"dashboard restarted — re-queued (attempt {task.retry_count}/{task.max_retries})"
                task.started_at = ""
                task.completed_at = ""
                requeued += 1
            else:
                task.status = "failed"
                task.error = f"dashboard restarted — max retries ({task.max_retries}) exhausted"
                task.completed_at = datetime.now().isoformat()
                failed += 1
            self.store.update(task)
        _log_event("orphan_reap", requeued=requeued, failed=failed)
        print(f"[dispatcher] Reaped {len(orphaned)} orphaned tasks: {requeued} re-queued, {failed} failed", flush=True)

    def _reap_zombies(self):
        """Mark tasks as failed if they've been 'running' for > 3x their
        model's timeout. These are stuck processes that local_farm.py didn't
        time out properly, or orphaned pids the dispatcher lost track of."""
        running = self.store.list_by_status("running", limit=500)
        if not running:
            return
        now = datetime.now()
        zombies = 0
        for task in running:
            timeout = TASK_TYPE_TIMEOUTS.get(task.task_type, MODEL_TIMEOUTS.get(task.model, 300))
            zombie_threshold = 3 * timeout
            try:
                started = datetime.fromisoformat(task.started_at)
                age_seconds = (now - started).total_seconds()
            except (ValueError, TypeError):
                continue
            if age_seconds > zombie_threshold:
                # Check if we can fallback to a faster model
                fallback = MODEL_FALLBACK.get(task.model)
                if fallback and task.retry_count < task.max_retries:
                    original_model = task.model
                    task.retry_count += 1
                    task.model = fallback
                    task.status = "queued"
                    task.error = f"zombie: {age_seconds:.0f}s > 3x timeout, retrying with {fallback}"
                    task.started_at = ""
                    task.completed_at = ""
                    self.store.update(task)
                    _log_event("zombie_retry", task_id=task.id, original_model=original_model, fallback_model=fallback)
                    zombies += 1
                else:
                    task.status = "failed"
                    task.error = f"zombie: exceeded 3x timeout ({age_seconds:.0f}s > {zombie_threshold}s)"
                    task.completed_at = now.isoformat()
                    self.store.update(task)
                    zombies += 1
        if zombies:
            print(f"[dispatcher] Reaped {zombies} zombie tasks (3x timeout)", flush=True)

    def _parse_metadata(self, stderr: str) -> dict:
        """Parse: '── qwen2.5:7b | 329 tokens | 112.91s | 3.7 t/s ──'"""
        # Match the metadata line format
        match = re.search(
            r"──\s*(\S+)\s*\|\s*(\d+)\s+tokens\s*\|\s*([\d.]+)s\s*\|\s*([\d.]+)\s+t/s\s*──",
            stderr
        )
        if match:
            return {
                "model": match.group(1),
                "completion_tokens": int(match.group(2)),
                "elapsed_seconds": float(match.group(3)),
                "tokens_per_second": float(match.group(4)),
            }
        return {}

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def active_task_ids(self) -> list[int]:
        with self._lock:
            return [tid for _, tid in self._active.values()]


# ═══════════════════════════════════════════════════════════════════
# REPORTER (periodic aggregation)
# ═══════════════════════════════════════════════════════════════════

class Reporter(threading.Thread):
    """Periodically generates aggregate reports. The callback receives the
    report dict — wire it to whatever delivery mechanism you want."""

    def __init__(self, store: ResultStore, interval_minutes: int = 30,
                 callback=None):
        super().__init__(daemon=True, name="farm-reporter")
        self.store = store
        self.interval = interval_minutes * 60
        self.callback = callback
        self._last_report_at: Optional[str] = None

    def run(self):
        print(f"[reporter] Started (every {self.interval // 60} min)", flush=True)
        while True:
            time.sleep(self.interval)
            try:
                report = self.generate()
                if self.callback:
                    self.callback(report)
            except Exception as e:
                print(f"[reporter] Error: {e}", flush=True)

    def generate(self) -> dict:
        now = datetime.now().isoformat()
        since = self._last_report_at

        stats = self.store.get_stats()
        recent = self.store.list_recent(10)

        # Tasks completed since last report
        new_tasks = []
        if since:
            new_tasks = self.store.list_since(since)

        self._last_report_at = now

        return {
            "generated_at": now,
            "since": since,
            "stats": stats,
            "new_completed": len([t for t in new_tasks if t.status == "completed"]),
            "new_failed": len([t for t in new_tasks if t.status == "failed"]),
            "recent": [
                {
                    "id": t.id,
                    "model": t.model,
                    "task_type": t.task_type,
                    "status": t.status,
                    "tokens_per_second": t.tokens_per_second,
                    "elapsed_seconds": t.elapsed_seconds,
                    "completed_at": t.completed_at,
                }
                for t in recent if t.status in ("completed", "failed")
            ],
        }
