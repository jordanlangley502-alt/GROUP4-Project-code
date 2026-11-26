"""Kitchen Display (Feature 2) tests, written from the SRS test scenarios TS-2.1A to TS-2.3B.

UC-2 View Order on Kitchen Display, UC-3 Update Order Status, SR-2.1 to SR-2.3.
Run with:  python -m pytest tests/test_kitchen_display.py -q
"""
from datetime import date, timedelta
from time import monotonic
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.database import contextmanager_connection
from backend.main import create_app
from backend.security import hash_password

PASSWORD = "testing-pass-123"
ROLES = {"cashier": "Cashier", "kitchen": "Kitchen", "owner": "Owner",
         "supervisor": "Supervisor", "driver": "Delivery Person"}


@pytest.fixture
def system(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with contextmanager_connection(app.state.database) as conn:
            for username, role in ROLES.items():
                conn.execute("INSERT INTO users(username,display_name,role,password_hash) VALUES (?,?,?,?)",
                             (username, username.title(), role, hash_password(PASSWORD)))
        tokens = {}
        for username in ROLES:
            result = client.post("/auth/login", json={"username": username, "password": PASSWORD})
            assert result.status_code == 200, result.text
            tokens[username] = result.json()["access_token"]

        def headers(name):
            return {"Authorization": "Bearer " + tokens[name]}

        menu = {}
        for name, price in (("Chicken", "500.25"), ("Festival", "150.00")):
            stock = client.post("/inventory", headers=headers("kitchen"),
                                json={"name": name + " stock", "unit": "portion", "reorder_level": 5}).json()["item_id"]
            client.post(f"/inventory/{stock}/stock", headers=headers("kitchen"),
                        json={"quantity": 100, "expiry_date": (date.today() + timedelta(days=10)).isoformat()})
            menu_id = client.post("/menu", headers=headers("kitchen"), json={"name": name, "price": price}).json()["menu_item_id"]
            client.post(f"/menu/{menu_id}/recipe", headers=headers("kitchen"),
                        json={"inventory_item_id": stock, "quantity_required": 1})
            menu[name] = menu_id

        def place(key, kind="Dine-in", items=None):
            lines = items or [{"menu_item_id": menu["Chicken"], "quantity": 2, "special_request": "no pepper"}]
            body = {"order_type": kind, "items": lines}
            if kind == "Delivery":
                body.update(delivery_address="10 Test Lane", delivery_phone="876-555-0100")
            return client.post("/orders", headers={**headers("cashier"), "Idempotency-Key": key}, json=body)

        def board(role="kitchen", sequence="oldest"):
            return client.get(f"/orders?sequence={sequence}", headers=headers(role)).json()

        def set_status(order_id, status, role="kitchen"):
            return client.patch(f"/orders/{order_id}/status", headers=headers(role), json={"status": status})

        yield SimpleNamespace(client=client, app=app, tokens=tokens, headers=headers, menu=menu,
                              place=place, board=board, set_status=set_status)


def statuses(orders):
    return {order["order_id"]: order["status"] for order in orders}


# SR-2.1 / AC-2.1: confirmed orders appear in confirmation order, within two seconds


def test_ts_2_1a_confirmed_order_appears_with_confirmed_status_within_two_seconds(system):
    start = monotonic()
    order = system.place("one").json()
    shown = system.board()
    assert monotonic() - start < 2.0
    assert [o["order_id"] for o in shown] == [order["order_id"]]
    assert shown[0]["status"] == "Confirmed"
    assert shown[0]["items"][0]["item_name"] == "Chicken"
    assert shown[0]["items"][0]["quantity"] == 2


def test_ts_2_1a_websocket_pushes_new_order_to_open_screen_within_two_seconds(system):
    with system.client.websocket_connect("/ws/changes", headers={"origin": "http://testserver"}) as socket:
        socket.send_json({"token": system.tokens["kitchen"]})
        assert socket.receive_json()["type"] == "resync"
        start = monotonic()
        assert system.place("pushed").status_code == 201
        event = socket.receive_json()
        assert event["type"] == "changed" and event["topic"] == "orders"
        assert monotonic() - start < 2.0
        assert len(system.board()) == 1


def test_ts_2_1b_rapid_orders_keep_the_order_they_were_placed(system):
    placed = [system.place(key, kind).json()["order_id"]
              for key, kind in (("a", "Dine-in"), ("b", "Takeout"), ("c", "Delivery"))]
    start = monotonic()
    shown = system.board(sequence="oldest")
    assert monotonic() - start < 2.0
    assert [o["order_id"] for o in shown] == placed
    assert statuses(shown) == {oid: "Confirmed" for oid in placed}


def test_kitchen_sees_order_type_but_no_customer_contact_details(system):
    system.place("delivery", kind="Delivery")
    (order,) = system.board()
    assert order["order_type"] == "Delivery"
    text = str(order).lower()
    assert "10 test lane" not in text and "876-555-0100" not in text


def test_special_requests_stay_with_their_own_line_item(system):
    system.place("requests", items=[
        {"menu_item_id": system.menu["Chicken"], "quantity": 1, "special_request": "no pepper"},
        {"menu_item_id": system.menu["Festival"], "quantity": 3, "special_request": "extra crispy"},
        {"menu_item_id": system.menu["Chicken"], "quantity": 1},
    ])
    items = system.board()[0]["items"]
    assert [(i["item_name"], i["quantity"], i["special_request"]) for i in items] == [
        ("Chicken", 1, "no pepper"), ("Festival", 3, "extra crispy"), ("Chicken", 1, "")]


# SR-2.2 / AC-2.2: Kitchen changes an order to Making, then Ready


def test_ts_2_2a_and_2_2b_order_moves_to_making_then_ready_and_keeps_status(system):
    order_id = system.place("one").json()["order_id"]
    making = system.set_status(order_id, "Making")
    assert making.status_code == 200 and making.json()["status"] == "Making"
    assert system.board()[0]["status"] == "Making"
    ready = system.set_status(order_id, "Ready")
    assert ready.status_code == 200 and ready.json()["status"] == "Ready"
    assert system.board()[0]["status"] == "Ready"


def test_status_changes_cannot_skip_or_reverse_a_step(system):
    order_id = system.place("one").json()["order_id"]
    assert system.set_status(order_id, "Ready").status_code == 400  # skips Making
    assert system.board()[0]["status"] == "Confirmed"
    assert system.set_status(order_id, "Making").status_code == 200
    assert system.set_status(order_id, "Making").status_code == 400  # already Making
    assert system.set_status(order_id, "Ready").status_code == 200
    assert system.set_status(order_id, "Making").status_code == 400  # cannot reverse
    assert system.board()[0]["status"] == "Ready"


def test_invalid_status_value_and_unknown_order_are_rejected(system):
    order_id = system.place("one").json()["order_id"]
    for bad in ("Completed", "Confirmed", "", "making"):
        assert system.set_status(order_id, bad).status_code == 422
    assert system.set_status(99999, "Making").status_code == 404
    assert system.board()[0]["status"] == "Confirmed"


@pytest.mark.parametrize("role", ["cashier", "owner", "supervisor", "driver"])
def test_only_kitchen_staff_can_change_order_status(system, role):
    order_id = system.place("one").json()["order_id"]
    assert system.set_status(order_id, "Making", role=role).status_code == 403
    assert system.board()[0]["status"] == "Confirmed"


def test_kitchen_screen_requires_sign_in_and_the_right_role(system):
    assert system.client.get("/orders").status_code == 401
    assert system.client.patch("/orders/1/status", json={"status": "Making"}).status_code == 401
    assert system.client.get("/orders", headers=system.headers("driver")).status_code == 403


# SR-2.3 / AC-2.3: the register shows the latest kitchen status


def test_ts_2_3a_register_shows_the_status_the_kitchen_set(system):
    order_id = system.place("one").json()["order_id"]
    assert system.board("cashier")[0]["status"] == "Confirmed"
    for status in ("Making", "Ready"):
        system.set_status(order_id, status)
        assert system.board("cashier")[0]["status"] == status


def test_ts_2_3b_register_shows_the_correct_status_against_each_order(system):
    first, second, third = (system.place(key).json()["order_id"] for key in "abc")
    system.set_status(first, "Making")
    system.set_status(second, "Making")
    system.set_status(second, "Ready")
    for role in ("cashier", "owner", "supervisor"):
        assert statuses(system.board(role)) == {first: "Making", second: "Ready", third: "Confirmed"}


# The screen itself


def test_kitchen_page_is_served_and_never_writes_order_text_as_html(system):
    page = system.client.get("/kitchen/")
    assert page.status_code == 200 and "Kitchen Display" in page.text
    script = system.client.get("/kitchen/kitchen.js")
    assert script.status_code == 200
    assert "innerHTML" not in script.text  # special requests are typed by staff; show them as text only
    assert system.client.get("/kitchen/kitchen.css").status_code == 200


def test_live_connection_accepts_the_kitchen_page_origin_and_rejects_other_sites(system):
    for origin in ("http://testserver", "http://localhost:5500"):
        with system.client.websocket_connect("/ws/changes", headers={"origin": origin}) as socket:
            socket.send_json({"token": system.tokens["kitchen"]})
            assert socket.receive_json()["type"] == "resync"
    with pytest.raises(WebSocketDisconnect):
        with system.client.websocket_connect("/ws/changes", headers={"origin": "http://evil.example"}):
            pass


def test_every_request_commits_before_its_response_is_sent():
    # With the default dependency scope FastAPI sends the response first and commits afterwards, so a screen
    # that signs in (or changes a status) and immediately asks again could be told "not signed in" or read the
    # old status. A real server showed ~1 in 6 logins rejected. The test client cannot reproduce the timing,
    # so guard the setting itself.
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "backend" / "main.py").read_text()
    assert "Depends(transaction)" not in source
    assert source.count('Depends(transaction, scope="function")') >= 20


def test_live_connection_rejects_a_bad_session_token(system):
    with system.client.websocket_connect("/ws/changes", headers={"origin": "http://testserver"}) as socket:
        socket.send_json({"token": "not-a-real-token"})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
