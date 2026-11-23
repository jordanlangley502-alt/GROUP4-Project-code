# Jamrock Bitez group project

Python 3.12+ and FastAPI shared backend for COMP2140 Group 4. The existing
`Inventorytest` services are reused by the API. Each frontend talks to this one
server, rather than opening its own database.

## Start on Windows

Run these commands in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create staff accounts locally. Each command asks for a password and confirmation.
There are no default passwords or public registration endpoint.

```powershell
.\.venv\Scripts\python.exe -m backend.create_user cashier --role Cashier --name "Test Cashier"
.\.venv\Scripts\python.exe -m backend.create_user kitchen --role Kitchen --name "Test Kitchen"
.\.venv\Scripts\python.exe -m backend.create_user owner --role Owner --name "Test Owner"
.\.venv\Scripts\python.exe -m backend.create_user driver --role "Delivery Person" --name "Test Driver"
.\.venv\Scripts\python.exe -m backend.create_user supervisor --role Supervisor --name "Test Supervisor"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/docs** for interactive API documentation. Call
`POST /auth/login` with a username and password. Copy `access_token`, click
**Authorize**, and paste the token. The docs add the Bearer prefix.

The database defaults to `jamrock_data/` in this project. To use a different local
folder, set `$env:JAMROCK_DATA_DIR` before account creation and server startup.
The new server does not automatically import data from a different CLI working
directory. Back up all database files together while the server is stopped.

## First working order

Use `/docs` and these steps:

1. Sign in as Kitchen. `POST /inventory` with
   `{"name":"Test Chicken","unit":"portion","reorder_level":5}`.
2. Use the returned item ID in `POST /inventory/{item_id}/stock` with a positive
   quantity and a future expiry date, for example
   `{"quantity":20,"expiry_date":"2026-12-31"}`. Use a future date when running later.
3. `POST /menu` with `{"name":"Test Chicken Meal","price":"500.25"}`.
4. Use that menu ID in `POST /menu/{menu_id}/recipe` with
   `{"inventory_item_id":1,"quantity_required":1}`. Replace `1` with the actual stock ID.
5. Sign in as Cashier. `POST /orders`, with `Idempotency-Key` set to a unique
   order-attempt identifier, and this body (replace the menu ID if needed):

   ```json
   {
     "order_type": "Dine-in",
     "items": [{"menu_item_id": 1, "quantity": 2, "special_request": "no pepper"}]
   }
   ```

6. The returned total is 1000.50. Stock drops from 20 to 18. Sign in as Kitchen
   and use `PATCH /orders/{order_id}/status` for Making, then Ready.
7. Sign in as Owner or Supervisor and read `/dashboard` to see the same saved order.

## Shared routes for teammates

All routes below require a Bearer session. `/health`, `/docs`, the OpenAPI schema
and `/auth/login` are public. Logout invalidates the current session; sessions
expire after eight hours. Passwords use salted scrypt hashes; only session-token
hashes are stored.

| Module | Routes | Permissions |
| --- | --- | --- |
| Login | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | Staff |
| POS | `GET /menu`, `GET /orders`, `POST /orders` | Cashier reads/places; other reads below |
| Kitchen | `GET /orders?sequence=oldest`, `PATCH /orders/{id}/status` | Kitchen |
| Inventory | `GET /inventory?sort=quantity`, `GET /inventory/expiry` | Kitchen, Owner |
| Inventory changes | `POST /inventory`, `POST /inventory/{id}/stock`, `POST /inventory/{id}/remove`, `PATCH /inventory/lots/{lot_id}/expiry` | Kitchen |
| Menu setup | `POST /menu`, `POST /menu/{id}/recipe` | Kitchen; Kitchen and Owner may also read menu |
| Delivery | `GET /deliveries` | Delivery Person, Cashier, Owner, Supervisor |
| Delivery changes | `PATCH /deliveries/{order_id}/status`, `PATCH /deliveries/{order_id}/cash` | Assigned Delivery Person; first dispatch claims an unassigned order |
| Payments | `POST /orders/{id}/payment` | Cashier |
| Reports | `GET /reports/daily-sales?day=2026-11-22` | Owner |
| Dashboard | `GET /dashboard?order_type=Delivery`, `GET /orders` | Owner, Supervisor; Cashier and Kitchen may also read orders |
| Audit | `GET /audit-log?limit=100` | Owner, Supervisor |
| Live notifications | `WS /ws/changes` | Staff; topics restricted by role |

Exact request fields and validation are shown in `/docs`. Cash values accept up
to two decimal places. Frontends send menu IDs and quantities, never trusted
totals or a chosen acting username. Delivery orders also require nonblank
`delivery_address` and `delivery_phone`. The phone field is currently validated
as nonblank text, not as a particular national phone format.

For each order attempt generate one `Idempotency-Key` (e.g. `crypto.randomUUID()`)
and reuse that key on network retries. The same key and payload return the original
order without deducting stock twice. Reusing a key with different data returns 409.
A newly generated key represents a new order.

Delivery transitions are Awaiting Pickup, Out for Delivery, Delivered. Include
`cash_collected` when setting Delivered. Negative/blank amounts are rejected;
amounts different from the order total are saved and flagged. Only the assigned
driver can subsequently correct cash. Status history retains the actor and time.
Cash correction does not change a status-change timestamp.

Payment is a separate stored sale, not an online payment integration. Cashier
records it with `{"amount":"1000.50","method":"Cash"}` or method `Card`.
One full payment is allowed per order. Daily reports count paid records only,
using the payment's Jamaica calendar date, and split Dine-in/Takeout from Delivery.
Delivery cash is tracked separately: a driver cash update does not automatically
create a payment, so the cashier must record a reconciled payment for that sale.

## Frontend connection and LAN demo

Serve frontends through a local HTTP server instead of opening `file://` pages.
For another origin/port set an explicit list before starting the backend:

