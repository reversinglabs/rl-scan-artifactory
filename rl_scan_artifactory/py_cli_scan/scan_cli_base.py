#! /usr/bin/env python3

from typing import (
    List,
    Dict,
)

import os
import subprocess
import tempfile
import logging
import zipfile


from .results import Results
from ..constants import (
    CLI_REPORTS_FILE,
    CliReportFormatList,
)

logger: logging.Logger = logging.getLogger(__name__)


class ScanCliBase:
    STATUS_PASS = 0
    STATUS_FAIL = 1

    bundle_name: str = CLI_REPORTS_FILE
    results: Dict[str, Results]
    purl: str
    clean: bool
    temp_dir_path: str
    pass_fail_string: str

    temp_dir: tempfile.TemporaryDirectory[str] | None
    scan_status: int | None
    store: str | None = None
    reports_list: List[str]

    def __init__(
        self,
        *,
        purl: str,
        store: str | None = None,
        temp_dir_path: str | None = None,  # you handle temp_dir yourself, must be empty
        reports_list: List[str] | None = None,
    ) -> None:
        # ----------------------------------------
        self.temp_dir = None  # must be first
        self.reports_list = [] if reports_list is None else reports_list
        # ----------------------------------------
        self.purl: str = purl
        self.store = store

        # ----------------------------------------
        if temp_dir_path:
            self.temp_dir_path = temp_dir_path
        else:
            self.temp_dir_path = self._make_temp_dir()

        t_real_path = os.path.realpath(self.temp_dir_path)
        assert os.path.exists(t_real_path), f"temp path must exist: {t_real_path}"
        assert os.path.isdir(t_real_path), f"temp path must be a directory {t_real_path}"
        self.temp_dir_path = t_real_path

        # ----------------------------------------
        if self.store is not None:
            s_real_path = os.path.realpath(self.store)
            assert os.path.exists(s_real_path), f"store path must exist: {s_real_path}"
            assert os.path.isdir(s_real_path), f"store path must be a directory {s_real_path}"
            self.store = s_real_path

        # ----------------------------------------
        self.scan_status: int | None = None
        self.clean: bool = True
        self.results = {}

    def __del__(
        self,
    ) -> None:
        logger.debug("")
        self.cleanup_temp_dir()

    def _make_temp_dir(
        self,
    ) -> str:
        logger.debug("")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.clean = False
        return self.temp_dir.name

    def _do_command(
        self,
        what: str,
        command: List[str],
    ) -> int:
        logger.debug("%s", command)

        process = subprocess.run(
            command,
            capture_output=True,
            encoding="utf8",
        )

        self.results[what] = Results(
            ret_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

        return process.returncode

    # PUBLIC
    def cleanup_temp_dir(
        self,
    ) -> None:
        logger.debug("")
        if self.temp_dir is None:
            logger.debug("no temp dir")
            return

        if self.clean is True:
            logger.debug("clean is true")
            return

        if not os.path.exists(self.temp_dir_path):
            logger.debug("path not exists: %s", self.temp_dir_path)
            return

        logger.debug("real cleanup")
        self.temp_dir.cleanup()
        self.clean = True

    def make_reports_bundle(
        self,
    ) -> str:
        reports_folder = self.temp_dir_path
        bundle_name = self.bundle_name

        reports_bundle_path = f"{reports_folder}/{bundle_name}"

        # reports.rl-safe will be put in the regular reports dir when requested with --pack-safe
        with zipfile.ZipFile(reports_bundle_path, "w") as outzip:
            for subdir, dirs, files in os.walk(reports_folder):
                logger.debug("%s %s %s ", subdir, dirs, files)

                for file in files:  # Read file
                    if file == bundle_name:  # skip myself
                        continue

                    source_path = os.path.join(subdir, file)
                    dstpath_in_zip = os.path.relpath(source_path, start=reports_folder)
                    with open(source_path, "rb") as infile:  # Write to zip
                        outzip.writestr(
                            dstpath_in_zip,
                            infile.read(),
                        )

        arr = os.listdir(reports_folder)
        logger.debug("temp dir files: %s", arr)

        return reports_bundle_path

    def set_bundle_name(
        self,
        bundle_name: str,
    ) -> None:
        logger.debug("")
        self.bundle_name = bundle_name

    def make_scan_status_string(
        self,
    ) -> str:
        logger.debug("")
        if self.scan_status not in [0, 1]:
            return "error"

        self.pass_fail_string = "pass" if self.scan_status == 0 else "fail"
        return self.pass_fail_string

    def get_report_bundle_path(
        self,
    ) -> str:
        logger.debug("")
        if self.temp_dir is not None and self.clean is True:
            raise Exception("tempdir is flagged clean: files and dir have already been removed")

        report_bundle_path = f"{self.temp_dir_path}/{self.bundle_name}"
        if not os.path.exists(report_bundle_path):
            raise Exception("the report bundle is not available (yet)")

        return report_bundle_path

    def set_report_list(
        self,
        reports_list: List[str],
    ) -> None:
        if "all" in reports_list:
            self.reports_list = ["all"]
            return

        out_list: List[str] = []
        for report_name in reports_list:
            if report_name in CliReportFormatList:
                if report_name not in out_list:
                    out_list.append(report_name)

        self.reports_list = out_list
