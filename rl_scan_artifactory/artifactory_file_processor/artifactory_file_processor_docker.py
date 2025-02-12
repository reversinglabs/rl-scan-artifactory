# python3 ts=4space
import json
import logging
import re
import tarfile

from typing import (
    Any,
    Dict,
    Tuple,
)

from .artifactory_file_processor_common import ArtifactoryFileProcessorCommon
from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..constants import (
    PROCESS_FILE_SKIP,
)
from ..docker_manifest_extract import DockerManifestExtract
from ..spectra_assure_api import SpectraAssureApi

logger = logging.getLogger(__name__)


class ArtifactoryFileProcessorDocker(
    ArtifactoryFileProcessorCommon,
):
    def __init__(
        self,
        *,
        cli_args: Dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: Dict[str, Any],
        repo_db: Dict[str, Any],  # pass infor between file processing; docker list.manifest.json currently
    ) -> None:
        super().__init__(
            cli_args=cli_args,
            spectra_assure_api=spectra_assure_api,
            artifactory_api=artifactory_api,
            repo=repo,
            artifact_item=artifact_item,
            repo_db=repo_db,
        )
        self.process_status: str | None = None
        self.docker_version: str | None = None
        self.config_digest_uri: str | None = None

    def _process_one_docker_manifest_item(
        self,
        item: str,
        data: Dict[str, Any],
    ) -> Tuple[str | None, bool]:
        """
        download a config or a layer item as specified in the manifest.json
        and verify with the specified sha256 from the manifest.json
        """
        logger.debug("%s; %s", item, data)

        item_uri = "/".join([self.up_uri, item])
        url = f"{self.artifactory_api.get_base_url()}/{self.file.repo.name}{item_uri}"

        t = "_".join(item_uri.split("/"))
        target_path = f"{self.download_dir}/{t}"
        sha256 = data.get("digest", "").split(":")[1]

        logger.debug("%s %s %s", url, target_path, sha256)

        download_path, verify_ok = self.artifactory_api.download_url_to_target_with_verify(
            url=url,
            target_path=target_path,
            sha256=sha256,
        )

        if download_path:
            self.add_file_to_remove(download_path)

        return download_path, verify_ok

    def _process_one_docker_manifest_json(
        self,
        target_path: str,  # path may be relative
    ) -> DockerManifestExtract | None:
        dme = DockerManifestExtract(
            file_path=target_path,
        )

        items = dme.get_items()
        logger.debug("items: %s", items)

        # now look for the sha256__ files on the same level as the manifest.json and download
        output: Dict[str, str] = {}
        for item, data in items.items():
            download_path, verify_ok = self._process_one_docker_manifest_item(
                item=item,
                data=data,
            )  # download happens here
            if download_path is None:
                return None

            if verify_ok is False:
                logger.error("verify failed for %s", download_path)
                return None

            output[item] = download_path

        logger.debug("output: %s", output)
        if len(output) == 0:
            return None

        dme.set_output(output)
        return dme

    @staticmethod
    def _docker_make_target_name(
        input_name: str,
    ) -> str:
        aa = input_name.split("/")
        return "_".join(aa)

    def make_config_uri(self, config_digest: str) -> None:
        aa = self.uri.split("/")[:-1]
        aa.append(
            config_digest.replace(
                ":",
                "__",
            ),
        )
        self.config_digest_uri = "/".join(aa)

        # if we block the config_file we block the docker download
        logger.debug("config_uri %s", self.config_digest_uri)

    def _read_config_digest_docker(
        self,
        config_digest: str,
    ) -> Dict[str, Any] | None:
        # prep
        self.make_config_uri(config_digest)

        base_a = self.uri.split("/")[:-1]
        cd_a = config_digest.split(":")
        config_digest_file_path = self.download_dir + "/" + "_".join(base_a) + "_" + "__".join(cd_a)

        # if we block the config_file we block the docker download
        logger.debug("%s", self.config_digest_uri)

        # read
        try:
            with open(config_digest_file_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.exception("can not read the json file at: %s; %s", config_digest_file_path, e)
            return None

        # normalize type
        rr: Dict[str, Any] = {}
        for k, v in data.items():
            rr[k] = v
        logger.debug("%s", rr)
        return rr

    def _make_tar_file_name_bundle_docker(
        self,
        package: str,
        version: str,
        arch: str,
    ) -> str:
        logger.debug("%s", self.file.simple)

        z = [
            package,
            version,
            arch,
        ]

        tarfile_name = self.download_dir + "/" + "_".join(z) + ".tar"
        logger.debug("tarfile: %s", tarfile_name)

        return str(tarfile_name)

    @staticmethod
    def _compact_created_docker(
        created: str,
    ) -> str:
        assert "T" in created
        assert len(created) >= len("YYYY-mm-ddTHH:MM:SS")

        pattern = r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})"
        m = re.match(pattern, created)
        logger.debug("%s %s %s", created, pattern, m)

        if m:
            return f"{m[1]}{m[2]}{m[3]}.{m[4]}{m[5]}"
        return ""

    def _extrapolate_docker_version_string(
        self,
        dme: DockerManifestExtract,
    ) -> str | None:
        version: str | None = None
        if len(self.file.simple.get("version", [])) > 0:
            version = self.file.simple["version"][0]

        if "sha256__" in self.uri.lower():
            k = "org.opencontainers.image.version"
            z = dme.annotations.get(k, "")
            logger.debug("%s %s", self.filename, z)
            if z and len(z) > 0:
                version = z
            else:
                version = self.docker_version

        if version == "latest":
            config = self._compact_created_docker(self.file.last_modified)
            version = f"{version}.{config}"

        logger.debug("version fixed: %s", version)
        return version

    @staticmethod
    def _make_docker_architecture_string(  # modifies self.file.simple
        config_data: Dict[str, Any],
    ) -> str:
        arch = config_data.get("architecture", "")
        os = config_data.get("os", "")
        variant = config_data.get("variant", "")  # may be not present

        if len(variant) == 0:
            return f"{os}-{arch}"
        return f"{os}-{arch}-{variant}"

    def _make_tar_file_from_docker_parts(
        self,
        project: str,
        package: str,
        version: str,
        dme: DockerManifestExtract,
        arch: str,
        target_path: str,
    ) -> Tuple[bool, str]:
        # purl = self.purl_info.make_purl()

        tarfile_name = self._make_tar_file_name_bundle_docker(
            package=package,
            version=version,
            arch=arch,
        )

        for item in list(dme.output.values()) + [target_path, tarfile_name]:
            self.add_file_to_remove(item=item)

        try:
            with tarfile.open(tarfile_name, "w:gz") as tar:  # not:wb, binary is implicit
                for k, v in dme.output.items():
                    logger.debug("add item %s: %s to tar", k, v)
                    tar.add(v)
        except Exception as e:
            msg = f"cannot create tar file for upload from items of {self.uri}; {e}"
            logger.exception(msg)
            return False, msg

        return True, tarfile_name

    def _upload_docker_tarfile(
        self,
        project: str,
        package: str,
        version: str,
        arch: str,
        dme: DockerManifestExtract,
        target_path: str,
    ) -> bool:
        purl = self.purl_info.make_purl()

        flag, info = self._make_tar_file_from_docker_parts(
            project=project,
            package=package,
            version=version,
            dme=dme,
            arch=arch,
            target_path=target_path,
        )
        logger.debug("flag: %s info: %s", flag, info)

        if flag is False:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.reason = info
            self.processing_info.purl = purl
            self.processing_info.report = None
            return True

        # we now have a tar file, we can upload it to the portal
        assert self.what_backend == "portal"

        is_uploaded = self._do_one_portal_upload(
            project=project,
            package=package,
            version=version,
            file_path=info,
        )
        return is_uploaded

    @staticmethod
    def _read_file_json_docker(
        download_path: str,
    ) -> Any:
        with open(download_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_list_manifest_json_docker(
        self,
    ) -> None:
        # download and get version/latest from path, collect hash info and architecture/os/variant
        uri = self.uri
        logger.debug("%s", uri)
        download_path, verify_ok = self.artifactory_api.download_one_file_with_verify(
            file=self.file,
            download_dir=self.download_dir,
        )
        logger.debug("%s -> %s, %s", uri, download_path, verify_ok)

        assert download_path is not None
        data = self._read_file_json_docker(download_path=download_path)
        manifests = data.get("manifests", [])
        for manifest in manifests:
            manifest["__uri__"] = uri.split("/")
            digest = manifest.get("digest")
            if digest:
                key = "__".join(digest.split(":"))
                assert key is not None
                if key not in self.repo_db:
                    self.repo_db[key] = manifest

        self.add_file_to_remove(item=download_path)

    def _try_extract_version_from_manifest_uri_and_repo_db(
        self,
    ) -> None:
        assert self.filename.lower() == "manifest.json"

        zz = self.uri.split("/")
        self.docker_version = zz[-2]
        if self.docker_version.startswith("sha256__"):
            if self.docker_version in self.repo_db:
                self.docker_version = self.repo_db[self.docker_version]["__uri__"][-2]
                logger.debug("my info: %s", self.docker_version)

        logger.debug(
            "project: %s, package: %s, version: %s, docker_version: %s",
            self.purl_info.project,
            self.purl_info.package,
            self.purl_info.version,
            self.docker_version,
        )

    def _process_portal(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        assert self.what_backend == "portal"

        purl = self.purl_info.make_purl()

        exists_on_portal, scan_status, report = self._exists_on_portal(
            project=project,
            package=package,
            version=version,
            digest=None,
        )

        # again if older 2 week use sync # TODO
        logger.debug(
            "EXISTS?: %s %s %s",
            exists_on_portal,
            scan_status,
            report,
        )

        sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime

        is_uploaded = self.file.simple.get("is_uploaded", False)
        if exists_on_portal:
            is_uploaded = True
            self.steps["portal_upload_ok"] = True
            msg = "purl exists on portal"

            if sync_requested is False:
                self.processing_info.reason = msg
                self.processing_info.scan_state = scan_status
                self.processing_info.purl = purl
                self.processing_info.report = report

                self.processing_info.completed = False
                if scan_status in ["pass", "fail"]:
                    self.steps["portal_scan_complete"] = True
                    self.processing_info.completed = True
            else:
                self.processing_info.reason = "portal-sync"
                sync_started = self._purl_sync_portal()
                if sync_started is None:
                    self.processing_info.purl = self.get_prop_purl()
                    self.processing_info.completed = True
                    self.processing_info.status = PROCESS_FILE_SKIP
                    self.processing_info.scan_state = None
                    self.processing_info.report = None
                    self.steps["artifactory_properties_exists"] = False
                    self.processing_info.reason = "request to sync failed"
                    return True
        else:
            is_uploaded = False

        if is_uploaded is False:
            is_uploaded = self._upload_docker_tarfile(
                project=project,
                package=package,
                version=version,
                arch=self.file.simple["arch"][0],
                dme=self.file.simple["dme"],
                target_path=self.file.simple["download_path"],
            )
            if is_uploaded is False:
                msg = "failed to upload to the portal"
                self.processing_info.reason = msg
                self.processing_info.completed = True
                return True

        return self._wait_for_scan_status_one_portal()

    def _process_cli(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        assert self.what_backend == "cli"

        purl = self.purl_info.make_purl()
        arch = self.file.simple["arch"][0]
        dme = self.file.simple["dme"]
        download_path = self.file.simple["download_path"]
        self.add_file_to_remove(download_path)

        # sync_requested = self.cli_args.get("sync", False) or self.need_sync_datetime
        # for now just keep the downloaded file even if we dont actually need it for sync
        flag, info = self._make_tar_file_from_docker_parts(
            project=project,
            package=package,
            version=version,
            dme=dme,
            arch=arch,
            target_path=download_path,
        )
        logger.debug("flag: %s info: %s", flag, info)

        if flag is False:
            self.processing_info.completed = True
            self.processing_info.status = PROCESS_FILE_SKIP
            self.processing_info.scan_state = None
            self.processing_info.reason = info
            self.processing_info.purl = purl
            self.processing_info.report = None
            return True

        return self.do_cli_after_download(  # will handle sync now internally
            project=project,
            package=package,
            version=version,
            download_path=info,
        )

    # PUBLIC

    def process(  # noqa: C901
        self,
    ) -> bool:
        """
        Docker is complicated:
        1. we have a path to a manifest.json.
        2. we need to find the architecture and os to make a unique purl.
        3. that info is in the actual build file only (the config part of the manifest).
        4. we download the config file and all the layers.
        5. we parse the config to extract architecture and os.
        6. once we have all that we bundle config and layers into a tar that we can upload.
        7. the purl will be <repo-name>.<os>-<arch>/<path1>_<path2>@<version-or-latest>
        8. there is no version in the manifest ,
            unless we have "annotations" in the manifest.json and "org.opencontainers.image.version"
        """
        self.processing_info.completed = True
        self.processing_info.status = PROCESS_FILE_SKIP
        self.processing_info.scan_state = None
        self.processing_info.report = None
        self.processing_info.purl = None

        assert self.fp is not None
        skip_candidate = self.fp.skip_non_candidate_file()
        if skip_candidate:
            self.processing_info.reason = "skip: not a candidate for inspection"
            return True

        if self.filename.lower() == "list.manifest.json":
            self._get_list_manifest_json_docker()
            self.processing_info.reason = "file is only used for info gathering"
            return True

        if self.filename.lower() != "manifest.json":
            self.processing_info.reason = "file is not relevant"
            return True

        # we now have a relevant file to inspect
        is_uploaded = False
        self.steps["portal_upload_ok"] = False
        self.steps["artifactory_properties_exists"] = False

        logger.debug("relevent file: %s", self.uri)
        self._try_extract_version_from_manifest_uri_and_repo_db()

        # look at artifactory properties first
        progress = self.get_prop_progress()
        if progress in ["scanned", "upload_to_portal_ok"]:
            self.processing_info.scan_state = progress
            self.steps["portal_upload_ok"] = True
            self.steps["artifactory_properties_exists"] = True

            if self.cli_args.get("ignore_artifactory_properties") is False:
                is_uploaded = True

                # if the scan date is older then 2 weeks schedule a sync instead of a scan # TODO
                if progress == "scanned":
                    if self.sync_possible() is False:  # requires property scanned
                        msg = f"already scanned: {self.file.repo.name}; {self.uri}"
                        self.processing_info.reason = msg
                        self.processing_info.report = self.get_prop_report()
                        self.processing_info.purl = self.get_prop_purl()
                        return True

                    # we can do a sync instead of a scan
                    self.need_sync_datetime = True

                msg = f"uploaded but no scan result yet: {self.file.repo.name}; {self.uri}"
                self.processing_info.completed = False
                self.processing_info.reason = msg
                self.processing_info.purl = self.get_prop_purl()

        # (neither scanned nor uploaded) or ignore
        logger.debug("prep for download&upload: docker uri: %s, %s", self.uri, self.file)

        target_name = self._docker_make_target_name(
            input_name=self.uri,
        )
        if target_name:
            self.add_file_to_remove(target_name)

        download_path, verify_ok = self._do_one_artifactory_download(
            target_name=target_name,
        )
        if download_path:
            self.add_file_to_remove(download_path)

        if download_path is None:
            msg = f"download failed file for: {download_path}"
            self.processing_info.reason = msg
            return True

        if verify_ok is False:
            msg = f"verify failed file for: {download_path}"
            self.processing_info.reason = msg
            return True

        # we now have a downloaded file (manifest.json) but still no purl info
        # -------------------------------------
        """
        With the manifest.json as the start of the journey,
        we try to collect sufficient data to find:
         - package
         - version
         - arch
         - os
         - variant
         - created
        As we already have the:
         - project
        from the uri path name.

        Depending on the path of the manifest.json (uri has sha256__ in the name),
        we may need to dive deeper to find the actual version from:
         - the config component of the manifest.json (it may have annotations).
         - or if we cant find any and version stays latest,
           then we add the creation date to make latest-yyyymmdd unique.

        If the version is not latest we already have the correct version in the uri path anyway,
        but a annotation may create a more distinct version string.
        """

        dme = self._process_one_docker_manifest_json(  # downloads layers and config
            target_path=download_path,
        )
        if dme is None:
            msg = f"cannot extract info from manifest.json for uri: {self.uri}"
            self.processing_info.reason = msg
            return True

        config_digest = dme.get_config_digest()
        if config_digest is None:
            msg = f"cannot extract 'config_digest' from manifest.json for uri: {self.uri}"
            self.processing_info.reason = msg
            return True

        logger.debug(
            "Config digest, Output, Annotations: %s, %s, %s",
            config_digest,
            dme.output,
            dme.annotations,
        )

        config_data = self._read_config_digest_docker(config_digest)
        if config_data is None:
            msg = f"cannot extract 'config_data' from {config_digest} via manifest.json for uri: {self.uri}"
            self.processing_info.reason = msg
            return True

        # ===============================================
        # a docker image may have a architecture
        self.file.last_modified = config_data.get("created", "")
        arch = self._make_docker_architecture_string(config_data=config_data)

        self.file.simple["arch"] = [arch]
        self.file.simple["dme"] = dme
        self.file.simple["download_path"] = download_path
        self.file.simple["is_uploaded"] = is_uploaded

        # ===============================================
        # now we can make a pUrl
        project = self.file.repo.name + "." + self.file.simple["arch"][0]
        package = self.file.simple["name"][0].replace("/", "_")
        version = self._extrapolate_docker_version_string(dme)
        assert version is not None

        self.purl_info.project = project
        self.purl_info.package = package
        self.purl_info.version = version

        purl = self.purl_info.make_purl()
        self.steps["have_package_url"] = True
        logger.debug("purl: %s", purl)

        if self.what_backend == "portal":
            return self._process_portal(
                project=project,
                package=package,
                version=version,
            )

        return self._process_cli(
            project=project,
            package=package,
            version=version,
        )