```powershell
$env:JAMROCK_ALLOWED_ORIGINS="http://localhost:5500,http://192.168.1.10:5500"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Replace the address with the actual server LAN IP. Other devices use that address
for API calls; `localhost` on a phone refers to the phone. Bind to the LAN only for
the restaurant/demo network and allow that private network through the host firewall.
The server has no internet dependency after packages are installed. CORS controls
browser origins, not network access. LAN-only access is enforced by the host/network
configuration. HTTP is supported; TLS setup and login rate limiting remain deployment
work before use with real staff/customer data.

Minimal browser integration (keep the returned token in memory):

```javascript
const API = "http://127.0.0.1:8000";
const response = await fetch(`${API}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username, password })
});
if (!response.ok) throw new Error("Sign-in failed");
const { access_token: token } = await response.json();
async function loadDashboard() {
  const result = await fetch(`${API}/dashboard`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!result.ok) throw new Error(`Dashboard failed: ${result.status}`);
  const data = await result.json();
  // Render data.orders and data.deliveries in your frontend.
  return data;
}
function connectChanges() {
  const socket = new WebSocket(API.replace(/^http/, "ws") + "/ws/changes");
  socket.onopen = () => socket.send(JSON.stringify({ token }));
  socket.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    if (event.type === "resync" || event.type === "changed") {
      loadDashboard().catch(console.error);
    }
  };
  socket.onclose = ({ code }) => {
    if (code !== 1008) setTimeout(connectChanges, 1000);
    // 1008 means rejected/expired authentication or origin: sign in again.
  };
}
connectChanges();
```

Other screens use their permitted read routes instead of `loadDashboard`.
Notifications contain only a topic and event metadata. The frontend refetches its
authorized view on connection/reconnection and on changes. The backend polls its
durable change log every 0.5 seconds, then pushes over WebSocket; this is not a
measured guarantee of the SRS latency targets. Load/latency testing on demo hardware
is still required. Use a single server process for this small local deployment.

## Structure and integration decisions

- `backend/main.py`: API and role checks at each action, plus live notifications.
- `backend/database.py`: shared transactions and additional tables.
- `backend/security.py`: password verification, sessions and permissions.
- `backend/schemas.py`: request validation and API field names.
- `backend/create_user.py`: local account setup.
- `Inventorytest/`: existing menu, inventory and order business services.
- `tests/test_backend.py`: end-to-end API, transaction and permission checks.

Orders, accounts, sessions, audit, payments and events are in `orders.db`.
Inventory, menu and delivery files are attached through the same shared database
manager. This preserves the existing layout while using one connection/transaction
for each API operation. Order saving, recipe stock deduction, idempotency, audit
and notifications commit or roll back together. SQLite's default rollback-journal
mode is retained for transactions across attached files. Do not switch these files
to WAL independently or run independent writers that bypass the shared service.

Group decisions used for this first implementation:

- Stock is deducted once on confirmed order placement, per SDS/SR-4.4.
- Delivery starts Awaiting Pickup on every screen, matching Delivery Tracking.
- Live orders include Takeout as well as Dine-in and Delivery.
- Owner and Supervisor business routes are read-only. Kitchen maintains stock/menu.
- A driver may correct their own Delivered order's cash; the correction is audited.
- All API-created orders are confirmed; unconfirmed drafts stay in the frontend.

Review those choices against the group's conflicting SRS wording. This is a shared
integration starting point, not a complete implementation of every group feature.
Existing CLI services can bypass API authentication/audit and should not be used
as a staff interface once the API is in use. Waste-record endpoints, menu availability
editing, account lifecycle management, report export/receipt UI, and frontend screens
are not added here. The inventory service's existing expired-waste behavior still
needs review before exposing waste recording through an API.

## Run checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use temporary databases. They exercise login/logout, roles, order/stock
integration, concurrent duplicate retries, rollback, kitchen transitions, delivery
assignment and cash, paid-sales reporting, WebSocket updates/reconnection, audit
access and restart persistence. They do not replace the group's full test plan or
browser/device and six-user performance testing.

API conventions follow the official FastAPI documentation:
[Bearer authentication](https://fastapi.tiangolo.com/tutorial/security/first-steps/)
and [application lifespan](https://fastapi.tiangolo.com/advanced/events/).
