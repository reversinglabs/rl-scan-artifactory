# python3 ts=4space
import logging
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..constants import (
    PROCESS_FILE_SKIP,
    PROGRESS_ALL,
    PROGRESS_SCANNED,
    SCAN_STATUS_ALL,
)
from ..exceptions import (
    SpectraAssureInvariantError,
)
from ..spectra_assure_api import SpectraAssureApi
from .artifactory_file_processor_common import ArtifactoryFileProcessorCommon

logger = logging.getLogger(__name__)


class ArtifactoryFileProcessorDefault(
    ArtifactoryFileProcessorCommon,
):
    def __init__(
        self,
        *,
        cli_args: dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: dict[str, Any],
        repo_db: dict[str, Any],  # pass info between file processing; docker list.manifest.json currently
    ) -> None:
        super().__init__(
            cli_args=cli_args,
            spectra_assure_api=spectra_assure_api,
            artifactory_api=artifactory_api,
            repo=repo,
            artifact_item=artifact_item,
            repo_db=repo_db,
        )

    def _process_portal(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

        purl = self.purl_info.make_purl()
        # ---------------------------------
        # has this file been uploaded already to the portal?
        exists_on_portal, scan_status, report = self._exists_on_portal(
            project=project,
            package=package,
            version=version,
            digest=self.file.sha2,
        )

        if exists_on_portal is True:
            progress = self.get_prop_progress()
            is_uploaded = True

            self.processing_info.purl = purl
            self.processing_info.reason = "purl exists on portal"

            sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime
            if sync_requested is False:
                self.processing_info.status = PROCESS_FILE_SKIP
                self.processing_info.scan_state = scan_status
                self.processing_info.report = report

                if progress == PROGRESS_SCANNED and scan_status in SCAN_STATUS_ALL:
                    self.processing_info.completed = True
                    return True
            else:
                self.processing_info.reason = "portal-sync"
                sync_started = self._purl_sync_portal()
                if sync_started is None:
                    self.processing_info.completed = True
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = None
                    self.processing_info.report = None
                    self.processing_info.purl = self.get_prop_purl()
                    self.processing_info.reason = "request to sync failed"
                    return True

        else:
            # download_upload_default()
            progress = None
            if self.cli_args.get("ignore_artifactory_properties") is False:
                progress = self.get_prop_progress()  # may return ""

            is_uploaded = False
            if progress in PROGRESS_ALL:
                is_uploaded = self._handle_progress_present_on_artifactory(progress=progress)

            if is_uploaded is False:
                is_uploaded = self._file_download_upload_common()

            if is_uploaded is False:
                logger.info("skip: %s::%s", self.file.repo.name, self.uri)
                return True

        return self._wait_then_upload_if_the_portal_has_no_such_version()

    def _wait_then_upload_if_the_portal_has_no_such_version(
        self,
    ) -> bool:
        """Wait for the scan; if the portal has no such version, upload and wait again.

        RL.progress does not record which backend wrote it, so a `scanned` written
        by a cli run makes this one believe the portal already has the artifact.
        It then waits for a scan of a version the portal has never seen. The portal
        is the only thing that knows, and it has now said no three times, so the
        property was about something else and the artifact still has to be
        uploaded.
        """
        completed = self._wait_for_scan_status_one_portal()
        if completed is not None:
            return completed

        logger.warning(
            "%s:%s; uploading it now: what artifactory recorded was not about this portal",
            self.file.repo.name,
            self.uri,
        )

        if self._file_download_upload_common() is False:
            logger.info("skip: %s::%s", self.file.repo.name, self.uri)
            return True

        return bool(self._wait_for_scan_status_one_portal())

    def _process_cli(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        if self.what_backend != "cli":
            msg = "expected self.what_backend == 'cli'"
            raise SpectraAssureInvariantError(msg)
        return self.do_cli_scan_or_sync(
            project=project,
            package=package,
            version=version,
        )

    # PUBLIC

    def process(
        self,
    ) -> bool:
        self.processing_info.completed = False
        self.processing_info.reason = None
        self.processing_info.status = None
        self.processing_info.scan_state = None
        self.processing_info.report = None
        self.processing_info.purl = None

        if self.fp is None:
            msg = "expected self.fp is not None"
            raise SpectraAssureInvariantError(msg)
        skip_candidate = self.fp.skip_non_candidate_file()
        if skip_candidate:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            self.processing_info.reason = "not a candidate file"
            return True

        # we have a candidate but is was already scanned
        # if the scan date is older then 2 weeks schedule a sync instead of a scan # TODO
        if self.cli_args.get("ignore_artifactory_properties") is False:
            if self.get_prop_progress() == PROGRESS_SCANNED:
                if self.sync_possible() is False:
                    self.processing_info.completed = True
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = self.get_prop_progress()
                    self.processing_info.report = self.get_prop_report()
                    self.processing_info.purl = self.get_prop_purl()
                    self.processing_info.reason = "properties already exist in artifactory"
                    return True

                # we can do a sync instead of a scan
                self.need_sync_datetime = True
                # return True
        # -----------------------------
        # get the purl components
        project, package, version = self.get_purl_from_name_mangler(
            p_type=self.p_type,
        )
        self._populate_purl_info(project, package, version)

        if self.what_backend == "portal":
            return self._process_portal(
                project=project,
                package=package,
                version=version,
            )

        return self._process_cli(
            project=project,
            package=package,
            version=version,
        )
