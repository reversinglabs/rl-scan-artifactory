# python3 ts=4space
"""What a cli scan writes besides the scanned item: the report and the side-car.

- A report bundle carries RL.noscan=true and no other property of ours
  (R10.9.6). It used to have RL.scan-status deleted and then written back as
  `__novalue__`, and for docker the recursive write on the tag directory, which
  came after the tagging, put the whole scan result on the report again.
  Report bundles already in a repository lose the rest when a run passes them.
- A cli scan or sync of a generic file also updates RL.timestamp on the file's
  `.rl_meta` side-car (R7.10.1), and only that: RL.progress and RL.sha256 there
  are a portal run's.

Only artifactory is faked.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.constants import (
    PROGRESS_SCANNED,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
)

from .conftest import make_repo
from .test_run_containment import make_app, repo_info

AFTER_A_DOCKER_WRITE = {
    "RL.noscan": ["true"],
    "RL.progress": ["scanned"],
    "RL.timestamp": ["2026-10-28T11:59:16Z"],
    "RL.scan-status": ["fail"],
    "RL.package-url": ["pkg:rl/docker/img@1.0"],
    "RL.scan-report": ["https://a/r"],
    "RL.organization": ["Test"],
    "RL.group": ["testGroup"],
    "RL.sha256": ["a" * 64],
    "Spectra.Assure.scan-status": ["fail"],
    "secure.software.verdict": ["null"],
}
OURS_BUT_NOSCAN = set(AFTER_A_DOCKER_WRITE) - {"RL.noscan", "secure.software.verdict"}


class FakeArtifactoryApi:
    def __init__(self, properties: dict[str, list[str]] | Exception | None = None) -> None:
        self.properties = properties if properties is not None else {}
        self.calls: list[tuple[str, str, str]] = []

    def put_one_prop(self, *, repo: Any, item_uri: str, key: str, value: str) -> bool:
        self.calls.append(("put", item_uri, f"{key}={value}"))
        return True

    def get_item_properties(self, *, file: Any) -> dict[str, list[str]]:
        self.calls.append(("get", file.uri, ""))
        if isinstance(self.properties, Exception):
            raise self.properties
        return dict(self.properties)

    def del_one_prop(self, *, repo: Any, item_uri: str, key: str, recursive: bool = False) -> bool:
        assert recursive is False
        self.calls.append(("del", item_uri, key))
        return True

    def deleted(self) -> set[str]:
        return {key for what, _, key in self.calls if what == "del"}


# ------------------------------------------------- tagging an uploaded report


def tagger(properties: dict[str, list[str]], *, repo_type: str = "local") -> Any:
    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.uri = "/img/1.0/manifest.json"
    proc.repo = make_repo(name="docker-local", package_type="docker", repo_type=repo_type)
    proc.cli_args = {"cli": True}
    proc.artifactory_api = FakeArtifactoryApi(properties)
    return proc


def tag(proc: Any) -> None:
    proc._tag_the_report_as_not_to_scan(purl="docker-local/img@1.0", report_bundle_path="/t/reports.zip")


def test_the_report_gets_noscan() -> None:
    proc = tagger({})
    tag(proc)
    assert ("put", "/img/1.0/manifest.json-reports.zip", "RL.noscan=true") in proc.artifactory_api.calls


def test_the_report_loses_every_other_property_of_ours() -> None:
    proc = tagger(AFTER_A_DOCKER_WRITE)
    tag(proc)
    assert proc.artifactory_api.deleted() == OURS_BUT_NOSCAN


def test_no_placeholder_status_is_written_back() -> None:
    proc = tagger(AFTER_A_DOCKER_WRITE)
    tag(proc)
    puts = [value for what, _, value in proc.artifactory_api.calls if what == "put"]
    assert puts == ["RL.noscan=true"]


def test_a_report_in_the_reports_repository_is_not_tagged() -> None:
    """A remote repository's report goes elsewhere and is not in the repo scanned."""
    proc = tagger(AFTER_A_DOCKER_WRITE, repo_type="remote")
    tag(proc)
    assert proc.artifactory_api.calls == []


def test_the_report_is_tagged_after_the_item_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """For docker the item write is recursive over the directory holding the report."""
    from rl_scan_artifactory.artifactory_file_processor import artifactory_file_processor_common as common

    from .test_scan_cli_file import FakeScanCli

    order: list[str] = []
    monkeypatch.setattr(common, "ScanCli", lambda cli_args: FakeScanCli((0, "/t/reports.zip", "pass")))

    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.what_backend = "cli"
    proc.cli_args = {}
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo(project="docker-local", package="img", version="1.0")
    proc.files_to_remove = []

    def upload(**kwargs: Any) -> str:
        order.append("upload")
        return "https://a/r"

    proc._upload_the_report = upload
    proc._update_artifactory_item_with_scan_status = lambda **kwargs: order.append("write")
    proc._tag_the_report_as_not_to_scan = lambda **kwargs: order.append("tag")

    proc.do_cli_after_download(project="docker-local", package="img", version="1.0", download_path="/dl/x")
    assert order == ["upload", "write", "tag"]


