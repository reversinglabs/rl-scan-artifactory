# python3 ts=4space
"""The purl table: (package type, uri, artifactory properties) -> project/package@version.

This is the closest thing the project has to an executable specification.
Each row pins what a real repository item produces today.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.name_mangler import (
    NameManglerDebian,
    NameManglerDefault,
    NameManglerDocker,
    NameManglerGems,
    NameManglerGeneric,
    NameManglerMaven,
    NameManglerNpm,
    NameManglerPypi,
    NameManglerRpm,
)

from .conftest import make_file, make_simple


def purl_of(
    mangler_class: Any,
    *,
    uri: str,
    name: str,
    version: str,
    repo_name: str = "my-repo",
    package_type: str = "generic",
    properties: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    file = make_file(
        uri=uri,
        repo_name=repo_name,
        package_type=package_type,
        properties=properties or {},
        simple=make_simple(name=name, version=version),
    )
    result: tuple[str, str, str] = mangler_class(file=file).make_long()
    return result


# ------------------------------------------------------------------ generic
# NameManglerGeneric and NameManglerMaven deliberately produce no remainder,
# so the project is always the bare repository name.


@pytest.mark.parametrize("mangler_class", [NameManglerGeneric, NameManglerMaven])
def test_flat_manglers_never_extend_the_project(mangler_class: Any) -> None:
    project, package, version = purl_of(
        mangler_class,
        uri="/some/deep/path/whatever-1.2.3-linux-x86_64.bin",
        name="whatever",
        version="1.2.3",
        repo_name="the-repo",
    )
    assert (project, package, version) == ("the-repo", "whatever", "1.2.3")


# ------------------------------------------------------------------ default


@pytest.mark.parametrize(
    ("uri", "name", "version", "expected"),
    [
        # nothing left over once name and version are removed
        ("/a/foo-1.0", "foo", "1.0", ("my-repo", "foo", "1.0")),
        # the leftover (arch, build tag) is appended to the project
        ("/a/foo-1.0-linux", "foo", "1.0", ("my-repo_linux", "foo", "1.0")),
        ("/a/foo-1.0-x86_64", "foo", "1.0", ("my-repo_x86_64", "foo", "1.0")),
    ],
)
def test_default_mangler_moves_the_remainder_into_the_project(
    uri: str,
    name: str,
    version: str,
    expected: tuple[str, str, str],
) -> None:
    assert purl_of(NameManglerDefault, uri=uri, name=name, version=version) == expected


def test_default_mangler_escapes_the_purl_components() -> None:
    project, package, version = purl_of(
        NameManglerDefault,
        uri="/a/weird",
        name="a/b",
        version="1:2.0",
        repo_name="repo",
    )
    for part in (project, package, version):
        assert "/" not in part
        assert "@" not in part
        assert "%" not in part


# --------------------------------------------------------------- extensions
# Each type strips its own archive suffix before the shared mangling runs.


@pytest.mark.parametrize(
    ("mangler_class", "suffix"),
    [
        (NameManglerDebian, ".deb"),
        (NameManglerGems, ".gem"),
        (NameManglerPypi, ".whl"),
    ],
)
def test_archive_suffix_is_stripped_before_mangling(mangler_class: Any, suffix: str) -> None:
    project, package, version = purl_of(
        mangler_class,
        uri=f"/a/mypkg-1.0{suffix}",
        name="mypkg",
        version="1.0",
    )
    assert (project, package, version) == ("my-repo", "mypkg", "1.0")
    assert suffix.lstrip(".") not in project


@pytest.mark.parametrize(
    ("mangler_class", "uri", "expected_project"),
    [
        (NameManglerGems, "/a/nokogiri-1.16.7-x86_64-linux.gem", "my-repo_x86_64-linux"),
        (NameManglerPypi, "/a/mypkg-1.0-py3-none-any.whl", "my-repo_py3-none-any"),
        (NameManglerDebian, "/a/mypkg-1.0_amd64.deb", "my-repo_amd64"),
    ],
)
def test_arch_and_build_tags_end_up_in_the_project(
    mangler_class: Any,
    uri: str,
    expected_project: str,
) -> None:
    name = "nokogiri" if "nokogiri" in uri else "mypkg"
    version = "1.16.7" if "nokogiri" in uri else "1.0"
    project, _package, _version = purl_of(mangler_class, uri=uri, name=name, version=version)
    assert project == expected_project


# --------------------------------------------------------------------- npm


def test_npm_scoped_package_becomes_namespace_underscore_name() -> None:
    _project, package, _version = purl_of(
        NameManglerNpm,
        uri="/@types/minipass/-/minipass-3.3.5.tgz",
        name="@types/minipass",
        version="3.3.5",
        package_type="npm",
    )
    assert package == "types_minipass"


def test_npm_unscoped_package_is_unchanged() -> None:
    _project, package, _version = purl_of(
        NameManglerNpm,
        uri="/run-series/-/run-series-1.1.9.tgz",
        name="run-series",
        version="1.1.9",
        package_type="npm",
    )
    assert package == "run-series"


# --------------------------------------------------------------------- rpm


def rpm_props(*, release: str, arch: str) -> dict[str, Any]:
    return {
        "rpm.metadata.release": [release],
        "rpm.metadata.arch": [arch],
        "rpm.metadata.name": ["glibc-gconv-extra"],
        "rpm.metadata.version": ["2.34"],
    }


def test_rpm_moves_platform_and_arch_to_the_project_and_release_to_the_version() -> None:
    project, package, version = purl_of(
        NameManglerRpm,
        uri="/a/glibc-gconv-extra-2.34-100.el9_4.3.i686.rpm",
        name="glibc-gconv-extra",
        version="2.34",
        package_type="rpm",
        properties=rpm_props(release="100.el9_4.3", arch="i686"),
    )
    assert package == "glibc-gconv-extra"
    assert version == "2.34-100.3"
    assert "el9_4" in project
    assert "i686" in project


def test_rpm_without_a_platform_tag_still_produces_a_clean_version() -> None:
    _project, _package, version = purl_of(
        NameManglerRpm,
        uri="/a/mypkg-1.0-7.x86_64.rpm",
        name="mypkg",
        version="1.0",
        package_type="rpm",
        properties={"rpm.metadata.release": ["7"], "rpm.metadata.arch": ["x86_64"]},
    )
    assert version == "1.0-7"


def test_rpm_numeric_dotted_release_is_not_lost() -> None:
    _project, _package, version = purl_of(
        NameManglerRpm,
        uri="/a/mypkg-1.0-7.2.x86_64.rpm",
        name="mypkg",
        version="1.0",
        package_type="rpm",
        properties={"rpm.metadata.release": ["7.2"], "rpm.metadata.arch": ["x86_64"]},
    )
    assert not version.endswith("-")
    assert version == "1.0-7.2"


@pytest.mark.parametrize(
    "properties",
    [
        {},
        {"rpm.metadata.release": [], "rpm.metadata.arch": []},
        {"rpm.metadata.arch": ["x86_64"]},
    ],
)
def test_rpm_without_metadata_properties_falls_back_to_empty(properties: dict[str, Any]) -> None:
    """Missing rpm metadata is tolerated rather than fatal, and must not leave a
    trailing '-' on the version."""
    _project, package, version = purl_of(
        NameManglerRpm,
        uri="/a/mypkg-1.0-7.x86_64.rpm",
        name="mypkg",
        version="1.0",
        package_type="rpm",
        properties=properties,
    )
    assert package == "mypkg"
    assert version == "1.0"
    assert not version.endswith("-")


# ------------------------------------------------------------------ docker


def test_docker_uses_the_default_mangling() -> None:
    project, package, version = purl_of(
        NameManglerDocker,
        uri="/reversinglabs/rl-scanner/1.2.3/manifest.json",
        name="reversinglabs/rl-scanner",
        version="1.2.3",
        package_type="docker",
        repo_name="docker-local",
    )
    assert "/" not in package
    assert version == "1.2.3"
    assert project.startswith("docker-local")


# ------------------------------------------------------------- determinism


@pytest.mark.parametrize(
    "mangler_class",
    [
        NameManglerDefault,
        NameManglerDebian,
        NameManglerDocker,
        NameManglerGems,
        NameManglerGeneric,
        NameManglerMaven,
        NameManglerPypi,
    ],
)
def test_mangling_is_stable_across_two_instances(mangler_class: Any) -> None:
    kwargs: dict[str, Any] = {
        "uri": "/a/mypkg-1.0-linux-x86_64.bin",
        "name": "mypkg",
        "version": "1.0",
    }
    assert purl_of(mangler_class, **kwargs) == purl_of(mangler_class, **kwargs)
