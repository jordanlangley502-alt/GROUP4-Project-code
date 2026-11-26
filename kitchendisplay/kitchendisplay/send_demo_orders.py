"""Fill the Kitchen Display with sample orders so the screen can be demonstrated.

Needs the backend running and one Kitchen and one Cashier account (see the main README).
Passwords are typed in, never stored. Run from the project folder:

    python -m kitchendisplay.send_demo_orders --count 4
"""
import argparse
from datetime import date, timedelta
from getpass import getpass
import time
import uuid

import httpx

SAMPLE_MENU = [
    ("Jerk Chicken Plate", "chicken portion", "700.00"),
    ("Curry Goat", "goat portion", "950.00"),
    ("Festival", "festival", "150.00"),
]
SAMPLE_REQUESTS = ["no pepper", "extra gravy", "", "", "sauce on the side"]


def login(client, role):
    username = input(f"{role} username [{role.lower()}]: ").strip() or role.lower()
    response = client.post("/auth/login", json={"username": username, "password": getpass(f"{role} password: ")})
    if response.status_code != 200:
        raise SystemExit(f"{role} sign-in failed: {response.json().get('detail', response.status_code)}")
    user = response.json()
    if user["user"]["role"] != role:
        raise SystemExit(f"{username} is a {user['user']['role']} account, not {role}.")
    return {"Authorization": "Bearer " + user["access_token"]}


def ensure_menu(client, kitchen):
    """Return menu item ids, creating sample stock, menu items and recipes when the menu is empty."""
    menu = client.get("/menu", headers=kitchen).json()
    if menu:
        return [item["menu_item_id"] for item in menu if item.get("available", 1)]
    expiry = (date.today() + timedelta(days=30)).isoformat()
    ids = []
    for name, unit, price in SAMPLE_MENU:
        stock = client.post("/inventory", headers=kitchen, json={"name": name + " stock", "unit": unit, "reorder_level": 5})
        item_id = stock.json()["item_id"]
        client.post(f"/inventory/{item_id}/stock", headers=kitchen, json={"quantity": 100, "expiry_date": expiry}).raise_for_status()
        menu_id = client.post("/menu", headers=kitchen, json={"name": name, "price": price}).json()["menu_item_id"]
        client.post(f"/menu/{menu_id}/recipe", headers=kitchen, json={"inventory_item_id": item_id, "quantity_required": 1}).raise_for_status()
        ids.append(menu_id)
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=4, help="orders to send (default 4)")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between orders")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=10) as client:
        kitchen = login(client, "Kitchen")
        menu_ids = ensure_menu(client, kitchen)
        if not menu_ids:
            raise SystemExit("The menu has no available items.")
        cashier = login(client, "Cashier")
        kinds = ["Dine-in", "Takeout", "Delivery"]
        for number in range(args.count):
            lines = [
                {"menu_item_id": menu_ids[(number + offset) % len(menu_ids)], "quantity": 1 + (number + offset) % 3,
                 "special_request": SAMPLE_REQUESTS[(number + offset) % len(SAMPLE_REQUESTS)]}
                for offset in range(1 + number % 2)
            ]
            body = {"order_type": kinds[number % 3], "items": lines}
            if body["order_type"] == "Delivery":
                body.update(delivery_address="12 Demo Road, Kingston", delivery_phone="876-555-0100")
            response = client.post("/orders", headers={**cashier, "Idempotency-Key": str(uuid.uuid4())}, json=body)
            print(f"Order {number + 1}: {response.status_code}", response.json().get("order_id", response.text))
            time.sleep(args.pause)


if __name__ == "__main__":
    main()
