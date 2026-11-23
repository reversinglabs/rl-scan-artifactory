# python3 ts=4space
"""A generic file may carry its purl data as RL.meta.* properties (R7.11).

The side-car stays the first choice; the properties are the alternative for a
file without one. Only artifactory and the portal are faked.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
    obsolete_property_names,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.artifactory_repo_processor import ArtifactoryRepoProcessor
from rl_scan_artifactory.constants import (
    PROCESS_FILE_SKIP,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
    PROP_SPECTRA_ASSURE_ALL,
    PROP_SPECTRA_ASSURE_ON_SIDE_CAR,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction, SpectraAssureInvariantError
from rl_scan_artifactory.file_properties import FilePropertiesGeneric
from rl_scan_artifactory.py_cli_scan import ScanCliLocal

from .conftest import make_file, make_repo

REPO = "generic-local"
FILE_URI = "/a/mypkg-1.0.msi"
META_URI = "/a/mypkg-1.0.msi.rl_meta"
FILE_SHA2 = "F" * 64

META_PROPS: dict[str, Any] = {
    "RL.meta.name": ["mypkg"],
    "RL.meta.version": ["v1.0"],
}
FULL_META_PROPS: dict[str, Any] = {
    **META_PROPS,
    "RL.meta.namespace": ["windows"],
    "RL.meta.architecture": ["arm_v8"],
}


def processor(
    *,
    backend: str,
    uri: str = FILE_URI,
    properties: dict[str, Any] | None = None,
    repo_db: dict[str, Any] | None = None,
    progress: str = "",
    sync_possible: bool = False,
) -> Any:
    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)

    proc.uri = uri
    proc.filename = uri.split("/")[-1]
    proc.what_backend = backend
    proc.p_type = "generic"
    proc.cli_args = {"portal": backend == "portal", "ignore_artifactory_properties": False}
    proc.processing_info = ProcessingInfo()
    proc.need_sync_datetime = False
    proc.files_to_remove = []
    proc.repo_db = repo_db if repo_db is not None else {}

    proc.repo = make_repo(name=REPO)
    proc.file = make_file(
        uri=uri,
        repo=proc.repo,
        properties=dict(properties) if properties is not None else {},
        sha2=FILE_SHA2,
    )

    class Candidate:
        def skip_non_candidate_file(self) -> bool:
            return False

    proc.fp = Candidate()
    proc.purl_info = PurlInfo()

    proc.get_prop_progress = lambda: progress
    proc.get_prop_report = lambda: None
    proc.get_prop_purl = lambda: None
    proc.sync_possible = lambda: sync_possible

    def no_side_car() -> Any:
        pytest.fail("a file with RL.meta.* properties must not be read as a side-car")

    proc._load_meta_info = no_side_car

    proc.reached = []
    proc._process_portal = lambda **kwargs: proc.reached.append(("portal", kwargs)) or True
    proc.do_cli_scan_or_sync = lambda **kwargs: proc.reached.append(("cli", kwargs)) or True
    proc._populate_purl_info = lambda project, package, version: None

    return proc


def purl_reached(proc: Any) -> dict[str, Any]:
    _where, kwargs = proc.reached[0]
    result: dict[str, Any] = kwargs
    return result


# ------------------------------------------- R7.11.1 the purl from properties


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_the_mandatory_properties_make_the_purl(backend: str) -> None:
    proc = processor(backend=backend, properties=META_PROPS)
    proc.process()

    assert purl_reached(proc) == {"project": REPO, "package": "mypkg", "version": "v1.0"}


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_the_optional_properties_go_where_the_side_car_keys_go(backend: str) -> None:
    """R7.8: <repo>-<architecture>/<namespace>-<name>@<version>."""
    proc = processor(backend=backend, properties=FULL_META_PROPS)
    proc.process()

    assert purl_reached(proc) == {"project": f"{REPO}-arm_v8", "package": "windows-mypkg", "version": "v1.0"}


def test_the_first_value_of_a_property_is_used() -> None:
    props = {**META_PROPS, "RL.meta.version": ["v1.0", "v2.0"]}
    proc = processor(backend="portal", properties=props)
    proc.process()

    assert purl_reached(proc)["version"] == "v1.0"


def test_the_properties_are_escaped_like_the_side_car_keys() -> None:
    props = {"RL.meta.name": ["my@pkg"], "RL.meta.version": ["1/0"]}
    proc = processor(backend="portal", properties=props)
    proc.process()

    assert purl_reached(proc) == {"project": REPO, "package": "my0x40pkg", "version": "10x2F0"}


def test_other_rl_meta_names_are_ignored() -> None:
    props = {**META_PROPS, "RL.meta.path": ["elsewhere.bin"], "RL.meta.whatever": ["x"]}
    proc = processor(backend="portal", properties=props)
    proc.process()

    assert purl_reached(proc) == {"project": REPO, "package": "mypkg", "version": "v1.0"}
    assert proc._scanned_file() == ("mypkg-1.0.msi", FILE_SHA2.lower())


# ------------------------------------------------------ R7.11.2 a side-car wins


def described_by_a_side_car() -> dict[str, Any]:
    return {
        FILE_URI: {"project": "from-side-car", "package": "pkg-from-side-car", "version": "9.9"},
        REPO_DB_DESCRIBED_BY_SIDE_CAR: {META_URI: FILE_URI},
    }


def test_portal_skips_a_file_its_side_car_describes_even_with_properties() -> None:
    proc = processor(backend="portal", properties=META_PROPS, repo_db=described_by_a_side_car())
    assert proc.process() is True

    assert proc.reached == []
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert "side-car" in proc.processing_info.reason


def test_cli_takes_the_purl_from_the_side_car_over_the_properties() -> None:
    proc = processor(backend="cli", properties=META_PROPS, repo_db=described_by_a_side_car())
    proc.process()

    assert purl_reached(proc) == {"project": "from-side-car", "package": "pkg-from-side-car", "version": "9.9"}


def test_portal_reads_a_side_car_and_not_its_rl_meta_properties() -> None:
    proc = processor(backend="portal", uri=META_URI, properties={"RL.meta.name": ["only-a-name"]})
    proc._load_meta_info = lambda: (False, None)
    proc.process()

    assert proc.reached == []
    assert proc.processing_info.reason == "meta file extract failed"


# ----------------------------------------- R7.11.3 an incomplete set is refused


@pytest.mark.parametrize("backend", ["portal", "cli"])
@pytest.mark.parametrize(
    ("props", "missing"),
    [
        ({"RL.meta.name": ["mypkg"]}, ["RL.meta.version"]),
        ({"RL.meta.version": ["v1"]}, ["RL.meta.name"]),
        ({"RL.meta.namespace": ["windows"]}, ["RL.meta.name", "RL.meta.version"]),
        ({"RL.meta.name": [""], "RL.meta.version": ["v1"]}, ["RL.meta.name"]),
        ({"RL.meta.name": [], "RL.meta.version": ["v1"]}, ["RL.meta.name"]),
    ],
)
def test_an_incomplete_set_raises_naming_what_is_missing(
    backend: str,
    props: dict[str, Any],
    missing: list[str],
) -> None:
    proc = processor(backend=backend, properties=props)

    with pytest.raises(SpectraAssureInvalidAction) as e:
        proc.process()

    for name in missing:
        assert name in str(e.value)
    assert proc.reached == []


def test_an_incomplete_set_does_not_fall_back_to_the_cli_placeholder() -> None:
    proc = processor(backend="cli", properties={"RL.meta.name": ["mypkg"]})

    with pytest.raises(SpectraAssureInvalidAction):
        proc.process()

    assert proc.purl_info.version != "v0"


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_an_item_an_earlier_run_scanned_reports_that_and_raises_nothing(backend: str) -> None:
    """The check is made when the purl is needed, as for a side-car (R7.3)."""
    proc = processor(backend=backend, properties={"RL.meta.name": ["mypkg"]}, progress=PROGRESS_SCANNED)

    assert proc.process() is True
    assert proc.reached == []
    assert proc.processing_info.reason == "already processed"


# ------------------------------- R7.11.4 portal scans the file with properties


def test_portal_scans_the_file_itself_with_its_own_hash() -> None:
    proc = processor(backend="portal", properties=META_PROPS)

    assert proc._scanned_file() == ("mypkg-1.0.msi", FILE_SHA2.lower())
    assert proc._portal_artifact_sha2() == FILE_SHA2.lower()
    assert proc._scanned_sha256() == FILE_SHA2.lower()
    assert proc._described_file_uri() is None


def test_a_side_car_still_scans_the_file_it_describes() -> None:
    proc = processor(backend="portal", uri=META_URI, repo_db={FILE_URI: {"sha2": "D" * 64}})
    proc.file.properties["generic._derived_.path"] = ["mypkg-1.0.msi"]
    proc.file.properties["generic._derived_.sha256"] = ["d" * 64]

    assert proc._scanned_file() == ("mypkg-1.0.msi", "d" * 64)
    assert proc._portal_artifact_sha2() == "D" * 64


class FakeArtifactoryApi:
    def __init__(self) -> None:
        self.downloads: list[dict[str, Any]] = []

    def get_base_url(self) -> str:
        return "https://artifactory.example/artifactory"

    def download_url_to_target_with_verify(self, *, url: str, target_path: str, sha256: str | None) -> Any:
        self.downloads.append({"url": url, "target_path": target_path, "sha256": sha256})
        return target_path, True


def test_portal_downloads_uploads_and_records_on_the_file_itself() -> None:
    proc = processor(backend="portal", properties=META_PROPS)
    proc.artifactory_api = FakeArtifactoryApi()
    proc.download_dir = "/tmp/x"
    uploads: list[dict[str, Any]] = []

    def upload(**kwargs: Any) -> bool:
        uploads.append(kwargs)
        return True

    proc._do_one_portal_upload = upload
    written: list[dict[str, Any]] = []
    proc.set_props_all = lambda **kwargs: written.append(kwargs)

    assert proc._portal_download_upload_generic(project=REPO, package="mypkg", version="v1.0") is True

    (download,) = proc.artifactory_api.downloads
    assert download["url"] == f"https://artifactory.example/artifactory/{REPO}{FILE_URI}"
    assert download["sha256"] == FILE_SHA2.lower()
    assert uploads[0]["file_path"] == "/tmp/x/mypkg-1.0.msi"
    assert written == [
        {"report": None, "progress": PROGRESS_UPLOADED, "scan_status": None, "recursive": False, "uri": FILE_URI},
    ]


def test_portal_writes_the_full_result_on_the_file_itself() -> None:
    proc = processor(backend="portal", properties=META_PROPS)
    proc._portal_make_report_base = lambda: "https://portal.example"
    written: list[dict[str, Any]] = []
    proc.set_props_all = lambda **kwargs: written.append(kwargs)

    proc._update_artifactory_item_with_scan_status(scan_status="pass", report="r")

    (only,) = written
    assert only["uri"] == FILE_URI
    assert "only" not in only


def test_portal_asks_the_portal_with_the_files_own_hash() -> None:
    proc = processor(backend="portal", properties=META_PROPS)
    asked: list[Any] = []

    def exists_on_portal(**kwargs: Any) -> Any:
        asked.append(kwargs["digest"])
        return True, "pass", "r"

    proc._exists_on_portal = exists_on_portal
    proc.purl_info.project, proc.purl_info.package, proc.purl_info.version = REPO, "mypkg", "v1.0"
    del proc._process_portal  # the real one

    proc._process_portal(project=REPO, package="mypkg", version="v1.0")

    assert asked == [FILE_SHA2.lower()]


def test_portal_can_sync_a_file_with_properties() -> None:
    proc = processor(backend="portal", properties=META_PROPS, progress=PROGRESS_SCANNED, sync_possible=True)
    proc.process()

    assert proc.need_sync_datetime is True
    assert proc.reached[0][0] == "portal"


def test_the_side_car_keeps_its_narrow_set_and_the_file_the_full_one() -> None:
    assert processor(backend="portal", uri=META_URI)._maintained_properties() == PROP_SPECTRA_ASSURE_ON_SIDE_CAR
    assert processor(backend="portal", properties=META_PROPS)._maintained_properties() == tuple(PROP_SPECTRA_ASSURE_ALL)


# --------------------------------- R7.11.5 every generic file is looked at


class FakePropertiesApi:
    def __init__(self, stored: dict[str, Any]) -> None:
        self.stored = stored
        self.reads = 0

    def get_item_properties(self, file: Any) -> dict[str, Any]:
        self.reads += 1
        return dict(self.stored)


def generic_props(*, uri: str, portal: bool, stored: dict[str, Any]) -> Any:
    api = FakePropertiesApi(stored)
    properties_class: Any = FilePropertiesGeneric
    fp = properties_class(
        cli_args={"portal": portal},
        file=make_file(uri=uri, package_type="generic", repo_name=REPO),
        artifactory_api=api,
    )
    fp.api = api
    return fp


@pytest.mark.parametrize("portal", [True, False])
def test_the_properties_of_every_generic_file_are_read(portal: bool) -> None:
    fp = generic_props(uri=FILE_URI, portal=portal, stored=META_PROPS)

    assert fp.api.reads == 1
    assert fp.file.properties == META_PROPS


def test_portal_makes_a_file_with_properties_a_candidate() -> None:
    assert generic_props(uri=FILE_URI, portal=True, stored=META_PROPS).skip_non_candidate_file() is False


def test_portal_makes_a_file_with_an_incomplete_set_a_candidate_too() -> None:
    """So that R7.11.3 can refuse it rather than it being skipped unseen."""
    fp = generic_props(uri=FILE_URI, portal=True, stored={"RL.meta.name": ["mypkg"]})
    assert fp.skip_non_candidate_file() is False


def test_portal_still_skips_a_file_with_neither() -> None:
    fp = generic_props(uri=FILE_URI, portal=True, stored={"RL.noscan": ["false"], "other.name": ["x"]})
    assert fp.skip_non_candidate_file() is True


def test_portal_never_reaches_the_purl_step_with_neither() -> None:
    """The candidate check above is the only skip for such a file (R7.11.5).

    The purl step used to carry a second, unreachable skip for it; reaching it
    now means the candidate check has changed, and that must not pass quietly.
    """
    proc = processor(backend="portal", properties={})
    with pytest.raises(SpectraAssureInvariantError, match="side-car or RL.meta"):
        proc._stop_if_there_is_no_purl_data()


def test_rl_noscan_still_wins_over_the_properties() -> None:
    fp = generic_props(uri=FILE_URI, portal=True, stored={**META_PROPS, "RL.noscan": ["true"]})
    assert fp.skip_non_candidate_file() is True


@pytest.mark.parametrize("cli", [True, False])
def test_the_listing_hands_on_every_generic_file(cli: bool) -> None:
    arp: Any = ArtifactoryRepoProcessor.__new__(ArtifactoryRepoProcessor)
    arp.p_type = "generic"
    arp.cli_args = {"cli": cli, "portal": not cli}
    arp.sha2_by_uri = {}
    listing = {"files": [{"uri": META_URI, "sha2": "m" * 64}, {"uri": FILE_URI, "sha2": FILE_SHA2}]}

    assert [item["uri"] for item in arp.extract_my_interesting_files(listing)] == [META_URI, FILE_URI]


# --------------------------------------------------- R7.11.6 the cli purl


def test_cli_without_either_uses_the_placeholder() -> None:
    proc = processor(backend="cli", properties={})
    proc.process()

    assert purl_reached(proc) == {"project": REPO, "package": "mypkg-1.0.msi", "version": "v0"}


def test_cli_syncs_a_file_with_properties() -> None:
    proc = processor(backend="cli", properties=META_PROPS, progress=PROGRESS_SCANNED, sync_possible=True)
    assert proc.process() is True

    assert proc.need_sync_datetime is True
    assert proc.purl_is_a_placeholder is False
    assert proc.sync_requested() is True
    assert purl_reached(proc) == {"project": REPO, "package": "mypkg", "version": "v1.0"}


def test_cli_syncs_a_file_its_side_car_describes() -> None:
    side_car = {"project": REPO, "package": "fromsidecar", "version": "2.0"}
    proc = processor(backend="cli", repo_db={FILE_URI: side_car}, progress=PROGRESS_SCANNED, sync_possible=True)
    assert proc.process() is True

    assert proc.sync_requested() is True
    assert purl_reached(proc) == side_car


def test_cli_never_syncs_the_placeholder() -> None:
    proc = processor(backend="cli", progress=PROGRESS_SCANNED, sync_possible=True)
    assert proc.process() is True

    assert proc.reached == []
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert proc.processing_info.reason == (
        "sync not possible with cli: no .rl_meta side-car and no RL.meta.* properties"
    )


@pytest.mark.parametrize(("properties", "syncs"), [({}, False), (META_PROPS, True)])
def test_an_explicit_sync_skips_only_the_placeholder(properties: dict[str, Any], syncs: bool) -> None:
    """--sync implies -I, so no earlier-run stop applies; the scan goes on, as a sync or not."""
    proc = processor(backend="cli", properties=properties)
    proc.cli_args["sync"] = True
    proc.cli_args["ignore_artifactory_properties"] = True
    assert proc.process() is True

    assert proc.reached != []
    assert proc.purl_is_a_placeholder is not syncs
    assert proc.sync_requested() is syncs


@pytest.mark.parametrize(("properties", "asked"), [({}, False), (META_PROPS, True)])
def test_the_store_is_asked_only_about_a_real_purl(
    monkeypatch: pytest.MonkeyPatch,
    properties: dict[str, Any],
    asked: bool,
) -> None:
    """The common sync-without-download step goes through sync_requested() (R7.11.6.2)."""
    proc = processor(backend="cli", properties=properties)
    proc.cli_args.update(sync=True, ignore_artifactory_properties=True, cli_rlstore_path="/store")
    proc.process()

    questions: list[str] = []

    def purl_in_store(*, rlsecure_path: str, store: str | None, purl: str) -> bool:
        questions.append(purl)
        return True

    monkeypatch.setattr(ScanCliLocal, "purl_in_store", staticmethod(purl_in_store))

    assert proc.cli_can_sync_without_download() is asked
    assert len(questions) == int(asked)


def test_an_incomplete_set_raises_once_a_sync_needs_the_purl() -> None:
    """R7.11.3: the purl is checked when it is needed, and a sync needs it."""
    proc = processor(
        backend="cli",
        properties={"RL.meta.name": ["mypkg"]},
        progress=PROGRESS_SCANNED,
        sync_possible=True,
    )
    with pytest.raises(SpectraAssureInvalidAction, match=r"RL\.meta\.version"):
        proc.process()


# ------------------------------------------- R7.11.7 never removed by cleanup


@pytest.mark.parametrize(
    "maintained",
    [tuple(PROP_SPECTRA_ASSURE_ALL), PROP_SPECTRA_ASSURE_ON_SIDE_CAR, ()],
    ids=["file", "side-car", "report"],
)
def test_the_cleanup_never_removes_rl_meta(maintained: tuple[str, ...]) -> None:
    properties = {**FULL_META_PROPS, "RL.meta.other": ["x"], "RL.gone": ["x"], "Spectra.Assure.old": ["x"]}

    assert obsolete_property_names(properties, maintained) == ["RL.gone", "Spectra.Assure.old"]
