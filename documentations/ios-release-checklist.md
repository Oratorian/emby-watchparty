# iPhone and iPad Safari release checklist

Run this checklist on the oldest supported iPhone and one current iPad before release. Test portrait and landscape on a production-like HTTPS deployment with a real Emby server.

- Join an existing party from a fresh private Safari tab; confirm participant count and avatar.
- Select media and confirm native HLS starts after the expected iOS user gesture.
- Confirm an autoplay rejection shows a readable prompt and tapping the video resumes playback.
- Play, pause, drag the native seek control, and use timestamp/relative seek controls; verify another client stays synchronized.
- Rotate portrait to landscape and back; verify video, chat, controls, and safe-area padding remain usable around the notch and home indicator.
- Background Safari for at least 30 seconds, foreground it, and verify membership, current stream, position, and play/pause state recover.
- Disable and restore Wi-Fi; verify the reconnecting banner appears, clears, and membership/stream restore without a vote.
- Send and receive chat messages with the software keyboard open; verify the composer and send control remain visible.
- Change audio, text subtitles, quality, and per-user stream settings; verify another viewer's stream selection does not change.
- Repeat join, playback, seeking, rotation, background/foreground, chat, and reconnect on iPad Safari in split-screen and full-screen.

Automated Chromium and iPhone WebKit flows must be green before starting this checklist. Record device, iOS/iPadOS version, Safari version, deployment version, and pass/fail notes in the release ticket.
