"""
RiskPilot 确定性风险引擎
========================
本模块是整个系统的核心：所有仓位、损失、费用、压力测试均由确定性程序计算，
不交给大模型自由生成。风险引擎拥有否决权——即使所有 AI Agent 都看多，
只要标准情景预计损失超过用户设置的账户最大损失，就必须否决方案。

设计原则：
1. 纯函数，无外部依赖，可独立测试
2. 所有计算保留中间过程，便于审计和页面展示
3. A 股规则适配：100 股申报单位、T+1 风险情景、涨跌停、佣金最低 5 元等
"""

from dataclasses import dataclass, field
from typing import Optional
import math


# ============================================================
# 数据结构
# ============================================================

@dataclass
class UserInput:
    """用户输入"""
    stock_code: str          # 股票代码，如 "600519"
    stock_name: str          # 股票名称
    capital: float           # 模拟账户本金（元）
    max_loss: float          # 账户最大可承受损失（元）
    current_price: float     # 当前参考价格（元）
    atr_14: float            # 14 日 ATR（元）
    key_support: float       # 关键支撑位/风险失效位置（元），由技术面 Agent 给出
    board: str = "main"      # 板块：main=沪深主板，limit=10%


@dataclass
class FeeConfig:
    """A 股交易费用配置（2026 年现行标准）"""
    commission_rate: float = 0.00025    # 佣金费率，万 2.5（买卖双向）
    commission_min: float = 5.0         # 佣金最低 5 元
    stamp_tax_rate: float = 0.0005      # 印花税，卖出时 0.05%（2023-08-28 起）
    transfer_fee_rate: float = 0.00001  # 过户费，0.001%（买卖双向）
    slippage_rate: float = 0.001        # 保守滑点，0.1%
    max_single_position_ratio: float = 0.3  # MVP 默认单只股票仓位上限 30%


@dataclass
class PositionResult:
    """仓位计算结果"""
    # 输入回显
    capital: float
    max_loss: float
    max_loss_rate: float        # 最大损失率 = max_loss / capital
    current_price: float
    atr_14: float
    key_support: float

    # 风险保护距离
    atr_risk_multiplier: float  # ATR 风险倍数
    volatility_distance: float  # 波动保护距离 = ATR × 倍数
    structure_distance: float   # 结构保护距离 = 当前价 - 关键支撑
    final_stop_distance: float  # 最终保护距离 = max(波动, 结构)
    stop_loss_price: float      # 止损价 = 当前价 - 最终保护距离

    # 每股风险
    risk_per_share: float       # 每股计划风险 = 最终保护距离

    # 仓位反推
    theoretical_shares: float   # 理论允许股数 = max_loss / risk_per_share
    lot_rounded_shares: int     # 按 100 股向下取整后
    capital_limit_shares: int   # 本金限制股数 = capital / 当前价(含滑点)，向下取整到手
    position_limit_shares: int  # 单票仓位上限股数
    final_shares: int           # 最终模拟股数 = min(三者)
    final_position_value: float # 最终模拟市值
    final_position_ratio: float # 最终仓位占比

    # 费用
    buy_commission: float
    buy_transfer_fee: float
    buy_total_fee: float
    sell_commission: float
    sell_stamp_tax: float
    sell_transfer_fee: float
    sell_total_fee: float
    total_fees: float

    # 标准情景
    standard_loss: float        # 标准情景预计损失 = 股数 × 每股风险 + 总费用
    standard_loss_rate: float   # 标准情景损失率
    within_budget: bool         # 是否在用户损失预算内
    vetoed: bool                # 是否被风险引擎否决
    veto_reason: str            # 否决原因

    # 高风险提示
    high_risk_warning: bool     # 最大损失率超过 5%


@dataclass
class StressTestResult:
    """单种压力测试结果"""
    scenario: str               # 情景名称
    description: str            # 情景描述
    assumed_exit_price: float   # 假设卖出价
    actual_loss: float          # 实际损失 = (买入成本 - 卖出收入) + 费用
    actual_loss_rate: float     # 相对本金损失率
    exceeds_budget: bool        # 是否超过用户损失预算
    note: str                   # 备注


@dataclass
class RiskEngineOutput:
    """风险引擎完整输出"""
    input: UserInput
    position: PositionResult
    stress_tests: list  # list[StressTestResult]
    timestamp: str
    engine_version: str = "1.0.0"


# ============================================================
# 核心计算函数
# ============================================================

