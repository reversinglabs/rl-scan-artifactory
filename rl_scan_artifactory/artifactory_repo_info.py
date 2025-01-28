# python3 ts=4space
import logging
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    List,
)

logger = logging.getLogger(__name__)


@dataclass
class ArtifactoryRepoInfo:
    name: str
    repo_type: str
    package_type: str
    layout: str
    environments: List[str] = field(default_factory=list)

    def __str__(
        self,
    ) -> str:
        return ", ".join(
            [
                f"name: {self.name}",
                f"type: {self.repo_type}",
                f"package_type: {self.package_type}",
                f"layout: {self.layout}",
                f"environments: {self.environments}",
            ]
        )
