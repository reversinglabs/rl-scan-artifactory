# python3 ts=4space
"""Waiting for a portal scan, and knowing when not to.

A portal run polled seven artifacts ninety times each for a scan of a version the
portal had already said does not exist, then timed out. At twenty seconds a poll
that is half an hour per artifact spent on a settled answer.

A version uploaded moments ago can take a little while to become visible, so a
few "no such version" answers in a row are tolerated. After that the answer is
settled: the portal does not have it, and no amount of waiting will produce a
scan of it.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.constants import (
    PORTAL_STATUS_ABSENT,
    PORTAL_STATUS_ABSENT_LIMIT,
    PROCESS_FILE_TIMEOUT,
)

PURL = "nmpjs.org/next-event@1.0.0"


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty seconds a poll is the point; these tests only count the polls."""
    import time

    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def waiter(answers: list[int], *, succeeds_at: int | None = None) -> Any:
    """A processor whose portal answers with these status codes, in order."""
    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)

    proc.what_backend = "portal"
    proc.max_time = 7200
    proc.uri = "/next-event/-/next-event-1.0.0.tgz"
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo()
    proc.purl_info.project = "nmpjs.org"
    proc.purl_info.package = "next-event"
    proc.purl_info.version = "1.0.0"
    proc.file = type("F", (), {"repo": ArtifactoryRepoInfo("nmpjs.org", "remote", "npm", "s")})()

    proc.polls = 0

    def one() -> tuple[str | None, str | None, int]:
        proc.polls += 1
        if succeeds_at is not None and proc.polls >= succeeds_at:
            return "pass", "https://reports.example/x", 200
        return None, None, answers[min(proc.polls - 1, len(answers) - 1)]

    proc._get_purl_scan_status_one = one
    proc._update_artifactory_item_with_scan_status = lambda **kwargs: None
    return proc


# ------------------------------------------------ a version that is not there


def test_a_run_of_absent_answers_stops_the_wait() -> None:
    proc = waiter([PORTAL_STATUS_ABSENT])
    proc._wait_for_scan_status_one_portal()

    assert proc.polls == PORTAL_STATUS_ABSENT_LIMIT


def test_the_absent_case_is_told_apart_from_a_timeout() -> None:
    """None says the thing being waited for cannot arrive, so a caller that can
    upload should do that instead of waiting again. False would have looked like
    an ordinary timeout."""
    proc = waiter([PORTAL_STATUS_ABSENT])
    completed = proc._wait_for_scan_status_one_portal()

    assert completed is None
    assert proc.processing_info.status == PROCESS_FILE_TIMEOUT
    assert proc.processing_info.purl == PURL


def test_an_ordinary_timeout_is_still_false() -> None:
    proc = waiter([500])
    proc.max_time = 60

    assert proc._wait_for_scan_status_one_portal() is False


def test_the_warning_says_the_portal_has_no_such_version(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        waiter([PORTAL_STATUS_ABSENT])._wait_for_scan_status_one_portal()

    assert "the portal has no version" in caplog.text
    assert "nmpjs.org" in caplog.text
    assert "next-event" in caplog.text


def test_it_does_not_also_claim_a_timeout(caplog: pytest.LogCaptureFixture) -> None:
    """Two warnings for one item, one of them wrong, is worse than one."""
    with caplog.at_level(logging.WARNING):
        waiter([PORTAL_STATUS_ABSENT])._wait_for_scan_status_one_portal()

    assert "timeout reached" not in caplog.text


# ------------------------------------------------ everything else still waits


def test_a_scan_that_is_not_finished_is_waited_for() -> None:
    """200 with no verdict yet: the ordinary case, and it must keep polling."""
    proc = waiter([200], succeeds_at=5)
    completed = proc._wait_for_scan_status_one_portal()

    assert completed is True
    assert proc.polls == 5


def test_a_server_error_does_not_stop_the_wait() -> None:
    proc = waiter([500], succeeds_at=10)
    proc._wait_for_scan_status_one_portal()

    assert proc.polls == 10


def test_an_occasional_absent_answer_does_not_stop_the_wait() -> None:
    """Only a run of them settles it; one in the middle is not an answer."""
    answers = [PORTAL_STATUS_ABSENT, 500, PORTAL_STATUS_ABSENT, 200, PORTAL_STATUS_ABSENT, 500]
    proc = waiter(answers, succeeds_at=7)
    proc._wait_for_scan_status_one_portal()

    assert proc.polls == 7


def test_the_counter_resets_on_any_other_answer() -> None:
    """Two absent, something else, two absent again: still not a run of three."""
    answers = [PORTAL_STATUS_ABSENT, PORTAL_STATUS_ABSENT, 500, PORTAL_STATUS_ABSENT, PORTAL_STATUS_ABSENT]
    proc = waiter(answers, succeeds_at=6)
    proc._wait_for_scan_status_one_portal()

    assert proc.polls == 6


def test_a_timeout_with_no_absent_answers_still_says_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc = waiter([500])
    proc.max_time = 60

    with caplog.at_level(logging.WARNING):
        proc._wait_for_scan_status_one_portal()

    assert "timeout reached" in caplog.text


# ------------------------------- uploading what the portal turns out not to have
# RL.progress does not record which backend wrote it, so a `scanned` written by a
# cli run made a portal run believe the artifact was already there. It then waited
# for a scan of a version the portal had never seen. The portal is the only thing
# that knows, and once it has said no three times the artifact has to be uploaded.


def portal_processor(waits: list[bool | None], *, upload_ok: bool = True) -> Any:
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_default import (
        ArtifactoryFileProcessorDefault,
    )

    proc: Any = ArtifactoryFileProcessorDefault.__new__(ArtifactoryFileProcessorDefault)
    proc.uri = "/next-event/-/next-event-1.0.0.tgz"
    proc.processing_info = ProcessingInfo()
    proc.file = type("F", (), {"repo": ArtifactoryRepoInfo("nmpjs.org", "remote", "npm", "s")})()

    proc.waits = list(waits)
    proc.uploads = 0

    def wait() -> bool | None:
        answer: bool | None = proc.waits.pop(0)
        return answer

    def upload() -> bool:
        proc.uploads += 1
        return upload_ok

    proc._wait_for_scan_status_one_portal = wait
    proc._file_download_upload_common = upload
    return proc


def test_a_finished_scan_needs_no_upload() -> None:
    proc = portal_processor([True])
    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is True
    assert proc.uploads == 0


def test_an_ordinary_timeout_needs_no_upload() -> None:
    """It is there and not finished; a later run picks it up from RL.progress."""
    proc = portal_processor([False])

    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is False
    assert proc.uploads == 0


def test_a_version_the_portal_does_not_have_is_uploaded() -> None:
    proc = portal_processor([None, True])

    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is True
    assert proc.uploads == 1


def test_after_uploading_it_waits_again() -> None:
    proc = portal_processor([None, False])

    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is False
    assert proc.uploads == 1
    assert proc.waits == []


def test_a_failed_upload_stops_there() -> None:
    proc = portal_processor([None], upload_ok=False)

    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is True
    assert proc.uploads == 1


def test_it_uploads_at_most_once() -> None:
    """If the portal still has no such version after an upload, stop rather than loop."""
    proc = portal_processor([None, None])

    assert proc._wait_then_upload_if_the_portal_has_no_such_version() is False
    assert proc.uploads == 1


def test_the_upload_is_announced_with_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        portal_processor([None, True])._wait_then_upload_if_the_portal_has_no_such_version()

    assert "uploading it now" in caplog.text
    assert "nmpjs.org" in caplog.text