def validate_input(user_input: UserInput) -> list[str]:
    """输入校验，返回错误列表（空列表表示通过）"""
    errors = []
    if user_input.capital <= 0:
        errors.append("本金必须大于 0")
    if user_input.max_loss <= 0:
        errors.append("最大可承受损失必须大于 0")
    if user_input.max_loss > user_input.capital:
        errors.append("最大可承受损失不得超过本金")
    if user_input.current_price <= 0:
        errors.append("当前价格必须大于 0")
    if user_input.atr_14 <= 0:
        errors.append("ATR 必须大于 0")
    if user_input.key_support <= 0:
        errors.append("关键支撑位必须大于 0")
    if user_input.key_support > user_input.current_price:
        errors.append("关键支撑位不能高于当前价格")
    return errors


def calculate_atr_risk_multiplier(atr_14: float, current_price: float) -> float:
    """
    根据 ATR 占价格比例确定风险倍数。
    波动越大，倍数越小（避免止损过宽）；波动越小，倍数适当放大。
    这是一个保守的经验映射，可通过回测优化。
    """
    atr_ratio = atr_14 / current_price
    if atr_ratio >= 0.04:      # 高波动（日波动 >= 4%）
        return 1.0
    elif atr_ratio >= 0.025:   # 中高波动
        return 1.5
    elif atr_ratio >= 0.015:   # 中等波动
        return 2.0
    else:                      # 低波动
        return 2.5


def round_down_to_lot(shares: float) -> int:
    """A 股最小交易单位 100 股，向下取整"""
    return int(math.floor(shares / 100.0)) * 100


def calc_buy_fees(shares: int, price: float, config: FeeConfig) -> tuple[float, float, float]:
    """
    计算买入费用
    返回: (佣金, 过户费, 总费用)
    """
    amount = shares * price
    commission = max(amount * config.commission_rate, config.commission_min)
    transfer_fee = amount * config.transfer_fee_rate
    total = commission + transfer_fee
    return commission, transfer_fee, total


def calc_sell_fees(shares: int, price: float, config: FeeConfig) -> tuple[float, float, float, float]:
    """
    计算卖出费用
    返回: (佣金, 印花税, 过户费, 总费用)
    """
    amount = shares * price
    commission = max(amount * config.commission_rate, config.commission_min)
    stamp_tax = amount * config.stamp_tax_rate
    transfer_fee = amount * config.transfer_fee_rate
    total = commission + stamp_tax + transfer_fee
    return commission, stamp_tax, transfer_fee, total


