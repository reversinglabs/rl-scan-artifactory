# python3 ts=4space
import logging
import os
import sys
import time
from typing import (
    Any,
)

from .app_base_with_logging import AppBaseWithLogging
from .artifactory_api import ArtifactoryApi
from .artifactory_file_processor import (
    ArtifactoryFileProcessorCommon,
    ArtifactoryFileProcessorDefault,
    ArtifactoryFileProcessorDocker,
    ArtifactoryFileProcessorGeneric,  # artifactory generic package_type
)
from .artifactory_file_processor.artifactory_file_processor_common import obsolete_property_names
from .artifactory_repo_info import ArtifactoryRepoInfo
from .artifactory_repo_processor import ArtifactoryRepoProcessor
from .constants import (
    CLI_REPORTS_FILE_TAIL,
    DOCKER_LIST_MANIFEST_FILE,
    EXIT_FATAL,
    EXIT_ITEM_FAILURES,
    EXIT_OK,
    META_STRING,
    PROCESS_FILE_FAILED,
    PROCESS_FILE_SKIP,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
    WRITABLE_REPO_TYPES,
)
from .exceptions import SpectraAssureInvalidAction
from .file_properties import (
    FilePropertiesDefault,
    FilePropertiesDocker,
    FilePropertiesGeneric,
    FilePropertiesMaven,
    FilePropertiesNuget,
    FilePropertiesRpm,
)
from .fileinfo import FileInfo
from .helpers import set_proxy
from .my_args import MyArgs
from .py_cli_scan import ScanCliLocal
from .spectra_assure_api import SpectraAssureApi
from .version import VERSION

logger = logging.getLogger(__name__)


