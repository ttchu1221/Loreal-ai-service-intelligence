import uvicorn

from loreal_ai_service_intelligence.config import get_settings


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "loreal_ai_service_intelligence.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=settings.app_reload,
    )


if __name__ == "__main__":
    run()
