# python3 ts=4space
"""Failure containment, exit codes, and where the log goes.

A repository holds data we do not control, so one malformed artifact must never
end the run. These tests drive MyApp with fake file processors: no Artifactory,
no Portal, no downloads.
"""

import logging
import pathlib
import sys
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.app_base_with_logging import AppBaseWithLogging
from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.constants import (
    EXIT_FATAL,
    EXIT_INTERRUPTED,
    EXIT_ITEM_FAILURES,
    EXIT_OK,
    PROCESS_FILE_FAILED,
)
from rl_scan_artifactory.my_app import MyApp


class FakeFileProcessor:
    """Stands in for an ArtifactoryFileProcessor; records whether cleanup ran."""

    def __init__(
        self,
        uri: str,
        *,
        raises: BaseException | None = None,
        completed: bool = True,
    ) -> None:
        self.uri = uri
        self.raises = raises
        self.completed = completed
        self.cleaned = False
        self.max_time = 0
        self.obsolete_removed = False

    def remove_obsolete_properties(self) -> None:
        self.obsolete_removed = True

    def process(self) -> bool:
        if self.raises is not None:
            raise self.raises
        return self.completed

    def remove_my_files(self) -> None:
        self.cleaned = True

    def get_uri(self) -> str:
        return self.uri

    def get_process_status(self) -> str:
        return "Processed"


def make_app(*, portal: bool = True, repo_names: list[str] | None = None) -> Any:
    app: Any = MyApp.__new__(MyApp)
    app.cli_args = {"portal": portal, "repo": repo_names if repo_names is not None else ["r1"]}
    app.verbose = False
    app.not_finished = []
    app.failed_items = []
    app.failed_repos = []
    app.printed = []
    app.my_print = app.printed.append
    app._print_info_report = lambda **_kwargs: None
    app._if_print_version_and_exit = lambda: None
    app._verify_portal_connect = lambda: None
    return app


def repo_info(name: str = "r1") -> ArtifactoryRepoInfo:
    return ArtifactoryRepoInfo(name=name, repo_type="local", package_type="generic", layout="s")


def run_items(app: Any, uris: list[str], *, exploding: set[str] | None = None) -> list[str]:
    """Drive _run_one_repo_one_artifact over a list of uris."""
    exploding = exploding if exploding is not None else set()
    made: list[FakeFileProcessor] = []

    def get_afp(**kwargs: Any) -> FakeFileProcessor:
        uri = kwargs["artifact_item"]["uri"]
        raises = ValueError(f"bad item {uri}") if uri in exploding else None
        proc = FakeFileProcessor(uri, raises=raises)
        made.append(proc)
        return proc

    app._get_my_afp = get_afp
    app.made = made

    return [
        app._run_one_repo_one_artifact(
            repo=repo_info(),
            p_type="generic",
            artifact_item={"uri": uri},
            repo_db={},
        )
        for uri in uris
    ]


# ------------------------------------------------------- per item containment


def test_a_failing_item_does_not_stop_the_ones_after_it() -> None:
    app = make_app()
    statuses = run_items(app, ["/a.bin", "/bad.bin", "/c.bin"], exploding={"/bad.bin"})
    assert statuses == ["Processed", PROCESS_FILE_FAILED, "Processed"]


def test_a_failing_item_is_recorded_with_its_repo_and_uri() -> None:
    app = make_app()
    run_items(app, ["/bad.bin"], exploding={"/bad.bin"})
    assert app.failed_items == [("r1", "/bad.bin")]


def test_cleanup_runs_even_when_the_item_raised() -> None:
    """remove_my_files is in a finally: a crash must not leak the download."""
    app = make_app()
    run_items(app, ["/a.bin", "/bad.bin"], exploding={"/bad.bin"})
    assert all(proc.cleaned for proc in app.made)


def test_a_failing_item_is_logged_and_printed(caplog: pytest.LogCaptureFixture) -> None:
    app = make_app()
    with caplog.at_level(logging.ERROR):
        run_items(app, ["/bad.bin"], exploding={"/bad.bin"})

    assert "/bad.bin" in caplog.text
    assert any("/bad.bin" in line for line in app.printed)


