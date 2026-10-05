"""将人工核对的官方财报结构化字段写入证据快照和激活快照。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_evidence_pack import write_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ingest(pack_relative_path: str) -> list[Path]:
    pack_dir = (PROJECT_ROOT / pack_relative_path).resolve()
    if PROJECT_ROOT.resolve() not in pack_dir.parents:
        raise ValueError("证据包目录超出项目范围")

    facts_path = pack_dir / "normalized" / "fundamental_facts.json"
    snapshot_path = pack_dir / "normalized" / "riskpilot_snapshot.json"
    documents_path = pack_dir / "official_documents.json"
    for path in (facts_path, snapshot_path, documents_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    documents = json.loads(documents_path.read_text(encoding="utf-8"))
    if facts["stock_code"] != snapshot["stock_code"]:
        raise ValueError("结构化财报与行情快照股票代码不一致")

    snapshot["fundamental"] = facts
    snapshot["official_documents"] = documents.get("documents", [])
    snapshot["data_source"] = (
        "AKShare固定历史行情（上游：东方财富）+ 巨潮资讯官方公告原文"
    )
    write_json(snapshot_path, snapshot)

    active_path = PROJECT_ROOT / "data" / "snapshots" / f"{snapshot['stock_code']}.json"
    write_json(active_path, snapshot)
    return [snapshot_path, active_path]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="写入官方财报结构化字段")
    parser.add_argument("pack", help="相对于项目根目录的证据包目录")
    args = parser.parse_args()
    for output in ingest(args.pack):
        print(output)
