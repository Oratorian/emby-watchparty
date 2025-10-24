# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-10-25

### Added
- **Skip Intro Button**: Interactive button to skip intro sequences
  - Appears when intro markers are detected in Emby metadata
  - Positioned above video controls for easy access
  - Automatically shows/hides based on current playback position
  - Only works in normal viewing mode (limitation: not visible in fullscreen due to HTML5 video fullscreen constraints)
  - Synced across all party members when clicked
  - **Note:** Requires Emby API key to be configured for intro marker detection

- **Intelligent PGS Subtitle Handling**: Smart detection and burn-in for image-based subtitles
  - Automatically detects PGS (Presentation Graphic Stream) subtitles
  - Burns in PGS/VobSub/DVD subtitles for pixel-perfect quality
  - Supports: pgssub, pgs, dvd_subtitle, dvdsub, vobsub formats
  - Prevents quality loss from PGS-to-text conversion
  - Works on both GPU and software encoding setups
  - PGS subtitles marked with [Burned-in] indicator in dropdown

- **Independent VTT Subtitle Selection**: Per-user subtitle language choice
  - All text-based subtitles automatically loaded as WebVTT tracks
  - Each party member can independently choose their subtitle language
  - Uses native browser CC button for subtitle selection
  - No transcode restarts needed for VTT subtitle changes
  - Subtitle dropdown automatically hides when only VTT subtitles available
  - PGS subtitles remain synced (burned-in), VTT selection is local-only

### Changed
- **Subtitle Workflow**: Dual-mode subtitle handling
  - PGS subtitles: Server-side burn-in with `SubtitleMethod=Encode` (synced for all users)
  - Text subtitles: Client-side VTT loading with independent selection (local per user)
  - Subtitle dropdown now only shows PGS options when available
  - Audio selection remains synced across all party members (requires transcode)

- **Multi-Audio Track Support**: Re-enabled audio track selection
  - Added back `AudioStreamIndex` parameter for proper audio track selection
  - Users can now switch between multiple audio tracks (e.g., different languages)
  - Audio track changes are synced across all party members
  - Fixes issue where only default audio track was available

- **Sync Architecture Overhaul**: Removed periodic sync workaround
  - Disabled 5-second periodic sync check (added in v1.0.5, no longer needed)
  - Server now calculates accurate current time for new joiners
  - Client compensates for network and loading delays
  - Sync accuracy improved from ±4 seconds to sub-second precision
  - Simpler, more reliable sync mechanism

### Fixed
- **Mid-Play Join Sync Issues**: Complete overhaul of new joiner sync behavior
  - Fixed video restarting to 0:00 for existing users when someone joins
  - New joiners now start at correct position (e.g., 22 minutes, not 0:00)
  - New joiners can immediately receive play/pause/seek commands
  - Set isSyncing flag before loadVideo() to prevent MANIFEST_PARSED reset
  - Use HLS.js startPosition config to load correct video segments immediately
  - Clear isSyncing in MANIFEST_PARSED to allow command processing
  - Server calculates elapsed time since last play/pause/seek for accurate sync
  - Client compensates for network + metadata loading delay (0.1-0.5s typical)
  - Loading delay compensation capped at 2 seconds to prevent over-compensation

- **False Drift Detection**: Eliminated random seeking and desyncing
  - Periodic sync was detecting false "drift" after pause/play
  - Example: Pause at 496s, play again → periodic sync thought 5s drift existed
  - Removed periodic sync - play/pause/seek events provide sufficient sync
  - No more random video forwarding or seeking
  - Pause/play now works smoothly without desyncing users

