"""Загрузка HTML-страниц с паузой, тайм-аутом и повторными попытками.

Модуль только получает текст страницы. Он не разбирает книги и не обходит
ограничения сайта: чужой сертификат не отключается, заголовки браузера не
подменяются, а ответы 403 и 429 не повторяются.
"""

import logging
import time
from typing import Protocol

import requests

from books_parser.url_policy import ensure_allowed_url


logger = logging.getLogger(__name__)

# Честное имя учебного клиента. Это не маскировка под браузер.
USER_AGENT = "SiteParserExcel/1.0 (educational portfolio; demo catalog only)"

# Эти ответы часто означают кратковременную перегрузку, а не запрет доступа.
# Код 429 сюда не входит: это Too Many Requests. Повтор без заголовка
# Retry-After был бы попыткой продавить ограничение сайта.
RETRY_STATUSES = {408, 500, 502, 503, 504}


class FetchError(Exception):
    """Ошибка загрузки, которую можно показать пользователю."""

    def __init__(self, message: str, url: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class SiteLimitError(FetchError):
    """Сайт ответил 403 или 429. Дальше запросы отправлять нельзя."""


class TemporaryFetchError(FetchError):
    """Сбой, который имеет смысл повторить: сеть, тайм-аут или ответ 5xx."""

    def __init__(self, message: str, url: str, kind: str, status: int | None = None) -> None:
        super().__init__(message, url)
        self.kind = kind
        self.status = status


class HtmlFetcher(Protocol):
    """Любой источник HTML. В тестах вместо сети подставляется заглушка."""

    def get_html(self, url: str) -> str:
        """Возвращает текст страницы или выбрасывает FetchError."""


class PageFetcher:
    """Скачивает одну страницу за раз и выдерживает паузу между запросами."""

    def __init__(
        self,
        timeout: float = 15,
        attempts: int = 3,
        delay: float = 0.5,
        backoff_base: float = 0.5,
        session: requests.Session | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Тайм-аут должен быть больше нуля")
        if attempts < 1:
            raise ValueError("Число попыток должно быть не меньше 1")
        if delay < 0:
            raise ValueError("Задержка не может быть отрицательной")
        if backoff_base < 0:
            raise ValueError("Пауза между повторами не может быть отрицательной")

        self.timeout = timeout
        self.attempts = attempts
        self.delay = delay
        self.backoff_base = backoff_base
        self._owns_session = session is None
        self._session = session or requests.Session()
        if self._owns_session:
            self._session.headers["User-Agent"] = USER_AGENT
            self._session.headers["Accept"] = "text/html,application/xhtml+xml"
        self._requests_started = 0

    def close(self) -> None:
        """Закрывает собственную сессию. Чужую сессию не трогает."""

        if self._owns_session:
            self._session.close()

    def get_html(self, url: str) -> str:
        """Загружает страницу. Между разными адресами выдерживается delay.

        Повтор выполняется только для временного сбоя. Если попытки закончились,
        наружу выходит обычный FetchError с понятной формулировкой.
        Чужой адрес отклоняется до запроса. Редиректы не выполняются.
        """

        ensure_allowed_url(url)
        last_error: TemporaryFetchError | None = None
        for attempt in range(1, self.attempts + 1):
            self._pause(attempt)
            try:
                return self._fetch_once(url)
            except TemporaryFetchError as exc:
                last_error = exc
                logger.warning(
                    "Временная ошибка для %s, попытка %s из %s: %s",
                    url,
                    attempt,
                    self.attempts,
                    exc,
                )
        assert last_error is not None
        raise self._final_error(last_error)

    def _pause(self, attempt: int) -> None:
        # Первая попытка первого запроса идёт сразу. Дальше либо обычная
        # пауза между страницами, либо увеличивающаяся пауза после сбоя.
        if attempt == 1:
            if self._requests_started > 0:
                self._sleep(self.delay)
            return
        pause = min(8.0, self.backoff_base * (2 ** (attempt - 2)))
        self._sleep(pause)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def _fetch_once(self, url: str) -> str:
        self._requests_started += 1
        try:
            # verify=True по умолчанию: сертификат сайта проверяется, а не отключается.
            # allow_redirects=False: библиотека сама не уйдёт на чужой адрес.
            response = self._session.get(url, timeout=self.timeout, allow_redirects=False)
        except requests.Timeout as exc:
            raise TemporaryFetchError(
                f"Сайт не ответил за {self.timeout} с.",
                url,
                kind="timeout",
            ) from exc
        except requests.ConnectionError as exc:
            raise TemporaryFetchError(
                "Нет соединения с сайтом.",
                url,
                kind="network",
            ) from exc
        except requests.RequestException as exc:
            raise TemporaryFetchError(
                "Сетевой запрос завершился ошибкой.",
                url,
                kind="network",
            ) from exc

        status = response.status_code
        if status in {301, 302, 303, 307, 308}:
            # Куда ведёт Location, не проверяем переходом: даже «свой» редирект
            # мог бы смениться на чужой адрес. Безопаснее остановить запрос.
            raise FetchError(
                f"Сайт вернул перенаправление с {url} (код {status}). "
                "Программа не переходит по редиректам, чтобы запрос не ушёл на посторонний адрес.",
                url,
                status=status,
            )
        if 200 <= status < 300:
            return decode_response(response)
        if status == 429:
            raise SiteLimitError(
                f"Сайт ограничил частоту запросов к {url} (код 429). "
                "Программа не повторяет запрос и не обходит это ограничение.",
                url,
                status=429,
            )
        if status in RETRY_STATUSES or status >= 500:
            raise TemporaryFetchError(
                f"Сервер временно ответил кодом {status}.",
                url,
                kind="http",
                status=status,
            )
        if status == 403:
            raise SiteLimitError(
                f"Сайт ограничил доступ к {url} (код 403). "
                "Программа не обходит ограничения и не повторяет этот запрос.",
                url,
                status=403,
            )
        if status == 401:
            raise FetchError(
                f"Сайт ограничил доступ к {url} (код 401). "
                "Программа не обходит ограничения и не повторяет этот запрос.",
                url,
                status=401,
            )
        if status == 404:
            raise FetchError(f"Страница не найдена: {url} (код 404).", url)
        raise FetchError(f"Сайт вернул ошибку {status} для {url}. Запрос не повторяется.", url)

    def _final_error(self, last_error: TemporaryFetchError) -> FetchError:
        url = last_error.url or ""
        if last_error.kind == "network":
            message = (
                f"Не удалось открыть страницу {url}: сайт недоступен или не отвечает. "
                "Проверьте подключение к интернету и повторите попытку позже."
            )
        elif last_error.kind == "timeout":
            message = (
                f"Не удалось открыть страницу {url}: сайт не ответил за {self.timeout} с. "
                f"Повторные попытки исчерпаны ({self.attempts})."
            )
        else:
            message = (
                f"Сервер временно не отвечает (код {last_error.status}) по адресу {url}. "
                f"Сделано попыток: {self.attempts}. Программа не обходит ограничения сайта."
            )
        return FetchError(message, url)


def decode_response(response: requests.Response) -> str:
    """Декодирует тело страницы.

    Учебный сайт отдаёт HTML в UTF-8, но не пишет charset в заголовке.
    Без этой проверки requests прочитает байты как ISO-8859-1, и символ
    фунта, а также буквы с акцентами, превратятся в кракозябры.
    """

    content = response.content
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        encoding = response.apparent_encoding or "utf-8"
        return content.decode(encoding, errors="replace")