# ------------------------------------------- report bundles already in a repo


def cleaning_app(properties: dict[str, list[str]] | Exception, **cli_args: Any) -> Any:
    app = make_app(portal=False)
    app.cli_args.update(cli_args)
    app.artifactory_api = FakeArtifactoryApi(properties)
    return app


def clean(app: Any, uri: str = "/a/mypkg-1.0.bin-reports.zip") -> None:
    app._clean_report(repo=repo_info(), artifact_item={"uri": uri, "sha1": "1", "sha2": "2"})


def test_a_report_in_a_listing_loses_every_other_property_of_ours() -> None:
    app = cleaning_app(AFTER_A_DOCKER_WRITE)
    clean(app)
    assert app.artifactory_api.deleted() == OURS_BUT_NOSCAN
    assert app.failed_items == []


def test_a_clean_report_costs_only_the_read() -> None:
    app = cleaning_app({"RL.noscan": ["true"]})
    clean(app)
    assert [what for what, _, _ in app.artifactory_api.calls] == ["get"]


def test_keep_obsolete_properties_leaves_reports_alone() -> None:
    app = cleaning_app(AFTER_A_DOCKER_WRITE, keep_obsolete_properties=True)
    clean(app)
    assert app.artifactory_api.calls == []


def test_a_failed_report_cleanup_is_contained() -> None:
    app = cleaning_app(ConnectionError("artifactory unreachable"))
    clean(app)
    assert app.failed_items == [("r1", "/a/mypkg-1.0.bin-reports.zip")]


def test_the_main_loop_cleans_reports_and_does_not_process_them() -> None:
    app = cleaning_app(AFTER_A_DOCKER_WRITE)
    app.WITH_TEST_LIMIT_REPO_TO = 0
    processed: list[str] = []

    def run_one(**kwargs: Any) -> str:
        processed.append(kwargs["artifact_item"]["uri"])
        return "Processed"

    app._run_one_repo_one_artifact = run_one

    class Listing:
        p_type = "generic"

        def process(self) -> list[dict[str, str]]:
            return [{"uri": "/a.bin"}, {"uri": "/a.bin-reports.zip"}]

    app._process_repo_items(Listing(), repo_info(), {})
    assert processed == ["/a.bin"]
    assert app.artifactory_api.deleted() == OURS_BUT_NOSCAN


# ------------------------------------------------ the side-car of a cli scan

FILE_URI = "/a/mypkg-1.0.bin"
SIDE_CAR_URI = "/a/mypkg-1.0.bin.rl_meta"


def generic_cli(repo_db: dict[str, Any], *, portal: bool = False) -> tuple[Any, list[dict[str, Any]]]:
    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)
    proc.uri = FILE_URI
    proc.what_backend = "portal" if portal else "cli"
    proc.cli_args = {"portal": portal, "cli": not portal}
    proc.repo_db = repo_db
    proc._described_file_uri = lambda: None

    writes: list[dict[str, Any]] = []
    proc.set_props_all = lambda **kwargs: writes.append(kwargs)
    return proc, writes


def described_by_side_car() -> dict[str, Any]:
    return {REPO_DB_DESCRIBED_BY_SIDE_CAR: {SIDE_CAR_URI: FILE_URI, "/b.rl_meta": "/b"}}


def test_a_cli_scan_writes_the_result_on_the_file() -> None:
    proc, writes = generic_cli(described_by_side_car())
    proc._update_artifactory_item_with_scan_status(scan_status="pass", report="https://a/r")
    assert writes[0]["uri"] == FILE_URI
    assert writes[0].get("only") is None


def test_a_cli_scan_updates_only_the_timestamp_on_the_side_car() -> None:
    proc, writes = generic_cli(described_by_side_car())
    proc._update_artifactory_item_with_scan_status(scan_status="pass", report="https://a/r")
    assert len(writes) == 2
    assert writes[1]["uri"] == SIDE_CAR_URI
    assert writes[1]["only"] == ("RL.timestamp",)
    assert writes[1]["progress"] == PROGRESS_SCANNED


def test_a_file_without_a_side_car_gets_one_write() -> None:
    proc, writes = generic_cli({})
    proc._update_artifactory_item_with_scan_status(scan_status="pass", report="https://a/r")
    assert [write["uri"] for write in writes] == [FILE_URI]


def test_a_portal_run_without_a_described_file_does_not_stamp_twice() -> None:
    """Portal writes on the side-car itself when it describes nothing (R7.10)."""
    proc, writes = generic_cli(described_by_side_car(), portal=True)
    proc._update_artifactory_item_with_scan_status(scan_status="pass")
    assert [write["uri"] for write in writes] == [FILE_URI]