def calculate_position(
    user_input: UserInput,
    config: Optional[FeeConfig] = None
) -> PositionResult:
    """
    核心：根据用户损失预算反推模拟仓位
    """
    if config is None:
        config = FeeConfig()

    cap = user_input.capital
    max_loss = user_input.max_loss
    price = user_input.current_price
    atr = user_input.atr_14
    support = user_input.key_support

    # 1. 最大损失率
    max_loss_rate = max_loss / cap
    high_risk = max_loss_rate > 0.05

    # 2. 风险保护距离
    atr_mult = calculate_atr_risk_multiplier(atr, price)
    vol_distance = atr * atr_mult
    struct_distance = price - support
    final_distance = max(vol_distance, struct_distance)
    stop_price = price - final_distance

    # 3. 每股价格风险（不含费用和滑点）
    risk_per_share = final_distance

    # 4. 本金限制（考虑滑点后的实际买入成本）
    effective_buy_price = price * (1 + config.slippage_rate)
    capital_limit = int(cap / effective_buy_price)
    capital_limit = round_down_to_lot(capital_limit)

    # 5. 单票仓位上限
    position_limit_value = cap * config.max_single_position_ratio
    position_limit = int(position_limit_value / effective_buy_price)
    position_limit = round_down_to_lot(position_limit)

    # 6. 理论允许股数（不含费用）
    theoretical = max_loss / risk_per_share if risk_per_share > 0 else 0

    # 7. 费用感知的仓位反推：从理论股数开始，逐档（100股）下调，
    #    直到标准情景损失（含费用和滑点）不超过用户最大损失。
    #    这是关键修正：交易费用和滑点必须计入损失预算。
    def calc_standard_loss_for_shares(s: int) -> float:
        if s <= 0:
            return 0.0
        bc, bt, btot = calc_buy_fees(s, effective_buy_price, config)
        sc, sst, stt, stot = calc_sell_fees(s, stop_price, config)
        buy_c = s * effective_buy_price + btot
        sell_r = s * stop_price - stot
        return buy_c - sell_r

    lot_shares = round_down_to_lot(theoretical)
    fee_adjusted_shares = min(lot_shares, capital_limit, position_limit)

    # 逐档下调，直到损失在预算内（最多迭代到 0）
    while fee_adjusted_shares >= 100:
        loss = calc_standard_loss_for_shares(fee_adjusted_shares)
        if loss <= max_loss:
            break
        fee_adjusted_shares -= 100

    final_shares = fee_adjusted_shares

    # 8. 费用计算（买入按含滑点价，卖出按止损价）
    buy_comm, buy_trans, buy_total = calc_buy_fees(final_shares, effective_buy_price, config)
    sell_comm, sell_stamp, sell_trans, sell_total = calc_sell_fees(final_shares, stop_price, config)
    total_fees = buy_total + sell_total

    # 9. 标准情景损失
    # 买入成本 = 股数 × 含滑点买入价 + 买入费用
    # 卖出收入 = 股数 × 止损价 - 卖出费用
    # 损失 = 买入成本 - 卖出收入
    buy_cost = final_shares * effective_buy_price + buy_total
    sell_revenue = final_shares * stop_price - sell_total
    standard_loss = buy_cost - sell_revenue
    standard_loss_rate = standard_loss / cap if cap > 0 else 0

    # 11. 判断
    within_budget = standard_loss <= max_loss
    vetoed = not within_budget or final_shares < 100

    veto_reason = ""
    if final_shares < 100:
        veto_reason = (
            f"当前本金与账户损失预算不足以支持符合约束的最小模拟仓位"
            f"（理论允许 {theoretical:.1f} 股，不足 100 股一手）。"
            f"系统不得为了给出结果而突破用户的风险上限。"
        )
    elif not within_budget:
        veto_reason = (
            f"标准情景预计损失 {standard_loss:.2f} 元超过用户设置的"
            f"账户最大可承受损失 {max_loss:.2f} 元，风险引擎行使否决权。"
        )

    position_value = final_shares * price
    position_ratio = position_value / cap if cap > 0 else 0

    return PositionResult(
        capital=cap,
        max_loss=max_loss,
        max_loss_rate=max_loss_rate,
        current_price=price,
        atr_14=atr,
        key_support=support,
        atr_risk_multiplier=atr_mult,
        volatility_distance=vol_distance,
        structure_distance=struct_distance,
        final_stop_distance=final_distance,
        stop_loss_price=stop_price,
        risk_per_share=risk_per_share,
        theoretical_shares=theoretical,
        lot_rounded_shares=lot_shares,
        capital_limit_shares=capital_limit,
        position_limit_shares=position_limit,
        final_shares=final_shares,
        final_position_value=position_value,
        final_position_ratio=position_ratio,
        buy_commission=buy_comm,
        buy_transfer_fee=buy_trans,
        buy_total_fee=buy_total,
        sell_commission=sell_comm,
        sell_stamp_tax=sell_stamp,
        sell_transfer_fee=sell_trans,
        sell_total_fee=sell_total,
        total_fees=total_fees,
        standard_loss=standard_loss,
        standard_loss_rate=standard_loss_rate,
        within_budget=within_budget,
        vetoed=vetoed,
        veto_reason=veto_reason,
        high_risk_warning=high_risk,
    )


