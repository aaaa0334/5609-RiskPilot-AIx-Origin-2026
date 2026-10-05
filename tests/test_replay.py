"""Run: py -3 -m unittest discover -s tests -p test_replay.py -v"""
import asyncio
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from replay import Account, Action, ReplayRequest, DrawRequest, STOCKS, decision_nodes, draw_stock, fees, load_data, replay, simulate, summary


class ReplayTests(unittest.TestCase):
    def test_weekly_calendar_and_cutoff(self):
        for code in STOCKS:
            r = replay(ReplayRequest(stock_code=code, decision_mode='weekly'))
            self.assertEqual(r['total_decisions'], 17)
            self.assertEqual(r['nodes'][0], '2025-04-30')
            self.assertEqual(r['nodes'][1], '2025-05-09')
            self.assertEqual(r['nodes'][-1], '2025-08-29')
            self.assertFalse(r['finished'])
            r2 = replay(ReplayRequest(stock_code=code, decision_mode='weekly', max_loss=90000, actions=[Action(target_value=50000)]))
            self.assertEqual(r2['cutoff'], '2025-05-09')
            self.assertEqual(r2['ledger'][0]['date'], '2025-05-06')
            self.assertTrue(all(p['date'] <= r2['cutoff'] for p in r2['prices']))
            self.assertTrue(all(d['published_date'] <= r2['cutoff'] for d in r2['documents']))

    def test_weekly_matches_monthly_if_only_holding(self):
        for code in STOCKS:
            monthly = replay(ReplayRequest(stock_code=code, actions=[Action(target_value=50000)]+[Action()]*3))
            weekly = replay(ReplayRequest(stock_code=code, decision_mode='weekly', actions=[Action(target_value=50000)]+[Action()]*16))
            self.assertEqual(monthly['account'], weekly['account'])
            self.assertEqual(monthly['benchmarks'], weekly['benchmarks'])
            self.assertTrue(weekly['finished'])

    def test_weekly_repeated_adjustments_identity_and_budget(self):
        actions = [Action(target_value=50000 if i % 2 == 0 else 0) for i in range(17)]
        for step in range(18):
            r = replay(ReplayRequest(stock_code='000876', decision_mode='weekly', actions=actions[:step]))
            a = r['account']
            self.assertEqual(r['finished'], step == 17 or r['stop'] is not None)
            if r['stop'] and r['stop']['status'] == 'cash':
                self.assertEqual(a['shares'], 0)
            self.assertGreaterEqual(a['cash'], 0)
            self.assertEqual(a['shares'] % 100, 0)
            self.assertAlmostEqual(a['realized']+a['unrealized']+a['dividends'], a['pnl'], places=2)
            self.assertAlmostEqual(a['budget_headroom'], a['equity']-98000, places=2)

    def test_reject_extra_weekly_decision_or_invalid_mode(self):
        with self.assertRaises(ValueError):
            replay(ReplayRequest(decision_mode='weekly', actions=[Action()]*18))
        with self.assertRaises(ValueError):
            ReplayRequest(decision_mode='daily')

    def test_all_stocks_are_real_and_isolated(self):
        for code in STOCKS:
            r = replay(ReplayRequest(stock_code=code))
            self.assertEqual(r['code'], code)
            self.assertEqual(r['name'], STOCKS[code]['name'])
            self.assertEqual(r['account']['shares'], 0)
            self.assertEqual(r['cutoff'], '2025-04-30')
            self.assertTrue(all(d['published_date'] <= r['cutoff'] for d in r['documents']))
            if code != '601318':
                self.assertTrue(all(code in d['url'] for d in r['documents']))
                self.assertNotIn('中国平安', json.dumps(r, ensure_ascii=False))

    def test_draw_without_replacement_and_cycle_boundary(self):
        drawn = []
        picks = []
        for _ in range(len(STOCKS)):
            r = draw_stock(DrawRequest(drawn=drawn))
            picks.append(r['stock']['code'])
            drawn = r['drawn']
        self.assertEqual(set(picks), set(STOCKS))
        self.assertEqual(r['remaining'], 0)
        r = draw_stock(DrawRequest(drawn=drawn))
        self.assertTrue(r['new_cycle'])
        self.assertNotEqual(r['stock']['code'], picks[-1])
        self.assertEqual(len(r['drawn']), 1)

    def test_draw_respects_industry_filter(self):
        for _ in range(20):
            r = draw_stock(DrawRequest(drawn=[], industry='银行'))
            self.assertEqual(r['stock']['industry'], '银行')
        with self.assertRaises(HTTPException):
            draw_stock(DrawRequest(drawn=[], industry='不存在的行业'))

    def test_unsupported_stock_rejected(self):
        with self.assertRaises(ValueError):
            replay(ReplayRequest(stock_code='999999'))

    def test_each_stock_uses_own_dividend(self):
        # Original three fixtures have one event each; expanded multi-event
        # samples are covered by test_stock_pool_expansion.
        for code in ('601318', '000876', '600010'):
            rows, nodes, manifest = load_data(code)
            r = replay(ReplayRequest(stock_code=code, actions=[Action(target_value=50000), Action(), Action(), Action()]))
            a = r['account']
            expected = round(a['shares'] * manifest['dividends'][0]['gross_per_share'], 2)
            self.assertEqual(a['dividends'], expected)
            events = [e for e in r['ledger'] if e['kind'] == '税前现金分红']
            self.assertEqual(events[0]['date'], manifest['dividends'][0]['pay_date'])
            self.assertAlmostEqual(a['pnl'], a['realized'] + a['unrealized'] + a['dividends'], places=2)

    def test_api_stock_list_draw_and_pdf(self):
        from fastapi.testclient import TestClient
        from main import app
        c = TestClient(app)
        self.assertEqual(len(c.get('/api/replay/stocks').json()['stocks']), len(STOCKS))
        self.assertEqual(c.post('/api/replay/draw', json={'drawn': []}).status_code, 200)
        for code in ('000876', '600010'):
            self.assertTrue(c.get(f'/api/replay/document/{code}/1').content.startswith(b'%PDF'))
        self.assertEqual(c.post('/api/replay', json={'stock_code': '999999'}).status_code, 400)

    def test_leaderboard_recomputes_score_on_server(self):
        from fastapi.testclient import TestClient
        from main import app
        c = TestClient(app)
        payload = {
            'name': '可信度测试', 'avatar': '🎮', 'faction': 'jin',
            'stock_code': '601318', 'decision_mode': 'monthly',
            'capital': 100000, 'max_loss': 3000,
            'actions': [{'target_value': None}] * 4,
            # 即使浏览器夹带伪造成绩，后端也必须忽略并自行重放。
            'pnl': 999999, 'pnl_pct': 999,
        }
        with patch('main.submit_score', return_value={'ok': True}) as mocked:
            response = c.post('/api/submit-score', json=payload)
        self.assertEqual(response.status_code, 200)
        submitted = mocked.call_args.kwargs
        self.assertEqual(submitted['pnl'], 0)
        self.assertEqual(submitted['pnl_pct'], 0)
        self.assertEqual(submitted['capital'], 100000)

    def test_leaderboard_rejects_unfinished_replay(self):
        from fastapi.testclient import TestClient
        from main import app
        c = TestClient(app)
        response = c.post('/api/submit-score', json={
            'name': '未完成测试', 'avatar': '🎮', 'faction': 'jin',
            'stock_code': '601318', 'decision_mode': 'monthly',
            'capital': 100000, 'max_loss': 3000, 'actions': [],
        })
        self.assertEqual(response.status_code, 400)

    def test_initial_is_cash_and_future_is_hidden(self):
        r = replay(ReplayRequest())
        self.assertEqual(r['cutoff'], '2025-04-30')
        self.assertEqual(r['account']['equity'], 100000)
        self.assertTrue(all(x['date'] <= r['cutoff'] for x in r['prices']))
        self.assertEqual(len(r['documents']), 1)
        self.assertNotIn('benchmarks', r)
        self.assertNotIn('2025-08-27', json.dumps(r['documents']))

    def test_future_prices_cannot_affect_current_result(self):
        rows, nodes, manifest = load_data()
        initial = replay(ReplayRequest())
        changed = [dict(r, close=9999) if r['date'] > nodes[0] else r for r in rows]
        with patch('replay.load_data', return_value=(changed, nodes, manifest)):
            self.assertEqual(initial, replay(ReplayRequest()))

    def test_all_cash_path(self):
        r = replay(ReplayRequest(actions=[Action()] * 4))
        self.assertTrue(r['finished'])
        self.assertEqual(r['account']['pnl'], 0)
        self.assertEqual(r['account']['fees'], 0)
        self.assertEqual(len(r['benchmarks']), 3)

    def test_next_open_execution_and_keep(self):
        req = ReplayRequest(actions=[Action(target_value=50000)])
        r = replay(req)
        rows, nodes, _ = load_data()
        nxt = next(x for x in rows if x['date'] > nodes[0])
        trade = r['ledger'][0]
        self.assertEqual(trade['date'], nxt['date'])
        self.assertEqual(trade['price'], round(nxt['open'] * 1.001, 2))
        r2 = replay(ReplayRequest(actions=[Action(target_value=50000), Action()]))
        self.assertEqual(r['account']['shares'], r2['account']['shares'])
        self.assertEqual(r['account']['fees'], r2['account']['fees'])

    def test_dividend_entitlement(self):
        r = replay(ReplayRequest(actions=[Action(target_value=50000), Action()]))
        self.assertEqual(r['account']['dividends'], r['account']['shares'] * 1.62)
        r2 = replay(ReplayRequest(actions=[Action(target_value=50000), Action(target_value=0)]))
        self.assertEqual(r2['account']['dividends'], 0)

    def test_cash_no_leverage_and_lots(self):
        r = replay(ReplayRequest(capital=1000, max_loss=100, actions=[Action(target_value=10000000)] * 4))
        self.assertGreaterEqual(r['account']['cash'], 0)
        self.assertEqual(r['account']['shares'] % 100, 0)
        self.assertEqual(r['account']['shares'], 0)

    def test_account_identity(self):
        r = replay(ReplayRequest(actions=[Action(target_value=50000), Action(), Action(target_value=20000), Action(target_value=0)]))
        a = r['account']
        self.assertAlmostEqual(a['cash'] + a['position_value'], a['equity'], places=2)
        self.assertAlmostEqual(a['realized'] + a['unrealized'] + a['dividends'], a['pnl'], places=2)
        self.assertEqual(a['shares'], 0)

    def test_budget_not_reset_and_daily_drawdown(self):
        a = Account(98000)
        a.history = [{'date': 'a', 'equity': 100000}, {'date': 'b', 'equity': 96000}, {'date': 'c', 'equity': 98000}]
        s = summary(a, 100000, 2000, 10)
        self.assertEqual(s['budget_headroom'], 0)
        self.assertEqual(s['breach_days'], 1)
        self.assertEqual(s['max_drawdown'], 4000)
        self.assertEqual(s['max_drawdown_pct'], 4)

    def test_preview_is_not_committed(self):
        r = replay(ReplayRequest(preview_target=50000))
        self.assertGreater(r['preview_shares'], 0)
        self.assertEqual(r['account']['shares'], 0)
        self.assertEqual(r['ledger'], [])
        self.assertGreater(r['scenarios'][2]['account_loss'], r['scenarios'][0]['account_loss'])

    def test_position_limit_is_advisory_and_audited(self):
        normal = replay(ReplayRequest(actions=[Action(target_value=30000)], faction='jin'))
        self.assertEqual(normal['position_limit_type'], 'advisory')
        self.assertEqual(normal['position_violation_count'], 0)

        exceeded = replay(ReplayRequest(actions=[Action(target_value=60000)], faction='jin'))
        self.assertGreater(exceeded['account']['shares'], normal['account']['shares'])
        self.assertEqual(exceeded['position_violation_count'], 1)
        self.assertTrue(exceeded['ledger'][0]['position_violation'])
        self.assertEqual(exceeded['ledger'][0]['suggested_position_limit_pct'], 30.0)

        fire_limit = replay(ReplayRequest(actions=[Action(target_value=40000)], faction='huo'))
        self.assertEqual(fire_limit['position_violation_count'], 0)

    def test_limit_reject(self):
        rows = [dict(date='2025-04-30', open=10, high=10, low=10, close=10, volume=100),
                dict(date='2025-05-06', open=11, high=11, low=11, close=11, volume=100)]
        a = simulate(rows, ['2025-04-30', '2025-05-06'], 100000, [Action(target_value=50000)])
        self.assertEqual(a.shares, 0)
        self.assertEqual(a.ledger[0]['kind'], '未成交')

    def test_invalid_inputs(self):
        for kwargs in [{'capital': float('nan')}, {'actions': [Action()] * 5}, {'max_loss': -1}]:
            with self.assertRaises(ValueError):
                ReplayRequest(**kwargs)
        with self.assertRaises(ValueError):
            replay(ReplayRequest(max_loss=200000))

    def test_hash_covers_final_payload(self):
        r = replay(ReplayRequest(actions=[Action()] * 4))
        digest = r.pop('integrity_hash')
        self.assertEqual(digest, hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest())

    def test_legacy_hash_and_short_history_regressions(self):
        from main import analyze, AnalyzeRequest
        from report import verify_hash
        from backtest import run_backtest
        r = asyncio.run(analyze(AnalyzeRequest(stock_code='601318', capital=100000, max_loss=2000, agent_mode='preset_demo')))
        self.assertTrue(r.success)
        self.assertTrue(verify_hash(r.report))
        self.assertEqual(run_backtest([], 10, 9, 12).lookback_days, 0)


if __name__ == '__main__':
    unittest.main()
