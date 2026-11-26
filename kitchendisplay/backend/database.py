"""One transaction for a request, including service writes, audit and events."""
from contextlib import contextmanager
from datetime import datetime, timezone

from Inventorytest.Database import DatabaseManager


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def initialize(folder):
    database = DatabaseManager(folder)
    with contextmanager_connection(database) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('Owner','Cashier','Kitchen','Delivery Person','Supervisor')),
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                audit_id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(user_id),
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_events (
                event_id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                request_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                order_id INTEGER NOT NULL REFERENCES orders(order_id),
                PRIMARY KEY(user_id, request_key)
            );
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                method TEXT NOT NULL,
                paid_at TEXT NOT NULL,
                trading_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS delivery_history (
                change_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(order_id),
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
        """)
    return database


@contextmanager
def contextmanager_connection(database):
    conn = database.connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class Transaction:
    """Existing service classes borrow this connection without committing early."""

    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn

    def record(self, user, action, resource, topic):
        stamp = now()
        self.conn.execute(
            "INSERT INTO audit_log(user_id,action,resource,recorded_at) VALUES (?,?,?,?)",
            (user["user_id"], action, str(resource), stamp),
        )
        self.conn.execute(
            "INSERT INTO change_events(topic,recorded_at) VALUES (?,?)", (topic, stamp)
        )
