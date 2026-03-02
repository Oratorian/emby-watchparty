// state.js - Shared state container for all party modules
(function() {
    'use strict';

    // Derive party ID from URL
    var pathParts = window.location.pathname.split('/').filter(function(p) { return p; });
    var partyId = pathParts[pathParts.length - 1];

    // App prefix (set by template, defaults to empty string)
    var appPrefix = (typeof APP_PREFIX !== 'undefined') ? APP_PREFIX : '';

    // Initialize Socket.IO with custom path if prefix is set
    var socketPath = (typeof SOCKETIO_PATH !== 'undefined' && SOCKETIO_PATH) ? SOCKETIO_PATH : '/socket.io';
    var socket = io({ path: socketPath });

    window.PartyState = {
        // Configuration (read-only after init)
        partyId: partyId,
        appPrefix: appPrefix,
        socket: socket,

        // User state
        username: '',
        currentUsers: [],
        isHost: false,

        // Sync state
        isSyncing: false,
        syncThreshold: 0.3,
        lastPlayBroadcast: 0,
        lastPauseBroadcast: 0,
        playPauseThrottle: 300,
        lastSyncedTime: 0,
        lastSyncType: '',
        isUserSeeking: false,
        seekSettleTimer: null,

        // Video / stream state
        hls: null,
        currentItemId: null,
        currentMediaSourceId: null,
        availableStreams: { audio: [], subtitles: [] },
        canStopVideo: false,
        progressReportInterval: null,
        currentPartyState: null,
        introData: null,
        introCheckInterval: null,

        // Autoplay state
        autoplayEnabled: true,
        currentEpisodeList: [],
        currentEpisodeIndex: -1,
        currentSeasonId: null,
        currentSeriesId: null,
        currentSeriesName: null,
        autoplayCountdownTimer: null,
        autoplayTimeoutId: null,
        videoSelectedBy: null,

        // Library state
        LIBRARY_STATE_KEY: 'emby-watchparty-library-state',
        searchTimeout: null,

        // DOM element cache (populated by party.js orchestrator before module inits)
        dom: {}
    };
})();
