# python3 ts=4space
import hashlib
import logging
import os
import pathlib
import re
import time
from typing import (
    Any,
)

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .app_base_with_logging import AppBaseWithLogging
from .artifactory_repo_info import ArtifactoryRepoInfo
from .constants import (
    ARTIFACTORY_DOWNLOAD_TIMEOUT,
    DEFAULT_DIGEST_TYPE,
    DOWNLOAD_ANSWERED_STATUSES,
    DOWNLOAD_RETRY_WAIT_SECONDS,
    HTTP_RETRY_BACKOFF,
    HTTP_RETRY_METHODS,
    HTTP_RETRY_STATUSES,
    HTTP_RETRY_TOTAL,
    RECURSIVE_PROPS_LIMIT_PATTERN,
    RECURSIVE_PROPS_RETRY_STATUS,
    VERIFY_BUF_SIZE,
)
from .exceptions import (
    SpectraAssureInvalidAction,
    SpectraAssureInvariantError,
)
from .fileinfo import FileInfo
from .helpers import set_proxy
from .my_args import MyArgs

logger = logging.getLogger(__name__)


class ArtifactoryApiBase(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)
        self.session = self._make_session()
        self._validate_my_params()
        self.timeout = ARTIFACTORY_DOWNLOAD_TIMEOUT  # 2 hours for large downloads

        proxy_server = self.cli_args.get("proxy_server")
        proxy_port = self.cli_args.get("proxy_port")
        proxy_user = self.cli_args.get("proxy_user")
        proxy_password = self.cli_args.get("proxy_password")

        if proxy_port:
            proxy_port = int(proxy_port)

        self.proxies: dict[str, str] = set_proxy(
            server=proxy_server,
            port=proxy_port,
            user=proxy_user,
            password=proxy_password,
        )

    def _validate_my_params(
        self,
    ) -> None:
        self.host = self.cli_args.get("artifactory_host")
        if self.host is None:
            msg = "expected self.host is not None"
            raise SpectraAssureInvariantError(msg)

        self.user = self.cli_args.get("artifactory_user")
        if self.user is None:
            msg = "expected self.user is not None"
            raise SpectraAssureInvariantError(msg)

        self.token = self.cli_args.get("artifactory_token")
        self.api_key = self.cli_args.get("artifactory_api_key")
        if not (self.token is not None or self.api_key is not None):
            msg = "expected self.token is not None or self.api_key is not None"
            raise SpectraAssureInvariantError(msg)

        self.base_url = f"https://{self.host}/artifactory"

        if self.cli_args.get("ignore_cert_errors", False):
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            msg = (
                "certificate verify has been switched off as requested;"
                + " this will work both on the portal and artifactory"
            )
            logger.warning(msg)
            self.session.verify = False

    @staticmethod
    def _make_session() -> requests.Session:
        """One session for every call, retrying what is worth retrying.

        A run walks thousands of artifacts over minutes or hours, so a connection
        that drops once is expected. Without this, a single dropped connection on
        one report upload ended the run.

        Only transport failures and the statuses that mean "not now" are retried.
        A request artifactory answered - 401, 403, 404, or the 400 of the
        recursive property cap - is an answer, and retrying it would only be
        slower (R11.5.x handles that one itself).
        """
        session = requests.Session()

        retry = Retry(
            total=HTTP_RETRY_TOTAL,
            connect=HTTP_RETRY_TOTAL,
            read=HTTP_RETRY_TOTAL,
            status=HTTP_RETRY_TOTAL,
            backoff_factor=HTTP_RETRY_BACKOFF,
            status_forcelist=list(HTTP_RETRY_STATUSES),
            allowed_methods=list(HTTP_RETRY_METHODS),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    def _request_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if params is None:
            params = {}

        logger.debug("url: %s", url)

        if self.api_key:
            headers = {"X-JFrog-Art-Api": self.api_key}
            r = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )
        else:
            if self.token is None:
                msg = "expected self.token is not None"
                raise SpectraAssureInvariantError(msg)
            if self.user is None:
                msg = "expected self.user is not None"
                raise SpectraAssureInvariantError(msg)
            r = self.session.get(
                url,
                auth=(self.user, self.token),
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )

        logger.debug("status: %d, %s", r.status_code, r.text)
        return r

    def _request_put(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if params is None:
            params = {}

        logger.debug("url: %s:: %s", url, params)
        # Supported by local and local-cached repositories.

        if self.api_key:
            headers = {"X-JFrog-Art-Api": self.api_key}
            r = self.session.put(
                url,
                headers=headers,
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )
        else:
            if self.token is None:
                msg = "expected self.token is not None"
                raise SpectraAssureInvariantError(msg)
            if self.user is None:
                msg = "expected self.user is not None"
                raise SpectraAssureInvariantError(msg)
            r = self.session.put(
                url,
                auth=(self.user, self.token),
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )

        logger.debug("status: %d, %s", r.status_code, r.text)
        return r

    def _request_put_upload_file(
        self,
        url: str,
        file_path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if params is None:
            params = {}

        logger.debug("url: %s:: %s", url, params)

        if self.token is None:
            msg = "expected self.token is not None"
            raise SpectraAssureInvariantError(msg)
        if self.user is None:
            msg = "expected self.user is not None"
            raise SpectraAssureInvariantError(msg)

        with pathlib.Path(file_path).open("rb") as upload_data:
            r = self.session.put(
                url,
                auth=(self.user, self.token),
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
                data=upload_data,
            )

        logger.debug("status: %d, %s", r.status_code, r.text)
        return r

    def _request_del(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if params is None:
            params = {}

        logger.debug("url: %s, %s", url, params)
        # Supported by local and local-cached repositories.

        if self.api_key:
            headers = {"X-JFrog-Art-Api": self.api_key}
            r = self.session.delete(
                url,
                headers=headers,
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )
        else:
            if self.token is None:
                msg = "expected self.token is not None"
                raise SpectraAssureInvariantError(msg)
            if self.user is None:
                msg = "expected self.user is not None"
                raise SpectraAssureInvariantError(msg)
            r = self.session.delete(
                url,
                auth=(self.user, self.token),
                timeout=self.timeout,
                params=params,
                proxies=self.proxies,
            )

        logger.debug("status: %d, %s", r.status_code, r.text)
        return r

    def _request_post(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, Any] | None = None,
    ) -> Any:
        if headers is None:
            headers = {}

        logger.debug("url: %s:: %s", url, data)

        if self.api_key:
            headers["X-JFrog-Art-Api"] = self.api_key

            r = self.session.post(
                url,
                timeout=self.timeout,
                headers=headers,
                json=data,
                proxies=self.proxies,
            )
        else:
            if self.token is None:
                msg = "expected self.token is not None"
                raise SpectraAssureInvariantError(msg)
            if self.user is None:
                msg = "expected self.user is not None"
                raise SpectraAssureInvariantError(msg)
            r = self.session.post(
                url,
                auth=(self.user, self.token),
                timeout=self.timeout,
                headers=headers,
                json=data,
                proxies=self.proxies,
            )

        logger.debug("status: %d, %s", r.status_code, r.text)
        return r


class ArtifactoryApi(ArtifactoryApiBase):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)

    # download file with verify

    @staticmethod
    def _verify_download_file(
        sha256: str,
        download_path: str,
    ) -> bool:
        """True when the file matches sha256, False when it does not.

        There is no third answer here: 'nothing to verify against' is not a
        verification outcome and must be decided before calling, which is what
        download_url_to_target_with_verify does. An empty or absent digest
        reaching this point is a bug in the caller, not a mismatch to report.
        """
        if not sha256:
            msg = f"no digest to verify {download_path} against"
            raise SpectraAssureInvalidAction(msg)

        what = DEFAULT_DIGEST_TYPE

        h = hashlib.new(what)
        with pathlib.Path(download_path).open("rb") as f:
            while True:
                data = f.read(VERIFY_BUF_SIZE)
                if not data:
                    break
                h.update(data)
            digest = h.hexdigest()

        logger.info("file: %s has digest(%s): %s", download_path, what, digest)
        if digest.lower() == sha256.lower():
            return True

        logger.warning(
            "file: %s with digest(%s): %s is not identical to artifactory sha2: %s",
            download_path,
            what,
            digest,
            sha256,
        )
        return False

    def download_url_to_file(
        self,
        url: str,
        file_path: str,
        attempts: int = 2,
    ) -> str | None:
        """
        Downloads a URL content into a file (with large file support by streaming).

        :param url: URL to download.
        :param file_path: Local file name to contain the data downloaded.
        :param attempts: Number of attempts.

        :return: New file path. None if the download failed.

        A status that is an answer is not retried: 403 is how artifactory refuses
        an artifact a policy plugin has blocked, and asking again only spends the
        wait. A run over a repository of blocked artifacts used to spend twenty
        seconds per artifact re-asking a settled question.
        """
        logger.debug(f"Downloading {url} content to {file_path}")

        chunk_size = 1024 * 1024
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    time.sleep(DOWNLOAD_RETRY_WAIT_SECONDS)

                if self.api_key:
                    headers = {"X-JFrog-Art-Api": self.api_key}
                    r = self.session.get(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                        stream=True,
                        proxies=self.proxies,
                    )
                else:
                    if self.token is None:
                        msg = "expected self.token is not None"
                        raise SpectraAssureInvariantError(msg)
                    if self.user is None:
                        msg = "expected self.user is not None"
                        raise SpectraAssureInvariantError(msg)
                    r = self.session.get(
                        url,
                        auth=(self.user, self.token),
                        timeout=self.timeout,
                        stream=True,
                        proxies=self.proxies,
                    )

                r.raise_for_status()
                with pathlib.Path(file_path).open("wb") as out_file:
                    out_file.writelines(
                        r.iter_content(
                            chunk_size=chunk_size,
                        ),
                    )

                logger.info("Download finished successfully: %s", file_path)
                return file_path

            except requests.HTTPError as ex:
                status = ex.response.status_code if ex.response is not None else 0
                if status in DOWNLOAD_ANSWERED_STATUSES:
                    logger.error("%s: %s", self._download_refusal(status), url)
                    return None

                logger.error("Attempt #%s failed with error: %s", attempt, ex)

            except Exception as ex:  # noqa: BLE001
                logger.error("Attempt #%s failed with error: %s", attempt, ex)

        return None

    @staticmethod
    def _download_refusal(
        status: int,
    ) -> str:
        """Say what a refusal means, so a run does not look like a network problem.

        A 403 on an artifact that exists is almost always a policy plugin such as
        Spectra Assure Protect refusing to serve something that failed a scan, or
        an address that is not on its allow list. Reporting that as "download
        failed" sends people looking at the network.
        """
        if status == 403:
            return "download refused (403): blocked by a policy, or this address is not permitted"
        if status == 404:
            return "download refused (404): not found"
        if status == 401:
            return "download refused (401): not authenticated"

        return f"download refused ({status})"

    @staticmethod
    def _make_target_name(
        download_dir: str,
        file_name: str,
        target_name: str | None,
    ) -> str:
        """Build the download path: one plain file directly inside download_dir.

        Both names are derived from a repository uri we do not control, so a path
        separator or a parent reference in one would put the download outside the
        directory we later clean up. Refuse rather than sanitise: every legitimate
        caller passes a flat file name already.
        """
        name = file_name if target_name is None else target_name

        if name in ("", ".", "..") or "/" in name or "\\" in name:
            msg = f"refusing to download to '{name}': not a plain file name"
            raise SpectraAssureInvalidAction(msg)

        return "/".join([download_dir, name])

    def download_url_to_target_with_verify(
        self,
        url: str,
        target_path: str,
        sha256: str | None = None,
    ) -> tuple[str | None, bool | None]:
        """
        Download `url` to `target_path` and verify the result against `sha256`.

        :return: (download path or None, verify result)
            The verify result is True on a digest match, False on a mismatch,
            and None when there was nothing to verify against
            (no sha256 given, or nothing was downloaded).
        """
        logger.debug("%s -> %s, %s", url, target_path, sha256)

        download_path = self.download_url_to_file(
            url=url,
            file_path=target_path,
        )

        # an empty sha2 from artifactory is as good as none: there is nothing to
        # verify against, which is None rather than a failed verification
        verify_ok: bool | None = None
        if sha256 and download_path is not None:
            verify_ok = self._verify_download_file(
                sha256=sha256,
                download_path=download_path,
            )

        logger.debug("download path: %s verify_ok: %s", download_path, verify_ok)
        return download_path, verify_ok

    def get_base_url(
        self,
    ) -> str:
        return self.base_url

    def download_one_file_with_verify(
        self,
        *,
        file: FileInfo,
        download_dir: str = "/tmp",
        target_name: str | None = None,
    ) -> tuple[str | None, bool | None]:
        file_name = os.path.basename(file.uri)

        target_path = self._make_target_name(
            download_dir=download_dir,
            file_name=file_name,
            target_name=target_name,
        )

        download_path, verify_ok = self.download_url_to_target_with_verify(
            url=f"{self.base_url}/{file.repo.name}{file.uri}",
            target_path=target_path,
            sha256=file.sha2,
        )

        return download_path, verify_ok

    # repository info
    @staticmethod
    def list_repo_items_valid_qp(
        qp: dict[str, Any],
    ) -> dict[str, Any]:
        keys: dict[str, str] = {
            "deep": "bool_int",  # only 0 and 1 are valid
            "depth": "int",
            "listFolders": "bool_int",
            "mdTimestamps": "bool_int",
            "includeRootPath": "bool_int",
        }

        qp_out: dict[str, Any] = {}
        for k, v in qp.items():
            if k not in keys:
                continue
            if keys[k] == "int":
                qp_out[k] = int(v)
                continue
            if keys[k] == "bool_int":
                qp_out[k] = int(bool(v))
                continue

        return qp_out

    def get_artifactory_version(self) -> Any:
        # https://alt-artifactory-dev.rl.lan/artifactory/api/system/version
        url = f"{self.base_url}/api/system/version"

        r = self._request_get(url)
        if r.status_code < 200 or r.status_code >= 300:
            return {}

        logger.debug("result: %s", r.json())
        return r.json()

    def search_prop_fail(
        self,
        repo_list: list[str] | None = None,
    ) -> Any:
        # GET https://alt-artifactory-dev/artifactory/api/search/
        #    prop?RL.scan-status=fail[&repos=my-release-candidates,docker-local]
        url = f"{self.base_url}/api/search/prop?RL.scan-status=fail"

        if repo_list is None:
            repo_list = []

        repos = ",".join(repo_list)
        if len(repos) > 0:
            url = url + "&repos=" + repos

        logger.debug("url: %s", url)
        r = self._request_get(url)
        if r.status_code < 200 or r.status_code >= 300:
            return {}
        logger.debug("result: %s", r.json())

        return r.json()

    def list_repo_items(
        self,
        repo: ArtifactoryRepoInfo,
        qp: dict[str, Any] | None = None,
    ) -> Any:
        # GET /api/storage/{repoKey}/{folder-path}
        #   ?list[&deep=0/1][&depth=n][&listFolders=0/1][&mdTimestamps=0/1][&includeRootPath=0/1]
        if qp is None:
            qp = {}
        qp = self.list_repo_items_valid_qp(qp=qp)

        z = []
        for k, v in qp.items():
            z.append(f"{k}={v}")
        z_s = "&".join(z)
        if z:
            z_s = "&" + z_s

        url = f"{self.base_url}/api/storage/{self._storage_repo_name(repo)}?list{z_s}"
        r = self._request_get(url)

        if r.status_code < 200 or r.status_code >= 300:
            return {}

        logger.debug("result: %s", r.json())

        return r.json()

    def get_repo_info(
        self,
        repo: str,
    ) -> dict[str, Any]:
        """The configuration of one repository, or {} when we cannot read it.

        An empty result is not the same as an empty configuration: it means the
        repository does not exist, or we may not read it, or the request failed.

        The caller reports the skip, so the status is logged here at **debug**
        only: at warning it made one unreadable repository produce two warnings
        saying the same thing. The status still tells a 404 from a 403 when you
        need it, which is the reason to keep it at all.
        """
        # GET /api/v2/repositories/{repoKey}
        url = f"{self.base_url}/api/v2/repositories/{repo}"
        r = self._request_get(url)

        result: dict[str, Any] = {}
        if r.status_code < 200 or r.status_code >= 300:
            logger.debug(
                "cannot read the configuration of repository '%s': status %s; %s",
                repo,
                r.status_code,
                self._error_message(r),
            )
            return result

        logger.debug("result: %s", r.text)
        result = r.json()
        return result

    # properties

    def get_item_properties(
        self,
        file: FileInfo,
    ) -> dict[str, Any]:
        # GET /api/storage/{repoKey}/{itemPath}?properties[=x[,y]]
        url = f"{self.base_url}/api/storage/{self._storage_repo_name(file.repo)}{file.uri}?properties"
        r = self._request_get(url)

        result: dict[str, Any] = {}
        if r.status_code < 200 or r.status_code >= 300:
            return result

        result = r.json().get("properties", {})
        return result

    @staticmethod
    def _storage_repo_name(
        repo: ArtifactoryRepoInfo,
    ) -> str:
        """The canonical /api/storage name of a repository.

        Only local repositories and the cache side of a remote one hold artifacts
        and accept custom properties; a remote repository itself is not writable.

        Reads through the bare remote name happen to work, because Artifactory
        resolves it to the cache and even answers with the cache uri, but that
        convenience is not part of the api contract. Every /api/storage call
        therefore uses the canonical name.

        This does NOT apply to the artifact download url, which is not an
        /api/storage call: that one proxies through the bare remote name.
        """
        if repo.repo_type.lower() == "remote":
            return repo.name + "-cache"
        return repo.name

    @staticmethod
    def _error_message(
        r: Any,
    ) -> str:
        """The message out of Artifactory's ErrorResponse, if it sent one."""
        try:
            errors = r.json().get("errors", [])
        except ValueError:
            return ""

        if not isinstance(errors, list):
            return ""

        return "; ".join(str(e.get("message", "")) for e in errors if isinstance(e, dict))

    @staticmethod
    def _recursive_limit_from(
        message: str,
    ) -> str | None:
        """The item limit named in a 'more than <n> items' refusal, if that is what this is."""
        m = re.search(RECURSIVE_PROPS_LIMIT_PATTERN, message, re.IGNORECASE | re.DOTALL)
        if m is None:
            return None
        return m.group(1)

    def _put_props_once(
        self,
        repo_name: str,
        item_uri: str,
        key: str,
        value: str,
        recursive: bool,
    ) -> Any:
        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}"

        params: dict[str, Any] = {
            "properties": f"{key}={value}",
            "recursive": int(recursive),
        }

        return self._request_put(
            url=url,
            params=params,
        )

    def list_items_below(
        self,
        repo: ArtifactoryRepoInfo,
        item_uri: str,
    ) -> list[str]:
        """Every file below item_uri, as uris relative to the repository root."""
        repo_name = self._storage_repo_name(repo)
        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}?list&deep=1&listFolders=0"

        r = self._request_get(url)
        if r.status_code < 200 or r.status_code >= 300:
            logger.error("cannot list %s%s: %s", repo_name, item_uri, r.status_code)
            return []

        files = r.json().get("files", [])
        if not isinstance(files, list):
            return []

        out: list[str] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            if item.get("folder"):
                continue
            uri = item.get("uri")
            if uri:
                out.append(f"{item_uri}{uri}")

        return out

    def put_one_prop(
        self,
        repo: ArtifactoryRepoInfo,
        item_uri: str,
        key: str,
        value: str,
        recursive: bool = False,
    ) -> bool:
        # PUT /api/storage/{repoKey}/{itemPath}?properties=p1=v1&recursive=0]
        # https://my.secure.software/<instance = server>/<report part>
        logger.debug("%s; %s: %s", item_uri, key, value)

        # value = quote(value, safe="/@=")
        repo_name = self._storage_repo_name(repo)

        r = self._put_props_once(
            repo_name=repo_name,
            item_uri=item_uri,
            key=key,
            value=value,
            recursive=recursive,
        )
        if 200 <= r.status_code < 300:
            return True

        message = self._error_message(r)
        logger.error(
            "set property failed: %s%s; %s=%s; recursive=%s; status %s; %s",
            repo_name,
            item_uri,
            key,
            value,
            recursive,
            r.status_code,
            message,
        )

        if self._should_retry_per_item(recursive=recursive, status=r.status_code, message=message) is False:
            return False

        return self._put_one_prop_per_item(
            repo=repo,
            repo_name=repo_name,
            item_uri=item_uri,
            key=key,
            value=value,
        )

    def _should_retry_per_item(
        self,
        recursive: bool,
        status: int,
        message: str,
    ) -> bool:
        """Is this refusal one that splitting into single items could get past?

        Only a recursive call, and only on the status the cap arrives as. 401, 403
        and 404 mean credentials, permissions or a missing item, and splitting
        cannot help with any of those.
        """
        if not recursive or status != RECURSIVE_PROPS_RETRY_STATUS:
            return False

        limit = self._recursive_limit_from(message)
        if limit is not None:
            logger.warning("the server caps recursive property updates at %s item(s)", limit)
            return True

        # retry anyway: the wording is not part of the api contract, and a 400 we
        # do not recognise is more likely a reworded cap than a malformed value
        logger.warning(
            "unrecognised 400 on a recursive property update, retrying per item: %s",
            message,
        )
        return True

    def _put_one_prop_per_item(
        self,
        repo: ArtifactoryRepoInfo,
        repo_name: str,
        item_uri: str,
        key: str,
        value: str,
    ) -> bool:
        """Fall back from one recursive update to one update per item below item_uri.

        A recursive update can be refused because the server caps how many artifacts
        it may touch at once (artifactory.max.artifacts.set.properties.recursive,
        since 7.104.x). The api has no dedicated status for that, so this runs on any
        400 from a recursive call; when the 400 was really a malformed properties
        value the per item calls fail too, and the log says so for each.

        Setting a property is idempotent, so items the refused call had already
        updated are simply set to the same value again.
        """
        items = self.list_items_below(repo=repo, item_uri=item_uri)
        if not items:
            logger.error("no items below %s%s to update one by one", repo_name, item_uri)
            return False

        logger.warning(
            "recursive set property refused for %s%s; retrying %d item(s) one by one",
            repo_name,
            item_uri,
            len(items),
        )

        failed: list[str] = []
        for uri in items:
            r = self._put_props_once(
                repo_name=repo_name,
                item_uri=uri,
                key=key,
                value=value,
                recursive=False,
            )
            if 200 <= r.status_code < 300:
                continue

            failed.append(uri)
            logger.error(
                "set property failed: %s%s; %s=%s; status %s; %s",
                repo_name,
                uri,
                key,
                value,
                r.status_code,
                self._error_message(r),
            )

        if failed:
            logger.error(
                "%d of %d item(s) below %s%s could not be updated",
                len(failed),
                len(items),
                repo_name,
                item_uri,
            )
            return False

        logger.info("updated %d item(s) below %s%s one by one", len(items), repo_name, item_uri)
        return True

    def del_one_prop(
        self,
        repo: ArtifactoryRepoInfo,
        item_uri: str,
        key: str,
        recursive: bool = False,
    ) -> bool:
        # DELETE /api/storage/libs-release-local/ch/qos/logback/logback-classic/0.9.9?properties=os,qa&recursive=0
        logger.debug("del prop %s:%s %s %s", repo.name, item_uri, key, recursive)

        repo_name = self._storage_repo_name(repo)

        params = {
            "properties": key,
            "recursive": int(recursive),
        }

        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}"
        r = self._request_del(
            url,
            params=params,
        )
        if 200 <= r.status_code < 300:
            return True

        message = self._error_message(r)
        logger.error(
            "delete property failed: %s%s; %s; recursive=%s; status %s; %s",
            repo_name,
            item_uri,
            key,
            recursive,
            r.status_code,
            message,
        )

        if self._should_retry_per_item(recursive=recursive, status=r.status_code, message=message) is False:
            return False

        return self._del_one_prop_per_item(
            repo=repo,
            repo_name=repo_name,
            item_uri=item_uri,
            key=key,
        )

    def _del_one_prop_per_item(
        self,
        repo: ArtifactoryRepoInfo,
        repo_name: str,
        item_uri: str,
        key: str,
    ) -> bool:
        """Fall back from one recursive delete to one delete per item below item_uri.

        The cap of R11.4.3 applies to deleting properties as it does to setting
        them, and the refusal reads the same way. Deleting a property that is not
        there is not an error, so items the refused call had already handled cost
        nothing on the retry.
        """
        items = self.list_items_below(repo=repo, item_uri=item_uri)
        if not items:
            logger.error("no items below %s%s to delete from one by one", repo_name, item_uri)
            return False

        logger.warning(
            "recursive delete property refused for %s%s; retrying %d item(s) one by one",
            repo_name,
            item_uri,
            len(items),
        )

        failed: list[str] = []
        for uri in items:
            url = f"{self.base_url}/api/storage/{repo_name}{uri}"
            r = self._request_del(url, params={"properties": key, "recursive": 0})
            if 200 <= r.status_code < 300:
                continue

            failed.append(uri)
            logger.error(
                "delete property failed: %s%s; %s; status %s; %s",
                repo_name,
                uri,
                key,
                r.status_code,
                self._error_message(r),
            )

        if failed:
            logger.error(
                "%d of %d item(s) below %s%s could not have %s deleted",
                len(failed),
                len(items),
                repo_name,
                item_uri,
                key,
            )
            return False

        logger.info("deleted %s from %d item(s) below %s%s one by one", key, len(items), repo_name, item_uri)
        return True

    def set_one_prop(
        self,
        repo: ArtifactoryRepoInfo,
        item_uri: str,
        key: str,
        value: str,
        recursive: bool = False,
    ) -> Any:
        return self.put_one_prop(
            repo=repo,
            item_uri=item_uri,
            key=key,
            value=value,
            recursive=recursive,
        )

    def touch_rpm_info_uri(
        self,
        file: FileInfo,
    ) -> bool:
        if file.repo.package_type.lower() not in ["rpm"]:
            logger.warning(
                "this operation only applies to rpm type repo's; this is: name: '%s' type: '%s'",
                file.repo.name,
                file.repo.package_type,
            )
            return True

        repo_name = file.repo.name
        if file.repo.repo_type.lower() == "remote":
            repo_name = self._storage_repo_name(file.repo)

        url = f"{self.base_url}/ui/views/rpm"
        headers: dict[str, Any] = {"Content-type": "application/json"}
        data: dict[str, Any] = {
            "view": "rpm",
            "repoKey": repo_name,
            "path": file.uri,
        }

        r = self._request_post(
            url,
            headers=headers,
            data=data,
        )
        logger.debug("post result: %s -> %s, %s", url, r.status_code, r.text)

        if r.status_code < 200 or r.status_code >= 300:
            return False
        return True

    def upload_file_to_artifactory(
        self,
        file_path: str,
        repo_name: str,
        uri_path: str,
    ) -> tuple[int, str, str]:
        url = f"{self.base_url}/{repo_name}{uri_path}"
        logger.debug(url)
        response = self._request_put_upload_file(
            url=url,
            file_path=file_path,
        )
        logger.debug("%s", response)

        return response.status_code, response.text, url
