# python3 ts=4space
import logging
from typing import (
    Any,
    Dict,
    List,
)

from .artifactory_api import ArtifactoryApi
from .artifactory_repo_info import ArtifactoryRepoInfo
from .artifactory_to_portal_base import ArtifactoryToPortalBase
from .constants import (
    ARTIFACTORY_KNOWN_PACKAGE_TYPES,
)
from .spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)


class ArtifactoryRepoProcessor(
    ArtifactoryToPortalBase,
):
    def __init__(
        self,
        *,
        cli_args: Dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo_name: str,
    ) -> None:
        super().__init__(
            cli_args=cli_args,
            spectra_assure_api=spectra_assure_api,
            artifactory_api=artifactory_api,
        )
        self.repo = self._make_repo_info(
            repo_name=repo_name,
        )
        self.p_type = self.repo.package_type.lower()

    def _make_repo_info(
        self,
        repo_name: str,
    ) -> ArtifactoryRepoInfo:
        repo_info = self.artifactory_api.get_repo_info(repo_name)
        logger.debug("%s", repo_info)

        repo = ArtifactoryRepoInfo(
            name=repo_name,
            repo_type=repo_info.get("type", ""),
            package_type=repo_info.get("packageType", ""),
            layout=repo_info.get("repoLayoutRef", ""),
            environments=repo_info.get("environments", []),
        )
        logger.debug("%s", repo)

        return repo

    def extract_my_interesting_files(
        self,
        one_repo_list: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        my_interesting_files: List[Dict[str, Any]] = []

        for item in one_repo_list.get("files", []):
            if not (self.p_type == "generic" and self.cli_args.get("cli")):
                # only ends with (if defined)
                ew = ARTIFACTORY_KNOWN_PACKAGE_TYPES[self.p_type].get("endswith", "")
                if len(ew) > 0:
                    if not item.get("uri", "").endswith(ew):
                        continue

                # skip specific items not endswith (if defined)
                not_ew = ARTIFACTORY_KNOWN_PACKAGE_TYPES[self.p_type].get("not_endswith", "")
                if len(not_ew) > 0:
                    if item.get("uri", "").endswith(not_ew):
                        continue

            logger.debug("append %s", item)
            my_interesting_files.append(item)

        return my_interesting_files

    def _make_file_list_one_repo(
        self,
        repo: ArtifactoryRepoInfo,
    ) -> List[Dict[str, Any]]:
        if self.p_type not in ARTIFACTORY_KNOWN_PACKAGE_TYPES:
            return []

        qp: Dict[str, Any] = {
            "deep": 1,
            "mdTimestamps": 0,
            "listFolders": 0,
        }

        one_repo_list = self.artifactory_api.list_repo_items(
            repo=repo,
            qp=qp,
        )

        return self.extract_my_interesting_files(one_repo_list)

    # PUBLIC

    def get_repo(
        self,
    ) -> ArtifactoryRepoInfo:
        return self.repo

    def get_ptype(
        self,
    ) -> str:
        return self.p_type

    def process(
        self,
    ) -> List[Dict[str, Any]]:
        return self._make_file_list_one_repo(
            repo=self.repo,
        )
