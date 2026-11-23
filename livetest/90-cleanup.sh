#! /bin/bash
# Delete ${REPO}/${DIR} (the test items and the reports the cli uploaded next
# to them) and the local work directory. Asks first.
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/live.env"

"${CURL[@]}" "${BASE}/api/storage/${REPO}/${DIR}?list&deep=1&listFolders=0" 2>/dev/null \
    | python3 -c 'import json,sys; [print("  ", f["uri"]) for f in json.load(sys.stdin).get("files", [])]' || true
read -r -p "Delete ${REPO}/${DIR} with everything above? [y/N] " ok
[ "${ok}" = "y" ] || die "nothing deleted"

"${CURL[@]}" -X DELETE "${BASE}/${REPO}/${DIR}" >/dev/null
rm -rf "${WORK}"
echo "deleted ${REPO}/${DIR} and ${WORK}"
