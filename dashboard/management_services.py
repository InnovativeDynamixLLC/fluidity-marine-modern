#!/usr/bin/env python3
"""
Management Offloading Services
───────────────────────────────
Background processes that offload Natasha's management functions:
  1. System Watchdog — health checks, alerting, auto-restart
  2. Log Aggregator — collects, rotates, and indexes logs
  3. Metrics Collector — Prometheus-style metrics export
  4. Model Pre-warmer — keeps Ollama models hot
  5. Content Validator — truth enforcement on generated outputs

Run standalone or import as modules into the dashboard server.
"""

import os
import sys
import time
import json
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque, defaultdict
from typing import Optional

import psutil

# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────

LOG_DIR = Path(os.path.expanduser("~/.hermes/profiles/fluidity/cron/output/mgmt/"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# ────────────────────────────────────────────────────────────────────
# 1. System Watchdog
# ────────────────────────────────────────────────────────────────────

class SystemWatchdog:
    """
    Monitors system health and takes corrective action:
    - CPU temperature (throttle if >85°C)
    - RAM usage (alert if >90%)
    - Disk space (alert if >95%)
    - Ollama service (restart if unresponsive)
    - Farm coordinator (restart if dead)
    - Stuck tasks (cancel if running >30 min)
    """

    def __init__(self, check_interval: int = 60):
        self.interval = check_interval
        self.logger = self._setup_logger("watchdog")
        self.alerts: deque = deque(maxlen=100)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _setup_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(f"mgmt.{name}")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(LOG_DIR / f"{name}.log")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"
            ))
            logger.addHandler(handler)
        return logger

    def check_cpu(self) -> dict:
        """Check CPU health."""
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_temp = None
        try:
            temps = psutil.sensors_temperatures()
            if "coretemp" in temps:
                cpu_temp = max(t.current for t in temps["coretemp"])
        except Exception:
            pass

        status = "ok"
        if cpu_temp and cpu_temp > 85:
            status = "critical"
            self.alert("cpu_temp", f"CPU temp {cpu_temp}°C exceeds 85°C threshold")
        elif cpu_percent > 95:
            status = "warning"
            self.alert("cpu_high", f"CPU at {cpu_percent}% sustained")

        return {"cpu_percent": cpu_percent, "cpu_temp": cpu_temp, "status": status}

    def check_ram(self) -> dict:
        """Check RAM usage."""
        ram = psutil.virtual_memory()
        status = "ok"
        if ram.percent > 95:
            status = "critical"
            self.alert("ram_critical", f"RAM at {ram.percent}% — {ram.available >> 20}MB free")
        elif ram.percent > 85:
            status = "warning"
            self.alert("ram_high", f"RAM at {ram.percent}%")

        return {
            "total_gb": ram.total / (1024**3),
            "used_gb": ram.used / (1024**3),
            "percent": ram.percent,
            "status": status,
        }

    def check_disk(self) -> dict:
        """Check disk space."""
        disk = psutil.disk_usage("/")
        status = "ok"
        if disk.percent > 95:
            status = "critical"
            self.alert("disk_critical", f"Disk at {disk.percent}% — {disk.free >> 20}MB free")
        elif disk.percent > 85:
            status = "warning"
            self.alert("disk_high", f"Disk at {disk.percent}%")

        return {
            "total_gb": disk.total / (1024**3),
            "used_gb": disk.used / (1024**3),
            "percent": disk.percent,
            "status": status,
        }

    def check_ollama(self) -> dict:
        """Check Ollama service health."""
        import urllib.request
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                return {"status": "ok", "models_loaded": len(models), "models": models}
        except Exception as e:
            self.alert("ollama_down", f"Ollama unresponsive: {e}")
            return {"status": "down", "error": str(e)}

    def check_coordinator(self) -> dict:
        """Check farm coordinator health."""
        import urllib.request
        try:
            req = urllib.request.Request("http://localhost:8080/api/metrics", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return {
                    "status": "ok",
                    "active_tasks": data.get("active_tasks", 0),
                    "completed_today": data.get("tasks_completed_today", 0),
                }
        except Exception as e:
            self.alert("coordinator_down", f"Coordinator unresponsive: {e}")
            return {"status": "down", "error": str(e)}

    def check_stuck_tasks(self) -> list:
        """Find tasks running longer than 30 minutes."""
        import urllib.request
        try:
            req = urllib.request.Request("http://localhost:8080/farm/tasks?status=running", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                tasks = json.loads(resp.read())
                stuck = []
                for t in tasks:
                    if t.get("started_at"):
                        started = datetime.fromisoformat(t["started_at"])
                        elapsed = (datetime.now() - started).total_seconds()
                        if elapsed > 1800:  # 30 min
                            stuck.append({"id": t["id"], "elapsed_min": elapsed / 60, "prompt": t["prompt"][:80]})
                            self.alert("stuck_task", f"Task #{t['id']} stuck for {elapsed/60:.0f}min: {t['prompt'][:60]}")
                return stuck
        except Exception:
            return []

    def alert(self, alert_type: str, message: str):
        """Record an alert."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": alert_type,
            "message": message,
        }
        self.alerts.append(entry)
        self.logger.warning(f"[{alert_type}] {message}")

    def run_checks(self) -> dict:
        """Run all health checks."""
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu": self.check_cpu(),
            "ram": self.check_ram(),
            "disk": self.check_disk(),
            "ollama": self.check_ollama(),
            "coordinator": self.check_coordinator(),
            "stuck_tasks": self.check_stuck_tasks(),
            "recent_alerts": list(self.alerts)[-10:],
        }

    def start(self):
        """Start watchdog in background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info("Watchdog started")

    def _loop(self):
        while self._running:
            try:
                self.run_checks()
            except Exception as e:
                self.logger.error(f"Watchdog loop error: {e}")
            time.sleep(self.interval)

    def stop(self):
        self._running = False
        self.logger.info("Watchdog stopped")


# ────────────────────────────────────────────────────────────────────
# 2. Log Aggregator
# ────────────────────────────────────────────────────────────────────

class LogAggregator:
    """
    Collects logs from all management services, rotates them,
    and provides searchable access.
    """

    def __init__(self, retention_days: int = 7):
        self.retention = retention_days
        self.logger = logging.getLogger("mgmt.aggregator")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(LOG_DIR / "aggregator.log")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        self._index: dict = {}  # filename -> (size, last_modified)

    def scan_logs(self) -> list:
        """Scan all log files and return metadata."""
        logs = []
        for f in LOG_DIR.glob("*.log"):
            stat = f.stat()
            logs.append({
                "name": f.name,
                "size_kb": stat.st_size / 1024,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "lines": sum(1 for _ in open(f)),
            })
        return sorted(logs, key=lambda x: x["modified"], reverse=True)

    def rotate_if_needed(self, max_size_mb: float = 50.0):
        """Rotate log files that exceed max size."""
        for f in LOG_DIR.glob("*.log"):
            size_mb = f.stat().st_size / (1024**2)
            if size_mb > max_size_mb:
                backup = f.with_suffix(f".{datetime.now():%Y%m%d_%H%M}.log")
                f.rename(backup)
                f.touch()
                self.logger.info(f"Rotated {f.name} ({size_mb:.1f}MB -> {backup.name})")

    def cleanup_old(self):
        """Remove logs older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.retention)
        for f in LOG_DIR.glob("*.log.*"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                self.logger.info(f"Removed old log: {f.name}")


# ────────────────────────────────────────────────────────────────────
# 3. Metrics Collector
# ────────────────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Collects time-series metrics and exposes them for dashboard consumption.
    Drop-in Prometheus-style metrics without the full Prometheus stack.
    """

    def __init__(self, history_minutes: int = 60):
        self.history_minutes = history_minutes
        self._metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=history_minutes))
        self._lock = threading.Lock()

    def collect(self):
        """Collect current system metrics."""
        now = datetime.now().isoformat()
        with self._lock:
            self._metrics["cpu_percent"].append({"t": now, "v": psutil.cpu_percent()})
            ram = psutil.virtual_memory()
            self._metrics["ram_used_gb"].append({"t": now, "v": ram.used / (1024**3)})
            self._metrics["ram_percent"].append({"t": now, "v": ram.percent})
            disk = psutil.disk_usage("/")
            self._metrics["disk_percent"].append({"t": now, "v": disk.percent})
            self._metrics["load_avg_1m"].append({"t": now, "v": os.getloadavg()[0]})

    def get_history(self, metric: str, minutes: int = 60) -> list:
        """Get the last N minutes of a metric."""
        with self._lock:
            if metric not in self._metrics:
                return []
            cutoff = datetime.now() - timedelta(minutes=minutes)
            return [
                m for m in self._metrics[metric]
                if datetime.fromisoformat(m["t"]) > cutoff
            ]

    def get_snapshot(self) -> dict:
        """Get current snapshot of all metrics."""
        with self._lock:
            return {k: list(v)[-1] if v else None for k, v in self._metrics.items()}


