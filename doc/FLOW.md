# rl-scan-artifactory — the flow

Four diagrams, outermost first. One diagram for all 72 decision points would be
unreadable, so each layer ends where the next begins and says which one.

Every branch here is pinned by a test; the file and test are named under each
diagram, so a diagram that stops matching the code is a diagram someone changed
without changing the tests.

---

## 1. A run: repositories

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

## 2. One artifact: is it a candidate, and what does the purl look like

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

## 3. The portal

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

## 4. The cli

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
