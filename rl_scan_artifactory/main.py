# python3 ts=4space

import logging
import sys

from rl_scan_artifactory import (
    MyApp,
    MyArgs,
)

from .constants import (
    EXIT_FATAL,
    EXIT_INTERRUPTED,
)
from .exceptions import SpectraAssureInvalidAction

logger = logging.getLogger(__name__)


def main() -> None:
    for name in ["requests", "urllib3"]:
        # https://stackoverflow.com/questions/11029717/how-do-i-disable-log-messages-from-the-requests-library
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

    # a precondition failure here is a bad invocation, not a crash: EXIT_FATAL and
    # the message, not a traceback the user has to read past
    try:
        args = MyArgs()
        ma = MyApp(args=args)
    except SpectraAssureInvalidAction as e:
        logger.error("%s", e)
        print(f"{e}", file=sys.stderr)  # noqa: T201
        sys.exit(EXIT_FATAL)

    # MyApp contains its own failures per item and per repo; anything arriving here
    # ended the run early, so say so plainly instead of printing a traceback
    try:
        ma.run_all()
    except KeyboardInterrupt:
        msg = "interrupted by the user: the run did not finish"
        logger.warning(msg)
        ma.my_print(msg)
        sys.exit(EXIT_INTERRUPTED)
    except Exception as e:
        msg = f"the run did not finish: {type(e).__name__}: {e}"
        logger.exception(msg)
        ma.my_print(msg)
        sys.exit(EXIT_INTERRUPTED)

    sys.exit(ma.get_exit_code())


if __name__ == "__main__":
    main()
