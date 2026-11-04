# python3 ts=4space
"""The live .rl_meta side-car handling, in ArtifactoryFileProcessorGeneric.

This is the code path that actually runs. The parallel GenericMetaReader module
was never wired up and has been commented out; anything that looked like a bug
there did not affect a real scan, so this file replaces the old
test_generic_meta.py.

The three stages are tested directly, without the download that feeds them:
  _make_meta_dict   ini section -> meta dict + generic._derived_.* properties
  _verify_mandatory name / version / path must be present and non-empty
  _set_purl_data    meta dict   -> purl_info.project / .package / .version
"""

import configparser
import pathlib
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor import (
    artifactory_file_processor_generic as generic_module,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)
from rl_scan_artifactory.constants import (
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_SPECTRA_ASSURE_ALL,
    PROP_SPECTRA_ASSURE_ON_SIDE_CAR,
)
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction
from rl_scan_artifactory.name_mangler.name_mangler_common import NameManglerCommon

from .conftest import make_file

MINIMAL = "[rl_meta]\nname = mypkg\nversion = 1.2.3\npath = /repo/path/mypkg-1.2.3.bin\n"
FULL = (
    "[rl_meta]\n"
    "namespace = com.example\n"
    "name = mypkg\n"
    "version = 1.2.3\n"
    "architecture = amd64\n"
    "path = /repo/path/mypkg-1.2.3.bin\n"
    "sha256 = deadbeef\n"
)


def read_config(body: str, tmp_path: pathlib.Path) -> configparser.ConfigParser:
    target = tmp_path / "myfile.rl_meta"
    target.write_text(body)
    # the same construction the production code uses: a side-car is data, not a template
    config = configparser.ConfigParser(interpolation=None)
    config.read(str(target))
    return config


def processor(tmp_path: pathlib.Path) -> Any:
    """Build just enough of the processor to exercise the meta stages."""
    proc = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)

    file = make_file(uri="/a/b.rl_meta", package_type="generic", repo_name="generic-local")
    proc.file = file
    proc.repo = file.repo
    proc.purl_info = PurlInfo()
    return proc


def meta_of(body: str, tmp_path: pathlib.Path) -> tuple[Any, dict[str, Any]]:
    proc = processor(tmp_path)
    meta: dict[str, Any] = proc._make_meta_dict(config=read_config(body, tmp_path))
    return proc, meta


def purl_of(body: str, tmp_path: pathlib.Path) -> tuple[str | None, str | None, str | None]:
    proc, meta = meta_of(body, tmp_path)
    proc._verify_mandatory(meta=meta)
    proc._set_purl_data(meta=meta)
    return proc.purl_info.project, proc.purl_info.package, proc.purl_info.version


# --------------------------------------------------------------- meta dict


def test_all_known_fields_are_collected(tmp_path: pathlib.Path) -> None:
    proc, meta = meta_of(FULL, tmp_path)
    assert meta == {
        "namespace": "com.example",
        "name": "mypkg",
        "version": "1.2.3",
        "architecture": "amd64",
        "path": "/repo/path/mypkg-1.2.3.bin",
        "sha256": "deadbeef",
    }


def test_absent_optional_fields_are_none(tmp_path: pathlib.Path) -> None:
    proc, meta = meta_of(MINIMAL, tmp_path)
    assert meta["namespace"] is None
    assert meta["architecture"] is None
    assert meta["sha256"] is None


def test_meta_is_mirrored_into_derived_properties(tmp_path: pathlib.Path) -> None:
    proc, _meta = meta_of(FULL, tmp_path)
    front = "generic._derived_"
    assert proc.file.properties[f"{front}.name"] == ["mypkg"]
    assert proc.file.properties[f"{front}.version"] == ["1.2.3"]


def test_architecture_is_mirrored_as_arch(tmp_path: pathlib.Path) -> None:
    """The property suffix is .arch, matching the rpm naming, not .architecture."""
    proc, _meta = meta_of(FULL, tmp_path)
    assert proc.file.properties["generic._derived_.arch"] == ["amd64"]
    assert "generic._derived_.architecture" not in proc.file.properties


@pytest.mark.parametrize("body", [MINIMAL, FULL])
def test_derived_properties_keep_the_list_shape(tmp_path: pathlib.Path, body: str) -> None:
    """R3.1: every property value in this codebase is a list[str]."""
    proc, _meta = meta_of(body, tmp_path)

    assert proc.file.properties
    for key, value in proc.file.properties.items():
        assert isinstance(value, list), key
        assert all(isinstance(v, str) for v in value), key


def test_an_absent_optional_field_gets_no_property_at_all(tmp_path: pathlib.Path) -> None:
    """Better than a None or an empty list: the key simply is not there."""
    proc, meta = meta_of(MINIMAL, tmp_path)
    assert meta["architecture"] is None  # the meta dict still records the absence

    for key in ("arch", "namespace", "sha256"):
        assert f"generic._derived_.{key}" not in proc.file.properties


