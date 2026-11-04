# python3 ts=4space
"""The local rl-secure backend: is it usable, and what does it put on a command line.

The preflight exists because both of these used to be found out per artifact, in
the scanner's constructor, which runs *after* that artifact has been downloaded.
A broken rl-secure installation therefore cost one download per item in the
repository before it complained.

Only subprocess.run is faked; the command construction is the real code.
"""

import inspect
import logging
import re
import subprocess
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction
from rl_scan_artifactory.my_app import MyApp
from rl_scan_artifactory.py_cli_scan import scan_cli_local
from rl_scan_artifactory.py_cli_scan.scan_cli_local import ScanCliLocal

RLSECURE = "/opt/rl"
STORE = "/opt/rl-store"
PURL = "my-repo/mypkg@1.0"


class FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


class Recorder:
    """subprocess.run, returning a code per call in order."""

    def __init__(self, *codes: int, stderr: str = "") -> None:
        self.codes = list(codes) or [0]
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> FakeCompletedProcess:
        self.commands.append(list(command))
        code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
        return FakeCompletedProcess(code, stderr=self.stderr)


def record(monkeypatch: pytest.MonkeyPatch, *codes: int, stderr: str = "") -> Recorder:
    rec = Recorder(*codes, stderr=stderr)
    monkeypatch.setattr(subprocess, "run", rec)
    return rec


# ------------------------------------------------------------- the preflight


def test_a_usable_installation_gives_no_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 0, 0)
    assert ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE) is None


def test_it_asks_for_the_version_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """rl-secure cannot be installed without a licence, so a version that comes
    back at all proves the binary is present, runnable and licensed."""
    rec = record(monkeypatch, 0, 0)
    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert rec.commands[0] == [f"{RLSECURE}/rl-secure", "--version"]


def test_it_then_asks_the_store_to_list_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an initialised rl-store nothing can be analysed."""
    rec = record(monkeypatch, 0, 0)
    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert rec.commands[1] == [f"{RLSECURE}/rl-secure", "list", "--no-color", f"--rl-store={STORE}/.rl-secure"]


def test_the_version_check_needs_no_store_and_no_purl(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = record(monkeypatch, 0, 0)
    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert not any("--rl-store" in argument for argument in rec.commands[0])
    assert not any("--purl" in argument for argument in rec.commands[0])


def test_the_list_check_needs_a_store_but_no_purl(monkeypatch: pytest.MonkeyPatch) -> None:
    """'list' asks about the store itself, not about one package in it."""
    rec = record(monkeypatch, 0, 0)
    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert any("--rl-store" in argument for argument in rec.commands[1])
    assert not any("--purl" in argument for argument in rec.commands[1])


def test_an_unrunnable_rl_secure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 127)
    reason = ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert reason is not None
    assert RLSECURE in reason


def test_an_unrunnable_rl_secure_stops_before_the_store_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = record(monkeypatch, 127)
    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert len(rec.commands) == 1


def test_an_uninitialised_store_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 0, 1)
    reason = ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert reason is not None
    assert STORE in reason
    assert "rl-secure init" in reason


def test_no_store_at_all_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 0)
    reason = ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=None)

    assert reason is not None
    assert "--cli-rlstore-path" in reason


def test_the_failure_reason_from_rl_secure_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    record(monkeypatch, 127, stderr="rl-secure: command not found")

    with caplog.at_level(logging.ERROR):
        ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)

    assert "command not found" in caplog.text


# ------------------------------------------------------- when it is run


def app(**cli_args: Any) -> Any:
    instance: Any = MyApp.__new__(MyApp)
    instance.cli_args = dict(cli_args)
    return instance


def test_a_cli_run_is_refused_when_rl_secure_is_not_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record(monkeypatch, 127)

    with pytest.raises(SpectraAssureInvalidAction):
        app(cli=True, cli_rlsecure_path=RLSECURE, cli_rlstore_path=STORE)._verify_cli_usable()


def test_a_cli_run_proceeds_when_it_is_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 0, 0)
    app(cli=True, cli_rlsecure_path=RLSECURE, cli_rlstore_path=STORE)._verify_cli_usable()


def test_a_portal_run_does_not_check_rl_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = record(monkeypatch, 127)
    app(portal=True)._verify_cli_usable()

    assert rec.commands == []


def test_a_cli_docker_run_does_not_check_the_local_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The docker backend brings its own scanner; checking here would mean a pull."""
    rec = record(monkeypatch, 127)
    app(cli=True, cli_docker=True)._verify_cli_usable()

    assert rec.commands == []


