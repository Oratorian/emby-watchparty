// chat.js - Chat messaging module
(function() {
    'use strict';
    var S = window.PartyState;

    function sendMessage() {
        var message = S.dom.chatInput.value.trim();
        if (!message) return;

        S.socket.emit('chat_message', {
            party_id: S.partyId,
            message: message
        });

        S.dom.chatInput.value = '';
    }

    function addChatMessage(messageUsername, message) {
        var div = document.createElement('div');
        var isMyMessage = (messageUsername === S.username);
        div.className = isMyMessage ? 'chat-message chat-message-mine' : 'chat-message chat-message-other';

        var usernameSpan = document.createElement('span');
        usernameSpan.className = 'chat-message-username';
        usernameSpan.textContent = messageUsername;

        var messageSpan = document.createElement('span');
        messageSpan.className = 'chat-message-text';
        messageSpan.textContent = message;

        var bubble = document.createElement('div');
        bubble.className = 'chat-message-bubble';
        bubble.appendChild(usernameSpan);
        bubble.appendChild(messageSpan);

        div.appendChild(bubble);

        S.dom.chatMessages.appendChild(div);
        S.dom.chatMessages.scrollTop = S.dom.chatMessages.scrollHeight;
    }

    function addSystemMessage(message) {
        var div = document.createElement('div');
        div.className = 'chat-message chat-message-system';
        div.textContent = message;

        S.dom.chatMessages.appendChild(div);
        S.dom.chatMessages.scrollTop = S.dom.chatMessages.scrollHeight;
    }

    function init() {
        S.dom.sendChatBtn.addEventListener('click', sendMessage);
        S.dom.chatInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });

        S.socket.on('chat_message', function(data) {
            addChatMessage(data.username, data.message);
        });
    }

    window.PartyChat = {
        init: init,
        sendMessage: sendMessage,
        addChatMessage: addChatMessage,
        addSystemMessage: addSystemMessage
    };
})();
