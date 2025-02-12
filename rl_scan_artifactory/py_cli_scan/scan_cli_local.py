#! /usr/bin/env python3

from typing import (
    List,
    Tuple,
)

import logging
import os
import platform

from collections import deque
from .scan_cli_base import ScanCliBase

logger: logging.Logger = logging.getLogger(__name__)


class ScanCliLocal(
    ScanCliBase,
):
    where: str
    scan_status: int | None

    def __init__(
        self,
        *,
        purl: str,
        where: str,
        store: str | None = None,
        temp_dir_path: str | None = None,  # you handle temp_dir yourself, must be empty
        reports_list: List[str] | None = None,
    ) -> None:
        super().__init__(
            purl=purl,
            store=store,
            temp_dir_path=temp_dir_path,
            reports_list=reports_list,
        )

        self.where: str = where
        if self._licence_status() != 0:
            raise Exception("FATAL: rl-secure init must be done before using this module")

    def _do_command_local(
        self,
        what: str,
        command: List[str],
        base: str = "rl-secure",
    ) -> int:
        assert base in ["rl-secure", "rl-safe"]
        if platform.system() in ["Windows"]:
            base = base + ".exe"

        qcommand = deque(command)
        qcommand.appendleft(os.path.join(self.where, base))

        store = self.store
        assert store is not None, "store cannot be empty"

        k = "/.rl-secure"
        if not store.endswith(k):
            store = store + k

        if what not in ["license", "version"]:
            qcommand.append(f"--rl-store={store}")
            qcommand.append(f"--purl={self.purl}")

        command = list(qcommand)

        return self._do_command(
            what=what,
            command=command,
        )

    def _version_string(
        self,
    ) -> int:
        # /opt/rl/rl-secure version
        command = [
            "version",
        ]

        return self._do_command_local(
            what="version",
            command=command,
        )

    def _licence_status(
        self,
    ) -> int:
        # /opt/rl/rl-secure license status --no-color
        command = [
            "license",
            "status",
            "--no-color",
        ]

        return self._do_command_local(
            what="license",
            command=command,
        )

    def _scan_file(
        self,
        file_path: str,
    ) -> int:
        command = [
            "scan",
            "--no-tracking",
            "--replace",
            f"--file-path={file_path}",
        ]

        return self._do_command_local(
            what="scan",
            command=command,
        )

    def _sync_purl(
        self,
    ) -> int:
        command = [
            "sync",
            "--no-tracking",
        ]
        # future: --work-dir

        return self._do_command_local(
            what="scan",
            command=command,
        )

    def _status_purl(
        self,
    ) -> int:
        command = [
            "status",
            "--no-color",
            "--return-status",
        ]

        return self._do_command_local(
            what="status",
            command=command,
        )

    def _exists_purl(
        self,
    ) -> int:
        command = [
            "status",
            "--no-color",
        ]

        return self._do_command_local(
            what="status",
            command=command,
        )

    def _inspect_purl(
        self,
    ) -> int:
        command = [
            "inspect",
            "--no-color",
            "--all",
            "--fail-only",
        ]

        return self._do_command_local(
            what="inspect",
            command=command,
        )

    def _reports_purl(
        self,
        with_pack_safe: bool = False,
    ) -> int:
        reports = ",".join(self.reports_list)
        command = [
            "report",
            "--no-tracking",
            f"--format={reports}",
            f"--bundle={self.bundle_name}",
            f"--output-path={self.temp_dir_path}",
        ]

        return self._do_command_local(
            what="report",
            command=command,
        )

    def _rl_safe_purl(
        self,
    ) -> int:
        command = [
            "pack",
            "--no-tracking",
            "--format=all",
            f"--output-path={self.temp_dir_path}",
        ]

        return self._do_command_local(
            what="pack",
            command=command,
            base="rl-safe",
        )

    def _common_xxx_and_report(
        self,
        with_pack_safe: bool = False,
    ) -> Tuple[int, str, str | None]:
        self.scan_status = self._status_purl()
        status_string = self.make_scan_status_string()
        report_result = self._reports_purl()

        logger.debug("with_pack_safe: %s", with_pack_safe)
        if with_pack_safe is True:
            self._rl_safe_purl()

        self.make_reports_bundle()
        report_bundle_path = self.get_report_bundle_path()

        return report_result, report_bundle_path, status_string

    # PUBLIC

    def do_scan_and_report(
        self,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> Tuple[int, str, str | None]:

        scan_ok = self._scan_file(
            file_path=file_path,
        )
        if scan_ok != 0:
            return 101, "scan_file failed", None

        return self._common_xxx_and_report(
            with_pack_safe=with_pack_safe,
        )

    def do_sync_and_report(
        self,
        with_pack_safe: bool = False,
    ) -> Tuple[int, str, str | None]:

        scan_ok = self._sync_purl()
        if scan_ok != 0:
            return 101, "sync failed", None

        return self._common_xxx_and_report(
            with_pack_safe=with_pack_safe,
        )

    def test_purl_exists(self) -> bool:
        """Test if the purl actually exists in the given store
        return True if exists
        return False otherwise
        """
        r = self._exists_purl()
        if r == 0:  # the purl exists
            return True
        return False
