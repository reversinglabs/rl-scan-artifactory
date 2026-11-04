# python3 ts=4space
"""Setting properties, and the fallback when a recursive update is refused.

Artifactory 7.104.x and later can cap how many artifacts one recursive property
update may touch. The api defines no status code for that case — the documented
responses of setItemProperties are 204, 400, 401, 403 and 404 — so the fallback
triggers on a 400 from a recursive call and cannot be narrower than that.

Only the http layer is faked; the decision logic is the real code.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_api import ArtifactoryApi
from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.constants import RECURSIVE_PROPS_RETRY_STATUS

# the real refusal, as observed on Artifactory 7.161 with the cap set to 1
CAP_MESSAGE = "Cannot add property recursively to nmpjs.org-cache:@eslint-community because it has more than 1 items."

FOLDER = "/myimage/v1.2.3"
KEY = "RL.progress"
VALUE = "done"


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            msg = "no json"
            raise ValueError(msg)
        return self._payload


def error_body(message: str, status: int = 400) -> dict[str, Any]:
    """The ErrorResponse shape from the openapi definition."""
    return {"errors": [{"status": status, "message": message}]}


def listing(*names: str) -> dict[str, Any]:
    return {
        "uri": FOLDER,
        "files": [
            {"uri": "/sub", "folder": True},
            *({"uri": name, "folder": False} for name in names),
        ],
    }


class FakeApi:
    """ArtifactoryApi with only the two http calls replaced."""

    def __init__(
        self,
        *,
        put_results: list[FakeResponse],
        list_result: FakeResponse | None = None,
    ) -> None:
        self.api: Any = ArtifactoryApi.__new__(ArtifactoryApi)
        self.api.base_url = "https://artifactory.example.com/artifactory"
        self.put_results = put_results
        self.list_result = list_result

        self.puts: list[dict[str, Any]] = []
        self.gets: list[str] = []

        # patch the two http calls; everything above them is the real code
        setattr(self.api, "_request_put", self._request_put)  # noqa: B010
        setattr(self.api, "_request_get", self._request_get)  # noqa: B010

    def _request_put(self, url: str, params: dict[str, Any] | None = None) -> FakeResponse:
        self.puts.append({"url": url, "params": params})
        if len(self.put_results) > 1:
            return self.put_results.pop(0)
        return self.put_results[0]

    def _request_get(self, url: str) -> FakeResponse:
        self.gets.append(url)
        if self.list_result is None:
            return FakeResponse(404)
        return self.list_result


def repo(*, repo_type: str = "local") -> ArtifactoryRepoInfo:
    return ArtifactoryRepoInfo(
        name="docker-local",
        repo_type=repo_type,
        package_type="docker",
        layout="simple",
    )


def set_prop(fake: FakeApi, *, recursive: bool = True) -> bool:
    result: bool = fake.api.put_one_prop(
        repo=repo(),
        item_uri=FOLDER,
        key=KEY,
        value=VALUE,
        recursive=recursive,
    )
    return result


# ------------------------------------------------------------- happy path


def test_a_successful_recursive_update_makes_one_call() -> None:
    fake = FakeApi(put_results=[FakeResponse(204)])
    assert set_prop(fake) is True
    assert len(fake.puts) == 1
    assert fake.gets == []


def test_the_recursive_flag_is_sent() -> None:
    fake = FakeApi(put_results=[FakeResponse(204)])
    set_prop(fake)
    assert fake.puts[0]["params"]["recursive"] == 1
    assert fake.puts[0]["params"]["properties"] == f"{KEY}={VALUE}"


def test_a_remote_repository_writes_to_the_cache() -> None:
    fake = FakeApi(put_results=[FakeResponse(204)])
    fake.api.put_one_prop(
        repo=repo(repo_type="remote"),
        item_uri=FOLDER,
        key=KEY,
        value=VALUE,
    )
    assert "docker-local-cache" in fake.puts[0]["url"]


# --------------------------------------------------- statuses that do not retry


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_status_the_split_cannot_help_is_not_retried(status: int) -> None:
    """Credentials, permissions and a missing item fail the same way per item."""
    fake = FakeApi(put_results=[FakeResponse(status, error_body("nope", status))])
    assert set_prop(fake) is False
    assert len(fake.puts) == 1
    assert fake.gets == []


def test_a_non_recursive_failure_is_not_retried() -> None:
    fake = FakeApi(put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS)])
    assert set_prop(fake, recursive=False) is False
    assert len(fake.puts) == 1


def test_the_server_error_message_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeApi(put_results=[FakeResponse(403, error_body("no annotate permission", 403))])
    with caplog.at_level(logging.ERROR):
        set_prop(fake)
    assert "no annotate permission" in caplog.text


def test_a_failure_without_a_json_body_is_still_reported(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeApi(put_results=[FakeResponse(403)])
    with caplog.at_level(logging.ERROR):
        assert set_prop(fake) is False
    assert "403" in caplog.text


# ------------------------------------------------------------- the fallback


def refused_then(
    *later: FakeResponse,
    files: tuple[str, ...] = ("/a.bin", "/b.bin"),
    message: str = CAP_MESSAGE,
) -> FakeApi:
    return FakeApi(
        put_results=[
            FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(message)),
            *later,
        ],
        list_result=FakeResponse(200, listing(*files)),
    )


def test_a_refused_recursive_update_is_retried_per_item() -> None:
    fake = refused_then(FakeResponse(204))
    assert set_prop(fake) is True
    assert len(fake.puts) == 3  # the recursive attempt, then one per file


def test_the_per_item_calls_are_not_recursive() -> None:
    fake = refused_then(FakeResponse(204))
    set_prop(fake)
    assert [p["params"]["recursive"] for p in fake.puts] == [1, 0, 0]


def test_the_per_item_calls_address_each_file() -> None:
    fake = refused_then(FakeResponse(204))
    set_prop(fake)
    assert fake.puts[1]["url"].endswith(f"{FOLDER}/a.bin")
    assert fake.puts[2]["url"].endswith(f"{FOLDER}/b.bin")


def test_folders_in_the_listing_are_skipped() -> None:
    """listFolders=0 is requested, but a folder entry must not become a target."""
    fake = refused_then(FakeResponse(204))
    set_prop(fake)
    assert not any(p["url"].endswith("/sub") for p in fake.puts)


def test_the_listing_is_deep_and_below_the_folder() -> None:
    fake = refused_then(FakeResponse(204))
    set_prop(fake)
    assert fake.gets[0].endswith(f"{FOLDER}?list&deep=1&listFolders=0")


def test_the_fallback_warns_with_the_item_count(caplog: pytest.LogCaptureFixture) -> None:
    fake = refused_then(FakeResponse(204))
    with caplog.at_level(logging.WARNING):
        set_prop(fake)
    assert "retrying 2 item(s) one by one" in caplog.text


def test_one_failing_item_does_not_stop_the_others() -> None:
    fake = refused_then(FakeResponse(404), FakeResponse(204))
    assert set_prop(fake) is False
    assert len(fake.puts) == 3  # both files were still attempted


def test_a_partial_failure_is_reported_with_counts(caplog: pytest.LogCaptureFixture) -> None:
    fake = refused_then(FakeResponse(404), FakeResponse(204))
    with caplog.at_level(logging.ERROR):
        set_prop(fake)
    assert "1 of 2 item(s)" in caplog.text


def test_a_listing_that_fails_gives_up(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeApi(
        put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE))],
        list_result=FakeResponse(500),
    )
    with caplog.at_level(logging.ERROR):
        assert set_prop(fake) is False
    assert len(fake.puts) == 1


def test_an_empty_folder_gives_up_rather_than_claiming_success() -> None:
    fake = FakeApi(
        put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE))],
        list_result=FakeResponse(200, {"uri": FOLDER, "files": []}),
    )
    assert set_prop(fake) is False


def test_a_malformed_properties_value_fails_everywhere(caplog: pytest.LogCaptureFixture) -> None:
    """A 400 can also mean a bad properties value; then the per item calls fail too.

    The retry still happens on an unrecognised 400, because the cap message is not
    part of the api contract and a rewording must not silently disable the fallback.
    """
    fake = refused_then(
        FakeResponse(400, error_body("malformed properties")),
        message="The properties parameter is missing or malformed.",
    )
    with caplog.at_level(logging.ERROR):
        assert set_prop(fake) is False
    assert "malformed properties" in caplog.text


# --------------------------------------------------- recognising the cap


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (CAP_MESSAGE, "1"),
        (CAP_MESSAGE.replace("1 items", "5000 items"), "5000"),
        ("Cannot delete property recursively to r:p because it has more than 5000 items.", "5000"),
        ("The properties parameter is missing or malformed.", None),
        ("", None),
    ],
)
def test_the_cap_message_yields_its_limit(message: str, expected: str | None) -> None:
    assert ArtifactoryApi._recursive_limit_from(message) == expected


def test_a_recognised_cap_logs_the_limit(caplog: pytest.LogCaptureFixture) -> None:
    fake = refused_then(FakeResponse(204))
    with caplog.at_level(logging.WARNING):
        set_prop(fake)
    assert "caps recursive property updates at 1 item(s)" in caplog.text


def test_an_unrecognised_400_says_so_and_still_retries(caplog: pytest.LogCaptureFixture) -> None:
    fake = refused_then(FakeResponse(204), message="something new and unexpected")
    with caplog.at_level(logging.WARNING):
        assert set_prop(fake) is True
    assert "unrecognised 400" in caplog.text
    assert len(fake.puts) == 3


# ------------------------------------------------- the canonical storage name
# Only a local repository and the cache side of a remote one hold artifacts.
# Reads through the bare remote name happen to work — Artifactory resolves them
# and answers with the cache uri — but that is convenience, not contract.


@pytest.mark.parametrize(
    ("repo_type", "expected"),
    [
        ("local", "docker-local"),
        ("remote", "docker-local-cache"),
        ("REMOTE", "docker-local-cache"),
    ],
)
def test_the_canonical_storage_name(repo_type: str, expected: str) -> None:
    assert ArtifactoryApi._storage_repo_name(repo(repo_type=repo_type)) == expected


def test_every_storage_call_uses_the_canonical_name() -> None:
    """Listing, reading properties and writing them must agree on the repository."""
    fake = FakeApi(
        put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE))],
        list_result=FakeResponse(200, listing("/a.bin")),
    )
    fake.api.put_one_prop(
        repo=repo(repo_type="remote"),
        item_uri=FOLDER,
        key=KEY,
        value=VALUE,
        recursive=True,
    )

    for url in [p["url"] for p in fake.puts] + fake.gets:
        assert "docker-local-cache" in url
        assert "/docker-local/" not in url


# ------------------------------------------------- deleting, the same way
# The cap of R11.4.3 applies to deleting properties as it does to setting them,
# and the refusal reads the same way.


def del_prop(fake: FakeApi, *, recursive: bool = True) -> bool:
    result: bool = fake.api.del_one_prop(
        repo=repo(),
        item_uri=FOLDER,
        key=KEY,
        recursive=recursive,
    )
    return result


class FakeDeleteApi(FakeApi):
    """Same recorder, but the delete verb."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        setattr(self.api, "_request_del", self._request_del)  # noqa: B010

    def _request_del(self, url: str, params: dict[str, Any] | None = None) -> FakeResponse:
        self.puts.append({"url": url, "params": params})
        if len(self.put_results) > 1:
            return self.put_results.pop(0)
        return self.put_results[0]


