from typing import (
    Tuple,
    Dict,
    Any,
    Optional,
)
import logging
import tempfile
import shutil
import os

from .py_cli_scan import (
    ScanCliBase,
    ScanCliDocker,
    ScanCliLocal,
)

logger = logging.getLogger()


class ScanCli:

    def __init__(
        self,
        cli_args: Dict[str, Any],
    ) -> None:
        self.cli_args = cli_args

        self.scanner: ScanCliBase | None = None
        self.temp_dir_name: str | None = None

        self.rlsecure_dir = self.cli_args.get("cli_rlsecure_path")
        if self.rlsecure_dir:  # is None for docker
            msg = f"the path '{self.rlsecure_dir}' must be the directory where we can find rl-secure and rl-safe"
            assert os.path.isdir(self.rlsecure_dir), msg

    def _cli_docker_scan_or_sync(
        self,
        file_path: str,
        purl: str,
        encoded_license: str,
        site_key: str,
        store: Optional[str] = None,
        sync_requested: bool = False,
    ) -> Tuple[int, str, str | None]:
        logger.debug("%s %s", file_path, purl)

        assert encoded_license is not None
        assert site_key is not None

        self.temp_dir_name = tempfile.mkdtemp()

        # currently no external rl-store so no sync possible
        self.scanner = ScanCliDocker(
            purl=purl,
            encoded_license=encoded_license,
            site_key=site_key,
            store=store,
            temp_dir_path=self.temp_dir_name,
            reports_list=self.cli_args.get("reports_requested", []),
        )

        if sync_requested:
            assert store is not None

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

    def _cli_local_scan_or_sync(
        self,
        file_path: str,
        purl: str,
        rlsecure: str,
        store: Optional[str] = None,
        sync_requested: bool = False,
    ) -> Tuple[int, str, str | None]:
        logger.debug("file_path: %s purl: %s rlsecure: %s store: %s", file_path, purl, rlsecure, store)

        assert rlsecure is not None

        self.temp_dir_name = tempfile.mkdtemp()
        self.scanner = ScanCliLocal(
            purl=purl,
            where=rlsecure,
            store=store,
            temp_dir_path=self.temp_dir_name,
            reports_list=self.cli_args.get("reports_requested", []),
        )

        if sync_requested:
            assert store is not None

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
        file_path: str,
        purl: str,
        sync_requested: bool = False,
    ) -> Any:
        store = self.cli_args.get("cli_rlstore_path")

        logger.debug("%s", self.cli_args.get("cli_report_types"))

        if self.cli_args.get("cli_docker") is True:
            return self._cli_docker_scan_or_sync(
                file_path=file_path,
                purl=purl,
                encoded_license=self.cli_args.get("rlsecure_encoded_license", ""),
                site_key=self.cli_args.get("rlsecure_site_key", ""),
                store=store,
                sync_requested=sync_requested,
            )

        assert self.rlsecure_dir is not None
        return self._cli_local_scan_or_sync(
            file_path=file_path,
            purl=purl,
            rlsecure=self.rlsecure_dir,
            store=store,
            sync_requested=sync_requested,
        )

    def cleanup(
        self,
    ) -> None:
        assert self.scanner is not None
        assert self.temp_dir_name is not None
        self.scanner.cleanup_temp_dir()
        shutil.rmtree(self.temp_dir_name)
