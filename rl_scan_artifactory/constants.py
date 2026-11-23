# python3
import tempfile
from typing import (
    Any,
)

# possibly change to yaml or json later

MY_ENV_NAMES: list[str] = [
    "ARTIFACTORY_HOST",
    "ARTIFACTORY_USER",
    "ARTIFACTORY_TOKEN",
    "RLPORTAL_HOST",
    "RLPORTAL_SERVER",
    "RLPORTAL_ORG",
    "RLPORTAL_GROUP",
    "RLPORTAL_ACCESS_TOKEN",
    "RLSECURE_SITE_KEY",
    "RLSECURE_ENCODED_LICENSE",
    "PROXY_SERVER",  # must be identical to the sdk
    "PROXY_PORT",
    "PROXY_USER",
    "PROXY_PASSWORD",
    "LOG_LEVEL",
]

# Any cli_args key whose name contains one of these holds a credential and must
# never reach a log file, a console or a ticket attachment. Matching is on the
# name, not on a list of known keys, so a new secret option is covered the day it
# is added rather than the day someone remembers to extend a list.
SECRET_ARG_NAME_PARTS: tuple[str, ...] = (
    "token",
    "password",
    "secret",
    "license",
    "site_key",
    "apikey",
    "api_key",
)
SECRET_REDACTED: str = "***"

# Settings without which a run cannot do its work. They are checked together
# after all options are gathered, so one run reports every missing one at once
# instead of one per attempt. The names are cli_args keys; where an upper case
# form appears in MY_ENV_NAMES the setting can also come from the environment.
# Below this artifactory version a report url needs a leading space to be viewable
REPORT_URL_SPACE_UNTIL: tuple[int, int, int] = (7, 104, 5)

# An artifactory repository name has no spaces, and no punctuation beyond - _ and
# a dot. A repository is often named after what it proxies, such as 'nmpjs.org',
# and artifactory is more permissive than that: 'jjj.....kkk' is a legal name.
# So this only excludes what artifactory itself excludes.
#
# Validating here turns a typo into one clear message instead of a REPO SKIP that
# looks like the repository is missing.
REPO_NAME_PATTERN: str = r"^[0-9a-zA-Z_.-]+$"

# The two names that are a path segment rather than a name. Everything else the
# pattern allows is harmless in a url path, because '/' is not in the pattern, so
# a dot run inside a name such as 'a..b' cannot climb anywhere.
REPO_NAMES_REFUSED: tuple[str, ...] = (".", "..")

MANDATORY_ARGS_ALWAYS: tuple[str, ...] = (
    "artifactory_host",
    "artifactory_user",
    "artifactory_token",
)
MANDATORY_ARGS_PORTAL: tuple[str, ...] = (
    "rlportal_org",
    "rlportal_group",
    "rlportal_access_token",
)
# The portal is reached by its host, by its instance (server) or by both: a server
# alone means my.secure.software/<server>, a host alone is a dedicated portal. Only
# a run with neither cannot work.
MANDATORY_ONE_OF_PORTAL: tuple[str, ...] = (
    "rlportal_host",
    "rlportal_server",
)
MANDATORY_ARGS_CLI: tuple[str, ...] = (
    "cli_rlstore_path",
    "cli_rlsecure_path",
)
MANDATORY_ARGS_CLI_DOCKER: tuple[str, ...] = (
    "rlsecure_encoded_license",
    "rlsecure_site_key",
)

# A run walks thousands of artifacts over minutes or hours, so a connection that
# drops once is expected rather than exceptional. These are for the transport:
# a request that reaches artifactory and is refused is answered, not retried.
HTTP_RETRY_TOTAL: int = 3
HTTP_RETRY_BACKOFF: float = 1.0  # 1s, 2s, 4s
HTTP_RETRY_STATUSES: tuple[int, ...] = (429, 500, 502, 503, 504)
# A download that comes back with one of these has been answered, so asking again
# only spends the wait. 403 is how artifactory refuses a blocked artifact when a
# policy plugin such as Spectra Assure Protect is in front of it, and that answer
# does not change within a run.
# What the rl-scanner docker image answers with. Unlike the local rl-secure,
# where a scan returns 0 and the verdict comes from a separate status call, the
# image returns the verdict itself: 0 pass, 1 fail. Only 101 is a real error.
DOCKER_SCAN_ANSWER_CODES: tuple[int, ...] = (0, 1)

