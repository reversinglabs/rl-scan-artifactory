# python3 ts=4space
"""What the default processor decides: the path every ordinary package type takes.

`ArtifactoryFileProcessorDefault` handles everything except docker and generic —
pypi, npm, maven, rpm, nuget, gems, debian — so it is the path most artifacts in
most repositories actually go down. It was the least tested file in the package.

Its `process()` is the same decision tree docker and generic have, with two
differences that exist only here:

- the purl comes from the name mangler for the package type, so this is the one
  `process()` whose result depends on which type the repository is;
- it *clears* processing_info at the top, where docker presets it to skip and
  generic sets the fields per branch.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_default import (
    ArtifactoryFileProcessorDefault,
)
from rl_scan_artifactory.constants import (
    PROCESS_FILE_SKIP,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvariantError

from .conftest import make_file

REPORT = "https://reports.example/abc"
STORED_PURL = "pkg:rl/my-repo/mypkg@1.0"

# one uri per package type, as the repository would hold it
BY_TYPE: dict[str, str] = {
    "pypi": "/m/mypkg/mypkg-1.0-py3-none-any.whl",
    "npm": "/mypkg/-/mypkg-1.0.tgz",
    "maven": "/org/example/mypkg/1.0/mypkg-1.0.jar",
    "rpm": "/mypkg-1.0-1.el9.x86_64.rpm",
    "nuget": "/mypkg.1.0.nupkg",
    "gems": "/gems/mypkg-1.0.gem",
    "debian": "/pool/m/mypkg/mypkg_1.0_amd64.deb",
}


class FakeFileProperties:
    def __init__(self, skip: bool) -> None:
        self.skip = skip

    def skip_non_candidate_file(self) -> bool:
        return self.skip


def processor(
    *,
    package_type: str = "pypi",
    uri: str | None = None,
    skip_candidate: bool = False,
    progress: str = "",
    ignore_properties: bool = False,
    sync_possible: bool = False,
    backend: str = "portal",
    purl_parts: tuple[str, str, str] = ("my-repo", "mypkg", "1.0"),
) -> Any:
    proc: Any = ArtifactoryFileProcessorDefault.__new__(ArtifactoryFileProcessorDefault)

    proc.uri = uri if uri is not None else BY_TYPE[package_type]
    proc.filename = proc.uri.split("/")[-1]
    proc.what_backend = backend
    proc.p_type = package_type
    proc.cli_args = {"ignore_artifactory_properties": ignore_properties}
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo()
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.files_to_remove = []

    proc.file = make_file(uri=proc.uri, package_type=package_type, repo_name="my-repo")
    proc.fp = FakeFileProperties(skip_candidate)

    proc.get_prop_progress = lambda: progress
    proc.get_prop_report = lambda: REPORT
    proc.get_prop_purl = lambda: STORED_PURL
    proc.sync_possible = lambda: sync_possible

    proc.mangled = []

    def mangler(p_type: str) -> tuple[str, str, str]:
        proc.mangled.append(p_type)
        return purl_parts

    proc.get_purl_from_name_mangler = mangler

    def populate(project: str, package: str, version: str) -> None:
        proc.purl_info.project = project
        proc.purl_info.package = package
        proc.purl_info.version = version

    proc._populate_purl_info = populate

    proc.reached = []
    proc._process_portal = lambda **kwargs: proc.reached.append(("portal", kwargs)) or True
    proc._process_cli = lambda **kwargs: proc.reached.append(("cli", kwargs)) or True

    return proc


def run(**kwargs: Any) -> Any:
    proc = processor(**kwargs)
    proc.result = proc.process()
    return proc


# ------------------------------------------------------- not a candidate


def test_a_non_candidate_is_skipped() -> None:
    proc = run(skip_candidate=True)

    assert proc.result is True
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert proc.processing_info.reason == "not a candidate file"
    assert proc.processing_info.scan_state is None
    assert proc.processing_info.report is None
    assert proc.processing_info.purl is None


def test_a_non_candidate_never_reaches_the_mangler() -> None:
    """No point deriving a purl for something we are not going to scan."""
    proc = run(skip_candidate=True)
    assert proc.mangled == []


def test_a_missing_file_properties_object_is_an_internal_fault() -> None:
    proc = processor()
    proc.fp = None

    with pytest.raises(SpectraAssureInvariantError, match="self.fp"):
        proc.process()


# ------------------------------------------- what an earlier run recorded


def test_an_already_scanned_artifact_stops_there() -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=False)

    assert proc.result is True
    assert proc.processing_info.reason == "properties already exist in artifactory"
    assert proc.processing_info.scan_state == PROGRESS_SCANNED
    assert proc.processing_info.report == REPORT
    assert proc.processing_info.purl == STORED_PURL
    assert proc.reached == []


def test_an_already_scanned_artifact_that_can_sync_carries_on() -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc.need_sync_datetime is True
    assert proc.reached != []


def test_an_uploaded_but_unscanned_artifact_carries_on() -> None:
    """Only 'scanned' stops here; an unfinished upload is picked up again."""
    proc = run(progress=PROGRESS_UPLOADED)
    assert proc.reached != []


def test_ignoring_the_properties_skips_the_whole_check() -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=False, ignore_properties=True)
    assert proc.reached != []


def test_ignoring_the_properties_does_not_leak_the_old_scan_state() -> None:
    """Unlike docker, this one clears processing_info at the top and never
    reads the stored progress when it was told to ignore it."""
    proc = run(progress=PROGRESS_SCANNED, ignore_properties=True)
    assert proc.processing_info.scan_state is None


# ----------------------------------------------- the purl, per package type


@pytest.mark.parametrize("package_type", sorted(BY_TYPE))
def test_every_package_type_reaches_its_own_mangler(package_type: str) -> None:
    """This is the one process() whose result depends on the package type."""
    proc = run(package_type=package_type)
    assert proc.mangled == [package_type]


@pytest.mark.parametrize("package_type", sorted(BY_TYPE))
def test_every_package_type_reaches_a_backend(package_type: str) -> None:
    proc = run(package_type=package_type)
    assert proc.reached != []


def test_the_purl_parts_are_handed_on() -> None:
    proc = run(purl_parts=("my-repo", "mypkg", "1.0"))
    _where, kwargs = proc.reached[0]

    assert kwargs == {"project": "my-repo", "package": "mypkg", "version": "1.0"}


def test_the_purl_parts_are_stored_before_the_handover() -> None:
    """The backend reads purl_info as well as its arguments."""
    proc = run(purl_parts=("my-repo", "mypkg", "9.9.9"))

    assert proc.purl_info.project == "my-repo"
    assert proc.purl_info.package == "mypkg"
    assert proc.purl_info.version == "9.9.9"


# --------------------------------------------------------- which backend


def test_a_portal_run_goes_to_the_portal() -> None:
    proc = run(backend="portal")
    where, _kwargs = proc.reached[0]
    assert where == "portal"


def test_a_cli_run_goes_to_the_cli() -> None:
    proc = run(backend="cli")
    where, _kwargs = proc.reached[0]
    assert where == "cli"


# ---------------------------------------------------- the starting state


def test_processing_info_starts_cleared() -> None:
    """Docker starts as skip, generic sets fields per branch, this one clears."""
    proc = processor()
    proc.processing_info.completed = True
    proc.processing_info.reason = "left over"

    proc.fp = FakeFileProperties(False)
    proc.process()

    assert proc.processing_info.reason != "left over"


def test_a_carried_on_artifact_is_not_marked_completed_here() -> None:
    """Whether it completed is for the backend to say, not for this step."""
    proc = processor()
    proc._process_portal = lambda **kwargs: True
    proc.process()

    assert proc.processing_info.completed is False


def test_nothing_is_logged_at_warning_on_the_ordinary_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        run()
    assert caplog.text == ""
