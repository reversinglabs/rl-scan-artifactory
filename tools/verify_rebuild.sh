#! /bin/bash
# ==================================================
# Verify, against a live Artifactory (and Spectra Assure Portal), that an
# artifact rebuilt and redeployed under the same path is scanned again
# (R10.7.5, R10.8, A.21, A.22 in DECISIONS.md).
#
# For each case - a pypi wheel (the default processor) and a generic file with
# its .rl_meta side-car - it:
#
#   1. deploys version 1 of the bytes and runs the scanner
#      -> RL.progress=scanned, RL.sha256 = sha256 of version 1
#   2. rebuilds the bytes, redeploys them to the same path
#      (generic: only the described file, the side-car is left alone)
#      -> reports whether artifactory KEPT or DROPPED the RL.* properties
#   3. runs the scanner again, an ordinary run
#      -> processed again, RL.sha256 = sha256 of version 2;
#         portal: the version is replaced, not refused with a 409
#   4. runs the scanner again
#      -> skipped: nothing changed, RL.timestamp is untouched
#   5. portal only: runs with --ignore-artifactory-properties
#      -> the portal now holds the bytes of version 2 (no digest mismatch)
#
# Requirements:
#   - a dedicated LOCAL pypi repository and a dedicated LOCAL generic repository:
#     every run of the scanner processes the whole repository
#   - an artifactory user that may deploy, delete and set properties there
#   - curl, python3, and rl-scan-artifactory importable by python3
#     (e.g. a venv with `pip install -e .` from this checkout, activated)
#
# Every artifact gets a fresh version (0.0.<epoch>), so the script can be run
# again; it deletes what it deployed unless KEEP=1. The scanner logs of each run
# are kept in ./verify-rebuild/<date>-<time>.<id>/ (VERIFY_WORK_DIR). The portal versions it made
# stay: tools/cleanup_portal_projects.py removes them.
# ==================================================

set -u -o pipefail

# ----- configuration: environment, or ~/.env_testing like doc/example_*.sh

[ -f ~/.env_testing ] && {
    source ~/.env_testing
}

ARTIFACTORY_HOST="${ARTIFACTORY_HOST:-}"
ARTIFACTORY_USER="${ARTIFACTORY_USER:-}"
ARTIFACTORY_TOKEN="${ARTIFACTORY_TOKEN:-}"

VERIFY_PYPI_REPO="${VERIFY_PYPI_REPO:-test-pypi-local}"       # local pypi repo, dedicated to this test
VERIFY_GENERIC_REPO="${VERIFY_GENERIC_REPO:-test-generic-local}" # local generic repo, dedicated to this test
VERIFY_BACKEND="${VERIFY_BACKEND:-portal}"     # portal | cli
VERIFY_CASES="${VERIFY_CASES:-pypi generic}"   # which of the two to run
VERIFY_WAITTIME="${VERIFY_WAITTIME:-30}"       # --waittime for the scanner, minutes
VERIFY_INSECURE="${VERIFY_INSECURE:-1}"        # 1: self-signed artifactory cert
KEEP="${KEEP:-0}"                              # 1: leave the deployed artifacts

# how to start the scanner; the default runs this checkout
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# one directory per run below this, with the scanner logs; not ./tmp, which
# `make clean` removes
VERIFY_WORK_DIR="${VERIFY_WORK_DIR:-${HERE}/verify-rebuild}"
SCANNER="${SCANNER:-python3 ${HERE}/rl-scan-artifactory-dev.py}"

# portal: RLPORTAL_SERVER, RLPORTAL_ORG, RLPORTAL_GROUP, RLPORTAL_ACCESS_TOKEN
# cli:    RL_STORE_PATH, RL_SECURE_PATH
RL_STORE_PATH="${RL_STORE_PATH:-}"
RL_SECURE_PATH="${RL_SECURE_PATH:-}"

export LOG_LEVEL="INFO" # the rebuild and the replace are logged at info

# ----- results

PASSED=0
FAILED=0
NOTES=()

pass() {
    echo "  PASS  $*"
    PASSED=$((PASSED + 1))
}

fail() {
    echo "  FAIL  $*"
    FAILED=$((FAILED + 1))
}

note() {
    echo "  NOTE  $*"
    NOTES+=("$*")
}

die() {
    echo "ERROR: $*" >&2
    exit 2
}

expect_eq() { # what, expected, actual
    if [ "$2" == "$3" ]; then
        pass "$1: ${3}"
    else
        fail "$1: expected '${2}', got '${3}'"
    fi
}

