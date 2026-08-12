# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release has a short user-facing summary on top and a longer **Technical details** section underneath for anyone who wants the full story.

### Special Thanks
Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

Thanks to **[Christian Gillinger](https://github.com/cgillinger)** for the "Refined Cyber" design language that the 2.0 visual refresh is built on -- the cyan/magenta/violet palette, glass surface treatment, chip/pill control language, animated LIVE badge, and centred system-message pill in chat all come from his mockup.

---

## [3.0.0-beta3] - Unreleased Internal beta - Director's Cut

**Not published.** Nothing in beta2 or beta3 is in `:3.0.0-beta1`, `:devel` or `:nightly` yet; pulling any of those still gets beta1.

beta2 brought the library work in. beta3 is about living with it. Everything here came out of actually using the new title view, plus one long pass over the test suite asking a narrower question than usual: not "does it pass", but "could it fail".

### The title view stops pushing itself off the screen

Extras, Trailers and the rest used to expand downwards, one block each, so opening all three left all three on screen with two "None available." lines trailing the one list that had anything in it. They are now a single panel that shows one section at a time, opens upward, and closes when the pointer leaves or Escape is pressed.

A series no longer renders every episode as its own stacked row. A 24-episode season used to push the rest of the page out of view; there are now two dropdowns, one for the season and one for the episode, and they load with the title rather than waiting for a button.

Both control groups moved up beside Back. They previously sat below the synopsis, which meant their position moved with the length of the synopsis, and a long one put them off the fold entirely.

Titles with artwork are readable again. Light text was rendering straight onto whatever the backdrop happened to be, so a bright frame took the title, the buttons and the metadata with it.

### A party that no longer exists says so

Landing on a dead link, or on any link after the server restarts, used to leave you looking at a Retry button that could never succeed. It now says what happened and takes you back to the start page on a short countdown, with a "Go now" if you would rather not wait.

### A host can keep a party off the public list

An eye in the party header toggles whether the party appears under Active Parties. **Parties now start hidden.** This is unlisted rather than private: anyone holding the code still joins exactly as before, so it is for a private evening rather than for access control. The control is visible to everyone in the room and only the host can change it, because the state matters to the people already there.

### Rate limits are the same two controls everywhere

Admin Login, Avatar Recovery, Chat and Socket Connections were free-text fields while API Rate Limit and Party Creation Limit already used a number and a window dropdown. They now all work the same way. The parser behind them was also reading `10 per 15 minutes` back as `10 per minute`, which on the next save would have written a fifteen-fold tighter limit than the operator set.

### Fixed

- Copying the party code confirms again. The pill's icon swaps to a tick and the border tints for two seconds. The confirmation had been moved into a tooltip, which never appears after a click because the pointer is already sitting still.
- Leaving a dead party no longer follows you into the next one. The "no longer exists" card could reappear on a perfectly healthy party, frozen, with only "Go now" as a way out.
- Switching to a shorter version of a title no longer leaves your position reported minutes ahead of the picture. The stream was being started at a corrected offset while the old one was still being reported, so drift correction spent the rest of the film pulling against it.
- A failed Related / Extras / Trailers fetch says it failed instead of reporting "None available.", and retries when the section is reopened rather than caching the failure for the life of the page.
- A search that genuinely fails shows the failure. A dead Emby had been indistinguishable from an empty library.

### Technical details

See [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md) for the test-suite audit behind most of this section: what it found, the two real bugs that came out of it, and why 64 deliberate mutations were applied to the source to check the tests could see them.

---

## [3.0.0-beta2] - Unreleased Internal beta - Director's Cut

**Not published.** Nothing here is in `:3.0.0-beta1`, `:devel` or `:nightly` yet; pulling any of those still gets beta1. This section is what the next beta will carry.

beta1 said the change most likely to be noticed was rate limiting becoming enforced, **and that it is silent when it bites**: a third person tries to join movie night and simply cannot, with nothing in the interface naming a limit. This is the release that stops it being silent.

It also stops the upgrade itself being guesswork. There is now a read-only command that tells you what 3.0 will make of your 2.1.x configuration before you pull it, and the deployment examples for Compose, CasaOS, TrueNAS and Portainer are generated from one schema rather than kept in step by hand.

The third change is the one your Emby server will feel: HEVC sources are no longer re-encoded for viewers whose browser could already play them. That shipped on the stable line as 2.1.2 and is carried here so upgrading to 3.0 does not undo it.

### A blocked action now says so

Party creation, joining, admin login, avatar recovery, background requests, socket connections and chat all name the limit and show a safe retry delay. Previously most of them showed nothing useful: chat, avatar recovery and the background party list said nothing at all, and a rate-limited join showed only a generic "could not authenticate" banner. Party creation and admin login were worse than nothing, throwing an error neither page caught, so the create button stuck on "Creating party..." and the admin login button simply did not respond.

Chat text refused by a limit is handed back rather than discarded, and if you had already started typing something else it is kept beside the composer instead of being pasted in front of it.

Every 429 carries the same `{detail, code, retry_after}` shape, and each one names the limit that actually refused the request. That last part is not decoration. Diagnostics that describe a limit the request never hit send you looking for a setting that does not exist, and this cycle found several of those, described in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

### Find out before you upgrade, not after

```
docker compose run --rm --no-deps emby-watchparty python -m backend.migration_preflight
```

A read-only command that reads your existing configuration, whether it reaches 3.0 through the process environment, `.env` or `config.json`, and reports what 3.0 will make of it. It writes nothing, prints no secrets, and needs the container only to run, not to start the application. Under Compose your `.env` arrives as environment variables rather than as a file, so the report names `process environment` as the source and notes that no `.env` was found; mount it read-only as well if you want its lines checked directly.

It resolves values with the same loader the application boots with and takes its verdict from the same startup validation, so **it cannot clear a configuration that 3.0 would then refuse**. It reports the settings that decide a 2.1.x migration, the proxy, HLS, session-expiry and rate-limit values, saying which are in effect and where each came from; the rest of your configuration is deliberately kept out of the report so a secret cannot reach it. It also gives the one-worker rule, the paths to preserve, the health and readiness URLs to check afterwards, and the backup and rollback steps that stay manual.

Run it **after** pointing your Compose file at a 3.0 image carrying this work and pulling it. The command ships inside that image, and no published image has it yet, `:3.0.0-beta1`, `:devel` and `:nightly` included; a 2.1.x image has no such module either. [`docs/Migration-HowTo.md`](docs/Migration-HowTo.md) carries the step order along with Compose, appliance, plain Docker, source and Windows invocations.

### One command that says whether playback works

`npm run test:playback-gate` drives a complete session against a fake Emby: authenticated master and media playlists, segments and byte ranges, pause and resume, seeking in both directions, audio and subtitle selection, reconnect, host reload, session-bind retry, cross-party denial, and the iPhone WebKit native-HLS path. It is the check to run before calling a change safe, and the one this cycle's fixes were held to.

### CI tests the application in parallel

Pull requests now split backend, frontend, browser, native-HLS, container and dependency checks into parallel jobs, then combine them behind one stable merge gate. Changed executable lines need 80% coverage, superseded runs are cancelled, failures retain browser/container evidence, and the exact built container must pass health, readiness, authenticated Chromium playback and high/critical runtime-vulnerability checks. Firefox and desktop WebKit add lifecycle, reconnect and accessibility coverage; macOS WebKit remains the native-HLS authority. Release automation is unchanged.

### Appliance deployment comes from one schema

`deploy/schema.json` is now the single description of a deployment, and
`scripts/generate_deployment_artifacts.py` renders it into the Compose example, `.env.example`,
the environment reference, a CasaOS v2 manifest and a TrueNAS SCALE 24.10+ Custom App YAML.
Each carries a schema hash, and CI fails the build if any of them drifts from the schema or
stops parsing as Compose. Portainer imports the Compose file directly; the maintainer keeps
Unraid's template in a separate repository, which Community Apps indexes through `TemplateURL`.

The generated files are examples to copy, not files to run in place. They ship
`APP_ENV=production` and leave `BEHIND_PROXY` and `SESSION_COOKIE_SECURE` commented out,
because neither has a safe default: production refuses to boot until you declare the proxy
topology, and a Secure cookie is silently discarded over plain HTTP. Both are explained
inline, along with the `config.json` mount, the `APP_PREFIX` subpath trap and what each image
tag tracks.

New platform guides under [`docs/deployment/`](docs/deployment/) cover Compose, CasaOS,
TrueNAS and Portainer, each with the read-only preflight, fail-closed health and readiness
diagnosis, updates, playback acceptance and full rollback, without ever deleting legacy data.

### HEVC stops being transcoded for viewers who can already play it

Shipped first on the stable line as 2.1.2 and carried here, so 3.0 does not regress against it. If you are coming from 2.1.2 you already have this; nothing below is new to you.

Until now every stream was requested as H.264, whatever the source was. That is the safe answer when you have no idea what the viewer's browser can decode, and it was the only answer available, because nothing ever asked. So an HEVC file was re-encoded on your Emby server for everybody, including people whose browser would have played the original untouched.

Watch Party now asks. Each viewer's browser reports what it can decode when they join, and the server keeps the source codec for the ones that can handle it. Anyone else still gets H.264, automatically, so nobody is left staring at a black video. Because streams are already built per viewer, **two people in the same party can be served different codecs**, which is the only thing that works when one is on a Mac and one is on a Windows box without the codec.

Nothing to configure, no `.env` changes, nothing added to the migration.

Measured on 2.1.2 against an 8K HEVC file, same machine, same browser, the only variable being whether the viewer could decode HEVC:

| | encoder on your server | work per 3s of video |
|---|---|---|
| viewer can decode HEVC | **none**, stream copied | **~50 ms** |
| viewer cannot | libx264 at 1080p | ~1750 ms |

Whether you get it depends on the viewer's machine, not just their browser, and that is worth knowing before anyone reports it as a bug. **macOS, iOS and Safari** decode HEVC natively. **Chromium browsers on Windows** use the GPU directly, but only while **hardware acceleration is enabled**, since Chromium ships no software HEVC decoder and turning acceleration off removes HEVC entirely. **Firefox on Windows** goes through Windows Media Foundation and needs a codec from the Microsoft Store: try the free [HEVC Video Extensions from Device Manufacturer](https://apps.microsoft.com/detail/9n4wgh0z6vhq) first, the [paid package](https://apps.microsoft.com/detail/9NMZLZ57R3T7) works everywhere, and codec packs such as K-Lite do **not** help because browsers do not use DirectShow filters.

Support is detected when you join, so if you install a codec or change your hardware-acceleration setting with Watch Party open, reload the page before rejoining.

One practical note that predates this but matters more now: **Auto** quality means "do not downscale". That is what you want when the source can be copied, and the worst case when it cannot, because a large source is then re-encoded at full resolution. If a viewer cannot decode HEVC, a capped quality will reach them far sooner than Auto will.

### Fixed

Three of these are defects a beta1 user can actually hit today.

- **Mobile library browsing no longer hides its own navigation.** Opening a library on a phone now replaces the oversized party controls with a compact library bar, keeps search and the A-Z rail inside the viewport, and provides an always-visible route back to all libraries. Alphabet jumps now use Emby's full-library prefixes and `SortName` pagination instead of only the posters already loaded, so enabled letters work immediately on mobile and desktop without fetching every image first.
- **A proxy error page no longer replaces the explanation.** When a reverse proxy answered with its own HTML error page, that page was printed in the party banner where the guidance should be. The fixed sentence now leads and any upstream detail follows in bounded parentheses.
- **Turning rate limiting off now turns off chat's limit too.** Chat is the one limiter that ignored the master switch in **Admin -> Security**, so with limiting disabled it was still the only one firing, silently dropping messages. This release would have made that visible by disabling the composer, which is what surfaced it.
- **A retry delay could be longer than the limit it belonged to.** A three-second window reported four seconds in `Retry-After`.
- **HEVC and other non-H.264 sources are no longer transcoded unconditionally.** `VideoCodec=h264` was hardcoded into every stream URL. It is now chosen per viewer from what that viewer's browser reported. Reported by **[miakkia](https://github.com/miakkia)** in [#61](https://github.com/Oratorian/emby-watchparty/issues/61), including a measurement showing Emby reporting Direct Play once the source codec was preserved.
- **The transcode log line no longer goes stale.** "Source is hevc, transcoding to h264" was written independently of the parameter that actually decides, so it kept claiming a transcode that was no longer being requested. Both now come from the same decision, and the message says whether the client could decode the source.

### Browse your library the way Emby does

The library browser gains filters driven by what your server actually reports, a A-Z jump bar backed by Emby's own prefix index rather than the posters already on screen, a grouped search across every library, and a full detail view for a title with its cast, related items, extras, trailers, seasons and episodes. A host can mark items played or favourite and build playlists without leaving the party.

Everything it sends to Emby is pinned against a corpus of real 4.9.5.0 responses, so a change that would have altered a request is caught by a test rather than by a viewer.

Two things to know if you are watching for them: filtering or sorting a TV library, and jumping to a letter in a large one, were both broken in the first cut of this work and are fixed. The details are in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

The rest of the rate-limit surfacing was written and corrected inside this cycle, so no published image ever carried these; they are listed because the code is on `3.0-dev` and reviewable, not because you are running them. A viewer's first join could be refused as "too many join attempts", the chat "message not sent" warning outlived its countdown, two refused chat messages merged into one reversed line, ordinary socket reconnects painted a red `xhr poll error` alert, and a stale party-list warning blamed rate limiting for the rest of a server outage. All are described with their causes in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

### Technical details

Three of the four bodies of work here are **[dnordel](https://github.com/dnordel)**'s: the rate-limit surfacing and the preflight as [#57](https://github.com/Oratorian/emby-watchparty/pull/57), 25 commits over 45 files, the deployment schema as [#58](https://github.com/Oratorian/emby-watchparty/pull/58), 16 commits over 20 files, and the library parity work as [#59](https://github.com/Oratorian/emby-watchparty/pull/59) and [#60](https://github.com/Oratorian/emby-watchparty/pull/60), 39 commits over 89 files. All landed on `3.0-dev` via their branches after an audit rather than through a PR merge.

Those audits found 20 defects in the first, 13 in the second and 64 in the third, all fixed before any of them landed. Their methodology, the defect classes, and the two failure patterns now recurring across cycles are in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

The codec negotiation is the third, built on the stable line for 2.1.2 and forward-ported here rather than written twice. `TranscodeReasons` was not the cause, despite being the obvious suspect: Emby treats it as informational, so removing `VideoCodecNotSupported` alone changes nothing. The forcing was the hardcoded `VideoCodec=h264`.

The client probes with `MediaSource.isTypeSupported` for the hls.js path and `canPlayType` for native HLS, accepting only `probably`, since `maybe` is the browser guessing and a guess is what this exists to avoid. Anything that throws counts as no capability. The server allowlists what it is told before any of it reaches an Emby URL, and stores it against the persistent `client_id`, so it survives a reload the same way the video selector does. Watch Party reports what the viewer can decode and stops there; which encoder Emby then reaches for is Emby's decision and is not second-guessed here.

Four things differ from the 2.1.2 change, all because 3.0 has diverged underneath it. `join_party` is a validated typed contract, so `video_codecs` is declared on `JoinPartyPayload` and the schema and TypeScript types are regenerated; strict inbound validation then makes the payload the first gate and the allowlist the second. The party is a typed aggregate, so codecs are a domain field rather than a dict key. The reconnect join lives in `usePartyReconnect`, so there are three emit sites rather than two. And a client that sends nothing gets the default empty list, which reads as H.264-only, which is exactly what an un-upgraded frontend sends.

Test coverage since beta1: **267 backend tests** across 36 modules (was 116), **70 Vitest** across 23 files (was 17), **16 Playwright** (was 14), with `ruff check`, `ruff format` and `eslint` clean, `mypy` clean over 48 source files, and both generated contracts free of drift.

---

## [3.0.0-beta1] - 2026-08-05 - Director's Cut

**First beta of the 3.0 line.** Published to GHCR as `:3.0.0-beta1`, and tracked by `:devel` and `:nightly`. It does **not** move `:latest`, which stays on the 2.1.x stable line, so a deployment pinned to `:latest` will not pick this up by accident.

Betas are image-only, as the whole 2.0 beta cycle was: no git tag and no GitHub Release, so the release list keeps showing 2.1.1 as the current stable.

Treat it as a beta. It has been exercised by an automated suite that drives real HLS through a fake Emby, and by a security pass that reopened and closed two blockers, but it has not been run in anger by a real household on a real Emby server. That is what this beta is for. Keep your 2.1.x image and configuration for rollback until you have completed a playback test.

**Read [`docs/Migration-HowTo.md`](docs/Migration-HowTo.md) before upgrading.** Its first section tells you whether you need to change anything at all; for most production deployments coming from 2.1.x the only addition is `BEHIND_PROXY`. The exception is anyone who turned HLS token validation off in **Admin -> Security**: that value is carried forward, production refuses to boot with the gate disabled, and the toggle that would have re-enabled it has moved out of the panel, so `ENABLE_HLS_TOKEN_VALIDATION=true` must be set in the environment.

2.0 rebuilt the product. 3.0 rebuilds the foundation underneath it. Nothing about what a watch party *does* changes: same parties, same per-user transcodes, same late-joiner vote, same admin panel, same look. What changes is how much of it the server can prove before it runs.

Three things drive the release:

- **Nothing untyped crosses a boundary.** Socket events, REST responses and the party's own state were passed around as raw dictionaries, so a mistyped payload key surfaced as a runtime `None` three layers away, and an untrusted socket payload was trusted as it arrived. Inbound events are now validated against generated contracts before a handler sees them, outbound events are validated on the way out, the party is a typed aggregate rather than a dict, and `mypy` runs across the whole backend.
- **The app is built, not imported.** Construction moved into an application factory, so the server is assembled by a function instead of assembling itself at import time. A test can bring up a real app per case, and a startup that fails halfway releases what it already opened instead of leaving it behind.
- **Tests talk to something that behaves like Emby.** The mocked routers are gone, replaced by a fake Emby server that serves real, playable HLS. Rate limits, socket validation, HLS rejection and browser-to-browser sync are exercised over the public surface, and CI gained a macOS WebKit job, so Safari's native-HLS path is finally covered by something other than a user reporting it.

Alongside those: a production readiness gate that refuses to boot an unsafe configuration instead of warning and continuing; redacted structured route logs, so an upstream failure cannot spill credentials into a log aggregator; hash-pinned Python dependencies; and `PartyView.vue` broken up into composables.

**Configuration stays environment-only.** A development build of 3.0 briefly carried a guided first-run setup page, and it is gone. It could not work where most of this project runs: on Unraid, CasaOS, Portainer and TrueNAS every setting is already a container environment variable, and the form short-circuited any field it found in the environment back to its existing value. So it accepted your edits, reported success, and changed nothing. The recovery token compounded it, written `0600` inside a `0700` directory owned by root, which is unreadable from the appdata path those platforms give you. If you completed that setup on a development build, copy anything you set only through the form into your environment before upgrading; `data/bootstrap.json` and `data/setup-token` are now ignored and deleted on first boot.

The work is **[dnordel](https://github.com/dnordel)**'s, contributed as [#45](https://github.com/Oratorian/emby-watchparty/pull/45): 165 commits over 139 files, of which 57 are tests and 51 are refactors. Too large and too breaking to land as one merge, so it went onto `3.0-dev` as the integration branch and was worked issue by issue against the [3.0 milestone](https://github.com/Oratorian/emby-watchparty/milestone/2), which is now empty.

### Security

`3.0-dev` forked from `2.0.2`, **before** the 2.1.0 security release, so none of that release's authorization work existed on the branch. All of it is back, and four findings the rework introduced are closed alongside it.

- **The 2.1.0 authorization work is re-established.** `/hls` requires the party-bound session cookie again, and the cookie's party must match the stream token's party, so the two gates can no longer be satisfied independently by different parties. Upstream playlist URIs are validated *before* rewriting rather than after, which had made the guard reject its own output. Legacy `admin_emby_*` cookie keys are scrubbed again, now from the party-session gate as well as the admin routes, so an admin upgrading from 2.0.x is cleaned up on their first request rather than only if they revisit `/admin`.
- **A departed host can get back into their own party.** `host_client_id` is deliberately retained after the host leaves so the in-flight stream survives, which keeps the identity reserved, while leaving discarded `host_session_grant`, the only proof of ownership. The result was unrecoverable rather than annoying: `/api/auth/login` needs a bound party, and `video_ended` / `stop_video` are gated to the selector, who is the locked-out host, so nobody remaining could end the video either. The grant now stands on its own and survives the unbind.
- **Socket rate limiting keys on the real client.** python-engineio writes the literal `127.0.0.1` into the handshake environ rather than the peer address, so every viewer in a deployment shared one bucket. With the shipped defaults that is 30 socket connections per minute *in total*, with no proxy and no attacker involved; Socket.IO reconnects spend the same budget, so a few people on poor connections could stop anyone else joining. The peer now comes from the ASGI scope.
- **HLS tokens no longer reach the logs.** uvicorn runs its own access logger, separate from the application's, and it writes the full request line at INFO. Every HLS URL carries `?token=`, so each playlist and segment request published a working stream credential to anything that ships logs onward. The redaction work had only ever covered the application logger.

Every one of these was verified by removing the fix and confirming the tests fail, rather than by inspection.

A second pass then went through the remaining audit findings. The ones with user-visible consequences:

- **Playback no longer dies on a parameter Emby chose.** The HLS proxy held every request to one allowlist of query parameters, built from what this application sends. Variant and segment URLs are Emby's, and their query round-trips through the browser back to that guard, so a parameter name Emby used and we did not recognise returned 400 and ended the stream. Emby's own names are now dropped rather than refused, which leaves the guard's security property untouched, since the parameter still never reaches Emby, and changes only the cost of being wrong from the whole stream to one parameter. The top-level request the player builds is still refused outright, because there an unknown name really is tampering.
- **An uppercase `.M3U8` no longer bypasses playlist handling.** Nothing constrained the case of a requested path, so that spelling missed the playlist branch entirely and the upstream body was returned unrewritten, unvalidated, and with no token appended to the child URIs it advertises.
- **Seeking works on iPhone and iPad.** Range metadata was forwarded only when Emby answered `206`, so a plain `200` arrived with no `Accept-Ranges` and a `416` lost the `Content-Range` a client needs to learn the real length and retry. iOS drives native HLS entirely through range requests, so it was the platform that suffered. Relatedly, the native-HLS path started playing during an active ready check, jumping ahead of everyone else, because that branch was missing a guard the other two playback paths had.
- **A host who reloads keeps their party.** An empty party was dissolved five seconds after the last socket dropped, sharing a constant with the unrelated question of how long to wait before handing on host privilege. A phone waking from background or a slow reconnect exceeded it and took the party's URL with it. Dissolution now has its own thirty-second window.
- **`SESSION_EXPIRY` now does what it has always claimed.** `.env.example` has always described it as the session cookie lifetime; the cookie was hardcoded to fourteen days and the setting governed only how long an administrator session survived server-side. **With the default `86400`, people are asked to rejoin after 24 hours idle rather than fourteen days.** The migration guide gives the value that restores the old behaviour. The administrator session TTL also became an idle timeout that renews on use, so a host who logged in a day earlier no longer loses admin controls part-way through an evening while the party itself keeps working.
- **Logs are readable again.** `/socket.io`, the SPA bundle and the party list, which is polled every few seconds per open tab, were each writing a line per request at INFO. The party list was the pointed case: its handler already logged at DEBUG and said why, and the middleware overrode that.
- **Upstream calls are time-bounded.** The Emby gateway passed `timeout=None` through to httpx, which reads an explicit `None` as *no timeout at all* rather than *use the client default*, so it actively overrode the configured 30-second bound and left twelve call sites unbounded. A slow or wedged Emby could pin a worker slot until the operating system gave up on the socket.
- **Two upstream advisories are patched**, carried over from 2.1.1: `socket.io-parser` ([CVE-2026-69185](https://github.com/advisories/GHSA-2m8v-j782-fhvr), high, and it runs in the browser) and `postcss` ([CVE-2026-69153](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp), medium, build-time only).

Two lessons from that pass are worth stating, because they shaped how the rest was checked. Three separate defects were hidden by the test harness rather than by the code: the fake Emby emitted only the narrowest shape a real Emby sends, so playlists carried no query string and ranges were clamped so `416` was unreachable. And five defects across the cycle existed only in a *second* copy of a guard that was correct in the first, including one introduced during this very pass and caught one commit later. Both patterns are now covered by tests that fail if the twin is missed.

### Expect a migration, not a drop-in

Unlike every 2.x release, this one needs reading before you upgrade, and [`docs/Migration-HowTo.md`](docs/Migration-HowTo.md) now covers the 2.1.x → 3.0 path.

Rate limiting becomes **enforced**, using the values already sitting in your `config.json`, values nobody has tuned because they previously did nothing. This is the change most likely to be noticed, and it is silent when it bites: a third person tries to join movie night and simply cannot, with nothing in the interface naming a limit.

`BEHIND_PROXY` is the one genuinely new setting, and production refuses to boot until you declare it, `true` or `false`. That is deliberate, because guessing wrong is silent: rate limiting keys on the address a connection arrives from, and behind a reverse proxy that address is the proxy, identical for every viewer, so all of them share one bucket. Setting it `true` makes `TRUSTED_PROXY_CIDRS` mandatory. If a forwarding header turns up on a deployment that declared itself direct, the server now says so in the log, once, rather than silently discarding it.

Bare-metal installs must delete and recreate their virtualenv rather than upgrading in place, because the hash-locked requirements put pip into `--require-hashes` mode and because pip never removes a package merely for leaving the requirements file. `requires-python` is declared, so a mismatched interpreter refuses the install instead of succeeding quietly; 3.0 is Python 3.12 only.

A misconfigured container now reports `setup_required` from `/api/health`, returns 503 from `/api/ready` and every other route, and prints the failing field names to stderr, instead of reporting healthy and writing nothing. It stays up rather than crash-looping, so the diagnosis survives in the log viewer those appliance platforms give you.

The two rough edges previously listed here are both closed. `EMBY_SERVER_URL` values like `http://emby_server:8096` now validate, because Docker Compose service names may legally contain underscores and Docker's own DNS resolves them; browser-facing CORS origins keep the strict form. The `data/` volume chmod went with the setup flow.

The full breakdown, breaking changes with their blast radius, the security analysis and the complete change log, lives in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

---

## [2.1.0] - 2026-08-03 - Midnight Premiere

A security release. Two authorization gaps are closed, and because the stricter gating can now refuse requests that used to succeed, the UI gained the banners needed to explain itself instead of leaving you staring at a dead player.

Nothing you have to configure, no `.env` changes, no migration. Upgrade, restart, done.

### Security

- **`/hls/...` now requires the party-bound session cookie.** These were the only browser-facing routes with no session gate: possession of the URL was the entire credential, and an HLS URL leaks easily through browser history, the `Referer` header, reverse-proxy access logs, and copy-as-cURL. They are now gated by `require_host_token`, the same gate `/api/image` and `/api/subtitles` have used since 2.0.0. This is what [CHANGELOG 2.0.0's breaking-change note](#200---2026-07-11---midnight-premiere) and `hls.py`'s own module docstring have described all along; `git log -S require_host_token -- backend/src/routers/hls.py` returns nothing, so the gate was documented but never actually applied.
- **The cookie's party and the stream token's party must now agree.** Adding the gate alone would have been close to cosmetic. `require_host_token` resolves a party from the *cookie*; the HLS proxy resolved one from the *URL token* and used that party's host credentials to sign the upstream Emby call. Nothing compared them, so both gates were independently satisfiable by different parties: a leaked token for a private party plus a session cookie from any open party streamed the private party's content under its host's Emby token. Verified during development that with the gate in place but the match assert removed, the cross-party request returns 200 and serves the playlist.
- **A scraped `client_id` no longer confers host or admin rights.** Host identity was established by matching `client_id` alone, but `host_client_id` is broadcast to every member in the `host_changed` event, and `POST /api/party/<id>/join` stores whatever `client_id` the caller supplies. Any attendee could therefore read the host's id off the broadcast, re-join supplying it, receive a **validly signed** session cookie carrying the host's identity, and reach `/api/admin/config` with full read/write whenever the host's Emby account had `IsAdministrator=true`. No leaked cookie and no network position were needed, only being in the party, which is the normal state for every viewer. Host identity is now proved by `host_session_grant`, a 256-bit secret minted server-side by `set_host`, written only to the real host's cookie, never broadcast, and compared with `compare_digest`. It is rotated on every promotion and cleared on `clear_host`, so a previous host's cookie stops proving anything the moment someone else takes over. The same check now guards host reclaim over Socket.IO, whose docstring had claimed a cookie-proof protection that this bypass defeated. Found by **[dnordel](https://github.com/dnordel)** while reviewing [#45](https://github.com/Oratorian/emby-watchparty/pull/45); the flaw predates 2.1.0 and shipped in every 2.0.x release.
- **The Emby admin token is no longer stored in the session cookie.** Starlette's `SessionMiddleware` *signs* the cookie but does not *encrypt* it, so the payload is `base64(json)` and anyone holding the cookie could decode it and recover a full Emby **administrator** access token, with no secret and no server access. That token grants control of the whole Emby server, far beyond Watch Party. Credentials now live in a server-side `AdminSessionStore` with only an opaque handle in the cookie, mirroring how `host_access_token` has always been kept server-side. Not XSS-reachable (the cookie is `httponly`); the realistic exposure was proxy and CDN logs that capture headers, infostealers scraping browser cookie jars, and plaintext on the wire wherever `SESSION_COOKIE_SECURE=false`. Admin logout now destroys the stored credentials rather than only forgetting where they live, and logging in scrubs the old plaintext keys from an upgrading admin's existing cookie.

### Fixed

- **The variant-playlist fetch is time-bounded again.** The `.m3u8` branch of the segment proxy called `httpx.get` without `timeout=_EMBY_HTTP_TIMEOUT`, unlike the master-playlist and segment fetches either side of it. Every HLS request pulls a variant playlist, so this was the most-hit of the three upstream calls and the only unbounded one; a slow or misbehaving Emby could pin a uvicorn worker slot until the OS TCP timeout, which is the exact failure the constant exists to prevent.
- **A failed session bind is no longer swallowed.** Joining a party caught a failed cookie call and carried on, on the reasoning that the socket join carried the same identity. That held while `/hls` authenticated on the URL token alone. It does not hold now: such a viewer would receive a stream URL and then 401 on every segment while chat, the participant list, and the member count kept working, so the party looked healthy and only the video was dead, with nothing logged and nothing shown. The bind now retries once to absorb a genuinely transient blip, then surfaces a banner with a working Retry that re-announces to the server and recovers playback without a page reload.

- **Better behaviour on iPhone and iPad.** The layout now honours the notch and home-indicator safe areas (`viewport-fit=cover` plus `env(safe-area-inset-*)`) and sizes against the dynamic viewport (`100dvh`), so controls no longer sit under Safari's collapsing toolbar. On the native-HLS path Safari uses, leaving a party now releases the stream instead of leaving the Emby transcode running, and playback blocked by the browser's autoplay policy is reported rather than failing silently. Lifted from [#45](https://github.com/Oratorian/emby-watchparty/pull/45).
- **The Emby login modal traps focus.** Tab and Shift+Tab cycle inside the dialog rather than escaping to the page behind it, Escape cancels, focus lands on the username field on open, and returns to wherever it was when the modal closes. Also from [#45](https://github.com/Oratorian/emby-watchparty/pull/45).

### Added

- **A tab tells you when another tab takes over the party.** The session cookie holds exactly one party id and cookies are shared across every tab in a browser profile, so a second tab joining a *different* party silently repoints it and the first tab's playback stops. Each tab now announces its party over a `BroadcastChannel` and a superseded tab says so, naming the other party, rather than stalling silently. Two tabs on the *same* party stay quiet, since both point the cookie at the same place. The banner leads with the no-action path (switch to the other tab) and puts the consequence in the button itself, because resuming here stops the other tab in turn: only one party can hold the cookie at a time.
- **Test coverage for both gaps** (`tests/test_admin_session.py`, plus expansion of `tests/test_hls_proxy.py` to 8 tests). The admin tests decode the `Set-Cookie` header exactly the way an attacker would and assert the token never appears in it. The HLS tests cover a missing cookie, a cleared host token, and a cookie/token party mismatch, the first automated coverage of the 423 the docstring has claimed since it was written. Both guards were checked for vacuousness by reintroducing the original bugs and confirming the suite fails.

### Known limitation

Two **different** parties open in two tabs of the same browser profile now break the older tab's playback immediately, where previously the video kept playing. This is inherent to the session cookie holding a single party id; `/api/image` and `/api/subtitles` have degraded this way since 2.0.0, and this makes it total and visible rather than partial and silent. Separate browsers, separate profiles, incognito windows, and separate devices are all unaffected. Scoping session state per party would fix it properly and is deliberately left for a future release.

---

## [2.0.2] - 2026-08-01 - Midnight Premiere

A single-fix patch release for a playback failure that only showed up on some Emby servers: the video would sit at 0:00 buffering forever and never start, while the party itself, chat, participants, sync, looked perfectly healthy. If your setup worked fine, nothing here changes for you; this is a safe drop-in either way.

The cause was a stray carriage return. Emby emits its HLS playlists with Windows-style CRLF line endings, and WatchParty's proxy was splitting them on `\n` only, so every media URI kept a trailing `\r`. The party token was then appended *after* that control character, which made HLS.js read the token as its own separate, invalid line. The browser never requested a variant playlist or a single media segment, and Emby eventually gave up and marked the session idle.

### Fixed

- **Playback no longer hangs at 0:00 on Emby servers that emit CRLF playlists.** `_rewrite_playlist` now splits with `splitlines(keepends=True)`, strips the terminator off each URI before appending `?token=` / `&token=`, then reattaches it, so the tokenized variant and segment URLs stay on one valid playlist line. Upstream CRLF/LF formatting and the final line termination are preserved byte-for-byte rather than being normalised to LF, so the proxied playlist stays faithful to what Emby served. Public routes, configuration, and the token scheme are unchanged.

### Added

- **Integration test coverage for the HLS proxy** (`tests/test_hls_proxy.py`, 4 tests). Exercises master-playlist rewriting, variant-playlist rewriting, and transport-stream proxying through the real public HLS routes, plus a direct regression test asserting CRLF and final-line-ending preservation. This is the first automated coverage the HLS proxy has had.

Reported, diagnosed, and fixed by **[dnordel](https://github.com/dnordel)** in [#44](https://github.com/Oratorian/emby-watchparty/pull/44), including a reproduction against a real CRLF Emby master playlist. Thank you!

---

## [2.0.1] - 2026-07-14 - Midnight Premiere

A patch release focused on playback control and sync. In 2.0.0 only the host / video selector could play, pause, or seek; everyone else's controls silently did nothing. 2.0.1 makes control **democratic**: any member of the party can play, pause, seek, and skip the intro, and it syncs to the whole room. If one person pauses, everyone pauses -- the way a watch party is meant to work. The library panel also now closes for everyone when a video is picked, and the host's Hide/Show Library button once again follows on every client.

The harder part was doing this without the room dissolving into a pause-storm. The old selector-only gate had quietly been absorbing every client's *synthetic* playback events (buffering pauses, HLS re-alignment seeks, stall-recovery nudges), so opening control to everyone surfaced a class of browser-noise bugs that had been masked for two years. Those guards are now re-established client-side, decoupled from the access model, so shared control and clean sync coexist.

### Changed

- **Playback control is now democratic, not selector-only.** `_authorized_controller` was relaxed from a selector/host gate to a plain party-membership check: any joined member may drive play / pause / seek, and it broadcasts to the whole room. A stray / non-member socket (no registered `client_id`) is still rejected. This deliberately loosens the selector-only gate added during the 2.0.0 security audit -- shared control is the intended watch-party experience for a private, code-gated party. Seek stutter-loops remain guarded by the existing ready-check handshake, independent of who initiates the seek.
- **Library visibility syncs across the party.** Picking a video now closes the library for **every** client (via the symmetric `currentVideo` watcher), not just the picker's own screen. The `toggle_library` client listener dropped in the Vue rewrite is restored, so the host's Hide / Show Library button once again follows on every client -- the server was already broadcasting it to no listener.

### Fixed

- **"Something keeps pausing right after anyone hits play."** The play handler's stall-recovery nudge fires at 1000&nbsp;ms, but the `isSyncing` guard that suppresses synthetic seeks was released at 500&nbsp;ms. So the recovery's `hls.stopLoad()`/`startLoad()` re-seek dispatched a native `seeking` event that the player forwarded as a *user* seek, which the server's "seek during playback" path answered by force-pausing the whole room. A self-inflicted loop on the initiator's own client -- latent since the 2.0 rewrite, but unmasked once democratic control let every client's events reach the room. The stall-recovery re-seek is now wrapped in `isSyncing` so its synthetic events are swallowed. Diagnosed live from DEBUG server logs.
- **Buffering no longer pauses the party.** Under democratic control, a client whose HLS stream stalls fires a native `pause` that would broadcast to everyone. A genuine user pause leaves the element fully buffered (`readyState >= 3`); a stall drops below it. The pause emit is now suppressed while buffering, so one person's connection hiccup can't pause the room.
- **Spectator desync self-corrects.** A resume-only heartbeat safety net re-asserts the authoritative play state when a client's `<video>` drifts from a still-playing party (dropped emit, tab-suspend, OS media key), wrapped in `isSyncing` so it never re-emits or flaps.

Every issue fixed in this release was reported by **@xyxxyxxy** -- the play/pause reproduction, the library-not-closing observation, and the "everyone should be able to control the party" call that shaped it. A per-party host-only-vs-everyone toggle is planned for a follow-up.

---

## [2.0.0] - 2026-07-11 - Midnight Premiere

2.0 is a top-to-bottom rewrite of Emby Watch Party. The 1.x line was a Flask app with Jinja templates, vanilla JS on the frontend, and a single shared Emby transcode that the whole party watched in lockstep: one stream URL, one audio track, one subtitle, one quality. It worked, but the architecture made every "can I have my own subtitles", "can I lower my quality on hotel wifi", "why am I stuck on Japanese audio because someone else picked it" request a structural impossibility.

2.0 starts over on three foundations:

- **FastAPI + Vue 3 + TypeScript** replaces Flask + Jinja + vanilla JS. Async end-to-end, typed Pydantic schemas with auto-generated OpenAPI docs at `/docs` and `/redoc`, Pinia stores, Vue Router, Vite for dev + build. A single uvicorn process serves the backend and the compiled frontend from the same Docker image.
- **Per-user transcodes**. Each user gets their own `PlaySessionId` and their own Emby HLS stream. Audio track, subtitle, and quality are now personal settings that can be changed mid-playback without pausing the rest of the party. Drift correction was re-added to keep these independent streams in sync against the authoritative party clock.
- **Late-joiner vote flow**. Per-user transcodes break the old "everyone gets the same Emby segments" guarantee, so late joiners can no longer be slotted in mid-playback without keyframe misalignment. Existing users now vote on whether to admit a late joiner; if the vote passes, the video restarts from the beginning so every session lands on PTS-aligned segment 0.

Around those pillars: an admin panel at `/admin` with 17 hot-reloadable runtime settings, a unified subtitle dropdown that handles text subs (side-channel proxy) and image subs (burned-in transcode) in the same UI, a mobile chat slide-over, reload-as-rejoin via persistent `client_id`, library browse-position persistence, and a codename system. See the **[project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** for the full end-user walk-through.

Codename: **Midnight Premiere**. Branch: `2.0-Rework` (becoming `main` on cutover). Closed-beta images were tagged `2.0.0-betaN` on GHCR through the eighteen-beta cycle; the stable image is tagged `2.0.0` and `:latest`. The three fixes below land on top of `2.0.0-beta18` as the last changes before the stable cut.

### Changed

- **Admin panel opens as an in-party modal.** Clicking the gear icon from inside a party used to route to the standalone `/admin` view, which unmounted the video component and destroyed the HLS.js instance -- returning restarted playback for the whole party. The panel is now extracted into an `AdminPanel` component that mounts as a modal overlay above the player, so opening / saving / closing settings never touches the video. Standalone `/admin` still works for pre-party admins.

### Fixed

- **Silent socket disconnects no longer strand users in the party.** Reported by [@xyxxyxxy](https://github.com/xyxxyxxy) on Discord: a mid-session network blip caused pause / play / seek events to stop reaching the affected user in both directions, with no indication anything had gone wrong -- only a page reload restored sync. Traced end-to-end: the server hard-evicts the user from the party room on `disconnect`, `socket.io-client` auto-reconnects with a fresh sid, and nothing on the client re-issued `join_party`. So the reconnected socket belonged to no party room, and every `sio.emit(..., room=party_id)` silently skipped it. The socket store now tracks a `hasEverConnected` flag; the party store re-emits `join_party` on every subsequent connect (client_id is stable, so the server takes the known-participant fast path via `_replace_sid` -- no late-joiner vote, no lost transcode). An amber "Reconnecting to party…" banner renders during the outage so the drop is visible instead of invisible.
- **Library rescan no longer traps users in a fake-empty grid.** Reported by [@xyxxyxxy](https://github.com/xyxxyxxy) on Discord: mid-scan Emby responses came back empty, the frontend pinned that empty state to `localStorage` as the restore target, and every subsequent mount rendered "no items" until the container was restarted. Three separate bugs stacked: `emby_client.get_items` swallowed `requests.RequestException` into `{}` so a genuine upstream error looked identical to an empty folder; `/api/items` returned no `Cache-Control` header so intermediate proxies could cache the empty page; and `LibraryBrowser.saveLibraryState` unconditionally pinned the current location on load, including when the response was empty. Now `get_items` re-raises and the router returns a proper `502 Bad Gateway`, `/api/items` responses carry `Cache-Control: no-store`, and the localStorage restore target is only pinned when the response actually contained items -- so a mid-rescan empty response is treated as ambiguous instead of authoritative.

The full per-beta breakdown of the 2.0 development cycle (beta1 through beta18, every Added / Changed / Fixed bullet, breaking changes, and technical deep-dives) is preserved at the [v2.1.0 tag](https://github.com/Oratorian/emby-watchparty/blob/v2.1.0/SUMMARY-OF-CHANGES.md); `SUMMARY-OF-CHANGES.md` on this branch tracks the 3.0 cycle instead.



### Breaking Changes (cumulative across the 2.0 dev cycle)

- **`EMBY_USERNAME` and `EMBY_PASSWORD` are no longer read from `.env`.** Per-user Emby authentication is now an in-app action: any party member clicks "Login to Become Host" inside the party and supplies their own Emby credentials. The backend never stores long-lived user credentials at rest; only the admin server key (`EMBY_API_KEY`) remains in env. Existing deployments must remove these two lines from `.env` before upgrading.
- **`REQUIRE_LOGIN` semantics changed** ([#31](https://github.com/Oratorian/emby-watchparty/issues/31)). The setting now gates only party CREATION:
  - `false` (default): anyone can create a party. Spectators join with just the code. Any member can later click "Login to Become Host" to unlock the library for everyone in the room. Browsing always requires a host with a valid Emby session.
  - `true`: party creation requires Emby credentials in the request body; the creator becomes host atomically. Spectators still join with just the code, no Emby login prompt.
  - The setting also moved from `.env` to `config.json` -- it's now a runtime admin-panel toggle, hot-reloadable.
- **Backend HTTP endpoints now require a party-bound session cookie.** `/api/libraries`, `/api/items`, `/api/search`, `/api/item/<id>...`, `/api/intro`, `/api/image`, `/api/subtitles`, and `/hls/...` all return `401` without a session and `423 Locked` when the party has no host. The frontend obtains the cookie automatically via the new `POST /api/party/<id>/join` step before the socket connection.
- **`POST /api/party/create` request body changed.** Anonymous create with `REQUIRE_LOGIN=false` accepts an empty body or just `{ client_id }`. With `REQUIRE_LOGIN=true`, the body now requires `{ client_id, display_name, username, password }`.
- **`/api/auth/login` is now "become host of your current party"**, not a global login. Requires a party-bound session cookie. Body is `{ username, password }`; on success the caller is recorded as host and the room sees a `host_changed` socket event.
- **Frontend `/login` route removed.** The global LoginView is gone; logging in as host happens inside a party via the "Login to Become Host" button.
- **`current_video.selected_by` is now a client_id, not a sid.** Selector identity now survives reloads and brief reconnects without re-electing on a fresh sid.
- **New `.env` values as of beta18** (session cookie hardening, see beta18 entry below):
  - **`SESSION_SECRET`** — the signing key for the party-bound session cookie. Must persist across process restarts and across every uvicorn worker or existing cookies stop verifying. Previously an anonymous per-process random; now loaded from env. When empty, an ephemeral key is generated with a loud warning at boot — fine for local dev, catastrophic in production. Generate once with `openssl rand -hex 32`.
  - **`SESSION_COOKIE_SECURE`** (default `false`) — when `true`, the session cookie carries the `Secure` flag so it only rides HTTPS requests. Set `true` in every deployment behind TLS. Left `false` in local dev so the cookie still works over `http://localhost`.
  - **`CORS_ALLOWED_ORIGINS`** (default `*`) — comma-separated origin allowlist for the Socket.IO server. The historical `*` remains for backwards compat; production deploys should pin to their actual origin(s) (e.g. `https://watchparty.example.com`) so cross-origin XHR polling from unrelated pages can't open sockets against the server.
- **Session cookie name changed from `session` to `ewp_session` (beta18).** All existing party-bound cookies stop verifying on upgrade; every user is re-prompted to join their party. Sessions issued after the upgrade persist across restarts as long as `SESSION_SECRET` is stable.
- **HLS stream URL no longer carries `api_key=` (beta18).** The URL is now credential-free; the `/hls/...` proxy signs upstream Emby requests via the party's host access token. External tools that grabbed a full HLS URL from a party and expected to hit Emby directly with the embedded key no longer work — the URL only makes sense as a request to the WatchParty proxy from a session-cookie'd browser.

---

## Version History Summary

- **v3.0.0-beta1**  (2026-08-05): Architecture release, first beta -- typed socket/REST contracts with runtime validation, application factory, production readiness gate, and a fake-Emby test suite. Configuration is environment-only. The 2.1.0 authorization work is re-established, and the audit backlog is closed. Does not move `:latest`.
- **v2.1.0**  (2026-08-03): Security -- `/hls` now session-gated with a cookie/token party match, and the Emby admin token moved out of the session cookie.
- **v2.0.2**  (2026-08-01): HLS token rewriting fixed for CRLF playlists (playback stuck buffering at 0:00) + first HLS proxy tests.
- **v2.0.1**  (2026-07-14): Democratic playback control (any member can play/pause/seek) + sync-guard fixes.
- **v2.0.0**  (2026-07-11): Official release after 6 months of beta.
- **v1.6.7**  (2026-07-01): Security bump python-socketio to >=5.16.2 (CVE-2026-48804)
- **v1.6.6** (2026-05-05): CC button switching fix, subtitle 401 fix, label clarity
- **v1.6.5** (2026-05-03): PGS subtitles fixed, Skip Intro 403 fixed
- **v1.6.4** (2026-04-21): Pause/seek after host reconnect fixed
- **v1.6.3** (2026-04-12): `EnableAutoStreamCopy=false` -- the actual seek fix
- **v1.6.2** (2026-04-11): Force-transcode (attempt at seek fix)
- **v1.6.1** (2026-04-10): Peak-bitrate "fix" (later proven a no-op)
- **v1.6.0** (2026-03-22): Drift correction, chat actions, participant list
- **v1.5.x** (2026-03): Quality selector, static session, modular refactor, security fixes
- **v1.4.0** (2026-01-26): APP_PREFIX, playback progress sync, unified entrypoint
- **v1.3.x** (2026-01): `.env`-based config, gevent, library permissions
- **v1.2.x** (2025-11-12): Auto next episode, login gatekeeping, modular architecture
- **v1.1.x** (2025-10): Skip Intro, PGS handling, sync overhaul, themes
- **v1.0.x** (2025-10): Foundation -- core party features, audio fix, HLS proxy

---

## Links

- **Repository**: https://github.com/Oratorian/emby-watchparty
- **Issues**: https://github.com/Oratorian/emby-watchparty/issues
- **Releases**: https://github.com/Oratorian/emby-watchparty/releases

---

## Educational Use Notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
