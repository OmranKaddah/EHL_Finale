import io
import zipfile

import pytest

from atira_agent.documents import read_document


def test_zip_lists_only_then_reads_selected_member():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("selected.txt", "Chosen specification")
        archive.writestr("other.txt", "Unselected content")
    result = read_document(buffer.getvalue(), "docs.zip")
    assert "text" not in result
    assert len(result["members"]) == 2
    assert read_document(buffer.getvalue(), "docs.zip", "selected.txt")["text"] == "Chosen specification"


def test_zip_rejects_traversal():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.txt", "data")
    with pytest.raises(ValueError):
        read_document(buffer.getvalue(), "docs.zip", "../escape.txt")


def test_pdf_text_extraction():
    # Tiny independently generated PDF fixture; no external document content.
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(200, 100)
    page.close()
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    result = read_document(buffer.getvalue(), "blank.pdf")
    assert result["pages"] == 1 and result["page"] == 1 and "image" in result
