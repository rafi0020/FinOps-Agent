"""Run once before the API and workers start: apply migrations, then load demo data if asked to."""

import asyncio
import logging

from alembic import command
from alembic.config import Config

from app.config import get_settings
from app.obs.logging import configure_logging

log = logging.getLogger("finops.bootstrap")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    command.upgrade(Config("alembic.ini"), "head")
    log.info("migrations applied")
    if settings.seed_demo:
        asyncio.run(seed_demo())


async def seed_demo() -> None:
    from seed.demo_users import ensure_demo_users

    await ensure_demo_users()
    log.info("demo accounts ready")
    from seed.generate import generate, has_data

    if not has_data():
        summary = await asyncio.to_thread(generate)
        log.info("demo finance data loaded", extra={"rows": summary.total})
        from app.finance.alerts_eval import evaluate_all

        await evaluate_all()


if __name__ == "__main__":
    main()
