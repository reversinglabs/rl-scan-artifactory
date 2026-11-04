# python3 ts=4space
"""An upload over other bytes must replace the version on the portal.

`exist_version` tells three states apart: absent, present with these bytes, and
present with other bytes (R10.7.5). The last one used to be folded into
"absent" in `_exists_on_portal`, so the upload that followed went out without
`replace` and the portal refused it with a 409 - on every run, for every
artifact rebuilt under the same version.

What is pinned here is the hand over: the answer of the existence check reaches
the upload as `replace`, and only that answer does.

Only the spectra assure api and artifactory are faked.
"""

from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_common import (
    ProcessingInfo,
    PurlInfo,
)
from rl_scan_artifactory.artifactory_file_processor.artifactory_file_processor_default import (
    ArtifactoryFileProcessorDefault,
)

from .conftest import make_file

DIGEST = "a" * 64


class FakeSpectraAssureApi:
    def __init__(self, answer: tuple[bool, bool]) -> None:
        self.answer = answer
        self.uploads: list[dict[str, Any]] = []

    def exist_version(self, **kwargs: Any) -> tuple[bool, bool]:
        return self.answer

    def upload_artifact_to_portal(self, **kwargs: Any) -> tuple[bool, str | None]:
        self.uploads.append(kwargs)
        return True, None


def processor(answer: tuple[bool, bool]) -> Any:
    proc: Any = ArtifactoryFileProcessorDefault.__new__(ArtifactoryFileProcessorDefault)

    proc.uri = "/m/mypkg/mypkg-1.0-py3-none-any.whl"
    proc.what_backend = "portal"
    proc.cli_args = {}
    proc.processing_info = ProcessingInfo()
    proc.purl_info = PurlInfo(project="my-repo", package="mypkg", version="1.0")
    proc.file = make_file(uri=proc.uri, package_type="pypi", repo_name="my-repo")
    proc.files_to_remove = []
    proc.portal_has_other_bytes = False
    proc.spectra_assure_api = FakeSpectraAssureApi(answer)

    proc._what_uri_and_recursive = lambda: (False, proc.uri)
    proc.set_props_all = lambda **kwargs: None
    proc._remove_files = lambda files: None

    return proc


def check_then_upload(answer: tuple[bool, bool]) -> Any:
    proc = processor(answer)
    exists, _scan_status, _report = proc._exists_on_portal(
        project="my-repo",
        package="mypkg",
        version="1.0",
        digest=DIGEST,
    )
    assert exists is False
    proc._do_one_portal_upload(
        project="my-repo",
        package="mypkg",
        version="1.0",
        file_path="/tmp/mypkg-1.0-py3-none-any.whl",
    )
    return proc


def test_other_bytes_on_the_portal_upload_with_replace() -> None:
    proc = check_then_upload((False, True))
    assert proc.spectra_assure_api.uploads[0]["replace"] is True


def test_an_absent_version_uploads_without_replace() -> None:
    """Nothing to overwrite, and one uploaded meanwhile by someone else must not be."""
    proc = check_then_upload((False, False))
    assert proc.spectra_assure_api.uploads[0]["replace"] is False


@pytest.mark.parametrize("answer", [(False, False), (True, False), (False, True)])
def test_the_flag_is_what_the_portal_said(answer: tuple[bool, bool]) -> None:
    """Set on every check, so nothing carries over from an earlier answer."""
    proc = processor(answer)
    proc.portal_has_other_bytes = not answer[1]
    proc._get_purl_scan_status_one = lambda: (None, None, 404)
    proc._portal_make_report_base = lambda: ""
    proc._exists_on_portal(project="my-repo", package="mypkg", version="1.0", digest=DIGEST)
    assert proc.portal_has_other_bytes is answer[1]
