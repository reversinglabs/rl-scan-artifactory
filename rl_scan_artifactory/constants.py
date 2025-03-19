# python3
from typing import (
    Dict,
    List,
    Any,
)

import tempfile

# possibly change to yaml or json later

MY_ENV_NAMES: List[str] = [
    "ARTIFACTORY_HOST",
    "ARTIFACTORY_USER",
    "ARTIFACTORY_TOKEN",
    #
    "RLPORTAL_HOST",
    "RLPORTAL_SERVER",
    "RLPORTAL_ORG",
    "RLPORTAL_GROUP",
    "RLPORTAL_ACCESS_TOKEN",
    #
    "RLSECURE_SITE_KEY",
    "RLSECURE_ENCODED_LICENSE",
    #
    "PROXY_SERVER",  # must be identical to the sdk
    "PROXY_PORT",
    "PROXY_USER",
    "PROXY_PASSWORD",
    #
    "LOG_LEVEL",
]

DEFAULT_TEMPDIR = tempfile.gettempdir()

SPECTRA_ASSURE_HOST_BASE = "secure.software"
SPECTRA_ASSURE_HOST = f"my.{SPECTRA_ASSURE_HOST_BASE}"
SPECTRA_ASSURE_HOST_URL = f"https://{SPECTRA_ASSURE_HOST}/"
SECURE_SOFTWARE_URL = f"https://{SPECTRA_ASSURE_HOST_BASE}/"

META_STRING = ".rl_meta"
META_SECTION_KEY = "rl_meta"

ARTIFACTORY_KNOWN_PACKAGE_TYPES: Dict[str, Dict[str, Any]] = {
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
    "generic": {
        "endswith": META_STRING,
        "what": {
            # all values come from the `.rl_meta` file
        },
    },
}

# map artifactory package type to secure software package type
SECURE_SOFTWARE_COMMUNITY_PACKAGE_TYPES: Dict[str, str] = {
    "npm": "npm",
    "gems": "gems",
    "nuget": "nuget",
    "pypi": "pypi",
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

PROP_SPECTRA_ASSURE_ALL = [
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_NAME_SPECTRA_ASSURE_TIMESTAMP,
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS,
    PROP_NAME_SPECTRA_ASSURE_PURL,
    PROP_NAME_SPECTRA_ASSURE_SCAN_REPORT,
    PROP_NAME_SPECTRA_ASSURE_ORG,
    PROP_NAME_SPECTRA_ASSURE_GROUP,
]

PROP_SPECTRA_ASSURE_VALID_VALUES: Dict[str, Any] = {
    PROP_NAME_SPECTRA_ASSURE_PROGRESS: [
        "upload_to_portal_ok",
        "scanned",
    ],
    PROP_NAME_SPECTRA_ASSURE_SCAN_STATUS: [
        "pass",
        "fail",
    ],
}

_MINUTE: int = 60

SCAN_STATUS_WAIT_TIME: int = 20  # seconds, could be made proportional to the file size
SCAN_STATUS_WAIT_TIME_MAX: int = 120 * _MINUTE  # minutes, could be made proportinal to the file size

# PROCESS_FILE_NONE: str = ""  # used in development (docker)
PROCESS_FILE_SKIP: str = "Skip"
PROCESS_FILE_UPDATED: str = "Processed"
PROCESS_FILE_TIMEOUT: str = "Timeout"

PORTAL_UPLOAD_TIMEOUT: int = 3600 * 2
ARTIFACTORY_DOWNLOAD_TIMEOUT: int = 3600 * 2
VERIFY_BUF_SIZE: int = 65536

DEFAULT_DIGEST_TYPE: str = "sha256"

# if 1 all docker items under to the dirname path of the manifest.json get all the properties set.
DOCKER_RECURSIVE = 1

CLI_REPORTS_FILE = "reports.zip"
CLI_REPORTS_FILE_TAIL = f"-{CLI_REPORTS_FILE}"

CliReportFormatList: List[str] = [
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
