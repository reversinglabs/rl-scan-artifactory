# python3 ts=4space
"""set_proxy() builds the requests proxies dict from the 4 proxy cli options."""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction
from rl_scan_artifactory.helpers import (
    is_secret_arg_name,
    redact_secrets,
    set_proxy,
)


def test_no_server_gives_empty_dict() -> None:
    assert set_proxy() == {}
    assert set_proxy(port=3128, user="u", password="p") == {}


def test_server_without_port_is_rejected() -> None:
    with pytest.raises(SpectraAssureInvalidAction):
        set_proxy(server="proxy.example.com")


def test_server_and_port_without_credentials() -> None:
    got = set_proxy(server="proxy.example.com", port=3128)
    assert got == {
        "http": "http://proxy.example.com:3128",
        "https": "http://proxy.example.com:3128",
    }


def test_server_and_port_with_credentials() -> None:
    got = set_proxy(server="proxy.example.com", port=3128, user="bob", password="s3cret")
    assert got == {
        "http": "http://bob:s3cret@proxy.example.com:3128",
        "https": "http://bob:s3cret@proxy.example.com:3128",
    }


def test_https_proxy_url_uses_http_scheme() -> None:
    """Both entries deliberately use the http:// scheme for the proxy itself."""
    got = set_proxy(server="proxy.example.com", port=3128)
    assert got["https"].startswith("http://")


# Proxy credentials are all or nothing (R3.3): either both, or neither.


def test_a_user_without_a_password_is_refused() -> None:
    """It used to build 'http://bob:None@host:port' and send that verbatim."""
    with pytest.raises(SpectraAssureInvalidAction, match="password is missing"):
        set_proxy(server="proxy.example.com", port=3128, user="bob")


def test_a_password_without_a_user_is_refused() -> None:
    with pytest.raises(SpectraAssureInvalidAction, match="user is missing"):
        set_proxy(server="proxy.example.com", port=3128, password="s3cret")


def test_the_refusal_does_not_echo_the_password() -> None:
    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        set_proxy(server="proxy.example.com", port=3128, password="s3cret")
    assert "s3cret" not in str(excinfo.value)


# ------------------------------------------------------------- redaction
# cli_args holds the artifactory token, the portal token, the rl-secure license
# and the proxy password, and <program>.log is always written. Anything that
# renders the whole dict has to go through redact_secrets() first.


SECRET_ARGS: dict[str, Any] = {
    "artifactory_token": "SECRET-ARTIFACTORY",
    "rlportal_access_token": "SECRET-PORTAL",
    "rlsecure_site_key": "SECRET-SITE-KEY",
    "rlsecure_encoded_license": "SECRET-LICENSE",
    "proxy_password": "SECRET-PROXY-PW",
}

PLAIN_ARGS: dict[str, Any] = {
    "artifactory_host": "https://artifactory.example.com",
    "artifactory_user": "admin",
    "proxy_user": "bob",
    "repo": ["r1", "r2"],
    "verbose": False,
    "waittime": 30,
}


@pytest.mark.parametrize("key", sorted(SECRET_ARGS))
def test_every_credential_is_redacted(key: str) -> None:
    got = redact_secrets({**PLAIN_ARGS, **SECRET_ARGS})
    assert got[key] == "***"


def test_no_secret_value_survives_anywhere_in_the_output() -> None:
    """The check that matters: nothing secret in the rendered string."""
    rendered = str(redact_secrets({**PLAIN_ARGS, **SECRET_ARGS}))
    for value in SECRET_ARGS.values():
        assert value not in rendered


@pytest.mark.parametrize("key", sorted(PLAIN_ARGS))
def test_ordinary_values_are_untouched(key: str) -> None:
    got = redact_secrets({**PLAIN_ARGS, **SECRET_ARGS})
    assert got[key] == PLAIN_ARGS[key]


def test_the_input_is_not_modified() -> None:
    original = {**PLAIN_ARGS, **SECRET_ARGS}
    redact_secrets(original)
    assert original["artifactory_token"] == "SECRET-ARTIFACTORY"


@pytest.mark.parametrize("empty", [None, ""])
def test_an_unset_secret_stays_visible_as_unset(empty: Any) -> None:
    """A log should still show which options were not supplied."""
    got = redact_secrets({"artifactory_token": empty})
    assert got["artifactory_token"] == empty


@pytest.mark.parametrize(
    "name",
    [
        "artifactory_token",
        "rlportal_access_token",
        "proxy_password",
        "rlsecure_site_key",
        "rlsecure_encoded_license",
        "SOME_NEW_TOKEN",
        "client_secret",
        "api_key",
    ],
)
def test_names_recognised_as_secret(name: str) -> None:
    """Matching is on the name, so a new secret option is covered on the day it is added."""
    assert is_secret_arg_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["artifactory_host", "artifactory_user", "proxy_user", "repo", "verbose", "log_level"],
)
def test_names_not_recognised_as_secret(name: str) -> None:
    assert is_secret_arg_name(name) is False
