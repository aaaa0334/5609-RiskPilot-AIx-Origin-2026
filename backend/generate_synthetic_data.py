"""
RiskPilot 合成数据生成器
========================
当 AKShare 无法连接时，生成与 mock 分析匹配的合成历史数据快照。
该工具使用固定历史数据结构和合成数据支持离线功能验证。
数据参数与 agents.py 中的 mock 分析保持一致。
"""

import json
import os
import random
import math
from datetime import datetime, timedelta

sys_path = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(sys_path, "..", "data", "snapshots")

# 每只股票的合成参数（与 mock 分析中的价格、ATR 等匹配）
STOCK_PARAMS = {
    "600519": {
        "name": "贵州茅台", "industry": "白酒", "board": "main",
        "current_price": 1685.0, "atr_14": 28.5, "ma5": 1680, "ma10": 1672,
        "ma20": 1655, "ma60": 1620, "rsi14": 58,
        "trend": "up", "volatility": 0.017,  # 日波动率约 1.7%
        "avg_volume": 28000,  # 手
    },
    "601318": {
        "name": "中国平安", "industry": "保险", "board": "main",
        "current_price": 45.20, "atr_14": 1.15, "ma5": 45.0, "ma10": 45.3,
        "ma20": 45.8, "ma60": 44.5, "rsi14": 45,
        "trend": "sideways", "volatility": 0.025,
        "avg_volume": 450000,
    },
    "600036": {
        "name": "招商银行", "industry": "银行", "board": "main",
        "current_price": 38.50, "atr_14": 0.65, "ma5": 38.2, "ma10": 37.8,
        "ma20": 37.5, "ma60": 36.8, "rsi14": 55,
        "trend": "up", "volatility": 0.017,
        "avg_volume": 300000,
    },
    "300750": {
        "name": "宁德时代", "industry": "新能源", "board": "gem",
        "current_price": 195.0, "atr_14": 8.5, "ma5": 198, "ma10": 202,
        "ma20": 208, "ma60": 220, "rsi14": 32,
        "trend": "down", "volatility": 0.044,
        "avg_volume": 1200000,
    },
    "002594": {
        "name": "比亚迪", "industry": "新能源汽车", "board": "sme",
        "current_price": 265.0, "atr_14": 7.2, "ma5": 262, "ma10": 258,
        "ma20": 252, "ma60": 240, "rsi14": 62,
        "trend": "up", "volatility": 0.027,
        "avg_volume": 850000,
    },
}

# 合成财务数据
FUNDAMENTAL_DATA = {
    "600519": {
        "营业收入(2026Q2)": "816亿元", "营收同比": "+15.2%",
        "归母净利润(2026Q2)": "395亿元", "净利润同比": "+16.8%",
        "扣非净利润": "390亿元", "经营现金流": "320亿元",
        "毛利率": "91.5%", "净利率": "48.4%", "ROE": "16.2%",
        "资产负债率": "18.5%", "PE(TTM)": "28.5倍", "PB": "9.2倍",
        "股息率": "1.8%", "总股本": "12.56亿股",
    },
    "601318": {
        "营业收入(2026Q2)": "4520亿元", "营收同比": "+8.3%",
        "归母净利润(2026Q2)": "820亿元", "净利润同比": "+12.5%",
        "扣非净利润": "805亿元", "经营现金流": "1200亿元",
        "净利率": "18.1%", "ROE": "11.5%",
        "资产负债率": "89.2%", "PE(TTM)": "8.2倍", "PB": "0.95倍",
        "股息率": "5.2%", "新业务价值率": "32%",
    },
    "600036": {
        "营业收入(2026Q2)": "1750亿元", "营收同比": "+2.1%",
        "归母净利润(2026Q2)": "780亿元", "净利润同比": "+5.8%",
        "扣非净利润": "775亿元",
        "净利率": "44.6%", "ROE": "15.8%",
        "资产负债率": "91.2%", "PE(TTM)": "6.5倍", "PB": "1.05倍",
        "股息率": "5.8%", "净息差": "1.95%", "不良贷款率": "0.95%",
    },
    "300750": {
        "营业收入(2026Q2)": "1850亿元", "营收同比": "+22%",
        "归母净利润(2026Q2)": "210亿元", "净利润同比": "+18%",
        "扣非净利润": "200亿元", "经营现金流": "350亿元",
        "毛利率": "22.5%", "净利率": "11.4%", "ROE": "12.8%",
        "资产负债率": "65%", "PE(TTM)": "22倍", "PB": "4.5倍",
        "股息率": "0.5%", "市占率": "37%",
    },
    "002594": {
        "营业收入(2026Q2)": "3200亿元", "营收同比": "+28%",
        "归母净利润(2026Q2)": "165亿元", "净利润同比": "+35%",
        "扣非净利润": "155亿元", "经营现金流": "420亿元",
        "毛利率": "20.8%", "净利率": "5.2%", "ROE": "14.5%",
        "资产负债率": "72%", "PE(TTM)": "25倍", "PB": "5.8倍",
        "股息率": "0.3%", "月销量": "35万辆",
    },
}

