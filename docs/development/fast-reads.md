# Fast catalog, definitions and runs

Owner decisions and supporting measurements. The Engine DB remains authoritative. This study changes no shipped code, schema, configuration or release gate. [Monitoring and operability](monitoring-and-operability.md#scale-and-storage) sets the baseline. [S7.BD](road-to-1.0.0.md#s7bd-bounded-catalog-lineage-lookup) already owns the large-project catalog blocker. Its budgets remain cold build ≤5 minutes, warm rebuild ≤60 seconds and one-pipeline re-parse ≤10 seconds. Monitor retains the proposed 250 KiB first page and local PostgreSQL warm p95 ≤500 ms, with a fixed statement count.

## What runs today

`generate-docs` gathers definitions, parsed lineage, recent audit data and documentation versions through `services/catalog/collect.py`. `services/catalog/site.py` builds HTML and `catalog.json` in a staging directory and swaps the folder under the publication lock. The API reads the output path from the last successful catalog publication or the configured default. The catalog's site files live in this filesystem directory. The content-addressed `ArtifactStore` serves independently readable bundle artifacts and is a separate storage mechanism. A shared catalog path is still required when multiple serving processes read the same generated output.

`CATALOG_PAGE` resolves the project and pipeline grants on each request, refuses partial project visibility, verifies the file's project marker, and streams file chunks. The React catalog fetches the entire `catalog.json` via `useCatalog` and calls `JSON.parse` before drawing the explorer. Its lineage views search and walk arrays from the same document. The document carries recent runs, pauses and observations alongside definitions. A metadata version alone consequently cannot validate today's complete catalog. The separate operational pipeline graph comes through the pipeline graph action. Run history and grid read the Engine DB directly. The catalog has an explicit rebuild action, and lineage re-parse currently tells the viewer to rebuild to see its result in the catalog.

The run history SQL orders by run ID with a keyset cursor and limits returned rows. Optional pool, agent and failure class filters add correlated attempt checks. Grid cell SQL fans out only for selected runs but also finds the latest attempt for each returned cell. Home's windowed aggregate services cover a different workload from a bounded Monitor feed. The current React live views use polling, including selected live run and task/attempt reads. The source at the measured revision contains streamed downloads and log-window reads, and found no browser EventSource or HTTP `text/event-stream` run feed. An SSE comparison needs a specific implementation or route.

## Methods and reproduction

Baseline source is `106e672d` (PR #477). Reproduction scripts live on the retained branch `perf/fast-reads-prototype` under `experiments/`. Use the repository dev environment, its bundled React build, Playwright Chromium and the fixture's local HTTPS server. Use the demo preparation and SOURCE_A, SOURCE_B and DEMO executions from [PR #476's browser method](monitoring-and-operability.md#measurements-appendix), then generate its catalog. A scratch copy is used for browser measurements. The PostgreSQL experiment requires the local fixture service. All workloads use synthetic data or the local demo. Run one large seed at a time.

```bash
export TMPDIR="$HOME/.cache/etl-craft-tmp"
export PYTHONPATH="$PWD/src:$PWD/tests"
# Run from the prototype checkout with the dev Python environment on PATH.
for size in 0 500 5000; do
  systemd-run --user --scope --quiet -- \
    python experiments/fast_reads.py "$size" "$TMPDIR/bb-demo" \
    > "$TMPDIR/fast-reads-catalog-$size.log" 2>&1
done
for size in 0 500 5000; do
  systemd-run --user --scope --quiet -- \
    python experiments/fast_reads_browser.py "$size" "$TMPDIR/bb-demo" \
    > "$TMPDIR/fast-reads-browser-$size.log" 2>&1
done
systemd-run --user --scope --quiet -- python experiments/fast_reads_invalidation.py \
  > "$TMPDIR/fast-reads-invalidation.log" 2>&1
python experiments/fast_reads_failures.py
```

The synthetic catalog seed is the repository's `seed_catalog` with 10 tasks and 25 runs per pipeline. At 5,000 pipelines that is 125,000 pipeline runs and 1.25 million task runs. This gives the full 25 × 10 grid shape. The run benchmark spreads the pipeline runs across approximately 730 days, uses sparse attempt evidence and creates 50 active runs. It samples a two-year window at reduced density. The #476 workload models 14.6 million runs, 146 million task runs and 175 million attempts. Treat any extrapolation from this study as a hypothesis. Pipeline definitions have representative counts but simple SQL and minimal lineage, dependencies and documentation.

Set FAST_READS_LARGE_CATALOG=1 to assemble and stage the large browse document for Chromium. Set FAST_READS_CATALOG_ONLY=1 to isolate catalog navigation, and FAST_READS_PAGES to select comma-separated routes. Large definitions and run workloads should run sequentially. For the file-slice replay, use FAST_READS_EXPORT_CATALOG with a scratch output file to retain the staged full document. Run python experiments/fast_reads_slice.py FULL_JSON SLICE_JSON under the same scope. Rerun the browser with FAST_READS_CATALOG_FILE pointing to the slice, and FAST_READS_PAGES=lineage. The scope used MemoryMax=3500M for the large catalog and slice replay.

The browser harness defines usable per route by a semantic UI selector, after sign-in, measures fresh route navigation and reload in the same browser profile, and records response bodies and statements through an ASGI wrapper and SQLAlchemy cursor events. Cursor timing covers execute rather than all fetch/conversion. Response wall time includes authorization, response generation and ASGI delivery, which can overlap across calls. Browser time includes server, transport, parsing and rendering. Wall time minus cursor time includes more than Python assembly. Body sizes are uncompressed unless explicitly called gzip, which is an offline level-1 comparison. Browser timings are single local observations. First-route navigation and reload both have warmed shell assets from sign-in. The scale browser harness stages the experimental JSON into the ordinary file reader when requested. It omits full HTML generation, warehouse comparison and publication writes.

## Catalog build and representation

| Size | Cold / warm collection s (statements) | Current / indexed document assembly s | JSON encoding s | Whole document raw / gzip bytes | Definition index raw / gzip bytes | One definition shard raw / gzip bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Demo | 0.261 (49) / 0.120 (49) | 0.0064 / 0.0069 | 0.0011 | 133,754 / 15,123 | 254 / 153 | 658 / 297 |
| 500 × 10 | 23.117 (30,080) / 10.949 (80) | 2.845 / 2.565 | 0.289 | 46,143,711 / 1,400,685 | 21,780 / 2,443 | 1,841 / 307 |
| 5,000 × 10 | 78.283 (353) / 95.989 (353) | 110.489 / 25.875 | 3.286 | 465,289,698 / 13,784,550 | 227,780 / 24,812 | 1,841 / 307 |

The 5,000-pipeline collection disables global lineage recording to get past the documented SQLite bind limit. The pair of collection timings does not certify the release budgets. It excludes full site generation, warehouse comparison and publication. Even the warm collection alone exceeded the 60-second budget by 36 seconds. The run-rich seed carries 25 runs per entity, whereas the earlier #476 warm catalog study used four. The large collection and assembly remain independent bottlenecks.

The current-path prototype pre-indexes trigger references by target pipeline before reusing the current document assembly. It asserts exact document equality. It saved 84.6 seconds in one 5,000-pipeline observation and retained the same 465 MB browser document. The sample has no trigger fan-out. A varied trigger fixture and profiling the remaining collection and assembly are still needed. Production site generation also resolves dependent visibility inside its pipeline loop. Measure that loop and the HTML write separately before making a full-build claim.

The latest-only prototype serializes a definition-only index and one definition shard per pipeline. It excludes audit/history, and its fields are a reduced sample of the definition contract. At 5,000 pipelines it took 167 ms to construct the new generation from already collected and assembled inputs. Resident serialized shard bytes were 9,560,570, plus lookup structures and index output. The mixed build process reached 3,868,928 KiB peak RSS including both catalog objects, both assembled documents, encoded JSON, compression and shards. Use 9.56 MB as a bytes-only floor for one process and one project. Neither number measures peak RSS of an isolated production API cache. Cold restart may have to pay gathering and parsing as well. The prototype generated the full index in 4.8 ms and a 50-pipeline viewer's index in 0.8 ms (2,274 raw bytes), using already-resolved access. A hit with the matching validator returned an empty body. The two-store failure simulation used a scratch SQLite revision row. Assertions passed for 304 on a current and permitted revision, refusal after simulated revocation, mismatched generations across copies, preserved generation after an interrupted build, and a failed version lookup. The simulation supplied grants and substituted a revision bump for deploy and re-parse. It does not validate production actions or authorization races.

Compression helps transfer on supported deployments. The full JSON still has to be decoded, parsed and traversed by the current browser. The index and shard split demonstrate a payload reduction from scope and separating live evidence. Both a file-backed projection and a memory-backed projection could send those same bytes. The 0.142 ms p95 local PostgreSQL version read and the cheap local shard lookup do not establish a reason to duplicate a warmed file-system cache in every API process.

## Browser baseline

A request count is the count through the initial route settling, including shell calls. The representative operation columns are statements / server ms / body bytes from one completed response on reload (task history at 500 uses the first navigation sample). The shell heading and table selectors can precede completion of data calls, so the browser column measures the specified landmark rather than every panel. In particular the Home heading appeared well before Insights data.

| Page / representative read | Demo requests | Demo fresh / reload s | Demo SQL / ms / bytes | 500 requests | 500 fresh / reload s | 500 SQL / ms / bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Catalog / catalog.json | 6 | 0.852 / 0.888 | 12 / 61 / 133,754 | 6 | 0.931 / 0.979 | 12 / 294 / 46,183,698 |
| Lineage route / catalog.json | 7 | 0.854 / 0.860 | 12 / 41 / 133,754 | 7 | 1.659 / 1.510 | 12 / 201 / 46,183,698 |
| Home / Insights | 6 | 0.096 / 0.107 | 69 / 183 / 8,712 | 7 | 0.112 / 0.130 | 96 / 9,777 / 180,985 |
| Project run history | 6 | 0.183 / 0.116 | 18 / 77 / 3,684 | 6 | 0.077 / 0.137 | 18 / 125 / 42,720 |
| Pipeline grid / history with cells | 8 | 0.295 / 0.174 | 19 / 55 / 10,260 | 8 | 0.278 / 0.275 | 19 / 92 / 34,983 |
| Pipeline graph / definition graph | 9 | 0.637 / 0.522 | 19 / 48 / 1,165 | 9 | 1.120 / 1.133 | 18 / 28 / 370 |
| Selected run / exact run | 7 | 0.255 / 0.261 | 28 / 52 / 7,529 | 7 | 0.193 / 0.197 | 27 / 74 / 844 |
| Task panel / selected task history | 16 | 0.440 / 0.461 | 27 / 20 / 2,486 | 14–15 | 1.012 / 0.956 | 27 / 41 / 869 |

The medium catalog browser experiment staged a document with run dates filled in. This accounts for its size difference from the assembly table. The demo and medium lineage route landmarks were the catalog tree and selected lineage tab. They do not time post-layout completion. A render profile should account for repeated scans of all tasks for pipeline groups and repeated copies of each schema table group in the browser tree. Preliminary API timings include streaming and authorization but exclude JSON parsing in the browser.

The demo selected run also fetched steps (22 statements, 34 ms, 7,695 bytes) and status (124 statements, 119 ms, 99,420 bytes) on reload. The successful demo had attempt evidence while the initial 500-pipeline seed had none. Use the two as different workload shapes. The data supports looking at status and repeated capabilities requests before a new run cache. The graph read was already small. Graph interaction and rendering were a larger part of the observed page time, but this run did not isolate graph rendering from interaction and other requests. At 500 pipelines the Insights cursor events took 1.01 seconds on the measured reload, of 9.78 seconds total. This is a concrete reason to profile the fallback gap calculation, audit and Python fetch/assembly before selecting an index or adding summary rows.

At 5,000 pipelines, the staged 465,689,698-byte document reached Chromium as 200 on catalog and lineage navigations. Both pages issued six initial API requests and never reached the tree landmark within the 10-second selector window on either fresh route or reload. Each catalog request ran 12 Engine DB statements. Catalog delivery took 2.38/1.98 seconds and lineage delivery took 1.85/4.96 seconds on fresh/reload. Cursor execute accounted for 30–82 ms of these samples. Chromium and the local server were inside a 3.5 GB scope for that run. This is a large-page failure on the measured workstation, including a substantial transfer and browser component. It is not an isolated parse or layout benchmark.

A persisted 89,916-byte pipeline/table slice of the same document reached the same lineage route on the same-size Engine DB in 0.860/0.856 seconds including the selected lineage tab. The slice used seven requests, and the file read ran 12 SQL statements and took 210/81 ms. It preserved the selected object and provided one pipeline's catalog context. Search, cross-pipeline traversal and the rest of the project tree were outside the slice. This comparison demonstrates the file-backed path on the smaller view. It does not verify feature parity or establish an advantage for RAM.

The first large Home attempt rendered its heading in 93/153 ms. It failed to reach network idle within 12 seconds, and the subsequent navigation could not sign in while the Home read was still in flight. This rules out using the shell heading to certify data readiness. Run the routes independently when reproducing.

| Operational page at 5,000 pipelines | Initial requests | Fresh / reload browser landmark s | Representative SQL / server ms / bytes |
| --- | ---: | ---: | ---: |
| Home | 6 | 0.093 / 0.153 (heading only) | Insights incomplete at deadline |
| Project run history | 6–7 | 0.109 / 0.241 (table only) | 18 / 468 / 43,021 (fresh) |
| Pipeline grid | 8 | Miss / 14.275 | 19 / 232 to 23,357 / 35,304 |
| Pipeline graph | 9 | 1.198 / 1.227 | 18 / 24 / 370 |
| Selected run | 7 | 0.258 / 0.249 | 27 / 140 / 846 |
| Task panel | 14–15 | 0.995 / 0.951 | 27 / 196 / 873 |

This follow-up used the 5,000-pipeline seed with run dates populated and sparse or absent selected-run attempt evidence. It ran the operational routes separately from Home. History showed the table before remaining initial requests settled and exceeded the subsequent 12-second idle deadline. Grid responses varied sharply. The slow grid history response spent about 23.3 seconds in cursor execute, while the same SQL statement count and payload appeared in a 232 ms response. The harness can see delayed completions from a previous navigation, so the grid column reports a range of completed grid responses. This is consistent with contention in the local mixed SQLite workload, but the experiment did not isolate the lock/queue holder. It is not evidence that adding a history index will fix the slow tail.


## Large run reads and Monitor-shaped probes

These are direct local SQLite SQL calls including fetch. Each row is one statement. Byte counts use a JSON encoding of the raw rows. The grid combines two statements and 83,873 bytes in this encoding. It excludes real HTTP output, auth, repeated loads, Python response assembly and browser work. The rare-pool case matches roughly 1% of sparse recorded attempts. Absent-pool search is an important negative case. Most rows have no attempts, and the seed has 125,000 attempts plus selected and live evidence. It does not model #476's 1.2 attempts per task at full density.

| Read | Rows | Body estimate (bytes) | Median / max ms |
| --- | ---: | ---: | ---: |
| Project history first page | 50 | 25,836 | 19.38 / 23.56 |
| Deep ID keyset, before 5,000 | 50 | 26,535 | 15.62 / 17.51 |
| Project history, rare pool | 50 | 26,845 | 357.92 / 359.83 |
| Project history, absent pool | 0 | 2 | 349.06 / 349.67 |
| Grid headers, one pipeline | 25 | 13,140 | 0.35 / 0.86 |
| All cells for this grid | 250 | 70,733 | 0.56 / 1.05 |
| Active runs probe | 50 | 2,898 | 0.07 / 0.13 |
| Recent terminal feed shape | 50 | 3,750 | 1.54 / 2.02 |
| Recent feed with end-date/ID index | 50 | 3,750 | 0.11 / 0.32 |

The poll experiment used two synchronized waves of 50 local SQL clients through the API fixture's Engine DB connection pool. It measured checkout and active query time, without browser tabs, HTTP authorization, terminal feed queries or concurrent writes. At 15/5/3 seconds it yielded 591/389/386 ms p95 respectively over 100 samples per cadence. The ideal staggered rates are 3.3, 10 and 16.7 requests/s per polled read. The slower first burst has an ordering/warmup confound. These data are a reason to stagger, pause hidden tabs and stop terminal polling where the user can still explicitly refresh. They do not compare steady-state cadences or establish the #476 warm PostgreSQL feed budget.

For an ended-run cache, keep selected evidence separate from current operator capabilities, project permissions, log retention and later intervention state. A future prototype should validate against a terminal generation keyed by run ID. Reopen must replace that generation before it can be reused, with ended evidence served again after finalization. An ID-only or start-time validator cannot distinguish those cases.

The history bottleneck in this sample is the optional attempt filter even with tiny output. Keep the existing keyset and ask for PostgreSQL plans with restricted viewers, rare and absent matches, and realistic attempt skew. For Monitor, keep the partial active-state index and a bounded terminal feed. The candidate end-date index saved 1.43 ms in the local SQL probe. Defer it until the authenticated PostgreSQL feed shows a worthwhile improvement and the write/storage costs are known. Keyset SQL and grid evidence do not suggest run summaries on their own. Home's broad windowed Insights response and the selected demo's status fan-out point to different fixes first. There is no measured SSE or durable changes-cursor alternative at this revision.

## PostgreSQL invalidation

On local PostgreSQL, 100 committed changes reached two listening connections. A single version SELECT took 0.101 ms median and 0.142 ms p95 across 200 reads. Commit to notification consumption took 0.865 ms median and 1.118 ms p95 across two serially consumed listeners. These are small-message local transport measurements, without API authorization or deployment work. A notification moves invalidation work off the request only if a reliable recovery protocol can replace the durable version check. Reconnect needs to re-read the durable version and discard any uncertain local generation. A reader can still race notification delivery in normal operation. Every API replica checks the stored version on each request. The design has no notification subscriptions. SQLite uses the same stored-version check in its single API process.

## Publication and access contract

Keep only the latest completed definition generation per project. Build from a consistent Engine DB snapshot. Revalidate the version before publishing and swap the entire generation atomically, including its index. A request must resolve its scope and effective visibility before it can return either 200 or 304. Validate metadata/parse and the access representation independently. A project revision must cover deploy, re-parse and every authorized definition mutation that can bypass those two commands. If no existing cheap value can meet that contract, stop for a schema decision. A single project revision is a safe invalidation unit. Dependency-aware reuse of unaffected shard bytes would need its own consistency proof and a measured re-parse benefit.

Use `Cache-Control: private, no-cache`. Include representation identity and effective visibility in the validator where they affect bytes. For a restricted viewer intersect the index with their allowed pipeline IDs. Within the selected shard, filter cross-pipeline edges, table and column references, triggers, counts and any other derived data that expose a hidden pipeline before computing the validator. Keep one canonical shard per pipeline. The experiment's filtered index measures only ID intersection and serialization. It supplies the already-verified allowed set and does not test real grants or scoped edge filtering.

| Scenario | Proposed result |
| --- | --- |
| Engine DB unavailable | Refuse definition requests, including conditional hits, because current authorization cannot be established. An already open page retains its displayed content and shows a “can't refresh” notice. |
| Deploy or re-parse commits during assembly | Discard a build that observes a changed generation before publication. Rebuild against the new version or return retriable unavailability. A request that finishes against its earlier consistent snapshot carries that revision. A new request checks the new revision. |
| Grants revoked while shard is resident | Refuse the next unauthorized request including matching validators. Rebuild any representation whose visible edges or list changed. An already rendered response was disclosed before revocation. The next revalidation clears inaccessible content and marks failures. |
| Build fails halfway | Keep incomplete data private to the builder. Refuse the new generation explicitly until a retry succeeds. A consistent previous generation stays useful only where it is still authoritative. |
| API restarts | Resolve authorization and version before using the first body. Measure lazy first-request cost and transient duplicate builds before choosing an eager startup policy. |

## Owner decisions and release order

1. Finish [S7.BD](road-to-1.0.0.md#s7bd-bounded-catalog-lineage-lookup) first. Add the indexed trigger-reference lookup and keep the output-equality test. The measured assembly time fell from 110.5 s to 25.9 s.
2. Implement [S7.BF Scoped catalog reads](road-to-1.0.0.md#s7bf-scoped-catalog-reads) before 0.9.0, after S7.BD. Persist one slice per pipeline and a project index with the pipeline list, cross-pipeline table-level lineage edges and search entries. Use the index to preserve search and follow-lineage navigation. Apply grants to the served slices and index rows.
3. Refuse new definition requests during an Engine DB outage. Open pages retain displayed content with a “can't refresh” notice. Cached definitions are never served stale.
4. Each API replica checks the stored version on every request. Notification subscriptions are out of scope.
5. Use persisted slices. Reconsider in-process RAM only with a same-shape benchmark.
6. In [S7.BB.6](road-to-1.0.0.md#s7bb-run-monitoring), measure the authenticated PostgreSQL Monitor and sparse-filter history before proposing storage changes. Change storage only for a confirmed budget miss on the affected page.

S7.BD stays one PR. S7.BF has two slices for publication and authorized reads, then browser
navigation and evidence. Preserve the existing catalog operation and its whole-project file
semantics for existing callers. The plan adds no core dependency, server or setting. If a
stored version covering all definition writers requires a schema change, bring that change
back for approval. Consider ended-run caching after 0.9.0 only for a measured miss and with
a reopen-safe validator. Run-summary storage and a live changes cursor stay out of this plan.
