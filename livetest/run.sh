#! /bin/bash
# Run the live tests on a machine with rl-secure (and docker for d1/d2),
# against this checkout. Rerun after each development step.
#
#   ./run.sh all            setup c1 c2 age c3 age d1 d2 p1 p2, then the summary
#   ./run.sh c1 c2          only these steps (each one is checked right away)
#   ./run.sh check          check every step that has results again
#   ./run.sh cleanup        delete the test folder in Artifactory (asks)
#
# Steps (README.md has the expected result per item):
#   setup  upload the items a..g          c1  first cli run
#   c2     cli --sync                     age RL.timestamp 30 days back (+ g1)
#   c3     cli, automatic sync            d1  cli-docker, no -I (never syncs)
#   d2     cli-docker -I with a store     p1  portal -I
#   p2     portal -I without RLPORTAL_HOST: RLPORTAL_SERVER alone (R12.5.1.1)
#
# Gradle (R4.1.7), in its own repository GREPO; not part of 'all':
#   ./run.sh gradle         gsetup g1 g2 g3, then their summary
#   gsetup  upload the gradle items       g1  cli
#   g2      cli --sync                    g3  portal -I
#   gcleanup  delete the gradle test folder (asks)
#
# Settings (environment):
#   CHECKOUT      the rl-scan-artifactory checkout to run   (default: the one holding livetest/)
#   REPO          generic local test repository             (default: rl-live-generic)
#   GREPO         gradle local test repository              (default: rl-live-gradle)
#                 with the default layout maven-2-default
#   CLI_HOME      rl-secure install dir and cli store       (default: $HOME/tmp/rl-secure, as Makefile.test)
#   DOCKER_STORE  store for cli-docker                      (default: $HOME/tmp/rl-store-live-docker, new)
#                 DOCKER_STORE=$HOME/tmp/rl-secure reuses the cli store instead
#   ENV_FILE / ENV_FILE_PORTAL                              (default: ~/.env_cli / ~/.env_portal)
#   DIR           test folder in REPO                       (default: live-test; DIR=live-1.2.0 for
#                 items an older kit set up)
#   PYTHON        python 3.11 or newer                      (default: python3)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/live.env"

CHECKOUT="${CHECKOUT:-$(cd "${HERE}/.." && pwd)}"
CLI_HOME="${CLI_HOME:-${HOME}/tmp/rl-secure}"
DOCKER_STORE="${DOCKER_STORE:-${HOME}/tmp/rl-store-live-docker}"
ENV_FILE_PORTAL="${ENV_FILE_PORTAL:-${HOME}/.env_portal}"
PYTHON="${PYTHON:-python3}"
RESULTS="${HERE}/work/results"
VENV="${HERE}/work/venv"

[ -f "${CHECKOUT}/rl-scan-artifactory-dev.py" ] || die "no checkout at ${CHECKOUT}; set CHECKOUT="

venv() {
    [ -x "${VENV}/bin/python" ] && return
    "${PYTHON}" -m venv "${VENV}" || die "cannot make a venv with ${PYTHON}"
    "${VENV}/bin/pip" -q --disable-pip-version-check install -r "${CHECKOUT}/requirements.txt" || die "pip install failed"
}

# run_tool <step> <env file> <options...>: the program, in results/<step>.
# UNSET_VARS: names removed after the env file is read (recorded in env.txt);
# REQUIRE_VARS: names the env file must set for this step.
run_tool() {
    local step="$1" env_file="$2"
    shift 2
    local dir="${RESULTS}/${step}"
    rm -rf "${dir}"
    mkdir -p "${dir}/download"
    venv
    echo "=== ${step}: $(cd "${CHECKOUT}" && git log --oneline -1)"
    (
        cd "${dir}" || exit 1
        # shellcheck disable=SC1090
        source "${env_file}"
        for v in ${REQUIRE_VARS:-}; do
            if [ -z "${!v:-}" ]; then
                echo "ERROR: ${v} is not set in ${env_file}, needed for step ${step}" >&2
                echo 2 >"${dir}/exit"
                exit 1
            fi
        done
        for v in ${UNSET_VARS:-}; do
            if [ -n "${!v:-}" ]; then
                echo "${v}: set in the env file, unset for this step" >>"${dir}/env.txt"
            else
                echo "${v}: not set in the env file" >>"${dir}/env.txt"
            fi
            unset "${v}"
        done
        export LOG_LEVEL=DEBUG WITH_TEST_LIMIT_REPO_TO=0
        "${VENV}/bin/python" "${CHECKOUT}/rl-scan-artifactory-dev.py" \
            --verbose --log-to-stderr --pack-safe --ignore-cert-errors \
            --download="${dir}/download" --repo "${REPO}" "$@" \
            >"${dir}/out.txt" 2>"${dir}/err.txt"
        echo $? >"${dir}/exit"
    )
    mv "${dir}/rl-scan-artifactory-dev.log" "${dir}/run.log" 2>/dev/null
    rm -rf "${dir}/download"
    "${HERE}/20-show.sh" >"${dir}/props.txt" 2>&1
    echo "exit $(cat "${dir}/exit"); output in ${dir}"
    DIR="${DIR}" GREPO="${GREPO}" GDIR="${GDIR}" "${PYTHON}" "${HERE}/check.py" "${RESULTS}" "${REPO}" "${step}" || true
}

