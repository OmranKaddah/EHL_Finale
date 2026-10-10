"""Build a submission from runtime code and dependency manifests only."""

import argparse
import json
from pathlib import Path
import tarfile

LIMIT = 20 * 1024 * 1024


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    manifest = json.loads((root / 'agent.json').read_text())
    browsers = manifest.get('browsers', 1)
    if type(browsers) is not int or not 1 <= browsers <= 4:
        raise ValueError('agent.json must request one to four browsers')
    files = [root / name for name in ('agent.json', 'pyproject.toml', 'uv.lock')]
    files += sorted((root / 'src' / 'rfq_agent').rglob('*.py'))
    if not files[3:]:
        raise ValueError('No runtime Python source found')
    for path in files:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Package inputs must be regular project files')
    if output in files:
        raise ValueError('Output cannot overwrite a package input')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    if output.stat().st_size > LIMIT:
        raise ValueError('Package exceeds the 20 MB compressed limit; do not upload')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='dist/agent.tar.gz')
    args = parser.parse_args()
    print(build(Path.cwd(), args.output))
