"""Build a small allowlisted package; never include credentials, test facts or run artifacts."""
from pathlib import Path
import tarfile


def build(root: Path, output: Path):
    selected = [root / name for name in ("agent.json", "pyproject.toml", "README.md", "requirements-rfq.txt",
                                       "docs/RFQ_AGENT.md")]
    selected.extend(sorted((root / "src").rglob("*.py")))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path in selected:
            archive.add(path, arcname=path.relative_to(root), recursive=False)
    if output.stat().st_size > 20_000_000:
        output.unlink()
        raise ValueError("Package exceeds 20 MB compressed")
    return output


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(build(root, root / "dist" / "rfq-agent.tar.gz"))
