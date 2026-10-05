"""
风险引擎单元测试
每次修改 risk_engine.py 后必须运行本文件全部用例。
运行方式：python3 -m pytest tests/test_risk_engine.py -v
或直接：python3 tests/test_risk_engine.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from risk_engine import (
    UserInput, FeeConfig, calculate_position, run_risk_engine,
    run_stress_tests, validate_input, round_down_to_lot,
    calculate_atr_from_closes, find_key_support, calc_buy_fees, calc_sell_fees
)


def test_round_down_to_lot():
    assert round_down_to_lot(150) == 100
    assert round_down_to_lot(250) == 200
    assert round_down_to_lot(99) == 0
    assert round_down_to_lot(1000) == 1000
    assert round_down_to_lot(1050.7) == 1000
    print("✓ test_round_down_to_lot passed")


def test_validate_input():
    # 正常输入
    ui = UserInput("600519", "主板样本 A", 100000, 3000, 1700, 30, 1650)
    assert validate_input(ui) == []

    # 本金 <= 0
    ui2 = UserInput("600519", "主板样本 A", 0, 3000, 1700, 30, 1650)
    assert len(validate_input(ui2)) > 0

    # 损失 > 本金
    ui3 = UserInput("600519", "主板样本 A", 10000, 20000, 1700, 30, 1650)
    assert len(validate_input(ui3)) > 0

    # 支撑位 >= 当前价
    ui4 = UserInput("600519", "主板样本 A", 100000, 3000, 1700, 30, 1750)
    assert len(validate_input(ui4)) > 0

    print("✓ test_validate_input passed")


def test_calc_fees():
    config = FeeConfig()
    # 买入 100 股，价格 1700
    comm, trans, total = calc_buy_fees(100, 1700, config)
    amount = 100 * 1700  # 170000
    assert comm == max(amount * 0.00025, 5)  # 42.5
    assert trans == amount * 0.00001  # 1.7
    assert abs(total - (comm + trans)) < 0.01

    # 小额交易触发最低佣金
    comm2, _, _ = calc_buy_fees(100, 10, config)
    assert comm2 == 5.0

    # 卖出费用含印花税
    comm3, stamp, trans3, total3 = calc_sell_fees(100, 1700, config)
    assert stamp == 170000 * 0.0005  # 85
    print("✓ test_calc_fees passed")


def test_position_normal_case():
    """正常案例：本金 10 万，最大损失 3000，茅台"""
    ui = UserInput("600519", "主板样本 A", 100000, 3000, 1700, 35, 1650)
    pos = calculate_position(ui)

    # 最大损失率 3%
    assert abs(pos.max_loss_rate - 0.03) < 0.001

    # 结构保护距离 = 1700 - 1650 = 50
    assert abs(pos.structure_distance - 50) < 0.01

    # 波动保护距离 = 35 × 倍数（ATR/价格=2.06%，倍数=2.0）= 70
    assert abs(pos.atr_risk_multiplier - 2.0) < 0.01
    assert abs(pos.volatility_distance - 70) < 0.01

    # 最终保护距离 = max(70, 50) = 70
    assert abs(pos.final_stop_distance - 70) < 0.01

    # 止损价 = 1700 - 70 = 1630
    assert abs(pos.stop_loss_price - 1630) < 0.01

    # 理论股数 = 3000 / 70 = 42.86 → 向下取整到 0 股（不足 100）
    assert pos.theoretical_shares < 100
    assert pos.final_shares == 0
    assert pos.vetoed is True
    assert "最小模拟仓位" in pos.veto_reason

    print("✓ test_position_normal_case passed (茅台高股价导致预算不足，正确否决)")


def test_position_lower_price_stock():
    """主板样本案例：风险预算允许，但受到30%单股仓位上限约束"""
    ui = UserInput("601318", "主板样本 B", 100000, 3000, 45, 1.2, 43)
    pos = calculate_position(ui)

    # ATR 比例 = 1.2/45 = 2.67% → 倍数 1.5
    assert abs(pos.atr_risk_multiplier - 1.5) < 0.01
    # 波动距离 = 1.2 × 1.5 = 1.8
    assert abs(pos.volatility_distance - 1.8) < 0.01
    # 结构距离 = 45 - 43 = 2
    assert abs(pos.structure_distance - 2) < 0.01
    # 最终 = max(1.8, 2) = 2
    assert abs(pos.final_stop_distance - 2) < 0.01

    # 理论股数 = 3000 / 2 = 1500（不含费用）
    assert pos.theoretical_shares == 1500
    # 单股仓位上限30%，最多约可容纳600股
    assert pos.final_shares == 600
    assert pos.lot_rounded_shares == 1500  # 取整后但费用调整前

    # 市值 = 600 × 45 = 27000，仓位 27%
    assert abs(pos.final_position_value - 27000) < 1
    assert abs(pos.final_position_ratio - 0.27) < 0.01

    # 标准损失应 <= 3000
    assert pos.standard_loss <= 3000 + 1  # 加费用容差
    assert pos.vetoed is False
    assert pos.within_budget is True

    print(f"✓ test_position_lower_price_stock passed")
    print(f"  股数={pos.final_shares}, 市值={pos.final_position_value:.0f}, "
          f"标准损失={pos.standard_loss:.2f}, 费用={pos.total_fees:.2f}")


def test_high_risk_warning():
    """最大损失率超过 5% 应触发高风险提示"""
    ui = UserInput("601318", "主板样本 B", 100000, 8000, 45, 1.2, 43)
    pos = calculate_position(ui)
    assert pos.high_risk_warning is True
    assert pos.max_loss_rate == 0.08
    print("✓ test_high_risk_warning passed")


def test_stress_tests():
    """压力测试：三种情景损失应递增"""
    ui = UserInput("601318", "主板样本 B", 100000, 3000, 45, 1.2, 43)
    pos = calculate_position(ui)
    stress = run_stress_tests(ui, pos)

    assert len(stress) == 3
    # 正常止损损失 < 低开损失 < 跌停损失
    assert stress[0].actual_loss < stress[1].actual_loss
    assert stress[1].actual_loss < stress[2].actual_loss

    # 极端情景应超过预算
    assert stress[2].exceeds_budget is True

    print(f"✓ test_stress_tests passed")
    for s in stress:
        print(f"  {s.scenario}: 损失={s.actual_loss:.2f}元, "
              f"率={s.actual_loss_rate*100:.2f}%, 超预算={s.exceeds_budget}")


def test_atr_calculation():
    """ATR 计算验证"""
    # 构造简单数据：每天 high-low=2, 无跳空
    highs = [10 + i for i in range(20)]
    lows = [8 + i for i in range(20)]
    closes = [9 + i for i in range(20)]
    atr = calculate_atr_from_closes(highs, lows, closes, 14)
    # TR = max(2, |10+i - (9+i-1)|, |8+i - (9+i-1)|) = max(2, 2, 0) = 2
    assert abs(atr - 2.0) < 0.01
    print("✓ test_atr_calculation passed")


def test_key_support():
    """支撑位识别：取近期最低价"""
    closes = [100, 95, 98, 92, 97, 90, 96]
    support = find_key_support(closes, 60)
    assert support == 90
    print("✓ test_key_support passed")


def test_full_engine_run():
    """完整引擎运行测试"""
    ui = UserInput("601318", "主板样本 B", 100000, 5000, 45, 1.2, 43)
    output = run_risk_engine(ui)

    assert output.engine_version == "1.0.0"
    assert output.position.final_shares > 0
    assert len(output.stress_tests) == 3
    assert output.timestamp is not None

    print(f"✓ test_full_engine_run passed")
    print(f"  股票={output.input.stock_name}, 股数={output.position.final_shares}, "
          f"否决={output.position.vetoed}")


def run_all():
    print("=" * 60)
    print("RiskPilot 风险引擎单元测试")
    print("=" * 60)
    test_round_down_to_lot()
    test_validate_input()
    test_calc_fees()
    test_position_normal_case()
    test_position_lower_price_stock()
    test_high_risk_warning()
    test_stress_tests()
    test_atr_calculation()
    test_key_support()
    test_full_engine_run()
    print("=" * 60)
    print("全部测试通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
