#!/usr/bin/env python3
"""
Fluidity Marine — Local Dashboard Server
Serves real-time metrics API + static dashboard + farm coordinator.
"""

import os
import subprocess
import threading

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import psutil

from farm_coordinator import ResultStore, Dispatcher, Reporter, ResourceMonitor
from farm_api import api as farm_api, init_store
from cloud_monitor import get_cloud_monitor
from management_services import ManagementSupervisor

app = Flask(__name__, static_folder="static")
CORS(app)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Farm Coordinator ────────────────────────────────────────────────

store = ResultStore()
init_store(store)
app.register_blueprint(farm_api)

dispatcher = Dispatcher(store, poll_interval=3.0, max_concurrent=3, stagger_seconds=5.0)

# Reporter callback — logs to stdout; Natasha reads reports from here
_report_lock = threading.Lock()
_last_report: dict = {}

def on_report(report: dict):
    global _last_report
    with _report_lock:
        _last_report = report
    print(f"\n[reporter] ═══ Farm Report ═══", flush=True)
    print(f"  Completed: {report['stats']['completed']} total "
          f"(+{report['new_completed']} since last report)", flush=True)
    print(f"  Failed:    {report['stats']['failed']} "
          f"(+{report['new_failed']} since last report)", flush=True)
    print(f"  Queued:    {report['stats']['queued']}", flush=True)
    print(f"  Avg t/s:   {report['stats']['avg_tps']}", flush=True)
    print(f"  Tokens:    {report['stats']['total_tokens']}", flush=True)
    print(f"[reporter] ═══════════════════\n", flush=True)

reporter = Reporter(store, interval_minutes=30, callback=on_report)

# ── Management Services ────────────────────────────────────────────

mgmt_supervisor = ManagementSupervisor()
mgmt_supervisor.start_all()

# ── Cloud Monitor ──────────────────────────────────────────────────

cloud = get_cloud_monitor()

dispatcher.start()
reporter.start()


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "dashboard.html")


@app.route("/api/metrics")
def metrics():
    # Real stats from the coordinator
    stats = store.get_stats()
    sys_stats = ResourceMonitor.get_system_stats()

    return jsonify({
        "cpu_percent": sys_stats["cpu_percent"],
        "ram_used_gb": sys_stats["ram_used_gb"],
        "ram_total_gb": sys_stats["ram_total_gb"],
        "ollama_models_loaded": ResourceMonitor.get_loaded_models(),
        "active_tasks": dispatcher.active_count,
        "tasks_completed_today": stats["completed"],
        "tasks_failed_today": stats["failed"],
        "tasks_queued": stats["queued"],
        "avg_tokens_per_sec": stats["avg_tps"],
        "total_tokens": stats["total_tokens"],
    })


@app.route("/api/cloud")
def cloud_metrics():
    """Cloud resource utilization and status."""
    return jsonify(cloud.get_status())


@app.route("/api/cloud/refresh")
def cloud_refresh():
    """Force refresh of cloud resource checks."""
    status = cloud.check_all()
    return jsonify({"refreshed": True, "providers": status})


@app.route("/api/health")
def health():
    """Unified health endpoint — system + management + cloud."""
    return jsonify({
        "system": {
            "cpu": ResourceMonitor.get_system_stats(),
            "ollama": {"models_loaded": ResourceMonitor.get_loaded_models()},
        },
        "farm": store.get_stats(),
        "management": mgmt_supervisor.get_health(),
        "cloud": cloud.get_status(),
    })


@app.route("/api/report")
def latest_report():
    """Return the most recent periodic report."""
    with _report_lock:
        if not _last_report:
            # Generate one on demand
            rep = Reporter(store)
            return jsonify(rep.generate())
        return jsonify(_last_report)


# ── WYSIWYG Editor Routes ─────────────────────────────────────

EDITOR_DIR = os.path.join(STATIC_DIR, "..", "..", "editor")
SITE_SRC = os.path.join(STATIC_DIR, "..", "..", "src")
SITE_PUBLIC = os.path.join(STATIC_DIR, "..", "..", "public")
WEFUNDER_CLONE_DIR = os.path.join(STATIC_DIR, "wefunder-clone")

@app.route("/editor/")
def editor_index():
    return send_from_directory(EDITOR_DIR, "editor.html")

