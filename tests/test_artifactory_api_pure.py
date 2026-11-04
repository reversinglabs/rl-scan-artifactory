# python3 ts=4space
"""The pure (no-network) parts of ArtifactoryApi: digest verification and path building."""

import hashlib
import logging
import pathlib
from typing import (
    Any,
)

import pytest
import requests

from rl_scan_artifactory.artifactory_api import ArtifactoryApi
from rl_scan_artifactory.constants import (
    HTTP_RETRY_BACKOFF,
    HTTP_RETRY_TOTAL,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction

CONTENT = b"the quick brown fox\n" * 10_000  # larger than VERIFY_BUF_SIZE, forces chunking


@pytest.fixture
def downloaded(tmp_path: pathlib.Path) -> tuple[str, str]:
    target = tmp_path / "artifact.bin"
    target.write_bytes(CONTENT)
    return str(target), hashlib.sha256(CONTENT).hexdigest()


# ------------------------------------------------------- digest verification


def test_a_matching_digest_verifies(downloaded: tuple[str, str]) -> None:
    path, digest = downloaded
    assert ArtifactoryApi._verify_download_file(sha256=digest, download_path=path) is True


def test_digest_comparison_is_case_insensitive(downloaded: tuple[str, str]) -> None:
    path, digest = downloaded
    assert ArtifactoryApi._verify_download_file(sha256=digest.upper(), download_path=path) is True


def test_a_wrong_digest_fails(downloaded: tuple[str, str]) -> None:
    path, _digest = downloaded
    assert ArtifactoryApi._verify_download_file(sha256="0" * 64, download_path=path) is False


def test_a_truncated_file_fails(downloaded: tuple[str, str]) -> None:
    path, digest = downloaded
    pathlib.Path(path).write_bytes(CONTENT[:-1])
    assert ArtifactoryApi._verify_download_file(sha256=digest, download_path=path) is False


def test_an_empty_file_has_the_empty_digest(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    empty_digest = hashlib.sha256(b"").hexdigest()
    assert ArtifactoryApi._verify_download_file(sha256=empty_digest, download_path=str(target)) is True


def test_a_missing_file_raises(tmp_path: pathlib.Path) -> None:
    with pytest.raises(OSError):  # noqa: PT011
        ArtifactoryApi._verify_download_file(sha256="0" * 64, download_path=str(tmp_path / "gone.bin"))


def test_an_empty_expected_digest_is_rejected_explicitly(downloaded: tuple[str, str]) -> None:
    """'nothing to verify against' is not a verification outcome: the caller decides
    that before getting here, so an empty digest arriving is a caller bug."""
    path, _digest = downloaded
    with pytest.raises(SpectraAssureInvalidAction, match="no digest"):
        ArtifactoryApi._verify_download_file(sha256="", download_path=path)


# ------------------------------------------------------------ target naming


def test_target_name_defaults_to_the_file_name() -> None:
    got = ArtifactoryApi._make_target_name(
        download_dir="/tmp/dl",
        file_name="artifact.bin",
        target_name=None,
    )
    assert got == "/tmp/dl/artifact.bin"


def test_an_explicit_target_name_wins() -> None:
    got = ArtifactoryApi._make_target_name(
        download_dir="/tmp/dl",
        file_name="artifact.bin",
        target_name="sha256__abcdef",
    )
    assert got == "/tmp/dl/sha256__abcdef"


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "../escaped.bin", "a/b", "sub\\file", ".", "..", ""],
)
def test_a_target_name_that_is_not_a_plain_file_name_is_refused(hostile: str) -> None:
    """Both names come from a repository uri we do not control."""
    with pytest.raises(SpectraAssureInvalidAction, match="plain file name"):
        ArtifactoryApi._make_target_name(
            download_dir="/tmp/dl",
            file_name="artifact.bin",
            target_name=hostile,
        )


@pytest.mark.parametrize("hostile", ["..", "", "../escaped.bin"])
def test_a_file_name_that_is_not_a_plain_file_name_is_refused(hostile: str) -> None:
    """os.path.basename('/a/..') is '..', so the file_name side needs the same guard."""
    with pytest.raises(SpectraAssureInvalidAction, match="plain file name"):
        ArtifactoryApi._make_target_name(
            download_dir="/tmp/dl",
            file_name=hostile,
            target_name=None,
        )


