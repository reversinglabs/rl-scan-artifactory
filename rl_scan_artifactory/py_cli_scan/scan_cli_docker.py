#! /usr/bin/env python3

import logging
import os
import pathlib

from rl_scan_artifactory.constants import (
    DOCKER_SCAN_ANSWER_CODES,
)

from .scan_cli_base import ScanCliBase

logger: logging.Logger = logging.getLogger(__name__)


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
        *,
        purl: str,
        encoded_license: str,
        site_key: str,
        store: str | None = None,
        temp_dir_path: str,  # owned and removed by the caller, must be empty
        reports_list: list[str] | None = None,
    ) -> None:
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
        except Exception:
            logger.exception("Only on unix platforms")
            # alternatively fail and say Unix only

    def _do_docker_rl_scan(
        self,
        *,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> int:
        realdir_packages = pathlib.Path(file_path).parent
        file_name = pathlib.Path(file_path).name

        # with a store (--cli-rlstore-path) it is mounted read-write, so the
        # history survives the container; there is no sync (R12.7.2)

        command1 = [
            "docker",
            "run",
            "--rm",
            f"--volume={realdir_packages}:/packages:ro",
            f"--volume={self.temp_dir_path}:/report",
            # no '=value' here: docker takes the value from our own environment,
            # so the license never becomes an argv element visible in ps
            "--env=RLSECURE_ENCODED_LICENSE",
            "--env=RLSECURE_SITE_KEY",
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
        # the image answers with the verdict, so a 'fail' is an answer here, not a
        # failure of the command
        return self._do_command(
            what="docker_rl_scan",
            command=command,
            secrets=self._license_environment(),
            answer_codes=DOCKER_SCAN_ANSWER_CODES,
        )

    def _license_environment(
        self,
    ) -> dict[str, str]:
        """The values the two --env flags above tell docker to pick up."""
        return {
            "RLSECURE_ENCODED_LICENSE": self.RLSECURE_ENCODED_LICENSE,
            "RLSECURE_SITE_KEY": self.RLSECURE_SITE_KEY,
        }

    def do_scan_and_report(
        self,
        *,
        file_path: str,
        with_pack_safe: bool = False,
    ) -> tuple[int, str, str | None]:
        f_real_path = os.path.realpath(file_path)

        if not pathlib.Path(f_real_path).exists():
            msg = f"path must exist: {f_real_path}"
            raise ValueError(msg)

        if not pathlib.Path(f_real_path).is_file():
            msg = f"path is not a file {f_real_path}"
            raise ValueError(msg)

        self.scan_status = self._do_docker_rl_scan(
            file_path=f_real_path,
            with_pack_safe=with_pack_safe,
        )

        if self.scan_status not in {0, 1}:
            return self.scan_status, "", None

        self.make_reports_bundle()
        result = self.make_scan_status_string()

        return self.scan_status, self.get_report_bundle_path(), result
