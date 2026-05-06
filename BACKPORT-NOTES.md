# Backport Notes: 1.6.x → 2.0

Tracking which 1.6.x patches have been ported to 2.0 and what's left.
2.0 is structurally a port of 1.6.x onto FastAPI + Vue 3 with per-user
transcodes, so most fixes apply conceptually but may need adaptation
for the new transport layer or reactive frontend.

**Port status legend:**
- ✅ Done — backend or frontend equivalent is in place
- 🚧 Partial — some pieces ported, others pending
- ⏳ Pending — needs porting
- ⚠️ Reimagine — direct port doesn't apply; needs 2.0-native solution
- ❌ N/A — irrelevant to 2.0's architecture

---

## 1.6.3 — `EnableAutoStreamCopy=false` and PlaybackInfo parity

Already ported in this branch. Reference commit on `2.0-Rework`:
"Erweitere die get_playback_info-Methode um zusätzliche Parameter…"

### Backend

| Item | Status | Notes |
|---|---|---|
| `EnableAutoStreamCopy=false` on HLS URL | ✅ Done | `backend/src/stream_builder.py` |
| `MinSegments=1` | ✅ Done | Same |
| `h264-profile`, `h264-level`, `TranscodeReasons` | ✅ Done | Same |
| Manifest subtitle params (`SubtitleMethod=Hls`, `ManifestSubtitles=vtt`, `SubtitleStreamIndexes`) | ⚠️ See 1.6.6 | These were ported but **need to be removed again** — see 1.6.6 below. The 1.6.6 fix supersedes the 1.6.3 manifest-subs decision. |
| `IsPlayback=true`, `AutoOpenLiveStream=true` on PlaybackInfo | ✅ Done | `backend/src/emby_client.py` |
| `MaxStreamingBitrate` on PlaybackInfo | ✅ Done | Same |
| `AudioStreamIndex` / `SubtitleStreamIndex` / `MediaSourceId` / `StartTimeTicks` on PlaybackInfo | ✅ Done | Same |

### Frontend

Nothing — 1.6.3 was purely a backend transcode-decision change.

---

## 1.6.4 — Selector role survives reconnects (issue #28)

### Backend

| Item | Status | Notes |
|---|---|---|
| Track `selected_by_username` alongside `selected_by` (sid) | ⏳ Pending | In 1.x: `src/socket_handlers/playback.py` — when storing `current_video`, also save the selector's username. Apply same to whatever creates `current_video` in 2.0 (search for `selected_by`). |
| Reclaim selector on rejoin if username matches and old sid is orphaned | ⏳ Pending | In 1.x: `src/socket_handlers/party.py` — `join_party` handler. After adding the rejoining user, check if `current_video.selected_by` points at a sid not in `users`, and if `current_video.selected_by_username` matches the joining username, transfer the role. |
| Update existing fast-refresh eviction path to also update `selected_by_username` | ⏳ Pending | Same file. The eviction branch already transfers the sid; just add the username transfer for consistency. |

### Frontend

Nothing — 1.6.4 was purely backend logic. No UI implications.

### Risk: low

Pure backend change with no architectural overlap with 2.0's per-user transcodes or vote flow. Should port cleanly.

---

## 1.6.5 — PGS subtitles + Skip Intro 403 (issue #29)

### Backend

| Item | Status | Notes |
|---|---|---|
| Restructure subtitle URL builder to compute plan once, emit one consistent set of params | 🚧 Partial | `backend/src/stream_builder.py` already has the structure as of the 1.6.3 port. **But:** the 1.6.5 restructure is more thorough — image-sub indexes filtered out of `SubtitleStreamIndexes`, exactly one `SubtitleMethod` per URL. Diff against `src/socket_handlers/quality.py` from 1.6.5+ to confirm parity. |
| `/api/intro/<id>` route uses `config.EMBY_API_KEY` directly, not `emby_client.api_key` | ⏳ Pending | In 1.x: `src/routes/media.py`. After username/password auth, `emby_client.api_key` becomes the user AccessToken which is rejected by admin-only endpoints (HTTP 403). Use the persistent admin key from config. Apply same fix to whatever `/api/intro/...` route exists in 2.0's `backend/src/routers/`. |

### Frontend

| Item | Status | Notes |
|---|---|---|
| PGS dropdown selection triggers stream restart with `SubtitleMethod=Encode` | ⏳ Pending — verify | In 1.x: `static/js/video.js` PGS path emits `change_streams` with the PGS subtitle index. 2.0's `change_streams` flow is per-user transcode, so this should naturally Just Work — but verify the PGS code path in the Vue subtitle component still uses the dropdown-based selection for image subs and not the manifest path. |

### Risk: medium

The intro 403 fix is a one-line route change, low risk. The subtitle URL builder may already be correct as of the 1.6.3 port — needs a careful diff. The PGS frontend path is conceptually preserved but worth verifying in Vue components.

---

## 1.6.6 — CC button switching + subtitle 401 + label clarity

### Backend

