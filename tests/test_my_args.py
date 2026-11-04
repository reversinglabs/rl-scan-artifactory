# python3 ts=4space
"""MyArgs: where the options come from, which combinations are refused, and
the promise that no credential ever reaches the log.

MyArgs reads sys.argv and the environment, so each test sets both explicitly.
Nothing here touches Artifactory or the Portal.
"""

import logging
from typing import (
    Any,
)

import pytest

from rl_scan_artifactory.constants import MY_ENV_NAMES
from rl_scan_artifactory.exceptions import SpectraAssureInvalidAction
from rl_scan_artifactory.my_args import MyArgs

SECRETS: dict[str, str] = {
    "ARTIFACTORY_TOKEN": "SECRET-ARTIFACTORY",
    "RLPORTAL_ACCESS_TOKEN": "SECRET-PORTAL",
    "RLSECURE_SITE_KEY": "SECRET-SITE-KEY",
    "RLSECURE_ENCODED_LICENSE": "SECRET-LICENSE",
    "PROXY_PASSWORD": "SECRET-PROXY-PW",
}

ARTIFACTORY_ENV: dict[str, str] = {
    "ARTIFACTORY_HOST": "https://artifactory.example.com",
    "ARTIFACTORY_USER": "admin",
    "ARTIFACTORY_TOKEN": SECRETS["ARTIFACTORY_TOKEN"],
}

PORTAL_ENV: dict[str, str] = {
    "RLPORTAL_HOST": "https://my.secure.software",
    "RLPORTAL_SERVER": "test",
    "RLPORTAL_ORG": "Test",
    "RLPORTAL_GROUP": "testGroup",
    "RLPORTAL_ACCESS_TOKEN": SECRETS["RLPORTAL_ACCESS_TOKEN"],
}

PORTAL_ARGV: list[str] = ["rl-scan-artifactory", "--portal", "--repo", "my-repo"]

# each of these is needed on its own; the host and the server stand in for each other
PORTAL_REQUIRED: list[str] = ["RLPORTAL_ACCESS_TOKEN", "RLPORTAL_GROUP", "RLPORTAL_ORG"]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from no environment at all, so a developer's own shell cannot leak in."""
    for name in MY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def build(
    monkeypatch: pytest.MonkeyPatch,
    *,
    argv: list[str],
    env: dict[str, str] | None = None,
) -> Any:
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", argv)
    return MyArgs()


# ------------------------------------------------------- where options come from


def test_the_environment_supplies_an_option(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(monkeypatch, argv=PORTAL_ARGV, env={**ARTIFACTORY_ENV, **PORTAL_ENV})
    assert args.cli_args["artifactory_host"] == "https://artifactory.example.com"


def test_the_command_line_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(
        monkeypatch,
        argv=[*PORTAL_ARGV, "--artifactory-host", "https://from-the-cli.example.com"],
        env={**ARTIFACTORY_ENV, **PORTAL_ENV},
    )
    assert args.cli_args["artifactory_host"] == "https://from-the-cli.example.com"


def test_every_env_name_becomes_an_option(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(monkeypatch, argv=PORTAL_ARGV, env={**ARTIFACTORY_ENV, **PORTAL_ENV})
    for name in MY_ENV_NAMES:
        assert name.lower() in args.cli_args, name


# ------------------------------------------------------------ refused combinations


def test_neither_portal_nor_cli_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    with pytest.raises(SpectraAssureInvalidAction):
        build(
            monkeypatch,
            argv=["rl-scan-artifactory", "--repo", "my-repo"],
            env={**ARTIFACTORY_ENV, **PORTAL_ENV},
        )


def test_both_portal_and_cli_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    with pytest.raises(SpectraAssureInvalidAction):
        build(
            monkeypatch,
            argv=["rl-scan-artifactory", "--portal", "--cli", "--repo", "my-repo"],
            env={**ARTIFACTORY_ENV, **PORTAL_ENV},
        )


def test_no_repository_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """--repo is required by the parser, so this is argparse's own exit 2."""
    with pytest.raises(SystemExit) as excinfo:
        build(monkeypatch, argv=["rl-scan-artifactory", "--portal"], env={**ARTIFACTORY_ENV, **PORTAL_ENV})
    assert excinfo.value.code == 2


# ------------------------------------------------ mandatory settings
# Checked after every source of options has been read, so one run reports every
# missing setting at once instead of one per attempt.


@pytest.mark.parametrize("missing", sorted(ARTIFACTORY_ENV) + PORTAL_REQUIRED)
def test_a_missing_mandatory_setting_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    missing: str,
) -> None:
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV}
    del env[missing]

    with pytest.raises(SpectraAssureInvalidAction, match="missing mandatory setting"):
        build(monkeypatch, argv=PORTAL_ARGV, env=env)


