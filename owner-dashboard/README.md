# Owner Dashboard — Jamrock Bitez

Jevoy Johnson's part: the owner-facing read-only dashboard.

Shows live totals (orders, revenue, dine-in vs delivery), recent orders,
inventory count, and an end-of-day report. Reads from the shared backend when
it's running; falls back to demo data so the UI always works.

## Run

```bash
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Open **http://127.0.0.1:8001**

The shared backend (Danyl's `backend/`) should run on port **8000** for live
data. This dashboard logs in as the **Owner** — give it credentials with either
environment variables or a gitignored `owner-dashboard/backend_login.json`:

```bash
# backend (from the repo root)
JAMROCK_DATA_DIR=./jamrock_data uvicorn backend.main:app --port 8000

# dashboard
export JAMROCK_OWNER_USERNAME=owner
export JAMROCK_OWNER_PASSWORD=...
uvicorn main:app --port 8001
```

### Teammates: one shared backend, any platform

One machine runs the backend; everyone else only needs a browser (POS is a
web app served by the backend itself, so Windows/macOS/Linux are identical):

```text
POS (cashiers):     http://<backend-host>:8000/pos/
Dashboard (view):   http://<backend-host>:8001
```

To run your **own dashboard copy** against a teammate's backend instead of a
local one, point it at their machine:

```bash
JAMROCK_BACKEND_URL=http://100.x.x.x:8000 uvicorn main:app --port 8001
```

No extra config is needed for the POS — it posts to whichever backend served
the page. Orders placed anywhere appear on every open dashboard within ~3 s.

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

- Adapter over his real routes: `POST /auth/login`, `GET /dashboard`,
  `GET /inventory`, `GET /reports/daily-sales?day=YYYY-MM-DD` — all with a
  `Bearer` token; no route of his was changed for this dashboard.
- Field mapping: `order_id → id`; `Dine-in`/`Takeout → in-store`,
  `Delivery → delivery`; `Confirmed`/`Making → Preparing`, `Ready → Ready`,
  delivery `Out for Delivery → Out for delivery`, `Delivered → Completed`.
  `placed_at` (UTC) is converted to Jamaica time for date/hour grouping.
- Money totals come from `/reports/daily-sales` (paid orders, trading day
  UTC-5); order counts and the hourly chart come from the mirrored order list.
- Waste has no endpoint in his backend — the board shows 0 honestly.
- Popular menu items are aggregated from live `line_items.item_name` counts;
  the built-in list is a fallback for when the backend is offline.
- Inventory fallback numbers are demo data when the backend is unreachable.
- `owner.db` is gitignored and regenerates with fresh seed data on first run.
- Google Fonts needs internet; offline it falls back to system fonts and still works.
