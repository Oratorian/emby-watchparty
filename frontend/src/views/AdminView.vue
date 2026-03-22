<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'

const authenticated = ref(false)
const loginUser = ref('')
const loginPass = ref('')
const loginError = ref('')
const config = ref<Record<string, any>>({})
const saveStatus = ref('')
const saveClass = ref('')

const boolFields = ['LOG_TO_FILE', 'ENABLE_HLS_TOKEN_VALIDATION', 'ENABLE_RATE_LIMITING', 'STATIC_SESSION_ENABLED']
const numFields = ['LOG_MAX_SIZE', 'MAX_USERS_PER_PARTY', 'HLS_TOKEN_EXPIRY']

async function adminLogin() {
  loginError.value = ''
  const result = await api.adminLogin(loginUser.value, loginPass.value)
  if (result.success) {
    authenticated.value = true
    await loadConfig()
  } else {
    loginError.value = result.message || 'Login failed'
  }
}

async function loadConfig() {
  config.value = await api.adminGetConfig()
}

async function saveConfig() {
  saveStatus.value = 'Saving...'
  saveClass.value = ''
  const result = await api.adminUpdateConfig(config.value)
  if (result.success) {
    const changed = result.changed || []
    saveStatus.value = changed.length ? `Saved: ${changed.join(', ')}` : 'No changes'
    saveClass.value = 'success'
    if (result.config) config.value = result.config
  } else {
    saveStatus.value = result.error || 'Save failed'
    saveClass.value = 'error'
  }
}

async function logout() {
  await api.adminLogout()
  authenticated.value = false
}

onMounted(async () => {
  // Check if already authenticated
  try {
    const cfg = await api.adminGetConfig()
    if (!cfg.error) {
      authenticated.value = true
      config.value = cfg
    }
  } catch { /* not authenticated */ }
})
</script>

<template>
  <!-- Admin login -->
  <div v-if="!authenticated" class="login-container">
    <div class="login-header">
      <h1>Admin Panel</h1>
      <p>Sign in with an Emby administrator account</p>
    </div>
    <div class="login-card">
      <div v-if="loginError" class="error-msg">{{ loginError }}</div>
      <form @submit.prevent="adminLogin">
        <div class="form-group">
          <label>Username</label>
          <input v-model="loginUser" required autofocus />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input v-model="loginPass" type="password" required />
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%;padding:0.75rem;">Sign In</button>
      </form>
      <div style="text-align:center;margin-top:1rem;">
        <router-link to="/" style="color:var(--text-secondary,#888);font-size:0.85rem;">Back to Watch Party</router-link>
      </div>
    </div>
  </div>

  <!-- Admin panel -->
  <div v-else class="admin-container">
    <div class="admin-header">
      <h1>Admin Panel</h1>
      <div>
        <router-link to="/">Back to WatchParty</router-link>
        <button @click="logout" class="btn btn-small btn-danger" style="margin-left:0.5rem;">Logout</button>
      </div>
    </div>

    <div class="admin-grid">
      <div class="admin-section">
        <h2>Logging</h2>
        <div class="setting-row">
          <span>Log Level</span>
          <select v-model="config.LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <span>Console Log Level</span>
          <select v-model="config.CONSOLE_LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <span>Log to File</span>
          <input type="checkbox" v-model="config.LOG_TO_FILE" />
        </div>
        <div class="setting-row">
          <span>Log File</span>
          <input v-model="config.LOG_FILE" />
        </div>
        <div class="setting-row">
          <span>Max Log Size (MB)</span>
          <input type="number" v-model.number="config.LOG_MAX_SIZE" min="1" />
        </div>
      </div>

      <div class="admin-section">
        <h2>Security</h2>
        <div class="setting-row">
          <span>Max Users per Party</span>
          <input type="number" v-model.number="config.MAX_USERS_PER_PARTY" min="0" />
        </div>
        <div class="setting-row">
          <span>HLS Token Validation</span>
          <input type="checkbox" v-model="config.ENABLE_HLS_TOKEN_VALIDATION" />
        </div>
        <div class="setting-row">
          <span>HLS Token Expiry (s)</span>
          <input type="number" v-model.number="config.HLS_TOKEN_EXPIRY" min="300" />
        </div>
        <div class="setting-row">
          <span>Rate Limiting</span>
          <input type="checkbox" v-model="config.ENABLE_RATE_LIMITING" />
        </div>
        <div class="setting-row">
          <span>Party Creation Limit</span>
          <input v-model="config.RATE_LIMIT_PARTY_CREATION" />
        </div>
        <div class="setting-row">
          <span>API Rate Limit</span>
          <input v-model="config.RATE_LIMIT_API_CALLS" />
        </div>
      </div>

      <div class="admin-section">
        <h2>Session</h2>
        <div class="setting-row">
          <span>Static Session Mode</span>
          <input type="checkbox" v-model="config.STATIC_SESSION_ENABLED" />
        </div>
        <div class="setting-row">
          <span>Static Session ID</span>
          <input v-model="config.STATIC_SESSION_ID" style="text-transform:uppercase;" />
        </div>
      </div>
    </div>

    <div class="save-bar">
      <span :class="['save-status', saveClass]">{{ saveStatus }}</span>
      <button @click="saveConfig" class="btn btn-primary">Save Settings</button>
    </div>
  </div>
</template>

<style scoped>
.login-container { max-width: 400px; margin: 3rem auto; padding: 2rem; }
.login-header { text-align: center; margin-bottom: 2rem; }
.login-header p { color: var(--text-secondary, #888); }
.login-card { background: var(--bg-secondary, #1a1a2e); border-radius: 8px; padding: 2rem; }
.form-group { margin-bottom: 1.5rem; }
.form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
.form-group input {
  width: 100%; padding: 0.75rem; box-sizing: border-box;
  border: 1px solid var(--cyber-primary, #6c63ff); border-radius: 4px;
  background: var(--bg-primary, #0f0f23); color: var(--text-primary, #fff);
}
.error-msg { color: #ff4444; background: rgba(255,68,68,0.1); padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; }

.admin-container { max-width: 1100px; margin: 1.5rem auto; padding: 0 1rem; }
.admin-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
.admin-header a { color: var(--cyber-primary, #6c63ff); text-decoration: none; }
.admin-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
@media (max-width: 768px) { .admin-grid { grid-template-columns: 1fr; } }
.admin-section { background: var(--bg-secondary, #1a1a2e); border-radius: 8px; padding: 1.25rem; }
.admin-section h2 { margin: 0 0 1rem; color: var(--cyber-gold, #ffbe0b); border-bottom: 1px solid var(--cyber-border, #333); padding-bottom: 0.5rem; }
.setting-row { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.setting-row:last-child { border-bottom: none; }
.setting-row input, .setting-row select {
  padding: 0.4rem; border: 1px solid var(--cyber-primary, #6c63ff); border-radius: 4px;
  background: var(--bg-primary, #0f0f23); color: var(--text-primary, #fff);
}
.setting-row input[type="checkbox"] { width: 18px; height: 18px; }
.save-bar {
  position: sticky; bottom: 0; background: var(--bg-secondary, #1a1a2e);
  padding: 1rem; border-radius: 8px; margin-top: 1rem;
  display: flex; justify-content: space-between; align-items: center;
}
.save-status { font-size: 0.85rem; color: var(--text-secondary, #888); }
.save-status.success { color: #48bb78; }
.save-status.error { color: #ff4444; }
</style>
