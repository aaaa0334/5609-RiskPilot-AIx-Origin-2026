"""真实演示基础设施的离线回归测试。"""

import json
import sys
import tempfile
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from agents import _real_failure, get_agent_analyses
from build_evidence_pack import sha256_file, write_json


def test_hash_and_json_writer():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.json"
        write_json(path, {"中文": "可追溯", "value": 1})
        assert json.loads(path.read_text(encoding="utf-8"))["中文"] == "可追溯"
        assert len(sha256_file(path)) == 64


def test_real_failure_is_not_success():
    result = _real_failure("test")
    assert result["mode"] == "real"
    assert result["run_status"] == "FAILED"


def test_preset_is_explicitly_labelled():
    result = get_agent_analyses(
        "000000",
        {"is_synthetic": True, "stock_name": "合成样本", "technical_indicators": {}},
        mode="preset_demo",
    )
    assert result["mode"] == "preset_demo"
    assert result["run_status"] == "PRESET_DEMO"


if __name__ == "__main__":
    test_hash_and_json_writer()
    test_real_failure_is_not_success()
    test_preset_is_explicitly_labelled()
    print("3 demo integrity tests passed")
