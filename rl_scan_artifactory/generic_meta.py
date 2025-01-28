# python3 ts=4space

import configparser
import logging
from dataclasses import (
    dataclass,
)
from typing import (
    List,
    Dict,
)

logger = logging.getLogger(__name__)


@dataclass
class GenericMeta:
    name: str
    version: str
    path: str
    architecture: str | None = None
    namespace: str | None = None

    def __str__(
        self,
    ) -> str:
        return ", ".join(
            [
                str(self.namespace),
                self.name,
                str(self.architecture),
                self.version,
                self.path,
            ]
        )


class GenericMetaReader:
    key: str = "rl_meta"
    tail = "rl_meta"

    required: List[str] = [
        "name",
        "version",
        "path",
        "sha256",
    ]

    optional: List[str] = [
        "architecture",
        "namespace",
    ]

    def __init__(
        self,
        filepath: str,
    ) -> None:
        self.filepath = filepath
        self.data: GenericMeta | None = None

        ok = self._load_file()
        if ok is False:
            return

        ok = self._test_meta()
        if ok is False:
            return

        self._load_values()

    def _load_file(
        self,
    ) -> bool:
        if not self.filepath.lower().endswith(self.tail):
            logger.critical("the meta file must end with: '%s'; the file will be ignored", self.tail)
            return False

        self.config = configparser.ConfigParser()
        self.config.read(self.filepath)
        return True

    def _test_meta(
        self,
    ) -> bool:
        if self.key not in self.config:
            logger.critical(
                "the file '%s' has no required %s section: the file will be ignored", self.filepath, self.key
            )
            return False
        return True

    def _load_values(
        self,
    ) -> None:

        data: Dict[str, str] = {}
        for key in self.config[self.key]:
            if key in self.required or key in self.optional:
                logger.debug("%s -> %s", key, self.config[self.key][key])
                data[key] = self._clean_value(self.config[self.key][key])

        self.data = GenericMeta(**data)

    @staticmethod
    def _clean_value(
        value: str,
    ) -> str:
        """
        - take a value,
        - remove '/' and '@' and
        - possibly other conflicting html/utf8 chars
        """

        for k in ["/", "@"]:
            if k in value:
                value.replace(k, "_")

        for k in ["&", "?"]:  # rpm may have also + ~ ^
            if k in value:
                value.replace(k, "_")

        return value


"""
[rl_meta]
namespace =
name =
version =
architecture =
path =

#
# all keys are lower case string
# all values are string
#
# generic will need a helper file describing the metadata we need,
# so it can find the matching file and its:
#
# - <name>         [mandatory]
# - <version>      [mandatory]
# - <architecture> [optional]
# - <namespace>    [optional]
#
# namespace may be used to create a unique name (like e.g. npm )
# architecture must be used for binary packages (e.g. i386, amd64, arm_v8, ... ,
#   optionally 'none' may be used for binary neutral `source` code.
#
# to create the unique purl, where components are:
#
# - project:  <artifactory repository name>
# - package:  [ <arch>. ] [ <namespace>. ] <name>
# - version:  <version>
#
# none of the resulting strings above may contain @ or / or any html conflicting data,
# if they do contain restricted substrings these will be mapped away to safe values:
#   e.g. '_'
#
# the resulting purl used by the spectra_assure portal is:
#
# - purl:    <project>/<package>@<version>
##
# the file will be loaded from the <path> specified, we expect a single file currently
#
"""