class MyApp(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)
        self._validate_params()
        logger.debug("args: %s", args)
        self.artifactory_api = ArtifactoryApi(args=args)

        self.spectra_assure_api = None
        if self.cli_args.get("portal") is True:
            self.spectra_assure_api = SpectraAssureApi(args=args)

        self.verbose = self.cli_args["verbose"]

        self.WITH_TEST_LIMIT_REPO_TO = 0
        if os.getenv("WITH_TEST_LIMIT_REPO_TO"):
            self.WITH_TEST_LIMIT_REPO_TO = int(os.getenv("WITH_TEST_LIMIT_REPO_TO") or 0)

        self.not_finished: list[ArtifactoryFileProcessorCommon] = []

        # anything we could not process, collected so the run can finish and still
        # report what went wrong and exit with a meaningful status
        self.failed_items: list[tuple[str, str]] = []  # (repo name, uri)
        self.failed_repos: list[str] = []

        self.proxies: dict[str, str] = set_proxy(
            server=self.cli_args.get("proxy_server"),
            port=self.cli_args.get("proxy_port"),
            user=self.cli_args.get("proxy_user"),
            password=self.cli_args.get("proxy_password"),
        )

    def my_print(self, msg: str) -> None:
        """Progress output for the user; this is what --verbose promises on stdout.

        It also goes to the log as info, so a log file tells the same story. The
        console copy of the log goes to stderr (--log-to-stderr), so the two never
        collide and neither has to be suppressed.
        """
        logger.info(msg)
        print(msg)  # noqa: T201

    @staticmethod
    def _now_string_compact() -> str:
        time_format = "%G-%m-%dT%H:%M:%S%z"
        now = time.localtime()
        return time.strftime(time_format, now)

    def _validate_params(
        self,
    ) -> None:
        self.repo_list = self.cli_args["repo"]
        if len(self.repo_list) == 0:
            msg = "repo list is empty"
            raise ValueError(msg)

    def _add_fp(
        self,
        p_type: str,
        afp: ArtifactoryFileProcessorCommon,
    ) -> Any:
        dispatch = {
            "docker": FilePropertiesDocker,
            "nuget": FilePropertiesNuget,
            "rpm": FilePropertiesRpm,
            "maven": FilePropertiesMaven,
            "generic": FilePropertiesGeneric,
        }
        if p_type in dispatch:
            fp = dispatch[p_type](
                cli_args=self.cli_args,
                file=afp.get_file(),
                artifactory_api=self.artifactory_api,
            )
        else:
            fp = FilePropertiesDefault(
                cli_args=self.cli_args,
                file=afp.get_file(),
                artifactory_api=self.artifactory_api,
            )

        afp.set_file_properties(fp=fp)

    def _get_my_afp(
        self,
        repo: ArtifactoryRepoInfo,
        p_type: str,
        artifact_item: dict[str, Any],
        repo_db: dict[str, Any],
    ) -> ArtifactoryFileProcessorCommon:
        dispatch = {
            "docker": ArtifactoryFileProcessorDocker,
            "generic": ArtifactoryFileProcessorGeneric,
        }

        if p_type in dispatch:
            afp = dispatch[p_type](
                cli_args=self.cli_args,
                spectra_assure_api=self.spectra_assure_api,
                artifactory_api=self.artifactory_api,
                repo=repo,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )
        else:
            afp = ArtifactoryFileProcessorDefault(
                cli_args=self.cli_args,
                spectra_assure_api=self.spectra_assure_api,
                artifactory_api=self.artifactory_api,
                repo=repo,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )

        self._add_fp(
            p_type=p_type,
            afp=afp,
        )

        return afp

    def _print_info_report(
        self,
        afp: ArtifactoryFileProcessorCommon,
        start: Any,
    ) -> None:
        info = afp.processing_info
        logger.debug("%s", info)

        if not self.verbose:
            return

        zz = [
            # self._now_string_compact(),
            f"{afp.file.repo.name}::{afp.uri}",
            f"processed: {info.completed}",
            f"status: {info.status}",
        ]

        if info.scan_state:
            zz.append(f"scan_status: {info.scan_state}")

        if info.reason:
            zz.append(f"reason: {info.reason}")

        if info.purl:
            zz.append(f"pUrl: {info.purl}")

        if info.report:
            zz.append(f"report: {self._full_report_url(afp, info.report)}")

        elapsed = time.time() - start
        mm = int(elapsed / 60)
        ss = "%2.0f" % (elapsed % 60)
        elapsed_str = f"took: {mm}m {ss}s"
        zz.append(elapsed_str)

        msg = f"{'; '.join(zz)}"
        self.my_print(msg)

    @staticmethod
    def _full_report_url(
        afp: ArtifactoryFileProcessorCommon,
        report: str,
    ) -> str:
        """A stored report that is a path is completed with the portal it came from.

        Only a portal run can do that: a cli run has no portal, and its reports
        live in artifactory, so whatever was stored is already the whole answer.
        A cli run over a repository an earlier portal run had scanned used to
        raise here, which cost that artifact.
        """
        if "https://" in report:
            return report

        if afp.what_backend != "portal":
            return report

        base = afp._portal_make_report_base()
        return f"{base}/{report}"

    def _run_one_repo_one_artifact(
        self,
        repo: ArtifactoryRepoInfo,
        p_type: str,
        artifact_item: dict[str, Any],
        repo_db: dict[str, Any],
    ) -> str:
        """
        Inspect one artifact file

        params:
        - repo:     what is the repo we are currently processing.
        - p_type:   what is the package_type.
        - artifact_item: the info artifactory has for this artifact s dict.
        - repo_db:  a place we can collect data that may be useful for other artifacts
            e.g. docker images consist of multiple files in a tree
            we can also use it to collect meta files for p_type: `generic`
        """
        start: float = time.time()

        afp = self._get_my_afp(  # ArtifactoryFileProcessor
            p_type=p_type,
            repo=repo,
            artifact_item=artifact_item,
            repo_db=repo_db,
        )

        uri = artifact_item.get("uri", "")
        portal_mode = self.cli_args.get("portal") is True
        uri_l = uri.lower()

        if uri_l.endswith(META_STRING) and not portal_mode:
            # in portal mode meta files are mandatory and stand for real files;
            # a cli run does not scan them, but still cleans them (R10.9.5)
            logger.debug("skip meta %s", uri_l)
            return self._remove_obsolete_properties_of_skipped(repo=repo, uri=uri, afp=afp)

        if uri_l.endswith(CLI_REPORTS_FILE_TAIL):
            logger.debug("skip report file %s", uri_l)
            return PROCESS_FILE_SKIP

        msg = f"Inspecting {repo.name}:{uri}"
        self.my_print(msg)

        try:
            if not self.cli_args.get("keep_obsolete_properties"):
                afp.remove_obsolete_properties()

            completed = afp.process()
            if completed is False and portal_mode:
                self.not_finished.append(afp)  # save for later inspection

            self._print_info_report(
                afp=afp,
                start=start,
            )
        except Exception as e:
            # one bad artifact must never end the run: the repository holds data we
            # do not control, so log what failed and carry on with the next item
            self.failed_items.append((repo.name, uri))
            logger.exception("FAIL: %s:%s; %s: %s", repo.name, uri, type(e).__name__, e)

            msg = f"FAIL: {repo.name}:{uri}; {type(e).__name__}: {e}"
            self.my_print(msg)
            return PROCESS_FILE_FAILED
        finally:
            afp.remove_my_files()

        return afp.get_process_status()

    def _remove_obsolete_properties_of_skipped(
        self,
        *,
        repo: ArtifactoryRepoInfo,
        uri: str,
        afp: Any,
    ) -> str:
        """An item that is not processed is still cleaned (R10.9.1), with the same containment."""
        if self.cli_args.get("keep_obsolete_properties"):
            return PROCESS_FILE_SKIP

        try:
            afp.remove_obsolete_properties()
        except Exception as e:
            self._record_failed_item(repo=repo, uri=uri, e=e)
            return PROCESS_FILE_FAILED

        return PROCESS_FILE_SKIP

    def _clean_report(
        self,
        *,
        repo: ArtifactoryRepoInfo,
        artifact_item: dict[str, Any],
    ) -> None:
        """A report bundle carries only RL.noscan (R10.9.6); it is never processed.

        Read and cleaned here rather than through a file processor: a report has
        no purl, layout or side-car of its own for one to work with.
        """
        if self.cli_args.get("keep_obsolete_properties"):
            return

        uri = artifact_item.get("uri", "")
        report = FileInfo(
            repo=repo,
            uri=uri,
            sha1=str(artifact_item.get("sha1")),
            sha2=str(artifact_item.get("sha2")),
            last_modified=artifact_item.get("lastModified", ""),
            file_name=os.path.basename(uri),
        )

        try:
            properties = self.artifactory_api.get_item_properties(file=report)
            obsolete = obsolete_property_names(properties, maintained=())
            for key in obsolete:
                self.artifactory_api.del_one_prop(repo=repo, item_uri=uri, key=key)
        except Exception as e:
            self._record_failed_item(repo=repo, uri=uri, e=e)
            return

        if obsolete:
            logger.info("%s:%s; removed obsolete properties: %s", repo.name, uri, ", ".join(obsolete))

    def _record_failed_item(
        self,
        *,
        repo: ArtifactoryRepoInfo,
        uri: str,
        e: Exception,
    ) -> None:
        self.failed_items.append((repo.name, uri))
        logger.exception("FAIL: %s:%s; %s: %s", repo.name, uri, type(e).__name__, e)

        msg = f"FAIL: {repo.name}:{uri}; {type(e).__name__}: {e}"
        self.my_print(msg)

    @staticmethod
    def _is_unsupported_repo_type(
        repo: ArtifactoryRepoInfo,
    ) -> bool:
        """Only a local repo, or the cache of a remote one, can hold our properties.

        A remote repository is handled as usual: we simply address its cache
        (see ArtifactoryApi._storage_repo_name), which is what the integration
        has always done, so there is nothing to skip and nothing to announce.

        A virtual repo stacks a local over a remote, so it has no storage identity
        of its own to annotate, and is refused.

        An empty type means we never read the configuration at all; that is not a
        type problem and is reported separately by the caller.
        """
        if not repo.repo_type:
            return False

        return repo.repo_type.lower() not in WRITABLE_REPO_TYPES

    def _is_cli_and_remote_and_no_reports_location_specified(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> bool:

        return bool(
            self.cli_args.get("cli") is True
            and repo.repo_type == "remote"
            and self.cli_args.get("cli_reports_repo") is None
        )

    def _is_cli_and_local_and_current_repo_is_reports_location(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> bool:
        return bool(
            self.cli_args.get("cli") is True
            and repo.repo_type == "local"
            and self.cli_args.get("cli_reports_repo") is not None
            and repo.name == self.cli_args.get("cli_reports_repo")
        )

    def _is_cli_and_uri_ends_with_reports_tail(
        self,
        uri: str,
    ) -> bool:
        if self.cli_args.get("cli") is True and uri.lower().endswith(CLI_REPORTS_FILE_TAIL):
            return True

        # during internal testing we mix portal and cli in the same artifactory instance
        # so skip the report tails always
        return bool(uri.lower().endswith(CLI_REPORTS_FILE_TAIL))

    def _repo_generic_extract_rl_meta_info(
        self,
        arp: ArtifactoryRepoProcessor,
        repo_db: dict[str, Any],
    ) -> None:
        """Find all files ending in .rl_meta and extract the meta info"""
        repo = arp.get_repo()
        p_type = arp.p_type

        for artifact_item in arp.process():
            uri = artifact_item.get("uri", "")
            if not uri.lower().endswith(META_STRING):
                continue

            afp = self._get_my_afp(  # ArtifactoryFileProcessor
                p_type=p_type,
                repo=repo,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )

            zz = afp.extract_generic_meta_info()
            meta = zz.get("meta")

            msg = f"Uri: {uri} -> {zz}"
            if meta is not None and meta.get("path"):
                k = "/"
                uri_path = k.join(uri.split(k)[:-1])
                file = uri_path + k + meta["path"]
                # the hash of the file described, to compare with the portal's (R10.7.4)
                zz["sha2"] = arp.sha2_by_uri.get(file)
                # set the path of the file in the meta to the same path as the current meta file
                repo_db[file] = zz
                repo_db.setdefault(REPO_DB_DESCRIBED_BY_SIDE_CAR, {})[uri] = file
                msg = f"Uri: {uri} -> {file} {zz}"

            logger.debug(msg)
            logger.debug("%s %s", uri, zz)

    def _repo_docker_extract_list_manifest_info(
        self,
        arp: ArtifactoryRepoProcessor,
        repo_db: dict[str, Any],
    ) -> None:
        """Find all list.manifest.json files and collect their per architecture digests.

        This must run before the main loop: a multi architecture image stores each
        architecture under a sha256__<hex> directory, and the manifest.json in there can
        only recover its real tag from the list.manifest.json that names the digest.
        Artifactory does not guarantee an order, and 'sha256__' sorts before common tags
        such as 'v1.2.3', so relying on the main loop to reach the list first would give
        those images a digest as their purl version.
        """
        repo = arp.get_repo()
        p_type = arp.p_type

        for artifact_item in arp.process():
            uri = artifact_item.get("uri", "")
            if not uri.lower().endswith(DOCKER_LIST_MANIFEST_FILE):
                continue

            afp = self._get_my_afp(  # ArtifactoryFileProcessor
                p_type=p_type,
                repo=repo,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )

            logger.debug("collect list manifest info: %s", uri)
            afp.collect_list_manifest_info()

    def _run_one_repo_all_artifacts(
        self,
        repo_name: str,
    ) -> None:
        """Process every artifact in one repository."""
        self.my_print(f"Start processing repo: {repo_name}")

        arp = ArtifactoryRepoProcessor(
            cli_args=self.cli_args,
            spectra_assure_api=self.spectra_assure_api,
            artifactory_api=self.artifactory_api,
            repo_name=repo_name,
        )
        repo = arp.get_repo()

        skip = self._why_skip_this_repo(repo)
        if skip is not None:
            self._report_repo_skipped(repo, skip)
            return

        # the repo_db collects what items need from each other: docker manifest
        # lists, and the .rl_meta side-cars of a generic repository
        repo_db: dict[str, Any] = {}
        self._collect_repo_db(arp=arp, repo_db=repo_db)

        self._process_repo_items(arp=arp, repo=repo, repo_db=repo_db)

    def _why_skip_this_repo(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> tuple[str, bool] | None:
        """The reason not to process this repository, and whether it is verbose only.

        None to carry on. The two repository problems are always announced; the
        two that are a consequence of how this run was invoked are only announced
        with --verbose, because a run over many repositories would otherwise
        repeat them for each one.
        """
        if not repo.repo_type:
            # we never got a configuration back for this name; this is the only
            # message about it, and the status the server gave is at debug in
            # get_repo_info
            return "repository does not exist, or we may not read its configuration", False

        if self._is_unsupported_repo_type(repo):
            t = " ".join(
                [
                    f"only {', '.join(WRITABLE_REPO_TYPES)} repositories are supported:",
                    "we cannot write our properties to this repository type",
                ],
            )
            return t, False

        if self._is_cli_and_remote_and_no_reports_location_specified(repo):
            t = "processing with cli is not supported, missing report location: we cannot upload the report"
            return t, True

        if self._is_cli_and_local_and_current_repo_is_reports_location(repo):
            t = "if option 'cli_reports_repo' is given, that local repo will not be scanned"
            return t, True

        return None

    def _report_repo_skipped(
        self,
        repo: ArtifactoryRepoInfo,
        skip: tuple[str, bool],
    ) -> None:
        reason, verbose_only = skip

        what = repo.name if not repo.repo_type else f"{repo.name} {repo.repo_type}"
        msg = f"REPO SKIP: {what}; {reason}"
        logger.warning(msg)

        if verbose_only and not self.verbose:
            return

        self.my_print(f"{self._now_string_compact()}; {msg}")

    def _collect_repo_db(
        self,
        arp: ArtifactoryRepoProcessor,
        repo_db: dict[str, Any],
    ) -> None:
        """Read what the main loop will need before it starts.

        Both passes list the whole repository, which is why they run once here
        rather than per item.
        """
        if arp.p_type == "generic":
            # lets extract all meta files we can find
            self._repo_generic_extract_rl_meta_info(arp, repo_db)

        if arp.p_type == "docker":
            # multi architecture docker images need their list.manifest.json read first
            self._repo_docker_extract_list_manifest_info(arp, repo_db)

    def _process_repo_items(
        self,
        arp: ArtifactoryRepoProcessor,
        repo: ArtifactoryRepoInfo,
        repo_db: dict[str, Any],
    ) -> None:
        """Every artifact in the repository, up to the development limit if one is set."""
        processed = 0

        for artifact_item in arp.process():
            uri = artifact_item.get("uri", "")
            if self._is_cli_and_uri_ends_with_reports_tail(uri=uri):
                self._clean_report(repo=repo, artifact_item=artifact_item)
                continue

            logger.debug("%s", uri)

            reason = self._run_one_repo_one_artifact(
                repo=repo,
                p_type=arp.p_type,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )
            if reason not in {PROCESS_FILE_SKIP}:
                processed += 1

            if self._development_limit_reached(processed):
                break

    def _development_limit_reached(
        self,
        processed: int,
    ) -> bool:
        """WITH_TEST_LIMIT_REPO_TO stops a run early while developing.

        It counts artifacts that were actually processed, not artifacts seen, so
        a repository full of skipped items still reaches the ones that matter.
        """
        if self.WITH_TEST_LIMIT_REPO_TO == 0:
            return False

        if processed < self.WITH_TEST_LIMIT_REPO_TO:
            return False

        logger.info(
            "limit reached: WITH_TEST_LIMIT_REPO_TO: %d",
            self.WITH_TEST_LIMIT_REPO_TO,
        )
        return True

    def _finish_any_pending(
        self,
    ) -> None:
        for afp in self.not_finished:
            afp.max_time = 60 * 60 * 2  # wait max 2 hours on retry

            if self.verbose:
                msg = f"processing not finished item: {afp.get_uri()}"
                self.my_print(msg)

            start: float = time.time()
            uri = afp.get_uri()
            try:
                afp.process()

                self._print_info_report(
                    afp=afp,
                    start=start,
                )
            except Exception as e:
                self.failed_items.append(("", uri))
                logger.exception("FAIL pending item: %s; %s: %s", uri, type(e).__name__, e)
                self.my_print(f"FAIL pending item: {uri}; {type(e).__name__}: {e}")
            finally:
                afp.remove_my_files()

    def _if_print_version_and_exit(self) -> None:
        if self.cli_args.get("version", "") is True:
            msg = f"version: {VERSION}"
            self.my_print(msg)
            sys.exit(0)

    def _verify_portal_connect(self) -> None:
        """
        Connect to the portal with server org and group,

        make sure they exist
        """
        if self.spectra_assure_api is None:
            msg = "spectra_assure_api is not initialized."
            raise RuntimeError(msg)

        try:
            rr = self.spectra_assure_api.api_client.list()
            data = rr.json()  # expect >= 0 results (projects)
            logger.debug("list projects: %s", data)
        except Exception:
            logger.exception("no valid result from list projects")
            msg = "Fatal: Server, Org and Group parameter check failed, please verify their correctness."
            logger.error(msg)
            sys.exit(EXIT_FATAL)

    # PUBLIC
    def _verify_cli_usable(
        self,
    ) -> None:
        """Is the local rl-secure installation usable, before we download anything?

        The scanner used to find this out per artifact, in its constructor, which
        runs after that artifact has been downloaded. A broken installation then
        cost one download per item in the repository before it complained.

        Only the local cli: the docker backend pulls its scanner image, and
        checking that here would mean a pull before the run.
        """
        if self.cli_args.get("cli") is not True:
            return
        if self.cli_args.get("cli_docker") is True:
            return

        reason = ScanCliLocal.preflight(
            rlsecure_path=self.cli_args.get("cli_rlsecure_path", ""),
            store=self.cli_args.get("cli_rlstore_path"),
        )
        if reason is None:
            return

        raise SpectraAssureInvalidAction(reason)

    def run_all(
        self,
    ) -> None:
        self._if_print_version_and_exit()
        self.not_finished = []
        if self.cli_args.get("portal") is True:
            self._verify_portal_connect()

        self._verify_cli_usable()

        version = self.artifactory_api.get_artifactory_version()
        self.cli_args["_artifactory_version"] = version
        logger.debug("artifactory_version: %s", version)

        repo_names = self.cli_args.get("repo", [])
        try:
            for repo_name in repo_names:
                try:
                    self._run_one_repo_all_artifacts(repo_name)
                except Exception as e:
                    # a broken repo must not cost us the repos after it
                    self.failed_repos.append(repo_name)
                    logger.exception("FAIL REPO: %s; %s: %s", repo_name, type(e).__name__, e)
                    self.my_print(f"FAIL REPO: {repo_name}; {type(e).__name__}: {e}")
        finally:
            # pending items hold portal scans we already paid for and downloads we still
            # have to clean up, so finish them even when the run above went wrong
            if self.cli_args.get("portal") is True:
                self._finish_any_pending()

        self._report_failures()

    def _report_failures(
        self,
    ) -> None:
        if not self.failed_items and not self.failed_repos:
            return

        for repo_name in self.failed_repos:
            logger.error("repo could not be processed: %s", repo_name)

        for repo_name, uri in self.failed_items:
            logger.error("item could not be processed: %s:%s", repo_name, uri)

        msg = (
            f"finished with {len(self.failed_items)} failed item(s)"
            f" and {len(self.failed_repos)} failed repo(s); see the log for details"
        )
        logger.error(msg)
        self.my_print(msg)

    # PUBLIC
    def get_exit_code(
        self,
    ) -> int:
        """EXIT_OK, or EXIT_ITEM_FAILURES when the run finished but something was skipped.

        Non zero is the default because exiting 0 after silently skipping
        artifacts is how under scanning goes unnoticed. A pipeline that would
        rather treat a partial run as success asks for that with
        --ignore-skipped; the failures are logged and summarised either way, so
        the information is not lost, only the exit code changes.
        """
        if not (self.failed_items or self.failed_repos):
            return EXIT_OK

        if self.cli_args.get("ignore_skipped") is True:
            logger.warning(
                "exiting 0 because --ignore-skipped was given: %d item(s) and %d repo(s) were skipped",
                len(self.failed_items),
                len(self.failed_repos),
            )
            return EXIT_OK

        return EXIT_ITEM_FAILURES
