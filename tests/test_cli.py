"""Параметры запуска и поведение, когда учебный сайт недоступен."""

import logging
from pathlib import Path

import pytest

from datetime import datetime

from books_parser.cli import RunConfig, build_parser, run
from books_parser.excel_export import save_excel
from books_parser.http_client import FetchError, SiteLimitError
from books_parser.models import RawBook
from books_parser.normalizer import build_summary, normalize_book
from openpyxl import load_workbook
from tests.helpers import make_book


def test_without_max_pages_the_whole_catalog_is_requested():
    args = build_parser().parse_args([])

    assert args.max_pages is None
    assert args.output == Path("output/books_catalog.xlsx")
    assert args.delay == 0.5
    assert args.attempts == 3


def test_rejects_zero_pages_and_too_small_delay():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--max-pages", "0"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--delay", "0"])


def test_run_reports_unavailable_site_and_does_not_create_excel(tmp_path):
    class UnavailableSite:
        def get_html(self, url: str) -> str:
            raise FetchError(
                "Не удалось открыть страницу https://books.toscrape.com/: "
                "сайт недоступен или не отвечает. "
                "Проверьте подключение к интернету и повторите попытку позже.",
                url,
            )

    output = tmp_path / "output" / "books_catalog.xlsx"
    config = RunConfig(
        max_pages=1,
        output=output,
        log_file=tmp_path / "parser.log",
    )

    code = run(config, fetcher=UnavailableSite())

    assert code == 1
    assert not output.exists()
    assert "недоступен" in config.log_file.read_text(encoding="utf-8")


def test_log_capture_works_after_program_run(tmp_path, caplog):
    """Запуск программы не должен отключать перехват журнала в следующих тестах."""

    class UnavailableSite:
        def get_html(self, url: str) -> str:
            raise FetchError("Сайт недоступен или не отвечает.", url)

    config = RunConfig(
        max_pages=1,
        output=tmp_path / "output" / "books.xlsx",
        log_file=tmp_path / "parser.log",
    )
    assert run(config, fetcher=UnavailableSite()) == 1

    raw = RawBook(
        title=None,
        price_text=None,
        rating_class=None,
        availability_text=None,
        url=None,
        source_page="https://books.toscrape.com/",
    )
    with caplog.at_level(logging.WARNING):
        normalize_book(raw)

    assert "Название отсутствует" in caplog.text


def test_empty_catalog_exits_with_error_and_creates_no_report(tmp_path):
    class EmptyCatalog:
        def get_html(self, url: str) -> str:
            return "<html><body><p>пусто</p></body></html>"

    output = tmp_path / "books_catalog.xlsx"
    config = RunConfig(output=output, log_file=tmp_path / "parser.log", max_pages=1)

    code = run(config, fetcher=EmptyCatalog())

    assert code == 1
    assert not output.exists()
    assert not output.with_name("books_catalog.partial.xlsx").exists()


def test_incomplete_run_does_not_overwrite_the_main_report(tmp_path):
    attic = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    velvet = "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html"
    catalog = f"""
    <html><body>
      <article class="product_pod">
        <p class="star-rating Three"></p>
        <h3><a href="{attic}" title="A Light in the Attic">A Light</a></h3>
        <p class="price_color">£51.77</p>
        <p class="availability">In stock</p>
      </article>
      <article class="product_pod">
        <p class="star-rating One"></p>
        <h3><a href="{velvet}" title="Tipping the Velvet">Velvet</a></h3>
        <p class="price_color">£53.74</p>
        <p class="availability">In stock</p>
      </article>
    </body></html>
    """

    class LimitFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_html(self, url: str) -> str:
            self.calls.append(url)
            if url == "https://books.toscrape.com/":
                return catalog
            if url == attic:
                raise SiteLimitError(
                    f"Сайт ограничил частоту запросов к {url} (код 429).",
                    url,
                    status=429,
                )
            raise AssertionError(f"Лишний запрос: {url}")

    output = tmp_path / "books_catalog.xlsx"
    old_books = [make_book(title="Старый отчёт")]
    save_excel(
        output,
        old_books,
        build_summary(old_books, pages_processed=1, collected_at=datetime(2026, 1, 1)),
    )
    fetcher = LimitFetcher()
    config = RunConfig(output=output, log_file=tmp_path / "parser.log", max_pages=1)

    code = run(config, fetcher=fetcher)

    assert code == 1
    assert load_workbook(output)["Каталог"]["A2"].value == "Старый отчёт"
    partial = tmp_path / "books_catalog.partial.xlsx"
    assert partial.exists()
    assert load_workbook(partial)["Каталог"]["A2"].value == "A Light in the Attic"
    assert velvet not in fetcher.calls
