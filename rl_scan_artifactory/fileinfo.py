# python3 ts=4space
import logging

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
)

from .artifactory_repo_info import ArtifactoryRepoInfo

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    uri: str
    sha1: str
    sha2: str
    repo: ArtifactoryRepoInfo
    last_modified: str  # note this has a time zone

    properties: dict[str, Any] = field(default_factory=dict)
    simple: dict[str, Any] = field(default_factory=dict)
    file_name: str = ""

    def __str__(
        self,
    ) -> str:
        return ", ".join(
            [
                self.repo.name,
                self.uri,
                self.sha1,
                self.sha2,
                self.last_modified,
                str(self.properties),
                str(self.simple),
                self.file_name,
            ]
        )
