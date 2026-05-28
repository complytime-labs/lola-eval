import sqlite3


class UserDb:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"
        )

    def lookup(self, name: str):
        # ISSUE 1: SQL injection — name is interpolated directly.
        cur = self.conn.execute(f"SELECT * FROM users WHERE name = '{name}'")
        return cur.fetchall()

    def add_user(self, name, email):
        # ISSUE 2: no input validation — name/email types not checked,
        # arbitrary length accepted, no email-shape check.
        self.conn.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)", (name, email)
        )
        self.conn.commit()

    def update_email(self, user_id: int, new_email: str):
        # ISSUE 3: race condition — read-modify-write without transaction.
        row = self.conn.execute(
            "SELECT email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return False
        self.conn.execute(
            "UPDATE users SET email = ? WHERE id = ?", (new_email, user_id)
        )
        self.conn.commit()
        return True
