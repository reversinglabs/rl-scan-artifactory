# python3 ts=4space
import configparser
import logging
import time
from typing import (
    Any,
    Dict,
    Tuple,
)

from .artifactory_file_processor_common import ArtifactoryFileProcessorCommon
from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..constants import (
    PROCESS_FILE_SKIP,
    META_STRING,
    META_SECTION_KEY,
)
from ..constants import (
    SCAN_STATUS_WAIT_TIME,
    PROCESS_FILE_UPDATED,
    PROCESS_FILE_TIMEOUT,
)
from ..exceptions import SpectraAssureInvalidAction
from ..spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)

"""
[rl_meta]
namespace:      optional
name:           mandatory
version:        mandatory
architecture:   optional

path:           mandatory
sha256:         mandatory
"""


class ArtifactoryFileProcessorGeneric(
    ArtifactoryFileProcessorCommon,
):
    rl_meta_fields = [
        "namespace",
        "name",
        "version",
        "architecture",
        "path",
        "sha256",
    ]

    rl_meta_mandatory = [
        "name",
        "version",
        "path",
    ]

    derived = "_derived_"
    rl_meta = META_SECTION_KEY
    what = "generic"

    def __init__(
        self,
        *,
        cli_args: Dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],  # pass infor between file processing; docker list.manifest.json currently
    ) -> None:
        super().__init__(
            cli_args=cli_args,
            spectra_assure_api=spectra_assure_api,
            artifactory_api=artifactory_api,
            repo=repo,
            artifact_item=artifact_item,
            repo_db=repo_db,
        )

    @staticmethod
    def _escape_string_for_spectra_assure_purl_component(
        string: str,
    ) -> str:
        trans = {
            "@": "40",
            "/": "2F",
        }
        for k, v in trans.items():
            if k in string:
                string = string.replace(k, f"0x{v}")

        return string

    def _make_meta_dict(
        self,
        config: Any,
    ) -> Dict[str, str | None]:
        meta: Dict[str, str | None] = {}

        for n in self.rl_meta_fields:
            meta[n] = config[self.rl_meta].get(n)

            k = n
            if n == "architecture":
                k = "arch"

            k = f"{self.what}.{self.derived}.{k}"
            v = meta[n]
            self.file.properties[k] = v

        logger.debug("%s", meta)
        return meta

    def _verify_mandatory(
        self,
        meta: Dict[str, Any],
    ) -> None:
        crit = False
        for n in self.rl_meta_mandatory:
            z: str | None = meta[n]
            if z is None or len(z) == 0:
                logger.critical("item %s in %s is mandatory", n, self.rl_meta)
                crit = True

        if crit is True:
            raise SpectraAssureInvalidAction(f"missing mandatory items in {META_STRING} file")

    def _set_purl_data(
        self,
        meta: Dict[str, Any],
    ) -> None:
        # -- project --
        self.purl_info.project = self.repo.name
        k = "architecture"
        z = self._escape_string_for_spectra_assure_purl_component(meta[k])

        if z is not None and len(z) > 0:
            self.purl_info.project = f"{self.repo.name}-{z}"

        # -- package --
        name = self._escape_string_for_spectra_assure_purl_component(meta["name"])
        self.purl_info.package = name
        k = "namespace"
        z = self._escape_string_for_spectra_assure_purl_component(meta[k])
        if z is not None and len(z) > 0:
            self.purl_info.package = f"{z}-{name}"

        # -- version --
        self.purl_info.version = self._escape_string_for_spectra_assure_purl_component(meta["version"])

    def _load_meta_info(
        self,
    ) -> Tuple[bool, Any]:
        """Download the meta file and extract ist info"""
        is_downloaded = False

        aa = self.uri.split("/")
        target_name = aa[-1]
        assert target_name is not None
        download_path, verify_ok = self._do_one_artifactory_download(
            target_name=target_name,
        )

        if download_path is None:
            logger.error("download failed file for: %s", download_path)
            return is_downloaded, None

        config = configparser.ConfigParser()
        config.read(download_path)

        if self.rl_meta not in config:
            logger.error("missing %s in meta file", self.rl_meta, download_path)
            return is_downloaded, None

        meta = self._make_meta_dict(config=config)
        self._verify_mandatory(meta=meta)
        self._set_purl_data(meta=meta)
        self._remove_files([download_path])

        return True, meta

    def _update_artifactory_item_with_scan_status(
        self,
        scan_status: str | None,
        report: str | None = None,
        progress: str = "scanned",
    ) -> None:
        logger.debug("%s", report)
        if report is not None and self.what_backend == "portal":
            base = self._portal_make_report_base()
            report = f"{base}/{report}"
        logger.debug("%s", report)

        uri = self.uri
        self.set_props_all(
            report=report,
            progress=progress,
            scan_status=scan_status,
            recursive=False,
            uri=uri,
        )

        if self.cli_args.get("portal"):
            aa = uri.split("/")
            aa[-1] = self.file.properties[f"{self.what}.{self.derived}.path"]
            uri2 = "/".join(aa)

            self.set_props_all(
                report=report,
                progress=progress,
                scan_status=scan_status,
                recursive=False,
                uri=uri2,
            )

    def _wait_for_scan_status_one_portal(
        self,
    ) -> bool:
        assert self.max_time > 0
        assert self.what_backend == "portal"

        purl = self.purl_info.make_purl()
        time.sleep(1)
        report = None

        n = 0
        while n < self.max_time:
            scan_status, report = self._get_purl_scan_status_one()
            if scan_status is not None:
                break

            time.sleep(SCAN_STATUS_WAIT_TIME)  # seconds
            n += SCAN_STATUS_WAIT_TIME
            logger.debug("purl: %s, %d, %s", self.purl_info.make_purl(), n, scan_status)

        completed = False
        if scan_status is None:
            logger.warning("timout reached: no scan status for: '%s'", self.purl_info.make_purl())

            self.processing_info.completed = completed
            self.processing_info.status = PROCESS_FILE_TIMEOUT
            self.processing_info.scan_state = scan_status
            self.processing_info.report = report
            self.processing_info.purl = purl
            return completed

        assert report is not None

        completed = True
        self._update_artifactory_item_with_scan_status(
            scan_status=scan_status,
            report=report,
        )
        self.steps["artifactory_properties_exists"] = True

        self.processing_info.completed = completed
        self.processing_info.status = PROCESS_FILE_UPDATED
        self.processing_info.scan_state = scan_status
        self.processing_info.report = report
        self.processing_info.purl = purl

        self.steps["portal_scan_complete"] = True
        return completed

    def make_new_uri_from_file_name(
        self,
        file_name: str,
    ) -> str:
        aa = self.uri.split("/")
        aa[-1] = file_name
        return "/".join(aa)

    def _portal_download_upload_generic(
        self,
        project: str,
        package: str,
        version: str,
    ) -> Any:
        assert self.what_backend == "portal"

        is_uploaded = False
        self.steps["portal_upload_ok"] = False
        self.steps["portal_scan_complete"] = False
        self.processing_info.scan_state = None
        self.processing_info.purl = None
        self.processing_info.report = None

        # download the file
        file_name = self.file.properties[f"{self.what}.{self.derived}.path"]
        k = f"{self.what}.{self.derived}.sha256"
        sha256 = None
        if self.file.properties.get(k):
            sha256 = self.file.properties[k]

        new_uri = self.make_new_uri_from_file_name(file_name=file_name)
        target_path = "/".join([self.download_dir, file_name])
        url = f"{self.artifactory_api.get_base_url()}/{self.file.repo.name}{new_uri}"
        download_path, verify_ok = self.artifactory_api.download_url_to_target_with_verify(
            url=url,
            target_path=target_path,
            sha256=sha256,
        )
        if download_path is None:
            # if we block `rlBlock plugin`,  we get no download dir
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "skip: file cannot be downloaded"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return is_uploaded

        assert download_path is not None
        # upload the file
        is_uploaded = self._do_one_portal_upload(
            project=project,
            package=package,
            version=version,
            file_path=download_path,
        )
        self._remove_files([download_path])
        if is_uploaded is False:
            self.processing_info.completed = True
            self.processing_info.reason = "upload to portal failed"
            self.processing_info.status = PROCESS_FILE_SKIP
            return is_uploaded

        self.steps["portal_upload_ok"] = True
        self.set_props_all(
            report=None,
            progress="upload_to_portal_ok",
            scan_status=None,
            recursive=False,
            uri=self.make_new_uri_from_file_name(
                file_name=file_name,
            ),
        )
        self.steps["artifactory_properties_exists"] = True
        return is_uploaded

    def _process_portal(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        assert self.what_backend == "portal"

        is_uploaded = False
        purl = self.purl_info.make_purl()
        sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime

        exists_on_portal, scan_status, report = self._exists_on_portal(
            project=project,
            package=package,
            version=version,
            digest=None,
        )
        logger.debug("scan status: %s", scan_status)

        if exists_on_portal is True:
            is_uploaded = True
            self.steps["portal_upload_ok"] = True
            self.processing_info.reason = "purl exists on portal"

            if sync_requested is False:
                if scan_status in ["pass", "fail"]:
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = scan_status
                    self.processing_info.purl = purl
                    self.processing_info.report = report
                    self.processing_info.completed = True
                    self.steps["portal_scan_complete"] = True
                    return True
            else:
                self.processing_info.reason = "portal-sync"
                sync_started = self._purl_sync_portal()
                if sync_started is None:
                    self.processing_info.reason = "request to sync failed"
                    self.processing_info.purl = self.get_prop_purl()
                    self.processing_info.completed = True
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = None
                    self.processing_info.report = None
                    self.steps["artifactory_properties_exists"] = False
                    return True
        else:
            is_uploaded = self._portal_download_upload_generic(
                project=project,
                package=package,
                version=version,
            )
            if is_uploaded is False:
                return True

        return self._wait_for_scan_status_one_portal()

    def process_portal(
        self,
    ) -> bool:
        # will load the properties from artifactory or create derived based on uri
        assert self.what_backend == "portal"
        assert self.fp is not None

        skip_candidate = self.fp.skip_non_candidate_file()  # it there is no meta we will have to scan all files
        if skip_candidate:
            logger.debug("skip: %s", self.uri)
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "skip: not a candidate for inspection"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return True

        if self.get_prop_progress() in ["scanned", "portal_upload_ok"]:
            self.steps["artifactory_properties_exists"] = True
            if self.cli_args.get("ignore_artifactory_properties") is False:
                if self.get_prop_progress() in ["scanned"]:
                    if self.sync_possible() is False:  # requires property scanned
                        self.processing_info.completed = True
                        self.processing_info.status = PROCESS_FILE_SKIP
                        self.processing_info.reason = "already proccessed"
                        self.processing_info.scan_state = self.get_prop_progress()
                        self.processing_info.report = self.get_prop_report()
                        self.processing_info.purl = self.get_prop_purl()
                        return True

                    # we can do a sync instead of a scan
                    self.need_sync_datetime = True

        self.steps["artifactory_properties_exists"] = False
        logger.debug("inspect %s", self.uri)

        meta_ok, _ = self._load_meta_info()  # if there is no meta we ignore this item
        if meta_ok is False:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "meta file extract failed"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return True

        assert self.purl_info.project is not None
        assert self.purl_info.package is not None
        assert self.purl_info.version is not None

        self.steps["have_package_url"] = True

        project = self.purl_info.project
        package = self.purl_info.package
        version = self.purl_info.version

        return self._process_portal(
            project=project,
            package=package,
            version=version,
        )

    def _process_cli(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        assert self.what_backend == "cli"

        logger.debug("candidate2 %s", self.uri)
        self.steps["artifactory_properties_exists"] = False

        self._populate_purl_info(project, package, version)
        self.steps["have_package_url"] = True
        purl = self.purl_info.make_purl()

        # for now just keep the downloaded file even if we dont actually need it for sync
        download_path, verify_ok = self._do_one_artifactory_download()
        if download_path is None:
            msg = f"skip: download failed for: {self.file}"
            logger.error(msg)

            self.processing_info.completed = True
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.purl = purl
            self.processing_info.report = None
            return False

        return self.do_cli_after_download(  # will handle sync now internally
            project=project,
            package=package,
            version=version,
            download_path=download_path,
        )

    def process_cli(
        self,
    ) -> bool:
        assert self.what_backend == "cli"
        logger.debug("candidate1 %s", self.uri)

        assert self.fp is not None

        skip_candidate = self.fp.skip_non_candidate_file()
        if skip_candidate:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "skip: not a candidate for inspection"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return True

        if self.get_prop_progress() in ["scanned", "portal_upload_ok"]:
            self.steps["artifactory_properties_exists"] = True
            if self.cli_args.get("ignore_artifactory_properties") is False:

                # if the scan date is older then 2 weeks schedule a sync instead of a scan # TODO
                if self.get_prop_progress() in ["scanned"]:
                    if self.sync_possible() is False:
                        self.processing_info.completed = True
                        self.processing_info.status = PROCESS_FILE_SKIP
                        self.processing_info.reason = "already proccessed"
                        self.processing_info.scan_state = self.get_prop_progress()
                        self.processing_info.report = self.get_prop_report()
                        self.processing_info.purl = self.get_prop_purl()
                        return True

                    self.need_sync_datetime = True
                    # sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime
                    # we can do a sync instead of a scan
                    # but generic has no true purl as we have no meta file for cli currently
                    # so we cant sync as all packages are the same purl

                    self.processing_info.completed = True
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.reason = (
                        "sync not possible with cli as we have no valid purl without a meta file"
                    )
                    self.processing_info.scan_state = self.get_prop_progress()
                    self.processing_info.report = self.get_prop_report()
                    self.processing_info.purl = self.get_prop_purl()
                    return True

        # sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime

        self.steps["artifactory_properties_exists"] = False
        logger.debug("inspect %s", self.uri)

        # for generic
        meta_info = {
            "project": self.file.repo.name,
            "package": self._escape_string_for_spectra_assure_purl_component(self.filename),
            "version": "v0",
        }
        logger.debug(self.repo_db)
        if self.uri in self.repo_db:
            logger.debug("%s", self.repo_db[self.uri])
            meta_info = self.repo_db[self.uri]
        logger.debug("%s", meta_info)

        # currently no meta file for cli
        self.purl_info.project = meta_info["project"]
        self.purl_info.package = meta_info["package"]
        self.purl_info.version = meta_info["version"]
        # print(self.purl_info)

        self.steps["have_package_url"] = True

        assert self.purl_info.project is not None
        assert self.purl_info.package is not None
        assert self.purl_info.version is not None

        project = self.purl_info.project
        package = self.purl_info.package
        version = self.purl_info.version

        return self._process_cli(
            project=project,
            package=package,
            version=version,
        )

    # PUBLIC
    def extract_generic_meta_info(self) -> Dict[str, Any]:
        """
        Download the rl_meta file
        extract its properties,
        return a dict with the meta info and a valid purl.
        """
        meta_dict: Dict[str, Any] = {}
        has_meta, meta = self._load_meta_info()
        if has_meta is False:
            logger.debug("%s", meta)
            return meta_dict

        meta_dict["project"] = self.purl_info.project
        meta_dict["package"] = self.purl_info.package
        meta_dict["version"] = self.purl_info.version
        meta_dict["meta"] = meta

        logger.debug("%s", meta_dict)

        return meta_dict

    def process(  # noqa: C901
        self,
    ) -> bool:  # completed yes/no if no we have uploaded but the scan has not completed yet
        # will load the properties from artifactory or create derived based on uri
        assert self.fp is not None
        if self.what_backend == "portal":
            return self.process_portal()
        return self.process_cli()
