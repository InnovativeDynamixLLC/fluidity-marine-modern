#!/usr/bin/env python3
"""
8-Hour Task Queue Generator — Sustained 80% CPU Utilization

Generates a diverse, 8-hour workload for the Farm Coordinator.
Targets 322 tasks/hour × 8 hours ≈ 2,600 tasks, rounded to 3,000.
Mix designed to:
  - Keep 2 concurrent dispatches always running
  - Hit 80% CPU (load avg ~3.2 on 4 threads)
  - Produce useful output (docs, code, content, analysis)
  - Include periodic system health checks
  - Cycle through different models to avoid cache thrashing
"""

import json, time, requests, random, sys
from datetime import datetime

API = "http://localhost:8080/farm/tasks"

# ─── Task Templates ───────────────────────────────────────────────

FAST_TASKS = {  # llama3.2:3b — avg 6.2s, 9.1 t/s
    "haiku": [
        "Write a haiku about {topic}.",
    ],
    "classify": [
        "Classify this as positive/negative/neutral: '{text}'",
    ],
    "rewrite": [
        "Rewrite this in {style} voice: {text}",
    ],
    "format": [
        "Format this as JSON: {topic}",
    ],
    "tags": [
        "Generate 5 relevant tags for: {topic}",
    ],
}

MEDIUM_TASKS = {  # qwen2.5:7b — avg 37.8s, 3.4 t/s
    "explain": [
        "Explain {topic} in three sentences.",
        "Describe how {topic} works to a 10-year-old.",
    ],
    "pitch": [
        "Write a 3-sentence investor pitch for: {topic}",
    ],
    "pros_cons": [
        "List 3 pros and 3 cons of: {topic}",
    ],
    "summary": [
        "Summarize the key technical advantages of {topic} in 5 bullet points.",
    ],
    "qa": [
        "Answer this question in 2-3 sentences: {question}",
    ],
}

CODE_TASKS = {  # qwen2.5-coder:7b — avg 31.4s, 3.8 t/s
    "python_util": [
        "Write a Python function to {task}. Include docstring and type hints.",
    ],
    "bash_oneliner": [
        "Write a bash one-liner to {task}",
    ],
    "sql_query": [
        "Write a SQL query to {task}. Include comments.",
    ],
    "css_component": [
        "Write a CSS-only {component} component. Dark theme, responsive.",
    ],
    "regex": [
        "Write a regex pattern to match {pattern}. Explain each part.",
    ],
}

HEAVY_TASKS = {  # qwen2.5:14b — not in current mix, adding for RAM pressure
    "deep_analysis": [
        "Analyze the trade-offs of {topic}. Consider technical, economic, and environmental factors.",
    ],
    "compare": [
        "Compare {a} vs {b} for marine propulsion. Include efficiency, cost, and maintenance.",
    ],
    "synthesize": [
        "Synthesize these three concepts into a unified framework: {a}, {b}, {c}",
    ],
}

META_TASKS = {  # System self-reflection — qwen2.5:7b
    "health_report": [
        "Given the last 20 completed tasks, identify any patterns in failures or slowdowns.",
    ],
    "model_routing": [
        "Based on task type patterns, recommend which model should handle which task categories.",
    ],
    "throughput_analysis": [
        "Analyze task throughput: what's causing bottlenecks and how to increase utilization.",
    ],
}

# ─── Topic Pools ──────────────────────────────────────────────────

TOPICS = [
    # Marine / TVC
    "active boundary layer thrust vectoring", "transom jet arrays",
    "differential drag steering", "marine electrification",
    "propellerless propulsion", "underwater noise reduction",
    "marine ecosystem protection", "zero-emission vessels",
    "autonomous marine navigation", "hydrodynamic efficiency",
    "coastal resilience", "ocean thermal energy",
    "tidal energy harvesting", "wave energy conversion",
    "marine battery technology", "electric ferry design",
    # Technology
    "edge computing", "distributed systems", "vector databases",
    "real-time data processing", "API gateway design",
    "event-driven architecture", "container orchestration",
    "continuous deployment", "infrastructure as code",
    "observability pipelines", "chaos engineering",
    "semantic search", "knowledge graphs",
    # Science
    "coral reef restoration", "carbon sequestration",
    "ocean acidification", "marine biodiversity",
    "sustainable aquaculture", "desalination technology",
    # Business
    "seed stage fundraising", "equity crowdfunding",
    "revenue models for hardware startups", "IP strategy",
    "supply chain resilience", "manufacturing partnerships",
]

