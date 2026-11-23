# python3 ts=4space

import logging
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..constants import (
    META_STRING,
    PROP_META_PRE,
)
from ..fileinfo import FileInfo

# from .simple_data import SimpleData
from .file_properties_common import FilePropertiesCommon

logger = logging.getLogger(__name__)

"""
We are hunting for properties so that we can build a package url.

- name                # always
- version             # always
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
        cli_args: dict[str, Any],
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
        # Every file is read, in either mode: a file without a side-car may carry
        # its purl data as RL.meta.* properties (R7.11), and only its properties
        # can say so.
        logger.debug("investigate properties uri: %s", self.uri)
        self.props = self.artifactory_api.get_item_properties(
            file=self.file,
        )

        # Nothing is derived from the uri here: a generic repository has no layout
        # to derive from. The name and version of a generic artifact come from its
        # .rl_meta side-car or its RL.meta.* properties (see
        # ArtifactoryFileProcessorGeneric), not through this class.
        #
        # Whatever generic.name / generic.version the repository itself carries is
        # therefore left alone; writing empty derived values here used to overwrite
        # them, which made the repository's own properties unusable.

        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    def _skip_non_candidate_file(
        self,
    ) -> bool:
        """
        Decide if we process or skip:

        in portal mode
            a .rl_meta side-car is a candidate, and stands for the file it describes;
            so is a file carrying RL.meta.* properties (R7.11);
            every other file is skipped

        in cli mode we process
        """
        if self.cli_args.get("portal") and not self.uri.endswith(self.k) and not has_meta_properties(self.props):
            logger.debug(
                "SKIP: %s not a '%s' file and no %s.* properties: %s",
                self.p_type,
                self.k,
                PROP_META_PRE,
                self.uri,
            )
            self.file.simple = {}
            return True

        # generic never skips on name/version: its purl comes from the rl_meta side-car
        # or the RL.meta.* properties, not from the item properties, so R4.2 does not
        # apply here
        self._populate_simple_data()
        return False


def has_meta_properties(
    properties: dict[str, Any],
) -> bool:
    """True when any RL.meta.* property is set, even an incomplete set (R7.11.3)."""
    return any(key.startswith(f"{PROP_META_PRE}.") for key in properties)
