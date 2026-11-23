# python3 ts=4space
"""What the generic processor decides, in portal mode and in cli mode.

Characterization tests for `process_portal` and `process_cli`, both at
complexity 12. They share a decision tree - not a candidate, already processed,
can we sync - with differences that are easy to lose in a restructure, so each
one is pinned separately here rather than assumed to be the same.

The important difference: in cli mode a generic artifact without a side-car
or RL.meta.* properties has only the <repo>/<file>@v0 placeholder purl, and
that is never synced (R7.11.6). portal mode always has a real purl.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.constants import (
    PROCESS_FILE_SKIP,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvariantError

from .conftest import make_file

META_URI = "/a/mypkg-1.0.bin.rl_meta"
REPORT = "https://reports.example/abc"
STORED_PURL = "pkg:rl/generic-local/mypkg@1.0"


class FakeFileProperties:
    def __init__(self, skip: bool) -> None:
        self.skip = skip

    def skip_non_candidate_file(self) -> bool:
        return self.skip


def processor(
    *,
    backend: str,
    uri: str = META_URI,
    skip_candidate: bool = False,
    progress: str = "",
    ignore_properties: bool = False,
    sync_possible: bool = False,
    meta_ok: bool = True,
    purl_parts: tuple[str | None, str | None, str | None] = ("generic-local", "mypkg", "1.0"),
) -> Any:
    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)

    proc.uri = uri
    proc.filename = uri.split("/")[-1]
    proc.what_backend = backend
    proc.p_type = "generic"
    proc.cli_args = {"ignore_artifactory_properties": ignore_properties}
    proc.processing_info = ProcessingInfo()
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.files_to_remove = []
    proc.repo_db = {}

    proc.file = make_file(uri=uri, package_type="generic", repo_name="generic-local")
    proc.fp = FakeFileProperties(skip_candidate)

    proc.purl_info = PurlInfo()
    project, package, version = purl_parts
    proc.purl_info.project = project
    proc.purl_info.package = package
    proc.purl_info.version = version

    proc.get_prop_progress = lambda: progress
    proc.get_prop_report = lambda: REPORT
    proc.get_prop_purl = lambda: STORED_PURL
    proc.sync_possible = lambda: sync_possible
    proc._load_meta_info = lambda: (meta_ok, {})

    proc.reached = []
    proc._process_portal = lambda **kwargs: proc.reached.append(("portal", kwargs)) or True
    proc.do_cli_scan_or_sync = lambda **kwargs: proc.reached.append(("cli", kwargs)) or True
    proc._populate_purl_info = lambda project, package, version: None

    return proc


def run_portal(**kwargs: Any) -> Any:
    proc = processor(backend="portal", **kwargs)
    proc.result = proc.process_portal()
    return proc


def run_cli(**kwargs: Any) -> Any:
    proc = processor(backend="cli", **kwargs)
    proc.result = proc.process_cli()
    return proc


# ------------------------------------------------- the backend has to match


def test_process_portal_refuses_a_cli_run() -> None:
    proc = processor(backend="cli")
    with pytest.raises(SpectraAssureInvariantError, match="portal"):
        proc.process_portal()


def test_process_cli_refuses_a_portal_run() -> None:
    proc = processor(backend="portal")
    with pytest.raises(SpectraAssureInvariantError, match="cli"):
        proc.process_cli()


# ------------------------------------------------- not a candidate, in both


@pytest.mark.parametrize("run", [run_portal, run_cli])
def test_a_non_candidate_is_skipped(run: Any) -> None:
    proc = run(skip_candidate=True)

    assert proc.result is True
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert proc.processing_info.reason == "skip: not a candidate for inspection"
    assert proc.processing_info.scan_state is None
    assert proc.processing_info.report is None
    assert proc.processing_info.purl is None


# --------------------------------------------- already processed, in both


@pytest.mark.parametrize("run", [run_portal, run_cli])
def test_an_already_scanned_artifact_stops_there(run: Any) -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=False)

    assert proc.result is True
    assert proc.processing_info.reason == "already processed"
    assert proc.processing_info.scan_state == PROGRESS_SCANNED
    assert proc.processing_info.report == REPORT
    assert proc.processing_info.purl == STORED_PURL


@pytest.mark.parametrize("run", [run_portal, run_cli])
def test_ignoring_the_properties_goes_straight_on(run: Any) -> None:
    proc = run(progress=PROGRESS_SCANNED, sync_possible=False, ignore_properties=True)
    assert proc.reached != []


@pytest.mark.parametrize("run", [run_portal, run_cli])
def test_an_uploaded_but_unscanned_artifact_goes_on(run: Any) -> None:
    proc = run(progress=PROGRESS_UPLOADED)
    assert proc.reached != []


# ------------------------------------ where the two backends differ on sync


def test_portal_can_sync_and_carries_on() -> None:
    proc = run_portal(progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc.need_sync_datetime is True
    assert proc.reached != []


def test_cli_cannot_sync_a_generic_artifact_with_the_placeholder() -> None:
    """No side-car and no RL.meta.* properties: only the placeholder purl."""
    proc = run_cli(progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc.result is True
    assert proc.reached == []
    assert "sync not possible with cli" in proc.processing_info.reason
    assert proc.processing_info.status == PROCESS_FILE_SKIP


def test_cli_still_records_what_the_earlier_run_found() -> None:
    proc = run_cli(progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc.processing_info.scan_state == PROGRESS_SCANNED
    assert proc.processing_info.report == REPORT
    assert proc.processing_info.purl == STORED_PURL


# ------------------------------------------------- the side-car, portal only


def test_portal_stops_when_the_meta_file_cannot_be_read() -> None:
    proc = run_portal(meta_ok=False)

    assert proc.result is True
    assert proc.processing_info.reason == "meta file extract failed"
    assert proc.processing_info.status == PROCESS_FILE_SKIP


@pytest.mark.parametrize(
    ("parts", "missing"),
    [
        ((None, "mypkg", "1.0"), "project"),
        (("generic-local", None, "1.0"), "package"),
        (("generic-local", "mypkg", None), "version"),
    ],
)
def test_portal_needs_every_purl_part_from_the_meta_file(
    parts: tuple[str | None, str | None, str | None],
    missing: str,
) -> None:
    """The side-car said it was valid, so a missing part here is an internal fault."""
    with pytest.raises(SpectraAssureInvariantError, match=missing):
        run_portal(purl_parts=parts)


def test_portal_hands_the_purl_parts_on() -> None:
    proc = run_portal()
    where, kwargs = proc.reached[0]

    assert where == "portal"
    assert kwargs == {"project": "generic-local", "package": "mypkg", "version": "1.0"}


# ------------------------------------------------------ the purl, cli only


def test_cli_makes_its_own_purl_without_a_side_car() -> None:
    """Repo name as project, the file name as package, and a fixed version."""
    proc = run_cli()
    where, kwargs = proc.reached[0]

    assert where == "cli"
    assert kwargs["project"] == "generic-local"
    assert kwargs["version"] == "v0"


def test_cli_uses_the_pre_pass_entry_when_there_is_one() -> None:
    """The generic pre pass collects .rl_meta info into repo_db before the loop."""
    proc = processor(backend="cli")
    proc.repo_db = {
        META_URI: {"project": "from-db", "package": "pkg-from-db", "version": "9.9.9"},
    }
    proc.process_cli()

    _where, kwargs = proc.reached[0]
    assert kwargs == {"project": "from-db", "package": "pkg-from-db", "version": "9.9.9"}


def test_cli_escapes_the_file_name_it_uses_as_a_package() -> None:
    """Only '@' and '/' today: the generic path has its own escaper (R7.9.1).

    A space survives until FUTURE_GENERIC_PURL_ESCAPE is turned on, at which point
    the name manglers' escaper is used and this becomes 'my+pkg...'.
    """
    proc = run_cli(uri="/a/my pkg@1.0.bin")
    _where, kwargs = proc.reached[0]

    assert "@" not in kwargs["package"]
    assert "/" not in kwargs["package"]
    assert kwargs["package"] == "my pkg0x401.0.bin"


def test_cli_escaping_follows_the_future_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag on, the same name comes out as the name manglers would have it."""
    from rl_scan_artifactory.artifactory_file_processor import (
        artifactory_file_processor_generic as module,
    )

    monkeypatch.setattr(module, "FUTURE_GENERIC_PURL_ESCAPE", True)

    proc = run_cli(uri="/a/my pkg@1.0.bin")
    _where, kwargs = proc.reached[0]

    assert " " not in kwargs["package"]
    assert kwargs["package"] == "my+pkg0x401.0.bin"


