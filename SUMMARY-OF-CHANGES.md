# Summary of Changes -- 3.0 "Director's Cut"

Detailed development log for the 3.0 cycle. [CHANGELOG.md](CHANGELOG.md) carries the release-facing summary; this file carries the commit-level detail, the breaking changes with their blast radius, and the security analysis behind the milestone blockers.

The 2.0 "Midnight Premiere" log (beta1 through beta18, every Added / Changed / Fixed bullet and the 2.0 technical deep-dives) is not carried forward. It is preserved unchanged at the [v2.1.0 tag](https://github.com/Oratorian/emby-watchparty/blob/v2.1.0/SUMMARY-OF-CHANGES.md).

---

## [Unreleased]

### Four provider variables collapse into two

**Blast radius: every deployment. 3.0 refuses to boot until the operator edits
the environment.**

`EMBY_SERVER_URL` and `JELLYFIN_SERVER_URL` become `MEDIA_SERVER_URL`;
`EMBY_API_KEY` and `JELLYFIN_API_KEY` become `MEDIA_SERVER_API_KEY`.
`MEDIA_SERVER_TYPE` is untouched, stays explicit, and is still not
auto-detected.

The four existed because Jellyfin support was added by duplicating the Emby
pair rather than by asking which part of the configuration was actually
provider-specific. One part was: which dialect the server speaks. A URL is a
URL and an API key is an API key. The duplication bought a second name for each
plus a rule to arbitrate between them, and that rule -- the selected provider
never falls back to the other provider's variables -- only needed to exist
because the second name did.

**No aliases, no fallback reads.** A retired name found in the process
environment or `.env` is a boot error naming its replacement, and it is an
error even when the new name is set too, since a half-migrated `.env` holding
both is precisely the case where which value survives depends on line order.
Both softer options are worse. Reading the old name as a fallback postpones the
break to a release where nobody is reading migration notes. Ignoring it boots
the server against the default `http://localhost:8096`, which reaches the
operator as an empty library rather than as a configuration error, a symptom a
long way from its cause.

`Config.boot_warnings()` is deleted along with the concept it existed to warn
about: there is no inactive provider variable left to be inactive.
`MEDIA_SERVER_URL` and `MEDIA_SERVER_API_KEY` are real `EnvConfig` fields
rather than values synthesised in `Config.__getattr__` from whichever provider
was selected, and `MEDIA_SERVER_URL_VARIABLE`, which existed only to report
which field that had been, is gone entirely.

The migration preflight reports the rename as a `REQUIRED ACTION` ahead of the
boot gate, and separates the three shapes an operator can arrive in: one
retired name to rename, both provider variants set so a human has to choose
which value survives, or the new name already in place beside a leftover old
one. The boot gate reports retired names one at a time, which would read as two
instructions to move two different values into one variable.

Deployment artifacts are regenerated from `deploy/schema.json`. Its
`schema_version` stays `1`: that number versions the schema format, not its
contents.

---

## [3.0.0-beta3] - 2026-08-13 - Director's Cut

Two bodies of work. A UX pass over the title detail view and the party header,
driven by using beta2's library rather than by a report; and an audit of the
test suite itself, which is the larger half and the reason this section is
mostly about tests.

Published as `:3.0.0-beta3`, and tracked by `:devel` and `:nightly`. Image-only, as
every beta on this project has been: no git tag, no GitHub Release, no release
assets. `:latest` stays on the 2.1.x stable line.

---

### The UX pass

Nine commits, all on `TitleDetails.vue`, `PartyView.vue` and `AdminPanel.vue`.
The detail view's controls were correct and badly placed: sections expanded
downwards and stacked, a series rendered one row per episode, and the whole
group sat below the synopsis so its position moved with the length of the
synopsis. They are now one popover opening upward, two dropdowns, and a
`.detail-topbar` beside Back.

Three of these were placement problems rather than behaviour problems, which is
worth recording because the existing tests could not have caught any of them:
they selected buttons and popovers globally and so constrained nothing about
where anything lived.

Two smaller pieces landed alongside. Party visibility is host-controlled and
parties now start hidden, with a **known consequence accepted at the time**: a
party that has never had a host cannot be listed by anyone, so Active Parties
stays empty until a host logs in and opts in. Previously every party with
members was listed, hostless ones included, shown as locked. And the admin
rate-limit fields became number-plus-window pairs matching the two that already
worked that way.

---

### The test-suite audit

The suite was green throughout: 270 backend, 85 frontend, 27 e2e. The question
was not whether it passed but whether it could fail. Six read-only agents over
six areas, each area's findings then put to an adversarial verifier told to
refute by default and to treat coverage hiding in an unexpected file as the
most likely reason a "missing" finding is wrong.

**66 raw findings, 47 confirmed.** Categories were fixed rather than counted:
`stale` (asserts on markup the redesign deleted), `vacuous` (cannot fail), and
`missing` (nothing covers it at all). A finding was only accepted with a named
mutation to the **source** that the whole suite would not notice.

Every fix was then checked by applying that mutation for real. **64 mutations,
64 caught.** Two survived on the first attempt and are the more interesting
half of the exercise:

- The sanitizer's privacy inheritance could be removed without any test
  failing, because default-deny caught the leak anyway. The two rules only come
  apart under a key that is otherwise allowed through verbatim, so the probe was
  rewritten to use one.
- The episode-control reset could not be observed the way the audit proposed.
  The handler writes `''` back over what `v-model` just set, so the ref ends the
  tick reading what it last rendered and Vue schedules no update; the element
  keeps showing the picked episode until something else re-renders. Harmless,
  since choosing an episode navigates away, but the suggested assertion fails
  against correct code and the test now forces the render instead.

#### Two real bugs, not coverage gaps

**A dead-party flag outlived its view.** The party store deliberately survives
`PartyView` unmounting, and `leave()` never cleared `partyMissing`. After the
countdown returned a viewer to the index, the next party they opened rendered
"This party no longer exists" on mount, and rendered it frozen, because the
countdown is driven by a watcher that fires on the transition into missing and
that had already happened. Only "Go now" got them out. Cleared in `leave()`, and
again at the top of `join()` before its first await so navigating straight from
a dead party to a live one does not show the card for the duration of the join.

**`streams_changed` reported the wrong position.** The clamp added in beta2
starts a switched stream at a corrected offset, but the event kept sending the
raw party clock, and the client maps the new stream's `t=0` onto whatever that
field says. Switching to a version shorter than the current position therefore
left the viewer's reported position minutes ahead of the frame on screen with
drift correction fighting the gap. The frontend comment stated the assumption
outright and had simply stopped being true. Found because the audit noted its
proposed assertion would fail against the source; that failure was the finding.

#### What kept recurring

Three shapes, all of which had produced real incidents on this project before:

1. **An assertion that survived its subject.** `findAll('button[data-episode-id]')
   .toHaveLength(0)` counted markup the redesign had deleted, so it held for any
   template, including one that had dropped the attribute entirely.
2. **A test satisfied by the framework.** Re-selecting a `<select>` option and
   counting emits proves nothing: `setValue` dispatches `change` whether or not
   the value moved.
3. **An expectation derived from its subject.** The clamp asserted
   `start == 7200.0 - END_OF_MEDIA_BUFFER_SECONDS`, leaving the constant's size
   unpinned in both directions. `1800.0` passed.

#### The gaps that mattered most

- **The artifact sanitizer had no coverage at all**, which is the tool behind
  the leak recorded in beta2. `test_emby_artifacts` checks the committed corpus,
  which only proves today's files are clean; it says nothing about what the next
  capture writes, and captures run against a real private Emby and land in a
  public repo. All three defects behind that incident were invisible from the
  output side. Now 11 tests, written as properties rather than as a list of the
  fields that leaked, because Emby adds fields between versions.
- **Contract drift was structurally invisible to pytest.** The only
  `--check` ran in one CI step, so removing an event from `INBOUND_MODELS` /
  `OUTBOUND_MODELS` kept every render-based test agreeing with itself while the
  frontend stayed typed for an event the backend no longer accepts. Both
  generators are now checked from the suite.
- **`video_codecs` on `join_party` had no assertion anywhere.** Dropping it, or
  hardcoding it, left the suite green while every viewer silently fell back to
  h264 and every HEVC source was re-encoded for people whose hardware would have
  played it. A merge on this branch nearly did exactly that.
- **The identity-collision message is one contract in two languages.** The
  frontend matches the backend's sentence verbatim to decide whether to rotate
  onto a tab-scoped client id and retry. Rewording the Python left both suites
  green while second tabs stopped recovering. Asserted from pytest, the only
  side that can read both files.
- **`select_video`'s `resume_mode` and its host-only `binge` rule** were
  untested. Both fail quietly, and the binge one let any joined member arm
  auto-advance for the whole room.

#### The e2e specs, which no suite runs

These had never run against the redesigned UI, because nothing on this branch
has been pushed. Rather than reading selectors, all four Playwright projects
were run locally: chromium 18, ios-webkit 3, firefox 3, webkit 3, all passing.
The specs drive by role and test-id rather than by the classes the redesign
moved, which is why they survived.

Two real problems in them, both found by reading rather than running:

- `getByRole('button', { name: 'Close chat' })` resolved to the `.chat-backdrop`
  overlay, whose `aria-label` is that string, rather than to the drawer's close
  button, whose accessible name is its text. Nothing proved the button did
  anything. Both exits are now asserted by effect.
- Every desktop spec ran at 1138px, inside beta2's compact-desktop media query,
  so the layout most people use had no coverage. Widening that query to swallow
  the ordinary desktop failed nothing.

#### Verification posture

| | beta2 | beta3 |
|---|---|---|
| backend (pytest) | 270 | 298 |
| frontend (vitest) | 85 | 152 |
| e2e (playwright) | 27 | 28 |

Plus ruff check and format, mypy over 48 files, `vue-tsc`, eslint, and both
generated-contract drift checks, which now run under pytest rather than only in
CI.

#### The shared toggle had no name

`ToggleSwitch` renders its `<input>` inside its own `<label>`, but every one of
its eleven call sites puts the wording in a sibling element outside that label,
so the association never formed. All eleven announced as "checkbox, not
checked" with nothing saying which setting was about to change; on the admin
panel that is nine consecutive identical controls.

The `label` prop is **required** rather than optional, so `vue-tsc` refuses a
call site that forgets it. Optional would have let the next one reintroduce the
same silence. The input also carries `role="switch"`, which is what it is: a
screen reader then says on/off rather than checked/not checked, while the
element stays a real checkbox so keyboard behaviour and the `:checked` styling
remain the browser's.

`CONTRIBUTING.md` was reworded in the same pass to tell contributors to add a
`## [Unreleased]` heading rather than to file under one that only exists
between releases.

#### Recorded rather than quietly fixed

Three process notes, kept because each was a mistake in this cycle:

- One batch was committed with `git add -A` under a message describing only the
  source fix in it. Reset and split into three.
- `npx` rewrote `frontend/package.json` and `package-lock.json` mid-session,
  adding `playwright` to `dependencies` where `@playwright/test` already sat in
  dev. Reverted rather than committed. A subsequent `npm ci` installed from that
  mangled lock and produced a broken jsdom, which was briefly misdiagnosed as
  the committed lockfile being at fault; it is not, and `3.0-dev`'s is sound too.
- The frontend suite was exiting non-zero while reporting 152 passed: a new
  `playing: true` case made `loadedmetadata` call `video.play()`, which jsdom
  does not implement, raising an unhandled rejection that fails the run without
  failing a test.

#### Still open

- `frontend/package.json` and `backend/src/__init__.py` still read
  `3.0.0-beta1`.
- The artifact leak's external half is unchanged and not ours to close:
  dnordel's fork branch `codex/emby-library-parity`, and `refs/pull/60/head` on
  `Oratorian/emby-watchparty`, which needs GitHub Support.

---

## [3.0.0-beta2] - 2026-08-13 - Director's Cut

Four bodies of work since beta1. Three are **[dnordel](https://github.com/dnordel)**'s, all
landed on `3.0-dev` via their branch after an audit rather than through a PR merge:
appliance deployment ([#58](https://github.com/Oratorian/emby-watchparty/pull/58)),
migration diagnostics ([#57](https://github.com/Oratorian/emby-watchparty/pull/57)) and
library parity ([#59](https://github.com/Oratorian/emby-watchparty/pull/59) +
[#60](https://github.com/Oratorian/emby-watchparty/pull/60)). The fourth is per-viewer codec
negotiation ([#61](https://github.com/Oratorian/emby-watchparty/issues/61)), built on the
stable line and forward-ported.

Never published as its own image. There is no `:3.0.0-beta2` tag on GHCR; this work
ships inside `:3.0.0-beta3`, which is why both sections carry the same date.

---

### Library parity

**[dnordel](https://github.com/dnordel)**'s, as [#59](https://github.com/Oratorian/emby-watchparty/pull/59) and [#60](https://github.com/Oratorian/emby-watchparty/pull/60): 39 commits over 89 files, `+23872 / -226`, of which roughly 17000 lines are a captured corpus of real Emby 4.9.5.0 responses rather than code. Filters driven by server capability, an A-Z jump backed by Emby's prefix index, grouped search, a full title detail view, and host actions for played/favourite/playlists.

#### The stacking, and why neither could merge

#60 targets #59's branch rather than `3.0-dev`, so one blocked merge blocked both. #59 branched before the codec negotiation landed and conflicted with it in `SUMMARY-OF-CHANGES.md`, which is all GitHub needed to refuse. Assembled locally instead; both PRs are closed with that explanation.

Only one conflict needed judgement rather than a side. #60 moved the `join_party` emit inside `if (bound)`, so a tab that failed to bind no longer announces a join, while the codec work had added `video_codecs` to that emit while it still sat outside the block. Taking #60's version drops `video_codecs` and silently returns every viewer to h264-only with no test failing; taking the other leaves two emits so every successful join fires twice.

#### The audit

Twelve dimension finders over the merged diff, each finding then put to three adversarial verifiers on different lenses (is it reachable, is it handled elsewhere, does anything actually break) with the default set to refuted. 229 agents, 77 candidates, **64 confirmed**: 6 critical, 26 high, 26 medium, 6 low. All fixed here.

The `authz-writes` dimension came back clean, which is worth recording: the new `PUT favorite`, `PUT played` and `POST playlists` routes act on the host's Emby account from a party containing untrusted guests, and that was the sharpest question going in.

#### Two merge blockers that were green, not red

Neither showed as a failure, which is why they matter more than the count suggests.

The 80% changed-line coverage gate matched **zero** Python lines and reported 100%. coverage.py names each file relative to its `--cov` root (`src/app.py`) while the diff produces repo-relative paths (`backend/src/app.py`), so the two sets could never intersect. Measured on this branch's own diff: 2946 changed Python lines, 0 matched. Its unit test could not catch it because the fixture hand-wrote a path shape coverage.py never emits. A per-language breakdown now prints on every run, because a gate measuring nothing is indistinguishable from a gate passing.

The `container` job could never go green: it starts the fake Emby on loopback and then points the containerised app at the docker bridge gateway. `ci-gate` requires that job, so every PR was blocked. Demonstrated by connecting from this machine's own non-loopback address rather than by reading the config.

#### A public, permanent leak

`scripts/capture_emby_artifacts.py` pulls from a real Emby into a corpus committed to a public repository, and its sanitizer was **default-allow**: any key nobody had explicitly listed passed through. `SortName`, `ForcedSortName` and `FileName` shipped verbatim beside the `<text-037>` placeholders meant to anonymise them, so `"…And Justice for All"` and `24 S01e01 1200 A.M. - 100 A.M..mkv` sat next to their own redactions. `system-info.json` carried the capture machine's hostname.

The `providerid` rule was dead code. `ProviderIds` is a dict and the key check sat below the dict-recursion branch, so it could never fire: 97 raw Imdb, Tmdb, Tvdb, TvRage and Zap2It ids shipped, and an external id re-identifies a title on its own.

The leak test could not fail. `PRIVATE_MARKERS` listed `api_key`, `access_token`, `password` and two IP prefixes, every one of them a string the sanitizer already redacts unconditionally, so the assertion had nothing to match and passed over a corpus containing all of the above.

All three had to hold simultaneously for this to ship. The sanitizer now default-denies with the private flag inherited through the recursion, the test asserts the positive property (every string leaf under a title key, a private ancestor, or matching a content-betraying shape must be a placeholder), and the committed corpus is repaired in place: 169 values across 10 files.

The branch history was then rewritten so that no commit on it ever carried the raw corpus. 28 of its 60 commits did; all 28 now hold the sanitized version. Verified by walking every commit for the hostname and the external ids, both now zero, with the final tree byte-identical to the pre-rewrite branch. The local refs that held the raw blobs are deleted and the objects pruned.

Worth stating precisely, because the first framing of this was too broad: the raw corpus has **never** been on any Oratorian branch, pushed or local. `3.0-dev` and `main` do not contain it, so nothing published ever carried it and no force-push is needed. The remaining exposure is dnordel's fork branch and the `refs/pull/60/head` that GitHub retains for the closed PR, neither of which a rewrite here can reach. Clearing those needs dnordel to delete the fork branch and GitHub support to purge the PR ref.

#### Both recurring patterns, again

Third cycle for both, and together they account for most of the yield.

*The harness is more permissive than the real server.* Seven detail endpoints ran `del item_id` and answered any id with a fully shaped payload. `_filter_artifact` truncated every captured catalogue to a single row, so the fake could not express a filter control with more than one option. The fake served no Images route at all, so `/api/image` answered 404 in every run and the artwork proxy had no executable coverage, which is what hid `item_id` being the one value interpolated raw into the upstream URL while type and index were both constrained. Failure injection was wired into five legacy handlers and none of the library ones, so every new upstream-failure path was untestable in principle.

Four tests were confirmed unable to fail. `test_filter_options_are_capability_driven_from_emby` passed with every scoping parameter deleted. The multi-value filter test sent one element per list, and a single-element list joins to itself under any separator, so all fourteen could have been replaced with garbage.

*The twin path.* `_normalize_items_response` guarded the POST twin but not GET, which hits the same upstream endpoint and 500d on the exact row the guard was written for. `/api/search` took an uncapped `q` where `/search/grouped` capped at 200, and ranking is O(len(q) x len(title)) on a single event loop. `GET /api/items` forwarded `startIndex` and `limit` to Emby unbounded where the POST twin bounds both. `ChangeStreamsPayload` left stream indices unbounded where `SelectVideoPayload` bounds them. The version switch passed the raw party clock as a start time where both sibling paths clamp.

The audit named eight routes missing the upstream-error mapping; enumerating the router found **thirteen**. Rather than write a thirteenth copy, it is registered once for the whole application, which is the shape of most of these fixes: one authority instead of N copies. `query_items` now calls the same scope resolver `GET /api/items` uses; `clamp_start_seconds` is one shared helper; the REST contract is checked by the compiler.

#### What the fixes exposed on their own

Three defects the audit did not find, surfaced by the repairs.

`get_libraries` swallowed upstream errors and returned `{"Items": []}`, which the UI renders as "No items found." An unreachable Emby was reported to the viewer as an empty media server, the one diagnosis guaranteed to send them looking in the wrong place.

`LibraryItem.Type` was declared `string` while the backend declares `str | None`. The lie was load-bearing: `LibraryBrowser` guards `it.Type &&` in one branch and omits it in the neighbouring line, which only reads as safe because the type claimed null was impossible. Found by wiring the generated REST types into the build.

That same assertion found nine fields the backend has always sent that the frontend type never declared, `SeriesId` among them, so components needing the parent series redeclared a local shape instead.

#### Verification posture

Every fix for a real defect has a test proven to fail against the code it replaces, by reverting the source and rerunning. Where a test passes on both sides it is labelled a guard rather than passed off as coverage: two of the four `VideoControls` tests are guards, and the commit says so.

Two fixes initially shipped without a test, flagged rather than implied, and both now have one. The party-rejoin hang mounts `PartyView` against a store that already knows the party and asserts the join is re-emitted; restoring the old guard fails that case while the other two keep passing, which is precisely the reported symptom. The filter-panel wipe drives an aborted fetch, leaves the library and returns, and asserts the second visit refetches; restoring the old catch fails it with one call instead of two. A second case pins that a genuine failure still empties the controls, so the abort path cannot become a way to swallow real errors.

One test was written, found to be a tautology that re-implemented the clamp arithmetic it was meant to check, and deleted in favour of one driving real Emby tick payloads. A `vue-tsc` error was committed and caught one commit later, because the exit code had been read through a pipe and reported `tail`'s status.

State after this work: **267 backend tests** across 36 modules, **70 Vitest** across 23 files, **16 Playwright**. `ruff check` and `ruff format --check` clean over 90 files, `mypy` clean over 48, eslint and `vue-tsc` clean, the socket contract, the REST contract and the deployment artifacts all free of drift. All on 3.12.10, run with CI's exact commands.

---

### Per-viewer codec negotiation

Reported by **[miakkia](https://github.com/miakkia)** as [#61](https://github.com/Oratorian/emby-watchparty/issues/61), with a local patch and a measurement showing Emby reporting Direct Play once the source codec was preserved. Built on `main` and released as 2.1.2, then forward-ported here as `feat/hevc-client-capability-3.0`, four commits, `+473 / -12` over 12 files.

Built stable-first deliberately. The bug is in 2.x, most users are on 2.x, and shipping the fix only on an unreleased 3.0 would have left them waiting on a major version for a one-parameter defect. Forward-porting also meant the design was validated against a real Emby server before it went anywhere near the branch that is still moving.

#### What was actually wrong

`VideoCodec=h264` was hardcoded into the parameter list for every stream, including h264 sources. `TranscodeReasons=VideoCodecNotSupported` was the obvious suspect and is not the cause: Emby treats that field as informational, for logging and telemetry, not as the copy-or-transcode decision. Removing it alone changes nothing, which is why the reporter's own patch worked only once they also changed the codec parameter.

A second defect fell out of the first. The human-readable log line was written independently of the parameter it described, so it kept claiming "Source is hevc, transcoding to h264" after the request had stopped asking for that. Both now derive from one `keep_source_codec` decision, so the log cannot go stale against the URL again.

#### Why not simply preserve the source codec

That is what the issue proposed, and it is unsafe: nothing detected client capability, browser HEVC support is narrower than it looks, and in a synchronised party the failure lands on one person as a black video while everyone else is fine.

Browser HEVC turned out to depend on four separate things, two of which a user can change without installing anything. Chromium ships no software HEVC decoder and defers to the platform, so it needs hardware acceleration left enabled. Firefox on Windows goes through Media Foundation and needs a Microsoft Store codec that most Windows 10 installs lack. Apple platforms have it natively. Measured states during the work included one browser giving both answers on one machine before and after an OS-level install, and two Chromes disagreeing purely on a settings toggle. No user-agent rule reproduces that; only a runtime probe does.

The probe accepts only `probably` from `canPlayType`, since `maybe` is the browser guessing and a guess is the thing being eliminated. Anything that throws counts as no capability.

#### Scope boundary

Watch Party states what the viewer's browser reported it can decode. What Emby does with that, stream-copy or re-encode, and which encoder it selects, is Emby's decision and is not modelled here.

A stricter rule was proposed during review and rejected: keep the source codec only when Emby would *actually* copy it, meaning no bitrate cap, no resolution cap and `FORCE_TRANSCODE` off. It required predicting another system's internal decision from the outside, which cannot be verified from here and would go stale on any Emby release. Its premise was also wrong, resting on a capped HEVC session falling back to software x265 when the hard fallback is x264, which removes the cost the rule existed to avoid.

#### Verification

Verified end to end on 2.x by installing and then removing the Windows HEVC Store codec and watching the request switch between `VideoCodec=hevc` with `-c:v:0 copy` at ~50 ms per 3 s segment, and `VideoCodec=h264` with `TranscodeReasons=VideoCodecNotSupported` and libx264 at ~1750 ms, with nothing else changed. That is the whole claim, observed rather than reasoned about.

The no-capability path was checked for byte-identical output against 2.1.1 across h264, hevc and av1 sources at auto, capped and resolution-only qualities, so the change is inert until a browser actually reports something.

#### 3.0 deltas, and the test they needed

Four things differ from the 2.1.2 change because 3.0 has diverged underneath it: `join_party` is a validated typed contract, so `video_codecs` is declared on `JoinPartyPayload` and the socket schema and TypeScript types are regenerated; the party is a typed aggregate, so codecs are a domain field rather than a dict key; the reconnect join moved to `usePartyReconnect`, so there are three emit sites; and strict inbound validation makes the payload the first gate.

The eight forward-ported tests cover negotiation, which is identical on both lines, and covered none of that. Three were added here. The field being optional is load-bearing in a way the 2.x line has no equivalent for: if a missing `video_codecs` failed validation, an unpatched client would not lose a stream copy, it would fail to join the party at all. Strict validation also rejects a wrong-shaped list before `_parse_client_codecs` sees it, so on this line the allowlist is the second gate rather than the first; it keeps its own defences, because it is written against the raw 2.x-shaped value, but the ordering is now pinned so a later loosening of the contract cannot move the trust boundary unnoticed.

#### A correction, recorded rather than quietly fixed

The browser-matrix fixture originally recorded the second Chrome as lacking HEVC hardware. It has the hardware; acceleration was switched off in the browser's settings. The distinction changes what the fixture argues: absent hardware makes support a property of the machine, checkable once, while a settings toggle makes it a property of the session, which is the actual reason the probe runs per page load and is not cached beyond it. An inference about the reporter's Opera GX result was dropped in the same commit, because they reported HEVC working with acceleration on and never reported testing it off.

#### Still open

The README section on what decides whether a viewer gets HEVC exists on `main` and has not been carried here.

---

### PR #59 follow-up: responsive library navigation

Mobile library browsing had two independent failures. The party header kept a fixed
80-pixel height while its controls wrapped into several rows, so those rows overlaid the
library breadcrumb and made the route back to all libraries unreachable. The A-Z rail
then built its enabled state from the current 50-item page and bucketed display `Name`,
even though Emby orders libraries by `SortName`; letters outside that first page were
therefore disabled on desktop and mobile.

The mobile library-open state now uses a compact **All Libraries / current folder / Hide
Library** bar and gives the library the remaining dynamic viewport height. Search, a
responsive two-column poster grid and the sticky prefix rail stay within the viewport.
Desktop keeps the full party header.

Alphabet navigation now has an authenticated `/api/items/prefixes` boundary backed by
Emby's `/Items/Prefixes`, plus an alphabetical item mode using `SortBy=SortName`.
Selecting a prefix resolves its absolute offset through `NameLessThan`, fetches only that
page, and keeps top and bottom sentinels so earlier and later pages remain reachable
without loading the whole poster catalog. Season and episode views retain their numeric
ordering. Prefix failures hide the shortcut without breaking ordinary browsing.

Contract tests pin Emby scope, prefix forwarding and anchored offsets. Chromium proves a
jump into an unloaded mixed-letter catalog and upward paging; iPhone WebKit proves the
compact header, root navigation, visible search/prefix controls and overflow bounds. A
checked local `docker-compose.dev.yml` is also included for building and running this checkout
with credentials supplied only through environment variables.

---

### Appliance deployment

**[dnordel](https://github.com/dnordel)**'s, contributed as [#58](https://github.com/Oratorian/emby-watchparty/pull/58): 16 commits over 20 files, +1627 / -204, making `deploy/schema.json` the single description of a deployment and rendering five artifacts from it with a hash stamp and a CI drift gate.

The design is right and the two largest commits in the PR are the author hardening his own guarantees, `+181` of schema validation and a drift check taught to notice deleted artifacts. The audit found nothing wrong with the architecture. It found that the *values* it shipped did not work.

#### The audit

Six lenses over the 20-file diff, then severity-scaled adversarial verification. 36 candidates, 16 verified, **13 confirmed and all fixed here**, 2 refuted, 1 split.

**Nothing it generated could be deployed.** Three layers, each hiding the next:

1. Every artifact pinned `:3.0`, which this project publishes for stable releases only. Verified against GHCR directly: `:3.0` is a 404 while `:devel`, `:nightly`, `:latest` and `:3.0.0-beta1` resolve. All four documented paths failed at the first `up` with `manifest unknown`, and the new CI gate could not catch it because `docker compose config` never contacts a registry.
2. Fix the tag and none of them boot. Every artifact shipped `BEHIND_PROXY=""`, and `EnvConfig.declared()` is a membership test, so an empty value counts as declared, gets parsed, and fails with `Must be true or false` *unconditionally*, development included. The tri-state `None` the setting exists for became unreachable from any shipped file, and its purpose-written guidance was replaced by a generic parse error. The base branch shipped `BEHIND_PROXY=false` and booted.
3. Fix that and CasaOS and TrueNAS still cannot hold a session: both forced `SESSION_COOKIE_SECURE=true` while their own metadata advertises a plain-HTTP tile, so the browser discards the cookie and every request after party creation returns 401.

The schema can now say *emit no assignment* rather than *emit empty*, which is the only encoding of "the operator has not chosen yet". `BEHIND_PROXY` and `SESSION_COOKIE_SECURE` use it and ship commented out rather than dropped, because Compose passes only what the environment mapping names.

**Documentation that destroyed data.** All four platform guides told a 2.1.x migrator to create `config.json` containing `{}` as an unconditional step, *before* running the preflight. On an in-place upgrade that truncates the operator's file, discarding every admin setting, and then blinds the preflight to the one case it exists to catch: with the real file it emits `REQUIRED ACTION: Set ENABLE_HLS_TOKEN_VALIDATION=true`; after the truncation that action is gone and every rate limit reports as `(default)`.

Relatedly, `README.md` still said `touch config.json` in two places, which predates this PR by a long way. An empty file is not valid JSON, so `RuntimeConfig` quarantines it as `config.json.corrupt-<timestamp>` on every boot: a brand-new install following the project's own instructions saw a corruption warning. Both are now conditional `echo {}`.

**The schema was a third description of the same configuration**, after `config.py` and `.env.example`, which is the twin-path shape that produced four preflight defects in the previous cycle. It held here in two places. `schema.storage` was decoration, since the mount list was a literal in the generator, so adding a required mount changed the hash, satisfied `--check` and the drift tests, and produced no volume anywhere. And the published `APP_PREFIX` pattern admitted `/_media`, `/-wp`, `/.hidden` and `/~user`, which the boot gate refuses with a message contradicting the docs the operator just read.

**A gate that was red for everyone.** `--check` swept for the generated header to find obsolete artifacts, and that header is exactly what `cp .env.example .env` copies, so the check `CONTRIBUTING.md` makes a required pre-PR step failed for anyone who had ever run the app, on a clean tree with no drift. A gate everyone must ignore is worse than no gate.

#### What the tests could not have caught

The 44 tests shipped with the PR all passed against artifacts that could not be pulled, could not boot, and could not hold a session, because none of them asked the real loader what it made of the output, and the image was asserted as a literal rather than derived. Five tests added: omitted settings ship absent and commented, a deployment built from `.env.example` actually boots, published validation patterns agree with the loader they describe, `schema.storage` reaches every artifact, and the image derives from the schema. CI additionally resolves the schema's image against the registry.

#### Provenance note

`397ed2f` removed `deploy/unraid/emby-watchparty.xml` citing "platform ownership". The outcome is correct, Unraid templates are published from a separate repository, but the stated reason is not: that repository is the maintainer's own, and Unraid Community Apps only indexes it via `TemplateURL`. `schema.json` still carries the `display` metadata that existed to generate the XML, so the capability survives if it is ever wanted.

---

---

### Migration diagnostics

Ships in `:3.0.0-beta3`; no `:3.0.0-beta2` image was ever published.

31 commits over 46 files, +2466 / -111. 21 of those files are tests.

#### Provenance

The feature work is **[dnordel](https://github.com/dnordel)**'s, contributed as [#57](https://github.com/Oratorian/emby-watchparty/pull/57): 25 commits over 45 files, split 12 fixes, 7 tests, 3 features, 2 docs, 1 formatting.

The PR was closed rather than merged, and its branch landed on `3.0-dev` directly, the same arrangement as [#45](https://github.com/Oratorian/emby-watchparty/pull/45). It carried no defect that made it unmergeable; closing it reflects that `3.0-dev` takes this work without a per-change PR gate. The branch is preserved at `refs/pull/57/head` and was deleted after merge.

The remaining 6 commits are fixes for what an audit of that work found before it landed, described below.

#### What the PR added

**A uniform 429.** `rate_limit_response(action, retry_after)` in `backend/src/rate_limit.py` is now the single construction site for a rate-limit refusal, returning `{detail, code: "rate_limited", retry_after}` with the matching `Retry-After` header. The middleware, admin login and avatar recovery all route through it, replacing two hand-rolled bodies with different shapes, one of which did not conform to its own route's declared `response_model`.

**A machine-readable code.** `ApiError` on the frontend carries `code` and `retryAfter`, parsed from the body with a header fallback. Three call sites branch on the code rather than string-matching a message: `stores/party.ts` for session binding and `views/IndexView.vue` for the background party-list poll, both off `ApiError`, plus `stores/socket.ts` for the socket handshake, which reads the same code off the `connect_error` payload rather than an `ApiError`. Party creation in `IndexView.vue` gained a `catch` in this PR but still surfaces `error.message` without inspecting the code.

**A new `rate_limited` socket event**, added to `backend/socket-events.schema.json` with regenerated TypeScript, carrying `action`, `message`, `retry_after` and the originating `request_id`. It is emitted to the offending socket only, which is what lets a refused chat message be handed back to the one person who sent it.

**`backend/migration_preflight.py`**, 492 lines, read-only, with `tests/test_migration_preflight.py` alongside it. Reports config precedence and provenance, proxy topology, the HLS gate, inherited rate limits, runtime and worker requirements, paths to preserve, health and readiness expectations, and manual backup and rollback steps.

**Startup cleanup deferred until startup succeeds**, so a failed boot no longer discards the stale setup state a retry might need.

**`npm run test:playback-gate`**, a Playwright grep on `@playback-gate` covering one complete authenticated session end to end.

#### The audit

Two passes over the 45-file diff before it merged. Seven lenses ran blind to each other, so the same defect was frequently reported several times under different wording: 38 candidates, of which the first pass verified 8 and the second adjudicated the remaining 30. They collapse to **19 distinct defects, all confirmed and all fixed**. Four candidates were refuted, one split its verifiers, and three were already closed by a fix earlier in the same cycle. A twentieth turned up later, when this section itself was fact-checked; it is described below.

Convergence did the useful work. Four independent lenses landed on the preflight's `.env` parser and four on its handling of `ENABLE_RATE_LIMITING`, which is far stronger evidence than any single lens asserting either.

##### The dominant defect class: diagnostics describing a system that does not exist

Most of the 19 were a report contradicting the code it reported on. This is the failure mode a diagnostics feature can least afford, because the whole product is the report, and an operator acts on it precisely when they cannot yet observe the thing themselves.

**The preflight cleared configurations that then refuse to boot.** Four separate ways, all the twin-path pattern from the previous cycle: it re-implemented what `config.py` already owns, and the copies disagreed.

| the preflight did | `config.py` does | consequence |
| --- | --- | --- |
| hand-rolled `.env` split on `=` | `dotenv_values`, which strips inline `# comment` | correct settings reported malformed; `ENABLE_HLS_TOKEN_VALIDATION=false  # ...` parsed to `None`, so the required action was never printed |
| non-empty `TRUSTED_PROXY_CIDRS` ⇒ "is declared" | `ipaddress.ip_network` on every entry, **all environments** | `172.16.0.0/12 10.0.0.0/8`, a space where a comma belongs, cleared preflight and then blocked the boot |
| verdict from a four-name `_BOOT_FIELDS` list | `startup_errors()` hard-fails on roughly twelve | a stock 2.1.x production `.env`, wildcard CORS and no API key, collected a clean report and then served 503 everywhere |
| `legacy.get()` for the HLS flag | `RuntimeConfig` coerces JSON `null` to `False` | an explicit `null` read as absent and reported as the default `true` |

A fifth surfaced only when this section was fact-checked, and it was introduced *by the fix for the other four*. Evaluating against `--target` means substituting `APP_ENV`, which hides `startup_errors`' own check that the declared value is one 3.0 accepts at all; the substituted value always is. So `APP_ENV=prod` collected an explicit "boot validation passes" and then refused to start. The declared value is now checked separately. Worth recording rather than quietly patching: the same twin-path reflex that caused the original four produced one more inside the repair, which is the second time in two cycles a fix has introduced a narrower instance of the bug it closed.

Values now come from `dotenv_values` and the verdict from `Config.startup_errors()`, evaluated against `--target` rather than whatever `APP_ENV` currently says. Asking "does your current `APP_ENV` pass" answers the wrong question: a 2.1.x deployment that never set it reads as development and sails through every production rule it is about to meet. `EnvConfig.from_env` gained an injectable `environ` so the preflight can resolve precedence through the real loader instead of imitating it.

**Read-only is a hard constraint and it is why the duplication existed.** `Config.from_env` routes through `RuntimeConfig.from_file`, which `shutil.copy2`s a corrupt `config.json` to `config.json.corrupt-<timestamp>`. The preflight therefore rebuilds the runtime half from the JSON it already parsed and never calls that loader. A test now pins the absence of that side-move on the corrupt-config path, which is exactly where the guarantee had only ever been asserted on the happy path.

**`ENABLE_RATE_LIMITING` was never read**, so all six limits were reported "enforced in 3.0" while the master switch sat in the same parsed dict. That flag carries over from 2.1.x untouched, so an operator who turned limiting off in **Admin -> Security** was told six limits protected them while nothing was throttled. Compounding it, `socket_handlers/chat.py` was the only limiter with no such guard, so with the switch off chat was simultaneously the only limit still firing, and this PR promotes it from a silent drop to a visible notice that disables the composer.

**The health and readiness probes were printed unprefixed.** Both mount under `APP_PREFIX`, so on a subpath deployment the documented `curl` returns 404 against a perfectly healthy upgrade, and against a broken one it falls to the unprefixed 503 catch-all and reports "dead" precisely where those lines promise to separate "misconfigured" from "dead". Resolved through `_effective` and dropped when the boot gate rejects the prefix, mirroring `app.py`.

**A 429 named a limit the request had not hit.** `is_party_join` in the middleware changed only the wording, not the bucket: joining shares `api:{ip}` with every other route, and `IndexView` polls `/api/party/list` through it every five seconds, so a viewer's first join was reported as too many join attempts by the very page they joined from. Scope, spec and label are now chosen in one block, which removes the class rather than the instance.

**`retry_after` overshot.** `int(...) + 1` truncated and added a second, so a full three-second window reported four. The eviction above it already leaves `bucket[0]` as the oldest hit inside the window, making the expression the exact wait, so `math.ceil` is correct. The `max(1, ...)` floor stays.

##### Frontend: state that outlived its cause

- **Refused chat drafts were concatenated into the composer.** With anything already typed, two distinct messages merged into one, and because refusals arrive in send order while each arrival prepended, the merge came out reversed. Drafts now return only to an empty composer; otherwise they queue FIFO and render as restorable chips, and restoring into an occupied composer is refused so a draft can never overwrite live typing.
- **The chat rate-limit alert was never cleared**, only its counter, so it persisted until the next successful send.
- **`connectionError` was assigned on every `connect_error`.** engine.io fires that for each failed transport probe with a library string as the message, so routine churn painted an assertive banner reading `xhr poll error`. Only a server-authored refusal is worth interrupting a viewer for; everything else now speaks in the application's own words, and only once the party had actually connected.
- **The session banner interpolated raw upstream text and dropped its own guidance**, so a proxy's HTML 502 page rendered where the explanation belongs. The fixed sentence now leads, with upstream detail in bounded, ellipsised parentheses. `party.ts` no longer promotes a fetch-layer exception, and `client.ts` takes a non-JSON body only when it reads like one line of prose. That last discrimination is deliberate: dropping unparsed bodies outright would have broken the `preserves readable multipart upload errors` test that predates this branch, which encodes a real nginx 413.
- **`IndexView`'s party-list banner was assigned only on 429**, so it survived every later failure and blamed rate limiting for the duration of an outage.

##### Tests that could not fail

Four, each found by mutation rather than reading.

- `test_party_join_limit_names_the_blocked_action` filled the bucket using joins only, so it asserted the label while structurally unable to catch a wrong one.
- The fake Emby subtitle endpoint discarded item, source and index and answered WEBVTT to any of them. That the whole suite passed once validation was added is itself the finding: nothing exercised the subtitle path.
- A second audio stream was added to the fake with nothing pinning which is default, so inverting default-track selection kept the suite green.
- The progress-throttle test asserted that exactly one report reached Emby but never which one. "Drop anything inside the window" and "coalesce to the latest" both send exactly one, and they send different positions.

Separately, `usePartyChat.test.ts` asserted nothing about the "without resending it" half of its own name, leaving the guard in `send()` deletable with the suite green.

One near-miss is worth recording. `chat.py` emits `rate_limited` with `to=sid`, which is correct, but replacing that with `room=party_id` passes the **entire** backend suite. The code is right and nothing pins it, and `usePartyChat.ts` has no `request_id` ownership guard, so a regression there would broadcast one viewer's rate-limit banner to the whole party. Left as-is deliberately, since it is a coverage gap rather than a defect.

##### Documentation that had drifted from the artefact

- **The CHANGELOG rewrote the already-published beta1 section** to advertise the preflight and the playback gate, neither of which that image can run, and deleted the sentence explaining why enforced rate limiting is the change most likely to be noticed. beta1 is restored byte-for-byte, verified by diffing against `3.0-dev`, and the new prose moved under `[Unreleased]`. Retroactively editing published release notes is worth calling out as a class: the beta1 text is linked from the Discord announcement and read by people deciding whether to upgrade.
- **The documented upgrade order ran the preflight before pulling the 3.0 image**, so as written it executes inside the 2.1.x image, which has no such module. Steps swapped, with the image repoint made explicit since no step previously said to do it, and `docker-compose.yml.example` carries the same caveat because `:latest` is still 2.1.x.

#### Verification posture

Every fix for a real defect has a test proven to fail against the code it replaced, by reverting the source and rerunning; tests that pass on both sides are labelled guards rather than passed off as regression coverage. The audit's own findings were adversarially refuted before being accepted, with lenses assigned by severity, and vote splits recorded rather than collapsed.

Current state after all four bodies of work: **267 backend tests** across 36 modules, **65 Vitest** across 21 files, **16 Playwright**. `ruff check` and `ruff format --check` clean over 90 files, `mypy` clean over the 48 it covers (`backend` and `scripts`), eslint and `vue-tsc` clean, the socket contract and the REST contract free of drift, and the generated deployment artifacts in sync with the schema. All on 3.12.10, run with CI's exact commands against the merged tree.

That last clause is not decoration. The first draft of this section claimed `ruff format` was clean having only ever run `ruff check`, and CI runs both; the merged tree was red on the format step until a fact-check pass caught it. The gap and its correction are recorded here rather than quietly fixed, because "the checks pass" is the one claim a reader cannot verify without redoing the work.

The two patterns flagged at beta1 both recurred, which is the argument for keeping them named. The fake Emby hid a defect again by being more permissive than the real server. And the twin path produced four more, all in one new module that re-derived what `config.py` already owned; the fix was structural, making the preflight call the boot gate rather than predict it, because patching the four instances individually would have left the fifth to be found later.

#### Still open

Unchanged from beta1 and still a tuning decision rather than a defect: party creation at 5/hour and socket connects at 30/minute are the tight ones for a household behind a single public IP. Beta feedback is what should settle them. The difference now is that hitting one says so.

---

## [3.0.0-beta1] - 2026-08-05 - Director's Cut

**First beta.** Published to GHCR as `:3.0.0-beta1`, tracked by `:devel` and `:nightly`. It does **not** move `:latest` or the rolling `:3` / `:3.0` tags, so the stable line is untouched.

Cut through `release.yml`'s `workflow_dispatch` path with `docker_only`, against `3.0-dev`. Betas carry no git tag and no GitHub Release; that is how the entire 2.0 beta cycle ran, and the only tags in the repository are stable releases.

Beta means the automated suite passes and the audit backlog is closed, not that it has been run by a real household against a real Emby server. Keep 2.1.x available for rollback until a playback test succeeds.

### Provenance

3.0 is **[dnordel](https://github.com/dnordel)**'s rework, contributed as [#45](https://github.com/Oratorian/emby-watchparty/pull/45): 165 commits touching 139 files, of which 57 are tests, 51 are refactors, 31 are fixes and 10 are features.

The PR was initially closed rather than merged, because the change is too large and too breaking to land in one step and because it forked from `2.0.2`, before the 2.1.0 security release. It was then reopened against `3.0-dev` and its commits landed there, followed by focused fixes for the milestone blockers. `3.0-dev` is the integration branch for the release; CI runs on every push to it, and betas are cut from it.

The [3.0 milestone](https://github.com/Oratorian/emby-watchparty/milestone/2) is empty: nine issues filed, all closed.

Grouped by area below rather than by commit; the branch has no beta cadence to break on.

---

### Breaking Changes

Ranked by how many deployments they affect, and each marked with where it ended up: **RESOLVED** if it was fixed, **MOOT** if the code it described stopped existing when the setup flow was removed. None is still open. The section is kept in full rather than pruned, because the reasoning behind a breaking change is worth more than the status line, and because two of these were closed by deleting a feature rather than by fixing it.

#### 1. Rate limiting becomes enforced, and collapses to a single bucket behind a reverse proxy

**Blast radius: nearly every deployment. The single most important item in the release.**

2.x has no global rate limiter. The `/admin` → Security sliders have been **inert** since they were added; only the ad-hoc admin-login bucket ever did anything. 3.0 installs `RateLimitMiddleware` on every request, covering all of `${APP_PREFIX}/api/*` except `/api/health` and `/api/ready`, **driven by the values already sitting in the operator's `config.json`**, values nobody has ever tuned because they did nothing.

It keys on the socket peer with `proxy_headers=False`, and `TRUSTED_PROXY_CIDRS` defaults to **empty**. Behind nginx, Caddy or Traefik, `resolve_client_ip` returns the proxy's address for every request, so **every viewer in every party shares one bucket**: 5 party creations per hour and 30 socket connects per minute, deployment-wide.

The symptom an operator actually sees is a third person trying to join movie night and silently failing to.

**Partly resolved.** The socket half was worse than described and is fixed: python-engineio writes the literal `127.0.0.1` into the handshake environ, so *every* socket shared one bucket regardless of proxy, which made 30 connects per minute a deployment-wide cap out of the box ([#52](https://github.com/Oratorian/emby-watchparty/issues/52)). The peer now comes from the ASGI scope. The HTTP half stands as written: behind a reverse proxy with `TRUSTED_PROXY_CIDRS` unset, every request still keys on the proxy's address.

#### 2. Bare-metal upgrades break; the virtualenv must be recreated

**Blast radius: every non-Docker install.**

`requirements.txt` is now `pip-compile --generate-hashes` output. **Any** hash in a requirements file puts pip into `--require-hashes` mode, which additionally demands every transitive dependency be pinned with a hash **for the running interpreter**. The lock also drops `requests` and the `uvicorn[standard]` extras, and pip will not remove those from an existing environment, so an in-place upgrade leaves a half-migrated venv.

**Resolved in part.** `pyproject.toml` now declares `[project]` with `requires-python = ">=3.12,<3.13"`, so a mismatched interpreter refuses the install rather than succeeding quietly. That gap was live long enough to bite during review, where a shell defaulting to 3.13 ran the whole suite on an interpreter neither CI nor the image covers. The venv recreation itself is still required.

#### 3. Losing `data/bootstrap.json` fails **open** into development mode -- MOOT

**Blast radius: anyone who loses or does not mount `./data`. Security-relevant.** Tracked as [#49](https://github.com/Oratorian/emby-watchparty/issues/49).

`EnvConfig.from_env` treats a missing `data/bootstrap.json` as "no persisted values" and falls through to hardcoded defaults: `APP_ENV=development`, `CORS_ALLOWED_ORIGINS=*`, empty `SESSION_SECRET`, `SESSION_COOKIE_SECURE=false`. Because the strict checks only run when `APP_ENV == "production"`, a production deployment that loses its bootstrap file **silently downgrades to development posture**. It does not enter setup mode, and it does not fail.

**Moot.** This was first resolved with a `CONFIGURED: true` sentinel, then the whole persistence layer was removed. No bootstrap file is read or written, so there is no fail-open path left to close. A stale `data/bootstrap.json` from a development build is ignored and deleted on boot.

#### 4. Setup mode reports HEALTHY to Docker and writes nothing to any log -- RESOLVED, then partly MOOT

**Blast radius: every Docker deployment that hits a boot-config error.** Tracked as [#50](https://github.com/Oratorian/emby-watchparty/issues/50).

`create_app` catches the startup-validation error and returns the setup app instead of raising. The setup app's health endpoint returns `{"status": "ok"}`, indistinguishable from the normal app, while the Dockerfile still probes `/api/health` and the compose example uses `restart: unless-stopped`. So a misconfigured container reports healthy, serves a setup page, and serves no API, no Socket.IO and no HLS. The setup app installs no middleware and never reaches `_setup_logging`, so nothing is logged at all; the bootstrap token reaches **stdout only**, printed at module import.

**Resolved, and then half of it stopped applying.** What survives: `/api/health` returns `{"status": "setup_required"}` at HTTP 200 so an orchestrator does not restart-loop, `/api/ready` holds at 503, every other route returns 503, and the failing field names are printed to stderr in a framed banner, which is what the appliance log viewers actually show. The token half is moot; there is no token. It was also the mechanism that made the flow unworkable, being written `0600` inside a root-owned `0700` directory. Separately, and still relevant: construction was happening at module scope, so any `import backend.app` built an app and printed a token, including in nine test modules.

#### 5. `EMBY_SERVER_URL` validation rejects Docker service names containing underscores -- RESOLVED

**Blast radius: anyone using `http://emby_server:8096`.**

Hostname validation runs unconditionally, outside the production-only block, and the DNS label pattern permits no underscore. Docker Compose service and container names may legally contain `_`, and Docker's embedded DNS resolves them. The value was also not stripped the way `SESSION_SECRET` is, so a trailing space failed too.

**Resolved.** Underscores are accepted through a separate service-name pattern applied only to addresses this server dials itself. CORS origins keep the strict RFC 1123 form, because a browser cannot originate from such a host, so loosening it there would only ever accept a typo. `EMBY_SERVER_URL` and `EMBY_API_KEY` are both stripped now. Both were later renamed (see Unreleased, above); the validation and stripping behaviour carries over unchanged to `MEDIA_SERVER_URL` and `MEDIA_SERVER_API_KEY`.

#### 6. The setup form silently discards edits to env-provided fields -- MOOT, and the reason the flow was removed

`validate_bootstrap_submission` short-circuits every field in `explicit_env_fields` back to its current value before validation, and a field counts as explicit if it appears in `os.environ` **or** `.env`. The recommended compose file uses `env_file: .env`, which loads the whole file into the process environment. **So for the recommended Docker deployment every bootstrap field was "explicit" and the setup page was entirely inert.** Edits appeared to save and were discarded.

**Moot.** This is the argument that ended the flow rather than a defect that was fixed. On Unraid, CasaOS, Portainer and TrueNAS every setting is a container environment variable, so the form was inert exactly where this project's users are, while reporting success. It bought no security either: environment beats persisted state in the precedence order, and anyone who could read the token from a log or the volume already had host access.

#### 7. `ENABLE_HLS_TOKEN_VALIDATION` moves from the admin panel to boot config

Restart-only now; runtime writes return an explicit "boot setting; restart required" rejection. The existing `config.json` value **is inherited automatically**, so nobody's setting silently changes, only the UI location moved. Documentation-only, but worth stating plainly: "my setting vanished from /admin" reads as data loss.

#### 8. Completing setup chmods the shared data volume to `0700` -- MOOT

`save_bootstrap_config` created the directory then **unconditionally** chmodded it to `0700`. `data/` is not new for upgraders; it has held `avatars.db` since 2.0 and is a documented bind mount. The container runs as root, so the host directory became root-owned `0700`.

**Moot.** No chmod remains anywhere in `backend/`.

#### 9. Single-worker requirement

Parties, Socket.IO mappings, HLS grants, admin sessions, limiters and timers are all process-local. README and SECURITY.md state this; the migration path does not.

#### 10. `uvicorn[standard]` becomes plain `uvicorn` -- RESOLVED

`uvicorn[standard]` is restored in `requirements.in`, and both locks were regenerated universally, so `uvloop` (marked `sys_platform != 'win32'`), `httptools`, `watchfiles` and `websockets` are present for the Linux image without breaking a Windows install. Verified by a `pip install --dry-run --require-hashes` on Windows, which resolves clean. Raised on the PR [here](https://github.com/Oratorian/emby-watchparty/pull/45#issuecomment-5160203879).

#### 11. No 2.x to 3.0 migration document exists yet -- RESOLVED

`docs/Migration-HowTo.md` is now titled "Migration: 2.1.x → 3.0" and covers the beta line built from `3.0-dev`. It was previously titled "Migration: 1.x → 2.0", with this branch's entire change to it being one table row. Every new operator concept is documented only as first-install material. It covers, in order: whether you need to change anything at all, `BEHIND_PROXY` and `TRUSTED_PROXY_CIDRS`, venv recreation with both reasons stated, what unconfigured mode looks like, the `ENABLE_HLS_TOKEN_VALIDATION` relocation and that your value is carried forward, `SESSION_EXPIRY` now genuinely governing the cookie, the single-worker rule, and a performance note. The `EMBY_SERVER_URL` pre-check is deliberately absent, because #5 above makes it unnecessary.

---

### Security

#### Resolved: the 2.1.0 authorization work, re-established

`3.0-dev` forked from `2.0.2`, so **none** of the 2.1.0 security release was present. All of it is back, each with a test verified non-vacuous by removing the fix and confirming failure. **Milestone: 9 closed / 0 open.**

- **[#46](https://github.com/Oratorian/emby-watchparty/issues/46) `/hls` session gate and cookie-party vs token-party check.** The worst of the set: possession of the URL was once again the entire credential, and a leaked token plus any open party's cookie streamed a private party's content under its host's Emby token. Both routes now take `require_host_token`, and `_resolve_host_creds` takes a keyword-only, non-defaulted `session_party_id`, so it cannot be called ungated.
- **[#47](https://github.com/Oratorian/emby-watchparty/issues/47) `_rewrite_playlist` validated URIs after rewriting,** so it rejected its own output on any Emby that emits absolute or root-relative media URIs. Validation now runs on the raw upstream body.
- **[#53](https://github.com/Oratorian/emby-watchparty/issues/53) legacy `admin_emby_*` cookie keys.** All six keys 2.0.x and 2.1.0 wrote are scrubbed, and the scrub now also runs from `require_party_session`. That last part is what makes it real: the original three call sites all require a 3.0-era `admin_session_id`, which an upgrading 2.0.x admin does not have, so a live Emby administrator token would otherwise have sat in their cookie indefinitely.
- **[#48](https://github.com/Oratorian/emby-watchparty/issues/48) permanent identity lockout.** Broader than filed, and needing no attacker, no second tab and no socket: create a party, log in, leave, come back. `host_client_id` is retained through PLAYING-ONLY so the stream survives, which keeps the identity reserved, while `/api/party/leave` discarded `host_session_grant`, the only proof of ownership. Unrecoverable, because `/api/auth/login` needs a bound party and `video_ended` / `stop_video` are gated to the selector, who is the locked-out host. The grant now stands alone in the gate and survives the unbind; the socket gate, which the first fix never touched, was brought in line and now reserves on live sockets rather than on stale participant records.

#### Resolved: findings introduced by the rework

- **[#52](https://github.com/Oratorian/emby-watchparty/issues/52)** was misnamed by its own title. Spoofing was real but secondary; python-engineio writes the literal `127.0.0.1` into the handshake environ rather than the peer address, so with the shipped defaults (`ENABLE_RATE_LIMITING=True`, `30 per minute`) **every socket connection in a deployment shared one bucket**. An availability bug needing no attacker: Socket.IO reconnects spend the same budget, so a few users on poor connections lock everyone else out of joining. The peer now comes from the ASGI scope via `environ_client_ip`.
- **[#51](https://github.com/Oratorian/emby-watchparty/issues/51) setup save wrote env-injected secrets to disk.** `save_bootstrap_config` now takes an `excluded_fields` set fed from `explicit_env_fields`.
- **[#49](https://github.com/Oratorian/emby-watchparty/issues/49) bootstrap fail-open** is closed by a `CONFIGURED: true` sentinel that persisted values must carry before they are adopted.
- **[#50](https://github.com/Oratorian/emby-watchparty/issues/50) silent setup mode** now reports `setup_required` from `/api/health`, holds readiness at 503, configures a logger, and writes the bootstrap token to a recoverable file rather than stdout only.

#### Also fixed, never filed

- **uvicorn's access log published HLS tokens.** uvicorn runs a second logger in the same process, and it writes the full request line at INFO including the query string. Every HLS URL carries `?token=`, so each playlist and segment request emitted a working stream credential to anything that ships logs onward. The redaction work had only ever covered the `emby-watchparty` logger. It stayed out of CI logs purely because pytest captures stdout during collection, which is luck rather than a control.
- **The app was constructed at import time.** `backend/app.py` ended in a module-level `create_app()` call, so importing it built an app against ambient config and, when that failed validation, minted a bootstrap token, printed it to stdout and rewrote `data/setup-token`. Nine test modules import that file, so every local test run leaked a fresh admin credential. It also undercut the application-factory refactor that is the branch's headline change. `app` and `sio` remain reachable via PEP 562 for `uvicorn backend.app:app`, but the work now happens on first attribute access.

#### Genuine improvements, take these regardless

- **Inbound socket payload validation.** Every inbound event is validated against a generated typed contract before a handler sees it, replacing hand-rolled key access on untrusted input. Unambiguously good and the strongest single piece of the branch.
- **Outbound socket event validation.** Emitted events are validated on the way out too, so a server-side shape drift is caught in CI rather than by a client that silently ignores the field.
- **Redacted structured route logs.** Exception details from routes and from upstream Emby calls no longer reach the log verbatim, so an upstream failure cannot spill credentials or internals into a log aggregator. Admin authentication failures are redacted specifically.
- **HLS path and playlist-URL rejection.** Unsafe HLS paths and foreign playlist URLs are refused, and the upstream query allowlist is tightened, with duplicate approved values preserved rather than collapsed.
- **Bounded, expiring security registries** and a shared bounded avatar-recovery limiter, so the new tracking structures cannot grow without limit.
- **Participant HLS tokens are revoked on departure** rather than left live until expiry.

---

### Added

- **A secure first-run setup mode.** A guided initial configuration path with validation, replacing "hand-edit `.env` before the first boot". Gated by a bootstrap token. This is also the largest new attack surface in the release; see the items above.
- **Production readiness enforcement.** Startup refuses configurations that are fine for local dev but not for a public deploy, instead of warning and continuing. A `/api/ready` endpoint reports the outcome separately from `/api/health`.
- **Generated typed socket contracts,** for both inbound and outbound events, with runtime validation on both sides.
- **Typed REST responses and abort signals** on the frontend, so a stale request can be cancelled and a response shape is checked rather than assumed.
- **Structured, redacted route logging.**
- **A centralized async Emby retry policy** for transient upstream read failures.
- **Network-recovery and reduced-motion surfacing** in the UI.
- **Hash-locked runtime and development dependencies.**
- **Strict Ruff checks, a frontend lint gate, and an incremental backend type gate** in CI.

### Changed

- **The application is built, not imported.** An isolated application factory constructs the app, so tests bring up a real ASGI app per case instead of importing a half-configured module-level singleton. A startup that fails partway now closes what it already opened.
- **The party becomes a typed dataclass aggregate.** Raw party dictionaries and their compatibility shims are gone. Playback state, ready-check state, vote and auto-advance state, per-user stream state and selected media are all typed aggregates, and participants are the canonical membership record.
- **State transitions serialize through `PartyManager`.** Playback controls, progress commits, video-selection reservations, vote/ready/auto state, reconnects and socket detachment all route through the manager under its lock rather than mutating shared dicts from handlers.
- **Emby operations are fully asynchronous,** and HLS traffic routes through an Emby gateway abstraction.
- **`mypy` runs across the whole backend,** not a subset.
- **`PartyView.vue` is decomposed into composables** for stream, subtitles, media selection, voting, reconnect, chat, admin and playback-timer ownership, with party lifecycle and playback listeners owned explicitly rather than registered ad hoc.
- **Untyped protocol boundaries are removed on both sides,** with untrusted API payloads modelled as JSON rather than assumed-shaped objects.
- **Process resource shutdown is centralized,** with owned background tasks typed and limiter buckets cleared on teardown.

### Fixed

- **Native HLS is preferred on iPhone WebKit,** the stream is released on unmount rather than leaving the Emby transcode running, iOS byte-range responses are preserved, and autoplay blocked by the browser policy is surfaced instead of failing silently. iOS safe areas and the dynamic viewport are honoured.
- **The Emby login modal traps and restores focus.**
- **Empty parties are dissolved along with their owned resources,** and an empty party is preserved through the reconnect grace window rather than collapsed.
- **Reconnect restores typed user streams and a serialized playback snapshot** instead of a partially rebuilt one.
- **Playback is broadcast before Emby reporting,** so a slow upstream report no longer delays the room.
- **Stale video-selection reservations and stale library-navigation requests are cancelled.**
- **A pending join vote replays idempotently,** and party status changes are announced through the chat log.
- **Large library rendering is bounded.**
- **Multipart API errors are preserved** rather than flattened.
- **Intro metadata is served protocol-faithfully.**
- **The Docker frontend builder is aligned with Node 24,** and the Python lock is made portable to Linux.

### Testing and CI

The test suite is the largest single part of the branch: **57 test commits, 23 test modules**, replacing mocked routers with tests that run over the public surface.

- **A shared live fake Emby server** (`tests/support/fake_emby.py`) serves real, playable HLS with controllable playlists and observable stream-cancellation state. Browser flows and two-browser lifecycle tests run against it through the live backend.
- **Mocked HLS router tests are gone,** along with logger and config test doubles; limits, Emby reliability and socket validation are exercised through concrete public dependencies.
- **Two-browser seek synchronization, guest stream restoration after reload, sole-participant preservation across reload, late-joiner approve and reject paths, and voter-eligibility freezing** are all covered end to end.
- **Accessibility coverage:** core controls by keyboard, admin modal focus containment, and playback announcements.
- **CI gains a macOS WebKit job** validating the native-HLS path on Apple's engine, the first automated coverage Safari has ever had here, plus ordered validation before release and parallel-browser isolation from the rate limiter.
- Starlette tests migrated to an async ASGI client on httpx 2.

---

### Outstanding before release

The 3.0 milestone is empty, and the audit backlog behind it is now closed too. Everything previously listed here has landed:

1. ~~The three operator traps.~~ #5 is fixed, #6 and #8 are moot with the setup flow.
2. ~~Make every remaining breaking change announce itself.~~ Production refuses to boot with an undeclared `BEHIND_PROXY`; a misdeclared one is reported at runtime when a forwarded header arrives and is discarded, once per process; invalid boot config names its failing fields on stderr.
3. ~~Warn when a proxy is likely and `TRUSTED_PROXY_CIDRS` is empty.~~ Done at runtime rather than boot, because boot cannot observe traffic and any guess would be wrong in both directions. Both variables are in the compose example.
4. ~~Case-insensitive `.m3u8` matching.~~ Three sites were case-sensitive, not one, and the fake Emby was hiding it by routing uppercase paths to its segment handler.
5. ~~`_sanitize_query` returns 400 where it should drop.~~ Strict on the request the player builds, dropping on URLs Emby authored.
6. ~~Re-verify the findings not independently confirmed.~~ All checked. The challengers were right every time, except 5.4, where the note was stale rather than the code and the behaviour simply had no test.

What is genuinely left is **not a defect**: five of the six rate limits are enforced for the first time in 3.0, carrying values nobody tuned because tuning them previously did nothing. Party creation at 5/hour and socket connects at 30/minute are the tight ones for a household behind a single public IP. That is a tuning decision to make on beta feedback, which is part of what this beta is for.

### Verification posture

Every security fix in this cycle was checked by removing the guard and confirming the tests fail, not by reading the diff. That was not ceremony: all eight milestone issues were closed once after per-issue verification, and two had to be reopened because the verification had followed the code path the issue *named* rather than every path implementing the behaviour. In both cases the fix had been applied to one gate and not its twin.

Current state at beta1: **116 backend tests**, 17 Vitest, 14 Playwright, ruff, `ruff format` and `mypy` clean over 42 source files on 3.12.10, socket contracts current, CI green on `3.0-dev` across `validate`, `docker` and the macOS WebKit native-HLS job.

Two patterns are worth carrying into the next cycle. The fake Emby harness hid three separate defects by emitting only the narrowest shape a real Emby sends, so playlists carried no query string and ranges were clamped such that `416` was unreachable. And five defects existed only in a *second* copy of a guard that was correct in the first, including one introduced during the final pass and caught one commit later.