@pytest.mark.parametrize(
    "name",
    ["artifact.bin", "sha256__abcdef", "a-b_c.1.2.3.tgz", "manifest.json-reports.zip"],
)
def test_the_names_real_callers_pass_are_accepted(name: str) -> None:
    got = ArtifactoryApi._make_target_name(
        download_dir="/tmp/dl",
        file_name=name,
        target_name=None,
    )
    assert got == f"/tmp/dl/{name}"
    assert pathlib.Path(got).resolve().is_relative_to(pathlib.Path("/tmp/dl"))


# ------------------------------------------------------------ retrying
# A run walks thousands of artifacts over minutes or hours, so a connection that
# drops once is expected rather than exceptional. A single dropped connection on
# one report upload used to end the whole run.


def adapter() -> Any:
    session = ArtifactoryApi._make_session()
    return session.get_adapter("https://artifactory.example.com/")


def retry_policy() -> Any:
    return adapter().max_retries


def test_both_schemes_get_the_adapter() -> None:
    session = ArtifactoryApi._make_session()
    assert session.get_adapter("https://x/") is session.get_adapter("http://x/")


def test_a_dropped_connection_is_retried() -> None:
    policy = retry_policy()
    assert policy.connect == HTTP_RETRY_TOTAL
    assert policy.read == HTTP_RETRY_TOTAL


def test_the_waits_grow() -> None:
    """A server that is busy is not helped by three requests in a row."""
    assert retry_policy().backoff_factor == HTTP_RETRY_BACKOFF


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_status_meaning_not_now_is_retried(status: int) -> None:
    assert status in retry_policy().status_forcelist


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_a_status_that_is_an_answer_is_not_retried(status: int) -> None:
    """Artifactory answered. Retrying would only be slower, and the 400 of the
    recursive property cap is handled by its own fallback (R11.5.x)."""
    assert status not in retry_policy().status_forcelist


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "HEAD"])
def test_the_verbs_this_integration_uses_are_retried(method: str) -> None:
    assert method in retry_policy().allowed_methods


def test_a_retried_status_is_not_raised_as_an_exception() -> None:
    """The callers read status codes; they must still see the last response."""
    assert retry_policy().raise_on_status is False


# ------------------------------------------- a refused download is an answer
# A run against an artifactory whose policy plugin blocks failed artifacts spent
# two attempts and ten seconds on each one, then reported "download failed",
# which sends people looking at the network. 403 is an answer, and it does not
# change within a run.


class DownloadResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} Client Error: ")
            error.response = self
            raise error

    def iter_content(self, chunk_size: int = 0) -> list[bytes]:
        return [b"the artifact"]


class DownloadSession:
    def __init__(self, status: int) -> None:
        self.status = status
        self.attempts = 0

    def get(self, url: str, **kwargs: Any) -> DownloadResponse:
        self.attempts += 1
        return DownloadResponse(self.status)


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wait between attempts is real; these tests only care that it happened."""
    import time

    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def download(status: int, tmp_path: pathlib.Path) -> tuple[str | None, int]:
    api: Any = ArtifactoryApi.__new__(ArtifactoryApi)
    api.api_key = None
    api.token = "a-token"
    api.user = "a-user"
    api.timeout = 5
    api.proxies = None
    api.session = DownloadSession(status)

    got = api.download_url_to_file(url="https://artifactory.example.com/x", file_path=str(tmp_path / "f.bin"))
    return got, api.session.attempts


@pytest.mark.parametrize("status", [401, 403, 404, 405, 410])
def test_an_answered_status_is_asked_once(status: int, tmp_path: pathlib.Path) -> None:
    got, attempts = download(status, tmp_path)

    assert got is None
    assert attempts == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_status_that_may_pass_is_retried(status: int, tmp_path: pathlib.Path) -> None:
    """A server that is briefly unwell can answer differently on the second ask."""
    got, attempts = download(status, tmp_path)

    assert got is None
    assert attempts > 1


def test_a_successful_download_is_asked_once(tmp_path: pathlib.Path) -> None:
    got, attempts = download(200, tmp_path)

    assert got is not None
    assert attempts == 1


def test_a_403_says_what_it_probably_is(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """'download failed' sent someone looking at the network for an hour."""
    with caplog.at_level(logging.ERROR):
        download(403, tmp_path)

    assert "blocked by a policy" in caplog.text
    assert "not permitted" in caplog.text


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "blocked by a policy"), (404, "not found"), (401, "not authenticated")],
)
def test_each_refusal_names_itself(status: int, expected: str) -> None:
    assert expected in ArtifactoryApi._download_refusal(status)


def test_an_unlisted_refusal_still_names_its_status() -> None:
    assert "418" in ArtifactoryApi._download_refusal(418)
