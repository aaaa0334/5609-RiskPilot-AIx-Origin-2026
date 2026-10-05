"""
RiskPilot FastAPI 后端主入口
============================
启动方式：
    cd backend
    pip install fastapi uvicorn
    python main.py
    或：uvicorn main:app --host 0.0.0.0 --port 8000 --reload

API 端点：
    GET  /api/stocks              获取可用演示股票列表
    POST /api/analyze             执行完整分析（Agent + 风险引擎 + 报告）
    GET  /api/report/{code}       获取某只股票的最新报告（缓存）
    GET  /api/health              健康检查
"""

import os
import sys
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(__file__))

from risk_engine import UserInput, run_risk_engine, FeeConfig
from data_loader import load_stock_snapshot, get_available_stocks, extract_risk_engine_input, DEMO_STOCKS
from agents import get_agent_analyses
from report import build_report, report_to_markdown, verify_hash, compute_hash
from replay import router as replay_router, replay as calculate_replay, ReplayRequest, Action
from run_archive import archive_real_run
from backtest import run_backtest, generate_trading_plan
from capital_flow import calculate_capital_flow, generate_capital_flow_analysis
from leaderboard import (get_leaderboard, submit_score, get_faction_ranking,
                         get_faction_trait, apply_faction_trait, FACTIONS)
from finch import router as finch_router

app = FastAPI(
    title="RiskPilot API",
    description="最大账户损失约束下的多智能体 A 股研究与可验证风险决策系统",
    version="1.0.0",
)

# 允许跨域（前端单独端口访问时需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简单的内存缓存
app.include_router(replay_router)
app.include_router(finch_router)


@app.get('/replay')
def replay_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'replay.html'))


@app.get('/')
def home_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html'))


report_cache = {}


class AnalyzeRequest(BaseModel):
    stock_code: str
    capital: float
    max_loss: float
    agent_mode: str = "auto"  # auto / real / mock
    use_agent_suggested_support: bool = False  # 兼容旧前端；MVP 不允许 Agent 覆盖风险数值


class AnalyzeResponse(BaseModel):
    success: bool
    report: Optional[dict] = None
    report_markdown: Optional[str] = None
    daily_data: Optional[list] = None
    error: Optional[str] = None
    demo_run_dir: Optional[str] = None


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "RiskPilot",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "agent_mode": "real" if (
            os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ) else "preset_demo",
        "agent_provider": (
            "deepseek" if os.environ.get("DEEPSEEK_API_KEY")
            else "openai" if os.environ.get("OPENAI_API_KEY") else None
        ),
        "agent_mode_notice": (
            "正在调用真实 LLM" if (
                os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
            )
            else "当前为预设离线演示，不代表本次执行了真实 AI 推理"
        ),
    }


