"""
Jamrock Bitez — Owner Dashboard
Read-only overview across cashier, kitchen, delivery, and inventory.

Run:  uvicorn main:app --reload
Open: http://127.0.0.1:8001
"""

import asyncio
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Jamrock Bitez — Owner Dashboard")

# Shared backend (Danyl's main.py) — used when available.
BACKEND = "http://127.0.0.1:8000"

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "owner.db"


# ---------------------------------------------------------------------------
# SQLite — local orders table for this module
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor():
    conn = get_db()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


# Demo menu — popular items for the owner board
POPULAR_ITEMS = [
    {"name": "Jerk Chicken Plate", "desc": "Rice & peas, plantain, slaw", "qty": 28, "pct": 22, "tone": "#9a3412"},
    {"name": "Curry Goat", "desc": "Bone-in, slow-cooked", "qty": 22, "pct": 17, "tone": "#1e5c4a"},
    {"name": "Oxtail Dinner", "desc": "Butter beans, gravy", "qty": 18, "pct": 14, "tone": "#a16207"},
    {"name": "Escovitch Snapper", "desc": "Fried whole, pepper sauce", "qty": 16, "pct": 13, "tone": "#9a3412"},
    {"name": "Festival & Patty", "desc": "Sweet fried dough, beef patty", "qty": 12, "pct": 10, "tone": "#1e5c4a"},
]


