# python3 ts=4space
"""A generic artifact is compared with the portal on the hash of the file described.

For generic, `self.file` is the `.rl_meta` side-car, so `self.file.sha2` is the
hash of the side-car and the portal was asked without a digest at all (A.17): an
artifact rebuilt under the same version was taken as already scanned on its purl
alone, and never uploaded again.

The repository listing already carries `sha2` for every file. What is pinned
here is the hand over, in three steps: the listing keeps the hash of every file,
not only of the side-cars it hands on; the generic pre pass puts the hash of the
described file beside the side-car's entry in repo_db; and `_process_portal`
passes that hash as the digest (R10.7.4).

Only artifactory and the spectra assure api are faked.
"""

from typing import (
    Any,
)

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.artifactory_repo_processor import ArtifactoryRepoProcessor
from rl_scan_artifactory.constants import (
    PROCESS_FILE_FAILED,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
    REPO_DB_FAILED_SIDE_CARS,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction
from rl_scan_artifactory.my_app import MyApp

from .conftest import make_file, make_repo

META_URI = "/a/mypkg-1.0.bin.rl_meta"
TARGET_URI = "/a/mypkg-1.0.bin"
META_SHA2 = "m" * 64
TARGET_SHA2 = "t" * 64

LISTING = {
    "files": [
        {"uri": META_URI, "sha2": META_SHA2},
        {"uri": TARGET_URI, "sha2": TARGET_SHA2},
        {"uri": "/a/no-hash.bin"},
    ],
}


def repo_processor(*, cli: bool = False) -> Any:
    arp: Any = ArtifactoryRepoProcessor.__new__(ArtifactoryRepoProcessor)
    arp.p_type = "generic"
    arp.cli_args = {"cli": cli}
    arp.sha2_by_uri = {}
    return arp


# ------------------------------------------------ the listing keeps the hashes


def test_the_listing_hands_on_every_file() -> None:
    """A file without a side-car may carry RL.meta.* properties (R7.11.5)."""
    arp = repo_processor()
    handed_on = [item["uri"] for item in arp.extract_my_interesting_files(LISTING)]
    assert handed_on == [META_URI, TARGET_URI, "/a/no-hash.bin"]


def test_the_listing_keeps_the_hash_of_every_file() -> None:
    """Including the files it does not hand on, and none it was not given."""
    arp = repo_processor()
    arp.extract_my_interesting_files(LISTING)
    assert arp.sha2_by_uri == {META_URI: META_SHA2, TARGET_URI: TARGET_SHA2}


def test_a_cli_run_keeps_the_hashes_too() -> None:
    arp = repo_processor(cli=True)
    arp.extract_my_interesting_files(LISTING)
    assert arp.sha2_by_uri[TARGET_URI] == TARGET_SHA2


# ------------------------------------------- the pre pass puts it in repo_db


class FakeSideCar:
    def __init__(self, path: str | None, *, raises: Exception | None = None) -> None:
        self.path = path
        self.raises = raises
        self.cleaned = False

    def extract_generic_meta_info(self) -> dict[str, Any]:
        if self.raises is not None:
            raise self.raises
        meta = {} if self.path is None else {"path": self.path}
        return {"project": "generic-local", "package": "mypkg", "version": "1.0", "meta": meta}

    def remove_my_files(self) -> None:
        self.cleaned = True


def pre_pass_app(side_car_for: Any, listing: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    arp = repo_processor()
    arp.repo = make_repo(name="generic-local", package_type="generic")
    arp.process = lambda: arp.extract_my_interesting_files(listing if listing is not None else LISTING)

    app: Any = MyApp.__new__(MyApp)
    app._get_my_afp = lambda **kwargs: side_car_for(kwargs["artifact_item"]["uri"])
    app.failed_items = []
    app.printed = []
    app.my_print = app.printed.append

    repo_db: dict[str, Any] = {}
    app._repo_generic_extract_rl_meta_info(arp, repo_db)
    return app, repo_db


def pre_pass(path: str | None) -> dict[str, Any]:
    _app, repo_db = pre_pass_app(lambda _uri: FakeSideCar(path))
    return repo_db


def test_the_pre_pass_stores_the_hash_of_the_described_file() -> None:
    assert pre_pass("mypkg-1.0.bin")[TARGET_URI]["sha2"] == TARGET_SHA2


def test_the_pre_pass_maps_each_side_car_to_the_file_it_describes() -> None:
    """A later run decides on the side-car's properties before reading it again (R10.8)."""
    assert pre_pass("mypkg-1.0.bin")[REPO_DB_DESCRIBED_BY_SIDE_CAR] == {META_URI: TARGET_URI}


def test_a_described_file_missing_from_the_listing_has_no_hash() -> None:
    assert pre_pass("not-there.bin")["/a/not-there.bin"]["sha2"] is None


def test_a_side_car_without_a_path_stores_nothing() -> None:
    assert pre_pass(None) == {}


# ------------------------------- R12.1.1 one unreadable side-car fails only itself

BROKEN_URI = "/a/broken.bin.rl_meta"
TWO_SIDE_CARS = {"files": [{"uri": BROKEN_URI, "sha2": "b" * 64}, *LISTING["files"]]}


def broken_then_good() -> tuple[Any, dict[str, Any], dict[str, FakeSideCar]]:
    made: dict[str, FakeSideCar] = {}

    def side_car_for(uri: str) -> FakeSideCar:
        raises = SpectraAssureInvalidAction("missing mandatory items in .rl_meta file") if uri == BROKEN_URI else None
        made[uri] = FakeSideCar("mypkg-1.0.bin", raises=raises)
        return made[uri]

    app, repo_db = pre_pass_app(side_car_for, TWO_SIDE_CARS)
    return app, repo_db, made


def test_an_unreadable_side_car_does_not_end_the_pre_pass() -> None:
    _app, repo_db, _made = broken_then_good()
    assert repo_db[REPO_DB_DESCRIBED_BY_SIDE_CAR] == {META_URI: TARGET_URI}


def test_an_unreadable_side_car_is_recorded_as_failed() -> None:
    app, repo_db, _made = broken_then_good()
    assert app.failed_items == [("generic-local", BROKEN_URI)]
    assert repo_db[REPO_DB_FAILED_SIDE_CARS] == {BROKEN_URI}
    assert any(BROKEN_URI in line and line.startswith("FAIL") for line in app.printed)


def test_the_download_of_every_side_car_is_cleaned_up() -> None:
    _app, _repo_db, made = broken_then_good()
    assert all(side_car.cleaned for side_car in made.values())


def test_the_main_loop_does_not_try_a_failed_side_car_again() -> None:
    app: Any = MyApp.__new__(MyApp)
    app.cli_args = {"portal": True}
    app.failed_items = [("generic-local", BROKEN_URI)]
    app.printed = []
    app.my_print = app.printed.append
    processed: list[str] = []

    class Untouchable(FakeSideCar):
        def process(self) -> bool:
            processed.append("process")
            return True

        def remove_obsolete_properties(self) -> None:
            processed.append("cleanup")

    app._get_my_afp = lambda **kwargs: Untouchable(None)

    reason = app._run_one_repo_one_artifact(
        repo=make_repo(name="generic-local", package_type="generic"),
        p_type="generic",
        artifact_item={"uri": BROKEN_URI},
        repo_db={REPO_DB_FAILED_SIDE_CARS: {BROKEN_URI}},
    )

    assert reason == PROCESS_FILE_FAILED
    assert processed == []
    assert app.failed_items == [("generic-local", BROKEN_URI)]


# ------------------------------------------------ and the portal is asked with it


class FakeSpectraAssureApi:
    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []

    def exist_version(self, **kwargs: Any) -> tuple[bool, bool]:
        self.asked.append(kwargs)
        return False, False


def generic_processor(*, repo_db: dict[str, Any], portal: bool = True) -> Any:
    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)

    proc.uri = META_URI
    proc.what_backend = "portal"
    proc.cli_args = {"portal": portal}
    proc.need_sync_datetime = False
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo(project="generic-local", package="mypkg", version="1.0")
    proc.file = make_file(
        uri=META_URI,
        package_type="generic",
        repo_name="generic-local",
        sha2=META_SHA2,
        properties={"generic._derived_.path": ["mypkg-1.0.bin"]},
    )
    proc.repo_db = repo_db
    proc.portal_has_other_bytes = False
    proc.spectra_assure_api = FakeSpectraAssureApi()

    proc._portal_download_upload_generic = lambda **kwargs: False

    return proc


def asked_digest(proc: Any) -> Any:
    proc._process_portal(project="generic-local", package="mypkg", version="1.0")
    return proc.spectra_assure_api.asked[0]["digest"]


def test_the_portal_is_asked_with_the_hash_of_the_described_file() -> None:
    proc = generic_processor(repo_db={TARGET_URI: {"sha2": TARGET_SHA2}})
    assert asked_digest(proc) == TARGET_SHA2


def test_never_with_the_hash_of_the_side_car() -> None:
    """With no pre pass entry there is nothing to compare, not the side-car's hash."""
    proc = generic_processor(repo_db={})
    assert asked_digest(proc) is None
