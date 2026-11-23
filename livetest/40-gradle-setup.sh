#! /bin/bash
# Upload the gradle test items (live.env: GFILES) to ${GREPO}/${GDIR}, in the
# maven-2-default layout. Each jar gets unique content.
# Refuses when ${GDIR} exists already: ./run.sh gcleanup first.
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/live.env"
export REPO="${GREPO}"
export DIR="${GDIR}"

"${CURL[@]}" "${BASE}/api/repositories/${REPO}" >/dev/null 2>&1 \
    || die "repository ${REPO} not found on ${ARTIFACTORY_HOST}: create a gradle local repo (layout maven-2-default), or set GREPO="
TYPE=$("${CURL[@]}" "${BASE}/api/repositories/${REPO}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("packageType",""), d.get("rclass",""), d.get("repoLayoutRef",""))')
[ "${TYPE}" = "gradle local maven-2-default" ] \
    || die "${REPO} is '${TYPE}', expected 'gradle local maven-2-default' (package type, class, layout)"

if "${CURL[@]}" "${BASE}/api/storage/${REPO}/${DIR}" >/dev/null 2>&1; then
    die "${REPO}/${DIR} exists already; run ./run.sh gcleanup first"
fi
COUNT=$("${CURL[@]}" "${BASE}/api/storage/${REPO}?list&deep=1&listFolders=0" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("files", [])))')
[ "${COUNT}" = "0" ] || echo "WARNING: ${REPO} already holds ${COUNT} files; they will be scanned too"

G="${WORK}/gradle"
rm -rf "${G}"
mkdir -p "${G}"

for f in ${GFILES}; do
    mkdir -p "${G}/$(dirname "${f}")"
    case "${f}" in
    *.jar) # a jar is a zip: a manifest and one unique text file
        python3 - "${G}/${f}" <<'PY'
import random, sys, time, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nCreated-By: rl-scan-artifactory livetest\n")
    z.writestr("livetest.txt", f"rl-scan-artifactory gradle live test {time.time()} {random.random()}\n")
PY
        ;;
    *) printf 'rl-scan-artifactory gradle live test: %s\n' "${f}" >"${G}/${f}" ;;
    esac
    "${CURL[@]}" -T "${G}/${f}" "${BASE}/${REPO}/${DIR}/${f}" >/dev/null
    echo "uploaded ${REPO}/${DIR}/${f}"
done

echo
"${HERE}/20-show.sh"
