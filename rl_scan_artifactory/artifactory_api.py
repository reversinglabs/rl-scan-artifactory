# python3 ts=4space
import hashlib
import logging
import os
import time
from typing import (
    Dict,
    Any,
    Tuple,
    List,
)

import requests
import urllib3

from .app_base_with_logging import AppBaseWithLogging
from .artifactory_repo_info import ArtifactoryRepoInfo
from .fileinfo import FileInfo
from .helpers import set_proxy
from .my_args import MyArgs
from .constants import (
    ARTIFACTORY_DOWNLOAD_TIMEOUT,
    VERIFY_BUF_SIZE,
    DEFAULT_DIGEST_TYPE,
)

logger = logging.getLogger(__name__)


class ArtifactoryApiBase(
    AppBaseWithLogging,
):
    def __init__(
        self,
        args: MyArgs,
    ) -> None:
        super().__init__(args)
        self.session = requests.Session()
        self._validate_my_params()
        self.timeout = ARTIFACTORY_DOWNLOAD_TIMEOUT  # 2 hours for large downloads

        proxy_server = self.cli_args.get("proxy_server")
        proxy_port = self.cli_args.get("proxy_port")
        proxy_user = self.cli_args.get("proxy_user")
        proxy_password = self.cli_args.get("proxy_password")

        if proxy_port:
            proxy_port = int(proxy_port)

        self.proxies: Dict[str, str] = set_proxy(
            server=proxy_server,
            port=proxy_port,
            user=proxy_user,
            password=proxy_password,
        )

    def _validate_my_params(
        self,
    ) -> None:
        self.host = self.cli_args.get("artifactory_host")
        assert self.host is not None

        self.user = self.cli_args.get("artifactory_user")
        assert self.user is not None

        self.token = self.cli_args.get("artifactory_token")
        self.api_key = self.cli_args.get("artifactory_api_key")
        assert self.token is not None or self.api_key is not None

        self.base_url = f"https://{self.host}/artifactory"

        if self.cli_args.get("ignore_cert_errors", False):
            urllib3.disable_warnings()
            self.session.verify = False

    def _request_get(
        self,
        url: str,
        params: Dict[str, Any] | None = None,
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
            assert self.token is not None
            assert self.user is not None
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
        params: Dict[str, Any] | None = None,
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
            assert self.token is not None
            assert self.user is not None
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
        params: Dict[str, Any] | None = None,
    ) -> Any:
        if params is None:
            params = {}

        logger.debug("url: %s:: %s", url, params)

        assert self.token is not None
        assert self.user is not None

        with open(file_path, "rb") as upload_data:
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
        params: Dict[str, Any] | None = None,
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
            assert self.token is not None
            assert self.user is not None
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
        data: Dict[str, Any],
        headers: Dict[str, Any] | None = None,
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
            assert self.token is not None
            assert self.user is not None
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

    def _request_patch(
        self,
        url: str,
        data: Dict[str, Any],
        headers: Dict[str, Any],
    ) -> Any:
        logger.debug("url: %s::%s", url, data)
        # Supported by local and local-cached repositories.

        if self.api_key:
            headers["X-JFrog-Art-Api"] = self.api_key

            r = self.session.patch(
                url,
                headers=headers,
                timeout=300,
                proxies=self.proxies,
            )
        else:
            assert self.token is not None
            assert self.user is not None
            r = self.session.patch(
                url,
                data={"props": data},
                auth=(self.user, self.token),
                headers=headers,
                timeout=300,
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
        what = DEFAULT_DIGEST_TYPE

        h = hashlib.new(what)
        with open(download_path, "rb") as f:
            while True:
                data = f.read(VERIFY_BUF_SIZE)
                if not data:
                    break
                h.update(data)
            digest = h.hexdigest()

        logger.info("file: %s has digest(%s): %s", download_path, what, digest)
        if digest.lower() == sha256.lower():
            return True

        logger.warn(
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
        """Downloads a URL content into a file (with large file support by streaming).

        :param url: URL to download.
        :param file_path: Local file name to contain the data downloaded.
        :param attempts: Number of attempts.

        :return: New file path. None if the download failed.
        """
        logger.debug(f"Downloading {url} content to {file_path}")

        chunk_size = 1024 * 1024
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    time.sleep(10)  # 10 seconds wait time between downloads

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
                    assert self.token is not None
                    assert self.user is not None
                    r = self.session.get(
                        url,
                        auth=(self.user, self.token),
                        timeout=self.timeout,
                        stream=True,
                        proxies=self.proxies,
                    )

                r.raise_for_status()
                with open(file_path, "wb") as out_file:
                    for chunk in r.iter_content(
                        chunk_size=chunk_size,
                    ):
                        out_file.write(chunk)

                logger.info("Download finished successfully: %s", file_path)
                return file_path

            except Exception as ex:
                logger.error(f"Attempt #{attempt} failed with error: {ex}")
        return None

    @staticmethod
    def _make_target_name(
        download_dir: str,
        file_name: str,
        target_name: str | None,
    ) -> str:
        if target_name is None:
            return "/".join([download_dir, file_name])

        return "/".join([download_dir, target_name])

    def download_url_to_target_with_verify(
        self,
        url: str,
        target_path: str,
        sha256: str | None = None,
    ) -> Tuple[str | None, bool]:
        logger.debug("%s -> %s, %s", url, target_path, sha256)

        download_path = self.download_url_to_file(
            url=url,
            file_path=target_path,
        )

        if sha256 is None:
            return download_path, False

        verify_ok = False
        if download_path is not None:
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
    ) -> Tuple[str | None, bool]:
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
        qp: Dict[str, Any],
    ) -> Dict[str, Any]:
        keys: Dict[str, str] = {
            "deep": "bool_int",  # only 0 and 1 are valid
            "depth": "int",
            "listFolders": "bool_int",
            "mdTimestamps": "bool_int",
            "includeRootPath": "bool_int",
        }

        qp_out: Dict[str, Any] = {}
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
        repo_list: List[str] | None = None,
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
        qp: Dict[str, Any] | None = None,
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
        if len(z):
            z_s = "&" + z_s

        url = f"{self.base_url}/api/storage/{repo.name}?list{z_s}"
        r = self._request_get(url)

        if r.status_code < 200 or r.status_code >= 300:
            return {}

        logger.debug("result: %s", r.json())

        return r.json()

    def list_file_info(
        self,
        file: FileInfo,
    ) -> Any:
        # GET /api/storage/{repoKey}/{filePath}
        file_path = file.uri
        url = f"{self.base_url}/api/storage/{file.repo.name}/{file_path}"
        r = self._request_get(url)

        if r.status_code < 200 or r.status_code >= 300:
            return {}

        return r.json()

    def get_repo_info(
        self,
        repo: str,
    ) -> Dict[str, Any]:
        # GET /api/v2/repositories/{repoKey}
        url = f"{self.base_url}/api/v2/repositories/{repo}"
        r = self._request_get(url)

        result: Dict[str, Any] = {}
        if r.status_code < 200 or r.status_code >= 300:
            return result

        logger.debug("result: %s", r.text)
        result = r.json()
        return result

    # properties

    def _get_item_properties_by_repo_name(
        self,
        repo_name: str,
        item_uri: str,
    ) -> Dict[str, Any]:
        # GET /api/storage/{repoKey}/{itemPath}?properties[=x[,y]]
        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}?properties"
        r = self._request_get(url)

        result: Dict[str, Any] = {}
        if r.status_code < 200 or r.status_code >= 300:
            return result

        result = r.json().get("properties", {})
        return result

    def get_item_properties(
        self,
        file: FileInfo,
    ) -> Dict[str, Any]:
        # GET /api/storage/{repoKey}/{itemPath}?properties[=x[,y]]
        url = f"{self.base_url}/api/storage/{file.repo.name}{file.uri}?properties"
        r = self._request_get(url)

        result: Dict[str, Any] = {}
        if r.status_code < 200 or r.status_code >= 300:
            return result

        result = r.json().get("properties", {})
        return result

    def get_one_prop(
        self,
        repo: ArtifactoryRepoInfo,
        item_uri: str,
        key: str,
    ) -> Any:
        # GET /api/storage/{repoKey}/{itemPath}?properties[=x[,y]]

        url = f"{self.base_url}/api/storage/{repo.name}{item_uri}?properties={key}"
        r = self._request_get(url)
        if r.status_code < 200 or r.status_code >= 300:
            return None
        result = r.json().get("properties", {})
        return result

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
        repo_name = repo.name
        if repo.repo_type.lower() == "remote":
            repo_name = repo.name + "-cache"

        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}"

        params: Dict[str, Any] = {
            "properties": f"{key}={value}",
            "recursive": int(recursive),
        }

        r = self._request_put(
            url=url,
            params=params,
        )
        if r.status_code < 200 or r.status_code >= 300:
            return False
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

        repo_name = repo.name
        if repo.repo_type.lower() == "remote":
            repo_name = repo.name + "-cache"

        params = {
            "properties": key,
            "recursive": int(recursive),
        }

        url = f"{self.base_url}/api/storage/{repo_name}{item_uri}"
        r = self._request_del(
            url,
            params=params,
        )
        if r.status_code < 200 or r.status_code >= 300:
            return False
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
            repo_name = file.repo.name + "-cache"

        url = f"{self.base_url}/ui/views/rpm"
        headers: Dict[str, Any] = {"Content-type": "application/json"}
        data: Dict[str, Any] = {
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

    def get_tags_docker(
        self,
        file: FileInfo,
    ) -> Any:
        # https://jfrog.com/help/r/jfrog-rest-apis/list-docker-repositories
        # GET /api/docker/{repo-key}/v2/{image name}/tags/list
        #   ?n=<Number of consecutive tags>&
        #   last=<last tag position (numeric) from previous response>
        logger.debug("uri: %s", file.uri)

        repo_key = "docker"
        image_name = "reversinglabs/rl-scanner:latest"
        url = f"{self.base_url}/api/docker/{repo_key}/v2/{image_name}/tags/list"

        r = self._request_get(url)
        if r.status_code < 200 or r.status_code >= 300:
            return None

        logger.debug("result: %s", r.json())

        return r.json()

    def upload_file_to_artifactory(
        self,
        file_path: str,
        repo_name: str,
        uri_path: str,
    ) -> Tuple[int, str, str]:
        url = f"{self.base_url}/{repo_name}{uri_path}"
        logger.debug(url)
        response = self._request_put_upload_file(
            url=url,
            file_path=file_path,
        )
        logger.debug("%s", response)

        return response.status_code, response.text, url