def init_db():
    with db_cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_type TEXT NOT NULL CHECK(order_type IN ('in-store','delivery')),
            total REAL NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Completed',
            customer TEXT NOT NULL DEFAULT '')""")
        # older DBs may lack the newer columns
        cols = {r[1] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
        if "status" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'Completed'")
        if "customer" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN customer TEXT NOT NULL DEFAULT ''")

        # orders mirrored from the shared backend (team's main.py on :8000)
        c.execute("""CREATE TABLE IF NOT EXISTS shared_orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_id INTEGER NOT NULL UNIQUE,
            order_type TEXT NOT NULL CHECK(order_type IN ('in-store','delivery')),
            total REAL NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Preparing',
            customer TEXT NOT NULL DEFAULT '',
            items TEXT NOT NULL DEFAULT '[]')""")
        scols = {r[1] for r in c.execute("PRAGMA table_info(shared_orders)").fetchall()}
        if "items" not in scols:
            c.execute("ALTER TABLE shared_orders ADD COLUMN items TEXT NOT NULL DEFAULT '[]'")

        count = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if count == 0:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

            def row(kind, total, when, status, customer):
                return (kind, total, when, status, customer)

            rows = [
                # yesterday — quieter service for the comparison
                row("in-store", 16.00, f"{yesterday} 12:10:00", "Completed", "Sarah J."),
                row("delivery", 24.50, f"{yesterday} 12:40:00", "Completed", "Mike C."),
                row("in-store", 21.25, f"{yesterday} 13:15:00", "Completed", "Emily D."),
                row("delivery", 33.00, f"{yesterday} 14:05:00", "Completed", "James W."),
                row("in-store", 18.75, f"{yesterday} 15:20:00", "Completed", "Rachel K."),
                row("delivery", 29.50, f"{yesterday} 17:30:00", "Completed", "David L."),
                row("in-store", 35.00, f"{yesterday} 18:15:00", "Completed", "Anna P."),
                row("delivery", 41.00, f"{yesterday} 18:55:00", "Completed", "Chris B."),
                row("in-store", 27.25, f"{yesterday} 19:10:00", "Completed", "Leah M."),
                row("delivery", 38.50, f"{yesterday} 19:40:00", "Completed", "Tom R."),
                row("in-store", 22.00, f"{yesterday} 20:05:00", "Completed", "Nina S."),
                row("delivery", 30.75, f"{yesterday} 20:35:00", "Completed", "Omar F."),
                # today
                row("in-store", 18.50, f"{today} 11:42:00", "Completed", "Sarah J."),
                row("in-store", 22.00, f"{today} 12:05:00", "Completed", "Mike C."),
                row("delivery", 31.00, f"{today} 12:18:00", "Completed", "Emily D."),
                row("in-store", 24.50, f"{today} 12:31:00", "Completed", "James W."),
                row("delivery", 27.50, f"{today} 12:44:00", "Completed", "Rachel K."),
                row("in-store", 16.75, f"{today} 13:02:00", "Completed", "David L."),
                row("delivery", 42.25, f"{today} 13:15:00", "Completed", "Anna P."),
                row("in-store", 19.25, f"{today} 13:28:00", "Completed", "Chris B."),
                row("delivery", 35.00, f"{today} 14:10:00", "Out for delivery", "Leah M."),
                row("in-store", 28.75, f"{today} 14:35:00", "Completed", "Tom R."),
                row("in-store", 14.50, f"{today} 15:02:00", "Completed", "Nina S."),
                row("delivery", 48.00, f"{today} 15:20:00", "Completed", "Omar F."),
                row("in-store", 32.00, f"{today} 17:05:00", "Completed", "Sarah J."),
                row("delivery", 39.50, f"{today} 17:22:00", "Preparing", "Mike C."),
                row("in-store", 26.25, f"{today} 17:40:00", "Completed", "Emily D."),
                row("delivery", 51.00, f"{today} 18:05:00", "Out for delivery", "James W."),
                row("in-store", 21.75, f"{today} 18:28:00", "Completed", "Rachel K."),
                row("delivery", 44.25, f"{today} 18:50:00", "Preparing", "David L."),
            ]
            c.executemany(
                "INSERT INTO orders(order_type,total,created_at,status,customer)"
                " VALUES(?,?,?,?,?)",
                rows,
            )


init_db()


# ---------------------------------------------------------------------------
# Shared-backend ingestion — mirror the team's orders into shared_orders
# ---------------------------------------------------------------------------
# Their statuses -> our pills. Their "kind" -> our "order_type".
REMOTE_STATUS = {"new": "Preparing", "cooking": "Preparing",
                 "ready": "Ready", "done": "Completed"}
SYNC_TTL = 2.5
_sync_lock = asyncio.Lock()
_sync = {"t": 0.0, "reachable": False}


async def ensure_shared_synced() -> bool:
    """Fetch the shared backend's orders at most every SYNC_TTL seconds."""
    now = time.monotonic()
    if now - _sync["t"] < SYNC_TTL:
        return _sync["reachable"]
    async with _sync_lock:
        now = time.monotonic()
        if now - _sync["t"] < SYNC_TTL:
            return _sync["reachable"]
        data = await fetch_backend("/api/orders")
        _sync["t"] = time.monotonic()
        if not isinstance(data, list):
            _sync["reachable"] = False
            return False
        _sync["reachable"] = True
        _ingest_shared_orders(data)
        return True


def _ingest_shared_orders(rows: list) -> None:
    """Upsert backend rows; drop ones it no longer has. created_at is their
    NULL, so we stamp first-seen locally (kept stable across syncs)."""
    now = datetime.now().isoformat(timespec="seconds")
    kept = []
    with db_cursor() as c:
        for r in rows:
            rid = r.get("id")
            if rid is None:
                continue
            kind = r.get("kind") or "dine_in"
            order_type = "delivery" if kind == "delivery" else "in-store"
            status = REMOTE_STATUS.get(str(r.get("status") or "new"), "Preparing")
            total = float(r.get("total") or 0)
            customer = (r.get("address") or "") if order_type == "delivery" else "Walk-in"
            raw_items = r.get("items") or "[]"
            if not isinstance(raw_items, str):
                raw_items = json.dumps(raw_items)
            c.execute(
                """INSERT INTO shared_orders(remote_id,order_type,total,created_at,status,customer,items)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(remote_id) DO UPDATE SET
                     order_type=excluded.order_type, total=excluded.total,
                     status=excluded.status, customer=excluded.customer,
                     items=excluded.items,
                     created_at=shared_orders.created_at""",
                (rid, order_type, total, now, status, customer, raw_items),
            )
            kept.append(int(rid))
        if kept:
            marks = ",".join("?" * len(kept))
            c.execute(f"DELETE FROM shared_orders WHERE remote_id NOT IN ({marks})", kept)
        else:
            c.execute("DELETE FROM shared_orders")


