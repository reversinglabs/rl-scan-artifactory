# python3 ts=4space
import configparser
import logging
import time
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..constants import (
    DERIVED_PROPERTY_INFIX,
    FUTURE_GENERIC_PURL_ESCAPE,
    FUTURE_GENERIC_PURL_SEPARATOR,
    META_SECTION_KEY,
    META_STRING,
    PROCESS_FILE_SKIP,
    PROCESS_FILE_TIMEOUT,
    PROCESS_FILE_UPDATED,
    PROGRESS_ALL,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
    PROP_META_FIELDS,
    PROP_META_MANDATORY,
    PROP_META_PRE,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_SPECTRA_ASSURE_ON_SIDE_CAR,
    REPO_DB_DESCRIBED_BY_SIDE_CAR,
    SCAN_STATUS_WAIT_TIME,
)
from ..exceptions import (
    SpectraAssureInvalidAction,
    SpectraAssureInvariantError,
)
from ..file_properties.file_properties_generic import has_meta_properties
from ..name_mangler.name_mangler_common import NameManglerCommon
from ..spectra_assure_api import SpectraAssureApi
from .artifactory_file_processor_common import ArtifactoryFileProcessorCommon

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

    derived = DERIVED_PROPERTY_INFIX
    rl_meta = META_SECTION_KEY
    what = "generic"

    # cli only: True once the purl turned out to be the <repo>/<file>@v0
    # placeholder, which is never synced (R7.11.6)
    purl_is_a_placeholder: bool = False

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

    @staticmethod
    def _escape_string_for_spectra_assure_purl_component(
        string: str | None,
    ) -> str:
        """Make one purl component safe; an absent optional field is an empty component.

        Two schemes, see FUTURE_GENERIC_PURL_ESCAPE in constants.py. The new one
        calls the name manglers' escaper rather than repeating it, so the two can
        no longer drift apart once the flag is on.
        """
        if string is None:
            return ""

        if FUTURE_GENERIC_PURL_ESCAPE:
            return NameManglerCommon._escape_string_for_spectra_assure_purl_component(string)

        trans = {
            "@": "40",
            "/": "2F",
        }
        for k, v in trans.items():
            if k in string:
                string = string.replace(k, f"0x{v}")

        return string

    @staticmethod
    def _purl_separator() -> str:
        """'-' today, '_' as the name manglers use; see FUTURE_GENERIC_PURL_SEPARATOR."""
        if FUTURE_GENERIC_PURL_SEPARATOR:
            return "_"
        return "-"

    def _derived_property(
        self,
        key: str,
    ) -> str | None:
        """One derived property as a scalar.

        The properties themselves are list[str] like every other property (R3.1),
        so every reader has to unwrap; doing it here keeps that in one place.
        """
        values = self.file.properties.get(f"{self.what}.{self.derived}.{key}")
        if not values:
            return None

        value: str = values[0]
        return value

    def _make_meta_dict(
        self,
        config: Any,
    ) -> dict[str, str | None]:
        """Read the side-car section, and mirror it into the derived properties.

        The meta dict keeps every field, absent ones as None, because
        _verify_mandatory has to tell 'missing' from 'empty'. The properties do
        not: their values are list[str] like every other property in this
        codebase, and a field the side-car did not supply gets no property at
        all rather than a None or an empty list.
        """
        meta: dict[str, str | None] = {}

        for n in self.rl_meta_fields:
            value = config[self.rl_meta].get(n)
            meta[n] = value

            k = "arch" if n == "architecture" else n
            key = f"{self.what}.{self.derived}.{k}"

            if value is None:
                self.file.properties.pop(key, None)
                continue

            self.file.properties[key] = [value]

        logger.debug("%s", meta)
        return meta

    def _verify_mandatory(
        self,
        meta: dict[str, Any],
    ) -> None:
        crit = False
        for n in self.rl_meta_mandatory:
            z: str | None = meta[n]
            if z is None or len(z) == 0:
                logger.critical("item %s in %s is mandatory", n, self.rl_meta)
                crit = True

        if crit is True:
            raise SpectraAssureInvalidAction(f"missing mandatory items in {META_STRING} file")

    def _meta_from_properties(
        self,
    ) -> dict[str, str | None] | None:
        """The purl data a person set as RL.meta.* properties on this file (R7.11).

        None when there is none at all. A set that has some but lacks a mandatory
        one is refused like an incomplete side-car (R7.11.3): skipping it quietly,
        or giving it the cli placeholder purl, would hide a mistake the person
        can fix.
        """
        if not has_meta_properties(self.file.properties):
            return None

        meta: dict[str, str | None] = {}
        for n in PROP_META_FIELDS:
            values = self.file.properties.get(f"{PROP_META_PRE}.{n}")
            meta[n] = values[0] if values else None

        missing = [f"{PROP_META_PRE}.{n}" for n in PROP_META_MANDATORY if not meta[n]]
        if missing:
            msg = f"missing mandatory properties: {', '.join(missing)}"
            raise SpectraAssureInvalidAction(msg)

        logger.debug("%s", meta)
        return meta

    def _set_purl_data(
        self,
        meta: dict[str, Any],
    ) -> None:
        sep = self._purl_separator()

        # -- project --
        self.purl_info.project = self.repo.name
        k = "architecture"
        z = self._escape_string_for_spectra_assure_purl_component(meta[k])

        if z is not None and len(z) > 0:
            self.purl_info.project = f"{self.repo.name}{sep}{z}"

        # -- package --
        name = self._escape_string_for_spectra_assure_purl_component(meta["name"])
        self.purl_info.package = name
        k = "namespace"
        z = self._escape_string_for_spectra_assure_purl_component(meta[k])
        if z is not None and len(z) > 0:
            self.purl_info.package = f"{z}{sep}{name}"

        # -- version --
        self.purl_info.version = self._escape_string_for_spectra_assure_purl_component(meta["version"])

    def _load_meta_info(
        self,
    ) -> tuple[bool, Any]:
        """Download the meta file and extract its info"""
        is_downloaded = False

        aa = self.uri.split("/")
        target_name = aa[-1]
        if target_name is None:
            msg = "expected target_name is not None"
            raise SpectraAssureInvariantError(msg)
        download_path, verify_ok = self._do_one_artifactory_download(
            target_name=target_name,
        )

        if download_path is None:
            logger.error("download failed for: %s", self.uri)
            return is_downloaded, None

        if verify_ok is False:
            logger.error("download digest mismatch for: %s", self.uri)
            self._remove_files([download_path])
            return is_downloaded, None

        # interpolation=None: a side-car is data, not a template. With the default
        # BasicInterpolation a '%' in any value raises InterpolationSyntaxError, so
        # a name or version containing one could not be described at all.
        config = configparser.ConfigParser(interpolation=None)
        config.read(download_path)

        if self.rl_meta not in config:
            logger.error("missing %s in meta file: %s", self.rl_meta, download_path)
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
        progress: str = PROGRESS_SCANNED,
    ) -> None:
        logger.debug("%s", report)
        if report is not None and self.what_backend == "portal":
            base = self._portal_make_report_base()
            report = f"{base}/{report}"
        logger.debug("%s", report)

        # The .rl_meta side-car is how a generic artifact is found, never what is
        # scanned: the scan is of the file its 'path' names, so the full result
        # belongs on that file. The side-car keeps only enough to say it was
        # handled and when, which is what a later run reads to skip it.
        described = self._described_file_uri()

        self.set_props_all(
            report=report,
            progress=progress,
            scan_status=scan_status,
            recursive=False,
            uri=described if described is not None else self.uri,
        )

        if described is None:
            self._stamp_the_side_car_of_a_cli_scan(progress=progress)
            return

        self.set_props_all(
            report=report,
            progress=progress,
            scan_status=scan_status,
            recursive=False,
            uri=self.uri,
            only=PROP_SPECTRA_ASSURE_ON_SIDE_CAR,
        )

    def _stamp_the_side_car_of_a_cli_scan(
        self,
        *,
        progress: str,
    ) -> None:
        """A cli scan or sync also updates RL.timestamp on the side-car (R7.10.1).

        Only that one: RL.progress and RL.sha256 there are a portal run's, which
        reads them to decide whether to skip, so they are left as they are.
        """
        if self.cli_args.get("portal"):
            return

        side_car = self._side_car_uri()
        if side_car is None:
            return

        self.set_props_all(
            report=None,
            progress=progress,
            scan_status=None,
            recursive=False,
            uri=side_car,
            only=(PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,),
        )

    def _side_car_uri(
        self,
    ) -> str | None:
        """The side-car describing this file, from the generic pre pass, or None."""
        described_by: dict[str, str] = self.repo_db.get(REPO_DB_DESCRIBED_BY_SIDE_CAR, {})
        for side_car, described in described_by.items():
            if described == self.uri:
                return side_car

        return None

    def _described_file_uri(
        self,
    ) -> str | None:
        """The uri of the file the side-car describes, or None when there is none.

        Portal only: a cli run has no side-car, so self.uri is already the
        artifact.
        """
        if not self.cli_args.get("portal"):
            return None

        path = self._derived_property("path")
        if path is None:
            # the side-car is not read yet when the properties decide whether to
            # read it at all; the pre pass has read it already
            described: str | None = self.repo_db.get(REPO_DB_DESCRIBED_BY_SIDE_CAR, {}).get(self.uri)
            return described

        aa = self.uri.split("/")
        aa[-1] = path
        return "/".join(aa)

    def _maintained_properties(self) -> tuple[str, ...]:
        """A side-car keeps only what says it was handled (R7.10); 1.0.4 wrote the full set.

        A cli run scans the files themselves and never writes on a side-car, but a
        portal run on the same repo does, so a side-car is one in either mode.
        """
        if not self.uri.lower().endswith(META_STRING):
            return super()._maintained_properties()

        return PROP_SPECTRA_ASSURE_ON_SIDE_CAR

    def _scanned_sha256(self) -> str | None:
        """The hash of the file the side-car describes: that is what is scanned.

        A cli run has no side-car, so there self.file is the artifact itself.
        """
        if not self.cli_args.get("portal"):
            return super()._scanned_sha256()

        sha2 = self._portal_artifact_sha2()
        return sha2.lower() if sha2 else None

    def _portal_artifact_sha2(
        self,
    ) -> str | None:
        """The hash of what a portal run scans: the described file, or this one (R7.11.4)."""
        if self._is_side_car():
            return self._described_file_sha2()

        return super()._scanned_sha256()

    def _described_file_sha2(
        self,
    ) -> str | None:
        """The sha256 Artifactory holds for the file the side-car describes.

        Not self.file.sha2, that is the hash of the side-car. The generic pre pass
        keeps the described file's hash from the repository listing in repo_db.
        None when the pre pass did not see it, which compares nothing.
        """
        described = self._described_file_uri()
        if described is None:
            return None

        sha2: str | None = self.repo_db.get(described, {}).get("sha2")
        return sha2

    def _wait_for_scan_status_one_portal(
        self,
    ) -> bool:
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
        while n < self.max_time:
            scan_status, report, _status_code = self._get_purl_scan_status_one()
            if scan_status is not None:
                break

            time.sleep(SCAN_STATUS_WAIT_TIME)  # seconds
            n += SCAN_STATUS_WAIT_TIME
            logger.debug("purl: %s, %d, %s", self.purl_info.make_purl(), n, scan_status)

        completed = False
        if scan_status is None:
            logger.warning("timeout reached: no scan status for: '%s'", self.purl_info.make_purl())

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

    def make_new_uri_from_file_name(
        self,
        file_name: str,
    ) -> str:
        aa = self.uri.split("/")
        aa[-1] = file_name
        return "/".join(aa)

    def _scanned_file(
        self,
    ) -> tuple[str | None, str | None]:
        """The name, next to self.uri, and the expected sha256 of what is scanned.

        For a side-car the file its 'path' names, with the side-car's sha256 if it
        gives one; otherwise this file itself (R7.11.4), with the hash Artifactory
        holds for it.
        """
        if self._is_side_car():
            return self._derived_property("path"), self._derived_property("sha256")

        return self.filename, super()._scanned_sha256()

    def _portal_download_upload_generic(
        self,
        project: str,
        package: str,
        version: str,
    ) -> Any:
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

        is_uploaded = False
        self.processing_info.scan_state = None
        self.processing_info.purl = None
        self.processing_info.report = None

        # download the file the side-car describes, or this file itself (R7.11.4)
        file_name, sha256 = self._scanned_file()
        if file_name is None:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = f"skip: no 'path' in the {META_STRING} file"
            logger.error("no 'path' in the %s of %s", META_STRING, self.uri)
            return is_uploaded

        new_uri = self.make_new_uri_from_file_name(file_name=file_name)
        target_path = "/".join([self.download_dir, file_name])
        url = f"{self.artifactory_api.get_base_url()}/{self.file.repo.name}{new_uri}"
        download_path, verify_ok = self.artifactory_api.download_url_to_target_with_verify(
            url=url,
            target_path=target_path,
            sha256=sha256,
        )
        if download_path is None:
            # if we block with `rlArtifactoryPlugin`,  we get no download dir
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "skip: file cannot be downloaded"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return is_uploaded

        if verify_ok is False:
            logger.error("download digest mismatch for: %s", self.file)

            self._remove_files([download_path])
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.reason = "skip: download digest mismatch"
            self.processing_info.scan_state = None
            self.processing_info.report = None
            self.processing_info.purl = None
            return is_uploaded

        if download_path is None:
            msg = "expected download_path is not None"
            raise SpectraAssureInvariantError(msg)
        # upload the file
        is_uploaded = self._do_one_portal_upload(
            project=project,
            package=package,
            version=version,
            file_path=download_path,
        )
        if is_uploaded is False:
            self.processing_info.completed = True
            self.processing_info.reason = "upload to portal failed"
            self.processing_info.status = PROCESS_FILE_SKIP
            return is_uploaded

        self.set_props_all(
            report=None,
            progress=PROGRESS_UPLOADED,
            scan_status=None,
            recursive=False,
            uri=self.make_new_uri_from_file_name(
                file_name=file_name,
            ),
        )
        return is_uploaded

    def _process_portal(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

        is_uploaded = False
        purl = self.purl_info.make_purl()
        sync_requested = self.sync_requested()

        exists_on_portal, scan_status, report = self._exists_on_portal(
            project=project,
            package=package,
            version=version,
            digest=self._portal_artifact_sha2(),
        )
        logger.debug("scan status: %s", scan_status)

        if exists_on_portal is True:
            is_uploaded = True
            self.processing_info.reason = "purl exists on portal"

            if sync_requested is False:
                if scan_status in ["pass", "fail"]:
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = scan_status
                    self.processing_info.purl = purl
                    self.processing_info.report = report
                    self.processing_info.completed = True
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
                    return True
        else:
            is_uploaded = self._portal_download_upload_generic(
                project=project,
                package=package,
                version=version,
            )
            if is_uploaded is False:
                return True

        return bool(self._wait_for_scan_status_one_portal())

    def process_portal(
        self,
    ) -> bool:
        """Scan one generic artifact against the portal.

        A generic repository has no layout to derive a purl from, so the purl
        comes from the .rl_meta side-car or the RL.meta.* properties (§7). The steps are the same three as in
        process_cli, with the side-car read where cli derives a name instead.
        """
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

        handled = self._stop_if_not_a_candidate()
        if handled is not None:
            return handled

        handled = self._stop_if_an_earlier_run_finished_this(purl_is_a_placeholder=False)
        if handled is not None:
            return handled

        logger.debug("inspect %s", self.uri)

        handled = self._stop_if_there_is_no_purl_data()
        if handled is not None:
            return handled

        project, package, version = self._purl_parts()

        return self._process_portal(
            project=project,
            package=package,
            version=version,
        )

    def _stop_if_there_is_no_purl_data(
        self,
    ) -> bool | None:
        """Portal: read the purl data from the side-car or the RL.meta.* properties.

        None to carry on with the purl set; R7.11.1 and R7.11.2 decide which.
        """
        if self._is_side_car():
            meta_ok, _ = self._load_meta_info()  # if there is no meta we ignore this item
            if meta_ok is False:
                return self._stop("meta file extract failed")
            return None

        meta = self._meta_from_properties()
        if meta is None:
            # the candidate check lets no other file through in portal mode (R7.11.5)
            msg = f"expected a {META_STRING} side-car or {PROP_META_PRE}.* properties: {self.uri}"
            raise SpectraAssureInvariantError(msg)

        self._set_purl_data(meta=meta)
        return None

    def _process_cli(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        if self.what_backend != "cli":
            msg = "expected self.what_backend == 'cli'"
            raise SpectraAssureInvariantError(msg)

        logger.debug("candidate2 %s", self.uri)

        self._populate_purl_info(project, package, version)

        return self.do_cli_scan_or_sync(
            project=project,
            package=package,
            version=version,
        )

    def process_cli(
        self,
    ) -> bool:
        """Scan one generic artifact with the cli backend.

        The purl comes from the side-car, the RL.meta.* properties, or else the
        repository name and the file name (R7.11.6). Only a real purl is synced:
        the placeholder names a file, not a package version, so a sync of it
        would re-analyse whatever was last stored under that name.
        """
        if self.what_backend != "cli":
            msg = "expected self.what_backend == 'cli'"
            raise SpectraAssureInvariantError(msg)

        logger.debug("candidate1 %s", self.uri)

        handled = self._stop_if_not_a_candidate()
        if handled is not None:
            return handled

        handled = self._stop_if_an_earlier_run_finished_this(
            purl_is_a_placeholder=not self._has_purl_data(),
        )
        if handled is not None:
            return handled

        logger.debug("inspect %s", self.uri)
        self._set_purl_without_a_meta_file()
        project, package, version = self._purl_parts()

        return self._process_cli(
            project=project,
            package=package,
            version=version,
        )

    def _stop(
        self,
        reason: str,
        *,
        from_properties: bool = False,
    ) -> bool:
        """Stop with this reason.

        `from_properties` carries over what an earlier run recorded, for the cases
        where we stop *because* of it; otherwise the fields are cleared, because
        nothing has been established about this artifact.
        """
        self.processing_info.completed = True
        self.processing_info.status = PROCESS_FILE_SKIP
        self.processing_info.reason = reason

        if from_properties:
            self.processing_info.scan_state = self.get_prop_progress()
            self.processing_info.report = self.get_prop_report()
            self.processing_info.purl = self.get_prop_purl()
            return True

        self.processing_info.scan_state = None
        self.processing_info.report = None
        self.processing_info.purl = None
        return True

    def _stop_if_not_a_candidate(
        self,
    ) -> bool | None:
        """None to carry on. Without a side-car every file has to be looked at."""
        if self.fp is None:
            msg = "expected self.fp is not None"
            raise SpectraAssureInvariantError(msg)

        if self.fp.skip_non_candidate_file():
            logger.debug("skip: %s", self.uri)
            return self._stop("skip: not a candidate for inspection")

        if self.cli_args.get("portal") and self._is_described_by_a_side_car():
            # the side-car wins over RL.meta.* properties (R7.11.2); the portal
            # run handles this file when it reaches the side-car
            logger.debug("skip: %s is described by a %s side-car", self.uri, META_STRING)
            return self._stop(f"skip: described by a {META_STRING} side-car")

        return None

    def _is_side_car(self) -> bool:
        return self.uri.lower().endswith(META_STRING)

    def _is_described_by_a_side_car(self) -> bool:
        """True when the generic pre pass found a side-car naming this file."""
        described_by: dict[str, str] = self.repo_db.get(REPO_DB_DESCRIBED_BY_SIDE_CAR, {})
        return self.uri in described_by.values()

    def _stop_if_an_earlier_run_finished_this(
        self,
        *,
        purl_is_a_placeholder: bool,
    ) -> bool | None:
        """What the RL.* properties of an earlier run say. None to carry on.

        `purl_is_a_placeholder` is the one difference between the two backends:
        a cli run without a side-car or RL.meta.* properties has only the
        <repo>/<file>@v0 placeholder, and that is never synced (R7.11.6).
        """
        progress = self.get_prop_progress()
        if progress not in PROGRESS_ALL:
            return None

        if self.cli_args.get("ignore_artifactory_properties") is not False:
            return None

        # if the scan date is older then 2 weeks schedule a sync instead of a scan # TODO
        if progress != PROGRESS_SCANNED:
            return None

        if self.sync_possible() is False:  # requires property scanned
            return self._stop("already processed", from_properties=True)

        # we can do a sync instead of a scan
        self.need_sync_datetime = True

        if purl_is_a_placeholder:
            return self._stop(
                f"sync not possible with cli: no {META_STRING} side-car and no {PROP_META_PRE}.* properties",
                from_properties=True,
            )

        return None

    def _has_purl_data(self) -> bool:
        """A side-car the pre pass read, or RL.meta.* properties (complete or not).

        Decided without raising: an incomplete set raises only once the purl is
        actually made (R7.11.3).
        """
        return self.uri in self.repo_db or has_meta_properties(self.file.properties)

    def sync_requested(self) -> bool:
        """The placeholder purl is never synced, not even on --sync (R7.11.6)."""
        if self.what_backend == "cli" and self.purl_is_a_placeholder:
            return False
        return super().sync_requested()

    def _set_purl_without_a_meta_file(
        self,
    ) -> None:
        """The cli purl (R7.11.6): from the side-car the pre pass read, else from the
        RL.meta.* properties, else the placeholder of the repository name and the
        file name.
        """
        self.purl_is_a_placeholder = False
        if self.uri not in self.repo_db:
            meta = self._meta_from_properties()
            if meta is not None:
                self._set_purl_data(meta=meta)
                return
            self.purl_is_a_placeholder = True

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

        self.purl_info.project = meta_info["project"]
        self.purl_info.package = meta_info["package"]
        self.purl_info.version = meta_info["version"]

    def _purl_parts(
        self,
    ) -> tuple[str, str, str]:
        """The three purl components, once whatever set them says it succeeded."""
        if self.purl_info.project is None:
            msg = "expected self.purl_info.project is not None"
            raise SpectraAssureInvariantError(msg)
        if self.purl_info.package is None:
            msg = "expected self.purl_info.package is not None"
            raise SpectraAssureInvariantError(msg)
        if self.purl_info.version is None:
            msg = "expected self.purl_info.version is not None"
            raise SpectraAssureInvariantError(msg)

        return self.purl_info.project, self.purl_info.package, self.purl_info.version

    # PUBLIC
    def extract_generic_meta_info(self) -> dict[str, Any]:
        """
        Download the rl_meta file
        extract its properties,
        return a dict with the meta info and a valid purl.
        """
        meta_dict: dict[str, Any] = {}
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

    def process(
        self,
    ) -> bool:  # completed yes/no if no we have uploaded but the scan has not completed yet
        # will load the properties from artifactory or create derived based on uri
        if self.fp is None:
            msg = "expected self.fp is not None"
            raise SpectraAssureInvariantError(msg)
        if self.what_backend == "portal":
            return self.process_portal()
        return self.process_cli()
