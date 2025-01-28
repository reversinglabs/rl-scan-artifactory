# python3 ts=4space

# DANGER THIS WILL DELETE ALL YOUR PROJECTS IN YOUR GROUP
import logging

from rl_scan_artifactory import (
    MyArgs,
)
from rl_scan_artifactory.with_cleanup_porta import WithCleanupPortal
from rl_scan_artifactory.spectra_assure_api import SpectraAssureApi


logger = logging.getLogger(__name__)


def main() -> None:
    for name in ["requests", "urllib3"]:
        # https://stackoverflow.com/questions/11029717/how-do-i-disable-log-messages-from-the-requests-library
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

    args = MyArgs()
    print(args.cli_args["repo"])

    spectra_assure_api = SpectraAssureApi(args=args)
    wcp = WithCleanupPortal()
    wcp.cleanup_test_portal(
        spectra_assure_api=spectra_assure_api,
        repo_list=args.cli_args["repo"],
    )


main()