def test_a_clean_item_is_not_recorded_as_failed() -> None:
    app = make_app()
    run_items(app, ["/a.bin", "/b.bin"])
    assert app.failed_items == []


# ------------------------------------------------------- per repo containment


def run_repos(app: Any, *, exploding: set[str] | None = None) -> None:
    exploding = exploding if exploding is not None else set()
    app.artifactory_api = type("Api", (), {"get_artifactory_version": lambda _self: "7.0"})()
    app.seen = []

    def run_one(name: str) -> None:
        app.seen.append(name)
        if name in exploding:
            msg = f"repo {name} exploded"
            raise RuntimeError(msg)

    app._run_one_repo_all_artifacts = run_one
    app.run_all()


def test_a_failing_repo_does_not_stop_the_repos_after_it() -> None:
    app = make_app(repo_names=["r1", "r2", "r3"])
    run_repos(app, exploding={"r2"})
    assert app.seen == ["r1", "r2", "r3"]


def test_a_failing_repo_is_recorded() -> None:
    app = make_app(repo_names=["r1", "r2"])
    run_repos(app, exploding={"r2"})
    assert app.failed_repos == ["r2"]


# --------------------------------------------------------- pending items
# In portal mode unfinished items are parked and completed at the very end.
# They hold scans we already paid for, so they must run even after a failure.


def park(app: Any, *processors: FakeFileProcessor) -> None:
    app.not_finished = list(processors)


def test_pending_items_are_finished_even_after_a_repo_failed() -> None:
    app = make_app(repo_names=["r1"])
    pending = FakeFileProcessor("/pending.bin")

    app.artifactory_api = type("Api", (), {"get_artifactory_version": lambda _self: "7.0"})()

    def run_one(_name: str) -> None:
        park(app, pending)
        msg = "boom"
        raise RuntimeError(msg)

    app._run_one_repo_all_artifacts = run_one
    app.run_all()

    assert pending.cleaned is True


def test_one_failing_pending_item_does_not_stop_the_others() -> None:
    app = make_app()
    ok_before = FakeFileProcessor("/one.bin")
    bad = FakeFileProcessor("/two.bin", raises=RuntimeError("portal still busy"))
    ok_after = FakeFileProcessor("/three.bin")
    park(app, ok_before, bad, ok_after)

    app._finish_any_pending()

    assert [p.cleaned for p in (ok_before, bad, ok_after)] == [True, True, True]
    assert [uri for _repo, uri in app.failed_items] == ["/two.bin"]


def test_pending_items_are_not_run_outside_portal_mode() -> None:
    app = make_app(portal=False, repo_names=["r1"])
    pending = FakeFileProcessor("/pending.bin")
    park(app, pending)

    app.artifactory_api = type("Api", (), {"get_artifactory_version": lambda _self: "7.0"})()
    app._run_one_repo_all_artifacts = lambda _name: None
    app.run_all()

    assert pending.cleaned is False


# ------------------------------------------------------------- exit codes


def test_a_clean_run_exits_ok() -> None:
    app = make_app()
    run_items(app, ["/a.bin"])
    assert app.get_exit_code() == EXIT_OK


def test_a_run_with_a_failed_item_exits_with_item_failures() -> None:
    app = make_app()
    run_items(app, ["/bad.bin"], exploding={"/bad.bin"})
    assert app.get_exit_code() == EXIT_ITEM_FAILURES


def test_ignore_skipped_turns_a_partial_run_into_success() -> None:
    """A pipeline may prefer to treat a partial run as success."""
    app = make_app()
    app.cli_args["ignore_skipped"] = True
    run_items(app, ["/bad.bin"], exploding={"/bad.bin"})

    assert app.get_exit_code() == EXIT_OK


def test_ignore_skipped_says_so_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """The failures are still logged and summarised; only the exit code changes."""
    app = make_app()
    app.cli_args["ignore_skipped"] = True
    run_items(app, ["/bad.bin"], exploding={"/bad.bin"})

    with caplog.at_level(logging.WARNING):
        app.get_exit_code()

    assert "--ignore-skipped" in caplog.text


def test_ignore_skipped_does_not_invent_failures() -> None:
    app = make_app()
    app.cli_args["ignore_skipped"] = True
    run_items(app, ["/a.bin"])

    assert app.get_exit_code() == EXIT_OK


