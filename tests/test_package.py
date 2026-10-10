import json
import os
import runpy
import tarfile
from pathlib import Path


def test_archive_is_reproducible_and_excludes_local_state(tmp_path):
    package = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/package_check.py"))
    (tmp_path / "agent.json").write_text(json.dumps({"setup": ["uv", "sync"], "run": ["python", "agent.py"],
                                                   "models": ["qwen"], "browsers": 1}))
    source = tmp_path / "agent.py"
    source.write_text("print('synthetic')\n")
    (tmp_path / ".env").write_text("FAKE_SECRET=excluded\n")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "trace.jsonl").write_text("excluded\n")
    first = package["check"](tmp_path, tmp_path / "first.tar.gz")
    os.utime(source, (1_000_000, 1_000_000))
    second = package["check"](tmp_path, tmp_path / "second.tar.gz")
    assert first["sha256"] == second["sha256"]
    with tarfile.open(first["archive"]) as archive:
        assert set(archive.getnames()) == {"agent.json", "agent.py"}
        assert all(member.isfile() and member.mtime == 0 for member in archive.getmembers())