expect_in_log() { # log, pattern, what
    if grep -q -- "$2" "$1"; then
        pass "$3"
    else
        fail "$3 (no '$2' in $(basename "$1"))"
    fi
}

expect_not_in_log() { # log, pattern, what
    if grep -q -- "$2" "$1"; then
        fail "$3 (found '$2' in $(basename "$1"))"
    else
        pass "$3"
    fi
}

# ----- preflight

check_config() {
    local missing=()
    for v in ARTIFACTORY_HOST ARTIFACTORY_USER ARTIFACTORY_TOKEN; do
        [ -z "${!v}" ] && missing+=("$v")
    done

    for c in ${VERIFY_CASES}; do
        case "$c" in
        pypi) [ -z "${VERIFY_PYPI_REPO}" ] && missing+=(VERIFY_PYPI_REPO) ;;
        generic) [ -z "${VERIFY_GENERIC_REPO}" ] && missing+=(VERIFY_GENERIC_REPO) ;;
        *) die "unknown case in VERIFY_CASES: $c (pypi, generic)" ;;
        esac
    done

    case "${VERIFY_BACKEND}" in
    portal)
        for v in RLPORTAL_SERVER RLPORTAL_ORG RLPORTAL_GROUP RLPORTAL_ACCESS_TOKEN; do
            [ -z "${!v:-}" ] && missing+=("$v")
        done
        ;;
    cli)
        for v in RL_STORE_PATH RL_SECURE_PATH; do
            [ -z "${!v}" ] && missing+=("$v")
        done
        ;;
    *) die "VERIFY_BACKEND must be portal or cli, not ${VERIFY_BACKEND}" ;;
    esac

    [ "${#missing[@]}" -gt 0 ] && die "not set: ${missing[*]}"

    command -v curl >/dev/null || die "curl is needed"
    command -v python3 >/dev/null || die "python3 is needed"
    local out
    out=$(${SCANNER} --version 2>&1) || die "cannot run the scanner: ${SCANNER}
  $(echo "${out}" | tail -1)
  run this from a venv with rl-scan-artifactory and its dependencies installed
  (pip install -e .), or point SCANNER at that venv's python"
}

# ----- artifactory

CURL=(curl -s -u "${ARTIFACTORY_USER}:${ARTIFACTORY_TOKEN}")
[ "${VERIFY_INSECURE}" == "1" ] && CURL+=(--insecure)
BASE="https://${ARTIFACTORY_HOST}/artifactory"

sha256_of() {
    sha256sum "$1" | cut -d' ' -f1
}

deploy() { # repo, path, file
    local code
    code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X PUT \
        -H "X-Checksum-Sha256: $(sha256_of "$3")" \
        -T "$3" "${BASE}/$1/$2")
    [ "${code}" == "201" ] || [ "${code}" == "200" ] || die "deploy of $1/$2 answered ${code}"
}

delete_path() { # repo, path
    "${CURL[@]}" -o /dev/null -X DELETE "${BASE}/$1/$2"
}

# one property of one item, or "" when it has none
prop() { # repo, path, key
    "${CURL[@]}" "${BASE}/api/storage/$1/$2?properties" |
        python3 -c '
import json, sys
try:
    props = json.load(sys.stdin).get("properties", {})
except ValueError:
    props = {}
print((props.get(sys.argv[1]) or [""])[0])
' "$3"
}

# artifactory sets pypi.name and pypi.version once it has indexed the wheel;
# without them the scanner has no purl for it
wait_for_prop() { # repo, path, key
    local i
    for i in $(seq 1 30); do
        [ -n "$(prop "$1" "$2" "$3")" ] && return 0
        sleep 2
    done
    die "artifactory did not set $3 on $1/$2 within 60s"
}

# ----- the artifacts

NAME="rl-verify-rebuild"
VERSION="" # set in main: 0.0.<epoch>
WORK=""    # set in main: a fresh temp dir

