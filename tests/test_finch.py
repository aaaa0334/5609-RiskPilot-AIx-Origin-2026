import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import app


class FinchDirectApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_is_public_and_ready(self):
        response = self.client.get("/api/finch/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_risk_coach_returns_compact_educational_result(self):
        response = self.client.post("/api/finch/risk-coach", json={
            "stock_code": "601318",
            "capital": 100000,
            "max_loss": 3000,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result_type"], "historical_risk_education")
        self.assertIs(body["stock"]["is_live"], False)
        self.assertGreaterEqual(body["simulation"]["simulated_shares"], 0)
        self.assertEqual(len(body["stress_scenarios"]), 3)
        self.assertIn("not investment advice", body["limitations"][-1])
        self.assertLess(len(json.dumps(body, ensure_ascii=False).encode("utf-8")), 65536)

    def test_rejects_loss_budget_above_capital(self):
        response = self.client.post("/api/finch/risk-coach", json={
            "stock_code": "601318",
            "capital": 100000,
            "max_loss": 100001,
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()