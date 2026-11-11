"""Какие адреса парсеру разрешено открывать.

urljoin только склеивает ссылку со страницей. Он не решает, можно ли
по ней переходить. Эту проверку делает модуль перед каждым запросом.
"""

import ipaddress
from urllib.parse import urlparse


ALLOWED_HOST = "books.toscrape.com"


class UnsafeUrlError(Exception):
    """Адрес нельзя открывать: это не учебный каталог Books to Scrape."""


def ensure_allowed_url(url: str) -> str:
    """Возвращает тот же адрес, если он принадлежит учебному каталогу.

    Разрешены только https и точное имя books.toscrape.com.
    Любая секция userinfo, IP, localhost, локальная сеть и чужой порт запрещены.
    """

    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise UnsafeUrlError(
            "Разрешён только адрес https://books.toscrape.com. "
            f"Схема «{parsed.scheme or 'пустая'}» запрещена."
        )
    # «https://@host/» содержит userinfo, но логин и пароль при этом пустые.
    # Проверка username or password такой адрес пропускает.
    if "@" in parsed.netloc:
        raise UnsafeUrlError("Адрес с логином или паролем запрещён.")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeUrlError("В адресе нет имени сайта.")
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError("Переход на localhost запрещён.")
    if _is_ip_address(host):
        raise UnsafeUrlError("Переход на IP-адрес или адрес локальной сети запрещён.")
    if host != ALLOWED_HOST:
        raise UnsafeUrlError(
            f"Переход на посторонний сайт {host} запрещён. "
            "Парсер работает только с books.toscrape.com."
        )
    _reject_disallowed_port(parsed)
    return url


def _reject_disallowed_port(parsed) -> None:
    """Разрешает только отсутствие порта или HTTPS-порт 443.

    urllib при буквенном или слишком большом порте выбрасывает ValueError
    из свойства port. Пустой порт вроде «host:» он считает отсутствующим.
    Оба случая здесь становятся UnsafeUrlError, без чужого traceback.
    """

    explicit_port = _explicit_port_text(parsed.netloc)
    if explicit_port == "":
        raise UnsafeUrlError(
            "Пустой порт в адресе запрещён. Разрешён только HTTPS-порт 443."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        shown = explicit_port if explicit_port is not None else ""
        raise UnsafeUrlError(
            f"Некорректный порт «{shown}» запрещён. Разрешён только HTTPS-порт 443."
        ) from exc
    if port not in (None, 443):
        raise UnsafeUrlError(
            f"Нестандартный порт {port} запрещён. Разрешён только HTTPS-порт 443."
        )


def _explicit_port_text(netloc: str) -> str | None:
    """Возвращает сырой текст порта.

    None — двоеточия порта нет. Пустая строка — двоеточие есть, а номера нет.
    """

    _, _, hostinfo = netloc.rpartition("@")
    if hostinfo.startswith("["):
        bracket_end = hostinfo.find("]")
        if bracket_end == -1:
            return None
        rest = hostinfo[bracket_end + 1 :]
        if rest.startswith(":"):
            return rest[1:]
        return None
    if ":" not in hostinfo:
        return None
    return hostinfo.partition(":")[2]


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
