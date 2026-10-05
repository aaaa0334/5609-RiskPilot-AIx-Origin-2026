"""
RiskPilot 数据下载脚本
======================
使用 AKShare 下载 5 只演示股票的历史行情、财务和公告数据，
保存为 JSON 快照，用于离线演示。

运行方式：
    pip install akshare
    python download_data.py
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import DEMO_STOCKS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "snapshots")


def download_stock_data(stock_code: str, stock_info: dict) -> dict:
    """下载单只股票的完整数据快照"""
    try:
        import akshare as ak
    except ImportError:
        print("错误：未安装 akshare，请运行 pip install akshare")
        raise

    print(f"  下载 {stock_code} {stock_info['name']}...")

    # 确定日期范围：最近 180 个交易日
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    # 1. 日线行情
    print(f"    - 日线行情...")
    try:
        # AKShare 的 A 股日线接口
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"  # 前复权
        )
        daily = []
        for _, row in df.iterrows():
            daily.append({
                "date": str(row.get("日期", "")),
                "open": float(row.get("开盘", 0)),
                "close": float(row.get("收盘", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "volume": float(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
            })
    except Exception as e:
        print(f"    警告：日线数据下载失败: {e}")
        daily = []

    if not daily:
        print(f"    错误：{stock_code} 没有获取到日线数据")
        return None

    latest_price = daily[-1]["close"]
    latest_date = daily[-1]["date"]

    # 2. 财务数据（简化版，使用主要财务指标）
    print(f"    - 财务数据...")
    fundamental = {}
    try:
        # 获取个股信息
        info_df = ak.stock_individual_info_em(symbol=stock_code)
        for _, row in info_df.iterrows():
            key = str(row.get("item", ""))
            value = row.get("value", "")
            fundamental[key] = str(value)
    except Exception as e:
        print(f"    警告：个股信息获取失败: {e}")

    # 3. 公告数据（最近 30 条）
    print(f"    - 公告数据...")
    news = []
    try:
        # 使用 AKShare 的公告接口
        notice_df = ak.stock_notice_report(symbol=stock_code)
        for _, row in notice_df.head(30).iterrows():
            news.append({
                "date": str(row.get("公告日期", "")),
                "title": str(row.get("公告标题", "")),
                "source": "交易所公告",
                "type": str(row.get("公告类型", "")),
            })
    except Exception as e:
        print(f"    警告：公告数据获取失败: {e}")

    # 构造快照
    snapshot = {
        "stock_code": stock_code,
        "stock_name": stock_info["name"],
        "industry": stock_info["industry"],
        "board": stock_info["board"],
        "latest_price": latest_price,
        "latest_date": latest_date,
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "AKShare（前复权历史数据）",
        "daily": daily,
        "fundamental": fundamental,
        "news": news,
    }

    return snapshot


def save_snapshot(stock_code: str, snapshot: dict):
    """保存数据快照为 JSON"""
    filepath = os.path.join(OUTPUT_DIR, f"{stock_code}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"    已保存: {filepath} ({len(snapshot['daily'])} 条日线)")


def main():
    print("=" * 60)
    print("RiskPilot 数据快照下载")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    success = 0
    failed = []

    for code, info in DEMO_STOCKS.items():
        try:
            snapshot = download_stock_data(code, info)
            if snapshot:
                save_snapshot(code, snapshot)
                success += 1
            else:
                failed.append(code)
        except Exception as e:
            print(f"  错误：{code} 下载失败: {e}")
            failed.append(code)

    print("=" * 60)
    print(f"下载完成：成功 {success} 只，失败 {len(failed)} 只")
    if failed:
        print(f"失败股票：{', '.join(failed)}")
        print("提示：失败的股票可以稍后重试，或使用 mock 模式演示")
    print("=" * 60)


if __name__ == "__main__":
    main()
