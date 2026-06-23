import uvicorn

from transcoder.config import settings
from transcoder.api.app import create_app


def main():
    uvicorn.run(create_app(), host=settings.API_HOST, port=settings.API_PORT)


if __name__ == "__main__":
    main()
