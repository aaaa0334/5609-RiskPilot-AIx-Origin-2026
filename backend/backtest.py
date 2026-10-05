"""
RiskPilot 历史支撑位有效性检验模块
==================================
用历史数据检验当前止损/目标价格水平在过去的被触及频率。

注意：本模块不是严格意义上的策略回测（Strategy Backtest）。
严格回测需要对历史每一天用当时已有的数据计算止损位，
再模拟后续走势（避免前视偏差 Look-ahead Bias）。
本模块做的是"静态价格水平检验"：统计当前设定的止损价和目标价
在历史上被触及的频率，用于评估该价位的合理性。

参考：Lopez de Prado,《Advances in Financial Machine Learning》(2018)
中关于回测方法论偏差的论述。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class BacktestResult:
    """历史价格水平检验结果"""
    lookback_days: int           # 检验天数
    stop_hit_count: int          # 止损价被触及次数
    target_hit_count: int        # 目标价被触及次数
    stop_hit_rate: float         # 止损价被触及频率（%）
    target_hit_rate: float       # 目标价被触及频率（%）
    max_drawdown: float          # 期间最大回撤（元）
    max_drawdown_pct: float      # 最大回撤百分比
    avg_daily_range: float       # 平均日振幅（%）
    volatility_level: str        # 波动率评价
    touch_frequency_note: str    # 触及频率说明（非胜率）
    conclusion: str              # 一句话结论


def run_backtest(
    daily_data: list[dict],
    current_price: float,
    stop_price: float,
    target_price: float,
    lookback: int = 120,
) -> BacktestResult:
    """
    简易回测：统计过去lookback天内，止损价和目标价被触及的频率。

    逻辑：
    - 止损触发：最低价 <= stop_price（说明如果在当前价买入，期间曾跌到止损位）
    - 目标触发：最高价 >= target_price（说明期间曾涨到目标位）
    - 最大回撤：期间最高价到之后最低价的最大跌幅
    """
    if not daily_data or len(daily_data) < 10:
        return BacktestResult(
            lookback_days=0, stop_hit_count=0, target_hit_count=0,
            stop_hit_rate=0, target_hit_rate=0, max_drawdown=0,
            max_drawdown_pct=0, avg_daily_range=0,
            volatility_level="数据不足", touch_frequency_note="资料不足，不能统计历史触及频率；不是策略胜率。",
            conclusion="历史数据不足，无法回测",
        )

    data = daily_data[-lookback:] if len(daily_data) > lookback else daily_data
    n = len(data)

    # 统计止损/目标触发
    stop_hits = sum(1 for d in data if (d.get("low", 0) or 0) <= stop_price)
    target_hits = sum(1 for d in data if (d.get("high", 0) or 0) >= target_price)

    # 最大回撤（期间内最高价到之后最低价的最大跌幅）
    peak = data[0].get("high", current_price)
    max_dd = 0
    max_dd_pct = 0
    for d in data:
        high = d.get("high", 0) or 0
        low = d.get("low", 0) or 0
        if high > peak:
            peak = high
        dd = peak - low
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    # 平均日振幅
    ranges = []
    for d in data:
        high = d.get("high", 0) or 0
        low = d.get("low", 0) or 0
        if high > 0 and low > 0:
            ranges.append((high - low) / low * 100)
    avg_range = sum(ranges) / len(ranges) if ranges else 0

    # 波动率评价
    if avg_range >= 4:
        vol_level = "高波动"
    elif avg_range >= 2.5:
        vol_level = "中高波动"
    elif avg_range >= 1.5:
        vol_level = "中等波动"
    else:
        vol_level = "低波动"

    # 触及频率说明（非胜率！仅描述两个价位被触及的相对频率）
    total_hits = target_hits + stop_hits
    if total_hits > 0:
        touch_note = (
            f"历史上目标价被触及{target_hits}次、止损价被触及{stop_hits}次。"
            f"注意：这不是策略胜率，因为同一天可能同时触及两个价位，"
            f"且先触及哪个决定盈亏，本检验不模拟出场顺序。"
        )
    else:
        touch_note = "历史上两个价位均未被触及。"

    # 结论
    stop_rate = (stop_hits / n * 100) if n > 0 else 0
    target_rate = (target_hits / n * 100) if n > 0 else 0

    if stop_rate > 30:
        conclusion = (
            f"过去{n}个交易日里，止损价被触及{stop_hits}次（{stop_rate:.0f}%的交易日），"
            f"说明当前止损位较近，容易被正常震荡洗出。"
            f"建议适当放宽止损，或等待更明确的入场点（如回调至支撑位附近）。"
        )
    elif target_rate > 40:
        conclusion = (
            f"过去{n}个交易日里，目标价被触及{target_hits}次（{target_rate:.0f}%的交易日），"
            f"说明目标位较近，盈利空间有限。"
            f"可考虑上移目标价，或寻找波动更大的标的。"
        )
    elif stop_rate < 10 and target_rate > 20:
        conclusion = (
            f"过去{n}个交易日里，止损价仅被触及{stop_hits}次（{stop_rate:.0f}%），"
            f"目标价被触及{target_hits}次（{target_rate:.0f}%），"
            f"在当前观察窗口内触及次数较少；仅描述历史价格位置，不代表未来风险较低。"
        )
    else:
        conclusion = (
            f"过去{n}个交易日里，止损价被触及{stop_hits}次（{stop_rate:.0f}%），"
            f"目标价被触及{target_hits}次（{target_rate:.0f}%）。"
            f"需结合基本面和资金面综合判断是否值得参与。"
        )

    return BacktestResult(
        lookback_days=n,
        stop_hit_count=stop_hits,
        target_hit_count=target_hits,
        stop_hit_rate=round(stop_rate, 1),
        target_hit_rate=round(target_rate, 1),
        max_drawdown=round(max_dd, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        avg_daily_range=round(avg_range, 2),
        volatility_level=vol_level,
        touch_frequency_note=touch_note,
        conclusion=conclusion,
    )


def generate_trading_plan(
    current_price: float,
    stop_price: float,
    target_price: float,
    shares: int,
    capital: float,
    max_loss: float,
    standard_loss: float,
    risk_reward_ratio: float,
    backtest: Optional[BacktestResult] = None,
    ma20: float = 0,
) -> dict:
    """
    生成完整的操作计划（面向股市小白）。
    包括：入场时机、怎么买、怎么卖、止损怎么移动、组合建议、注意事项。

    理论依据：
    - 分批买入：降低择时风险，经典资金管理方法
    - 50%回撤位加仓：斐波那契回撤理论（Fibonacci Retracement），50%是标准回撤位
    - 移动止损：锁定利润，经典趋势跟踪方法
    - 分散化：Markowitz现代投资组合理论(1952)，单票仓位不宜过高
    """
    position_value = shares * current_price
    position_ratio = (position_value / capital * 100) if capital > 0 else 0
    stop_distance_pct = ((current_price - stop_price) / current_price * 100) if current_price > 0 else 0

    # 入场时机判断（理论依据：支撑位买入可改善风险收益比）
    if stop_distance_pct <= 5:
        entry_advice = (
            f"当前价距止损位仅{stop_distance_pct:.1f}%，止损距离较近，"
            f"可考虑现价附近分批建仓。若看好该标的，不必过度等待回调。"
        )
    elif stop_distance_pct >= 10:
        # 50%回撤位（斐波那契标准回撤位）
        pullback_price = stop_price + (current_price - stop_price) * 0.5
        entry_advice = (
            f"当前价距止损位{stop_distance_pct:.1f}%，距离较远。"
            f"建议等待回调至{pullback_price:.2f}元附近（当前价与止损位的50%回撤位，"
            f"经典斐波那契回撤位）再入场，可显著改善风险收益比。"
        )
    else:
        pullback_price = stop_price + (current_price - stop_price) * 0.5
        entry_advice = (
            f"当前价距止损位{stop_distance_pct:.1f}%。"
            f"可现价建底仓，若回调至{pullback_price:.2f}元（50%回撤位）可加仓。"
        )

    # 分批买入建议
    if position_ratio <= 20:
        buy_plan = f"仓位较轻（{position_ratio:.0f}%），可一次性买入{shares}股。"
    elif position_ratio <= 40:
        first_batch = shares // 2
        second_batch = shares - first_batch
        # 加仓价用50%回撤位（斐波那契理论）
        add_price = stop_price + (current_price - stop_price) * 0.5
        buy_plan = (
            f"建议分两批买入：第一批{first_batch}股（约{first_batch * current_price:.0f}元），"
            f"若回调至{add_price:.2f}元附近（50%回撤位）再加{second_batch}股。"
            f"避免一次性买在高点。"
        )
    else:
        first_batch = int(shares * 0.4)
        second_batch = shares - first_batch
        add_price = stop_price + (current_price - stop_price) * 0.5
        buy_plan = (
            f"仓位较重（{position_ratio:.0f}%），强烈建议分两批："
            f"第一批{first_batch}股试探，确认走势后再加{second_batch}股。"
            f"单只股票仓位不宜超过本金的50%。"
        )

    # 卖出策略
    sell_plan = (
        f"到达目标价{target_price:.2f}元时，建议先卖出一半（{shares // 2}股）锁定利润，"
        f"剩余一半将止损上移至成本价{current_price:.2f}元（保本止损），"
        f"让利润奔跑。若跌破{stop_price:.2f}元则全部卖出止损。"
    )

    # 止损移动规则
    stop_move_plan = (
        f"初始止损：{stop_price:.2f}元（亏损约{standard_loss:.0f}元）。"
        f"当股价涨到{current_price + (target_price - current_price) * 0.5:.2f}元时，"
        f"将止损上移至成本价{current_price:.2f}元（保本）。"
        f"到达目标价后，止损上移至{current_price + (target_price - current_price) * 0.3:.2f}元（锁定部分利润）。"
    )

    # 组合分散化建议（理论依据：Markowitz现代投资组合理论）
    portfolio_advice = (
        f"当前单票仓位{position_ratio:.1f}%。"
        f"根据现代投资组合理论（Markowitz, 1952），建议配置3-5只低相关性股票以分散风险。"
        f"避免将资金集中于同一行业（如全部买入银行股），行业集中会降低分散化效果。"
    )

    # 风险提示
    if backtest and backtest.stop_hit_rate > 25:
        risk_note = (
            f"注意：历史检验显示过去{backtest.lookback_days}个交易日里止损价被触及{backtest.stop_hit_count}次"
            f"（{backtest.stop_hit_rate:.0f}%），该止损位容易被触及，建议严格执行纪律。"
        )
    elif risk_reward_ratio < 1:
        risk_note = (
            f"注意：当前风险收益比仅1:{risk_reward_ratio:.2f}（低于1:1），"
            f"意味着每承担1元风险只能获得{risk_reward_ratio:.2f}元潜在收益，长期期望值为负，需谨慎参与。"
        )
    else:
        risk_note = "风险收益结构尚可，但仍需严格执行止损纪律。"

    return {
        "entry_advice": entry_advice,
        "buy_plan": buy_plan,
        "sell_plan": sell_plan,
        "stop_move_plan": stop_move_plan,
        "portfolio_advice": portfolio_advice,
        "risk_note": risk_note,
        "position_summary": (
            f"总投入约{position_value:.0f}元（占本金{position_ratio:.1f}%），"
            f"剩余可用资金约{(capital - position_value):.0f}元。"
        ),
    }
