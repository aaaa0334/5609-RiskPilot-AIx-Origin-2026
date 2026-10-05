"""Deterministic educational analysis; never uses rows after the decision cutoff."""


def analyze_at(rows, cutoff, account, capital, budget, fee_fn):
    visible = [r for r in rows if r['date'] <= cutoff]
    result = dict(cutoff=cutoff, engine='历史规则测算（非LLM）',
                  observations=len(visible), ready=False)
    if len(visible) < 21:
        return dict(result, message='不足21个交易日，暂不生成趋势和仓位测算。')
    recent = visible[-20:]
    price = visible[-1]['close']
    ma5 = sum(r['close'] for r in visible[-5:]) / 5
    ma20 = sum(r['close'] for r in recent) / 20
    change = (price / visible[-21]['close'] - 1) * 100
    low, high = min(r['low'] for r in recent), max(r['high'] for r in recent)
    trend = '近期偏强' if price > ma20 and ma5 > ma20 * 1.01 else '近期偏弱' if price < ma20 and ma5 < ma20 * .99 else '近期震荡'
    equity = account.cash + account.shares * price

    def scenario(qty, exit_reference):
        delta = qty - account.shares
        fill = round(price * (.999 if delta < 0 else 1.001), 2)
        cash = account.cash - delta * fill - fee_fn(abs(delta), fill, delta < 0)
        exit_price = round(exit_reference * .999, 2)
        final = cash + qty * exit_price - fee_fn(qty, exit_price, True)
        return cash, round(capital - final, 2), round(final - equity, 2)

    # This fixed demo cap is not optimized against future performance.
    cap = max(0, int(equity * .30 / price / 100) * 100)
    qty = 0
    if low < price < high and not account.stop:
        for candidate in range(cap, 0, -100):
            cash, loss, _ = scenario(candidate, low)
            if cash >= 0 and loss <= budget:
                qty = candidate
                break
    _, loss, downside = scenario(qty, low)
    _, _, upside = scenario(qty, high)
    ratio = round(upside / -downside, 2) if qty and downside < 0 and upside > 0 else None
    return dict(result, ready=True, window_start=recent[0]['date'], price=price,
                ma5=round(ma5, 2), ma20=round(ma20, 2), change20=round(change, 2), trend=trend,
                reference_shares=qty, reference_value=round(qty*price, 2), delta_shares=qty-account.shares,
                downside_reference=low, upside_reference=high, scenario_account_loss=loss,
                incremental_downside=round(max(0, -downside), 2), incremental_upside=round(max(0, upside), 2), ratio=ratio,
                message=('本轮已结束，不再生成可执行的仓位参考。' if account.stop else
                         '当前预算或历史价格区间不支持非零参考仓位，可选择现金观望。' if not qty else
                         '这是风险预算下的模拟总持仓参考，不是追加买入数量，也不是买入信号。'),
                rules=['只使用截至本节点的行情；MA5/MA20为收盘均值，20日涨跌比较当前与20个交易日前收盘。',
                       '上下参考价取近20个交易日最低价、最高价，并非预测目标；不复权价格可能受除息影响。',
                       '演示参考仓位按当前资产30%测算并按100股取整；这是可主动突破的建议值，并非强制上限、收益优化策略或行业标准。',
                       '仓位按当前价假设调整，再假设下跌至下参考价全部卖出；包括调整及卖出费用、滑点，净亏损仍以初始本金为基准。',
                       '情景收益风险比以当前资产为起点；不代表胜率或期望收益。参考价不触发自动止盈止损，实际仅执行账户预算退出规则。',
                       '未调用AI或最新报告；公告仅展示当时已公开的已存文件，不自动推断基本面或新闻情绪。'])
