# python3 ts=4space
"""SimpleData turns raw Artifactory properties into name/version/arch/release/namespace."""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.simple_data import (
    SimpleDataDefault,
    SimpleDataDocker,
    SimpleDataMaven,
)

from .conftest import make_file


def simple_default(
    *,
    package_type: str,
    properties: dict[str, Any],
    uri: str = "/a/b.bin",
) -> dict[str, Any]:
    file = make_file(uri=uri, package_type=package_type, properties=properties)
    return SimpleDataDefault(file=file).make_simple_data()


# ------------------------------------------------------- property matching


def test_name_and_version_are_picked_up_by_suffix() -> None:
    got = simple_default(
        package_type="pypi",
        properties={"pypi.name": ["mypkg"], "pypi.version": ["1.0"]},
    )
    assert got == {"name": ["mypkg"], "version": ["1.0"]}


def test_properties_of_another_package_type_are_ignored() -> None:
    got = simple_default(
        package_type="pypi",
        properties={"npm.name": ["other"], "pypi.version": ["1.0"]},
    )
    assert got == {"version": ["1.0"]}


def test_a_middle_component_in_the_property_key_is_allowed() -> None:
    """rpm.metadata.name and maven._derived_.name must both match."""
    got = simple_default(
        package_type="rpm",
        properties={
            "rpm.metadata.name": ["glibc"],
            "rpm.metadata.version": ["2.34"],
            "rpm.metadata.arch": ["x86_64"],
            "rpm.metadata.release": ["100.el9"],
        },
    )
    assert got == {
        "name": ["glibc"],
        "version": ["2.34"],
        "arch": ["x86_64"],
        "release": ["100.el9"],
    }


def test_nuget_id_is_mapped_to_name() -> None:
    got = simple_default(
        package_type="nuget",
        properties={"nuget.id": ["Newtonsoft.Json"], "nuget.version": ["13.0.3"]},
    )
    assert got["name"] == ["Newtonsoft.Json"]


@pytest.mark.parametrize(
    ("package_type", "property_prefix"),
    [
        ("debian", "deb"),
        ("gems", "gem"),
    ],
)
def test_package_type_is_translated_to_the_property_prefix(
    package_type: str,
    property_prefix: str,
) -> None:
    got = simple_default(
        package_type=package_type,
        properties={f"{property_prefix}.name": ["x"], f"{property_prefix}.version": ["1"]},
    )
    assert got == {"name": ["x"], "version": ["1"]}


def test_no_matching_properties_gives_an_empty_result() -> None:
    assert simple_default(package_type="pypi", properties={}) == {}


# ------------------------------------------------------------------- maven


def test_maven_only_looks_at_jar_files() -> None:
    props = {"maven._derived_.name": ["a.b"], "maven._derived_.version": ["1.0"]}

    jar = make_file(uri="/o/a/b/1.0/b-1.0.jar", package_type="maven", properties=props)
    assert SimpleDataMaven(file=jar).make_simple_data() == {"name": ["a.b"], "version": ["1.0"]}

    pom = make_file(uri="/o/a/b/1.0/b-1.0.pom", package_type="maven", properties=props)
    assert SimpleDataMaven(file=pom).make_simple_data() == {}


# ------------------------------------------------------------------ docker


def docker_simple(*, uri: str, properties: dict[str, Any]) -> dict[str, Any]:
    file = make_file(uri=uri, package_type="docker", properties=properties)
    return SimpleDataDocker(file=file).make_simple_data()


def test_docker_only_looks_at_manifest_json() -> None:
    props = {"docker.repoName": ["reversinglabs/rl-scanner"], "docker.manifest": ["1.2.3"]}
    assert docker_simple(uri="/rl-scanner/1.2.3/sha256__abc", properties=props) == {}


def test_docker_maps_reponame_and_manifest() -> None:
    got = docker_simple(
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        properties={"docker.repoName": ["reversinglabs/rl-scanner"], "docker.manifest": ["1.2.3"]},
    )
    assert got == {"name": ["reversinglabs/rl-scanner"], "version": ["1.2.3"]}


DIGEST_MANIFEST_PROPS = {
    "docker.repoName": ["reversinglabs/rl-scanner"],
    "docker.manifest": ["sha256:deadbeef"],
}


def test_docker_digest_manifest_is_not_usable_as_a_version() -> None:
    """A sha256 manifest is not a version, so it must be cleared."""
    got = docker_simple(
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        properties=DIGEST_MANIFEST_PROPS,
    )
    assert not got["version"][0]


def test_docker_cleared_version_keeps_the_list_shape() -> None:
    """Downstream code does simple['version'][0]; a bare '' would make that an IndexError."""
    got = docker_simple(
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        properties=DIGEST_MANIFEST_PROPS,
    )
    assert got["version"] == [""]
