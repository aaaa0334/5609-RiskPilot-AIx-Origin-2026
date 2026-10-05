"""
RiskPilot 数据加载器
====================
从本地 JSON 快照加载股票数据，支持离线演示。
数据快照可以由 download_data.py 下载，也可以使用明确标注的合成演示数据。
"""

import json
import os
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")


# 演示股票池。合成数据使用"样本X"命名，避免把虚构财务数据归因给真实上市公司。
# 真实数据（中国平安）使用真实公司名称。
DEMO_STOCKS = {
    "600519": {"name": "样本 A", "industry": "消费", "board": "main"},
    "601318": {"name": "中国平安", "industry": "金融", "board": "main"},
    "600036": {"name": "样本 C", "industry": "银行", "board": "main"},
    "002594": {"name": "样本 D", "industry": "新能源", "board": "main"},
    "300750": {"name": "样本 E", "industry": "新能源", "board": "main"},
}

# The test expansion is shared with replay; no synthetic fallbacks are added.
_pool_path = os.path.join(DATA_DIR, '..', 'stock_pool.json')
if os.path.exists(_pool_path):
    with open(_pool_path, encoding='utf-8') as _pool_file:
        DEMO_STOCKS = json.load(_pool_file)

# 合成数据标注后缀，在列表和分析结果中统一显示
SYNTHETIC_LABEL = "（合成演示数据，非真实行情）"


