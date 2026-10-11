"""The submitted package is an explicit allowlist: manifest, frozen deps, runtime source."""
import importlib.util
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"(^|/)(tests?|docs|artifacts|dist|\.entire|\.claude|\.codex|\.git|\.venv|__pycache__)(/|$)"
                       r"|(^|/)\.env|\.md$|\.jsonl$|\.db$|\.sqlite$", re.IGNORECASE)


def load_packager():
    spec = importlib.util.spec_from_file_location("package_script", ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.archive, cls.manifest = load_packager().build(ROOT, Path(cls.tmp.name))
        with tarfile.open(cls.archive) as tar:
            cls.names = sorted(member.name for member in tar.getmembers() if member.isfile())
            cls.texts = {member.name: tar.extractfile(member).read().decode("utf-8") for member in tar.getmembers()
                         if member.isfile() and member.name.endswith((".py", ".json"))}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_only_allowlisted_files_are_packaged(self):
        source = sorted(f"src/rfq_agent/{path.name}" for path in (ROOT / "src/rfq_agent").glob("*.py"))
        self.assertEqual(self.names, sorted(["agent.json", "pyproject.toml", "uv.lock"] + source))
        self.assertEqual([name for name in self.names if FORBIDDEN.search(name)], [])
        self.assertEqual(sorted(entry["path"] for entry in self.manifest["files"]), self.names)

    def test_archive_is_small_and_manifest_is_at_the_root(self):
        self.assertLessEqual(self.archive.stat().st_size, 20 * 1024 * 1024)
        self.assertEqual(self.manifest["compressed_bytes"], self.archive.stat().st_size)
        manifest = json.loads(self.texts["agent.json"])
        self.assertLessEqual(manifest["browsers"], 4)
        self.assertEqual(manifest["setup"][:2], ["uv", "sync"])
        self.assertIn("--frozen", manifest["setup"])
        self.assertIn("--no-sync", manifest["run"])

    def test_packager_refuses_a_forbidden_path(self):
        packager = load_packager()
        for path in ("tests/test_x.py", ".env", "docs/PHASE1_CONTRACT.md", ".entire/metadata/x.jsonl", "src/rfq_agent/notes.md"):
            with self.assertRaises(ValueError):
                packager.check_path(path)

    def test_runtime_source_names_no_website_or_model_host(self):
        for name, text in self.texts.items():
            self.assertEqual(re.findall(r"https?://[\w.-]+", text), [], name)
        self.assertNotRegex(self.texts["src/rfq_agent/model.py"], r"launch\(|localhost|127\.0\.0\.1")

    def test_only_browser_module_can_launch_and_never_in_a_run(self):
        launching = [name for name, text in self.texts.items() if ".launch(" in text]
        self.assertEqual(launching, ["src/rfq_agent/browser.py"])
        self.assertIn("CHALLENGE_RUN_TOKEN", self.texts["src/rfq_agent/browser.py"])


if __name__ == "__main__":
    unittest.main()
