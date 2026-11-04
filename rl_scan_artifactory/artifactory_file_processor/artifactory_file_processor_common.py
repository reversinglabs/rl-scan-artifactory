# python3 ts=4space
import logging
import os
import pathlib
import time
from collections.abc import Callable
from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..artifactory_to_portal_base import ArtifactoryToPortalBase
from ..constants import (
    _MINUTE,
    DOCKER_RECURSIVE,
    PORTAL_STATUS_ABSENT,
    PORTAL_STATUS_ABSENT_LIMIT,
    PROCESS_FILE_SKIP,
    PROCESS_FILE_TIMEOUT,
    PROCESS_FILE_UPDATED,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
    PROP_LEGACY_PRE,
    PROP_NAME_SPECTRA_ASSURE_GROUP,
    PROP_NAME_SPECTRA_ASSURE_NOSCAN,
    PROP_NAME_SPECTRA_ASSURE_ORG,
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_PURL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
    PROP_NAME_SPECTRA_ASSURE_SHA256,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_SPECTRA_ASSURE_ALL,
    PROP_SPECTRA_ASSURE_VALID_VALUES,
    REPORT_URL_SPACE_UNTIL,
    SCAN_STATUS_WAIT_TIME,
    SCAN_STATUS_WAIT_TIME_MAX,
    SPECTRA_ASSURE_HOST,
    SPECTRA_ASSURE_HOST_BASE,
    SPECTRA_ASSURE_PRE,
)
from ..exceptions import (
    SpectraAssureInvalidAction,
    SpectraAssureInvariantError,
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
from ..py_cli_scan import ScanCliLocal
from ..py_cli_scan.report_hashes import digest_from_report_file
from ..scan_cli_file import ScanCli
from ..spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)


def obsolete_property_names(
    properties: dict[str, Any],
    maintained: tuple[str, ...],
) -> list[str]:
    """The properties of this integration that are not maintained on an item (R10.9).

    The integration is the sole owner of the RL. prefix (the other
    ReversingLabs integration uses secure.software.), so any RL.* name not in
    `maintained` is obsolete, as is everything under the old Spectra.Assure.
    prefix. RL.noscan stays: it is read on every item, and a person may have set
    it.
    """
    keep = (*maintained, PROP_NAME_SPECTRA_ASSURE_NOSCAN)

    obsolete: list[str] = []
    for key in properties:
        if key.startswith(f"{PROP_LEGACY_PRE}."):
            obsolete.append(key)
        elif key.startswith(f"{SPECTRA_ASSURE_PRE}.") and key not in keep:
            obsolete.append(key)

    return obsolete


