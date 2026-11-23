# python3 ts=4space
"""The cli backend: what it puts on a command line, and what it must not.

rl-secure runs as a subprocess, so every argument this builds is visible in `ps`
to every user on the host for as long as the command runs. The license and the
site key therefore travel in the environment of the child process and never as
an argument.

Only subprocess.run is faked. The command construction, the environment handling
and the result bookkeeping are the real code.
"""

import logging
import subprocess
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.py_cli_scan.scan_cli_docker import ScanCliDocker

LICENSE = "SECRET-ENCODED-LICENSE"
SITE_KEY = "SECRET-SITE-KEY"
PURL = "my-repo/mypkg@1.0"


class FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    """Stands in for subprocess.run and records every call."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict[str, Any]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> FakeCompletedProcess:
        self.calls.append({"command": command, **kwargs})
        return FakeCompletedProcess(self.returncode, stderr=self.stderr)

    @property
    def command(self) -> list[str]:
        return list(self.calls[-1]["command"])

    @property
    def env(self) -> dict[str, str] | None:
        value: dict[str, str] | None = self.calls[-1].get("env")
        return value


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    return rec


def scanner(tmp_path: Any, **kwargs: Any) -> Any:
    scan: Any = ScanCliDocker.__new__(ScanCliDocker)

    scan.RLSECURE_ENCODED_LICENSE = LICENSE
    scan.RLSECURE_SITE_KEY = SITE_KEY
    scan.docker_image_name = "reversinglabs/rl-scanner:latest"
    scan.purl = PURL
    scan.reports_list = ["rl-json", "rl-html"]
    scan.temp_dir_path = str(tmp_path)
    scan.store = None
    scan.user_id = -1
    scan.group_id = -1

    for key, value in kwargs.items():
        setattr(scan, key, value)

    return scan


def run_scan(tmp_path: Any, **kwargs: Any) -> Any:
    scan = scanner(tmp_path, **kwargs)
    scan._do_docker_rl_scan(file_path=str(tmp_path / "artifact.tgz"))
    return scan


# --------------------------------------------------------------- no secrets


def test_the_license_is_not_an_argument(recorder: Recorder, tmp_path: Any) -> None:
    """An argv element is visible in ps to every user on the host."""
    run_scan(tmp_path)
    assert not any(LICENSE in argument for argument in recorder.command)


def test_the_site_key_is_not_an_argument(recorder: Recorder, tmp_path: Any) -> None:
    run_scan(tmp_path)
    assert not any(SITE_KEY in argument for argument in recorder.command)


def test_the_env_flags_name_the_variables_without_a_value(
    recorder: Recorder,
    tmp_path: Any,
) -> None:
    """--env=NAME tells docker to take the value from our own environment."""
    run_scan(tmp_path)
    assert "--env=RLSECURE_ENCODED_LICENSE" in recorder.command
    assert "--env=RLSECURE_SITE_KEY" in recorder.command


def test_the_secrets_reach_the_child_through_the_environment(
    recorder: Recorder,
    tmp_path: Any,
) -> None:
    run_scan(tmp_path)

    env = recorder.env
    assert env is not None
    assert env["RLSECURE_ENCODED_LICENSE"] == LICENSE
    assert env["RLSECURE_SITE_KEY"] == SITE_KEY


def test_the_child_keeps_the_rest_of_our_environment(
    recorder: Recorder,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker itself needs PATH and its own settings."""
    monkeypatch.setenv("SOME_UNRELATED_SETTING", "keep me")
    run_scan(tmp_path)

    env = recorder.env
    assert env is not None
    assert env["SOME_UNRELATED_SETTING"] == "keep me"


# ------------------------------------------------------------- the command


def test_the_command_is_a_list_and_no_shell_is_used(recorder: Recorder, tmp_path: Any) -> None:
    """A list plus no shell means nothing in a file name or purl is read as syntax."""
    run_scan(tmp_path)

    assert isinstance(recorder.calls[-1]["command"], list)
    assert recorder.calls[-1].get("shell") in (None, False)


def test_the_output_is_captured(recorder: Recorder, tmp_path: Any) -> None:
    run_scan(tmp_path)
    assert recorder.calls[-1]["capture_output"] is True


def test_a_non_zero_exit_is_not_raised_by_subprocess(recorder: Recorder, tmp_path: Any) -> None:
    """check=False: the return code is handled here, not by an exception."""
    run_scan(tmp_path)
    assert recorder.calls[-1]["check"] is False


@pytest.mark.parametrize(
    "expected",
    ["docker", "run", "--rm", "--report-path=/report", "--replace", "rl-scan"],
)
def test_the_scan_command_has_its_fixed_parts(
    recorder: Recorder,
    tmp_path: Any,
    expected: str,
) -> None:
    run_scan(tmp_path)
    assert expected in recorder.command


def test_the_purl_and_the_reports_are_passed(recorder: Recorder, tmp_path: Any) -> None:
    run_scan(tmp_path)
    assert f"--purl={PURL}" in recorder.command
    assert "--report-format=rl-json,rl-html" in recorder.command


