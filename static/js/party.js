// Get party ID from URL
const partyId = window.location.pathname.split('/').pop();

// Initialize Socket.IO
const socket = io();

// DOM elements
const usernameModal = document.getElementById('usernameModal');
const usernameInput = document.getElementById('usernameInput');
const joinBtn = document.getElementById('joinBtn');
const partyCodeEl = document.getElementById('partyCode');
const copyCodeBtn = document.getElementById('copyCodeBtn');
const userCountEl = document.getElementById('userCount');
const leavePartyBtn = document.getElementById('leavePartyBtn');
const libraryContent = document.getElementById('libraryContent');
const navBtns = document.querySelectorAll('.nav-btn');
const toggleSidebarBtn = document.getElementById('toggleSidebarBtn');
const librarySidebar = document.getElementById('librarySidebar');
const noVideoState = document.getElementById('noVideoState');
const videoPlayer = document.getElementById('videoPlayer');
const videoElement = document.getElementById('videoElement');
const videoTitle = document.getElementById('videoTitle');
const videoDescription = document.getElementById('videoDescription');
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const sendChatBtn = document.getElementById('sendChatBtn');
const audioSelect = document.getElementById('audioSelect');
const subtitleSelect = document.getElementById('subtitleSelect');

// State
let username = '';
let currentUsers = [];
let isHost = false;
let isSyncing = false;
let lastSyncTime = 0;
let syncThreshold = 0.5; // Only sync if difference is more than 2 seconds
// Allows some drift to prevent constant re-syncing when browsers buffer differently
let lastSeekBroadcast = 0;
let seekBroadcastDelay = 500; // Throttle seek broadcasts to max once per 500ms
let currentItemId = null;
let availableStreams = { audio: [], subtitles: [] };
let lastPlayBroadcast = 0;
let lastPauseBroadcast = 0;
let playPauseThrottle = 300; // Throttle play/pause broadcasts to max once per 300ms
let lastSyncedTime = 0;
let lastSyncType = '';
let isUserSeeking = false;
let seekSettleTimer = null;
let hls = null; // HLS.js instance

// Show username modal on load
usernameModal.style.display = 'flex';

// Join party
joinBtn.addEventListener('click', () => {
    username = usernameInput.value.trim();

    // Allow empty username - server will generate a random one
    usernameModal.style.display = 'none';
    socket.emit('join_party', {
        party_id: partyId,
        username: username
    });

    // Load libraries by default
    loadLibraries();
});

usernameInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        joinBtn.click();
    }
});

// Copy party code
copyCodeBtn.addEventListener('click', () => {
    // Try modern clipboard API first
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(partyId).then(() => {
            copyCodeBtn.textContent = 'Copied!';
            setTimeout(() => {
                copyCodeBtn.textContent = 'Copy';
            }, 2000);
        }).catch(err => {
            // Fallback if clipboard API fails
            fallbackCopyToClipboard(partyId);
        });
    } else {
        // Fallback for older browsers or non-secure contexts
        fallbackCopyToClipboard(partyId);
    }
});

// Fallback copy method using textarea
function fallbackCopyToClipboard(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();

    try {
        document.execCommand('copy');
        copyCodeBtn.textContent = 'Copied!';
        setTimeout(() => {
            copyCodeBtn.textContent = 'Copy';
        }, 2000);
    } catch (err) {
        // Fallback: select the party code text
        const partyCodeEl = document.getElementById('partyCode');
        const range = document.createRange();
        range.selectNode(partyCodeEl);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        alert('Party code selected. Press Ctrl+C (or Cmd+C on Mac) to copy.');
    }

    document.body.removeChild(textarea);
}

// Leave party
leavePartyBtn.addEventListener('click', () => {
    if (confirm('Are you sure you want to leave the party?')) {
        socket.emit('leave_party', { party_id: partyId });
        window.location.href = '/';
    }
});

// Toggle sidebar
toggleSidebarBtn.addEventListener('click', () => {
    librarySidebar.classList.toggle('hidden');
    toggleSidebarBtn.textContent = librarySidebar.classList.contains('hidden') ? 'Show' : 'Hide';
});

// Navigation buttons
navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        navBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const type = btn.dataset.type;

        if (type === 'libraries') {
            loadLibraries();
        } else if (type === 'movies') {
            loadItems('Movie');
        } else if (type === 'shows') {
            loadItems('Series');
        }
    });
});