def orders_table() -> str:
    """shared_orders while the backend has ever answered; demo orders otherwise."""
    with db_cursor() as c:
        n = c.execute("SELECT COUNT(*) FROM shared_orders").fetchone()[0]
    return "shared_orders" if n else "orders"


def orders_id_col(table: str) -> str:
    return "remote_id AS id" if table == "shared_orders" else "id"


def sync_state() -> str:
    return "live" if _sync["reachable"] else (
        "stale" if orders_table() == "shared_orders" else "demo")


def local_order_stats() -> dict:
    """Aggregates for today only — the owner opens this board for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    t = orders_table()
    with db_cursor() as c:
        row = c.execute(
            f"SELECT COUNT(*) AS orders, COALESCE(SUM(total),0) AS revenue,"
            f" COALESCE(SUM(CASE WHEN order_type='in-store' THEN total END),0) AS in_store,"
            f" COALESCE(SUM(CASE WHEN order_type='delivery' THEN total END),0) AS delivery,"
            f" SUM(CASE WHEN order_type='in-store' THEN 1 ELSE 0 END) AS in_store_n,"
            f" SUM(CASE WHEN order_type='delivery' THEN 1 ELSE 0 END) AS delivery_n"
            f" FROM {t} WHERE date(created_at) = ?",
            (today,),
        ).fetchone()
    return {
        "orders": row["orders"] or 0,
        "revenue": round(row["revenue"] or 0, 2),
        "in_store": round(row["in_store"] or 0, 2),
        "delivery": round(row["delivery"] or 0, 2),
        "in_store_orders": row["in_store_n"] or 0,
        "delivery_orders": row["delivery_n"] or 0,
    }


# ---------------------------------------------------------------------------
# Helpers — pull live data from the shared backend when available
# ---------------------------------------------------------------------------
async def fetch_backend(path: str):
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{BACKEND}{path}")
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# API — owner-facing aggregates
# ---------------------------------------------------------------------------
@app.get("/api/overview")
async def overview():
    await ensure_shared_synced()
    stats = local_order_stats()
    shared = await fetch_backend("/api/stats")
    stats["waste_logged"] = (shared or {}).get("waste_logged", 0)
    stats["inventory_items"] = (shared or {}).get("inventory_items", 0)
    stats["mode"] = sync_state()
    stats["live"] = _sync["reachable"]
    return stats


@app.get("/api/orders")
async def orders(date: str | None = None):
    """All orders, or only one day when ?date=YYYY-MM-DD."""
    await ensure_shared_synced()
    t = orders_table()
    idc = orders_id_col(t)
    with db_cursor() as c:
        if date:
            rows = c.execute(
                f"SELECT {idc}, order_type, total, created_at, status, customer"
                f" FROM {t} WHERE date(created_at) = ? ORDER BY id",
                (date,),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {idc}, order_type, total, created_at, status, customer"
                f" FROM {t} ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def _day_rollup(day: str) -> dict:
    t = orders_table()
    with db_cursor() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(total),0) AS total,"
            " COALESCE(SUM(CASE WHEN order_type='in-store' THEN total END),0) AS in_store,"
            " COALESCE(SUM(CASE WHEN order_type='delivery' THEN total END),0) AS delivery,"
            " COUNT(*) AS n"
            f" FROM {t} WHERE date(created_at) = ?",
            (day,),
        ).fetchone()
    n = row["n"] or 0
    total = round(row["total"], 2)
    return {
        "total": total,
        "in_store": round(row["in_store"], 2),
        "delivery": round(row["delivery"], 2),
        "orders": n,
        "avg": round(total / n, 2) if n else 0.0,
    }


def _pct_delta(today_v: float, yday_v: float) -> float | None:
    if not yday_v:
        return None
    return round((today_v - yday_v) / yday_v * 100, 1)


@app.get("/api/dashboard/today")
async def dashboard_today(date: str | None = None):
    """Sales report for a selected date (defaults to today), with the previous day for context."""
    def parse_day(s: str | None) -> datetime:
        if not s:
            return datetime.now()
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return datetime.now()

    await ensure_shared_synced()
    selected = parse_day(date)
    day = selected.strftime("%Y-%m-%d")
    prev = (selected - timedelta(days=1)).strftime("%Y-%m-%d")

    t = _day_rollup(day)
    y = _day_rollup(prev)
    delta = round(t["total"] - y["total"], 2)
    is_today = day == datetime.now().strftime("%Y-%m-%d")

    return {
        "date": day,
        "is_today": is_today,
        "total": t["total"],
        "in_store": t["in_store"],
        "delivery": t["delivery"],
        "orders": t["orders"],
        "avg": t["avg"],
        "yesterday_date": prev,
        "yesterday_total": y["total"],
        "yesterday_orders": y["orders"],
        "yesterday_avg": y["avg"],
        "delta": delta,
        "delta_pct": _pct_delta(t["total"], y["total"]),
        "orders_delta_pct": _pct_delta(t["orders"], y["orders"]),
        "avg_delta_pct": _pct_delta(t["avg"], y["avg"]),
        "delivery_share": round(t["delivery"] / t["total"] * 100, 1) if t["total"] else 0,
    }


@app.get("/api/menu/popular")
async def popular_menu():
    """Live orders aggregated by item name; demo list until the backend has orders."""
    await ensure_shared_synced()
    if orders_table() == "shared_orders":
        with db_cursor() as c:
            rows = c.execute("SELECT items FROM shared_orders").fetchall()
        qty_by_name: dict[str, int] = {}
        for r in rows:
            try:
                items = json.loads(r["items"] or "[]")
            except (ValueError, TypeError):
                continue
            if not isinstance(items, list):
                continue
            for it in items:
                name = str((it or {}).get("name") or "").strip()
                if not name:
                    continue
                qty_by_name[name] = qty_by_name.get(name, 0) + int((it or {}).get("qty") or 1)
        if qty_by_name:
            total_q = sum(qty_by_name.values())
            tones = ["#9a3412", "#1e5c4a", "#a16207", "#7c2d12", "#14532d"]
            top = sorted(qty_by_name.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            return [
                {"name": name, "desc": "", "qty": qty,
                 "pct": round(qty / total_q * 100), "tone": tones[i % len(tones)]}
                for i, (name, qty) in enumerate(top)
            ]
    return POPULAR_ITEMS


@app.get("/api/inventory")
async def inventory():
    data = await fetch_backend("/api/inventory")
    if data is None:
        return [
            {"id": 1, "name": "Chicken", "qty": 25, "unit": "lb", "expiry_date": "2026-11-25", "kind": "food"},
            {"id": 2, "name": "Rice", "qty": 40, "unit": "lb", "expiry_date": "2027-01-01", "kind": "food"},
            {"id": 3, "name": "Cooking Oil", "qty": 8, "unit": "L", "expiry_date": "2026-12-15", "kind": "supplies"},
        ]
    return data


@app.get("/report/end-of-day", response_class=HTMLResponse)
async def end_of_day_page():
    """Human-readable end-of-day report (the JSON stays at /api/report/end-of-day)."""
    return FileResponse(STATIC_DIR / "eod.html")


@app.get("/api/report/end-of-day")
async def end_of_day():
    """Consolidated end-of-day report (in-store + delivery cash)."""
    await ensure_shared_synced()
    stats = local_order_stats()
    shared = await fetch_backend("/api/stats")
    return {
        "date": datetime.now().date().isoformat(),
        "mode": sync_state(),
        "revenue": stats["revenue"],
        "orders": stats["orders"],
        "in_store": stats["in_store"],
        "delivery": stats["delivery"],
        "in_store_orders": stats["in_store_orders"],
        "delivery_orders": stats["delivery_orders"],
        "waste_logged": (shared or {}).get("waste_logged", 0),
        "note": "Consolidated report — split into delivery vs in-store cash when agreed.",
        "live": _sync["reachable"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "owner-dashboard"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
