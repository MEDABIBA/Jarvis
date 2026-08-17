from loguru import logger

from jarvis import __version__
from jarvis.core import setup_logging


def main() -> None:
    setup_logging()

    logger.debug("Started Jarvis with {} version", __version__)


if __name__ == "__main__":
    main()
