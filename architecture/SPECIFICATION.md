# rl-scan-artifactory — derived specification

Reconstructed from the code as it stands, not from a design document. Where the
code and the prose in the source disagreed, the disagreement was recorded rather
than silently resolved; those are in `DECISIONS.md`, and none are open.

The executable form of this document is `tests/`. Every numbered rule has at
least one test, and a rule the code does not satisfy would carry an
`xfail(strict=True)` test so it turns red the moment it starts passing.

**Current state: 1098 passing tests, no xfails, no open deviations.** `make all`
also checks formatting, types (`mypy --strict`), complexity (nothing above 10),
unreachable code and spelling. §11 lists the Artifactory endpoints used, for
checking against the official OpenAPI reference.

What the unit tests cannot show - a real Artifactory, rl-secure, the
rl-scanner image and the Portal together - is covered by `livetest/`: one
`run.sh all` per development step, with `check.py` comparing every item against
the expected result in `livetest/README.md`, rule by rule.

---

## How to read this

Every **R-number** is normative: it says what the program does, and it is the
thing to check against the code. Everything else — the diagrams in §3, the prose
around the rules, the tables of examples — explains or illustrates them.

So when an illustration and a rule disagree, **the rule wins** and the
illustration is stale. Fixing the illustration is then the job; changing a rule
to match a picture is not.

Starting cold, §3 is the fastest way in: the four diagrams give the shape of a
run in a couple of minutes, and the rules make sense afterwards in a way they do
not before.

What was tried, what went wrong, and what is still open lives in `DECISIONS.md`.
None of it is needed to work on the code.

## 1. Purpose

Walk one or more Artifactory repositories, decide which items are scannable
artifacts, derive a stable Spectra Assure package URL for each, scan it (Portal
or CLI backend), and write the outcome back onto the Artifactory item as
properties.

## 2. The purl

Every artifact is identified on the Portal by three components:

```
<project>/<package>@<version>
```

| Component | Source |
|---|---|
| `project` | the Artifactory repository name, optionally extended with a `_<remainder>` suffix |
| `package` | the package name, sometimes `<namespace>_<name>` or `<namespace>.<name>` |
| `version` | the package version, for rpm extended with the release |

### 2.1 Why the remainder moves to the project

The same name and version can exist for several architectures and build
environments (`x86_64` vs `aarch64`, `py3-none-any` vs `cp311-manylinux`). If
those all mapped to one purl, Portal version-to-version diffs would compare
unrelated binaries. So the architecture and build tags are lifted out of the
file name and appended to the **project**, keeping each build line separately
diffable.

### 2.2 Component escaping

**R2.2.1** No purl component may contain `/`, `@` or `%`.
**R2.2.2** Escaping is `urllib.parse.quote_plus`, then `%` → `0x`. So `:` becomes
`0x3A`, a space becomes `+`, `/` becomes `0x2F`.
**R2.2.3** Escaping is applied at the end of `make_long()`, to all three
components.

## 3. The flow

Two views of the same thing. The diagrams below show the decisions — which
artifacts are looked at, and what is done with each. The stage pipeline after
them shows the data: what each artifact is turned into on the way to a purl.

One diagram for all 72 decision points would be unreadable, so there are four,
outermost first; each ends where the next begins and says which one. Every branch
is pinned by a test, and each diagram names the functions it draws and the tests
that hold them: a diagram that stops matching the code is a diagram someone
changed without changing the tests.

**These diagrams are not normative.** They are drawn from the rules in §4 to §13
and from the tests, and nothing enforces that they stay in step. Read them for
the shape of a run; check behaviour against the R-numbers and the tests. If one
contradicts a rule, the diagram is the thing that is wrong.


### 1. A run: repositories

```mermaid
flowchart TD
    start([rl-scan-artifactory]) --> args[read options:<br/>command line, then environment]
    args --> valid{every mandatory<br/>setting present?}
    valid -- no --> fatal([exit 101<br/>names all that are missing]):::stop
    valid -- yes --> backend{which backend?}

    backend -- portal --> vportal[verify server, org, group]
    backend -- cli --> vcli["rl-secure --version<br/>rl-secure list --rl-store"]
    vportal --> loop
    vcli -- not usable --> fatal
    vcli -- usable --> loop

    loop[for each --repo] --> cfg{configuration<br/>readable?}
    cfg -- no --> skip1[REPO SKIP<br/>does not exist or not readable]:::skip
    cfg -- yes --> rtype{type is<br/>local or remote?}
    rtype -- no --> skip2[REPO SKIP<br/>unsupported type]:::skip
    rtype -- yes --> ptype{package type<br/>supported?}
    ptype -- no --> skip4[REPO SKIP<br/>unsupported package type]:::skip
    ptype -- yes --> glayout{gradle: the maven-2-default<br/>layout?}
    glayout -- no --> skip5[REPO SKIP<br/>unsupported gradle layout]:::skip
    glayout -- "yes, or not gradle" --> cliok{cli, and the reports<br/>have somewhere to go?}
    cliok -- no --> skip3[REPO SKIP<br/>verbose only]:::skip
    cliok -- yes --> pre{package type?}

    pre -- generic --> preg[pre pass:<br/>collect every .rl_meta]
    pre -- docker --> pred[pre pass:<br/>collect every list.manifest.json]
    pre -- other --> items
    preg --> items
    pred --> items

    items[for each artifact] --> tail{a report bundle<br/>we uploaded?}
    tail -- yes --> next[next artifact]
    tail -- no --> item[["2. one artifact"]]
    item --> limit{development limit<br/>reached?}
    limit -- no --> next
    limit -- yes --> done
    next --> items

    skip1 --> loop
    skip2 --> loop
    skip3 --> loop
    done([summary, then exit<br/>0, or 103 if anything was skipped])

    classDef stop fill:#fdd,stroke:#900
    classDef skip fill:#ffd,stroke:#960
```

`my_app.py` — `run_all`, `_why_skip_this_repo`, `_process_repo_items`.
Tested in `test_run_one_repo.py`, `test_my_args.py`, `test_main_exit_codes.py`.

The four skip reasons differ in one way worth knowing: the two about the
repository are always printed, the two about how the run was invoked only with
`--verbose`, because a run over many repositories would otherwise repeat them.

---

### 2. One artifact: is it a candidate, and what does the purl look like

```mermaid
flowchart TD
    start([one artifact]) --> props[read its artifactory properties]
    props --> noscan{RL.noscan?}
    noscan -- yes --> skipn[skip: it is one of our own reports]:::skip
    noscan -- no --> type{package type}

    type -- "docker" --> d1{manifest.json?}
    d1 -- "list.manifest.json" --> skipl[skip: read by the pre pass]:::skip
    d1 -- "anything else" --> skipo[skip: not relevant]:::skip
    d1 -- "manifest.json" --> earlier

    type -- "generic" --> g1[purl from the .rl_meta side-car,<br/>else the RL.meta.* properties,<br/>else portal skips, cli uses the file name]
    g1 --> earlier
    type -- "everything else" --> n1[purl from the name mangler<br/>for that package type]
    n1 --> earlier

    earlier{RL.progress says<br/>scanned or uploaded?} -- no --> go
    earlier -- yes --> ignore{--ignore-artifactory-properties<br/>or --sync?}
    ignore -- yes --> go
    ignore -- no --> scanned{scanned?}
    scanned -- "no, uploaded only" --> go
    scanned -- yes --> stale{last scan<br/>older than 14 days?}
    stale -- no --> skipa[skip: already scanned<br/>reports the stored result]:::skip
    stale -- yes --> nosync{cli-docker, or the generic<br/>cli placeholder purl?}
    nosync -- yes --> skipn[skip: already scanned<br/>never synced]:::skip
    nosync -- no --> sync[sync instead of scan]
    sync --> go

    go{backend?}
    go -- portal --> p[["3. the portal"]]
    go -- cli --> c[["4. the cli"]]

    classDef skip fill:#ffd,stroke:#960
```

`process()` in each of the three processors.
Tested in `test_docker_process.py`, `test_generic_process.py`,
`test_default_process.py`, `test_file_properties.py`.

Docker cannot skip the download even when the answer is "already scanned": the
purl needs the architecture, the architecture is in the config blob, and the
config blob is only reachable by downloading the manifest and following it.

For generic in **cli** mode without a side-car or `RL.meta.*` properties the purl
is the placeholder `<repo>/<file name>@v0`. It names a file, not a package
version, so it is never synced - there and only there (R7.11.6).

---

### 3. The portal