def test_a_run_with_a_failed_repo_exits_with_item_failures() -> None:
    app = make_app(repo_names=["r1"])
    run_repos(app, exploding={"r1"})
    assert app.get_exit_code() == EXIT_ITEM_FAILURES


def test_the_failure_summary_names_the_counts(caplog: pytest.LogCaptureFixture) -> None:
    app = make_app(repo_names=["r1", "r2"])
    with caplog.at_level(logging.ERROR):
        run_repos(app, exploding={"r2"})
    assert "1 failed item(s)" in caplog.text or "0 failed item(s)" in caplog.text
    assert "1 failed repo(s)" in caplog.text


def test_a_clean_run_prints_no_failure_summary() -> None:
    app = make_app(repo_names=["r1"])
    run_repos(app)
    assert app.printed == []


def test_the_exit_codes_are_distinct() -> None:
    """A wrapper has to tell these apart, and apart from argparse's own 2."""
    codes = [EXIT_OK, EXIT_FATAL, EXIT_INTERRUPTED, EXIT_ITEM_FAILURES]
    assert len(set(codes)) == len(codes)
    assert 2 not in codes


# ----------------------------------------------------------------- logging
# _setup_logging is checked by capturing what it hands to logging.basicConfig.
# Asserting on the root logger instead would fight pytest's own log capture handler.


def captured_basic_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    **extra: Any,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_basic_config(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    cli_args: dict[str, Any] = {"verbose": False, "log_level": "INFO"}
    cli_args.update(extra)

    app: Any = AppBaseWithLogging.__new__(AppBaseWithLogging)
    app.prog = str(tmp_path / "testprog")
    app.cli_args = cli_args
    app._setup_logging()

    for handler in captured.get("handlers", []):
        handler.close()

    return captured


def handler_names(captured: dict[str, Any]) -> list[str]:
    return [type(h).__name__ for h in captured["handlers"]]


def test_the_log_file_is_the_only_destination_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    captured = captured_basic_config(monkeypatch, tmp_path)
    assert handler_names(captured) == ["FileHandler"]


def test_the_log_file_is_named_after_the_program(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    captured = captured_basic_config(monkeypatch, tmp_path)
    assert captured["handlers"][0].baseFilename == str(tmp_path / "testprog.log")


def test_log_to_stderr_adds_a_stream_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    captured = captured_basic_config(monkeypatch, tmp_path, log_to_stderr=True)
    assert handler_names(captured) == ["FileHandler", "StreamHandler"]


def test_log_to_stderr_keeps_the_file_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The console copy is additional: the log file is what you read after the run."""
    captured = captured_basic_config(monkeypatch, tmp_path, log_to_stderr=True)
    assert captured["handlers"][0].baseFilename == str(tmp_path / "testprog.log")


def test_the_stream_handler_writes_to_stderr_not_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """stdout carries the program's own output, so the log must not share it."""
    captured = captured_basic_config(monkeypatch, tmp_path, log_to_stderr=True)
    assert captured["handlers"][1].stream is sys.stderr
    assert captured["handlers"][1].stream is not sys.stdout


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("INFO", "INFO"),
        ("debug", "DEBUG"),
        (None, "WARNING"),
    ],
)
def test_the_log_level_is_normalised(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    given: str | None,
    expected: str,
) -> None:
    """A lower case level works, and an absent level falls back to WARNING."""
    captured = captured_basic_config(monkeypatch, tmp_path, log_level=given)
    assert captured["level"] == expected


def test_both_destinations_share_one_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    captured = captured_basic_config(monkeypatch, tmp_path, log_to_stderr=True)
    assert "%(levelname)s" in captured["format"]
    assert "%(message)s" in captured["format"]


# --------------------------------------------------------------- my_print
# --verbose promises progress output on stdout. It was lost when the print
# was removed while fixing a ruff T201 finding; these tests pin it back.


def print_app(**cli_args: Any) -> Any:
    app: Any = MyApp.__new__(MyApp)
    app.cli_args = dict(cli_args)
    return app


def test_my_print_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    print_app().my_print("progress line")
    assert capsys.readouterr().out.strip() == "progress line"


