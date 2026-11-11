"""Сценарий обхода каталога: страницы, карточки, страницы книг."""

import logging

from books_parser.extractor import extract_book_page, extract_catalog_books, extract_next_page_url
from books_parser.http_client import FetchError, HtmlFetcher, SiteLimitError
from books_parser.models import BookRecord, CollectionResult, RawBook
from books_parser.normalizer import normalize_book
from books_parser.url_policy import UnsafeUrlError, ensure_allowed_url


logger = logging.getLogger(__name__)

# Учебный каталог короче. Предел не даёт случайно читать страницы без конца.
DEFAULT_PAGE_LIMIT = 200
MAX_CONSECUTIVE_BOOK_ERRORS = 5


def collect_books(
    fetcher: HtmlFetcher,
    start_url: str,
    max_pages: int | None = None,
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    max_consecutive_book_errors: int = MAX_CONSECUTIVE_BOOK_ERRORS,
) -> CollectionResult:
    """Обходит каталог и возвращает проверенные записи.

    Если не открылась первая страница из-за сети, ошибка уходит вызывающему коду.
    Ответы 403 и 429, чужой адрес и пустой каталог останавливают обход сразу:
    такой результат не считается успешным.
    """

    if max_pages is not None and max_pages < 1:
        raise ValueError("Количество страниц должно быть больше нуля")
    if page_limit < 1:
        raise ValueError("Предел страниц должен быть больше нуля")
    if max_consecutive_book_errors < 1:
        raise ValueError("Порог ошибок страниц книг должен быть больше нуля")

    ensure_allowed_url(start_url)
    # Меньший явный предел пользователя важнее. Больший всё равно упирается в page_limit.
    effective_limit = page_limit if max_pages is None else min(max_pages, page_limit)

    books: list[BookRecord] = []
    pages_processed = 0
    seen_pages: set[str] = set()
    page_url: str | None = start_url
    consecutive_book_errors = 0

    while page_url:
        if page_url in seen_pages:
            message = f"Обход остановлен: страница каталога повторилась ({page_url})."
            logger.error(message)
            return _stopped(books, pages_processed, message)
        seen_pages.add(page_url)

        try:
            ensure_allowed_url(page_url)
            html = fetcher.get_html(page_url)
        except SiteLimitError as exc:
            logger.error("%s", exc)
            return _stopped(books, pages_processed, str(exc))
        except UnsafeUrlError as exc:
            logger.error("%s", exc)
            return _stopped(books, pages_processed, str(exc))
        except FetchError as exc:
            if pages_processed == 0:
                raise
            logger.error("%s", exc)
            return _stopped(books, pages_processed, str(exc))

        pages_processed += 1
        raw_books = extract_catalog_books(html, page_url)
        logger.info("Страница %s: найдено книг %s", pages_processed, len(raw_books))
        if not raw_books:
            message = (
                f"На странице {page_url} нет карточек книг. "
                "Сбор остановлен: ответ сайта не похож на каталог."
            )
            logger.error(message)
            return _stopped(books, pages_processed, message)

        for raw_book in raw_books:
            loaded, stop_reason = _load_book_details(fetcher, raw_book)
            if stop_reason is not None:
                books.append(loaded.record)
                logger.error("%s", stop_reason)
                return _stopped(books, pages_processed, stop_reason)
            books.append(loaded.record)
            if loaded.detail_was_loaded or not raw_book.url:
                # Успешная страница книги сбрасывает счётчик. Карточка без ссылки
                # не считается ни успехом загрузки, ни очередной ошибкой.
                if loaded.detail_was_loaded:
                    consecutive_book_errors = 0
            else:
                consecutive_book_errors += 1
                if consecutive_book_errors >= max_consecutive_book_errors:
                    message = (
                        f"Сбор остановлен: {consecutive_book_errors} страниц книг подряд "
                        "не загрузились. Программа не продолжает обход."
                    )
                    logger.error(message)
                    return _stopped(books, pages_processed, message)
            logger.debug("Собрана книга: %s", loaded.record.title or "без названия")

        next_url = extract_next_page_url(html, page_url)
        if pages_processed >= effective_limit:
            if next_url:
                message = (
                    f"Достигнут предел страниц ({effective_limit}), "
                    "а в каталоге есть следующая страница. Сбор неполный."
                )
                logger.error(message)
                return _stopped(books, pages_processed, message)
            break
        if next_url:
            try:
                ensure_allowed_url(next_url)
            except UnsafeUrlError as exc:
                logger.error("%s", exc)
                return _stopped(books, pages_processed, str(exc))
        page_url = next_url

    return CollectionResult(books, pages_processed, completed=True)


class _BookLoad:
    """Результат открытия одной страницы книги."""

    def __init__(self, record: BookRecord, detail_was_loaded: bool) -> None:
        self.record = record
        self.detail_was_loaded = detail_was_loaded


def _load_book_details(
    fetcher: HtmlFetcher,
    raw_book: RawBook,
) -> tuple[_BookLoad, str | None]:
    """Открывает страницу книги. Второй элемент — причина немедленной остановки.

    Обычная сетевая ошибка останавливает только эту книгу. 403, 429 и чужой
    адрес останавливают весь обход: следующих запросов быть не должно.
    """

    if not raw_book.url:
        return _BookLoad(normalize_book(raw_book), False), None

    try:
        ensure_allowed_url(raw_book.url)
    except UnsafeUrlError as exc:
        record = normalize_book(raw_book)
        return _BookLoad(record, False), str(exc)

    try:
        # Пауза стоит внутри загрузчика и действует на каждый адрес.
        detail_html = fetcher.get_html(raw_book.url)
    except SiteLimitError as exc:
        record = normalize_book(raw_book)
        return _BookLoad(record, False), str(exc)
    except FetchError as exc:
        logger.warning("Не удалось открыть страницу книги %s: %s", raw_book.url, exc)
        record = normalize_book(raw_book)
        return _BookLoad(record, False), None

    details = extract_book_page(detail_html)
    return _BookLoad(normalize_book(raw_book, details, detail_loaded=True), True), None


def _stopped(books: list[BookRecord], pages_processed: int, message: str) -> CollectionResult:
    return CollectionResult(books, pages_processed, completed=False, error_message=message)
