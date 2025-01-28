# python3 ts=4space
import logging
from typing import (
    Dict,
    Any,
)

from .simple_data_common import SimpleDataCommon
from ..fileinfo import FileInfo

logger = logging.getLogger(__name__)

"""
SimpleData wants to find basic attributes for a file or package.
This is not always possible or easy.

e.g.

    Docker images are complicated and are described by layers and lists if multiple architectures exist.
    The architecture is not in the manifest.json. but in the build layer or in the list.manifest.json (if it exists).
    Image layer files may actually not even be downloadable if they are .marker (dedup),
      they may be located elsewhere as they are shared between images,
      or in worst case may not be downloadable at all if a image was deleted that has the ream layer.
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
    ) -> Dict[str, Any]:
        """we can parse name and version from the file path.
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

        k = "version"
        logger.debug("%s %s", k, self.simple_data.get(k))
        z = self.simple_data.get(k, [])
        if len(z) > 0:
            # if the manifest.json is a sha255 uri path
            #   the version may be
            #       in the manifest itself
            #       or in the build layer,
            #   we don't yet know a version here,
            #   so erase
            if z[0].startswith("sha256:"):
                self.simple_data[k] = ""

        return self.simple_data

    def make_simple_data(
        self,
    ) -> Dict[str, Any]:
        logger.debug("repository type: %s, file: %s", self.p_type, self.uri)
        return self._make_simple_data_docker()
