import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from rfq_agent import model
from rfq_agent.package import build


class ComplianceTests(unittest.TestCase):
    def test_sandbox_qwen_cannot_use_local_override(self):
        env = {'CHALLENGE_RUN_TOKEN': 'invented-token', 'RFQ_MODEL_PROVIDER': 'qwen',
               'LLM_PROXY_URL': 'https://platform.test/llm/run/invented',
               'QWEN_BASE_URL': 'https://outside.test/v1', 'QWEN_API_KEY': 'local'}
        with patch.dict('os.environ', env, clear=True):
            self.assertEqual(model.configuration()[2:],
                             ('https://platform.test/llm/run/invented/qwen/v1', 'invented-token'))
            del model.os.environ['LLM_PROXY_URL']
            with self.assertRaises(RuntimeError):
                model.configuration()

    def test_package_excludes_secrets_fixtures_and_scouting_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'agent.json').write_text(json.dumps({'browsers': 4}))
            for name in ('pyproject.toml', 'uv.lock', '.env'):
                (root / name).write_text('invented')
            for name in ('src/rfq_agent/__main__.py', 'artifacts/evidence.json',
                         'tests/fixtures.py', 'docs/scouting.md'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('invented')
            output = build(root, root / 'dist/agent.tar.gz')
            with tarfile.open(output) as archive:
                self.assertEqual(set(archive.getnames()),
                                 {'agent.json', 'pyproject.toml', 'uv.lock', 'src/rfq_agent/__main__.py'})
