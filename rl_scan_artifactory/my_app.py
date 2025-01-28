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
        self.artifactory_api = ArtifactoryApi(args=args)
        self.spectra_assure_api = SpectraAssureApi(args=args)
        self.verbose = self.cli_args["verbose"]
        self.WITH_TEST_LIMIT_REPO_TO = int(os.getenv("WITH_TEST_LIMIT_REPO_TO", 0))
        self.not_finished: List[ArtifactoryFileProcessorCommon] = []

        logger.debug("%s", args.cli_args)

        self.proxies: Dict[str, str] = set_proxy(
            server=self.cli_args.get("proxy_server"),
            port=self.cli_args.get("proxy_port"),
            user=self.cli_args.get("proxy_user"),
            password=self.cli_args.get("proxy_password"),
        )

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
                base = afp.make_report_base()
                report = f"{base}/{report}"

            zz.append(f"report: {report}")

        elapsed = time.time() - start
        elapsed_str = f"took: {int(elapsed / 60)}m %2.0fs" % (elapsed % 60)
        zz.append(elapsed_str)
        print(f"{'; '.join(zz)}")

    def _run_one_repo_one_artifact(
        self,
        repo: ArtifactoryRepoInfo,
        p_type: str,
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],
    ) -> str:
        logger.debug("%s", p_type)
        portal_mode = self.cli_args.get("portal") is True

        start: float = time.time()
        afp = self._get_my_afp(  # ArtifactoryFileProcessor
            p_type=p_type,
            repo=repo,
            artifact_item=artifact_item,
            repo_db=repo_db,
        )

        if artifact_item.get("uri", "").lower().endswith(META_STRING) and not portal_mode:
            # in portal mode mate files stand for real files so we need them
            logger.debug("skip meta %s", artifact_item.get("uri", ""))
            return PROCESS_FILE_SKIP

        if artifact_item.get("uri", "").lower().endswith(CLI_REPORTS_FILE_TAIL):
            logger.debug("skip report file %s", artifact_item.get("uri", ""))
            return PROCESS_FILE_SKIP

        print(f"Inspecting {repo.name}:{artifact_item.get('uri', '')}")

        completed = afp.process()

        if portal_mode:
            if completed is False:  # TODO: fix_not scanned for exists on portal and exists on artifactory
                self.not_finished.append(afp)

        self._print_info_report(
            afp=afp,
            start=start,
        )

        logger.debug("%s", afp.files_to_remove)
        afp.remove_my_files()

        return afp.get_process_status()

    def _run_one_repo_all_artifacts(  # noqa: C901
        self,
        repo_name: str,
    ) -> None:
        msg = f"Start processing repo: {repo_name}"
        logger.info(msg)
        print(msg)

        arp = ArtifactoryRepoProcessor(
            cli_args=self.cli_args,
            spectra_assure_api=self.spectra_assure_api,
            artifactory_api=self.artifactory_api,
            repo_name=repo_name,
        )
        repo = arp.get_repo()
        p_type = arp.p_type

        if self.cli_args.get("cli") is True:
            if repo.repo_type == "remote":
                if self.cli_args.get("cli_reports_repo") is None:
                    t = "processing with cli is not supported, we cannot upload the report"
                    msg = f"REPO SKIP: {repo.name} {repo.repo_type}; {t}"
                    logger.warning(msg)
                    if self.verbose:
                        zz = [self._now_string_compact(), msg]
                        print(f"{'; '.join(zz)}")
                    return

            if repo.repo_type == "local":
                if self.cli_args.get("cli_reports_repo") is not None:
                    if repo.name == self.cli_args.get("cli_reports_repo"):
                        t = "if option 'cli_reports_repo' is given, that local repo will not be scanned"
                        msg = f"REPO SKIP: {repo.name} {repo.repo_type}; {t}"
                        logger.warning(msg)
                        if self.verbose:
                            zz = [self._now_string_compact(), msg]
                            print(f"{'; '.join(zz)}")
                        return

        # ----------------------------------------
        n = 0
        repo_db: Dict[str, Any] = {}
        for artifact_item in arp.process():
            if self.cli_args.get("cli") is True and artifact_item.get("uri", "").lower().endswith(
                CLI_REPORTS_FILE_TAIL
            ):
                continue

            if artifact_item.get("uri", "").lower().endswith(CLI_REPORTS_FILE_TAIL):
                # during internal testing we mix portal and cli in the same artifactory instance so skip the reports
                continue

            logger.debug("%s", artifact_item.get("uri", "").lower())

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

    def finish_any_pending(
        self,
    ) -> None:
        for afp in self.not_finished:
            afp.max_time = 60 * 60 * 2  # wait max 2 hours on retry

            if self.verbose:
                print(f"processing not finished item: {afp.get_uri()}")

            start: float = time.time()
            afp.process()
            afp.remove_my_files()  # later add as destructor

            self._print_info_report(
                afp=afp,
                start=start,
            )

    def run_all(
        self,
    ) -> None:
        if self.cli_args.get("version", "") is True:
            logger.info("version: %s", VERSION)
            print(f"Version: {VERSION}")
            sys.exit(0)

        self.not_finished = []

        repo_names = self.cli_args.get("repo", [])
        for repo_name in repo_names:
            self._run_one_repo_all_artifacts(repo_name)

        if self.cli_args.get("portal") is True:
            self.finish_any_pending()