# a minimal valid wheel; the build marker makes each build other bytes
make_wheel() { # out_dir, build_marker -> prints the file name
    python3 - "$1" "${NAME}" "${VERSION}" "$2" <<'EOF'
import base64, hashlib, sys, zipfile

out_dir, name, version, marker = sys.argv[1:]
dist = name.replace("-", "_")
info = f"{dist}-{version}.dist-info"
files = {
    f"{dist}/__init__.py": f'BUILD = "{marker}"\n',
    f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nSummary: rl-scan-artifactory rebuild verification\n",
    f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: verify_rebuild.sh\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
}

def record_line(path, data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"

record = [record_line(p, d.encode()) for p, d in files.items()] + [f"{info}/RECORD,,"]
files[f"{info}/RECORD"] = "\n".join(record) + "\n"

wheel = f"{dist}-{version}-py3-none-any.whl"
with zipfile.ZipFile(f"{out_dir}/{wheel}", "w", zipfile.ZIP_DEFLATED) as z:
    for path, data in files.items():
        z.writestr(path, data)
print(wheel)
EOF
}

make_generic() { # out_dir, build_marker -> prints the file name
    local file="${NAME}-${VERSION}.bin"
    printf 'rl-scan-artifactory rebuild verification\nbuild: %s\n' "$2" >"$1/${file}"
    head -c 4096 /dev/urandom >>"$1/${file}"
    echo "${file}"
}

# no sha256 in the side-car: the rebuild redeploys only the described file, and
# a declared digest would then (rightly) fail the download check
make_side_car() { # out_dir, described file name -> prints the side-car name
    cat >"$1/$2.rl_meta" <<EOF
[rl_meta]
namespace =
name = ${NAME}
version = ${VERSION}
architecture =
path = $2
EOF
    echo "$2.rl_meta"
}

# ----- the scanner

RUN=0
LOG=""    # the log of the last run
STATUS="" # the exit code of the last run

# not called as $(scan): in a subshell RUN would never count up, and every run
# would overwrite the log of the one before
scan() { # extra args... -> sets LOG and STATUS
    RUN=$((RUN + 1))
    LOG="${WORK}/run-${RUN}.log"
    local backend=()

    case "${VERIFY_BACKEND}" in
    portal) backend=(--portal) ;;
    cli) backend=(--cli "--cli-rlstore-path=${RL_STORE_PATH}" "--cli-rlsecure-path=${RL_SECURE_PATH}") ;;
    esac

    [ "${VERIFY_INSECURE}" == "1" ] && backend+=(--ignore-cert-errors)

    mkdir -p "${WORK}/download"
    (
        cd "${WORK}" &&
            ${SCANNER} --verbose --log-to-stderr \
                "${backend[@]}" \
                --waittime "${VERIFY_WAITTIME}" \
                --download "${WORK}/download" \
                "$@" \
                --repo "${REPO}"
    ) >"${LOG}" 2>&1
    STATUS=$?
}

# the scanner exits 0 when every item was processed; anything else is shown,
# with the end of its log, because nothing after it can be trusted
expect_clean_run() {
    if [ "${STATUS}" == "0" ]; then
        pass "the scanner finished cleanly ($(basename "${LOG}"))"
        return 0
    fi

    fail "the scanner exited with ${STATUS}: the end of ${LOG}"
    tail -20 "${LOG}" | sed 's/^/        | /'
    return 1
}

# ----- one case

