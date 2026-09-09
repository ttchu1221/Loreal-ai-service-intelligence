from fastapi import FastAPI

from loreal_ai_service_intelligence import __version__
from loreal_ai_service_intelligence.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
