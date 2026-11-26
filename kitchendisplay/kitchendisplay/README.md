# Kitchen Display (Feature 2)

Owner: Anneka Nunes. Covers UC-2 View Order on Kitchen Display, UC-3 Update Order Status, and SR-2.1 to SR-2.3 of the SRS.

The screen is plain HTML, CSS and JavaScript served by the shared backend, so it uses the same database, logins and
live updates as the register, delivery and dashboard screens. There is no second server to run.

```
kitchendisplay/
├── web/
│   ├── index.html        the screen (sign-in, New orders / Making / Ready board)
│   ├── kitchen.css
│   └── kitchen.js        loads orders, changes status, keeps the screen live
├── send_demo_orders.py   optional: puts sample orders on the screen for a demo
└── README.md
tests/test_kitchen_display.py   tests written from TS-2.1A to TS-2.3B
```

## Run it

Follow the main README to install and create a **Kitchen** and a **Cashier** account, then start the server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/kitchen/** on the kitchen monitor or tablet and sign in as the Kitchen user.
For another device on the restaurant network start the server with `--host 0.0.0.0` and open
`http://<server LAN address>:8000/kitchen/`. Because the page comes from the backend itself, nothing needs to be
added to `JAMROCK_ALLOWED_ORIGINS`.

To see the screen working without the register, in a second terminal (with the server running):

```powershell
.\.venv\Scripts\python.exe -m kitchendisplay.send_demo_orders --count 4
```

It asks for the Kitchen and Cashier passwords, adds a small sample menu if there is none, and places orders
a couple of seconds apart.

## How it meets the requirements

| SRS | What the screen does | Backend it uses |
| --- | --- | --- |
| SR-2.1 / AC-2.1 | Lists confirmed orders oldest first, so the sequence placed is the sequence cooked. New orders are pushed over the live connection, which checks for changes every 0.5 s. | `GET /orders?sequence=oldest`, `WS /ws/changes` |
| SR-2.2 / AC-2.2 | One large button per order: **Start making** (Confirmed to Making) then **Mark ready** (Making to Ready). Steps cannot be skipped or reversed. | `PATCH /orders/{id}/status` |
| SR-2.3 / AC-2.3 | Nothing extra to build here: the register reads the same order status from the same backend. | `GET /orders` |

Other behaviour:

- Each ticket shows order number, order type, time placed, how long it has been waiting, every item with its
  quantity, and any special request highlighted under the item it belongs to.
- Delivery addresses and phone numbers are never shown to the kitchen.
- Ready orders stay in the Ready column (latest 8) so the cashier can see what is waiting for pickup.
- If the live connection drops, the screen shows "Refreshing every 2 s", keeps polling, and reconnects by itself.
  Orders placed while it was disconnected appear as soon as it reconnects.
- If two kitchen screens press the same button, the second one is told the order was already updated and the board
  refreshes.
- Only Kitchen accounts can sign in to this screen or change an order's status. Other roles get 403 from the backend.
- Staff-typed special requests are displayed as plain text only.

## Test scenarios

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests/test_kitchen_display.py -q
```

| SRS scenario | Test |
| --- | --- |
| TS-2.1A order appears within 2.0 s | `test_ts_2_1a_confirmed_order_appears_with_confirmed_status_within_two_seconds`, `test_ts_2_1a_websocket_pushes_new_order_to_open_screen_within_two_seconds` |
| TS-2.1B orders A, B, C keep their sequence | `test_ts_2_1b_rapid_orders_keep_the_order_they_were_placed` |
| TS-2.2A Making keeps its status | `test_ts_2_2a_and_2_2b_order_moves_to_making_then_ready_and_keeps_status` |
| TS-2.2B Making to Ready | same test |
| TS-2.3A register shows the same status | `test_ts_2_3a_register_shows_the_status_the_kitchen_set` |
| TS-2.3B two orders, two different statuses | `test_ts_2_3b_register_shows_the_correct_status_against_each_order` |

Extra tests cover skipped or reversed steps, invalid statuses, unknown orders, role restrictions (cashier, owner,
supervisor and delivery person cannot change status), special requests staying on their own line item, the
customer-details privacy rule, the page being served, and the live connection's origin and session checks.

The six-user load and device testing in section 3.1 of the SRS still has to be done on the restaurant hardware.

## Changes made to teammates' files

All in `backend/main.py`:

1. **Serves the screen** at `/kitchen` (a three-line static mount).
2. **Live connection accepts pages served by the backend.** `WS /ws/changes` only allowed origins listed in
   `JAMROCK_ALLOWED_ORIGINS`, so a page served by the backend itself was rejected. It now also accepts a same-origin
   page. Other sites are still refused.
3. **Each request now commits before its response is sent** (`Depends(transaction, scope="function")` on all routes).
   With the default setting FastAPI sends the response first and commits afterwards. On a real server about 1 login
   in 6 was followed by a 401 on the very next request, and a screen could read an order's old status straight after
   changing it. The in-process test client cannot show this, so `test_every_request_commits_before_its_response_is_sent`
   guards the setting.
4. **No error in the server log when a screen disconnects.** Closing a screen that was already gone raised an
   unhandled `RuntimeError` each time; it is now ignored.
