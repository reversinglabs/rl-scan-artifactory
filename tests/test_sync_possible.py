# python3 ts=4space
"""sync_possible: the automatic sync of a scan older than 14 days (R12.7.3).

A cli-docker run never syncs (R12.7.2.1). The check used to look for the key
`cli-docker`, but the options arrive as `cli_docker`, so it never matched: an
item last scanned more than 14 days ago was sent to a sync, and without
--cli-rlstore-path the docker backend then raised "store is None" for that item
on every later run.

The options come from MyArgs itself, so a renamed key fails here.
"""

from datetime import UTC, datetime, timedelta
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ArtifactoryFileProcessorCommon,
)
from rl_scan_artifactory.constants import MY_ENV_NAMES, PROP_NAME_SPECTRA_ASSURE_TIMESTAMP

from .conftest import make_file
from .test_my_args import ARTIFACTORY_ENV, build

CLI_DOCKER_ENV: dict[str, str] = {
    **ARTIFACTORY_ENV,
    "RLSECURE_ENCODED_LICENSE": "SECRET-LICENSE",
    "RLSECURE_SITE_KEY": "SECRET-SITE-KEY",
}

CLI_DOCKER_ARGV = ["rl-scan-artifactory", "--cli-docker", "--repo", "my-repo"]
CLI_ARGV = [
    "rl-scan-artifactory",
    "--cli",
    "--cli-rlsecure-path",
    "/opt/rl-secure",
    "--cli-rlstore-path",
    "/opt/rl-store",
    "--repo",
    "my-repo",
]


def scanned_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def processor(cli_args: dict[str, Any], *, last_scan: str) -> Any:
    proc: Any = ArtifactoryFileProcessorCommon.__new__(ArtifactoryFileProcessorCommon)
    proc.cli_args = cli_args
    proc.file = make_file(uri="/m/mypkg-1.0.tgz", properties={PROP_NAME_SPECTRA_ASSURE_TIMESTAMP: [last_scan]})
    return proc


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in MY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_cli_docker_never_syncs_an_old_scan(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    args = build(monkeypatch, argv=CLI_DOCKER_ARGV, env=CLI_DOCKER_ENV)
    assert processor(args.cli_args, last_scan=scanned_days_ago(30)).sync_possible() is False


def test_cli_syncs_an_old_scan(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    args = build(monkeypatch, argv=CLI_ARGV, env=CLI_DOCKER_ENV)
    assert processor(args.cli_args, last_scan=scanned_days_ago(30)).sync_possible() is True


def test_cli_does_not_sync_a_recent_scan(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    args = build(monkeypatch, argv=CLI_ARGV, env=CLI_DOCKER_ENV)
    assert processor(args.cli_args, last_scan=scanned_days_ago(3)).sync_possible() is False
