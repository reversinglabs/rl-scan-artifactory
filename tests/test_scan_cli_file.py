# python3 ts=4space
"""The scan directory of a cli scan is removed whatever happens (A.16).

`ScanCli` makes one directory per scan, before the scanner starts, and only
`ScanCli.cleanup()` removes it. That used to run on the normal paths of
`do_cli_after_download` only, while an exception there is contained per artifact
and the run goes on: every artifact that raised left its directory, reports and
all, behind in the temp dir. And `cleanup()` itself refused to run when the
scanner had failed to start, so it could not have been put in a `finally`.

`ScanCliBase` no longer makes a directory of its own: nothing used that path,
and the cleanup it relied on never ran.

The scanners are faked; the directories are real.
"""

import logging
import pathlib
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory import scan_cli_file
from rl_scan_artifactory.artifactory_file_processor import artifactory_file_processor_common as common
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.constants import (
    PROCESS_FILE_SKIP,
    PROCESS_FILE_UPDATED,
)
from rl_scan_artifactory.py_cli_scan import ScanCliBase
from rl_scan_artifactory.scan_cli_file import ScanCli

PURL = "pkg:rl/my-repo/mypkg@1.0"


class FakeScanner:
    """Stands in for ScanCliLocal and ScanCliDocker, and remembers its directory."""

    made: list["FakeScanner"]

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.temp_dir_path = kwargs["temp_dir_path"]
        self.purl_exists = True
        self.calls: list[str] = []
        FakeScanner.made.append(self)

    def test_purl_exists(self) -> bool:
        return self.purl_exists

    def do_scan_and_report(self, **kwargs: Any) -> tuple[int, str, str | None]:
        self.calls.append("scan")
        return 0, f"{self.temp_dir_path}/bundle.zip", "pass"

    def do_sync_and_report(self, **kwargs: Any) -> tuple[int, str, str | None]:
        self.calls.append("sync")
        return 0, f"{self.temp_dir_path}/bundle.zip", "pass"


class BrokenScanner:
    def __init__(self, **kwargs: Any) -> None:
        raise RuntimeError("FATAL: rl-secure init must be done before using this module")


