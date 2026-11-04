# python3 ts=4space
"""The list.manifest.json pre pass: collecting per architecture digests into repo_db.

A multi architecture docker image stores each architecture under a sha256__<hex>
directory. The manifest.json in there can only recover its real tag from the
list.manifest.json that names the digest, so the list has to be read first.

Only the download is faked; the parsing, the guards and the version recovery are
the real code.
"""

import json
import logging
import pathlib
import tempfile
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_docker import (
    ArtifactoryFileProcessorDocker,
)

from .conftest import make_file

DIGEST = "sha256:" + "a" * 64
DIGEST_KEY = "sha256__" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
OTHER_KEY = "sha256__" + "b" * 64

LIST_URI = "/myimage/v1.2.3/list.manifest.json"


def list_manifest(*digests: str) -> str:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [{"digest": d, "platform": {"architecture": "amd64", "os": "linux"}} for d in digests],
        }
    )


class FakeDownloadApi:
    """Writes the canned payload to a temp file, as a real download would."""

    def __init__(
        self,
        payload: str,
        *,
        verify_ok: bool | None = True,
        fails: bool = False,
    ) -> None:
        self.payload = payload
        self.verify_ok = verify_ok
        self.fails = fails

    def download_one_file_with_verify(
        self,
        *,
        file: Any,
        download_dir: str,
        target_name: str | None = None,
    ) -> tuple[str | None, bool | None]:
        if self.fails:
            return None, None

        target = pathlib.Path(tempfile.mkdtemp()) / "list.manifest.json"
        target.write_text(self.payload)
        return str(target), self.verify_ok


def processor(*, uri: str, api: Any, repo_db: dict[str, Any]) -> Any:
    proc = ArtifactoryFileProcessorDocker.__new__(ArtifactoryFileProcessorDocker)
    file = make_file(uri=uri, package_type="docker", repo_name="docker-local")

    proc.file = file
    proc.repo = file.repo
    proc.uri = uri
    proc.filename = uri.split("/")[-1]
    proc.artifactory_api = api
    proc.download_dir = tempfile.mkdtemp()
    proc.repo_db = repo_db
    proc.files_to_remove = []
    proc.purl_info = PurlInfo()
    proc.docker_version = None
    return proc


def collect(payload: str, **kwargs: Any) -> dict[str, Any]:
    repo_db: dict[str, Any] = {}
    proc = processor(uri=LIST_URI, api=FakeDownloadApi(payload, **kwargs), repo_db=repo_db)
    proc.collect_list_manifest_info()
    return repo_db


# ------------------------------------------------------------- collection


def test_each_digest_becomes_a_repo_db_entry() -> None:
    repo_db = collect(list_manifest(DIGEST, OTHER_DIGEST))
    assert set(repo_db) == {DIGEST_KEY, OTHER_KEY}


def test_the_key_uses_the_artifactory_directory_form() -> None:
    """Artifactory names the directory sha256__<hex>, not sha256:<hex>."""
    for key in collect(list_manifest(DIGEST)):
        assert key.startswith("sha256__")
        assert ":" not in key


def test_the_entry_records_the_uri_of_the_list_that_named_it() -> None:
    repo_db = collect(list_manifest(DIGEST))
    assert repo_db[DIGEST_KEY]["__uri__"] == LIST_URI.split("/")


def test_an_existing_entry_is_not_overwritten() -> None:
    repo_db: dict[str, Any] = {DIGEST_KEY: {"__uri__": ["", "first", "wins"]}}
    proc = processor(uri=LIST_URI, api=FakeDownloadApi(list_manifest(DIGEST)), repo_db=repo_db)
    proc.collect_list_manifest_info()
    assert repo_db[DIGEST_KEY]["__uri__"] == ["", "first", "wins"]


def test_an_empty_manifest_list_collects_nothing() -> None:
    assert collect(list_manifest()) == {}


# ------------------------------------------------------------------ guards
# None of these may abort the run: the image just keeps its digest as version.


def test_a_failed_download_is_logged_not_fatal(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        assert collect(list_manifest(DIGEST), fails=True) == {}
    assert "download failed" in caplog.text


def test_a_digest_mismatch_does_not_populate_repo_db(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        assert collect(list_manifest(DIGEST), verify_ok=False) == {}
    assert "digest mismatch" in caplog.text


def test_nothing_to_verify_against_is_still_accepted() -> None:
    """verify_ok None means no sha was available, which is not a failure."""
    assert set(collect(list_manifest(DIGEST), verify_ok=None)) == {DIGEST_KEY}


def test_unreadable_json_is_logged_not_fatal(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        assert collect("{not json") == {}
    assert "as json" in caplog.text


def test_manifests_of_the_wrong_type_is_logged_not_fatal(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        assert collect(json.dumps({"manifests": {"a": 1}})) == {}
    assert "not a list" in caplog.text


def test_a_missing_manifests_key_collects_nothing() -> None:
    assert collect(json.dumps({"schemaVersion": 2})) == {}


@pytest.mark.parametrize(
    "manifests",
    [
        [{"digest": "nocolon"}],
        [{"digest": ""}],
        [{"platform": {"architecture": "amd64"}}],
        ["not a dict"],
    ],
)
def test_malformed_entries_are_skipped(manifests: list[Any]) -> None:
    assert collect(json.dumps({"manifests": manifests})) == {}


def test_good_entries_survive_a_malformed_neighbour() -> None:
    payload = json.dumps({"manifests": [{"digest": "nocolon"}, {"digest": DIGEST}]})
    assert set(collect(payload)) == {DIGEST_KEY}


# -------------------------------------------------------- version recovery


def recover(*, uri: str, repo_db: dict[str, Any]) -> Any:
    proc = processor(uri=uri, api=FakeDownloadApi(""), repo_db=repo_db)
    proc._try_extract_version_from_manifest_uri_and_repo_db()
    return proc.docker_version


def test_a_digest_directory_recovers_the_real_tag() -> None:
    repo_db = collect(list_manifest(DIGEST))
    assert recover(uri=f"/myimage/{DIGEST_KEY}/manifest.json", repo_db=repo_db) == "v1.2.3"


def test_a_plain_tag_is_used_as_is() -> None:
    assert recover(uri="/myimage/v1.2.3/manifest.json", repo_db={}) == "v1.2.3"


def test_an_unknown_digest_keeps_the_digest_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """The old code failed this silently; the digest then became the purl version."""
    uri = f"/myimage/{DIGEST_KEY}/manifest.json"
    with caplog.at_level(logging.WARNING):
        assert recover(uri=uri, repo_db={}) == DIGEST_KEY
    assert "no list.manifest.json entry" in caplog.text


def test_a_plain_tag_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        recover(uri="/myimage/latest/manifest.json", repo_db={})
    assert caplog.text == ""


# --------------------------------------------------------------- ordering
# The reason the pre pass exists.


def test_recovery_works_when_the_digest_dir_is_reached_before_the_list() -> None:
    """Artifactory does not guarantee an order, and 'sha256__' sorts before 'v1.2.3'.

    With the pre pass, repo_db is already filled by the time the main loop reaches
    the digest directory, whatever order the listing came back in.
    """
    repo_db: dict[str, Any] = {}

    # the pre pass runs first, regardless of where the list sits in the listing
    processor(
        uri=LIST_URI,
        api=FakeDownloadApi(list_manifest(DIGEST)),
        repo_db=repo_db,
    ).collect_list_manifest_info()

    # the main loop then reaches the digest directory
    assert recover(uri=f"/myimage/{DIGEST_KEY}/manifest.json", repo_db=repo_db) == "v1.2.3"
