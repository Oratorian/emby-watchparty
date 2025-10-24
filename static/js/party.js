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
const showLibraryBtn = document.getElementById('showLibraryBtn');
const userCountEl = document.getElementById('userCount');
const leavePartyBtn = document.getElementById('leavePartyBtn');
const libraryContent = document.getElementById('libraryContent');
const navBtns = document.querySelectorAll('.nav-btn');
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
const searchInput = document.getElementById('searchInput');
const clearSearchBtn = document.getElementById('clearSearchBtn');
const stopVideoBtn = document.getElementById('stopVideoBtn');

// State
let username = '';
let currentUsers = [];
let isHost = false;
let isSyncing = false;
let lastSyncTime = 0;
let syncThreshold = 0.3; // Only sync if difference is more than 0.3 seconds
// Tighter threshold for better sync accuracy, while still allowing minor buffering differences
let lastSeekBroadcast = 0;
let seekBroadcastDelay = 500; // Throttle seek broadcasts to max once per 500ms
let currentItemId = null;
let currentMediaSourceId = null;
let availableStreams = { audio: [], subtitles: [] };
let lastPlayBroadcast = 0;
let lastPauseBroadcast = 0;
let playPauseThrottle = 300; // Throttle play/pause broadcasts to max once per 300ms
let lastSyncedTime = 0;
let lastSyncType = '';
let isUserSeeking = false;
let seekSettleTimer = null;
let hls = null; // HLS.js instance
let canStopVideo = false; // Track if current user can stop the video
let periodicSyncInterval = null; // Periodic sync check interval
let currentPartyState = null; // Store current party playback state for periodic sync
let playbackStartTime = null; // Track when playback started for drift calculation
let introData = null; // Store intro timing data for current video
let introCheckInterval = null; // Interval for checking if we're in intro

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

// Stop video button
stopVideoBtn.addEventListener('click', () => {
    if (confirm('Are you sure you want to stop the video for everyone?')) {
        socket.emit('stop_video', { party_id: partyId });
    }
});

// Show library button (in header)
if (showLibraryBtn) {
    showLibraryBtn.addEventListener('click', () => {
        librarySidebar.classList.remove('hidden');
        showLibraryBtn.style.display = 'none';
    });
}

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
async function loadSeriesSeasons(seriesId, seriesName) {
    try {
        libraryContent.innerHTML = '<p>Loading seasons...</p>';

        // Get seasons (non-recursive to get only direct children)
        const response = await fetch(`/api/items?parentId=${seriesId}&recursive=false`);
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

        // Check if we have seasons or just episodes
        const items = data.Items || [];
        if (items.length > 0 && items[0].Type === 'Season') {
            // Display seasons
            displayItems(items, 'seasons', seriesName);
        } else {
            // No seasons, display episodes directly
            displayItems(items, 'episodes');
        }
    } catch (error) {
        libraryContent.innerHTML = '<p>Error loading seasons</p>';
    }
}

