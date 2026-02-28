// ui.js - UI chrome: user count, collapse toggles, resize, fullscreen, autoplay countdown
(function() {
    'use strict';
    var S = window.PartyState;

    function updateUserCount() {
        var count = S.currentUsers.length;
        S.dom.userCountEl.textContent = count === 1 ? '1 user' : count + ' users';
    }

    function handleFullscreenChange() {
        var isFullscreen = !!(
            document.fullscreenElement ||
            document.webkitFullscreenElement ||
            document.mozFullScreenElement ||
            document.msFullscreenElement
        );

        var ve = S.dom.videoElement;
        if (isFullscreen) {
            ve.style.border = 'none';
            ve.style.borderRadius = '0';
            ve.style.outline = 'none';
            ve.style.boxShadow = 'none';
            ve.style.outlineOffset = '0';
        } else {
            ve.style.border = '';
            ve.style.borderRadius = '';
            ve.style.outline = '';
            ve.style.boxShadow = '';
            ve.style.outlineOffset = '';
        }
    }

    function showLibraryAfterVideoEnd() {
        if (S.dom.librarySidebar.classList.contains('hidden')) {
            S.dom.librarySidebar.classList.remove('hidden');
            S.dom.showLibraryBtn.style.display = 'inline-block';
        }
    }

    function startAutoplayCountdown(nextEpisode) {
        console.log('Starting autoplay countdown for:', nextEpisode.Name);

        S.dom.autoplayCountdown.style.display = 'flex';

        document.getElementById('nextEpisodeTitle').textContent = 'Next Episode';
        document.getElementById('nextEpisodeInfo').textContent = nextEpisode.Name;

        var timeLeft = 4;
        document.getElementById('countdownNumber').textContent = timeLeft;

        S.autoplayCountdownTimer = setInterval(function() {
            timeLeft--;
            document.getElementById('countdownNumber').textContent = timeLeft;
            if (timeLeft <= 0) {
                clearInterval(S.autoplayCountdownTimer);
                S.autoplayCountdownTimer = null;
            }
        }, 1000);

        S.autoplayTimeoutId = setTimeout(function() {
            hideAutoplayCountdown();
            window.PartyLibrary.selectVideo(nextEpisode);
            window.PartyChat.addSystemMessage('\uD83C\uDFAC Autoplaying: ' + nextEpisode.Name);
        }, 4000);
    }

    function cancelAutoplay() {
        console.log('Cancelling autoplay');

        if (S.autoplayCountdownTimer) {
            clearInterval(S.autoplayCountdownTimer);
            S.autoplayCountdownTimer = null;
        }

        if (S.autoplayTimeoutId) {
            clearTimeout(S.autoplayTimeoutId);
            S.autoplayTimeoutId = null;
        }

        hideAutoplayCountdown();
        showLibraryAfterVideoEnd();
    }

    function hideAutoplayCountdown() {
        if (S.dom.autoplayCountdown) {
            S.dom.autoplayCountdown.style.display = 'none';
        }
    }

    function init() {
        // Socket handlers
        S.socket.on('user_joined', function(data) {
            S.currentUsers = data.users;
            updateUserCount();

            if (!S.username && data.users.includes(data.username)) {
                S.username = data.username;
            }

            window.PartyChat.addSystemMessage(data.username + ' joined the party');
        });

        S.socket.on('user_left', function(data) {
            if (data.users) {
                S.currentUsers = data.users;
                updateUserCount();
            }
            window.PartyChat.addSystemMessage(data.username + ' left the party');
        });

        S.socket.on('video_ended', function(data) {
            console.log('Video ended notification received');

            if (S.dom.librarySidebar.classList.contains('hidden')) {
                S.dom.librarySidebar.classList.remove('hidden');
                S.dom.showLibraryBtn.style.display = 'inline-block';
            }

            window.PartyChat.addSystemMessage('\uD83C\uDFAC Video ended - Ready for next episode');
        });

        S.socket.on('toggle_library', function(data) {
            console.log('Library toggle received:', data.show);

            if (data.show) {
                S.dom.librarySidebar.classList.remove('hidden');
                S.dom.showLibraryBtn.style.display = 'none';
            } else {
                S.dom.librarySidebar.classList.add('hidden');
                S.dom.showLibraryBtn.style.display = 'inline-block';
            }
        });

        S.socket.on('error', function(data) {
            alert('Error: ' + data.message);
        });

        // Collapse toggles
        S.dom.collapseHeaderBtn.addEventListener('click', function() {
            S.dom.partyHeader.classList.add('collapsed');
            S.dom.expandHeaderBtn.style.display = 'block';
        });

        S.dom.expandHeaderBtn.addEventListener('click', function() {
            S.dom.partyHeader.classList.remove('collapsed');
            S.dom.expandHeaderBtn.style.display = 'none';
        });

        S.dom.collapseChatBtn.addEventListener('click', function() {
            S.dom.chatContainer.classList.add('collapsed');
            S.dom.expandChatBtn.style.display = 'block';
        });

        S.dom.expandChatBtn.addEventListener('click', function() {
            S.dom.chatContainer.classList.remove('collapsed');
            S.dom.expandChatBtn.style.display = 'none';
        });

        S.dom.collapseFooterBtn.addEventListener('click', function() {
            S.dom.videoMeta.classList.toggle('collapsed');
            S.dom.collapseFooterBtn.classList.toggle('collapsed');
            S.dom.collapseFooterBtn.title = S.dom.videoMeta.classList.contains('collapsed') ? 'Expand info' : 'Collapse info';
        });

        // Chat resize
        if (S.dom.chatResizeHandle && S.dom.chatContainer) {
            var isResizing = false;
            var startX = 0;
            var startWidth = 0;

            S.dom.chatResizeHandle.addEventListener('mousedown', function(e) {
                isResizing = true;
                startX = e.clientX;
                startWidth = S.dom.chatContainer.offsetWidth;
                S.dom.chatResizeHandle.classList.add('dragging');
                e.preventDefault();
                document.body.style.userSelect = 'none';
                document.body.style.cursor = 'ew-resize';
            });

            document.addEventListener('mousemove', function(e) {
                if (!isResizing) return;
                var deltaX = startX - e.clientX;
                var newWidth = startWidth + deltaX;
                var constrainedWidth = Math.max(250, Math.min(600, newWidth));
                S.dom.chatContainer.style.width = constrainedWidth + 'px';
            });

            document.addEventListener('mouseup', function() {
                if (isResizing) {
                    isResizing = false;
                    S.dom.chatResizeHandle.classList.remove('dragging');
                    document.body.style.userSelect = '';
                    document.body.style.cursor = '';
                }
            });
        }

        // Fullscreen change
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
        document.addEventListener('mozfullscreenchange', handleFullscreenChange);
        document.addEventListener('MSFullscreenChange', handleFullscreenChange);
    }

    window.PartyUI = {
        init: init,
        updateUserCount: updateUserCount,
        showLibraryAfterVideoEnd: showLibraryAfterVideoEnd,
        startAutoplayCountdown: startAutoplayCountdown,
        cancelAutoplay: cancelAutoplay
    };
})();
