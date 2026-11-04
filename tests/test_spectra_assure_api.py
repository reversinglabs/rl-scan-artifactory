# python3 ts=4space
"""Does this artifact already exist on the portal?

A version existing is not enough: a rebuilt artifact published under the same
version has the same purl and different content, and without comparing the
digest it would be reported as already scanned and never looked at again.

The comparison was present but switched off - `with_compare_digest` was assigned
False twice and never True - with the note "it seems the sha is not always
identical". The case that cannot work is docker, where the thing uploaded is a
bundle this integration builds itself, so artifactory holds no hash of it. Those
callers pass digest=None, which still means "do not compare".

The answer has three states, not two: absent, present with these bytes, and
present with other bytes. The last needs an upload with `replace`, because the
portal refuses an upload to an existing version with a 409; folding it into
"absent" made every rebuilt artifact fail its upload on every run.

Only the sdk client is faked.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.fileinfo import FileInfo
from rl_scan_artifactory.spectra_assure_api import SpectraAssureApi

from .conftest import make_file

PROJECT = "my-repo"
PACKAGE = "mypkg"
VERSION = "1.0"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64

ABSENT = (False, False)
PRESENT = (True, False)
OTHER_BYTES = (False, True)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    @property
    def status_code(self) -> int:
        return 200

    @property
    def text(self) -> str:
        return str(self._payload)


class FakeClient:
    """The sdk client: list() says whether the version exists, status() carries the hashes."""

    def __init__(self, *, version: str | None, hashes: list[list[str]] | None = None) -> None:
        self.version = version
        self.hashes = hashes if hashes is not None else []
        self.status_calls = 0
        self.scans: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeResponse:
        if self.version is None:
            return FakeResponse({})
        return FakeResponse({"version": self.version})

    def status(self, **kwargs: Any) -> FakeResponse:
        self.status_calls += 1
        return FakeResponse(
            {"analysis": {"report": {"info": {"file": {"hashes": self.hashes}}}}},
        )

    def scan(self, **kwargs: Any) -> FakeResponse:
        self.scans.append(kwargs)
        return FakeResponse({})

    def edit(self, **kwargs: Any) -> FakeResponse:
        return FakeResponse({})


def api(client: FakeClient) -> Any:
    instance: Any = SpectraAssureApi.__new__(SpectraAssureApi)
    instance.api_client = client
    return instance


def exists(client: FakeClient, digest: str | None) -> tuple[bool, bool]:
    result: tuple[bool, bool] = api(client).exist_version(
        project=PROJECT,
        package=PACKAGE,
        version=VERSION,
        digest=digest,
    )
    return result


def with_digest(*digests: str) -> FakeClient:
    return FakeClient(version=VERSION, hashes=[["sha256", d] for d in digests])


# ------------------------------------------------------------ does it exist


def test_an_unknown_version_does_not_exist() -> None:
    assert exists(FakeClient(version=None), DIGEST) == ABSENT


def test_a_different_version_does_not_exist() -> None:
    assert exists(FakeClient(version="9.9.9"), DIGEST) == ABSENT


def test_an_unknown_version_is_not_asked_for_its_hashes() -> None:
    """No point fetching the analysis of something that is not there."""
    client = FakeClient(version=None)
    exists(client, DIGEST)
    assert client.status_calls == 0


# --------------------------------------------------------- the digest matters


def test_a_matching_digest_exists() -> None:
    assert exists(with_digest(DIGEST), DIGEST) == PRESENT


def test_a_different_digest_is_other_bytes() -> None:
    """The same version rebuilt: same purl, different content, scan it again."""
    assert exists(with_digest(OTHER_DIGEST), DIGEST) == OTHER_BYTES


def test_the_digest_is_found_among_several() -> None:
    assert exists(with_digest(OTHER_DIGEST, DIGEST), DIGEST) == PRESENT


def test_no_hashes_at_all_is_nothing_to_compare() -> None:
    """A scan still running has no analysis; replacing it would restart it."""
    assert exists(with_digest(), DIGEST) == PRESENT


def test_a_hash_of_another_type_is_nothing_to_compare() -> None:
    client = FakeClient(version=VERSION, hashes=[["md5", DIGEST]])
    assert exists(client, DIGEST) == PRESENT


def test_a_sha256_beside_another_type_still_decides() -> None:
    client = FakeClient(version=VERSION, hashes=[["md5", DIGEST], ["sha256", OTHER_DIGEST]])
    assert exists(client, DIGEST) == OTHER_BYTES


@pytest.mark.parametrize("malformed", [[], ["sha256"], ["only-one-element"]])
def test_a_malformed_hash_entry_is_skipped(malformed: list[str]) -> None:
    """It used to index [0] and [1] unconditionally."""
    client = FakeClient(version=VERSION, hashes=[malformed, ["sha256", DIGEST]])
    assert exists(client, DIGEST) == PRESENT


def test_a_missing_analysis_section_does_not_raise() -> None:
    client = FakeClient(version=VERSION)
    client.status = lambda **kwargs: FakeResponse({})  # type: ignore[method-assign]
    assert exists(client, DIGEST) == PRESENT


# ------------------------------------------------- when not to compare at all


def test_no_digest_means_the_version_alone_decides() -> None:
    """The docker case: the bundle is built here, so artifactory has no hash of it."""
    assert exists(with_digest(OTHER_DIGEST), None) == PRESENT


def test_no_digest_does_not_fetch_the_hashes() -> None:
    client = with_digest(OTHER_DIGEST)
    exists(client, None)
    assert client.status_calls == 0


# ------------------------------------------------------------- the upload


def upload(client: FakeClient, **kwargs: Any) -> dict[str, Any]:
    file: FileInfo = make_file(uri="/mypkg-1.0.tgz")
    ok, _msg = api(client).upload_artifact_to_portal(
        file=file,
        project=PROJECT,
        package=PACKAGE,
        version=VERSION,
        file_path="/dev/null",
        **kwargs,
    )
    assert ok is True
    return client.scans[0]


def test_an_upload_does_not_replace_by_default() -> None:
    """A version that is absent needs no replace, and one uploaded meanwhile must not be overwritten."""
    assert "replace" not in upload(FakeClient(version=None))


def test_an_upload_over_other_bytes_replaces() -> None:
    """Without it the portal answers 409 to an upload to an existing version."""
    assert upload(FakeClient(version=None), replace=True)["replace"] == "true"
