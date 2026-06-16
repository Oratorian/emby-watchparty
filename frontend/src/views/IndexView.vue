<script setup lang="ts">
import { ref, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { getHiddenParties } from '@/utils/hiddenParties'

// Modal is only opened in the REQUIRE_LOGIN=true create flow,
// so defer loading until the user actually clicks Create.
const EmbyLoginModal = defineAsyncComponent(
  () => import('@/components/EmbyLoginModal.vue'),
)

const router = useRouter()
const auth = useAuthStore()
const partyCode = ref('')
const status = ref('')

// Active-party listing (only shown when REQUIRE_LOGIN is off). Polled so
// parties appear / disappear and the "now watching" title stays current.
interface ActiveParty {
  code: string
  title: string | null
  user_count: number
  playing: boolean
  locked: boolean
}
const parties = ref<ActiveParty[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadParties() {
  if (auth.requireLogin) {
    parties.value = []
    return
  }
  try {
    const data = await api.listParties()
    const hidden = getHiddenParties()
    parties.value = (data.parties || []).filter((p: ActiveParty) => !hidden.includes(p.code))
  } catch {
    /* ignore transient errors; the next poll retries */
  }
}

function joinListedParty(code: string) {
  // Reuses the normal join flow: a party that is mid-playback triggers
  // the late-joiner vote; an idle one joins straight away.
  router.push(`/party/${code}`)
}

// REQUIRE_LOGIN=true create flow: open the Emby login modal first,
// then post the credentials with /api/party/create so the creator
// becomes host atomically.
const showCreateModal = ref(false)
const createBusy = ref(false)
const createError = ref<string | null>(null)

const CLIENT_ID_STORAGE_KEY = 'emby-watchparty-client-id'

function getClientId(): string {
  let id = localStorage.getItem(CLIENT_ID_STORAGE_KEY)
  if (id) return id
  id = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  localStorage.setItem(CLIENT_ID_STORAGE_KEY, id)
  return id
}

onMounted(async () => {
  try {
    await auth.refresh()
  } catch { /* ignore */ }
  try {
    const res = await fetch('/api/party/static-session')
    const data = await res.json()
    if (data.party_id) {
      router.replace(`/party/${data.party_id}`)
      return
    }
  } catch {
    // No static session or error, show normal index
  }
  loadParties()
  pollTimer = setInterval(loadParties, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function createParty() {
  status.value = ''
  createError.value = null
  if (auth.requireLogin) {
    showCreateModal.value = true
    return
  }
  status.value = 'Creating party...'
  const data = await api.createParty({ client_id: getClientId() })
  if (data.party_id) {
    router.push(`/party/${data.party_id}`)
  } else {
    status.value = data.message || 'Error creating party'
  }
}

async function submitCreateLogin(payload: { username: string; password: string }) {
  createBusy.value = true
  createError.value = null
  try {
    const data = await api.createParty({
      client_id: getClientId(),
      display_name: payload.username,
      username: payload.username,
      password: payload.password,
    })
    if (data.party_id) {
      showCreateModal.value = false
      router.push(`/party/${data.party_id}`)
    } else {
      createError.value = data.message || 'Could not create the party'
    }
  } finally {
    createBusy.value = false
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

    <section v-if="!auth.requireLogin && parties.length" class="active-parties">
      <h2 class="ap-heading">Active parties</h2>
      <ul class="ap-list">
        <li
          v-for="p in parties"
          :key="p.code"
          class="ap-item card card-interactive"
          @click="joinListedParty(p.code)"
        >
          <div class="ap-now">
            <span class="ap-label">{{ p.playing ? 'Now watching' : 'In lobby' }}</span>
            <span class="ap-title">{{ p.playing ? p.title : 'No video selected yet' }}</span>
          </div>
          <div class="ap-meta">
            <span class="ap-count">{{ p.user_count }} {{ p.user_count === 1 ? 'person' : 'people' }}</span>
            <span v-if="p.locked" class="ap-badge">locked</span>
            <span class="ap-code">{{ p.code }}</span>
          </div>
        </li>
      </ul>
      <p class="ap-hint">Joining a party that is mid-playback asks the current watchers to let you in.</p>
    </section>

    <div v-if="status" class="status-msg">{{ status }}</div>

    <EmbyLoginModal
      v-if="showCreateModal"
      title="Login to Create a Party"
      description="Emby login is required to start a new watch party. Spectators will only need the party code."
      submit-label="Create Party"
      :busy="createBusy"
      :error-message="createError"
      @submit="submitCreateLogin"
      @cancel="showCreateModal = false"
    />

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

/* ─── Active parties ─── */
.active-parties {
  margin-top: var(--space-2xl);
  width: 100%;
  max-width: 700px;
}

.ap-heading {
  font-size: 1.05rem;
  margin-bottom: var(--space-md);
  color: var(--text-secondary);
  text-align: center;
}

.ap-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.ap-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  cursor: pointer;
}

.ap-now {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.ap-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent-secondary);
}

.ap-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ap-meta {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
}

.ap-count {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.ap-badge {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 0.1rem 0.4rem;
}

.ap-code {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 0.85rem;
  letter-spacing: 0.1em;
  color: var(--accent-primary);
}

.ap-hint {
  margin-top: var(--space-sm);
  font-size: 0.8rem;
  color: var(--text-muted);
  text-align: center;
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
