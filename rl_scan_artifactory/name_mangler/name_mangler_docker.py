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


class NameManglerDocker(
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
        return self._mangle_default(file_name=file_name)
