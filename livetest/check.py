#! /usr/bin/env python3
"""Check the results of the live test steps against README.md.

    check.py <results dir> <repo> [step ...]     (default: every step with results)

Reads, per step, results/<step>/out.txt (the --verbose line per item),
run.log (downloads, the failed-item summary), exit and props.txt (20-show.sh).
Prints one line per check and exits 1 when any check failed.
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# the test folder in the repository; live.env sets DIR, run.sh passes it on
DIR = f"/{os.environ.get('DIR', 'live-test')}/"
# the gradle steps (marked "gradle") run in their own repository and folder
GREPO = os.environ.get("GREPO", "rl-live-gradle")
GDIR = f"/{os.environ.get('GDIR', 'org/example/livetest')}/"
GPURL = "pUrl: {repo}/org.example.livetest.mylib@"
PLACEHOLDER_STOP = "reason: sync not possible with cli: no .rl_meta side-car and no RL.meta.* properties"

# per item: ("has", text) the item's output line contains text
#           ("fail", text) there is a FAIL line for it, containing text
#           ("download", bool) a 'Download finished' log line for it, or none
#           ("prop", "RL.x") / ("noprop", "RL.x") in props.txt after the step
#           ("absent", "") no output line at all for the item (not a candidate)
# per step: "gradle" (True: GREPO and GDIR instead of the repo argument and DIR),
#           "exit", "failed" (the count in the summary), "never" (text that must not appear),
#           "env" (text that env.txt must hold: what run.sh unset for the step)
EXPECT: dict[str, dict[str, Any]] = {
    "c1": {
        "exit": 103,
        "failed": 2,
        "items": {
            "a1.tgz": [("has", "pUrl: {repo}/live-a@1.0.0"), ("prop", "RL.meta.name")],
            "b1.tgz": [("has", "pUrl: {repo}/live-b@2.0.0"), ("prop", "RL.meta.name")],
            "c1.tgz": [("fail", "RL.meta.version"), ("prop", "RL.meta.name")],
            "d1.tgz": [("has", "pUrl: {repo}/d1.tgz@v0")],
            "e1.rl_meta": [("fail", "")],
            "e1.tgz": [("has", "pUrl: {repo}/e1.tgz@v0")],
            "f1.tgz": [("has", "pUrl: {repo}/live-f@3.0.0")],
            "g1.tgz": [("has", "pUrl: {repo}/live-g@4.0.0"), ("prop", "RL.meta.version")],
        },
    },
    "c2": {
        "exit": 103,
        "failed": 2,
        "items": {
            "a1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "b1.tgz": [("has", "reason: cli-sync"), ("has", "live-b@2.0.0"), ("download", False)],
            "f1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "g1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "d1.tgz": [("has", "reason: cli;"), ("download", True)],
            "e1.tgz": [("has", "reason: cli;"), ("download", True)],
            "c1.tgz": [("fail", "RL.meta.version")],
            "e1.rl_meta": [("fail", "")],
        },
    },
    "c3": {
        "exit": 103,
        "failed": 3,
        "items": {
            "a1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "b1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "f1.tgz": [("has", "reason: cli-sync"), ("download", False)],
            "d1.tgz": [("has", PLACEHOLDER_STOP), ("download", False)],
            "g1.tgz": [("fail", "RL.meta.version")],
            "e1.tgz": [("has", "reason: already processed")],
            "c1.tgz": [("fail", "RL.meta.version")],
            "e1.rl_meta": [("fail", "")],
        },
    },
    "d1": {
        "exit": 103,
        "failed": 2,
        "never": ["store is None", "rl-sync"],
        "items": {
            "a1.tgz": [("has", "reason: already processed"), ("download", False)],
            "b1.tgz": [("has", "reason: already processed"), ("download", False)],
            "d1.tgz": [("has", "reason: already processed"), ("download", False)],
            "f1.tgz": [("has", "reason: already processed"), ("download", False)],
            "g1.tgz": [("has", "reason: already processed"), ("download", False)],
            "c1.tgz": [("fail", "RL.meta.version")],
            "e1.rl_meta": [("fail", "")],
        },
    },
    "d2": {
        "exit": 103,
        "failed": 3,
        "never": ["store is None", "rl-sync"],
        "items": {
            "a1.tgz": [("has", "reason: cli;"), ("has", "live-a@1.0.0"), ("download", True)],
            "b1.tgz": [("has", "reason: cli;"), ("has", "live-b@2.0.0")],
            "d1.tgz": [("has", "reason: cli;"), ("has", "d1.tgz@v0")],
            "e1.tgz": [("has", "reason: cli;"), ("has", "e1.tgz@v0")],
            "f1.tgz": [("has", "reason: cli;"), ("has", "live-f@3.0.0")],
            "c1.tgz": [("fail", "RL.meta.version")],
            "g1.tgz": [("fail", "RL.meta.version")],
            "e1.rl_meta": [("fail", "")],
        },
    },
    "p1": {
        "exit": 103,
        "failed": 3,
        "items": {
            "a1.tgz": [("has", "live-a@1.0.0"), ("prop", "RL.sha256"), ("prop", "RL.meta.name")],
            "b1.tgz": [("has", "reason: skip: described by a .rl_meta side-car")],
            "b1.rl_meta": [("has", "live-b@2.0.0")],
            "c1.tgz": [("fail", "RL.meta.version")],
            "d1.tgz": [("has", "reason: skip: not a candidate for inspection")],
            "e1.rl_meta": [("fail", "")],
            "e1.tgz": [("has", "reason: skip: not a candidate for inspection")],
            "f1.rl_meta": [("has", "live-f@3.0.0")],
            "g1.tgz": [("fail", "RL.meta.version")],
        },
    },
}

# gradle (R4.1.7): read as maven, in the maven-2-default layout
GRADLE_NOT_CANDIDATES: dict[str, list[tuple[str, Any]]] = {
    "mylib/1.0/mylib-1.0.pom": [("absent", "")],
    "mylib/1.0/mylib-1.0.module": [("absent", "")],
}
EXPECT["g1"] = {
    "gradle": True,
    "exit": 0,
    "failed": 0,
    "items": {
        "mylib/1.0/mylib-1.0.jar": [
            ("has", "reason: cli;"),
            ("has", GPURL + "1.0"),
            ("download", True),
            ("prop", "RL.package-url"),
        ],
        "mylib/2.0/mylib-2.0.jar": [
            ("has", "reason: cli;"),
            ("has", GPURL + "2.0"),
            ("download", True),
            ("prop", "RL.package-url"),
        ],
        **GRADLE_NOT_CANDIDATES,
    },
}
EXPECT["g2"] = {
    "gradle": True,
    "exit": 0,
    "failed": 0,
    "items": {
        "mylib/1.0/mylib-1.0.jar": [("has", "reason: cli-sync"), ("has", GPURL + "1.0"), ("download", False)],
        "mylib/2.0/mylib-2.0.jar": [("has", "reason: cli-sync"), ("has", GPURL + "2.0"), ("download", False)],
        **GRADLE_NOT_CANDIDATES,
    },
}
EXPECT["g3"] = {
    "gradle": True,
    "exit": 0,
    "failed": 0,
    "items": {
        "mylib/1.0/mylib-1.0.jar": [("has", GPURL + "1.0"), ("prop", "RL.sha256"), ("prop", "RL.package-url")],
        "mylib/2.0/mylib-2.0.jar": [("has", GPURL + "2.0"), ("prop", "RL.sha256"), ("prop", "RL.package-url")],
        **GRADLE_NOT_CANDIDATES,
    },
}

# p2: p1 again with RLPORTAL_SERVER alone (R12.5.1.1): the same results, and the
# portal reached is my.secure.software/<server>
EXPECT["p2"] = {
    **EXPECT["p1"],
    "env": ["RLPORTAL_HOST: "],
    "items": {
        **EXPECT["p1"]["items"],
        "a1.tgz": [*EXPECT["p1"]["items"]["a1.tgz"], ("has", "report: https://my.secure.software/")],
        "b1.rl_meta": [*EXPECT["p1"]["items"]["b1.rl_meta"], ("has", "report: https://my.secure.software/")],
    },
}


def props_of(text: str) -> dict[str, set[str]]:
    """props.txt: '== file' headers, then '   key=value' lines."""
    result: dict[str, set[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("== "):
            current = line[3:].strip()
            result[current] = set()
        elif current and "=" in line:
            result[current].add(line.strip().split("=", 1)[0])
    return result


@dataclass
class StepResult:
    """What one step left in results/<step>/."""

    out: list[str]
    log: str
    err: str
    props: dict[str, set[str]]
    code: int
    env: str
    bad: int = 0

    def report(self, ok: bool, what: str) -> None:
        self.bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {what}")


def read_step(d: Path) -> StepResult:
    def text(name: str) -> str:
        return (d / name).read_text(errors="replace") if (d / name).exists() else ""

    code_text = text("exit").strip()
    return StepResult(
        out=text("out.txt").splitlines(),
        log=text("run.log"),
        err=text("err.txt"),
        props=props_of(text("props.txt")),
        code=int(code_text) if code_text else -1,
        env=text("env.txt"),
    )


def check_item(r: StepResult, repo: str, folder: str, name: str, checks: list[tuple[str, Any]]) -> None:
    uri = f"{folder}{name}"
    line = next((x for x in r.out if f"{repo}::{uri};" in x), "")
    fail = next((x for x in r.out if x.startswith(f"FAIL: {repo}:{uri};")), "")
    for kind, raw in checks:
        value = raw.format(repo=repo) if isinstance(raw, str) else raw
        if kind == "has":
            r.report(value in line, f"{name}: '{value}'" + ("" if line else " (no output line)"))
        elif kind == "fail":
            r.report(bool(fail) and value in fail, f"{name}: FAIL line" + (f" naming '{value}'" if value else ""))
        elif kind == "download":
            base = name.rsplit("/", 1)[-1]  # the gradle items have folders; the download may not
            seen = re.search(rf"Download finished successfully: .*/{re.escape(base)}\b", r.log) is not None
            r.report(seen is value, f"{name}: {'downloaded' if value else 'not downloaded'}")
        elif kind == "prop":
            r.report(value in r.props.get(name, set()), f"{name}: has {value}")
        elif kind == "noprop":
            r.report(value not in r.props.get(name, set()), f"{name}: no {value}")
        elif kind == "absent":
            r.report(not line and not fail, f"{name}: no output line (not a candidate)")


def check_step(results: Path, repo: str, step: str) -> int:
    d = results / step
    if not (d / "out.txt").exists():
        print(f"--- {step}: no results")
        return 0

    r = read_step(d)
    exp = EXPECT[step]
    repo, folder = (GREPO, GDIR) if exp.get("gradle") else (repo, DIR)

    print(f"--- {step}")
    r.report(r.code == exp["exit"], f"exit {r.code} (expected {exp['exit']})")

    m = re.search(r"finished with (\d+) failed item", r.log + r.err)
    failed = int(m.group(1)) if m else 0
    r.report(failed == exp["failed"], f"{failed} failed item(s) (expected {exp['failed']})")

    for text in exp.get("never", []):
        r.report(text not in r.log + r.err + "\n".join(r.out), f"never '{text}'")

    for text in exp.get("env", []):
        r.report(text in r.env, f"env.txt has '{text}'")

    for name, checks in exp["items"].items():
        check_item(r, repo, folder, name, checks)

    print(f"--- {step}: {'ok' if r.bad == 0 else f'{r.bad} check(s) failed'}")
    return r.bad


def main() -> int:
    results, repo = Path(sys.argv[1]), sys.argv[2]
    steps = sys.argv[3:] or [s for s in EXPECT if (results / s / "out.txt").exists()]
    total = sum(check_step(results, repo, s) for s in steps)
    if len(steps) > 1:
        print(f"=== {len(steps)} step(s): {'all ok' if total == 0 else f'{total} check(s) failed'}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
