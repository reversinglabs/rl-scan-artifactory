#! /usr/bin/env python3
"""Read the sha256 of the artifact an rl-json report describes.

The report is how we find out what the store actually holds without downloading
anything: the hashes of the scanned artifact are at report.info.file.hashes, as
a list of [type, value] pairs. The components under report.metadata each carry
their own hashes, so the path is read exactly and never searched for.

The portal answers the same question with the same shape, at
analysis.report.info.file.hashes, so read_hashes() serves both.
"""

import json
import logging
import pathlib
from typing import (
    Any,
)

from ..constants import (
    DEFAULT_DIGEST_TYPE,
    REPORT_HASHES_PATH,
    REPORT_SCHEMA_TESTED,
)

logger: logging.Logger = logging.getLogger(__name__)


def digest_from_hashes(
    hashes: Any,
    digest_type: str = DEFAULT_DIGEST_TYPE,
) -> str | None:
    """The value of one hash type out of a [[type, value], ...] list."""
    if not isinstance(hashes, list):
        return None

    for item in hashes:
        # an entry that is not a pair is not ours to interpret
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        if item[0] == digest_type:
            value: str = str(item[1])
            return value

    return None


def digest_from_report_data(
    data: Any,
    digest_type: str = DEFAULT_DIGEST_TYPE,
) -> str | None:
    """The scanned artifact's digest, from an already parsed rl-json report."""
    if not isinstance(data, dict):
        return None

    schema = data.get("schema")
    if schema != REPORT_SCHEMA_TESTED:
        # not a reason to refuse: the path may well be the same. Say so once, so a
        # later mismatch is not a mystery.
        logger.warning(
            "rl-json report schema is %s, this was written against %s",
            schema,
            REPORT_SCHEMA_TESTED,
        )

    node: Any = data
    for key in REPORT_HASHES_PATH:
        if not isinstance(node, dict):
            return None
        node = node.get(key)

    return digest_from_hashes(node, digest_type=digest_type)


def digest_from_report_file(
    report_path: str,
    digest_type: str = DEFAULT_DIGEST_TYPE,
) -> str | None:
    """The scanned artifact's digest, or None when we cannot tell.

    None means "unknown", never "different": every caller must treat not knowing
    as a reason to do the full work, not as a reason to skip it.
    """
    path = pathlib.Path(report_path)
    if not path.exists():
        logger.warning("no rl-json report at %s", report_path)
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("cannot read %s as json: %s: %s", report_path, type(e).__name__, e)
        return None

    return digest_from_report_data(data, digest_type=digest_type)
