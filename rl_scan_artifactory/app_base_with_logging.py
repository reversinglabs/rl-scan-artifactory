# python3 ts=4space


import logging
import sys
from datetime import datetime

from .my_args import MyArgs

logger = logging.getLogger(__name__)

LOG_FORMAT: str = " ".join(
    [
        "%(asctime)s",
        "%(levelname)s",
        "%(pathname)s:%(lineno)s:%(funcName)s",
        "%(message)s",
    ],
)


class AppBaseWithLogging:
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        self.now_iso = datetime.now(
            datetime.now().astimezone().tzinfo,
        ).isoformat()

        self.prog = args.prog
        self.cli_args = args.cli_args

        self.verbose = self.cli_args["verbose"]
        self._setup_logging()

    def _setup_logging(
        self,
    ) -> None:
        """Log to <prog>.log, and additionally to stderr with --log-to-stderr.

        The log file is always written: it is what you look at after a run.

        The console copy goes to stderr, not stdout: stdout carries the program's
        own output, the progress lines of --verbose, so a caller can redirect one
        without the other. Keeping both on stdout meant they interleaved and the
        progress lines had to be suppressed to avoid printing twice.
        """
        log_level = self.cli_args.get("log_level", "INFO")
        if log_level is None:
            log_level = "WARNING"

        log_level = log_level.upper()

        handlers: list[logging.Handler] = [
            logging.FileHandler(
                filename=f"{self.prog}.log",
                encoding="utf-8",
            ),
        ]

        if self.cli_args.get("log_to_stderr"):
            handlers.append(logging.StreamHandler(stream=sys.stderr))

        logging.basicConfig(
            level=log_level,
            format=LOG_FORMAT,
            handlers=handlers,
        )
