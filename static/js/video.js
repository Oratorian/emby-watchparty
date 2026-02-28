// video.js - Video loading, streaming, subtitles, intro skip, and progress reporting module
(function() {
    'use strict';
    var S = window.PartyState;

    async function loadAvailableStreams(itemId) {
        try {
            var response = await fetch(S.appPrefix + '/api/item/' + itemId + '/streams');
            var data = await response.json();

            S.availableStreams = data;
            S.currentItemId = itemId;
            if (data.media_source_id) {
                S.currentMediaSourceId = data.media_source_id;
            }

            // Populate audio select
            S.dom.audioSelect.innerHTML = '';
            if (data.audio && data.audio.length > 0) {
                data.audio.forEach(function(stream) {
                    var option = document.createElement('option');
                    option.value = stream.index;
                    var lang = stream.displayLanguage || stream.language || 'Unknown';
                    var title = stream.title ? ' (' + stream.title + ')' : '';
                    var channels = stream.channels ? ' ' + stream.channels + 'ch' : '';
                    option.textContent = lang + title + channels;
                    if (stream.isDefault) {
                        option.selected = true;
                    }
                    S.dom.audioSelect.appendChild(option);
                });
            } else {
                S.dom.audioSelect.innerHTML = '<option value="">Default Audio</option>';
            }

            // Check if there are any PGS subtitles
            var hasPGS = data.subtitles && data.subtitles.some(function(s) { return s.isPGS; });
            var subtitleControlContainer = document.getElementById('subtitleControlContainer');

            if (hasPGS) {
                subtitleControlContainer.style.visibility = 'visible';
                S.dom.subtitleSelect.innerHTML = '<option value="none">None</option>';
                data.subtitles.filter(function(s) { return s.isPGS; }).forEach(function(stream) {
                    var option = document.createElement('option');
                    option.value = stream.index;
                    var lang = stream.displayLanguage || stream.language || 'Unknown';
                    var title = stream.title ? ' (' + stream.title + ')' : '';
                    var forced = stream.isForced ? ' [Forced]' : '';
                    option.textContent = lang + title + forced + ' [Burned-in]';
                    S.dom.subtitleSelect.appendChild(option);
                });
                S.dom.subtitleSelect.value = 'none';
            } else {
                subtitleControlContainer.style.visibility = 'hidden';
            }
        } catch (error) {
            S.dom.audioSelect.innerHTML = '<option value="">Default Audio</option>';
            S.dom.subtitleSelect.innerHTML = '<option value="none">None</option>';
        }
    }

    function loadSubtitleTrack(subtitleIndex) {
        var ve = S.dom.videoElement;

        // Disable all text tracks
        for (var i = 0; i < ve.textTracks.length; i++) {
            ve.textTracks[i].mode = 'disabled';
        }

        // Remove all existing text track elements
        while (ve.textTracks.length > 0) {
            var track = ve.textTracks[0];
            var trackElement = Array.from(ve.querySelectorAll('track')).find(function(t) { return t.track === track; });
            if (trackElement) {
                ve.removeChild(trackElement);
            }
        }

        if (!subtitleIndex || subtitleIndex === 'none' || subtitleIndex === -1) {
            return;
        }

        var subtitle = S.availableStreams.subtitles && S.availableStreams.subtitles.find(function(s) { return s.index === parseInt(subtitleIndex); });

        if (subtitle && subtitle.isPGS) {
            return;
        }

        if (subtitle && subtitle.isTextSubtitleStream && S.currentMediaSourceId) {
            var trackEl = document.createElement('track');
            trackEl.kind = 'subtitles';
            trackEl.label = subtitle.displayLanguage || subtitle.language || 'Unknown';
            trackEl.srclang = subtitle.language || 'und';
            trackEl.src = S.appPrefix + '/api/subtitles/' + S.currentItemId + '/' + S.currentMediaSourceId + '/' + subtitleIndex;
            trackEl.default = true;

            trackEl.addEventListener('load', function() {
                if (this.track.mode !== 'showing') {
                    this.track.mode = 'showing';
                }
            });

            ve.appendChild(trackEl);
        }
    }

    function loadAllTextSubtitles() {
        var ve = S.dom.videoElement;
        var existingTracks = ve.querySelectorAll('track');
        existingTracks.forEach(function(track) { track.remove(); });

        if (!S.availableStreams.subtitles || !S.currentItemId || !S.currentMediaSourceId) {
            return;
        }

        var textSubtitles = S.availableStreams.subtitles.filter(function(s) { return !s.isPGS && s.isTextSubtitleStream; });

        if (textSubtitles.length === 0) {
            return;
        }

        textSubtitles.forEach(function(subtitle) {
            var track = document.createElement('track');
            track.kind = 'subtitles';
            track.label = subtitle.displayLanguage || subtitle.language || 'Unknown';
            track.srclang = subtitle.language || 'und';
            track.src = S.appPrefix + '/api/subtitles/' + S.currentItemId + '/' + S.currentMediaSourceId + '/' + subtitle.index;
            track.mode = 'hidden';
            ve.appendChild(track);
        });
    }

    function loadVideo(video) {
        var ve = S.dom.videoElement;

        S.dom.noVideoState.style.display = 'none';
        S.dom.videoPlayer.style.display = 'block';

        // Auto-hide library sidebar
        if (S.dom.librarySidebar && !S.dom.librarySidebar.classList.contains('hidden')) {
            S.dom.librarySidebar.classList.add('hidden');
            if (S.dom.showLibraryBtn) {
                S.dom.showLibraryBtn.style.display = 'inline-block';
            }
        }

        // Destroy previous HLS instance
        if (S.hls) {
            S.hls.destroy();
            S.hls = null;
        }

        // Clear previous handlers
        ve.onerror = null;
        ve.onloadedmetadata = null;
        ve.onloadstart = null;
        ve.onprogress = null;

        S.currentItemId = video.item_id;
        S.currentMediaSourceId = video.media_source_id;

        loadAvailableStreams(video.item_id);

        S.dom.videoTitle.textContent = video.title;
        S.dom.videoDescription.textContent = video.overview || '';

        // Show/hide stop button
        if (S.canStopVideo) {
            S.dom.stopVideoBtn.style.display = 'inline-block';
        } else {
            S.dom.stopVideoBtn.style.display = 'none';
        }

        // Update stream selectors
        if (video.audio_index !== undefined) {
            S.dom.audioSelect.value = video.audio_index === null ? 'none' : video.audio_index;
        }
        if (video.subtitle_index !== undefined) {
            S.dom.subtitleSelect.value = video.subtitle_index === null ? 'none' : video.subtitle_index;
        }

        // Video ready handler
        ve.onloadedmetadata = function() {
            ve.muted = false;
            loadAllTextSubtitles();
            if (video.subtitle_index !== undefined && video.subtitle_index !== null) {
                loadSubtitleTrack(video.subtitle_index);
            }
        };

        // HLS playback
        if (video.stream_url.includes('.m3u8')) {
            if (Hls.isSupported()) {
                var hlsConfig = {
                    debug: false,
                    enableWorker: true,
                    lowLatencyMode: false,
                    backBufferLength: 90,
                    fragLoadingTimeOut: 20000,
                    fragLoadingMaxRetry: 4,
                    fragLoadingRetryDelay: 1000,
                    manifestLoadingTimeOut: 10000,
                    levelLoadingTimeOut: 10000
                };

                if (S.currentPartyState && S.currentPartyState.time > 0) {
                    hlsConfig.startPosition = S.currentPartyState.time;
                }

                S.hls = new Hls(hlsConfig);
                S.hls.attachMedia(ve);

                S.hls.on(Hls.Events.MEDIA_ATTACHED, function() {
                    S.hls.loadSource(video.stream_url);
                });

                S.hls.on(Hls.Events.MANIFEST_PARSED, function(event, data) {
                    ve.muted = false;
                    if (!S.isSyncing && !hlsConfig.startPosition) {
                        ve.currentTime = 0;
                    }
                    if (S.isSyncing) {
                        S.isSyncing = false;
                    }
                });

                S.hls.on(Hls.Events.ERROR, function(event, data) {
                    if (!data.fatal) {
                        if (data.details === 'fragLoadTimeOut' || data.details === 'fragLoadError') {
                            return;
                        }
                    }
                    if (data.fatal) {
                        switch(data.type) {
                            case Hls.ErrorTypes.NETWORK_ERROR:
                                window.PartyChat.addSystemMessage('Network error, attempting recovery...');
                                S.hls.startLoad();
                                break;
                            case Hls.ErrorTypes.MEDIA_ERROR:
                                window.PartyChat.addSystemMessage('Media error, attempting recovery...');
                                S.hls.recoverMediaError();
                                break;
                            default:
                                window.PartyChat.addSystemMessage('Fatal HLS error: ' + data.type);
                                S.hls.destroy();
                                break;
                        }
                    }
                });
            } else if (ve.canPlayType('application/vnd.apple.mpegurl')) {
                ve.src = video.stream_url;
            } else {
                window.PartyChat.addSystemMessage('Error: HLS playback not supported in this browser');
            }
        } else {
            ve.src = video.stream_url;
            ve.load();
        }

        loadIntroData(video.item_id);
        startProgressReporting();
    }

    async function loadIntroData(itemId) {
        try {
            var response = await fetch(S.appPrefix + '/api/intro/' + itemId);
            var data = await response.json();

            if (data.hasIntro) {
                S.introData = data;
                console.log('Intro detected: ' + data.start.toFixed(2) + 's - ' + data.end.toFixed(2) + 's (' + data.duration.toFixed(2) + 's)');
                startIntroCheck();
            } else {
                S.introData = null;
                stopIntroCheck();
                hideSkipIntroButton();
            }
        } catch (error) {
            console.error('Failed to load intro data:', error);
            S.introData = null;
            stopIntroCheck();
            hideSkipIntroButton();
        }
    }

    function checkIntroButton() {
        if (!S.introData || !S.dom.videoElement || !S.dom.videoElement.src) {
            hideSkipIntroButton();
            return;
        }

        var currentTime = S.dom.videoElement.currentTime;

        if (currentTime >= (S.introData.start + 1) && currentTime < S.introData.end) {
            if (S.dom.skipIntroBtn) {
                S.dom.skipIntroBtn.style.display = 'block';
            }
        } else {
            hideSkipIntroButton();
        }
    }

    function hideSkipIntroButton() {
        if (S.dom.skipIntroBtn) {
            S.dom.skipIntroBtn.style.display = 'none';
        }
    }

    function skipIntro() {
        if (!S.introData) return;

        console.log('Skipping intro to ' + S.introData.end.toFixed(2) + 's');

        S.socket.emit('seek', {
            party_id: S.partyId,
            time: S.introData.end
        });

        hideSkipIntroButton();
    }

    function startIntroCheck() {
        stopIntroCheck();
        S.introCheckInterval = setInterval(checkIntroButton, 500);
    }

    function stopIntroCheck() {
        if (S.introCheckInterval) {
            clearInterval(S.introCheckInterval);
            S.introCheckInterval = null;
        }
    }

    function startProgressReporting() {
        if (S.progressReportInterval) {
            clearInterval(S.progressReportInterval);
        }

        S.progressReportInterval = setInterval(function() {
            if (!S.canStopVideo) return;
            if (!S.dom.videoElement.src || S.dom.videoElement.readyState < 2) return;
            if (S.dom.videoElement.paused) return;

            S.socket.emit('report_progress', {
                party_id: S.partyId,
                time: S.dom.videoElement.currentTime
            });
        }, 10000);
    }

    function stopProgressReporting() {
        if (S.progressReportInterval) {
            clearInterval(S.progressReportInterval);
            S.progressReportInterval = null;
        }
    }

    function init() {
        var ve = S.dom.videoElement;

        // Skip intro button listener (replacing HTML onclick)
        if (S.dom.skipIntroBtn) {
            S.dom.skipIntroBtn.addEventListener('click', skipIntro);
        }

        // Audio/subtitle dropdown change listeners
        S.dom.audioSelect.addEventListener('change', function() {
            var audioIndex = S.dom.audioSelect.value === 'none' ? null : parseInt(S.dom.audioSelect.value);
            var subtitleIndex = S.dom.subtitleSelect.value === 'none' ? null : parseInt(S.dom.subtitleSelect.value);

            S.socket.emit('change_streams', {
                party_id: S.partyId,
                audio_index: audioIndex,
                subtitle_index: subtitleIndex
            });
        });

        S.dom.subtitleSelect.addEventListener('change', function() {
            var audioIndex = S.dom.audioSelect.value === 'none' ? null : parseInt(S.dom.audioSelect.value);
            var subtitleIndex = S.dom.subtitleSelect.value === 'none' ? null : parseInt(S.dom.subtitleSelect.value);

            var subtitle = S.availableStreams.subtitles && S.availableStreams.subtitles.find(function(s) { return s.index === subtitleIndex; });

            if (!subtitle || subtitle.isPGS || subtitleIndex === null) {
                loadSubtitleTrack(subtitleIndex);
                S.socket.emit('change_streams', {
                    party_id: S.partyId,
                    audio_index: audioIndex,
                    subtitle_index: subtitleIndex
                });
            }
        });

        // Video ended listener
        ve.addEventListener('ended', function() {
            console.log('Video playback ended');

            S.currentPartyState = null;
            stopProgressReporting();

            // Exit fullscreen if active
            if (document.fullscreenElement || document.webkitFullscreenElement ||
                document.mozFullScreenElement || document.msFullscreenElement) {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                } else if (document.mozCancelFullScreen) {
                    document.mozCancelFullScreen();
                } else if (document.msExitFullscreen) {
                    document.msExitFullscreen();
                }
                console.log('Exiting fullscreen - video ended');
            }

            S.socket.emit('video_ended', { party_id: S.partyId });

            var isVideoSelector = S.videoSelectedBy && S.videoSelectedBy === S.socket.id;

            if (isVideoSelector && S.autoplayEnabled && S.currentEpisodeIndex !== -1 && S.currentEpisodeList.length > 0) {
                var nextEpisodeIndex = S.currentEpisodeIndex + 1;
                if (nextEpisodeIndex < S.currentEpisodeList.length) {
                    console.log('Video selector triggering autoplay countdown');
                    window.PartyUI.startAutoplayCountdown(S.currentEpisodeList[nextEpisodeIndex]);
                } else {
                    window.PartyUI.showLibraryAfterVideoEnd();
                    window.PartyChat.addSystemMessage('\uD83C\uDFAC Season finished - Select next content from library');
                }
            } else {
                if (!isVideoSelector && S.autoplayEnabled && S.currentEpisodeIndex !== -1) {
                    console.log('Non-selector waiting for autoplay from selector');
                }
                window.PartyUI.showLibraryAfterVideoEnd();
                if (isVideoSelector || !(S.autoplayEnabled && S.currentEpisodeIndex !== -1)) {
                    window.PartyChat.addSystemMessage('\uD83C\uDFAC Video ended - Select next content from library');
                }
            }
        });

        // Socket handlers
        S.socket.on('sync_state', function(data) {
            if (data.current_video) {
                var syncStateArrivalTime = Date.now();

                S.videoSelectedBy = data.current_video.selected_by;

                if (data.playback_state && data.playback_state.time >= 0) {
                    S.isSyncing = true;
                    setTimeout(function() {
                        if (S.isSyncing) {
                            console.warn('isSyncing was stuck true, resetting after 3 seconds');
                            S.isSyncing = false;
                        }
                    }, 3000);
                }

                loadVideo(data.current_video);

                if (data.playback_state) {
                    S.currentPartyState = {
                        time: data.playback_state.time,
                        playing: data.playback_state.playing
                    };
                }

                if (data.playback_state && data.playback_state.time >= 0) {
                    ve.addEventListener('loadedmetadata', function syncAfterLoad() {
                        ve.muted = false;

                        var loadingDelay = (Date.now() - syncStateArrivalTime) / 1000;
                        var cappedDelay = Math.min(loadingDelay, 2.0);
                        var compensatedTime = data.playback_state.time + (data.playback_state.playing ? cappedDelay : 0);

                        ve.currentTime = compensatedTime;

                        if (data.playback_state.playing) {
                            ve.play().then(function() {
                                setTimeout(function() { S.isSyncing = false; }, 100);
                            }).catch(function() {
                                setTimeout(function() { S.isSyncing = false; }, 100);
                            });
                        } else {
                            setTimeout(function() { S.isSyncing = false; }, 100);
                        }

                        ve.removeEventListener('loadedmetadata', syncAfterLoad);
                    }, { once: true });
                }
            }
        });

        S.socket.on('video_selected', function(data) {
            S.videoSelectedBy = data.video.selected_by;
            S.currentPartyState = null;
            loadVideo(data.video);
        });

        S.socket.on('video_stopped', function(data) {
            if (S.hls) {
                S.hls.destroy();
                S.hls = null;
            }

            ve.pause();
            ve.src = '';
            S.dom.videoPlayer.style.display = 'none';
            S.dom.noVideoState.style.display = 'flex';

            if (S.dom.librarySidebar && S.dom.librarySidebar.classList.contains('hidden')) {
                S.dom.librarySidebar.classList.remove('hidden');
                if (S.dom.showLibraryBtn) {
                    S.dom.showLibraryBtn.style.display = 'none';
                }
            }

            S.canStopVideo = false;
            S.currentItemId = null;
            S.currentPartyState = null;
            stopProgressReporting();

            window.PartyChat.addSystemMessage(data.message);
        });

        S.socket.on('streams_changed', function(data) {
            var wasPlaying = !ve.paused;
            var currentTime = ve.currentTime;

            S.videoSelectedBy = data.video.selected_by;

            if (data.video.media_source_id) {
                S.currentMediaSourceId = data.video.media_source_id;
            }

            if (S.hls) {
                S.hls.destroy();
                S.hls = null;
            }

            S.isSyncing = true;

            if (data.video.stream_url.includes('.m3u8')) {
                if (Hls.isSupported()) {
                    S.hls = new Hls({
                        debug: false,
                        enableWorker: true,
                        lowLatencyMode: false,
                        backBufferLength: 90,
                        fragLoadingTimeOut: 20000,
                        fragLoadingMaxRetry: 4,
                        fragLoadingRetryDelay: 1000,
                        manifestLoadingTimeOut: 10000,
                        levelLoadingTimeOut: 10000
                    });

                    S.hls.attachMedia(ve);

                    S.hls.on(Hls.Events.MEDIA_ATTACHED, function() {
                        S.hls.loadSource(data.video.stream_url);
                    });

                    S.hls.on(Hls.Events.MANIFEST_PARSED, function() {
                        ve.currentTime = data.current_time || currentTime;

                        if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                            loadSubtitleTrack(data.video.subtitle_index);
                        }

                        if (wasPlaying) {
                            ve.play().then(function() {
                                setTimeout(function() { S.isSyncing = false; }, 100);
                            }).catch(function() {
                                setTimeout(function() { S.isSyncing = false; }, 100);
                            });
                        } else {
                            setTimeout(function() { S.isSyncing = false; }, 100);
                        }
                    });
                } else if (ve.canPlayType('application/vnd.apple.mpegurl')) {
                    ve.src = data.video.stream_url;
                    ve.addEventListener('loadedmetadata', function restorePlayback() {
                        ve.currentTime = data.current_time || currentTime;
                        if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                            loadSubtitleTrack(data.video.subtitle_index);
                        }
                        if (wasPlaying) {
                            ve.play().then(function() {
                                setTimeout(function() { S.isSyncing = false; }, 100);
                            });
                        } else {
                            setTimeout(function() { S.isSyncing = false; }, 100);
                        }
                        ve.removeEventListener('loadedmetadata', restorePlayback);
                    }, { once: true });
                }
            } else {
                ve.src = data.video.stream_url;
                ve.load();
                ve.addEventListener('loadedmetadata', function restorePlayback() {
                    ve.currentTime = data.current_time || currentTime;
                    if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                        loadSubtitleTrack(data.video.subtitle_index);
                    }
                    if (wasPlaying) {
                        ve.play().then(function() {
                            setTimeout(function() { S.isSyncing = false; }, 100);
                        }).catch(function() {
                            setTimeout(function() { S.isSyncing = false; }, 100);
                        });
                    } else {
                        setTimeout(function() { S.isSyncing = false; }, 100);
                    }
                    ve.removeEventListener('loadedmetadata', restorePlayback);
                }, { once: true });
            }

            // Update selectors
            if (data.video.audio_index !== undefined) {
                S.dom.audioSelect.value = data.video.audio_index === null ? 'none' : data.video.audio_index;
            }
            if (data.video.subtitle_index !== undefined) {
                S.dom.subtitleSelect.value = data.video.subtitle_index === null ? 'none' : data.video.subtitle_index;
            }

            window.PartyChat.addSystemMessage('Stream settings changed');
        });
    }

    window.PartyVideo = {
        init: init,
        loadVideo: loadVideo,
        loadAvailableStreams: loadAvailableStreams,
        skipIntro: skipIntro,
        stopProgressReporting: stopProgressReporting
    };
})();
