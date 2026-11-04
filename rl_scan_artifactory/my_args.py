# python3 ts=4space
import argparse
import logging
import os
import pathlib
import re
import sys
from typing import (
    Any,
)

from .constants import (
    DEFAULT_TEMPDIR,
    MANDATORY_ARGS_ALWAYS,
    MANDATORY_ARGS_CLI,
    MANDATORY_ARGS_CLI_DOCKER,
    MANDATORY_ARGS_PORTAL,
    MANDATORY_ONE_OF_PORTAL,
    MY_ENV_NAMES,
    REPO_NAME_PATTERN,
    REPO_NAMES_REFUSED,
    CliReportFormatList,
)
from .exceptions import SpectraAssureInvalidAction
from .helpers import redact_secrets
from .version import VERSION

logger = logging.getLogger(__name__)


class MyArgs:  # pylint: disable=R0903; Too few public methods
    def __init__(
        self,
        *,
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
        xx = self.cli_args.get("version")
        if xx is not False:
            msg = f"version is not False: {xx}"
            raise RuntimeError(msg)

        if self.cli_args.get("cli_docker") is True:
            self.cli_args["cli"] = True
            if self.cli_args.get("sync"):
                msg = "cli-docker currently cannot support sync"
                raise ValueError(msg)

        if no_portal_or_cli is False:
            self._exor_portal_and_cli()
            self._validate_cli_or_docker()

        self._validate_mandatory_args(no_portal_or_cli=no_portal_or_cli)

        if self.cli_args.get("sync", False) is True:
            # if sync is requested any existing scan must be done again so ignore artifactory properties
            self.cli_args["ignore_artifactory_properties"] = True

        logger.debug("%s", self.cli_args.get("cli_report_types"))
        self.cli_args["reports_requested"] = self._cleanup_reports()
        logger.debug("%s", self.cli_args.get("reports_requested"))

        # never the raw dict: it holds the artifactory token, the portal token,
        # the rl-secure license and the proxy password
        logger.debug("%s", redact_secrets(self.cli_args))

    def _cleanup_reports(self) -> list[str]:
        k = "cli_report_types"

        report_list = self.cli_args.get(k)
        if not report_list:
            return []

        report_list = self.cli_args.get(k, "").split(",")
        if "all" in report_list:
            return ["all"]

        out_list: list[str] = []
        for report_name in report_list:
            if report_name in CliReportFormatList and report_name not in out_list:
                out_list.append(report_name)
        return out_list

    def mandatory_repo(
        self,
        args: dict[str, Any],
    ) -> list[str]:
        """The repositories to scan, from --repo given any number of times.

        Each occurrence may itself be a comma separated list, so
        `--repo a --repo b,c` and `--repo a,b,c` mean the same thing. Order is
        kept and duplicates are dropped.

        Surrounding space is removed, because `--repo "a, b"` is a natural thing
        to type and used to produce a repository called " b". Empty names, which
        `a,,b` and a trailing comma used to produce, are dropped for the same
        reason: both were passed on and failed later looking like a missing
        repository.
        """
        out_list: list[str] = []

        in_list: Any = args.get("repo") or []
        for entry in in_list:
            items = entry if isinstance(entry, list) else [entry]
            for item in items:
                for name in str(item).split(","):
                    name = name.strip()
                    if name and name not in out_list:
                        out_list.append(name)

        self._verify_repo_names(out_list)

        if self.repo_list_may_be_empty is False and len(out_list) == 0:
            msg = "The list of repository names cannot be empty: use the --repo/-r option"
            logger.error(msg)
            sys.exit(2)

        return out_list

    @staticmethod
    def _verify_repo_names(
        names: list[str],
    ) -> None:
        """Refuse a name artifactory cannot have, naming all of them at once."""
        invalid = [name for name in names if not re.match(REPO_NAME_PATTERN, name) or name in REPO_NAMES_REFUSED]
        if not invalid:
            return

        detail = ", ".join(f"'{name}'" for name in invalid)
        msg = f"not a repository name: {detail}; expected only letters, digits, '-', '_' and '.'"
        logger.error(msg)
        raise SpectraAssureInvalidAction(msg)

    def _mandatory_arg_names(
        self,
        *,
        no_portal_or_cli: bool,
    ) -> list[str]:
        """Which settings this particular invocation cannot do without."""
        needed: list[str] = list(MANDATORY_ARGS_ALWAYS)

        if no_portal_or_cli is True:
            # a tool that only reads artifactory: it chose neither backend
            return needed

        if self.cli_args.get("portal") is True:
            needed += list(MANDATORY_ARGS_PORTAL)

        # cli_docker implies cli, and needs a license instead of the local paths
        if self.cli_args.get("cli_docker") is True:
            needed += list(MANDATORY_ARGS_CLI_DOCKER)
        elif self.cli_args.get("cli") is True:
            needed += list(MANDATORY_ARGS_CLI)

        return needed

    def _missing_one_of(
        self,
        *,
        no_portal_or_cli: bool,
    ) -> list[tuple[str, ...]]:
        """The groups of settings of which this invocation has not one."""
        groups: list[tuple[str, ...]] = []
        if no_portal_or_cli is False and self.cli_args.get("portal") is True:
            groups.append(MANDATORY_ONE_OF_PORTAL)

        return [group for group in groups if not any(self.cli_args.get(name) for name in group)]

    @staticmethod
    def _how_to_supply(
        name: str,
    ) -> str:
        option = "--" + name.replace("_", "-")
        if name.upper() in MY_ENV_NAMES:
            return f"environment {name.upper()}, or {option}"
        return option

    def _validate_mandatory_args(
        self,
        *,
        no_portal_or_cli: bool,
    ) -> None:
        """Refuse a run that is missing a mandatory setting, naming all of them.

        This runs after every source of options has been read, so the message
        lists everything that is missing rather than stopping at the first one:
        finding out one setting at a time costs a round trip each.
        """
        missing = [
            name for name in self._mandatory_arg_names(no_portal_or_cli=no_portal_or_cli) if not self.cli_args.get(name)
        ]
        lines = [f"  {name}: {self._how_to_supply(name)}" for name in missing]

        # of these any one will do, so they are named together
        for group in self._missing_one_of(no_portal_or_cli=no_portal_or_cli):
            missing.append(" or ".join(group))
            how = " or ".join(self._how_to_supply(name) for name in group)
            lines.append(f"  one of {', '.join(group)}: {how}")

        if not missing:
            return

        detail = "\n".join(lines)
        msg = f"missing mandatory setting(s):\n{detail}"
        logger.error("missing mandatory setting(s): %s", ", ".join(missing))
        raise SpectraAssureInvalidAction(msg)

    def _exor_portal_and_cli(
        self,
    ) -> None:
        s = "Portal and cli cannot be both"

        if self.cli_args["portal"] is False and self.cli_args["cli"] is False:
            msg = f"{s} unset: choose one scanner backend"
            raise SpectraAssureInvalidAction(msg)

        if self.cli_args["portal"] is True and self.cli_args["cli"] is True:
            msg = f"{s} set: choose one only scanner backend"
            raise SpectraAssureInvalidAction(msg)

    def _validate_cli_or_docker(
        self,
    ) -> None:
        """What is merely advisable for a cli run.

        What is mandatory for one - the rl-secure paths, or the license and site
        key for cli-docker - is listed in MANDATORY_ARGS_CLI and
        MANDATORY_ARGS_CLI_DOCKER and checked by _validate_mandatory_args, so
        that a run missing several of them reports all of them at once.
        """
        if not (self.cli_args.get("cli") or self.cli_args.get("cli_docker")):
            return

        if self.cli_args.get("cli_reports_repo") is None:
            logger.warning("no reports_repo specified, remote repositories will not be processed")

    @staticmethod
    def _get_prog_name() -> str:
        prog = pathlib.Path(sys.argv[0]).name
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
            help=f"specify what reports you need, a comma separated list of {z}; default 'all'",
        )

        self.parser.add_argument(
            "--cli-docker",
            action="store_true",
            help="Use the docker cli (reversinglabs/rl-scanner) to scan the file.",
        )

        dd: list[str] = [
            "When a package url already exists on the portal, use sync and not scan.",
            "Will implicitly activate ignore-artifactory-properties (-I)",
        ]
        self.parser.add_argument(
            "-S",
            "--sync",
            action="store_true",
            help=", ".join(dd),
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

        dd = [
            "Wait on scan status in the portal max xx minutes",
            "if not finished continue without updating artifactory",
            "implicitly wait for all pending at the end",
        ]

        self.parser.add_argument(
            "-w",
            "--waittime",
            type=int,
            default=30,
            help=", ".join(dd),
        )

        self.parser.add_argument(
            "--ignore-cert-errors",
            action="store_true",
            help="Allow selfsigned https certs.",
        )

        self.parser.add_argument(
            "--keep-obsolete-properties",
            action="store_true",
            help=" ".join(
                [
                    "Leave properties this integration wrote earlier and no longer maintains:",
                    "the old Spectra.Assure.* ones, and the scan result on a generic .rl_meta side-car.",
                    "Without it they are removed from each item the run inspects.",
                    "Default: `false`",
                ],
            ),
        )

        self.parser.add_argument(
            "--ignore-skipped",
            action="store_true",
            help=" ".join(
                [
                    "Exit 0 when the run finished but some artifacts or repositories were skipped.",
                    "Without it such a run exits 103.",
                    "The skipped items are logged and summarised either way.",
                    "Default: `false`",
                ],
            ),
        )

        self.parser.add_argument(
            "--log-to-stderr",
            action="store_true",
            help=" ".join(
                [
                    "Also write the log to stderr.",
                    "The log file is always written regardless of this option.",
                    "Progress output goes to stdout, so the two can be redirected separately.",
                ],
            ),
        )

    def _do_env_args(
        self,
    ) -> None:
        for a_name in MY_ENV_NAMES:
            b_name = a_name.lower().replace("_", "-")
            logger.debug("%s %s", a_name, b_name)
            z = os.getenv(a_name, None)
            if not z:
                z = None
            self.parser.add_argument(
                f"--{b_name}",
                type=str,
                default=z,
            )

    def _finalize_args(
        self,
    ) -> dict[str, Any]:
        args = vars(self.parser.parse_args())
        if args.get("version", False) is True:
            logger.info("version: %s", VERSION)
            sys.exit(0)

        repo_list = self.mandatory_repo(args)
        args["repo"] = repo_list
        return args