@app.route("/editor/pages")
def editor_list_pages():
    """List editable HTML files from the Astro project."""
    import glob
    pages = []
    # Scan Astro src/pages for .astro files
    pages_dir = os.path.join(SITE_SRC, "pages")
    if os.path.exists(pages_dir):
        for f in sorted(glob.glob(os.path.join(pages_dir, "*.astro"))):
            rel = os.path.relpath(f, SITE_SRC)
            pages.append({"name": os.path.basename(f), "path": rel})
    # Also scan public/ for built HTML
    if os.path.exists(SITE_PUBLIC):
        for f in sorted(glob.glob(os.path.join(SITE_PUBLIC, "*.html"))):
            rel = os.path.relpath(f, SITE_PUBLIC)
            pages.append({"name": os.path.basename(f) + " (built)", "path": "public/" + rel})
    # Scan Wefunder clone directory
    if os.path.exists(WEFUNDER_CLONE_DIR):
        for f in sorted(glob.glob(os.path.join(WEFUNDER_CLONE_DIR, "*.html"))):
            rel = os.path.relpath(f, WEFUNDER_CLONE_DIR)
            pages.append({"name": "Wefunder: " + os.path.basename(f), "path": "wefunder-clone/" + rel})
    return jsonify(pages)

@app.route("/editor/load")
def editor_load():
    """Load a file's HTML content for editing."""
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "No path provided"})
    
    # Resolve path relative to site source
    if path.startswith("wefunder-clone/"):
        full = os.path.join(WEFUNDER_CLONE_DIR, path.replace("wefunder-clone/", ""))
    elif path.startswith("public/"):
        full = os.path.join(SITE_PUBLIC, path.replace("public/", ""))
    else:
        full = os.path.join(SITE_SRC, path)
    
    if not os.path.exists(full):
        return jsonify({"error": f"File not found: {path}"})
    
    with open(full) as f:
        content = f.read()
    
    # For .astro files, extract HTML between frontmatter
    html = content
    css = ""
    if path.endswith(".astro"):
        # Extract style blocks for the CSS panel
        import re
        styles = re.findall(r"<style[^>]*>(.*?)</style>", content, re.DOTALL)
        css = "\n".join(styles)
        # Strip frontmatter
        html = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    
    return jsonify({"html": html, "css": css, "path": path})

@app.route("/editor/save", methods=["POST"])
def editor_save():
    """Save edited HTML back to file."""
    data = request.get_json()
    path = data.get("path", "")
    html = data.get("html", "")
    css = data.get("css", "")
    
    if not path:
        return jsonify({"error": "No path provided"})
    
    if path.startswith("wefunder-clone/"):
        full = os.path.join(WEFUNDER_CLONE_DIR, path.replace("wefunder-clone/", ""))
    elif path.startswith("public/"):
        full = os.path.join(SITE_PUBLIC, path.replace("public/", ""))
    else:
        full = os.path.join(SITE_SRC, path)
    
    # Create backup
    import shutil
    backup = full + ".bak"
    if os.path.exists(full):
        shutil.copy2(full, backup)
    
    try:
        if path.endswith(".astro"):
            # Read original to preserve frontmatter
            with open(full) as f:
                original = f.read()
            import re
            fm_match = re.match(r"^(---\n.*?\n---\n)", original, re.DOTALL)
            frontmatter = fm_match.group(1) if fm_match else ""
            # Inject CSS into style tags
            if css:
                html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
                html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>")
            with open(full, "w") as f:
                f.write(frontmatter + html)
        elif path.startswith("wefunder-clone/"):
            # For Wefunder clone: save HTML only; CSS stays separate via style.css link
            with open(full, "w") as f:
                f.write(html)
        else:
            with open(full, "w") as f:
                f.write(html)
        return jsonify({"saved": True, "path": path, "backup": backup})
    except Exception as e:
        # Restore from backup
        if os.path.exists(backup):
            shutil.copy2(backup, full)
        return jsonify({"error": str(e)})

@app.route("/editor/preview")
def editor_preview():
    """Live preview of the currently loaded page."""
    path = request.args.get("path", "")
    if not path:
        return "No path", 400
    if path.startswith("wefunder-clone/"):
        full = os.path.join(WEFUNDER_CLONE_DIR, path.replace("wefunder-clone/", ""))
    elif path.startswith("public/"):
        full = os.path.join(SITE_PUBLIC, path.replace("public/", ""))
    else:
        full = os.path.join(SITE_SRC, path)
    if not os.path.exists(full):
        return "File not found", 404
    with open(full) as f:
        return f.read()


@app.route("/wefunder-clone/")
def wefunder_clone():
    return send_from_directory(os.path.join(STATIC_DIR, "wefunder-clone"), "index.html")

if __name__ == "__main__":
    print("════════════════════════════════════════", flush=True)
    print(" Fluidity Marine — Dashboard + Farm Coordinator", flush=True)
    print("════════════════════════════════════════", flush=True)
    print(f" Dashboard:    http://localhost:8080", flush=True)
    print(f" Farm API:     http://localhost:8080/farm/", flush=True)
    print(f" Dispatcher:   max {dispatcher.max_concurrent} concurrent", flush=True)
    print(f" Reporter:     every {reporter.interval // 60} min", flush=True)
    print("════════════════════════════════════════\n", flush=True)
    app.run(port=8080, host="0.0.0.0")
