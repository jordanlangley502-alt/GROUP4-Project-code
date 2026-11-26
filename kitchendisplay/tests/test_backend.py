from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend.database import contextmanager_connection, Transaction
from backend.main import create_app
from backend.security import hash_password, token_hash


@pytest.fixture
def system(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with contextmanager_connection(app.state.database) as conn:
            for username, role in [("owner", "Owner"), ("cashier", "Cashier"), ("kitchen", "Kitchen"), ("driver", "Delivery Person"), ("driver2", "Delivery Person"), ("supervisor", "Supervisor")]:
                conn.execute("INSERT INTO users(username,display_name,role,password_hash) VALUES (?,?,?,?)",
                             (username, username.title(), role, hash_password("testing-pass-123")))
        tokens = {}
        for username in ["owner", "cashier", "kitchen", "driver", "driver2", "supervisor"]:
            result = client.post("/auth/login", json={"username": username, "password": "testing-pass-123"})
            assert result.status_code == 200, result.text
            tokens[username] = result.json()["access_token"]
        def headers(name):
            return {"Authorization": "Bearer " + tokens[name]}
        kitchen = headers("kitchen")
        stock = client.post("/inventory", headers=kitchen, json={"name": "Chicken", "unit": "portion", "reorder_level": 5}).json()["item_id"]
        result = client.post(f"/inventory/{stock}/stock", headers=kitchen, json={"quantity": 20, "expiry_date": (date.today()+timedelta(days=10)).isoformat()})
        assert result.status_code == 201, result.text
        menu = client.post("/menu", headers=kitchen, json={"name": "Test Chicken", "price": "500.25"}).json()["menu_item_id"]
        assert client.post(f"/menu/{menu}/recipe", headers=kitchen, json={"inventory_item_id": stock, "quantity_required": 1}).status_code == 201
        yield client, app, headers, tokens, menu


def place(system, key="one", kind="Dine-in", quantity=2):
    client, _, headers, _, menu = system
    body = {"order_type": kind, "items": [{"menu_item_id": menu, "quantity": quantity, "special_request": "no pepper"}]}
    if kind == "Delivery":
        body.update(delivery_address="10 Test Lane", delivery_phone="000-test-phone")
    return client.post("/orders", headers={**headers("cashier"), "Idempotency-Key": key}, json=body)


def test_auth_session_and_password_storage(system):
    client, app, headers, tokens, _ = system
    assert client.get("/orders").status_code == 401
    assert client.post("/auth/login", json={"username": "cashier", "password": "wrong"}).status_code == 401
    assert client.get("/auth/me", headers=headers("cashier")).json()["role"] == "Cashier"
    with contextmanager_connection(app.state.database) as conn:
        assert conn.execute("SELECT password_hash FROM users LIMIT 1").fetchone()[0].startswith("scrypt$")
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash=?", (tokens["cashier"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash=?", (token_hash(tokens["cashier"]),)).fetchone()[0] == 1
    assert client.post("/auth/logout", headers=headers("cashier")).status_code == 200
    assert client.get("/auth/me", headers=headers("cashier")).status_code == 401


@pytest.mark.parametrize("role", ["owner", "supervisor", "driver", "kitchen"])
def test_roles_cannot_submit_orders(system, role):
    client, _, headers, _, menu = system
    response = client.post("/orders", headers={**headers(role), "Idempotency-Key": "denied"}, json={"order_type": "Dine-in", "items": [{"menu_item_id": menu, "quantity": 1}]})
    assert response.status_code == 403


def test_order_uses_menu_price_and_keeps_request(system):
    client, _, headers, _, _ = system
    result = place(system)
    assert result.status_code == 201, result.text
    order = result.json()
    assert order["total"] == 1000.5
    assert order["items"][0]["item_name"] == "Test Chicken"
    assert order["items"][0]["special_request"] == "no pepper"
    assert client.get("/inventory", headers=headers("kitchen")).json()[0]["quantity"] == 18
    assert client.get("/dashboard", headers=headers("owner")).json()["orders"][0]["order_id"] == order["order_id"]


def test_duplicates_and_key_conflicts(system):
    client, _, headers, _, _ = system
    first = place(system).json()
    assert place(system).json()["order_id"] == first["order_id"]
    assert place(system, quantity=3).status_code == 409
    assert len(client.get("/orders", headers=headers("cashier")).json()) == 1
    assert client.get("/inventory", headers=headers("kitchen")).json()[0]["quantity"] == 18


def test_simultaneous_retries_deduct_once(system):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: place(system), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["order_id"] == responses[1].json()["order_id"]
    client, _, headers, _, _ = system
    assert client.get("/inventory", headers=headers("kitchen")).json()[0]["quantity"] == 18


def test_validation_and_insufficient_stock_leave_no_order(system):
    client, _, headers, _, menu = system
    assert place(system, quantity=21).status_code == 400
    for address, phone in [(" ", "123"), ("Test Lane", None)]:
        response = client.post("/orders", headers={**headers("cashier"), "Idempotency-Key": "bad"}, json={"order_type": "Delivery", "items": [{"menu_item_id": menu, "quantity": 1}], "delivery_address": address, "delivery_phone": phone})
        assert response.status_code in (400, 422)
    assert place(system, quantity=-1).status_code == 422
    assert place(system, quantity=1.5).status_code == 422
    assert client.get("/orders", headers=headers("cashier")).json() == []
    assert client.get("/inventory", headers=headers("kitchen")).json()[0]["quantity"] == 20


