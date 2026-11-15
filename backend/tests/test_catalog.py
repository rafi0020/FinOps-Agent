from sqlalchemy import text

from app.db import get_engine
from app.finance.catalog import CATALOG, METRICS


async def test_catalogue_documents_every_analytics_column_and_nothing_else(seeded):
    async with get_engine("ro").connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'analytics'")
            )
        ).all()
    in_database = {(t, c) for t, c in rows}
    documented = {(t.name, c.name) for t in CATALOG.values() for c in t.columns}
    assert documented == in_database
    assert not any(c.name == "org_id" for t in CATALOG.values() for c in t.columns)


async def test_catalogue_is_served_to_any_signed_in_user(client, team):
    assert (await client.get("/api/catalog")).status_code == 401
    body = (await team.viewer.get("/api/catalog")).json()
    assert {t["name"] for t in body["tables"]} == set(CATALOG)
    assert {m["name"] for m in body["metrics"]} == set(METRICS) >= {"operating_margin", "gross_margin", "dso"}
