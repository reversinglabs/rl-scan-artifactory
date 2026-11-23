#! /bin/bash
# Upload the test items to ${REPO}/${DIR} (live.env) and set their properties.
# Each file gets unique content, so every sha256 differs. Safe to run again:
# it first refuses when ${DIR} already exists, use 90-cleanup.sh before a rerun.
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/live.env"

"${CURL[@]}" "${BASE}/api/repositories/${REPO}" >/dev/null 2>&1 \
    || die "repository ${REPO} not found on ${ARTIFACTORY_HOST}: create a generic local repo, or set REPO="
TYPE=$("${CURL[@]}" "${BASE}/api/repositories/${REPO}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("packageType",""), d.get("rclass",""))')
[ "${TYPE}" = "generic local" ] || die "${REPO} is '${TYPE}', expected 'generic local'"

if "${CURL[@]}" "${BASE}/api/storage/${REPO}/${DIR}" >/dev/null 2>&1; then
    die "${REPO}/${DIR} exists already; run ./90-cleanup.sh first"
fi
COUNT=$("${CURL[@]}" "${BASE}/api/storage/${REPO}?list&deep=1&listFolders=0" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("files", [])))')
[ "${COUNT}" = "0" ] || echo "WARNING: ${REPO} already holds ${COUNT} files; they will be scanned too"

rm -rf "${WORK}"
mkdir -p "${WORK}"

# a small tgz with unique content per item
for i in ${ITEMS}; do
    mkdir -p "${WORK}/src-${i}"
    printf 'rl-scan-artifactory live test item %s\n%s\n' "${i}" "$(date -u +%FT%TZ) $RANDOM$RANDOM" >"${WORK}/src-${i}/README.txt"
    tar -czf "${WORK}/${i}1.tgz" -C "${WORK}/src-${i}" README.txt
done

side_car() { # <item> <version or empty>
    {
        echo "[rl_meta]"
        echo "name = live-$1"
        [ -n "$2" ] && echo "version = $2"
        echo "path = ${1}1.tgz"
    } >"${WORK}/${1}1.rl_meta"
}
side_car b 2.0.0
side_car e ""   # no version: the pre pass cannot read it
side_car f 3.0.0

upload() { # <file name in WORK>
    "${CURL[@]}" -T "${WORK}/$1" "${BASE}/${REPO}/${DIR}/$1" >/dev/null
    echo "uploaded ${REPO}/${DIR}/$1"
}
for i in ${ITEMS}; do upload "${i}1.tgz"; done
for i in b e f; do upload "${i}1.rl_meta"; done

set_props a1.tgz "RL.meta.name=live-a;RL.meta.version=1.0.0"
set_props b1.tgz "RL.meta.name=wrong-b;RL.meta.version=9.9.9"
set_props c1.tgz "RL.meta.name=live-c"
set_props g1.tgz "RL.meta.name=live-g;RL.meta.version=4.0.0"

echo
"${HERE}/20-show.sh"
