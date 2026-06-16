#!/usr/bin/env python3
"""Stress test generator — submits mixed tasks to the farm coordinator for ~1 hour."""
import requests
import time
import random
import sys

API = "http://localhost:8080/farm/tasks"

# ── Task templates ──────────────────────────────────────────────────
FAST_TASKS = [  # llama3.2:3b — ~2-5s each
    ("Write a haiku about {}", "llama3.2:3b"),
    ("Classify this as positive/negative/neutral: '{}'", "llama3.2:3b"),
    ("Format this as JSON: {}", "llama3.2:3b"),
    ("Generate 3 tags for: {}", "llama3.2:3b"),
    ("Rewrite this in pirate voice: {}", "llama3.2:3b"),
    ("What emotion does this convey: '{}'", "llama3.2:3b"),
]

MEDIUM_TASKS = [  # qwen2.5:7b — ~10-30s each
    ("Explain {} in two sentences.", "qwen2.5:7b"),
    ("Summarize this: {}", "qwen2.5:7b"),
    ("Write a 3-sentence pitch for: {}", "qwen2.5:7b"),
    ("What are the pros and cons of {}?", "qwen2.5:7b"),
    ("Describe how {} works to a 10-year-old.", "qwen2.5:7b"),
]

CODING_TASKS = [  # qwen2.5-coder:7b — ~15-40s each
    ("Write a Python function that {}", "qwen2.5-coder:7b"),
    ("Write a CSS snippet for {}", "qwen2.5-coder:7b"),
    ("Write a SQL query to {}", "qwen2.5-coder:7b"),
    ("Write a bash one-liner to {}", "qwen2.5-coder:7b"),
]

WEFUNDER_TASKS = [  # campaign-related — mix of models
    ("Write a compelling 2-sentence investor tagline for a marine propulsion startup replacing polluting outboard motors with electric impeller technology.", "qwen2.5:7b"),
    ("Draft a Wefunder campaign update announcing our TVC (Thrust Vector Control) technology milestone.", "qwen2.5:7b"),
    ("Write 3 FAQ answers for potential investors: what is TVC, why electric marine, what's the market size.", "qwen2.5:7b"),
    ("Generate 5 bullet points for a Wefunder 'Why Invest' section for a sustainable marine tech startup.", "qwen2.5:7b"),
    ("Write a 1-paragraph founder story for Aaron Evans, CEO of Fluidity Marine, focused on the mission to clean up our seas.", "qwen2.5:7b"),
    ("Draft social media copy (Twitter/X style) announcing our seed round on Wefunder. 280 chars max.", "llama3.2:3b"),
    ("List 5 compelling statistics about marine pollution that would resonate with impact investors.", "qwen2.5:7b"),
    ("Write investor-facing copy explaining how TVC eliminates rudders and why that matters for reliability.", "qwen2.5:14b"),
]

# ── Topic fillers ───────────────────────────────────────────────────
TOPICS = [
    "solar panels", "electric vehicles", "ocean cleanup", "coral reefs",
    "wind turbines", "marine biology", "sustainable fishing", "tidal energy",
    "autonomous boats", "hydrogen fuel cells", "wave power", "seagrass meadows",
    "carbon capture", "desalination", "aquaculture", "marine protected areas",
    "electric ferries", "underwater drones", "smart buoys", "ocean thermal energy",
    "mangrove restoration", "plastic pollution", "ballast water treatment",
    "ship electrification", "marine battery tech", "hydrofoil design",
    "propeller efficiency", "rudder dynamics", "water jet propulsion",
    "naval architecture", "coastal erosion", "sea level rise",
]


def submit(prompt: str, model: str) -> int:
    try:
        r = requests.post(API, json={"prompt": prompt, "model": model}, timeout=5)
        data = r.json()
        return data.get("task_id", 0)
    except Exception as e:
        print(f"  ✗ Submit error: {e}", flush=True)
        return 0


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    print(f"Stress test: {total} tasks, mixed models, ~1hr target", flush=True)
    print(f"API: {API}\n", flush=True)

    submitted = 0
    wefunder_count = 0
    fast_count = 0
    medium_count = 0
    code_count = 0

    start = time.monotonic()

    for i in range(total):
        # Mix: 40% fast (3b), 30% medium (7b), 15% code (coder:7b), 15% wefunder (mixed)
        roll = random.random()

        if roll < 0.15:
            # Wefunder task
            tmpl, model = random.choice(WEFUNDER_TASKS)
            prompt = tmpl
            wefunder_count += 1
        elif roll < 0.30:
            # Code task
            tmpl, model = random.choice(CODING_TASKS)
            topic = random.choice(TOPICS)
            prompt = tmpl.format(topic)
            code_count += 1
        elif roll < 0.60:
            # Medium task
            tmpl, model = random.choice(MEDIUM_TASKS)
            topic = random.choice(TOPICS)
            prompt = tmpl.format(topic)
            medium_count += 1
        else:
            # Fast task
            tmpl, model = random.choice(FAST_TASKS)
            topic = random.choice(TOPICS)
            prompt = tmpl.format(topic)
            fast_count += 1

        tid = submit(prompt, model)
        submitted += 1

        if submitted % 20 == 0:
            elapsed = time.monotonic() - start
            print(f"  [{submitted}/{total}] submitted ({elapsed:.0f}s) — "
                  f"fast:{fast_count} med:{medium_count} code:{code_count} "
                  f"wefunder:{wefunder_count}", flush=True)

        # Small delay between submissions so the queue doesn't flood instantly
        time.sleep(0.3)

    elapsed = time.monotonic() - start
    print(f"\n✓ Done. {submitted} tasks submitted in {elapsed:.0f}s", flush=True)
    print(f"  Fast (3b):     {fast_count}", flush=True)
    print(f"  Medium (7b):   {medium_count}", flush=True)
    print(f"  Code (coder):  {code_count}", flush=True)
    print(f"  Wefunder:      {wefunder_count}", flush=True)
    print(f"\nMonitor: curl http://localhost:8080/farm/queue | python3 -m json.tool", flush=True)


if __name__ == "__main__":
    main()
