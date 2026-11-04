# python3 ts=4space
"""The string surgery in NameManglerCommon.

These helpers decide what ends up in the purl, so their edge cases matter.
Tests marked xfail(strict=True) document a bug: they will start failing
(as XPASS) the moment the bug is fixed, which is the signal to drop the mark.
"""

import pytest

from rl_scan_artifactory.name_mangler.name_mangler_common import NameManglerCommon

from .conftest import make_file, make_simple


def mangler(
    *,
    uri: str = "/a/foo-1.0.tgz",
    name: str = "foo",
    version: str = "1.0",
    repo_name: str = "my-repo",
    package_type: str = "generic",
) -> NameManglerCommon:
    file = make_file(
        uri=uri,
        repo_name=repo_name,
        package_type=package_type,
        simple=make_simple(name=name, version=version),
    )
    return NameManglerCommon(file=file)


# ---------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ("with:colon", "with0x3Acolon"),
        ("with/slash", "with0x2Fslash"),
        ("with space", "with+space"),
        ("with@at", "with0x40at"),
    ],
)
def test_escape_purl_component(raw: str, expected: str) -> None:
    """No '/' '@' or '%' may survive into a purl component."""
    got = NameManglerCommon._escape_string_for_spectra_assure_purl_component(raw)
    assert got == expected
    assert "/" not in got
    assert "@" not in got
    assert "%" not in got


# ------------------------------------------- connector strip front and back


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("abc", "abc"),
        ("-abc", "abc"),
        ("abc-", "abc"),
        ("_.-abc-._", "abc"),
        ("--abc--", "abc"),
        ("a-b-c", "a-b-c"),
        ("---", ""),
    ],
)
def test_remove_connector_front_and_back(raw: str, expected: str) -> None:
    assert NameManglerCommon._remove_connector_front_and_back(raw) == expected


# ------------------------------------------------------- substring removal


@pytest.mark.parametrize(
    ("str1", "str2", "expected"),
    [
        ("foo-1.0", "foo", "1.0"),
        ("FOO-1.0", "foo", "1.0"),
        ("bar-1.0", "foo", "bar-1.0"),
        ("", "foo", ""),
    ],
)
def test_remove_substring_front(str1: str, str2: str, expected: str) -> None:
    assert mangler()._remove_substring_front(str1, str2) == expected


@pytest.mark.parametrize(
    ("str1", "str2", "expected"),
    [
        ("foo-1.0.tgz", ".tgz", "foo-1.0"),
        ("foo-1.0.TGZ", ".tgz", "foo-1.0"),
        ("foo-1.0.zip", ".tgz", "foo-1.0.zip"),
    ],
)
def test_remove_substring_tail(str1: str, str2: str, expected: str) -> None:
    assert mangler()._remove_substring_tail(str1, str2) == expected


def test_remove_substring_identical_strings_is_empty() -> None:
    assert mangler()._remove_substring("foo", "FOO") == ""


def test_remove_substring_rejects_unknown_mode() -> None:
    with pytest.raises(RuntimeError):
        mangler()._remove_substring("a", "b", "sideways")


@pytest.mark.parametrize("what", ["all", "front", "tail", "mid"])
def test_remove_substring_accepts_documented_modes(what: str) -> None:
    mangler()._remove_substring("aXb", "X", what)


def test_remove_substring_mid_keeps_the_tail() -> None:
    assert mangler()._remove_substring_mid("aaaXXXbbbccc", "XXX") == "aaabbbccc"


def test_remove_substring_mid_only_removes_the_first_occurrence() -> None:
    assert mangler()._remove_substring_mid("aXbXc", "X") == "abXc"


def test_remove_substring_mid_at_position_zero_is_left_alone() -> None:
    """The mid variant deliberately skips a match at position 0 (that is _front's job)."""
    assert mangler()._remove_substring_mid("Xabc", "X") == "Xabc"


# --------------------------------------------------------- _strip_tail


