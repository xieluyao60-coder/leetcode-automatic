from __future__ import annotations

import logging
import sys


try:
    from loguru import logger as logger
except ImportError:

    class _CompatLogger:
        def __init__(self) -> None:
            self._logger = logging.getLogger("lc_auto")
            if not self._logger.handlers:
                handler = logging.StreamHandler(sys.stderr)
                handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
                self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

        def remove(self) -> None:
            for handler in list(self._logger.handlers):
                self._logger.removeHandler(handler)

        def add(self, sink, level: str = "INFO", format: str | None = None) -> None:
            handler = logging.StreamHandler(sink)
            handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        def info(self, message: str, *args) -> None:
            self._logger.info(message.format(*args))

        def debug(self, message: str, *args) -> None:
            self._logger.debug(message.format(*args))

        def warning(self, message: str, *args) -> None:
            self._logger.warning(message.format(*args))

        def error(self, message: str, *args) -> None:
            self._logger.error(message.format(*args))

    logger = _CompatLogger()
