# python3 ts=4space
"""The exit codes, end to end.

`main()` is small but it is the whole contract a pipeline sees: 0 for a clean
run, 101 for a bad invocation, 102 for a run that ended early, 103 for a run that
finished with items skipped. Nothing verified any of it before.

The two halves are deliberately different. A precondition failure is a bad
invocation and gets the message with no traceback; anything escaping the run
itself is unexpected, so it is logged with its traceback and still exits cleanly
rather than dumping one on the user.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory import main as module
from rl_scan_artifactory.constants import (
    EXIT_FATAL,
    EXIT_INTERRUPTED,
    EXIT_ITEM_FAILURES,
    EXIT_OK,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction


class FakeApp:
    def __init__(self, *, raises: BaseException | None = None, exit_code: int = EXIT_OK) -> None:
        self.raises = raises
        self.exit_code = exit_code
        self.printed: list[str] = []
        self.ran = False

    def run_all(self) -> None:
        self.ran = True
        if self.raises is not None:
            raise self.raises

    def my_print(self, msg: str) -> None:
        self.printed.append(msg)

    def get_exit_code(self) -> int:
        return self.exit_code


def wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app: FakeApp | None = None,
    args_raises: BaseException | None = None,
) -> FakeApp:
    instance = app if app is not None else FakeApp()

    def make_args() -> Any:
        if args_raises is not None:
            raise args_raises
        return object()

    monkeypatch.setattr(module, "MyArgs", make_args)
    monkeypatch.setattr(module, "MyApp", lambda args: instance)
    return instance


def exit_code(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> int:
    wire(monkeypatch, **kwargs)
    with pytest.raises(SystemExit) as excinfo:
        module.main()

    code: int = int(excinfo.value.code or 0)
    return code


# ------------------------------------------------------------ the four codes


def test_a_clean_run_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    assert exit_code(monkeypatch, app=FakeApp(exit_code=EXIT_OK)) == 0


def test_a_run_with_skipped_items_exits_103(monkeypatch: pytest.MonkeyPatch) -> None:
    """MyApp decides this; main only passes it on."""
    assert exit_code(monkeypatch, app=FakeApp(exit_code=EXIT_ITEM_FAILURES)) == 103


def test_a_bad_invocation_exits_101(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = SpectraAssureInvalidAction("missing mandatory setting(s): artifactory_token")
    assert exit_code(monkeypatch, args_raises=refusal) == 101


def test_an_interrupted_run_exits_102(monkeypatch: pytest.MonkeyPatch) -> None:
    assert exit_code(monkeypatch, app=FakeApp(raises=KeyboardInterrupt())) == 102


def test_a_run_that_raised_exits_102(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything escaping the run ended it early, which is the same outcome."""
    assert exit_code(monkeypatch, app=FakeApp(raises=RuntimeError("the portal went away"))) == 102


def test_the_four_codes_are_distinct() -> None:
    assert len({EXIT_OK, EXIT_FATAL, EXIT_INTERRUPTED, EXIT_ITEM_FAILURES}) == 4


# ------------------------------------------------------- what the user sees


def test_a_bad_invocation_says_what_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """On stderr, because stdout carries the program's own output."""
    refusal = SpectraAssureInvalidAction("missing mandatory setting(s): artifactory_token")
    exit_code(monkeypatch, args_raises=refusal)

    captured = capsys.readouterr()
    assert "artifactory_token" in captured.err
    assert captured.out == ""


def test_a_bad_invocation_never_starts_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp()
    wire(monkeypatch, app=app, args_raises=SpectraAssureInvalidAction("nope"))

    with pytest.raises(SystemExit):
        module.main()

    assert app.ran is False


def test_an_interruption_is_reported_to_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp(raises=KeyboardInterrupt())
    exit_code(monkeypatch, app=app)

    assert any("interrupted by the user" in line for line in app.printed)


def test_a_failed_run_names_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp(raises=RuntimeError("the portal went away"))
    exit_code(monkeypatch, app=app)

    printed = " ".join(app.printed)
    assert "RuntimeError" in printed
    assert "the portal went away" in printed


def test_a_failed_run_is_logged_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected, so the traceback goes in the log rather than at the user."""
    with caplog.at_level(logging.ERROR):
        exit_code(monkeypatch, app=FakeApp(raises=RuntimeError("boom")))

    assert "Traceback" in caplog.text


def test_an_interruption_is_not_logged_as_an_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ctrl-C is a thing the user did, not a fault to investigate."""
    with caplog.at_level(logging.WARNING):
        exit_code(monkeypatch, app=FakeApp(raises=KeyboardInterrupt()))

    assert "Traceback" not in caplog.text


# ------------------------------------------------------ the noisy libraries


def test_the_http_libraries_are_quietened(monkeypatch: pytest.MonkeyPatch) -> None:
    """requests and urllib3 log every connection at info, which buries the run."""
    for name in ("requests", "urllib3"):
        logging.getLogger(name).setLevel(logging.DEBUG)
        logging.getLogger(name).propagate = True

    exit_code(monkeypatch)

    for name in ("requests", "urllib3"):
        assert logging.getLogger(name).level == logging.CRITICAL
        assert logging.getLogger(name).propagate is False
