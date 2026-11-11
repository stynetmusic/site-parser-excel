"""Командная строка учебного парсера."""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from books_parser.excel_export import partial_output_path, save_excel
from books_parser.http_client import FetchError, HtmlFetcher, PageFetcher
from books_parser.logging_setup import use_logging
from books_parser.normalizer import build_summary
from books_parser.pipeline import DEFAULT_PAGE_LIMIT, collect_books
from books_parser.url_policy import UnsafeUrlError, ensure_allowed_url


logger = logging.getLogger(__name__)

DEFAULT_START_URL = "https://books.toscrape.com/"
DEFAULT_OUTPUT = Path("output/books_catalog.xlsx")
DEFAULT_LOG_FILE = Path("logs/parser.log")


@dataclass
class RunConfig:
    """Параметры одного запуска.

    Пути создаются отдельно для каждого запуска, чтобы два конфига
    не делили один и тот же объект Path.
    """

    start_url: str = DEFAULT_START_URL
    max_pages: int | None = None
    output: Path = field(default_factory=lambda: Path("output/books_catalog.xlsx"))
    delay: float = 0.5
    timeout: float = 15
    attempts: int = 3
    log_file: Path = field(default_factory=lambda: Path("logs/parser.log"))


def build_parser() -> argparse.ArgumentParser:
    """Описывает аргументы программы."""

    parser = argparse.ArgumentParser(
        prog="books_parser",
        description=(
            "Собирает учебный каталог Books to Scrape и сохраняет его в Excel. "
            "Сайт демонстрационный, цены и рейтинги на нём случайные."
        ),
    )
    parser.add_argument(
        "-n",
        "--max-pages",
        type=_positive_int,
        default=None,
        help=(
            "Сколько страниц каталога обработать. "
            f"Без параметра действует безопасный предел {DEFAULT_PAGE_LIMIT}. "
            "Большее значение тоже ограничивается этим пределом. "
            "Если страницы ещё остались, запуск считается неполным."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Куда сохранить Excel-файл. По умолчанию output/books_catalog.xlsx.",
    )
    parser.add_argument(
        "--delay",
        type=_delay_value,
        default=0.5,
        help="Пауза между запросами в секундах, не меньше 0.2. По умолчанию 0.5.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=15,
        help="Сколько секунд ждать ответ сайта. По умолчанию 15.",
    )
    parser.add_argument(
        "--attempts",
        type=_positive_int,
        default=3,
        help="Сколько раз пробовать загрузить страницу при временной ошибке. По умолчанию 3.",
    )
    parser.add_argument(
        "--start-url",
        type=_http_url,
        default=DEFAULT_START_URL,
        help="Адрес первой страницы каталога. По умолчанию учебный сайт Books to Scrape.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help="Файл журнала. По умолчанию logs/parser.log.",
    )
    return parser


def config_from_argv(argv: list[str] | None = None) -> RunConfig:
    """Читает аргументы командной строки в RunConfig."""

    args = build_parser().parse_args(argv)
    return RunConfig(
        start_url=args.start_url,
        max_pages=args.max_pages,
        output=args.output,
        delay=args.delay,
        timeout=args.timeout,
        attempts=args.attempts,
        log_file=args.log_file,
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа командной строки. Возвращает код завершения процесса."""

    return run(config_from_argv(argv))


def run(config: RunConfig, fetcher: HtmlFetcher | None = None) -> int:
    """Запускает сбор, пишет Excel и возвращает 0 при полном успехе."""

    owns_fetcher = fetcher is None
    if fetcher is None:
        fetcher = PageFetcher(
            timeout=config.timeout,
            attempts=config.attempts,
            delay=config.delay,
        )

    try:
        with use_logging(config.log_file):
            logger.info("Каталог: %s", config.start_url)
            if config.max_pages is None:
                logger.info("Ограничение страниц: безопасный предел %s", DEFAULT_PAGE_LIMIT)
            elif config.max_pages > DEFAULT_PAGE_LIMIT:
                logger.info(
                    "Запрошено страниц: %s. Применён безопасный предел %s.",
                    config.max_pages,
                    DEFAULT_PAGE_LIMIT,
                )
            else:
                logger.info("Ограничение страниц: %s", config.max_pages)

            try:
                result = collect_books(fetcher, config.start_url, config.max_pages)
            except (FetchError, UnsafeUrlError) as exc:
                logger.error("%s", exc)
                return 1
            except ValueError as exc:
                logger.error("Ошибка параметров: %s", exc)
                return 1

            if not result.completed and not result.books:
                logger.error(
                    "Сбор не выполнен. %s Файл отчёта не создан.",
                    result.error_message or "",
                )
                return 1

            target = config.output if result.completed else partial_output_path(config.output)
            summary = build_summary(
                result.books,
                result.pages_processed,
                datetime.now().astimezone(),
            )
            try:
                save_excel(target, result.books, summary)
            except OSError as exc:
                logger.error("Не удалось сохранить Excel-файл %s: %s", target, exc)
                return 1

            logger.info("Обработано страниц: %s", summary.pages_processed)
            logger.info("Найдено книг: %s", summary.books_found)
            logger.info("Книг в наличии: %s", summary.in_stock_count)
            logger.info("Книг нет в наличии: %s", summary.out_of_stock_count)
            logger.info("Средняя цена: %s", _format_number(summary.average_price))
            logger.info("Средний рейтинг: %s", _format_number(summary.average_rating))
            logger.info("Файл: %s", target)

            if not result.completed:
                logger.error(
                    "Сбор неполный. %s Основной отчёт не перезаписан: %s",
                    result.error_message or "",
                    config.output,
                )
                return 1
            return 0
    finally:
        if owns_fetcher:
            close = getattr(fetcher, "close", None)
            if callable(close):
                close()


def _format_number(value: float | None) -> str:
    if value is None:
        return "нет данных"
    return f"{value:.2f}"


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Нужно целое число") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("Число должно быть больше нуля")
    return number


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Нужно число больше нуля") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Число должно быть больше нуля")
    return number


def _delay_value(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Нужно число") from exc
    if number < 0.2:
        raise argparse.ArgumentTypeError(
            "Задержка не может быть меньше 0.2 секунды, чтобы не перегружать сайт"
        )
    return number


def _http_url(value: str) -> str:
    try:
        return ensure_allowed_url(value)
    except UnsafeUrlError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
