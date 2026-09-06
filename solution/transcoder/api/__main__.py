import socket
import sys

import uvicorn

from transcoder.config import settings


def port_is_free(host: str, port: int) -> bool:
    """True if nothing answers on (host, port).

    On Windows, binding 0.0.0.0 does not reliably fail just because another
    process already holds 127.0.0.1 on the same port -- and the more specific
    loopback listener wins for local traffic anyway. So the right question is
    whether something ANSWERS on loopback, not whether we can bind.
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        result = sock.connect_ex((probe_host, port))
    return result != 0


def main():
    if not port_is_free(settings.API_HOST, settings.API_PORT):
        print(
            f"Port {settings.API_PORT} is already in use by another process. "
            "Free the port, or set API_PORT to a different value and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Construct the app only after refusing an occupied port.
    from transcoder.api.app import create_app

    app = create_app()
    server = uvicorn.Server(uvicorn.Config(
        app, host=settings.API_HOST, port=settings.API_PORT,
        timeout_graceful_shutdown=5,  # Do not wait forever for SSE streams.
    ))

    def request_shutdown():
        server.should_exit = True

    app.state.request_shutdown = request_shutdown
    server.run()


if __name__ == "__main__":
    main()
