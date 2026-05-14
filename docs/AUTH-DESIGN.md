# Auth Design

Design notes for the 2.0 authentication overhaul. The current login
model is a partial enforcement layer: `REQUIRE_LOGIN=true` gates the
frontend UI only, the backend HTTP and Socket.IO surfaces are anonymous
to anyone who can reach them, and a long-lived service account in
`.env` (`EMBY_USERNAME` / `EMBY_PASSWORD`) signs every Emby call. This
document describes the model that replaces it before 2.0.0 is cut.

The refactor keeps `REQUIRE_LOGIN` as a runtime admin setting, but
narrows what it controls. In both modes, browsing the library always
requires Emby authentication (this is what gatekeeps the backend). The
setting only governs whether **party creation** is also gated:

- `REQUIRE_LOGIN=false` (default, permissive): anyone can create an
  empty party with a code; the party starts in the locked state and
  unlocks the moment someone in it logs into Emby. Matches the
  zero-friction "I want to spin up rooms without restrictions" mode.
- `REQUIRE_LOGIN=true` (restrictive): party creation also requires
  Emby login. The creator is the party's first host. Matches
  [#31](https://github.com/Oratorian/emby-watchparty/issues/31)'s
  "Emby login required only for creating rooms" use case.

## Table of contents

- [The problem](#the-problem)
- [The model](#the-model)
- [Goals and non-goals](#goals-and-non-goals)
- [Session kinds](#session-kinds)
- [Party-state additions](#party-state-additions)
- [Three-state lock](#three-state-lock)
- [Lifecycle](#lifecycle)
- [Backend to Emby calls](#backend-to-emby-calls)
- [Route-level auth requirements](#route-level-auth-requirements)
- [Token lifecycle](#token-lifecycle)
- [What changes vs. today](#what-changes-vs-today)
- [Threat model](#threat-model)
- [Open questions](#open-questions)
- [Migration notes](#migration-notes)

## The problem

The current 2.0 backend has two unresolved auth weaknesses:

1. **Service account in `.env`.** `EMBY_USERNAME` and `EMBY_PASSWORD`
   are long-lived plaintext credentials sitting in the deployment
   environment. They sign every library / item / image / HLS call.
2. **Anonymous backend access.** `REQUIRE_LOGIN` gates the frontend UI
   only. The backend HTTP routes (`/api/library`, `/api/items`,
   `/hls/*`, `/api/image`) and the Socket.IO server accept any caller,
   so a third party who can reach the server can enumerate libraries,
   start transcodes, or join Socket.IO for any party id they know
   without ever going through the UI.

Issue #31 adds a third requirement that the current `REQUIRE_LOGIN`
implementation cannot express: "Emby login required only for creating
rooms." Today's `REQUIRE_LOGIN=true` forces login on everyone
(including spectators); `REQUIRE_LOGIN=false` skips login entirely
even though the backend itself is callable anonymously. Neither maps
to "create gated, join open." The new model keeps the setting and
maps it directly: `true` gates create, `false` does not, browse is
always gated regardless.

## The model

A party has a **host**: the Emby user whose account currently powers
its library and transcodes. The host's Emby `AccessToken` is what the
backend uses to talk to Emby for everything inside that party --
library listings, transcode starts, HLS proxying, image proxy. While
the host is present, every party member can browse the host's library
and pick from it; the host's account is the lens but everyone in the
party gets to look through it. Spectators join with the party code
only and never see an Emby login prompt unless they want to take over
as host themselves.

How a party gets its first host depends on `REQUIRE_LOGIN`:

- **`REQUIRE_LOGIN=true`**: only Emby-authenticated requests can call
  `POST /api/party/create`. The creator is the host from the moment
  the party exists.
- **`REQUIRE_LOGIN=false`**: anyone can call `POST /api/party/create`.
  The new party has no host and starts in the locked state. The
  first person inside it to click **Login to Become Host** becomes
  the host.

When the host leaves the party, the library re-locks immediately (no
new picks are possible), but the current playback continues to its
natural end using the host's stored token. Once the playback ends, the
token is wiped and the party is fully locked. Any spectator still in
the party can click **Login to Become Host** at any time, authenticate
with their own Emby account, and take over. The new host's library
replaces the old one; the new host's token is used from then on.

There is no admin bootstrap step at server start. The server boots
with no Emby credentials and is immediately ready to host parties.
`/admin` requires whoever the current host is to have
`Policy.IsAdministrator=true`; any Emby admin who logs into a party
also gains admin-panel access for the lifetime of that session.

Only one Emby identity is ever active per party at a time. Pool /
multi-host models were considered and rejected because Emby applies
per-user library ACLs: two logged-in users with different libraries
would produce a confused shared view. A single host means one
unambiguous library, one unambiguous token, one unambiguous
`IsAdministrator` answer.

## Goals and non-goals

**Goals**

- Remove `EMBY_USERNAME` / `EMBY_PASSWORD` from `.env`. The backend
  starts with no Emby credentials and never holds a global service
  token.
- Make every Emby-touching backend call require an Emby-authenticated
  caller (the party's current host), in both `REQUIRE_LOGIN` modes.
- Keep `REQUIRE_LOGIN` as a runtime admin toggle that controls
  whether party creation is also gated (resolves #31).
- Keep the party-code join UX intact: spectators visit the shared
  link, pick a display name, join. They never see an Emby login
  prompt unless they want to take over as host.
- Allow any Emby user on the configured server to become the host of
  any party they are inside, including parties someone else created.

**Non-goals**

- Replacing Emby as the identity provider. This design uses Emby's
  `AuthenticateByName` endpoint; the watch party backend stores no
  passwords and grants no tokens of its own.
- Pool / multi-host model. One Emby identity at a time per party.
- A single "admin who runs the deployment" concept that has to log in
  at startup. Any Emby user with admin policy gains admin-panel access
  by virtue of being the host.
- MFA, password complexity, rate limiting, account lockout. Those are
  Emby's responsibility.
- Forcing every party participant through Emby login. Spectators watch
  and chat with just the party code.

## Session kinds

A request to the backend is authenticated as one of three kinds:

1. **Anonymous.** No session at all. Allowed to hit health,
   party-existence probe, the join endpoint, the create-party endpoint
   (which itself may require Emby creds in the body, depending on
   `REQUIRE_LOGIN`), and static assets. Everything else: 401.
2. **Party-bound** (signed session cookie). Issued by
   `POST /api/party/<id>/join`. Carries `{ party_id, client_id,
   display_name, issued_at }`, signed server-side. Required for
   essentially everything party-scoped: chat, playback state, the
   Socket.IO connection, HLS streaming, subtitle proxying, image
   proxy, library browse, search, item details, `select_video`,
   `change_streams`, Stop Video.
3. **Admin.** A party-bound session whose `client_id` matches the
   party's `host_client_id` AND whose host record has
   `host_is_admin=true`. Required for `/admin/*`.

The "host" is not a session class. It is a property of the **party**
recording which client currently provides the Emby token. Any
party-bound caller can browse and pick. Whether the call succeeds
depends on whether the party currently has a host whose token can be
used. This is how the user's stated intent works: "whoever logs in
opens the library for everybody in the party."

Per-route auth therefore breaks into two checks:

- **Party-bound** (have a valid party cookie for this party).
- **Party unlocked** (`party.host_access_token` is set, i.e. the
  party currently has a host).

Most library / item / select routes require both: party-bound AND
party unlocked. Stop Video adds a third check: the caller's
`client_id` matches `current_video.selected_by` (whoever picked is
the only one who can stop, same as 1.x).

## Party-state additions

Each party record gains the following fields (in `party_manager.py`):

| Field | Meaning |
|---|---|
| `host_client_id` | Persistent client id (from localStorage) of the current host. None when the party is locked. |
| `host_user_id` | Emby `User.Id` of the host. |
| `host_access_token` | Emby `AccessToken` of the host. In-memory only, never persisted, never sent to the client. |
| `host_is_admin` | Cached `Policy.IsAdministrator` from the auth response. |
| `host_username` | Emby display name of the host, used for UI. |
| `host_left_at` | Wall-clock time when the host last disconnected. Drives the rejoin grace window and the three-state transition. |

When the host disconnects, `host_client_id` is preserved for a short
grace window so a refresh / brief reconnect reclaims host status
automatically (via the existing `_replace_sid` path). If the window
expires without a matching rejoin, the host fields stay set just long
enough for current playback to drain; the access token is wiped on
`video_ended` / `stop_video`.

## Three-state lock

| Host present | Playback active | State | Browse button reads |
|---|---|---|---|
| Yes | * | **UNLOCKED** | "Browse Library" |
| No | Yes | **PLAYING-ONLY** | "Login to Become Host" |
| No | No | **LOCKED** | "Login to Become Host" |

Transitions:

- Anonymous join into a party with no host yet → LOCKED.
- Emby login (create party or become host) → UNLOCKED.
- Host disconnects without rejoin within ~5s → PLAYING-ONLY if a video
  is active, otherwise LOCKED.
- `video_ended` / `stop_video` while host is absent → LOCKED;
  `host_access_token` is wiped.
- New "Login to Become Host" submitted from any spectator in the
  party → UNLOCKED with the new host's identity. If the previous
  host's token was still serving an in-flight playback, that playback
  transitions to the new host's token at the next natural break
  (`change_streams`, segment boundary on the next pull) or simply
  stays under the old token until the video ends and the new host
  picks something fresh. Implementation detail; punted.

The disconnect grace window reuses `_replace_sid`: a rejoin whose
`client_id` matches the party's `host_client_id` re-establishes host
status without re-authentication.

## Lifecycle

### Server start

Backend reads `EMBY_URL` from `.env`. No Emby credentials. Health and
party-existence probe are immediately available. No bootstrap step.

### Creating a party

Behaviour depends on `REQUIRE_LOGIN`.

**`REQUIRE_LOGIN=true`:** A user clicks **Create Party** on the index.
The frontend opens an Emby login modal. User submits credentials.
Frontend calls `POST /api/party/create` with `{ username, password }`.
Backend:

1. Calls Emby `AuthenticateByName`. On 401, returns the error to the
   form.
2. On success, generates a party id, creates the party record,
   populates the host fields with the authenticated user.
3. Issues a party-bound session cookie that also flags this client as
   the host.
4. Returns `{ party_id, url }`.

The user is redirected to the party. They are the host.

**`REQUIRE_LOGIN=false`:** A user clicks **Create Party** on the
index. No login prompt. Frontend calls `POST /api/party/create`
anonymously. Backend creates the party with no host (all host fields
None), issues a party-bound session cookie without host status,
returns `{ party_id, url }`. The user is redirected to the party.
The party is in the LOCKED state until someone clicks **Login to
Become Host**.

### Joining a party (anonymous)

A spectator visits `/party/<id>` (from a shared link or by entering
the code on the index). Frontend calls `POST /api/party/<id>/join`
with `{ display_name, client_id }`. Backend validates the party
exists, issues a party-bound session cookie carrying
`{ party_id, client_id, display_name }`. No Emby contact.

Inside the party the spectator can chat, watch what the host picks,
and change their own audio / subtitle / quality. The library button
reads "Login to Become Host" because there is a host who is not them
(or because the party is currently locked).

### Picking a video (any party member)

Any party member (host or spectator) clicks **Browse Library**.
Frontend calls `GET /api/library` with the party cookie. Backend
reads the party's `host_access_token` (which is set because the
party is unlocked), fetches libraries from Emby under it, returns
them. The caller drills in, picks an item, frontend calls
`POST /api/party/<id>/select`. Backend uses the host's token to call
PlaybackInfo, start the transcode, sets `current_video.selected_by`
to the caller's `client_id`, and broadcasts `video_selected`.
Per-user transcodes for every party member (including the caller and
the host) are started under the host's token, each with its own
`PlaySessionId`.

The host's Emby ACL determines what is in the library. Spectators
without their own Emby accounts see and pick from whatever the host's
account is allowed to see. This is how the user's intent is realised:
the host's login opens the library for everybody.

Only the user who picked the current video (`selected_by`) can stop
it (Stop Video). This preserves 1.x's selector model. Changing the
selection by picking something new makes the new caller the
selector.

### Host disconnects mid-playback

Host's socket closes. `host_left_at` is set. After ~5 seconds without
a rejoin matching `host_client_id`, the backend emits `host_left` and
the party transitions to PLAYING-ONLY. The current transcode keeps
running because Emby holds the session by token, not by socket. HLS
proxying for the rest of the party continues using
`host_access_token`. Library browse for any spectator now returns 401
and the UI shows "Login to Become Host."

### Host returns mid-playback (via client_id)

If the host reopens the URL or refreshes their browser before the
playback ends, their persistent `client_id` matches. `_replace_sid`
migrates the host status to the new sid, party transitions back to
UNLOCKED, `host_reclaimed` is broadcast.

### Playback ends with no host

Either `video_ended` (natural completion) or `stop_video` (the
selector was still present and stopped it before disconnecting)
fires. If the party has no active host at that moment,
`host_access_token` and the rest of the host fields are wiped. Party
transitions to LOCKED.

Note that in PLAYING-ONLY state with the selector still present but
the host gone, `stop_video` is still allowed (it is selector-bound,
not host-bound). The host's stored token continues to serve the
in-flight teardown.

### New host takes over

Any spectator clicks **Login to Become Host**. Modal opens. They
submit Emby credentials. Backend calls `AuthenticateByName`, on
success populates the party's host fields with the new user, upgrades
their session to host, emits `host_changed`. Their library is now
what the party sees. They can pick the next thing.

## Backend to Emby calls

Every call the backend makes to Emby is signed with the current
party's `host_access_token`. The token lives in `party.host_access_token`
keyed by `party_id`, in-memory, scoped to the party.

- **Library / item / search / image proxy / PlaybackInfo / transcode
  start / HLS / subtitles / intro**: all use `host_access_token`.
- **Admin endpoints in Emby** (rare): same token, the host has admin
  policy.

If any call returns 401 (token revoked, password changed in Emby),
the party clears `host_access_token`, transitions to PLAYING-ONLY if
playback is active or LOCKED otherwise, and emits `host_left` so
clients re-render the locked UI.

There is no global service token at any point. The backend starts
with no Emby identity. Until at least one party has a host, the
backend makes no Emby calls.

## Route-level auth requirements

| Route | Required auth |
|---|---|
| `GET /api/health` | Anonymous |
| `GET /api/auth/status` | Anonymous |
| `GET /api/party/<id>/exists` | Anonymous |
| `POST /api/party/<id>/join` | Anonymous |
| `POST /api/party/create` | Anonymous if `REQUIRE_LOGIN=false`; Emby creds in body if `REQUIRE_LOGIN=true` (becomes host on success) |
| `POST /api/auth/become-host` | Party-bound (becomes host on success) |
| `POST /api/auth/logout` | Party-bound |
| `GET /api/party/<id>` | Party-bound for this party |
| Socket.IO connection | Party-bound |
| `GET /api/library` | Party-bound + party unlocked (uses host token) |
| `GET /api/items` | Party-bound + party unlocked |
| `GET /api/search` | Party-bound + party unlocked |
| `GET /api/item/<id>` | Party-bound + party unlocked |
| `GET /api/item/<id>/streams` | Party-bound + party unlocked |
| `GET /api/image/*` | Party-bound + party unlocked |
| `POST /api/party/<id>/select` | Party-bound + party unlocked (selector becomes caller) |
| `POST /api/party/<id>/change-streams` | Party-bound + party unlocked (each user can change their own stream) |
| `POST /api/party/<id>/stop` | Party-bound + caller's `client_id` matches `selected_by` |
| `GET /hls/*` | Party-bound |
| `GET /api/subtitles/*` | Party-bound |
| `GET /api/intro` | Party-bound |
| `/api/admin/*` | Admin (the party's host, and host has admin policy) |

Browse / search / select / stop are host-only. Streaming routes are
party-bound: spectators get HLS, but the backend resolves their pulls
through the party's host token.

## Token lifecycle

Emby `AccessToken`s do not expire on their own. They remain valid
until revoked from Emby's admin panel or invalidated by a password
change.

- **Host logs out**: party host fields cleared, party transitions to
  LOCKED (or PLAYING-ONLY if currently playing). Host's session
  cookie becomes a plain party-bound cookie.
- **Host leaves the party** (closes browser, navigates away): same as
  logout after the grace window expires.
- **Host's Emby password changes**: next Emby call returns 401,
  backend clears the host state, emits `host_left`, party locks.
- **Server restart**: all party state is in-memory; everything gone.
  No persisted tokens to worry about.
- **Party closes** (last spectator leaves): party record is dropped,
  no token to clean up.

Tokens are held in memory only, scoped to the party they belong to,
never written to disk, never sent to clients.

## What changes vs. today

Removed:

- `EMBY_USERNAME` env var.
- `EMBY_PASSWORD` env var.
- The global service account model. No backend-held token outside of a
  party's host record.
- The "trusted network" assumption that allowed anonymous HTTP and
  Socket.IO callers to talk to Emby through the backend.

Changed:

- `REQUIRE_LOGIN` runtime setting **kept**, but its semantics change.
  Today it gates the entire frontend UI (and is not actually enforced
  on the backend). After the refactor it gates **party creation
  only**: `true` requires Emby login to create a party, `false` lets
  anyone create one. In both modes the backend itself stays gatekept:
  library browse / select / change-streams require host auth, HLS /
  chat / Socket.IO require a party-bound session.

Added:

- Party-bound session middleware: signed cookie issued by
  `/api/party/<id>/join`, enforced on every party-scoped route and on
  the Socket.IO handshake.
- Host status on the party record (six new fields). Persists across
  short reconnects via the existing `_replace_sid` path.
- `POST /api/party/create` now requires Emby creds and atomically
  creates the party with the requester as host.
- `POST /api/auth/become-host` for spectators to claim host status of
  a party that has none.
- `host_changed`, `host_left`, `host_reclaimed` Socket.IO events so
  clients can re-render the lock state.
- Three-state lock semantics tied to `host_access_token` presence and
  `current_video` state.

Kept:

- `EMBY_URL` env var. Deployment topology, not a credential.
- `/admin` panel, gated by `IsAdministrator`. Now reachable only when
  the host's Emby policy says they are an admin.
- Per-user transcodes, unique `PlaySessionId`s per spectator, drift
  correction, the late-joiner vote, all the existing party UX. Auth
  changes do not affect playback semantics.
- The 5-character party code UX for spectators.

## Threat model

What this fixes:

- Anonymous library / item enumeration. Library endpoints now require
  host auth.
- Anonymous Emby image fetching.
- Anonymous transcode initiation. The server cannot start a transcode
  without a host present.
- HLS stream theft by callers with no party session. The HLS proxy is
  party-bound.
- Anonymous Socket.IO connection. Handshake checks the session.
- Long-lived service password in `.env` on the host.
- Single point of failure if the admin loses their credentials: any
  Emby user can become host of any party they are inside, so
  recovering only requires another account on the same Emby server.

What this does not fix:

- A spectator the host invited behaving badly (kicking, spam, picking
  offensive content). Party-level moderation, not auth.
- Use of a leaked party code by someone the host did not intend to
  invite. The leaker can lurk, chat, watch whatever the host picks,
  and attempt "Become Host" with their own Emby credentials. They
  cannot enumerate the library or start their own transcode without
  being the host.
- An Emby account whose password is shared / weak. That account's
  library is what an attacker who logs in with those credentials
  would see.
- An attacker who can read the host's process memory while a host
  token is loaded.
- DoS via repeated login attempts. Emby's own rate limiting applies.

Party codes remain bearer credentials for spectator access. The
intent is preserved: knowing the code lets you watch, not browse the
catalog. If the host's account is wrong about who they trust, the
mitigation is to close the party and create a new one.

## Open questions

1. **Live host handover during active playback.** When a new host
   logs in while playback is still running under the previous host's
   token, the simplest behaviour is "new host is recorded, but the
   ongoing transcode keeps using the old token until the next natural
   reset (video ends, change-streams, stop)." Cleaner UX would be
   "transition all in-flight HLS pulls to the new token now," but
   Emby pins transcode sessions to the token that started them, so
   the cleaner version requires a new transcode + seek. Punted to a
   follow-up; the simple behaviour is acceptable for the first
   iteration.
2. **Grace window length.** ~5 seconds for the disconnect grace
   before the party transitions to PLAYING-ONLY / LOCKED. Could be
   exposed as runtime config if real-world testing shows refreshes
   take longer.
3. **Party-code entropy.** Codes are 5 uppercase letters. Codes now
   gate spectator access, not library access; the threat is
   "stranger lurks in your party," which is acceptable for the
   intended use case. Length stays as-is unless feedback says
   otherwise.

## Migration notes

For deployments upgrading from beta5 or earlier:

1. Remove `EMBY_USERNAME` and `EMBY_PASSWORD` from `.env`. The
   container will start with no Emby credentials.
2. Decide on `REQUIRE_LOGIN`. Default `false` (anyone can create a
   party, browse still requires Emby auth). Set `true` if you want
   `#31`-style "only Emby account holders can create rooms."
   Configurable from the admin panel after first boot, no restart
   needed.
3. Start the container. No bootstrap login is required at boot.
4. Open the URL.
   - If `REQUIRE_LOGIN=true`: clicking **Create Party** opens an Emby
     login form. Authenticate and the party is created with you as
     host.
   - If `REQUIRE_LOGIN=false`: clicking **Create Party** drops you
     straight into the new party. The library is locked until you
     click **Login to Become Host** and authenticate.
5. Share the party URL with friends/family. They visit, pick a
   display name, join. They do not see an Emby login prompt.
6. To pick a video, browse the library as host. To stop being host
   (you have to leave), close the tab; the library re-locks and
   any spectator with an Emby account can take over.
7. `/admin` requires you to be host of some party AND for your
   Emby policy to say you are an admin. If you do not see the
   admin link after creating a party, your Emby account is not
   flagged as administrator.

Docker compose snippets in `README.md` need their `environment:`
blocks updated to drop `EMBY_USERNAME` and `EMBY_PASSWORD`.
`REQUIRE_LOGIN` stays.