- **Subtitle Filtering and Sync Issues**: Resolved subtitle-related sync loop bug
  - Fixed issue where mid-play joiners caused sync loops
  - Improved subtitle stream filtering logic
  - Better handling of default/forced subtitle selection
  - Removed invalid `SubtitleMethod=Drop` parameter (doesn't exist in Emby API)
  - Fixed PGS subtitles appearing by default when "None" selected
  - Omit subtitle parameters entirely when None selected to prevent Emby auto-selection

- **UI Layout Issues**: Fixed spacing and layout problems
  - Clear all subtitle tracks from video element when changing videos (prevents CC button clutter)
  - Fixed Stop Video button stretching with `flex: 0 0 auto`
  - Changed subtitle container visibility from `display` to `visibility` toggle
  - Prevents Audio and Stop Video button from squishing together
  - Added max-width to stream controls for consistent spacing
  - Proper button positioning with `.stop-button-group` class

### Technical
- **Server-Side (app.py):**
  - Calculate accurate current time when new user joins (handle_join_party)
  - Add elapsed time since last_update to playback_state.time for playing videos
  - Send compensated time to new joiners: `current_time = stored_time + elapsed`
  - Added debug logging for new joiner sync calculations

- **Client-Side (party.js):**
  - Capture sync_state arrival time for delay compensation
  - Set playbackStartTime when new joiner starts playing
  - Disabled periodic sync (removed from play handler and sync_state handler)
  - Improved periodic sync guards (check both party state and video state)
  - Enhanced subtitle stream detection with `isPGS` flag
  - Automatic text track cleanup in `loadAllTextSubtitles()` function
  - Modified subtitle dropdown event listener to only emit party sync for PGS subtitles

- **Code Cleanup:**
  - Removed 3 unused variables (lastSyncTime, lastSeekBroadcast, seekBroadcastDelay)
  - Removed empty socket.on('connected') handler
  - Removed 12 development console.log statements
  - Reduced party.js from 1493 to 1459 lines (34 lines saved)
  - Fixed syntax error (extra closing brace in subtitle change handler)

## [1.0.6] - 2025-10-24

### Fixed
- **Critical Audio Fix**: Videos now play with audio correctly
  - Added `AudioCodec=aac,mp3` parameter to force compatible audio transcoding
  - Added `TranscodingMaxAudioChannels=2` and `MaxAudioChannels=2` to ensure audio inclusion
  - Removed `AudioStreamIndex` parameter that was causing Emby to strip audio
  - Fixes issue where videos with FLAC or other lossless audio codecs had no sound
  - **Dolby TrueHD support**: Now properly downmixes and transcodes to stereo AAC/MP3
  - HLS streams now properly transcode audio to browser-compatible formats

- **Video Looping Fix**: Videos no longer loop after 2-4 seconds
  - Added `BreakOnNonKeyFrames=True` to allow proper HLS segment generation
  - Added `VideoCodec=h264` to ensure maximum browser compatibility
  - Fixes issue where videos would play 2-4 seconds then restart
  - Works with both HEVC (H.265) and AVC (H.264) source videos

### Changed
- **Unified Transcoding Profile**: All clients receive same quality stream
  - Video: H.264 (maximum compatibility, works on all browsers)
  - Audio: AAC or MP3 (handles FLAC, TrueHD, DTS, AC3, etc.)
  - Channels: Downmixed to stereo (2.0) from any multi-channel format
  - Single transcode per party = better performance and perfect sync

- **Enhanced HLS Parameters**:
  - `AudioCodec=aac,mp3` - Supports both AAC and MP3 fallback
  - `VideoCodec=h264` - Force H.264 for universal browser support
  - `BreakOnNonKeyFrames=True` - Allow seeking to any point in video
  - `MaxAudioChannels=2` - Downmix surround sound to stereo

### Technical
- Modified HLS URL generation in `select_video` and `change_streams` handlers
- Added debug logging for HLS master playlist content
- Enhanced audio stream handling to prevent transcoding issues
- Optimized for "lowest common denominator" approach (single transcode for all clients)

## [1.0.5] - 2025-10-23

### Added
- **Periodic Sync Check**: Automatic drift correction every 5 seconds
  - New `startPeriodicSync()` function monitors playback timing
  - Automatically corrects sync drift greater than 0.3 seconds
  - Only syncs during active playback (skips when paused or seeking)
  - Stops when video is stopped to conserve resources
- **Browser Compatibility Documentation**: Added detailed browser support section to README
  - Desktop browser compatibility (Chrome, Edge, Firefox, Safari, Brave)
  - Mobile browser compatibility with specific iOS/Android recommendations
  - Known issues section for Brave iOS subtitle limitation

### Changed
- **Improved Invite Codes**: Simplified party code format for easier communication
  - Changed from 10-12 character URL-safe tokens to simple 5-character codes
  - Uses uppercase letters and numbers only (A-Z, 2-9)
  - Excludes confusing characters (0, O, 1, I, L) for clarity
  - Examples: `A3B7K`, `N2YS2`, `Y5HYP` instead of `abc123XyZ9aBc1`
  - Much easier to communicate over phone or in person
- **Tighter Sync Threshold**: Reduced from 0.5s to 0.3s for better accuracy
  - Fixed misleading comment (was "2 seconds" but code was 0.5s)
  - More accurate synchronization between players
  - Reduces typical sync offset from ~4 seconds to under 0.3 seconds
- **Better Browser Reload Handling**: Improved sync behavior when users refresh
  - Changed condition from `time > 1` to `time >= 0`
  - Now syncs correctly at any video timestamp, including beginning
  - Starts periodic sync check immediately after reload

### Fixed
- **Sync Timing Issues**: Addressed offset between players after seeking or reloading
  - Periodic sync check prevents drift accumulation over time
  - Browser reloads now sync correctly regardless of video position
  - Seeking and leaving/reloading no longer causes 4-second desync
- **State Tracking**: Enhanced playback state management
  - Added `currentPartyState` variable to track server's authoritative state
  - Updated on every play/pause/seek event from server
  - Used by periodic sync to detect and correct drift

### Documentation
- Added browser compatibility matrix for desktop and mobile
- Added known issues section for Brave iOS subtitle limitation
- Documented recommended browsers for different platforms
- Updated party code format in features list

## [1.0.4] - 2025-10-22

### Added
- **External Subtitle Support**: Major improvement to subtitle handling
  - New subtitle proxy endpoint `/api/subtitles/<item_id>/<media_source_id>/<index>` for serving WebVTT files
  - HTML5 `<track>` element integration for native browser subtitle rendering
  - `loadSubtitleTrack()` function for dynamic subtitle loading in frontend
  - `isTextSubtitleStream` flag in streams API response
  - `media_source_id` tracking across video selection and stream changes
- **Transcoding Cleanup**: Automatic cleanup of Emby HLS transcoding sessions
  - `stop_active_encodings()` method in EmbyClient
  - Calls DELETE `/Videos/ActiveEncodings` when video stops or changes
  - Prevents abandoned transcoding processes from consuming server resources

### Changed
- **Subtitle Delivery Method**: Switched from burned-in to external subtitles
  - Removed `SubtitleMethod` parameter from HLS URLs
  - Subtitles now load as separate WebVTT files instead of being encoded into video
  - Enables instant subtitle switching without video reload
- **UI Layout Redesign**: Compact video controls layout
  - Video description and stream controls now displayed side-by-side
  - Audio, Subtitles, and Stop Video button placed in single horizontal row
  - Video description reduced to 2-line clamp for space efficiency
  - Added invisible label to Stop Video button for proper vertical alignment
  - Improved responsive flex layout for stream controls

### Fixed
- **Subtitle Timeout Issues**: Resolved 502 Bad Gateway errors on complex subtitle files
  - Complex ASS/SSA subtitle files (e.g., "The Apothecary Diaries") no longer cause timeouts
  - Emby no longer forced to burn subtitles into video stream during transcoding
  - Significantly reduced CPU load during playback with subtitles
- **Resource Management**: Proper cleanup of server resources
  - HLS transcoding sessions now properly terminated when playback ends
  - Prevents memory and CPU waste from abandoned encoding processes

### Technical
- Frontend subtitle track management with proper cleanup and replacement
- Media source ID propagation through `video_selected`, `streams_changed`, and `sync_state` events
- Enhanced stream metadata with text subtitle stream detection

## [1.0.3] - 2025-10-21

### Added
- **Stop Video Button**: Allows the user who selected a video to stop it for all party members
  - Only visible to the video selector
  - Clears video player for all users
  - Backend validates only the selector can stop the video
- **HLS Token Validation System**: New security layer for HLS stream access
  - Per-user HLS tokens tied to socket session IDs
  - Token expiry tracking and automatic cleanup
  - Each user gets their own unique token for stream access
  - Prevents direct stream access bypass
- **Comprehensive Debug Logging**: Enhanced debugging capabilities
  - Detailed debug logs for token generation and validation
  - Playlist URL rewriting visibility
  - Token assignment tracking per user
  - Comprehensive error reporting with full context (error type, URLs, tracebacks)
  - Separate error handling for network errors vs internal errors
- **Configuration Template**: Added `config.py.example` for easier setup
  - `config.py` is now untracked to prevent committing credentials
  - Users copy `config.py.example` to `config.py` and configure

### Changed
- **Library Sidebar Behavior**: Improved UI consistency
  - Library sidebar now hides for ALL users when video is selected (not just selector)
  - Library sidebar automatically reopens when video is stopped
  - Consistent UI state across all party members
- **Rate Limiting**: Increased default API rate limit to 1000 requests/minute (from 100)

### Fixed
- Token URL parameter construction now uses proper separator detection (& vs ?)
- Tokens correctly appended to ALL playlist types including `main.m3u8`

### Security
- Per-user HLS tokens with session validation
- Token expiry tracking and cleanup
- Rate limiting configuration improvements
- Tokens properly tied to socket session IDs for validation

## [1.0.2] - 2025-10-20

### Fixed
- Clean up chat system messages and fix username display
  - Remove verbose system messages (track counts, HLS ready, video loaded)
  - Change message format from "selected:" to "selected" for cleaner display
  - Fix username variable not being set when server generates random username
  - Keep only essential messages: user selections and critical errors
  - Auto-capture username from server on join event

### Changed
- Chat only shows relevant user actions instead of technical status updates

## [1.0.1] - 2025-10-20

### Added
- **Secure HLS Proxy**: Major security improvement
  - Implement lightweight HLS proxy endpoints for master playlists and segments
  - Add URL rewriting to redirect playlist requests through Flask proxy
  - Only Flask app needs to be exposed, Emby stays on local network
  - Security improvement: Emby server no longer needs internet exposure

### Fixed
- Fixed syntax error in `party.js:529` (extra closing brace, missing `)`)

### Documentation
- Updated README with note about Emby remote access no longer being required
- Clarified that only the Flask app needs to be exposed to the internet

## [1.0.0] - 2025-10-20

### Added
- **Initial Release**: First public version of Emby Watch Party
- **Core Features**:
  - Create and join watch parties with shareable party codes
  - Synchronized video playback across all party members
  - Real-time chat functionality
  - Video library browsing and search
  - Season and episode selection for TV shows
  - Audio and subtitle track selection
  - Automatic playback synchronization
  - Random username generation for guests
- **Media Server Integration**:
  - Direct integration with Emby media server
  - HLS streaming support with quality selection
  - Support for movies and TV shows
  - Direct transcoding through Emby
- **User Interface**:
  - Clean, modern web interface
  - Responsive design for desktop and mobile
  - Library sidebar with search
  - Video player with full controls
  - Chat panel with drag-to-resize
  - System messages for user actions
- **Technical Features**:
  - Flask backend with Socket.IO for real-time communication
  - HLS.js for adaptive bitrate streaming
  - Session-based party management
  - Custom logging system with rotation
  - Environment variable configuration

### Documentation
- Comprehensive README with setup instructions
- Installation guide with dependencies
- Configuration documentation
- Development setup instructions

---

## Version History Summary

- **v1.0.6** (2025-10-24): Critical audio fix - videos now play with sound
- **v1.0.5** (2025-10-23): Simplified invite codes, improved sync timing, browser compatibility docs
- **v1.0.4** (2025-10-22): External subtitle support, transcoding cleanup, UI layout improvements
- **v1.0.3** (2025-10-21): Stop video feature, HLS token validation, enhanced debugging
- **v1.0.2** (2025-10-20): Chat cleanup and username fixes
- **v1.0.1** (2025-10-20): Secure HLS proxy, Emby stays internal
- **v1.0.0** (2025-10-20): Initial release with core watch party features

---

## Links

- **Repository**: https://github.com/Oratorian/emby-watchparty
- **Issues**: https://github.com/Oratorian/emby-watchparty/issues
- **Releases**: https://github.com/Oratorian/emby-watchparty/releases

---

## Educational Use Notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
