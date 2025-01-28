# python3 ts=4space


import logging
from datetime import datetime

from .my_args import MyArgs

logger = logging.getLogger(__name__)


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
        log_level = self.cli_args.get("log_level", "INFO")
        if log_level is None:
            log_level = "WARNING"

        log_level = log_level.upper()
        logging.basicConfig(
            filename=f"{self.prog}.log",
            encoding="utf-8",
            level=log_level,
            format=" ".join(
                [
                    "%(asctime)s",
                    "%(levelname)s",
                    "%(pathname)s:%(lineno)s:%(funcName)s",
                    "%(message)s",
                ]
            ),
        )
