# Bundeskartellamt source audit — 2026-09-30, updated 2026-10-01

## Integration result — 2026-10-01 Asia/Taipei

After the bounded per-source floor was implemented, main ran the normal
robots-aware source-audit against BMI, BNetzA, BKA and SWP. Run
`dc8779b59fe1485792575cb1d6a2c99e` began at
`2026-09-30T23:53:59.287857+00:00`. All four endpoint and parse assessments
were healthy. BKA's parse completed in 152.160 seconds, with five requests,
seven raw/assessed articles, 100% high-confidence publication dates,
zero credible conflicts, future dates or missing required dates, and no failed
parse requests. It retained detail enrichment and respected Crawl-delay 30.
This is one live observation, not proof of complete historical coverage,
three qualifying runs, or a complete scheduled artifact/state acceptance.

The following sections preserve the earlier sandbox-limited probe and planning
evidence separately; their pending live work is superseded by the specific
integration result above, not by the offline synthetic fixtures.

Recommendation: retain `detail_pages = 12` and implement the coordinating user's
proposed `Source.minimum_budget_seconds = 0` with
`effective_budget = max(global_budget, source.minimum_budget_seconds)`.
Set only BKA's source floor to **600 seconds**. During this review the coordinating
task implemented the floor in the shared tree; this task verified its loaded
value, central deadline calculation and source profile/hash integration. The
reported first-party robots response specifies **Crawl-delay: 30**, making a
60-second source deadline incompatible with a full listing-plus-12-details run.
This is a request-cost budget adjustment, not a change to date or health quality
thresholds. This task made no canonical module or core edits.

The original sandbox DNS restriction was an execution-environment limitation,
**not evidence of a Bundeskartellamt website failure**. Primary live observations
reported by the coordinating user now fill the robots/latency gap below. They do
not yet establish full listing/detail date parity, relevant coverage parity or a
completed 600-second production validation.

## Scope and inspected implementation

Worktree: `/private/tmp/eu-crawler-audit.7A5hi9`.
Inspected `config.py`, `http.py`, `http_cache.py`, `robots.py`, `scraper.py`,
`parsers.py`, `models.py`, `source_audit.py`, `organisation_registry.py`, the
canonical Bundeskartellamt JSON, and the production workflow.

Runtime loads canonical organisation JSON by default; `sources.toml` is the
compatibility export. The observed registry has 148 total sources, 55 scheduled,
and 53 scheduled/unpaused on 2026-09-30. European Parliament and CEA remain paused
through 2026-10-31. No source configuration, pause, HTTP, parser, workflow, budget,
or date-health gate was changed by this audit.

The configured listing is:
https://www.bundeskartellamt.de/DE/Home/home_node.html

Cards: `div.c-teaser`; links: `.c-teaser__link-wrapper a`; titles:
`.c-teaser__headline`; dates: `.c-topline__item:last-child`.
Only `/SharedDocs/Meldung/DE/Pressemitteilungen/` HTML article URLs are accepted.
The source requires publication dates and uses `Europe/Berlin`. It has no
configured feed or explicit summary selector.

`scrape_source` initially had one 60-second deadline covering robots, listing,
parsing and detail enrichment; main's subsequent change applies the source floor
to that same deadline. Its timeout handler discards partial articles and resets
page/raw counts; those zero counts alone cannot identify which phase stalled.
HTTP requests use a per-host semaphore of two, a serialized pacing clock, and
an effective interval of `max(min_interval, robots crawl-delay)`. Redirects and
the built-in second attempt consume additional requests. Normal production uses
`obey_robots=True`, `min_interval=0.5`, and conditional response caching.

Detail candidates include missing dates, non-high-confidence dates, **or summaries
shorter than 40 characters**, with high-confidence out-of-period items excluded.
Thus high-confidence listing dates alone do not make detail requests unnecessary.
The first paragraph in the historical card is its category/date, not a substantive
summary. A new listing with genuine summaries could avoid requests through the
existing implementation, but requires live coverage/date verification first.

