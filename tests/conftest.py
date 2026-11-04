# python3 ts=4space
"""Shared fixtures.

Everything here is pure in-memory: no Artifactory, no Portal, no network.
The production code takes its input from two dataclasses (ArtifactoryRepoInfo
and FileInfo), so a test only has to build those.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.fileinfo import FileInfo


def make_repo(
    *,
    name: str = "my-repo",
    package_type: str = "generic",
    repo_type: str = "local",
    layout: str = "simple-default",
) -> ArtifactoryRepoInfo:
    return ArtifactoryRepoInfo(
        name=name,
        repo_type=repo_type,
        package_type=package_type,
        layout=layout,
    )


def make_file(
    *,
    uri: str,
    repo: ArtifactoryRepoInfo | None = None,
    package_type: str = "generic",
    repo_name: str = "my-repo",
    properties: dict[str, Any] | None = None,
    simple: dict[str, Any] | None = None,
    sha1: str = "0" * 40,
    sha2: str = "0" * 64,
    last_modified: str = "2025-01-01T00:00:00.000+00:00",
) -> FileInfo:
    """Build a FileInfo the way ArtifactoryApi would have populated it."""
    if repo is None:
        repo = make_repo(name=repo_name, package_type=package_type)

    file = FileInfo(
        uri=uri,
        sha1=sha1,
        sha2=sha2,
        repo=repo,
        last_modified=last_modified,
    )
    file.properties = properties if properties is not None else {}
    file.simple = simple if simple is not None else {}
    return file


def make_simple(
    *,
    name: str,
    version: str,
    **extra: str,
) -> dict[str, Any]:
    """Artifactory property values are always lists, simple data keeps that shape."""
    simple: dict[str, Any] = {
        "name": [name],
        "version": [version],
    }
    for key, value in extra.items():
        simple[key] = [value]
    return simple


@pytest.fixture
def repo() -> ArtifactoryRepoInfo:
    return make_repo()