def run_stress_tests(
    user_input: UserInput,
    position: PositionResult,
    config: Optional[FeeConfig] = None
) -> list[StressTestResult]:
    """
    三种压力测试：
    1. 正常触发止损：价格到达止损价后卖出
    2. 次日不利低开：用次日低开 2% 模拟 T+1 下无法当日退出的风险
    3. 止损触发后流动性枯竭：止损单因跌停无法成交，随后在止损价基础上继续下跌 8%
    """
    if config is None:
        config = FeeConfig()

    results = []
    shares = position.final_shares
    cap = user_input.capital
    max_loss = user_input.max_loss
    buy_price = user_input.current_price * (1 + config.slippage_rate)
    buy_cost = shares * buy_price + position.buy_total_fee
    limit_down_rate = 0.10 if user_input.board == "main" else 0.20

    if shares < 100:
        # 仓位被否决时，压力测试无意义
        return [
            StressTestResult(
                scenario="仓位不足",
                description="模拟仓位不足 100 股，无法进行压力测试",
                assumed_exit_price=0,
                actual_loss=0,
                actual_loss_rate=0,
                exceeds_budget=False,
                note="风险引擎已否决该方案"
            )
        ]

    # --- 情景 1：正常触发止损 ---
    exit_price_1 = position.stop_loss_price
    _, _, _, sell_fee_1 = calc_sell_fees(shares, exit_price_1, config)
    sell_rev_1 = shares * exit_price_1 - sell_fee_1
    loss_1 = buy_cost - sell_rev_1
    results.append(StressTestResult(
        scenario="情景一：正常触发止损",
        description=f"价格到达止损价 {exit_price_1:.2f} 元后正常卖出",
        assumed_exit_price=exit_price_1,
        actual_loss=loss_1,
        actual_loss_rate=loss_1 / cap,
        exceeds_budget=loss_1 > max_loss,
        note="标准情景，假设止损单可以按计划成交"
    ))

    # --- 情景 2：次日不利低开 ---
    # T+1 规则：当日买入不能卖出，次日低开 2%
    gap_down_price = position.stop_loss_price * (1 - 0.02)
    _, _, _, sell_fee_2 = calc_sell_fees(shares, gap_down_price, config)
    sell_rev_2 = shares * gap_down_price - sell_fee_2
    loss_2 = buy_cost - sell_rev_2
    results.append(StressTestResult(
        scenario="情景二：次日不利低开",
        description=f"T+1 限制当日无法卖出，次日低开 2% 至 {gap_down_price:.2f} 元后卖出",
        assumed_exit_price=gap_down_price,
        actual_loss=loss_2,
        actual_loss_rate=loss_2 / cap,
        exceeds_budget=loss_2 > max_loss,
        note="A 股 T+1 制度下的常见风险，低开幅度为保守假设"
    ))

    # --- 情景 3：止损触发后因流动性枯竭无法卖出，继续下跌 ---
    # 价格跌至止损位触发止损，但因一字跌停/流动性枯竭无法成交，
    # 随后在止损价基础上继续下跌 8% 后才能卖出。
    # 8%的依据：A股主板涨跌停限制为10%，8%是小于一个跌停板的保守极端假设，
    # 参考历史上连续跌停个股在打开跌停前的累计跌幅（通常首日跌停10%后次日继续低开）。
    # 该情景确保极端损失始终大于标准止损情景。
    day3_exit_price = position.stop_loss_price * (1 - 0.08)
    _, _, _, sell_fee_3 = calc_sell_fees(shares, day3_exit_price, config)
    sell_rev_3 = shares * day3_exit_price - sell_fee_3
    loss_3 = buy_cost - sell_rev_3
    results.append(StressTestResult(
        scenario="情景三：止损触发后流动性枯竭继续下跌",
        description=(
            f"价格跌至止损价 {position.stop_loss_price:.2f} 元触发止损，"
            f"但因一字跌停/流动性枯竭无法成交，随后继续下跌 8% 至 "
            f"{day3_exit_price:.2f} 元后才能卖出"
        ),
        assumed_exit_price=day3_exit_price,
        actual_loss=loss_3,
        actual_loss_rate=loss_3 / cap,
        exceeds_budget=loss_3 > max_loss,
        note=f"极端情景，止损单无法成交时实际损失远超标准情景，{limit_down_rate*100:.0f}% 涨跌停制度下流动性风险显著"
    ))

    return results


def run_risk_engine(
    user_input: UserInput,
    config: Optional[FeeConfig] = None
) -> RiskEngineOutput:
    """
    风险引擎主入口：校验 → 仓位计算 → 压力测试 → 输出
    """
    from datetime import datetime

    errors = validate_input(user_input)
    if errors:
        raise ValueError("输入校验失败: " + "; ".join(errors))

    position = calculate_position(user_input, config)
    stress = run_stress_tests(user_input, position, config)

    return RiskEngineOutput(
        input=user_input,
        position=position,
        stress_tests=stress,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ============================================================
# 便捷函数：从数据快照计算 ATR
# ============================================================

def calculate_atr_from_closes(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """
    从 K 线数据计算 ATR（Average True Range）
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = TR 的简单移动平均
    """
    if len(closes) < period + 1:
        return 0.0

    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else 0.0

    # 取最近 period 个 TR 的平均
    recent_tr = tr_list[-period:]
    return sum(recent_tr) / period


def find_key_support(closes: list[float], lookback: int = 20) -> float:
    """
    简化版关键支撑位识别：取近 lookback 个交易日的最低价作为保守支撑。
    默认使用 20 日低点（约一个月交易周期），止损距离更合理。
    实际项目中可由技术面 Agent 给出更精确的结构位置，
    这里提供一个确定性的兜底值。
    """
    if not closes:
        return 0.0
    recent = closes[-lookback:] if len(closes) >= lookback else closes
    return min(recent)
