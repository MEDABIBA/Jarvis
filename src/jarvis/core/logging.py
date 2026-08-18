import sys
from pathlib import Path

from loguru import logger

from jarvis.core import get_settings


def setup_logging() -> None:
    """Configure application-wide logging handlers and sinks.

    Removes default Loguru handlers and establishes two output destinations:
    1. Standard error (console) sink with colored, level-sensitive formatting
       (DEBUG or INFO based on application settings).
    2. Daily rotating, compressed log file sink in the `./logs` directory with
       asynchronous thread-safe queuing and dynamic diagnostic reporting.
    """
    settings = get_settings()

    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=log_format,
        level="DEBUG" if settings.debug else "INFO",
        colorize=True,
    )

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "jarvis_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        level="DEBUG",
        enqueue=True,
        backtrace=True,
        diagnose=settings.debug,
    )
