# python3 ts=4space
"""Properties this integration wrote earlier and no longer maintains are removed (R10.9).

Two kinds exist on repositories scanned by earlier versions:

- everything under the old `Spectra.Assure.` prefix, from before `RL.`;
- the full scan result on a generic `.rl_meta` side-car: 1.0.4 wrote
  status, report, purl, organization and group there, where a side-car now
  keeps only what says it was handled (R7.10).

- any other `RL.*` name: the integration is the sole owner of the `RL.` prefix
  (the other ReversingLabs integration uses `secure.software.`), so a name it
  does not maintain is one it no longer writes.

Each item a run inspects is cleaned before it is processed, skipped items
included (a cli run cleans the side-cars it does not scan), unless
`--keep-obsolete-properties` is given. `RL.noscan` stays, and nothing outside
the integration's two prefixes is touched.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_docker import (
    ArtifactoryFileProcessorDocker,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.constants import (
    PROCESS_FILE_FAILED,
    PROCESS_FILE_SKIP,
)

from .conftest import make_file
from .test_run_containment import FakeFileProcessor, make_app, repo_info, run_items

FULL = {
    "RL.progress": ["scanned"],
    "RL.timestamp": ["2025-10-01T00:00:00Z"],
    "RL.scan-status": ["pass"],
    "RL.package-url": ["pkg:rl/generic-local/mypkg@1.0"],
    "RL.scan-report": [" https://my.secure.software/test/report"],
    "RL.organization": ["Test"],
    "RL.group": ["testGroup"],
    "RL.sha256": ["a" * 64],
}
NOT_OURS = {
    "generic._derived_.path": ["mypkg-1.0.bin"],
    "pypi.name": ["mypkg"],
    "secure.software.scan-status": ["pass"],
}
NOSCAN = {"RL.noscan": ["true"]}
NO_LONGER_WRITTEN = {"RL.uploaded": ["yes"]}
LEGACY = {
    "Spectra.Assure.progress": ["scanned"],
    "Spectra.Assure.scan-status": ["fail"],
}
SIDE_CAR_RESULT = {"RL.scan-status", "RL.package-url", "RL.scan-report", "RL.organization", "RL.group"}


class RecordingApi:
    def __init__(self, *, refuse: set[str] | None = None) -> None:
        self.deleted: list[tuple[str, str, bool]] = []
        self.refuse = refuse or set()

    def del_one_prop(self, *, repo: Any, item_uri: str, key: str, recursive: bool) -> bool:
        self.deleted.append((item_uri, key, recursive))
        return key not in self.refuse


def processor(cls: Any, *, uri: str, package_type: str, properties: dict[str, list[str]], **cli_args: Any) -> Any:
    proc: Any = cls.__new__(cls)
    proc.uri = uri
    proc.up_uri = "/".join(uri.split("/")[:-1])
    proc.p_type = package_type
    proc.cli_args = cli_args
    proc.file = make_file(uri=uri, package_type=package_type, properties=dict(properties))
    proc.artifactory_api = RecordingApi()
    return proc


def default(properties: dict[str, list[str]]) -> Any:
    return processor(ArtifactoryFileProcessorCommon, uri="/m/mypkg-1.0.tgz", package_type="npm", properties=properties)


def side_car(properties: dict[str, list[str]], *, portal: bool = True) -> Any:
    return processor(
        ArtifactoryFileProcessorGeneric,
        uri="/a/mypkg-1.0.bin.rl_meta",
        package_type="generic",
        properties=properties,
        portal=portal,
    )


def deleted_keys(proc: Any) -> set[str]:
    proc.remove_obsolete_properties()
    return {key for _, key, _ in proc.artifactory_api.deleted}


# ----------------------------------------------------------- what is obsolete


def test_an_ordinary_item_keeps_every_property_it_carries() -> None:
    assert deleted_keys(default({**FULL, **NOT_OURS, **NOSCAN})) == set()


def test_an_rl_name_the_integration_no_longer_writes_is_removed() -> None:
    """The integration is the sole owner of RL.: an unknown name there is an old one."""
    assert deleted_keys(default({**FULL, **NO_LONGER_WRITTEN})) == set(NO_LONGER_WRITTEN)


def test_the_old_prefix_is_removed_everywhere() -> None:
    assert deleted_keys(default({**FULL, **LEGACY})) == set(LEGACY)


def test_a_side_car_loses_the_scan_result_1_0_4_wrote_there() -> None:
    assert deleted_keys(side_car(FULL)) == SIDE_CAR_RESULT


def test_a_side_car_keeps_what_says_it_was_handled() -> None:
    proc = side_car(FULL)
    proc.remove_obsolete_properties()
    assert set(proc.file.properties) == {"RL.progress", "RL.timestamp", "RL.sha256"}


def test_names_that_are_not_the_integrations_own_are_left_alone() -> None:
    """secure.software.* is the other ReversingLabs integration's."""
    assert deleted_keys(side_car({**FULL, **NOT_OURS})) == SIDE_CAR_RESULT


