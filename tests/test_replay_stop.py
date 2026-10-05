"""Budget-triggered exit: daily close detection, next tradable open fill."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from replay import Action, ReplayRequest, replay, simulate


class StopTests(unittest.TestCase):
    def rows(self):
        return [dict(date=f'2025-05-{day:02}', open=o, close=c, low=min(o,c)-.1,
                     high=max(o,c)+.1, volume=1000)
                for day,o,c in [(6,10,10),(7,10,9),(8,9,9),(9,9,10),(12,10,10)]]

    def test_next_open_and_no_reentry(self):
        rows = self.rows()
        a = simulate(rows, [r['date'] for r in rows], 10000,
                     [Action(target_value=5000)]*4, [], 100)
        self.assertEqual(a.stop['trigger_date'], '2025-05-07')
        self.assertEqual(a.stop['liquidation_date'], '2025-05-08')
        self.assertEqual(a.shares, 0)
        self.assertEqual(len(a.ledger), 2)
        self.assertEqual(a.history[-1]['date'], '2025-05-08')
        self.assertEqual(a.ledger[-1]['kind'], '强制清仓')

    def test_equal_budget_does_not_trigger(self):
        rows = self.rows()[:2]
        nodes = [r['date'] for r in rows]
        a = simulate(rows,nodes,10000,[Action(target_value=5000)],[])
        loss = round(10000-a.history[-1]['equity'],2)
        self.assertIsNone(simulate(rows,nodes,10000,[Action(target_value=5000)],[],loss).stop)
        self.assertEqual(simulate(rows,nodes,10000,[Action(target_value=5000)],[],loss-.01).stop['status'],'pending')

    def test_blocked_exit_retries_beyond_node(self):
        rows=self.rows()
        rows[2]['volume']=0
        a=simulate(rows,[rows[0]['date'],rows[1]['date']],10000,[Action(target_value=5000)],[],100)
        self.assertEqual(a.ledger[1]['kind'],'强制清仓未成交')
        self.assertEqual(a.stop['liquidation_date'],'2025-05-09')
        self.assertEqual(a.shares,0)

    def test_no_future_fill_when_data_ends(self):
        rows=self.rows()[:2]
        a=simulate(rows,[r['date'] for r in rows],10000,[Action(target_value=5000)],[],100)
        self.assertEqual(a.stop['status'],'pending')
        self.assertGreater(a.shares,0)
        self.assertIsNone(a.stop['liquidation_date'])

    def test_real_data_exit_hides_future_and_ignores_later_actions(self):
        r=replay(ReplayRequest(max_loss=1, actions=[Action(target_value=100000)]))
        self.assertTrue(r['finished'])
        self.assertEqual(r['stop']['status'],'cash')
        self.assertEqual(r['account']['shares'],0)
        self.assertLess(r['cutoff'],'2025-08-29')
        self.assertTrue(all(p['date']<=r['cutoff'] for p in r['prices']))
        later=replay(ReplayRequest(max_loss=1, actions=[Action(target_value=100000)]*4))
        self.assertEqual(r['account'],later['account'])
        self.assertEqual(r['benchmarks'],later['benchmarks'])


if __name__=='__main__':
    unittest.main()
