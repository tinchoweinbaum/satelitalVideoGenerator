"""Logging a consola y archivo, con aviso por mail opcional ante errores."""

from __future__ import annotations

import json
import logging
import smtplib
import sys
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from typing import List

from config import LoggingConfig

LOGGER_NAME = "satelital"

_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_BACKUPS = 3


class _EmailAlertHandler(logging.Handler):
    """Envía un mail por cada registro de nivel ERROR o superior."""

    def __init__(self, config: LoggingConfig) -> None:
        super().__init__(level=logging.ERROR)
        self._config = config

    def _recipients(self) -> List[str]:
        try:
            with open(self._config.emails_file, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [str(item).strip() for item in data if str(item).strip()]

    def emit(self, record: logging.LogRecord) -> None:
        recipients = self._recipients()
        if not recipients or not self._config.smtp_user or not self._config.smtp_password:
            return
        message = MIMEText(self.format(record), "plain", "utf-8")
        message["Subject"] = "ERROR EN EL GENERADOR DE VIDEOS DE MAPAS SATELITALES"
        message["From"] = self._config.smtp_user
        message["To"] = ", ".join(recipients)
        try:
            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=20) as server:
                server.starttls()
                server.login(self._config.smtp_user, self._config.smtp_password)
                server.sendmail(self._config.smtp_user, recipients, message.as_string())
        except Exception:  # noqa: BLE001 - un fallo de mail nunca debe frenar el proceso
            self.handleError(record)


def setup_logging(config: LoggingConfig) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, config.level, logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    config.file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        config.file, maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUPS, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if config.email_on_error:
        email_handler = _EmailAlertHandler(config)
        email_handler.setFormatter(formatter)
        logger.addHandler(email_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
