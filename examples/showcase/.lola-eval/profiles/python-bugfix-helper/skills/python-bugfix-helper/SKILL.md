---
name: python-bugfix-helper
description: Guide Python off-by-one and similar logic bug fixes. Use when asked to find or fix a Python bug.
version: "1.0"
---

# Python Bugfix Helper

When asked to find or fix a bug in Python code:

1. Read the failing test or error message first.
2. Identify the exact line — focus on off-by-one errors, index bounds, and loop
   boundary conditions.
3. Propose the minimal change that fixes the bug without altering surrounding
   logic.
4. Confirm the fix by tracing through the corrected code mentally before
   applying it.

Do not refactor, rename, or reformat code outside the buggy section.
