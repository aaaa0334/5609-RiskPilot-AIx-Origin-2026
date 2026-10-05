"""
RiskPilot 资金面分析模块
========================
全部基于真实日线 OHLCV 数据计算经典金融指标，不编造任何数据。

计算的指标：
1. OBV（On-Balance Volume，能量潮）— Joe Granville 1963年提出的经典指标
2. 近N日资金净流入估算 — 上涨日成交量减下跌日成交量（经典资金流向估算方法）
3. 量价配合度 — 价格与成交量的同向/背离关系
4. 成交量均线（5日/20日）— 量能趋势
5. 换手率相对水平 — 近期成交量相对于历史的位置

注意：本模块不使用实时主力资金、北向资金等需要外部API的数据，
全部从已有的日线价格和成交量推导，确保离线可复现、可验证。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CapitalFlowResult:
    """资金面分析结果"""
    # OBV 能量潮
    obv_current: float            # 当前OBV值
    obv_ma5: float                # OBV的5日均线
    obv_trend: str                # OBV趋势：上升/下降/震荡
    obv_signal: str               # OBV信号

    # 资金流向估算
    flow_5d: float                # 近5日资金净流入估算（手）
    flow_20d: float               # 近20日资金净流入估算（手）
    flow_5d_ratio: float          # 近5日净流入占总成交量比例
    flow_direction: str           # 资金方向：净流入/净流出/平衡

    # 量价关系
    volume_price_status: str      # 量价配合：放量上涨/缩量上涨/放量下跌/缩量下跌/震荡
    volume_price_signal: str      # 量价信号

    # 成交量趋势
    vol_ma5: float                # 5日均量
    vol_ma20: float               # 20日均量
    vol_ratio: float              # 5日均量/20日均量
    volume_trend: str             # 量能趋势：放大/缩小/平稳

    # 换手率（相对水平）
    turnover_level: str           # 换手率相对水平：高/中/低
    recent_avg_volume: float      # 近5日平均成交量

    # 综合结论
    conclusion: str               # 一句话资金面结论
    bullish_signals: list         # 看多信号列表
    bearish_signals: list         # 看空信号列表


def calculate_capital_flow(daily_data: list[dict]) -> CapitalFlowResult:
    """
    基于日线OHLCV数据计算资金面指标。

    参数:
        daily_data: 日线数据列表，每个元素需包含 open/close/high/low/volume

    返回:
        CapitalFlowResult，所有指标均从输入数据计算得出
    """
    if not daily_data or len(daily_data) < 20:
        return CapitalFlowResult(
            obv_current=0, obv_ma5=0, obv_trend="数据不足", obv_signal="数据不足",
            flow_5d=0, flow_20d=0, flow_5d_ratio=0, flow_direction="数据不足",
            volume_price_status="数据不足", volume_price_signal="数据不足",
            vol_ma5=0, vol_ma20=0, vol_ratio=0, volume_trend="数据不足",
            turnover_level="数据不足", recent_avg_volume=0,
            conclusion="历史数据不足，无法进行资金面分析。",
            bullish_signals=[], bearish_signals=[],
        )

    data = daily_data[-60:] if len(daily_data) > 60 else daily_data
    closes = [d.get("close", d.get("c", 0)) for d in data]
    volumes = [d.get("volume", d.get("vol", d.get("amount", 0))) for d in data]

    # ===== 1. OBV 能量潮计算 =====
    # 经典公式：上涨日OBV += 成交量，下跌日OBV -= 成交量，平盘日不变
    obv_values = []
    obv = 0
    for i in range(len(data)):
        if i == 0:
            obv = volumes[i]  # 初始值设为第一天成交量
        else:
            if closes[i] > closes[i - 1]:
                obv += volumes[i]
            elif closes[i] < closes[i - 1]:
                obv -= volumes[i]
        obv_values.append(obv)

    obv_current = obv_values[-1]
    obv_ma5 = sum(obv_values[-5:]) / 5 if len(obv_values) >= 5 else obv_current
    obv_ma20 = sum(obv_values[-20:]) / 20 if len(obv_values) >= 20 else obv_current

    # OBV趋势判断
    if obv_current > obv_ma5 > obv_ma20:
        obv_trend = "持续上升"
        obv_signal = "资金持续流入，OBV多头排列"
    elif obv_current < obv_ma5 < obv_ma20:
        obv_trend = "持续下降"
        obv_signal = "资金持续流出，OBV空头排列"
    elif obv_current > obv_ma20:
        obv_trend = "震荡偏强"
        obv_signal = "OBV在均线上方震荡，资金面偏多"
    else:
        obv_trend = "震荡偏弱"
        obv_signal = "OBV在均线下方震荡，资金面偏空"

    # ===== 2. 资金流向估算 =====
    # 经典方法：上涨日成交量视为流入，下跌日视为流出
    def calc_flow(n_days):
        flow = 0
        total_vol = 0
        start = max(1, len(data) - n_days)
        for i in range(start, len(data)):
            total_vol += volumes[i]
            if closes[i] > closes[i - 1]:
                flow += volumes[i]
            elif closes[i] < closes[i - 1]:
                flow -= volumes[i]
        return flow, total_vol

    flow_5d, total_5d = calc_flow(5)
    flow_20d, total_20d = calc_flow(20)
    flow_5d_ratio = (flow_5d / total_5d * 100) if total_5d > 0 else 0

    if flow_5d > 0 and flow_20d > 0:
        flow_direction = "持续净流入"
    elif flow_5d < 0 and flow_20d < 0:
        flow_direction = "持续净流出"
    elif flow_5d > 0:
        flow_direction = "短期流入、中期流出"
    else:
        flow_direction = "短期流出、中期流入"

    # ===== 3. 量价关系分析 =====
    # 最近5日价格涨跌和成交量变化
    price_change_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    vol_ma5 = sum(volumes[-5:]) / 5
    vol_ma20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else vol_ma5
    vol_change = (vol_ma5 / vol_ma20 - 1) * 100 if vol_ma20 > 0 else 0

    if price_change_5d > 1 and vol_change > 10:
        vp_status = "放量上涨"
        vp_signal = "价涨量增，资金主动买入，上涨动能健康"
    elif price_change_5d > 1 and vol_change < -10:
        vp_status = "缩量上涨"
        vp_signal = "价涨量缩，买盘不足，上涨持续性存疑"
    elif price_change_5d < -1 and vol_change > 10:
        vp_status = "放量下跌"
        vp_signal = "价跌量增，资金主动卖出，下跌动能较强"
    elif price_change_5d < -1 and vol_change < -10:
        vp_status = "缩量下跌"
        vp_signal = "价跌量缩，抛压减轻，可能接近阶段性底部"
    else:
        vp_status = "量价平稳"
        vp_signal = "价格和成交量均无明显变化，市场观望情绪浓"

    # ===== 4. 成交量趋势 =====
    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1
    if vol_ratio > 1.3:
        volume_trend = "明显放大"
    elif vol_ratio > 1.1:
        volume_trend = "温和放大"
    elif vol_ratio < 0.7:
        volume_trend = "明显萎缩"
    elif vol_ratio < 0.9:
        volume_trend = "温和萎缩"
    else:
        volume_trend = "平稳"

    # ===== 5. 换手率相对水平 =====
    # 没有流通股本数据，用近期成交量在历史中的分位代替
    all_volumes = sorted(volumes)
    recent_vol = vol_ma5
    percentile = sum(1 for v in all_volumes if v <= recent_vol) / len(all_volumes) * 100
    if percentile >= 70:
        turnover_level = "高（近5日均量处于历史70%分位以上）"
    elif percentile >= 40:
        turnover_level = "中等（处于历史40%-70%分位）"
    else:
        turnover_level = "低（处于历史40%分位以下）"

    # ===== 6. 综合多空信号 =====
    bullish = []
    bearish = []

    if "上升" in obv_trend or "偏强" in obv_trend:
        bullish.append(f"OBV{obv_trend}，资金面偏多")
    else:
        bearish.append(f"OBV{obv_trend}，资金面偏空")

    if flow_5d > 0:
        bullish.append(f"近5日资金净流入约{flow_5d/10000:.1f}万手")
    else:
        bearish.append(f"近5日资金净流出约{abs(flow_5d)/10000:.1f}万手")

    if vp_status == "放量上涨":
        bullish.append("放量上涨，量价配合良好")
    elif vp_status == "缩量上涨":
        bearish.append("缩量上涨，上涨动能不足")
    elif vp_status == "放量下跌":
        bearish.append("放量下跌，抛压较重")
    elif vp_status == "缩量下跌":
        bullish.append("缩量下跌，抛压减轻")

    if vol_ratio > 1.2 and price_change_5d > 0:
        bullish.append("成交量放大且价格上涨，资金关注度提升")

    # 综合结论
    if len(bullish) > len(bearish) + 1:
        conclusion = (
            f"资金面偏多。{vp_signal}。"
            f"近5日资金{flow_direction}，OBV{obv_trend}。"
            f"整体看资金有主动买入迹象，但需结合基本面和技术面综合判断。"
        )
    elif len(bearish) > len(bullish) + 1:
        conclusion = (
            f"资金面偏空。{vp_signal}。"
            f"近5日资金{flow_direction}，OBV{obv_trend}。"
            f"整体看资金流出压力较大，短期需谨慎。"
        )
    else:
        conclusion = (
            f"资金面中性。{vp_signal}。"
            f"近5日资金{flow_direction}，OBV{obv_trend}。"
            f"多空信号交织，建议观望等待更明确的方向。"
        )

    return CapitalFlowResult(
        obv_current=round(obv_current, 0),
        obv_ma5=round(obv_ma5, 0),
        obv_trend=obv_trend,
        obv_signal=obv_signal,
        flow_5d=round(flow_5d, 0),
        flow_20d=round(flow_20d, 0),
        flow_5d_ratio=round(flow_5d_ratio, 2),
        flow_direction=flow_direction,
        volume_price_status=vp_status,
        volume_price_signal=vp_signal,
        vol_ma5=round(vol_ma5, 0),
        vol_ma20=round(vol_ma20, 0),
        vol_ratio=round(vol_ratio, 2),
        volume_trend=volume_trend,
        turnover_level=turnover_level,
        recent_avg_volume=round(vol_ma5, 0),
        conclusion=conclusion,
        bullish_signals=bullish,
        bearish_signals=bearish,
    )


def generate_capital_flow_analysis(
    result: CapitalFlowResult,
    stock_name: str,
    is_synthetic: bool = False,
) -> str:
    """
    生成资金面Agent的分析文本。
    所有数据均来自 CapitalFlowResult 的计算结果，不编造额外数字。
    """
    data_note = "（注：以下指标基于历史成交量数据计算，非实时主力资金数据）" if is_synthetic else ""

    lines = [
        f"【资金面 Agent 分析】{stock_name}",
        data_note,
        "",
        f"一、OBV能量潮（经典资金流向指标）",
        f"  当前OBV：{result.obv_current:,.0f}",
        f"  OBV趋势：{result.obv_trend}",
        f"  信号：{result.obv_signal}",
        "",
        f"二、资金流向估算（上涨日成交量-下跌日成交量）",
        f"  近5日：{'净流入' if result.flow_5d >= 0 else '净流出'} {abs(result.flow_5d)/10000:,.1f}万手（占比{result.flow_5d_ratio:+.1f}%）",
        f"  近20日：{'净流入' if result.flow_20d >= 0 else '净流出'} {abs(result.flow_20d)/10000:,.1f}万手",
        f"  方向判断：{result.flow_direction}",
        "",
        f"三、量价关系",
        f"  当前状态：{result.volume_price_status}",
        f"  解读：{result.volume_price_signal}",
        "",
        f"四、成交量趋势",
        f"  5日均量：{result.vol_ma5/10000:,.1f}万手",
        f"  20日均量：{result.vol_ma20/10000:,.1f}万手",
        f"  量比（5日/20日）：{result.vol_ratio}",
        f"  量能趋势：{result.volume_trend}",
        f"  换手活跃度：{result.turnover_level}",
        "",
        f"五、多空信号汇总",
    ]

    if result.bullish_signals:
        lines.append("  看多信号：")
        for s in result.bullish_signals:
            lines.append(f"    ✓ {s}")

    if result.bearish_signals:
        lines.append("  看空信号：")
        for s in result.bearish_signals:
            lines.append(f"    ✗ {s}")

    lines.extend([
        "",
        f"六、资金面结论",
        f"  {result.conclusion}",
        "",
        f"【方法论说明】",
        f"  本分析全部基于历史日线的收盘价和成交量数据计算，使用OBV能量潮、",
        f"  资金流向估算、量价分析等经典技术分析方法。未使用实时主力资金、",
        f"  北向资金等需要外部API的数据，所有指标均可从原始K线数据复现验证。",
    ])

    return "\n".join(lines)