@app.get("/api/stocks")
async def list_stocks():
    """获取可用的演示股票列表"""
    stocks = get_available_stocks()
    return {
        "stocks": stocks,
        "total": len(stocks),
        "note": "5只演示样本；仅中国平安为真实历史数据，其余4只为合成演示数据（已标注）",
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """
    执行完整分析流程：
    1. 加载数据快照
    2. 调用 AI Agent 分析
    3. 运行确定性风险引擎
    4. 生成带本地完整性哈希的报告
    """
    try:
        # 1. 加载数据
        snapshot = load_stock_snapshot(request.stock_code)
        if snapshot is None:
            return AnalyzeResponse(
                success=False,
                error=f"股票 {request.stock_code} 没有可用的数据快照。"
                      f"可用股票：{', '.join(DEMO_STOCKS.keys())}"
            )

        stock_info = extract_risk_engine_input(snapshot, request.stock_code)

        # 2. 调用 AI Agent
        agent_analyses = get_agent_analyses(
            request.stock_code,
            stock_info,
            mode=request.agent_mode
        )

        # 2b. 资金面Agent（基于真实成交量数据计算经典指标，非LLM）
        capital_flow_result = calculate_capital_flow(stock_info.get("daily_data", []))
        capital_flow_text = generate_capital_flow_analysis(
            capital_flow_result,
            stock_info.get("stock_name", ""),
            is_synthetic=stock_info.get("is_synthetic", False),
        )
        agent_analyses["capital_flow"] = capital_flow_text
        agent_analyses["capital_flow_data"] = {
            "obv_current": capital_flow_result.obv_current,
            "obv_trend": capital_flow_result.obv_trend,
            "flow_5d": capital_flow_result.flow_5d,
            "flow_20d": capital_flow_result.flow_20d,
            "flow_direction": capital_flow_result.flow_direction,
            "volume_price_status": capital_flow_result.volume_price_status,
            "vol_ratio": capital_flow_result.vol_ratio,
            "volume_trend": capital_flow_result.volume_trend,
            "conclusion": capital_flow_result.conclusion,
            "bullish_signals": capital_flow_result.bullish_signals,
            "bearish_signals": capital_flow_result.bearish_signals,
        }
        if (
            agent_analyses.get("mode") == "real"
            and agent_analyses.get("run_status") != "REAL_SUCCESS"
        ):
            failed = [
                name
                for name, call in agent_analyses.get("calls", {}).items()
                if call.get("status") != "SUCCESS"
            ]
            call_errors = [
                f"{name}: {call.get('error', '未知错误')}"
                for name, call in agent_analyses.get("calls", {}).items()
                if call.get("status") != "SUCCESS"
            ]
            detail = agent_analyses.get("error") or (
                "；".join(call_errors)
                if call_errors
                else "失败 Agent：" + "、".join(failed)
                if failed
                else "真实模型调用未完整成功"
            )
            return AnalyzeResponse(
                success=False,
                error=f"真实 LLM 全链路未完成，未生成正式报告。{detail}",
            )

        # 3. 确定结构风险参考位。风险数值只来自确定性数据计算，
        # Agent 无权覆盖该数值，避免语言模型绕过风险引擎。
        key_support = stock_info["key_support"]

        # 4. 运行风险引擎
        user_input = UserInput(
            stock_code=request.stock_code,
            stock_name=stock_info["stock_name"],
            capital=request.capital,
            max_loss=request.max_loss,
            current_price=stock_info["current_price"],
            atr_14=stock_info["atr_14"],
            key_support=key_support,
            board=stock_info["board"],
        )

        risk_output = run_risk_engine(user_input)

        # 回测验证
        backtest_result = run_backtest(
            daily_data=stock_info.get("daily_data", []),
            current_price=stock_info["current_price"],
            stop_price=risk_output.position.stop_loss_price,
            target_price=stock_info.get("target_price", stock_info["current_price"] * 1.05),
        )

        # 操作计划
        ma20 = stock_info.get("technical_indicators", {}).get("ma20", 0)
        trading_plan = generate_trading_plan(
            current_price=stock_info["current_price"],
            stop_price=risk_output.position.stop_loss_price,
            target_price=stock_info.get("target_price", stock_info["current_price"] * 1.05),
            shares=risk_output.position.final_shares,
            capital=request.capital,
            max_loss=request.max_loss,
            standard_loss=risk_output.position.standard_loss,
            risk_reward_ratio=(
                (stock_info.get("target_price", 0) - stock_info["current_price"])
                / risk_output.position.final_stop_distance
            ) if risk_output.position.final_stop_distance > 0 else 0,
            backtest=backtest_result,
            ma20=ma20,
        )

        # 5. 生成报告
        data_snapshot_info = {
            "snapshot_date": stock_info.get("snapshot_date", ""),
            "analysis_cutoff": stock_info.get("analysis_cutoff", ""),
            "retrieved_at": stock_info.get("retrieved_at", ""),
            "evidence_pack": stock_info.get("evidence_pack", ""),
            "evidence_pack_info": stock_info.get("evidence_pack_info", {}),
            "data_source": stock_info.get("data_source", ""),
            "data_days": len(stock_info.get("daily_data", [])),
            "target_price": stock_info.get("target_price", 0),
            "is_live": False,
            "is_synthetic": stock_info.get("is_synthetic", False),
            "note": (
                "合成演示快照，使用虚构样本名，不代表任何真实上市公司"
                if stock_info.get("is_synthetic", False)
                else "预先下载的历史数据快照，非实时行情"
            ),
        }

        report = build_report(risk_output, agent_analyses, data_snapshot_info)
        report["backtest"] = {
            "lookback_days": backtest_result.lookback_days,
            "stop_hit_count": backtest_result.stop_hit_count,
            "target_hit_count": backtest_result.target_hit_count,
            "stop_hit_rate": backtest_result.stop_hit_rate,
            "target_hit_rate": backtest_result.target_hit_rate,
            "max_drawdown": backtest_result.max_drawdown,
            "max_drawdown_pct": backtest_result.max_drawdown_pct,
            "avg_daily_range": backtest_result.avg_daily_range,
            "volatility_level": backtest_result.volatility_level,
            "touch_frequency_note": backtest_result.touch_frequency_note,
            "conclusion": backtest_result.conclusion,
        }
        report["trading_plan"] = trading_plan

        # 自动判断个股近期趋势（替代用户手动输入大盘环境）
        # 理论依据：均线交叉法（Moving Average Crossover），MA5上穿MA20为金叉（偏多），
        # 下穿为死叉（偏空），是技术分析中最经典的趋势判断方法之一。
        daily = stock_info.get("daily_data", [])
        auto_trend = "sideways"
        auto_trend_label = "震荡"
        trend_basis = ""
        if len(daily) >= 20:
            closes = [d.get("close", 0) for d in daily if d.get("close", 0) > 0]
            if len(closes) >= 20:
                ma5 = sum(closes[-5:]) / 5
                ma20 = sum(closes[-20:]) / 20
                change_20d = (closes[-1] - closes[-20]) / closes[-20] * 100 if closes[-20] > 0 else 0

                if ma5 > ma20 * 1.01 and change_20d > 3:
                    auto_trend = "up"
                    auto_trend_label = "近期上涨趋势"
                    trend_basis = f"MA5({ma5:.2f}) > MA20({ma20:.2f})，近20日涨{change_20d:.1f}%"
                elif ma5 < ma20 * 0.99 and change_20d < -3:
                    auto_trend = "down"
                    auto_trend_label = "近期下跌趋势"
                    trend_basis = f"MA5({ma5:.2f}) < MA20({ma20:.2f})，近20日跌{abs(change_20d):.1f}%"
                else:
                    auto_trend = "sideways"
                    auto_trend_label = "近期震荡"
                    trend_basis = f"MA5({ma5:.2f})≈MA20({ma20:.2f})，近20日涨跌{change_20d:+.1f}%"

        market_notes = {
            "up": "该股票近期处于上涨趋势，短期动能偏多。但追高需谨慎，止损纪律不可放松。",
            "sideways": "该股票近期震荡，方向不明，建议控制仓位、严格执行止损。",
            "down": "该股票近期处于下跌趋势，短期动能偏空。即使基本面良好，趋势性下跌也可能持续，建议降低仓位或等待企稳信号。",
        }
        report["market_environment"] = {
            "trend": auto_trend,
            "trend_label": auto_trend_label,
            "note": market_notes.get(auto_trend, ""),
            "auto_detected": True,
            "trend_basis": trend_basis,
            "disclaimer": "基于该股票自身近期走势自动判断，非大盘指数判断。仅供参考。",
        }
        # 在大白话结论后追加趋势提示
        if auto_trend == "down" and not report["system_status"]["vetoed"]:
            report["plain_language_summary"] += " 该股票近期下跌趋势中，建议降低仓位或等待企稳。"

        report['report_hash'] = compute_hash(report)
        report_md = report_to_markdown(report)

        demo_run_dir = None
        if agent_analyses.get("run_status") == "REAL_SUCCESS":
            demo_run_dir = archive_real_run(
                request_data={
                    "stock_code": request.stock_code,
                    "capital": request.capital,
                    "max_loss": request.max_loss,
                    "agent_mode": request.agent_mode,
                },
                stock_data=stock_info,
                agent_analyses=agent_analyses,
                risk_output=risk_output,
                report=report,
                report_markdown=report_md,
            )

        # 6. 缓存
        report_cache[request.stock_code] = {
            "report": report,
            "markdown": report_md,
            "generated_at": datetime.now().isoformat(),
        }

        return AnalyzeResponse(
            success=True,
            report=report,
            report_markdown=report_md,
            daily_data=stock_info.get("daily_data", []),  # 返回全部日线数据，前端可切换时间范围
            demo_run_dir=demo_run_dir,
        )

    except ValueError as e:
        return AnalyzeResponse(success=False, error=str(e))
    except Exception as e:
        return AnalyzeResponse(success=False, error=f"系统错误: {str(e)}")


@app.get("/api/report/{stock_code}")
async def get_report(stock_code: str):
    """获取缓存的报告"""
    if stock_code not in report_cache:
        raise HTTPException(status_code=404, detail="该股票暂无缓存报告，请先调用 /api/analyze")
    return report_cache[stock_code]


@app.post("/api/verify-hash")
async def verify_report_hash(report: dict):
    """验证报告哈希是否被篡改"""
    is_valid = verify_hash(report)
    return {
        "valid": is_valid,
        "stored_hash": report.get("report_hash", ""),
        "message": "报告哈希匹配，内容未被篡改" if is_valid else "报告哈希不匹配，内容可能已被篡改",
    }


# ============ 板块新闻与行业数据 ============

SECTOR_NEWS_CUTOFF = "2025-08-31"


def public_sector_info(info: dict) -> dict:
    """只公开截止日前的摘要，并把人工热度明确标记为演示值。"""
    result = dict(info or {})
    result["news"] = [
        item for item in result.get("news", [])
        if str(item.get("date", "")) <= SECTOR_NEWS_CUTOFF
    ]
    result["demo_heat_score"] = result.pop("hot_score", None)
    return result

@app.get("/api/sector-news")
async def get_sector_news(industry: str = None):
    """获取板块热点新闻（2025年1-8月历史数据演示）"""
    import json
    news_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'sector_news.json')
    try:
        with open(news_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        sectors = data.get('sectors', {})
        if industry and industry in sectors:
            return {"status": "ok", "industry": industry, "data": public_sector_info(sectors[industry]), "meta": data.get('meta', {})}
        # 返回所有板块的热点摘要（用于顶部轮播）
        highlights = []
        for name, raw_info in sectors.items():
            info = public_sector_info(raw_info)
            for news in info.get('news', [])[:1]:
                highlights.append({
                    "industry": name,
                    "icon": info.get('icon', '📊'),
                    "demo_heat_score": info.get('demo_heat_score'),
                    "title": news.get('title', ''),
                    "date": news.get('date', ''),
                    "impact": news.get('impact', '')
                })
        return {"status": "ok", "highlights": highlights, "meta": data.get('meta', {})}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/sector-observation/{stock_code}")
async def get_sector_observation(stock_code: str):
    """同板块观察面板：同业对比+板块走势+板块新闻+估值指标"""
    import json
    import math
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    # 加载股票池
    pool_path = os.path.join(base_dir, 'data', 'stock_pool.json')
    with open(pool_path, 'r', encoding='utf-8') as f:
        stock_pool = json.load(f)
    if stock_code not in stock_pool:
        raise HTTPException(status_code=404, detail="股票不在样本池中")
    target = stock_pool[stock_code]
    industry = target.get('industry', '')
    # 同行业股票
    peers = [{"code": c, "name": v.get('name',''), "industry": v.get('industry','')}
             for c, v in stock_pool.items() if v.get('industry') == industry and c != stock_code]
    # 计算每只股票的区间涨跌幅和波动率
    def calc_metrics(code):
        snap_path = os.path.join(base_dir, 'data', 'snapshots', f'{code}.json')
        if not os.path.exists(snap_path):
            return None
        with open(snap_path, 'r', encoding='utf-8') as f:
            snap = json.load(f)
        daily = snap.get('daily', [])
        if len(daily) < 2:
            return None
        prices = [d['close'] for d in daily]
        volumes = [d.get('volume', 0) for d in daily]
        first_price = prices[0]
        last_price = prices[-1]
        total_return = round((last_price / first_price - 1) * 100, 2)
        high = max(d.get('high', d['close']) for d in daily)
        low = min(d.get('low', d['close']) for d in daily)
        # 年化波动率
        returns = [(prices[i]/prices[i-1] - 1) for i in range(1, len(prices))]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r)**2 for r in returns) / len(returns)
        vol = round(math.sqrt(variance) * math.sqrt(252) * 100, 1)
        # 原始成交量单位为“股”；1手=100股，因此1万手=1,000,000股。
        avg_vol = round(sum(volumes) / len(volumes) / 1000000, 2)
        return {
            "code": code, "name": stock_pool.get(code, {}).get('name', code),
            "last_price": last_price, "total_return": total_return,
            "high": high, "low": low, "volatility": vol, "avg_volume": avg_vol
        }
    target_metrics = calc_metrics(stock_code)
    peer_metrics = []
    for p in peers[:15]:  # 最多15个同业
        m = calc_metrics(p['code'])
        if m:
            peer_metrics.append(m)
    # 板块平均涨跌幅
    all_metrics = [target_metrics] + peer_metrics if target_metrics else peer_metrics
    sector_avg_return = round(sum(m['total_return'] for m in all_metrics) / len(all_metrics), 2) if all_metrics else 0
    sector_avg_vol = round(sum(m['volatility'] for m in all_metrics) / len(all_metrics), 1) if all_metrics else 0
    # 板块内排名
    sorted_by_return = sorted(all_metrics, key=lambda x: x['total_return'], reverse=True)
    rank = next((i+1 for i, m in enumerate(sorted_by_return) if m['code'] == stock_code), None)
    # 板块新闻
    news_path = os.path.join(base_dir, 'data', 'sector_news.json')
    sector_news = {}
    if os.path.exists(news_path):
        with open(news_path, 'r', encoding='utf-8') as f:
            news_data = json.load(f)
        sector_news = public_sector_info(news_data.get('sectors', {}).get(industry, {}))
        sector_news_meta = news_data.get('meta', {})
    else:
        sector_news_meta = {}
    return {
        "status": "ok",
        "stock_code": stock_code,
        "stock_name": target.get('name', ''),
        "industry": industry,
        "target_metrics": target_metrics,
        "peers": peer_metrics,
        "sector_avg_return": sector_avg_return,
        "sector_avg_volatility": sector_avg_vol,
        "sector_rank": rank,
        "sector_total": len(all_metrics),
        "sector_news": sector_news,
        "sector_news_meta": sector_news_meta,
        "valuation_note": "PE/PB/股息率等财务估值指标待接入实时数据源，当前展示价格行为类指标"
    }


