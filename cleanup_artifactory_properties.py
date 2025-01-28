import logging
import os

from typing import (
    Dict,
    List,
    Any,
)

from rl_scan_artifactory import (
    MyArgs,
)
from rl_scan_artifactory.constants import (
    ARTIFACTORY_KNOWN_PACKAGE_TYPES,
    SPECTRA_ASSURE_PRE,
)
from rl_scan_artifactory.app_base_with_logging import AppBaseWithLogging
from rl_scan_artifactory.artifactory_api import ArtifactoryApi
from rl_scan_artifactory.artifactory_repo_info import ArtifactoryRepoInfo
from rl_scan_artifactory.fileinfo import FileInfo

logger = logging.getLogger("")


class ArtifactoryCleanup(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)
        self._validate_params()
        self.artifactory_api = ArtifactoryApi(args=args)
        self.verbose = self.cli_args["verbose"]
        logger.debug("%s", args.cli_args)

    def _validate_params(
        self,
    ) -> None:
        self.repo_list = self.cli_args["repo"]
        assert len(self.repo_list) > 0

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
            if self.p_type != "generic":
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

    def clear_all_spectra_assure_props(
        self,
        file: FileInfo,
    ) -> None:
        to_del: List[str] = []
        for key, val in file.properties.items():
            if key.startswith(f"{SPECTRA_ASSURE_PRE}."):
                logger.debug(key)
                self.artifactory_api.del_one_prop(
                    repo=file.repo,
                    item_uri=file.uri,
                    key=key,
                    recursive=False,
                )
                to_del.append(key)

            if key.startswith("Spectra.Assure."):
                logger.debug(key)
                self.artifactory_api.del_one_prop(
                    repo=file.repo,
                    item_uri=file.uri,
                    key=key,
                    recursive=False,
                )
                to_del.append(key)

        if len(to_del) > 0:
            logger.debug(to_del)
            for k in to_del:
                del file.properties[k]

    def run(
        self,
    ) -> None:
        repo_names = self.cli_args.get("repo", [])
        for repo_name in sorted(repo_names):
            repo = self._make_repo_info(repo_name=repo_name)
            self.p_type = repo.package_type.lower()
            item_list = self._make_file_list_one_repo(
                repo=repo,
            )
            for item in item_list:
                uri = item.get("uri", "")
                file = FileInfo(
                    repo=repo,
                    uri=uri,
                    sha1=str(item.get("sha1")),
                    sha2=str(item.get("sha2")),
                    last_modified=item.get("lastModified", ""),
                    file_name=os.path.basename(uri),
                )
                file.properties = self.artifactory_api.get_item_properties(file=file)
                print("# FILE: ", file)
                print("# PRE: ", file.properties)

                self.clear_all_spectra_assure_props(file=file)

                props = self.artifactory_api.get_item_properties(file=file)
                print("# POST: ", props)


def main() -> None:
    for name in ["requests", "urllib3"]:
        # https://stackoverflow.com/questions/11029717/how-do-i-disable-log-messages-from-the-requests-library
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

    args = MyArgs()

    ac = ArtifactoryCleanup(args=args)
    ac.run()


main()