def test_audit_failure_rolls_back_order_stock_and_events(system, monkeypatch):
    client, app, headers, _, _ = system
    with contextmanager_connection(app.state.database) as conn:
        before = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    def broken(*args):
        raise ValueError("Simulated audit failure")
    monkeypatch.setattr(Transaction, "record", broken)
    assert place(system).status_code == 400
    assert client.get("/orders", headers=headers("cashier")).json() == []
    assert client.get("/inventory", headers=headers("kitchen")).json()[0]["quantity"] == 20
    with contextmanager_connection(app.state.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == before


def test_kitchen_status_and_readonly_dashboard(system):
    client, _, headers, _, _ = system
    order = place(system).json()["order_id"]
    assert client.patch(f"/orders/{order}/status", headers=headers("kitchen"), json={"status": "Ready"}).status_code == 400
    for status in ("Making", "Ready"):
        assert client.patch(f"/orders/{order}/status", headers=headers("kitchen"), json={"status": status}).status_code == 200
        assert client.get("/dashboard", headers=headers("supervisor")).json()["orders"][0]["status"] == status
    for role in ("owner", "supervisor"):
        assert client.patch(f"/orders/{order}/status", headers=headers(role), json={"status": "Making"}).status_code == 403
        assert client.post("/inventory", headers=headers(role), json={"name": "Denied", "unit": "kg"}).status_code == 403
    assert client.get("/dashboard?order_type=Delivery", headers=headers("owner")).json()["orders"] == []


def test_delivery_assignment_cash_history_and_permissions(system):
    client, _, headers, _, _ = system
    order = place(system, kind="Delivery").json()["order_id"]
    path = f"/deliveries/{order}/status"
    assert client.get("/deliveries", headers=headers("owner")).json()[0]["cash_display"] == "Not collected"
    assert client.patch(path, headers=headers("driver"), json={"status": "Delivered", "cash_collected": "1000.50"}).status_code == 409
    assert client.patch(path, headers=headers("driver"), json={"status": "Out for Delivery"}).status_code == 200
    assert client.patch(path, headers=headers("driver2"), json={"status": "Delivered", "cash_collected": "1000.50"}).status_code == 409
    assert client.patch(path, headers=headers("driver"), json={"status": "Delivered"}).status_code == 400
    result = client.patch(path, headers=headers("driver"), json={"status": "Delivered", "cash_collected": "900.25"})
    assert result.status_code == 200, result.text
    assert result.json()["cash_mismatch"] is True
    assert len(result.json()["history"]) == 2
    corrected = client.patch(f"/deliveries/{order}/cash", headers=headers("driver"), json={"cash_collected": "1000.50"})
    assert corrected.json()["cash_mismatch"] is False
    assert corrected.json()["cash_collected"] == 1000.5
    for role in ("owner", "supervisor", "cashier"):
        assert client.patch(path, headers=headers(role), json={"status": "Out for Delivery"}).status_code == 403
    assert client.get("/deliveries", headers=headers("kitchen")).status_code == 403


def test_payment_reports_exclude_unpaid_and_other_dates(system):
    client, app, headers, _, _ = system
    dine = place(system, key="dine", quantity=2).json()["order_id"]
    delivery = place(system, key="delivery", kind="Delivery", quantity=1).json()["order_id"]
    place(system, key="unpaid", quantity=1)
    today = datetime.now(timezone(timedelta(hours=-5))).date().isoformat()
    for order, amount in [(dine, "1000.50"), (delivery, "500.25")]:
        result = client.post(f"/orders/{order}/payment", headers=headers("cashier"), json={"amount": amount, "method": "Cash"})
        assert result.status_code == 201, result.text
    assert client.post(f"/orders/{dine}/payment", headers=headers("cashier"), json={"amount": "1000.50", "method": "Cash"}).status_code == 409
    report = client.get(f"/reports/daily-sales?day={today}", headers=headers("owner")).json()
    assert report == {"date": today, "in_store": 1000.5, "delivery": 500.25, "total": 1500.75}
    assert client.get("/reports/daily-sales?day=2000-01-01", headers=headers("owner")).json()["total"] == 0
    assert client.get(f"/reports/daily-sales?day={today}", headers=headers("cashier")).status_code == 403
    with contextmanager_connection(app.state.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 2


def test_websocket_updates_and_reconnect_resync(system):
    client, _, headers, tokens, _ = system
    with client.websocket_connect("/ws/changes") as socket:
        socket.send_json({"token": tokens["owner"]})
        assert socket.receive_json()["type"] == "resync"
        assert place(system).status_code == 201
        event = socket.receive_json()
        assert event["type"] == "changed" and event["topic"] == "orders"
        assert "address" not in event
    place(system, key="while-disconnected")
    with client.websocket_connect("/ws/changes") as socket:
        socket.send_json({"token": tokens["owner"]})
        assert socket.receive_json()["type"] == "resync"
        assert len(client.get("/dashboard", headers=headers("owner")).json()["orders"]) == 2


def test_restart_persistence_and_audit_visibility(system):
    client, app, headers, tokens, _ = system
    order = place(system).json()["order_id"]
    assert client.get("/audit-log", headers=headers("cashier")).status_code == 403
    audit = client.get("/audit-log", headers=headers("owner")).json()
    assert any(item["action"] == "place_order" and item["resource"] == str(order) for item in audit)
    with TestClient(create_app(app.state.database.folder)) as restarted:
        assert restarted.get("/orders", headers=headers("cashier")).json()[0]["order_id"] == order
