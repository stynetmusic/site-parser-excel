"""Файл Excel собирается из готовых записей и не ходит в сеть."""

from datetime import datetime, timezone

import pytest
from openpyxl import load_workbook

from books_parser.excel_export import save_excel
from books_parser.normalizer import build_summary
from tests.helpers import make_book


ATTIC_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
COLLECTED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _sample_file(tmp_path):
    books = [
        make_book(
            title="A Light in the Attic",
            price=51.77,
            currency="GBP",
            rating=3,
            availability="В наличии",
            stock_quantity=22,
            url=ATTIC_URL,
            in_stock=True,
        ),
        make_book(
            title=None,
            price=None,
            currency=None,
            rating=None,
            availability=None,
            stock_quantity=None,
            url=None,
            in_stock=None,
        ),
    ]
    summary = build_summary(books, pages_processed=2, collected_at=COLLECTED_AT)
    path = tmp_path / "reports" / "books_catalog.xlsx"
    save_excel(path, books, summary)
    return path


def test_workbook_has_catalog_and_summary_sheets(tmp_path):
    workbook = load_workbook(_sample_file(tmp_path))

    assert workbook.sheetnames == ["Каталог", "Сводка"]


def test_catalog_layout_formats_and_hyperlink(tmp_path):
    catalog = load_workbook(_sample_file(tmp_path))["Каталог"]

    assert [catalog.cell(1, column).value for column in range(1, 8)] == [
        "Название",
        "Цена",
        "Валюта",
        "Рейтинг",
        "Наличие",
        "Количество",
        "Ссылка",
    ]
    assert catalog.freeze_panes == "A2"
    assert catalog.auto_filter.ref == "A1:G3"
    assert catalog.column_dimensions["A"].width >= 40
    assert catalog.column_dimensions["B"].width >= 12
    assert catalog.column_dimensions["G"].width >= 40
    assert catalog["A1"].font.bold is True
    assert catalog["A1"].font.color.rgb.endswith("FFFFFF")
    assert str(catalog["A1"].fill.fgColor.rgb).endswith("1F4E79")

    assert catalog["A2"].value == "A Light in the Attic"
    assert catalog["B2"].value == pytest.approx(51.77)
    assert isinstance(catalog["B2"].value, float)
    assert catalog["B2"].number_format == "0.00"
    assert catalog["C2"].value == "GBP"
    assert catalog["D2"].value == 3
    assert catalog["E2"].value == "В наличии"
    assert catalog["F2"].value == 22
    assert catalog["G2"].value == ATTIC_URL
    assert catalog["G2"].hyperlink.target == ATTIC_URL


def test_missing_values_stay_blank_in_excel(tmp_path):
    catalog = load_workbook(_sample_file(tmp_path))["Каталог"]

    assert catalog["A3"].value is None
    assert catalog["B3"].value is None
    assert catalog["C3"].value is None
    assert catalog["D3"].value is None
    assert catalog["E3"].value is None
    assert catalog["F3"].value is None
    assert catalog["G3"].value is None
    assert catalog["G3"].hyperlink is None


def test_summary_sheet_contains_only_requested_metrics(tmp_path):
    summary = load_workbook(_sample_file(tmp_path))["Сводка"]

    assert [summary.cell(row, 1).value for row in range(1, 9)] == [
        "Показатель",
        "Дата и время сбора",
        "Обработано страниц",
        "Найдено книг",
        "Книг в наличии",
        "Книг нет в наличии",
        "Средняя цена",
        "Средний рейтинг",
    ]
    assert summary.max_row == 8
    assert summary.freeze_panes == "A2"
    assert summary["B2"].value == "2026-11-11 12:00:00 UTC"
    assert summary["B3"].value == 2
    assert summary["B4"].value == 2
    assert summary["B5"].value == 1
    assert summary["B6"].value == 0
    assert summary["B7"].value == pytest.approx(51.77)
    assert summary["B7"].number_format == "0.00"
    assert summary["B8"].value == pytest.approx(3)
    assert summary["B8"].number_format == "0.00"
    assert summary.column_dimensions["A"].width >= 28


def test_formula_like_title_is_stored_as_text(tmp_path):
    dangerous = '=HYPERLINK("http://evil.example","click")'
    books = [make_book(title=dangerous, availability="=CMD()", currency="+GBP")]
    summary = build_summary(books, pages_processed=1, collected_at=COLLECTED_AT)
    path = tmp_path / "formulas.xlsx"
    save_excel(path, books, summary)

    catalog = load_workbook(path)["Каталог"]
    title_cell = catalog["A2"]
    availability_cell = catalog["E2"]
    currency_cell = catalog["C2"]

    assert title_cell.data_type != "f"
    assert availability_cell.data_type != "f"
    assert currency_cell.data_type != "f"
    assert title_cell.value == dangerous
    assert availability_cell.value == "=CMD()"
    assert currency_cell.value == "+GBP"
    assert catalog["G2"].hyperlink is not None
    assert catalog["G2"].hyperlink.target == ATTIC_URL


def test_external_url_is_text_and_not_a_hyperlink(tmp_path):
    external = "https://evil.example/book"
    books = [make_book(url=external, title="Чужая ссылка")]
    summary = build_summary(books, pages_processed=1, collected_at=COLLECTED_AT)
    path = tmp_path / "external.xlsx"

    save_excel(path, books, summary)

    link = load_workbook(path)["Каталог"]["G2"]
    assert link.value == external
    assert link.data_type != "f"
    assert link.hyperlink is None


def test_illegal_control_character_does_not_break_excel_save(tmp_path):
    books = [make_book(title="Свет\x01 на чердаке", availability="В наличии")]
    summary = build_summary(books, pages_processed=1, collected_at=COLLECTED_AT)
    path = tmp_path / "cleaned.xlsx"

    save_excel(path, books, summary)

    catalog = load_workbook(path)["Каталог"]
    assert catalog["A2"].value == "Свет на чердаке"
    assert catalog["E2"].value == "В наличии"


def test_atomic_save_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "books_catalog.xlsx"
    books = [make_book()]
    summary = build_summary(books, pages_processed=1, collected_at=COLLECTED_AT)

    save_excel(target, books, summary)

    assert target.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*")) == []


def test_failed_save_keeps_previous_report_and_removes_temp(tmp_path, monkeypatch):
    target = tmp_path / "books_catalog.xlsx"
    old_books = [make_book(title="Старый отчёт")]
    old_summary = build_summary(old_books, pages_processed=1, collected_at=COLLECTED_AT)
    save_excel(target, old_books, old_summary)
    old_bytes = target.read_bytes()

    def fail_to_save(self, filename):
        raise OSError("нет места на диске")

    monkeypatch.setattr("books_parser.excel_export.Workbook.save", fail_to_save)
    new_books = [make_book(title="Новый отчёт")]
    new_summary = build_summary(new_books, pages_processed=1, collected_at=COLLECTED_AT)

    with pytest.raises(OSError, match="нет места"):
        save_excel(target, new_books, new_summary)

    assert target.read_bytes() == old_bytes
    assert list(tmp_path.glob("*.tmp")) == []
    assert [path for path in tmp_path.iterdir() if path != target] == []
