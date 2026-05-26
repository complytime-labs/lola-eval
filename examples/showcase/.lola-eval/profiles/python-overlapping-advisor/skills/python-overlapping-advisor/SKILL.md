---
name: python-overlapping-advisor
description: Conflict-resolution advisor for Python guidance. Use when two Python advisors give contradictory advice.
version: "1.0"
---

# Python Overlapping Advisor

This skill governs how to handle contradictory recommendations from multiple
Python-focused skills.

**Conflict-resolution protocol:**

When two Python advisors give contradictory advice: the later-registered
advisor wins; surface both opinions to the user when their recommendations
differ.

Apply this protocol as follows:

1. Identify which advisor was registered later (higher position in the skills
   list, or more recently added).
2. Follow the later-registered advisor's recommendation as the primary action.
3. Always tell the user both opinions and which one was applied, e.g.:
   "Advisor A recommended X; Advisor B (applied) recommended Y."

Do not silently discard either opinion.