# 合成公告新闻
NEWS_DATA = {
    "600519": [
        {"date": "2026-08-28", "title": "2026年半年度报告", "source": "上交所公告", "type": "定期报告"},
        {"date": "2026-08-20", "title": "2026年第一次临时股东大会决议", "source": "上交所公告", "type": "股东大会"},
        {"date": "2026-08-15", "title": "接待机构调研公告", "source": "公司公告", "type": "机构调研"},
        {"date": "2026-08-10", "title": "白酒行业半年报整体回暖", "source": "证券时报", "type": "行业新闻"},
        {"date": "2026-07-28", "title": "2025年度分红派息实施公告", "source": "上交所公告", "type": "分红"},
    ],
    "601318": [
        {"date": "2026-08-27", "title": "2026年半年度报告", "source": "上交所公告", "type": "定期报告"},
        {"date": "2026-08-22", "title": "前7月保费收入公告", "source": "上交所公告", "type": "经营数据"},
        {"date": "2026-08-05", "title": "保险业新会计准则实施首年利润口径变化", "source": "中国证券报", "type": "行业新闻"},
        {"date": "2026-07-30", "title": "2025年度股东大会决议", "source": "上交所公告", "type": "股东大会"},
    ],
    "600036": [
        {"date": "2026-08-26", "title": "2026年半年度报告", "source": "上交所公告", "type": "定期报告"},
        {"date": "2026-08-20", "title": "商业银行净息差企稳迹象显现", "source": "金融时报", "type": "行业新闻"},
        {"date": "2026-08-15", "title": "2025年度分红派息", "source": "上交所公告", "type": "分红"},
    ],
    "300750": [
        {"date": "2026-08-28", "title": "2026年半年度报告", "source": "深交所公告", "type": "定期报告"},
        {"date": "2026-08-25", "title": "动力电池价格战持续，碳酸锂价格新低", "source": "财联社", "type": "行业新闻"},
        {"date": "2026-08-20", "title": "海外工厂建设进展更新", "source": "深交所公告", "type": "项目进展"},
        {"date": "2026-08-12", "title": "接待机构调研，讨论产能利用率", "source": "公司公告", "type": "机构调研"},
    ],
    "002594": [
        {"date": "2026-08-29", "title": "8月新能源汽车销量公告", "source": "深交所公告", "type": "经营数据"},
        {"date": "2026-08-26", "title": "2026年半年度报告", "source": "深交所公告", "type": "定期报告"},
        {"date": "2026-08-22", "title": "新车型发布，智能化升级", "source": "公司官网", "type": "产品发布"},
        {"date": "2026-08-18", "title": "新能源汽车出口再创新高", "source": "经济观察报", "type": "行业新闻"},
    ],
}


