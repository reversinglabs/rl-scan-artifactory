# python3 ts=4space
import json
import logging
import pathlib
from typing import (
    Any,
)

from .exceptions import (
    SpectraAssureInvalidAction,
    SpectraAssureInvariantError,
)

logger = logging.getLogger(__name__)

"""
read, parse and extract relevant info from:

 - the manifest.json (single item) or
 - the list.manifest.json (multiple items of different architecture)

 - a config describes a single item composed of layers.
 - a item can have annotations, we may later get the version from there.

"""


class DockerManifestExtract:
    known_mediatypes: list[str] = [  # top level mediatypes
        r"application\/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.index.v1+json",
        r"application\/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        r"application\/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        r"application\/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]

    def __init__(
        self,
        file_path: str,
    ) -> None:
        self.mt = None
        self.data: dict[str, Any] = {}
        self.output: dict[str, str] = {}
        self.manifest_type: str | None = None
        self.file_path = file_path

        self.config: dict[str, Any] = {}  # manifest.json; node
        self.layers: list[dict[str, Any]] = []  # manifest.json; node
        self.manifests: list[dict[str, Any]] = []  # list.manifest.json; tree/list
        self.annotations: dict[str, Any] = {}

        self.validate_file_name()
        self.read_file_json()
        self.check_schema()
        self.check_mediatype()
        self.get_annotations()

    def get_annotations(
        self,
    ) -> None:
        # org.opencontainers.image.version
        k = "annotations"
        if k in self.data:
            self.annotations = self.data.get(k, {})
        logger.debug("%s", self.annotations)

    def validate_file_name(
        self,
    ) -> None:
        valid = {
            # longer ones first, substrings at the end
            "list.manifest.json": "tree",
            "manifest.json": "node",
        }
        for tail, what in valid.items():
            if self.file_path.lower().endswith(tail):
                self.manifest_type = what
                return

        raise SpectraAssureInvalidAction(f"unknown manifest file, expecting one of {valid.keys()}")

    def read_file_json(
        self,
    ) -> None:
        """Read the manifest, or fail saying so.

        Swallowing the read error here made the next step report a missing
        'schemaVersion', which points at the content of a file we never read.
        """
        try:
            with pathlib.Path(self.file_path).open("r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError) as e:  # ValueError covers json.JSONDecodeError
            msg = f"cannot read '{self.file_path}' as json: {type(e).__name__}: {e}"
            logger.error(msg)
            raise SpectraAssureInvalidAction(msg) from e

        if not isinstance(self.data, dict):
            msg = f"'{self.file_path}' is not a json object but a {type(self.data).__name__}"
            logger.error(msg)
            raise SpectraAssureInvalidAction(msg)

        logger.debug("json data: %s", self.data)

    def check_schema(
        self,
    ) -> None:
        k = "schemaVersion"
        sv = self.data.get(k, None)
        if sv is None:
            raise SpectraAssureInvalidAction(f"missing '{k}' json: {self.file_path}")
        if sv != 2:
            msg = "expected sv == 2"
            raise SpectraAssureInvariantError(msg)

    def check_mediatype(
        self,
    ) -> None:
        k = "mediaType"
        self.mt = self.data.get(k, None)
        if self.mt is None:
            raise SpectraAssureInvalidAction(f"missing '{k}' json: {self.file_path} {self.data}")

        logger.debug("%s: %s", self.mt, self.known_mediatypes)
        if self.mt not in self.known_mediatypes:
            msg = "expected self.mt in self.known_mediatypes"
            raise SpectraAssureInvariantError(msg)

    def _get_node_config(
        self,
        rr: dict[str, Any],
    ) -> None:
        logger.debug("before: %s", rr)

        self.config = self.data.get("config", {})
        digest = self.config.get("digest")
        if digest and digest.startswith("sha256:"):
            rr["__".join(digest.split(":"))] = self.config  # prep the filename sha256__<sha2>
            # this file has the architecture

        logger.debug("after: %s", rr)

    def _get_node_layers(
        self,
        rr: dict[str, Any],
    ) -> None:
        logger.debug("before: %s", rr)

        self.layers = self.data.get("layers", [])
        for layer in self.layers:
            logger.debug("%s", layer)
            digest = layer.get("digest")
            if digest and digest.startswith("sha256:"):
                rr["__".join(digest.split(":"))] = layer  # prep the filename sha256__<sha2>

        logger.debug("after: %s", rr)

    def _get_node_items(
        self,
    ) -> dict[str, Any]:
        rr: dict[str, Any] = {}
        logger.debug("before: %s", rr)

        self._get_node_config(rr)
        self._get_node_layers(rr)

        logger.debug("after: %s", rr)
        return rr

    def get_items(
        self,
    ) -> dict[str, Any]:
        if self.manifest_type == "tree":
            return {}  # known dead code for now we do  not scan tree's

        if self.manifest_type == "node":
            return self._get_node_items()

        raise SpectraAssureInvalidAction(f"unknown manifest_type: not supported: {self.manifest_type}")

    def set_output(
        self,
        output: dict[str, str],
    ) -> None:
        self.output = output

    def get_config_digest(
        self,
    ) -> str | None:
        if self.manifest_type != "node":
            return None

        if len(self.config) == 0:
            return None

        return self.config.get("digest")
