# python3 ts=4space

import logging
from typing import (
    Any,
)

from rl_scan_artifactory.artifactory_api import ArtifactoryApi
from rl_scan_artifactory.constants import (
    DERIVED_PROPERTY_INFIX,
    DOCKER_URI_MIN_SEGMENTS,
)
from rl_scan_artifactory.fileinfo import FileInfo

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


class FilePropertiesDocker(
    FilePropertiesCommon,
):
    what = "docker"
    k = "manifest.json"

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
        # we are looking for files ending in manifest.json (can be list.manifest.json also)
        if not self.uri.lower().endswith(self.k):
            self.file.properties = self.props
            return

        logger.debug("investigate properties uri: %s", self.uri)
        self.props = self.artifactory_api.get_item_properties(
            file=self.file,
        )

        # for remote docker repo's: len should be 5 /<org>/<name>/<version>/<manifest_json>
        # for local we may not have a org part
        # e.g upload python/alpine results in /python/alpine/manifest.json

        aa = self.uri.split("/")
        if aa and aa[0] == "":  # a leading '/' gives an empty first segment
            aa = aa[1:]

        logger.debug("%s", aa)

        # <name>/<version>/<manifest json> is the shortest layout that has
        # both a name and a version; an org part may precede it
        if len(aa) < DOCKER_URI_MIN_SEGMENTS or not all(aa):
            logger.warning(
                "SKIP: %s uri is not a docker layout [<org>/]<name>/<version>/%s: %s",
                self.p_type,
                self.k,
                self.uri,
            )
            self.file.properties = self.props
            return

        aa.pop()  # the manifest file name itself
        version = aa.pop()
        name = aa.pop()

        if len(aa) > 0:
            org = aa.pop()
            if len(org) > 0:
                name = f"{org}/{name}"

        front = f"{self.what}.{DERIVED_PROPERTY_INFIX}"
        self.props[f"{front}.name"] = [name]
        self.props[f"{front}.version"] = [version]

        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    def _skip_non_candidate_file(
        self,
    ) -> bool:
        if not self.uri.endswith(self.k):
            logger.debug("SKIP: %s not a '%s' file: %s", self.p_type, self.k, self.uri)
            self.file.simple = {}
            return True
        return self._common_filter_on_item_properties()