// Load libraries
async function loadLibraries() {
    try {
        libraryContent.innerHTML = '<p>Loading libraries...</p>';

        const response = await fetch('/api/libraries');
        const data = await response.json();

        if (data.Items && data.Items.length > 0) {
            libraryContent.innerHTML = '';

            data.Items.forEach(library => {
                const item = createLibraryItem(library, () => {
                    loadItemsFromLibrary(library.Id);
                });
                libraryContent.appendChild(item);
            });
        } else {
            libraryContent.innerHTML = '<p>No libraries found</p>';
        }
    } catch (error) {
        libraryContent.innerHTML = '<p>Error loading libraries</p>';
    }
}

// Load items from a specific library
async function loadItemsFromLibrary(parentId) {
    try {
        libraryContent.innerHTML = '<p>Loading items...</p>';

        const response = await fetch(`/api/items?parentId=${parentId}&recursive=true`);
        const data = await response.json();

        displayItems(data.Items, 'library');
    } catch (error) {
        libraryContent.innerHTML = '<p>Error loading items</p>';
    }
}

// Load episodes from a series
async function loadSeriesEpisodes(seriesId, seriesName) {
    try {
        libraryContent.innerHTML = '<p>Loading episodes...</p>';

        const response = await fetch(`/api/items?parentId=${seriesId}&recursive=true`);
        const data = await response.json();

        // Add a back button
        libraryContent.innerHTML = '';

        const backBtn = document.createElement('div');
        backBtn.className = 'library-item';
        backBtn.style.background = '#667eea';
        backBtn.style.cursor = 'pointer';
        backBtn.innerHTML = `
            <div class="library-item-info">
                <div class="library-item-title">← Back</div>
                <div class="library-item-meta">Return to library</div>
            </div>
        `;
        backBtn.addEventListener('click', () => {
            loadLibraries();
        });
        libraryContent.appendChild(backBtn);

        // Show series title
        const titleDiv = document.createElement('div');
        titleDiv.style.padding = '1rem';
        titleDiv.style.color = '#667eea';
        titleDiv.style.fontWeight = 'bold';
        titleDiv.style.fontSize = '1.1rem';
        titleDiv.textContent = seriesName;
        libraryContent.appendChild(titleDiv);

        displayItems(data.Items, 'episodes');
    } catch (error) {
        libraryContent.innerHTML = '<p>Error loading episodes</p>';
    }
}

// Load items by type
async function loadItems(itemType) {
    try {
        libraryContent.innerHTML = '<p>Loading items...</p>';

        const response = await fetch(`/api/items?type=${itemType}&recursive=true`);
        const data = await response.json();

        displayItems(data.Items);
    } catch (error) {
        libraryContent.innerHTML = '<p>Error loading items</p>';
    }
}

// Display items in the library
function displayItems(items, context = 'library') {
    if (items && items.length > 0) {
        libraryContent.innerHTML = '';

        let displayableItems;

        if (context === 'library') {
            // When browsing a library, show Series and Movies, but NOT individual Episodes
            displayableItems = items.filter(item =>
                item.Type === 'Movie' || item.Type === 'Series' || item.Type === 'Video'
            );
        } else {
            // When browsing specific content, show playable items
            displayableItems = items.filter(item =>
                item.Type === 'Movie' || item.Type === 'Episode' || item.Type === 'Video'
            );
        }

        if (displayableItems.length > 0) {
            displayableItems.forEach(item => {
                const itemEl = createLibraryItem(item, () => {
                    // If it's a Series, load its episodes
                    if (item.Type === 'Series') {
                        loadSeriesEpisodes(item.Id, item.Name);
                    } else {
                        selectVideo(item);
                    }
                }, true);
                libraryContent.appendChild(itemEl);
            });
        } else {
            libraryContent.innerHTML = '<p>No items found</p>';
        }
    } else {
        libraryContent.innerHTML = '<p>No items found</p>';
    }
}

// Create library item element
function createLibraryItem(item, onClick, showImage = false) {
    const div = document.createElement('div');
    div.className = 'library-item';
    div.addEventListener('click', onClick);

    if (showImage && item.Id) {
        const img = document.createElement('img');
        img.src = `/api/image/${item.Id}?type=Primary`;
        img.onerror = () => {
            img.style.display = 'none';
        };
        div.appendChild(img);
    }

    const info = document.createElement('div');
    info.className = 'library-item-info';

    const title = document.createElement('div');
    title.className = 'library-item-title';
    title.textContent = item.Name;

    const meta = document.createElement('div');
    meta.className = 'library-item-meta';

    if (item.Type) {
        meta.textContent = item.Type;
    }

    if (item.ProductionYear) {
        meta.textContent += ` • ${item.ProductionYear}`;
    }

    info.appendChild(title);
    if (meta.textContent) {
        info.appendChild(meta);
    }

    div.appendChild(info);

    return div;
}

