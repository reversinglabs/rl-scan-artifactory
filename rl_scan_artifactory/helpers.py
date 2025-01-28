from typing import Dict

from .exceptions import SpectraAssureInvalidAction


def set_proxy(
    *,
    server: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
) -> Dict[str, str]:
    proxies: Dict[str, str] = {}

    if server is None:
        return proxies

    if port is None:
        msg = "when specifying a proxy server, you also must specify a proxy port"
        raise SpectraAssureInvalidAction(message=msg)

    if user is None:
        return {
            "http": f"http://{server}:{port}",
            "https": f"http://{server}:{port}",
        }

    return {
        "http": f"http://{user}:{password}@{server}:{port}",
        "https": f"http://{user}:{password}@{server}:{port}",
    }
