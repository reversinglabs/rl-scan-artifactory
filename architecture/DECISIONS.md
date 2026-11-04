# rl-scan-artifactory — decisions and history

The companion to `SPECIFICATION.md`. The specification says what the program
does; this says what was tried, what went wrong, what was decided and what is
still open.

Nothing here is normative: the R-numbers in `SPECIFICATION.md` say what the
program does, and these pages say why. Where the two disagree, the specification
is right and an entry here is out of date.

Split out because the two are read at different times: the rules when changing
the code, this when asking *why* something is the way it is. Most of what follows
is settled and needs no attention — it is here so the same ground is not
covered twice.

## Contents

| Part | What it holds |
|---|---|
| [1. Still open](#part-1-still-open) | needs a decision or work |
| [2. Deliberate](#part-2-deliberate) | decided, and not to be re-opened by accident |
| [3. What this codebase taught](#part-3-what-this-codebase-taught) | patterns worth recognising again |
| [4. Archive](#part-4-archive) | fixed, kept for the reasoning behind the fix |

---

## Part 1. Still open

Nothing at the moment.

---

## Part 2. Deliberate

These are decided. They look like defects and are not.

### A.6 Unreachable code in `scan_cli_docker.py`


One `raise` is followed by unreachable statements (line ~198). Unlike the other
two unreachable blocks found during review, this one looks deliberate — a sketch
of a not-yet-implemented sync path. A `# TODO` naming what is missing would say
so, rather than leaving a reader to work it out.

### A.3 `findparentmanifestlists` is not used, though the server may have it

Since 7.119.0 Artifactory answers which manifest lists include a docker
manifest, which looks like the server-side version of the pre pass of R8.10. It
is not adopted, for three reasons:

- **More calls, not fewer.** The request
  (`POST /api/docker/{repo-key}/v2/parentManifests`) takes one
  `dockerRepository` and one `tag`, so it answers for one manifest per call. The
  pre pass downloads each `list.manifest.json` once, one request per multi
  architecture image; the endpoint would need one per architecture.
- **It may not answer our question.** An architecture manifest is stored under a
  `sha256__<hex>` directory and has no tag. The reference does not say whether
  `tag` accepts a digest.
- **It answers more than we ask.** It returns every tag of every parent list,
  so R8.10.4 (the first list that names a digest wins) would still have to pick
  one.

Adopting it would also mean keeping both paths and switching on the version
from `GET /api/system/version` (R11.4.1), since older servers lack it: two paths
to keep correct, for no gain.

Worth looking at again only if a repository turns up that holds the
architecture manifests without the `list.manifest.json` naming them (a remote or
cache repository might), and the endpoint is shown to answer there.

---

## Part 3. What this codebase taught

Patterns, not defects. Each cost real time to find once.

### A.13 Deleting dead code creates dead code


Removing `_check_secure_software` (A.5) left four things unreachable that had
been live only through it: `ProxyInfo.get_proxy_info`, `ProxyInfo._set_proxy`,
and two constants. Nothing failed, and no gate noticed — `ruff` removes unused
*imports*, not unused definitions.

So the check in A.11 is worth re-running after any deletion, not only
periodically, which is why `make dead-code` exists.

Deleting the fourteen bore this out: the removal ran in rounds, re-running the
check after each, because a function can only be seen to be unreachable once its
last caller is gone. In the event nothing further was orphaned, but that is a
property of this codebase today rather than something to assume next time.

### A.18 State that is maintained and then discarded


Three pieces of state have now been found that were written carefully and never
consulted, or consulted only after being overwritten:

| What | Found in | Outcome |
|---|---|---|
| `ArtifactoryFileProcessorCommon.steps` | A.14 | removed, 37 assignments |
| `ScanCliBase.results` | A.16 | removed, 9 keys |
| `is_uploaded` in `docker.process` | here | removed |

The last one is the subtlest of the three, and worth describing because the
pattern will recur. `process()` computed whether an earlier run had uploaded the
artifact, stored it in `file.simple["is_uploaded"]`, and `_process_portal` read
it back - and then overwrote it unconditionally from `exists_on_portal`, which is
the only thing that actually knows. So the value was computed, carried across two
methods and discarded before use, while looking load bearing at every step.

It also had a real cost: it raised the question "should `is_uploaded = True` move
above the `ignore_artifactory_properties` check?", which took a careful reading
of two methods to answer, and the answer was that it did not matter at all.

None of this is careless: all three date from working out how Artifactory and the
Portal behave while building against them, which is exactly when you keep state
you are not yet sure you need. The lesson is only that such state should be
removed once the shape is known, because afterwards it costs a reader the same
effort as state that matters.

`tools/find_dead_code.py` now checks for it. A **dead store** is an assignment
whose value cannot reach any reader, in two shapes narrow enough to be right
rather than merely suggestive:

```python
x = a          # immediately followed by
x = b

x = a          # immediately followed by
if ...:
    x = b
else:
    x = c
```

In the second both branches must assign before reading, so every path replaces
the value. That is the shape `is_uploaded` had. An assignment that is
deliberately a default carries `# DEAD STORE OK` on its line and is reported
without the `!` that fails `--strict`.

It deliberately does not flag: a read between the two assignments, a
reassignment that uses the old value (`x = x + 1`), only one branch assigning, a
branch that reads before assigning, or a loop accumulator. Verified against all
six, and against the pre-fix tree, where it finds `is_uploaded` at the right
line and nothing else.

What it cannot see is the other half of the same story: the value travelling
through `file.simple["is_uploaded"]` from one method to another. Only the
overwrite on arrival is detectable, which in that case was enough.

### A.19 Documentation that nobody could check


Two claims stood for a long time because nothing compared them with the program:

- **R11.3** said every call went through a session **with a retry adapter**.
  There was no adapter. The claim survived because urllib3 says "Max retries
  exceeded" even when it retried nothing, so the traceback appeared to confirm
  it. Written from what the code looked like it should do rather than what it
  did.
- The README's option table named **`--proxy-pass`** and **`PROXY_PASS`**. The
  option is `--proxy-password` and the variable is `PROXY_PASSWORD`, so anyone
  following the table got an argparse error. It also said `LOG_LEVEL` was "not
  supported as parameter" while `--log-level` existed, and never mentioned
  `--waittime` at all.

The options and the environment variables are now checked by
`test_progress_vocabulary.py`, in both directions: the README may not name an
option or a variable that does not exist, and every one that exists must be in
the README. Those four tests read `argparse` itself, so the table cannot drift
again without the suite saying so.

The numbers in the spec were cross checked by hand against `constants.py` at the
same time - exit codes, the progress and scan-status vocabularies, the 7.104.5
report url boundary, the 14 day sync window, the maven and docker segment
minimums, the retry counts and statuses, the rl-json hashes path and schema, the
repository name pattern - and all of them matched. The endpoint table of §11 was
checked against `artifactory_api.py`: all nine are real.

What is still only prose is the **reasoning**: why a rule exists, what it cost
before. That cannot be tested, and it is most of the value here, so it is worth
re-reading whenever a rule changes rather than assuming it kept up.

---

## Part 4. Archive

Fixed. Kept because the reasoning is the part that would otherwise be lost, and
because a fix whose reason is forgotten gets undone.

## 14. Known deviations

Each has a strict-xfail test; fixing the code turns that test red, which is the
cue to delete the mark. Numbering is stable — a fixed entry keeps its number and
moves to §14.1 rather than being renumbered.

**None open.** Everything found so far is listed as fixed below.

One strict xfail remains in the suite and is deliberately not a deviation:
`get_tree_items()` in `DockerManifestExtract` is a stub, but the class is only
ever constructed for a `manifest.json`, so that branch is unreachable (D9). The
mark keeps the stub from being mistaken for working code.

Things worth doing that are not deviations are in Appendix A.

### 14.1 Fixed

| # | Was | Fixed by |
|---|---|---|
| D1 | `_clean_value` discarded the result of `str.replace`, so `/` and `@` reached the purl | assigning the result — moot once the module was found to be dead (D3) |
| D2 | `GenericMeta` had no `sha256` field | adding the field; also moot with D3 |
| D3 | `self.required` was never enforced | the module was never wired up: `GenericMeta` / `GenericMetaReader` are commented out, and the live path (§7) does enforce the mandatory keys |
| D4 | `_remove_substring_mid` indexed one character instead of slicing | `str1[start + len(str2) :]` |
| D5 | a release with no platform tag was lost, leaving a trailing `-` in the version | widening the numeric branch to `^[-\d.]+$` and returning the release verbatim |
| D6 | `_strip_tail` lowercased only one operand | lowercasing both |
| D7 | the cleared docker version was `""` (a string) among lists | `[""]`, plus the fallback of R5.7 so it is rarely empty at all |
| D8 | the rpm mangler raised `IndexError` on missing rpm metadata | defaulting arch and release to `""`, and appending the release only when there is one, so the version no longer ends in `-` |
| D9 | `get_tree_items()` returned `{}`, apparently leaving multi-architecture images unscanned | not a gap: the class's tree branch is unreachable, and multi architecture images are handled by R8.10 |
| D11 | maven tested `endswith("jar")` not `endswith(".jar")` | `JAR_TAIL` in `constants.py`, used case-insensitively by all three maven stages |
| D10 | the `get_items()` error for an unknown manifest type printed the literal `{self.manifest_type}` | the missing `f` prefix |
| D12 | a maven uri with too few segments raised `IndexError`, or silently named the package `.` | the layout check of R4.1.6: too few or empty segments are logged and skipped |
| D13 | `_make_target_name` joined blindly, so `..` in either name escaped the download directory | the plain-file-name check of R9.7 |
| D14 | an empty version made `_mangle_default` call `str.split("")` | guarding on a non-empty version; since D16 an empty version never reaches the mangling at all |
| D15 | `_split_release` raised `IndexError` on an empty segment in a non-numeric release | testing the candidate segment for content before looking at its first character (R6.3.2) |
| D16 | a missing or empty `name` or `version` became an empty purl component | one helper that refuses any absent, empty-list or empty-string value, naming the key and the uri (R3.2) |
| D17 | docker `_get_properties` used a bare `assert` and unguarded `pop()` on the uri | the layout check of R4.3.0, matching the maven one |
| D18 | an unreadable manifest was swallowed and then reported as a missing `schemaVersion` | raising `SpectraAssureInvalidAction` from the read itself, and rejecting json that is not an object (R8.2) |
| D19 | `_verify_download_file` could not tell "no digest" from "mismatch" | the tri-state lives with the caller; the verifier refuses an empty digest (R9.4) |
| D20 | a proxy user without a password produced `http://user:None@host:port` | refusing half a credential, whichever half is missing (R3.3) |
| D23 | `_make_meta_dict` stored `str` or `None` where property values are `list[str]` | storing `[value]`, and omitting the property entirely for a key the side-car did not supply (R7.6) |
| D27 | the generic processor tested `RL.progress` against `portal_upload_ok`, which is never written, so an uploaded-but-unscanned artifact was uploaded to the Portal again | one vocabulary in `constants.py`, referenced by name everywhere, with tests that fail if either word is typed as a literal again (R10.4.x) |
| D24 | `FilePropertiesGeneric` hardcoded empty derived name and version, overwriting the repository's own | deriving nothing at all: a generic repository has no layout, and its purl comes from the side-car (§7) |
| D21 | the generic path escaped only `@` and `/` | `FUTURE_GENERIC_PURL_ESCAPE`, off until the release that flips it (R7.9.1) |
| D22 | the generic path joined with `-`, the name manglers with `_` | `FUTURE_GENERIC_PURL_SEPARATOR`, off until the release that flips it (R7.9.2) |
| D26 | a `%` anywhere in a side-car value raised `InterpolationSyntaxError`, so such an artifact could not be described at all | reading the side-car with `interpolation=None` (R7.2) |
| D25 | a recursive property update refused by the server side cap failed silently for the whole folder | the per item fallback of R11.5.x, plus logging the server's own error message on every property failure; the refusal is recognised by its message and the cap value is named in the log |

---

## Appendix A. Optional future items

Observations noticed while working on something adjacent. None of these is a
deviation: the code is correct as it stands, and none has a test in `tests/`.
They are recorded so they are not rediscovered from scratch, and so the reasons
for leaving them alone stay attached.

### A.1 Exception types — done


Every `raise Exception(...)` now raises a project class. `exceptions.py` has
three:

| Class | Means |
|---|---|
| `SpectraAssureExceptions` | the base; nothing raises it directly |
| `SpectraAssureInvalidAction` | what was asked for is not allowed, or the input is malformed |
| `SpectraAssureInvariantError` | an internal expectation of this program did not hold |

A caller can now catch the project's own base class instead of `Exception`, and
tell "you asked for something impossible" from "the program is confused about
its own state".

### A.2 `assert` under `python -O` — done


All 79 became `SpectraAssureInvariantError`. None remains in
`rl_scan_artifactory`. The shape is uniform:

```python
if self.token is None:
    msg = "expected self.token is not None"
    raise SpectraAssureInvariantError(msg)
```

The condition is the negation of what the assert asserted, written the direct way
(`is None`, `not in`, `!=`) rather than as `not (...)`, and the message names the
expectation that failed. A trailing comment on the original assert is kept, since
it was often the only explanation.

One thing to watch for, found later in a live run: the conversion inserts the
guard as the **first** statement of the function, and in one case that put it
above the docstring. A string that is not the first statement is not a
docstring, so the function silently lost its own. Only
`_portal_make_report_base` was affected, and `test_progress_vocabulary.py` now
checks the whole package for a docstring sitting below something else.

Two things this settles. `python -O` no longer removes any of these checks, so a
release build behaves like a development one. And `mypy --strict` still narrows
exactly as it did before - verified on the whole package - so nothing was lost by
the change.

The messages are mechanical (`expected <condition>`) rather than prose. That is
deliberate: 79 hand-written messages would have been 79 chances to describe the
wrong thing, and the condition is what a reader needs. Individual ones are worth
improving when a real failure shows which ones people actually hit.

### A.4 No per item fallback on recursive property deletion — done


`del_one_prop` now falls back exactly as `put_one_prop` does (R11.5.x), and the
decision of whether a refusal is worth splitting lives in one place,
`_should_retry_per_item`, shared by both. Deleting a property that is not there
is not an error, so items the refused call had already handled cost nothing on
the retry.

Still nothing passes `recursive=True` to it today, so this is defence rather than
a fix - but the two verbs no longer behave differently for no reason.

### A.5 `_check_secure_software` is an unreachable stub — done


Deleted. See A.13 for what the deletion left behind.

Original note:

#### The stub

`ArtifactoryFileProcessorCommon._check_secure_software` has no callers, builds
its url from `name = ""` and `version = ""`, and unconditionally returns
`False`. It is half-written scaffolding rather than dead code with a purpose.
Either finish it or delete it; leaving it invites someone to call it.

### A.7 Logs on stdout versus stderr — done


The console copy of the log is on **stderr**, behind `--log-to-stderr`. stdout
carries the program's own output - the progress lines - so the two can be
redirected separately, which is the conventional split and the reason to prefer
it.

It also removed a rule rather than adding one. While both were on stdout,
`my_print` had to work out whether the log was already going to print the same
line, and suppress itself when it was; that logic and its level check are gone,
and `my_print` now simply prints.

**User visible change:** the option was `--log-to-stdout` and is now
`--log-to-stderr`.

### A.8 Exit code 103 is a policy choice — done


`--ignore-skipped` makes a run that finished with skipped items exit 0 instead of
103. The default stays non-zero, because exiting 0 after silently skipping
artifacts is how under-scanning goes unnoticed; the flag is for a pipeline that
has decided it would rather not fail on that.

Either way the failures are logged per item and summarised (R12.3.5), so the
information is never lost - only the exit code changes. Using the flag says so in
the log, with the counts.

### A.10 Test coverage gaps — done


810 tests, 61% of statements. The shape matters more than the number, and it is
now the one to want:

| Layer | Cover | Why |
|---|---|---|
| purl pipeline, parsers, helpers, constants | ~100% | pure, and the answers are the product |
| the three `process()` decision trees | characterized | each has its own tests, written before it was restructured |
| `main.py` exit codes | 97% | the whole contract a pipeline sees |
| `my_args` validation | covered | mandatory settings, repository names |
| http and upload plumbing | 32-46% | mocking `requests` here buys little real assurance |

The last gap closed was `artifactory_file_processor_default.py`, which was at 15%
and is the path **every ordinary package type** takes - pypi, npm, maven, rpm,
nuget, gems, debian. Docker and generic had characterization tests; the one
covering the other seven did not. Its tests run each type through `process()` and
assert the type's own mangler is the one reached, because this is the only
`process()` whose result depends on which type the repository is.

`main.py` went from 0%: the four exit codes (0, 101, 102, 103), that a bad
invocation prints to stderr and never starts the run, that an unexpected error is
logged with its traceback while a Ctrl-C is not, and that `requests` and
`urllib3` are quietened.

What is deliberately not chased: `artifactory_file_processor_common.py` at 32%
and `artifactory_api.py` at 45% are mostly http and upload plumbing. The decision
logic inside them - property writing, the recursive cap fallback, digest
verification, report hashes - is covered by its own tests; the rest is
`requests` calls whose behaviour is the library's, not ours.

### A.11 Functions that are never called — done


All fourteen were deleted. The check itself stays: `tools/find_dead_code.py`,
run by `make dead-code`, fails on anything unreachable that does not document
itself with a `NOT CALLED` docstring.

Deleted: `_request_patch`, `list_file_info`,
`_get_item_properties_by_repo_name`, `get_one_prop`, `get_tags_docker`,
`PurlInfo.from_purl`, `get_prop_scan_status`, `get_ptype`,
`_is_portal_and_remote_and_no_reports_location_specified`, `get_tree_items`,
`_version_string`, `_inspect_purl`, `set_bundle_name`, `set_docker_image_name`.
`ProxyInfo.get_proxy_info` and `ProxyInfo._set_proxy` went earlier, with the
credential work.

### A.12 Constants that are never used — done


`SPECTRA_ASSURE_HOST_URL`, `SECURE_SOFTWARE_URL`,
`SECURE_SOFTWARE_COMMUNITY_PACKAGE_TYPES` and `SECURE_SOFTWARE_HEAD_TIMEOUT`
were deleted. `SPECTRA_ASSURE_HOST` and `SPECTRA_ASSURE_HOST_BASE` remain: both
are still read.

### A.14 `self.steps` is write-only — done


Removed: the dict, its 37 assignments and the four `STEP_*` constants. Nothing
read it, so nothing changed behaviourally; `ArtifactoryFileProcessorCommon` and
the three type processors are that much shorter.

The lookalike string that caused D27 went with it. `portal_upload_ok` now exists
nowhere in the repository, and `tests/test_progress_vocabulary.py` asserts it
does not come back.

**What the removal exposed.** The ordering question filed here is now visible on
its own line. In `docker.process`:

```python
progress = self.get_prop_progress()
if progress in PROGRESS_ALL:
    self.processing_info.scan_state = progress      # from the stored property

    if self.cli_args.get("ignore_artifactory_properties") is False:
        ...
```

A run told to ignore the stored properties still takes `scan_state` from them,
so the reported scan state of a re-scanned item can be inherited from the
previous run. The generic and default processors do not have this: their
`ignore_artifactory_properties` check comes first, with nothing before it. Only
the docker path reads a property before consulting the flag.

Not fixed here, because it changes what a `--sync` run reports: today such a run
shows the previous scan state until the new scan overwrites it, and with the
assignment moved inside the flag check it would show nothing until then. Decide
which is wanted, then move the line.

### A.15 Complexity — done


Nothing in the package exceeds **complexity 10**, and `C90` is now selected in
`pyproject.toml` with `max-complexity = 10`, so a function that grows past it
fails `make` rather than being noticed a year later.

| Function | Was | Now |
|---|---|---|
| `docker.process` | 18, 184 lines | under 10, 57 lines |
| `_run_one_repo_all_artifacts` | 14 | under 10 |
| `generic.process_portal` / `process_cli` | 12 each | under 10 |
| `do_cli_after_download` | 12 | under 10 |
| `artifactory_report_url_needs_space` | 12 | under 10 |
| `mandatory_repo` | 11 | under 10, as a by-product of R12.5.0.x |

Each split followed the same order: characterization tests first, then the
restructure, with the tests passing unchanged. That is the whole method - the
tests are what make the restructure a safe, boring change rather than a careful
one.

Two of them were worth more than the complexity number:

- `do_cli_after_download` had the report destination rule buried in the middle
  of it: a remote repository cannot take an upload, so its reports go to
  `--cli-reports-repo` under a path made from the purl. That is
  `_report_destination()` now, and says so.
- `artifactory_report_url_needs_space` was a hand written triple compare with a
  `SpectraAssureInvariantError` after each step. It is a tuple comparison against
  `REPORT_URL_SPACE_UNTIL`, and the 13 boundary tests written for the old one
  passed against the new one unchanged.

### A.20 `scan_state` ordering in docker — done

`docker.process` set `processing_info.scan_state` from the stored `RL.progress`
**above** the `--ignore-artifactory-properties` check, so a `--sync` run carried
the previous verdict, the one the sync exists to replace. Generic and default
did not: their flag check comes first. The assignment now sits below the check,
in the two branches that act on the stored value: an already-scanned artifact
that stops there, and an uploaded one still waiting for its scan.

`scan_state` is read in one place only, the verbose per-item line in `my_app.py`
(`scan_status: ...`), so this changes what is printed and nothing else. The stale
value survived only where no later step overwrote it - a failed portal upload,
or a cli sync found to be about other bytes - since a timeout or an absent
version resets it to `None`.

Fixing it showed a second wrong report in the same function. An artifact
scanned more than 14 days ago, with the properties *not* ignored, is synced
rather than skipped (`need_sync_datetime`), but it fell through to the reason
`uploaded but no scan result yet`, and carried the stored verdict too. The portal
path overwrites the reason when the purl is on the portal (`portal-sync`) and the
cli path always does, but when the purl is gone from the portal the artifact is
uploaded again and the wrong reason stayed to the end of the run. That branch now
returns with its own reason and no `scan_state`.

**User visible change:** in verbose output, a `--sync` item that does not finish
in the run shows no `scan_status` rather than the old verdict, and a sync by age
says so in its reason.

### A.21 A rebuilt artifact could never be uploaded — done

R10.7.1 compares the digest so that an artifact rebuilt under the same version
is scanned again. `exist_version` did notice the mismatch, but answered it as
"does not exist", and `_exists_on_portal` read only that boolean. Everything
after it saw an absent version and uploaded without `replace`, which the Portal
refuses with a 409. So the comparison bought nothing: the artifact was skipped
as "no upload to portal", on every run.

`exist_version` now answers three states (R10.7.5), `_exists_on_portal` keeps the
third in `portal_has_other_bytes`, and `_do_one_portal_upload` passes it on as
`replace`. Only that answer asks for a replace, so an absent version is never
overwritten by accident.

Fixing it changed one more answer. A version with no `sha256` among its hashes
used to count as a mismatch too. That was harmless while a mismatch only led to
a refused upload, but with `replace` it would re-upload a version whose scan is
still running. It now counts as present, with nothing to compare (R10.7.6).

**User visible change:** under `--ignore-artifactory-properties` or `--sync`, a
default artifact whose bytes differ from the version on the Portal is uploaded
and replaces it, where before its upload failed. See A.22 for the ordinary run.

**Verified live** on 2026-10-27 with `tools/verify_rebuild.sh` (portal backend,
a pypi wheel and a generic file): the portal accepts `replace=true` for a version
that holds other bytes, scans the replaced version again (`pass`), and afterwards
holds the new bytes - a run with the properties ignored no longer sees a digest
mismatch. No 409 in any run.

### A.17 The generic path offered no digest to compare — done

Generic passed `digest=None` to `exist_version()`, so a generic artifact was
taken as already scanned on its purl alone, though it is a single file with a
real hash. That was structural rather than accidental: for generic,
`self.file` is the `.rl_meta` side-car, and its `sha2` is the hash of the
side-car. Passing that would have been worse than passing nothing.

Two values were candidates. `generic._derived_.sha256`, the digest the publisher
declares in the side-car, is optional (R7.4). The `sha2` Artifactory holds for
the described file is authoritative, and it is free: the repository listing
(`?list&deep=1`) already carries it, but `extract_my_interesting_files` kept only
the `.rl_meta` entries for generic and dropped it. It is also what the Portal
records, the hash of the bytes uploaded.

`ArtifactoryRepoProcessor` now keeps `sha2_by_uri` for every file the listing
holds, the generic pre pass stores the described file's hash in its `repo_db`
entry, and `_process_portal` passes it (R10.7.4). It needed A.21 first: before
that a mismatch could only end in a refused upload.

**User visible change:** a generic artifact rebuilt under the same version is
now compared with the Portal, and uploaded again to replace the version
(R10.7.5), under `--ignore-artifactory-properties` or `--sync`. An ordinary run
still skips it on its properties, as for default (A.22).

### A.16 The cli backend: the scan directory leaked — done

`py_cli_scan` had never been reviewed before the round that opened this. The
secret handling, the `--pull` flag, the result names and the error logging were
fixed and tested then (R12.6.x), and `ScanCliBase.results` with its `Results`
class went, since nothing read them.

Two items were left open, and neither was what it said:

- **"`ScanCliBase.__del__` raises `AttributeError` when construction fails
  partway."** It could not: the constructor set `temp_dir = None` before
  anything that can raise, and both subclasses call it first. Trying every
  failure the constructor has showed nothing raised from `__del__`.
- **"`scan_cli_file.py` is at 19%."** True, under a wrong path: the file is
  `rl_scan_artifactory/scan_cli_file.py`, not part of `py_cli_scan`.

Looking at both found two real faults instead:

- **`cleanup_temp_dir()` never removed what it made.** `_make_temp_dir()` set
  `clean = False`, and the last line of the constructor set it back to `True`,
  so the cleanup always returned early and the directory was left to the
  `TemporaryDirectory` finaliser (with a `ResourceWarning`). The path was dead in
  production, because `ScanCli` always passes a directory of its own, so it was
  removed rather than repaired: the scanner now requires a directory and owns
  none, and `__del__`, `cleanup_temp_dir`, `temp_dir` and `clean` are gone.
- **A directory leaked for every artifact whose cli scan raised.** `ScanCli`
  makes one with `mkdtemp()` per scan, which is never removed on its own, and
  `cleanup()` ran only on the normal paths of `do_cli_after_download`. An
  exception from the scanner, from the store check made after `mkdtemp()`, or
  from the report upload skipped it, and was then contained per artifact while
  the run went on. `cleanup()` also refused to run without a scanner, so it could
  not simply have been moved. It now runs in a `finally` and is safe in every
  state (R12.6.7).

`tests/test_scan_cli_file.py` covers `ScanCli` and the `finally`;
`scan_cli_file.py` went from 19% to 89%, and `scan_cli_base.py` from 42% to 57%
by losing the dead path.

### A.22 A stored `RL.progress` outranked a digest mismatch — done

An ordinary run skipped an artifact whose `RL.progress` said `scanned`, in two
places. `process()` skipped it before the portal was asked anything when the
last scan was 14 days old or less; past that, `_process_portal` asked, heard
"other bytes" (R10.7.5), read `RL.progress` again and skipped it as already
scanned. So the replace of A.21 only ever happened under
`--ignore-artifactory-properties` or `--sync`.

Whether that bit for default depended on artifactory keeping an item's
properties across a redeploy to the same path, which was not verified then. For
generic it always bit: a later run reads `RL.progress` from the side-car, and
redeploying only the file it describes leaves that alone.

Three answers were weighed. Trusting the properties (and documenting that a
rebuild needs `--sync`) cost nothing and missed rebuilds silently. Asking the
portal about every scanned item would have let "other bytes" win, at one or two
portal calls per item on every run, unchanged repositories included, and for the
portal backend only. The one taken records which bytes the properties are about,
`RL.sha256`, and compares it with the hash artifactory holds now, which the
listing gives for free (R10.8). It needs no call, works for both backends, and
does not depend on what artifactory does with properties on a redeploy.

The comparison lives in `get_prop_progress()`, through which every skip on the
properties reads, rather than beside each of the four. Generic reads its
properties before it reads the side-car, so the pre pass now also maps each
side-car to the file it describes. Docker records no hash: what it scans is a
bundle it assembles.

**User visible change:** a rebuilt artifact redeployed under the same path is
scanned again in an ordinary run, and on the portal replaces its version. Items
scanned before `RL.sha256` existed keep their old behaviour until their next
scan writes it.

**Verified live** on 2026-10-27 with `tools/verify_rebuild.sh` (portal backend):

- **pypi:** redeploying a wheel to the same path **dropped** its `RL.*`
  properties, so a rebuilt default artifact is treated as new even without
  `RL.sha256`; for pypi at least, the skip described above never happened, and
  only the portal side (A.21) was missing. Other package types were not tried.
- **generic:** the side-car **kept** `RL.progress=scanned` when only the described
  file was redeployed, as expected. `RL.sha256` caught it (`rebuilt since the
  last scan`), the version was replaced, and the next run skipped it again.
  Without `RL.sha256` this rebuild would have been skipped.
