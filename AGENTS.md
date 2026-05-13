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
