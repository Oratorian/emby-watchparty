<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSocketStore } from '@/stores/socket'
import { usePartyStore } from '@/stores/party'

const route = useRoute()
const router = useRouter()
const socket = useSocketStore()
const party = usePartyStore()

const usernameInput = ref('')
const joined = ref(false)
const chatMessages = ref<Array<{ username: string; message: string; timestamp: string; system?: boolean }>>([])
const chatInput = ref('')

const STORAGE_KEY = 'emby-watchparty-username'

onMounted(() => {
  socket.connect()
  party.setupListeners()

  // Chat message handler
  socket.on('chat_message', (data: any) => {
    chatMessages.value.push(data)
  })

  // Auto-join with saved username
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    joinWithName(saved)
  }
})

onUnmounted(() => {
  party.leave()
})

function joinWithName(name: string) {
  const id = route.params.id as string
  if (!name) name = ''
  party.join(id, name)
  if (name) localStorage.setItem(STORAGE_KEY, name)
  joined.value = true
}

function submitJoin() {
  joinWithName(usernameInput.value.trim())
}

function sendChat() {
  if (!chatInput.value.trim() || !party.partyId) return
  socket.emit('chat_message', {
    party_id: party.partyId,
    message: chatInput.value.trim(),
  })
  chatInput.value = ''
}

function leaveParty() {
  party.leave()
  router.push('/')
}
</script>

<template>
  <!-- Username modal -->
  <div v-if="!joined" class="modal-overlay">
    <div class="modal-card">
      <h2>Join Watch Party</h2>
      <p>Enter your name (or leave blank for random name):</p>
      <input v-model="usernameInput" @keypress.enter="submitJoin" placeholder="Your name (optional)" />
      <button @click="submitJoin" class="btn btn-primary">Join</button>
    </div>
  </div>

  <!-- Party room -->
  <div v-else class="party-container">
    <header class="party-header">
      <div>
        <strong>Party: {{ route.params.id }}</strong>
        <span class="user-count">{{ party.userCount }} users</span>
      </div>
      <button @click="leaveParty" class="btn btn-small btn-danger">Leave</button>
    </header>

    <div class="party-content">
      <!-- Video area -->
      <main class="video-area">
        <div v-if="!party.currentVideo" class="no-video">
          <h2>No video selected</h2>
          <p>Browse the library and select a video to start watching together</p>
        </div>
        <div v-else class="video-player">
          <video id="videoElement" controls width="100%"></video>
          <h3>{{ party.currentVideo.title }}</h3>
        </div>
      </main>

      <!-- Chat -->
      <aside class="chat-panel">
        <div class="chat-header"><h3>Chat</h3></div>
        <div class="chat-messages">
          <div v-for="(msg, i) in chatMessages" :key="i" class="chat-msg">
            <strong>{{ msg.username }}:</strong> {{ msg.message }}
          </div>
        </div>
        <div class="chat-input">
          <input v-model="chatInput" @keypress.enter="sendChat" placeholder="Type a message..." />
          <button @click="sendChat" class="btn btn-small">Send</button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.7); z-index: 1000;
}
.modal-card {
  background: var(--bg-secondary, #1a1a2e);
  padding: 2rem; border-radius: 8px; text-align: center;
  max-width: 400px; width: 90%;
}
.modal-card input {
  width: 100%; padding: 0.75rem; margin: 1rem 0; box-sizing: border-box;
  border: 1px solid var(--cyber-primary, #6c63ff); border-radius: 4px;
  background: var(--bg-primary, #0f0f23); color: var(--text-primary, #fff);
}
.party-container { display: flex; flex-direction: column; height: 100vh; }
.party-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.5rem 1rem; background: var(--bg-secondary, #1a1a2e);
}
.user-count { margin-left: 1rem; color: var(--cyber-gold, #ffbe0b); }
.party-content { display: flex; flex: 1; overflow: hidden; }
.video-area { flex: 1; padding: 1rem; overflow: auto; }
.no-video { text-align: center; padding: 4rem 1rem; opacity: 0.6; }
.chat-panel {
  width: 300px; display: flex; flex-direction: column;
  background: var(--bg-secondary, #1a1a2e); border-left: 1px solid var(--cyber-border, #333);
}
.chat-header { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--cyber-border, #333); }
.chat-header h3 { margin: 0; }
.chat-messages { flex: 1; overflow-y: auto; padding: 0.5rem 0.75rem; font-size: 0.9rem; }
.chat-msg { margin-bottom: 0.3rem; }
.chat-input { display: flex; padding: 0.5rem; gap: 0.5rem; }
.chat-input input {
  flex: 1; padding: 0.4rem; border: 1px solid var(--cyber-primary, #6c63ff);
  border-radius: 4px; background: var(--bg-primary, #0f0f23); color: var(--text-primary, #fff);
}
</style>
