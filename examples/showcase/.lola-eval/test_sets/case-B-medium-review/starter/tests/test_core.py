from userdb import UserDb


def test_add_and_lookup():
    db = UserDb()
    db.add_user("alice", "alice@example.com")
    rows = db.lookup("alice")
    assert len(rows) == 1


def test_update_email():
    db = UserDb()
    db.add_user("bob", "bob@example.com")
    rows = db.lookup("bob")
    user_id = rows[0][0]
    assert db.update_email(user_id, "bob+new@example.com") is True
