import hashlib
import hmac
import secrets

from app import database


def digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def authenticate(name, password):
    with database() as db:
        row = db.execute("SELECT * FROM accounts WHERE name=?", (name,)).fetchone()
    if row and hmac.compare_digest(row["digest"], digest(password, row["salt"])):
        return row["role"]
    return None


def setup():
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(name TEXT PRIMARY KEY, role TEXT NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries(
          id TEXT PRIMARY KEY, address TEXT NOT NULL, phone TEXT NOT NULL, total_cents INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'Awaiting Pickup', confirmed_at TEXT NOT NULL, confirmed_by TEXT NOT NULL,
          driver TEXT, picked_at TEXT, delivered_at TEXT, cash_cents INTEGER);
        """)
        for name, role in [("cashier","cashier"), ("driver1","driver"), ("driver2","driver"),
                           ("supervisor","supervisor"), ("owner","owner")]:
            if db.execute("SELECT 1 FROM accounts WHERE name=?", (name,)).fetchone():
                continue
            password, salt = secrets.token_urlsafe(14), secrets.token_bytes(16)
            db.execute("INSERT INTO accounts VALUES(?,?,?,?)", (name, role, salt, digest(password, salt)))
            print(f"{name}   {password}")
