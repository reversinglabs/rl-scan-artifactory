#! /usr/bin/env python3

import logging
import platform
from collections import deque
from pathlib import Path

from .scan_cli_base import ScanCliBase

logger: logging.Logger = logging.getLogger(__name__)


# What each rl-secure command needs appended. 'version' and 'license' ask about
# the installation itself; 'list' asks about the store; everything else works on
# one package in the store and needs both.
COMMANDS_WITHOUT_STORE: frozenset[str] = frozenset({"version", "license"})
COMMANDS_WITHOUT_PURL: frozenset[str] = COMMANDS_WITHOUT_STORE | {"list"}


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
        temp_dir_path: str,  # owned and removed by the caller, must be empty
        reports_list: list[str] | None = None,
    ) -> None:
        super().__init__(
            purl=purl,
            store=store,
            temp_dir_path=temp_dir_path,
            reports_list=reports_list,
        )

        self.where: str = where
        if self._licence_status() != 0:
            msg = "FATAL: rl-secure init must be done before using this module"
            raise RuntimeError(msg)

    def _do_command_local(
        self,
        *,
        what: str,
        command: list[str],
        base: str = "rl-secure",
        answer_codes: tuple[int, ...] | None = (0,),
    ) -> int:
        if base not in {"rl-secure", "rl-safe"}:
            msg = "base must be one of: 'rl-secure', 'rl-safe'"
            raise RuntimeError(msg)

        if platform.system() == "Windows":
            base += ".exe"

        qcommand = deque(command)
        qcommand.appendleft(str(Path(self.where) / base))

        if what not in COMMANDS_WITHOUT_STORE:
            store = self.store
            if not store:
                msg = f"the '{what}' command needs an rl-store and none is set"
                raise RuntimeError(msg)

            k = "/.rl-secure"
            if not store.endswith(k):
                store += k

            qcommand.append(f"--rl-store={store}")

        if what not in COMMANDS_WITHOUT_PURL:
            qcommand.append(f"--purl={self.purl}")

        # temp fix to 6 later cli arg in case of cli, for docker we would need a updated docker image and extra param
        # qcommand.append("--concurrency=2")
        command = list(qcommand)

        logger.debug("%s", command)

        return self._do_command(
            what=what,
            command=command,
            answer_codes=answer_codes,
        )

    # PUBLIC
    @staticmethod
    def purl_in_store(
        rlsecure_path: str,
        store: str | None,
        purl: str,
    ) -> bool:
        """Is this purl already in the store? Asked without the artifact.

        A sync re-analyses what the store already holds, so whether a sync is
        possible at all can be decided before anything is downloaded. It used to
        be decided after, which cost a download per artifact for nothing.
        """
        if not store:
            return False

        probe = ScanCliLocal.__new__(ScanCliLocal)
        probe.where = rlsecure_path
        probe.store = store
        probe.purl = purl

        return probe.test_purl_exists()

    # PUBLIC
    @staticmethod
    def preflight(
        rlsecure_path: str,
        store: str | None,
    ) -> str | None:
        """Is rl-secure usable at all? Returns the reason it is not, or None.

        Run once before any repository work. Both of these were previously found
        out per artifact, after that artifact had already been downloaded, so a
        broken installation cost a download for every item in the repository
        before the first complaint.

        Two things are checked, in the order they can fail:

        1. `rl-secure --version` - the binary is present, runnable and licensed.
           rl-secure cannot be installed without a licence, so a version that
           comes back at all proves both.
        2. `rl-secure list --rl-store <store>` - the store exists and has been
           initialised with `rl-secure init`. Without a store nothing can be
           analysed.
        """
        probe = ScanCliLocal.__new__(ScanCliLocal)
        probe.where = rlsecure_path
        probe.store = store
        probe.purl = ""

        if probe._do_command_local(what="version", command=["--version"]) != 0:
            return f"rl-secure is not usable at '{rlsecure_path}': see the log for what it said"

        if not store:
            return "no rl-store: use --cli-rlstore-path"

        if probe._do_command_local(what="list", command=["list", "--no-color"]) != 0:
            return f"'{store}' is not an initialised rl-store: run 'rl-secure init' first"

        return None

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
            what="sync",
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

        # --return-status answers with the scan result: 0 pass, 1 fail. Both are
        # answers; make_scan_status_string() turns anything else into "error".
        return self._do_command_local(
            what="status",
            command=command,
            answer_codes=(0, 1),
        )

    def _exists_purl(
        self,
    ) -> int:
        """Does this purl have a scan in the store? The return code is the answer.

        A non-zero code means "not scanned yet", which is the ordinary case on a
        first run and not worth an error in the log.
        """
        command = [
            "status",
            "--no-color",
        ]

        return self._do_command_local(
            what="exists",
            command=command,
            answer_codes=None,
        )

    def _reports_purl(
        self,
        *,
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
        *,
        with_pack_safe: bool = False,
    ) -> tuple[int, str, str | None]:
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
        *,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> tuple[int, str, str | None]:

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
        *,
        with_pack_safe: bool = False,
    ) -> tuple[int, str, str | None]:

        scan_ok = self._sync_purl()
        if scan_ok != 0:
            return 101, "sync failed", None

        return self._common_xxx_and_report(
            with_pack_safe=with_pack_safe,
        )

    def test_purl_exists(self) -> bool:
        """
        Test if the purl actually exists in the given store

        return True if exists
        return False otherwise

        """
        r = self._exists_purl()
        return r == 0  # the purl exists