# ------------------------------------------------ the shared steps, on their own
# Both process functions are now the same three steps, with two differences:
# where the purl comes from, and whether it is a placeholder that never syncs.


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_a_candidate_hands_on(backend: str) -> None:
    proc = processor(backend=backend)
    assert proc._stop_if_not_a_candidate() is None


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_a_non_candidate_stops(backend: str) -> None:
    proc = processor(backend=backend, skip_candidate=True)
    assert proc._stop_if_not_a_candidate() is True


def test_nothing_recorded_hands_on() -> None:
    proc = processor(backend="portal", progress="")
    assert proc._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=False) is None


def test_ignoring_the_properties_hands_on() -> None:
    proc = processor(backend="portal", progress=PROGRESS_SCANNED, ignore_properties=True)
    assert proc._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=False) is None


def test_a_recent_scan_stops_whichever_backend() -> None:
    for placeholder in (False, True):
        proc = processor(backend="portal", progress=PROGRESS_SCANNED, sync_possible=False)
        assert proc._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=placeholder) is True
        assert proc.processing_info.reason == "already processed"


def test_a_syncable_scan_hands_on_when_a_purl_exists() -> None:
    """A real purl - a side-car, or RL.meta.* properties - can be synced."""
    proc = processor(backend="portal", progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=False) is None
    assert proc.need_sync_datetime is True


