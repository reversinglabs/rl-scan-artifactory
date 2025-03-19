# python3 ts=4space
import logging
import os
import sys
import time
from dataclasses import (
    dataclass,
)
from datetime import (
    timezone,
    datetime,
)

from typing import (
    Any,
    Dict,
    List,
    Tuple,
)

import requests

from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..artifactory_to_portal_base import ArtifactoryToPortalBase
from ..constants import (
    SPECTRA_ASSURE_PRE,
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
    PROP_NAME_SPECTRA_ASSURE_PURL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT,
    PROP_NAME_SPECTRA_ASSURE_ORG,
    PROP_NAME_SPECTRA_ASSURE_GROUP,
    PROP_NAME_SPECTRA_ASSURE_NOSCAN,
    #
    PROP_SPECTRA_ASSURE_VALID_VALUES,
    PROP_SPECTRA_ASSURE_ALL,
    #
    SCAN_STATUS_WAIT_TIME_MAX,
    SCAN_STATUS_WAIT_TIME,
    #
    SPECTRA_ASSURE_HOST,
    SPECTRA_ASSURE_HOST_BASE,
    #
    PROCESS_FILE_SKIP,
    PROCESS_FILE_UPDATED,
    PROCESS_FILE_TIMEOUT,
    #
    _MINUTE,
    DOCKER_RECURSIVE,
    SECURE_SOFTWARE_COMMUNITY_PACKAGE_TYPES,
    SECURE_SOFTWARE_URL,
)
from ..exceptions import (
    SpectraAssureInvalidAction,
)
from ..file_properties import FilePropertiesCommon
from ..fileinfo import FileInfo
from ..name_mangler import (
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
from ..spectra_assure_api import SpectraAssureApi
from ..scan_cli_file import ScanCli

logger = logging.getLogger(__name__)


@dataclass
class PurlInfo:
    project: str | None = None
    package: str | None = None
    version: str | None = None

    def make_purl(
        self,
    ) -> str:
        assert self.project is not None
        assert self.package is not None
        assert self.version is not None
        return f"{self.project}/{self.package}@{self.version}"

    def from_purl(
        self,
        purl: str,
    ) -> None:
        assert "@" in purl
        assert "/" in purl

        aa = purl.split("@")
        assert len(aa) == 2
        self.version = aa[1]

        bb = aa[0].split("/")
        assert len(bb) == 2
        self.project = bb[0]
        self.package = bb[1]


@dataclass
class PortalInfo:
    server: str | None = None
    group: str | None = None
    org: str | None = None


@dataclass
class ProxyInfo:
    server: str | None = None
    port: str | None = None
    user: str | None = None
    password: str | None = None
    proxies: Dict[str, str] | None = None

    def _set_proxy(
        self,
    ) -> Dict[str, str]:
        # TODO: use proxy helper
        proxies: Dict[str, str] = {}

        if self.server is None:
            return proxies

        if self.port is None:
            msg = "when specifying a proxy server, you also must specify a proxy port"
            raise SpectraAssureInvalidAction(message=msg)

        if self.user is None:
            return {
                "http": f"http://{self.server}:{self.port}",
                "https": f"http://{self.server}:{self.port}",
            }

        return {
            "http": f"http://{self.user}:{self.password}@{self.server}:{self.port}",
            "https": f"http://{self.user}:{self.password}@{self.server}:{self.port}",
        }

    def get_proxy_info(
        self,
    ) -> Dict[str, str]:
        if self.proxies is None:
            self.proxies = self._set_proxy()
        return self.proxies


@dataclass
class ProcessingInfo:
    completed: bool = False  # if not completed we have a purl, we uploaded for processing, but it is not yet finished
    scan_state: str | None = None  # pass/fail
    status: str | None = None  # skip, updated
    reason: str | None = None  # if skip then explain why
    report: str | None = None  # if report url (portal) what is the url
    purl: str | None = None  # if we found a purl , show it


class ArtifactoryFileProcessorCommon(
    ArtifactoryToPortalBase,
):
    def __init__(
        self,
        *,
        cli_args: Dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],  # pass info between file processing; docker list.manifest.json currently
    ) -> None:
        """
        ArtifactoryFileProcessorCommon

        args:
        - cli_args:
        - spectra_assure_api:
        - artifactory_api:
        - repo:
        - artifact_item:
        - repo_db:
        """
        # -----------------------------
        super().__init__(
            cli_args=cli_args,
            spectra_assure_api=spectra_assure_api,
            artifactory_api=artifactory_api,
        )
        self.repo = repo
        self.p_type = self.repo.package_type.lower()

        self.artifact_item = artifact_item
        self.uri: str = str(artifact_item.get("uri"))
        self.filename = self.uri.split("/")[-1]
        self.up_uri: str = "/".join(self.uri.split("/")[:-1])

        self.repo_db = repo_db
        self.purl_info = PurlInfo()
        self.max_time: int = self._do_max_time()

        self.portal_info = PortalInfo(
            server=self.cli_args.get("rlportal_server"),
            org=self.cli_args.get("rlportal_org"),
            group=self.cli_args.get("rlportal_group"),
        )

        self.file = FileInfo(
            repo=repo,
            uri=self.uri,
            sha1=str(artifact_item.get("sha1")),
            sha2=str(artifact_item.get("sha2")),
            last_modified=artifact_item.get("lastModified", ""),
            file_name=os.path.basename(self.uri),
        )

        self.fp: FilePropertiesCommon | None = None

        self.proxy_info = ProxyInfo(
            server=self.cli_args.get("proxy_server"),
            port=self.cli_args.get("proxy_port"),
            user=self.cli_args.get("proxy_user"),
            password=self.cli_args.get("proxy_password"),
        )

        self.processing_info = ProcessingInfo()
        self.what_backend: str = self.do_what_backend()
        self.files_to_remove: List[str] = []

        self.steps: Dict[str, bool] = {
            "artifactory_properties_exists": False,
            "have_package_url": False,
            "portal_upload_ok": False,
            "portal_scan_complete": False,
        }

        self.need_sync_datetime: bool = False

    def do_what_backend(
        self,
    ) -> str:
        for k in ["cli", "portal"]:
            if self.cli_args.get(k, False) is True:
                return k
        raise SpectraAssureInvalidAction("unsupported scanner backend")

    def _do_max_time(
        self,
    ) -> int:
        max_time = SCAN_STATUS_WAIT_TIME_MAX

        try:
            wt = self.cli_args.get("waittime")
            if wt is not None and float(wt) > 0:
                max_time = int(_MINUTE * float(wt))
            assert max_time > 0
            logger.debug("wait time for scan status per uploaded item set to: %d minutes", int(max_time / 60))
        except Exception as e:
            logger.exception("wrong value for 'waittime': %s, expecting float; %s", wt, e)
            max_time = SCAN_STATUS_WAIT_TIME_MAX
        return max_time

    def _do_one_artifactory_download(
        self,
        target_name: str | None = None,
    ) -> Tuple[str | None, bool]:
        download_path, verify_ok = self.artifactory_api.download_one_file_with_verify(
            file=self.file,
            download_dir=self.download_dir,
            target_name=target_name,
        )
        return download_path, verify_ok

    def add_file_to_remove(
        self,
        item: str,
    ) -> None:
        if item not in self.files_to_remove:
            self.files_to_remove.append(item)

    def remove_my_files(
        self,
    ) -> None:
        logger.debug("%s", self.files_to_remove)

        for item in self.files_to_remove:
            if os.path.exists(item):
                os.remove(item)
            else:
                logger.debug("file does not exist: %s", item)

    @staticmethod
    def _remove_files(
        files_to_remove: List[str],
    ) -> None:
        for item in files_to_remove:
            if not os.path.exists(item):
                logger.error("file missing: '%s'", item)
                continue
            os.remove(item)

    def _do_one_portal_upload(
        self,
        project: str,
        package: str,
        version: str,
        file_path: str,
    ) -> bool:
        assert self.what_backend == "portal"
        assert self.spectra_assure_api is not None
        purl = self.purl_info.make_purl()

        is_uploaded, optional_msg = self.spectra_assure_api.upload_artifact_to_portal(
            file=self.file,
            project=project,
            package=package,
            version=version,
            file_path=file_path,
        )

        if is_uploaded is False:
            msg = f"skip: no upload to portal for: {purl}; {optional_msg}"
            logger.error(msg)
            print(msg)

            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.reason = msg
            self.processing_info.purl = purl
            self.processing_info.report = None
            return is_uploaded

        recursive, uri = self._what_uri_and_recursive()

        self.set_props_all(
            report=None,
            progress="upload_to_portal_ok",
            scan_status=None,
            recursive=recursive,
            uri=uri,
        )

        self._remove_files([file_path])

        return is_uploaded

    def artifactory_report_url_needs_space(self) -> bool:  # noqa: ignore=C901, too complex
        # if artifactory version < 7.104.5 add the space to the report url to make it vizible

        version_dict = self.cli_args.get("_artifactory_version")
        if version_dict is None:
            return True

        version_string = version_dict.get("version")
        if version_string is None:
            return True

        version_triple = version_string.split(".")
        if len(version_triple) < 3:
            return True

        try:
            v1 = int(version_triple[0])
            v2 = int(version_triple[1])
            v3 = int(version_triple[2])
        except Exception as e:
            logger.exception("version convert to int triple fails: %s; %s", version_triple, e)
            return True

        if v1 < 7:
            return True
        if v1 > 7:
            return False
        assert v1 == 7

        if v2 < 104:
            return True
        if v2 > 104:
            return False
        assert v2 == 104

        if v3 < 5:
            return True
        return False

    def set_props_all(  # noqa: ignore=C901, too complex
        self,
        report: str | None,
        progress: str,
        scan_status: str | None,
        recursive: bool,
        uri: str,
    ) -> None:
        # now verify is we already have all RL properties and if not set them now
        repo = self.file.repo
        logger.debug("%s %s %s", repo, uri, report)

        for p in PROP_SPECTRA_ASSURE_ALL:
            logger.debug("%s %s %s %s", p, repo, uri, report)

            if p == PROP_NAME_SPECTRA_ASSURE_PROGRESS:
                self.artifactory_api.set_one_prop(
                    repo=repo,
                    item_uri=uri,
                    key=p,
                    value=progress,
                    recursive=recursive,
                )
                continue

            if p == PROP_NAME_SPECTRA_ASSURE_TIMESTAMP:
                now_utc = datetime.now(timezone.utc)
                utc_stamp = now_utc.isoformat()[:19] + "Z"
                self.artifactory_api.set_one_prop(
                    repo=repo,
                    item_uri=uri,
                    key=p,
                    value=utc_stamp,
                    recursive=recursive,
                )
                continue

            if p == PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS:
                if scan_status is None:
                    continue

                if self.know_scan_status(scan_status=scan_status) is False:
                    continue

                self.artifactory_api.set_one_prop(
                    repo=repo,
                    item_uri=uri,
                    key=p,
                    value=scan_status,
                    recursive=recursive,
                )
                continue

            if p == PROP_NAME_SPECTRA_ASSURE_PURL:
                self.artifactory_api.set_one_prop(
                    repo=repo,
                    item_uri=uri,
                    key=p,
                    value=f"pkg:rl/{self.purl_info.make_purl()}",
                    recursive=recursive,
                )
                continue

            if p == PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT:
                if report is None or len(report) == 0:
                    continue

                if self.artifactory_report_url_needs_space() is True:
                    report = " " + report  # apparently one space in front fixes the no view issue

                self.artifactory_api.set_one_prop(
                    repo=repo,
                    item_uri=uri,
                    key=p,
                    value=report,
                    recursive=recursive,
                )
                continue

            if self.cli_args.get("portal", False) is True:
                assert self.portal_info.org is not None
                if p == PROP_NAME_SPECTRA_ASSURE_ORG:
                    self.artifactory_api.set_one_prop(
                        repo=repo,
                        item_uri=uri,
                        key=p,
                        value=self.portal_info.org,
                        recursive=recursive,
                    )
                    continue

            if self.cli_args.get("portal", False) is True:
                assert self.portal_info.group is not None
                if p == PROP_NAME_SPECTRA_ASSURE_GROUP:
                    self.artifactory_api.set_one_prop(
                        repo=repo,
                        item_uri=uri,
                        key=p,
                        value=self.portal_info.group,
                        recursive=recursive,
                    )
                    continue

    def _what_uri_and_recursive(
        self,
    ) -> Tuple[bool, str]:
        recursive: bool = False
        uri = self.uri

        if DOCKER_RECURSIVE and self.p_type == "docker":
            recursive = True
            uri = self.up_uri

        return recursive, uri

    def _populate_purl_info(
        self,
        project: str,
        package: str,
        version: str,
    ) -> None:
        self.purl_info.project = project
        self.purl_info.package = package
        self.purl_info.version = version

    def _handle_progress_present_on_artifactory(
        self,
        progress: str,
    ) -> bool:
        if progress == "scanned":
            msg = f"already scanned {self.file.repo.name}{self.uri}"
            logger.info(msg)

            self.processing_info.completed = True
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = progress
            self.processing_info.purl = self.get_prop_purl()
            self.processing_info.report = self.get_prop_report()
            return True

        if progress == "upload_to_portal_ok":
            msg = f"uploaded but no scan result yet: {self.file.repo.name}; {self.uri}"
            logger.info(msg)

            self.processing_info.completed = False
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = progress
            self.processing_info.purl = self.get_prop_purl()
            self.processing_info.report = None
            return True

        raise SpectraAssureInvalidAction("property: progress has a unknown value")

    def _file_download_upload_common(
        self,
    ) -> bool:
        download_path, verify_ok = self._do_one_artifactory_download()
        if download_path is None:
            msg = f"skip: download failed for: {self.file}"
            logger.error(msg)

            self.processing_info.completed = True
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.purl = self.purl_info.make_purl()
            self.processing_info.report = None
            return False

        assert self.purl_info.project is not None
        assert self.purl_info.package is not None
        assert self.purl_info.version is not None

        is_uploaded = self._do_one_portal_upload(
            project=self.purl_info.project,
            package=self.purl_info.package,
            version=self.purl_info.version,
            file_path=download_path,
        )

        return is_uploaded

    def _get_purl_status(
        self,
    ) -> Any | None:

        purl = self.purl_info.make_purl()
        project, package, version = self._purl_split(purl=purl)

        assert self.what_backend == "portal"
        assert self.spectra_assure_api is not None

        rr = self.spectra_assure_api.api_client.status(
            project=project,
            package=package,
            version=version,
        )

        if rr.status_code < 200 or rr.status_code >= 300:
            logger.warning("status issue (%s) on purl: %s", rr.status_code, self.purl_info.make_purl())
            return None

        return rr.json()

    def _purl_sync_portal(
        self,
    ) -> bool | None:
        """execute a sync with the current purl componetns

        returns:
        - None if no sync could be done at all
        - False is no sync is needed
        - True if sync has started
        """
        assert self.what_backend == "portal"
        assert self.spectra_assure_api is not None

        purl = self.purl_info.make_purl()
        project, package, version = self._purl_split(purl=purl)

        rr = self.spectra_assure_api.api_client.sync(
            project=project,
            package=package,
            version=version,
        )
        logger.debug("sync issue (%s) on purl: %s", rr.status_code, self.purl_info.make_purl())

        if rr.status_code < 200 or rr.status_code >= 300:
            logger.warning("sync issue (%s) on purl: %s", rr.status_code, self.purl_info.make_purl())
            return None

        assert int(rr.status_code) in [200, 202]  # 200 means no sync needed, 202 means sync started
        sync_started = bool(int(rr.status_code) == 202)
        if sync_started:
            time.sleep(2)

        return sync_started

    def _update_artifactory_item_with_scan_status(
        self,
        scan_status: str | None,
        report: str | None = None,
        progress: str = "scanned",
    ) -> None:
        logger.debug("XXX %s", report)

        if report is not None and "http" not in report.lower():
            base = self._portal_make_report_base()
            report = f"{base}/{report}"

        logger.debug("YYY %s", report)

        recursive, uri = self._what_uri_and_recursive()

        self.set_props_all(
            report=report,
            progress=progress,
            scan_status=scan_status,
            recursive=recursive,
            uri=uri,
        )

    @staticmethod
    def _strip_redundant_build_is_version(
        report_url: str,
    ) -> str:
        k = "?build=version"
        if report_url.lower().endswith(k):
            report_url = report_url[: (-1 * len(k))]
        return report_url

    def _check_secure_software(
        self,
    ) -> bool:
        # https://secure.software/npm/packages/run-series/1.1.9
        # https://secure.software/npm/packages/@types/minipass/3.3.5
        # add proxy support and ignore ssl cert errors

        if self.p_type not in SECURE_SOFTWARE_COMMUNITY_PACKAGE_TYPES.keys():
            logger.debug("not in secure.software %s", self.file.repo.package_type)
            return False

        # get me the purl and check if we have the package and the version on secure.software
        uri_list = self.uri.split("/")
        name = ""
        version = ""
        url = "/".join(
            [
                SECURE_SOFTWARE_URL,
                self.p_type,
                "packages",
                name,
                version,
            ]
        )
        x = requests.head(
            url,
            proxies=self.proxy_info.get_proxy_info(),
        )

        logger.debug("%s %s %s", uri_list, url, x)

        return False

    def _get_purl_scan_status_one(
        self,
    ) -> Tuple[str | None, str | None]:
        data = self._get_purl_status()
        if data is None:
            return None, None

        scan_status = self._get_path_in_dict_simple(
            "analysis.report.info.statistics.quality.status",
            data,
        )

        if scan_status is None or self.know_scan_status(scan_status=scan_status) is False:
            logger.info("SCAN NOT COMPLETE for: %s %s", self.purl_info.make_purl(), self.uri)
            return None, None

        report = self._get_path_in_dict_simple(
            "analysis.report.info.portal.reference",
            data,
        )

        assert scan_status is not None
        assert report is not None

        return scan_status, self._strip_redundant_build_is_version(report_url=report)

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
            logger.debug("purl: %s, %d, %s", purl, n, scan_status)

        completed = False
        if scan_status is None:
            logger.warning("timout reached: no scan status for: '%s'", purl)

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

    def _exists_on_portal(
        self,
        package: str,
        project: str,
        version: str,
        digest: str | None,
    ) -> Tuple[bool, str | None, str | None]:
        assert self.what_backend == "portal"
        assert self.spectra_assure_api is not None

        exists = self.spectra_assure_api.exist_version(
            project=project,
            package=package,
            version=version,
            digest=digest,
        )
        if exists[0] is False:
            return False, None, None

        scan_status, report = self._get_purl_scan_status_one()

        logger.debug("%s", report)
        if report:
            base = self._portal_make_report_base()
            report = f"{base}/{report}"
        logger.debug("%s", report)

        progress = "scanned"
        if scan_status is None or self.know_scan_status(scan_status=scan_status) is False:
            progress = "upload_to_portal_ok"

        recursive, uri = self._what_uri_and_recursive()
        self.set_props_all(
            report=report,
            progress=progress,
            scan_status=scan_status,
            recursive=recursive,
            uri=uri,
        )
        return True, scan_status, report

    # PUBLIC

    @staticmethod
    def know_scan_status(
        scan_status: str,
    ) -> bool:
        return str(scan_status).lower() in PROP_SPECTRA_ASSURE_VALID_VALUES[PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS]

    def get_purl_from_name_mangler(
        self,
        p_type: str,
    ) -> Tuple[str, str, str]:
        dispatch = {
            "rpm": NameManglerRpm,
            "npm": NameManglerNpm,
            "pypi": NameManglerPypi,
            "debian": NameManglerDebian,
            "deb": NameManglerDebian,
            "maven": NameManglerMaven,
            "gems": NameManglerGems,
            "docker": NameManglerDocker,
            "generic": NameManglerGeneric,
        }

        if p_type in dispatch:
            nm = dispatch[p_type](file=self.file)
        else:
            nm = NameManglerDefault(file=self.file)

        project, package, version = nm.make_long()
        return project, package, version

    def get_file(
        self,
    ) -> FileInfo:
        assert self.file is not None
        return self.file

    def set_file_properties(
        self,
        fp: FilePropertiesCommon,
    ) -> None:
        self.fp = fp

    def _get_prop_what(
        self,
        what: str,
    ) -> str:
        z = self.file.properties.get(what, [])
        if len(z):
            return str(z[0])
        return ""

    def get_prop_progress(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_PROGRESS)

    def get_prop_report(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT)

    def get_prop_scan_status(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS)

    def get_prop_purl(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_PURL)

    def get_prop_last_scan_moment(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_TIMESTAMP)

    def sync_possible(
        self,
    ) -> bool:
        if self.cli_args.get("cli-docker"):
            logger.warning("sync is currently not possible with cli-docker")
            return False

        last_scan = self.get_prop_last_scan_moment()
        if last_scan is None:
            return False

        if len(last_scan) < 20:  # YYYY-mm-ddThh:mm:ssZ
            return False

        last_scan_utc = datetime.strptime(last_scan, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        logger.debug("%s now: %s", last_scan_utc, now_utc)

        duration = now_utc - last_scan_utc
        if duration.days > 14:  # any scan older then 2 weeks can be synced
            return True

        return False

    def _portal_make_report_base(
        self,
    ) -> str:
        assert self.spectra_assure_api is not None

        """create the correct base for normal and special 'server' strings."""
        server = self.spectra_assure_api.server
        if server in ["trial", "playground"]:
            return f"https://{server}.{SPECTRA_ASSURE_HOST_BASE}"
        return f"https://{SPECTRA_ASSURE_HOST}/{server}"

    def get_uri(
        self,
    ) -> str:
        return self.uri

    def clear_all_spectra_assure_props(
        self,
    ) -> None:
        return

        k = "WITH_TEST_CLEAR_PROPS_ALL"
        z = bool(int(os.getenv(k, 0)))
        if z is False:  # Force Reprocessing or check the portal
            return

        logger.debug("%s: %s, %s", k, z, self.uri)

        recursive, uri = self._what_uri_and_recursive()

        to_del: List[str] = []
        for key, val in self.file.properties.items():
            if key.startswith(f"{SPECTRA_ASSURE_PRE}."):
                self.artifactory_api.del_one_prop(
                    repo=self.file.repo,
                    item_uri=uri,
                    key=key,
                    recursive=recursive,
                )
                to_del.append(key)

        if len(to_del) > 0:
            for k in to_del:
                del self.file.properties[k]

    def do_cli_after_download(
        self,
        project: str,
        package: str,
        version: str,
        download_path: str,
    ) -> bool:
        assert self.what_backend == "cli"
        logger.debug("purl:: %s/%s@%s;; %s", project, package, version, download_path)

        self.add_file_to_remove(download_path)
        purl = self.purl_info.make_purl()
        sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime

        scan_cli = ScanCli(cli_args=self.cli_args)

        # does the purl exist in the store ?
        # if not we have to do a scan instead
        # call  cli sync -> status -> report
        # currently we cannot support sync on docker
        # and we cannot test if a purl exists on docker

        # call  cli sync -> status -> report
        ret, report_bundle_path, scan_status = scan_cli.scan_file(
            file_path=download_path,
            purl=purl,
            sync_requested=sync_requested,
        )

        # ret is 0 for cli rl-secure but ret is 0 or 1 for docker only 101 is a real error

        if scan_status is None or ret in [101]:
            scan_cli.cleanup()
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = purl
            self.steps["artifactory_properties_exists"] = True
            self.steps["portal_scan_complete"] = True
            self.processing_info.reason = f"cli scan failed, no result {ret}"
            return True

        assert scan_status is not None

        # report_path: /tmp/tmpadb99u4c/reports.zip
        # uri: /org/codehaus/plexus/plexus-classworlds/2.2.3/plexus-classworlds-2.2.3.jar
        # repo: maven2-dev (actually maven2-dev-cache)
        # upload report to artifactory
        # set properties

        logger.debug("%s %s %s", self.file.uri, report_bundle_path, scan_status)

        report_file_name = report_bundle_path.split("/")[-1]

        repo_name = self.repo.name
        report_uri = f"{self.uri}-{report_file_name}"

        logger.debug("pre %s %s", repo_name, report_uri)

        if self.repo.repo_type == "remote":
            if self.cli_args.get("cli_reports_repo") is not None:
                reports_repo = self.cli_args.get("cli_reports_repo")
                assert reports_repo is not None
                # https://alt-artifactory-dev.rl.lan/artifactory/Spectra-Assure-Reports/
                report_name = f"{purl}_{report_file_name}".replace("/", "_").replace("@", "_")
                report_uri = f"/{purl}/".replace("@", "/") + report_name
                repo_name = reports_repo

        logger.debug("post %s %s", repo_name, report_uri)

        try:
            r_code, r_text, report_url = self.artifactory_api.upload_file_to_artifactory(
                file_path=report_bundle_path,
                repo_name=repo_name,
                uri_path=report_uri,
            )
            logger.debug("%s %s %s", r_code, r_text, report_url)
        except Exception as e:
            logger.exception(
                "Fatal: %s:%s; cannot upload report_bundle: %s; %s", repo_name, report_uri, report_bundle_path, e
            )
            sys.exit(101)

        scan_cli.cleanup()
        logger.debug("%s", report_url)

        self._update_artifactory_item_with_scan_status(
            scan_status=scan_status,
            report=report_url,
        )

        if self.repo.repo_type != "remote":
            logger.debug("%s %s %s", self.repo.repo_type, self.repo, report_uri)

            self.artifactory_api.put_one_prop(
                repo=self.repo,
                item_uri=report_uri,
                key=PROP_NAME_SPECTRA_ASSURE_NOSCAN,
                value="true",
            )
            # with recursive docker tagging we now tagged the report file
            # if 'fail' that blocks the report download
            # remove the fail tag from the reports.zip (or all RL tags)
            # https://alt-artifactory-dev.rl.lan/artifactory
            #  /docker-local/cicd-builds/java-hello-world/30/manifest.json-reports.zip

            logger.debug("clear props from report: %s", report_uri)
            self.artifactory_api.del_one_prop(
                repo=self.repo,
                item_uri=report_uri,
                key=PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
            )
            self.artifactory_api.put_one_prop(
                repo=self.repo,
                item_uri=report_uri,
                key=PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
                value="__novalue__",
            )

        self.processing_info.completed = True
        self.processing_info.status = PROCESS_FILE_UPDATED
        self.processing_info.scan_state = scan_status
        self.processing_info.report = report_url
        self.processing_info.purl = purl
        self.steps["artifactory_properties_exists"] = True

        if sync_requested:
            reason = "cli-sync"
        else:
            reason = "cli"

        self.processing_info.reason = reason
        return True

    def get_process_status(
        self,
    ) -> str:
        assert self.processing_info.status is not None
        return self.processing_info.status

    def extract_generic_meta_info(
        self,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def process(
        self,
    ) -> bool:
        raise NotImplementedError