@pytest.fixture(autouse=True)
def fake_scanners(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeScanner.made = []
    monkeypatch.setattr(scan_cli_file, "ScanCliLocal", FakeScanner)
    monkeypatch.setattr(scan_cli_file, "ScanCliDocker", FakeScanner)


def local_cli(tmp_path: pathlib.Path, **cli_args: Any) -> ScanCli:
    return ScanCli(cli_args={"cli_rlsecure_path": str(tmp_path), **cli_args})


def docker_cli(**cli_args: Any) -> ScanCli:
    return ScanCli(
        cli_args={
            "cli_docker": True,
            "rlsecure_encoded_license": "lic",
            "rlsecure_site_key": "key",
            **cli_args,
        },
    )


# ---------------------------------------------------------------- cleanup()


def test_cleanup_removes_the_scan_directory(tmp_path: pathlib.Path) -> None:
    cli = local_cli(tmp_path)
    cli.scan_file(file_path="/dl/x.tgz", purl=PURL)
    made = cli.temp_dir_name
    assert made is not None
    assert pathlib.Path(made).is_dir()

    cli.cleanup()
    assert not pathlib.Path(made).exists()


def test_cleanup_twice_is_harmless(tmp_path: pathlib.Path) -> None:
    cli = local_cli(tmp_path)
    cli.scan_file(file_path="/dl/x.tgz", purl=PURL)
    cli.cleanup()
    cli.cleanup()
    assert cli.temp_dir_name is None


def test_cleanup_before_any_scan_is_harmless(tmp_path: pathlib.Path) -> None:
    """It runs from a finally, possibly before the scan made anything."""
    local_cli(tmp_path).cleanup()


def test_cleanup_removes_the_directory_when_the_scanner_did_not_start(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scan_cli_file, "ScanCliLocal", BrokenScanner)
    cli = local_cli(tmp_path)

    with pytest.raises(RuntimeError):
        cli.scan_file(file_path="/dl/x.tgz", purl=PURL)

    made = cli.temp_dir_name
    assert made is not None
    assert cli.scanner is None
    cli.cleanup()
    assert not pathlib.Path(made).exists()


def test_a_directory_that_cannot_be_removed_is_logged_not_raised(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Raising here would replace whatever the scan itself raised."""
    cli = local_cli(tmp_path)
    cli.temp_dir_name = str(tmp_path / "not-there")

    with caplog.at_level(logging.WARNING):
        cli.cleanup()

    assert "cannot remove scan directory" in caplog.text
    assert cli.temp_dir_name is None


# --------------------------------------------------------------- scan_file()


def test_local_scans_in_its_own_directory(tmp_path: pathlib.Path) -> None:
    cli = local_cli(tmp_path, cli_rlstore_path="/store", reports_requested=["rl-html"])
    result = cli.scan_file(file_path="/dl/x.tgz", purl=PURL)

    scanner = FakeScanner.made[0]
    assert result == (0, f"{cli.temp_dir_name}/bundle.zip", "pass")
    assert scanner.calls == ["scan"]
    assert scanner.kwargs["temp_dir_path"] == cli.temp_dir_name
    assert scanner.kwargs["where"] == str(tmp_path)
    assert scanner.kwargs["store"] == "/store"
    assert scanner.kwargs["reports_list"] == ["rl-html"]
    cli.cleanup()


def test_docker_scans_in_its_own_directory() -> None:
    cli = docker_cli()
    cli.scan_file(file_path="/dl/x.tgz", purl=PURL)

    scanner = FakeScanner.made[0]
    assert scanner.calls == ["scan"]
    assert scanner.kwargs["encoded_license"] == "lic"
    assert scanner.kwargs["site_key"] == "key"
    cli.cleanup()


def test_a_sync_uses_the_store_when_the_purl_is_there(tmp_path: pathlib.Path) -> None:
    cli = local_cli(tmp_path, cli_rlstore_path="/store")
    cli.scan_file(file_path="", purl=PURL, sync_requested=True)
    assert FakeScanner.made[0].calls == ["sync"]
    cli.cleanup()


@pytest.mark.parametrize("store", [None, "/store"])
def test_docker_always_scans(store: str | None) -> None:
    """The rl-scanner image has no sync and cannot ask a store about a purl (R12.7.2)."""
    cli = docker_cli(cli_rlstore_path=store)
    cli.scan_file(file_path="/dl/x.tgz", purl=PURL, sync_requested=True)

    scanner = FakeScanner.made[0]
    assert scanner.calls == ["scan"]
    assert scanner.kwargs["store"] == store
    cli.cleanup()


def test_a_sync_without_a_store_is_refused(tmp_path: pathlib.Path) -> None:
    """Refused after the directory was made, so the caller's cleanup must still run."""
    cli = local_cli(tmp_path)
    with pytest.raises(RuntimeError, match="store is None"):
        cli.scan_file(file_path="", purl=PURL, sync_requested=True)

    made = cli.temp_dir_name
    assert made is not None
    cli.cleanup()
    assert not pathlib.Path(made).exists()


@pytest.mark.parametrize("missing", ["rlsecure_encoded_license", "rlsecure_site_key"])
def test_docker_needs_its_licence(missing: str) -> None:
    cli = docker_cli(**{missing: ""})
    with pytest.raises(RuntimeError):
        cli.scan_file(file_path="/dl/x.tgz", purl=PURL)
    assert cli.temp_dir_name is None


def test_rlsecure_must_be_a_directory(tmp_path: pathlib.Path) -> None:
    with pytest.raises(RuntimeError, match="must be the directory"):
        ScanCli(cli_args={"cli_rlsecure_path": str(tmp_path / "missing")})


# ----------------------------------------- the caller always cleans up


class FakeScanCli:
    def __init__(self, result: tuple[int, str, str | None] | Exception) -> None:
        self.result = result
        self.cleaned = 0

    def scan_file(self, **kwargs: Any) -> tuple[int, str, str | None]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def get_rl_json_report_path(self) -> str:
        return "/nowhere/report.rl.json"

    def cleanup(self) -> None:
        self.cleaned += 1


def after_download(
    monkeypatch: pytest.MonkeyPatch,
    result: tuple[int, str, str | None] | Exception,
    *,
    upload: Any = None,
    sync: bool = False,
    unchanged: bool | None = False,
) -> tuple[Any, FakeScanCli]:
    fake = FakeScanCli(result)
    monkeypatch.setattr(common, "ScanCli", lambda cli_args: fake)

    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.what_backend = "cli"
    proc.cli_args = {"sync": sync}
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo(project="my-repo", package="mypkg", version="1.0")
    proc.files_to_remove = []
    proc._upload_the_report = upload or (lambda **kwargs: "https://reports.example/r")
    proc._update_artifactory_item_with_scan_status = lambda **kwargs: None
    proc._tag_the_report_as_not_to_scan = lambda **kwargs: None
    proc.cli_synced_artifact_is_unchanged = lambda report_path: unchanged
    return proc, fake


def run(proc: Any, download_path: str = "/dl/x.tgz") -> Any:
    return proc.do_cli_after_download(project="my-repo", package="mypkg", version="1.0", download_path=download_path)


def test_a_scan_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, fake = after_download(monkeypatch, (0, "/t/bundle.zip", "pass"))
    assert run(proc) is True
    assert proc.processing_info.status == PROCESS_FILE_UPDATED
    assert proc.processing_info.reason == "cli"
    assert fake.cleaned == 1


def test_a_failed_scan_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, fake = after_download(monkeypatch, (101, "", None))
    assert run(proc) is True
    assert proc.processing_info.status == PROCESS_FILE_SKIP
    assert fake.cleaned == 1


def test_a_stale_sync_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, fake = after_download(monkeypatch, (0, "/t/bundle.zip", "pass"))
    assert run(proc, download_path="") is False
    assert proc.cli_sync_was_stale is True
    assert fake.cleaned == 1


def test_a_scan_that_raises_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, fake = after_download(monkeypatch, RuntimeError("store is None"))
    with pytest.raises(RuntimeError):
        run(proc)
    assert fake.cleaned == 1


def test_an_upload_that_raises_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def upload(**kwargs: Any) -> str:
        raise OSError("connection reset")

    proc, fake = after_download(monkeypatch, (0, "/t/bundle.zip", "pass"), upload=upload)
    with pytest.raises(OSError, match="connection reset"):
        run(proc)
    assert fake.cleaned == 1


# ------------------------------------------- the reason says what happened
# A run over 548 npm artifacts reported every one of them as 'cli-sync' while
# every one had been downloaded and scanned: the purls were not in the local
# store, so each sync fell back (R12.7.4.2). The reason reported what was asked
# for rather than what was done, and the timings were the only way to tell.


@pytest.mark.parametrize("unchanged", [True, None])
def test_a_sync_that_used_the_store_says_so(monkeypatch: pytest.MonkeyPatch, unchanged: bool | None) -> None:
    """No download path means the store answered; an unknown digest lets it stand."""
    proc, _ = after_download(monkeypatch, (0, "/t/bundle.zip", "pass"), sync=True, unchanged=unchanged)
    assert run(proc, download_path="") is True
    assert proc.processing_info.reason == "cli-sync"


@pytest.mark.parametrize("sync", [True, False])
def test_a_scan_says_it_scanned_however_it_was_reached(monkeypatch: pytest.MonkeyPatch, sync: bool) -> None:
    """Asked for a sync and fell back to a download, or never asked: both scanned."""
    proc, _ = after_download(monkeypatch, (0, "/t/bundle.zip", "pass"), sync=sync)
    assert run(proc) is True
    assert proc.processing_info.reason == "cli"


# ------------------------------------------- the scanner owns no directory


def test_the_scanner_needs_a_directory_from_its_caller() -> None:
    with pytest.raises(TypeError):
        ScanCliBase(purl=PURL)  # type: ignore[call-arg]


def test_the_scanner_leaves_the_directory_to_its_caller(tmp_path: pathlib.Path) -> None:
    scan = ScanCliBase(purl=PURL, temp_dir_path=str(tmp_path))
    del scan
    assert tmp_path.is_dir()
