#!/usr/bin/env python3
"""Migrate imports after removing duplicate root modules."""

import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Patterns to fix
REPLACEMENTS = [
    (re.compile(r"^from\s+config\s+import", re.M), "from core.config import"),
    (re.compile(r"^import\s+config\b", re.M), "import core.config as config"),
]

fixed_count = 0
for root, dirs, files in os.walk(PROJECT_ROOT):
    if ".git" in root or "scripts" in root.split(os.sep):
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except Exception as e:
            print(f"Skip {path}: {e}")
            continue

        new_content = content
        for pattern, replacement in REPLACEMENTS:
            new_content = pattern.sub(replacement, new_content)

        if new_content != content:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            fixed_count += 1
            print(f"Fixed: {os.path.relpath(path, PROJECT_ROOT)}")

print(f"\nTotal files fixed: {fixed_count}")