@dataclass
class PurlInfo:
    project: str | None = None
    package: str | None = None
    version: str | None = None

    def make_purl(
        self,
    ) -> str:
        if self.project is None:
            msg = "expected self.project is not None"
            raise SpectraAssureInvariantError(msg)
        if self.package is None:
            msg = "expected self.package is not None"
            raise SpectraAssureInvariantError(msg)
        if self.version is None:
            msg = "expected self.version is not None"
            raise SpectraAssureInvariantError(msg)
        return f"{self.project}/{self.package}@{self.version}"


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
    proxies: dict[str, str] | None = None


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
        cli_args: dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: dict[str, Any],
        repo_db: dict[str, Any],  # pass info between file processing; docker list.manifest.json currently
    ) -> None:
        """
        ArtifactoryFileProcessorCommon

        Args:
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
        self.files_to_remove: list[str] = []

        self.need_sync_datetime: bool = False
        # set when a sync turned out to be about different bytes than artifactory holds
        self.cli_sync_was_stale: bool = False
        # set when the portal holds this version with other bytes, so an upload must replace it
        self.portal_has_other_bytes: bool = False

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
            if max_time <= 0:
                msg = "expected max_time > 0"
                raise SpectraAssureInvariantError(msg)
            logger.debug(
                "wait time for scan status per uploaded item set to: %d minutes",
                int(max_time / 60),
            )
        except Exception as e:
            logger.exception("wrong value for 'waittime': %s, expecting float; %s", wt, e)
            max_time = SCAN_STATUS_WAIT_TIME_MAX
        return max_time

    def _do_one_artifactory_download(
        self,
        target_name: str | None = None,
    ) -> tuple[str | None, bool | None]:
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

        if len(self.files_to_remove):
            for item in self.files_to_remove:
                logger.debug("try: remove file: %s", item)
                if pathlib.Path(item).exists():
                    pathlib.Path(item).unlink()
                else:
                    logger.debug("file does not exist: %s", item)

    @staticmethod
    def _remove_files(
        files_to_remove: list[str],
    ) -> None:
        for item in files_to_remove:
            if not pathlib.Path(item).exists():
                logger.error("file missing: '%s'", item)
                continue
            pathlib.Path(item).unlink()

    def _do_one_portal_upload(
        self,
        project: str,
        package: str,
        version: str,
        file_path: str,
    ) -> bool:
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)
        if self.spectra_assure_api is None:
            msg = "expected self.spectra_assure_api is not None"
            raise SpectraAssureInvariantError(msg)
        purl = self.purl_info.make_purl()

        # the file was downloaded, or assembled, only to be uploaded; whatever the
        # answer it is not needed any more, and this is the one place that removes it
        try:
            is_uploaded, optional_msg = self.spectra_assure_api.upload_artifact_to_portal(
                file=self.file,
                project=project,
                package=package,
                version=version,
                file_path=file_path,
                replace=self.portal_has_other_bytes,
            )
        finally:
            self._remove_files([file_path])

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
            progress=PROGRESS_UPLOADED,
            scan_status=None,
            recursive=recursive,
            uri=uri,
        )

        return is_uploaded

    def artifactory_report_url_needs_space(self) -> bool:
        """Below artifactory 7.104.5 a leading space makes the report url viewable.

        A version we cannot read means yes: the space is harmless on a version
        that does not need it, while leaving it off a version that does makes the
        report unreachable, so the unknown case takes the harmless answer.
        """
        version_dict = self.cli_args.get("_artifactory_version")
        if version_dict is None:
            return True

        version = self._version_triple(version_dict.get("version"))
        if version is None:
            return True

        return version < REPORT_URL_SPACE_UNTIL

    @staticmethod
    def _version_triple(
        version_string: str | None,
    ) -> tuple[int, int, int] | None:
        """(major, minor, patch), or None when the string is not one.

        Anything after the third part is ignored: artifactory reports versions
        like 7.104.5 and sometimes carries a build suffix.
        """
        if version_string is None:
            return None

        parts = version_string.split(".")
        if len(parts) < 3:
            return None

        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError as e:
            logger.error("cannot read '%s' as a version: %s", version_string, e)
            return None

    def set_props_all(
        self,
        report: str | None,
        progress: str,
        scan_status: str | None,
        recursive: bool,
        uri: str,
        only: tuple[str, ...] | None = None,
    ) -> None:
        """Write the RL.* properties of one item.

        `only` narrows the set to those names, for an item that is not the thing
        that was scanned: a .rl_meta side-car keeps just enough to say it was
        handled (R7.10).

        One value per property, computed by _value_for_property(); a None means
        this property is not written for this item. The values are computed one at
        a time, inside the loop, so that a property whose value cannot be produced
        leaves the ones before it already written, as it always has.
        """
        repo = self.file.repo
        logger.debug("%s %s %s", repo, uri, report)

        for key in PROP_SPECTRA_ASSURE_ALL:
            if only is not None and key not in only:
                continue

            value = self._value_for_property(
                key,
                report=report,
                progress=progress,
                scan_status=scan_status,
            )
            logger.debug("%s %s %s %s", key, repo, uri, value)

            if value is None:
                continue

            self.artifactory_api.set_one_prop(
                repo=repo,
                item_uri=uri,
                key=key,
                value=value,
                recursive=recursive,
            )

    def _value_for_property(
        self,
        key: str,
        *,
        report: str | None,
        progress: str,
        scan_status: str | None,
    ) -> str | None:
        """The value to write for one property, or None to not write it."""
        dispatch: dict[str, Callable[[], str | None]] = {
            PROP_NAME_SPECTRA_ASSURE_PROGRESS: lambda: progress,
            PROP_NAME_SPECTRA_ASSURE_TIMESTAMP: self._value_timestamp,
            PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS: lambda: self._value_scan_status(scan_status),
            PROP_NAME_SPECTRA_ASSURE_PURL: self._value_purl,
            PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT: lambda: self._value_report(report),
            PROP_NAME_SPECTRA_ASSURE_ORG: lambda: self._value_portal("org", self.portal_info.org),
            PROP_NAME_SPECTRA_ASSURE_GROUP: lambda: self._value_portal("group", self.portal_info.group),
            PROP_NAME_SPECTRA_ASSURE_SHA256: self._scanned_sha256,
        }

        make = dispatch.get(key)
        if make is None:
            logger.warning("no value known for property %s", key)
            return None

        return make()

    @staticmethod
    def _value_timestamp() -> str:
        now_utc = datetime.now(UTC)
        return now_utc.isoformat()[:19] + "Z"

    def _scanned_sha256(self) -> str | None:
        """The sha256 of the bytes that are scanned, or None when there is none to record.

        For most types that is the item itself. A missing sha2 reaches FileInfo as
        the string 'None', which is not a hash.
        """
        sha2 = self.file.sha2
        if not sha2 or sha2 == "None":
            return None

        return sha2.lower()

    def _value_scan_status(
        self,
        scan_status: str | None,
    ) -> str | None:
        """Only a value we recognise; an unknown one is not written at all."""
        if scan_status is None:
            return None

        if self.know_scan_status(scan_status=scan_status) is False:
            return None

        return scan_status

    def _value_purl(self) -> str:
        return f"pkg:rl/{self.purl_info.make_purl()}"

    def _value_report(
        self,
        report: str | None,
    ) -> str | None:
        if report is None or len(report) == 0:
            return None

        if self.artifactory_report_url_needs_space() is True:
            # apparently one space in front fixes the no view issue
            return " " + report

        return report

    def _value_portal(
        self,
        what: str,
        value: str | None,
    ) -> str | None:
        """The portal org and group; a cli run has neither and writes neither."""
        if self.cli_args.get("portal", False) is not True:
            return None

        if value is None:
            msg = f"expected self.portal_info.{what} is not None"
            raise SpectraAssureInvariantError(msg)

        return value

    def _what_uri_and_recursive(
        self,
    ) -> tuple[bool, str]:
        recursive: bool = False
        uri = self.uri

        if DOCKER_RECURSIVE and self.p_type == "docker":
            recursive = True
            uri = self.up_uri

        return recursive, uri

    def _maintained_properties(self) -> tuple[str, ...]:
        """The RL.* properties this item carries; generic narrows it for a side-car."""
        return tuple(PROP_SPECTRA_ASSURE_ALL)

    def obsolete_properties(self) -> list[str]:
        """Properties of this integration on this item that it no longer maintains (R10.9)."""
        return obsolete_property_names(self.file.properties, self._maintained_properties())

    def remove_obsolete_properties(self) -> None:
        """Delete what obsolete_properties() names, on the item it was written to.

        A failed delete is logged by the api and left for a later run; the item is
        processed either way.
        """
        obsolete = self.obsolete_properties()
        if not obsolete:
            return

        recursive, uri = self._what_uri_and_recursive()
        for key in obsolete:
            if self.artifactory_api.del_one_prop(repo=self.file.repo, item_uri=uri, key=key, recursive=recursive):
                self.file.properties.pop(key, None)

        logger.info("%s:%s; removed obsolete properties: %s", self.file.repo.name, uri, ", ".join(obsolete))

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
        if progress == PROGRESS_SCANNED:
            msg = f"already scanned {self.file.repo.name}{self.uri}"
            logger.info(msg)

            self.processing_info.completed = True
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = progress
            self.processing_info.purl = self.get_prop_purl()
            self.processing_info.report = self.get_prop_report()
            return True

        if progress == PROGRESS_UPLOADED:
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

        if verify_ok is False:
            msg = f"skip: download digest mismatch for: {self.file}"
            logger.error(msg)

            self._remove_files([download_path])
            self.processing_info.completed = True
            self.processing_info.reason = msg
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.purl = self.purl_info.make_purl()
            self.processing_info.report = None
            return False

        if self.purl_info.project is None:
            msg = "expected self.purl_info.project is not None"
            raise SpectraAssureInvariantError(msg)
        if self.purl_info.package is None:
            msg = "expected self.purl_info.package is not None"
            raise SpectraAssureInvariantError(msg)
        if self.purl_info.version is None:
            msg = "expected self.purl_info.version is not None"
            raise SpectraAssureInvariantError(msg)

        is_uploaded = self._do_one_portal_upload(
            project=self.purl_info.project,
            package=self.purl_info.package,
            version=self.purl_info.version,
            file_path=download_path,
        )

        return is_uploaded

    def _get_purl_status(
        self,
    ) -> tuple[Any | None, int]:
        """The portal's answer about this purl, and the status it answered with.

        The caller needs the status code: a 404 means the version is not there,
        which is a settled answer, while other failures may pass on a retry.
        """

        purl = self.purl_info.make_purl()
        project, package, version = self._purl_split(purl=purl)

        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)
        if self.spectra_assure_api is None:
            msg = "expected self.spectra_assure_api is not None"
            raise SpectraAssureInvariantError(msg)

        rr = self.spectra_assure_api.api_client.status(
            project=project,
            package=package,
            version=version,
        )

        status_code: int = rr.status_code
        if status_code < 200 or status_code >= 300:
            logger.warning(
                "status issue (%s) on purl: %s",
                status_code,
                self.purl_info.make_purl(),
            )
            return None, status_code

        return rr.json(), status_code

    def _purl_sync_portal(
        self,
    ) -> bool | None:
        """
        Execute a sync with the current purl componetns

        Returns:
        - None if no sync could be done at all
        - False is no sync is needed
        - True if sync has started

        """
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)
        if self.spectra_assure_api is None:
            msg = "expected self.spectra_assure_api is not None"
            raise SpectraAssureInvariantError(msg)

        purl = self.purl_info.make_purl()
        project, package, version = self._purl_split(purl=purl)

        rr = self.spectra_assure_api.api_client.sync(
            project=project,
            package=package,
            version=version,
        )
        logger.debug("sync issue (%s) on purl: %s", rr.status_code, self.purl_info.make_purl())

        if rr.status_code < 200 or rr.status_code >= 300:
            logger.warning(
                "sync issue (%s) on purl: %s",
                rr.status_code,
                self.purl_info.make_purl(),
            )
            return None

        if int(rr.status_code) not in [200, 202]:  # 200 means no sync needed, 202 means sync started
            msg = "expected int(rr.status_code) in [200, 202]"
            raise SpectraAssureInvariantError(msg)
        sync_started = bool(int(rr.status_code) == 202)
        if sync_started:
            time.sleep(2)

        return sync_started

    def _update_artifactory_item_with_scan_status(
        self,
        scan_status: str | None,
        report: str | None = None,
        progress: str = PROGRESS_SCANNED,
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

    def _get_purl_scan_status_one(
        self,
    ) -> tuple[str | None, str | None, int]:
        """The scan status, its report, and the status the portal answered with."""
        data, status_code = self._get_purl_status()
        if data is None:
            return None, None, status_code

        scan_status = self._get_path_in_dict_simple(
            "analysis.report.info.statistics.quality.status",
            data,
        )

        if scan_status is None or self.know_scan_status(scan_status=scan_status) is False:
            logger.info("SCAN NOT COMPLETE for: %s %s", self.purl_info.make_purl(), self.uri)
            return None, None, status_code

        report = self._get_path_in_dict_simple(
            "analysis.report.info.portal.reference",
            data,
        )

        if scan_status is None:
            msg = "expected scan_status is not None"
            raise SpectraAssureInvariantError(msg)
        if report is None:
            msg = "expected report is not None"
            raise SpectraAssureInvariantError(msg)

        return scan_status, self._strip_redundant_build_is_version(report_url=report), status_code

    def _wait_for_scan_status_one_portal(
        self,
    ) -> bool | None:
        """Wait for the scan of this purl. None when the portal has no such version.

        None is not a failure: it says the thing being waited for cannot arrive,
        so a caller that can upload should do that instead of waiting again.
        """
        if self.max_time <= 0:
            msg = "expected self.max_time > 0"
            raise SpectraAssureInvariantError(msg)
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

        purl = self.purl_info.make_purl()
        time.sleep(1)
        report = None

        n = 0
        absent = 0
        while n < self.max_time:
            scan_status, report, status_code = self._get_purl_scan_status_one()
            if scan_status is not None:
                break

            if status_code == PORTAL_STATUS_ABSENT:
                absent += 1
                if absent >= PORTAL_STATUS_ABSENT_LIMIT:
                    # the portal does not have this version at all, so waiting for
                    # a scan of it cannot succeed however long we wait
                    logger.warning(
                        "%s:%s; the portal has no version '%s' after %d attempts",
                        self.file.repo.name,
                        self.uri,
                        purl,
                        absent,
                    )
                    self.processing_info.completed = False
                    self.processing_info.status = PROCESS_FILE_TIMEOUT
                    self.processing_info.scan_state = None
                    self.processing_info.report = None
                    self.processing_info.purl = purl
                    return None
            else:
                absent = 0

            time.sleep(SCAN_STATUS_WAIT_TIME)  # seconds
            n += SCAN_STATUS_WAIT_TIME
            logger.debug("purl: %s, %d, %s", purl, n, scan_status)

        completed = False
        if scan_status is None:
            logger.warning("timeout reached: no scan status for: '%s'", purl)

            self.processing_info.completed = completed
            self.processing_info.status = PROCESS_FILE_TIMEOUT
            self.processing_info.scan_state = scan_status
            self.processing_info.report = report
            self.processing_info.purl = purl
            return completed

        if report is None:
            msg = "expected report is not None"
            raise SpectraAssureInvariantError(msg)

        completed = True
        self._update_artifactory_item_with_scan_status(
            scan_status=scan_status,
            report=report,
        )

        self.processing_info.completed = completed
        self.processing_info.status = PROCESS_FILE_UPDATED
        self.processing_info.scan_state = scan_status
        self.processing_info.report = report
        self.processing_info.purl = purl

        return completed

    def _exists_on_portal(
        self,
        package: str,
        project: str,
        version: str,
        digest: str | None,
    ) -> tuple[bool, str | None, str | None]:
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)
        if self.spectra_assure_api is None:
            msg = "expected self.spectra_assure_api is not None"
            raise SpectraAssureInvariantError(msg)

        exists, other_bytes = self.spectra_assure_api.exist_version(
            project=project,
            package=package,
            version=version,
            digest=digest,
        )
        self.portal_has_other_bytes = other_bytes
        if exists is False:
            return False, None, None

        scan_status, report, _status_code = self._get_purl_scan_status_one()

        logger.debug("%s", report)
        if report:
            base = self._portal_make_report_base()
            report = f"{base}/{report}"
        logger.debug("%s", report)

        progress = PROGRESS_SCANNED
        if scan_status is None or self.know_scan_status(scan_status=scan_status) is False:
            progress = PROGRESS_UPLOADED

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
    ) -> tuple[str, str, str]:
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
        if self.file is None:
            msg = "expected self.file is not None"
            raise SpectraAssureInvariantError(msg)
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
        """RL.progress, or "" when it was written for other bytes than the item holds now.

        A rebuilt artifact redeployed under the same path may keep the properties
        of the one it replaced, and would then be skipped as already scanned on
        every ordinary run. RL.sha256 records which bytes the properties are
        about; when it differs, nothing has been recorded for these (R10.8).
        Every decision that skips on the properties reads them through here.
        """
        progress = self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_PROGRESS)
        if progress and self._recorded_for_other_bytes():
            return ""

        return progress

    def _recorded_for_other_bytes(
        self,
    ) -> bool:
        """True only when both digests are known and differ.

        No RL.sha256 (written before it existed) or no hash of our own means
        unknown, and unknown lets the recorded progress stand, as it always did.
        """
        recorded = self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_SHA256)
        current = self._scanned_sha256()
        if not recorded or current is None:
            return False

        if recorded.lower() == current:
            return False

        logger.info(
            "%s:%s; rebuilt since the last scan, the properties are about other bytes: %s, now %s",
            self.file.repo.name,
            self.uri,
            recorded,
            current,
        )
        return True

    def get_prop_report(
        self,
    ) -> str:
        return self._get_prop_what(PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT)

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

        last_scan_utc = datetime.strptime(last_scan, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        now_utc = datetime.now(UTC)
        logger.debug("%s now: %s", last_scan_utc, now_utc)

        duration = now_utc - last_scan_utc
        if duration.days > 14:  # any scan older then 2 weeks can be synced
            return True

        return False

    def _portal_make_report_base(
        self,
    ) -> str:
        """Create the correct base for normal and special 'server' strings.

        Portal only: a cli run has no portal to build a url for, so callers check
        the backend before asking.
        """
        if self.spectra_assure_api is None:
            msg = "expected self.spectra_assure_api is not None"
            raise SpectraAssureInvariantError(msg)

        server = self.spectra_assure_api.server
        if server in ["trial", "playground"]:
            return f"https://{server}.{SPECTRA_ASSURE_HOST_BASE}"
        return f"https://{SPECTRA_ASSURE_HOST}/{server}"

    def get_uri(
        self,
    ) -> str:
        return self.uri

    #     def clear_all_spectra_assure_props(
    #         self,
    #     ) -> None:
    #         return
    #
    #         k = "WITH_TEST_CLEAR_PROPS_ALL"
    #         z = bool(int(os.getenv(k, 0)))
    #         if z is False:  # Force Reprocessing or check the portal
    #             return
    #
    #         logger.debug("%s: %s, %s", k, z, self.uri)
    #
    #         recursive, uri = self._what_uri_and_recursive()
    #
    #         to_del: list[str] = []
    #         for key, val in self.file.properties.items():
    #             if key.startswith(f"{SPECTRA_ASSURE_PRE}."):
    #                 self.artifactory_api.del_one_prop(
    #                     repo=self.file.repo,
    #                     item_uri=uri,
    #                     key=key,
    #                     recursive=recursive,
    #                 )
    #                 to_del.append(key)
    #
    #         if len(to_del) > 0:
    #             for k in to_del:
    #                 del self.file.properties[k]

    # PUBLIC
    def cli_can_sync_without_download(
        self,
    ) -> bool:
        """Can this artifact be synced from the store, with no download at all?

        A sync re-analyses what the store already holds - a newer engine, or a
        changed policy, giving a different verdict on the same bytes - so the
        artifact itself is not needed. Deciding that here, before the download,
        is the whole point: the decision used to be made afterwards, so a sync
        run fetched every artifact and then ignored it.

        Docker is excluded: its uploads are bundles this integration assembles,
        so there is nothing in the store that a download would have matched, and
        sync with docker based scanning is not supported at all.
        """
        if self.what_backend != "cli":
            return False
        if self.cli_args.get("cli_docker") is True:
            return False
        if self.p_type == "docker":
            return False

        sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime
        if sync_requested is False:
            return False

        return ScanCliLocal.purl_in_store(
            rlsecure_path=self.cli_args.get("cli_rlsecure_path", ""),
            store=self.cli_args.get("cli_rlstore_path"),
            purl=self.purl_info.make_purl(),
        )

    # PUBLIC
    def cli_synced_artifact_is_unchanged(
        self,
        report_path: str,
    ) -> bool | None:
        """Did the store hold the same bytes artifactory holds?

        Checked after the sync rather than before it: the report we read the
        digest from is the one the sync produced anyway, so a matching digest -
        the ordinary case - costs nothing extra. A mismatch costs one sync that
        has to be followed by a real scan.

        Returns None when the answer is unknown, which every caller must treat
        as a reason to do the full work rather than to skip it.
        """
        expected = self.file.sha2
        if not expected:
            return None

        found = digest_from_report_file(report_path)
        if found is None:
            return None

        if found.lower() == expected.lower():
            return True

        logger.warning(
            "the store holds different content for %s: report %s, artifactory %s",
            self.purl_info.make_purl(),
            found,
            expected,
        )
        return False

    # PUBLIC
    def do_cli_scan_or_sync(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        """Scan this artifact, or sync it from the store without downloading it.

        A sync re-analyses what the store already holds, so when the purl is
        there the artifact is not needed. If the sync then turns out to have been
        about different bytes, the download happens after all and the artifact is
        scanned properly; that costs one wasted sync in the rare case, instead of
        a report generation in every case (R12.7.x).
        """
        if self.cli_can_sync_without_download():
            self.cli_sync_was_stale = False
            handled = self.do_cli_after_download(
                project=project,
                package=package,
                version=version,
                download_path="",
            )
            if self.cli_sync_was_stale is False:
                return handled

            logger.warning(
                "the store held different content for %s: downloading and scanning it",
                self.purl_info.make_purl(),
            )

        return self._cli_download_then_scan(
            project=project,
            package=package,
            version=version,
        )

    def _cli_download_then_scan(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        """Fetch the artifact and scan it: the ordinary path, and the fallback."""
        download_path, verify_ok = self._do_one_artifactory_download()

        if download_path is None:
            msg = f"skip: download failed for: {self.file}"
            logger.error(msg)
            self._set_skip(reason=msg)
            return False

        if verify_ok is False:
            msg = f"skip: download digest mismatch for: {self.file}"
            logger.error(msg)
            self._remove_files([download_path])
            self._set_skip(reason=msg)
            return False

        return self.do_cli_after_download(
            project=project,
            package=package,
            version=version,
            download_path=download_path,
        )

    def _set_skip(
        self,
        reason: str,
    ) -> None:
        self.processing_info.completed = True
        self.processing_info.reason = reason
        self.processing_info.status = PROCESS_FILE_SKIP
        self.processing_info.scan_state = None
        self.processing_info.purl = self.purl_info.make_purl()
        self.processing_info.report = None

    def do_cli_after_download(
        self,
        project: str,
        package: str,
        version: str,
        download_path: str,
    ) -> bool:
        """Scan or sync this artifact with the cli backend, then write the result back.

        An empty download_path means a sync from the store, where the artifact
        itself was never fetched (R12.7.4). That case has one extra step: the
        sync assumed the store holds what artifactory holds, and the report it
        produced is what says whether that was true.
        """
        if self.what_backend != "cli":
            msg = "expected self.what_backend == 'cli'"
            raise SpectraAssureInvariantError(msg)

        logger.debug("purl:: %s/%s@%s;; %s", project, package, version, download_path)

        if download_path:
            self.add_file_to_remove(download_path)

        purl = self.purl_info.make_purl()
        sync_requested = bool(self.cli_args.get("sync", False) or self.need_sync_datetime)

        # the scan directory is removed whatever happens: an exception here is
        # contained per artifact and the run goes on, so a cleanup on the normal
        # paths only left one directory behind for every artifact that raised
        scan_cli = ScanCli(cli_args=self.cli_args)
        try:
            return self._cli_scan_and_record(
                scan_cli=scan_cli,
                purl=purl,
                download_path=download_path,
                sync_requested=sync_requested,
            )
        finally:
            scan_cli.cleanup()

    def _cli_scan_and_record(
        self,
        *,
        scan_cli: ScanCli,
        purl: str,
        download_path: str,
        sync_requested: bool,
    ) -> bool:
        ret, report_bundle_path, scan_status = scan_cli.scan_file(
            file_path=download_path,
            purl=purl,
            sync_requested=sync_requested,
        )

        # ret is 0 for cli rl-secure but ret is 0 or 1 for docker only 101 is a real error
        if scan_status is None or ret in [101]:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = purl
            self.processing_info.reason = f"cli scan failed, no result {ret}"
            return True

        if not download_path and self._sync_was_about_other_bytes(scan_cli):
            self.cli_sync_was_stale = True
            return False

        report_url = self._upload_the_report(
            purl=purl,
            report_bundle_path=report_bundle_path,
        )

        self._update_artifactory_item_with_scan_status(
            scan_status=scan_status,
            report=report_url,
        )

        # after the write above: for docker that write is recursive over the tag
        # directory, which holds the report too, and would put the result back on it
        self._tag_the_report_as_not_to_scan(
            purl=purl,
            report_bundle_path=report_bundle_path,
        )

        self.processing_info.completed = True
        self.processing_info.status = PROCESS_FILE_UPDATED
        self.processing_info.scan_state = scan_status
        self.processing_info.report = report_url
        self.processing_info.purl = purl
        # what happened, not what was asked for: a sync that found the purl was not
        # in the store falls back to a download and a scan (R12.7.4.2), and
        # reporting that as 'cli-sync' made a run look like it synced 548 items
        # when it had scanned every one of them
        self.processing_info.reason = "cli-sync" if not download_path else "cli"
        return True

    def _sync_was_about_other_bytes(
        self,
        scan_cli: ScanCli,
    ) -> bool:
        """True only when the store demonstrably held something else.

        Unknown is not "different": if the digest cannot be read the sync stands,
        because doing the work again on a guess is worse than trusting it
        (R12.7.5.6).
        """
        unchanged = self.cli_synced_artifact_is_unchanged(
            report_path=scan_cli.get_rl_json_report_path(),
        )
        return unchanged is False

    def _report_destination(
        self,
        purl: str,
        report_file_name: str,
    ) -> tuple[str, str]:
        """Which repository the report goes to, and under which uri.

        A remote repository cannot take an upload at all, not even on its cache
        side, so its reports go to the separate local repository named by
        --cli-reports-repo, under a path made from the purl rather than from the
        artifact's own uri.
        """
        repo_name = self.repo.name
        report_uri = f"{self.uri}-{report_file_name}"

        if self.repo.repo_type != "remote":
            return repo_name, report_uri

        reports_repo = self.cli_args.get("cli_reports_repo")
        if reports_repo is None:
            return repo_name, report_uri

        # https://<artifactory>/artifactory/Spectra-Assure-Reports/
        report_name = f"{purl}_{report_file_name}".replace("/", "_").replace("@", "_")
        report_uri = f"/{purl}/".replace("@", "/") + report_name
        return str(reports_repo), report_uri

    def _upload_the_report(
        self,
        purl: str,
        report_bundle_path: str,
    ) -> str | None:
        """Put the report bundle in artifactory; the caller tags it once the item is written."""
        report_file_name = report_bundle_path.split("/")[-1]
        repo_name, report_uri = self._report_destination(
            purl=purl,
            report_file_name=report_file_name,
        )
        logger.debug("%s %s", repo_name, report_uri)

        try:
            r_code, r_text, report_url = self.artifactory_api.upload_file_to_artifactory(
                file_path=report_bundle_path,
                repo_name=repo_name,
                uri_path=report_uri,
            )
            logger.debug("%s %s %s", r_code, r_text, report_url)
        except Exception as e:
            # one artifact's report could not be uploaded, which is not a reason to
            # end a run over thousands of them. Raising lets the per item
            # containment record this artifact and carry on; the run then ends with
            # EXIT_ITEM_FAILURES and this item named in the summary.
            logger.exception(
                "cannot upload report_bundle: %s:%s; %s; %s",
                repo_name,
                report_uri,
                report_bundle_path,
                e,
            )
            msg = f"cannot upload the report bundle to {repo_name}{report_uri}: {e}"
            raise SpectraAssureInvalidAction(msg) from e

        url: str | None = report_url
        return url

    def _tag_the_report_as_not_to_scan(
        self,
        *,
        purl: str,
        report_bundle_path: str,
    ) -> None:
        """A report carries RL.noscan=true and no other property of ours (R10.9.6).

        RL.noscan keeps a later run from treating it as an artifact. Anything
        else is removed: for docker, the recursive write on the tag directory
        reaches the report as well, and a 'fail' there blocks downloading it.

        Only for a local repository: a report that went to the separate reports
        repository is not in the repository being scanned at all.
        """
        if self.repo.repo_type == "remote":
            return

        _, report_uri = self._report_destination(
            purl=purl,
            report_file_name=report_bundle_path.split("/")[-1],
        )
        logger.debug("tag the report: %s", report_uri)

        self.artifactory_api.put_one_prop(
            repo=self.repo,
            item_uri=report_uri,
            key=PROP_NAME_SPECTRA_ASSURE_NOSCAN,
            value="true",
        )

        report = FileInfo(
            repo=self.repo,
            uri=report_uri,
            sha1="",
            sha2="",
            last_modified="",
            file_name=os.path.basename(report_uri),
        )
        properties = self.artifactory_api.get_item_properties(file=report)
        for key in obsolete_property_names(properties, maintained=()):
            self.artifactory_api.del_one_prop(repo=self.repo, item_uri=report_uri, key=key)

    def get_process_status(
        self,
    ) -> str:
        if self.processing_info.status is None:
            msg = "expected self.processing_info.status is not None"
            raise SpectraAssureInvariantError(msg)
        return self.processing_info.status

    def extract_generic_meta_info(
        self,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def collect_list_manifest_info(
        self,
    ) -> None:
        """Pre pass hook: only docker gathers anything here."""
        raise NotImplementedError

    def process(
        self,
    ) -> bool:
        raise NotImplementedError
