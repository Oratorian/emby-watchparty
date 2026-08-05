# Summary of Changes -- 3.0 "Director's Cut"

Detailed development log for the 3.0 cycle. [CHANGELOG.md](CHANGELOG.md) carries the release-facing summary; this file carries the commit-level detail, the breaking changes with their blast radius, and the security analysis behind the milestone blockers.

The 2.0 "Midnight Premiere" log (beta1 through beta18, every Added / Changed / Fixed bullet and the 2.0 technical deep-dives) is not carried forward. It is preserved unchanged at the [v2.1.0 tag](https://github.com/Oratorian/emby-watchparty/blob/v2.1.0/SUMMARY-OF-CHANGES.md).

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

**Resolved.** Underscores are accepted through a separate service-name pattern applied only to addresses this server dials itself. CORS origins keep the strict RFC 1123 form, because a browser cannot originate from such a host, so loosening it there would only ever accept a typo. `EMBY_SERVER_URL` and `EMBY_API_KEY` are both stripped now.

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
