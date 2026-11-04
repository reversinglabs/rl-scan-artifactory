# python3 ts=4space
"""Syncing without a download, and checking afterwards that it was the right bytes.

A sync re-analyses what the store already holds - a newer engine, or a changed
policy, giving a different verdict on the same bytes - so the artifact itself is
not needed. Deciding that before the download is the point: it used to be decided
after, so a sync run fetched every artifact and then ignored it.

The digest is checked *after* the sync, from the rl-json report the sync produced
anyway. A matching digest, which is the ordinary case, costs nothing extra; a
mismatch costs one sync that is then followed by a real scan.
"""

import json
import pathlib
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.constants import (
    REPORT_FILE_RL_JSON,
    REPORT_FORMAT_RL_JSON,
)
from rl_scan_artifactory.py_cli_scan.report_hashes import (
    digest_from_hashes,
    digest_from_report_data,
    digest_from_report_file,
)
from rl_scan_artifactory.py_cli_scan.scan_cli_base import ScanCliBase

DIGEST = "858399ee9ee49e15a78c7018dbf0dd73dba8337d6f0adb841896ba553c9a646c"

SAMPLE_HASHES: list[list[str]] = [
    ["md5", "3b4e8f0f7cb8b32f85b60abed701ba0b"],
    ["sha1", "9da4e411e0ca62fc452cb91a3b33c7c1621f746d"],
    ["sha256", DIGEST],
    ["sha512", "599b0311" + "0" * 120],
]


def report(hashes: Any = None, *, schema: int = 3) -> dict[str, Any]:
    """The shape of a real rl-json report, cut down to what is read."""
    return {
        "schema": schema,
        "report": {
            "info": {"file": {"name": "putty.msi", "hashes": SAMPLE_HASHES if hashes is None else hashes}},
            "metadata": {
                # each component carries its own hashes; these are not the answer
                "41daa4af-6fd5-59e7-9786-5b1d214eb3ec": {"hashes": [["sha256", "c" * 64]]},
            },
        },
    }


def write_report(tmp_path: pathlib.Path, data: Any) -> str:
    target = tmp_path / REPORT_FILE_RL_JSON
    target.write_text(json.dumps(data), encoding="utf-8")
    return str(target)


# ------------------------------------------------------- picking one hash


def test_the_sha256_is_picked_out_of_the_list() -> None:
    assert digest_from_hashes(SAMPLE_HASHES) == DIGEST


def test_another_type_can_be_asked_for() -> None:
    assert digest_from_hashes(SAMPLE_HASHES, digest_type="md5") == "3b4e8f0f7cb8b32f85b60abed701ba0b"


def test_a_type_that_is_not_there_gives_none() -> None:
    assert digest_from_hashes([["md5", "x"]]) is None


@pytest.mark.parametrize("malformed", [[], ["sha256"], "not-a-list", None, 42])
def test_a_malformed_entry_is_skipped(malformed: Any) -> None:
    assert digest_from_hashes([malformed, ["sha256", DIGEST]]) == DIGEST


@pytest.mark.parametrize("not_a_list", [None, {}, "", 7])
def test_hashes_that_are_not_a_list_give_none(not_a_list: Any) -> None:
    assert digest_from_hashes(not_a_list) is None


# ------------------------------------------------- finding it in the report


def test_the_digest_comes_from_the_scanned_file() -> None:
    assert digest_from_report_data(report()) == DIGEST


def test_a_component_hash_is_not_mistaken_for_the_answer() -> None:
    """report.metadata.components each have hashes; only report.info.file counts."""
    data = report(hashes=[])
    assert digest_from_report_data(data) is None


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"report": {}},
        {"report": {"info": {}}},
        {"report": {"info": {"file": {}}}},
        None,
        [],
    ],
)
def test_a_missing_path_gives_none(data: Any) -> None:
    """None means unknown, never "different": the caller must do the full work."""
    assert digest_from_report_data(data) is None