def test_rl_noscan_stays_even_on_a_side_car() -> None:
    """It is read on every item, and a person may have set it."""
    assert deleted_keys(side_car({**FULL, **NOSCAN})) == SIDE_CAR_RESULT


def test_a_cli_run_cleans_a_side_car_the_same_way() -> None:
    """A cli run does not scan side-cars, but a portal run on the same repo wrote them."""
    assert deleted_keys(side_car(FULL, portal=False)) == SIDE_CAR_RESULT


def test_a_cli_run_leaves_the_full_set_on_a_scanned_generic_file() -> None:
    """In cli mode the described file is itself the scanned item."""
    proc = processor(
        ArtifactoryFileProcessorGeneric,
        uri="/a/mypkg-1.0.bin",
        package_type="generic",
        properties=FULL,
        portal=False,
    )
    assert deleted_keys(proc) == set()


def test_nothing_obsolete_means_no_call() -> None:
    proc = default(FULL)
    proc.remove_obsolete_properties()
    assert proc.artifactory_api.deleted == []


# ------------------------------------------------------------ how it is removed


def test_it_is_removed_from_the_item_itself() -> None:
    proc = side_car(FULL)
    proc.remove_obsolete_properties()
    assert {(uri, recursive) for uri, _, recursive in proc.artifactory_api.deleted} == {
        ("/a/mypkg-1.0.bin.rl_meta", False),
    }


def test_docker_removes_it_where_it_writes_recursively() -> None:
    proc = processor(
        ArtifactoryFileProcessorDocker,
        uri="/img/1.0/manifest.json",
        package_type="docker",
        properties={**FULL, **LEGACY},
    )
    proc.remove_obsolete_properties()
    assert {(uri, recursive) for uri, _, recursive in proc.artifactory_api.deleted} == {("/img/1.0", True)}


def test_a_refused_delete_keeps_the_property_known() -> None:
    """The api logs the refusal; a later run tries again."""
    proc = side_car(FULL)
    proc.artifactory_api.refuse = {"RL.group"}
    proc.remove_obsolete_properties()
    assert "RL.group" in proc.file.properties
    assert "RL.scan-status" not in proc.file.properties


def test_the_removal_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        side_car(FULL).remove_obsolete_properties()
    assert "removed obsolete properties" in caplog.text


# ------------------------------------------------------------ the option


def test_every_inspected_item_is_cleaned_by_default() -> None:
    app = make_app()
    run_items(app, ["/a.bin", "/b.bin"])
    assert [proc.obsolete_removed for proc in app.made] == [True, True]


def test_keep_obsolete_properties_leaves_them() -> None:
    app = make_app()
    app.cli_args["keep_obsolete_properties"] = True
    run_items(app, ["/a.bin"])
    assert app.made[0].obsolete_removed is False


def test_a_cli_run_cleans_the_side_cars_it_skips() -> None:
    app = make_app(portal=False)
    statuses = run_items(app, ["/a.bin.rl_meta"])
    assert statuses == [PROCESS_FILE_SKIP]
    assert app.made[0].obsolete_removed is True


def test_a_cli_run_with_keep_obsolete_properties_leaves_skipped_side_cars() -> None:
    app = make_app(portal=False)
    app.cli_args["keep_obsolete_properties"] = True
    assert run_items(app, ["/a.bin.rl_meta"]) == [PROCESS_FILE_SKIP]
    assert app.made[0].obsolete_removed is False


def test_a_failed_cleanup_of_a_skipped_side_car_is_contained() -> None:
    app = make_app(portal=False)

    def refuse() -> None:
        raise ConnectionError("artifactory unreachable")

    def get_afp(**kwargs: Any) -> Any:
        proc = FakeFileProcessor(kwargs["artifact_item"]["uri"])
        proc.remove_obsolete_properties = refuse  # type: ignore[method-assign]
        return proc

    app._get_my_afp = get_afp
    status = app._run_one_repo_one_artifact(
        repo=repo_info(),
        p_type="generic",
        artifact_item={"uri": "/a.bin.rl_meta"},
        repo_db={},
    )
    assert status == PROCESS_FILE_FAILED
    assert app.failed_items == [("r1", "/a.bin.rl_meta")]
