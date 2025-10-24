# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
