---
name: multi-language-feature-builder
description: Build multi-file features that span TypeScript and Python. Use when a feature requires changes in both languages.
version: "1.0"
---

# Multi-Language Feature Builder

When asked to implement a feature that touches both TypeScript and Python:

1. Identify the contract boundary (e.g., REST endpoint, shared schema, CLI
   interface) and agree on it before writing code in either language.
2. Implement the Python side first; write the TypeScript side to match the
   agreed contract.
3. Keep each language's code idiomatic — do not port Python patterns into
   TypeScript or vice versa.
4. Update both language's tests together; a feature is not done until tests
   pass in both.

If the scope is unclear, ask for the entry point and expected output before
starting.
