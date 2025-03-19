# python3 ts=4space
import argparse
import logging
import os
import sys
from typing import (
    Dict,
    List,
    Any,
)

from .constants import (
    MY_ENV_NAMES,
    DEFAULT_TEMPDIR,
    CliReportFormatList,
)
from .exceptions import SpectraAssureInvalidAction
from .version import VERSION

logger = logging.getLogger(__name__)


class MyArgs:  # pylint: disable=R0903; Too few public methods
    def __init__(
        self,
        repo_list_may_be_empty: bool = False,
        no_portal_or_cli: bool = False,
    ) -> None:
        self.repo_list_may_be_empty = repo_list_may_be_empty
        self.prog = self._get_prog_name()
        self.parser = argparse.ArgumentParser(
            prog=self.prog,
            description="Scan artifacts with Spectra Assure (Portal) or rl-secure (Cli)",
            epilog="",
        )
        self._setup_cli_args()
        self._do_env_args()

        self.cli_args = self._finalize_args()
        assert self.cli_args.get("version") is False

        if self.cli_args.get("cli_docker") is True:
            self.cli_args["cli"] = True
            if self.cli_args.get("sync"):
                raise Exception("cli-docker currently cannot support sync")

        if no_portal_or_cli is False:
            self._exor_portal_and_cli()
            self._validate_cli_or_docker()

        if self.cli_args.get("sync", False) is True:
            # if sync is requested any existing scan must be done again so ignore artifactory properties
            self.cli_args["ignore_artifactory_properties"] = True

        logger.debug("%s", self.cli_args.get("cli_report_types"))
        self.cli_args["reports_requested"] = self._cleanup_reports()
        logger.debug("%s", self.cli_args.get("reports_requested"))

        logger.debug("%s", self.cli_args)

    def _cleanup_reports(self) -> List[str]:
        k = "cli_report_types"

        report_list = self.cli_args.get(k)
        if not report_list:
            return []

        report_list = self.cli_args.get(k, "").split(",")
        if "all" in report_list:
            return ["all"]

        out_list: List[str] = []
        for report_name in report_list:
            if report_name in CliReportFormatList:
                if report_name not in out_list:
                    out_list.append(report_name)
        return out_list

    def mandatory_repo(  # noqa: C901
        self,
        args: Dict[str, Any],
    ) -> List[str]:
        out_list: List[str] = []
        in_list: List[str] = args.get("repo", [])
        if in_list is None:
            in_list = []

        def one_list(a_list: List[str]) -> None:
            for item in a_list:
                if "," in item:
                    for j in item.split(","):
                        if j not in out_list:
                            out_list.append(j)
                else:
                    if item not in out_list:
                        out_list.append(item)

        for k in in_list:
            if isinstance(k, list):
                one_list(k)
            else:
                one_list([k])

        if self.repo_list_may_be_empty is False:
            if len(out_list) == 0:
                msg = "The list of repository names cannot be empty: use the --repo/-r option"
                logger.error(msg)
                print(msg, file=sys.stderr)
                sys.exit(2)

        return out_list

    def _exor_portal_and_cli(
        self,
    ) -> None:
        s = "Portal and cli cannot be both"
        if self.cli_args["portal"] is False and self.cli_args["cli"] is False:
            raise SpectraAssureInvalidAction(f"{s} unset: choose one scanner backend")

        if self.cli_args["portal"] is True and self.cli_args["cli"] is True:
            raise SpectraAssureInvalidAction(f"{s} set: choose one only scanner backend")

    def _validate_cli_or_docker(
        self,
    ) -> None:
        logger.debug("%s")

        docker = self.cli_args.get("cli_docker")
        cli = self.cli_args.get("cli")
        if not (cli or docker):
            return

        if docker:
            s = "when using option '--docker-cli' you must specify the"
            t = "also either in the environment or as a command line option"

            if self.cli_args.get("rlsecure_encoded_license") is None:
                raise SpectraAssureInvalidAction(f"{s} rlsecure-encoded-license {t} ")

            if self.cli_args.get("rlsecure_site_key") is None:
                raise SpectraAssureInvalidAction(f"{s} rlsecure-site-key {t} ")
            return

        s = "when using option '--cli' you must specify the"

        if self.cli_args.get("cli_rlstore_path") is None:
            raise SpectraAssureInvalidAction(f"{s} rl-store path also with '--cli-rlstore-path'")

        if self.cli_args.get("cli_rlsecure_path") is None:
            raise SpectraAssureInvalidAction(f"{s} rl-secure path also with '--cli-rlsecure-path'")

        if self.cli_args.get("cli_reports_repo") is None:
            logger.warning("no reports_repo specified, remote repositories will not be processed")

    @staticmethod
    def _get_prog_name() -> str:
        prog = os.path.basename(sys.argv[0])
        if prog.lower().endswith(".py"):
            prog = prog[:-3]
        return prog

    def _setup_cli_args(
        self,
    ) -> None:
        self.parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Show processing results on stdout.",
        )

        self.parser.add_argument(
            "-V",
            "--version",
            action="store_true",
            help="Show the current version of the program library and exit.",
        )

        self.parser.add_argument(
            "-P",
            "--portal",
            action="store_true",
            help="Use the portal to scan the file.",
        )

        self.parser.add_argument(
            "-C",
            "--cli",
            action="store_true",
            help="Use the cli to scan the file.",
        )

        self.parser.add_argument(
            "--cli-rlstore-path",
            help="when using cli and not docker we need the location of the rl-store",
            # LATER: docker can also have a external rl-store
        )

        self.parser.add_argument(
            "--cli-rlsecure-path",
            help="when using cli and not docker we need the directory where we can find rl-secure and rl-safe",
        )

        self.parser.add_argument(
            "--cli-reports-repo",
            help="upload reports for remote repositories to a local repo",
        )

        z = list(filter(lambda x: x != "all", CliReportFormatList))
        self.parser.add_argument(
            "--cli-report-types",
            type=str,
            default="all",
            help=f"specify what reports you need, a comma seperated list of {z}; default 'all'",
        )

        self.parser.add_argument(
            "--cli-docker",
            action="store_true",
            help="Use the docker cli (reversinglabs/rl-scanner) to scan the file.",
        )

        self.parser.add_argument(
            "-S",
            "--sync",
            action="store_true",
            help=", ".join(
                [
                    "When a package url already exists on the portal, use sync and not scan.",
                    "Will implicitly acivate ignore-artifactory-properties (-I)",
                ],
            ),
        )

        self.parser.add_argument(
            "-I",
            "--ignore-artifactory-properties",
            action="store_true",
            help="When the 'Spectra.Asure' properties are already present in Artifactory, ignore them and re-scan.",
        )

        self.parser.add_argument(
            "--pack-safe",
            action="store_true",
            help="Create a reports.rl-safe archive and add it to the reports.",
        )

        self.parser.add_argument(
            "-r",
            "--repo",
            nargs="+",
            action="append",
            help="Add these repo(s) to the list of repositories to process for candidate files.",
            # allow for comma separated items 2025-01-16
        )

        self.parser.add_argument(
            "-d",
            "--download",
            type=str,
            default=DEFAULT_TEMPDIR,
            help=f"Use the specified download directory (must exist already) instead of the default {DEFAULT_TEMPDIR}.",
        )

        self.parser.add_argument(
            "-w",
            "--waittime",
            type=int,
            default=30,
            help=", ".join(
                [
                    "Wait on scan status in the portal max xx minutes",
                    "if not finished continue without updating artifactory",
                    "implicitly wait for all pending at the end",
                ],
            ),
        )

        self.parser.add_argument(
            "--ignore-cert-errors",
            action="store_true",
            help="Allow selfsigned https certs.",
        )

    def _do_env_args(
        self,
    ) -> None:
        for a_name in MY_ENV_NAMES:
            b_name = a_name.lower().replace("_", "-")
            logger.debug("%s %s", a_name, b_name)
            z = os.getenv(a_name, None)
            if z == "":
                z = None
            self.parser.add_argument(
                f"--{b_name}",
                type=str,
                default=z,
            )

    def _finalize_args(
        self,
    ) -> Dict[str, Any]:
        args = vars(self.parser.parse_args())
        if args.get("version", False) is True:
            print(f"version: {VERSION}")
            sys.exit(0)

        repo_list = self.mandatory_repo(args)
        args["repo"] = repo_list
        return args
