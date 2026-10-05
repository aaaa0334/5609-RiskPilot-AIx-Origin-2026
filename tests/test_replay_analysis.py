import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from replay import Account, Action, ReplayRequest, fees, load_data, replay
from replay_analysis import analyze_at


class HistoricalAnalysisTests(unittest.TestCase):
    def test_future_mutation_cannot_change_analysis(self):
        rows,nodes,manifest=load_data()
        for actions in ([],[Action()]):
            req=ReplayRequest(actions=actions)
            baseline=replay(req)
            mutated=[dict(r,open=9999,close=9999,high=10000,low=9000,volume=1) if r['date']>baseline['cutoff'] else r for r in rows]
            with patch('replay.load_data',return_value=(mutated,nodes,manifest)):
                self.assertEqual(baseline['analysis'],replay(req)['analysis'])

    def test_window_calculation_and_budget(self):
        for code in ('601318','000876','600010'):
            r=replay(ReplayRequest(stock_code=code))
            a=r['analysis']
            rows,_,_=load_data(code)
            past=[x for x in rows if x['date']<=r['cutoff']]
            self.assertEqual(a['ma5'],round(sum(x['close'] for x in past[-5:])/5,2))
            self.assertEqual(a['downside_reference'],min(x['low'] for x in past[-20:]))
            self.assertEqual(a['reference_shares']%100,0)
            self.assertLessEqual(a['reference_value'],r['account']['equity']*.30)
            if a['reference_shares']:
                self.assertLessEqual(a['scenario_account_loss'],r['max_loss'])

    def test_insufficient_data_and_cutoff_filter(self):
        rows,_,_=load_data()
        a=analyze_at(rows,rows[3]['date'],Account(100000),100000,2000,fees)
        self.assertFalse(a['ready'])
        self.assertEqual(a['observations'],4)

    def test_analysis_does_not_trade_or_depend_on_preview(self):
        a=replay(ReplayRequest())
        b=replay(ReplayRequest(preview_target=90000))
        self.assertEqual(a['analysis'],b['analysis'])
        self.assertEqual(b['account']['shares'],0)
        self.assertEqual(b['ledger'],[])

    def test_exited_account_has_no_position_reference(self):
        r=replay(ReplayRequest(max_loss=1,actions=[Action(target_value=100000)]))
        self.assertEqual(r['analysis']['reference_shares'],0)
