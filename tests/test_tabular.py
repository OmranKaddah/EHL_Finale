import csv
import io
import sys
from types import SimpleNamespace

import pytest

from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.parsing import document_content, parse_tabular_document


def test_csv_preserves_quoted_cells_and_actual_row_ranges():
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerows([["model", "notes"], ["AX", "line one\nline two"], ["BX", "a,b"], ["CX", "last"]])
    document = ingest_bytes(stream.getvalue().encode(), "products.csv")
    parsed = parse_tabular_document(document, rows_per_table=2)
    assert parsed.sections[0].heading == "products.csv"
    assert [table.source.table for table in parsed.sections[0].tables] == [
        "products.csv!rows-2-3", "products.csv!rows-4-4"]
    assert parsed.sections[0].tables[0].rows == [["AX", "line one\nline two"], ["BX", "a,b"]]
    assert parsed.sections[0].tables[1].rows == [["CX", "last"]]
    assert parsed.sections[0].tables[0].source.page is None
    text, spans = parsed.text_with_sources()
    assert text[spans[-1][0]:spans[-1][1]] == "CX | last"
    assert spans[-1][2].row == 4


def test_xlsx_uses_read_only_workbook_and_closes_it(monkeypatch):
    called = {}

    class Sheet:
        title = "Products"

        def iter_rows(self, *, values_only):
            assert values_only
            yield ["model", "power"]
            yield ["AX", 50]

    class Workbook:
        worksheets = [Sheet()]

        def close(self):
            called["closed"] = True

    def load_workbook(source, *, read_only, data_only):
        called.update(read_only=read_only, data_only=data_only)
        assert source.read() == b"workbook"
        return Workbook()

    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace(load_workbook=load_workbook))
    document = ingest_bytes(b"workbook", "products.xlsx")
    parsed = parse_tabular_document(document)
    assert called == {"read_only": True, "data_only": True, "closed": True}
    assert parsed.sections[0].tables[0].rows == [["AX", "50"]]
    assert parsed.sections[0].tables[0].source.table == "Products!rows-2-2"


def test_direct_file_input_rejects_spreadsheets_it_cannot_read_completely():
    with pytest.raises(ValueError, match="--parser tabular"):
        document_content(ingest_bytes(b"workbook", "products.xlsx"))
    rows = "name\n" + "\n".join(f"item-{number}" for number in range(1000))
    with pytest.raises(ValueError, match="after 1000"):
        document_content(ingest_bytes(rows.encode(), "products.csv"))
