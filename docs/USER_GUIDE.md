# Emby WatchParty User Guide

This guide explains how to use Emby WatchParty 2.0 from a user's
perspective, including the new late-joiner vote, per-user audio/quality,
and admin panel features.

If you are a developer looking for the Socket.IO event protocol, see
[SOCKET_API.md](SOCKET_API.md) instead.

## Table of contents

- [Creating and joining a party](#creating-and-joining-a-party)
- [Selecting a video](#selecting-a-video)
- [Playback controls](#playback-controls)
- [Changing audio, subtitles, and quality](#changing-audio-subtitles-and-quality)
- [Joining a party that is already watching](#joining-a-party-that-is-already-watching)
- [The vote modal (for existing users)](#the-vote-modal-for-existing-users)
- [The waiting room (for late joiners)](#the-waiting-room-for-late-joiners)
- [Chat and participants](#chat-and-participants)
- [Admin panel](#admin-panel)
- [Troubleshooting](#troubleshooting)

## Creating and joining a party

### Creating a new party

1. Open the WatchParty URL in your browser.
2. Click **Create Party**. You will be redirected to a new party room
   with a 5-character code (e.g. `PRFKE`).
3. Share the URL or the code with your friends. They can enter the code
   on the home page to join.

### Joining an existing party

- **From the home page**: click **Join Party**, enter the code, enter
  your name (or leave it blank for a randomly generated name), and
  click Join.
- **From a shared URL**: click the link you received. You will be asked
  for your name and then dropped into the party.

If there is no video playing yet, you will land directly in the party
room with the library browser open. If a video is already playing, see
[Joining a party that is already watching](#joining-a-party-that-is-already-watching)
below.

## Selecting a video

Any user in the party can pick a video. Click **Browse Library** to
open the sidebar, navigate through your Emby libraries, and click a
movie or episode to start it for the whole party.

The person who selects the video becomes the party's **"selector"**.
This designation matters for two things:

- **Stopping the video**: only the selector can click **Stop Video** to
  end playback for everyone.
- **Tiebreaking late-joiner votes**: if a late-joiner vote ends in a
  tie, the selector's vote decides the outcome (more on this below).

Everything else -- play, pause, seek, chat, audio/quality changes --
can be done by any user.

## Playback controls

When a video is playing, the standard HTML5 video controls are
available: play/pause, scrubber, volume, fullscreen.

- **Play and pause** propagate to every user in the party. If Andrew
  pauses, Harry and Fabio pause too.
- **Seeking** propagates the same way, with a short buffering period
  while all clients load the new position.
- **Drift correction** runs quietly in the background. If one user
  falls behind (e.g. due to a temporary network hiccup), the server
  nudges only their playback forward so they catch up with everyone
  else. Other users are not disturbed.

## Changing audio, subtitles, and quality

Each user can choose their own audio track, subtitle track, and video
quality **independently** from the rest of the party. This is useful
when some users prefer the original audio, others want dubbing, or
someone is on a slow connection.

There are two behaviors depending on whether the party is currently
playing:

### Paused party

If the party is paused (no video playing, or playback is paused),
changing your audio/quality/subtitle is **silent and instant**. Only
your video player reloads with the new stream. Nobody else in the
party is interrupted.

### Playing party

If the party is actively playing, the change happens **silently for
the other users**:

1. You pick a new audio track (or quality, or subtitle).
2. Your video player reloads with the new stream. Other users keep
   playing uninterrupted -- they are not aware of your change.
3. While your stream is buffering, you are briefly paused. The rest
   of the party continues at their normal playback position.
4. Your new stream starts at the party's current position (the server
   factors in the seconds that passed while it set up your new
   transcode), so you land close to where everyone else is.
5. Drift correction handles any residual lag over the next heartbeat
   or two.

You may miss a few seconds of content while the new stream loads.
This trade-off keeps the rest of the party from being interrupted
every time someone fiddles with their settings.

## Joining a party that is already watching

This is the **late-joiner** scenario. It is handled specially because
of a technical constraint:

Emby creates a separate video transcode for each user. When you join a
party mid-playback, Emby starts a fresh transcode at the current
playback position, but it rounds to the nearest keyframe -- and that
keyframe may be several seconds off from where the other users are.
This means the time displayed on your player and on the other users'
players might match numerically but show **different scenes** by up
to 15-20 seconds.

To avoid this visual desync, WatchParty asks the existing users
whether to **restart the video from the beginning** so you can join
in sync. If they accept, everyone restarts together and you all watch
from the first frame. If they decline, you are sent back to the home
page.

## The vote modal (for existing users)

When someone tries to join your party while a video is playing, a
**blocking modal** appears on your screen:

- The modal shows the late joiner's name.
- Two buttons: **Accept** and **Decline**.
- A countdown timer (default 20 seconds).
- A live list of the other eligible voters and their votes.

After you click Accept or Decline, your vote is locked and you watch
the modal update as others cast their votes. The modal dismisses as
soon as the outcome is decided.

### How the vote resolves

- **Strict majority of yes votes**: the vote passes immediately, even
  if not everyone has voted yet. The video restarts from the beginning
  for all users plus the late joiner.
- **Strict majority of no votes**: the vote fails immediately. The
  late joiner is rejected and sent home. Your playback is unaffected.
- **Everyone voted but no strict majority (tie)**: the vote resolves
  immediately using the **selector tiebreak rule** (see below).
- **Timeout (20s by default)**: the selector tiebreak rule is applied.

### Selector tiebreak rule

If the vote is a tie or times out, the person who originally selected
the video casts the deciding vote:

- Selector voted yes → pass
- Selector voted no → fail
- Selector did not vote → fail (default)

### Cooldown after a failed vote

After a failed or cancelled vote, the party enters a **30-second
cooldown** (configurable by the admin). During this window, new join
attempts are rejected immediately. This prevents a malicious user from
repeatedly hitting your party URL to spam vote modals on the rest of
the group.

## The waiting room (for late joiners)

If you try to join a party that is already watching, you will see a
full-screen waiting room:

- A spinner and "Waiting for party approval" message.
- A countdown timer matching the server's vote timeout.
- A live progress indicator showing how many users have voted so far
  (anonymized -- you do not see who voted which way).

### Possible outcomes

- **The vote passes**: the waiting room dismisses and you land in the
  party. The video has restarted from the beginning, and you are
  synchronized with the rest of the party.
- **The vote fails**: you see a short rejection message and are
  redirected back to the home page. You can try joining again later.
- **Another vote is already in progress**: you are rejected
  immediately with a message asking you to try again shortly. This
  happens when two users try to join the same party at the same time.
- **The party is on cooldown**: you are rejected with a message
  telling you how many seconds to wait before retrying.
- **You close the tab**: the vote is cancelled and the 30-second
  cooldown starts. Other users see a "vote cancelled" message and
  return to their video.

## Chat and participants

- **Chat**: type a message in the chat box at the bottom and press
  Enter. Everyone in the party sees it. Playback actions (play, pause,
  seek, stream change) are also announced in chat with the user's name.
- **Participants**: click the participants panel to see who is
  currently in the party.

## Admin panel

The admin panel is available at `/admin` (append `/admin` to your
WatchParty URL). It requires Emby administrator credentials.

Every runtime setting except the boot-essential ones (listed in
`.env.example`) can be changed from the admin panel without a server
restart.

### Sections

- **Logging**: log level (DEBUG/INFO/WARNING/ERROR), console vs file,
  log file path, log format, max file size.
- **Security**: max users per party, HLS token validation, HLS token
  expiry, rate limiting, per-IP party creation limit, per-IP API call
  limit.
- **Session**: static session mode (auto-create a fixed party ID on
  startup, useful for single-party deployments).
- **Late Join Vote**: enable/disable the vote feature, vote timeout
  (seconds), post-vote cooldown (seconds). Set the cooldown to 0 to
  disable the anti-spam cooldown.

### Settings that require a restart

These are defined in `.env` (not editable via admin panel):

- `WATCH_PARTY_BIND`, `WATCH_PARTY_PORT`, `APP_PREFIX`
- `SESSION_EXPIRY`
- `EMBY_SERVER_URL`, `EMBY_API_KEY`

Changing any of these requires editing `.env` and restarting the
service. `REQUIRE_LOGIN` and everything else is hot-reloadable via the
admin panel.

## Troubleshooting

### I joined a party but the waiting room never goes away

The vote may be stuck because an existing user is idle or
unresponsive. The watchdog will fire after the vote timeout (20s by
default) and apply the selector tiebreak rule. If that does not
resolve it, ask an existing user to vote explicitly.

### I was the late joiner and got "cooldown" errors

A recent vote failed or was cancelled in that party, and the party is
in a 30-second cooldown to prevent spam. Wait the number of seconds
shown in the error message and try again.

### I changed my audio track and the video jumped back a few seconds

Expected behavior. When the party is playing and you change streams,
everyone pauses briefly while your new stream buffers. The video then
resumes from the same position -- but HLS.js may re-decode a few
frames before catching up. Changing streams while paused avoids this.

### My video is out of sync with others

- If you just joined, wait a few seconds for drift correction to
  catch you up.
- If you just changed quality or audio, the ready-check dance should
  have kept you in sync -- if it did not, press pause and play again
  to manually re-sync.
- If you are still out of sync, check your network. A slow connection
  causes buffering lag that drift correction will try to fix
  automatically.

### I get "Join rejected: another user is currently waiting for approval"

Another late joiner is voting right now. Only one vote can run at a
time. Wait for the current vote to finish and try again.

### The vote modal is blocking my screen and I cannot dismiss it

That is intentional -- the modal is blocking until you vote or the
timeout expires. Click **Accept** or **Decline** to dismiss it.
