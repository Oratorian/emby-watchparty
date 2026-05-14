# Avatar System — Implementation Notes

## Status
**MVP shipped** (issue [#36](https://github.com/Oratorian/emby-watchparty/issues/36)). The flow below describes what is live in 2.0-Rework. Deferred items are listed at the bottom.

## Concept
Passwordless avatar persistence. No login, no cookies. UUID in IndexedDB (with localStorage fallback) for same-browser auto-recognition; shareable three-word code for cross-device recovery.

## Flow
1. User uploads avatar OR enters email for Gravatar
2. Backend: generate UUID + memorable code (e.g. `oceans-11-strikeagain`)
3. Store hash(code) server-side, return `{ uuid, code }` to client
4. Client saves uuid in IndexedDB, displays code prominently ("save this!")
5. Return visit: read uuid from IndexedDB → auto-load avatar
6. New device: "I have a code" → hash & lookup → restore uuid to IndexedDB

## Data shape
```json
{
  "uuid": {
    "type": "uploaded | gravatar",
    "code_hash": "argon2/bcrypt hash",
    "avatar_path": "avatars/uuid.jpg",
    "gravatar_hash": "sha256(email)",
    "created_at": "ISO timestamp",
    "last_seen": "ISO timestamp"
  }
}
```
- `avatar_path` → uploaded only
- `gravatar_hash` → gravatar only

## Must-dos
- **Hash the code** before storing (treat like a password)
- **Never expose code or uuid in avatar URL** — serve by internal id
- **Bump `last_seen`** on every recognized visit (so active users survive cleanup)
- **Rate-limit code entry** (brute-force protection)
- **Show code multiple times** — at upload, in a "your account" UI corner
- **Cleanup job**: delete entries where `last_seen` > 30 days, plus orphaned avatar files

## Gotchas
- Safari ITP wipes IndexedDB after 7 days of no interaction → users hit code prompt more often
- Flat JSON file = concurrent-write risk; move to SQLite if it grows
- Gravatar: SHA-256 of lowercased+trimmed email; decide fallback (`d=identicon` or `d=404`)
- Code collisions: use enough entropy (3-4 words from large list) or check on generation

## Render precedence (host model)

When a host is present in a party AND they have not set their own avatar via the modal, their member row falls through to `GET /api/avatar/host/{party_id}` which proxies the host's Emby Primary image using the stored host token. Stored avatars (uploaded / gravatar) always win.

```
1. party.members[name] -> /api/avatar/{uuid}      (stored avatar)
2. name == auth.hostUsername -> /api/avatar/host/{party_id}  (Emby Primary)
3. fallbackAvatarUrl(name) -> Gravatar monsterid    (deterministic default)
```

## Deferred (next pass)

- **Auto-linking via emby_user_id.** The `emby_user_id` column exists in the schema and `link_emby_user()` / `find_by_emby_user()` are implemented, but the auth router does not yet wire them on become-host. The intent: when a host logs in on a fresh browser, the backend recovers their stored avatar uuid from their Emby identity, no recovery-code prompt needed.
- **Cleanup job.** Entries with `last_seen` older than 30 days and orphaned image files should be pruned. Currently no scheduled task -- rows accumulate indefinitely.
- **Slowapi-backed rate limit on `/recover`.** Today's limiter is an in-memory dict (10/hour/IP). Once the project's general rate limiter is wired we should switch.

## Open questions

- Allow switching type (uploaded ↔ gravatar) on same uuid? Currently each create allocates a fresh uuid; switching means re-saving the recovery code. Considered acceptable for MVP.
- What's shown when a Gravatar email has no registered avatar? Backend serves identicon via `?d=identicon`. Configurable later if needed.