## Sandbox-restricted request attempt with the existing HttpClient

Called `HttpClient(timeout=15, obey_robots=True, min_interval=0.5)`, without cache,
custom transport, custom user agent, altered TLS, or escalation. The listing get
was wrapped in a 60-second deadline. Read-only diagnostic overrides timed the
existing `_pace` and `_read_response` implementations without changing behavior.
The coordinating user confirmed that the DNS error was caused by the sandbox;
the error string alone does not diagnose the website's DNS or availability.

| Phase | Observed result | Seconds |
|---|---|---:|
| robots network attempt 1 | `ConnectError: [Errno 8] nodename nor servname provided, or not known` | 0.005 |
| robots network attempt 2 | same DNS error | 0.008 |
| pacing before either attempt | no positive wait observed, rounded | 0.000 each |
| cold client creation plus listing get | `RobotsUnavailableError` before listing transport | 0.715 |
| listing transport | not issued | unmeasured |
| detail transport | not issued | unmeasured |

Robots URL: https://www.bundeskartellamt.de/robots.txt

Statistics: 2 request attempts, 1 retry, 0 bytes, 0 HTTP responses/statuses,
0 HTTP timeouts, 0 cache hits. The elapsed total includes initialization and the
existing randomized retry wait; those components were not individually timed.

This sandbox probe did not establish crawl-delay or robots permission. No
robots body was returned and no host delay was installed. There is no local
`.state/.http-cache` response cache or captured Bundeskartellamt robots fixture
in this worktree. The SWP crawl-delay reported by the coordinating task cannot
be assigned to Bundeskartellamt. No request bypassed the robots failure, and no
alternative endpoint was guessed, accessed through a different client, or adopted.
First-party dated listing/RSS discovery remains unverified by this probe. The
coordinating task subsequently obtained the primary live observations in the
next section. The lack of robots content here no longer means the site's actual
delay is unknown.

## Primary live observations supplied by the coordinating user

Provenance: the user reported these results from the main task's escalated
read-only requests. This task did not repeat network access or obtain the complete
251-byte robots body. No synthetic fixture is presented as that raw response.

| First-party URL / response | Reported result |
|---|---|
| `https://www.bundeskartellamt.de/robots.txt` | HTTP 200, plaintext, 251 bytes, `Crawl-delay: 30` |
| Homepage content | HTTP 200, 171613 bytes, two observations of 5.78 and 2.37 seconds |

Configured home: `https://www.bundeskartellamt.de/`; configured listing:
`https://www.bundeskartellamt.de/DE/Home/home_node.html`. The message did not
provide a separate final homepage URL, complete redirect history, robots
download duration or individual detail durations. The home latencies are not
whole-source measurements and cannot be treated as a bound on detail responses.
The main task must retain raw robots/group selection and any per-path permission
results with its own live artifacts.

The coordinating user withdrew the earlier suspicion about HTML base resolution:
the inspected `parse_listing` already honors `base[href]`. Existing synthetic
base/relative-link tests remain useful contracts; there is no generic parser fix
required by this audit.

## Source budget semantics and concrete recommendation

At the initial inspected implementation, `Source` had no per-source budget field.
`load_sources_and_registry` explicitly builds `Source` and therefore would not
activate a JSON-only budget key. The CLI passes the global `--source-budget`
value to `scrape_source`, whose effective deadline is currently
`max(1, source_budget_seconds)`. Source-audit passes `max(60, timeout)`.
Neither initially applied a source floor. The subsequent main-owned change now
adds `Source.minimum_budget_seconds`, loads it and resolves it centrally inside
`scrape_source`; the CLI and unchanged audit caller therefore both honor it.

