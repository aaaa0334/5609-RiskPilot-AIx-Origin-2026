"""重新计算指定证据包内所有材料的 SHA-256。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from build_evidence_pack import sha256_file, write_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def refresh(pack_relative_path: str) -> Path:
    pack_dir = (PROJECT_ROOT / pack_relative_path).resolve()
    if PROJECT_ROOT.resolve() not in pack_dir.parents or not pack_dir.is_dir():
        raise ValueError("证据包目录不存在或超出项目范围")

    excluded = {"sha256_manifest.json", "evidence_pack_id.txt"}
    files = sorted(
        path for path in pack_dir.rglob("*") if path.is_file() and path.name not in excluded
    )
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    manifest = {
        "algorithm": "SHA-256",
        "generated_at": generated_at,
        "files": {
            str(path.relative_to(pack_dir)).replace("\\", "/"): sha256_file(path)
            for path in files
        },
    }
    manifest_path = pack_dir / "sha256_manifest.json"
    write_json(manifest_path, manifest)
    (pack_dir / "evidence_pack_id.txt").write_text(
        sha256_file(manifest_path) + "\n", encoding="ascii"
    )
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="刷新 RiskPilot 证据包哈希")
    parser.add_argument("pack", help="相对于项目根目录的证据包目录")
    args = parser.parse_args()
    print(refresh(args.pack))
