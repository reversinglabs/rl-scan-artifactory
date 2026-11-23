# Live tests

End-to-end runs against a real Artifactory, rl-secure, the rl-scanner image
and the Portal, for what the unit tests in `tests/` cannot show. Run them after
each development step; extend `check.py` (the `EXPECT` table) and this file
when a step adds behaviour.

Covered now: R7.11 (`RL.meta.*`), generic cli sync, cli-docker never syncing,
the portal reached by `RLPORTAL_SERVER` alone, and Gradle (R4.1.7, its own
steps in its own repository, see [Gradle](#gradle-r417)).

Run on the test machine: it needs rl-secure for the cli (`CLI_HOME`, default
`$HOME/tmp/rl-secure` as in Makefile.test), docker for d1/d2, and
`~/.env_cli` / `~/.env_portal` as for `make test`. It runs the checkout this
`livetest/` folder is in (or `CHECKOUT=`).

```
cd livetest
./run.sh all          # setup c1 c2 age c3 age d1 d2 p1 p2, then a summary
./run.sh c1 c2        # or single steps; each is checked right after it runs
./run.sh check        # check all results again
./run.sh cleanup      # delete the test folder in Artifactory (asks)
./run.sh gradle       # gsetup g1 g2 g3 in the gradle repository, then a summary
./run.sh gcleanup     # delete the gradle test folder (asks)
```

`run.sh` runs the program itself (not `make test_*`), in its own venv
(`work/venv`), with the Makefile.test options, `LOG_LEVEL=DEBUG` and
`WITH_TEST_LIMIT_REPO_TO=0`. Per step it keeps `work/results/<step>/`:
`out.txt` (the `--verbose` line per item), `err.txt`, `run.log`, `exit` and
`props.txt` (`20-show.sh` after the step). `check.py` compares them with the
tables below and prints PASS / FAIL per check.

## Before you start

- A **generic local** repository used for nothing else, default
  `rl-live-generic` (`REPO=...`). A run scans the whole repository. The items
  go into its folder `live-test` (`DIR=...`; `DIR=live-1.2.0` for items an
  older kit set up, also for `check` and `cleanup`).
- The cli store `CLI_HOME` must be kept between c1, c2 and c3: the syncs need
  the scans of c1 in it.
- cli-docker store (`DOCKER_STORE`):
  - default `$HOME/tmp/rl-store-live-docker`, a **new** store: the image
    initialises it on the first scan (it must be empty or not exist);
    `run.sh` makes the directory first, so docker does not create it as root;
  - `DOCKER_STORE=$HOME/tmp/rl-secure` **reuses** the cli store. That works
    only when the image's rl-secure can read a store the local rl-secure
    wrote; the new store avoids the question.
- The cli-docker steps need `RLSECURE_ENCODED_LICENSE` and `RLSECURE_SITE_KEY`
  in `~/.env_cli`.

## The items (`10-setup.sh`)

All under `rl-live-generic/live-test/`, each a small tgz with unique content.

| Item | Set up with | Case |
|---|---|---|
| `a1.tgz` | `RL.meta.name=live-a`, `RL.meta.version=1.0.0` | purl from properties |
| `b1.tgz` + `b1.rl_meta` | side-car `live-b` / `2.0.0`; properties `wrong-b` / `9.9.9` | side-car wins |
| `c1.tgz` | only `RL.meta.name=live-c` | incomplete set |
| `d1.tgz` | nothing | cli placeholder; portal skips |
| `e1.tgz` + `e1.rl_meta` | side-car without `version` | unreadable side-car |
| `f1.tgz` + `f1.rl_meta` | side-car `live-f` / `3.0.0` | control |
| `g1.tgz` | `RL.meta.name=live-g`, `RL.meta.version=4.0.0`; version removed in C3 | incomplete set when a sync needs it |

## Steps and expected results

### setup, c1 - first cli run

| Item | Expected | Rule |
|---|---|---|
| a1.tgz | scanned, purl `rl-live-generic/live-a@1.0.0` | R7.11.6 |
| b1.tgz | scanned, purl `rl-live-generic/live-b@2.0.0` (not `wrong-b`) | R7.11.2 |
| c1.tgz | FAIL, message names `RL.meta.version` | R7.11.3 |
| d1.tgz | scanned, purl `rl-live-generic/d1.tgz@v0` | R7.11.6 |
| e1.rl_meta | FAIL (missing `version`); the rest of the repo still runs | R12.1.1 |
| e1.tgz | scanned with the placeholder `rl-live-generic/e1.tgz@v0` (its side-car failed) | R12.1.1, R7.11.6 |
| f1.tgz | scanned, purl `rl-live-generic/live-f@3.0.0` | R7.11.6 |
| g1.tgz | scanned, purl `rl-live-generic/live-g@4.0.0` | R7.11.6 |
| run | `finished with 2 failed item(s)` (c1.tgz, e1.rl_meta) | R12.4 |
| props | every `RL.meta.*` still there (`props.txt`) | R7.11.7 |

### c2 - cli with `--sync`

| Item | Expected | Rule |
|---|---|---|
| a1, b1, f1, g1 | reason `cli-sync`, **no** `Download finished` line for them | R7.11.6.1, R12.7.4.1 |
| d1, e1 | downloaded and scanned again, reason `cli` (no sync of a placeholder) | R7.11.6.2 |
| c1.tgz, e1.rl_meta | FAIL as in C1 | R7.11.3, R12.1.1 |

### age, c3 - automatic sync of old scans

`age` (`30-age.sh`) sets `RL.timestamp` 30 days back on a1, b1, d1, f1, g1 and removes
`RL.meta.version` from g1. No `--sync` this time.

| Item | Expected | Rule |
|---|---|---|
| a1, b1, f1 | synced by themselves: reason `cli-sync`, no download | R7.11.6.1, R12.7.3 |
| d1.tgz | not synced, not scanned: reason `sync not possible with cli: no .rl_meta side-car and no RL.meta.* properties`, earlier result reported | R7.11.6.2 |
| g1.tgz | FAIL naming `RL.meta.version` (the sync needs the purl) | R7.11.3 |
| e1.tgz | already processed (scanned recently in C2) | R10.2 |
| run | `finished with 3 failed item(s)` (c1, e1.rl_meta, g1) | |

### age, d1 - cli-docker never syncs (R12.7.2.1)

`age` again (c3 synced a1, b1, f1, so their timestamps are fresh), then
cli-docker **without** `-I` and without a store: an old scan must not be sent
to a sync, so no `store is None`.

| Item | Expected | Rule |
|---|---|---|
| a1, b1, d1, f1, g1 | reason `already processed`, no download | R12.7.2.1 |
| c1.tgz, e1.rl_meta | FAIL as before | R7.11.3, R12.1.1 |
| run | 2 failed items; `store is None` and `rl-sync` appear nowhere | R12.7.2 |

### d2 - cli-docker with a store and `-I` (R12.7.2)

| Item | Expected | Rule |
|---|---|---|
| a1, b1, d1, e1, f1 | scanned, reason `cli`, purls as in c1 (b1 from its side-car, d1/e1 placeholders) | R12.7.2, R7.11.6 |
| c1.tgz, g1.tgz | FAIL naming `RL.meta.version` | R7.11.3 |
| e1.rl_meta | FAIL | R12.1.1 |
| store | `DOCKER_STORE` now holds `.rl-secure` with these purls | R12.7.2 |

### p1 - portal with `-I`

`-I` because the cli runs wrote `RL.*` results on the same files.

| Item | Expected | Rule |
|---|---|---|
| a1.tgz | scanned via the portal itself (own sha2), full `RL.*` on a1.tgz incl. `RL.sha256`, purl `rl-live-generic/live-a@1.0.0`; `RL.meta.*` still there | R7.11.4, R7.11.7 |
| b1.tgz | not an item of its own: reason `skip: described by a .rl_meta side-car` | R7.11.2 |
| b1.rl_meta | scans b1.tgz with purl `rl-live-generic/live-b@2.0.0`; result on b1.tgz | R7.11.2 |
| c1.tgz | FAIL naming `RL.meta.version` | R7.11.3 |
| d1.tgz | skip: `skip: not a candidate for inspection` (neither side-car nor `RL.meta.*`) | R7.11.5 |
| e1.rl_meta | FAIL (missing `version`) | R12.1.1 |
| e1.tgz | skip: `skip: not a candidate for inspection` (neither side-car nor `RL.meta.*`) | R7.11.5 |
| f1.rl_meta | scans f1.tgz, purl `rl-live-generic/live-f@3.0.0` | control |
| g1.tgz | FAIL naming `RL.meta.version` (removed in C3) | R7.11.3 |
| run | `finished with 3 failed item(s)` | |

### p2 - portal without `RLPORTAL_HOST` (R12.5.1.1)

p1 again, with `RLPORTAL_HOST` removed after `~/.env_portal` is read; the env
file must set `RLPORTAL_SERVER` (the step stops otherwise). A server alone
means `my.secure.software/<server>`. `env.txt` in the results records whether
the env file had set the host: if it had not, p1 already ran this way.

| Item | Expected | Rule |
|---|---|---|
| every item | as in p1 | R12.5.1.1 |
| a1.tgz, b1.rl_meta | `report: https://my.secure.software/...` | R12.5.1.1 |
| env.txt | `RLPORTAL_HOST: ...` (the step really ran without it) | |

### Gradle (R4.1.7)

Not part of `all`: it needs a **gradle local** repository used for nothing
else, default `rl-live-gradle` (`GREPO=...`), with the layout Artifactory gives
a Gradle repository by default, **maven-2-default**. `gsetup`
(`40-gradle-setup.sh`) checks the package type, class and layout, then uploads
into the group folder `org/example/livetest/`:

| Item | Case |
|---|---|
| `mylib/1.0/mylib-1.0.jar`, `mylib/2.0/mylib-2.0.jar` | small jars with unique content: scanned |
| `mylib/1.0/mylib-1.0.pom`, `mylib/1.0/mylib-1.0.module` | not candidates |

The cli steps use the same store `CLI_HOME` as c1..c3.

| Step | Item | Expected | Rule |
|---|---|---|---|
| g1 (cli) | both jars | scanned, reason `cli`, downloaded, purl `rl-live-gradle/org.example.livetest.mylib@1.0` / `@2.0`, `RL.package-url` set | R4.1.7 |
| g1, g2, g3 | .pom, .module | no output line at all (never listed) | R4.1.7, R5.4 |
| g2 (cli `--sync`) | both jars | reason `cli-sync`, no download (the store knows the gradle purl) | R4.1.7, R12.7.4.1 |
| g3 (portal `-I`) | both jars | same purls, `RL.sha256` and `RL.package-url` set | R4.1.7 |
| every step | run | exit 0, no failed items | |

The purl is the one a maven repository gives for the same path. `gcleanup`
deletes the group folder `org/example/livetest` (the empty `org/example` stays). A second
`./run.sh gradle` after `gcleanup` meets the purls of the first run in the cli
store and on the portal; remove those first for a clean result.

### cleanup

Deletes `rl-live-generic/live-test` (asks first) and the local `work/`
directory. The portal projects and the cli store entries stay; remove them with
the usual tools if wanted.

Record the outcome per row in `Tests.md` (live table) as pass / fail + note.
