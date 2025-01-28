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


class SimpleDataDefault(SimpleDataCommon):
    def __init__(
        self,
        file: FileInfo,
    ) -> None:
        super().__init__(file=file)

    def make_simple_data(
        self,
    ) -> Dict[str, Any]:
        logger.debug("repository type: %s, file: %s", self.p_type, self.uri)
        return self._make_simple_data_from_props_artifactory_basic()
