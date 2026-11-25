import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from fastapi.testclient import TestClient
from accounts import setup
from app import app


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, DELIVERY_DB=str(Path(tmp.name) / "test.db"))
        env.start()
        self.addCleanup(env.stop)
        output = io.StringIO()
        with redirect_stdout(output):
            setup()
        self.auth = dict(line.split() for line in output.getvalue().splitlines())
        self.client = TestClient(app)
        self.order = dict(order_id="J1", order_type="delivery", address="10 Test Road",
                          phone="555-0100", total_cents=150000)

    def post(self, endpoint, role, data=None):
        return self.client.post("/api/" + endpoint, auth=(role, self.auth[role]), json=data)

    def confirm(self, **changes):
        return self.post("confirm", "cashier", self.order | changes)

    def rows(self, role="owner"):
        return self.client.get("/api/deliveries", auth=(role, self.auth[role])).json()

    def test_queue(self):
        for kind in ("takeout", "dine-in"):
            self.assertFalse(self.confirm(order_type=kind).json()["tracked"])
        self.assertEqual(self.rows(), [])
        for key in ("phone", "address"):
            self.assertEqual(self.confirm(**{key: " "}).status_code, 422)
        start = monotonic()
        self.assertTrue(self.confirm().json()["tracked"])
        row, = self.rows()
        self.assertLess(monotonic() - start, 3)
        self.assertEqual((row["status"], row["address"]), ("Awaiting Pickup", "10 Test Road"))
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.confirm(total_cents=0).status_code, 409)

    def test_access(self):
        self.confirm()
        self.assertEqual(self.client.get("/api/deliveries").status_code, 401)
        for role in ("cashier", "supervisor", "owner"):
            self.assertEqual(len(self.rows(role)), 1)
            self.assertEqual(self.post("deliveries/J1/pickup", role).status_code, 403)
            self.assertEqual(self.post("deliveries/J1/complete", role, {"cash_cents":0}).status_code, 403)

    def test_transitions_and_cash(self):
        for index, amount in enumerate((150000, 140000, 160000)):
            order_id = str(index)
            self.confirm(order_id=order_id)
            base = "deliveries/" + order_id
            cash = {"cash_cents": amount}
            self.assertEqual(self.post(base+"/complete", "driver1", cash).status_code, 409)
            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(lambda name: self.post(base+"/pickup", name), ("driver1", "driver2")))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
            driver = next(row["driver"] for row in self.rows() if row["id"] == order_id)
            other = "driver2" if driver == "driver1" else "driver1"
            self.assertEqual(self.post(base+"/complete", other, cash).status_code, 409)
            for bad in ({}, {"cash_cents":-1}, {"cash_cents":""}):
                self.assertEqual(self.post(base+"/complete", driver, bad).status_code, 422)
            self.assertEqual(self.post(base+"/complete", driver, cash).status_code, 200)
            self.assertEqual(self.post(base+"/pickup", driver).status_code, 409)
            row = next(row for row in self.rows() if row["id"] == order_id)
            self.assertTrue(row["picked_at"] and row["delivered_at"])
            self.assertEqual(row["mismatch"], amount != self.order["total_cents"])
