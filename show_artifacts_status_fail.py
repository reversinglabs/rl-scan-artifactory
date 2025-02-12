#! /usr/bin/env python3
import logging

from rl_scan_artifactory import (
    MyArgs,
)
from rl_scan_artifactory.app_base_with_logging import AppBaseWithLogging
from rl_scan_artifactory.artifactory_api import ArtifactoryApi

logger = logging.getLogger(__name__)


class ArtifactoryCleanup(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)
        self.repo_list = self.cli_args["repo"]
        self.artifactory_api = ArtifactoryApi(args=args)
        self.verbose = self.cli_args["verbose"]
        logger.debug("%s", args.cli_args)

    def run(
        self,
    ) -> None:
        rr = self.artifactory_api.search_prop_fail()
        logger.debug("%s", rr)
        if "results" not in rr:
            return

        for item in rr["results"]:
            uri = item.get("uri")
            if not uri:
                continue

            repo_list = self.cli_args.get("repo")
            if repo_list is None or len(repo_list) == 0:
                print(uri)
                continue

            for repo in repo_list:
                if f"/storage/{repo}/" in uri or f"/storage/{repo}-cache/" in uri:
                    print(uri)


def main() -> None:
    for name in ["requests", "urllib3"]:
        # https://stackoverflow.com/questions/11029717/how-do-i-disable-log-messages-from-the-requests-library
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

    args = MyArgs(
        repo_list_may_be_empty=True,
        no_portal_or_cli=True,
    )

    ac = ArtifactoryCleanup(args=args)
    ac.run()


main()
