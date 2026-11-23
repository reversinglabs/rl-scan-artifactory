#! /bin/bash
# Make the earlier scans look 30 days old, so the next cli run without --sync
# syncs them by itself (R12.7.3), and remove RL.meta.version from g1.tgz so
# that its sync needs a purl it cannot make (R7.11.3).
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/live.env"

OLD=$(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%SZ)
for f in a1.tgz b1.tgz d1.tgz f1.tgz g1.tgz; do
    set_props "${f}" "RL.timestamp=${OLD}"
    echo "${f}: RL.timestamp=${OLD}"
done
del_props g1.tgz "RL.meta.version"
echo "g1.tgz: RL.meta.version removed"
