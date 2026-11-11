"""Запись проверенного каталога в файл Excel с двумя листами."""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from books_parser.models import BookRecord, CatalogSummary
from books_parser.url_policy import UnsafeUrlError, ensure_allowed_url


logger = logging.getLogger(__name__)

# Эти символы в начале ячейки Excel понимает как формулу или команду.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


CATALOG_HEADERS = [
    "Название",
    "Цена",
    "Валюта",
    "Рейтинг",
    "Наличие",
    "Количество",
    "Ссылка",
]

SUMMARY_ROWS = [
    ("Дата и время сбора", "collected_at"),
    ("Обработано страниц", "pages_processed"),
    ("Найдено книг", "books_found"),
    ("Книг в наличии", "in_stock_count"),
    ("Книг нет в наличии", "out_of_stock_count"),
    ("Средняя цена", "average_price"),
    ("Средний рейтинг", "average_rating"),
]

# Ширина подобрана под русские заголовки и длинные адреса страниц.
CATALOG_WIDTHS = {
    "A": 48,
    "B": 14,
    "C": 12,
    "D": 14,
    "E": 20,
    "F": 16,
    "G": 64,
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=12)
ZEBRA_FILL = PatternFill("solid", fgColor="F4F7FB")
THIN_BORDER = Border(
    left=Side(style="thin", color="D9E2F0"),
    right=Side(style="thin", color="D9E2F0"),
    top=Side(style="thin", color="D9E2F0"),
    bottom=Side(style="thin", color="D9E2F0"),
)


def partial_output_path(path: Path) -> Path:
    """Имя для неполного отчёта рядом с основным файлом.

    output/books_catalog.xlsx становится output/books_catalog.partial.xlsx.
    Пользовательское имя сохраняется: report.xlsx → report.partial.xlsx.
    """

    suffix = path.suffix or ".xlsx"
    return path.with_name(f"{path.stem}.partial{suffix}")


def save_excel(path: Path, books: list[BookRecord], summary: CatalogSummary) -> Path:
    """Создаёт xlsx-файл и при необходимости недостающие папки.

    Сначала книга пишется во временный файл в той же папке. Готовый файл
    заменяет прежний через os.replace. Если запись оборвалась, временный
    файл удаляется, а старый отчёт остаётся на месте.
    """

    if path.exists() and path.is_dir():
        raise IsADirectoryError(f"Путь {path} является папкой, а не файлом")
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = _build_workbook(books, summary)
    _replace_atomically(path, workbook)
    return path


def _build_workbook(books: list[BookRecord], summary: CatalogSummary) -> Workbook:
    workbook = Workbook()
    catalog_sheet = workbook.active
    catalog_sheet.title = "Каталог"
    summary_sheet = workbook.create_sheet("Сводка")
    _write_catalog(catalog_sheet, books)
    _write_summary(summary_sheet, summary)
    workbook.properties.title = "Каталог Books to Scrape"
    workbook.properties.creator = "site-parser-excel"
    return workbook


def _replace_atomically(path: Path, workbook: Workbook) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        workbook.save(temporary_path)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def format_collected_at(value: datetime) -> str:
    """Показывает время сбора. Если пояс известен, добавляет его короткое имя."""

    stamp = value.strftime("%Y-%m-%d %H:%M:%S")
    if value.tzinfo is None:
        return stamp
    zone = value.tzname() or ""
    return f"{stamp} {zone}".strip()


def _write_catalog(sheet: Worksheet, books: list[BookRecord]) -> None:
    sheet.append(CATALOG_HEADERS)
    for book in books:
        # Цена, рейтинг и количество пишутся числами. Пустое поле остаётся
        # пустой ячейкой, а не нулём и не строкой «нет данных».
        sheet.append(
            [
                prepare_cell_text(book.title),
                book.price,
                prepare_cell_text(book.currency),
                book.rating,
                prepare_cell_text(book.availability),
                book.stock_quantity,
                prepare_cell_text(book.url),
            ]
        )

    _style_header(sheet, len(CATALOG_HEADERS))
    sheet.freeze_panes = "A2"
    sheet.row_dimensions[1].height = 22
    sheet.auto_filter.ref = f"A1:G{max(sheet.max_row, 1)}"
    sheet.print_title_rows = "1:1"
    sheet.sheet_view.showGridLines = False

    for column, width in CATALOG_WIDTHS.items():
        sheet.column_dimensions[column].width = width

    for row_index in range(2, sheet.max_row + 1):
        _style_catalog_row(sheet, row_index)


