import os

from loguru import logger

from app.core.settings import settings


def setup_logger():
    """Configure Loguru logging for development and production."""

    logger.remove()

    os.makedirs("logs", exist_ok=True)

    is_development = settings.ENV == "development"

    # ---------------------------------------------------------
    # Console
    # ---------------------------------------------------------
    # Development:
    #   DEBUG and above
    #
    # Production:
    #   INFO and above
    #
    # Production INFO/WARNING logs can be collected by
    # Docker/systemd/Gunicorn/etc. without filling app.log.
    # ---------------------------------------------------------

    console_level = "DEBUG" if is_development else "INFO"

    logger.add(
        sink=lambda message: print(message, end=""),
        level=console_level,
        colorize=is_development,
        backtrace=is_development,
        diagnose=is_development,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "{message}"
        ),
    )

    # ---------------------------------------------------------
    # Persistent application error log
    # ---------------------------------------------------------
    # Development:
    #   DEBUG and above
    #
    # Production:
    #   ERROR and CRITICAL only
    # ---------------------------------------------------------

    file_level = "DEBUG" if is_development else "ERROR"

    logger.add(
        "logs/app.log",
        level=file_level,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=is_development,
        diagnose=is_development,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )

    return logger
