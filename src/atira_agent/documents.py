"""Read only documents explicitly selected through the browser."""
from __future__ import annotations

import base64
import io
import zipfile
from pathlib import PurePosixPath

import pypdfium2 as pdfium

MAX_DOCUMENT_BYTES = 30 * 1024 * 1024


def read_document(data: bytes, name: str, member: str | None = None, page: int = 1) -> dict:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("Selected document exceeds the 30 MB extraction limit")
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 500 or sum(x.file_size for x in entries) > MAX_DOCUMENT_BYTES:
                raise ValueError("ZIP exceeds bounded extraction limits")
            if member is None:
                return {"name": name, "members": [{"name": x.filename, "bytes": x.file_size}
                                                    for x in entries if not x.is_dir()]}
            path = PurePosixPath(member.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe ZIP member")
            entry = archive.getinfo(member)
            if entry.flag_bits & 1 or entry.file_size > MAX_DOCUMENT_BYTES:
                raise ValueError("Encrypted or oversized ZIP member")
            return read_document(archive.read(entry), member, page=page)
    if data.startswith(b"%PDF"):
        with pdfium.PdfDocument(data) as document:
            if not 1 <= page <= len(document):
                raise ValueError("PDF page outside document")
            pdf_page = document[page - 1]
            text_page = pdf_page.get_textpage()
            text = text_page.get_text_range()
            result = {"name": name, "page": page, "pages": len(document), "text": text[:40000]}
            if len(text.strip()) < 100:
                bitmap = pdf_page.render(scale=1.5)
                buffer = io.BytesIO()
                bitmap.to_pil().save(buffer, format="PNG")
                result["image"] = base64.b64encode(buffer.getvalue()).decode()
            text_page.close()
            pdf_page.close()
            return result
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    if "\x00" in text[:500]:
        raise ValueError("Unsupported binary document; inspect it in the browser")
    return {"name": name, "text": text[:40000]}