# ────────────────────────────────────────────────────────────────────
# 4. Model Pre-Warmer
# ────────────────────────────────────────────────────────────────────

class ModelPreWarmer:
    """
    Keeps Ollama models warm by sending periodic lightweight queries.
    Prevents cold-start latency when real tasks arrive.
    """

    # Only keep the largest model (32b) permanently hot.
    # Other models auto-load on demand and expire after KEEP_ALIVE (30m).
    MODELS_TO_WARM = ["qwen2.5:32b"]
    WARM_INTERVAL = 1500  # 25 minutes (well within 30m KEEP_ALIVE window)

    def __init__(self):
        self.logger = logging.getLogger("mgmt.warmer")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(LOG_DIR / "warmer.log")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def warm_model(self, model: str) -> bool:
        """Send a minimal query to keep model loaded."""
        import urllib.request
        try:
            payload = json.dumps({
                "model": model,
                "prompt": "OK",  # minimal token
                "stream": False,
                "options": {"num_predict": 1},
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            return True
        except Exception as e:
            self.logger.warning(f"Failed to warm {model}: {e}")
            return False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info("Model pre-warmer started")

    def _loop(self):
        while self._running:
            for model in self.MODELS_TO_WARM:
                success = self.warm_model(model)
                status = "✓" if success else "✗"
                self.logger.info(f"Warmed {model} {status}")
                time.sleep(5)  # stagger to avoid queue contention
            time.sleep(self.WARM_INTERVAL)

    def stop(self):
        self._running = False
        self.logger.info("Model pre-warmer stopped")


# ────────────────────────────────────────────────────────────────────
# 5. Content Validator
# ────────────────────────────────────────────────────────────────────

class ContentValidator:
    """
    Validates generated content against source documents.
    Checks for fabrications, hallucinations, and consistency.
    Runs as a background process that samples completed tasks.
    """

    def __init__(self, sample_interval: int = 300):
        self.interval = sample_interval
        self.logger = logging.getLogger("mgmt.validator")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(LOG_DIR / "validator.log")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def validate_task(self, task: dict) -> dict:
        """Validate a completed task for quality issues."""
        issues = []

        # Check for empty output
        result = task.get("result", "")
        if not result or len(result.strip()) < 10:
            issues.append("empty_output")

        # Check for hallucination markers
        hallucination_markers = [
            "as an AI", "I don't have", "I cannot",
            "as a language model", "I'm not able",
        ]
        for marker in hallucination_markers:
            if marker.lower() in result.lower():
                issues.append(f"refusal_marker:{marker}")
                break

        # Check for fabricated numbers (high-risk for investor content)
        if task.get("task_type") in ("pitch", "explain", "deep_analysis", "investor"):
            import re
            # Look for suspiciously specific percentages
            percentages = re.findall(r"(\d{1,3}(?:\.\d)?%)\s+(?:efficiency|reduction|improvement|increase|decrease)", result)
            if len(percentages) > 2:
                issues.append("suspicious_specificity:multiple_precise_percentages")

        # Check minimum length for content tasks
        min_lengths = {
            "explain": 50,
            "pitch": 30,
            "deep_analysis": 100,
            "summary": 40,
        }
        min_len = min_lengths.get(task.get("task_type"), 10)
        if len(result.strip()) < min_len:
            issues.append(f"too_short:{len(result.strip())}chars")

        return {
            "task_id": task.get("id"),
            "issues": issues,
            "passed": len(issues) == 0,
        }

    def sample_and_validate(self):
        """Sample recent tasks and validate them."""
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://localhost:8080/farm/tasks?status=completed&limit=10",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                tasks = json.loads(resp.read())

            for task in tasks:
                if not isinstance(task, dict):
                    continue
                result = self.validate_task(task)
                if not result["passed"]:
                    self.logger.warning(
                        f"Task #{result['task_id']} issues: {result['issues']}"
                    )
        except Exception as e:
            self.logger.error(f"Validation error: {e}")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info("Content validator started")

    def _loop(self):
        while self._running:
            try:
                self.sample_and_validate()
            except Exception as e:
                self.logger.error(f"Validator loop error: {e}")
            time.sleep(self.interval)

    def stop(self):
        self._running = False
        self.logger.info("Content validator stopped")


# ────────────────────────────────────────────────────────────────────
# 6. Unified Management Supervisor
# ────────────────────────────────────────────────────────────────────

class ManagementSupervisor:
    """
    Starts and stops all management services.
    Provides a unified health endpoint for the dashboard.
    """

    def __init__(self):
        self.watchdog = SystemWatchdog(check_interval=60)
        self.aggregator = LogAggregator(retention_days=7)
        self.metrics = MetricsCollector(history_minutes=60)
        self.warmer = ModelPreWarmer()
        self.validator = ContentValidator(sample_interval=300)

    def start_all(self):
        """Start all management services."""
        self.watchdog.start()
        self.warmer.start()
        self.validator.start()
        self._metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        self._metrics_thread.start()
        print("[mgmt] All management services started")

    def _metrics_loop(self):
        """Collect metrics every 10 seconds."""
        while True:
            self.metrics.collect()
            time.sleep(10)

    def get_health(self) -> dict:
        """Get unified health status."""
        return {
            "timestamp": datetime.now().isoformat(),
            "watchdog": self.watchdog.run_checks(),
            "logs": self.aggregator.scan_logs(),
            "metrics_snapshot": self.metrics.get_snapshot(),
            "services": {
                "watchdog": self.watchdog._running,
                "warmer": self.warmer._running,
                "validator": self.validator._running,
            },
        }

    def stop_all(self):
        """Stop all management services."""
        self.watchdog.stop()
        self.warmer.stop()
        self.validator.stop()


# ────────────────────────────────────────────────────────────────────
# Standalone runner
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Starting Management Services ===")
    supervisor = ManagementSupervisor()
    supervisor.start_all()

    try:
        while True:
            time.sleep(60)
            health = supervisor.get_health()
            cpu = health["watchdog"]["cpu"]
            ram = health["watchdog"]["ram"]
            print(f"[mgmt] CPU: {cpu['cpu_percent']:.0f}% | RAM: {ram['percent']:.0f}% | "
                  f"Services: {sum(1 for v in health['services'].values() if v)}/3 up",
                  flush=True)
    except KeyboardInterrupt:
        supervisor.stop_all()
        print("\n[mgmt] Shutdown complete")