// Select video to watch
function selectVideo(item) {
    addSystemMessage(`${username} selected: ${item.Name}`);

    socket.emit('select_video', {
        party_id: partyId,
        item_id: item.Id,
        item_name: item.Name,
        item_overview: item.Overview || ''
    });
}

// Video player controls
videoElement.addEventListener('play', () => {
    if (!isSyncing && !isUserSeeking) {
        const now = Date.now();
        if (now - lastPlayBroadcast > playPauseThrottle) {
            lastPlayBroadcast = now;
            socket.emit('play', {
                party_id: partyId,
                time: videoElement.currentTime
            });
        }
    }
});

videoElement.addEventListener('pause', () => {
    if (!isSyncing && !isUserSeeking) {
        const now = Date.now();
        if (now - lastPauseBroadcast > playPauseThrottle) {
            lastPauseBroadcast = now;
            socket.emit('pause', {
                party_id: partyId,
                time: videoElement.currentTime
            });
        }
    }
});

videoElement.addEventListener('seeked', () => {
    if (!isSyncing) {
        if (isUserSeeking) {
            // Clear previous timer and set new one - user might still be dragging
            if (seekSettleTimer) {
                clearTimeout(seekSettleTimer);
            }

            // Wait 500ms after last seek before broadcasting
            // This prevents spam when user drags the seekbar
            seekSettleTimer = setTimeout(() => {
                isUserSeeking = false;
                seekSettleTimer = null;

                socket.emit('seek', {
                    party_id: partyId,
                    time: videoElement.currentTime
                });
            }, 500);
        }
    }
});

// Detect user-initiated seeking
videoElement.addEventListener('seeking', () => {
    if (!isSyncing) {
        // User is manually seeking
        isUserSeeking = true;

        // Clear any existing settle timer
        if (seekSettleTimer) {
            clearTimeout(seekSettleTimer);
        }
    }
});

// Stream selection event listeners
audioSelect.addEventListener('change', () => {
    const audioIndex = audioSelect.value === 'none' ? null : parseInt(audioSelect.value);
    const subtitleIndex = subtitleSelect.value === 'none' ? null : parseInt(subtitleSelect.value);

    socket.emit('change_streams', {
        party_id: partyId,
        audio_index: audioIndex,
        subtitle_index: subtitleIndex
    });
});

subtitleSelect.addEventListener('change', () => {
    const audioIndex = audioSelect.value === 'none' ? null : parseInt(audioSelect.value);
    const subtitleIndex = subtitleSelect.value === 'none' ? null : parseInt(subtitleSelect.value);

    socket.emit('change_streams', {
        party_id: partyId,
        audio_index: audioIndex,
        subtitle_index: subtitleIndex
    });
});

// Chat functionality
sendChatBtn.addEventListener('click', sendMessage);

chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

function sendMessage() {
    const message = chatInput.value.trim();

    if (!message) return;

    socket.emit('chat_message', {
        party_id: partyId,
        message: message
    });

    chatInput.value = '';
}

