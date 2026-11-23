# python3 ts=4space
"""What happens to one repository: which are skipped, and which items are visited.

Characterization tests for `_run_one_repo_all_artifacts` (complexity 14), so it
can be restructured without changing what it does. Nothing here asserted its
behaviour before: the containment tests replace the whole method with a fake, so
the skip reasons, the two pre passes and the item loop were untested.

`ArtifactoryRepoProcessor` is faked; everything else is the real code.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.constants import PROCESS_FILE_SKIP
from rl_scan_artifactory.my_app import MyApp

REPO = "my-repo"
REPORTS_REPO = "my-reports"


class FakeRepoProcessor:
    """Stands in for ArtifactoryRepoProcessor: a repo and the items it lists."""

    def __init__(self, repo: ArtifactoryRepoInfo, uris: list[str]) -> None:
        self.repo = repo
        self.p_type = repo.package_type.lower()
        self.uris = uris
        self.process_calls = 0

    def get_repo(self) -> ArtifactoryRepoInfo:
        return self.repo

    def process(self) -> Any:
        self.process_calls += 1
        for uri in self.uris:
            yield {"uri": uri}


def repo_info(
    *,
    name: str = REPO,
    repo_type: str = "local",
    package_type: str = "pypi",
    layout: str = "simple-default",
) -> ArtifactoryRepoInfo:
    return ArtifactoryRepoInfo(
        name=name,
        repo_type=repo_type,
        package_type=package_type,
        layout=layout,
    )


def app(
    *,
    repo: ArtifactoryRepoInfo | None = None,
    uris: list[str] | None = None,
    limit: int = 0,
    statuses: list[str] | None = None,
    **cli_args: Any,
) -> Any:
    instance: Any = MyApp.__new__(MyApp)

    instance.cli_args = dict(cli_args)
    instance.verbose = cli_args.get("verbose", False)
    instance.spectra_assure_api = None
    instance.artifactory_api = None
    instance.WITH_TEST_LIMIT_REPO_TO = limit

    instance.printed = []
    instance.my_print = instance.printed.append
    instance._now_string_compact = lambda: "T"

    arp = FakeRepoProcessor(repo if repo is not None else repo_info(), uris if uris is not None else [])
    instance.arp = arp

    instance.visited = []
    instance.cleaned_reports = []
    instance._clean_report = lambda **kwargs: instance.cleaned_reports.append(kwargs["artifact_item"]["uri"])
    instance.pre_passes = []
    instance._repo_generic_extract_rl_meta_info = lambda a, db: instance.pre_passes.append("generic")
    instance._repo_docker_extract_list_manifest_info = lambda a, db: instance.pre_passes.append("docker")

    results = list(statuses) if statuses else []

    def one_artifact(**kwargs: Any) -> str:
        instance.visited.append(kwargs["artifact_item"]["uri"])
        return results.pop(0) if results else "Processed"

    instance._run_one_repo_one_artifact = one_artifact
    return instance


def run(instance: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Drive the method with the repository processor replaced."""
    from rl_scan_artifactory import my_app as module

    monkeypatch.setattr(module, "ArtifactoryRepoProcessor", lambda **kwargs: instance.arp)
    instance._run_one_repo_all_artifacts(REPO)
    return instance


# --------------------------------------------------------- the five skips


def skipped(instance: Any) -> bool:
    """A skipped repository never asks the processor for its items."""
    calls: int = instance.arp.process_calls
    return calls == 0


def test_a_repository_with_no_configuration_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instance = app(repo=repo_info(repo_type=""), uris=["/a.whl"])

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert "does not exist, or we may not read its configuration" in caplog.text


def test_an_unsupported_repository_type_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instance = app(repo=repo_info(repo_type="virtual"), uris=["/a.whl"])

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert "only local, remote repositories are supported" in caplog.text


@pytest.mark.parametrize("package_type", ["ivy", "Ivy", "conan", "sbt"])
def test_an_unsupported_package_type_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    package_type: str,
) -> None:
    """R11.6.9: it used to be listed as empty, so the run found nothing and said nothing."""
    instance = app(repo=repo_info(package_type=package_type), uris=["/a.jar"])

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert f"package type '{package_type.lower()}' is not supported" in caplog.text
    assert "maven" in caplog.text  # the supported ones are named
    assert any("REPO SKIP" in line for line in instance.printed)


@pytest.mark.parametrize("package_type", ["maven", "Maven", "generic", "Docker"])
def test_a_supported_package_type_is_not_skipped_whatever_its_case(
    monkeypatch: pytest.MonkeyPatch,
    package_type: str,
) -> None:
    instance = app(repo=repo_info(package_type=package_type), uris=["/a.jar"])
    run(instance, monkeypatch)

    assert not skipped(instance)


@pytest.mark.parametrize("package_type", ["gradle", "Gradle"])
def test_a_gradle_repository_in_the_maven_2_default_layout_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
    package_type: str,
) -> None:
    """R4.1.7: the layout Artifactory gives a gradle repository by default."""
    instance = app(repo=repo_info(package_type=package_type, layout="maven-2-default"), uris=["/a.jar"])
    run(instance, monkeypatch)

    assert not skipped(instance)


