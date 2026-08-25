"""Phase 0 stub worker entrypoint.

Proves the shared backend image can boot a second process distinct from the
API. Real job processing (Arq/Celery) is wired up in the ingestion/background
jobs phase.
"""

import logging
import time

from app.core.logging import configure_logging

logger = logging.getLogger("helix.worker")


def main() -> None:
    configure_logging()
    logger.info("worker started (Phase 0 stub, no jobs registered yet)")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
