"""构建可追溯的 A 股历史数据证据包。

该脚本只获取固定日期范围的历史数据，不获取实时行情。它同时保存：
1. AKShare 原始 CSV；
2. RiskPilot 标准化 JSON；
3. 接口、参数、版本、获取时间和上游来源清单；
4. 每个文件的 SHA-256。

示例：
    python build_evidence_pack.py --code 601318 --name 中国平安 \
        --industry 保险 --start 20250901 --end 20260831 --activate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = PROJECT_ROOT / "data" / "evidence"
SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_daily(frame) -> list[dict]:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "date": str(row.get("日期", "")),
                "open": float(row.get("开盘", 0)),
                "close": float(row.get("收盘", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "volume": float(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
            }
        )
    return rows


def normalize_fundamental(frame) -> dict:
    result = {}
    for _, row in frame.iterrows():
        key = str(row.get("item", "")).strip()
        if key:
            result[key] = str(row.get("value", ""))
    return result


def normalize_notices(frame, limit: int = 30) -> list[dict]:
    notices = []
    for _, row in frame.head(limit).iterrows():
        notices.append(
            {
                "date": str(row.get("公告时间", row.get("公告日期", ""))),
                "title": str(row.get("公告标题", "")),
                "type": str(row.get("公告类型", "公司公告")),
                "source": "巨潮资讯（经 AKShare 公告接口获取）",
                "source_url": str(row.get("公告链接", row.get("网址", ""))),
            }
        )
    return notices


def build_pack(args: argparse.Namespace) -> Path:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("未安装 AKShare，请先运行 python -m pip install -r requirements.txt") from exc

    retrieved_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    cutoff = datetime.strptime(args.end, "%Y%m%d").strftime("%Y-%m-%d")
    pack_dir = EVIDENCE_ROOT / args.code / cutoff
    raw_dir = pack_dir / "raw"
    normalized_dir = pack_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    price_frame = ak.stock_zh_a_hist(
        symbol=args.code,
        period="daily",
        start_date=args.start,
        end_date=args.end,
        adjust=args.adjust,
    )
    if price_frame.empty:
        raise RuntimeError("历史行情接口返回空数据，请检查代码、日期或网络连接")
    price_frame.to_csv(raw_dir / "price_daily.csv", index=False, encoding="utf-8-sig")

    try:
        fundamental_frame = ak.stock_individual_info_em(symbol=args.code)
    except Exception:
        fundamental_frame = None
    if fundamental_frame is not None and not fundamental_frame.empty:
        fundamental_frame.to_csv(
            raw_dir / "fundamental_index.csv", index=False, encoding="utf-8-sig"
        )

    try:
        notice_frame = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=args.code,
            market="沪深京",
            category="",
            start_date=args.start,
            end_date=args.end,
        )
    except Exception:
        notice_frame = None
    if notice_frame is not None and not notice_frame.empty:
        notice_frame.to_csv(raw_dir / "announcement_index.csv", index=False, encoding="utf-8-sig")

    daily = normalize_daily(price_frame)
    fundamental = (
        normalize_fundamental(fundamental_frame)
        if fundamental_frame is not None and not fundamental_frame.empty
        else {}
    )
    notices = (
        normalize_notices(notice_frame)
        if notice_frame is not None and not notice_frame.empty
        else []
    )

    snapshot = {
        "stock_code": args.code,
        "stock_name": args.name,
        "industry": args.industry,
        "board": "main",
        "latest_price": daily[-1]["close"],
        "latest_date": daily[-1]["date"],
        "snapshot_date": cutoff,
        "analysis_cutoff": cutoff,
        "retrieved_at": retrieved_at,
        "data_source": "AKShare 固定历史快照（行情上游：东方财富）",
        "is_synthetic": False,
        "evidence_pack": str(pack_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "daily": daily,
        "fundamental": fundamental,
        "news": notices,
    }
    normalized_path = normalized_dir / "riskpilot_snapshot.json"
    write_json(normalized_path, snapshot)

    manifest = {
        "schema_version": "1.0.0",
        "stock_code": args.code,
        "stock_name": args.name,
        "analysis_cutoff": cutoff,
        "retrieved_at": retrieved_at,
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "sources": [
            {
                "dataset": "daily_price",
                "library": "AKShare",
                "interface": "stock_zh_a_hist",
                "upstream": "东方财富",
                "parameters": {
                    "symbol": args.code,
                    "period": "daily",
                    "start_date": args.start,
                    "end_date": args.end,
                    "adjust": args.adjust,
                },
                "raw_file": "raw/price_daily.csv",
            },
            {
                "dataset": "company_profile",
                "library": "AKShare",
                "interface": "stock_individual_info_em",
                "upstream": "东方财富",
                "raw_file": "raw/fundamental_index.csv",
                "available": bool(fundamental),
            },
            {
                "dataset": "announcement_index",
                "library": "AKShare",
                "interface": "stock_zh_a_disclosure_report_cninfo",
                "upstream": "巨潮资讯；正式报告需逐条核对并保存原始公告 PDF",
                "parameters": {
                    "symbol": args.code,
                    "market": "沪深京",
                    "category": "",
                    "start_date": args.start,
                    "end_date": args.end,
                },
                "raw_file": "raw/announcement_index.csv",
                "available": bool(notices),
            },
        ],
        "normalization": {
            "output": "normalized/riskpilot_snapshot.json",
            "notes": "原始CSV保持不变；标准化JSON只做字段映射。",
        },
        "usage_boundary": "研究教育、产品展示、固定历史快照；非实时行情，不自动交易。",
    }
    manifest_path = pack_dir / "source_manifest.json"
    write_json(manifest_path, manifest)

    document_template = {
        "instructions": "将官方PDF放入raw目录，并为每份文件填写真实标题、日期和原始URL。",
        "documents": [],
    }
    official_documents_path = pack_dir / "official_documents.json"
    if not official_documents_path.exists():
        write_json(official_documents_path, document_template)

    generated_manifest_names = {"sha256_manifest.json", "evidence_pack_id.txt"}
    tracked_files = sorted(
        path
        for path in pack_dir.rglob("*")
        if path.is_file() and path.name not in generated_manifest_names
    )
    hashes = {
        str(path.relative_to(pack_dir)).replace("\\", "/"): sha256_file(path)
        for path in tracked_files
    }
    hash_manifest = {
        "algorithm": "SHA-256",
        "generated_at": retrieved_at,
        "files": hashes,
    }
    hash_path = pack_dir / "sha256_manifest.json"
    write_json(hash_path, hash_manifest)
    (pack_dir / "evidence_pack_id.txt").write_text(
        sha256_file(hash_path) + "\n", encoding="ascii"
    )

    if args.activate:
        SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        target = SNAPSHOT_ROOT / f"{args.code}.json"
        if target.exists():
            backup = target.with_suffix(f".backup-{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
            shutil.copy2(target, backup)
        shutil.copy2(normalized_path, target)

    return pack_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 RiskPilot 可追溯历史数据证据包")
    parser.add_argument("--code", required=True, help="六位 A 股代码")
    parser.add_argument("--name", required=True, help="股票名称")
    parser.add_argument("--industry", default="未填写", help="行业")
    parser.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", required=True, help="结束日期 YYYYMMDD")
    parser.add_argument("--adjust", choices=("", "qfq", "hfq"), default="qfq")
    parser.add_argument("--activate", action="store_true", help="备份并替换当前演示快照")
    return parser.parse_args()


if __name__ == "__main__":
    output = build_pack(parse_args())
    print(f"证据包已生成：{output}")
    print("请补充 official_documents.json，并核对每份官方公告原文。")
