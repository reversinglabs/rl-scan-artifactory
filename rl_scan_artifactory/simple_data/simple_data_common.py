# python3 ts=4space
import logging
from typing import (
    Dict,
    Any,
)

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

We look for name, version , arch to make a unique item later on,
  we also collect additional info to make a file unique:

e.g.

    rpm: release
    maven: namespace

note:
    nuget uses id not name

"""


class SimpleDataCommon:
    change_package_type_to_property = {
        "debian": "deb",
        "gems": "gem",
    }

    what = {
        ".id": "name",  # nuget
        ".name": "name",
        ".version": "version",
        ".arch": "arch",  # rpm
        ".release": "release",  # rpm
        ".namespace": "namespace",  # maven
    }

    def __init__(
        self,
        file: FileInfo,
    ) -> None:
        self.simple_data: Dict[str, Any] = {}

        self.file = file
        self.uri: str = file.uri

        self.p_type: str = self._transform_p_type(
            self.file.repo.package_type.lower(),
        )

    def _transform_p_type(
        self,
        p_type: str,
    ) -> str:
        """some repository items have a different name for the property first part
        change the package_type to the proper first part used in properties
        """

        if p_type in self.change_package_type_to_property:
            return self.change_package_type_to_property[p_type]

        return p_type

    def _make_simple_data_from_props_artifactory_basic(
        self,
    ) -> Dict[str, Any]:
        """we are looking for properties that start with p_type and end with <what>
        basically we are looking for name and version but take some other ones along the way
        """

        logger.debug(
            "repo: %s, uri: %s, props: %s",
            self.file.repo.name,
            self.file.uri,
            self.file.properties,
        )

        for k, v in self.file.properties.items():
            for tail, name in self.what.items():
                if not k.startswith(f"{self.p_type}."):
                    continue
                if k.endswith(tail):
                    self.simple_data[name] = v

        logger.debug("%s", self.simple_data)
        return self.simple_data

    def make_simple_data(
        self,
    ) -> Dict[str, Any]:
        logger.debug("repository type: %s, file: %s", self.p_type, self.uri)
        return self._make_simple_data_from_props_artifactory_basic()