def _style_catalog_row(sheet: Worksheet, row_index: int) -> None:
    fill = ZEBRA_FILL if row_index % 2 == 0 else None
    for column in range(1, len(CATALOG_HEADERS) + 1):
        cell = sheet.cell(row_index, column)
        cell.font = Font(name="Calibri", size=11)
        cell.border = THIN_BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=(column == 1))
        if fill is not None and column != 7:
            cell.fill = fill

    price_cell = sheet.cell(row_index, 2)
    if isinstance(price_cell.value, (int, float)):
        price_cell.number_format = "0.00"
        price_cell.alignment = Alignment(horizontal="right", vertical="center")

    rating_cell = sheet.cell(row_index, 4)
    if isinstance(rating_cell.value, int):
        rating_cell.number_format = "0"
        rating_cell.alignment = Alignment(horizontal="center", vertical="center")

    quantity_cell = sheet.cell(row_index, 6)
    if isinstance(quantity_cell.value, int):
        quantity_cell.number_format = "0"
        quantity_cell.alignment = Alignment(horizontal="center", vertical="center")

    link_cell = sheet.cell(row_index, 7)
    url = link_cell.value
    if isinstance(url, str) and _is_allowed_catalog_url(url):
        # Стиль ссылки ставится до повторной записи адреса: иначе openpyxl
        # может сбросить и текст, и сам переход. Чужой адрес ссылкой не становится.
        link_cell.style = "Hyperlink"
        link_cell.value = url
        link_cell.hyperlink = url

    for column in range(1, len(CATALOG_HEADERS) + 1):
        _keep_untrusted_text(sheet.cell(row_index, column))


def _write_summary(sheet: Worksheet, summary: CatalogSummary) -> None:
    sheet.append(["Показатель", "Значение"])
    values = {
        "collected_at": format_collected_at(summary.collected_at),
        "pages_processed": summary.pages_processed,
        "books_found": summary.books_found,
        "in_stock_count": summary.in_stock_count,
        "out_of_stock_count": summary.out_of_stock_count,
        "average_price": summary.average_price,
        "average_rating": summary.average_rating,
    }
    for label, key in SUMMARY_ROWS:
        sheet.append([label, values[key]])

    _style_header(sheet, 2)
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 28
    sheet.row_dimensions[1].height = 22

    number_formats = {
        3: "0",
        4: "0",
        5: "0",
        6: "0",
        7: "0.00",
        8: "0.00",
    }
    for row_index in range(2, sheet.max_row + 1):
        label_cell = sheet.cell(row_index, 1)
        value_cell = sheet.cell(row_index, 2)
        label_cell.font = Font(name="Calibri", size=11)
        value_cell.font = Font(name="Calibri", size=11)
        label_cell.border = THIN_BORDER
        value_cell.border = THIN_BORDER
        label_cell.alignment = Alignment(vertical="center")
        value_cell.alignment = Alignment(vertical="center", horizontal="right")
        if row_index % 2 == 0:
            label_cell.fill = ZEBRA_FILL
            value_cell.fill = ZEBRA_FILL
        if row_index in number_formats and isinstance(value_cell.value, (int, float)):
            value_cell.number_format = number_formats[row_index]

    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "1:1"


def prepare_cell_text(value: str | None) -> str | None:
    """Готовит текст с сайта к записи в ячейку.

    Управляющие символы, которые нельзя хранить в XML, удаляются.
    Обычные буквы, в том числе кириллица, остаются.
    Строка, начинающаяся с =, +, - или @, здесь не меняется: её нельзя
    превращать в формулу, но и обрезать видимый текст не нужно. Тип ячейки
    выставляется отдельно в _keep_untrusted_text.
    Заголовки отчёта и числа сюда не передаются.
    """

    if value is None:
        return None
    cleaned = ILLEGAL_CHARACTERS_RE.sub("", value)
    if cleaned != value:
        logger.warning("Из текста удалены символы, которые нельзя записать в Excel")
    return cleaned


def _is_allowed_catalog_url(url: str) -> bool:
    """Ссылка в ячейке ведёт только на учебный каталог."""

    try:
        ensure_allowed_url(url)
    except UnsafeUrlError:
        return False
    return True


def _keep_untrusted_text(cell) -> None:
    """Не даёт Excel прочитать текст с сайта как формулу.

    openpyxl сам помечает строку, которая начинается с «=», как формулу.
    После записи возвращаем обычный текст и формат «@». Символы в ячейке
    те же, что пришли с сайта. Настоящих формул отчёт не создаёт: ссылка
    на книгу — это гиперссылка ячейки, а не строка формулы.
    """

    value = cell.value
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        cell.data_type = "s"
        cell.number_format = "@"


def _style_header(sheet: Worksheet, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(1, column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