verify_case() { # case
    local c="$1" repo dir file side_car="" sha_v1 sha_v2 progress stamp

    echo
    echo "== ${c}: ${VERIFY_BACKEND} backend"

    dir="${NAME}/${VERSION}"
    mkdir -p "${WORK}/v1" "${WORK}/v2"

    case "$c" in
    pypi)
        repo="${VERIFY_PYPI_REPO}"
        file=$(make_wheel "${WORK}/v1" "v1")
        make_wheel "${WORK}/v2" "v2" >/dev/null
        ;;
    generic)
        repo="${VERIFY_GENERIC_REPO}"
        file=$(make_generic "${WORK}/v1" "v1")
        make_generic "${WORK}/v2" "v2" >/dev/null
        side_car=$(make_side_car "${WORK}/v1" "${file}")
        ;;
    esac

    REPO="${repo}" # the scanner processes only the repository of this case
    sha_v1=$(sha256_of "${WORK}/v1/${file}")
    sha_v2=$(sha256_of "${WORK}/v2/${file}")
    [ "${sha_v1}" != "${sha_v2}" ] || die "the two builds are the same bytes"

    echo "  ${repo}/${dir}/${file}"
    echo "  v1 ${sha_v1}"
    echo "  v2 ${sha_v2}"

    # -- 1. version 1, first scan
    deploy "${repo}" "${dir}/${file}" "${WORK}/v1/${file}"
    [ -n "${side_car}" ] && deploy "${repo}" "${dir}/${side_car}" "${WORK}/v1/${side_car}"
    [ "$c" == "pypi" ] && wait_for_prop "${repo}" "${dir}/${file}" "pypi.version"

    echo "-- run 1: first scan of v1"
    scan
    expect_clean_run
    progress=$(prop "${repo}" "${dir}/${file}" RL.progress)
    expect_eq "RL.progress on the artifact" "scanned" "${progress}"
    expect_eq "RL.sha256 on the artifact" "${sha_v1}" "$(prop "${repo}" "${dir}/${file}" RL.sha256)"
    if [ -n "${side_car}" ]; then
        expect_eq "RL.progress on the side-car" "scanned" "$(prop "${repo}" "${dir}/${side_car}" RL.progress)"
        expect_eq "RL.sha256 on the side-car" "${sha_v1}" "$(prop "${repo}" "${dir}/${side_car}" RL.sha256)"
    fi

    # without a scan of v1 there is nothing a rebuild can be compared with, and
    # every check after this would pass or fail for the wrong reason
    if [ "${STATUS}" != "0" ] || [ "${progress}" != "scanned" ]; then
        fail "${c}: v1 was not scanned, so the rebuild cannot be verified; stopping this case"
        cleanup_case "${repo}" "${dir}"
        return
    fi

    # -- 2. rebuild, redeploy the same path
    deploy "${repo}" "${dir}/${file}" "${WORK}/v2/${file}"
    [ "$c" == "pypi" ] && wait_for_prop "${repo}" "${dir}/${file}" "pypi.version"

    progress=$(prop "${repo}" "${dir}/${file}" RL.progress)
    if [ -n "${progress}" ]; then
        note "${c}: artifactory KEPT the RL.* properties across the redeploy (RL.progress=${progress})"
    else
        note "${c}: artifactory DROPPED the RL.* properties on the redeploy"
    fi

    # what decides the skip: the side-car for generic, the artifact itself otherwise
    local decides="${dir}/${file}"
    [ -n "${side_car}" ] && decides="${dir}/${side_car}"
    local kept
    kept=$(prop "${repo}" "${decides}" RL.progress)

    # -- 3. an ordinary run must scan the rebuild
    echo "-- run 2: ordinary run after the rebuild"
    scan
    expect_clean_run
    if [ -n "${kept}" ]; then
        expect_in_log "${LOG}" "rebuilt since the last scan" "the rebuild was noticed over the old properties (R10.8)"
    fi
    if [ "${VERIFY_BACKEND}" == "portal" ]; then
        expect_in_log "${LOG}" "version exists but digest: sha256:${sha_v2}" "the portal reported other bytes (R10.7.5)"
        expect_not_in_log "${LOG}" "skip: no upload to portal" "the upload was not refused (no 409)"
    fi
    expect_eq "RL.progress on the artifact" "scanned" "$(prop "${repo}" "${dir}/${file}" RL.progress)"
    expect_eq "RL.sha256 on the artifact" "${sha_v2}" "$(prop "${repo}" "${dir}/${file}" RL.sha256)"
    if [ -n "${side_car}" ]; then
        expect_eq "RL.sha256 on the side-car" "${sha_v2}" "$(prop "${repo}" "${dir}/${side_car}" RL.sha256)"
    fi

    # -- 4. and then leave it alone
    stamp=$(prop "${repo}" "${decides}" RL.timestamp)
    echo "-- run 3: nothing changed"
    scan
    expect_clean_run
    expect_not_in_log "${LOG}" "rebuilt since the last scan" "no rebuild is reported"
    expect_eq "RL.timestamp is untouched (skipped)" "${stamp}" "$(prop "${repo}" "${decides}" RL.timestamp)"

    # -- 5. the portal holds the new bytes
    if [ "${VERIFY_BACKEND}" == "portal" ]; then
        echo "-- run 4: ask the portal, properties ignored"
        scan --ignore-artifactory-properties
        expect_clean_run
        expect_not_in_log "${LOG}" "version exists but digest: sha256:${sha_v2}" "the portal holds the bytes of v2"
    fi

    cleanup_case "${repo}" "${dir}"
}

cleanup_case() { # repo, dir
    if [ "${KEEP}" != "1" ]; then
        delete_path "$1" "$2"
    fi

    rm -rf "${WORK}/v1" "${WORK}/v2"
}

# ----- main

main() {
    check_config

    VERSION="0.0.$(date +%s)"
    mkdir -p "${VERIFY_WORK_DIR}"
    WORK="$(mktemp -d "${VERIFY_WORK_DIR}/$(date +%Y%m%d-%H%M%S).XXXX")"
    echo "work dir: ${WORK} (scanner logs: run-<n>.log, kept)"

    for c in ${VERIFY_CASES}; do
        verify_case "$c"
    done

    echo
    echo "== ${PASSED} passed, ${FAILED} failed"
    for n in "${NOTES[@]}"; do
        echo "   ${n}"
    done

    [ "${FAILED}" -eq 0 ]
}

# sourcing the file (to test a helper) defines everything and runs nothing
[ "${BASH_SOURCE[0]}" == "$0" ] && main "$@"
