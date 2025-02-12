# python3 ts=4space
import logging
from typing import (
    Dict,
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..fileinfo import FileInfo
from ..simple_data import SimpleDataDefault
from ..simple_data import SimpleDataDocker
from ..simple_data import SimpleDataMaven

logger = logging.getLogger(__name__)

"""
We are hunting for properties so that we can build a package url.

- name                # allways
- version             # allways
- arch (architecture) # optional
- namespace           # optional

Often Artifactory can provide these properties directly,
as it parses known package_types and build a properties tab.

Sometimes this data is simply not available.
e.g for 'generic' 'docker' 'maven'.

Rpm is a special case as the data may only become available after we vizit the rpm info tab in the gui.

As we progress and add more package_types the way we extract the data may change as well.

From the properties data we populate the unique purl PROJECT/PACKAGE@VERSION

PROJECT is the <repository name> normally
PACKAGE is the <name> or <namespace>-<name>
VERSION normally is the <version> part

the <arch> part may be already in the <name> for some repository types,
for others (rpm, docker) it may move either to the PACKAGE or the PROJECT part currently.

Normally (the generic type) we hunt for items that already have the .name and .version property set by artifactory.
If this is not the case we have to derive these properties from other sources (docker).
For maven we can simply extract all info from the artifactory uri path.
For docker we may not have a actual version (latest),
and after inspecting all the manifest and build files,
we use 'latest.YYYYMMDD'.
"""


class FilePropertiesCommon:
    def __init__(
        self,
        cli_args: Dict[str, Any],
        file: FileInfo,
        artifactory_api: ArtifactoryApi,
    ) -> None:
        self.cli_args = cli_args
        self.artifactory_api = artifactory_api
        self.file = file

        self.props: Dict[str, Any] = {
            # the value items are actually lists as that is what artifactory gives us.
            # props should start with the repository_type string and end with .name, .version, ...
            # this allows us to be flexible (rpm: rpm.metadata.name, maven._derived_.name, ) if we have a middle item.
        }

        self.p_type: str = self.file.repo.package_type.lower()
        self.uri: str = self.file.uri.lower()

    def make_simple_data_interface(
        self,
    ) -> Dict[str, Any]:
        dispatch = {
            "maven": SimpleDataMaven,
            "docker": SimpleDataDocker,
        }
        assert self.p_type is not None

        if self.p_type in dispatch:
            sd = dispatch[self.p_type](file=self.file)
        else:
            sd = SimpleDataDefault(file=self.file)

        return sd.make_simple_data()

    def _common_filter_on_item_properties(
        self,
    ) -> bool:
        simple_data = self.make_simple_data_interface()

        skip = False
        if simple_data.get("version", None) is None:
            skip = True

        if simple_data.get("name", None) is None:
            skip = True

        if skip is True:
            logger.debug(
                "skip repo: %s (%s), file: %s: missing name and/or version properties; %s",
                self.file.repo.name,
                self.p_type,
                self.uri,
                simple_data,
            )

        self.file.simple = simple_data
        logger.debug("%s", simple_data)
        logger.debug("skip: %s", skip)
        return skip

    def _get_common_properties(
        self,
    ) -> None:
        self.props = self.artifactory_api.get_item_properties(file=self.file)
        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    def skip_non_candidate_file(
        self,
    ) -> bool:
        raise NotImplementedError
