<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'

const router = useRouter()
const partyCode = ref('')
const status = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/api/party/static-session')
    const data = await res.json()
    if (data.party_id) {
      router.replace(`/party/${data.party_id}`)
    }
  } catch {
    // No static session or error, show normal index
  }
})

async function createParty() {
  status.value = 'Creating party...'
  const data = await api.createParty()
  if (data.party_id) {
    router.push(`/party/${data.party_id}`)
  } else {
    status.value = 'Error creating party'
  }
}

function joinParty() {
  const code = partyCode.value.trim().replace(/[^a-zA-Z0-9]/g, '')
  if (!code) {
    status.value = 'Please enter a valid party code'
    return
  }
  router.push(`/party/${code}`)
}
</script>

<template>
  <div class="index-page">
    <div class="hero">
      <div class="hero-badge badge badge-primary">Watch Party 2.0</div>
      <h1>Emby Watch Party</h1>
      <p class="hero-tagline">Watch together, wherever you are</p>
    </div>

    <main class="action-cards">
      <div class="action-card card card-interactive" @click="createParty">
        <div class="card-icon">+</div>
        <h2>Create Party</h2>
        <p>Start a new watch party and invite friends to join</p>
        <button class="btn btn-primary">Create Party</button>
      </div>

      <div class="action-card card">
        <div class="card-icon">#</div>
        <h2>Join Party</h2>
        <p>Enter a party code to join an existing watch party</p>
        <div class="join-form">
          <input
            v-model="partyCode"
            @keypress.enter="joinParty"
            placeholder="Party code"
            type="text"
            maxlength="6"
          />
          <button @click="joinParty" class="btn btn-secondary">Join</button>
        </div>
      </div>
    </main>

    <div v-if="status" class="status-msg">{{ status }}</div>

    <footer class="index-footer">
      <router-link to="/version">Version Info</router-link>
      <span class="dot">&middot;</span>
      <a href="https://ko-fi.com/jedziah" target="_blank" rel="noopener">Support on Ko-fi</a>
    </footer>
  </div>
</template>

<style scoped>
.index-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-xl);
}

.hero {
  text-align: center;
  margin-bottom: var(--space-2xl);
}

.hero-badge {
  margin-bottom: var(--space-md);
}

.hero h1 {
  font-size: 2.5rem;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-primary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-tagline {
  font-size: 1.1rem;
  color: var(--text-secondary);
  margin-top: var(--space-sm);
}

.action-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-lg);
  max-width: 700px;
  width: 100%;
}

.action-card {
  text-align: center;
  padding: var(--space-xl);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
}

.card-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent-primary);
  background: var(--accent-primary-dim);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-sm);
}

.action-card h2 {
  font-size: 1.2rem;
}

.action-card p {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin-bottom: var(--space-sm);
}

.join-form {
  display: flex;
  gap: var(--space-sm);
  width: 100%;
}

.join-form input {
  flex: 1;
  text-align: center;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  font-weight: 600;
  min-width: 0;
}

/* Placeholder text bypasses the uppercase + wide letter-spacing
   styling that real codes get. Otherwise the placeholder renders
   wider than the input and Chrome shows truncation artifacts where
   the last characters get clipped. */
.join-form input::placeholder {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
  font-size: 0.9em;
}

.status-msg {
  margin-top: var(--space-lg);
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.index-footer {
  margin-top: var(--space-2xl);
  font-size: 0.85rem;
  color: var(--text-muted);
  display: flex;
  gap: var(--space-sm);
  align-items: center;
}

.dot { opacity: 0.4; }

@media (max-width: 600px) {
  .action-cards {
    grid-template-columns: 1fr;
  }
  .hero h1 {
    font-size: 1.8rem;
  }
}
</style>