@pytest.mark.parametrize("missing", sorted(ARTIFACTORY_ENV) + PORTAL_REQUIRED)
def test_the_refusal_names_the_missing_setting_and_how_to_supply_it(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    missing: str,
) -> None:
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV}
    del env[missing]

    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        build(monkeypatch, argv=PORTAL_ARGV, env=env)

    message = str(excinfo.value)
    assert missing.lower() in message  # the cli_args key
    assert missing in message  # the environment variable
    assert "--" + missing.lower().replace("_", "-") in message  # the option


@pytest.mark.parametrize("left_out", ["RLPORTAL_HOST", "RLPORTAL_SERVER"])
def test_the_portal_host_or_the_server_alone_is_enough(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    left_out: str,
) -> None:
    """A server alone means my.secure.software/<server>; a host alone is a dedicated portal."""
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV}
    del env[left_out]

    args = build(monkeypatch, argv=PORTAL_ARGV, env=env)
    assert args.cli_args[left_out.lower()] is None


def test_a_portal_run_without_host_and_server_is_refused_naming_both(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV}
    del env["RLPORTAL_HOST"]
    del env["RLPORTAL_SERVER"]

    with pytest.raises(SpectraAssureInvalidAction, match="missing mandatory setting") as excinfo:
        build(monkeypatch, argv=PORTAL_ARGV, env=env)

    message = str(excinfo.value)
    for name in ("RLPORTAL_HOST", "RLPORTAL_SERVER", "--rlportal-host", "--rlportal-server"):
        assert name in message


def test_every_missing_setting_is_reported_at_once(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """Finding out one variable at a time costs a round trip each."""
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV}
    for name in ("ARTIFACTORY_TOKEN", "RLPORTAL_ORG", "RLPORTAL_ACCESS_TOKEN"):
        del env[name]

    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        build(monkeypatch, argv=PORTAL_ARGV, env=env)

    message = str(excinfo.value)
    for name in ("artifactory_token", "rlportal_org", "rlportal_access_token"):
        assert name in message


