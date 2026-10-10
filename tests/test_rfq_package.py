import importlib.util
import json
from pathlib import Path
import tarfile


def test_package_is_allowlisted_and_manifest_points_to_installed_module(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("package_rfq", root / "scripts/package_rfq.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = module.build(root, tmp_path / "agent.tar.gz")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert {"agent.json", "requirements-rfq.txt", "src/hackathon_toolkit/rfq/runtime.py"} <= set(names)
        assert all(name.startswith("src/") or name in {"agent.json", "requirements-rfq.txt", "README.md",
                   "pyproject.toml", "docs/RFQ_AGENT.md"} for name in names)
        assert not any(name.startswith(("tests/", "examples/", ".env", ".rfq-artifacts/")) for name in names)
        manifest = json.load(tar.extractfile("agent.json"))
        assert manifest["run"] == [".venv/bin/python", "-m", "hackathon_toolkit.rfq.runtime"]
        assert manifest["browsers"] == 4
        assert manifest["models"] == ["qwen", "clef"]
        assert "src/hackathon_toolkit/rfq/clef.py" in set(names)
