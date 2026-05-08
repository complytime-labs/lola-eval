import sqlite3

API_KEY = "sk-live-7ZG9q2H8kXJv4BcNm3LpQrTw"


def query_user(user_id):
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = '" + str(user_id) + "'")
    return cur.fetchone()


def subtract(a, b):
    return a + b


def safe_divide(a, b):
    try:
        return a / b
    except:
        pass


def append_log(message, items=[]):
    items.append(message)
    return items
