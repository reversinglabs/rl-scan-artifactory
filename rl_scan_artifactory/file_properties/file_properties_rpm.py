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

logger = logging.getLogger(__name__)

"""
We are hunting for properties so that we can build a package url.

- name                # allways
- version             # allwyas
- arch (artictecture) # optional
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


class FilePropertiesRpm(
    FilePropertiesCommon,
):
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
        what = "rpm"
        self.props = self.artifactory_api.get_item_properties(file=self.file)

        front = f"{what}.metadata"
        if self.props.get(f"{front}.name", None) and self.props.get(f"{front}.version", None):
            self.file.properties = self.props
            return

        # rpm may not yet have all properties,
        # see: [#314540],
        #   rpm metadata from a remote only available after manual download via web gui, not after yum download
        # force populate properties by simulating visiting the rpm info tab on the web gui.

        logger.debug("before touch rpm info; properties are now: %s", str(self.props))
        logger.info(
            "missing properties in rpm repo; try propagate rpm-info for: %s::%s",
            self.file.repo.name,
            self.file.uri,
        )
        self.artifactory_api.touch_rpm_info_uri(file=self.file)
        self.props = self.artifactory_api.get_item_properties(file=self.file)
        logger.debug("after touch rpm info; properties are now: %s", str(self.props))
        self.file.properties = self.props

    def skip_non_candidate_file(
        self,
    ) -> bool:
        return self._common_filter_on_item_properties()
