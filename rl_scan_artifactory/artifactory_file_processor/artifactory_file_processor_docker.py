# python3 ts=4space
import json
import logging
import pathlib
import re
import tarfile
from typing import (
    Any,
)

from ..artifactory_api import ArtifactoryApi
from ..artifactory_repo_info import ArtifactoryRepoInfo
from ..constants import (
    DOCKER_LIST_MANIFEST_FILE,
    DOCKER_MANIFEST_FILE,
    PROCESS_FILE_SKIP,
    PROGRESS_ALL,
    PROGRESS_SCANNED,
)
from ..docker_manifest_extract import DockerManifestExtract
from ..exceptions import (
    SpectraAssureInvariantError,
)
from ..spectra_assure_api import SpectraAssureApi
from .artifactory_file_processor_common import ArtifactoryFileProcessorCommon

logger = logging.getLogger(__name__)


class ArtifactoryFileProcessorDocker(
    ArtifactoryFileProcessorCommon,
):
    def __init__(
        self,
        *,
        cli_args: dict[str, Any],
        spectra_assure_api: SpectraAssureApi | None,
        artifactory_api: ArtifactoryApi,
        repo: ArtifactoryRepoInfo,
        artifact_item: dict[str, Any],
        repo_db: dict[str, Any],  # pass info between file processing; docker list.manifest.json currently
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

    def _scanned_sha256(self) -> str | None:
        """None: what is scanned is a bundle assembled here, with no hash in artifactory.

        The manifest.json is not the image, so its hash would not say whether the
        image was rebuilt; and a None is not written, so it is not compared either
        (R10.7.3, R10.8).
        """
        return None

    def _process_one_docker_manifest_item(
        self,
        item: str,
        data: dict[str, Any],
    ) -> tuple[str | None, bool | None]:
        """
        Download a config or a layer item as specified in the manifest.json

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
        output: dict[str, str] = {}
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
    ) -> dict[str, Any] | None:
        # prep
        self.make_config_uri(config_digest)

        base_a = self.uri.split("/")[:-1]
        cd_a = config_digest.split(":")
        config_digest_file_path = self.download_dir + "/" + "_".join(base_a) + "_" + "__".join(cd_a)

        # if we block the config_file we block the docker download
        logger.debug("%s", self.config_digest_uri)

        # read
        try:
            with pathlib.Path(config_digest_file_path).open(mode="r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.exception("can not read the json file at: %s; %s", config_digest_file_path, e)
            return None

        # normalize type
        rr: dict[str, Any] = {}
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
        if "T" not in created:
            msg = "expected 'T' in created"
            raise SpectraAssureInvariantError(msg)
        if len(created) < len("YYYY-mm-ddTHH:MM:SS"):
            msg = "expected len(created) >= len('YYYY-mm-ddTHH:MM:SS')"
            raise SpectraAssureInvariantError(msg)

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
        config_data: dict[str, Any],
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
    ) -> tuple[bool, str]:
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
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

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
        with pathlib.Path(download_path).open("r", encoding="utf-8") as f:
            return json.load(f)

    # PUBLIC
    def collect_list_manifest_info(
        self,
    ) -> None:
        """Entry point for the pre pass: read this list.manifest.json into repo_db."""
        self._get_list_manifest_json_docker()

    def _get_list_manifest_json_docker(
        self,
    ) -> None:
        """Collect the per architecture manifests of a multi architecture image into repo_db.

        Each entry maps the digest, in the sha256__<hex> form artifactory uses as a
        directory name, to the manifest that names it. A manifest.json later found under
        such a directory uses this to recover its real tag instead of the digest.

        A failure here is not fatal: it is logged and processing continues; the affected
        images then simply keep their digest as version.
        """
        uri = self.uri
        logger.debug("%s", uri)

        download_path, verify_ok = self.artifactory_api.download_one_file_with_verify(
            file=self.file,
            download_dir=self.download_dir,
        )
        logger.debug("%s -> %s, %s", uri, download_path, verify_ok)

        if download_path is None:
            logger.error("download failed for: %s", uri)
            return

        self.add_file_to_remove(item=download_path)

        if verify_ok is False:
            logger.error("download digest mismatch for: %s", uri)
            return

        try:
            data = self._read_file_json_docker(download_path=download_path)
        except (OSError, ValueError) as e:  # ValueError covers json.JSONDecodeError
            logger.error("cannot read %s as json: %s: %s", uri, type(e).__name__, e)
            return

        manifests = data.get("manifests", [])
        if not isinstance(manifests, list):
            logger.error("'manifests' in %s is not a list: %s", uri, type(manifests).__name__)
            return

        for manifest in manifests:
            if not isinstance(manifest, dict):
                continue

            digest = manifest.get("digest")
            if not digest or ":" not in digest:
                continue

            manifest["__uri__"] = uri.split("/")
            key = "__".join(digest.split(":"))
            if key not in self.repo_db:
                self.repo_db[key] = manifest

        logger.debug("repo_db now holds %d manifest digests", len(self.repo_db))

    def _try_extract_version_from_manifest_uri_and_repo_db(
        self,
    ) -> None:
        if self.filename.lower() != DOCKER_MANIFEST_FILE:
            msg = "expected self.filename.lower() == DOCKER_MANIFEST_FILE"
            raise SpectraAssureInvariantError(msg)

        zz = self.uri.split("/")
        self.docker_version = zz[-2]
        if not self.docker_version.startswith("sha256__"):
            return

        if self.docker_version not in self.repo_db:
            # lead with what identifies the item: a digest on its own says nothing
            # about which image in which repository is the cause
            logger.warning(
                "%s:%s; no list.manifest.json entry for this image, so the digest %s stays its version",
                self.file.repo.name,
                self.uri,
                self.docker_version,
            )
            return

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
        if self.what_backend != "portal":
            msg = "expected self.what_backend == 'portal'"
            raise SpectraAssureInvariantError(msg)

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

        if exists_on_portal:
            msg = "purl exists on portal"

            if sync_requested is False:
                self.processing_info.reason = msg
                self.processing_info.scan_state = scan_status
                self.processing_info.purl = purl
                self.processing_info.report = report

                self.processing_info.completed = False
                if scan_status in ["pass", "fail"]:
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
                    self.processing_info.reason = "request to sync failed"
                    return True

        # the portal is the only thing that knows whether this purl is there; what an
        # earlier run wrote in artifactory is a hint, not an answer
        if exists_on_portal is False:
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

        return bool(self._wait_for_scan_status_one_portal())

    def _process_cli(
        self,
        project: str,
        package: str,
        version: str,
    ) -> bool:
        if self.what_backend != "cli":
            msg = "expected self.what_backend == 'cli'"
            raise SpectraAssureInvariantError(msg)

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

    def process(
        self,
    ) -> bool:
        """Scan one docker manifest.json, in the order the steps can fail.

        Docker is the awkward one: the purl needs the architecture, the
        architecture is in the config blob, and the config blob is only reachable
        by downloading the manifest and following it. So unlike every other type,
        the download cannot be skipped by anything an earlier run recorded.

        Each step below either stops with a reason, which is what the run summary
        shows, or hands on to the next. The steps in order:

        1. is this file one we look at at all
        2. what an earlier run already recorded about it
        3. fetch the manifest
        4. follow it to the config, which carries the architecture
        5. build the purl from all of that
        6. hand over to the portal or the cli backend
        """
        self._start_as_skipped()

        handled = self._stop_unless_this_file_is_a_manifest()
        if handled is not None:
            return handled

        self._try_extract_version_from_manifest_uri_and_repo_db()

        handled = self._stop_if_an_earlier_run_finished_this()
        if handled is not None:
            return handled

        download_path = self._fetch_the_manifest()
        if download_path is None:
            return True

        described = self._read_what_the_manifest_describes(download_path=download_path)
        if described is None:
            return True

        project, package, version = self._make_the_purl(
            download_path=download_path,
            described=described,
        )

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

    def _start_as_skipped(
        self,
    ) -> None:
        """Every step that stops early leaves these as they are set here."""
        self.processing_info.completed = True
        self.processing_info.status = PROCESS_FILE_SKIP
        self.processing_info.scan_state = None
        self.processing_info.report = None
        self.processing_info.purl = None

    def _stop_unless_this_file_is_a_manifest(
        self,
    ) -> bool | None:
        """Is this a file we look at? None to carry on."""
        if self.fp is None:
            msg = "expected self.fp is not None"
            raise SpectraAssureInvariantError(msg)

        if self.fp.skip_non_candidate_file():
            self.processing_info.reason = "skip: not a candidate for inspection"
            return True

        if self.filename.lower() == DOCKER_LIST_MANIFEST_FILE:
            # already collected by the pre pass, nothing more to do here
            self.processing_info.reason = "file is only used for info gathering"
            return True

        if self.filename.lower() != DOCKER_MANIFEST_FILE:
            self.processing_info.reason = "file is not relevant"
            return True

        logger.debug("relevant file: %s", self.uri)
        return None

    def _stop_if_an_earlier_run_finished_this(
        self,
    ) -> bool | None:
        """What the RL.* properties of an earlier run say. None to carry on.

        An artifact scanned recently enough is done. One scanned long enough ago
        can be synced instead of scanned (R12.7). One uploaded whose scan had not
        finished is recorded as incomplete and carries on, so the scan is waited
        for.
        """
        progress = self.get_prop_progress()
        if progress not in PROGRESS_ALL:
            return None

        if self.cli_args.get("ignore_artifactory_properties") is not False:
            return None

        # if the scan date is older then 2 weeks schedule a sync instead of a scan # TODO
        if progress == PROGRESS_SCANNED:
            if self.sync_possible() is False:  # requires property scanned
                msg = f"already scanned: {self.file.repo.name}; {self.uri}"
                self.processing_info.reason = msg
                self.processing_info.scan_state = progress
                self.processing_info.report = self.get_prop_report()
                self.processing_info.purl = self.get_prop_purl()
                return True

            # we can do a sync instead of a scan; the stored verdict is the one
            # the sync replaces, so it is not reported as the state
            self.need_sync_datetime = True
            msg = f"last scan older than 14 days, sync: {self.file.repo.name}; {self.uri}"
            self.processing_info.completed = False
            self.processing_info.reason = msg
            self.processing_info.purl = self.get_prop_purl()
            return None

        msg = f"uploaded but no scan result yet: {self.file.repo.name}; {self.uri}"
        self.processing_info.completed = False
        self.processing_info.reason = msg
        self.processing_info.scan_state = progress
        self.processing_info.purl = self.get_prop_purl()
        return None

    def _fetch_the_manifest(
        self,
    ) -> str | None:
        """The manifest.json on disk, or None with a reason already set."""
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
            self.processing_info.reason = f"download failed file for: {download_path}"
            return None

        if verify_ok is False:
            self.processing_info.reason = f"verify failed file for: {download_path}"
            return None

        return download_path

    def _read_what_the_manifest_describes(
        self,
        download_path: str,
    ) -> tuple[Any, dict[str, Any]] | None:
        """Follow the manifest to its config blob. None with a reason already set.

        The config is where the architecture and the creation date live, and the
        purl needs both. Downloading the layers happens here too, because the
        bundle uploaded later is assembled from them.
        """
        dme = self._process_one_docker_manifest_json(  # downloads layers and config
            target_path=download_path,
        )
        if dme is None:
            self.processing_info.reason = f"cannot extract info from manifest.json for uri: {self.uri}"
            return None

        config_digest = dme.get_config_digest()
        if config_digest is None:
            self.processing_info.reason = f"cannot extract 'config_digest' from manifest.json for uri: {self.uri}"
            return None

        logger.debug(
            "Config digest, Output, Annotations: %s, %s, %s",
            config_digest,
            dme.output,
            dme.annotations,
        )

        config_data = self._read_config_digest_docker(config_digest)
        if config_data is None:
            self.processing_info.reason = (
                f"cannot extract 'config_data' from {config_digest} via manifest.json for uri: {self.uri}"
            )
            return None

        return dme, config_data

    def _make_the_purl(
        self,
        download_path: str,
        described: tuple[Any, dict[str, Any]],
    ) -> tuple[str, str, str]:
        """project.architecture / image_name @ version, and what the backend needs."""
        dme, config_data = described

        # a docker image may have a architecture
        self.file.last_modified = config_data.get("created", "")
        arch = self._make_docker_architecture_string(config_data=config_data)

        self.file.simple["arch"] = [arch]
        self.file.simple["dme"] = dme
        self.file.simple["download_path"] = download_path

        project = self.file.repo.name + "." + arch
        package = self.file.simple["name"][0].replace("/", "_")
        version = self._extrapolate_docker_version_string(dme)
        if version is None:
            msg = "expected version is not None"
            raise SpectraAssureInvariantError(msg)

        self.purl_info.project = project
        self.purl_info.package = package
        self.purl_info.version = version

        logger.debug("purl: %s", self.purl_info.make_purl())
        return project, package, version
