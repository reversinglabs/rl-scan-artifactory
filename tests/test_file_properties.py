# python3 ts=4space
"""FileProperties decides which files are candidates and derives properties Artifactory lacks.

ArtifactoryApi is replaced by a fake, so nothing here touches the network.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.file_properties import (
    FilePropertiesDefault,
    FilePropertiesDocker,
    FilePropertiesGeneric,
    FilePropertiesMaven,
    FilePropertiesNuget,
)
from rl_scan_artifactory.fileinfo import FileInfo

from .conftest import make_file


class FakeArtifactoryApi:
    """Stands in for ArtifactoryApi: serves canned properties, records touch calls."""

    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self._properties = properties if properties is not None else {}
        self.touched: list[str] = []

    def get_item_properties(self, *, file: FileInfo) -> dict[str, Any]:
        return dict(self._properties)

    def touch_rpm_info_uri(self, *, file: FileInfo) -> None:
        self.touched.append(file.uri)


def props_for(
    properties_class: Any,
    *,
    uri: str,
    package_type: str,
    stored_properties: dict[str, Any] | None = None,
    repo_name: str = "my-repo",
) -> Any:
    file = make_file(uri=uri, package_type=package_type, repo_name=repo_name)
    return properties_class(
        cli_args={},
        file=file,
        artifactory_api=FakeArtifactoryApi(stored_properties),
    )


# ------------------------------------------------------------------ default


def test_a_file_with_name_and_version_is_a_candidate() -> None:
    fp = props_for(
        FilePropertiesDefault,
        uri="/a/mypkg-1.0.whl",
        package_type="pypi",
        stored_properties={"pypi.name": ["mypkg"], "pypi.version": ["1.0"]},
    )
    assert fp.skip_non_candidate_file() is False
    assert fp.file.simple == {"name": ["mypkg"], "version": ["1.0"]}


@pytest.mark.parametrize(
    "stored",
    [
        {},
        {"pypi.name": ["mypkg"]},
        {"pypi.version": ["1.0"]},
    ],
)
def test_a_file_missing_name_or_version_is_skipped(stored: dict[str, Any]) -> None:
    fp = props_for(
        FilePropertiesDefault,
        uri="/a/mypkg-1.0.whl",
        package_type="pypi",
        stored_properties=stored,
    )
    assert fp.skip_non_candidate_file() is True


# -------------------------------------------------------------------- nuget


def test_nuget_only_accepts_nupkg_files() -> None:
    stored = {"nuget.id": ["Newtonsoft.Json"], "nuget.version": ["13.0.3"]}

    pkg = props_for(FilePropertiesNuget, uri="/a/x.nupkg", package_type="nuget", stored_properties=stored)
    assert pkg.skip_non_candidate_file() is False

    other = props_for(FilePropertiesNuget, uri="/a/x.nuspec", package_type="nuget", stored_properties=stored)
    assert other.skip_non_candidate_file() is True
    assert other.file.simple == {}


# -------------------------------------------------------------------- maven
# Maven jars carry no Artifactory properties, so name/version/namespace are
# derived from the uri layout: <namespace path>/<name>/<version>/<file>


def test_maven_derives_properties_from_the_uri() -> None:
    fp = props_for(
        FilePropertiesMaven,
        uri="/org/apache/logging/log4j/log4j-api/2.12.1/log4j-api-2.12.1.jar",
        package_type="maven",
    )
    front = "maven._derived_"
    assert fp.file.properties[f"{front}.namespace"] == ["org.apache.logging.log4j"]
    assert fp.file.properties[f"{front}.name_only"] == ["log4j-api"]
    assert fp.file.properties[f"{front}.name"] == ["org.apache.logging.log4j.log4j-api"]
    assert fp.file.properties[f"{front}.version"] == ["2.12.1"]


def test_maven_uri_without_a_leading_slash_is_handled() -> None:
    fp = props_for(
        FilePropertiesMaven,
        uri="org/example/mylib/1.0/mylib-1.0.jar",
        package_type="maven",
    )
    front = "maven._derived_"
    assert fp.file.properties[f"{front}.namespace"] == ["org.example"]
    assert fp.file.properties[f"{front}.version"] == ["1.0"]


def test_maven_non_jar_files_derive_nothing() -> None:
    fp = props_for(
        FilePropertiesMaven,
        uri="/org/example/mylib/1.0/mylib-1.0.pom",
        package_type="maven",
    )
    assert fp.file.properties == {}
    assert fp.skip_non_candidate_file() is True


def test_maven_jar_is_a_candidate() -> None:
    fp = props_for(
        FilePropertiesMaven,
        uri="/org/example/mylib/1.0/mylib-1.0.jar",
        package_type="maven",
    )
    assert fp.skip_non_candidate_file() is False


@pytest.mark.parametrize(
    ("uri", "expected_skip"),
    [
        ("/o/a/b/1.0/b-1.0.jar", False),
        ("/o/a/b/1.0/b-1.0.JAR", False),
        ("/a/notajar", True),
        ("/a/my.jar.sha1", True),
        ("/a/b.pom", True),
    ],
)
def test_maven_only_accepts_a_dot_jar_suffix(uri: str, expected_skip: bool) -> None:
    """The suffix test is '.jar', case insensitive, in all three stages."""
    fp = props_for(FilePropertiesMaven, uri=uri, package_type="maven")
    assert fp.skip_non_candidate_file() is expected_skip


def test_maven_uppercase_jar_still_derives_properties() -> None:
    """_get_properties and skip_non_candidate_file must agree on case."""
    fp = props_for(FilePropertiesMaven, uri="/org/example/mylib/1.0/mylib-1.0.JAR", package_type="maven")
    assert fp.file.properties["maven._derived_.version"] == ["1.0"]
    assert fp.skip_non_candidate_file() is False


@pytest.mark.parametrize(
    "uri",
    [
        "/mylib-1.0.jar",  # no namespace, name or version at all
        "mylib-1.0.jar",
        "/1.0/mylib-1.0.jar",  # no namespace and no name
        "/mylib/1.0/mylib-1.0.jar",  # no namespace: a maven artifact always has a groupId
        "//org/mylib/1.0/mylib-1.0.jar",  # an empty segment in the middle
    ],
)
def test_maven_rejects_a_uri_that_is_not_the_maven_layout(uri: str) -> None:
    """Too few segments used to raise IndexError, or silently name the package '.'."""
    fp = props_for(FilePropertiesMaven, uri=uri, package_type="maven")
    assert fp.file.properties == {}
    assert fp.skip_non_candidate_file() is True


@pytest.mark.parametrize(
    "uri",
    [
        "/org/example/mylib/1.0/mylib-1.0.jar",
        "org/example/mylib/1.0/mylib-1.0.jar",  # a leading slash is optional
    ],
)
def test_the_shortest_valid_maven_layout_is_accepted(uri: str) -> None:
    fp = props_for(FilePropertiesMaven, uri=uri, package_type="maven")
    front = "maven._derived_"
    assert fp.file.properties[f"{front}.namespace"] == ["org.example"]
    assert fp.file.properties[f"{front}.name_only"] == ["mylib"]
    assert fp.file.properties[f"{front}.version"] == ["1.0"]


def test_a_rejected_maven_uri_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        props_for(FilePropertiesMaven, uri="/mylib-1.0.jar", package_type="maven")
    assert "not a maven layout" in caplog.text


# ------------------------------------------------------------------- docker
# docker derives name and version from the uri path into docker._derived_.*,
# but SimpleDataDocker only maps .repoName and .manifest.


def docker_props(*, uri: str, stored: dict[str, Any] | None = None) -> Any:
    return props_for(
        FilePropertiesDocker,
        uri=uri,
        package_type="docker",
        repo_name="docker-local",
        stored_properties=stored,
    )


def test_docker_derives_name_and_version_from_the_uri() -> None:
    fp = docker_props(uri="/reversinglabs/rl-scanner/1.2.3/manifest.json")
    front = "docker._derived_"
    assert fp.file.properties[f"{front}.name"] == ["reversinglabs/rl-scanner"]
    assert fp.file.properties[f"{front}.version"] == ["1.2.3"]


def test_docker_local_repo_without_an_org_segment() -> None:
    fp = docker_props(uri="/alpine/3.20/manifest.json")
    assert fp.file.properties["docker._derived_.name"] == ["alpine"]
    assert fp.file.properties["docker._derived_.version"] == ["3.20"]


def test_docker_derived_properties_are_used_when_artifactory_has_none() -> None:
    """A local docker repo may carry no docker.repoName / docker.manifest at all."""
    fp = docker_props(uri="/reversinglabs/rl-scanner/1.2.3/manifest.json")
    assert fp.skip_non_candidate_file() is False
    assert fp.file.simple == {"name": ["reversinglabs/rl-scanner"], "version": ["1.2.3"]}


def test_docker_artifactory_properties_win_over_the_derived_ones() -> None:
    fp = docker_props(
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        stored={"docker.repoName": ["rl/other-name"], "docker.manifest": ["9.9.9"]},
    )
    assert fp.skip_non_candidate_file() is False
    assert fp.file.simple == {"name": ["rl/other-name"], "version": ["9.9.9"]}


def test_docker_digest_manifest_falls_back_to_the_derived_version() -> None:
    """A sha256 manifest is cleared, and the version from the uri takes its place."""
    fp = docker_props(
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        stored={"docker.repoName": ["reversinglabs/rl-scanner"], "docker.manifest": ["sha256:dead"]},
    )
    assert fp.skip_non_candidate_file() is False
    assert fp.file.simple["version"] == ["1.2.3"]


@pytest.mark.parametrize("key", ["name", "version"])
@pytest.mark.parametrize("value", [[], [""]])
def test_a_present_but_empty_property_is_not_a_candidate(key: str, value: list[str]) -> None:
    """A present-but-empty property must be skipped, not scanned with an empty
    purl component."""
    stored = {"pypi.name": ["mypkg"], "pypi.version": ["1.0"]}
    stored[f"pypi.{key}"] = value

    fp = props_for(
        FilePropertiesDefault,
        uri="/a/mypkg-1.0.whl",
        package_type="pypi",
        stored_properties=stored,
    )
    assert fp.skip_non_candidate_file() is True


@pytest.mark.parametrize(
    "uri",
    [
        "/manifest.json",  # no name and no version
        "manifest.json",
        "/1.2.3/manifest.json",  # no name
        "//rl-scanner/1.2.3/manifest.json",  # an empty segment in the middle
    ],
)
def test_docker_malformed_uri_is_skipped_not_crashed(uri: str) -> None:
    """A bare assert used to raise AssertionError here, and vanish under python -O."""
    fp = docker_props(uri=uri)
    assert fp.file.properties == {}
    assert fp.skip_non_candidate_file() is True


@pytest.mark.parametrize(
    ("uri", "expected_name"),
    [
        ("/reversinglabs/rl-scanner/1.2.3/manifest.json", "reversinglabs/rl-scanner"),
        ("reversinglabs/rl-scanner/1.2.3/manifest.json", "reversinglabs/rl-scanner"),
        ("/alpine/3.20/manifest.json", "alpine"),
    ],
)
def test_docker_accepts_the_layouts_with_and_without_an_org(uri: str, expected_name: str) -> None:
    """A leading slash is optional, and a local repo may have no org segment."""
    fp = docker_props(uri=uri)
    assert fp.file.properties["docker._derived_.name"] == [expected_name]


# ------------------------------------------------------------------ generic
# A generic repo carries no usable name/version properties: the purl comes from
# the .rl_meta side-car instead, so R4.2 must not be applied here.


def generic_props(
    *,
    uri: str,
    cli_args: dict[str, Any] | None = None,
    stored: dict[str, Any] | None = None,
) -> Any:
    file = make_file(uri=uri, package_type="generic", repo_name="generic-local")
    properties_class: Any = FilePropertiesGeneric
    return properties_class(
        cli_args=cli_args if cli_args is not None else {},
        file=file,
        artifactory_api=FakeArtifactoryApi(stored),
    )


def test_generic_does_not_skip_on_empty_name_and_version() -> None:
    fp = generic_props(uri="/a/b.rl_meta", cli_args={"portal": True})
    assert fp.skip_non_candidate_file() is False


def test_generic_in_cli_mode_does_not_skip() -> None:
    assert generic_props(uri="/a/b.bin").skip_non_candidate_file() is False


def test_generic_in_portal_mode_skips_everything_but_the_side_car() -> None:
    fp = generic_props(uri="/a/b.bin", cli_args={"portal": True})
    assert fp.skip_non_candidate_file() is True
    assert fp.file.simple == {}


REAL_GENERIC_PROPS = {"generic.name": ["real"], "generic.version": ["1.0"]}


def test_generic_keeps_real_artifactory_name_and_version() -> None:
    """A generic repo has no layout to derive from, so nothing is invented here;
    whatever the repository itself carries is left alone."""
    fp = generic_props(uri="/a/b.bin", stored=REAL_GENERIC_PROPS)
    fp.skip_non_candidate_file()
    assert fp.file.simple == {"name": ["real"], "version": ["1.0"]}


def test_generic_invents_no_derived_properties() -> None:
    fp = generic_props(uri="/a/b.bin", stored=REAL_GENERIC_PROPS)
    fp.skip_non_candidate_file()
    assert not [k for k in fp.file.properties if "_derived_" in k]


def test_generic_without_any_properties_is_still_not_skipped() -> None:
    """The purl comes from the .rl_meta side-car, so an empty simple dict is fine."""
    fp = generic_props(uri="/a/b.bin")
    assert fp.skip_non_candidate_file() is False
    assert fp.file.simple == {}


# -------------------------------------------------------------- RL.noscan
# The integration writes RL.noscan on the report files it uploads: into the
# scanned repository itself when that is local, and into a separate local
# repository when the scanned one is remote, because a remote repository cannot
# take an upload at all. Either way a later run must not scan them.


NOSCAN = "RL.noscan"
CANDIDATE_PROPS: dict[str, Any] = {"pypi.name": ["mypkg"], "pypi.version": ["1.0"]}


def pypi_props(*, stored: dict[str, Any]) -> Any:
    return props_for(
        FilePropertiesDefault,
        uri="/a/mypkg-1.0.whl",
        package_type="pypi",
        stored_properties=stored,
    )


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "1", "on", " true "])
def test_a_noscan_item_is_skipped(value: str) -> None:
    fp = pypi_props(stored={**CANDIDATE_PROPS, NOSCAN: [value]})
    assert fp.skip_non_candidate_file() is True


@pytest.mark.parametrize("value", ["false", "False", "no", "0", "", "maybe"])
def test_a_non_affirmative_noscan_does_not_skip(value: str) -> None:
    """Only an affirmative value skips; anything else leaves the item a candidate."""
    fp = pypi_props(stored={**CANDIDATE_PROPS, NOSCAN: [value]})
    assert fp.skip_non_candidate_file() is False


def test_no_noscan_property_does_not_skip() -> None:
    fp = pypi_props(stored=CANDIDATE_PROPS)
    assert fp.skip_non_candidate_file() is False


def test_a_skipped_noscan_item_has_no_simple_data() -> None:
    fp = pypi_props(stored={**CANDIDATE_PROPS, NOSCAN: ["true"]})
    fp.skip_non_candidate_file()
    assert fp.file.simple == {}


@pytest.mark.parametrize(
    ("properties_class", "uri", "package_type"),
    [
        (FilePropertiesDefault, "/a/mypkg-1.0.whl", "pypi"),
        (FilePropertiesMaven, "/org/example/mylib/1.0/mylib-1.0.jar", "maven"),
        (FilePropertiesNuget, "/a/x.nupkg", "nuget"),
        (FilePropertiesDocker, "/reversinglabs/rl-scanner/1.2.3/manifest.json", "docker"),
        (FilePropertiesGeneric, "/a/b.bin", "generic"),
    ],
)
def test_every_package_type_honours_noscan(
    properties_class: Any,
    uri: str,
    package_type: str,
) -> None:
    """The check is in the base class, so a new package type cannot forget it.

    Generic matters most here: it never skips on name and version, so before this
    it had no way to skip a report file at all.
    """
    fp = props_for(
        properties_class,
        uri=uri,
        package_type=package_type,
        stored_properties={**CANDIDATE_PROPS, NOSCAN: ["true"]},
    )
    assert fp.skip_non_candidate_file() is True


def test_noscan_is_checked_before_the_per_type_rules() -> None:
    """A .jar that is also a report file is skipped for being a report file."""
    fp = props_for(
        FilePropertiesMaven,
        uri="/org/example/mylib/1.0/mylib-1.0.jar",
        package_type="maven",
        stored_properties={NOSCAN: ["true"]},
    )
    assert fp.is_noscan() is True
    assert fp.skip_non_candidate_file() is True


def test_is_noscan_tolerates_a_bare_string() -> None:
    """Artifactory gives lists, but nothing guarantees it for a hand set property."""
    fp = pypi_props(stored={**CANDIDATE_PROPS, NOSCAN: "true"})
    assert fp.is_noscan() is True