Adopt the proposed `minimum_budget_seconds: int = 0` (zero means no additional
floor), validate it as a non-negative integer with booleans rejected, load/export
it faithfully, and use one shared effective-budget calculation in `scrape_source`:
`max(1, source_budget_seconds, source.minimum_budget_seconds)`.
Then existing CLI and audit callers both honor the same floor. BKA gets 600;
the other active sources keep their global 60-second budget unless separately
configured. A global value of 900 must raise BKA's effective budget to 900; a
global value below 600 must not lower its declared 600-second source floor.
Document `--source-budget` as a global baseline with source-specific floors,
and record both configured and effective budgets in run diagnostics. Read-only
inspection of main's current edits confirms the field is bounded to 0–900,
rejects booleans, is loaded from canonical JSON, is set to 600 for BKA, and uses
the stated central max calculation. CLI help and README explain floor semantics.

**Homepage and listing endpoint audits are outside the parse deadline.**
`audit_sources` checks home, listing and any configured feeds sequentially, then
calls `scrape_source`. Those endpoint checks share the same HttpClient, robots
cache and origin pacing clock with parsing. Their elapsed time must not be
charged again as full homepage downloads inside the source deadline, but any
remaining origin wait at parse entry is inside that deadline (up to 30 seconds
without other traffic/cooldowns). The total source-audit wall time is endpoint
checks plus parse, so it may exceed 600 without a parse-budget violation.
Raising audit `--timeout` to 600 is not an equivalent workaround: it changes
each HTTP/DNS timeout and the audit's generic budget, rather than just BKA's
request-cost allowance. Keep per-request timeouts and quality gates unchanged.

Pacing calculation for one listing and twelve selected details, on the same
origin with no redirects/retries: **13 allowed page requests have 12 start gaps,
so their start-to-start span is at least 12 × 30 = 360 seconds**. Robots is a
fourteenth HTTP request on a cold client, but it is obtained before the 30-second
policy is installed. Current HttpClient initially paces it with the 0.5-second
minimum, so adding an unconditional extra 30-second robots gap would overcount
this implementation's cold sequence. A warm source-audit client can instead
enter parsing with nearly 30 seconds of outstanding origin pacing.

For healthy responses taking less than 30 seconds, intermediate transfer time
overlaps the pacing gaps; it should not be summed as 13 × timeout on top of 360.
A conservative operating allowance is roughly 360 seconds of page pacing,
up to 30 seconds of existing host wait, allowance for robots acquisition when
cold, final response completion, parsing and scheduling. Using 25 seconds each
for robots and final transfer gives a planning envelope around 440 seconds with
ordinary overhead. This is a planning assumption, not a measured hard bound:
HTTPX's read timeout applies per read, not to the total streamed response.
The **600-second floor** leaves roughly 160 seconds of additional headroom,
equivalent to about five extra 30-second request slots under the same healthy
response assumptions. Retries, redirects, longer reads and server cooldowns
consume that headroom; request start gaps remain 30 seconds, even with two
per-host connections. The deadline still cancels incomplete work normally.

Do not claim 600 guarantees every permitted retry. If each of the thirteen page
requests retries once, there are 26 page attempts and 25 gaps: **750 seconds of
pacing alone**, plus initial wait/final transfer. More redirects or slow streaming
can take longer. Supporting that worst-case scenario would require a separately
justified larger bounded budget; it does not justify changing robots behavior,
silencing fetch failures or reducing detail quality. Start with 600 for the
observed 30-second source, then retain per-phase live measurements and evaluate
timeouts without weakening the existing quality gates.