# ------------------------------------------------------------- mandatory


def test_a_complete_side_car_passes_verification(tmp_path: pathlib.Path) -> None:
    proc, meta = meta_of(MINIMAL, tmp_path)
    proc._verify_mandatory(meta=meta)


@pytest.mark.parametrize("missing", ["name", "version", "path"])
def test_a_missing_mandatory_field_is_rejected(tmp_path: pathlib.Path, missing: str) -> None:
    body = "".join(line + "\n" for line in MINIMAL.splitlines() if not line.startswith(f"{missing} = "))
    proc, meta = meta_of(body, tmp_path)
    with pytest.raises(SpectraAssureInvalidAction, match="mandatory"):
        proc._verify_mandatory(meta=meta)


@pytest.mark.parametrize("empty", ["name", "version", "path"])
def test_an_empty_mandatory_field_is_rejected(tmp_path: pathlib.Path, empty: str) -> None:
    body = "".join(f"{empty} =\n" if line.startswith(f"{empty} = ") else line + "\n" for line in MINIMAL.splitlines())
    proc, meta = meta_of(body, tmp_path)
    with pytest.raises(SpectraAssureInvalidAction, match="mandatory"):
        proc._verify_mandatory(meta=meta)


# ------------------------------------------------------------------ purl


def test_minimal_side_car_yields_a_purl(tmp_path: pathlib.Path) -> None:
    """Only the three mandatory fields: namespace and architecture are absent."""
    assert purl_of(MINIMAL, tmp_path) == ("generic-local", "mypkg", "1.2.3")


def test_architecture_extends_the_project(tmp_path: pathlib.Path) -> None:
    project, _package, _version = purl_of(FULL, tmp_path)
    assert project == "generic-local-amd64"


def test_namespace_prefixes_the_package(tmp_path: pathlib.Path) -> None:
    _project, package, _version = purl_of(FULL, tmp_path)
    assert package == "com.example-mypkg"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my/pkg", "my0x2Fpkg"),
        ("my@pkg", "my0x40pkg"),
    ],
)
def test_purl_components_are_escaped(tmp_path: pathlib.Path, raw: str, expected: str) -> None:
    body = MINIMAL.replace("name = mypkg", f"name = {raw}")
    _project, package, _version = purl_of(body, tmp_path)
    assert package == expected


def test_path_is_not_a_purl_component_and_is_left_alone(tmp_path: pathlib.Path) -> None:
    proc, meta = meta_of(MINIMAL, tmp_path)
    assert meta["path"] == "/repo/path/mypkg-1.2.3.bin"


# -------------------------------------- the two future purl flags (D21, D22)
# Both default to False: turning either on moves every generic purl to a new
# project on the portal, so they flip on a release boundary, not per customer.