DOWNLOAD_ANSWERED_STATUSES: tuple[int, ...] = (401, 403, 404, 405, 410)
DOWNLOAD_RETRY_WAIT_SECONDS: int = 10

HTTP_RETRY_METHODS: tuple[str, ...] = ("HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE")

DEFAULT_TEMPDIR = tempfile.gettempdir()

SPECTRA_ASSURE_HOST_BASE = "secure.software"
SPECTRA_ASSURE_HOST = f"my.{SPECTRA_ASSURE_HOST_BASE}"

META_STRING = ".rl_meta"
META_SECTION_KEY = "rl_meta"

ARTIFACTORY_KNOWN_PACKAGE_TYPES: dict[str, dict[str, Any]] = {
    # package_type name: extension name
    "rpm": {
        "endswith": ".rpm",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "debian": {
        "endswith": ".deb",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "docker": {
        "endswith": "manifest.json",
        "what": {
            ".name": "name",
            ".version": "version",
        },
    },
    "pypi": {
        "not_endswith": ".html",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "npm": {
        "endswith": ".tgz",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "gems": {
        "endswith": ".gem",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "nuget": {
        "endswith": ".nupkg",
        "what": {
            ".id": "name",  # nuget
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
        },
    },
    "maven": {
        "endswith": ".jar",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
            ".namespace": "namespace",  # maven
        },
    },
    # a gradle repository holds the same artifacts as maven, in the
    # maven-2-default layout Artifactory gives it by default (R4.1.7)
    "gradle": {
        "endswith": ".jar",
        "what": {
            ".name": "name",
            ".version": "version",
            ".arch": "arch",  # rpm
            ".release": "release",  # rpm
            ".namespace": "namespace",  # maven
        },
    },
    "generic": {
        # no "endswith": every file is listed, in either mode. In portal mode a
        # file is scanned through its .rl_meta side-car or its RL.meta.*
        # properties (R7.11), and only reading the file's properties can tell.
        "what": {
            # all values come from the `.rl_meta` file or the RL.meta.* properties
        },
    },
}

SPECTRA_ASSURE_PRE = "RL"

PROP_NAME_SPECTRA_ASSURE_PROGRESS = f"{SPECTRA_ASSURE_PRE}.progress"
PROP_NAME_SPECTRA_ASSURE_TIMESTAMP = f"{SPECTRA_ASSURE_PRE}.timestamp"
PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS = f"{SPECTRA_ASSURE_PRE}.scan-status"  # ['pass', 'fail']
PROP_NAME_SPECTRA_ASSURE_PURL = f"{SPECTRA_ASSURE_PRE}.package-url"
PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT = f"{SPECTRA_ASSURE_PRE}.scan-report"
PROP_NAME_SPECTRA_ASSURE_ORG = f"{SPECTRA_ASSURE_PRE}.organization"
PROP_NAME_SPECTRA_ASSURE_GROUP = f"{SPECTRA_ASSURE_PRE}.group"
PROP_NAME_SPECTRA_ASSURE_NOSCAN = f"{SPECTRA_ASSURE_PRE}.noscan"
# The sha256 of the bytes the other RL.* properties are about. A rebuilt artifact
# redeployed under the same path may keep the properties of the one it replaced;
# this is how a later run can tell (R10.8).
PROP_NAME_SPECTRA_ASSURE_SHA256 = f"{SPECTRA_ASSURE_PRE}.sha256"
# What counts as "yes" in RL.noscan. The integration writes "true"; a human or
# another tool setting it by hand may reasonably write any of these.
PROP_NOSCAN_TRUE_VALUES: tuple[str, ...] = ("true", "yes", "1", "on")

PROP_SPECTRA_ASSURE_ALL = [
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
    PROP_NAME_SPECTRA_ASSURE_PURL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT,
    PROP_NAME_SPECTRA_ASSURE_ORG,
    PROP_NAME_SPECTRA_ASSURE_GROUP,
    # after RL.progress: if writing stops in between, a new progress with an old
    # digest reads as other bytes and is done again, never the other way round
    PROP_NAME_SPECTRA_ASSURE_SHA256,
]

# The two values RL.progress can hold. They decide whether an artifact an earlier
# run already handled is processed again, so the value written and the values
# tested for have to be the same words: use these names, never a literal.
#
# PROGRESS_UPLOADED is transient - it says an upload happened but the scan had not
# finished when the run ended. Nothing depends on it historically: if losing it
# causes a rescan, that is an acceptable outcome.
PROGRESS_UPLOADED: str = "upload_to_portal_ok"
PROGRESS_SCANNED: str = "scanned"
PROGRESS_ALL: list[str] = [
    PROGRESS_UPLOADED,
    PROGRESS_SCANNED,
]

SCAN_STATUS_PASS: str = "pass"
SCAN_STATUS_FAIL: str = "fail"
SCAN_STATUS_ALL: list[str] = [
    SCAN_STATUS_PASS,
    SCAN_STATUS_FAIL,
]

# What a .rl_meta side-car carries. The side-car is how a generic artifact is
# found, never what is scanned, so the scan result belongs on the file its 'path'
# names. It keeps only enough to say it was handled and when: RL.progress is what
# a later run reads to know it need not do the work again.
PROP_SPECTRA_ASSURE_ON_SIDE_CAR: tuple[str, ...] = (
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_NAME_SPECTRA_ASSURE_SHA256,
)

# A generic artifact without a .rl_meta side-car may carry the same purl data as
# properties a person sets on it (R7.11). They are inputs: the integration reads
# them, never writes them, and the obsolete-property cleanup never removes them.
PROP_META_PRE: str = f"{SPECTRA_ASSURE_PRE}.meta"
PROP_META_FIELDS: tuple[str, ...] = ("name", "version", "namespace", "architecture")
PROP_META_MANDATORY: tuple[str, ...] = ("name", "version")

# The prefix the integration used before RL. Everything under it was written by
# this integration and nothing maintains it any more (R10.9).
PROP_LEGACY_PRE: str = "Spectra.Assure"

# The repo_db key under which the generic pre pass maps each side-car uri to the
# uri of the file it describes. Uris start with '/', so this cannot collide.
REPO_DB_DESCRIBED_BY_SIDE_CAR: str = "__described_by_side_car__"
# The side-cars the pre pass could not read; already recorded as failed (R12.1.1).
REPO_DB_FAILED_SIDE_CARS: str = "__failed_side_cars__"

PROP_SPECTRA_ASSURE_VALID_VALUES: dict[str, Any] = {
    PROP_NAME_SPECTRA_ASSURE_PROGRESS: PROGRESS_ALL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS: SCAN_STATUS_ALL,
}

_MINUTE: int = 60

# How many times in a row the portal may answer "no such version" before we stop
# waiting for a scan of it. A version uploaded moments ago can take a little while
# to become visible, so a few are tolerated; after that the answer is settled and
# polling for another hour only slows the run down.
PORTAL_STATUS_ABSENT_LIMIT: int = 3
PORTAL_STATUS_ABSENT: int = 404

SCAN_STATUS_WAIT_TIME: int = 20  # seconds, could be made proportional to the file size
SCAN_STATUS_WAIT_TIME_MAX: int = 120 * _MINUTE  # minutes, could be made proportional to the file size

# Exit codes.
# 0 and 2 are the usual "all good" and "bad command line" of any cli tool;
# everything above 100 is ours, so a wrapper can tell them apart from an argparse error.
EXIT_OK: int = 0
EXIT_FATAL: int = 101  # a precondition failed: we never got to do any real work
EXIT_INTERRUPTED: int = 102  # the run started but did not finish: ctrl-c or an unexpected error
EXIT_ITEM_FAILURES: int = 103  # the run finished, but one or more items could not be processed

# PROCESS_FILE_NONE: str = ""  # used in development (docker)
PROCESS_FILE_SKIP: str = "Skip"
PROCESS_FILE_FAILED: str = "Failed"
PROCESS_FILE_UPDATED: str = "Processed"
PROCESS_FILE_TIMEOUT: str = "Timeout"

PORTAL_UPLOAD_TIMEOUT: int = 3600 * 2
ARTIFACTORY_DOWNLOAD_TIMEOUT: int = 3600 * 2
VERIFY_BUF_SIZE: int = 65536

DEFAULT_DIGEST_TYPE: str = "sha256"

# if 1 all docker items under to the dirname path of the manifest.json get all the properties set.
DOCKER_RECURSIVE = 1

# properties this tool derives itself (from the uri) rather than reading from Artifactory
# are stored as <package type>.<DERIVED_PROPERTY_INFIX>.<name>
DERIVED_PROPERTY_INFIX: str = "_derived_"

JAR_TAIL: str = ".jar"
# a maven artifact path is <namespace...>/<name>/<version>/<file>
MAVEN_URI_MIN_SEGMENTS: int = 4
# The one gradle repository layout the maven parser reads right, and the one
# Artifactory gives a gradle repository by default. Any other layout
# (ivy-default puts a [type]s folder before the file) would be misread (R4.1.7).
GRADLE_LAYOUT: str = "maven-2-default"
# a docker manifest path is [<org>/]<name>/<version>/<manifest json>
DOCKER_URI_MIN_SEGMENTS: int = 3

# The generic (.rl_meta) path builds its purl differently from the name manglers:
# it escapes fewer characters and joins with '-' instead of '_'. Both are accidents
# rather than decisions, but changing either moves every generic purl to a new
# project on the portal, so they flip on a release boundary and not per customer.
#
# Keep both False until that release. When they are on by default and no supported
# version still produces the old purls, delete the flags and the old branches.
FUTURE_GENERIC_PURL_ESCAPE: bool = False  # escape as the name manglers do (quote_plus)
FUTURE_GENERIC_PURL_SEPARATOR: bool = False  # join with '_' as the name manglers do

# Artifactory 7.104.x and later can cap how many artifacts one recursive property
# update may touch (artifactory.max.artifacts.set.properties.recursive, off by default,
# the documented example value is 5000).
#
# Over the cap the call fails with 400 and a message of the form:
#   Cannot add property recursively to <repo>:<path> because it has more than <n> items.
#
# The api defines no dedicated status for this (204, 400, 401, 403 and 404 are the
# documented responses), so the status alone cannot identify it. The message can, and
# the pattern below also captures the limit for the log. It stays deliberately loose,
# because the wording is not part of the api contract and may be reworded.
# Only local repositories and the cache side of a remote one hold artifacts and
# accept custom properties. A virtual repository is a stack of a local over a remote:
# writes go to its local part and reads fall through, so it has no storage identity
# of its own to annotate. It is not supported.
WRITABLE_REPO_TYPES: list[str] = ["local", "remote"]

RECURSIVE_PROPS_RETRY_STATUS: int = 400
RECURSIVE_PROPS_LIMIT_PATTERN: str = r"recursively.*more than\s+(\d+)\s+item"

# a docker image is described by a manifest.json; a multi architecture image additionally
# has a list.manifest.json naming the per architecture manifests by digest
DOCKER_MANIFEST_FILE: str = "manifest.json"
DOCKER_LIST_MANIFEST_FILE: str = "list.manifest.json"

CLI_REPORTS_FILE = "reports.zip"
CLI_REPORTS_FILE_TAIL = f"-{CLI_REPORTS_FILE}"

# The rl-json report is how we read back the sha256 of what the store actually
# holds (report.info.file.hashes), so it is generated even when the user did not
# ask for it, and removed again before the bundle is built if they did not.
REPORT_FORMAT_RL_JSON: str = "rl-json"
REPORT_FILE_RL_JSON: str = "report.rl.json"
# the json path to the hashes of the scanned artifact itself; the components under
# report.metadata each have their own hashes and are not what we are asking about
REPORT_HASHES_PATH: tuple[str, ...] = ("report", "info", "file", "hashes")
REPORT_SCHEMA_TESTED: int = 3

CliReportFormatList: list[str] = [
    "cyclonedx",
    "sarif",
    "spdx",
    "rl-html",
    "rl-json",
    "rl-checks",
    "rl-cve",
    "rl-uri",
    "all",
]
# what about rl-safe pack
