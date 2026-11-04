#! /usr/bin/env python3

import logging
import os
import pathlib
import subprocess
import zipfile

from rl_scan_artifactory.constants import (
    CLI_REPORTS_FILE,
    REPORT_FILE_RL_JSON,
    REPORT_FORMAT_RL_JSON,
    CliReportFormatList,
)

logger: logging.Logger = logging.getLogger(__name__)


class ScanCliBase:
    STATUS_PASS = 0
    STATUS_FAIL = 1

    bundle_name: str = CLI_REPORTS_FILE
    purl: str
    temp_dir_path: str
    pass_fail_string: str

    scan_status: int | None
    store: str | None = None
    reports_list: list[str]
    rl_json_was_requested: bool

    def __init__(
        self,
        *,
        purl: str,
        store: str | None = None,
        temp_dir_path: str,  # owned and removed by the caller, must be empty
        reports_list: list[str] | None = None,
    ) -> None:
        """Scan in `temp_dir_path`, which the caller creates and removes.

        The scanner used to make its own when none was given, and clean it up in
        `__del__`; nothing ever asked it to, and its cleanup never ran (A.16). One
        owner, with the removal in a `finally`, is the only one that is reliable.
        """
        # ----------------------------------------
        self.reports_list = []
        self.rl_json_was_requested = True
        if reports_list:
            self.set_report_list(reports_list)
        # ----------------------------------------
        self.purl: str = purl
        self.store = store

        # ----------------------------------------
        t_real_path = os.path.realpath(temp_dir_path)

        if not pathlib.Path(t_real_path).exists():
            msg = f"temp path must exist: {t_real_path}"
            raise ValueError(msg)

        if not pathlib.Path(t_real_path).is_dir():
            msg = f"temp path must be a directory {t_real_path}"
            raise ValueError(msg)

        self.temp_dir_path = t_real_path

        # ----------------------------------------
        if self.store is not None:
            s_real_path = os.path.realpath(self.store)

            if not pathlib.Path(s_real_path).exists():
                msg = f"store path must exist: {s_real_path}"
                raise ValueError(msg)

            if not pathlib.Path(s_real_path).is_dir():
                msg = f"store path must be a directory {s_real_path}"
                raise ValueError(msg)

            self.store = s_real_path

        # ----------------------------------------
        self.scan_status: int | None = None

    def _do_command(
        self,
        what: str,
        command: list[str],
        secrets: dict[str, str] | None = None,
        answer_codes: tuple[int, ...] | None = (0,),
    ) -> int:
        """Run one command and keep its result.

        `secrets` are added to the environment of the child process, never to the
        command line: an argv element is visible in `ps` to every user on the host
        for as long as the command runs.

        `answer_codes` are the return codes that are an answer rather than a
        failure, and so are not logged as errors. Most commands answer only with
        0; `rl-secure status` answers with the scan result, and 'this purl has not
        been scanned yet' is one of its answers, not something to complain about.
        Pass None when every code is an answer and the caller does the deciding.

        Never shell=True: the command is a list and stays a list, so nothing in a
        file name or a purl can be read as shell syntax.
        """
        logger.debug("%s", command)

        env: dict[str, str] | None = None
        if secrets:
            env = {**os.environ, **secrets}

        process = subprocess.run(
            command,
            capture_output=True,
            encoding="utf8",
            check=False,
            env=env,
        )

        # the output of every command, at debug: this was the only thing the
        # self.results dict did, and nothing ever read the dict
        logger.debug("%s exit code %s", what, process.returncode)
        logger.debug("%s stdout %s", what, process.stdout)
        logger.debug("%s stderr %s", what, process.stderr)

        if answer_codes is not None and process.returncode not in answer_codes:
            # without this a failing scan is silent at the default log level, and
            # the reason the scanner gave is the only thing that explains it
            logger.error(
                "command '%s' failed with %s: %s",
                what,
                process.returncode,
                (process.stderr or "").strip(),
            )

        return process.returncode

    # PUBLIC
    def make_reports_bundle(
        self,
    ) -> str:
        reports_folder = self.temp_dir_path
        bundle_name = self.bundle_name

        reports_bundle_path = f"{reports_folder}/{bundle_name}"

        # rl-json is generated for our own use; ship it only if it was asked for
        skip = {bundle_name}
        if not self.rl_json_was_requested:
            skip.add(REPORT_FILE_RL_JSON)

        # reports.rl-safe will be put in the regular reports dir when requested with --pack-safe
        with zipfile.ZipFile(reports_bundle_path, "w") as outzip:
            for subdir, dirs, files in os.walk(reports_folder):
                logger.debug("%s %s %s ", subdir, dirs, files)

                for file in files:  # Read file
                    if file in skip:  # myself, and rl-json when not requested
                        continue

                    source_path = pathlib.Path(subdir) / file
                    dstpath_in_zip = os.path.relpath(source_path, start=reports_folder)
                    data = pathlib.Path(source_path).read_bytes()
                    outzip.writestr(dstpath_in_zip, data)

        return reports_bundle_path

    def make_scan_status_string(
        self,
    ) -> str:
        logger.debug("")
        if self.scan_status not in {0, 1}:
            return "error"

        self.pass_fail_string = "pass" if self.scan_status == 0 else "fail"
        return self.pass_fail_string

    def get_report_bundle_path(
        self,
    ) -> str:
        logger.debug("")
        report_bundle_path = f"{self.temp_dir_path}/{self.bundle_name}"
        if not pathlib.Path(report_bundle_path).exists():
            msg = "the report bundle is not available (yet)"
            raise RuntimeError(msg)

        return report_bundle_path

    def set_report_list(
        self,
        reports_list: list[str],
    ) -> None:
        """The reports to generate, plus rl-json whether or not it was asked for.

        rl-json is how the sha256 of what the store holds is read back
        (report.info.file.hashes). It is generated always, and removed again
        before the bundle is built when the user did not ask for it, so their
        bundle holds exactly what they requested.
        """
        self.rl_json_was_requested = True

        if "all" in reports_list:
            self.reports_list = ["all"]
            return

        out_list: list[str] = []
        for report_name in reports_list:
            if report_name in CliReportFormatList and report_name not in out_list:
                out_list.append(report_name)

        self.rl_json_was_requested = REPORT_FORMAT_RL_JSON in out_list
        if not self.rl_json_was_requested:
            out_list.append(REPORT_FORMAT_RL_JSON)

        self.reports_list = out_list

    # PUBLIC
    def get_rl_json_report_path(
        self,
    ) -> str:
        """Where the rl-json report of the last scan or sync is."""
        return str(pathlib.Path(self.temp_dir_path) / REPORT_FILE_RL_JSON)