```mermaid
flowchart TD
    start([portal]) --> exists{does the portal have<br/>this purl, and this sha256?}

    exists -- "yes, same digest" --> sync{sync asked for?}
    sync -- no --> report[report the stored result]:::done
    sync -- yes --> dosync[ask the portal to re-analyse]
    dosync --> wait

    exists -- "no, or a different digest" --> upload[upload the artifact]
    upload -- failed --> fail[skip: upload failed]:::skip
    upload -- ok --> wait

    wait[poll for a scan status] --> answer{the portal answers}
    answer -- "a verdict" --> write[write RL.* back<br/>progress, status, report, purl, timestamp]:::done
    answer -- "not finished" --> wait
    answer -- "404, three times" --> absent{already uploaded<br/>in this run?}
    absent -- no --> upload2[upload it now:<br/>what artifactory recorded<br/>was not about this portal]
    upload2 --> wait
    absent -- yes --> park[timeout: left for a later run]:::skip
    answer -- "time is up" --> park

    classDef done fill:#dfd,stroke:#090
    classDef skip fill:#ffd,stroke:#960
```

`_process_portal` in each processor, `_wait_for_scan_status_one_portal` in the
common one. Tested in `test_portal_wait.py`, `test_spectra_assure_api.py`.

The digest comparison is skipped for **docker**, whose upload is a bundle this
integration assembles, so artifactory holds no hash of it to compare against.

The 404 path is the one to read twice. `RL.progress` does not record which
backend wrote it, so a `scanned` left by a cli run makes a portal run believe the
artifact is already there; the portal saying "no such version" three times is
what settles it.

---

### 4. The cli

```mermaid
flowchart TD
    start([cli]) --> syncq{sync asked for,<br/>and not docker?}
    syncq -- no --> down
    syncq -- yes --> instore{is the purl<br/>already in the store?}
    instore -- no --> down
    instore -- yes --> dosync[sync from the store<br/>nothing downloaded]
    dosync --> reports

    down[download the artifact] -- failed --> fail[skip: download refused<br/>403 means blocked, not broken]:::skip
    down -- "digest mismatch" --> fail2[skip: not what artifactory said]:::skip
    down -- ok --> scan[rl-secure scan]
    scan --> reports[generate the reports<br/>rl-json always, for the digest]

    reports --> synced{was this a sync?}
    synced -- no --> upl
    synced -- yes --> same{does the report's sha256<br/>match artifactory's?}
    same -- "yes, or unknown" --> upl
    same -- no --> down

    upl[upload the report bundle] -- failed --> failu[this artifact fails<br/>the run continues]:::skip
    upl -- ok --> write[write RL.* back]
    write --> tag[tag the report: RL.noscan only]:::done

    classDef done fill:#dfd,stroke:#090
    classDef skip fill:#ffd,stroke:#960
```

`do_cli_scan_or_sync` and `do_cli_after_download` in the common processor.
Tested in `test_report_hashes.py`, `test_scan_cli_local.py`,
`test_scan_cli_docker.py`, `test_run_containment.py`.

The digest is checked **after** the sync, from the report the sync produced
anyway: a matching digest is the ordinary case and costs nothing, while checking
first would cost a report generation on every artifact.

`unknown` counts as a match on purpose — no report, an unreadable one, or no
`sha2` in artifactory all mean "cannot tell", and doing the full work again on a
guess is worse than trusting the sync.

---

### The stages, per item

```
per repository, before the main loop:
    generic → collect every .rl_meta side car      (R12.1)
    docker  → collect every list.manifest.json     (R12.2)

then, per item:

ArtifactoryApi.list_repo_items
        │  FileInfo(uri, sha1, sha2, repo, last_modified)
        ▼
FileProperties<type>          ── fetch or derive Artifactory properties
        │  file.properties: dict[str, list[str]]
        ▼
SimpleData<type>              ── normalise to name / version / arch / release / namespace
        │  file.simple: dict[str, list[str]]
        ▼
NameMangler<type>.make_long() ── project / package / version
        │
        ▼
download + sha256 verify → scan (Portal or CLI) → write properties back
```

**R3.1** Artifactory property values are always lists, and that shape is
preserved through `file.properties` and `file.simple`. Consumers index `[0]`.
**R3.2** A purl component may never be empty. `NameManglerCommon` refuses a
`name` or `version` that is absent, an empty list, or an empty string, naming
the key and the uri. An empty component would create a project on the Portal
that no later build of the same artifact can ever match.
**R3.3** Proxy credentials are all or nothing: either both a `user` and a
`password`, or neither. Half a credential is refused whichever half is missing,
and the refusal does not echo the password. It used to format the missing half
into the proxy url verbatim, as `http://user:None@host:port`, and send that.

## 4. Stage: FileProperties

**R4.1** Each package type has a `skip_non_candidate_file()` that returns `True`
for items that are not scannable artifacts (checksum side-cars, `.pom`, `.nuspec`,
docker blobs …).
**R4.2** An item whose simple data has no *usable* `name` or `version` is
skipped. Usable means present and non-empty: a missing key, an empty list, and a
list whose first element is `""` all fail the test, because each would put an
empty component in the purl.
**R4.3** Skipping sets `file.simple = {}`.

Per type:

| Type | Candidate test | Properties |
|---|---|---|
| default | any file with `<ptype>.name` and `<ptype>.version` | read from Artifactory |
| nuget | uri ends with `nupkg` | read from Artifactory; `nuget.id` is the name |
| maven | uri ends with `jar` | **derived from the uri**, Artifactory has none |
| gradle | as maven (R4.1.7) | as maven, stored under `gradle.` |
| rpm | any | read; if `rpm.metadata.name`/`.version` are absent, `touch_rpm_info_uri()` then re-read |
| docker | uri ends with `manifest.json` | read; name/version come from `docker.repoName` / `docker.manifest`, and are also derived from the uri as a fallback (R4.3.x) |
| generic | governed by a `.rl_meta` side-car file or `RL.meta.*` properties | read, for every file in either mode (R7.11.5); **nothing is derived**, because a generic repository has no layout to derive from — see §7 |

### Maven uri layout (R4.1.x)

For `/<namespace path>/<name>/<version>/<file>.jar`:

**R4.1.1** `version` is the second-to-last path segment.
**R4.1.2** `name` is the third-to-last path segment.
**R4.1.3** `namespace` is everything before that, `/` joined as `.`.
**R4.1.4** A leading empty segment (uri starting with `/`) is dropped, so the
leading `/` is optional.
**R4.1.6** After that, the uri must have at least four segments and none of them
may be empty: `<namespace...>/<name>/<version>/<file>` is the shortest layout
that carries all of them, and a maven artifact always has a groupId. A uri that
does not match is logged and skipped, leaving `file.properties` untouched so the
item fails the R4.2 candidate test.
**R4.1.5** The derived properties are stored under
`maven.<DERIVED_PROPERTY_INFIX>.*`, with both `.name` (namespace-qualified) and
`.name_only`. `DERIVED_PROPERTY_INFIX` is `_derived_`, defined once in
`constants.py`: every producer and consumer of a derived property must use it,
or the two spellings drift apart and the property is silently never read.

Example: `/org/apache/logging/log4j/log4j-api/2.12.1/log4j-api-2.12.1.jar`
→ namespace `org.apache.logging.log4j`, name `log4j-api`, version `2.12.1`.

**R4.1.7** A `gradle` repository is read exactly as maven (same candidate test,
same parser, same name mangler), with the derived properties stored under
`gradle.<DERIVED_PROPERTY_INFIX>.*` so simple data, which reads properties by
package type (R5.1), finds them. Its layout (`repoLayoutRef`) must be
`maven-2-default`, the one Artifactory gives a gradle repository by default
(groupId as folders, `org/apache/logging/log4j/...`), so the same artifact gets
the same purl as in a maven repository. Any other layout is a `REPO SKIP`
naming the layout and the supported one, always printed: `ivy-default` puts a `[type]s` folder before the
file, which the parser would take for the version. Maven repositories are not
checked for their layout, as before.

### rpm property recovery (R4.2.x)

