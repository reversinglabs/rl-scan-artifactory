# python3 ts=4space
"""The RL.progress vocabulary lives in constants.py, and only there.

RL.progress decides whether an artifact an earlier run already handled gets
processed again, so the value written and the values tested for have to be the
same words. They were not: the generic processor compared RL.progress against
"portal_upload_ok", a key of the since-removed in-memory steps dict that was
never written to the property, while the value actually stored is
"upload_to_portal_ok". That comparison could never match, so a generic artifact
uploaded but not yet scanned was uploaded to the Portal a second time.

Two words that read alike is the whole cause. The lookalike is gone with the
steps dict, and the remaining two words are typed nowhere but in constants.py.
These tests read the source to keep it that way: a literal reintroduced by hand
fails here rather than in production.
"""

import ast
import pathlib
import re

import pytest

from rl_scan_artifactory.constants import (
    PROGRESS_ALL,
    PROGRESS_SCANNED,
    PROGRESS_UPLOADED,
    PROP_NAME_SPECTRA_ASSURE_PROGRESS,
    PROP_SPECTRA_ASSURE_VALID_VALUES,
    SCAN_STATUS_ALL,
    SCAN_STATUS_FAIL,
    SCAN_STATUS_PASS,
)

PACKAGE = pathlib.Path("rl_scan_artifactory")
CONSTANTS = PACKAGE / "constants.py"

# every word that must not be typed outside constants.py
RESERVED: tuple[str, ...] = (
    PROGRESS_UPLOADED,
    PROGRESS_SCANNED,
)


def source_files() -> list[pathlib.Path]:
    return [path for path in sorted(PACKAGE.rglob("*.py")) if "__pycache__" not in path.parts and path != CONSTANTS]


def string_literals(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# ------------------------------------------------------------ the vocabulary


def test_there_are_exactly_two_progress_values() -> None:
    assert PROGRESS_ALL == [PROGRESS_UPLOADED, PROGRESS_SCANNED]


def test_the_progress_values_are_the_documented_ones() -> None:
    assert PROP_SPECTRA_ASSURE_VALID_VALUES[PROP_NAME_SPECTRA_ASSURE_PROGRESS] == PROGRESS_ALL


def test_the_scan_status_values() -> None:
    assert SCAN_STATUS_ALL == [SCAN_STATUS_PASS, SCAN_STATUS_FAIL]


def test_the_lookalike_word_exists_nowhere() -> None:
    """'portal_upload_ok' went with the steps dict; it must not come back."""
    gone = "portal_upload_ok"

    offenders = [
        f"{path}:{lineno}"
        for path in [*source_files(), CONSTANTS]
        for lineno, value in string_literals(path)
        if value == gone
    ]
    assert not offenders, offenders


# ------------------------------------------- nobody types these words by hand


def test_there_are_source_files_to_check() -> None:
    """Guard the guard: if this ever finds none, the tests below prove nothing."""
    assert len(source_files()) > 10


@pytest.mark.parametrize("word", RESERVED)
def test_the_word_appears_nowhere_outside_constants(word: str) -> None:
    offenders = [
        f"{path}:{lineno}" for path in source_files() for lineno, value in string_literals(path) if value == word
    ]
    assert not offenders, f"{word!r} typed as a literal at: {offenders}"


def test_constants_is_where_the_words_live() -> None:
    values = {value for _lineno, value in string_literals(CONSTANTS)}
    for word in RESERVED:
        assert word in values, word


# ----------------------------------------------- every comparison uses a name


def progress_comparisons() -> list[tuple[pathlib.Path, int, str]]:
    """Every `... progress ... in/== ...` in the source, with the compared expression."""
    found: list[tuple[pathlib.Path, int, str]] = []

    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if "progress" not in ast.unparse(node.left).lower():
                continue

            found.append((path, node.lineno, ast.unparse(node.comparators[0])))

    return found


def test_there_are_progress_comparisons_to_check() -> None:
    assert len(progress_comparisons()) >= 4


def test_every_progress_comparison_uses_a_constant() -> None:
    """This is the test the old bug would have failed."""
    literal = [
        f"{path}:{lineno} compares against {compared}"
        for path, lineno, compared in progress_comparisons()
        if '"' in compared or "'" in compared
    ]
    assert not literal, literal


# ------------------------------------------------------- docstrings survived
# The assert to raise conversion (A.2) inserted the guard as the first statement
# of each function, which in one case put it above the docstring. A string that
# is not the first statement is not a docstring, so the function silently lost
# it. This checks it cannot happen again unnoticed.


def misplaced_docstrings() -> list[str]:
    found: list[str] = []

    for path in [*source_files(), CONSTANTS]:
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for index, statement in enumerate(node.body):
                if index == 0:
                    continue
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                    if isinstance(statement.value.value, str):
                        found.append(f"{path}:{statement.lineno} {node.name}")
                        break

    return found


def test_no_docstring_sits_below_something_else() -> None:
    assert misplaced_docstrings() == []


# ------------------------------------------ the documented surface is the real one
# The spec claimed a retry adapter that did not exist, and the README named a
# --proxy-pass option and a PROXY_PASS variable that were never right. Both were
# prose nobody could check. These compare the documents with argparse itself.


def documented_options(text: str) -> set[str]:
    return set(re.findall(r"(--[a-z][a-z0-9-]{2,})", text))


def real_options() -> set[str]:
    import os
    import sys

    from rl_scan_artifactory.constants import MY_ENV_NAMES
    from rl_scan_artifactory.my_args import MyArgs

    kept = {name: os.environ.pop(name, None) for name in MY_ENV_NAMES}
    argv = sys.argv
    try:
        os.environ.update(
            {
                "ARTIFACTORY_HOST": "h",
                "ARTIFACTORY_USER": "u",
                "ARTIFACTORY_TOKEN": "t",
                "RLPORTAL_HOST": "h",
                "RLPORTAL_SERVER": "s",
                "RLPORTAL_ORG": "o",
                "RLPORTAL_GROUP": "g",
                "RLPORTAL_ACCESS_TOKEN": "p",
            },
        )
        sys.argv = ["rl-scan-artifactory", "--portal", "--repo", "r"]
        args = MyArgs()
        return {
            option for action in args.parser._actions for option in action.option_strings if option.startswith("--")
        }
    finally:
        sys.argv = argv
        for name, value in kept.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


README = pathlib.Path("README.md")


def test_the_readme_names_no_option_that_does_not_exist() -> None:
    """'--proxy-pass' was in the table for a long time; the option is --proxy-password."""
    assert documented_options(README.read_text(encoding="utf-8")) - real_options() == set()


def test_every_option_is_in_the_readme() -> None:
    missing = real_options() - documented_options(README.read_text(encoding="utf-8")) - {"--help"}
    assert missing == set()


def test_the_readme_names_no_environment_variable_that_does_not_exist() -> None:
    """'PROXY_PASS' was in the table; the variable is PROXY_PASSWORD."""
    from rl_scan_artifactory.constants import MY_ENV_NAMES

    named = {
        name
        for name in re.findall(r"\b([A-Z][A-Z0-9_]{4,})\b", README.read_text(encoding="utf-8"))
        if name.startswith(("ARTIFACTORY_", "RLPORTAL_", "RLSECURE_", "PROXY_", "LOG_"))
    }
    assert named - set(MY_ENV_NAMES) == set()


def test_every_environment_variable_is_in_the_readme() -> None:
    from rl_scan_artifactory.constants import MY_ENV_NAMES

    text = README.read_text(encoding="utf-8")
    assert {name for name in MY_ENV_NAMES if name not in text} == set()
