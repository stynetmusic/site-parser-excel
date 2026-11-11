"""Настройка сообщений в консоль и в файл журнала."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


LOGGER_NAME = "books_parser"


def setup_logging(log_file: Path) -> logging.Logger:
    """Включает журнал программы.

    В консоли остаётся короткий текст без технических префиксов.
    В файл пишутся время, уровень и модуль — так проще разбирать сбой после запуска.
    """

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    # propagate остаётся включённым. Иначе сообщения books_parser не доходят
    # до корневого логгера, и pytest caplog перестаёт видеть их после запуска
    # программы. При обычном запуске у корня нет своего обработчика, поэтому
    # строка в консоли не печатается дважды.
    logger.propagate = True

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError as exc:
        logger.warning("Не удалось открыть файл журнала %s: %s", log_file, exc)
        return logger

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)
    return logger


@contextmanager
def use_logging(log_file: Path) -> Iterator[logging.Logger]:
    """Включает журнал на время одного запуска и затем возвращает прежнее состояние.

    Без восстановления уровень, обработчики и propagate остаются изменёнными
    до конца процесса. Следующий тест тогда зависит от того, шёл ли перед ним
    запуск программы.
    """

    logger = logging.getLogger(LOGGER_NAME)
    saved_level = logger.level
    saved_propagate = logger.propagate
    saved_handlers = list(logger.handlers)
    setup_logging(log_file)
    try:
        yield logger
    finally:
        created = [handler for handler in list(logger.handlers) if handler not in saved_handlers]
        for handler in created:
            handler.close()
        logger.handlers.clear()
        for handler in saved_handlers:
            logger.addHandler(handler)
        logger.setLevel(saved_level)
        logger.propagate = saved_propagate
