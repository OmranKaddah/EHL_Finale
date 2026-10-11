"""Build the submission tarball from an explicit allowlist.

Usage: uv run --python 3.12 --frozen python scripts/package.py [--out dist]
Only the run manifest, the frozen dependency files and the runtime source are
packaged. Anything else (tests, docs, notes, captured sessions, artifacts, .env)
is refused by path, not merely skipped.
"""
import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT_FILES = ("agent.json", "pyproject.toml", "uv.lock")
SOURCE_DIR = "src/rfq_agent"
MAX_BYTES = 20 * 1024 * 1024
ALLOWED = re.compile(r"^(agent\.json|pyproject\.toml|uv\.lock|src/rfq_agent/[A-Za-z_][A-Za-z0-9_]*\.py)$")


def check_path(path: str) -> str:
    if not ALLOWED.fullmatch(path):
        raise ValueError(f"not on the package allowlist: {path}")
    return path


def build(root: Path, out_dir: Path) -> tuple[Path, dict]:
    paths = [*ROOT_FILES, *sorted(f"{SOURCE_DIR}/{item.name}" for item in (root / SOURCE_DIR).glob("*.py"))]
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "rfq-agent.tar.gz"
    files = []
    with tarfile.open(archive, "w:gz") as tar:
        for path in map(check_path, paths):
            source = root / path
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"allowlisted file is missing or not a regular file: {path}")
            data = source.read_bytes()
            files.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            tar.add(source, arcname=path, recursive=False)
    size = archive.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"package is {size} bytes; the limit is {MAX_BYTES}")
    return archive, {"archive": str(archive), "compressed_bytes": size, "files": files}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist")
    arguments = parser.parse_args()
    _, manifest = build(Path(__file__).resolve().parents[1], Path(arguments.out))
    json.dump(manifest, sys.stdout, indent=2)
    print()
