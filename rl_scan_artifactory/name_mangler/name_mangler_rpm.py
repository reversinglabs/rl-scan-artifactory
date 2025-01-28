# python3 ts=4space

import logging

from .name_mangler_common import NameManglerCommon
from ..fileinfo import FileInfo

logger = logging.getLogger(__name__)

"""
docker.manifest: not consistent, somtimes a sha256 sometimes the version
docker.repoName: reversinglabs/rl-scanner

Artifactory repo items have a name and version property (often but not allways).
But may not have other info to make a unique purl. (e.g. for docker the arch is in the json

Particularly:
the same version may exists for different architectures
and different build environments (pypi)

We have the file path (the uri) on artifactory
We may have a name and version property (not for docker so far: mboot:sept 2024)

Find a way to make a unique purl by moving arch and build info to the project.
This way we can do valid diffs on the Spectra Assure Portals,
between versions of the same architecture and build-environments.
"""


class NameManglerRpm(
    NameManglerCommon,
):
    def __init__(
        self,
        file: FileInfo,
    ) -> None:
        super().__init__(file=file)

    def _mangle(
        self,
        file_name: str,
    ) -> str:
        remainder = file_name

        # a rpm file is roughly: name version release arch .rpm; parts may be empty except name
        # according to artifactory may be different the name from the file
        version = self.version  # the artifactory version usually is missing the release part
        name = self._remove_connector_front_and_back(remainder.split(version)[0])
        release = self.file.properties.get("rpm.metadata.release", [])[0]
        arch = self.file.properties.get("rpm.metadata.arch", [])[0]

        # glibc-gconv-extra-2.34-100.el9_4.3.i686.rpm -> 100.el9_4.3
        os_release, release2 = self._split_release(release=release)

        logger.debug("in: %s", remainder)

        remainder = self._strip_tail(remainder, ".rpm")
        remainder = self._remove_substring(remainder, arch, "tail")
        remainder = self._remove_substring(remainder, name, "front")
        remainder = self._remove_substring(remainder, version, "front")
        remainder = self._remove_substring(remainder, release, "front")

        self.version = "-".join([version, release2])

        logger.debug(
            "remainder: %s, arch: %s, os_release: %s, release: %s, release2: %s version: %s, uri: %s",
            remainder,
            arch,
            os_release,
            release,
            release2,
            version,
            self.file.uri,
        )

        remainder = self._remove_connector_front_and_back(remainder)
        remainder = remainder + "_" + self._combine_args(os_release, arch)
        remainder = self._remove_connector_front_and_back(remainder)

        logger.debug("out: %s", remainder)
        return remainder
