# AGENTS.md

## SQLite connection hygiene

`with sqlite3.connect(db) as conn:` only commits/rollbacks — it does
**not** close the connection. Every unclosed connection leaks a file
descriptor. In tight loops (e.g. `insert_run` called 80× during
seeding) this exhausts the FD limit and crashes pytest cleanup.

Pattern to follow:

```python
conn = _connect(db)
try:
    with conn:
        conn.execute(...)
finally:
    conn.close()
```

For read-only queries where transaction semantics aren't needed:

```python
conn = _connect(db)
try:
    rows = list(conn.execute(...))
finally:
    conn.close()
```

Never use inline `sqlite3.connect(db).execute(...)` — assign to a
variable and close it.

## Mode 1 provisioning policy

lola-eval provisions a module by installing it with `lola install` and then
**restoring the target's instruction file** (`CLAUDE.md`/`AGENTS.md`) to its
pre-install state. We never leave a `<!-- lola:module:* -->` block in any
directory the agent reads — the eval measures *clean* behavior, matching where
lola is heading (no context-file injection).

Isolation is mandatory and non-negotiable:
- Each cell has a unique workdir (diffed) **and** a unique `$HOME` (registry,
  user-scope installs). The shared `starter/` and the host's real
  `$HOME`/`~/.lola`/`~/.claude` are never mutated.
- A workdir is a standalone `git init` repo, **never** a `git worktree` of the
  source — a worktree would share the source object store and registry.
- The `none` baseline is byte-identical to the pristine starter.
