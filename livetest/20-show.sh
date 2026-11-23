#! /bin/bash
# Read-only: the properties of every test item, to compare with README.md.
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/live.env"

# shellcheck disable=SC2046
for f in $(show_files); do
    "${CURL[@]}" "${BASE}/api/storage/${REPO}/${DIR}/${f}" >/dev/null 2>&1 || continue
    echo "== ${f}"
    shown=$(props "${f}" | grep -E '^RL\.(meta\.|progress|package-url|scan-status|timestamp|sha256)' || true)
    if [ -n "${shown}" ]; then
        echo "${shown}" | sed 's/^/   /'
    else
        echo "   (no RL.* properties)"
    fi
done