STYLES = ["pirate", "Shakespearean", "corporate", "poetic", "technical", "enthusiastic"]
TEXTS = [
    "ocean thermal energy shows promise for baseload power",
    "electric propulsion is transforming the marine industry",
    "the future of maritime is autonomous and electric",
    "investors are increasingly focused on blue economy startups",
]

QUESTIONS = [
    "How does differential drag steering work?",
    "Why are transom jets more efficient than rudders?",
    "What makes TVC technology patentable?",
    "How big is the marine electrification market?",
    "What are the main challenges in marine battery development?",
]

CODE_TASKS_POOL = [
    "parse a CSV file and compute column statistics",
    "monitor disk usage and alert when above 90%",
    "fetch JSON from an API and cache results for 5 minutes",
    "generate a random secure password",
    "validate an email address format",
    "convert timestamps between timezones",
    "find duplicate files in a directory by checksum",
    "rate-limit function calls to 10 per second",
    "parse nginx access logs and count status codes",
    "create a simple LRU cache with TTL support",
    "extract all URLs from a text file",
    "compute the levenshtein distance between two strings",
]

CSS_COMPONENTS = [
    "metric card", "status indicator", "progress bar", "data table",
    "notification toast", "modal overlay", "tab switcher", "tooltip",
]

REGEX_PATTERNS = [
    "valid IPv4 addresses", "ISO 8601 dates",
    "semantic version numbers (semver)",
    "hex color codes (#RGB or #RRGGBB)",
    "Markdown-style links [text](url)",
]

# ─── Build Task List ──────────────────────────────────────────────

def build_task_queue(count: int) -> list:
    """Generate a diverse task queue."""
    tasks = []
    
    for i in range(count):
        # Rotate through categories to maintain diversity
        phase = i % 100
        
        if phase < 30:  # 30% fast tasks
            category = random.choice(list(FAST_TASKS.keys()))
            template = random.choice(FAST_TASKS[category])
            topic = random.choice(TOPICS)
            style = random.choice(STYLES)
            text = random.choice(TEXTS)
            prompt = template.format(topic=topic, style=style, text=text)
            model = "llama3.2:3b"
            task_type = category
            
        elif phase < 60:  # 30% medium tasks
            category = random.choice(list(MEDIUM_TASKS.keys()))
            template = random.choice(MEDIUM_TASKS[category])
            topic = random.choice(TOPICS)
            question = random.choice(QUESTIONS)
            prompt = template.format(topic=topic, question=question)
            model = "qwen2.5:7b"
            task_type = category
            
        elif phase < 80:  # 20% code tasks
            category = random.choice(list(CODE_TASKS.keys()))
            template = random.choice(CODE_TASKS[category])
            if "component" in template:
                arg = random.choice(CSS_COMPONENTS)
            elif "pattern" in template:
                arg = random.choice(REGEX_PATTERNS)
            elif "one-liner" in template or "query" in template:
                arg = random.choice(CODE_TASKS_POOL)
            else:
                arg = random.choice(CODE_TASKS_POOL)
            prompt = template.format(task=arg, component=arg, pattern=arg)
            model = "qwen2.5-coder:7b"
            task_type = category
            
        elif phase < 95:  # 15% heavy analysis
            category = random.choice(list(HEAVY_TASKS.keys()))
            template = random.choice(HEAVY_TASKS[category])
            a = random.choice(TOPICS)
            b = random.choice(TOPICS)
            c = random.choice(TOPICS)
            prompt = template.format(topic=a, a=a, b=b, c=c)
            model = "qwen2.5:14b"
            task_type = category
            
        else:  # 5% meta/system tasks
            category = random.choice(list(META_TASKS.keys()))
            template = random.choice(META_TASKS[category])
            prompt = template
            model = "qwen2.5:7b"
            task_type = "meta_" + category
        
        tasks.append({
            "prompt": prompt,
            "model": model,
            "task_type": task_type,
            "priority": "normal" if phase < 95 else "low",
        })
    
    return tasks


