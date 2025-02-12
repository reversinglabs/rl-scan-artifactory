# python3 ts=4space
import logging
from typing import (
    Any,
    Dict,
    Tuple,
)

from .artifactory_api import ArtifactoryApi
from .spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)


class ArtifactoryToPortalBase:
    def __init__(
        self,
        *,
        cli_args: Dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
    ) -> None:
        self.cli_args = cli_args
        self.spectra_assure_api = spectra_assure_api
        self.artifactory_api = artifactory_api

        self.verbose = self.cli_args.get("verbose", False)
        self.download_dir = self.cli_args.get("download", "/tmp")

        self.not_finished: Dict[str, Any] = {}

    @staticmethod
    def _purl_split(
        purl: str,
    ) -> Tuple[str, str, str]:
        if "@" not in purl:
            raise Exception("package url is missing '@'")
        if "/" not in purl:
            raise Exception("package url is missing '/'")

        aa = purl.split("@")
        bb = aa[0].split("/")

        return bb[0], bb[1], aa[1]

    @staticmethod
    def _get_path_in_dict_simple(
        path: str,
        data: Dict[str, Any],
    ) -> Any:
        ppath = path.split(".")
        logger.debug("%s", ppath)
        d = data
        for p in ppath:
            d = d.get(p, None)
            logger.debug("%s", d)
            if d is None:
                break
        return d