def test_the_refusal_does_not_echo_a_secret_value(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """A missing setting is named; the ones that are present stay out of the message."""
    env = {**ARTIFACTORY_ENV, **PORTAL_ENV, **SECRETS}
    del env["RLPORTAL_ORG"]

    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        build(monkeypatch, argv=PORTAL_ARGV, env=env)

    for value in SECRETS.values():
        assert value not in str(excinfo.value)


def test_a_portal_setting_is_not_mandatory_in_cli_mode(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(
        monkeypatch,
        argv=[
            "rl-scan-artifactory",
            "--cli",
            "--repo",
            "my-repo",
            "--cli-rlstore-path",
            "/opt/rl-store",
            "--cli-rlsecure-path",
            "/opt/rl-secure",
        ],
        env=ARTIFACTORY_ENV,
    )
    assert args.cli_args["cli"] is True


@pytest.mark.parametrize("missing", ["--cli-rlstore-path", "--cli-rlsecure-path"])
def test_cli_mode_needs_the_rl_secure_paths(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    missing: str,
) -> None:
    argv = [
        "rl-scan-artifactory",
        "--cli",
        "--repo",
        "my-repo",
        "--cli-rlstore-path",
        "/opt/rl-store",
        "--cli-rlsecure-path",
        "/opt/rl-secure",
    ]
    index = argv.index(missing)
    del argv[index : index + 2]

    with pytest.raises(SpectraAssureInvalidAction, match="missing mandatory setting"):
        build(monkeypatch, argv=argv, env=ARTIFACTORY_ENV)


def test_cli_docker_needs_a_license_instead_of_the_paths(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        build(
            monkeypatch,
            argv=["rl-scan-artifactory", "--cli-docker", "--repo", "my-repo"],
            env=ARTIFACTORY_ENV,
        )

    message = str(excinfo.value)
    assert "rlsecure_encoded_license" in message
    assert "rlsecure_site_key" in message
    assert "cli_rlstore_path" not in message


def test_a_tool_that_chose_no_backend_needs_only_artifactory(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """show_artifacts_status_fail.py and the cleanup tools read artifactory only."""
    monkeypatch.setattr("sys.argv", ["show_artifacts_status_fail"])
    for name, value in ARTIFACTORY_ENV.items():
        monkeypatch.setenv(name, value)

    args = MyArgs(repo_list_may_be_empty=True, no_portal_or_cli=True)
    assert args.cli_args["artifactory_host"] == ARTIFACTORY_ENV["ARTIFACTORY_HOST"]


# --------------------------------------------------------------- derived options


def test_sync_forces_artifactory_properties_to_be_ignored(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """A re-scan must not be skipped because a property says it was already done."""
    args = build(
        monkeypatch,
        argv=[*PORTAL_ARGV, "--sync"],
        env={**ARTIFACTORY_ENV, **PORTAL_ENV},
    )
    assert args.cli_args["ignore_artifactory_properties"] is True


def test_without_sync_artifactory_properties_are_honoured(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(monkeypatch, argv=PORTAL_ARGV, env={**ARTIFACTORY_ENV, **PORTAL_ENV})
    assert args.cli_args["ignore_artifactory_properties"] is False


@pytest.mark.parametrize(("flag", "expected"), [([], False), (["--keep-obsolete-properties"], True)])
def test_obsolete_properties_are_removed_unless_kept(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    flag: list[str],
    expected: bool,
) -> None:
    """Removing them is the default (R10.9)."""
    args = build(monkeypatch, argv=[*PORTAL_ARGV, *flag], env={**ARTIFACTORY_ENV, **PORTAL_ENV})
    assert args.cli_args["keep_obsolete_properties"] is expected


def test_repositories_are_a_list(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    args = build(
        monkeypatch,
        argv=["rl-scan-artifactory", "--portal", "--repo", "one", "--repo", "two"],
        env={**ARTIFACTORY_ENV, **PORTAL_ENV},
    )
    assert args.cli_args["repo"] == ["one", "two"]


# ------------------------------------------------------------------- no leaks
# The log file is always written, and a DEBUG run is exactly what someone
# attaches to a support ticket.


def test_no_credential_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        build(
            monkeypatch,
            argv=[*PORTAL_ARGV, "--proxy-server", "p.example.com", "--proxy-port", "3128"],
            env={**ARTIFACTORY_ENV, **PORTAL_ENV, **SECRETS},
        )

    for name, value in SECRETS.items():
        assert value not in caplog.text, name


def test_the_log_still_shows_the_non_secret_settings(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redaction must not make the debug line useless."""
    with caplog.at_level(logging.DEBUG):
        build(monkeypatch, argv=PORTAL_ARGV, env={**ARTIFACTORY_ENV, **PORTAL_ENV, **SECRETS})

    assert "artifactory.example.com" in caplog.text
    assert "my-repo" in caplog.text


def test_the_secrets_are_still_available_to_the_program(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """Redaction is for rendering only; cli_args itself must keep the real values."""
    args = build(monkeypatch, argv=PORTAL_ARGV, env={**ARTIFACTORY_ENV, **PORTAL_ENV, **SECRETS})
    assert args.cli_args["artifactory_token"] == SECRETS["ARTIFACTORY_TOKEN"]
    assert args.cli_args["rlportal_access_token"] == SECRETS["RLPORTAL_ACCESS_TOKEN"]


# ------------------------------------------------------- the repository list
# --repo may be given any number of times, and each occurrence may itself be a
# comma separated list. An artifactory repository name has no spaces and no
# punctuation beyond '-' and '_', so a typo is refused here rather than turning
# into a REPO SKIP later that looks like the repository is missing.


def repos(value: Any, *, may_be_empty: bool = True) -> list[str]:
    args: Any = MyArgs.__new__(MyArgs)
    args.repo_list_may_be_empty = may_be_empty

    result: list[str] = args.mandatory_repo({"repo": value})
    return result


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (["a", "b"], ["a", "b"]),  # --repo a --repo b
        (["a,b"], ["a", "b"]),  # --repo a,b
        (["a,b", "c"], ["a", "b", "c"]),  # both at once
        ([["a", "b"], "c"], ["a", "b", "c"]),  # argparse can nest them
    ],
)
def test_the_ways_of_naming_repositories_agree(given: Any, expected: list[str]) -> None:
    assert repos(given) == expected


def test_the_order_given_is_kept() -> None:
    assert repos(["c,a", "b"]) == ["c", "a", "b"]


def test_a_repository_named_twice_appears_once() -> None:
    assert repos(["a", "b", "a", "b,a"]) == ["a", "b"]


@pytest.mark.parametrize("given", [None, [], [""], [","], [",,"]])
def test_nothing_usable_gives_an_empty_list(given: Any) -> None:
    assert repos(given) == []


# --------------------------------------------------- what used to slip through


def test_surrounding_space_is_removed() -> None:
    """'--repo "a, b"' is natural to type and used to give a repository called ' b'."""
    assert repos(["a, b"]) == ["a", "b"]


@pytest.mark.parametrize("given", [["a,,b"], ["a,"], [",a"]])
def test_an_empty_name_is_dropped(given: list[str]) -> None:
    """These used to produce '' in the list, which was then looked up."""
    assert "" not in repos(given)
    assert repos(given) == ["a"] or repos(given) == ["a", "b"]


# ------------------------------------------------------------ what is refused


@pytest.mark.parametrize(
    "name",
    ["my repo", "a/b", "a:b", "a@b", "a%b", "a+b", "repo!", "réps"],
)
def test_a_name_artifactory_cannot_have_is_refused(name: str) -> None:
    with pytest.raises(SpectraAssureInvalidAction, match="not a repository name"):
        repos([name])


@pytest.mark.parametrize(
    "name",
    [
        "a",
        "A",
        "9",
        "my-repo",
        "my_repo",
        "my-repo_2",
        "A-B_c9",
        "0123456789",
        "7-zip",
        "a.b.c.d",
    ],
)
def test_a_legal_name_is_accepted(name: str) -> None:
    assert repos([name]) == [name]


@pytest.mark.parametrize(
    "name",
    ["nmpjs.org", "npmjs.org", "maven2-dev", "docker-local", "Spectra-Assure-Reports", "rubygems-1"],
)
def test_the_repository_names_actually_in_use_are_accepted(name: str) -> None:
    """A proxying repository is often named after what it proxies, dots and all."""
    assert repos([name]) == [name]


def test_the_only_refused_names_are_the_two_path_segments() -> None:
    """Artifactory is permissive: 'jjj.....kkk' is a legal repository name.

    So only '.' and '..' are refused, and only because they are a path segment
    rather than a name. A dot run inside a name cannot climb anywhere, because
    '/' is not in the pattern.
    """
    for name in (".", ".."):
        with pytest.raises(SpectraAssureInvalidAction, match="not a repository name"):
            repos([name])


@pytest.mark.parametrize(
    "name",
    [
        "a..b",
        "jjj.....kkk",
        "...x",
        "x...",
        ".hidden",
        "-leading",
        "_x",
        "_hshshs____----....mmmm",
        "-",
        "_",
        ".-_",
        "0",
    ],
)
def test_a_name_artifactory_accepts_is_accepted(name: str) -> None:
    """Checked against a real artifactory: these are all legal, however they look.

    The rule is deliberately no stricter than artifactory itself. A validator that
    invents constraints rejects legitimate input, which is worse than not
    validating: the run stops on a name that would have worked.
    """
    assert repos([name]) == [name]


def test_every_bad_name_is_reported_at_once() -> None:
    with pytest.raises(SpectraAssureInvalidAction) as excinfo:
        repos(["ok", "a b", "c/d"])

    message = str(excinfo.value)
    assert "a b" in message
    assert "c/d" in message
    assert "ok" not in message


def test_the_refusal_says_what_is_allowed() -> None:
    with pytest.raises(SpectraAssureInvalidAction, match="letters, digits"):
        repos(["a b"])


# ---------------------------------------------------------- the empty list


def test_an_empty_list_is_refused_when_one_is_required() -> None:
    """argparse requires --repo, so this is the belt to that braces."""
    with pytest.raises(SystemExit) as excinfo:
        repos([], may_be_empty=False)
    assert excinfo.value.code == 2


def test_a_tool_that_allows_no_repositories_gets_an_empty_list() -> None:
    assert repos([], may_be_empty=True) == []
