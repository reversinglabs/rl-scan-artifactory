# python3 ts=4space
"""The file uploaded to the portal is removed once, whatever the upload answered.

`_do_one_portal_upload` removed the file after a successful upload, and
`_portal_download_upload_generic` removed it again, so every generic upload
logged `ERROR file missing` (seen in a live run of tools/verify_rebuild.sh).
After a failed upload nobody removed it, for default and docker alike, so each
one left its download behind.

The upload now removes the file in a `finally`, the only place that does.

Only artifactory and the portal are faked; the files are real.
"""

import logging
import pathlib
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_generic import (
    ArtifactoryFileProcessorGeneric,
)

from .conftest import make_file

META_URI = "/a/mypkg-1.0.bin.rl_meta"


class FakeSpectraAssureApi:
    def __init__(self, answer: tuple[bool, str | None] | Exception) -> None:
        self.answer = answer

    def upload_artifact_to_portal(self, **kwargs: Any) -> tuple[bool, str | None]:
        assert pathlib.Path(kwargs["file_path"]).exists(), "removed before it was uploaded"
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class FakeArtifactoryApi:
    """Downloads by writing the file where it was asked to."""

    def get_base_url(self) -> str:
        return "https://artifactory.example/artifactory"

    def download_url_to_target_with_verify(self, *, url: str, target_path: str, sha256: Any) -> tuple[str, bool]:
        pathlib.Path(target_path).write_bytes(b"the described file")
        return target_path, True


def processor(tmp_path: pathlib.Path, answer: tuple[bool, str | None] | Exception) -> Any:
    proc: Any = ArtifactoryFileProcessorGeneric.__new__(ArtifactoryFileProcessorGeneric)
    proc.uri = META_URI
    proc.what_backend = "portal"
    proc.cli_args = {"portal": True}
    proc.download_dir = str(tmp_path)
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo(project="generic-local", package="mypkg", version="1.0")
    proc.file = make_file(
        uri=META_URI,
        package_type="generic",
        repo_name="generic-local",
        properties={"generic._derived_.path": ["mypkg-1.0.bin"]},
    )
    proc.files_to_remove = []
    proc.portal_has_other_bytes = False
    proc.spectra_assure_api = FakeSpectraAssureApi(answer)
    proc.artifactory_api = FakeArtifactoryApi()
    proc.set_props_all = lambda **kwargs: None
    proc._what_uri_and_recursive = lambda: (False, META_URI)
    return proc


def upload(proc: Any) -> Any:
    return proc._portal_download_upload_generic(project="generic-local", package="mypkg", version="1.0")


def test_a_successful_upload_removes_the_file_once(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc = processor(tmp_path, (True, None))
    with caplog.at_level(logging.ERROR):
        assert upload(proc) is True

    assert list(tmp_path.iterdir()) == []
    assert "file missing" not in caplog.text


def test_a_failed_upload_removes_the_file_too(tmp_path: pathlib.Path) -> None:
    proc = processor(tmp_path, (False, "409 conflict"))
    assert upload(proc) is False
    assert list(tmp_path.iterdir()) == []


def test_an_upload_that_raises_removes_the_file_too(tmp_path: pathlib.Path) -> None:
    proc = processor(tmp_path, ConnectionError("portal unreachable"))
    with pytest.raises(ConnectionError):
        upload(proc)
    assert list(tmp_path.iterdir()) == []


def test_the_upload_itself_removes_the_file_when_refused(tmp_path: pathlib.Path) -> None:
    """Default and docker call it directly, with no clean up of their own after it."""
    proc = processor(tmp_path, (False, "409 conflict"))
    file_path = tmp_path / "mypkg-1.0-py3-none-any.whl"
    file_path.write_bytes(b"a wheel")

    assert proc._do_one_portal_upload(project="p", package="mypkg", version="1.0", file_path=str(file_path)) is False
    assert not file_path.exists()
