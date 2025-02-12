#! /usr/bin/env python3

from typing import (
    Tuple,
    List,
)

import os
import logging

from .scan_cli_base import ScanCliBase

logger: logging.Logger = logging.getLogger(__name__)

# temp_dir


class ScanCliDocker(
    ScanCliBase,
):
    docker_image_name: str = "reversinglabs/rl-scanner:latest"

    RLSECURE_ENCODED_LICENSE: str
    RLSECURE_SITE_KEY: str
    user_id: int = -1
    group_id: int = -1
    scan_status: int | None = None

    def __init__(
        self,
        purl: str,
        encoded_license: str,
        site_key: str,
        store: str | None = None,
        temp_dir_path: str | None = None,  # you handle temp_dir yourself, must be empy
        reports_list: List[str] | None = None,
    ) -> None:
        # later: add rl-store external to docker

        super().__init__(
            purl=purl,
            temp_dir_path=temp_dir_path,
            store=store,
            reports_list=reports_list,
        )

        self.RLSECURE_ENCODED_LICENSE: str = encoded_license
        self.RLSECURE_SITE_KEY: str = site_key

        try:
            self.user_id: int = -1
            self.user_id = os.getuid()
            self.group_id: int = -1
            self.group_id = os.getgid()
        except Exception as e:
            logger.exception("Only on unix platforms %s", e)
            # alternativly fail and say Unix only

    def set_docker_image_name(
        self,
        docker_image_name: str,
    ) -> None:
        self.docker_image_name: str = docker_image_name

    def _do_docker_rl_scan(
        self,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> int:
        realdir_packages = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)

        # no --rm as we will most likely use the docker image multiple times
        # currently no external rl-store so no sync possible
        # when rl-store is needed we have to pass a additional volume that we can read and write to

        command1 = [
            "docker",
            "run",
            "--rm",
            f"--volume={realdir_packages}:/packages:ro",
            f"--volume={self.temp_dir_path}:/report",
            f"--env=RLSECURE_ENCODED_LICENSE={self.RLSECURE_ENCODED_LICENSE}",
            f"--env=RLSECURE_SITE_KEY={self.RLSECURE_SITE_KEY}",
        ]

        if self.store is not None:
            s = f"--volume={self.store}:/rl-store"
            command1.append(s)

        reports = ",".join(self.reports_list)
        command2 = [
            f"{self.docker_image_name}",
            "rl-scan",
            f"--purl={self.purl}",
            f"--package-path=/packages/{file_name}",
            f"--report-format={reports}",
            "--report-path=/report",
            "--replace",
        ]

        if with_pack_safe is True:
            command2.append("--pack-safe")  # requires rl-scanner > v3.3.1; 2025-01-16

        if self.store is not None:
            command2.append("--rl-store=/rl-store")

        if self.user_id > -1:
            command1.append(
                f"--user={self.user_id}:{self.group_id}",
            )

        command = command1 + command2
        return self._do_command(
            what="docker_rl_scan",
            command=command,
        )

    def _do_docker_rl_sync(
        self,
        with_pack_safe: bool = False,
    ) -> int:
        # option force to force a download # TODO
        command1 = [
            "docker",
            "run",
            "--rm",
            "--pull allways",
            f"--volume={self.temp_dir_path}:/report",
            f"--env=RLSECURE_ENCODED_LICENSE={self.RLSECURE_ENCODED_LICENSE}",
            f"--env=RLSECURE_SITE_KEY={self.RLSECURE_SITE_KEY}",
        ]

        if self.store is not None:
            s = f"--volume={self.store}:/rl-store"
            command1.append(s)

        if self.user_id > -1:
            command1.append(
                f"--user={self.user_id}:{self.group_id}",
            )

        reports = ",".join(self.reports_list)
        command2 = [
            f"{self.docker_image_name}",
            "rl-sync",
            f"--purl={self.purl}",
            f"--report-format={reports}",
            "--report-path=/report",
        ]

        if with_pack_safe is True:
            command2.append("--pack-safe")  # requires rl-scanner > v3.3.1; 2025-01-16

        if self.store is not None:
            command2.append("--rl-store=/rl-store")

        command = command1 + command2

        return self._do_command(
            what="docker_rl_scan",
            command=command,
        )

    def do_scan_and_report(
        self,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> Tuple[int, str, str | None]:
        f_real_path = os.path.realpath(file_path)
        assert os.path.exists(f_real_path), f"path must exist: {f_real_path}"
        assert os.path.isfile(f_real_path), f"path is not a file {f_real_path}"

        self.scan_status = self._do_docker_rl_scan(
            file_path=f_real_path,
            with_pack_safe=with_pack_safe,
        )
        if self.scan_status not in [0, 1]:
            return self.scan_status, "", None

        self.make_reports_bundle()
        result = self.make_scan_status_string()

        return self.scan_status, self.get_report_bundle_path(), result

    def do_sync_and_report(
        self,
        with_pack_safe: bool = False,
    ) -> Tuple[int, str, str | None]:
        assert False, "sync currently not implemented"

        self.scan_status = self._do_docker_rl_sync(
            with_pack_safe=with_pack_safe,
        )
        if self.scan_status not in [0, 1]:
            return self.scan_status, "", None

        self.make_reports_bundle()
        result = self.make_scan_status_string()

        return self.scan_status, self.get_report_bundle_path(), result

    def test_purl_exists(self) -> bool:
        return False  # currently we cannot test for existing purls so always return False
