"""保存真实 LLM 全链路演示的可核验运行证据。"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from risk_engine import RiskEngineOutput


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_ROOT = PROJECT_ROOT / "data" / "demo_runs"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def archive_real_run(
    request_data: dict,
    stock_data: dict,
    agent_analyses: dict,
    risk_output: RiskEngineOutput,
    report: dict,
    report_markdown: str,
) -> str:
    """归档输入、数据来源、三次模型调用、风险结果和最终报告；绝不保存 API Key。"""
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    run_dir = RUN_ROOT / f"{stamp}_{request_data['stock_code']}"
    run_dir.mkdir(parents=True, exist_ok=False)

    _write_json(run_dir / "input.json", request_data)
    _write_json(run_dir / "stock_data_used.json", stock_data)
    _write_json(run_dir / "agent_run.json", agent_analyses)
    _write_json(run_dir / "risk_engine_output.json", asdict(risk_output))
    _write_json(run_dir / "final_report.json", report)
    (run_dir / "final_report.md").write_text(report_markdown, encoding="utf-8")

    for name in ("technical", "fundamental", "news"):
        (run_dir / f"agent_{name}_output.txt").write_text(
            agent_analyses.get(name, ""), encoding="utf-8"
        )

    evidence_relative = stock_data.get("evidence_pack", "")
    evidence_files = {}
    if evidence_relative:
        evidence_dir = (PROJECT_ROOT / evidence_relative).resolve()
        if PROJECT_ROOT.resolve() in evidence_dir.parents:
            for filename in (
                "source_manifest.json",
                "sha256_manifest.json",
                "evidence_pack_id.txt",
                "official_documents.json",
            ):
                source = evidence_dir / filename
                if source.is_file():
                    shutil.copy2(source, run_dir / filename)
                    evidence_files[filename] = filename

    calls = agent_analyses.get("calls", {})
    run_manifest = {
        "schema_version": "1.0.0",
        "run_type": "REAL_LLM_FULL_CHAIN",
        "run_status": agent_analyses.get("run_status"),
        "started_at": agent_analyses.get("started_at"),
        "completed_at": agent_analyses.get("completed_at"),
        "model": agent_analyses.get("model"),
        "provider": agent_analyses.get("provider"),
        "response_ids": {name: item.get("response_id") for name, item in calls.items()},
        "usage": {name: item.get("usage") for name, item in calls.items()},
        "evidence_pack": evidence_relative,
        "copied_evidence_files": evidence_files,
        "report_hash": report.get("report_hash"),
        "security_note": "本目录不保存 OPENAI_API_KEY 或其他密钥。",
    }
    _write_json(run_dir / "run_manifest.json", run_manifest)
    return str(run_dir.relative_to(PROJECT_ROOT)).replace("\\", "/")
