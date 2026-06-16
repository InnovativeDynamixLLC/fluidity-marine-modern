#!/usr/bin/env python3
"""
Farm API — Flask Blueprint for task submission, queue status, and reports.
Mounted by dashboard_server.py at /farm.
"""

from flask import Blueprint, request, jsonify
from farm_coordinator import Task, ResultStore

api = Blueprint("farm_api", __name__, url_prefix="/farm")

_store: ResultStore = None


def init_store(store: ResultStore):
    global _store
    _store = store


# ── POST /farm/tasks — submit a task ───────────────────────────────

@api.route("/tasks", methods=["POST"])
def submit_task():
    data = request.get_json(silent=True) or {}
    if "prompt" not in data:
        return jsonify({"error": "prompt is required"}), 400

    # Dedup: check if an identical prompt+model is already queued or running
    existing = _store.find_duplicate(data["prompt"], data.get("model", "qwen2.5:7b"))
    if existing:
        return jsonify({"task_id": existing, "status": "duplicate", "message": "identical task already queued/running"}), 200

    task = Task(
        prompt=data["prompt"],
        model=data.get("model", "qwen2.5:7b"),
        task_type=data.get("type", ""),
        priority=data.get("priority", 0),
        max_retries=data.get("max_retries", 2),
    )
    task_id = _store.add(task)

    # Mark as queued so the dispatcher picks it up
    task.id = task_id
    task.status = "queued"
    _store.update(task)

    return jsonify({"task_id": task_id, "status": "queued"}), 201


# ── GET /farm/tasks — list tasks ────────────────────────────────────

@api.route("/tasks", methods=["GET"])
def list_tasks():
    status = request.args.get("status")
    limit = int(request.args.get("limit", 50))
    model = request.args.get("model")
    sort = request.args.get("sort", "oldest")  # "oldest" (by id ASC) or "newest" (by id DESC)

    if status:
        tasks = _store.list_by_status(status, limit)
    else:
        tasks = _store.list_recent(limit)

    # Apply model filter
    if model:
        tasks = [t for t in tasks if t.model == model]

    # Apply sort
    if sort == "newest":
        tasks = sorted(tasks, key=lambda t: t.id or 0, reverse=True)
    # else: default oldest-first (already sorted by list_by_status / list_recent)

    return jsonify([_task_to_dict(t) for t in tasks])


# ── GET /farm/tasks/<id> — get one task ─────────────────────────────

@api.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    task = _store.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(_task_to_dict(task))


# ── POST /farm/tasks/<id>/cancel — cancel a task ─────────────────────

@api.route("/tasks/<int:task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    task = _store.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    if task.status not in ("queued", "running", "dispatching"):
        return jsonify({"error": f"cannot cancel task in status '{task.status}'"}), 409
    task.status = "cancelled"
    task.error = "cancelled by operator"
    task.completed_at = __import__("datetime").datetime.now().isoformat()
    _store.update(task)
    return jsonify({"task_id": task_id, "status": "cancelled"})


# ── GET /farm/queue — queue status snapshot ─────────────────────────

@api.route("/queue", methods=["GET"])
def queue_status():
    queued = _store.list_by_status("queued", 100)
    running = _store.list_by_status("running", 10)
    return jsonify({
        "queued_count": len(queued),
        "running_count": len(running),
        "queued": [_task_to_dict(t) for t in queued[:10]],
        "running": [_task_to_dict(t) for t in running],
    })


# ── GET /farm/models — per-model error rate tracking ─────────────────

@api.route("/models", methods=["GET"])
def model_stats():
    hours = int(request.args.get("hours", 24))
    return jsonify(_store.per_model_stats(since_hours=hours))


# ── GET /farm/queue/history — queue depth time-series ────────────────

@api.route("/queue/history", methods=["GET"])
def queue_history():
    import csv, os
    from farm_coordinator import QUEUE_LOG_PATH
    limit = int(request.args.get("limit", 200))
    points = []
    try:
        with open(QUEUE_LOG_PATH, "r") as f:
            reader = csv.DictReader(f)
            for row in list(reader)[-limit:]:
                points.append({
                    "timestamp": row["timestamp"],
                    "queued": int(row["queued"]),
                    "running": int(row["running"]),
                })
    except FileNotFoundError:
        pass
    return jsonify(points)


# ── GET /farm/report — aggregated report ────────────────────────────

@api.route("/report", methods=["GET"])
def report():
    stats = _store.get_stats()
    recent = _store.list_recent(20)
    return jsonify({
        "stats": stats,
        "recent": [_task_to_dict(t) for t in recent],
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    })


# ── Helpers ─────────────────────────────────────────────────────────

def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "prompt": t.prompt[:200] + ("..." if len(t.prompt) > 200 else ""),
        "model": t.model,
        "task_type": t.task_type,
        "priority": t.priority,
        "status": t.status,
        "result": t.result[:500] if t.result else "",
        "tokens_per_second": t.tokens_per_second,
        "elapsed_seconds": t.elapsed_seconds,
        "error": t.error,
        "retry_count": t.retry_count,
        "max_retries": t.max_retries,
        "submitted_at": t.submitted_at,
        "started_at": t.started_at,
        "completed_at": t.completed_at,
    }