**R4.2.1** rpm metadata is only materialised by Artifactory after the rpm info
tab is visited. When the properties are missing, the tool simulates that visit
and re-reads. This is issue [#314540].

### Docker uri layout (R4.3.x)

For `/<org>/<name>/<version>/manifest.json` (a local repo may have no `<org>`):

**R4.3.0** The leading `/` is optional, and the uri must have at least three
non-empty segments: `<name>/<version>/<manifest json>` is the shortest layout
carrying both a name and a version. A uri that does not match is logged and
skipped, leaving `file.properties` untouched.
**R4.3.1** `version` is the segment before `manifest.json`.
**R4.3.2** `name` is the segment before that, prefixed with `<org>/` when an
org segment is present.
**R4.3.3** The derived properties are stored under
`docker.<DERIVED_PROPERTY_INFIX>.name` and `.version`.

## 5. Stage: SimpleData

**R5.1** A property matches when its key starts with `<property prefix>.` and
ends with one of the known suffixes. An arbitrary middle component is allowed,
which is what makes `rpm.metadata.name` and `maven._derived_.name` both work.

**R5.2** Suffix map: `.name` → name, `.id` → name (nuget), `.version` → version,
`.arch` → arch (rpm), `.release` → release (rpm), `.namespace` → namespace (maven, gradle).

**R5.3** The repository package type is translated to the property prefix where
they differ: `debian` → `deb`, `gems` → `gem`.

**R5.4** maven and gradle only extract from `.jar` files; anything else yields `{}`.

**R5.5** docker only extracts from `manifest.json`; anything else yields `{}`.
`docker.repoName` → name, `docker.manifest` → version.

**R5.6** A docker manifest property holding a `sha256:` digest is a digest, not
a version, and must be cleared to `[""]` (keeping the list shape of R3.1).

**R5.7** docker then falls back to the properties derived by R4.3.x: for `name`
and `version`, if the value taken from Artifactory is absent or empty, the
`docker.<DERIVED_PROPERTY_INFIX>.<name>` value is used instead. An Artifactory
property that *is* usable always wins. This covers both a local repo with no
`docker.repoName` / `docker.manifest` at all, and the digest case above.

## 6. Stage: NameMangler

**R6.1** Input is the file name (`pathlib.Path(uri).name`) plus the name and
version from simple data.
**R6.2** `_mangle()` removes the known parts (extension, name, version, release,
arch) and returns the **remainder**.
**R6.3** A non-empty remainder is appended to the project as `<repo>_<remainder>`.
An empty remainder leaves the project as the bare repository name.
**R6.4** Mangling is deterministic: same input, same purl.

### 6.1 String helpers

**R6.1.1** `_remove_connector_front_and_back` strips any run of `-`, `_` and `.`
from both ends.
**R6.1.2** `_remove_substring(str1, str2, what)` accepts `all`, `front`, `tail`,
`mid`; anything else raises `RuntimeError`.
**R6.1.3** Substring matching is case-insensitive.
**R6.1.4** If `str1` and `str2` are equal (ignoring case), the result is empty.
**R6.1.5** Every helper re-strips connector characters before returning.

### 6.2 Per type

| Type | Strips | Remainder |
|---|---|---|
| default, docker | — | whatever is left after name and version |
| debian | `.deb` | arch / build tag |
| gems | `.gem` | arch / platform (e.g. `x86_64-linux`) |
| pypi | `.whl` | wheel tags (e.g. `py3-none-any`) |
| npm | `.tgz` | scoped `@ns/name` becomes `ns_name` |
| generic, maven | — | always empty: project stays the bare repo name |
| rpm | `.rpm`, arch, name, version, release | `<leftover>_<os_release>_<arch>` |

### 6.3 rpm release handling

An rpm release such as `100.el9_4.3` carries two things: the numeric release and
the build platform.

**R6.3.1** A release made only of digits, dots and dashes is returned verbatim
with no platform part. A release is a string, not a number, so leading zeros are
preserved: `007` stays `007`, and `1.2` stays `1.2`.
**R6.3.2** Otherwise the segment after the first `.` is the platform, if it is
non-empty and starts with a letter (`el9`, `el9_4`, `fc40`). An empty segment,
as in `1..el9`, has no first character and yields no platform.
**R6.3.3** The platform segment is removed from the release; the rest is rejoined:
`100.el9_4.3` → platform `el9_4`, release `100.3`.
**R6.3.4** The platform and arch go to the project; the remaining release is
appended to the version as `<version>-<release>`.

Example: `glibc-gconv-extra-2.34-100.el9_4.3.i686.rpm`
→ `my-repo_el9_4_i686/glibc-gconv-extra@2.34-100.3`.

## 7. Generic repositories and `.rl_meta`

A generic repository has no package metadata, so a side-car file supplies it.
The live implementation is `ArtifactoryFileProcessorGeneric`; the separate
`GenericMeta` / `GenericMetaReader` module was never wired up and is commented
out, so nothing in this section refers to it.

**R7.1** The side-car must end with `rl_meta` (case-insensitive) or it is ignored.
**R7.2** It is an ini file and must contain an `[rl_meta]` section, or it is
ignored. It is read with interpolation disabled: a side-car is data, not a
template, and `configparser`'s default would raise `InterpolationSyntaxError` on
any value containing a `%`.
**R7.3** Mandatory keys: `name`, `version`, `path`. A side-car missing any of
them, or holding an empty value for one, raises `SpectraAssureInvalidAction`.
**R7.4** Optional keys: `architecture`, `namespace`, `sha256`. An absent optional
key reads as `None`.
**R7.5** Unknown keys are ignored.
**R7.6** Every key that the side-car supplies is mirrored into `file.properties`
under `generic.<DERIVED_PROPERTY_INFIX>.<key>`, with `architecture` stored as
`.arch` to match the rpm naming. Values are `list[str]` like every other
property (R3.1); a key the side-car did not supply gets no property at all,
rather than a `None` or an empty list. The meta dict itself still records the
absence as `None`, because R7.3 has to tell "missing" from "empty".
**R7.7** Only the purl components are made purl safe: `name`, `version`,
`architecture` and `namespace`. `path` is a repository path and `sha256` a
digest, and both are used verbatim — sanitising them would break the lookup of
the very file the side-car describes.
**R7.8** The resulting purl is
`<repo>[-<architecture>]/[<namespace>-]<name>@<version>`, with the optional
parts omitted when the key is absent.

### Escaping and separators here differ from §2.2 and §6 (R7.9.x)

Both differences are accidents rather than decisions, but resolving either moves
every generic purl to a new project on the Portal. They are therefore behind two
constants in `constants.py`, both `False`, flipped on a release boundary and not
exposed to customers: a switch someone can forget to set would produce a
half-migrated Portal, which is worse than either scheme.

**R7.9.1** `FUTURE_GENERIC_PURL_ESCAPE` off (today): only `@` → `0x40` and
`/` → `0x2F` are escaped, so a space, a `%` or a `:` reaches the purl verbatim.
On: the name manglers' escaper of R2.2.2 is called directly rather than
reimplemented, so the two cannot drift once it is on.
**R7.9.2** `FUTURE_GENERIC_PURL_SEPARATOR` off (today): the architecture and the
namespace are joined with `-`. On: with `_`, as the name manglers join the
project remainder and the npm namespace.
**R7.9.3** The two are independent: either may be on without the other.
**R7.9.4** `%` is the escape character of a purl component, so the old scheme
leaving it raw is a defect and not merely a difference. R2.2.1 (`/`, `@` and `%`
may not appear) holds fully only with R7.9.1 on; `/` and `@` are escaped either
way.
**R7.9.5** When both are on by default and no supported version still produces
the old purls, the flags and the old branches are deleted.

**R7.10** In portal mode the `.rl_meta` side-car is how a generic artifact is
**found**, never what is **scanned**: the scan is of the file its `path` names.
So the full `RL.*` result — status, report, purl, org, group — is written to that
file, and the side-car keeps only `RL.progress`, `RL.timestamp` and `RL.sha256`.

Those are what it needs to carry: `RL.progress` is what a later run reads to
know the work is done, and the side-car is the item that run will look at;
`RL.sha256` says for which bytes of the described file (R10.8). A scan
verdict on a side-car would say that the side-car passed or failed, which is not
a thing that was ever scanned.

A cli run scans the file itself, so `self.uri` is already the artifact and the
full set goes there (minus the two portal-only properties, R10.6).

**R7.10.1** After a cli scan or sync that produced a result, the file's
`.rl_meta` side-car, when the generic pre pass found one, also gets a new
`RL.timestamp`, so it shows when the file was last handled by either backend.
Only that property: `RL.progress` and `RL.sha256` on a side-car are a portal
run's, which reads them to decide whether to skip (R10.8), so a cli run leaves
them as they are. A run that skipped or failed the file writes nothing there.

### Purl data as properties instead of a side-car (R7.11.x)

A side-car has to be created and deployed next to every artifact. A person may
instead set the same data as properties on the artifact itself.

**R7.11.1** A generic file may carry its purl data as properties:
`RL.meta.name` and `RL.meta.version` (mandatory), `RL.meta.namespace` and
`RL.meta.architecture` (optional). The first value of each is used. They make
the purl exactly as the side-car keys of the same name do: same escaping and
separators (R7.7, R7.9), same shape (R7.8). `path` and `sha256` have no property:
the file is the one the properties are on, and Artifactory holds its hash. Any
other `RL.meta.*` name is ignored.
**R7.11.2** A side-car wins. A file the generic pre pass found a side-car for
(R12.1) gets its purl from the side-car, and its `RL.meta.*` properties are
ignored; in portal mode the file is skipped as an item of its own, because it is
handled when the run reaches its side-car. `RL.meta.*` on a side-car itself is
ignored too.
**R7.11.3** A file with any `RL.meta.*` property but without a non-empty
`RL.meta.name` or `RL.meta.version` raises `SpectraAssureInvalidAction` naming
the missing properties, in either mode, like an incomplete side-car (R7.3). The
item is then a failed item (R12.3) and the run exits `103` (R12.4); it is
neither skipped quietly nor given the cli placeholder purl. As for a side-car,
the check is made when the purl is needed: an item that stops earlier, because
an earlier run recorded it as scanned (R10.2), reports that result and raises
nothing. A cli item that is due for a sync (R12.7.3) needs its purl, so there
the incomplete set raises.
**R7.11.4** In portal mode a file with `RL.meta.*` properties and no side-car is
a candidate, and it is both what is found and what is scanned: it is downloaded,
verified against its own `sha2`, uploaded, and the full `RL.*` result is written
on it, as for any other package type. Its own `sha2` is the digest asked of the
Portal (R10.7) and recorded as `RL.sha256` (R10.8). A sync works as for a
side-car.
**R7.11.5** So that its properties can be read, every file in a generic
repository is listed and inspected in either mode; there is no file name filter
for generic. In portal mode a file with neither a side-car nor `RL.meta.*`
properties is skipped, as before, by the candidate check ("skip: not a
candidate for inspection"); that is the only place it is skipped, and the purl
step treats such a file as an invariant error.
**R7.11.6** In cli mode the purl comes from the side-car (R7.11.2), else from the
`RL.meta.*` properties, else it is the placeholder
`<repo>/<file name>@v0`.
**R7.11.6.1** A purl from a side-car or from `RL.meta.*` is synced like that of
any other package type: the automatic sync of an old scan (R12.7.3) and an
explicit `--sync`, through the store without a download (R12.7.4) and with the
digest check of R12.7.5. This holds for `--cli`; `--cli-docker` never syncs
(R12.7.2).
**R7.11.6.2** The placeholder is never synced. An old scan stops as already
processed, with the reason "sync not possible with cli: no .rl_meta side-car
and no RL.meta.* properties"; an explicit `--sync` (which implies `-I`, R12.7.1)
scans the file again instead. Before 1.2.0 a sync was refused for every generic
cli item, although an explicit `--sync` slipped through and synced even the
placeholder.
**R7.11.7** `RL.meta.*` properties are input a person sets. The integration never
writes them and never removes them (R10.9.2), on any item.

## 8. Docker manifests

**R8.1** `manifest.json` is a *node* (one image); `list.manifest.json` is a
*tree* (multi-architecture). Any other file name is an error.
**R8.2** `schemaVersion` must be present and equal to 2. Before that, the file
must be readable and parse as a json **object**; a read or parse failure is
reported as such, not passed on to become a missing `schemaVersion` on data that
was never loaded.
**R8.3** `mediaType` must be present and one of the known OCI / Docker types.
**R8.4** For a node, the downloadable items are the config blob plus every layer
blob, keyed by digest.
**R8.5** Only `sha256:` digests are collected; others are skipped.
**R8.6** A digest key is rewritten to the Artifactory blob file name form:
`sha256:abc` → `sha256__abc`.
**R8.7** The config blob is the one carrying the architecture.
**R8.8** `annotations` are collected when present (a future source of the version).

**R8.9** `DockerManifestExtract` is only ever constructed for a `manifest.json`.
Its `tree` branch and `get_tree_items()` are unreachable: multi architecture
images are handled by R8.10 instead, not through this class.

### Multi architecture images (R8.10.x)

Artifactory stores each architecture of a multi architecture image under a
`sha256__<hex>` directory holding its own `manifest.json`, and names those
digests in a sibling `list.manifest.json`.

**R8.10.1** Every `list.manifest.json` in the repository is read in a pre pass
(R12.2) into `repo_db`, mapping `sha256__<hex>` to the manifest entry that names
it, with `__uri__` recording the path of the list that named it.
**R8.10.2** A `manifest.json` whose parent directory is a `sha256__<hex>` name
recovers its real tag from that entry: the tag is `__uri__[-2]`.
**R8.10.3** A `manifest.json` under a normal tag directory uses the tag as is
and consults nothing.
**R8.10.4** An entry that is already present is not overwritten: the first list
that named a digest wins.
**R8.10.5** A digest that no list named keeps the digest as its version and logs
a warning. It is never silent: a digest in the version field of a purl means
every future build lands under a different version.
**R8.10.6** Failure to read a `list.manifest.json` — download failure, digest
mismatch, unreadable json, a `manifests` value that is not a list, entries that
are not dicts, digests without a `:` — is logged and skipped, never fatal. The
affected images fall back to R8.10.5.

## 9. Download and verification

**R9.1** Downloads stream in 1 MiB chunks, with a retry (default 2 attempts,
10 s apart).
**R9.2** The download is verified against the Artifactory `sha2` with sha256.
**R9.3** Digest comparison is case-insensitive.
**R9.4** The verify result is tri-state: `True` match, `False` mismatch, `None`
nothing to verify against (no sha supplied, an empty sha, or nothing
downloaded). The tri-state is resolved by `download_url_to_target_with_verify`;
`_verify_download_file` itself answers only True or False and refuses an empty
digest, because "nothing to verify against" is not a verification outcome.
**R9.5** A `False` verify result must abort processing of that item: the file is
removed and the item is marked `PROCESS_FILE_SKIP`. `None` does not abort.
This applies to every caller that downloads with verification, including the
`list.manifest.json` reader of R8.10.6, which discards the file instead.
**R9.6** A download target is `<download_dir>/<file_name>`, or
`<download_dir>/<target_name>` when an explicit target is given.
**R9.7** Whichever of the two is used must be a plain file name: empty, `.`,
`..`, and any name containing `/` or `\` are refused with
`SpectraAssureInvalidAction`. Both names derive from a repository uri the
integration does not control, and either could otherwise place the download
outside the directory that is later cleaned up. Refusing beats sanitising here,
because every legitimate caller already passes a flat name.
**R9.8** A file downloaded or assembled for a portal upload is removed by
`_do_one_portal_upload`, in a `finally`, whatever the upload answered, and by
nothing else. Removing it on success only left one behind for every refused
upload of default and docker, and generic removing it a second time logged
`ERROR file missing` on every upload.

## 10. Properties written back

### The RL.progress vocabulary (R10.4.x)

**R10.4.1** `RL.progress` has exactly two values, both defined in `constants.py`
and referenced by name everywhere else:

| Constant | Value | Meaning |
|---|---|---|
| `PROGRESS_UPLOADED` | `upload_to_portal_ok` | uploaded, the scan had not finished when the run ended |
| `PROGRESS_SCANNED` | `scanned` | the scan finished and its result was written back |

**R10.4.2** `PROGRESS_UPLOADED` is transient. Nothing depends on it
historically: if it is lost, the artifact is scanned again, which is an
acceptable outcome.
**R10.4.3** Neither value may be typed as a literal outside `constants.py`. The
value written and the values tested for have to be the same words, and two
lookalike words are exactly how they came apart before: the generic processor
tested `RL.progress` against `portal_upload_ok`, a key of the in-memory `steps`
dict that is never written to the property, so that comparison could never match
and an uploaded-but-unscanned artifact was uploaded a second time.
**R10.4.4** The `steps` dict keys are named in `constants.py` for the same
reason, so no word resembling a progress value is typed by hand anywhere.
**R10.6** The properties are written one at a time, in the order of
`PROP_SPECTRA_ASSURE_ALL`. `set_props_all()` asks `_value_for_property()` for one
value per property and writes the ones that are not None; each property's value
comes from a small function of its own. Two consequences worth naming, because
both were true before the split and are kept deliberately:

- a property whose value is None is **not written**, rather than written empty;
- the values are computed inside the loop, so a property whose value cannot be
  produced leaves the properties before it already written.

**R10.4.5** `RL.scan-status` follows the same pattern: `SCAN_STATUS_PASS` and
`SCAN_STATUS_FAIL`, with `SCAN_STATUS_ALL` as the accepted set (R10.5).


Under the `RL.` prefix: `RL.progress`, `RL.timestamp`, `RL.scan-status`,
`RL.package-url`, `RL.scan-report`, `RL.organization`, `RL.group`, `RL.sha256`,
`RL.noscan`.

**R10.1** `RL.noscan` on an item excludes it from scanning. The check is in
`FilePropertiesCommon.skip_non_candidate_file()`, which every package type comes
through, so a new type cannot forget it; what counts as a candidate beyond that
is per type. An affirmative value is `true`, `yes`, `1` or `on`, case and
surrounding space ignored; anything else leaves the item a candidate.

**R10.1.1** The integration writes it on the report files it uploads. When the
scanned repository is **local** the reports go into that repository, so a later
run would otherwise see them as ordinary artifacts. A **remote** repository
cannot take an upload at all, not even on its cache side, so its reports go to a
separate local repository; that one should not be listed for scanning in the
first place, and the property makes including it by mistake harmless rather than
an error.

**R10.1.2** This matters most for generic repositories, which never skip on name
and version (R11.6.5 does not apply to them either), so before this they had no
way to skip a report file at all.
**R10.2** `RL.progress` drives re-processing decisions across runs.
**R10.3** For docker, properties are set recursively on the directory containing
`manifest.json` when `DOCKER_RECURSIVE` is set.

### Which bytes the properties are about (R10.8.x)

**R10.8.1** `RL.sha256` records the sha256 of the bytes the other `RL.*`
properties are about, in lower case. It is written with them, after
`RL.progress` in `PROP_SPECTRA_ASSURE_ALL`: if writing stops in between, a new
progress beside an old digest reads as other bytes and the work is done again,
never skipped.
**R10.8.2** `get_prop_progress()` answers `""`, nothing recorded, when
`RL.sha256` differs from the sha256 the item holds now, and logs the rebuild at
info. Every decision that skips on the properties reads `RL.progress` through
it, so a rebuilt artifact redeployed under the same path - whose properties
artifactory may keep - is processed again in an ordinary run, and on the portal
replaces its version (R10.7.5). The comparison ignores case.
Verified live (A.22): artifactory dropped the `RL.*` properties of a pypi wheel
redeployed to the same path, and a generic side-car kept them when only the
described file was redeployed, which is the case this exists for.
**R10.8.3** Unknown is not different. Without `RL.sha256` (properties written
before it existed) or without a hash of our own, the recorded progress stands,
as it always did.
**R10.8.4** The hash compared, and written, is that of what is scanned:

| Type | Hash |
|---|---|
| default | the item's own `sha2` from the listing; a missing one is not a hash |
| generic, portal | the `sha2` of the file the side-car describes (R10.7.4), on both the file and the side-car; for a file with `RL.meta.*` properties its own `sha2` (R7.11.4) |
| generic, cli | the item's own `sha2`: a cli run scans the file itself, never through its side-car |
| docker | none: what is scanned is a bundle assembled here, so `RL.sha256` is not written |

**R10.8.5** For generic the properties are read before the side-car is, so the
described file cannot come from the side-car yet. The generic pre pass maps each
side-car uri to the uri it describes, in `repo_db` under
`REPO_DB_DESCRIBED_BY_SIDE_CAR`, and `_described_file_uri()` falls back to it.
**R10.8.6** No extra call is made: the current hash comes from the repository
listing every run already reads.

### Properties no longer maintained (R10.9.x)

**R10.9.1** Each item a run inspects - processed or skipped - first loses the
properties this integration wrote on it earlier and no longer maintains, unless
`--keep-obsolete-properties` is given. Removing them is the default.
**R10.9.2** The integration is the sole owner of the `RL.` prefix; the other
ReversingLabs integration uses `secure.software.`. Obsolete therefore means:

- anything under `Spectra.Assure.`, the prefix used before `RL.`;
- any `RL.*` name outside what the item carries (`PROP_SPECTRA_ASSURE_ALL`, or
  `PROP_SPECTRA_ASSURE_ON_SIDE_CAR` for a generic `.rl_meta` side-car) and
  other than `RL.noscan` and the `RL.meta.*` input properties (R7.11.7). That
  covers the scan result 1.0.4 wrote on side-cars, which R7.10 no longer does,
  and any name an earlier version wrote and this one does not.

**R10.9.3** `RL.noscan` always stays: it is read on every item (R10.1) and a
person may have set it. `RL.meta.*` always stays too (R7.11.7). Nothing outside
the two prefixes is touched.
**R10.9.4** The delete goes where the properties were written: the item itself,
or for docker its directory, recursively. A refused delete is logged by the api
and left for a later run; the item is processed either way.
**R10.9.5** A cli run does not scan `.rl_meta` side-cars, but a portal run on the
same repo writes them, so a cli run cleans them too, by the same rule, before
skipping them. A cleanup that raises is contained like any failing item (R12.3).
**R10.9.6** A report bundle (`*-reports.zip`) carries `RL.noscan=true` and no
other property of this integration. After an upload the report is tagged
**after** the scanned item's properties are written: for docker that write is
recursive over the tag directory, which holds the report too, so tagging first
left the full result on the report, and a `fail` there blocks downloading it.
The tagging reads the report's properties and removes the rest; nothing is
written back in their place. Report bundles already in a repository are cleaned
the same way when a run lists them, and still never processed.
`--keep-obsolete-properties` turns the cleaning of listed reports off; the
tagging after an upload always runs.

## 10b. Does this artifact already exist on the Portal

**R10.7.1** A purl existing on the Portal is not enough to skip an artifact. The
sha256 is compared too: a rebuilt artifact published under the same version has
the same purl and different content, and would otherwise be reported as already
scanned and never looked at again.

**R10.7.2** The digest comes from the analysis of the stored version,
`analysis.report.info.file.hashes`, as a list of `[type, value]` pairs; a match
is an entry whose type is `sha256` and whose value is the digest we hold. An
entry that is not a pair is skipped rather than indexed.

**R10.7.3** A caller with no digest to offer passes `None`, which means "do not
compare" and leaves the version alone deciding. That is the **docker** case: the
thing uploaded is a bundle this integration assembles itself, so Artifactory
holds no hash of it. The hashes are then not even fetched.

**R10.7.4** What each caller passes today:

| Caller | Digest | Right? |
|---|---|---|
| default | `self.file.sha2` | yes, the artifact is one file with a known hash |
| docker | `None` | yes, see R10.7.3 |
| generic | the `sha2` of the file the side-car describes, else `None`; a file with `RL.meta.*` properties its own `sha2` (R7.11.4) | yes, see below |

For a generic side-car, `self.file` is the `.rl_meta` file, so its own `sha2`
is the wrong hash. The repository listing carries `sha2` for every file; the processor
keeps them all, the generic pre pass stores the described file's hash in its
`repo_db` entry, and the side-car's processor passes that. A described file
that is not in the listing has no hash, and compares nothing (R10.7.3).

**R10.7.5** The answer has three states, not two: the version is **absent**, it
is **present** with these bytes, or it is present with **other bytes**. The
third is not "absent": an upload to a version that exists is refused by the
Portal with a 409 unless it asks to `replace` it. So an upload after "other
bytes" is sent with `replace=true`, and an upload after "absent" is not - there
is nothing to overwrite, and a version someone else uploaded meanwhile must not
be. The value is sent as the string `"true"`, which every supported SDK passes
on unchanged.

**R10.7.6** A version with no `sha256` among its hashes - no analysis yet, or
only hashes of another type - has nothing to compare against, and counts as
present, as R10.7.3 does. Treating it as other bytes would replace a version
whose scan is still running, and restart that scan.

## 11. Artifactory API surface

Every call the integration makes, so it can be checked against the official
OpenAPI reference (indexed at `https://docs.jfrog.com/llms.txt`; appending `.md`
to a reference page URL gives markdown).

| Call | Endpoint | Reference page |
|---|---|---|
| list repository items | `GET /api/storage/{repo}?list&deep=1&listFolders=0&mdTimestamps=0&includeRootPath=0` | `getstorageitem` |
| read item properties | `GET /api/storage/{repo}{uri}?properties` | `getstorageitem` |
| set item properties | `PUT /api/storage/{repo}{uri}?properties=<k=v;...>&recursive=<0\|1>` | `setitemproperties` |
| delete item properties | `DELETE /api/storage/{repo}{uri}?properties=<k,...>&recursive=<0\|1>` | `deleteitemproperties` |
| repository configuration | `GET /api/v2/repositories/{repo}` | `getrepositoryconfigurationv2` |
| search by property | `GET /api/search/prop?...` | `searchproperty` |
| artifactory version | `GET /api/system/version` | system version |
| download an artifact | `GET /{repo}{uri}` | retrieve artifact |

**R11.1** `getstorageitem` query parameters are mutually exclusive: one
operation per call. `list` and `properties` are therefore separate requests.
**R11.2** `list` requires a non-anonymous privileged user.
**R11.3.1** The session retries **transport** failures - a dropped connection, a
read timeout - and the statuses that mean "not now": 429, 500, 502, 503, 504.
Three attempts with a growing wait. A request Artifactory answered is an answer
and is not retried: 401, 403 and 404 would only be slower, and the 400 of the
recursive property cap has its own fallback (R11.5.x). `raise_on_status` is off,
because every caller reads the status code itself.

**R11.3.2** A **download** that comes back with a status that is an answer -
401, 403, 404, 405, 410 - is not retried, and the message says what the status
probably means. A 403 on an artifact that exists is usually a policy plugin such
as Spectra Assure Protect refusing to serve something that failed a scan, or an
address that is not on its allow list. Reporting that as "download failed" and
then asking again cost ten seconds per artifact and sent someone looking at the
network for an afternoon.

**R11.3** All calls go through one `requests.Session` with a retry adapter, so
`--ignore-cert-errors` (`session.verify = False`) and the proxy settings apply
uniformly.

### Repository types and the canonical storage name (R11.6.x)

**R11.6.1** Only a **local** repository, and the **cache** side of a **remote**
one, hold artifacts and accept custom properties. A remote repository itself is
not writable — its UI has no properties tab at all.
**R11.6.2** The canonical `/api/storage` name is therefore `<name>` for a local
repository and `<name>-cache` for a remote one. Every `/api/storage` call uses
it, reads included.
**R11.6.3** Reading through the bare remote name also works: Artifactory
resolves it and answers with the cache in the response's own `uri` field. That
is convenience, not part of the api contract, so nothing relies on it.
**R11.6.4** The artifact **download** url is not an `/api/storage` call and does
use the bare remote name: that endpoint proxies.
**R11.6.5** A **remote** repository needs no announcement and is never skipped
on that ground: it is simply addressed through its cache, which is what the
integration has always done.
**R11.6.6** A **virtual** repository stacks a local over a remote — writes go to
its local part, reads fall through — so it has no storage identity of its own to
annotate. It is not supported, and a repository whose type is neither local nor
remote is skipped with a `REPO SKIP` line naming the type, rather than failing
once per artifact.
**R11.6.7** An **empty** repository type is not a type at all: it means
`GET /api/v2/repositories/{repo}` returned no configuration, because the
repository does not exist, is not readable, or the request failed. That is
reported as its own `REPO SKIP` reason — "repository does not exist, or we may
not read its configuration" — and never as an unsupported type.
**R11.6.9** A repository whose package type is not one the integration handles
(`ARTIFACTORY_KNOWN_PACKAGE_TYPES`, compared without case) - Ivy, Conan
and so on - is skipped with a `REPO SKIP` line naming its type and the
supported ones, always printed. It used to be listed as empty, so the run found
nothing and said nothing.

**R11.6.8** That skip is the **only** message about it at the default log level.
The status the server gave is logged by the lookup at **debug**, where it still
distinguishes a 404 from a 403 or a transient failure. Logging it at warning as
well made one unreadable repository produce two warnings saying the same thing,
which teaches a reader to skim warnings.

### Server version dependent behaviour (R11.4.x)

The integration ships to customers whose Artifactory version it does not
control, so a newer endpoint may only be used when the server actually has it.

**R11.4.1** `GET /api/system/version` is already called at startup, which is the
natural place to gate on.
**R11.4.2** `findparentmanifestlists` (since 7.119.0) returns the parent
manifest lists of a docker manifest directly. It is the server-side equivalent
of the `repo_db` reconstruction of R8.10. Not used: it answers for one
manifest per call, so it costs one request per architecture where the pre pass
costs one per `list.manifest.json`, and the pre pass works on every version.
See A.3 in `DECISIONS.md`.
**R11.4.3** From 7.104.x an administrator can cap how many artifacts a single
recursive property update may touch, with the system parameter
`artifactory.max.artifacts.set.properties.recursive`. The feature is off by
default and has no default value when turned on; the documented example value is
5000. Over the cap the call fails with **400** and a message of the form

```
Cannot add property recursively to <repo>:<path> because it has more than <n> items.
```

`setItemProperties` defines **no dedicated status code** for this — the
documented responses are 204, 400, 401, 403 and 404 — so the status alone cannot
identify it, but the message can. See R11.5.x.

### Recursive property updates and the per item fallback (R11.5.x)

**R11.5.0** This applies to `deleteItemProperties` as it does to
`setItemProperties`: the cap is on the recursive operation, not on the verb, and
the refusal reads the same way. One function decides whether a refusal is worth
splitting, and both verbs use it.
**R11.5.1** A recursive `setItemProperties` that fails with **400** is retried
as one non-recursive update per file below the path. 400 is the only documented
status the cap can plausibly arrive as; 401, 403 and 404 mean credentials,
permissions or a missing item, and splitting the call cannot help with any of
those, so they are not retried.
**R11.5.2** A non-recursive call is never retried this way.
**R11.5.3** The files are found with
`GET /api/storage/{repo}{path}?list&deep=1&listFolders=0`, and folder entries in
the response are skipped regardless.
**R11.5.4** Setting a property is idempotent, so files the refused call had
already updated are simply set to the same value again. No read back is done to
find which those were.
**R11.5.5** One failing file does not stop the others. The call returns success
only when every file succeeded, and logs `<n> of <m> item(s) could not be
updated` otherwise.
**R11.5.6** The refusal message is matched against
`RECURSIVE_PROPS_LIMIT_PATTERN` to confirm the cap and to capture the limit,
which is then named in the warning. The pattern is deliberately loose
(`recursively … more than <n> item`) because the wording is not part of the api
contract, and it also matches the delete counterpart.
**R11.5.7** A 400 whose message does not match is retried anyway, and logged as
unrecognised. A rewording of the message must not silently disable the fallback;
the cost is that a genuinely malformed properties value is retried once per
item, with each failure logged.
**R11.5.8** An empty listing, or a listing that itself fails, returns failure
rather than reporting success for nothing.
**R11.5.9** Only the docker path sets properties recursively, and only when
`DOCKER_RECURSIVE` is on (R10.3); every other type addresses one file at a time
and cannot reach the cap. Note that `setItemProperties` defaults `recursive` to
1 for folders, so the explicit `recursive=0` this integration always sends is
what keeps the other types out of that path.

## 12. Running a repository

**R12.1** Before the main loop over a generic repository, every `.rl_meta`
side-car in it is read into `repo_db`, so an artifact is matched to its side-car
regardless of the order Artifactory lists them in. That is also what lets a
side-car win over `RL.meta.*` properties (R7.11.2) when the file comes first.
**R12.1.1** A side-car the pre pass cannot read - for example one missing a
mandatory key (R7.3) - fails that side-car only: it is recorded as a failed item
(R12.3.1), its downloaded copy is removed, the pre pass carries on with the
next one, and the main loop does not process it again. It used to raise out of
the pre pass and fail the whole repository (R12.3.2), so no file in it was
scanned. The file it names then has no side-car, and is handled as one without
(R7.11).
**R12.2** The same holds for docker and `list.manifest.json` (R8.10.1).
Artifactory gives no ordering guarantee, and `sha256__` sorts before common tags
such as `v1.2.3`, so an opportunistic in-loop collection would leave those
images with a digest as their version.

### Failure containment (R12.3.x)

A repository holds data the integration does not control, so one malformed
artifact must never end the run.

**R12.3.1** An unexpected exception while processing one item is logged with a
traceback, recorded as `(repo, uri)`, reported as `PROCESS_FILE_FAILED`, and the
loop continues with the next item.
**R12.3.2** An unexpected exception while processing one repository is logged
and recorded, and the loop continues with the next repository.
**R12.3.3** The downloaded files of an item are removed in a `finally`: a crash
must not leak them into the download directory.
**R12.3.4** In portal mode, items whose scan had not completed are parked and
finished at the end of the run. That must happen even when the run above failed,
because those are scans already paid for and downloads still to clean up. Each
parked item is itself guarded, so one failure there does not stop the others.
**R12.3.4.1** A failed **report upload** fails that artifact and nothing else. It
called `sys.exit(101)`, so one dropped connection while uploading one report
ended a run over thousands of artifacts, bypassing everything else here. It
raises now, the item is recorded, and the run ends with `EXIT_ITEM_FAILURES`.

**R12.3.4.2** A message about one item names the repository and the uri, and
names them **first**. A docker digest on its own does not say which image in
which repository produced the warning, which is what
`_try_extract_version_from_manifest_uri_and_repo_db` used to report.

**R12.3.4.3** Waiting for a portal scan stops when the portal says the version is
not there. Three consecutive **404** answers settle it: a version uploaded moments
ago can take a little while to become visible, so a few are tolerated, and any
other answer in between resets the count. After that no amount of waiting can
produce a scan of a version that does not exist.

A live run polled seven artifacts ninety times each — half an hour per artifact
at twenty seconds a poll — for versions the portal had already refused.

**R12.3.4.4** That answer is then acted on: the artifact is **uploaded**, once,
and waited for again. `RL.progress` does not record which backend wrote it, so a
`scanned` written by a cli run makes a portal run believe the portal already has
the artifact; it then waits for a scan of a version the portal has never seen.
The portal is the only thing that knows, and it has now said no three times, so
the property was about something else and the artifact still has to be uploaded.

At most one upload: if the portal still has no such version afterwards the item
is recorded as `PROCESS_FILE_TIMEOUT` and left for a later run rather than
looping. Only the default processor needed this — docker and generic already
upload whenever the portal says the version is not there.

`_wait_for_scan_status_one_portal` therefore answers three ways: `True` scanned,
`False` not finished in time, `None` the portal has no such version. `None` is
not a failure — it says the thing being waited for cannot arrive, so a caller
that can upload should.

**R12.3.5** At the end of a run with failures, each failed repository and item
is logged, followed by a one line summary with both counts.

### Mandatory settings (R12.5.x)

**R12.5.0** `--repo` may be given any number of times, and each occurrence may
itself be a comma separated list, so `--repo a --repo b,c` and `--repo a,b,c`
mean the same thing. Order is kept and duplicates are dropped.
**R12.5.0.1** Surrounding space is removed and empty names are dropped:
`--repo "a, b"` used to produce a repository called `" b"`, and `a,,b` or a
trailing comma used to produce `""`. Both were then looked up and failed in a way
that looked like a missing repository.
**R12.5.0.2** A repository name matches `^[0-9a-zA-Z_.-]+$`: letters, digits,
`-`, `_` and a dot. The dot matters — a proxying repository is usually named
after what it proxies, such as `nmpjs.org` — and Artifactory is more permissive
than it looks: `jjj.....kkk` and `_hshshs____----....mmmm` are both legal names,
checked against a real server, as is a single `-` or `_`. The rule therefore
excludes only what Artifactory itself excludes: a validator that invents
constraints rejects legitimate input, which is worse than not validating,
because the run stops on a name that would have worked. Anything else is
refused with every offending name listed at once, so a typo is one clear message
here rather than a `REPO SKIP` later (R11.6.7) that reads as if the repository
does not exist.
**R12.5.0.3** The two exceptions are `.` and `..`, which are a path segment
rather than a name and go straight into the path of every `/api/storage` call.
Nothing else needs excluding: `/` is not in the pattern, so a dot run **inside**
a name cannot climb anywhere.

**R12.5.1** A run needs `ARTIFACTORY_HOST`, `ARTIFACTORY_USER` and
`ARTIFACTORY_TOKEN`. Portal mode additionally needs `RLPORTAL_ORG`,
`RLPORTAL_GROUP` and `RLPORTAL_ACCESS_TOKEN`, and at least one of
`RLPORTAL_HOST` and `RLPORTAL_SERVER`; cli mode needs `--cli-rlstore-path` and
`--cli-rlsecure-path`; and cli-docker needs `RLSECURE_ENCODED_LICENSE` and
`RLSECURE_SITE_KEY` instead of those two paths. For cli-docker the rl-store is
optional: without it the store inside the container is ephemeral.
**R12.5.1.1** The host and the server stand in for each other, as in the portal
sdk: a server alone means `my.secure.software/<server>`, a host alone is a
dedicated portal. Requiring both refused the documented setup of four
`RLPORTAL_*` variables. A run with neither is refused, naming both.
**R12.5.2** They are checked once, after every source of options has been read,
so a run reports **every** missing setting in one message. Discovering them one
at a time costs a round trip each.
**R12.5.3** Each is named by its `cli_args` key, by its environment variable
where it has one, and by its command line option.
**R12.5.4** A missing setting exits `EXIT_FATAL` with that message and no
traceback: it is a bad invocation, not a crash.
**R12.5.5** A tool that selects neither backend (`no_portal_or_cli`) needs only
the Artifactory settings.
**R12.5.6** The message never contains the value of a setting that *is* present
(R13.5).

### Exit codes (R12.4)

| Code | Meaning |
|---|---|
| 0 | the run finished and every artifact was processed |
| 2 | invalid command line (argparse) |
| 101 | a precondition failed: a mandatory setting is missing, or the portal could not be verified; no artifacts were processed |
| 102 | the run started and did not finish: unexpected error or Ctrl-C |
| 103 | the run finished, but items or repositories were skipped; `--ignore-skipped` makes this 0 instead |

Everything of ours is above 100, so a wrapper can tell it from argparse's 2.
`main()` catches `KeyboardInterrupt` and `Exception` separately and logs a plain
message rather than printing a traceback.

## 12b. The cli backend

rl-secure runs as a subprocess, directly or in a docker container.

**R12.6.0** Before any repository work, a **local** cli run checks that
rl-secure is usable, in this order:

1. `rl-secure --version` — the binary is present, runnable and licensed.
   rl-secure cannot be installed without a licence, so a version that comes back
   at all proves both.
2. `rl-secure list --rl-store <store>` — the store exists and has been
   initialised with `rl-secure init`. Without a store nothing can be analysed.

A failure raises `SpectraAssureInvalidAction`, which `main()` turns into
`EXIT_FATAL` with the reason (R12.5.4). The scanner used to discover both of
these in its constructor, which runs **after** the artifact it was built for has
been downloaded, so a broken installation cost one download per item in the
repository before it complained.

The docker backend is not checked this way: it brings its own scanner image, and
checking here would mean a pull before the run.

**R12.6.0.1** Which arguments an rl-secure command takes:

| Command | `--rl-store` | `--purl` |
|---|---|---|
| `version`, `license` | no | no |
| `list` | yes | no |
| everything else | yes | yes |

`version` in particular has to work before a store has ever been set up, so it
must not require one.

**R12.6.0.2** `--no-color` and `--no-tracking` only shape output for a terminal
(colour, progress bars), and the output goes to the log. Each command gets the
ones its page on [docs.secure.software/cli/commands](https://docs.secure.software/cli/commands)
lists, and no other: an option a command does not know may make it fail.

| Command | `--no-color` | `--no-tracking` |
|---|---|---|
| `--version` | no | no |
| `list` (R12.6.0) | yes | no |
| `license status` | yes | no |
| `status`, both uses (R12.6.4.1) | yes | no |
| `scan` | no | yes |
| `sync` | no | yes |
| `report` | no | yes |
| `rl-safe pack` | no | yes, not on that site; kept as it was |

The docker image's `rl-scan` lists neither ([docker-image](https://docs.secure.software/cli/integrations/docker-image)),
so the docker backend passes neither. The image has no sync command (R12.7.2).
`test_scan_cli_local.py` holds the same table and fails when a command is
added without an entry.

**R12.6.1** Commands are built as a **list** and run without a shell, so nothing
in a file name, a purl or a report path can be read as shell syntax.
**R12.6.2** The rl-secure **license and site key never appear as an argument**.
An argv element is readable in `ps` by every user on the host for as long as the
command runs. They are passed in the environment of the child process, and the
docker command names them with a valueless `--env=NAME` so docker picks them up
from there.
**R12.6.3** The child inherits the rest of the environment: docker needs `PATH`
and its own settings.
**R12.6.4** `check=False`: a non-zero exit is handled here rather than raised.
A code the caller did not declare as an answer is logged at **error** with the
command's own stderr, because at the default log level a failing scan is
otherwise silent.
**R12.6.4.1** Each command declares which return codes are an **answer** rather
than a failure, and only the others are logged as errors:

| Command | Answers | Why |
|---|---|---|
| most | `0` | anything else went wrong |
| `status --return-status` | `0`, `1` | the scan result itself: 0 pass, 1 fail |
| `status` (does this purl exist) | any | the code *is* the answer; "not scanned yet" is the ordinary first-run case |
| the **docker** scan | `0`, `1` | the image returns the verdict itself; only 101 is a real error |

The docker row is the one that is easy to get wrong. The local rl-secure returns
0 from a scan and the verdict comes from a separate `status` call, so the two
backends do not answer the same way for the same work. Treating the image's `1`
as a failure put an ERROR in the log for every artifact that did not pass.

Logging an expected outcome as an error says nothing useful and buries the
failures that do matter.
**R12.6.5** No log line may contain the license or the site key, at any level
(R13.5 covers the same for `cli_args`).
**R12.6.6** Each command is recorded under its own name, so a sync does not
overwrite the record of the scan that preceded it. The record is a debug log
line per command with its exit code, stdout and stderr; there is no results
object, because nothing ever read one.
**R12.6.7** Each scan or sync works in a directory of its own, made by `ScanCli`
before the scanner starts and removed by `ScanCli.cleanup()`. The scanner is
given that directory and never makes or removes one itself. The cleanup runs in a
`finally` around the whole scan, report upload included: an exception there is
contained per artifact (R12.4) and the run goes on, so a cleanup on the normal
paths only would leave a directory behind for every artifact that raised. It is
safe to call before the scanner started and more than once, and a directory that
cannot be removed is logged as a warning rather than raised, because raising
would replace whatever the scan itself raised.

## 12c. Sync

A sync re-analyses what a store or the Portal already holds. It is what you run
after a new rl-secure release, whose engine may judge the same bytes differently,
or after a policy change, which alters what passes and fails. The artifact itself
is not needed.

**R12.7.1** `--sync` implies `--ignore-artifactory-properties` (R12.5), because a
re-analysis must not be skipped by a property saying the work was already done.
**R12.7.2** `--sync` with `--cli-docker` is refused at startup. Without
`--cli-rlstore-path` the store lives inside the container and is gone after the
scan. With it, the store keeps the history (each scan uses `--replace`), but the
`reversinglabs/rl-scanner` image offers only `rl-scan`, `rl-scan-url`,
`rl-scan-purl`, `rl-scan-docker` and `rl-prune`: no sync, and no way to ask the
store whether a purl is there. rl-secure is installed when a command starts, so
it cannot be called directly either. The docker backend therefore always scans,
whatever it is asked; the unused `rl-sync` call it had is gone.
**R12.7.2.1** The automatic sync of R12.7.3 is not used with `--cli-docker`
either: an item an earlier run recorded as scanned stays "already processed",
however old the scan. The check used to look for the option under the wrong
key (`cli-docker` instead of `cli_docker`) and never matched, so a scan older
than 14 days was sent to a sync, and without `--cli-rlstore-path` that item
failed with "store is None" on every later run.
**R12.7.3** Two things ask for a sync and they are both honoured: the explicit
`--sync`, and `need_sync_datetime`, set when the artifact is already known and a
re-analysis is cheaper than an upload. Both go through `sync_requested()`. The
exceptions: `--cli-docker` never syncs (R12.7.2, R12.7.2.1), and a generic cli
item with the placeholder purl never syncs (R7.11.6.2).

### Sync without a download (R12.7.4.x)

**R12.7.4.1** Before downloading anything, a cli run asks the store whether the
purl is already there (`rl-secure status`, no artifact needed). If it is, the
sync runs against the store and **nothing is downloaded**. The decision used to
be made after the download, so a sync run fetched every artifact and then ignored
it.
**R12.7.4.2** If the purl is **not** in the store, the run falls back to the
ordinary path: download, scan, report. A first run with `--sync` therefore still
works.
**R12.7.4.2.1** The reason reported for the item says what **happened**, not what
was asked for: `cli-sync` only when the store answered and nothing was
downloaded, `cli` when the sync fell back to a download and a scan. A live run
over 548 npm artifacts reported every one as `cli-sync` while every one had been
downloaded and scanned, and the timings — 13.7s against 14.2s for an ordinary
scan — were the only way to tell.

**R12.7.4.3** A sync is followed by a report exactly as a scan is. The verdict
may or may not have changed, but the detail in the report has, so a fresh report
is always produced.
**R12.7.4.4** Docker is excluded from all of this: its uploads are bundles this
integration assembles, so the store holds nothing a download would have matched.

### Was the sync about the right bytes (R12.7.5.x)

**R12.7.5.1** A sync assumes the artifact behind the purl has not changed. That
is checked, from the sha256 the rl-json report carries at
`report.info.file.hashes`, compared with the `sha2` Artifactory holds.
**R12.7.5.2** The check happens **after** the sync, using the report the sync
produced anyway. A matching digest, which is the ordinary case, costs nothing
extra; a mismatch costs one sync that is then followed by a real scan. Checking
first would have cost a report generation on every artifact.
**R12.7.5.3** `rl-json` is therefore always generated, whatever
`--cli-report-types` asks for, and removed again before the bundle is built when
the user did not ask for it, so their bundle holds exactly what they requested.
**R12.7.5.4** The hashes are a list of `[type, value]` pairs; an entry that is
not a pair is skipped. The path is read exactly and never searched for: the
components under `report.metadata` carry their own hashes and are not the answer.
**R12.7.5.5** The report schema this was written against is **3**. A different
schema is logged once and the read is attempted anyway.
**R12.7.5.6** An answer that cannot be determined - no report, unreadable report,
path absent, no `sha2` in Artifactory - is **unknown**, never "different", and
every caller treats unknown as a reason to do the full work rather than skip it.

## 13. Output and logging

**R13.1** `<program>.log` is always written; its level comes from `--log-level`
or `LOG_LEVEL`, defaulting to `WARNING` when absent.
**R13.2** `--log-to-stderr` adds stderr as a second destination with the same
level and format. The file is never replaced.
**R13.3** Progress output (`my_print`) goes to stdout as plain text and to the
log at info level.
**R13.6** The console copy of the log goes to **stderr**, never stdout: stdout
carries the program's own output, so a caller can redirect one without the other.
Nothing therefore has to be suppressed to avoid printing a line twice.

**R13.7** A report stored as a **path** rather than a url is completed with the
portal it came from, and only a portal run can do that. A cli run has no portal,
and its own reports live in Artifactory, so whatever is stored is already the
whole answer. The check is on the backend, not on whether the portal api happens
to be set: a cli run over a repository an earlier portal run had scanned raised
here and lost that artifact.

**R13.8** The words a user reads are checked: `make spell` runs `codespell` over
the repository and `make all` includes it. A misspelling in a log line or a
`--help` text is not cosmetic - it is the text someone greps for, and a
misspelled "timeout" sat in the wait-for-scan warning through several runs before
anyone noticed.

**R13.8.1** What the check skips is what is not ours to correct:

- the virtualenv and the generated caches;
- the captured output of past runs (`keep/`, `*.1`, `*.2`), which holds the
  messages as they were spelled at the time and the names of whatever was
  scanned — a maven package can be named after a phrase the checker reads as a
  typo;
- patch files (`*.patch`, `*.diff`), which carry the old spelling on their `-`
  lines: correcting one would break the patch it describes.

**R13.5** Credentials never reach a log, a console or an exception message.
`cli_args` holds the Artifactory token, the Portal token, the rl-secure license
and the proxy password, and `<program>.log` is always written, so anything that
renders the whole dict passes it through `redact_secrets()` first. A key counts
as a credential when its name contains `token`, `password`, `secret`, `license`,
`site_key` or `api_key`, so a new secret option is covered on the day it is
added rather than the day someone remembers. A value that is absent stays absent
rather than becoming `***`, so a log still shows which options were not supplied.

**R13.4** Progress output always goes to stdout. It does not have to check
whether the log is also on a console, because the log's console copy is on
stderr (R13.6).

---

## 15. Where the rest is

What was tried, what went wrong, what is still open, and why each rule exists in
the form it does: `DECISIONS.md`. Nothing there is needed to work on the code —
it is there so the same ground is not covered twice.
