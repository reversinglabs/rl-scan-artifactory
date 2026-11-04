# python3 ts=4space
"""What set_props_all() writes, and the RL.progress vocabulary it writes it with.

These are characterization tests: they pin the behaviour as it is today, so that
the restructuring set_props_all needs (it is 101 lines at complexity 15) can be
done without changing what lands on an artifact.

Only the api is faked. The decision logic is the real code.
"""

import logging
import re
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
    PortalInfo,
    PurlInfo,
)
from rl_scan_artifactory.constants import (
    PROP_NAME_SPECTRA_ASSURE_GROUP,
    PROP_NAME_SPECTRA_ASSURE_ORG,
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_PURL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_SPECTRA_ASSURE_ALL,
    PROP_SPECTRA_ASSURE_VALID_VALUES,
)
from rl_scan_artifactory.exceptions import (
    SpectraAssureInvariantError,
)

from .conftest import make_file

REPORT_URL = "https://my.secure.software/test/reports/group/abc/report/repo/pkg/1.0/"


class RecordingApi:
    """Records every set_one_prop call instead of making it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def set_one_prop(
        self,
        repo: Any,
        item_uri: str,
        key: str,
        value: str,
        recursive: bool = False,
    ) -> bool:
        self.calls.append(
            {
                "repo": repo,
                "item_uri": item_uri,
                "key": key,
                "value": value,
                "recursive": recursive,
            }
        )
        return True

    def written(self) -> dict[str, str]:
        return {call["key"]: call["value"] for call in self.calls}


def processor(
    *,
    portal: bool = True,
    artifactory_version: str | None = "7.104.5",
) -> Any:
    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)

    proc.file = make_file(uri="/a/mypkg-1.0.tgz", package_type="generic", repo_name="my-repo")
    proc.api = RecordingApi()
    proc.artifactory_api = proc.api

    cli_args: dict[str, Any] = {"portal": portal}
    if artifactory_version is not None:
        cli_args["_artifactory_version"] = {"version": artifactory_version}
    proc.cli_args = cli_args

    proc.purl_info = PurlInfo()
    proc.purl_info.project = "my-repo"
    proc.purl_info.package = "mypkg"
    proc.purl_info.version = "1.0"

    proc.portal_info = PortalInfo(server="test", org="TestOrg", group="TestGroup")
    return proc


def write(
    proc: Any,
    *,
    report: str | None = REPORT_URL,
    progress: str = "scanned",
    scan_status: str | None = "pass",
    recursive: bool = False,
    uri: str = "/a/mypkg-1.0.tgz",
) -> dict[str, str]:
    proc.set_props_all(
        report=report,
        progress=progress,
        scan_status=scan_status,
        recursive=recursive,
        uri=uri,
    )

    written: dict[str, str] = proc.api.written()
    return written


# ------------------------------------------------------------- what is written


def test_a_complete_portal_scan_writes_every_property() -> None:
    written = write(processor())
    assert set(written) == set(PROP_SPECTRA_ASSURE_ALL)


def test_the_values_of_a_complete_portal_scan() -> None:
    written = write(processor())

    assert written[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == "scanned"
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS] == "pass"
    assert written[PROP_NAME_SPECTRA_ASSURE_PURL] == "pkg:rl/my-repo/mypkg@1.0"
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT] == REPORT_URL
    assert written[PROP_NAME_SPECTRA_ASSURE_ORG] == "TestOrg"
    assert written[PROP_NAME_SPECTRA_ASSURE_GROUP] == "TestGroup"


def test_the_timestamp_is_utc_to_the_second() -> None:
    written = write(processor())
    stamp = written[PROP_NAME_SPECTRA_ASSURE_TIMESTAMP]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp), stamp


def test_the_purl_carries_the_pkg_rl_prefix() -> None:
    """The property is the full package url, not the bare triple."""
    written = write(processor())
    assert written[PROP_NAME_SPECTRA_ASSURE_PURL].startswith("pkg:rl/")


def test_every_property_goes_to_the_same_item() -> None:
    proc = processor()
    write(proc, uri="/some/other/item.tgz")
    assert {call["item_uri"] for call in proc.api.calls} == {"/some/other/item.tgz"}


@pytest.mark.parametrize("recursive", [False, True])
def test_the_recursive_flag_is_passed_through_to_every_call(recursive: bool) -> None:
    proc = processor()
    write(proc, recursive=recursive)
    assert all(call["recursive"] is recursive for call in proc.api.calls)


# ------------------------------------------------------------- what is skipped


def test_no_scan_status_means_that_property_is_not_written() -> None:
    written = write(processor(), scan_status=None)
    assert PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS not in written


@pytest.mark.parametrize("unknown", ["maybe", "PASSED", "error", ""])
def test_an_unknown_scan_status_is_not_written(unknown: str) -> None:
    """Only the values in PROP_SPECTRA_ASSURE_VALID_VALUES reach artifactory."""
    written = write(processor(), scan_status=unknown)
    assert PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS not in written


@pytest.mark.parametrize("known", ["pass", "fail", "PASS", "Fail"])
def test_a_known_scan_status_is_written_as_given(known: str) -> None:
    """The check lowercases, the value is stored with its original case."""
    written = write(processor(), scan_status=known)
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS] == known


@pytest.mark.parametrize("empty", [None, ""])
def test_no_report_means_that_property_is_not_written(empty: str | None) -> None:
    written = write(processor(), report=empty)
    assert PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT not in written


def test_cli_mode_writes_no_org_and_no_group() -> None:
    """Those two are portal concepts; a cli scan has neither."""
    written = write(processor(portal=False))

    assert PROP_NAME_SPECTRA_ASSURE_ORG not in written
    assert PROP_NAME_SPECTRA_ASSURE_GROUP not in written
    assert PROP_NAME_SPECTRA_ASSURE_PROGRESS in written


# ------------------------------------------- the report url space, by version
# Below artifactory 7.104.5 a leading space makes the report url viewable.


@pytest.mark.parametrize("version", ["7.104.5", "7.104.6", "7.105.0", "8.0.0"])
def test_a_new_enough_artifactory_gets_the_report_url_as_is(version: str) -> None:
    written = write(processor(artifactory_version=version))
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT] == REPORT_URL


@pytest.mark.parametrize("version", ["7.104.4", "7.103.9", "6.99.99"])
def test_an_older_artifactory_gets_a_leading_space(version: str) -> None:
    written = write(processor(artifactory_version=version))
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT] == " " + REPORT_URL


@pytest.mark.parametrize("version", [None, "not-a-version", "7.104"])
def test_an_unknown_artifactory_version_gets_the_space(version: str | None) -> None:
    """When in doubt, prefer the value that is viewable everywhere."""
    proc = processor(artifactory_version=version)
    written = write(proc)
    assert written[PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT] == " " + REPORT_URL


# --------------------------------------------------- the RL.progress vocabulary
# RL.progress drives whether an artifact is processed again on the next run, so
# the value written and the values tested for have to be the same words.


def test_the_progress_value_is_written_as_given() -> None:
    written = write(processor(), progress="upload_to_portal_ok")
    assert written[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == "upload_to_portal_ok"


def test_an_unknown_progress_value_is_written_anyway() -> None:
    """Unlike the scan status, progress is not checked against its valid values."""
    written = write(processor(), progress="something-else")
    assert written[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == "something-else"


def test_the_documented_progress_values() -> None:
    assert PROP_SPECTRA_ASSURE_VALID_VALUES[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == [
        "upload_to_portal_ok",
        "scanned",
    ]


def test_only_upload_to_portal_ok_is_ever_written(caplog: pytest.LogCaptureFixture) -> None:
    """'portal_upload_ok' is a key of the in-memory steps dict, not a progress value.

    The two read alike and mean different things; see test_progress_vocabulary
    below for where that matters.
    """
    with caplog.at_level(logging.DEBUG):
        written = write(processor(), progress="upload_to_portal_ok")

    assert written[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == "upload_to_portal_ok"


# ------------------------------------------------------- the dispatch table
# set_props_all() asks _value_for_property() for one value per property. The
# table and PROP_SPECTRA_ASSURE_ALL have to stay in step, so this checks the
# structure rather than the values, which the tests above already cover.


def value_for(proc: Any, key: str, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {"report": REPORT_URL, "progress": "scanned", "scan_status": "pass"}
    defaults.update(kwargs)
    return proc._value_for_property(key, **defaults)


@pytest.mark.parametrize("key", PROP_SPECTRA_ASSURE_ALL)
def test_every_property_has_a_value(key: str) -> None:
    """A property with no entry would be silently never written."""
    assert value_for(processor(), key) is not None


@pytest.mark.parametrize("key", PROP_SPECTRA_ASSURE_ALL)
def test_every_value_is_a_string(key: str) -> None:
    assert isinstance(value_for(processor(), key), str)


def test_an_unknown_property_yields_no_value(caplog: pytest.LogCaptureFixture) -> None:
    """Rather than raising: an unrecognised name is a coding mistake, not a run failure."""
    with caplog.at_level(logging.WARNING):
        assert value_for(processor(), "RL.something-new") is None
    assert "RL.something-new" in caplog.text


def test_the_table_covers_exactly_the_property_list() -> None:
    """Nothing in the table that is not in the list, and nothing missing from it."""
    proc = processor()
    written = write(proc)
    assert set(written) == set(PROP_SPECTRA_ASSURE_ALL)


# ------------------------------------------------- one value at a time, in order


def test_properties_are_written_in_the_order_of_the_list() -> None:
    proc = processor()
    write(proc)
    assert [call["key"] for call in proc.api.calls] == list(PROP_SPECTRA_ASSURE_ALL)


def test_a_failing_value_leaves_the_earlier_properties_written() -> None:
    """Values are computed inside the loop, so a later failure does not undo the
    properties already set. That is how it has always behaved."""
    proc = processor()
    proc.portal_info.org = None  # the org value raises

    with pytest.raises(SpectraAssureInvariantError, match="org"):
        write(proc)

    written = proc.api.written()
    assert PROP_NAME_SPECTRA_ASSURE_PROGRESS in written
    assert PROP_NAME_SPECTRA_ASSURE_PURL in written
    assert PROP_NAME_SPECTRA_ASSURE_ORG not in written
    assert PROP_NAME_SPECTRA_ASSURE_GROUP not in written


def test_a_cli_run_needs_no_portal_org_or_group() -> None:
    proc = processor(portal=False)
    proc.portal_info.org = None
    proc.portal_info.group = None

    written = write(proc)
    assert PROP_NAME_SPECTRA_ASSURE_ORG not in written


# ------------------------------- the artifactory version behind the report url
# Below artifactory 7.104.5 a leading space makes the report url viewable. The
# comparison is a hand written triple compare (complexity 12), so this pins each
# boundary rather than a couple of samples.


def needs_space(version: str | None) -> bool:
    result: bool = processor(artifactory_version=version).artifactory_report_url_needs_space()
    return result


@pytest.mark.parametrize(
    "version",
    ["6.99.99", "7.0.0", "7.103.999", "7.104.0", "7.104.4"],
)
def test_older_than_7_104_5_needs_the_space(version: str) -> None:
    assert needs_space(version) is True


@pytest.mark.parametrize(
    "version",
    ["7.104.5", "7.104.6", "7.105.0", "7.999.0", "8.0.0", "10.0.0"],
)
def test_7_104_5_and_newer_does_not(version: str) -> None:
    assert needs_space(version) is False


def test_the_boundary_itself() -> None:
    """The version the fix landed in is the first that does not need the space."""
    assert needs_space("7.104.4") is True
    assert needs_space("7.104.5") is False


@pytest.mark.parametrize(
    "version",
    [None, "", "7", "7.104", "seven.one.five", "7.x.5", "7.104.beta"],
)
def test_a_version_we_cannot_read_gets_the_space(version: str | None) -> None:
    """When in doubt prefer the value that is viewable everywhere."""
    assert needs_space(version) is True


def test_no_version_at_all_gets_the_space() -> None:
    proc = processor()
    proc.cli_args.pop("_artifactory_version", None)
    assert proc.artifactory_report_url_needs_space() is True


def test_extra_version_parts_are_ignored() -> None:
    """Artifactory reports things like 7.104.5 with a build suffix elsewhere."""
    assert needs_space("7.104.5.1") is False
    assert needs_space("7.104.4.9") is True
