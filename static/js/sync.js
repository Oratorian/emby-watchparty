// sync.js - Playback synchronization module
(function() {
    'use strict';
    var S = window.PartyState;

    function formatSeekTime(seconds) {
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = Math.floor(seconds % 60);
        var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
        return h > 0 ? h + ':' + pad(m) + ':' + pad(s) : pad(m) + ':' + pad(s);
    }

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
                window.PartyChat.addSystemMessage('Autoplay blocked by browser - click the video to resume');
            });
        } else {
            S.isSyncing = true;
            ve.play().then(function() {
                setTimeout(function() { S.isSyncing = false; }, 300);
            }).catch(function() {
                setTimeout(function() { S.isSyncing = false; }, 300);
                window.PartyChat.addSystemMessage('Autoplay blocked by browser - click the video to resume');
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
                        setTimeout(function() { S.isSyncing = false; }, 2000);
                    }).catch(function() {
                        setTimeout(function() { S.isSyncing = false; }, 2000);
                        window.PartyChat.addSystemMessage('Autoplay blocked by browser - click the video to resume');
                    });
                }, bufferDelay);
                ve.removeEventListener('seeked', onSeeked);
            }, { once: true });
        } else {
            ve.addEventListener('seeked', function onSeeked() {
                setTimeout(function() { S.isSyncing = false; }, 2000);
                ve.removeEventListener('seeked', onSeeked);
            }, { once: true });
        }
    }

    function init() {
        var ve = S.dom.videoElement;

        // Local playback control -> emit to server
        ve.addEventListener('play', function() {
            if (ve.ended) return;
            S.wasPlayingBeforeSeek = true;
            if (!S.isSyncing && !S.isUserSeeking) {
                var now = Date.now();
                if (now - S.lastPlayBroadcast > S.playPauseThrottle) {
                    S.lastPlayBroadcast = now;
                    S.socket.emit('play', {
                        party_id: S.partyId,
                        time: ve.currentTime
                    });
                    window.PartyChat.addSystemMessage(S.username + ' resumed playback');
                }
            }
        });

        ve.addEventListener('pause', function() {
            if (ve.ended) return;
            if (!S.isSyncing && !S.isUserSeeking) {
                var now = Date.now();
                if (now - S.lastPauseBroadcast > S.playPauseThrottle) {
                    S.lastPauseBroadcast = now;
                    S.wasPlayingBeforeSeek = false;
                    S.socket.emit('pause', {
                        party_id: S.partyId,
                        time: ve.currentTime
                    });
                    window.PartyChat.addSystemMessage(S.username + ' paused playback');
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
                        var seekTime = ve.currentTime;
                        var wasPlaying = S.wasPlayingBeforeSeek || false;
                        S.socket.emit('seek', {
                            party_id: S.partyId,
                            time: seekTime,
                            was_playing: wasPlaying
                        });
                        window.PartyChat.addSystemMessage(S.username + ' seeked to ' + formatSeekTime(seekTime));
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
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'play';
            S.currentPartyState = { time: data.time, playing: true };
            if (data.username) window.PartyChat.addSystemMessage(data.username + ' resumed playback');
            processSyncCommand({ type: 'play', time: data.time });
        });

        S.socket.on('pause', function(data) {
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'pause';
            S.currentPartyState = { time: data.time, playing: false };
            if (data.username) window.PartyChat.addSystemMessage(data.username + ' paused playback');
            processSyncCommand({ type: 'pause', time: data.time });
        });

        S.socket.on('force_pause_before_seek', function(data) {
            S.isSyncing = true;
            ve.pause();
            setTimeout(function() { S.isSyncing = false; }, 2000);
        });

        S.socket.on('seek', function(data) {
            S.lastSyncedTime = data.time;
            S.lastSyncType = 'seek';
            S.currentPartyState = { time: data.time, playing: data.playing || false };
            if (data.username) window.PartyChat.addSystemMessage(data.username + ' seeked to ' + formatSeekTime(data.time));
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
