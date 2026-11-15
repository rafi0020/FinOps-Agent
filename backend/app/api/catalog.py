"""The data catalogue, for the Catalogue screen."""

from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.finance.catalog import catalog_payload
from app.security.sessions import Principal

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("")
async def get_catalog(_: Principal = Depends(current_user)) -> dict:
    return catalog_payload()
