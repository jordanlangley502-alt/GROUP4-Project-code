# POS Place Order

## Install

```bash
cd /path/to/GROUP4-Project-code
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Create a cashier, then start the shared demo app:

```bash
python -m backend.create_user cashier1 --role Cashier --name "Demo Cashier"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/pos/` and sign in on the page with the cashier
username and password. The POS uses the existing `POST /auth/login` endpoint
and keeps the session token in browser session storage.

## Tests

```bash
python -m pytest -q backend/tests/test_pos.py
```

## API

- `GET /api/menu`
- `POST /api/orders`
- `GET /api/orders/{order_id}`
- `GET /api/orders?status=Confirmed&order_type=dine_in`

POST uses the existing Cashier bearer role. Delivery orders require
`delivery_address` and `customer_phone`. The server reads menu prices and ignores
client-sent prices/totals. Duplicate `idempotency_key` submissions return 200
with the original order.

## Integration hooks

`notify_kitchen(order)` is an Anneka/Kitchen Display placeholder.
`deduct_inventory(order)` is a Jordan/Inventory placeholder.
Both currently log and do nothing.

Teammates should use these Order fields:
`delivery_address`, `customer_phone`, `order_type`, `status`, `total`,
`idempotency_key`, `placed_by`, and `placed_at`.
