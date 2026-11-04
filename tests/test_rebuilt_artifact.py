# python3 ts=4space
"""A rebuilt artifact is not skipped on the properties of the one it replaced (R10.8).

An ordinary run skips an artifact whose RL.progress says `scanned`, before the
portal is asked anything. A rebuild redeployed under the same path may keep those
properties - for generic it always does, because they live on the side-car - so
the new bytes were never scanned, and the replace of R10.7.5 could not happen.

RL.sha256 now records which bytes the properties are about. A later run compares
it with the sha2 artifactory holds today, which the listing gives for free, and
reads a mismatch as "nothing recorded". No extra call is made, and an item
written before RL.sha256 existed is trusted as it always was.

Only artifactory and the backends are faked.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
    PortalInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_docker import (
    ArtifactoryFileProcessorDocker,
)
from rl_scan_artifactory.constants import (
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_SHA256,
    PROP_SPECTRA_ASSURE_ALL,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
)

from .conftest import make_file
from .test_default_process import processor as default_processor
from .test_generic_process import META_URI
from .test_generic_process import processor as generic_processor

OLD = "a" * 64
NEW = "b" * 64
TARGET_URI = "/a/mypkg-1.0.bin"


def recorded(progress: str = PROGRESS_SCANNED, sha256: str | None = OLD) -> dict[str, list[str]]:
    props = {PROP_NAME_SPECTRA_ASSURE_PROGRESS: [progress]}
    if sha256 is not None:
        props[PROP_NAME_SPECTRA_ASSURE_SHA256] = [sha256]
    return props


def common(*, sha2: str, properties: dict[str, list[str]]) -> Any:
    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.uri = "/m/mypkg-1.0.tgz"
    proc.file = make_file(uri=proc.uri, sha2=sha2, properties=properties)
    return proc


# ------------------------------------------------- reading RL.progress


def test_the_same_bytes_keep_their_progress() -> None:
    assert common(sha2=OLD, properties=recorded()).get_prop_progress() == PROGRESS_SCANNED


def test_other_bytes_have_no_progress() -> None:
    assert common(sha2=NEW, properties=recorded()).get_prop_progress() == ""


def test_an_upload_of_other_bytes_has_no_progress_either() -> None:
    proc = common(sha2=NEW, properties=recorded(progress=PROGRESS_UPLOADED))
    assert proc.get_prop_progress() == ""


def test_the_comparison_ignores_case() -> None:
    assert common(sha2=OLD, properties=recorded(sha256=OLD.upper())).get_prop_progress() == PROGRESS_SCANNED


def test_properties_from_before_rl_sha256_are_trusted() -> None:
    assert common(sha2=NEW, properties=recorded(sha256=None)).get_prop_progress() == PROGRESS_SCANNED


@pytest.mark.parametrize("missing", ["", "None"])
def test_without_a_hash_of_our_own_the_progress_stands(missing: str) -> None:
    """Unknown is not different; 'None' is how a missing sha2 reaches FileInfo."""
    assert common(sha2=missing, properties=recorded()).get_prop_progress() == PROGRESS_SCANNED


def test_nothing_recorded_stays_nothing() -> None:
    assert common(sha2=NEW, properties={}).get_prop_progress() == ""


def test_a_rebuild_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        common(sha2=NEW, properties=recorded()).get_prop_progress()
    assert "rebuilt since the last scan" in caplog.text


# ------------------------------------------------- writing RL.sha256


class RecordingApi:
    def __init__(self) -> None:
        self.written: dict[str, dict[str, str]] = {}

    def set_one_prop(self, **kwargs: Any) -> bool:
        self.written.setdefault(kwargs["item_uri"], {})[kwargs["key"]] = kwargs["value"]
        return True


def write(proc: Any) -> dict[str, dict[str, str]]:
    proc.artifactory_api = RecordingApi()
    proc.cli_args = getattr(proc, "cli_args", {})
    proc.portal_info = PortalInfo(server="test", org="TestOrg", group="TestGroup")
    proc.purl_info = PurlInfo(project="my-repo", package="mypkg", version="1.0")
    proc.set_props_all(report=None, progress=PROGRESS_SCANNED, scan_status="pass", recursive=False, uri=proc.uri)
    written: dict[str, dict[str, str]] = proc.artifactory_api.written
    return written


def test_rl_sha256_comes_after_rl_progress() -> None:
    """Stopped in between, a new progress with an old digest is done again, never skipped."""
    order = list(PROP_SPECTRA_ASSURE_ALL)
    assert order.index(PROP_NAME_SPECTRA_ASSURE_SHA256) > order.index(PROP_NAME_SPECTRA_ASSURE_PROGRESS)


def test_the_hash_of_the_item_is_recorded_in_lower_case() -> None:
    written = write(common(sha2=NEW.upper(), properties={}))
    assert written["/m/mypkg-1.0.tgz"][PROP_NAME_SPECTRA_ASSURE_SHA256] == NEW


def test_no_hash_means_nothing_is_recorded() -> None:
    written = write(common(sha2="None", properties={}))
    assert PROP_NAME_SPECTRA_ASSURE_SHA256 not in written["/m/mypkg-1.0.tgz"]


def test_docker_records_no_hash() -> None:
    """What is scanned is a bundle assembled here; the manifest's hash says nothing."""
    proc: Any = ArtifactoryFileProcessorDocker.__new__(ArtifactoryFileProcessorDocker)
    proc.uri = "/img/1.0/manifest.json"
    proc.file = make_file(uri=proc.uri, sha2=NEW, properties=recorded(), package_type="docker")

    assert PROP_NAME_SPECTRA_ASSURE_SHA256 not in write(proc)[proc.uri]
    assert proc.get_prop_progress() == PROGRESS_SCANNED


