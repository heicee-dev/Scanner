"""Entry point for the Scanner desktop application."""

from __future__ import annotations

import logging
import sys

from src.app import App

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Import the App class and run the application's mainloop()."""
    try:
        app = App()
        app.mainloop()
    except Exception:
        logger.exception("Failed to start the Scanner application")
        sys.exit(1)


if __name__ == "__main__":
    main()
