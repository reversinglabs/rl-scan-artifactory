# python3 ts=4space
import logging
import os
import re
import urllib.parse

from typing import (
    Tuple,
)

from ..fileinfo import FileInfo

logger = logging.getLogger(__name__)

"""
docker.manifest: not consistent, somtimes a sha256 sometimes the version
docker.repoName: reversinglabs/rl-scanner

Artifactory repo items have a name and version property (often but not allways).
But may not have other info to make a unique purl. (e.g. for docker the arch is in the json

Particularly:
the same version may exists for different architectures
and different build environments (pypi)

We have the file path (the uri) on artifactory
We may have a name and version property (not for docker so far: mboot:sept 2024)

Find a way to make a unique purl by moving arch and build info to the project.
This way we can do valid diffs on the Spectra Assure Portals,
between versions of the same architecture and build-environments.
"""


class NameManglerCommon:

    def __init__(
        self,
        file: FileInfo,
    ) -> None:
        self.remainder: str = ""
        self.file = file
        # start with some basic info
        self.project = self.file.repo.name
        self.package = self.file.simple.get("name", [])[0]
        self.version = self.file.simple.get("version", [])[0]
        self.p_type = self.file.repo.package_type.lower()

    @staticmethod
    def _escape_string_for_spectra_assure_purl_component(
        string: str,
    ) -> str:
        s = string
        # s = string.replace(":", "0x3a") # .. does not work on cli , translate to 0x3a
        s = urllib.parse.quote_plus(s)  # will also deal with : but ' ' becomes '+'
        s = s.replace("%", "0x")
        return s

    @staticmethod
    def _remove_connector_front_and_back(
        what: str,
    ) -> str:
        """Remove connector characters like -, _, . from the front and back of a string
        In:
         - what: str
        Out:
           str with connector char's removed (0-n)
        """
        if len(what) == 0:
            return what

        logger.debug("what: %s", what)

        match = re.search(r"^[-\._]+", what)
        if match:
            what = what[len(match[0]) :]

        match = re.search(r"[-\._]+$", what)
        if match:
            what = what[: (-1 * len(match[0]))]

        logger.debug("what: %s", what)
        return what

    def _remove_substring_front(
        self,
        str1: str,
        str2: str,
    ) -> str:
        if str1.lower().startswith(str2.lower()):
            str1 = str1[len(str2) :]
        return self._remove_connector_front_and_back(str1)

    def _remove_substring_tail(
        self,
        str1: str,
        str2: str,
    ) -> str:
        if str1.lower().endswith(str2.lower()):
            str1 = str1[: (-1 * len(str2))]
        return self._remove_connector_front_and_back(str1)

    def _remove_substring_mid(
        self,
        str1: str,
        str2: str,
    ) -> str:
        # for now we ignore multiple times str2, and we start from the beginning
        if str2.lower() in str1.lower():
            start = str1.lower().index(str2.lower())
            if start > 0:
                str1 = str1[:start] + str1[start + len(str2)]
        return self._remove_connector_front_and_back(str1)

    def _remove_substring(
        self,
        str1: str,
        str2: str,
        what: str = "all",
    ) -> str:
        valid = [
            "all",
            "front",
            "tail",
            "mid",
        ]
        assert what in valid

        logger.debug("str1: |%s|, str2: |%s|, what: %s", str1, str2, what)

        if len(str1) == 0 or len(str2) == 0:
            return self._remove_connector_front_and_back(str1)

        if str1.lower() == str2.lower():
            return ""

        if what in ["all", "front"]:
            str1 = self._remove_substring_front(str1=str1, str2=str2)
            if what == "front":
                return self._remove_connector_front_and_back(str1)

        if what in ["all", "tail"]:
            str1 = self._remove_substring_tail(str1=str1, str2=str2)
            if what == "tail":
                return self._remove_connector_front_and_back(str1)

        if what in ["all", "mid"]:
            str1 = self._remove_substring_mid(str1=str1, str2=str2)
            if what == "mid":
                return self._remove_connector_front_and_back(str1)

        return self._remove_connector_front_and_back(str1)

    @staticmethod
    def _strip_tail(
        str1: str,
        str2: str,
    ) -> str:
        if str1.lower().endswith(str2):
            return str1[: (-1 * len(str2))]
        return str1

    def _split_release(
        self,
        release: str,
        separator: str = ".",
    ) -> Tuple[str, str]:
        """trailing data after the os build part:

        e.g.
         - glibc-gconv-extra-2.34-100.el9_4.3.i686.rpm
         - openssl-libs-3.0.7-27.el9.0.2.x86_64

        a string release can have more than one dot,
          in the above examples: '100.el9_4.3' or '27.el9.0.2'

        the release string '27.el9.0.2' and '100.el9_4.3' can be split like this:
         - all before the first dot is the base release
         - all until the next dot is the build os so el9 and el9_4
         - all after the second dot should be added to the base release,

        see CHANGELOGNAME in the rpm for additional info

         - glibc-gconv-extra-2.34-100.el9_4.3.i686.rpm:
            CHANGELOGNAME:Patsy Griffin <patsy@redhat.com> - 2.34-100.3
         - openssl-libs-3.0.7-27.el9.0.2.x86_64:
            CHANGELOGNAME:Release Engineering <releng@rockylinux.org> - 3.0.7-27.0.2

        although one is el9_4 and the other is el9, both packages are build on
            DISTRIBUTION:Rocky Linux 9.4

        """
        # release is purely a number
        if re.match(r"^\d+$", release):
            return "", str(int(release))

        os_release = ""
        if separator in release:
            os_release = release.split(separator)[1]
            if os_release[0].isdigit():  # so far the platform always starts with a letter
                os_release = ""

        # just the platform string and anything after it (fc40, el9, ...) ;; may not be there
        os_release = self._remove_connector_front_and_back(os_release)

        release2 = ""
        if len(os_release) > 0:
            pp = release.split(separator)
            del pp[1]
            release2 = separator.join(pp)

        release2 = self._remove_connector_front_and_back(release2)
        return os_release, release2

    def _combine_args(
        self,
        *arg_list: str,
        combiner: str = "_",
    ) -> str:
        zz = []
        for item in arg_list:
            if len(item):
                zz.append(item)

        return self._remove_connector_front_and_back(
            combiner.join(
                zz,
            ),
        )

    def _mangle_default(
        self,
        file_name: str,
    ) -> str:
        name = self.package
        version = self.version
        remainder = file_name

        logger.debug("in: %s", remainder)

        aa = remainder.split(version)
        if len(aa) == 2 and len(aa[0]) > 0 and len(aa[1]) > 0:
            logger.debug("aa[0]: %s", aa[0])
            logger.debug("aa[1]: %s", aa[1])
            aa[0] = self._remove_connector_front_and_back(aa[0])
            aa[1] = self._remove_connector_front_and_back(aa[1])
            # we may need to strip connector signs from aa[0] and aa[1]
            # we have a successful split on version
            if aa[0].lower() in name.lower():
                return aa[1]

            logger.debug("inspection needed: name: %s ;; %s", name, aa[0])

        remainder = remainder.replace(self.package, "", 1)  # remove the item name
        remainder = self._remove_connector_front_and_back(remainder)

        if "-" in self.package:
            z = self.package.replace("-", "_")
            remainder = remainder.replace(z, "", 1)
            remainder = self._remove_connector_front_and_back(remainder)

        remainder = remainder.replace(self.version, "", 1)  # remove the version
        remainder = self._remove_connector_front_and_back(remainder)

        logger.debug("out: %s", remainder)
        return remainder

    def _mangle(
        self,
        file_name: str,
    ) -> str:
        return self._mangle_default(file_name=file_name)

    # PUBLIC
    def make_long(
        self,
    ) -> Tuple[str, str, str]:
        file_name = os.path.basename(self.file.uri)

        self.remainder = self._mangle(
            file_name=file_name,
        )  # may change the version string

        if len(self.remainder) > 0:
            project = self._escape_string_for_spectra_assure_purl_component(self.project + "_" + self.remainder)
        else:
            project = self._escape_string_for_spectra_assure_purl_component(self.project)

        package = self._escape_string_for_spectra_assure_purl_component(self.package)
        version = self._escape_string_for_spectra_assure_purl_component(self.version)

        logger.info(
            "F2P :: %s :: Repo: %s File: %s -> Purl: %s/%s@%s",
            self.p_type,
            self.file.repo.name,
            self.file.uri,
            project,
            package,
            version,
        )

        return project, package, version
