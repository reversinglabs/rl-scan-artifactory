#! /usr/bin/env python3

import logging


logger: logging.Logger = logging.getLogger(__name__)


class Results:
    ret_code: int
    stdout: str
    stderr: str

    def __init__(
        self,
        ret_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.ret_code = ret_code
        self.stdout = stdout
        self.stderr = stderr

        logger.debug("exit code %d", ret_code)
        logger.debug("stdout %s", stdout)
        logger.debug("stderr %s", stderr)
