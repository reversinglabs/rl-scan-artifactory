# python3 ts=4space

import logging
from typing import (
    Any,
)

from rl_scan_artifactory.artifactory_api import ArtifactoryApi
from rl_scan_artifactory.constants import (
    DERIVED_PROPERTY_INFIX,
    JAR_TAIL,
    MAVEN_URI_MIN_SEGMENTS,
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


class FilePropertiesMaven(
    FilePropertiesCommon,
):
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
        what = self.p_type  # maven or gradle: the same maven-2-default layout (R4.1.7)
        self._get_common_properties()

        # we have no properties: parse the uri to get name and version and namespace
        uri = self.file.uri
        if not uri.lower().endswith(JAR_TAIL):
            self.file.properties = self.props
            return

        # /org/apache/logging/log4j/log4j-api/2.12.1/log4j-api-2.12.1.jar
        # note that namespace + name is unique and name is not required to be the end of namespace
        # groupId = org.apache.logging.log4j
        # name = log4j-api
        # version = 2.12.1

        aa = uri.split("/")
        if aa and aa[0] == "":  # a leading '/' gives an empty first segment
            aa = aa[1:]

        logger.debug("%s", aa)

        # <namespace...>/<name>/<version>/<file>: four segments is the shortest
        # layout that has all of them, and every part must be non empty
        if len(aa) < MAVEN_URI_MIN_SEGMENTS or not all(aa):
            logger.warning(
                "SKIP: %s uri is not a maven layout <namespace>/<name>/<version>/<file>: %s",
                what,
                uri,
            )
            self.file.properties = self.props
            return

        # file_name = aa[-1]
        version = aa[-2]
        name = aa[-3]
        namespace = ".".join(aa[:-3])

        front = f"{what}.{DERIVED_PROPERTY_INFIX}"
        self.props[f"{front}.name"] = [namespace + "." + name]
        self.props[f"{front}.name_only"] = [name]
        self.props[f"{front}.version"] = [version]
        self.props[f"{front}.namespace"] = [namespace]

        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    def _skip_non_candidate_file(
        self,
    ) -> bool:
        k = JAR_TAIL
        if not self.uri.lower().endswith(k):
            logger.debug("SKIP: %s not a '%s' file: %s", self.p_type, k, self.uri)
            self.file.simple = {}
            return True
        return self._common_filter_on_item_properties()
