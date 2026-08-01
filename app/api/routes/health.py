from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str
    version: str


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["reachable"]


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        version=settings.app_version,
    )


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
)
async def database_health_check(
    database: Annotated[AsyncSession, Depends(get_db)],
) -> DatabaseHealthResponse:
    try:
        await database.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from error

    return DatabaseHealthResponse(
        status="ok",
        database="reachable",
    )
