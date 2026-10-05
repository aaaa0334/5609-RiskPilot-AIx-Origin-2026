"""Offline expansion contract: same 100 genuine samples in both views."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from data_loader import get_available_stocks, load_stock_snapshot
from replay import STOCKS, Action, ReplayRequest, load_data, replay, stock_options
from fastapi.testclient import TestClient
from main import app


class StockPoolExpansionTests(unittest.TestCase):
    def test_same_hundred_real_samples(self):
        analysis = get_available_stocks()
        self.assertEqual(len(analysis), 100)
        self.assertEqual({s['code'] for s in analysis}, {s['code'] for s in stock_options()})
        self.assertTrue(all(not s['is_synthetic'] for s in analysis))
        for code in STOCKS:
            rows, _, _ = load_data(code)
            self.assertEqual(len(rows), 161)
            self.assertEqual(rows, load_stock_snapshot(code)['daily'])

    def test_each_analysis_succeeds_without_llm(self):
        client = TestClient(app)
        for code in STOCKS:
            with self.subTest(code=code):
                response = client.post('/api/analyze', json=dict(
                    stock_code=code, capital=100000, max_loss=3000, agent_mode='preset_demo'))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['success'], response.json().get('error'))

    def test_hundred_weekly_runs_and_point_in_time_isolation(self):
        for code in STOCKS:
            with self.subTest(code=code):
                rows, nodes, manifest = load_data(code)
                before = replay(ReplayRequest(stock_code=code))
                altered = [dict(r, close=r['close']*2) if r['date'] > nodes[0] else r for r in rows]
                with patch('replay.load_data', return_value=(altered, nodes, manifest)):
                    self.assertEqual(before, replay(ReplayRequest(stock_code=code)))
                result = replay(ReplayRequest(stock_code=code, decision_mode='weekly', max_loss=90000,
                    actions=[Action(target_value=30000)] + [Action()] * 16))
                self.assertTrue(result['finished'])
                self.assertEqual(result['cutoff'], '2025-08-29')
                self.assertGreaterEqual(result['account']['cash'], 0)
                shares = result['ledger'][0].get('shares_after', result['account']['shares'])
                events = [d for d in manifest['dividends'] if nodes[0] < d['record_date'] <= nodes[-1]]
                expected = sum(round(shares*d['gross_per_share'], 2) for d in events)
                self.assertAlmostEqual(result['account']['dividends'], expected, places=2)


if __name__ == '__main__':
    unittest.main()
