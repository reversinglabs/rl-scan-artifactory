import logging
from typing import (
    Any,
)

from spectra_assure_api_client import SpectraAssureApiOperations  # SDK

from .app_base_with_logging import AppBaseWithLogging
from .constants import (
    DEFAULT_DIGEST_TYPE,
    PORTAL_UPLOAD_TIMEOUT,
)
from .fileinfo import FileInfo
from .my_args import MyArgs

logger = logging.getLogger(__name__)


class SpectraAssureApi(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)

        self.host: str | None = None
        self.server: str | None = None
        self.group: str | None = None
        self.org: str | None = None

        self.host = self.cli_args.get("rlportal_host")
        self.server = self.cli_args.get("rlportal_server")
        self.group = self.cli_args.get("rlportal_group")
        self.org = self.cli_args.get("rlportal_org")
        token = self.cli_args.get("rlportal_access_token")
        proxy_server = self.cli_args.get("proxy_server")
        proxy_port = self.cli_args.get("proxy_port")
        proxy_user = self.cli_args.get("proxy_user")
        proxy_password = self.cli_args.get("proxy_password")
        ignore_cert_errors = bool(self.cli_args.get("ignore_cert_errors"))

        if proxy_port:
            proxy_port = int(proxy_port)

        # very large uploads will need a bit bigger timeout
        self.api_client = SpectraAssureApiOperations(
            host=self.host,
            server=self.server,
            organization=self.org,
            group=self.group,
            token=token,
            auto_adapt_to_throttle=True,
            timeout=PORTAL_UPLOAD_TIMEOUT,  # 2 hours
            proxy_server=proxy_server,
            proxy_port=proxy_port,
            proxy_user=proxy_user,
            proxy_password=proxy_password,
            no_ssl_verify=ignore_cert_errors,
        )

    def status_version(
        self,
        project: str,
        package: str,
        version: str,
    ) -> Any:
        # it is possible we just uploaded the artifact and scanning has not finished yet,
        #  then we may  not have this info yet
        qp: dict[str, Any] = {}

        version_check_response = self.api_client.status(
            project=project,
            package=package,
            version=version,
            **qp,
        )

        logger.debug(
            "%d %s",
            version_check_response.status_code,
            version_check_response.text,
        )

        return version_check_response

    def exist_version(
        self,
        project: str,
        package: str,
        version: str,
        digest: str | None,  # for docker images we will currently not verify the digest
    ) -> tuple[bool, bool]:
        """Does this artifact exist on the portal, as project, package, version and sha256?

        Returns (exists, other_bytes), one of three answers:

        - (False, False): the version is not on the portal
        - (True, False): it is, with these bytes, or there is nothing to compare:
          no digest was given, or the portal has no sha256 for it yet
        - (False, True): it is, with other bytes; an upload must replace it,
          because the portal refuses one to an existing version with a 409

        A digest of None means "do not compare": the caller has no hash that can
        be compared. That is the docker case, where the thing uploaded is a bundle
        this integration builds itself, so artifactory holds no hash of it.

        For everything else the version existing is not enough. A rebuilt artifact
        published under the same version has the same purl and different content,
        and without this check it would be reported as already scanned.
        """
        what = DEFAULT_DIGEST_TYPE
        exists = False

        with_compare_digest = True
        if digest is None:
            with_compare_digest = False

        # exists ?
        version_info = self.api_client.list(
            project=project,
            package=package,
            version=version,
        )
        version_data = version_info.json()
        if version_data.get("version", "") == version:
            exists = True  # it exists but maybe with a different sha256

        # if it now does not exist we are done
        if exists is False:
            logger.debug("%s %s %s", project, package, version)
            return False, False

        if with_compare_digest is False:
            return True, False

        # optionally: is sha256 identical ?
        zz = self.status_version(
            project=project,
            package=package,
            version=version,
        )
        data = zz.json()
        hashes = (
            data.get(
                "analysis",
                {},
            )
            .get(
                "report",
                {},
            )
            .get(
                "info",
                {},
            )
            .get(
                "file",
                {},
            )
            .get(
                "hashes",
                [],
            )
        )

        # each entry is [type, value]; anything else is not ours to interpret
        known = [h[1] for h in hashes if len(h) >= 2 and h[0] == what]

        if not known:
            # no analysis yet, or none with a sha256: nothing to compare against.
            # Not "other bytes": replacing a version whose scan is still running
            # would restart it, so the version alone decides, as with no digest.
            logger.debug("version exists but has no %s to compare: %s", what, hashes)
            return True, False

        if digest not in known:
            logger.info("version exists but digest: %s:%s not found in hashes", what, digest)
            logger.debug("%s", hashes)
            return False, True

        return True, False

    def upload_artifact_to_portal(
        self,
        file: FileInfo,
        project: str,
        package: str,
        version: str,
        file_path: str,
        replace: bool = False,
    ) -> tuple[bool, str | None]:
        """Upload version: scan(project, package, version)

        `replace` overwrites a version already on the portal; without it the
        portal answers 409. Only asked for when the version holds other bytes.
        """
        # purl = f"{project}/{package}@{version}"
        modified = f"{file.last_modified}"

        qp: dict[str, Any] = {
            # "publisher": "ReversingLabs Testing",
            # "product": "a reversingLabs test",
            # "category": "Development",
            # "license": "MIT License Modern Variant",
            # "platform": "Containers",
            "release_date": modified,
            # "build": "version",
        }
        if replace:
            # a string: sdk 1.0.x passes a bool on as "True", which is not a json boolean
            qp["replace"] = "true"

        # create a version with upload (scan)
        rr = self.api_client.scan(
            project=project,
            package=package,
            version=version,
            file_path=file_path,
            **qp,
        )
        logger.debug(
            "upload %s: %d, %s",
            file_path,
            rr.status_code,
            rr.text,
        )

        if rr.status_code < 200 or rr.status_code >= 300:
            msg = f"{rr.status_code}; {rr.reason}; {rr.text}"
            logger.error(msg)
            return False, msg

        # also set is_released if we have lastModified
        if modified:
            qp = {
                "is_released": True,
                "release_date": modified,
            }
            logger.debug("qp: %s", qp)

            rr = self.api_client.edit(
                project=project,
                package=package,
                version=version,
                **qp,
            )
            logger.debug("edit version set is_released: %s", rr)

        return True, None