| Item | Status | Notes |
|---|---|---|
| **Remove manifest text subtitle params** (`SubtitleMethod=Hls`, `ManifestSubtitles=vtt`, `SubtitleStreamIndexes` for text subs) | ✅ Done | `backend/src/stream_builder.py`. Removed the unconditional manifest text-sub params and the `subtitle_indexes` collection. `SubtitleStreamIndex` is now only emitted when an image sub is selected (paired with `SubtitleMethod=Encode`). Text subs are handled exclusively by the side-channel proxy. |
| Token injection in `#EXT-X-MEDIA URI="..."` attributes in HLS proxy | ⏳ Pending | In 1.x: `src/routes/hls.py`. Even though manifest text-subs are off, the URI-attribute token injection is a safety net in case the path is reactivated. Apply to 2.0's `backend/src/routers/hls.py`. |
| Broaden plain-URL token injection to any non-comment line (cover `.vtt`, `.srt`, `.ass`) | ⏳ Pending | Same file. Drop the extension allowlist, append token to any non-comment, non-empty line that doesn't already have `token=`. |

### Frontend

| Item | Status | Notes |
|---|---|---|
| CC menu label includes Title field plus `[Forced]` and `[External]` markers | ✅ Done | `frontend/src/views/PartyView.vue` auto-load watcher. Combines `displayLanguage`, `title`, `isForced`, `isExternal` into the `<track>` label. Multi-variant releases now show distinct CC menu entries. |
| Side-channel `<track>` ownership of all text subtitles (no manifest-managed text tracks) | ✅ Done | The architectural conflict was real in 2.0, not just hypothetical -- 2.0 inherited `SubtitleMethod=Hls` + `ManifestSubtitles=vtt` from the 1.6.3 port, plus NewBlade's `bcafaa6` had wired the dropdown to wipe-and-replace `<track>` elements. Resolved as a pair: backend manifest text-sub params removed (commit above), frontend `onChangeTextSubtitle` rewritten to find the preloaded `<track>` by URL and toggle `textTrack.mode` instead of wiping the set. The dropdown and the CC button now perform identical operations on the same preloaded tracks, eliminating the conflict. |
| Auto-load clears stale tracks on video change | ✅ Done | New in 2.0 (not a 1.x port). The auto-load watcher previously appended without clearing, so re-firing the watcher on a `currentVideo` reference change would duplicate every track in the CC menu. Fixed by clearing `<track>` elements at the start of each run. |

### Risk: high (frontend), low (backend)

The backend changes are pure deletions and HLS-proxy regex additions — apply mechanically. The frontend changes need real thought because Vue 3's reactivity model is fundamentally different from `static/js/video.js`'s imperative DOM manipulation. The bug being fixed (CC button "no captions" after switching from external to embedded) is browser-textTracks-specific behavior that may or may not reproduce in Vue's component lifecycle.

**Suggested approach:**

1. Port the backend deletions and HLS proxy changes first.
2. Spin up 2.0 with a multi-subtitle test file (one with both embedded and external SRT).
3. Test the CC button switching scenarios (embedded → external, external → embedded).
4. Only if the bug reproduces, port the frontend single-source-of-truth fix.
5. If it doesn't reproduce, document why in this file and skip the frontend port.

---

## Post-port verification checklist

After porting all of the above, run these test cases on 2.0:

### Backend ports (1.6.3, 1.6.4, 1.6.5 backend, 1.6.6 backend)

- [ ] HLS URL contains `EnableAutoStreamCopy=false` for every video
- [ ] HLS URL has exactly one `SubtitleMethod=` value (Encode for PGS, none for text)
- [ ] HLS URL has no `ManifestSubtitles=vtt` after 1.6.6 port
- [ ] Selector reconnect: drop network, rejoin, pause/seek still works
- [ ] Skip intro: button appears on items with intro data, no 403 in server logs
- [ ] HLS subtitle segment requests include `&token=` parameter (check server logs)

### Frontend ports (1.6.5 verify, 1.6.6 reimagine if needed)

- [ ] PGS subtitles burn in correctly via dropdown
- [ ] CC button shows external SRT alone — works
- [ ] CC button shows embedded sub alone — works
- [ ] CC button shows both, switch external → embedded — works
- [ ] CC button shows both, switch embedded → external — works
- [ ] CC menu shows distinct labels for `English (Signs & Songs)` vs `English (Full)` etc.

---

## Notes for future patches

When the next 1.6.x bugfix lands and needs porting:

1. Add a new section above with the version number and bug summary
2. Split into Backend / Frontend tables
3. Mark each item with ✅ / 🚧 / ⏳ / ⚠️ / ❌
4. Include 1.x file paths so the reference is fast to find
5. Flag risk level so future-you knows whether to port mechanically or carefully

The **⚠️ Reimagine** category is the important one. Direct ports from 1.x's vanilla JS frontend to 2.0's Vue 3 frontend are usually wrong even when they look right, because reactivity and imperative DOM are different paradigms. When in doubt, port the *conceptual* fix and re-test.
