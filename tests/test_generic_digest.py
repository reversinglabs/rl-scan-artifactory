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
from rl_scan_artifactory.constants import REPO_DB_DESCRIBED_BY_SIDE_CAR
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


def test_the_listing_hands_on_only_the_side_cars() -> None:
    arp = repo_processor()
    assert [item["uri"] for item in arp.extract_my_interesting_files(LISTING)] == [META_URI]


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
    def __init__(self, path: str | None) -> None:
        self.path = path

    def extract_generic_meta_info(self) -> dict[str, Any]:
        meta = {} if self.path is None else {"path": self.path}
        return {"project": "generic-local", "package": "mypkg", "version": "1.0", "meta": meta}


def pre_pass(path: str | None) -> dict[str, Any]:
    arp = repo_processor()
    arp.repo = make_repo(name="generic-local", package_type="generic")
    arp.process = lambda: arp.extract_my_interesting_files(LISTING)

    app: Any = MyApp.__new__(MyApp)
    app._get_my_afp = lambda **kwargs: FakeSideCar(path)

    repo_db: dict[str, Any] = {}
    app._repo_generic_extract_rl_meta_info(arp, repo_db)
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
