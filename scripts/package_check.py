"""Create an explicit, inspectable package; never include local state or scenario artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

ROOT_FILES = {"agent.py", "agent.json", "pyproject.toml", "uv.lock", ".python-version", ".gitignore", ".env.example", "README.md"}
ROOT_DIRS = {"src", "docs", "scripts", "tests"}
EXCLUDED = {"__pycache__", ".pytest_cache", ".hypothesis", ".ruff_cache"}


def package_files(root):
    files = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if rel.parts[0] not in ROOT_FILES | ROOT_DIRS or any(part in EXCLUDED for part in rel.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks are not permitted: {rel}")
        if path.is_file() and path.suffix not in {".pyc", ".png", ".pdf", ".zip", ".log", ".jsonl"}:
            files.append(path)
    return sorted(files)


def check(root, output):
    manifest = json.loads((root / "agent.json").read_text())
    for key in ("setup", "run"):
        if not isinstance(manifest.get(key), list) or not all(isinstance(x, str) for x in manifest[key]):
            raise ValueError(f"agent.json {key} must be an argv array")
    if manifest.get("browsers") not in range(1, 5) or manifest.get("models") != ["qwen"]:
        raise ValueError("Expected 1..4 browsers and Qwen-only warmup")
    files = package_files(root)
    patterns = [r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", r"atp_[A-Za-z0-9_-]{24,}"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        if any(re.search(pattern, text) for pattern in patterns):
            raise ValueError(f"Potential credential in {path.relative_to(root)}")
        if path.is_relative_to(root / "src") and re.search(r"atira-rfq-.*\.kyora\.run", text):
            raise ValueError("Public challenge website constant in runtime code")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    size = output.stat().st_size
    if size > 20_000_000:
        raise ValueError("Package exceeds 20 MB compressed")
    with tarfile.open(output) as archive:
        assert "agent.json" in archive.getnames()
        assert all(member.isfile() for member in archive.getmembers())
    return {"files": [str(x.relative_to(root)) for x in files], "compressed_bytes": size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "archive": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, default=Path("dist/agent.tar.gz"))
    args = parser.parse_args()
    print(json.dumps(check(args.root.resolve(), args.out.resolve()), indent=2))
