# Jamrock Bitez delivery tracking

## Run on Windows
Extract the ZIP and open a terminal in the folder containing app.py. With Python 3.12 installed, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_demo.py
.\.venv\Scripts\python.exe -m uvicorn app:app
```

Save the demo passwords printed by setup. Open http://127.0.0.1:8000 and sign in as cashier. Use a separate private browser window for driver1 so each window keeps its own login. All dashboard assets are local. The default server listens on the laptop only.

## Demonstrate one delivery
1. As cashier, expand **Confirm a test order**. Enter D101, delivery, a fictional address and phone, and JMD 1500. Confirm.
2. In the driver window, watch D101 appear as Awaiting Pickup. Select **Pick up order**. Check that the cashier sees the assigned driver and pickup time.
3. As driver, enter 1400 and mark delivered. The cashier sees JMD 1400 collected against JMD 1500 due, with the difference flagged.
4. Sign in as owner or supervisor in another browser session to see the read-only queue.

## Group integration
The standalone checkout simulates the POS confirmation step. The group POS must require address and phone before committing a delivery sale. Send the confirmed order to POST /api/confirm using its stable order ID (retry with the same details if necessary). Once database tables are shared, create the delivery record within the POS confirmation transaction. Money in the API is integer cents. Replace the demo account dependency with the team's staff login and preserve server-side role and assignment checks. app.py contains the API and database connection, accounts.py the demo accounts, and dashboard.html the polling interface. The setup script creates the SQLite tables. See /docs for request schemas.

The restaurant server can serve the same dashboard to on-site and off-site staff. The team still needs to select and configure Tailscale or ngrok and test an authenticated driver on mobile data against the restaurant server. Use an encrypted connection when sending staff credentials. The dashboard retries disconnected reads. Drivers must reconnect to submit a pickup or completion.

## Run checks
```powershell
.\.venv\Scripts\python.exe -m unittest -v
```
Tests use temporary databases and cover validation, filtering, duplicate confirmation, time to read a newly confirmed delivery, role permissions, simultaneous pickup, assignment, invalid transitions and cash discrepancies. The three-second display target also needs a timed run in an actual driver browser on the intended network.
