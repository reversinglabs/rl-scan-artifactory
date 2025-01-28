# python3 ts=4space

import logging

from rl_scan_artifactory import (
    MyArgs,
    MyApp,
)

logger = logging.getLogger(__name__)


def main() -> None:
    for name in ["requests", "urllib3"]:
        # https://stackoverflow.com/questions/11029717/how-do-i-disable-log-messages-from-the-requests-library
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

    args = MyArgs()
    ma = MyApp(args=args)
    ma.run_all()


if __name__ == "__main__":
    main()
