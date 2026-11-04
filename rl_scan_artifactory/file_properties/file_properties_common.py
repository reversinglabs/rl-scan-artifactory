# python3 ts=4space
import logging
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..constants import (
    PROP_NAME_SPECTRA_ASSURE_NOSCAN,
    PROP_NOSCAN_TRUE_VALUES,
)
from ..exceptions import (
    SpectraAssureInvariantError,
)
from ..fileinfo import FileInfo
from ..simple_data import SimpleDataDefault, SimpleDataDocker, SimpleDataMaven

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


class FilePropertiesCommon:
    def __init__(
        self,
        cli_args: dict[str, Any],
        file: FileInfo,
        artifactory_api: ArtifactoryApi,
    ) -> None:
        self.cli_args = cli_args
        self.artifactory_api = artifactory_api
        self.file = file

        self.props: dict[str, Any] = {
            # the value items are actually lists as that is what artifactory gives us.
            # props should start with the repository_type string and end with .name, .version, ...
            # this allows us to be flexible (rpm: rpm.metadata.name, maven._derived_.name, ) if we have a middle item.
        }

        self.p_type: str = self.file.repo.package_type.lower()
        self.uri: str = self.file.uri.lower()

    def make_simple_data_interface(
        self,
    ) -> dict[str, Any]:
        dispatch = {
            "maven": SimpleDataMaven,
            "docker": SimpleDataDocker,
        }
        if self.p_type is None:
            msg = "expected self.p_type is not None"
            raise SpectraAssureInvariantError(msg)

        if self.p_type in dispatch:
            sd = dispatch[self.p_type](file=self.file)
        else:
            sd = SimpleDataDefault(file=self.file)

        return sd.make_simple_data()

    @staticmethod
    def _has_usable_value(
        simple_data: dict[str, Any],
        key: str,
    ) -> bool:
        """A purl component needs a non-empty value, not merely a present key.

        Artifactory property values are lists, and a cleared value (e.g. a docker
        manifest that turned out to be a digest) is [""], which is present but unusable.
        """
        value = simple_data.get(key)
        if value is None:
            return False
        if isinstance(value, list):
            return len(value) > 0 and bool(value[0])
        return bool(value)

    def _populate_simple_data(
        self,
    ) -> dict[str, Any]:
        """Run the SimpleData stage and store the result on the file."""
        simple_data = self.make_simple_data_interface()
        self.file.simple = simple_data
        logger.debug("%s", simple_data)
        return simple_data

    def _common_filter_on_item_properties(
        self,
    ) -> bool:
        simple_data = self._populate_simple_data()

        skip = False
        for key in ("name", "version"):
            if not self._has_usable_value(simple_data, key):
                skip = True

        if skip is True:
            logger.debug(
                "skip repo: %s (%s), file: %s: missing name and/or version properties; %s",
                self.file.repo.name,
                self.p_type,
                self.uri,
                simple_data,
            )

        logger.debug("skip: %s", skip)
        return skip

    def _get_common_properties(
        self,
    ) -> None:
        self.props = self.artifactory_api.get_item_properties(file=self.file)
        logger.debug("properties are now: %s", str(self.props))
        self.file.properties = self.props

    # PUBLIC
    def is_noscan(
        self,
    ) -> bool:
        """True when this item carries RL.noscan.

        The integration writes RL.noscan on the report files it uploads. A cli run
        puts the reports in the repository it just scanned when that one is local,
        so the next run would otherwise see them as ordinary artifacts. A remote
        repository cannot take an upload at all, not even on its cache side, so
        those reports go to a separate local repository; that one should not be
        scanned in the first place, and the property makes including it by mistake
        harmless rather than an error.
        """
        values = self.props.get(PROP_NAME_SPECTRA_ASSURE_NOSCAN)
        if not values:
            return False

        value = values[0] if isinstance(values, list) else values
        return str(value).strip().lower() in PROP_NOSCAN_TRUE_VALUES

    # PUBLIC
    def skip_non_candidate_file(
        self,
    ) -> bool:
        """Decide whether to skip this item. Every package type comes through here.

        RL.noscan is checked first and for every type, so a new package type
        cannot forget it. What counts as a candidate beyond that is per type and
        lives in _skip_non_candidate_file().
        """
        if self.is_noscan():
            logger.debug("SKIP: %s is marked %s", self.uri, PROP_NAME_SPECTRA_ASSURE_NOSCAN)
            self.file.simple = {}
            return True

        return self._skip_non_candidate_file()

    def _skip_non_candidate_file(
        self,
    ) -> bool:
        raise NotImplementedError
