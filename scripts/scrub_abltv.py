#!/usr/bin/env python3
"""
ABLTV → TVC (Thrust Vector Control) scrub script.
Replaces all ABLTV references in the website source and related files.
Run from project root: python3 scripts/scrub_abltv.py
"""
import os, re, sys

PROJECT_ROOT = os.path.expanduser("~/src/fluidity-marine-modern")

# Directories to scrub
SCRUB_DIRS = [
    "src/pages",
    "src/layouts",
    "wefunder-clone",
    "docs",
    "tools",
    "public/tools",
    "dashboard",
]

# Directories to skip
SKIP_DIRS = ["node_modules", ".astro", "dist", ".git", "repos"]

# File extensions to scrub
SCRUB_EXTENSIONS = [".astro", ".html", ".md", ".py", ".js", ".ts", ".css", ".json", ".yaml", ".yml"]

# Replacement rules — ORDER MATTERS (most specific first)
REPLACEMENTS = [
    # Full expanded form with parens
    ("ABLTV (Active Boundary Layer Thrust Vectoring)", "TVC (Thrust Vector Control)"),
    # Expanded form without parens
    ("Active Boundary Layer Thrust Vectoring", "Thrust Vector Control"),
    # Wrong variant from old press release
    ("Active Boundary Layer Traction Vectoring", "Thrust Vector Control"),
    ("Air Boundary Layer Traction Vectoring", "Thrust Vector Control"),
    # ABLTV acronym — standalone word (not inside another word)
    # We use word boundary regex for this
]

# Files/dirs that contain historical audit references we should also scrub
# (These describe the old name in past tense — still need updating)
HISTORICAL_DESCRIPTIONS = [
    ("ABLTV — an array of vectored water jets", "TVC — an array of vectored water jets"),
    ("ABLTV — 7-jet array", "TVC — 7-jet array"),
    ("ABLTV — Active Boundary Layer", "TVC — Thrust Vector Control"),
    ("ABLTV platform", "TVC platform"),
    ("ABLTV technology", "TVC technology"),
    ("ABLTV system", "TVC system"),
    ("ABLTV propulsion", "TVC propulsion"),
    ("ABLTV jet array", "TVC jet array"),
    ("ABLTV control", "TVC control"),
    ("ABLTV Proof of Concept", "TVC Proof of Concept"),
    ("ABLTV engineering", "TVC engineering"),
    ("ABLTV physics", "TVC physics"),
    ("ABLTV simulation", "TVC simulation"),
    ("ABLTV deep dive", "TVC deep dive"),
    ("ABLTV diagram", "TVC diagram"),
    ("ABLTV SVG", "TVC SVG"),
    ("ABLTV = ", "TVC = "),
    ("inventor of ABLTV", "inventor of TVC"),
    ("invented ABLTV", "invented TVC"),
    ("bring ABLTV", "bring TVC"),
    ("bring TVC to market", "bring TVC to market"),
    ("ABLTV-equipped", "TVC-equipped"),
    ("ABLTV from prototype", "TVC from prototype"),
    ("ABLTV becomes a production", "TVC becomes a production"),
    ("ABLTV is the only", "TVC is the only"),
    ("ABLTV is the most", "TVC is the most"),
    ("ABLTV is more than", "TVC is more than"),
    ("ABLTV — that will power", "TVC — that will power"),
    ("ABLTV represents a generational", "TVC represents a generational"),
    ("ABLTV is raising", "Fluidity Marine is raising"),
    ("ABLTV — 7-node transom cutaway", "TVC — 7-node transom cutaway"),
    ("ABLTV propulsion system cross-section", "TVC propulsion system cross-section"),
    ("ABLTV replaces every", "TVC replaces every"),
    ("ABLTV — how rudderless", "TVC — how rudderless"),
    ("ABLTV deep dive — how", "TVC deep dive — how"),
    ("ABLTV doesn't fight", "TVC doesn't fight"),
    ("ABLTV can alter", "TVC can alter"),
    ("ABLTV redirects energy", "TVC redirects energy"),
    ("ABLTV — an opportunity", "TVC — an opportunity"),
    ("ABLTV is in a category", "TVC is in a category"),
    ("ABLTV jet array, control", "TVC jet array, control"),
    ("ABLTV is the only rudderless", "TVC is the only rudderless"),
    ("ABLTV is the most advanced", "TVC is the most advanced"),
    ("ABLTV is the common", "TVC is the common"),
    ("ABLTV Proof of Concept", "TVC Proof of Concept"),
    ("ABLTV through fluid", "TVC through fluid"),
    ("ABLTV engineering specifications", "TVC engineering specifications"),
    ("ABLTV system on water", "TVC system on water"),
    ("ABLTV becomes a production", "TVC becomes a production"),
    ("ABLTV handles failure", "TVC handles failure"),
    ("ABLTV theory & testing", "TVC theory & testing"),
    ("ABLTV engineering deep-dive", "TVC engineering deep-dive"),
    ("ABLTV as \"Air Boundary Layer", "TVC as \"Thrust Vector Control"),
    ("ABLTV as \"Active Boundary Layer", "TVC as \"Thrust Vector Control"),
    ("ABLTV = Active Boundary Layer Thrust Vectoring", "TVC = Thrust Vector Control"),
    ("ABLTV = Thrust Vector Control", "TVC = Thrust Vector Control"),
    # Title/heading specific
    ("ABLTV Technology |", "TVC Technology |"),
    ("ABLTV Technology", "TVC Technology"),
    # Page title
    ("Active Boundary Layer Thrust Vectoring", "Thrust Vector Control"),
    # Lowercase variants
    ("abltv", "tvc"),
    # Hashtag
    ("#ABLTV", "#TVC"),
]

