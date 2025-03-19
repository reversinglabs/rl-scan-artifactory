import logging
from typing import (
    Tuple,
    Dict,
    Any,
)

from spectra_assure_api_client import SpectraAssureApiOperations  # SDK

from .app_base_with_logging import AppBaseWithLogging
from .fileinfo import FileInfo
from .my_args import MyArgs
from .constants import (
    PORTAL_UPLOAD_TIMEOUT,
    DEFAULT_DIGEST_TYPE,
)


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
        #
        token = self.cli_args.get("rlportal_access_token")
        #
        proxy_server = self.cli_args.get("proxy_server")
        proxy_port = self.cli_args.get("proxy_port")
        proxy_user = self.cli_args.get("proxy_user")
        proxy_password = self.cli_args.get("proxy_password")

        if proxy_port:
            proxy_port = int(proxy_port)

        # very large uploads will need a bit bigger timeout
        self.api_client = SpectraAssureApiOperations(
            host=self.host,
            server=self.server,
            #
            organization=self.org,
            group=self.group,
            #
            token=token,
            #
            auto_adapt_to_throttle=True,
            timeout=PORTAL_UPLOAD_TIMEOUT,  # 2 hours
            #
            proxy_server=proxy_server,
            proxy_port=proxy_port,
            proxy_user=proxy_user,
            proxy_password=proxy_password,
        )

    def status_version(
        self,
        project: str,
        package: str,
        version: str,
    ) -> Any:
        # it is possible we just uploaded the artifact and scanning has not finished yet,
        #  then we may  not have this info yet
        qp: Dict[str, Any] = {}

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
    ) -> Tuple[bool, str]:
        """Test if the artifact exist in the portal, with project, package, version, sha256"""
        what = DEFAULT_DIGEST_TYPE
        exists = False
        info = ""

        with_compare_digest = False  # it seems the sha is not always identical
        if digest is None:
            with_compare_digest = False  # it seems the sha is not always identical

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
            return exists, info

        if with_compare_digest is False:
            return exists, info

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

        found = False
        for hash_list in hashes:
            if hash_list[0] == what and hash_list[1] == digest:
                found = True

        if found is False:
            exists = found
            info = f"version exists but digest: {what}:{digest} not found in hashes"
            logger.debug("%s: %s", info, str(hashes))

        return exists, info

    def upload_artifact_to_portal(
        self,
        file: FileInfo,
        project: str,
        package: str,
        version: str,
        file_path: str,
    ) -> Tuple[bool, str | None]:
        """Upload version: scan(project, package, version)"""
        # purl = f"{project}/{package}@{version}"
        modified = f"{file.last_modified}"

        qp: Dict[str, Any] = {
            # "publisher": "ReversingLabs Testing",
            # "product": "a reversingLabs test",
            # "category": "Development",
            # "license": "MIT License Modern Variant",
            # "platform": "Containers",
            "release_date": modified,
            # "build": "version",
        }

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
        if len(modified):
            qp = {
                "is_released": True,
                "release_date": modified,
            }
            logger.debug("qp: %s", str(qp))

            rr = self.api_client.edit(
                project=project,
                package=package,
                version=version,
                **qp,
            )
            logger.debug("edit version set is_released: %s", str(rr))

        return True, None