# --------------------------------------------- what each command is given


def local(**kwargs: Any) -> Any:
    scan: Any = ScanCliLocal.__new__(ScanCliLocal)
    scan.where = RLSECURE
    scan.store = STORE
    scan.purl = PURL

    for key, value in kwargs.items():
        setattr(scan, key, value)

    return scan


@pytest.mark.parametrize("what", ["version", "license"])
def test_a_command_about_the_installation_gets_neither_store_nor_purl(
    monkeypatch: pytest.MonkeyPatch,
    what: str,
) -> None:
    rec = record(monkeypatch, 0)
    local()._do_command_local(what=what, command=[what])

    assert not any("--rl-store" in argument for argument in rec.commands[0])
    assert not any("--purl" in argument for argument in rec.commands[0])


@pytest.mark.parametrize("what", ["scan", "status", "report", "sync"])
def test_a_command_about_one_package_gets_both(
    monkeypatch: pytest.MonkeyPatch,
    what: str,
) -> None:
    rec = record(monkeypatch, 0)
    local()._do_command_local(what=what, command=[what])

    assert f"--rl-store={STORE}/.rl-secure" in rec.commands[0]
    assert f"--purl={PURL}" in rec.commands[0]


def test_a_store_that_already_names_the_directory_is_not_doubled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = record(monkeypatch, 0)
    local(store=f"{STORE}/.rl-secure")._do_command_local(what="scan", command=["scan"])

    assert f"--rl-store={STORE}/.rl-secure" in rec.commands[0]


def test_a_command_that_needs_a_store_says_so_when_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record(monkeypatch, 0)

    with pytest.raises(RuntimeError, match="rl-store"):
        local(store=None)._do_command_local(what="scan", command=["scan"])


def test_a_command_that_needs_no_store_runs_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The version check has to work before a store has ever been set up."""
    rec = record(monkeypatch, 0)
    local(store=None)._do_command_local(what="version", command=["--version"])

    assert rec.commands[0] == [f"{RLSECURE}/rl-secure", "--version"]


def test_an_unknown_base_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    record(monkeypatch, 0)

    with pytest.raises(RuntimeError, match="base must be one of"):
        local()._do_command_local(what="scan", command=["scan"], base="something-else")


# --------------------------------------------- output options (R12.6.0.2)

# Per command, which of the two output options its page on
# docs.secure.software/cli/commands lists. Both only shape output for a terminal
# (colour, progress bars), so each command that has one gets it; an option a
# command does not know may make it fail, so the others stay off.
OUTPUT_OPTIONS: dict[str, set[str]] = {
    "version": set(),
    "list": {"--no-color"},
    "license": {"--no-color"},  # license status
    "status": {"--no-color"},  # status --return-status
    "exists": {"--no-color"},  # status
    "scan": {"--no-tracking"},
    "sync": {"--no-tracking"},
    "report": {"--no-tracking"},
    "pack": {"--no-tracking"},  # rl-safe has no page there: kept as it is
}
ALL_OUTPUT_OPTIONS = {"--no-color", "--no-tracking"}


def every_command(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Run each command the backend has, and record what it was given."""
    seen: dict[str, list[str]] = {}

    def fake(self: Any, *, what: str, command: list[str], **kwargs: Any) -> int:
        seen[what] = command
        return 0

    monkeypatch.setattr(ScanCliLocal, "_do_command", fake)

    ScanCliLocal.preflight(rlsecure_path=RLSECURE, store=STORE)
    scan = local(reports_list=["sarif"], temp_dir_path="/tmp/scan")
    scan._licence_status()
    scan._scan_file(file_path="/tmp/mypkg-1.0.tgz")
    scan._sync_purl()
    scan._status_purl()
    scan._exists_purl()
    scan._reports_purl()
    scan._rl_safe_purl()

    return seen


def test_every_command_the_backend_runs_is_in_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command added later must be looked up in the docs and added above."""
    in_source = set(re.findall(r'what="([a-z_]+)"', inspect.getsource(scan_cli_local)))

    assert in_source == set(OUTPUT_OPTIONS)
    assert set(every_command(monkeypatch)) == set(OUTPUT_OPTIONS)


@pytest.mark.parametrize("what", sorted(OUTPUT_OPTIONS))
def test_each_command_gets_the_output_options_it_supports(
    monkeypatch: pytest.MonkeyPatch,
    what: str,
) -> None:
    command = every_command(monkeypatch)[what]

    assert ALL_OUTPUT_OPTIONS & set(command) == OUTPUT_OPTIONS[what]