def add_health_checks(tasks: list, interval: int = 50) -> list:
    """Inject periodic system health check tasks."""
    health_tasks = [
        {"prompt": "Report current system status: CPU load, RAM usage, disk space, active processes. Format as JSON.", "model": "qwen2.5-coder:7b", "task_type": "health_check", "priority": "high"},
        {"prompt": "Check if all 5 Ollama models are responding. Report which ones are loaded and their response times.", "model": "llama3.2:3b", "task_type": "health_check", "priority": "high"},
        {"prompt": "List the last 10 completed tasks and identify any error patterns or quality issues.", "model": "qwen2.5:7b", "task_type": "health_check", "priority": "normal"},
    ]
    
    result = []
    for i, task in enumerate(tasks):
        result.append(task)
        if (i + 1) % interval == 0:
            health = health_tasks[i // interval % len(health_tasks)]
            result.append(health.copy())
    
    return result


def submit_batch(tasks: list, batch_size: int = 50, delay: float = 0.05):
    """Submit tasks to the farm coordinator."""
    submitted = 0
    failed = 0
    start = time.time()
    
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        for task in batch:
            try:
                resp = requests.post(API, json=task, timeout=5)
                if resp.status_code in (200, 201):
                    submitted += 1
                else:
                    failed += 1
                    print(f"  FAIL [{resp.status_code}]: {task['prompt'][:60]}...")
            except Exception as e:
                failed += 1
                print(f"  ERROR: {e}")
            time.sleep(delay)
        
        elapsed = time.time() - start
        rate = submitted / elapsed if elapsed > 0 else 0
        print(f"  [{elapsed:.0f}s] Submitted: {submitted}/{len(tasks)}  Failed: {failed}  Rate: {rate:.1f}/s")
    
    return submitted, failed, time.time() - start


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    
    print(f"=== Building {count}-task 8-hour queue ===")
    print(f"Target: 80% CPU utilization (~3.2 load avg on 4 threads)")
    print(f"Models: llama3.2:3b (30%), qwen2.5:7b (30%), qwen2.5-coder:7b (20%), qwen2.5:14b (15%), meta (5%)")
    print()
    
    tasks = build_task_queue(count)
    tasks = add_health_checks(tasks, interval=50)
    
    # Show distribution
    from collections import Counter
    model_dist = Counter(t['model'] for t in tasks)
    type_dist = Counter(t['task_type'] for t in tasks)
    
    print(f"Total tasks: {len(tasks)} (with health checks)")
    print(f"\nModel distribution:")
    for model, c in model_dist.most_common():
        pct = c / len(tasks) * 100
        print(f"  {model:<22} {c:>5} ({pct:.1f}%)")
    
    print(f"\nTask type distribution (top 10):")
    for ttype, c in type_dist.most_common(10):
        pct = c / len(tasks) * 100
        print(f"  {ttype:<22} {c:>4} ({pct:.1f}%)")
    
    # Estimate duration
    avg_times = {"llama3.2:3b": 7, "qwen2.5:7b": 38, "qwen2.5-coder:7b": 32, "qwen2.5:14b": 60}
    total_seconds = sum(avg_times.get(t['model'], 30) for t in tasks)
    wall_hours = total_seconds / 2 / 3600  # 2 concurrent
    print(f"\nEstimated wall time (2 concurrent): {wall_hours:.1f} hours")
    print(f"Estimated CPU load: ~{min(wall_hours/8*100, 100):.0f}% of 8-hour window")
    
    print(f"\n=== Submitting to coordinator ===")
    submitted, failed, elapsed = submit_batch(tasks, batch_size=50)
    
    print(f"\n✓ Submitted {submitted} tasks in {elapsed:.1f}s ({elapsed/submitted:.3f}s per task)")
    if failed:
        print(f"✗ {failed} failures")
