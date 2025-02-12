# python3 ts=4space

from typing import (
    Dict,
    Any,
)
import logging

# from .simple_data import SimpleData
from .file_properties_common import FilePropertiesCommon
from ..artifactory_api import ArtifactoryApi
from ..fileinfo import FileInfo
from ..constants import (
    META_STRING,
)

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


class FilePropertiesGeneric(
    FilePropertiesCommon,
):
    what = "generic"
    k = META_STRING

    def __init__(
        self,
        cli_args: Dict[str, Any],
        file: FileInfo,
        artifactory_api: ArtifactoryApi,
    ) -> None:
        super().__init__(
            cli_args=cli_args,
            file=file,
            artifactory_api=artifactory_api,
        )

        self._get_properties()  # modifies self.file.properties

    def _get_properties(
        self,
    ) -> None:
        if self.cli_args.get("portal"):
            if not self.uri.lower().endswith(self.k):
                self.file.properties = self.props
                return

        logger.debug("investigate properties uri: %s", self.uri)
        self.props = self.artifactory_api.get_item_properties(
            file=self.file,
        )

        name = ""
        version = ""

        front = f"{self.what}._derived_"
        self.props[f"{front}.name"] = [f"{name}"]
        self.props[f"{front}.version"] = [f"{version}"]

        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    def skip_non_candidate_file(
        self,
    ) -> bool:
        """
        Decide if we process or skip:

        in portal mode
            we only look at rl_meta files and process via the meta file
            we skip therfore all non meta files

        in cli mode we process
        """
        if self.cli_args.get("portal"):
            if not self.uri.endswith(self.k):
                logger.debug("SKIP: %s not a '%s' file: %s", self.p_type, self.k, self.uri)
                self.file.simple = {}
                return True

        return self._common_filter_on_item_properties()  # returns False , we do not skip