CLI=(--cli --cli-rlsecure-path="${CLI_HOME}" --cli-rlstore-path="${CLI_HOME}"
    --cli-reports-repo=Spectra-Assure-Reports --cli-report-types=all)
DOCKER=(--cli-docker --cli-reports-repo=Spectra-Assure-Reports --cli-report-types=all)

# gradle_env <command...>: the command with REPO and DIR set to the gradle ones,
# exported so 20-show.sh and 90-cleanup.sh (which read live.env again) see them
gradle_env() (
    export REPO="${GREPO}" DIR="${GDIR}"
    "$@"
)

docker_store() {
    command -v docker >/dev/null || die "docker is not installed here"
    # docker would create a missing bind-mount source owned by root, and the
    # scanner runs as this user: make it first
    mkdir -p "${DOCKER_STORE}"
    echo "cli-docker store: ${DOCKER_STORE}"
}

step() {
    case "$1" in
    setup) "${HERE}/10-setup.sh" ;;
    c1) run_tool c1 "${ENV_FILE}" "${CLI[@]}" ;;
    c2) run_tool c2 "${ENV_FILE}" "${CLI[@]}" --sync ;;
    age) "${HERE}/30-age.sh" ;;
    c3) run_tool c3 "${ENV_FILE}" "${CLI[@]}" ;;
    d1) docker_store && run_tool d1 "${ENV_FILE}" "${DOCKER[@]}" ;;
    d2) docker_store && run_tool d2 "${ENV_FILE}" "${DOCKER[@]}" --cli-rlstore-path="${DOCKER_STORE}" -I ;;
    p1) run_tool p1 "${ENV_FILE_PORTAL}" --portal -I ;;
    p2) UNSET_VARS=RLPORTAL_HOST REQUIRE_VARS=RLPORTAL_SERVER run_tool p2 "${ENV_FILE_PORTAL}" --portal -I ;;
    gsetup) "${HERE}/40-gradle-setup.sh" ;;
    g1) gradle_env run_tool g1 "${ENV_FILE}" "${CLI[@]}" ;;
    g2) gradle_env run_tool g2 "${ENV_FILE}" "${CLI[@]}" --sync ;;
    g3) gradle_env run_tool g3 "${ENV_FILE_PORTAL}" --portal -I ;;
    gcleanup) gradle_env "${HERE}/90-cleanup.sh" ;;
    check) DIR="${DIR}" GREPO="${GREPO}" GDIR="${GDIR}" "${PYTHON}" "${HERE}/check.py" "${RESULTS}" "${REPO}" ;;
    cleanup) "${HERE}/90-cleanup.sh" ;;
    all) for s in setup c1 c2 age c3 age d1 d2 p1 p2; do step "${s}" || die "step ${s} failed"; done
        step check ;;
    gradle) for s in gsetup g1 g2 g3; do step "${s}" || die "step ${s} failed"; done
        DIR="${DIR}" GREPO="${GREPO}" GDIR="${GDIR}" "${PYTHON}" "${HERE}/check.py" "${RESULTS}" "${REPO}" g1 g2 g3 ;;
    *) die "unknown step '$1'; see the top of $0" ;;
    esac
}

[ $# -gt 0 ] || die "usage: $0 all | gradle | setup c1 c2 age c3 d1 d2 p1 p2 gsetup g1 g2 g3 check cleanup gcleanup"
for s in "$@"; do step "${s}" || die "step ${s} failed"; done
