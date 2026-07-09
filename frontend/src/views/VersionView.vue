<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const version = ref({
  current_version: '',
  codename: '',
  latest_version: null as string | null,
  update_available: false,
  release_url: null as string | null,
})
const checkStatus = ref<'loading' | 'done' | 'error'>('loading')

// Match AdminView: return to the user's party if they have one, else
// fall back to the index. Without this the "Back to Home" link drops
// the user out of their active party.
const backTarget = computed(() => (auth.partyId ? `/party/${auth.partyId}` : '/'))
const backLabel = computed(() => (auth.partyId ? '← Back to Party' : '← Back to Home'))

onMounted(async () => {
  try { await auth.refresh() } catch { /* ignore */ }
  try {
    version.value = await api.version()
    checkStatus.value = 'done'
  } catch {
    checkStatus.value = 'error'
  }
})

const dependencies = [
  { name: 'FastAPI', url: 'https://fastapi.tiangolo.com/', license: 'MIT' },
  { name: 'Uvicorn', url: 'https://www.uvicorn.org/', license: 'BSD-3-Clause' },
  { name: 'python-socketio', url: 'https://github.com/miguelgrinberg/python-socketio', license: 'MIT' },
  { name: 'httpx', url: 'https://github.com/encode/httpx', license: 'BSD-3-Clause' },
  { name: 'requests', url: 'https://github.com/psf/requests', license: 'Apache-2.0' },
  { name: 'python-dotenv', url: 'https://github.com/theskumar/python-dotenv', license: 'BSD-3-Clause' },
  { name: 'Vue.js 3', url: 'https://vuejs.org/', license: 'MIT' },
  { name: 'Vite', url: 'https://vitejs.dev/', license: 'MIT' },
  { name: 'Pinia', url: 'https://pinia.vuejs.org/', license: 'MIT' },
  { name: 'HLS.js', url: 'https://github.com/video-dev/hls.js', license: 'Apache-2.0' },
  { name: 'Socket.IO Client', url: 'https://socket.io/', license: 'MIT' },
]

const thanks = [
  { name: 'QuackMasterDan', url: 'https://emby.media/community/index.php?/profile/1658172-quackmasterdan/', desc: 'Dedicated testing and valuable feedback throughout development' },
  { name: 'wlowen', url: 'https://github.com/wlowen', desc: 'Testing, detailed bug reports, and mediainfo for HEVC transcoding issues' },
  { name: 'JeslynMcKenzie', url: 'https://github.com/JeslynMcKenzie', desc: 'Testing, bug reports, feature requests, and mediainfo contributions' },
  { name: 'daniilkopylov', url: 'https://github.com/daniilkopylov', desc: 'Feature requests and testing (static sessions, user count fix)' },
]

const links = [
  { icon: '\uD83D\uDC1E', label: 'GitHub Issues', desc: 'Report bugs & request features', url: 'https://github.com/Oratorian/emby-watchparty/issues' },
  { icon: '\uD83D\uDCAC', label: 'Discord', desc: 'Chat with the community', url: 'https://discord.gg/RWUpxq9xsA' },
  { icon: '\uD83C\uDFA4', label: 'Emby Forums', desc: 'Discussion on Emby Community', url: 'https://emby.media/community/index.php?/topic/143565-emby-watch-party-synchronized-viewing-for-friends-family/' },
  { icon: '\uD83D\uDCBB', label: 'Source Code', desc: 'GitHub repository', url: 'https://github.com/Oratorian/emby-watchparty' },
  { icon: '\u2615', label: 'Ko-fi', desc: 'Support the project', url: 'https://ko-fi.com/jedziah' },
]
</script>

