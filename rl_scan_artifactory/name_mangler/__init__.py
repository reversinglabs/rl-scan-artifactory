from .name_mangler_debian import NameManglerDebian as NameManglerDebian
from .name_mangler_default import NameManglerDefault as NameManglerDefault
from .name_mangler_docker import NameManglerDocker as NameManglerDocker
from .name_mangler_gems import NameManglerGems as NameManglerGems
from .name_mangler_generic import NameManglerGeneric as NameManglerGeneric
from .name_mangler_maven import NameManglerMaven as NameManglerMaven
from .name_mangler_npm import NameManglerNpm as NameManglerNpm
from .name_mangler_pypi import NameManglerPypi as NameManglerPypi
from .name_mangler_rpm import NameManglerRpm as NameManglerRpm

__all__ = [
    "NameManglerDebian",
    "NameManglerDefault",
    "NameManglerDocker",
    "NameManglerGems",
    "NameManglerGeneric",
    "NameManglerMaven",
    "NameManglerNpm",
    "NameManglerPypi",
    "NameManglerRpm",
]