@pytest.fixture
def purl_flags(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Set both flags for one test; they are read from the module that uses them."""

    def _set(*, escape: bool, separator: bool) -> None:
        monkeypatch.setattr(generic_module, "FUTURE_GENERIC_PURL_ESCAPE", escape)
        monkeypatch.setattr(generic_module, "FUTURE_GENERIC_PURL_SEPARATOR", separator)

    return _set


def test_the_flags_ship_off() -> None:
    """The default must stay the current behaviour until the release that flips it."""
    assert getattr(generic_module, "FUTURE_GENERIC_PURL_ESCAPE") is False  # noqa: B009
    assert getattr(generic_module, "FUTURE_GENERIC_PURL_SEPARATOR") is False  # noqa: B009


# ---------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my/pkg", "my0x2Fpkg"),
        ("my@pkg", "my0x40pkg"),
        ("a b", "a b"),  # a space survives today
        ("a:b", "a:b"),  # so does a colon
    ],
)
def test_escaping_today_covers_only_at_and_slash(
    tmp_path: pathlib.Path,
    purl_flags: Any,
    raw: str,
    expected: str,
) -> None:
    purl_flags(escape=False, separator=False)
    body = MINIMAL.replace("name = mypkg", f"name = {raw}")
    _project, package, _version = purl_of(body, tmp_path)
    assert package == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my/pkg", "my0x2Fpkg"),
        ("my@pkg", "my0x40pkg"),
        ("a b", "a+b"),
        ("a:b", "a0x3Ab"),
    ],
)
def test_escaping_with_the_flag_matches_the_name_manglers(
    tmp_path: pathlib.Path,
    purl_flags: Any,
    raw: str,
    expected: str,
) -> None:
    purl_flags(escape=True, separator=False)
    body = MINIMAL.replace("name = mypkg", f"name = {raw}")
    _project, package, _version = purl_of(body, tmp_path)

    assert package == expected
    assert package == NameManglerCommon._escape_string_for_spectra_assure_purl_component(raw)


@pytest.mark.parametrize("raw", ["a b", "a%b", "a:b", "my/pkg", "my@pkg"])
@pytest.mark.parametrize("escape", [False, True])
def test_at_and_slash_never_survive_either_scheme(
    tmp_path: pathlib.Path,
    purl_flags: Any,
    escape: bool,
    raw: str,
) -> None:
    purl_flags(escape=escape, separator=False)
    body = MINIMAL.replace("name = mypkg", f"name = {raw}")
    _project, package, _version = purl_of(body, tmp_path)

    assert package is not None
    assert "/" not in package
    assert "@" not in package


def test_only_the_new_scheme_escapes_the_percent(tmp_path: pathlib.Path, purl_flags: Any) -> None:
    """'%' is the escape character of a purl, so leaving it raw is a defect of the
    old scheme, and one more reason to flip FUTURE_GENERIC_PURL_ESCAPE."""
    body = MINIMAL.replace("name = mypkg", "name = a%b")

    purl_flags(escape=False, separator=False)
    _project, old_package, _version = purl_of(body, tmp_path)
    assert old_package == "a%b"  # pin the defect

    purl_flags(escape=True, separator=False)
    _project, new_package, _version = purl_of(body, tmp_path)
    assert new_package is not None
    assert "%" not in new_package


# --------------------------------------------------------------- separator


@pytest.mark.parametrize(
    ("separator", "expected_project", "expected_package"),
    [
        (False, "generic-local-amd64", "com.example-mypkg"),
        (True, "generic-local_amd64", "com.example_mypkg"),
    ],
)
def test_the_separator_flag_switches_both_joins(
    tmp_path: pathlib.Path,
    purl_flags: Any,
    separator: bool,
    expected_project: str,
    expected_package: str,
) -> None:
    purl_flags(escape=False, separator=separator)
    project, package, _version = purl_of(FULL, tmp_path)

    assert project == expected_project
    assert package == expected_package


def test_the_separator_flag_does_not_touch_a_purl_without_optional_parts(
    tmp_path: pathlib.Path,
    purl_flags: Any,
) -> None:
    """With no architecture and no namespace there is nothing to join."""
    for separator in (False, True):
        purl_flags(escape=False, separator=separator)
        assert purl_of(MINIMAL, tmp_path) == ("generic-local", "mypkg", "1.2.3")


def test_the_two_flags_are_independent(tmp_path: pathlib.Path, purl_flags: Any) -> None:
    purl_flags(escape=True, separator=False)
    project_escaped_only, _package, _version = purl_of(FULL, tmp_path)

    purl_flags(escape=False, separator=True)
    project_separated_only, _package, _version = purl_of(FULL, tmp_path)

    assert project_escaped_only == "generic-local-amd64"
    assert project_separated_only == "generic-local_amd64"


# ------------------------------------------------------------ interpolation


@pytest.mark.parametrize("raw", ["a%b", "100%", "%(name)s", "50%-off"])
def test_a_percent_in_a_value_is_literal(tmp_path: pathlib.Path, raw: str) -> None:
    """A side-car is data: configparser's default interpolation would raise on '%'."""
    body = MINIMAL.replace("name = mypkg", f"name = {raw}")
    _proc, meta = meta_of(body, tmp_path)
    assert meta["name"] == raw


# ------------------------------------------------- reading back a property
# The properties are list[str] (R3.1). Every consumer has to unwrap, and the
# one that did not turned "/".join() into a TypeError on a live run.


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("name", "mypkg"),
        ("version", "1.2.3"),
        ("path", "/repo/path/mypkg-1.2.3.bin"),
        ("sha256", "deadbeef"),
        ("arch", "amd64"),
    ],
)
def test_a_derived_property_reads_back_as_a_string(
    tmp_path: pathlib.Path,
    key: str,
    expected: str,
) -> None:
    proc, _meta = meta_of(FULL.format(sha="deadbeef"), tmp_path)
    assert proc._derived_property(key) == expected


def test_an_absent_derived_property_reads_back_as_none(tmp_path: pathlib.Path) -> None:
    proc, _meta = meta_of(MINIMAL, tmp_path)
    for key in ("arch", "namespace", "sha256"):
        assert proc._derived_property(key) is None


def test_a_derived_property_is_usable_in_a_string_join(tmp_path: pathlib.Path) -> None:
    """The regression: the raw property is a list, and "/".join() on it raises."""
    proc, _meta = meta_of(MINIMAL, tmp_path)

    path = proc._derived_property("path")
    assert isinstance(path, str)

    aa = "/some/dir/myfile.rl_meta".split("/")
    aa[-1] = path
    assert "/".join(aa) == "/some/dir//repo/path/mypkg-1.2.3.bin"


