# python3 ts=4space
"""What ArtifactoryFileProcessorDocker.process() decides, and in what order.

Characterization tests: they pin the behaviour as it is today so that process()
(184 lines at complexity 18, the largest function left) can be restructured
without changing what it does.

process() is a chain of guarded steps. Each step either stops with a reason on
processing_info, or hands on to the next. These tests drive one step at a time by
faking the step below it, and assert the reason, because the reason is what a
user sees in the log and in the run summary.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_docker import (
    ArtifactoryFileProcessorDocker,
)
from rl_scan_artifactory.constants import (
    PROCESS_FILE_SKIP,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
)

MANIFEST_URI = "/reversinglabs/rl-scanner/1.2.3/manifest.json"
CONFIG_DIGEST = "sha256:" + "a" * 64
DOWNLOAD_PATH = "/tmp/dl/sha256__abc"


class FakeFileProperties:
    def __init__(self, skip: bool) -> None:
        self.skip = skip

    def skip_non_candidate_file(self) -> bool:
        return self.skip


class FakeManifest:
    """Stands in for DockerManifestExtract."""

    def __init__(self, config_digest: str | None = CONFIG_DIGEST) -> None:
        self._config_digest = config_digest
        self.output: dict[str, Any] = {}
        self.annotations: dict[str, str] = {}

    def get_config_digest(self) -> str | None:
        return self._config_digest


def processor(
    *,
    uri: str = MANIFEST_URI,
    skip_candidate: bool = False,
    progress: str = "",
    ignore_properties: bool = False,
    sync_possible: bool = False,
    backend: str = "portal",
    download: tuple[str | None, bool | None] = (DOWNLOAD_PATH, True),
    manifest: Any = "default",
    config_data: dict[str, Any] | None = None,
    version: str | None = "1.2.3",
) -> Any:
    proc: Any = ArtifactoryFileProcessorDocker.__new__(ArtifactoryFileProcessorDocker)

    proc.uri = uri
    proc.filename = uri.split("/")[-1]
    proc.what_backend = backend
    proc.p_type = "docker"
    proc.cli_args = {"ignore_artifactory_properties": ignore_properties}
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo()
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.files_to_remove = []
    proc.repo_db = {}
    proc.docker_version = None

    from .conftest import make_file

    proc.file = make_file(uri=uri, package_type="docker", repo_name="docker-local")
    proc.file.simple = {"name": ["reversinglabs/rl-scanner"], "version": ["1.2.3"]}

    proc.fp = FakeFileProperties(skip_candidate)

    # the properties of an earlier run
    proc.get_prop_progress = lambda: progress
    proc.get_prop_report = lambda: "https://reports.example/abc"
    proc.get_prop_purl = lambda: "pkg:rl/docker-local/rl-scanner@1.2.3"
    proc.sync_possible = lambda: sync_possible

    # the steps below the one under test
    proc._try_extract_version_from_manifest_uri_and_repo_db = lambda: None
    proc._docker_make_target_name = lambda input_name: "sha256__abc"
    proc.add_file_to_remove = lambda item: None
    proc._do_one_artifactory_download = lambda **kwargs: download

    made = FakeManifest() if manifest == "default" else manifest
    proc._process_one_docker_manifest_json = lambda **kwargs: made
    proc._read_config_digest_docker = lambda digest: config_data
    proc._make_docker_architecture_string = lambda config_data: "linux-amd64"
    proc._extrapolate_docker_version_string = lambda dme: version

    proc.reached = []
    proc._process_portal = lambda **kwargs: proc.reached.append(("portal", kwargs)) or True
    proc._process_cli = lambda **kwargs: proc.reached.append(("cli", kwargs)) or True

    return proc


def run(**kwargs: Any) -> Any:
    proc = processor(**kwargs)
    proc.result = proc.process()
    return proc


# ----------------------------------------------------- the file itself, first


def test_a_non_candidate_is_skipped() -> None:
    proc = run(skip_candidate=True)
    assert proc.result is True
    assert proc.processing_info.reason == "skip: not a candidate for inspection"
    assert proc.processing_info.status == PROCESS_FILE_SKIP


def test_a_list_manifest_is_only_for_the_pre_pass() -> None:
    """It was read before the loop started; there is nothing to do with it here."""
    proc = run(uri="/reversinglabs/rl-scanner/1.2.3/list.manifest.json")
    assert proc.result is True
    assert proc.processing_info.reason == "file is only used for info gathering"


def test_any_other_file_is_not_relevant() -> None:
    proc = run(uri="/reversinglabs/rl-scanner/1.2.3/sha256__deadbeef")
    assert proc.result is True
    assert proc.processing_info.reason == "file is not relevant"


def test_a_candidate_manifest_goes_on() -> None:
    proc = run(config_data={"created": "2026-01-01T00:00:00Z"})
    assert proc.reached != []


# ------------------------------------------- what an earlier run already did


def test_an_already_scanned_artifact_stops_there() -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=False)

    assert proc.result is True
    assert "already scanned" in proc.processing_info.reason
    assert proc.processing_info.scan_state == PROGRESS_SCANNED
    assert proc.processing_info.report == "https://reports.example/abc"
    assert proc.processing_info.purl == "pkg:rl/docker-local/rl-scanner@1.2.3"


def test_an_already_scanned_artifact_that_can_sync_goes_on() -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=True, config_data={"created": ""})

    assert proc.need_sync_datetime is True
    assert proc.reached != []


def test_a_sync_by_age_says_so_and_reports_no_stale_state() -> None:
    """It was scanned, not uploaded-and-waiting; the old verdict is what the sync replaces."""
    proc = run(progress=PROGRESS_SCANNED, sync_possible=True, config_data={"created": ""})

    assert "sync" in proc.processing_info.reason
    assert "no scan result yet" not in proc.processing_info.reason
    assert proc.processing_info.scan_state is None


def test_an_uploaded_but_unscanned_artifact_goes_on() -> None:
    """It was uploaded and the scan had not finished; it is not completed."""
    proc = run(progress=PROGRESS_UPLOADED, config_data={"created": ""})

    assert proc.processing_info.completed is False
    assert "no scan result yet" in proc.processing_info.reason
    assert proc.processing_info.scan_state == PROGRESS_UPLOADED


def test_ignoring_the_properties_skips_all_of_that() -> None:
    proc = run(
        progress=PROGRESS_SCANNED,
        sync_possible=False,
        ignore_properties=True,
        config_data={"created": ""},
    )
    assert proc.reached != []


def test_ignored_properties_give_no_scan_state() -> None:
    """A --sync run must not report the verdict it exists to replace (A.20)."""
    proc = run(progress=PROGRESS_SCANNED, ignore_properties=True, config_data={"created": ""})
    assert proc.processing_info.scan_state is None


# ----------------------------------------------------------- the download


def test_a_failed_download_stops_with_a_reason() -> None:
    proc = run(download=(None, None))
    assert proc.result is True
    assert "download failed" in proc.processing_info.reason


def test_a_digest_mismatch_stops_with_a_reason() -> None:
    proc = run(download=(DOWNLOAD_PATH, False))
    assert proc.result is True
    assert "verify failed" in proc.processing_info.reason


def test_nothing_to_verify_against_is_not_a_mismatch() -> None:
    proc = run(download=(DOWNLOAD_PATH, None), config_data={"created": ""})
    assert proc.reached != []


# --------------------------------------------------- reading the manifest


def test_an_unreadable_manifest_stops_with_a_reason() -> None:
    proc = run(manifest=None)
    assert proc.result is True
    assert "cannot extract info from manifest.json" in proc.processing_info.reason


def test_a_manifest_without_a_config_digest_stops() -> None:
    proc = run(manifest=FakeManifest(config_digest=None))
    assert proc.result is True
    assert "cannot extract 'config_digest'" in proc.processing_info.reason


def test_an_unreadable_config_stops() -> None:
    proc = run(config_data=None)
    assert proc.result is True
    assert "cannot extract 'config_data'" in proc.processing_info.reason


# ------------------------------------------------------------- the purl


def test_the_architecture_becomes_part_of_the_project() -> None:
    proc = run(config_data={"created": "2026-01-01T00:00:00Z"})
    assert proc.purl_info.project == "docker-local.linux-amd64"


def test_the_slash_in_an_image_name_becomes_an_underscore() -> None:
    proc = run(config_data={"created": ""})
    assert proc.purl_info.package == "reversinglabs_rl-scanner"


def test_the_version_comes_from_the_manifest() -> None:
    proc = run(config_data={"created": ""}, version="9.9.9")
    assert proc.purl_info.version == "9.9.9"


def test_the_created_date_is_taken_from_the_config() -> None:
    proc = run(config_data={"created": "2026-01-01T00:00:00Z"})
    assert proc.file.last_modified == "2026-01-01T00:00:00Z"


def test_no_version_at_all_is_an_invariant_failure() -> None:
    from rl_scan_artifactory.exceptions import SpectraAssureInvariantError

    with pytest.raises(SpectraAssureInvariantError, match="version"):
        run(config_data={"created": ""}, version=None)


# --------------------------------------------------------- which backend


def test_the_portal_backend_is_handed_the_purl_parts() -> None:
    proc = run(backend="portal", config_data={"created": ""})
    where, kwargs = proc.reached[0]

    assert where == "portal"
    assert kwargs == {"project": "docker-local.linux-amd64", "package": "reversinglabs_rl-scanner", "version": "1.2.3"}


def test_the_cli_backend_is_handed_the_same() -> None:
    proc = run(backend="cli", config_data={"created": ""})
    where, kwargs = proc.reached[0]

    assert where == "cli"
    assert kwargs["project"] == "docker-local.linux-amd64"


# ------------------------------------------------ what is set before anything


def test_the_starting_state_is_skip() -> None:
    """Every early return leaves these as process() set them at the top."""
    proc = run(skip_candidate=True)

    assert proc.processing_info.completed is True
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert proc.processing_info.scan_state is None
    assert proc.processing_info.report is None
    assert proc.processing_info.purl is None


# ------------------------------------------ what an earlier run cannot decide
# Whether the purl is on the portal is something only the portal knows. The
# RL.progress property of an earlier run is a hint that stops the work early; it
# never decides whether to upload, and process() no longer computes a guess at
# it that _process_portal would have thrown away.


def test_process_records_no_upload_guess() -> None:
    """is_uploaded used to travel through file.simple and be overwritten on arrival."""
    proc = run(progress=PROGRESS_SCANNED, ignore_properties=True, config_data={"created": ""})
    assert "is_uploaded" not in proc.file.simple


def test_what_process_does_hand_on() -> None:
    """Only what _process_portal cannot work out for itself."""
    proc = run(config_data={"created": "2026-01-01T00:00:00Z"})

    assert proc.file.simple["arch"] == ["linux-amd64"]
    assert proc.file.simple["download_path"] == DOWNLOAD_PATH
    assert proc.file.simple["dme"] is not None


# ---------------------------------------------------- the steps, on their own
# process() is a sequence of named steps, each of which either stops with a
# reason or hands on by returning None. These check the seam itself, so a future
# change to the order shows up as a failure here rather than as a behaviour
# difference somewhere downstream.


def test_a_step_that_hands_on_returns_none() -> None:
    proc = processor()
    assert proc._stop_unless_this_file_is_a_manifest() is None


def test_a_step_that_stops_returns_a_result() -> None:
    proc = processor(skip_candidate=True)
    assert proc._stop_unless_this_file_is_a_manifest() is True


def test_the_earlier_run_step_hands_on_when_there_is_nothing_recorded() -> None:
    proc = processor(progress="")
    assert proc._stop_if_an_earlier_run_finished_this() is None


def test_the_earlier_run_step_hands_on_for_an_unfinished_upload() -> None:
    """Recorded as incomplete, but the scan still has to be waited for."""
    proc = processor(progress=PROGRESS_UPLOADED)

    assert proc._stop_if_an_earlier_run_finished_this() is None
    assert proc.processing_info.completed is False


def test_the_download_step_gives_back_the_path() -> None:
    proc = processor()
    assert proc._fetch_the_manifest() == DOWNLOAD_PATH


def test_the_download_step_gives_none_and_a_reason() -> None:
    proc = processor(download=(None, None))

    assert proc._fetch_the_manifest() is None
    assert "download failed" in proc.processing_info.reason


def test_the_manifest_step_gives_back_what_it_read() -> None:
    proc = processor(config_data={"created": "2026-01-01T00:00:00Z"})
    described = proc._read_what_the_manifest_describes(download_path=DOWNLOAD_PATH)

    assert described is not None
    dme, config_data = described
    assert dme is not None
    assert config_data["created"] == "2026-01-01T00:00:00Z"


def test_the_purl_step_returns_the_three_parts() -> None:
    proc = processor()
    described = (FakeManifest(), {"created": ""})

    parts = proc._make_the_purl(download_path=DOWNLOAD_PATH, described=described)
    assert parts == ("docker-local.linux-amd64", "reversinglabs_rl-scanner", "1.2.3")
