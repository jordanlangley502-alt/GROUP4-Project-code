# Owner Dashboard — Jamrock Bitez

Jevoy Johnson's part: the owner-facing read-only dashboard.

Shows live totals (orders, revenue, waste, dine-in vs delivery), recent orders,
inventory count, and an end-of-day report. Reads from the shared backend when
it's running; falls back to demo data so the UI always works.

## Run

```bash
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Open **http://127.0.0.1:8001**

Shared backend (Danyl) should run on port **8000** for live data:

```bash
# in the demo folder
python main.py
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Dashboard UI |
| GET | `/api/dashboard/today` | Daily sales report for a selected date (default today): total, in-store, delivery, deltas — pass `?date=YYYY-MM-DD` for past reports |
| GET | `/api/menu/popular` | Popular menu items aggregated from live order lines (demo list while offline) |
| GET | `/api/overview` | Aggregated stats |
| GET | `/api/orders` | Recent orders (filter with `?date=YYYY-MM-DD`) |
| GET | `/api/inventory` | Inventory snapshot |
| GET | `/api/report/end-of-day` | Consolidated EOD report |
| GET | `/api/health` | Health check |

## Notes

- Live mode mirrors the shared backend (`127.0.0.1:8000`): order statuses map
  `new/cooking → Preparing`, `ready → Ready`, `done → Completed`; first-seen time
  is stamped locally because the backend leaves `created_at` empty.
- Popular menu items are aggregated from those live order lines; the built-in
  list is a fallback for when the backend is offline.
- Inventory fallback numbers are demo data until the inventory module ships.
- `owner.db` is gitignored and regenerates with fresh seed data on first run.
- Google Fonts needs internet; offline it falls back to system fonts and still works.