@pytest.mark.parametrize("layout", ["ivy-default", "gradle-default", "my-custom-layout", ""])
def test_a_gradle_repository_in_another_layout_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    layout: str,
) -> None:
    """R4.1.7: ivy-default puts a [type]s folder before the file; the maven parser
    would take that folder for the version."""
    instance = app(repo=repo_info(package_type="gradle", layout=layout), uris=["/a.jar"])

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert f"gradle repository layout '{layout}' is not supported" in caplog.text
    assert "(supported: maven-2-default)" in caplog.text
    assert any("REPO SKIP" in line for line in instance.printed)


def test_a_maven_repository_layout_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only gradle is checked: maven repositories behave as before 1.3.0."""
    instance = app(repo=repo_info(package_type="maven", layout="my-custom-layout"), uris=["/a.jar"])
    run(instance, monkeypatch)

    assert not skipped(instance)


def test_a_cli_run_on_a_remote_repo_without_a_report_location_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A remote repository cannot take an upload, so the reports need somewhere else."""
    instance = app(repo=repo_info(repo_type="remote"), uris=["/a.whl"], cli=True)

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert "missing report location" in caplog.text


def test_the_reports_repository_itself_is_not_scanned(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instance = app(
        repo=repo_info(name=REPORTS_REPO),
        uris=["/a.whl"],
        cli=True,
        cli_reports_repo=REPORTS_REPO,
    )

    with caplog.at_level(logging.WARNING):
        run(instance, monkeypatch)

    assert skipped(instance)
    assert "will not be scanned" in caplog.text


# ------------------------------------------- which skips reach the console
# Two of the four are always printed; two only with --verbose. That difference
# is in the current code and is pinned here rather than assumed to be a mistake.


@pytest.mark.parametrize("repo_type", ["", "virtual"])
def test_the_first_two_skips_always_print(
    monkeypatch: pytest.MonkeyPatch,
    repo_type: str,
) -> None:
    instance = app(repo=repo_info(repo_type=repo_type), uris=["/a.whl"])
    run(instance, monkeypatch)

    assert any("REPO SKIP" in line for line in instance.printed)


def test_the_cli_skips_print_only_when_verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    quiet = app(repo=repo_info(repo_type="remote"), uris=["/a.whl"], cli=True)
    run(quiet, monkeypatch)
    assert not any("REPO SKIP" in line for line in quiet.printed)

    loud = app(repo=repo_info(repo_type="remote"), uris=["/a.whl"], cli=True, verbose=True)
    run(loud, monkeypatch)
    assert any("REPO SKIP" in line for line in loud.printed)


# --------------------------------------------------------- the pre passes


def test_a_generic_repository_reads_its_side_cars_first(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(repo=repo_info(package_type="generic"), uris=["/a.bin"])
    run(instance, monkeypatch)

    assert instance.pre_passes == ["generic"]


def test_a_docker_repository_reads_its_list_manifests_first(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(repo=repo_info(package_type="docker"), uris=["/a/manifest.json"])
    run(instance, monkeypatch)

    assert instance.pre_passes == ["docker"]


def test_any_other_type_has_no_pre_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(repo=repo_info(package_type="pypi"), uris=["/a.whl"])
    run(instance, monkeypatch)

    assert instance.pre_passes == []


def test_a_skipped_repository_runs_no_pre_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(repo=repo_info(repo_type="virtual", package_type="generic"), uris=["/a.bin"])
    run(instance, monkeypatch)

    assert instance.pre_passes == []


# ----------------------------------------------------------- the item loop


def test_every_item_is_visited(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(uris=["/a.whl", "/b.whl", "/c.whl"])
    run(instance, monkeypatch)

    assert instance.visited == ["/a.whl", "/b.whl", "/c.whl"]


def test_a_report_bundle_is_never_visited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Our own uploaded reports are not artifacts to scan, in either mode; they are only cleaned (R10.9.6)."""
    instance = app(uris=["/a.whl", "/a.whl-reports.zip", "/b.whl"])
    run(instance, monkeypatch)

    assert instance.visited == ["/a.whl", "/b.whl"]
    assert instance.cleaned_reports == ["/a.whl-reports.zip"]


def test_an_empty_repository_visits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(uris=[])
    run(instance, monkeypatch)

    assert instance.visited == []


# -------------------------------------------------- the development limit
# WITH_TEST_LIMIT_REPO_TO stops a run early while developing. It counts only
# items that were not skipped, which is the part easiest to get wrong.


def test_no_limit_visits_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(uris=[f"/{n}.whl" for n in range(5)], limit=0)
    run(instance, monkeypatch)

    assert len(instance.visited) == 5


def test_the_limit_stops_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(uris=[f"/{n}.whl" for n in range(5)], limit=2)
    run(instance, monkeypatch)

    assert len(instance.visited) == 2


def test_skipped_items_do_not_count_towards_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three skips then two real ones, with a limit of two, visits all five."""
    instance = app(
        uris=[f"/{n}.whl" for n in range(5)],
        limit=2,
        statuses=[PROCESS_FILE_SKIP, PROCESS_FILE_SKIP, PROCESS_FILE_SKIP, "Processed", "Processed"],
    )
    run(instance, monkeypatch)

    assert len(instance.visited) == 5


def test_the_limit_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instance = app(uris=[f"/{n}.whl" for n in range(5)], limit=1)

    with caplog.at_level(logging.INFO):
        run(instance, monkeypatch)

    assert "limit reached" in caplog.text


# ------------------------------------------------------------- the start


def test_the_repository_is_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = app(uris=[])
    run(instance, monkeypatch)

    assert any(REPO in line for line in instance.printed)