def test_a_store_adds_a_volume_and_a_flag(recorder: Recorder, tmp_path: Any) -> None:
    run_scan(tmp_path, store="/opt/rl-store")
    assert "--volume=/opt/rl-store:/rl-store" in recorder.command
    assert "--rl-store=/rl-store" in recorder.command


def test_no_store_adds_neither(recorder: Recorder, tmp_path: Any) -> None:
    run_scan(tmp_path)
    assert not any("rl-store" in argument for argument in recorder.command)


# ------------------------------------------------------------ the results


def test_a_failure_is_logged_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without this a failed scan is silent at the default log level."""
    rec = Recorder(returncode=2, stderr="rl-secure: license expired")
    monkeypatch.setattr(subprocess, "run", rec)

    with caplog.at_level(logging.ERROR):
        scan = scanner(tmp_path)
        code = scan._do_docker_rl_scan(file_path=str(tmp_path / "artifact.tgz"))

    assert code == 2
    assert "license expired" in caplog.text


def test_a_failure_message_does_not_echo_the_license(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rec = Recorder(returncode=2, stderr="something went wrong")
    monkeypatch.setattr(subprocess, "run", rec)

    with caplog.at_level(logging.DEBUG):
        scan = scanner(tmp_path)
        scan._do_docker_rl_scan(file_path=str(tmp_path / "artifact.tgz"))

    assert LICENSE not in caplog.text
    assert SITE_KEY not in caplog.text


def test_a_success_logs_no_error(
    recorder: Recorder,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        run_scan(tmp_path)
    assert caplog.text == ""


# ----------------------------------------------- which codes are an answer
# rl-secure status answers with the scan result, and "this purl has not been
# scanned yet" is one of its answers. Logging that as an error says nothing
# useful and buries the failures that do matter.


def run_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, **kwargs: Any) -> Recorder:
    rec = Recorder(returncode=kwargs.pop("returncode", 0), stderr=kwargs.pop("stderr", ""))
    monkeypatch.setattr(subprocess, "run", rec)

    scan = scanner(tmp_path)
    scan._do_command(what="probe", command=["true"], **kwargs)
    return rec


@pytest.mark.parametrize("code", [1, 2, 127])
def test_a_code_outside_the_answers_is_logged_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    code: int,
) -> None:
    with caplog.at_level(logging.ERROR):
        run_with(monkeypatch, tmp_path, returncode=code, stderr="the reason")
    assert "the reason" in caplog.text


@pytest.mark.parametrize("code", [0, 1])
def test_a_declared_answer_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    code: int,
) -> None:
    """status --return-status answers 0 for pass and 1 for fail; neither is a failure."""
    with caplog.at_level(logging.ERROR):
        run_with(monkeypatch, tmp_path, returncode=code, answer_codes=(0, 1))
    assert caplog.text == ""


@pytest.mark.parametrize("code", [0, 1, 2, 127])
def test_no_answer_codes_means_the_caller_decides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    code: int,
) -> None:
    """'has this purl been scanned' uses the code as its answer, whatever it is."""
    with caplog.at_level(logging.ERROR):
        run_with(monkeypatch, tmp_path, returncode=code, answer_codes=None)
    assert caplog.text == ""


def test_the_output_is_still_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """This is what the removed results dict was really for."""
    with caplog.at_level(logging.DEBUG):
        run_with(monkeypatch, tmp_path, returncode=0, stderr="some detail")
    assert "probe stderr some detail" in caplog.text


# ------------------------------------------- the image answers with a verdict
# Unlike the local rl-secure, where a scan returns 0 and the verdict comes from a
# separate status call, the rl-scanner image returns the verdict itself: 0 pass,
# 1 fail. Logging a 'fail' as a command failure put an ERROR in the log for every
# artifact that did not pass.


@pytest.mark.parametrize("code", [0, 1])
def test_a_verdict_is_not_logged_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    code: int,
) -> None:
    rec = Recorder(returncode=code)
    monkeypatch.setattr(subprocess, "run", rec)

    with caplog.at_level(logging.ERROR):
        scan = scanner(tmp_path)
        result = scan._do_docker_rl_scan(file_path=str(tmp_path / "artifact.tgz"))

    assert result == code
    assert caplog.text == ""


@pytest.mark.parametrize("code", [101, 2, 127])
def test_anything_else_is_still_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    code: int,
) -> None:
    """Only 0 and 1 are verdicts; 101 is the image's own 'something went wrong'."""
    rec = Recorder(returncode=code, stderr="the reason")
    monkeypatch.setattr(subprocess, "run", rec)

    with caplog.at_level(logging.ERROR):
        scan = scanner(tmp_path)
        scan._do_docker_rl_scan(file_path=str(tmp_path / "artifact.tgz"))

    assert "the reason" in caplog.text


def test_the_local_scanner_does_not_share_this() -> None:
    """A local rl-secure scan returns 0; its verdict comes from `status`."""
    from rl_scan_artifactory.constants import DOCKER_SCAN_ANSWER_CODES

    assert DOCKER_SCAN_ANSWER_CODES == (0, 1)
