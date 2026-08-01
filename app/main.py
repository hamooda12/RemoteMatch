from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings


def create_application() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        description=("Remote job aggregation, CV matching, and application tracking platform."),
    )

    application.include_router(
        api_router,
        prefix=settings.api_v1_prefix,
    )

    return application


app = create_application()