def test_an_unexpected_schema_still_reads_but_warns(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        assert digest_from_report_data(report(schema=4)) == DIGEST
    assert "schema" in caplog.text


# ------------------------------------------------------------- from a file


def test_reading_it_from_a_report_file(tmp_path: pathlib.Path) -> None:
    assert digest_from_report_file(write_report(tmp_path, report())) == DIGEST


def test_a_missing_report_file_gives_none(tmp_path: pathlib.Path) -> None:
    assert digest_from_report_file(str(tmp_path / "absent.json")) is None


def test_an_unreadable_report_gives_none(tmp_path: pathlib.Path) -> None:
    target = tmp_path / REPORT_FILE_RL_JSON
    target.write_text("{not json", encoding="utf-8")
    assert digest_from_report_file(str(target)) is None


def test_the_real_sample_report_is_read(tmp_path: pathlib.Path) -> None:
    """The shape above is taken from a real report; this asserts it stays real."""
    data = report()
    path = write_report(tmp_path, data)

    assert digest_from_report_file(path) == DIGEST
    assert len(data["report"]["info"]["file"]["hashes"]) == 4


# --------------------------------------------------- rl-json is always made


def scanner(reports_list: list[str]) -> Any:
    scan: Any = ScanCliBase.__new__(ScanCliBase)
    scan.reports_list = []
    scan.rl_json_was_requested = True
    scan.set_report_list(reports_list)
    return scan


@pytest.mark.parametrize("asked", [["rl-html"], ["sarif", "spdx"], ["cyclonedx"]])
def test_rl_json_is_added_when_not_asked_for(asked: list[str]) -> None:
    """It is how the stored sha256 is read back."""
    scan = scanner(asked)
    assert REPORT_FORMAT_RL_JSON in scan.reports_list
    assert scan.rl_json_was_requested is False


def test_what_was_asked_for_is_still_generated() -> None:
    scan = scanner(["rl-html", "sarif"])
    assert "rl-html" in scan.reports_list
    assert "sarif" in scan.reports_list


def test_asking_for_rl_json_is_remembered() -> None:
    scan = scanner(["rl-html", REPORT_FORMAT_RL_JSON])
    assert scan.rl_json_was_requested is True
    assert scan.reports_list.count(REPORT_FORMAT_RL_JSON) == 1


def test_all_covers_rl_json() -> None:
    scan = scanner(["all"])
    assert scan.reports_list == ["all"]
    assert scan.rl_json_was_requested is True


def test_the_report_path_is_inside_the_temp_dir(tmp_path: pathlib.Path) -> None:
    scan = scanner(["rl-html"])
    scan.temp_dir_path = str(tmp_path)
    assert scan.get_rl_json_report_path() == str(tmp_path / REPORT_FILE_RL_JSON)


# ------------------------------------------- deciding to sync without a download


def processor(**cli_args: Any) -> Any:
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
        ArtifactoryFileProcessorCommon,
        PurlInfo,
    )

    from .conftest import make_file

    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.what_backend = "cli"
    proc.p_type = "pypi"
    proc.need_sync_datetime = False
    proc.cli_sync_was_stale = False
    proc.file = make_file(uri="/a/mypkg-1.0.whl", package_type="pypi")
    proc.file.sha2 = DIGEST

    proc.purl_info = PurlInfo()
    proc.purl_info.project = "my-repo"
    proc.purl_info.package = "mypkg"
    proc.purl_info.version = "1.0"

    defaults: dict[str, Any] = {
        "cli_rlsecure_path": "/opt/rl",
        "cli_rlstore_path": "/opt/rl-store",
    }
    defaults.update(cli_args)
    proc.cli_args = defaults
    return proc


def in_store(monkeypatch: pytest.MonkeyPatch, answer: bool) -> None:
    from rl_scan_artifactory.py_cli_scan.scan_cli_local import ScanCliLocal

    monkeypatch.setattr(
        ScanCliLocal,
        "purl_in_store",
        staticmethod(lambda **kwargs: answer),
    )


def test_a_sync_run_with_the_purl_in_store_needs_no_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_store(monkeypatch, True)
    assert processor(sync=True).cli_can_sync_without_download() is True


def test_a_sync_run_without_the_purl_in_store_must_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fall back to a normal scan and report; a first run still works."""
    in_store(monkeypatch, False)
    assert processor(sync=True).cli_can_sync_without_download() is False


def test_without_sync_there_is_nothing_to_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    in_store(monkeypatch, True)
    assert processor().cli_can_sync_without_download() is False


def test_the_need_sync_optimisation_also_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    in_store(monkeypatch, True)
    proc = processor()
    proc.need_sync_datetime = True
    assert proc.cli_can_sync_without_download() is True


@pytest.mark.parametrize(
    "cli_args",
    [
        {"sync": True, "cli_docker": True},
        {"sync": True},
    ],
)
def test_docker_never_syncs_without_a_download(
    monkeypatch: pytest.MonkeyPatch,
    cli_args: dict[str, Any],
) -> None:
    """Its uploads are bundles assembled here, so the store holds nothing to match."""
    in_store(monkeypatch, True)
    proc = processor(**cli_args)
    proc.p_type = "docker"
    assert proc.cli_can_sync_without_download() is False


def test_the_portal_backend_is_not_this_path(monkeypatch: pytest.MonkeyPatch) -> None:
    in_store(monkeypatch, True)
    proc = processor(sync=True)
    proc.what_backend = "portal"
    assert proc.cli_can_sync_without_download() is False


# ------------------------------------------ was the sync about the right bytes


def test_a_matching_digest_means_the_sync_stands(tmp_path: pathlib.Path) -> None:
    path = write_report(tmp_path, report())
    assert processor().cli_synced_artifact_is_unchanged(report_path=path) is True


def test_a_different_digest_means_a_real_scan_is_needed(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    path = write_report(tmp_path, report(hashes=[["sha256", "d" * 64]]))

    with caplog.at_level(logging.WARNING):
        assert processor().cli_synced_artifact_is_unchanged(report_path=path) is False
    assert "different content" in caplog.text


def test_a_digest_we_cannot_read_is_unknown_not_different(tmp_path: pathlib.Path) -> None:
    """Unknown must lead to the full work, never to skipping it."""
    path = write_report(tmp_path, {"schema": 3})
    assert processor().cli_synced_artifact_is_unchanged(report_path=path) is None


def test_no_digest_in_artifactory_is_unknown(tmp_path: pathlib.Path) -> None:
    path = write_report(tmp_path, report())
    proc = processor()
    proc.file.sha2 = ""
    assert proc.cli_synced_artifact_is_unchanged(report_path=path) is None


def test_the_comparison_ignores_case(tmp_path: pathlib.Path) -> None:
    path = write_report(tmp_path, report(hashes=[["sha256", DIGEST.upper()]]))
    assert processor().cli_synced_artifact_is_unchanged(report_path=path) is True