def test_the_raw_property_is_still_a_list(tmp_path: pathlib.Path) -> None:
    """The accessor unwraps; the stored shape stays list[str] as R3.1 requires."""
    proc, _meta = meta_of(MINIMAL, tmp_path)
    assert proc.file.properties["generic._derived_.path"] == ["/repo/path/mypkg-1.2.3.bin"]


# ------------------------------------------- where a generic result is written
# The .rl_meta side-car is how a generic artifact is found, never what is
# scanned: the scan is of the file its 'path' names. The full result therefore
# belongs on that file. The side-car keeps only enough to say it was handled and
# when, which is what a later run reads to skip it (R7.10).


def writing_processor(*, portal: bool, path: str | None = "HxDSetup_2.5.0.exe") -> Any:
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import PurlInfo
    from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
        ArtifactoryFileProcessorGeneric,
    )
    from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
    from rl_scan_artifactory.fileinfo import FileInfo

    class RecordingApi:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def set_one_prop(self, **kwargs: Any) -> bool:
            self.calls.append((kwargs["item_uri"], kwargs["key"]))
            return True

    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)
    proc.uri = "/a/HxDSetup_2.5.0.exe.rl_meta"
    proc.what_backend = "portal" if portal else "cli"
    proc.cli_args = {"portal": portal}

    repo = ArtifactoryRepoInfo("my-release-candidates", "local", "generic", "s")
    file = FileInfo(uri=proc.uri, sha1="", sha2="c" * 64, repo=repo, last_modified="")
    file.properties = {} if path is None else {"generic._derived_.path": [path]}
    proc.file = file
    proc.repo_db = {"/a/HxDSetup_2.5.0.exe": {"sha2": "d" * 64}}

    proc.artifactory_api = RecordingApi()
    proc.purl_info = PurlInfo()
    proc.purl_info.project = "my-release-candidates"
    proc.purl_info.package = "windows-HxDSetup"
    proc.purl_info.version = "2.5.0"
    proc.portal_info = type("P", (), {"org": "Test", "group": "testMboot"})()
    proc._portal_make_report_base = lambda: "https://my.secure.software/test"
    return proc


def written(proc: Any) -> dict[str, set[str]]:
    proc._update_artifactory_item_with_scan_status(scan_status="pass", report="group/x/report/y/")

    out: dict[str, set[str]] = {}
    for uri, key in proc.artifactory_api.calls:
        out.setdefault(uri, set()).add(key)
    return out


SIDE_CAR = "/a/HxDSetup_2.5.0.exe.rl_meta"
DESCRIBED = "/a/HxDSetup_2.5.0.exe"


def test_the_full_result_goes_on_the_file_that_was_scanned() -> None:
    out = written(writing_processor(portal=True))

    assert out[DESCRIBED] == set(PROP_SPECTRA_ASSURE_ALL)


def test_the_side_car_keeps_only_what_says_it_was_handled() -> None:
    """RL.progress and RL.timestamp, and RL.sha256 to say for which bytes."""
    out = written(writing_processor(portal=True))

    assert out[SIDE_CAR] == set(PROP_SPECTRA_ASSURE_ON_SIDE_CAR)


@pytest.mark.parametrize(
    "key",
    ["RL.scan-status", "RL.scan-report", "RL.package-url", "RL.organization", "RL.group"],
)
def test_no_scan_result_lands_on_the_side_car(key: str) -> None:
    """It was never the thing scanned, so it carries no verdict of its own."""
    out = written(writing_processor(portal=True))

    assert key not in out[SIDE_CAR]


def test_the_side_car_still_says_it_was_handled() -> None:
    """RL.progress is what a later run reads to skip the work."""
    out = written(writing_processor(portal=True))

    assert PROP_NAME_SPECTRA_ASSURE_PROGRESS in out[SIDE_CAR]


def test_both_items_are_written() -> None:
    out = written(writing_processor(portal=True))

    assert set(out) == {SIDE_CAR, DESCRIBED}


def test_a_cli_run_writes_only_the_artifact_itself() -> None:
    """There is no side-car for cli, so self.uri is already the artifact.

    Org and group are portal concepts and are not written by a cli run, which is
    the rule of R10.6 rather than anything to do with side-cars.
    """
    out = written(writing_processor(portal=False))
    portal_only = {"RL.organization", "RL.group"}

    assert set(out) == {SIDE_CAR}
    assert out[SIDE_CAR] == set(PROP_SPECTRA_ASSURE_ALL) - portal_only


def test_a_side_car_without_a_path_writes_only_itself() -> None:
    """Nothing to describe, so nothing to write it to."""
    out = written(writing_processor(portal=True, path=None))

    assert set(out) == {SIDE_CAR}
