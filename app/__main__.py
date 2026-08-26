from app.config import settings
import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