def load_stock_snapshot(stock_code: str) -> Optional[dict]:
    """加载单只股票的数据快照"""
    filepath = os.path.join(DATA_DIR, f"{stock_code}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_available_stocks() -> list[dict]:
    """获取所有可用的演示股票列表"""
    available = []
    for code, info in DEMO_STOCKS.items():
        filepath = os.path.join(DATA_DIR, f"{code}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            synthetic = bool(data.get("is_synthetic", False))
            base_name = info["name"] if synthetic else data.get("stock_name", info["name"])
            display_name = base_name + SYNTHETIC_LABEL if synthetic else base_name
            available.append({
                "code": code,
                "name": display_name,
                "industry": info["industry"],
                "board": info["board"],
                "latest_price": data.get("latest_price", 0),
                "latest_date": data.get("latest_date", ""),
                "data_days": len(data.get("daily", [])),
                "is_synthetic": synthetic,
                "data_source": data.get("data_source", "未知来源"),
            })
    return available


def extract_risk_engine_input(snapshot: dict, stock_code: str) -> dict:
    """
    从数据快照中提取风险引擎所需的输入参数。
    返回当前价格、ATR、关键支撑位等。
    """
    from risk_engine import calculate_atr_from_closes, find_key_support

    daily = snapshot.get("daily", [])
    if not daily:
        raise ValueError(f"股票 {stock_code} 没有日线数据")

    # 取最近的数据
    closes = [d["close"] for d in daily]
    highs = [d["high"] for d in daily]
    lows = [d["low"] for d in daily]

    current_price = closes[-1]
    atr_14 = calculate_atr_from_closes(highs, lows, closes, 14)
    key_support = find_key_support(closes, 20)
    # At a new closing low the close-only reference equals the current price.
    # Use the observed intraday low, not an invented lower price.
    if key_support >= current_price:
        key_support = min(lows[-20:])

    # 计算技术指标（简化版，供 Agent 使用）
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
    ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else 0

    # 简化 RSI 计算
    rsi14 = _calc_rsi(closes, 14)

    # 涨跌幅
    change_20d = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
    change_60d = (closes[-1] / closes[-61] - 1) * 100 if len(closes) >= 61 else 0

    # 目标价：近20日高点（作为保守的上行目标参考）
    recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    # 确保目标价高于当前价
    target_price = max(recent_high, current_price * 1.03)

    # 证据包信息
    evidence_pack_info = _extract_evidence_pack_info(snapshot)

    return {
        "stock_code": stock_code,
        "stock_name": (
            (DEMO_STOCKS.get(stock_code, {}).get("name", "合成演示样本") + SYNTHETIC_LABEL)
            if snapshot.get("is_synthetic", False)
            else snapshot.get("stock_name", DEMO_STOCKS.get(stock_code, {}).get("name", ""))
        ),
        "current_price": current_price,
        "target_price": round(target_price, 2),
        "atr_14": atr_14,
        "key_support": key_support,
        "board": DEMO_STOCKS.get(stock_code, {}).get("board", "main"),
        "technical_indicators": {
            "ma5": round(ma5, 2),
            "ma10": round(ma10, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "rsi14": round(rsi14, 2),
            "change_20d": round(change_20d, 2),
            "change_60d": round(change_60d, 2),
            "recent_high": round(recent_high, 2),
        },
        "daily_data": daily[-120:],  # 最近 120 个交易日
        "fundamental": snapshot.get("fundamental", {}),
        "news": snapshot.get("news", []),
        "official_documents": snapshot.get("official_documents", []),
        "evidence_pack_info": evidence_pack_info,
        "snapshot_date": snapshot.get("snapshot_date", ""),
        "analysis_cutoff": snapshot.get("analysis_cutoff", snapshot.get("snapshot_date", "")),
        "retrieved_at": snapshot.get("retrieved_at", ""),
        "evidence_pack": snapshot.get("evidence_pack", ""),
        "data_source": snapshot.get("data_source", "AKShare（历史数据快照）"),
        "is_synthetic": bool(snapshot.get("is_synthetic", False)),
    }


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    """简化版 RSI 计算"""
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _extract_evidence_pack_info(snapshot: dict) -> dict:
    """从快照中提取证据包信息，用于前端展示数据可追溯性"""
    import os
    info = {
        "has_evidence_pack": False,
        "official_documents": [],
        "data_source": snapshot.get("data_source", ""),
        "snapshot_date": snapshot.get("snapshot_date", ""),
        "retrieved_at": snapshot.get("retrieved_at", ""),
        "evidence_pack_path": snapshot.get("evidence_pack", ""),
        "is_synthetic": bool(snapshot.get("is_synthetic", False)),
    }

    # 从快照中提取官方文档列表
    official_docs = snapshot.get("official_documents", [])
    if official_docs and isinstance(official_docs, list):
        for doc in official_docs:
            if isinstance(doc, dict):
                info["official_documents"].append({
                    "title": doc.get("title", doc.get("document_title", "未命名文档")),
                    "date": doc.get("published_date", doc.get("date", "")),
                    "source": doc.get("source", ""),
                    "type": doc.get("type", "官方公告"),
                })

    # 尝试从证据包目录读取源清单和哈希
    evidence_path = snapshot.get("evidence_pack", "")
    if evidence_path:
        full_path = os.path.join(
            os.path.dirname(__file__), "..", evidence_path
        )
        source_manifest = os.path.join(full_path, "source_manifest.json")
        hash_manifest = os.path.join(full_path, "sha256_manifest.json")
        if os.path.exists(source_manifest):
            try:
                with open(source_manifest, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                info["has_evidence_pack"] = True
                info["akshare_version"] = manifest.get("akshare_version", "")
                info["sources"] = [
                    {
                        "dataset": s.get("dataset", ""),
                        "interface": s.get("interface", ""),
                        "upstream": s.get("upstream", ""),
                        "available": s.get("available", True),
                    }
                    for s in manifest.get("sources", [])
                ]
            except Exception:
                pass
        if os.path.exists(hash_manifest):
            try:
                with open(hash_manifest, "r", encoding="utf-8") as f:
                    hm = json.load(f)
                info["hash_algorithm"] = hm.get("algorithm", "SHA-256")
                info["hash_generated_at"] = hm.get("generated_at", "")
                info["file_count"] = len(hm.get("files", {}))
            except Exception:
                pass

    # 如果没有证据包但有公告数据，从公告中提取
    if not info["official_documents"]:
        news = snapshot.get("news", [])
        if news and isinstance(news, list):
            for item in news[:5]:
                if isinstance(item, dict):
                    info["official_documents"].append({
                        "title": item.get("title", ""),
                        "date": item.get("date", ""),
                        "source": item.get("source", "公告"),
                        "type": "公告",
                    })

    pool_manifest = snapshot.get('historical_pool_manifest')
    if pool_manifest:
        from pathlib import Path
        import hashlib
        manifest_path = Path(__file__).resolve().parents[1] / pool_manifest
        pool_data = json.loads(manifest_path.read_text(encoding='utf-8'))
        for filename, expected in pool_data['sha256'].items():
            evidence_path = manifest_path.parent / filename
            raw = evidence_path.read_bytes()
            candidates = [raw]
            if evidence_path.suffix.lower() in {'.csv', '.json'}:
                # Git may check text out as CRLF on Windows and LF on Linux/Render.
                lf = raw.replace(b'\r\n', b'\n')
                candidates.extend((lf, lf.replace(b'\n', b'\r\n')))
            if not any(hashlib.sha256(item).hexdigest() == expected for item in candidates):
                raise ValueError('历史样本文件完整性校验失败')
        info.update(has_evidence_pack=True, hash_algorithm='SHA-256',
                    file_count=len(pool_data['sha256']), evidence_pack_path=pool_manifest,
                    limitations=snapshot.get('data_limitations', ''),
                    source_urls=pool_data.get('source_urls', []))
    return info
