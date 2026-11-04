from typing import (
    Any,
)

from .constants import (
    SECRET_ARG_NAME_PARTS,
    SECRET_REDACTED,
)
from .exceptions import SpectraAssureInvalidAction


def is_secret_arg_name(
    name: str,
) -> bool:
    """True for a cli_args key that holds a credential."""
    lowered = name.lower()
    return any(part in lowered for part in SECRET_ARG_NAME_PARTS)


def redact_secrets(
    cli_args: dict[str, Any],
) -> dict[str, Any]:
    """A copy of cli_args safe to log, print or paste into a ticket.

    The tokens, the license and the proxy password all live in cli_args, and the
    log file is always written, so anything that renders the whole dict has to go
    through here first. A value that is already absent stays absent rather than
    becoming "***", so a log still shows which options were not supplied.
    """
    out: dict[str, Any] = {}
    for key, value in cli_args.items():
        if value is not None and value != "" and is_secret_arg_name(key):
            out[key] = SECRET_REDACTED
            continue
        out[key] = value

    return out


def set_proxy(
    *,
    server: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict[str, str]:
    proxies: dict[str, str] = {}

    if server is None:
        return proxies

    if port is None:
        msg = "when specifying a proxy server, you also must specify a proxy port"
        raise SpectraAssureInvalidAction(message=msg)

    if (user is None) != (password is None):
        # all or nothing: half a credential would be formatted into the url verbatim,
        # as 'http://user:None@host:port', and sent
        missing = "password" if password is None else "user"
        msg = f"a proxy user and a proxy password go together: the proxy {missing} is missing"
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