def test_my_print_writes_the_plain_message_without_log_decoration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_app().my_print("progress line")
    out = capsys.readouterr().out.strip()
    assert "INFO" not in out
    assert out == "progress line"


def test_my_print_also_logs_at_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="rl_scan_artifactory.my_app"):
        print_app().my_print("progress line")
    assert "progress line" in caplog.text


@pytest.mark.parametrize("log_to_stderr", [False, True])
def test_my_print_always_goes_to_stdout(
    capsys: pytest.CaptureFixture[str],
    log_to_stderr: bool,
) -> None:
    """The log's console copy is on stderr, so nothing has to be suppressed."""
    print_app(log_to_stderr=log_to_stderr).my_print("progress line")
    assert capsys.readouterr().out.strip() == "progress line"


# ---------------------------------------------------------- repository types
# A virtual repository stacks a local over a remote; it has no storage identity
# of its own to annotate, so it is skipped rather than failed one item at a time.


def repo_type_app(repo_type: str) -> tuple[Any, ArtifactoryRepoInfo]:
    app = make_app(repo_names=["r1"])
    info = ArtifactoryRepoInfo(
        name="r1",
        repo_type=repo_type,
        package_type="generic",
        layout="s",
    )
    return app, info


@pytest.mark.parametrize("repo_type", ["local", "remote", "LOCAL", "Remote"])
def test_a_writable_repository_type_is_processed(repo_type: str) -> None:
    _app, info = repo_type_app(repo_type)
    assert MyApp._is_unsupported_repo_type(info) is False


@pytest.mark.parametrize("repo_type", ["virtual", "VIRTUAL", "federated", "distribution"])
def test_an_unsupported_repository_type_is_skipped(repo_type: str) -> None:
    """A virtual repo has no storage identity to annotate; anything unknown is refused too."""
    _app, info = repo_type_app(repo_type)
    assert MyApp._is_unsupported_repo_type(info) is True


def test_a_remote_repository_is_processed_not_skipped() -> None:
    """A remote repo is addressed through its cache; that is not a reason to skip it."""
    _app, info = repo_type_app("remote")
    assert MyApp._is_unsupported_repo_type(info) is False


def test_an_empty_repository_type_is_not_a_type_problem() -> None:
    """An empty type means the configuration was never read, which the caller
    reports as 'does not exist' rather than as an unsupported type."""
    _app, info = repo_type_app("")
    assert MyApp._is_unsupported_repo_type(info) is False


# --------------------------------------------- one message per unreadable repo
# A repository whose configuration cannot be read used to produce two warnings
# saying the same thing: one from the lookup and one from the skip. The skip
# message is the one a user needs; the status the server gave stays at debug,
# where it still tells a 404 from a 403.


class FailingRepoLookup:
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message

    def json(self) -> Any:
        return {"errors": [{"status": self.status, "message": self.message}]}

    @property
    def status_code(self) -> int:
        return self.status


def repo_lookup(monkeypatch: pytest.MonkeyPatch, status: int, message: str) -> Any:
    from rl_scan_artifactory.artifactory_api import ArtifactoryApi

    api: Any = ArtifactoryApi.__new__(ArtifactoryApi)
    api.base_url = "https://artifactory.example.com"
    monkeypatch.setattr(api, "_request_get", lambda url: FailingRepoLookup(status, message))
    return api


def test_an_unreadable_repository_warns_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = repo_lookup(monkeypatch, 404, "The repository X was not found")

    with caplog.at_level(logging.WARNING):
        assert api.get_repo_info("X") == {}

    assert caplog.text == ""


def test_the_status_is_still_there_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """404 and 403 mean different things, and only the status says which."""
    api = repo_lookup(monkeypatch, 403, "Permission denied")

    with caplog.at_level(logging.DEBUG):
        api.get_repo_info("X")

    assert "403" in caplog.text
    assert "Permission denied" in caplog.text


# ------------------------------------------------- completing a stored report
# A report property that is a path, not a url, is completed with the portal it
# came from. Only a portal run can do that: a cli run has no portal, and it used
# to raise here, which cost the artifact. A cli run over a repository an earlier
# portal run had scanned hits exactly that.


class FakePortalApi:
    server = "test"