@pytest.mark.parametrize(
    ("str1", "str2", "expected"),
    [
        ("foo.rpm", ".rpm", "foo"),
        ("FOO.RPM", ".rpm", "FOO"),
        ("foo.deb", ".rpm", "foo.deb"),
    ],
)
def test_strip_tail(str1: str, str2: str, expected: str) -> None:
    assert NameManglerCommon._strip_tail(str1, str2) == expected


def test_strip_tail_is_case_insensitive_on_both_sides() -> None:
    assert NameManglerCommon._strip_tail("foo.rpm", ".RPM") == "foo"


# --------------------------------------------------------- _split_release


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        ("1", ("", "1")),
        ("5.fc40", ("fc40", "5")),
        ("100.el9_4.3", ("el9_4", "100.3")),
        ("27.el9.0.2", ("el9", "27.0.2")),
    ],
)
def test_split_release(release: str, expected: tuple[str, str]) -> None:
    """release -> (os/platform tag, release without the platform tag)."""
    assert mangler()._split_release(release=release) == expected


@pytest.mark.parametrize("release", ["1.2", "2.5", "1.2.3.4", "1-2", "1..2"])
def test_split_release_keeps_a_release_with_no_platform_tag(release: str) -> None:
    """Anything matching ^[-0-9.]+$ is a release with no platform part."""
    assert mangler()._split_release(release=release) == ("", release)


@pytest.mark.parametrize("release", ["007", "0", "01.02"])
def test_split_release_preserves_leading_zeros(release: str) -> None:
    """A release is a string, not a number: '007' stays '007'.

    The pre-D5 code returned str(int(release)) here, which turned '007' into '7'
    and would have made two distinct rpm releases collide on one purl version.
    """
    assert mangler()._split_release(release) == ("", release)


@pytest.mark.parametrize("release", ["1..el9", "100..el9_4.3", "1.", ".el9"])
def test_split_release_survives_an_empty_segment(release: str) -> None:
    """An empty segment has no first character to test for a leading digit."""
    os_release, _release2 = mangler()._split_release(release)
    assert isinstance(os_release, str)


# --------------------------------------------------------- _combine_args


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("el9", "x86_64"), "el9_x86_64"),
        (("", "x86_64"), "x86_64"),
        (("el9", ""), "el9"),
        (("", ""), ""),
    ],
)
def test_combine_args_skips_empty_parts(args: tuple[str, ...], expected: str) -> None:
    assert mangler()._combine_args(*args) == expected


# --------------------------------------------------------- construction


def test_constructor_reads_name_and_version_from_simple_data() -> None:
    nm = mangler(name="mypkg", version="2.3.4", repo_name="the-repo")
    assert nm.package == "mypkg"
    assert nm.version == "2.3.4"
    assert nm.project == "the-repo"


def test_constructor_reports_missing_simple_data_clearly() -> None:
    file = make_file(uri="/a/b", simple={})
    with pytest.raises(ValueError, match="simple"):
        NameManglerCommon(file=file)


@pytest.mark.parametrize(
    ("field", "simple"),
    [
        ("name", {"version": ["1.0"]}),  # key absent
        ("version", {"name": ["foo"]}),
        ("name", {"name": [], "version": ["1.0"]}),  # empty list
        ("version", {"name": ["foo"], "version": []}),
        ("name", {"name": [""], "version": ["1.0"]}),  # empty value
        ("version", {"name": ["foo"], "version": [""]}),
    ],
)
def test_constructor_rejects_a_missing_name_or_version(field: str, simple: dict[str, list[str]]) -> None:
    """An empty purl component makes a portal project no later build can match."""
    file = make_file(uri="/a/foo-1.0.tgz", simple=simple)
    with pytest.raises(ValueError, match=field):
        NameManglerCommon(file=file)


def test_the_rejection_names_the_uri() -> None:
    file = make_file(uri="/a/foo-1.0.tgz", simple={"name": ["foo"]})
    with pytest.raises(ValueError, match="/a/foo-1.0.tgz"):
        NameManglerCommon(file=file)


def test_an_empty_version_is_refused_rather_than_mangled() -> None:
    """_mangle_default used to call str.split("") on it; now it never gets there."""
    with pytest.raises(ValueError, match="version"):
        mangler(version="")
