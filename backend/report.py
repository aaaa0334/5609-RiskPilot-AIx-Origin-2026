"""
RiskPilot 报告生成与可验证哈希模块
==================================
生成结构化模拟研究报告，并对报告内容计算 SHA-256 哈希。
本地哈希只能校验同一份报告的内容完整性，不提供第三方时间证明，
也不能证明数据来源、AI 推理过程或结论正确。
"""

import hashlib
import json
from datetime import datetime
from dataclasses import asdict
from typing import Optional

from risk_engine import RiskEngineOutput


REPORT_VERSION = "1.0.0"
MODEL_VERSION = "riskpilot-mvp-1.0"
DISCLAIMER = (
    "RiskPilot 为研究教育与风险情景模拟原型，非持牌证券服务机构，不提供证券投资咨询业务。"
    "本系统仅用于投资研究教育和风险情景模拟，不构成任何证券投资、法律、税务或财务建议，"
    "亦不构成任何证券的买入、卖出或持有推荐。系统不连接真实证券账户，不执行任何交易。"
    "AI模型输出可能存在错误、遗漏、偏差或幻觉。历史数据与模拟结果不代表未来表现。"
    "用户设置的「账户最大可承受损失」是标准模型情景下的风险预算，不是实际损失保证；"
    "跳空、跌停、停牌和流动性异常等情况可能造成更大损失。投资有风险，入市需谨慎。"
)


