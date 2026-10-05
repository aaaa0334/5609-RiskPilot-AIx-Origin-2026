import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import app


class SectorObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_sector_summaries_do_not_look_past_cutoff(self):
        response = self.client.get("/api/sector-news")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["meta"]["provenance_status"], "unverified_summary")
        self.assertFalse(payload["meta"]["source_urls_archived"])
        self.assertTrue(all(item["date"] <= "2025-08-31" for item in payload["highlights"]))
        self.assertTrue(all("demo_heat_score" in item for item in payload["highlights"]))
        self.assertTrue(all("hot_score" not in item for item in payload["highlights"]))

    def test_industry_endpoint_filters_every_news_item(self):
        response = self.client.get("/api/sector-news", params={"industry": "医药"})
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(all(item["date"] <= "2025-08-31" for item in payload["data"]["news"]))
        self.assertIn("demo_heat_score", payload["data"])
        self.assertNotIn("hot_score", payload["data"])

    def test_price_extremes_and_volume_units_are_correct(self):
        code = "601318"
        snapshot = json.loads((ROOT / "data" / "snapshots" / f"{code}.json").read_text(encoding="utf-8"))
        daily = snapshot["daily"]
        expected_high = max(row["high"] for row in daily)
        expected_low = min(row["low"] for row in daily)
        expected_volume = round(sum(row.get("volume", 0) for row in daily) / len(daily) / 1_000_000, 2)

        response = self.client.get(f"/api/sector-observation/{code}")
        self.assertEqual(response.status_code, 200)
        metrics = response.json()["target_metrics"]
        self.assertEqual(metrics["high"], expected_high)
        self.assertEqual(metrics["low"], expected_low)
        self.assertEqual(metrics["avg_volume"], expected_volume)


if __name__ == "__main__":
    unittest.main()