# ------------------------------------------------- default: process()


def default(*, sha2: str) -> Any:
    proc = default_processor(sync_possible=False)
    del proc.get_prop_progress  # the real one, not the fixture's
    proc.file = make_file(uri=proc.uri, package_type="pypi", repo_name="my-repo", sha2=sha2, properties=recorded())
    proc.result = proc.process()
    return proc


def test_default_skips_what_it_scanned_before() -> None:
    proc = default(sha2=OLD)
    assert proc.processing_info.reason == "properties already exist in artifactory"
    assert proc.reached == []


def test_default_goes_on_with_a_rebuild() -> None:
    """On to the portal, which answers 'other bytes' and is replaced (R10.7.5)."""
    proc = default(sha2=NEW)
    assert [where for where, _ in proc.reached] == ["portal"]


# ------------------------------------------------- generic: the side-car


def generic(*, target_sha2: str | None) -> Any:
    """A side-car not read yet, as when the properties decide whether to read it."""
    proc = generic_processor(backend="portal", progress="")
    del proc.get_prop_progress
    proc.cli_args["portal"] = True
    proc.file = make_file(uri=META_URI, package_type="generic", repo_name="generic-local", sha2="c" * 64)
    proc.file.properties = recorded()
    proc.repo_db = {REPO_DB_DESCRIBED_BY_SIDE_CAR: {META_URI: TARGET_URI}}
    if target_sha2 is not None:
        proc.repo_db[TARGET_URI] = {"sha2": target_sha2}
    return proc


def test_generic_skips_what_it_scanned_before() -> None:
    proc = generic(target_sha2=OLD)
    assert proc._stop_if_an_earlier_run_finished_this(sync_needs_a_meta_file=False) is True


def test_generic_goes_on_when_the_described_file_was_rebuilt() -> None:
    """The side-car's own hash did not change; the file it describes did."""
    proc = generic(target_sha2=NEW)
    assert proc._stop_if_an_earlier_run_finished_this(sync_needs_a_meta_file=False) is None


def test_generic_trusts_the_progress_when_the_described_file_is_unknown() -> None:
    proc = generic(target_sha2=None)
    assert proc._stop_if_an_earlier_run_finished_this(sync_needs_a_meta_file=False) is True


def test_the_side_car_records_the_hash_of_the_described_file() -> None:
    proc = generic(target_sha2=NEW)
    proc.uri = META_URI
    assert write(proc)[META_URI][PROP_NAME_SPECTRA_ASSURE_SHA256] == NEW