function addChatMessage(username, message) {
    const div = document.createElement('div');
    div.className = 'chat-message';

    const usernameSpan = document.createElement('span');
    usernameSpan.className = 'chat-message-username';
    usernameSpan.textContent = username + ':';

    const messageSpan = document.createElement('span');
    messageSpan.className = 'chat-message-text';
    messageSpan.textContent = message;

    div.appendChild(usernameSpan);
    div.appendChild(messageSpan);

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addSystemMessage(message) {
    const div = document.createElement('div');
    div.className = 'chat-message chat-message-system';
    div.textContent = message;

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Socket.IO event handlers
socket.on('connected', (data) => {
    // Connected to server
});

socket.on('user_joined', (data) => {
    currentUsers = data.users;
    updateUserCount();
    addSystemMessage(`${data.username} joined the party`);
});

socket.on('user_left', (data) => {
    currentUsers = data.users;
    updateUserCount();
    addSystemMessage(`${data.username} left the party`);
});

socket.on('sync_state', (data) => {
    if (data.current_video) {
        loadVideo(data.current_video);

        // Only sync to non-zero time if video is actually playing or has meaningful progress
        // This prevents syncing to stale times when a new video is just selected
        if (data.playback_state && (data.playback_state.playing || data.playback_state.time > 1)) {
            isSyncing = true;

            // Wait for video to be loaded before syncing
            videoElement.addEventListener('loadedmetadata', function syncAfterLoad() {
                videoElement.currentTime = data.playback_state.time;

                if (data.playback_state.playing) {
                    videoElement.play().then(() => {
                        setTimeout(() => {
                            isSyncing = false;
                        }, 100);
                    }).catch(() => {
                        setTimeout(() => {
                            isSyncing = false;
                        }, 100);
                    });
                } else {
                    setTimeout(() => {
                        isSyncing = false;
                    }, 100);
                }

                // Remove this listener after first use
                videoElement.removeEventListener('loadedmetadata', syncAfterLoad);
            }, { once: true });
        }
    }
});

socket.on('video_selected', (data) => {
    loadVideo(data.video);
});

socket.on('streams_changed', (data) => {
    const wasPlaying = !videoElement.paused;
    const currentTime = videoElement.currentTime;

    // Destroy previous HLS instance if it exists
    if (hls) {
        hls.destroy();
        hls = null;
    }

    // Reload video with new streams
    isSyncing = true;

    // Check if the new stream is HLS
    if (data.video.stream_url.includes('.m3u8')) {
        if (Hls.isSupported()) {
            hls = new Hls({
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

            hls.attachMedia(videoElement);

            hls.on(Hls.Events.MEDIA_ATTACHED, function() {
                hls.loadSource(data.video.stream_url);
            });

            hls.on(Hls.Events.MANIFEST_PARSED, function() {
                videoElement.currentTime = data.current_time || currentTime;

                if (wasPlaying) {
                    videoElement.play().then(() => {
                        setTimeout(() => {
                            isSyncing = false;
                        }, 100);
                    }).catch(() => {
                        setTimeout(() => {
                            isSyncing = false;
                        }, 100);
                    });
                } else {
                    setTimeout(() => {
                        isSyncing = false;
                    }, 100);
                }
            });
        } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
            videoElement.src = data.video.stream_url;
            videoElement.addEventListener('loadedmetadata', function restorePlayback() {
                videoElement.currentTime = data.current_time || currentTime;

                if (wasPlaying) {
                    videoElement.play().then(() => {
                        setTimeout(() => { isSyncing = false; }, 100);
                    });
                } else {
                    setTimeout(() => { isSyncing = false; }, 100);
                }

                videoElement.removeEventListener('loadedmetadata', restorePlayback);
            }, { once: true });
        }
    } else {
        // Direct video source (non-HLS)
        videoElement.src = data.video.stream_url;
        videoElement.load();

        videoElement.addEventListener('loadedmetadata', function restorePlayback() {
            videoElement.currentTime = data.current_time || currentTime;

            if (wasPlaying) {
                videoElement.play().then(() => {
                    setTimeout(() => {
                        isSyncing = false;
                    }, 100);
                }).catch(() => {
                    setTimeout(() => {
                        isSyncing = false;
                    }, 100);
                });
            } else {
                setTimeout(() => {
                    isSyncing = false;
                }, 100);
            }

            videoElement.removeEventListener('loadedmetadata', restorePlayback);
        }, { once: true });
    }

    // Update the selectors
    if (data.video.audio_index !== undefined) {
        audioSelect.value = data.video.audio_index === null ? 'none' : data.video.audio_index;
    }
    if (data.video.subtitle_index !== undefined) {
        subtitleSelect.value = data.video.subtitle_index === null ? 'none' : data.video.subtitle_index;
    }

    addSystemMessage('Stream settings changed');
});

socket.on('play', (data) => {
    // Ignore duplicate commands for the same time
    if (Math.abs(data.time - lastSyncedTime) < 0.1 && lastSyncType === 'play') {
        return;
    }

    lastSyncedTime = data.time;
    lastSyncType = 'play';

    processSyncCommand({ type: 'play', time: data.time });
});

socket.on('pause', (data) => {
    // Ignore duplicate commands for the same time
    if (Math.abs(data.time - lastSyncedTime) < 0.1 && lastSyncType === 'pause') {
        return;
    }

    lastSyncedTime = data.time;
    lastSyncType = 'pause';

    processSyncCommand({ type: 'pause', time: data.time });
});

// Force pause before seek for better buffering
socket.on('force_pause_before_seek', (data) => {
    isSyncing = true;
    videoElement.pause();
    setTimeout(() => { isSyncing = false; }, 300);
});

socket.on('seek', (data) => {
    // Ignore duplicate commands for the same time
    if (Math.abs(data.time - lastSyncedTime) < 0.1 && lastSyncType === 'seek') {
        return;
    }

    lastSyncedTime = data.time;
    lastSyncType = 'seek';

    processSyncCommand({
        type: 'seek',
        time: data.time,
        playing: data.playing,
        buffer_delay: data.buffer_delay || 500
    });
});

socket.on('chat_message', (data) => {
    addChatMessage(data.username, data.message);
});

socket.on('error', (data) => {
    alert('Error: ' + data.message);
});

// Helper functions
function processSyncCommand(command) {
    const timeDiff = Math.abs(videoElement.currentTime - command.time);
    const needsSeek = timeDiff > syncThreshold;

    if (command.type === 'play') {
        handlePlaySync(command.time, needsSeek, timeDiff);
    } else if (command.type === 'pause') {
        handlePauseSync(command.time, needsSeek, timeDiff);
    } else if (command.type === 'seek') {
        handleSeekSync(command.time, command.playing || false, command.buffer_delay || 500);
    }
}

function handlePlaySync(targetTime, needsSeek, timeDiff) {
    if (needsSeek) {
        isSyncing = true;
        videoElement.currentTime = targetTime;
        videoElement.play().then(() => {
            setTimeout(() => { isSyncing = false; }, 500);
        }).catch(() => {
            setTimeout(() => { isSyncing = false; }, 500);
        });
    } else {
        isSyncing = true;
        videoElement.play().then(() => {
            setTimeout(() => { isSyncing = false; }, 300);
        }).catch(() => {
            setTimeout(() => { isSyncing = false; }, 300);
        });
    }
}

function handlePauseSync(targetTime, needsSeek, timeDiff) {
    if (needsSeek) {
        isSyncing = true;
        videoElement.currentTime = targetTime;
        videoElement.pause();
        setTimeout(() => { isSyncing = false; }, 500);
    } else {
        isSyncing = true;
        videoElement.pause();
        setTimeout(() => { isSyncing = false; }, 300);
    }
}

function handleSeekSync(targetTime, shouldPlay = false, bufferDelay = 500) {
    isSyncing = true;

    // Pause first to prevent buffering issues
    videoElement.pause();

    // Seek to the target time
    videoElement.currentTime = targetTime;

    // If video should be playing after seek, wait for segments to load
    if (shouldPlay) {
        // Wait for 'seeked' event to know the seek completed
        videoElement.addEventListener('seeked', function onSeeked() {
            // Wait for buffer to load (configurable delay)
            setTimeout(() => {
                videoElement.play().then(() => {
                    setTimeout(() => { isSyncing = false; }, 300);
                }).catch(() => {
                    setTimeout(() => { isSyncing = false; }, 300);
                });
            }, bufferDelay);

            videoElement.removeEventListener('seeked', onSeeked);
        }, { once: true });
    } else {
        // Just stay paused - wait for seek to complete
        videoElement.addEventListener('seeked', function onSeeked() {
            setTimeout(() => { isSyncing = false; }, 300);
            videoElement.removeEventListener('seeked', onSeeked);
        }, { once: true });
    }
}

async function loadAvailableStreams(itemId) {
    try {
        const response = await fetch(`/api/item/${itemId}/streams`);
        const data = await response.json();

        availableStreams = data;
        currentItemId = itemId;

        // Populate audio select
        audioSelect.innerHTML = '';
        if (data.audio && data.audio.length > 0) {
            data.audio.forEach(stream => {
                const option = document.createElement('option');
                option.value = stream.index;
                const lang = stream.displayLanguage || stream.language || 'Unknown';
                const title = stream.title ? ` (${stream.title})` : '';
                const channels = stream.channels ? ` ${stream.channels}ch` : '';
                option.textContent = `${lang}${title}${channels}`;
                if (stream.isDefault) {
                    option.selected = true;
                }
                audioSelect.appendChild(option);
            });
        } else {
            audioSelect.innerHTML = '<option value="">Default Audio</option>';
        }

        // Populate subtitle select
        subtitleSelect.innerHTML = '<option value="none">None</option>';
        if (data.subtitles && data.subtitles.length > 0) {
            data.subtitles.forEach(stream => {
                const option = document.createElement('option');
                option.value = stream.index;
                const lang = stream.displayLanguage || stream.language || 'Unknown';
                const title = stream.title ? ` (${stream.title})` : '';
                const forced = stream.isForced ? ' [Forced]' : '';
                option.textContent = `${lang}${title}${forced}`;
                if (stream.isDefault) {
                    option.selected = true;
                }
                subtitleSelect.appendChild(option);
            });
        }

        const audioCount = data.audio ? data.audio.length : 0;
        const subtitleCount = data.subtitles ? data.subtitles.length : 0;

        if (audioCount > 0 || subtitleCount > 0) {
            addSystemMessage(`Found ${audioCount} audio track(s) and ${subtitleCount} subtitle track(s)`);
        }
    } catch (error) {
        audioSelect.innerHTML = '<option value="">Default Audio</option>';
        subtitleSelect.innerHTML = '<option value="none">None</option>';
        addSystemMessage('Could not load stream information');
    }
}

function loadVideo(video) {
    noVideoState.style.display = 'none';
    videoPlayer.style.display = 'block';

    // Destroy previous HLS instance if it exists
    if (hls) {
        hls.destroy();
        hls = null;
    }

    // Clear any previous sources and handlers
    videoElement.onerror = null;
    videoElement.onloadedmetadata = null;
    videoElement.onloadstart = null;
    videoElement.onprogress = null;

    // Load available streams for this video
    loadAvailableStreams(video.item_id);

    // Set video properties
    videoTitle.textContent = video.title;
    videoDescription.textContent = video.overview || '';

    // Update stream selectors if provided
    if (video.audio_index !== undefined) {
        audioSelect.value = video.audio_index === null ? 'none' : video.audio_index;
    }
    if (video.subtitle_index !== undefined) {
        subtitleSelect.value = video.subtitle_index === null ? 'none' : video.subtitle_index;
    }

    // Add load success handler
    videoElement.onloadedmetadata = function() {
        addSystemMessage('Video loaded and ready to play');
    };

    // Check if the video is HLS (.m3u8)
    if (video.stream_url.includes('.m3u8')) {
        // Check if HLS.js is supported
        if (Hls.isSupported()) {
            hls = new Hls({
                debug: false,
                enableWorker: true,
                lowLatencyMode: false,
                backBufferLength: 90,
                fragLoadingTimeOut: 20000,  // 20 seconds for fragment loading (default is 10s)
                fragLoadingMaxRetry: 4,      // Retry up to 4 times
                fragLoadingRetryDelay: 1000, // Wait 1s between retries
                manifestLoadingTimeOut: 10000,
                levelLoadingTimeOut: 10000
            });

            // Attach media element
            hls.attachMedia(videoElement);

            // Handle HLS.js events
            hls.on(Hls.Events.MEDIA_ATTACHED, function() {
                hls.loadSource(video.stream_url);
            });

            hls.on(Hls.Events.MANIFEST_PARSED, function(event, data) {
                // Reset to beginning when loading a new video (unless we're syncing)
                if (!isSyncing) {
                    videoElement.currentTime = 0;
                }
                addSystemMessage('HLS stream ready');
            });

            hls.on(Hls.Events.ERROR, function(event, data) {
                // Handle non-fatal errors (like fragment load timeouts during seeking)
                if (!data.fatal) {
                    if (data.details === 'fragLoadTimeOut' || data.details === 'fragLoadError') {
                        // HLS.js will automatically retry, no action needed
                        return;
                    }
                }

                // Handle fatal errors
                if (data.fatal) {
                    switch(data.type) {
                        case Hls.ErrorTypes.NETWORK_ERROR:
                            addSystemMessage('Network error, attempting recovery...');
                            hls.startLoad();
                            break;
                        case Hls.ErrorTypes.MEDIA_ERROR:
                            addSystemMessage('Media error, attempting recovery...');
                            hls.recoverMediaError();
                            break;
                        default:
                            addSystemMessage('Fatal HLS error: ' + data.type);
                            hls.destroy();
                            break;
                    }
                }
            });

        } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
            // Native HLS support (Safari, some mobile browsers)
            videoElement.src = video.stream_url;
            addSystemMessage('Using native HLS playback');
        } else {
            addSystemMessage('Error: HLS playback not supported in this browser');
        }
    } else {
        // Fallback to direct video source (MP4, etc.)
        videoElement.src = video.stream_url;
        videoElement.load();
    }
}

function updateUserCount() {
    const count = currentUsers.length;
    userCountEl.textContent = count === 1 ? '1 user' : `${count} users`;
}