# ============ 排行榜与阵营系统 ============

class ScoreSubmit(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    avatar: str = Field(default="🎮", max_length=8)
    faction: str = Field(default="jin", pattern=r"^(jin|mu|shui|huo|tu)$")
    stock_code: str = Field(pattern=r"^\d{6}$")
    decision_mode: str = Field(pattern=r"^(monthly|weekly)$")
    capital: float = Field(ge=1000, le=10000000)
    max_loss: float = Field(gt=0, le=10000000)
    actions: list[Action] = Field(max_length=60)


@app.get("/api/leaderboard")
async def api_get_leaderboard(limit: int = 20):
    """获取个人牛人榜"""
    return get_leaderboard(limit=limit)


@app.post("/api/submit-score")
async def api_submit_score(score: ScoreSubmit):
    """服务端重放操作序列并提交成绩，不接受浏览器自报盈亏。"""
    try:
        result = calculate_replay(ReplayRequest(
            stock_code=score.stock_code,
            decision_mode=score.decision_mode,
            capital=score.capital,
            max_loss=score.max_loss,
            actions=score.actions,
            faction=score.faction,
        ))
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result['finished']:
        raise HTTPException(status_code=400, detail="模拟尚未结束，不能提交排行榜")
    pnl = result['account']['pnl']
    pnl_pct = round(pnl / result['capital'] * 100, 2)
    result = submit_score(
        name=score.name,
        avatar=score.avatar,
        faction=score.faction,
        pnl_pct=pnl_pct,
        capital=result['capital'],
        pnl=pnl,
        stock_name=result['name'],
        games=1,
    )
    return result


@app.get("/api/faction-ranking")
async def api_get_faction_ranking():
    """获取五行阵营榜"""
    return get_faction_ranking()


@app.get("/api/factions")
async def api_get_factions():
    """获取所有阵营信息（含天赋）"""
    return {"factions": FACTIONS}


@app.get("/api/faction/{faction_id}")
async def api_get_faction(faction_id: str):
    """获取单个阵营详情"""
    trait = get_faction_trait(faction_id)
    if not trait:
        raise HTTPException(status_code=404, detail="阵营不存在")
    return trait


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("RiskPilot 后端服务启动中...")
    print(f"API 文档: http://localhost:8000/docs")
    print(f"前端页面: http://localhost:8000/ （如已配置静态文件）")
    has_llm_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    print(f"Agent 模式: {'真实 LLM' if has_llm_key else '预设离线演示（非真实 AI 推理）'}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
