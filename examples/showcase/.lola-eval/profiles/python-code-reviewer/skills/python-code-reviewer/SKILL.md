---
name: python-code-reviewer
description: Review Python code for SQL injection, input validation gaps, and race conditions. Use when asked to review Python code.
version: "1.0"
---

# Python Code Reviewer

When asked to review Python code, check for:

1. **SQL injection** — any string interpolation or concatenation into a query;
   require parameterised queries or an ORM.
2. **Input validation** — untrusted data that reaches file I/O, subprocess
   calls, or deserialization without validation or sanitization.
3. **Race conditions** — shared mutable state accessed from threads or async
   tasks without appropriate locks or atomic operations.

Report each finding with file, line, category, and a one-sentence fix
recommendation. Do not rewrite the code unless explicitly asked.
