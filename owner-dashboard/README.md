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
| GET | `/api/overview` | Aggregated stats |
| GET | `/api/orders` | Recent orders |
| GET | `/api/inventory` | Inventory snapshot |
| GET | `/api/report/end-of-day` | Consolidated EOD report |
| GET | `/api/health` | Health check |
