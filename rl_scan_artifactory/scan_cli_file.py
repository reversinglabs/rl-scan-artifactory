import logging
import pathlib
import shutil
import tempfile
from typing import (
    Any,
)

from .py_cli_scan import (
    ScanCliBase,
    ScanCliDocker,
    ScanCliLocal,
)

logger = logging.getLogger()


class ScanCli:
    def __init__(
        self,
        cli_args: dict[str, Any],
    ) -> None:
        self.cli_args = cli_args

        self.scanner: ScanCliBase | None = None
        self.temp_dir_name: str | None = None

        self.rlsecure_dir = self.cli_args.get("cli_rlsecure_path")
        if self.rlsecure_dir:  # is None for docker
            msg = f"the path '{self.rlsecure_dir}' must be the directory where we can find rl-secure and rl-safe"
            if not pathlib.Path(self.rlsecure_dir).is_dir():
                raise RuntimeError(msg)

    def _cli_docker_scan(
        self,
        *,
        file_path: str,
        purl: str,
        encoded_license: str,
        site_key: str,
        store: str | None = None,
        sync_requested: bool = False,
    ) -> tuple[int, str, str | None]:
        logger.debug("%s %s", file_path, purl)

        if not encoded_license:
            msg = "encoded_license is None"
            raise RuntimeError(msg)
        if not site_key:
            msg = "site_key_license is None"
            raise RuntimeError(msg)

        self.temp_dir_name = tempfile.mkdtemp()

        # The rl-scanner image has no sync command and no way to ask the store
        # about a purl, so docker always scans; with --cli-rlstore-path the
        # store keeps the history (R12.7.2).
        self.scanner = ScanCliDocker(
            purl=purl,
            encoded_license=encoded_license,
            site_key=site_key,
            store=store,
            temp_dir_path=self.temp_dir_name,
            reports_list=self.cli_args.get("reports_requested", []),
        )

        if sync_requested:
            # refused at startup (R12.7.2) and never automatic (R12.7.2.1)
            logger.debug("docker cannot sync %s; scanning it", purl)

        ret, report_bundle_path, result = self.scanner.do_scan_and_report(
            file_path=file_path,
            with_pack_safe=self.cli_args.get("pack_safe", False),
        )

        logger.debug("%s %s %s", ret, report_bundle_path, result)

        return ret, report_bundle_path, result

    def _cli_local_scan_or_sync(
        self,
        *,
        file_path: str,
        purl: str,
        rlsecure: str,
        store: str | None = None,
        sync_requested: bool = False,
    ) -> tuple[int, str, str | None]:
        logger.debug(
            "file_path: %s purl: %s rlsecure: %s store: %s",
            file_path,
            purl,
            rlsecure,
            store,
        )

        if not rlsecure:
            msg = "rlsecure is None"
            raise RuntimeError(msg)

        self.temp_dir_name = tempfile.mkdtemp()
        self.scanner = ScanCliLocal(
            purl=purl,
            where=rlsecure,
            store=store,
            temp_dir_path=self.temp_dir_name,
            reports_list=self.cli_args.get("reports_requested", []),
        )

        if sync_requested and not store:
            msg = "store is None"
            raise RuntimeError(msg)

        if sync_requested is True and self.scanner.test_purl_exists():
            ret, report_bundle_path, result = self.scanner.do_sync_and_report(
                with_pack_safe=self.cli_args.get("pack_safe", False),
            )
        else:
            ret, report_bundle_path, result = self.scanner.do_scan_and_report(
                file_path=file_path,
                with_pack_safe=self.cli_args.get("pack_safe", False),
            )

        logger.debug("%s %s %s", ret, report_bundle_path, result)

        return ret, report_bundle_path, result

    # Public

    def scan_file(
        self,
        *,
        file_path: str,
        purl: str,
        sync_requested: bool = False,
    ) -> Any:
        store = self.cli_args.get("cli_rlstore_path")

        logger.debug("%s", self.cli_args.get("cli_report_types"))

        if self.cli_args.get("cli_docker") is True:
            return self._cli_docker_scan(
                file_path=file_path,
                purl=purl,
                encoded_license=self.cli_args.get("rlsecure_encoded_license", ""),
                site_key=self.cli_args.get("rlsecure_site_key", ""),
                store=store,
                sync_requested=sync_requested,
            )

        if not self.rlsecure_dir:
            msg = "self.rlsecure_dir is None"
            raise RuntimeError(msg)

        return self._cli_local_scan_or_sync(
            file_path=file_path,
            purl=purl,
            rlsecure=self.rlsecure_dir,
            store=store,
            sync_requested=sync_requested,
        )

    # Public
    def get_rl_json_report_path(
        self,
    ) -> str:
        """Where the rl-json report of the last scan or sync is."""
        if not self.scanner:
            msg = "self.scanner is None"
            raise RuntimeError(msg)

        return self.scanner.get_rl_json_report_path()

    def cleanup(
        self,
    ) -> None:
        """Remove the scan directory, if one was made. Safe to call more than once.

        Called from a `finally`, so it must not assume the scan got far: the
        directory is made before the scanner, and the scanner can fail to start.
        """
        if self.temp_dir_name is None:
            return

        temp_dir_name, self.temp_dir_name = self.temp_dir_name, None
        try:
            shutil.rmtree(temp_dir_name)
        except OSError as e:
            # never raise from here: it would replace whatever the scan raised
            logger.warning("cannot remove scan directory %s: %s", temp_dir_name, e)
