// party.js - Entry point and orchestrator
(function() {
    'use strict';
    var S = window.PartyState;

    // Populate DOM element cache (script loads at bottom of body, DOM is ready)
    S.dom = {
        usernameModal: document.getElementById('usernameModal'),
        usernameInput: document.getElementById('usernameInput'),
        joinBtn: document.getElementById('joinBtn'),
        partyCodeEl: document.getElementById('partyCode'),
        copyCodeBtn: document.getElementById('copyCodeBtn'),
        showLibraryBtn: document.getElementById('showLibraryBtn'),
        hideLibraryBtn: document.getElementById('hideLibraryBtn'),
        userCountEl: document.getElementById('userCount'),
        leavePartyBtn: document.getElementById('leavePartyBtn'),
        libraryContent: document.getElementById('libraryContent'),
        navBtns: document.querySelectorAll('.nav-btn'),
        librarySidebar: document.getElementById('librarySidebar'),
        noVideoState: document.getElementById('noVideoState'),
        videoPlayer: document.getElementById('videoPlayer'),
        videoElement: document.getElementById('videoElement'),
        videoTitle: document.getElementById('videoTitle'),
        videoDescription: document.getElementById('videoDescription'),
        chatMessages: document.getElementById('chatMessages'),
        chatInput: document.getElementById('chatInput'),
        sendChatBtn: document.getElementById('sendChatBtn'),
        audioSelect: document.getElementById('audioSelect'),
        subtitleSelect: document.getElementById('subtitleSelect'),
        searchInput: document.getElementById('searchInput'),
        clearSearchBtn: document.getElementById('clearSearchBtn'),
        stopVideoBtn: document.getElementById('stopVideoBtn'),
        autoplayToggle: document.getElementById('autoplayToggle'),
        autoplayCountdown: document.getElementById('autoplayCountdown'),
        cancelAutoplayBtn: document.getElementById('cancelAutoplayBtn'),
        chatContainer: document.getElementById('chatContainer'),
        chatResizeHandle: document.getElementById('chatResizeHandle'),
        collapseHeaderBtn: document.getElementById('collapseHeaderBtn'),
        expandHeaderBtn: document.getElementById('expandHeaderBtn'),
        partyHeader: document.getElementById('partyHeader'),
        collapseChatBtn: document.getElementById('collapseChatBtn'),
        expandChatBtn: document.getElementById('expandChatBtn'),
        collapseFooterBtn: document.getElementById('collapseFooterBtn'),
        videoMeta: document.getElementById('videoMeta'),
        skipIntroBtn: document.getElementById('skipIntroBtn')
    };

    // Initialize all modules (order: Chat first since others use addSystemMessage, UI before Video for autoplay)
    window.PartyChat.init();
    window.PartySync.init();
    window.PartyLibrary.init();
    window.PartyUI.init();
    window.PartyVideo.init();

    // --- Join flow ---
    S.dom.usernameModal.style.display = 'flex';

    S.dom.joinBtn.addEventListener('click', function() {
        S.username = S.dom.usernameInput.value.trim();
        S.dom.usernameModal.style.display = 'none';
        S.socket.emit('join_party', {
            party_id: S.partyId,
            username: S.username
        });
        window.PartyLibrary.restoreLibraryState();
    });

    S.dom.usernameInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') S.dom.joinBtn.click();
    });

    // --- Copy party code ---
    S.dom.copyCodeBtn.addEventListener('click', function() {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(S.partyId).then(function() {
                S.dom.copyCodeBtn.textContent = 'Copied!';
                setTimeout(function() { S.dom.copyCodeBtn.textContent = 'Copy'; }, 2000);
            }).catch(function() {
                fallbackCopyToClipboard(S.partyId);
            });
        } else {
            fallbackCopyToClipboard(S.partyId);
        }
    });

    function fallbackCopyToClipboard(text) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();

        try {
            document.execCommand('copy');
            S.dom.copyCodeBtn.textContent = 'Copied!';
            setTimeout(function() { S.dom.copyCodeBtn.textContent = 'Copy'; }, 2000);
        } catch (err) {
            var range = document.createRange();
            range.selectNode(S.dom.partyCodeEl);
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
            alert('Party code selected. Press Ctrl+C (or Cmd+C on Mac) to copy.');
        }

        document.body.removeChild(textarea);
    }

    // --- Leave party ---
    S.dom.leavePartyBtn.addEventListener('click', function() {
        if (confirm('Are you sure you want to leave the party?')) {
            S.socket.emit('leave_party', { party_id: S.partyId });
            window.location.href = S.appPrefix + '/';
        }
    });

    // --- Stop video ---
    S.dom.stopVideoBtn.addEventListener('click', function() {
        if (confirm('Are you sure you want to stop the video for everyone?')) {
            S.socket.emit('stop_video', { party_id: S.partyId });
        }
    });

    // --- Autoplay toggle ---
    if (S.dom.autoplayToggle) {
        S.dom.autoplayToggle.addEventListener('click', function() {
            S.autoplayEnabled = !S.autoplayEnabled;
            S.dom.autoplayToggle.dataset.enabled = S.autoplayEnabled;
            S.dom.autoplayToggle.querySelector('.toggle-text').textContent = S.autoplayEnabled ? 'ON' : 'OFF';
            if (!S.autoplayEnabled) {
                window.PartyUI.cancelAutoplay();
            }
            window.PartyChat.addSystemMessage('Play next Episode automatically ' + (S.autoplayEnabled ? 'enabled' : 'disabled'));
        });
    }

    // --- Cancel autoplay button ---
    if (S.dom.cancelAutoplayBtn) {
        S.dom.cancelAutoplayBtn.addEventListener('click', function() {
            window.PartyUI.cancelAutoplay();
            window.PartyChat.addSystemMessage('Play next Episode automatically cancelled');
        });
    }

    // --- Show/hide library ---
    if (S.dom.showLibraryBtn) {
        S.dom.showLibraryBtn.addEventListener('click', function() {
            S.socket.emit('toggle_library', { party_id: S.partyId, show: true });
        });
    }

    if (S.dom.hideLibraryBtn) {
        S.dom.hideLibraryBtn.addEventListener('click', function() {
            S.socket.emit('toggle_library', { party_id: S.partyId, show: false });
        });
    }
})();
