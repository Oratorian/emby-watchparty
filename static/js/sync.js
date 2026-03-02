// sync.js - Playback synchronization module
(function() {
    'use strict';
    var S = window.PartyState;

    function processSyncCommand(command) {
        var timeDiff = Math.abs(S.dom.videoElement.currentTime - command.time);
        var needsSeek = timeDiff > S.syncThreshold;

        if (command.type === 'play') {
            handlePlaySync(command.time, needsSeek, timeDiff);
        } else if (command.type === 'pause') {
            handlePauseSync(command.time, needsSeek, timeDiff);
        } else if (command.type === 'seek') {
            handleSeekSync(command.time, command.playing || false, command.buffer_delay || 500);
        }
    }

    function handlePlaySync(targetTime, needsSeek, timeDiff) {
        var ve = S.dom.videoElement;
        if (needsSeek) {
            S.isSyncing = true;
            ve.currentTime = targetTime;
            ve.play().then(function() {
                setTimeout(function() { S.isSyncing = false; }, 500);
            }).catch(function() {
                setTimeout(function() { S.isSyncing = false; }, 500);
            });
        } else {
            S.isSyncing = true;
            ve.play().then(function() {
                setTimeout(function() { S.isSyncing = false; }, 300);
            }).catch(function() {
                setTimeout(function() { S.isSyncing = false; }, 300);
            });
        }
    }

    function handlePauseSync(targetTime, needsSeek, timeDiff) {
        var ve = S.dom.videoElement;
        if (needsSeek) {
            S.isSyncing = true;
            ve.currentTime = targetTime;
            ve.pause();
            setTimeout(function() { S.isSyncing = false; }, 500);
        } else {
            S.isSyncing = true;
            ve.pause();
            setTimeout(function() { S.isSyncing = false; }, 300);
        }
    }

    function handleSeekSync(targetTime, shouldPlay, bufferDelay) {
        var ve = S.dom.videoElement;
        S.isSyncing = true;

        // Pause first to prevent buffering issues
        ve.pause();

        // Seek to the target time
        ve.currentTime = targetTime;

        // If video should be playing after seek, wait for segments to load
        if (shouldPlay) {
            ve.addEventListener('seeked', function onSeeked() {
                setTimeout(function() {
                    ve.play().then(function() {
                        setTimeout(function() { S.isSyncing = false; }, 300);
                    }).catch(function() {
                        setTimeout(function() { S.isSyncing = false; }, 300);
                    });
                }, bufferDelay);
                ve.removeEventListener('seeked', onSeeked);
            }, { once: true });
        } else {
            ve.addEventListener('seeked', function onSeeked() {
                setTimeout(function() { S.isSyncing = false; }, 300);
                ve.removeEventListener('seeked', onSeeked);
            }, { once: true });
        }
    }

    function init() {
        var ve = S.dom.videoElement;

        // Local playback control -> emit to server
        ve.addEventListener('play', function() {
            if (ve.ended) return;
            if (!S.isSyncing && !S.isUserSeeking) {
                var now = Date.now();
                if (now - S.lastPlayBroadcast > S.playPauseThrottle) {
                    S.lastPlayBroadcast = now;
                    S.socket.emit('play', {
                        party_id: S.partyId,
                        time: ve.currentTime
                    });
                }
            }
        });

        ve.addEventListener('pause', function() {
            if (ve.ended) return;
            if (!S.isSyncing && !S.isUserSeeking) {
                var now = Date.now();
                if (now - S.lastPauseBroadcast > S.playPauseThrottle) {
                    S.lastPauseBroadcast = now;
                    S.socket.emit('pause', {
                        party_id: S.partyId,
                        time: ve.currentTime
                    });
                }
            }
        });

        ve.addEventListener('seeked', function() {
            if (!S.isSyncing) {
                if (S.isUserSeeking) {
                    if (S.seekSettleTimer) {
                        clearTimeout(S.seekSettleTimer);
                    }
                    S.seekSettleTimer = setTimeout(function() {
                        S.isUserSeeking = false;
                        S.seekSettleTimer = null;
                        S.socket.emit('seek', {
                            party_id: S.partyId,
                            time: ve.currentTime
                        });
                    }, 500);
                }
            }
        });

        ve.addEventListener('seeking', function() {
            if (!S.isSyncing) {
                S.isUserSeeking = true;
                if (S.seekSettleTimer) {
                    clearTimeout(S.seekSettleTimer);
                }
            }
        });

        // Remote sync commands -> apply locally
        S.socket.on('play', function(data) {
            if (Math.abs(data.time - S.lastSyncedTime) < 0.1 && S.lastSyncType === 'play') return;
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'play';
            S.currentPartyState = { time: data.time, playing: true };
            processSyncCommand({ type: 'play', time: data.time });
        });

        S.socket.on('pause', function(data) {
            if (Math.abs(data.time - S.lastSyncedTime) < 0.1 && S.lastSyncType === 'pause') return;
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'pause';
            S.currentPartyState = { time: data.time, playing: false };
            processSyncCommand({ type: 'pause', time: data.time });
        });

        S.socket.on('force_pause_before_seek', function(data) {
            S.isSyncing = true;
            ve.pause();
            setTimeout(function() { S.isSyncing = false; }, 300);
        });

        S.socket.on('seek', function(data) {
            if (Math.abs(data.time - S.lastSyncedTime) < 0.1 && S.lastSyncType === 'seek') return;
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'seek';
            S.currentPartyState = { time: data.time, playing: data.playing || false };
            processSyncCommand({
                type: 'seek',
                time: data.time,
                playing: data.playing,
                buffer_delay: data.buffer_delay || 500
            });
        });
    }

    window.PartySync = {
        init: init,
        processSyncCommand: processSyncCommand
    };
})();