def test_a_successful_recursive_delete_makes_one_call() -> None:
    fake = FakeDeleteApi(put_results=[FakeResponse(204)])
    assert del_prop(fake) is True
    assert len(fake.puts) == 1


def test_a_refused_recursive_delete_is_retried_per_item() -> None:
    fake = FakeDeleteApi(
        put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE)), FakeResponse(204)],
        list_result=FakeResponse(200, listing("/a.bin", "/b.bin")),
    )
    assert del_prop(fake) is True
    assert len(fake.puts) == 3  # the recursive attempt, then one per file


def test_the_per_item_deletes_are_not_recursive() -> None:
    fake = FakeDeleteApi(
        put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE)), FakeResponse(204)],
        list_result=FakeResponse(200, listing("/a.bin")),
    )
    del_prop(fake)
    assert [p["params"]["recursive"] for p in fake.puts] == [1, 0]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_delete_status_the_split_cannot_help_is_not_retried(status: int) -> None:
    fake = FakeDeleteApi(put_results=[FakeResponse(status, error_body("nope", status))])
    assert del_prop(fake) is False
    assert len(fake.puts) == 1


def test_a_non_recursive_delete_failure_is_not_retried() -> None:
    fake = FakeDeleteApi(put_results=[FakeResponse(RECURSIVE_PROPS_RETRY_STATUS)])
    assert del_prop(fake, recursive=False) is False
    assert len(fake.puts) == 1


def test_one_failing_delete_does_not_stop_the_others() -> None:
    fake = FakeDeleteApi(
        put_results=[
            FakeResponse(RECURSIVE_PROPS_RETRY_STATUS, error_body(CAP_MESSAGE)),
            FakeResponse(404),
            FakeResponse(204),
        ],
        list_result=FakeResponse(200, listing("/a.bin", "/b.bin")),
    )
    assert del_prop(fake) is False
    assert len(fake.puts) == 3
