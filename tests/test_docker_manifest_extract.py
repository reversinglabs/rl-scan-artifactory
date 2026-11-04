# python3 ts=4space
"""DockerManifestExtract reads manifest.json / list.manifest.json and lists the blobs to fetch."""

import json
import pathlib
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.docker_manifest_extract import DockerManifestExtract
from rl_scan_artifactory.exceptions import (
    SpectraAssureInvalidAction,
    SpectraAssureInvariantError,
)

NODE_MEDIATYPE = "application/vnd.docker.distribution.manifest.v2+json"
TREE_MEDIATYPE = "application/vnd.docker.distribution.manifest.list.v2+json"

CONFIG_DIGEST = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
LAYER_DIGEST_1 = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
LAYER_DIGEST_2 = "sha256:3333333333333333333333333333333333333333333333333333333333333333"


def node_manifest(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": 2,
        "mediaType": NODE_MEDIATYPE,
        "config": {"mediaType": "application/vnd.docker.container.image.v1+json", "digest": CONFIG_DIGEST},
        "layers": [
            {"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip", "digest": LAYER_DIGEST_1},
            {"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip", "digest": LAYER_DIGEST_2},
        ],
    }
    data.update(overrides)
    return data


def write_manifest(tmp_path: pathlib.Path, data: Any, filename: str = "manifest.json") -> str:
    target = tmp_path / filename
    target.write_text(json.dumps(data))
    return str(target)


# ------------------------------------------------------------ file naming


def test_manifest_json_is_a_node(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    assert extract.manifest_type == "node"


def test_list_manifest_json_is_a_tree(tmp_path: pathlib.Path) -> None:
    data = {"schemaVersion": 2, "mediaType": TREE_MEDIATYPE, "manifests": []}
    path = write_manifest(tmp_path, data, filename="list.manifest.json")
    assert DockerManifestExtract(path).manifest_type == "tree"


def test_an_unknown_file_name_is_rejected(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SpectraAssureInvalidAction, match="unknown manifest file"):
        DockerManifestExtract(write_manifest(tmp_path, node_manifest(), filename="blob.json"))


# --------------------------------------------------------------- validation


def test_a_missing_schema_version_is_rejected(tmp_path: pathlib.Path) -> None:
    data = node_manifest()
    del data["schemaVersion"]
    with pytest.raises(SpectraAssureInvalidAction, match="schemaVersion"):
        DockerManifestExtract(write_manifest(tmp_path, data))


def test_a_missing_mediatype_is_rejected(tmp_path: pathlib.Path) -> None:
    data = node_manifest()
    del data["mediaType"]
    with pytest.raises(SpectraAssureInvalidAction, match="mediaType"):
        DockerManifestExtract(write_manifest(tmp_path, data))


def test_an_unknown_mediatype_is_rejected(tmp_path: pathlib.Path) -> None:
    """Was a bare assert, so it vanished under python -O and let the parse continue."""
    with pytest.raises(SpectraAssureInvariantError, match="known_mediatypes"):
        DockerManifestExtract(write_manifest(tmp_path, node_manifest(mediaType="application/json")))


def test_broken_json_is_reported_as_broken_json(tmp_path: pathlib.Path) -> None:
    """The read error used to be swallowed, and the next step then blamed schemaVersion."""
    target = tmp_path / "manifest.json"
    target.write_text("{not json")

    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        DockerManifestExtract(str(target))

    assert "as json" in str(excinfo.value)
    assert "schemaVersion" not in str(excinfo.value)


def test_an_unreadable_file_is_reported_as_unreadable(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SpectraAssureInvalidAction, match="as json"):
        DockerManifestExtract(str(tmp_path / "absent.manifest.json"))


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"a string"', "42"])
def test_json_that_is_not_an_object_is_rejected(tmp_path: pathlib.Path, payload: str) -> None:
    target = tmp_path / "manifest.json"
    target.write_text(payload)

    with pytest.raises(SpectraAssureInvalidAction, match="not a json object"):
        DockerManifestExtract(str(target))


# ------------------------------------------------------------------- items


def test_node_items_list_the_config_and_every_layer(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    items = extract.get_items()
    assert set(items) == {
        CONFIG_DIGEST.replace(":", "__"),
        LAYER_DIGEST_1.replace(":", "__"),
        LAYER_DIGEST_2.replace(":", "__"),
    }


def test_item_keys_use_the_artifactory_blob_file_name_form(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    for key in extract.get_items():
        assert key.startswith("sha256__")
        assert ":" not in key


def test_non_sha256_digests_are_skipped(tmp_path: pathlib.Path) -> None:
    data = node_manifest(layers=[{"digest": "sha512:abc"}, {"digest": LAYER_DIGEST_1}])
    extract = DockerManifestExtract(write_manifest(tmp_path, data))
    items = extract.get_items()
    assert LAYER_DIGEST_1.replace(":", "__") in items
    assert len(items) == 2  # config + one layer


def test_get_config_digest(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    extract.get_items()
    assert extract.get_config_digest() == CONFIG_DIGEST


def test_get_config_digest_is_none_before_items_are_read(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    assert extract.get_config_digest() is None


def test_annotations_are_collected(tmp_path: pathlib.Path) -> None:
    data = node_manifest(annotations={"org.opencontainers.image.version": "1.2.3"})
    extract = DockerManifestExtract(write_manifest(tmp_path, data))
    assert extract.annotations["org.opencontainers.image.version"] == "1.2.3"


def test_annotations_default_to_empty(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    assert extract.annotations == {}


# ------------------------------------------------------- multi-arch (tree)


def test_tree_items_are_currently_empty(tmp_path: pathlib.Path) -> None:
    """Pin the gap: a multi-arch image yields nothing to download."""
    data = {
        "schemaVersion": 2,
        "mediaType": TREE_MEDIATYPE,
        "manifests": [{"digest": LAYER_DIGEST_1, "platform": {"architecture": "amd64", "os": "linux"}}],
    }
    path = write_manifest(tmp_path, data, filename="list.manifest.json")
    assert DockerManifestExtract(path).get_items() == {}


# def test_tree_items_list_the_per_architecture_manifests(tmp_path: pathlib.Path) -> None:
#     data = {
#         "schemaVersion": 2,
#         "mediaType": TREE_MEDIATYPE,
#         "manifests": [{"digest": LAYER_DIGEST_1, "platform": {"architecture": "amd64", "os": "linux"}}],
#     }
#     path = write_manifest(tmp_path, data, filename="list.manifest.json")
#     assert DockerManifestExtract(path).get_items() != {}


# ------------------------------------------------------------ error message


def test_unknown_manifest_type_error_names_the_type(tmp_path: pathlib.Path) -> None:
    extract = DockerManifestExtract(write_manifest(tmp_path, node_manifest()))
    extract.manifest_type = "bogus"
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        extract.get_items()

    assert "bogus" in str(excinfo.value)
    assert "{self.manifest_type}" not in str(excinfo.value)
