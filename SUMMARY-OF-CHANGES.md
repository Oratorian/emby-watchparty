# Summary of Changes -- 3.0 "Director's Cut"

Detailed development log for the 3.0 cycle. [CHANGELOG.md](CHANGELOG.md) carries the release-facing summary; this file carries the commit-level detail, the breaking changes with their blast radius, and the security analysis behind the milestone blockers.

The 2.0 "Midnight Premiere" log (beta1 through beta18, every Added / Changed / Fixed bullet and the 2.0 technical deep-dives) is not carried forward. It is preserved unchanged at the [v2.1.0 tag](https://github.com/Oratorian/emby-watchparty/blob/v2.1.0/SUMMARY-OF-CHANGES.md).

---

## [3.0.0-dev] - in development - Director's Cut

**Not released. Not tagged. Not safe to deploy.** The running version reads `3.0.0-dev` until the release cut, the same convention 2.0 used through its beta cycle. No GHCR image carries a 3.0 tag.

### Provenance

3.0 is **[dnordel](https://github.com/dnordel)**'s rework, contributed as [#45](https://github.com/Oratorian/emby-watchparty/pull/45): 165 commits touching 139 files, of which 57 are tests, 51 are refactors, 31 are fixes and 10 are features. The PR was retargeted and then closed rather than merged, because the change is too large and too breaking to land in one step and because it forked from `2.0.2`, before the 2.1.0 security release.

The branch is preserved as `3.0-dev`, the integration branch for the release, and the work is being landed issue by issue against the [3.0 milestone](https://github.com/Oratorian/emby-watchparty/milestone/2). CI runs on every push to it.

Grouped by area below rather than by commit; the branch has no beta cadence to break on.

---

### Breaking Changes

Ranked by how many deployments they affect. **Every one of these is silent.** None currently produces an error message naming the cause, which is itself tracked as work.

#### 1. Rate limiting becomes enforced, and collapses to a single bucket behind a reverse proxy

**Blast radius: nearly every deployment. The single most important item in the release.**

2.x has no global rate limiter. The `/admin` → Security sliders have been **inert** since they were added; only the ad-hoc admin-login bucket ever did anything. 3.0 installs `RateLimitMiddleware` on every request, covering all of `${APP_PREFIX}/api/*` except `/api/health` and `/api/ready`, **driven by the values already sitting in the operator's `config.json`**, values nobody has ever tuned because they did nothing.

It keys on the socket peer with `proxy_headers=False`, and `TRUSTED_PROXY_CIDRS` defaults to **empty**. Behind nginx, Caddy or Traefik, `resolve_client_ip` returns the proxy's address for every request, so **every viewer in every party shares one bucket**: 5 party creations per hour and 30 socket connects per minute, deployment-wide.

The symptom an operator actually sees is a third person trying to join movie night and silently failing to.

#### 2. Bare-metal upgrades break; the virtualenv must be recreated

**Blast radius: every non-Docker install.**

`requirements.txt` is now `pip-compile --generate-hashes` output. **Any** hash in a requirements file puts pip into `--require-hashes` mode, which additionally demands every transitive dependency be pinned with a hash **for the running interpreter**. The lock also drops `requests` and the `uvicorn[standard]` extras, and pip will not remove those from an existing environment, so an in-place upgrade leaves a half-migrated venv.

`pyproject.toml` has no `[project]` table and therefore no `requires-python`, so nothing enforces the 3.12 floor. The code floor is actually 3.11, so a 3.11 install succeeds silently on an interpreter CI never covers.

#### 3. Losing `data/bootstrap.json` fails **open** into development mode

**Blast radius: anyone who loses or does not mount `./data`. Security-relevant.** Tracked as [#49](https://github.com/Oratorian/emby-watchparty/issues/49).

`EnvConfig.from_env` treats a missing `data/bootstrap.json` as "no persisted values" and falls through to hardcoded defaults: `APP_ENV=development`, `CORS_ALLOWED_ORIGINS=*`, empty `SESSION_SECRET`, `SESSION_COOKIE_SECURE=false`. Because the strict checks only run when `APP_ENV == "production"`, a production deployment that loses its bootstrap file **silently downgrades to development posture**. It does not enter setup mode, and it does not fail.

#### 4. Setup mode reports HEALTHY to Docker and writes nothing to any log

**Blast radius: every Docker deployment that hits a boot-config error.** Tracked as [#50](https://github.com/Oratorian/emby-watchparty/issues/50).

`create_app` catches the startup-validation error and returns the setup app instead of raising. The setup app's health endpoint returns `{"status": "ok"}`, indistinguishable from the normal app, while the Dockerfile still probes `/api/health` and the compose example uses `restart: unless-stopped`. So a misconfigured container reports healthy, serves a setup page, and serves no API, no Socket.IO and no HLS. The setup app installs no middleware and never reaches `_setup_logging`, so nothing is logged at all; the bootstrap token reaches **stdout only**, printed at module import.

#### 5. `EMBY_SERVER_URL` validation rejects Docker service names containing underscores

**Blast radius: anyone using `http://emby_server:8096`.**

Hostname validation runs unconditionally, outside the production-only block, and the DNS label pattern permits no underscore. Docker Compose service and container names may legally contain `_`, and Docker's embedded DNS resolves them. The value is also not stripped the way `SESSION_SECRET` is, so a trailing space fails too. Failure lands the operator in setup mode with a healthy-looking container and no log line naming the field, per the item above.

#### 6. The setup form silently discards edits to env-provided fields

`validate_bootstrap_submission` short-circuits every field in `explicit_env_fields` back to its current value before validation, and a field counts as explicit if it appears in `os.environ` **or** `.env`. The recommended compose file uses `env_file: .env`, which loads the whole file into the process environment. **So for the recommended Docker deployment every bootstrap field is "explicit" and the setup page is entirely inert.** Edits appear to save and are discarded.

#### 7. `ENABLE_HLS_TOKEN_VALIDATION` moves from the admin panel to boot config

Restart-only now; runtime writes return an explicit "boot setting; restart required" rejection. The existing `config.json` value **is inherited automatically**, so nobody's setting silently changes, only the UI location moved. Documentation-only, but worth stating plainly: "my setting vanished from /admin" reads as data loss.

#### 8. Completing setup chmods the shared data volume to `0700`

`save_bootstrap_config` creates the directory then **unconditionally** chmods it to `0700`. `data/` is not new for upgraders; it has held `avatars.db` since 2.0 and is a documented bind mount. The container runs as root, so the host directory becomes root-owned `0700`.

#### 9. Single-worker requirement

Parties, Socket.IO mappings, HLS grants, admin sessions, limiters and timers are all process-local. README and SECURITY.md state this; the migration path does not.

#### 10. `uvicorn[standard]` becomes plain `uvicorn`

`uvloop`, `httptools` and `websockets` are absent from the lock. `wsproto` remains via `simple-websocket`, so WebSockets keep working. Not a functional break, a throughput regression on the Linux image, on the HLS hot path. Raised on the PR [here](https://github.com/Oratorian/emby-watchparty/pull/45#issuecomment-5160203879).

#### 11. No 2.x to 3.0 migration document exists yet

`docs/Migration-HowTo.md` is still titled "Migration: 1.x → 2.0" and this branch's entire change to it is one table row. Every new operator concept is documented only as first-install material. A `docs/Migration-HowTo-2x-to-3.md` is required before release, ordered: nothing-required-if-your-env-already-validates, `TRUSTED_PROXY_CIDRS`, venv recreation, the `EMBY_SERVER_URL` pre-check, bootstrap and setup semantics, the HLS toggle relocation, the single-worker rule, and the performance note.

---

### Security

#### Regressions: the 2.1.0 authorization work is not on this branch

`3.0-dev` forked from `2.0.2`, so **none** of the 2.1.0 security release is present. These are release blockers, not nice-to-haves, and none is closed by the rework:

- **[#46](https://github.com/Oratorian/emby-watchparty/issues/46) `/hls` has lost the party-session gate and the cookie-party vs token-party check.** The worst of the set. Possession of the URL is once again the entire credential, and a leaked token plus any open party's cookie streams a private party's content under its host's Emby token.
- **[#47](https://github.com/Oratorian/emby-watchparty/issues/47) `_rewrite_playlist` validates URIs *after* rewriting them,** so it rejects its own output.
- **[#53](https://github.com/Oratorian/emby-watchparty/issues/53) legacy `admin_emby_*` cookie keys are no longer scrubbed,** so an admin upgrading from 2.0.x keeps a live Emby administrator token in a signed-but-unencrypted cookie.
- **[#48](https://github.com/Oratorian/emby-watchparty/issues/48) a returning participant can be permanently locked out** of their own identity.

3.0 does not get a version number until every one of these is re-established with a test that fails when the fix is removed.

#### New findings introduced by the rework

- **[#52](https://github.com/Oratorian/emby-watchparty/issues/52) a client inside `TRUSTED_PROXY_CIDRS` can spoof its IP and evade every rate limit.** The new middleware makes this reachable where 2.x had nothing to evade.
- **[#51](https://github.com/Oratorian/emby-watchparty/issues/51) setup save writes env-injected `EMBY_API_KEY` and `SESSION_SECRET` to disk in plaintext.** The first-run setup path is the largest new attack surface in the release.
- **[#49](https://github.com/Oratorian/emby-watchparty/issues/49)** and **[#50](https://github.com/Oratorian/emby-watchparty/issues/50)**, above, are security-relevant as well as operational.

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

1. Re-establish every 2.1.0 authorization gate, each with a test that fails when the fix is removed ([#46](https://github.com/Oratorian/emby-watchparty/issues/46), [#47](https://github.com/Oratorian/emby-watchparty/issues/47), [#48](https://github.com/Oratorian/emby-watchparty/issues/48), [#53](https://github.com/Oratorian/emby-watchparty/issues/53)).
2. Close the findings the rework introduced ([#49](https://github.com/Oratorian/emby-watchparty/issues/49), [#50](https://github.com/Oratorian/emby-watchparty/issues/50), [#51](https://github.com/Oratorian/emby-watchparty/issues/51), [#52](https://github.com/Oratorian/emby-watchparty/issues/52)).
3. Write `docs/Migration-HowTo-2x-to-3.md` and make every breaking change above announce itself in a log line naming the field.
4. Document `TRUSTED_PROXY_CIDRS` as the first item of that guide, add it to the commented `environment:` block in `docker-compose.yml.example`, and warn at boot when a proxy is likely and the list is empty.
5. Add `[project]` with `requires-python = ">=3.12"`, or a `sys.version_info` guard that exits with a named message.
6. Regenerate the Python lock on Linux so `uvloop` and `httptools` are present for the image.
7. Restore `docs/Migration-HowTo.md`'s missing 2.x context and reassure on the `ENABLE_HLS_TOKEN_VALIDATION` relocation.
