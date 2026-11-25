from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.database import contextmanager_connection
from backend.main import create_app
from backend.security import hash_password


@pytest.fixture
def pos(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with contextmanager_connection(app.state.database) as conn:
            conn.execute(
                "INSERT INTO users(username,display_name,role,password_hash) "
                "VALUES (?,?,?,?)",
                ("cashier1", "Cashier One", "Cashier", hash_password("demo-pass")),
            )
            conn.execute(
                "INSERT INTO menu.menu_items(name,price,available) "
                "VALUES ('Test 500',500,1), ('Test 300',300,1)"
            )
        login = client.post("/auth/login", json={"username": "cashier1", "password": "demo-pass"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        yield client, app, headers


def menu_id(app, name):
    with contextmanager_connection(app.state.database) as conn:
        row = conn.execute(
            "SELECT menu_item_id FROM menu.menu_items WHERE name=?", (name,)
        ).fetchone()
        return row["menu_item_id"]


def order_count(app):
    with contextmanager_connection(app.state.database) as conn:
        return conn.execute("SELECT COUNT(*) AS count FROM main.orders").fetchone()["count"]


@pytest.mark.parametrize(
    ("order_type", "extra"),
    [
        ("dine_in", {}),
        ("takeout", {}),
        ("delivery", {"delivery_address": "10 Test Lane", "customer_phone": "8765550100"}),
    ],
)
def test_order_types_are_saved_and_retrieved(pos, order_type, extra):
    client, app, headers = pos
    item_id = menu_id(app, "Test 500")
    body = {
        "order_type": order_type,
        "line_items": [{"menu_item_id": item_id, "quantity": 1}],
        "idempotency_key": f"type-{order_type}",
        **extra,
    }
    result = client.post("/api/orders", headers=headers, json=body)
    assert result.status_code == 201, result.text
    saved = result.json()
    assert saved["order_type"] == order_type
    assert saved["status"] == "Confirmed"
    assert client.get(f"/api/orders/{saved['order_id']}").json()["order_type"] == order_type


def test_special_requests_and_totals(pos):
    client, app, headers = pos
    first = menu_id(app, "Test 500")
    second = menu_id(app, "Test 300")
    body = {
        "order_type": "dine_in",
        "idempotency_key": "requests-and-total",
        "line_items": [
            {"menu_item_id": first, "quantity": 2, "special_request": "no pepper"},
            {"menu_item_id": second, "quantity": 1, "special_request": "extra sauce"},
        ],
    }
    result = client.post("/api/orders", headers=headers, json=body)
    assert result.status_code == 201, result.text
    order = result.json()
    assert Decimal(str(order["total"])) == Decimal("1300.00")
    assert order["line_items"][0]["special_request"] == "no pepper"
    assert order["line_items"][1]["special_request"] == "extra sauce"

    body["idempotency_key"] = "changed-quantity"
    body["line_items"][0]["quantity"] = 3
    second_order = client.post("/api/orders", headers=headers, json=body)
    assert second_order.status_code == 201
    assert Decimal(str(second_order.json()["total"])) == Decimal("1800.00")


@pytest.mark.parametrize(
    ("address", "phone"),
    [(None, "8765550100"), (" ", "8765550100"), ("10 Test Lane", None), ("10 Test Lane", "   ")],
)
def test_delivery_validation_saves_nothing(pos, address, phone):
    client, app, headers = pos
    item_id = menu_id(app, "Test 500")
    before = order_count(app)
    body = {
        "order_type": "delivery",
        "line_items": [{"menu_item_id": item_id, "quantity": 1}],
        "delivery_address": address,
        "customer_phone": phone,
    }
    result = client.post("/api/orders", headers=headers, json=body)
    assert result.status_code in (400, 422)
    assert order_count(app) == before


@pytest.mark.parametrize(
    "body",
    [
        {"order_type": "dine_in", "line_items": [{"menu_item_id": 999999, "quantity": 1}]},
        {"order_type": "dine_in", "line_items": []},
        {"order_type": "dine_in", "line_items": [{"menu_item_id": 1, "quantity": 0}]},
        {"order_type": "dine_in", "line_items": [{"menu_item_id": 1, "quantity": -1}]},
        {"line_items": [{"menu_item_id": 1, "quantity": 1}]},
    ],
)
def test_invalid_inputs_save_nothing(pos, body):
    client, app, headers = pos
    before = order_count(app)
    result = client.post("/api/orders", headers=headers, json=body)
    assert result.status_code in (400, 422)
    assert order_count(app) == before


def test_unavailable_item_saves_nothing(pos):
    client, app, headers = pos
    with contextmanager_connection(app.state.database) as conn:
        conn.execute(
            "INSERT INTO menu.menu_items(name,price,available) VALUES ('Unavailable',100,0)"
        )
        item_id = conn.execute(
            "SELECT menu_item_id FROM menu.menu_items WHERE name='Unavailable'"
        ).fetchone()["menu_item_id"]
    before = order_count(app)
    result = client.post(
        "/api/orders",
        headers=headers,
        json={"order_type": "takeout", "line_items": [{"menu_item_id": item_id, "quantity": 1}]},
    )
    assert result.status_code == 400
    assert order_count(app) == before


def test_duplicate_submission_returns_one_order(pos):
    client, app, headers = pos
    item_id = menu_id(app, "Test 500")
    body = {
        "order_type": "takeout",
        "idempotency_key": "same-key",
        "line_items": [{"menu_item_id": item_id, "quantity": 1}],
    }
    first = client.post("/api/orders", headers=headers, json=body)
    second = client.post("/api/orders", headers=headers, json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["order_id"] == second.json()["order_id"]
    assert order_count(app) == 1


def test_client_prices_and_totals_are_ignored(pos):
    client, app, headers = pos
    item_id = menu_id(app, "Test 500")
    result = client.post(
        "/api/orders",
        headers=headers,
        json={
            "order_type": "dine_in",
            "line_items": [{"menu_item_id": item_id, "quantity": 2, "unit_price": 1, "total": 2}],
            "total": 1,
            "idempotency_key": "server-prices",
        },
    )
    assert result.status_code == 201
    assert Decimal(str(result.json()["total"])) == Decimal("1000.00")