<template>
  <div class="version-page">
    <header class="version-header">
      <h1>Emby Watch Party</h1>
      <p>Version Information</p>
    </header>

    <div class="version-grid">
      <!-- Version Info -->
      <div class="version-card card">
        <h2 class="card-title">Current Version</h2>
        <div class="version-number">v{{ version.current_version }}</div>
        <div class="version-codename">"{{ version.codename }}"</div>
        <div class="update-status">
          <span v-if="checkStatus === 'loading'" class="update-badge badge-checking">Checking for updates...</span>
          <span v-else-if="version.update_available" class="update-badge badge-update">
            Update available: <a :href="version.release_url || '#'" target="_blank" rel="noopener">v{{ version.latest_version }}</a>
          </span>
          <span v-else-if="version.latest_version" class="update-badge badge-ok">Up to date</span>
          <span v-else class="update-badge badge-error">Could not check for updates</span>
        </div>
      </div>

      <!-- Software & Licenses -->
      <div class="version-card card">
        <h2 class="card-title">Software & Licenses</h2>
        <p class="license-intro">
          Emby Watch Party is open source under the <strong>MIT License</strong>
        </p>
        <table class="deps-table">
          <thead>
            <tr>
              <th>Package</th>
              <th>License</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dep in dependencies" :key="dep.name">
              <td><a :href="dep.url" target="_blank" rel="noopener">{{ dep.name }}</a></td>
              <td><span class="license-badge">{{ dep.license }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Special Thanks -->
      <div class="version-card card">
        <h2 class="card-title">Special Thanks</h2>
        <ul class="thanks-list">
          <li v-for="person in thanks" :key="person.name">
            <a :href="person.url" target="_blank" rel="noopener">{{ person.name }}</a>
            <span> -- {{ person.desc }}</span>
          </li>
        </ul>
      </div>

      <!-- Support & Community -->
      <div class="version-card card">
        <h2 class="card-title">Support & Community</h2>
        <div class="support-links">
          <a
            v-for="link in links"
            :key="link.label"
            :href="link.url"
            target="_blank"
            rel="noopener"
            class="support-link"
          >
            <span class="link-icon">{{ link.icon }}</span>
            <div>
              <div class="link-label">{{ link.label }}</div>
              <div class="link-desc">{{ link.desc }}</div>
            </div>
          </a>
        </div>
      </div>
    </div>

    <div class="back-nav">
      <router-link :to="backTarget" class="btn btn-ghost">{{ backLabel }}</router-link>
    </div>
  </div>
</template>

<style scoped>
.version-page {
  max-width: 800px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.version-header {
  text-align: center;
  margin-bottom: var(--space-xl);
}

.version-header h1 {
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-primary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.version-header p {
  color: var(--text-secondary);
  margin-top: var(--space-xs);
}

.version-grid {
  display: grid;
  gap: var(--space-md);
}

.version-card {
  padding: var(--space-lg);
}

.card-title {
  color: var(--accent-primary);
  font-size: 1.05rem;
  margin: 0 0 var(--space-md);
  padding-bottom: var(--space-sm);
  border-bottom: 1px solid var(--border-subtle);
}

.version-number {
  font-size: 2.2rem;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.version-codename {
  font-size: 1.1rem;
  color: var(--accent-secondary);
  margin-top: var(--space-xs);
}

.update-status {
  margin-top: var(--space-md);
}

.update-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.85rem;
  border-radius: var(--radius-full);
  font-size: 0.85rem;
}

.badge-checking {
  background: var(--bg-surface);
  color: var(--text-secondary);
}

.badge-ok {
  background: rgba(16, 185, 129, 0.15);
  color: var(--color-success);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-update {
  background: var(--accent-secondary-dim);
  color: var(--accent-secondary);
  border: 1px solid rgba(240, 160, 80, 0.3);
}

.badge-update a {
  color: inherit;
  text-decoration: underline;
  margin-left: 0.25rem;
}

.badge-error {
  background: var(--bg-surface);
  color: var(--text-muted);
}

/* Dependencies table */
.license-intro {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin: 0 0 var(--space-md);
}

.license-intro strong {
  color: var(--text-primary);
}

.deps-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.deps-table th {
  text-align: left;
  padding: var(--space-sm);
  color: var(--accent-primary);
  border-bottom: 1px solid var(--border-default);
  font-weight: 600;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.deps-table td {
  padding: 0.4rem var(--space-sm);
  border-bottom: 1px solid var(--border-subtle);
}

.deps-table a {
  color: var(--text-primary);
}

.deps-table a:hover {
  color: var(--accent-primary);
}

.license-badge {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

/* Thanks list */
.thanks-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.thanks-list li {
  padding: var(--space-sm) 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.thanks-list li:last-child {
  border-bottom: none;
}

.thanks-list a {
  font-weight: 600;
}

/* Support links */
.support-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-sm);
}

.support-link {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  text-decoration: none;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.support-link:hover {
  border-color: var(--accent-primary);
  background: var(--bg-surface-hover);
}

.link-icon {
  font-size: 1.4rem;
  flex-shrink: 0;
}

.link-label {
  font-weight: 600;
  font-size: 0.9rem;
}

.link-desc {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 2px;
}

.back-nav {
  text-align: center;
  margin-top: var(--space-xl);
}
</style>
