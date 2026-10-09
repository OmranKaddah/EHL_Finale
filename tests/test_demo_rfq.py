from pathlib import Path

from hackathon_toolkit.demos import match_sample_rfq


def test_sample_documents_match_with_evidence():
    root = Path(__file__).resolve().parents[1] / "examples" / "documents"
    result = match_sample_rfq(root / "rfq.txt", root / "technical_spec.txt")
    report = result["report"]
    assert report["overall"] == "PASS"
    assert all(item["outcome"] == "PASS" for item in report["matches"])
    assert report["matches"][0]["constraint"]["evidence"]
    assert report["matches"][0]["actual"]["evidence"]