def build_report(
    risk_output: RiskEngineOutput,
    agent_analyses: dict,
    data_snapshot_info: dict,
) -> dict:
    """
    构建完整的模拟研究报告。

    agent_analyses 结构：
    {
        "technical": "...",      # 技术面 Agent 输出
        "fundamental": "...",    # 基本面 Agent 输出
        "news": "...",           # 公告新闻 Agent 输出
        "bull_bear_summary": "..."  # 多空汇总
    }
    """
    pos = risk_output.position
    inp = risk_output.input

    # 目标价和风险收益比
    target_price = data_snapshot_info.get("target_price", 0)
    if target_price <= inp.current_price:
        target_price = round(inp.current_price * 1.05, 2)
    potential_gain_per_share = target_price - inp.current_price
    potential_profit = round(potential_gain_per_share * pos.final_shares, 2) if pos.final_shares >= 100 else 0
    risk_per_share = pos.final_stop_distance
    risk_reward_ratio = round(potential_gain_per_share / risk_per_share, 2) if risk_per_share > 0 else 0

    # 决定最终状态
    if pos.vetoed:
        if pos.final_shares < 100:
            status = "风险不匹配"
            status_detail = "本金与损失预算不足以支持最小模拟仓位"
        else:
            status = "暂不形成模拟计划"
            status_detail = "标准情景损失超过用户设置的账户最大可承受损失"
    else:
        status = "形成模拟研究计划"
        status_detail = "标准情景损失在用户风险预算范围内"

    # 大白话结论（面向股市小白）
    if pos.vetoed:
        if pos.final_shares < 100:
            plain_summary = (
                f"不建议买入。{inp.stock_name}当前股价{inp.current_price:.2f}元，"
                f"买一手（100股）就需要{inp.current_price * 100:.0f}元，"
                f"但按您的损失预算{inp.max_loss:.0f}元算，连最小仓位都无法满足风险约束。"
            )
        else:
            plain_summary = (
                f"不建议买入。按您的损失预算{inp.max_loss:.0f}元计算，"
                f"即使买最少的仓位，正常止损也会亏{pos.standard_loss:.0f}元，超出您的承受范围。"
            )
    else:
        rr_advice = "值得考虑" if risk_reward_ratio >= 1.5 else "收益空间一般"
        # R:R < 1 时给出更强烈的风险提示
        if risk_reward_ratio < 1:
            rr_warning = (
                f"注意：当前风险收益比仅1:{risk_reward_ratio}（低于1:1），"
                f"意味着每承担1元风险只能获得{risk_reward_ratio:.2f}元潜在收益，"
                f"长期期望值为负，需谨慎参与。"
            )
            conclusion_prefix = "风险收益比偏低，谨慎参与"
        else:
            rr_warning = ""
            conclusion_prefix = "可以考虑买入"

        plain_summary = (
            f"{conclusion_prefix}{pos.final_shares}股（约{pos.final_position_value:.0f}元）。"
            f"止损价设为{pos.stop_loss_price:.2f}元，正常止损亏{pos.standard_loss:.0f}元"
            f"（在您{inp.max_loss:.0f}元的承受范围内）。"
            f"目标价{target_price:.2f}元，潜在收益约{potential_profit:.0f}元，"
            f"风险收益比1:{risk_reward_ratio}，{rr_advice}。"
            f"{rr_warning}"
            f"注意：若遇跌停卖不掉，极端情景可能亏{risk_output.stress_tests[-1].actual_loss:.0f}元。"
        )

    report = {
        "report_meta": {
            "report_version": REPORT_VERSION,
            "model_version": MODEL_VERSION,
            "engine_version": risk_output.engine_version,
            "generated_at": risk_output.timestamp,
            "data_snapshot": data_snapshot_info,
            "agent_execution": {
                "mode": agent_analyses.get("mode"),
                "run_status": agent_analyses.get("run_status"),
                "model": agent_analyses.get("model"),
                "provider": agent_analyses.get("provider"),
                "started_at": agent_analyses.get("started_at"),
                "completed_at": agent_analyses.get("completed_at"),
            },
        },
        "user_input": {
            "stock_code": inp.stock_code,
            "stock_name": inp.stock_name,
            "capital": inp.capital,
            "max_loss": inp.max_loss,
            "max_loss_rate": round(pos.max_loss_rate * 100, 2),
            "current_price": inp.current_price,
        },
        "system_status": {
            "status": status,
            "detail": status_detail,
            "vetoed": pos.vetoed,
            "veto_reason": pos.veto_reason,
            "high_risk_warning": pos.high_risk_warning,
        },
        "plain_language_summary": plain_summary,
        "risk_reward": {
            "target_price": target_price,
            "potential_gain_per_share": round(potential_gain_per_share, 2),
            "potential_profit": potential_profit,
            "risk_per_share": round(risk_per_share, 2),
            "risk_reward_ratio": risk_reward_ratio,
            "advice": "值得考虑（R:R ≥ 1:1.5）" if risk_reward_ratio >= 1.5 else "收益空间一般（R:R < 1:1.5）",
        },
        "evidence_pack": data_snapshot_info.get("evidence_pack_info", {}),
        "agent_analyses": agent_analyses,
        "risk_calculation": {
            "atr_14": pos.atr_14,
            "atr_risk_multiplier": pos.atr_risk_multiplier,
            "volatility_distance": round(pos.volatility_distance, 4),
            "structure_distance": round(pos.structure_distance, 4),
            "final_stop_distance": round(pos.final_stop_distance, 4),
            "stop_loss_price": round(pos.stop_loss_price, 4),
            "risk_per_share": round(pos.risk_per_share, 4),
            "theoretical_shares": round(pos.theoretical_shares, 2),
            "lot_rounded_shares": pos.lot_rounded_shares,
            "capital_limit_shares": pos.capital_limit_shares,
            "position_limit_shares": pos.position_limit_shares,
            "final_shares": pos.final_shares,
            "final_position_value": round(pos.final_position_value, 2),
            "final_position_ratio": round(pos.final_position_ratio * 100, 2),
        },
        "fees": {
            "buy_commission": round(pos.buy_commission, 2),
            "buy_transfer_fee": round(pos.buy_transfer_fee, 2),
            "buy_total": round(pos.buy_total_fee, 2),
            "sell_commission": round(pos.sell_commission, 2),
            "sell_stamp_tax": round(pos.sell_stamp_tax, 2),
            "sell_transfer_fee": round(pos.sell_transfer_fee, 2),
            "sell_total": round(pos.sell_total_fee, 2),
            "total_fees": round(pos.total_fees, 2),
        },
        "standard_scenario": {
            "standard_loss": round(pos.standard_loss, 2),
            "standard_loss_rate": round(pos.standard_loss_rate * 100, 2),
            "within_budget": pos.within_budget,
            "budget": pos.max_loss,
        },
        "stress_tests": [
            {
                "scenario": s.scenario,
                "description": s.description,
                "assumed_exit_price": round(s.assumed_exit_price, 4),
                "actual_loss": round(s.actual_loss, 2),
                "actual_loss_rate": round(s.actual_loss_rate * 100, 2),
                "exceeds_budget": s.exceeds_budget,
                "note": s.note,
            }
            for s in risk_output.stress_tests
        ],
        "invalidation_conditions": _extract_invalidation_conditions(agent_analyses),
        "human_confirmation_points": [
            "我理解本报告使用模拟本金，不会连接账户或执行交易",
            "我理解账户最大损失是标准情景风险预算，不是损失保证",
            "我理解跳空、跌停、停牌和流动性异常可能造成更大损失",
            "我已查看数据来源、日期以及真实/合成标识",
        ],
        "limitations": [
            "本报告基于历史数据和模型假设，不代表未来表现",
            "AI 分析可能存在幻觉、偏差或遗漏，关键决策需人工复核",
            "T+1、跳空、跌停、停牌和流动性不足可能导致实际损失超过预算",
            "数据可能存在延迟或缺失，页面已标注数据来源和时间",
            "风险引擎的否决仅基于标准情景，极端情景损失不受预算约束",
            "报告 SHA-256 仅用于本地内容完整性校验，不等于链上存证或第三方见证",
        ],
        "disclaimer": DISCLAIMER,
    }

    # 计算哈希（排除 hash 字段本身）
    report["report_hash"] = compute_hash(report)
    return report