Profile/hash integration needs both paths: source-audit's `config_hash` hashes
`asdict(source)` with SHA-256, so a real dataclass field is automatically included.
The registry hash also includes canonical JSON. Production health uses an
explicit field dictionary in `health.source_config_fingerprint`, so the new floor must
be added there; CLI profile `source_settings` is also explicit and should report
the floor. Main's current edits include both fields, and this task's module-level
tests verify that changing only the floor changes the audit SHA-256 and health
source fingerprint. Do not assume adding the dataclass field alone updates every profile.
Changing the floor should start a distinct source configuration era for audit
promotion and health comparisons, while retaining the existing dates, summaries,
source selection, request failures and artifact-quality requirements.
Compatibility requirement: an unchanged source with the new default floor of
zero must retain its existing production health fingerprint. Merely adding a
zero-valued default key to a hashed dictionary must not reset every source's
baseline. A nonzero BKA floor must still participate in its fingerprint. Main's
review agent identified the default-key reset issue and main is correcting it;
the earlier floor-difference test does not by itself verify legacy compatibility.

## Existing evidence, distinct from the sandbox-restricted attempt

Read the already-present reports; no GitHub operation or external write occurred.

`source-audit/scheduled-compatibility/source-audit-dae247a25a2c7e999e918419be0cdf421f3e68deee3ab9c5b3011cf392a36636.json`
records timestamp `2026-09-30T07:06:02.879914+00:00`:

| Earlier phase | Result | Seconds |
|---|---|---:|
| Homepage endpoint, including 302 to listing | 200, 171613 bytes | 40.134138 |
| Listing endpoint | 200, 171613 bytes | 31.940328 |
| Subsequent scrape | `SOURCE_BUDGET_EXCEEDED`, 2 attempts, 1 retry, 0 bytes, no statuses | 60.005 |

These endpoint checks are separate from the scrape deadline. They do not supply
individual robots, pacing, or detail timings. The subsequent scrape's zero
completed responses means it did not obtain listing content to parse or enrich;
this observation does not support blaming 12 completed detail fetches.

The existing downloaded reports for runs `36683006047` and `36683317799` record
60.008/60.010-second source timeouts, each with 3 requests, 309037 bytes, three
200 statuses, no retries, and one deadline timeout. They do not retain URLs or
phase timings for those requests. Unlike the preceding zero-byte observation,
these runs may have reached enrichment; their exact phase cannot be inferred
from the timeout handler's zero page/raw counts.

## Offline date and coverage evidence

Existing `tests/fixtures/contract_de_bundeskartellamt.html` is labelled as captured
2026-07-18 from the configured homepage listing. SHA-256:
`fc89e49b6cd18dd8d339d57091d9de53577852ecce8dde949e767cd2fe54d579`.
Its one real card parses as:

- Title: `Erhöhung der RWE-Anteile an Amprion freigegeben`.
- Publication: `17.07.2026`, local date `2026-07-17`, UTC `2026-07-16T22:00:00+00:00`.
- Date source/confidence: `source-selector` / `high`; conflict false.
- Summary: `Pressemitteilungen 17.07.2026`, below the 40-character detail threshold.
- One cold offline listing parse took 0.034119 seconds; this is not a live-page
  performance measurement and does not measure a full twelve-card listing.

This single historical card cannot establish current listing/detail date parity
or relevant coverage parity. Existing topic-evaluation rows also contain short
category/date summaries; they do not provide current substantive detail text.

New fixtures explicitly label synthetic markup and adversarial cases. Tests
retain real local publication-day handling; reject malformed/missing dates as
high-confidence evidence; ignore event dates, navigation titles, non-news URLs
and external hosts; retain undated records in the raw health assessment; record
credible detail/listing date conflicts; reject conflict-based promotion; verify
short-summary detail requests; and verify no listing/detail transport when
robots is denied or unconfirmed. A synthetic summary-only topic hit demonstrates
why equal date rates do not prove equal relevant coverage when details are cut.