def processor_for(backend: str, *, portal: bool = True) -> Any:
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
        ArtifactoryFileProcessorCommon,
    )

    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.what_backend = backend
    proc.spectra_assure_api = FakePortalApi() if portal else None
    return proc


STORED_PATH = "group/abc/report/nmpjs.org/pkg/1.0/"
STORED_URL = "https://my.secure.software/test/reports/group/abc/report/nmpjs.org/pkg/1.0/"


def test_a_portal_run_completes_a_stored_path() -> None:
    got = MyApp._full_report_url(processor_for("portal"), STORED_PATH)
    assert got == f"https://my.secure.software/test/{STORED_PATH}"


def test_a_cli_run_leaves_a_stored_path_alone() -> None:
    """There is no portal to complete it with, and raising cost the artifact."""
    got = MyApp._full_report_url(processor_for("cli", portal=False), STORED_PATH)
    assert got == STORED_PATH


@pytest.mark.parametrize("backend", ["portal", "cli"])
def test_a_stored_url_is_never_touched(backend: str) -> None:
    proc = processor_for(backend, portal=backend == "portal")
    assert MyApp._full_report_url(proc, STORED_URL) == STORED_URL


def test_a_cli_run_does_not_ask_the_portal_for_anything() -> None:
    """The check is on the backend, not on whether the api happens to be set."""
    proc = processor_for("cli", portal=False)
    assert proc.spectra_assure_api is None

    MyApp._full_report_url(proc, STORED_PATH)  # must not raise


def test_the_report_base_still_refuses_to_guess_without_a_portal() -> None:
    """The guard stays: reaching it means a caller forgot to check the backend."""
    from rl_scan_artifactory.exceptions import SpectraAssureInvariantError

    proc = processor_for("portal", portal=False)
    with pytest.raises(SpectraAssureInvariantError, match="spectra_assure_api"):
        proc._portal_make_report_base()


def test_the_report_base_kept_its_docstring() -> None:
    """The assert to raise conversion had put the guard above it, so it was not one."""
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
        ArtifactoryFileProcessorCommon,
    )

    assert ArtifactoryFileProcessorCommon._portal_make_report_base.__doc__ is not None


# ------------------------------------- a failed report upload is one artifact
# It used to call sys.exit(101), so a dropped connection while uploading one
# report ended a run over thousands of artifacts. Everything the containment
# does was bypassed by that one line.


def upload_failure() -> Any:
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
        ArtifactoryFileProcessorCommon,
    )

    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.uri = "/mp4-box-encoding/-/mp4-box-encoding-1.4.1.tgz"
    proc.repo = ArtifactoryRepoInfo(
        name="nmpjs.org",
        repo_type="remote",
        package_type="npm",
        layout="s",
    )
    proc.cli_args = {"cli_reports_repo": "Spectra-Assure-Reports"}

    class FailingApi:
        def upload_file_to_artifactory(self, **kwargs: Any) -> Any:
            msg = "EOF occurred in violation of protocol"
            raise OSError(msg)

    proc.artifactory_api = FailingApi()
    return proc


def test_a_failed_report_upload_raises_rather_than_exiting() -> None:
    """Raising is what lets the per item containment record it and carry on."""
    from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction

    proc = upload_failure()

    with pytest.raises(SpectraAssureInvalidAction, match="cannot upload the report bundle"):
        proc._upload_the_report(purl="nmpjs.org/mp4-box-encoding@1.4.1", report_bundle_path="/tmp/x/reports.zip")


def test_a_failed_report_upload_does_not_end_the_process() -> None:
    proc = upload_failure()

    try:
        proc._upload_the_report(purl="p", report_bundle_path="/tmp/x/reports.zip")
    except SystemExit:  # pragma: no cover - the thing being guarded against
        pytest.fail("a failed report upload must not exit the process")
    except Exception:  # noqa: BLE001, S110
        pass


def test_the_failure_names_the_artifact_and_the_reason() -> None:
    from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction

    proc = upload_failure()

    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        proc._upload_the_report(purl="nmpjs.org/mp4-box-encoding@1.4.1", report_bundle_path="/tmp/x/reports.zip")

    message = str(excinfo.value)
    assert "Spectra-Assure-Reports" in message
    assert "EOF occurred in violation of protocol" in message