def _extract_invalidation_conditions(agent_analyses: dict) -> list:
    """从 Agent 分析中提取失效条件（简化版，实际可由 LLM 结构化输出）"""
    conditions = []
    # 从技术面分析中提取关键支撑位作为失效条件
    tech = agent_analyses.get("technical", "")
    if "关键支撑位" in tech:
        # 简单提取，实际应由结构化解析
        conditions.append("价格跌破技术面关键支撑位，原趋势判断失效")
    conditions.append("公司发布业绩下修或重大负面公告，基本面逻辑失效")
    conditions.append("行业政策发生重大不利变化")
    return conditions


def compute_hash(report: dict) -> str:
    """对报告内容计算 SHA-256 哈希"""
    # 深拷贝并移除 hash 字段（如果存在）
    content = {k: v for k, v in report.items() if k != "report_hash"}
    serialized = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_hash(report: dict) -> bool:
    """验证报告哈希是否匹配（检测报告是否被篡改）"""
    if "report_hash" not in report:
        return False
    stored_hash = report["report_hash"]
    computed_hash = compute_hash(report)
    return stored_hash == computed_hash


def report_to_markdown(report: dict) -> str:
    """将报告转为可读的 Markdown 格式"""
    lines = []
    meta = report["report_meta"]
    inp = report["user_input"]
    status = report["system_status"]
    risk = report["risk_calculation"]
    std = report["standard_scenario"]

    lines.append(f"# RiskPilot 模拟研究报告")
    lines.append(f"")
    lines.append(f"**股票：** {inp['stock_name']}（{inp['stock_code']}）")
    lines.append(f"**生成时间：** {meta['generated_at']}")
    lines.append(f"**报告版本：** {meta['report_version']} | **引擎版本：** {meta['engine_version']}")
    lines.append(f"**本地完整性哈希：** `{report['report_hash'][:16]}...`")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## 系统状态")
    lines.append(f"")
    lines.append(f"**结论：{status['status']}**")
    lines.append(f"")
    lines.append(f"### 一句话总结")
    lines.append(f"> {report['plain_language_summary']}")
    lines.append(f"")
    if status["vetoed"]:
        lines.append(f"> ⚠️ {status['veto_reason']}")
        lines.append(f"")
    if status["high_risk_warning"]:
        lines.append(f"> ⚠️ 高风险提示：最大损失率 {inp['max_loss_rate']}% 超过 5%，请谨慎评估。")
        lines.append(f"")

    lines.append(f"## 用户输入")
    lines.append(f"")
    lines.append(f"| 项目 | 数值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 模拟本金 | {inp['capital']:,.0f} 元 |")
    lines.append(f"| 最大可承受损失 | {inp['max_loss']:,.0f} 元（{inp['max_loss_rate']}%） |")
    lines.append(f"| 当前参考价格 | {inp['current_price']:.2f} 元 |")
    lines.append(f"")

    lines.append(f"## AI Agent 分析")
    lines.append(f"")
    for key, label in [("technical", "技术面"), ("fundamental", "基本面与行业宏观"), ("capital_flow", "资金面"), ("news", "公告与新闻")]:
        if key in report["agent_analyses"]:
            lines.append(f"### {label} Agent")
            lines.append(f"")
            lines.append(report["agent_analyses"][key])
            lines.append(f"")

    lines.append(f"## 确定性风险计算")
    lines.append(f"")
    lines.append(f"| 项目 | 数值 |")
    lines.append(f"|---|---|")
    lines.append(f"| ATR(14) | {risk['atr_14']:.2f} 元 |")
    lines.append(f"| ATR 风险倍数 | {risk['atr_risk_multiplier']} |")
    lines.append(f"| 波动保护距离 | {risk['volatility_distance']:.2f} 元 |")
    lines.append(f"| 结构保护距离 | {risk['structure_distance']:.2f} 元 |")
    lines.append(f"| 最终保护距离 | {risk['final_stop_distance']:.2f} 元 |")
    lines.append(f"| 止损参考价 | {risk['stop_loss_price']:.2f} 元 |")
    lines.append(f"| 理论允许股数 | {risk['theoretical_shares']:.0f} 股 |")
    lines.append(f"| 取整后股数 | {risk['lot_rounded_shares']} 股 |")
    lines.append(f"| **最终模拟股数** | **{risk['final_shares']} 股** |")
    lines.append(f"| 模拟市值 | {risk['final_position_value']:,.0f} 元（{risk['final_position_ratio']}% 仓位） |")
    lines.append(f"")

    lines.append(f"## 交易费用")
    lines.append(f"")
    fees = report["fees"]
    lines.append(f"| 项目 | 买入 | 卖出 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| 佣金 | {fees['buy_commission']:.2f} | {fees['sell_commission']:.2f} |")
    lines.append(f"| 印花税 | — | {fees['sell_stamp_tax']:.2f} |")
    lines.append(f"| 过户费 | {fees['buy_transfer_fee']:.2f} | {fees['sell_transfer_fee']:.2f} |")
    lines.append(f"| 小计 | {fees['buy_total']:.2f} | {fees['sell_total']:.2f} |")
    lines.append(f"| **费用合计** | | **{fees['total_fees']:.2f} 元** |")
    lines.append(f"")

    lines.append(f"## 标准风险情景")
    lines.append(f"")
    lines.append(f"| 项目 | 数值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 标准情景预计损失 | {std['standard_loss']:,.2f} 元（{std['standard_loss_rate']}%） |")
    lines.append(f"| 用户损失预算 | {std['budget']:,.0f} 元 |")
    lines.append(f"| 是否在预算内 | {'✅ 是' if std['within_budget'] else '❌ 否'} |")
    lines.append(f"")

    rr = report.get("risk_reward", {})
    if rr:
        lines.append(f"## 风险收益比")
        lines.append(f"")
        lines.append(f"| 项目 | 数值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 目标价（近20日高点） | {rr.get('target_price', 0):.2f} 元 |")
        lines.append(f"| 每股潜在收益 | {rr.get('potential_gain_per_share', 0):.2f} 元 |")
        lines.append(f"| 每股潜在风险 | {rr.get('risk_per_share', 0):.2f} 元 |")
        lines.append(f"| 潜在总收益 | {rr.get('potential_profit', 0):,.0f} 元 |")
        lines.append(f"| **风险收益比** | **1:{rr.get('risk_reward_ratio', 0)}** |")
        lines.append(f"| 评价 | {rr.get('advice', '')} |")
        lines.append(f"")

    ep = report.get("evidence_pack", {})
    if ep and ep.get("has_evidence_pack"):
        lines.append(f"## 数据可验证性（证据包）")
        lines.append(f"")
        lines.append(f"- 数据来源：{ep.get('data_source', '')}")
        lines.append(f"- 快照日期：{ep.get('snapshot_date', '')}")
        lines.append(f"- 获取时间：{ep.get('retrieved_at', '')}")
        lines.append(f"- 哈希算法：{ep.get('hash_algorithm', 'SHA-256')}")
        lines.append(f"- 证据文件数：{ep.get('file_count', 0)}")
        if ep.get("official_documents"):
            lines.append(f"- 引用官方文档：")
            for doc in ep["official_documents"][:5]:
                lines.append(f"  - [{doc.get('date', '')}] {doc.get('title', '')}（{doc.get('source', '')}）")
        lines.append(f"")

    bt = report.get("backtest", {})
    if bt:
        lines.append(f"## 历史支撑位有效性检验")
        lines.append(f"")
        lines.append(f"> 注意：本检验不是策略回测，仅统计当前设定的止损价/目标价在历史上被触及的频率。不模拟出场顺序，不计算胜率。")
        lines.append(f"")
        lines.append(f"| 项目 | 数值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 检验天数 | {bt.get('lookback_days', 0)} 个交易日 |")
        lines.append(f"| 止损价被触及 | {bt.get('stop_hit_count', 0)} 次（{bt.get('stop_hit_rate', 0)}%的交易日） |")
        lines.append(f"| 目标价被触及 | {bt.get('target_hit_count', 0)} 次（{bt.get('target_hit_rate', 0)}%的交易日） |")
        lines.append(f"| 期间最大回撤 | {bt.get('max_drawdown_pct', 0)}% |")
        lines.append(f"| 平均日振幅 | {bt.get('avg_daily_range', 0)}%（{bt.get('volatility_level', '')}） |")
        lines.append(f"")
        lines.append(f"> {bt.get('conclusion', '')}")
        lines.append(f"")

    tp = report.get("trading_plan", {})
    if tp:
        lines.append(f"## 操作计划")
        lines.append(f"")
        if tp.get("entry_advice"):
            lines.append(f"### 入场时机")
            lines.append(f"{tp['entry_advice']}")
            lines.append(f"")
        lines.append(f"### 怎么买")
        lines.append(f"{tp.get('buy_plan', '')}")
        lines.append(f"")
        lines.append(f"### 怎么卖")
        lines.append(f"{tp.get('sell_plan', '')}")
        lines.append(f"")
        lines.append(f"### 止损怎么移动")
        lines.append(f"{tp.get('stop_move_plan', '')}")
        lines.append(f"")
        lines.append(f"### 仓位与资金")
        lines.append(f"{tp.get('position_summary', '')}")
        lines.append(f"")
        if tp.get("portfolio_advice"):
            lines.append(f"### 组合分散化建议")
            lines.append(f"{tp['portfolio_advice']}")
            lines.append(f"")
        lines.append(f"### 注意事项")
        lines.append(f"{tp.get('risk_note', '')}")
        lines.append(f"")

    me = report.get("market_environment", {})
    if me:
        lines.append(f"## 近期趋势判断（系统自动）")
        lines.append(f"")
        lines.append(f"- 判断结果：{me.get('trend_label', '')}")
        if me.get("trend_basis"):
            lines.append(f"- 判断依据：{me['trend_basis']}")
        lines.append(f"- 分析：{me.get('note', '')}")
        if me.get("disclaimer"):
            lines.append(f"- 说明：{me['disclaimer']}")
        lines.append(f"")

    lines.append(f"## 压力测试")
    lines.append(f"")
    for i, st in enumerate(report["stress_tests"], 1):
        flag = "⚠️ 超预算" if st["exceeds_budget"] else "✅ 预算内"
        lines.append(f"### {st['scenario']} {flag}")
        lines.append(f"- {st['description']}")
        lines.append(f"- 假设卖出价：{st['assumed_exit_price']:.2f} 元")
        lines.append(f"- 预计损失：{st['actual_loss']:,.2f} 元（{st['actual_loss_rate']}%）")
        lines.append(f"- 备注：{st['note']}")
        lines.append(f"")

    lines.append(f"## 失效条件")
    lines.append(f"")
    for cond in report.get("invalidation_conditions", []):
        lines.append(f"- {cond}")
    lines.append(f"")

    lines.append(f"## 人工确认点")
    lines.append(f"")
    for pt in report.get("human_confirmation_points", []):
        lines.append(f"- [ ] {pt}")
    lines.append(f"")

    lines.append(f"## 局限性与免责声明")
    lines.append(f"")
    for lim in report.get("limitations", []):
        lines.append(f"- {lim}")
    lines.append(f"")
    lines.append(f"> {report['disclaimer']}")

    return "\n".join(lines)