def scrub_file(filepath):
    """Scrub a single file. Returns (changed, count)."""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    original = content
    count = 0
    
    # Apply direct string replacements
    for old, new in HISTORICAL_DESCRIPTIONS + REPLACEMENTS:
        if old in content:
            occurrences = content.count(old)
            content = content.replace(old, new)
            count += occurrences
    
    # Regex replacement for standalone "ABLTV" (word boundary)
    # This catches any we missed
    matches = re.findall(r'\bABLTV\b', content)
    if matches:
        content = re.sub(r'\bABLTV\b', 'TVC', content)
        count += len(matches)
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, count
    return False, 0

def main():
    total_files = 0
    total_replacements = 0
    files_changed = []
    
    for scrub_dir in SCRUB_DIRS:
        full_dir = os.path.join(PROJECT_ROOT, scrub_dir)
        if not os.path.exists(full_dir):
            print(f"  SKIP (not found): {scrub_dir}")
            continue
        
        for root, dirs, files in os.walk(full_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if not any(fname.endswith(ext) for ext in SCRUB_EXTENSIONS):
                    continue
                fpath = os.path.join(root, fname)
                changed, count = scrub_file(fpath)
                if changed:
                    total_files += 1
                    total_replacements += count
                    rel_path = fpath.replace(PROJECT_ROOT + "/", "")
                    files_changed.append((rel_path, count))
    
    print(f"\n{'='*60}")
    print(f"ABLTV → TVC SCRUB COMPLETE")
    print(f"{'='*60}")
    print(f"Files modified: {total_files}")
    print(f"Total replacements: {total_replacements}")
    print(f"\nBreakdown:")
    for fpath, count in sorted(files_changed, key=lambda x: -x[1]):
        print(f"  {count:3d}  {fpath}")
    
    # Verify
    print(f"\n{'='*60}")
    print("VERIFICATION — scanning for remaining ABLTV references...")
    remaining = 0
    for scrub_dir in SCRUB_DIRS:
        full_dir = os.path.join(PROJECT_ROOT, scrub_dir)
        if not os.path.exists(full_dir):
            continue
        for root, dirs, files in os.walk(full_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if not any(fname.endswith(ext) for ext in SCRUB_EXTENSIONS):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                matches = re.findall(r'\bABLTV\b', content)
                if matches:
                    remaining += len(matches)
                    rel_path = fpath.replace(PROJECT_ROOT + "/", "")
                    print(f"  ⚠️  {len(matches)} remaining in {rel_path}")
    
    if remaining == 0:
        print("  ✅ No ABLTV references remaining!")
    else:
        print(f"\n  ⚠️  {remaining} references still remain — manual review needed")

if __name__ == '__main__':
    main()
