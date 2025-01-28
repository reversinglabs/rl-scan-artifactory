# python3 ts=4space
import logging
import os

from typing import (
    List,
)

from .spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)


class WithCleanupPortal:
    @staticmethod
    def cleanup_test_portal(
        spectra_assure_api: SpectraAssureApi,
        repo_list: List[str] | None = None,
    ) -> None:
        if repo_list is None:
            repo_list = []

        logger.debug("%s", repo_list)

        response = spectra_assure_api.api_client.list()
        data = response.json()

        for what in ["WITH_TEST_CLEANUP_MY_PROJECTS", "WITH_TEST_CLEANUP_ALL_PROJECTS"]:
            z = bool(int(os.getenv(what, 0)))
            logger.debug("%s: %s", what, z)
            if z is False:
                continue

            for project in data.get("projects", []):
                logger.debug("%s", project)
                p_name = project.get("name", "")
                logger.debug("%s", p_name)
                if what == "WITH_TEST_CLEANUP_MY_PROJECTS" and p_name not in repo_list:
                    # as many package_types modify the project name we will not delete all items anyway
                    # we could do this later on the pUrl if needed.
                    continue

                rr = spectra_assure_api.api_client.delete(project=p_name)
                if rr.status_code <= 200 or rr.status_code > 300:
                    logger.critical("delete: %s %s", p_name, rr)
                else:
                    logger.info("delete: %s %s", p_name, rr)

            return  # effectively we only do one kind of delete