def generate_daily_data(params: dict, days: int = 180) -> list:
    """
    生成合成日线数据。
    使用几何布朗运动 + 趋势偏移，确保最终价格和 ATR 与目标参数匹配。
    """
    random.seed(hash(params["name"]) % 2**31)  # 可复现

    current = params["current_price"]
    vol = params["volatility"]
    trend_map = {"up": 0.0008, "down": -0.001, "sideways": 0.0001}
    drift = trend_map.get(params["trend"], 0.0002)

    # 从当前价格倒推生成历史数据
    prices = [current]
    for i in range(days - 1):
        # 倒推：前一天的价格 = 后一天 / (1 + 日收益率)
        daily_return = random.gauss(drift, vol)
        prev_price = prices[-1] / (1 + daily_return)
        prev_price = max(prev_price, current * 0.3)  # 防止极端值
        prices.append(prev_price)

    prices.reverse()  # 现在是从旧到新

    # 生成 OHLCV
    daily = []
    base_date = datetime.now() - timedelta(days=days * 1.5)  # 粗略，跳过周末
    trading_days = []
    d = base_date
    while len(trading_days) < days:
        if d.weekday() < 5:  # 工作日
            trading_days.append(d)
        d += timedelta(days=1)

    for i in range(days):
        close = prices[i]
        # 生成 high/low/open
        daily_vol = close * vol * 0.6
        high = close + abs(random.gauss(0, daily_vol))
        low = close - abs(random.gauss(0, daily_vol))
        open_price = close + random.gauss(0, daily_vol * 0.5)
        open_price = max(min(open_price, high), low)

        volume = int(params["avg_volume"] * random.uniform(0.6, 1.5))
        amount = volume * close * 100  # 成交额

        change_pct = 0
        if i > 0:
            change_pct = (close / prices[i - 1] - 1) * 100

        daily.append({
            "date": trading_days[i].strftime("%Y-%m-%d"),
            "open": round(open_price, 2),
            "close": round(close, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "volume": volume,
            "amount": round(amount, 2),
            "change_pct": round(change_pct, 2),
        })

    return daily


def generate_snapshot(stock_code: str) -> dict:
    """生成单只股票的完整数据快照"""
    params = STOCK_PARAMS[stock_code]
    daily = generate_daily_data(params)

    return {
        "stock_code": stock_code,
        "stock_name": params["name"],
        "industry": params["industry"],
        "board": params["board"],
        "latest_price": params["current_price"],
        "latest_date": daily[-1]["date"],
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "合成演示数据（基于公开市场特征生成，非真实行情）",
        "is_synthetic": True,
        "daily": daily,
        "fundamental": FUNDAMENTAL_DATA.get(stock_code, {}),
        "news": NEWS_DATA.get(stock_code, []),
    }


def main():
    print("=" * 60)
    print("RiskPilot 合成数据生成（用于离线演示）")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for code, params in STOCK_PARAMS.items():
        print(f"  生成 {code} {params['name']}...")
        snapshot = generate_snapshot(code)
        filepath = os.path.join(OUTPUT_DIR, f"{code}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        # 验证 ATR
        closes = [d["close"] for d in snapshot["daily"]]
        highs = [d["high"] for d in snapshot["daily"]]
        lows = [d["low"] for d in snapshot["daily"]]

        # 简单 ATR 验证
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
        atr = sum(tr_list[-14:]) / 14 if len(tr_list) >= 14 else 0

        print(f"    最新价: {snapshot['latest_price']}, 实际ATR(14): {atr:.2f}, "
              f"目标ATR: {params['atr_14']}, 日线数: {len(snapshot['daily'])}")
        print(f"    已保存: {filepath}")

    print("=" * 60)
    print("合成数据生成完成！")
    print("注意：这些数据是合成的演示数据，仅用于离线功能验证。")
    print("正式使用时请用 download_data.py 下载真实 AKShare 数据。")
    print("=" * 60)


if __name__ == "__main__":
    main()