The coordinating user also reported first-party BNetzA markup containing
`<base href="/">` and relative `SharedDocs/...` links. The BKA historical capture
contains an absolute article href and no document base; it cannot confirm that
BKA currently uses the same markup. The new quality fixture therefore labels
its base and relative hrefs as synthetic. Tests require the exact root-relative
resolved article path (not merely a matching include-pattern substring), while
retaining the genuine local date, high confidence, zero conflict and malformed
date behavior. The subsequent user correction confirms the inspected generic
parser already honors `base[href]`; the earlier broken-base suspicion is withdrawn.
HTTP/core work remains owned by the coordinating task; this task edited none of it.

## Required evidence before a speed change

The main task owns the already-authorized live follow-up and actual module/core
changes. This task will not repeat network requests. Retain the actual robots
body and selected delay; time network, pacing, redirects/retries, listing parsing
and every selected detail. Discover first-party news/RSS links from allowed
content and verify each proposed endpoint against the same robots policy.

Compare complete listing and enriched raw records over the same period: URL/title
coverage, relevant hits including summary-only hits, local dates, date confidence,
missing/future dates and credible conflicts. Preserve the 53-source production
selection, the 60-second global baseline with the recommended BKA 600-second
source floor, high-confidence gate of at least 75%, conflict gate
of at most 5%, and existing required-date, freshness, artifact and health gates.
Only reduce `detail_pages` if this establishes equal date quality and relevant
coverage. A green timeout result obtained by discarding news is insufficient.

## Verification and edited files

- `tests/test_bundeskartellamt_source.py`: 21 offline cases, including virtual
  30-second pacing for cold and audit-warmed clients with and without retries;
  actual scrape-deadline floor resolution; and audit/health source fingerprints.
- `tests/fixtures/bundeskartellamt_listing_quality.html`: historical card plus
  explicitly synthetic document-base, relative-link, malformed, missing,
  navigation and foreign-host cases.
- `tests/fixtures/bundeskartellamt_detail_quality.html`: explicitly synthetic
  publication metadata, event date and navigation heading.
- `tests/fixtures/bundeskartellamt_source_audit.md`: this factual report.

Earlier, the then-current source tests, HTTP-policy tests and source-audit workflow
tests passed together: 72 passed; two existing Bundeskartellamt contracts passed
separately. The virtual pacing cases subsequently passed: healthy cold sequence
366.28 seconds and audit-warmed sequence 390 seconds under the explicitly
synthetic 5.78-second-per-page scenario. All-page retries require at least 750
seconds of page-start spacing and exceed 600 in both scenarios.

Final read-only runtime inspection confirms 53 scheduled/unpaused sources,
global baseline 60, BKA floor 600, required dates, the original listing URL and
`detail_pages = 12`. The BKA module and core changes now visible in the shared
tree belong to the coordinating task, not this audit. This task only edited its
test file and `bundeskartellamt_*` fixtures/report. No git mutation, external write
or repeated network request occurred. The floor recommendation and offline tests
do not substitute for a complete live source/quality validation.

Final focused verification: all 21 cases in `test_bundeskartellamt_source.py`
passed, the two existing Bundeskartellamt source contracts passed, and Ruff passed
for the owned test file. No live execution was performed by this task.

## Latest integration status supplied by the coordinating user

- Main implemented BKA's 600-second source floor and reported 704 tests passing.
- Main reported the dependency security fix to `urllib3 2.8.0`.
- The official four-source audit is still running; elapsed time was reported as
  over five minutes. No completion, source-health result or quality acceptance
  is claimed here. Audit endpoint checks precede the parse deadline, so overall
  elapsed time alone cannot establish how much of BKA's 600 seconds remains.
- Main's review agent found mixed HTML `div` content mishandled by the MIME/robots
  detection and the default-field health-fingerprint reset described above.
  Main is fixing both. The reported 704-test snapshot is not represented as
  verification of those subsequent repairs.

These are user-supplied integration updates, not fresh observations by this
task. No additional research, network access or test run was performed for this
report-only update. The completed recommendation remains: BKA floor 600,
global baseline 60, twelve detail pages retained, and existing date/summary,
source-health and artifact gates preserved.