async function loadSeasonEpisodes(seasonId, seasonName, seriesName) {
    try {
        libraryContent.innerHTML = '<p>Loading episodes...</p>';

        const response = await fetch(`/api/items?parentId=${seasonId}&recursive=false`);
        const data = await response.json();

        // Add a back button
        libraryContent.innerHTML = '';

        const backBtn = document.createElement('div');
        backBtn.className = 'library-item';
        backBtn.style.background = '#667eea';
        backBtn.style.cursor = 'pointer';
        backBtn.innerHTML = `
            <div class="library-item-info">
                <div class="library-item-title">← Back to Seasons</div>
                <div class="library-item-meta">Return to ${seriesName}</div>
            </div>
        `;
        backBtn.addEventListener('click', () => {
            // Go back to season view - need to get series ID from season
            fetch(`/api/item/${seasonId}`)
                .then(res => res.json())
                .then(season => {
                    if (season.SeriesId) {
                        loadSeriesSeasons(season.SeriesId, seriesName);
                    } else {
                        loadLibraries();
                    }
                })
                .catch(() => loadLibraries());
        });
        libraryContent.appendChild(backBtn);

        // Show season title
        const titleDiv = document.createElement('div');
        titleDiv.style.padding = '1rem';
        titleDiv.style.color = '#667eea';
        titleDiv.style.fontWeight = 'bold';
        titleDiv.style.fontSize = '1.1rem';
        titleDiv.textContent = `${seriesName} - ${seasonName}`;
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
function displayItems(items, context = 'library', seriesName = null) {
    if (items && items.length > 0) {
        libraryContent.innerHTML = '';

        let displayableItems;

        if (context === 'library') {
            // When browsing a library, show Series and Movies, but NOT individual Episodes
            displayableItems = items.filter(item =>
                item.Type === 'Movie' || item.Type === 'Series' || item.Type === 'Video'
            );
        } else if (context === 'seasons') {
            // When showing seasons, show all Season items
            displayableItems = items.filter(item => item.Type === 'Season');
        } else {
            // When browsing specific content, show playable items
            displayableItems = items.filter(item =>
                item.Type === 'Movie' || item.Type === 'Episode' || item.Type === 'Video'
            );
        }

        if (displayableItems.length > 0) {
            displayableItems.forEach(item => {
                const itemEl = createLibraryItem(item, () => {
                    // If it's a Series, load its seasons
                    if (item.Type === 'Series') {
                        loadSeriesSeasons(item.Id, item.Name);
                    } else if (item.Type === 'Season') {
                        // Load episodes from this season
                        loadSeasonEpisodes(item.Id, item.Name, seriesName);
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
    addSystemMessage(`${username} selected ${item.Name}`);

    // Auto-hide library sidebar when video is selected
    const sidebar = document.getElementById('librarySidebar');
    if (sidebar && !sidebar.classList.contains('hidden')) {
        sidebar.classList.add('hidden');

        // Show the "Show Library" button in header
        if (showLibraryBtn) {
            showLibraryBtn.style.display = 'inline-block';
        }
    }

    socket.emit('select_video', {
        party_id: partyId,
        item_id: item.Id,
        item_name: item.Name,
        item_overview: item.Overview || ''
    });

    // Mark that this user selected the video (after emit so it happens first)
    canStopVideo = true;
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

    // Immediately update subtitles locally (without reloading video)
    loadSubtitleTrack(subtitleIndex);

    // Also notify server to sync with other users (server will send streams_changed)
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

    // If this is us joining and we don't have a username yet, use the one from server
    if (!username && data.users.includes(data.username)) {
        username = data.username;
    }

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

        // Store party state for periodic sync
        if (data.playback_state) {
            currentPartyState = {
                time: data.playback_state.time,
                playing: data.playback_state.playing
            };
        }

        // Improved browser reload handling: sync to current time even if it's small
        // Only skip sync if time is exactly 0 (brand new video)
        if (data.playback_state && data.playback_state.time >= 0) {
            isSyncing = true;

            // Wait for video to be loaded before syncing
            videoElement.addEventListener('loadedmetadata', function syncAfterLoad() {
                // Ensure video is not muted
                videoElement.muted = false;

                // Set to the exact time from server
                videoElement.currentTime = data.playback_state.time;

                if (data.playback_state.playing) {
                    videoElement.play().then(() => {
                        setTimeout(() => {
                            isSyncing = false;
                            startPeriodicSync(); // Start periodic sync check
                        }, 100);
                    }).catch(() => {
                        setTimeout(() => {
                            isSyncing = false;
                            startPeriodicSync(); // Start periodic sync check
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
    // canStopVideo is set to true in selectVideo() when this user selects
    // When this event arrives:
    // - If canStopVideo is true, this user selected it, keep it true
    // - If canStopVideo is false, someone else selected it, keep it false
    // This way only the user who selected can see the stop button
    loadVideo(data.video);
});

socket.on('video_stopped', (data) => {
    // Clear the video player and show no video state
    if (hls) {
        hls.destroy();
        hls = null;
    }

    videoElement.pause();
    videoElement.src = '';
    videoPlayer.style.display = 'none';
    noVideoState.style.display = 'flex';

    // Show library sidebar again for all users
    const sidebar = document.getElementById('librarySidebar');
    if (sidebar && sidebar.classList.contains('hidden')) {
        sidebar.classList.remove('hidden');

        // Hide the "Show Library" button since sidebar is now visible
        if (showLibraryBtn) {
            showLibraryBtn.style.display = 'none';
        }
    }

    // Reset state
    canStopVideo = false;
    currentItemId = null;
    currentPartyState = null;

    // Stop periodic sync check
    stopPeriodicSync();

    // Show message in chat
    addSystemMessage(data.message);
});

socket.on('streams_changed', (data) => {
    const wasPlaying = !videoElement.paused;
    const currentTime = videoElement.currentTime;

    // Update current video metadata
    if (data.video.media_source_id) {
        currentMediaSourceId = data.video.media_source_id;
    }

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

                // Load subtitle track if one is selected
                if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                    loadSubtitleTrack(data.video.subtitle_index);
                }

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

                // Load subtitle track if one is selected
                if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                    loadSubtitleTrack(data.video.subtitle_index);
                }

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

            // Load subtitle track if one is selected
            if (data.video.subtitle_index !== undefined && data.video.subtitle_index !== null) {
                loadSubtitleTrack(data.video.subtitle_index);
            }

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

    // Update party state for periodic sync
    currentPartyState = { time: data.time, playing: true };
    playbackStartTime = Date.now(); // Track when playback started

    // Start periodic sync if not already running
    if (!periodicSyncInterval) {
        startPeriodicSync();
    }

    processSyncCommand({ type: 'play', time: data.time });
});

socket.on('pause', (data) => {
    // Ignore duplicate commands for the same time
    if (Math.abs(data.time - lastSyncedTime) < 0.1 && lastSyncType === 'pause') {
        return;
    }

    lastSyncedTime = data.time;
    lastSyncType = 'pause';

    // Update party state for periodic sync
    currentPartyState = { time: data.time, playing: false };
    playbackStartTime = null; // Clear playback start time when paused

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

    // Update party state for periodic sync
    currentPartyState = { time: data.time, playing: data.playing || false };

    // Reset playback start time if resuming after seek
    if (data.playing) {
        playbackStartTime = Date.now();
    } else {
        playbackStartTime = null;
    }

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
        if (data.media_source_id) {
            currentMediaSourceId = data.media_source_id;
        }

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
                // Don't auto-select default subtitles - let users opt-in
                // (Removed: if (stream.isDefault) { option.selected = true; })
                subtitleSelect.appendChild(option);
            });
        }
        // Ensure "None" is selected by default
        subtitleSelect.value = 'none';

        // Don't spam chat with track counts - users can see in dropdowns
    } catch (error) {
        audioSelect.innerHTML = '<option value="">Default Audio</option>';
        subtitleSelect.innerHTML = '<option value="none">None</option>';
        // Don't show error message - not critical, users can still watch
    }
}

function loadSubtitleTrack(subtitleIndex) {
    // First, disable all text tracks
    for (let i = 0; i < videoElement.textTracks.length; i++) {
        videoElement.textTracks[i].mode = 'disabled';
    }

    // Remove all existing text track elements
    while (videoElement.textTracks.length > 0) {
        const track = videoElement.textTracks[0];
        const trackElement = Array.from(videoElement.querySelectorAll('track')).find(t => t.track === track);
        if (trackElement) {
            videoElement.removeChild(trackElement);
        }
    }

    // If subtitle index is 'none' or null, just leave them removed
    if (!subtitleIndex || subtitleIndex === 'none' || subtitleIndex === -1) {
        return;
    }

    // Find the subtitle in available streams
    const subtitle = availableStreams.subtitles?.find(s => s.index === parseInt(subtitleIndex));

    // Only load if it's a text subtitle stream
    if (subtitle && subtitle.isTextSubtitleStream && currentMediaSourceId) {
        const track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = subtitle.displayLanguage || subtitle.language || 'Unknown';
        track.srclang = subtitle.language || 'und';
        track.src = `/api/subtitles/${currentItemId}/${currentMediaSourceId}/${subtitleIndex}`;
        track.default = true;

        track.addEventListener('load', function() {
            // Ensure the track is showing
            if (this.track.mode !== 'showing') {
                this.track.mode = 'showing';
            }
        });

        videoElement.appendChild(track);
    }
}

function loadVideo(video) {
    noVideoState.style.display = 'none';
    videoPlayer.style.display = 'block';

    // Auto-hide library sidebar when video is loaded for all users
    const sidebar = document.getElementById('librarySidebar');
    if (sidebar && !sidebar.classList.contains('hidden')) {
        sidebar.classList.add('hidden');

        // Show the "Show Library" button in header
        if (showLibraryBtn) {
            showLibraryBtn.style.display = 'inline-block';
        }
    }

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

    // Store current video metadata
    currentItemId = video.item_id;
    currentMediaSourceId = video.media_source_id;

    // Load available streams for this video
    loadAvailableStreams(video.item_id);

    // Set video properties
    videoTitle.textContent = video.title;
    videoDescription.textContent = video.overview || '';

    // Show/hide stop button based on whether this user selected the video
    if (canStopVideo) {
        stopVideoBtn.style.display = 'inline-block';
    } else {
        stopVideoBtn.style.display = 'none';
    }

    // Update stream selectors if provided
    if (video.audio_index !== undefined) {
        audioSelect.value = video.audio_index === null ? 'none' : video.audio_index;
    }
    if (video.subtitle_index !== undefined) {
        subtitleSelect.value = video.subtitle_index === null ? 'none' : video.subtitle_index;
    }

    // Video ready handler - load subtitles once metadata is loaded
    videoElement.onloadedmetadata = function() {
        // Ensure video is not muted (browser autoplay policies may force mute)
        videoElement.muted = false;

        // Load subtitle track if one is selected
        if (video.subtitle_index !== undefined && video.subtitle_index !== null) {
            loadSubtitleTrack(video.subtitle_index);
        }
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
                // Ensure video is not muted
                videoElement.muted = false;

                // Reset to beginning when loading a new video (unless we're syncing)
                if (!isSyncing) {
                    videoElement.currentTime = 0;
                }
                // Stream is ready - no message needed
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
            // Native HLS playback - no message needed
        } else {
            addSystemMessage('Error: HLS playback not supported in this browser');
        }
    } else {
        // Fallback to direct video source (MP4, etc.)
        videoElement.src = video.stream_url;
        videoElement.load();
    }

    // Load intro data for this video
    loadIntroData(video.item_id);
}

// Load intro timing data for a video
async function loadIntroData(itemId) {
    try {
        const response = await fetch(`/api/intro/${itemId}`);
        const data = await response.json();

        if (data.hasIntro) {
            introData = data;
            console.log(`Intro detected: ${data.start.toFixed(2)}s - ${data.end.toFixed(2)}s (${data.duration.toFixed(2)}s)`);
            startIntroCheck();
        } else {
            introData = null;
            stopIntroCheck();
            hideSkipIntroButton();
        }
    } catch (error) {
        console.error('Failed to load intro data:', error);
        introData = null;
        stopIntroCheck();
        hideSkipIntroButton();
    }
}

// Check if current playback time is within intro range
function checkIntroButton() {
    if (!introData || !videoElement || !videoElement.src) {
        hideSkipIntroButton();
        return;
    }

    const currentTime = videoElement.currentTime;
    const skipButton = document.getElementById('skipIntroBtn');

    // Show button if we're within intro range (add 5s buffer at start to give user time to see it)
    if (currentTime >= (introData.start + 5) && currentTime < introData.end) {
        if (skipButton) {
            skipButton.style.display = 'block';
        }
    } else {
        hideSkipIntroButton();
    }
}

// Hide skip intro button
function hideSkipIntroButton() {
    const skipButton = document.getElementById('skipIntroBtn');
    if (skipButton) {
        skipButton.style.display = 'none';
    }
}

// Skip to end of intro
function skipIntro() {
    if (!introData) return;

    console.log(`Skipping intro to ${introData.end.toFixed(2)}s`);

    // Prevent sync correction during skip
    isSyncing = true;

    // Seek to end of intro
    videoElement.currentTime = introData.end;

    // Hide button
    hideSkipIntroButton();

    // Re-enable sync after a short delay
    setTimeout(() => {
        isSyncing = false;
    }, 1000);
}

// Start checking for intro timeframe
function startIntroCheck() {
    // Clear any existing interval
    stopIntroCheck();

    // Check every 500ms if we're in intro range
    introCheckInterval = setInterval(checkIntroButton, 500);
}

// Stop checking for intro
function stopIntroCheck() {
    if (introCheckInterval) {
        clearInterval(introCheckInterval);
        introCheckInterval = null;
    }
}

// Note: Skip Intro button only works in normal (non-fullscreen) mode
// This is a browser limitation - custom buttons cannot appear inside fullscreen <video> elements
// To support fullscreen, a custom video player with custom controls would be needed

function updateUserCount() {
    const count = currentUsers.length;
    userCountEl.textContent = count === 1 ? '1 user' : `${count} users`;
}

// Chat resize functionality
const chatContainer = document.getElementById('chatContainer');
const chatResizeHandle = document.getElementById('chatResizeHandle');

if (chatResizeHandle && chatContainer) {
    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    chatResizeHandle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = chatContainer.offsetWidth;
        chatResizeHandle.classList.add('dragging');

        // Prevent text selection while dragging
        e.preventDefault();
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'ew-resize';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        // Calculate new width (dragging left increases width, right decreases)
        const deltaX = startX - e.clientX;
        const newWidth = startWidth + deltaX;

        // Apply constraints (250px - 600px)
        const minWidth = 250;
        const maxWidth = 600;
        const constrainedWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));

        chatContainer.style.width = `${constrainedWidth}px`;
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            chatResizeHandle.classList.remove('dragging');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        }
    });
}

// Periodic sync check to correct drift over time
function startPeriodicSync() {
    // Clear any existing interval
    if (periodicSyncInterval) {
        clearInterval(periodicSyncInterval);
    }

    // Check sync every 5 seconds
    periodicSyncInterval = setInterval(() => {
        // Only sync if we have a video loaded and party state
        if (!currentPartyState || !videoElement.src || videoElement.paused) {
            return;
        }

        // Don't sync if user is actively seeking
        if (isUserSeeking || isSyncing) {
            return;
        }

        // Calculate expected time based on when playback started
        let expectedTime = currentPartyState.time;
        if (currentPartyState.playing && playbackStartTime) {
            const elapsedSeconds = (Date.now() - playbackStartTime) / 1000;
            expectedTime = currentPartyState.time + elapsedSeconds;
        }

        // Calculate time difference against expected time (not static party state)
        const timeDiff = Math.abs(videoElement.currentTime - expectedTime);

        // If drift is significant, correct it
        if (timeDiff > syncThreshold && currentPartyState.playing) {
            console.log(`Periodic sync: correcting ${timeDiff.toFixed(2)}s drift (expected: ${expectedTime.toFixed(2)}, actual: ${videoElement.currentTime.toFixed(2)})`);
            isSyncing = true;
            videoElement.currentTime = expectedTime;

            // Resume playing after sync
            videoElement.play().then(() => {
                setTimeout(() => { isSyncing = false; }, 300);
            }).catch(() => {
                setTimeout(() => { isSyncing = false; }, 300);
            });
        }
    }, 5000); // Check every 5 seconds
}

function stopPeriodicSync() {
    if (periodicSyncInterval) {
        clearInterval(periodicSyncInterval);
        periodicSyncInterval = null;
    }
}

// Search functionality
let searchTimeout;

if (searchInput) {
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.trim();

        // Show/hide clear button
        if (clearSearchBtn) {
            clearSearchBtn.style.display = query ? 'flex' : 'none';
        }

        // Debounce search
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            if (query.length >= 2) {
                performSearch(query);
            } else if (query.length === 0) {
                // Clear search - go back to libraries
                loadLibraries();
            }
        }, 300);
    });

    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const query = e.target.value.trim();
            if (query.length >= 2) {
                clearTimeout(searchTimeout);
                performSearch(query);
            }
        }
    });
}

if (clearSearchBtn) {
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        loadLibraries();
        searchInput.focus();
    });
}

async function performSearch(query) {
    try {
        libraryContent.innerHTML = '<p>Searching...</p>';

        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();

        libraryContent.innerHTML = '';

        // Add search header
        const headerDiv = document.createElement('div');
        headerDiv.style.padding = '1rem';
        headerDiv.style.color = '#667eea';
        headerDiv.style.fontWeight = 'bold';
        headerDiv.style.fontSize = '1.1rem';
        headerDiv.textContent = `Search results for "${query}"`;
        libraryContent.appendChild(headerDiv);

        if (data.Items && data.Items.length > 0) {
            displayItems(data.Items, 'library');
        } else {
            const noResults = document.createElement('p');
            noResults.textContent = 'No results found';
            noResults.style.padding = '1rem';
            noResults.style.color = '#aaa';
            libraryContent.appendChild(noResults);
        }
    } catch (error) {
        libraryContent.innerHTML = '<p>Error performing search</p>';
    }
}
