# python3 ts=4space
import logging
import os
import sys
import time

from typing import (
    Any,
    List,
    Dict,
)

from .app_base_with_logging import AppBaseWithLogging
from .artifactory_api import ArtifactoryApi
from .artifactory_file_processor import (
    ArtifactoryFileProcessorCommon,
    ArtifactoryFileProcessorDefault,
    ArtifactoryFileProcessorDocker,
    ArtifactoryFileProcessorGeneric,  # artifactory generic package_type
)
from .artifactory_repo_info import ArtifactoryRepoInfo
from .artifactory_repo_processor import ArtifactoryRepoProcessor
from .constants import (
    PROCESS_FILE_SKIP,
    CLI_REPORTS_FILE_TAIL,
    META_STRING,
)
from .file_properties import (
    FilePropertiesDefault,
    FilePropertiesDocker,
    FilePropertiesMaven,
    FilePropertiesNuget,
    FilePropertiesRpm,
    FilePropertiesGeneric,
)
from .helpers import set_proxy
from .my_args import MyArgs
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
        self.WITH_TEST_LIMIT_REPO_TO = int(os.getenv("WITH_TEST_LIMIT_REPO_TO", 0))
        self.not_finished: List[ArtifactoryFileProcessorCommon] = []

        self.proxies: Dict[str, str] = set_proxy(
            server=self.cli_args.get("proxy_server"),
            port=self.cli_args.get("proxy_port"),
            user=self.cli_args.get("proxy_user"),
            password=self.cli_args.get("proxy_password"),
        )

    def my_print(self, msg: str) -> None:
        logger.info(msg)
        print(msg)

    @staticmethod
    def _now_string_compact() -> str:
        time_format = "%G-%m-%dT%H:%M:%S%z"
        now = time.localtime()
        return time.strftime(time_format, now)

    def _validate_params(
        self,
    ) -> None:
        self.repo_list = self.cli_args["repo"]
        assert len(self.repo_list) > 0

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
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],
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
            report = info.report
            if "https://" not in report:
                base = afp._portal_make_report_base()
                report = f"{base}/{report}"
            zz.append(f"report: {report}")

        elapsed = time.time() - start
        elapsed_str = f"took: {int(elapsed / 60)}m %2.0fs" % (elapsed % 60)
        zz.append(elapsed_str)

        msg = f"{'; '.join(zz)}"
        self.my_print(msg)

    def _run_one_repo_one_artifact(
        self,
        repo: ArtifactoryRepoInfo,
        p_type: str,
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],
    ) -> str:
        """
        inspect one artifact file

        params:
        - repo:     what is the repo we are currently processing.
        - p_type:   what is the package_type.
        - artifact_item: the info artifactory has for this artifact s dict.
        - repo_db:  a place we can collect data that may be usefull for other artifacts
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
            # in portal mode meta files are mandatory and stand for real files
            logger.debug("skip meta %s", uri_l)
            return PROCESS_FILE_SKIP

        if uri_l.endswith(CLI_REPORTS_FILE_TAIL):
            logger.debug("skip report file %s", uri_l)
            return PROCESS_FILE_SKIP

        msg = f"Inspecting {repo.name}:{uri}"
        self.my_print(msg)

        completed = afp.process()
        if completed is False:
            if portal_mode:
                self.not_finished.append(afp)  # save for later inspection

        self._print_info_report(
            afp=afp,
            start=start,
        )

        afp.remove_my_files()

        return afp.get_process_status()

    def _is_portal_and_remote_and_no_reports_location_specified(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> bool:
        if self.cli_args.get("portal") is True:
            if repo.repo_type == "remote":
                if self.cli_args.get("cli_reports_repo") is None:
                    return True
        return False

    def _is_cli_and_remote_and_no_reports_location_specified(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> bool:
        if self.cli_args.get("cli") is True:
            if repo.repo_type == "remote":
                if self.cli_args.get("cli_reports_repo") is None:
                    return True
        return False

    def _is_cli_and_local_and_current_repo_is_reports_location(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> bool:
        if self.cli_args.get("cli") is True:
            if repo.repo_type == "local":
                if self.cli_args.get("cli_reports_repo") is not None:
                    if repo.name == self.cli_args.get("cli_reports_repo"):
                        return True
        return False

    def _is_cli_and_uri_ends_with_reports_tail(
        self,
        uri: str,
    ) -> bool:
        if self.cli_args.get("cli") is True:
            if uri.lower().endswith(CLI_REPORTS_FILE_TAIL):
                return True

        if uri.lower().endswith(CLI_REPORTS_FILE_TAIL):
            # during internal testing we mix portal and cli in the same artifactory instance
            # so skip the report tails always
            return True

        return False

    def _repo_generic_extract_rl_meta_info(
        self,
        arp: ArtifactoryRepoProcessor,
        repo_db: Dict[str, Any],
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
            if meta is not None:
                if meta.get("path"):
                    k = "/"
                    uri_path = k.join(uri.split(k)[:-1])
                    file = uri_path + k + meta["path"]
                    # set the path of the file in the meta to the same path as the current meta file
                    repo_db[file] = zz
                    msg = f"Uri: {uri} -> {file} {zz}"

            logger.debug(msg)
            logger.debug("%s %s", uri, zz)

    def _run_one_repo_all_artifacts(  # noqa: C901
        self,
        repo_name: str,
    ) -> None:
        msg = f"Start processing repo: {repo_name}"
        self.my_print(msg)

        arp = ArtifactoryRepoProcessor(
            cli_args=self.cli_args,
            spectra_assure_api=self.spectra_assure_api,
            artifactory_api=self.artifactory_api,
            repo_name=repo_name,
        )
        repo = arp.get_repo()
        p_type = arp.p_type

        # for portal we only store a report url st that works as property
        # for cli we upload reports, that only works on local so if we are remote we need a report location

        if self._is_cli_and_remote_and_no_reports_location_specified(repo):
            t = "processing with cli is not supported, missing report location: we cannot upload the report"
            msg = f"REPO SKIP: {repo.name} {repo.repo_type}; {t}"
            logger.warning(msg)
            if self.verbose:
                zz = [self._now_string_compact(), msg]
                msg = f"{'; '.join(zz)}"
                self.my_print(msg)
            return

        if self._is_cli_and_local_and_current_repo_is_reports_location(repo):
            t = "if option 'cli_reports_repo' is given, that local repo will not be scanned"
            msg = f"REPO SKIP: {repo.name} {repo.repo_type}; {t}"
            logger.warning(msg)
            if self.verbose:
                zz = [self._now_string_compact(), msg]
                msg = f"{'; '.join(zz)}"
                self.my_print(msg)
            return

        # ----------------------------------------
        # the repo_db can collect info on items we need later: docker json files
        # we can also collect meta files for cli and generic
        repo_db: Dict[str, Any] = {}

        # lets extract all meta files we can find
        if p_type == "generic":
            self._repo_generic_extract_rl_meta_info(arp, repo_db)

        n = 0
        for artifact_item in arp.process():
            uri = artifact_item.get("uri", "")
            if self._is_cli_and_uri_ends_with_reports_tail(uri=uri):
                continue

            logger.debug("%s", uri)

            reason = self._run_one_repo_one_artifact(
                repo=repo,
                p_type=p_type,
                artifact_item=artifact_item,
                repo_db=repo_db,
            )

            if reason not in [PROCESS_FILE_SKIP]:
                n += 1

            if self.WITH_TEST_LIMIT_REPO_TO == 0:
                continue

            if n < self.WITH_TEST_LIMIT_REPO_TO:
                continue

            logger.info(
                "limit reached: WITH_TEST_LIMIT_REPO_TO: %d",
                self.WITH_TEST_LIMIT_REPO_TO,
            )
            break

    def _finish_any_pending(
        self,
    ) -> None:
        for afp in self.not_finished:
            afp.max_time = 60 * 60 * 2  # wait max 2 hours on retry

            if self.verbose:
                msg = f"processing not finished item: {afp.get_uri()}"
                self.my_print(msg)

            start: float = time.time()
            afp.process()
            afp.remove_my_files()

            self._print_info_report(
                afp=afp,
                start=start,
            )

    def _if_print_version_and_exit(self) -> None:
        if self.cli_args.get("version", "") is True:
            msg = f"version: {VERSION}"
            self.my_print(msg)
            sys.exit(0)

    def _verify_portal_connect(self) -> None:
        """connect to the portal with server org and group,
        assert they exist
        """
        assert self.spectra_assure_api is not None
        try:
            rr = self.spectra_assure_api.api_client.list()
            data = rr.json()  # expect >= 0 results (projects)
            logger.debug("list projects: %s", data)
        except Exception as e:
            logger.exception("no valid result from list projects: %s", e)
            msg = "Fatal: Server, Org and Group parameter check failed, please verify their correctness."
            logger.error(msg)
            print(msg)
            sys.exit(101)
        return

    # PUBLIC
    def run_all(
        self,
    ) -> None:
        self._if_print_version_and_exit()
        self.not_finished = []
        if self.cli_args.get("portal") is True:
            self._verify_portal_connect()

        version = self.artifactory_api.get_artifactory_version()
        self.cli_args["_artifactory_version"] = version
        logger.debug("artifactory_version: %s", version)

        repo_names = self.cli_args.get("repo", [])
        for repo_name in repo_names:
            self._run_one_repo_all_artifacts(repo_name)

        if self.cli_args.get("portal") is True:
            self._finish_any_pending()
