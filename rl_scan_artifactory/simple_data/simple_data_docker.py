# python3 ts=4space
import logging
from typing import (
    Any,
)

from rl_scan_artifactory.constants import DERIVED_PROPERTY_INFIX
from rl_scan_artifactory.fileinfo import FileInfo

from .simple_data_common import SimpleDataCommon

logger = logging.getLogger(__name__)

"""
SimpleData wants to find basic attributes for a file or package.
This is not always possible or easy.

e.g.

    Docker images are complicated and are described by layers and lists if multiple architectures exist.
    The architecture is not in the manifest.json. but in the build layer or in the list.manifest.json (if it exists).
    Image layer files may actually not even be downloadable if they are .marker (dedup),
      they may be located elsewhere as they are shared between images,
      or in worst case may not be downloadable at all if a image was deleted that has the real layer.
      (possibly via the storage layer it may be downloadable)

Some package format have a different name on the repo level then the file extension:

e.g.

    repo level: 'debian' file extension '.deb'
    repo level: 'gems' file extension '.gem'

We look for name, version, arch to make a unique item later on,
  we also collect additional info to make a file unique:

e.g.

    rpm: release
    maven: namespace

note:
    nuget uses id not name

"""


class SimpleDataDocker(SimpleDataCommon):
    def __init__(
        self,
        file: FileInfo,
    ) -> None:
        super().__init__(file=file)

    def _make_simple_data_docker(
        self,
    ) -> dict[str, Any]:
        """
        We can parse name and version from the file path.

        arch would only be in the list.manifest.json or in the sha256_<hash> file describing the build layer
        which we would have to find via the manifest.json (download and parse)
        name: docker.repoName
        version: docker.manifest # but not if the file is sha256_<sha>
        arch: None yet
        """
        logger.debug(
            "repo: %s, uri: %s, props: %s",
            self.file.repo.name,
            self.file.uri,
            self.file.properties,
        )

        k = "manifest.json"
        if not self.file.uri.lower().endswith(k):
            self.simple_data = {}
            return self.simple_data

        what = {
            ".repoName": "name",
            ".manifest": "version",
        }

        for k, v in self.file.properties.items():
            for tail, name in what.items():
                logger.debug("%s %s %s %s", k, v, tail, name)
                if not k.startswith(f"{self.p_type}."):
                    continue
                if k.endswith(tail):
                    self.simple_data[name] = v

        # a sha256 manifest is a digest, not a version: it cannot go in a purl
        k = "version"
        logger.debug("%s %s", k, self.simple_data.get(k))
        z = self.simple_data.get(k, [])
        if len(z) > 0 and z[0].startswith("sha256:"):
            logger.debug("manifest is a digest, not a version: %s", z[0])
            self.simple_data[k] = [""]

        # fall back to what we derived from the uri ourselves;
        # a local docker repo may have no docker.repoName/docker.manifest properties at all
        for name in ("name", "version"):
            self._fallback_to_derived_property(name)

        return self.simple_data

    def _fallback_to_derived_property(
        self,
        name: str,
    ) -> None:
        """Use <p_type>.<derived>.<name> when the Artifactory property is absent or unusable."""
        current = self.simple_data.get(name, [])
        if len(current) > 0 and current[0]:
            return

        key = f"{self.p_type}.{DERIVED_PROPERTY_INFIX}.{name}"
        derived = self.file.properties.get(key, [])
        if len(derived) > 0 and derived[0]:
            logger.debug("%s taken from the derived property %s: %s", name, key, derived)
            self.simple_data[name] = derived

    def make_simple_data(
        self,
    ) -> dict[str, Any]:
        logger.debug("repository type: %s, file: %s", self.p_type, self.uri)
        return self._make_simple_data_docker()