def test_a_syncable_scan_stops_when_the_purl_is_a_placeholder() -> None:
    """cli without either: the placeholder names a file, not a version."""
    proc = processor(backend="cli", progress=PROGRESS_SCANNED, sync_possible=True)

    assert proc._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=True) is True
    assert proc.need_sync_datetime is True
    assert "sync not possible with cli" in proc.processing_info.reason


# ------------------------------------------------------- stopping, either way


def test_stopping_because_of_the_properties_carries_them_over() -> None:
    proc = processor(backend="portal", progress=PROGRESS_SCANNED)
    proc._stop("a reason", from_properties=True)

    assert proc.processing_info.scan_state == PROGRESS_SCANNED
    assert proc.processing_info.report == REPORT
    assert proc.processing_info.purl == STORED_PURL


def test_stopping_for_any_other_reason_clears_them() -> None:
    """Nothing has been established about this artifact, so claim nothing."""
    proc = processor(backend="portal", progress=PROGRESS_SCANNED)
    proc._stop("a reason")

    assert proc.processing_info.scan_state is None
    assert proc.processing_info.report is None
    assert proc.processing_info.purl is None


@pytest.mark.parametrize("missing", ["project", "package", "version"])
def test_the_purl_parts_are_checked_together(missing: str) -> None:
    parts = {"project": "generic-local", "package": "mypkg", "version": "1.0"}
    parts[missing] = None  # type: ignore[assignment]

    proc = processor(
        backend="portal",
        purl_parts=(parts["project"], parts["package"], parts["version"]),
    )
    with pytest.raises(SpectraAssureInvariantError, match=missing):
        proc._purl_parts()
