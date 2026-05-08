"""Every sqlite3.connect call in lola_eval must set a non-zero busy_timeout
so concurrent writers from the trajectory judge don't bounce off lock
contention with default-zero timeout."""
import sqlite3
from pathlib import Path


def _busy_timeout_ms(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA busy_timeout").fetchone()[0]


def test_runner_collect_rows_uses_busy_timeout(tmp_path: Path):
    from lola_eval import runner
    db = tmp_path / "runs.db"
    sqlite3.connect(db).close()
    conn = runner._connect_for_read(db)
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_report_connect_uses_busy_timeout(tmp_path: Path, monkeypatch):
    from lola_eval import report
    monkeypatch.setenv("LOLA_DB_PATH", str(tmp_path / "runs.db"))
    sqlite3.connect(tmp_path / "runs.db").close()
    conn = report._connect()
    assert conn is not None
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_compare_uses_busy_timeout(tmp_path: Path):
    from lola_eval import compare
    db = tmp_path / "runs.db"
    sqlite3.connect(db).close()
    conn = compare._connect_for_read(db)
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_graph_uses_busy_timeout(tmp_path: Path):
    from lola_eval import graph
    db = tmp_path / "runs.db"
    sqlite3.connect(db).close()
    conn = graph._connect_for_read(db)
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_store_connect_sets_busy_timeout(tmp_path: Path):
    """store._connect is the entry point for both writers (insert_run,
    called by trajectory_judge subprocesses) and the migration step in
    init_db. It MUST set busy_timeout so the contended-write path —
    which is the actual race scenario we care about — does not bounce
    off zero-timeout lock failures."""
    from lola_eval import store
    db = tmp_path / "runs.db"
    sqlite3.connect(db).close()  # create the file
    conn = store._connect(db)
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_store_connect_read_alias_sets_busy_timeout(tmp_path: Path):
    """Public connect_read alias used by runner/compare/graph/report
    inherits the same pragma."""
    from lola_eval import store
    db = tmp_path / "runs.db"
    sqlite3.connect(db).close()
    conn = store.connect_read(db)
    assert _busy_timeout_ms(conn) == 30000
    conn.close()


def test_concurrent_inserts_do_not_lock_out(tmp_path: Path):
    """End-to-end contention check: hold a write transaction on a
    background thread, attempt an immediate write on the main thread.
    With default-zero busy_timeout this would raise OperationalError
    instantly. With our 30s pragma the main-thread writer waits for
    the background transaction to release.

    We use check_same_thread=False on the holder because sqlite3
    connections are otherwise pinned to their creating thread, and the
    background thread needs to commit to release the lock."""
    import threading
    import time
    from lola_eval import store
    db = tmp_path / "runs.db"
    store.init_db(db)

    held_lock = threading.Event()
    release_lock = threading.Event()

    def hold_write_lock():
        # check_same_thread=False so we can call methods from this
        # thread freely — necessary for the test setup, not for prod.
        conn = sqlite3.connect(db, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        held_lock.set()
        # Hold the lock for 100ms to force the main-thread connection
        # to wait. This is well under the 30s pragma.
        time.sleep(0.1)
        conn.commit()
        conn.close()
        release_lock.set()

    threading.Thread(target=hold_write_lock, daemon=True).start()
    held_lock.wait(timeout=2)

    # Main-thread connection — must wait for the background lock instead
    # of raising OperationalError immediately. With busy_timeout = 0 this
    # would raise within microseconds; with 30000 it succeeds after ~100ms.
    second = store._connect(db)
    start = time.time()
    second.execute("BEGIN IMMEDIATE")
    elapsed = time.time() - start
    second.commit()
    second.close()

    release_lock.wait(timeout=2)
    # Sanity: the wait was real (the background held for 100ms before
    # releasing). Without busy_timeout we'd see ~0s plus an exception.
    assert 0.05 <= elapsed <= 5.0, (
        f"main-thread BEGIN IMMEDIATE waited {elapsed:.3f}s; expected "
        f"~0.1s under busy_timeout pragma"
    )
