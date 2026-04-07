<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import ToggleSwitch from '@/components/ToggleSwitch.vue'

const authenticated = ref(false)
const loginUser = ref('')
const loginPass = ref('')
const loginError = ref('')
const config = ref<Record<string, any>>({})
const saveStatus = ref('')
const saveClass = ref('')

// Split rate limit strings into value + unit
const partyLimitValue = ref(5)
const partyLimitUnit = ref('per hour')
const apiLimitValue = ref(1000)
const apiLimitUnit = ref('per minute')

function parseRateLimit(str: string): { value: number; unit: string } {
  const match = (str || '').match(/^(\d+)\s*(per\s+\w+)$/i)
  if (match) return { value: parseInt(match[1]!), unit: match[2]!.toLowerCase() }
  return { value: 0, unit: 'per minute' }
}

function syncRateLimitsFromConfig() {
  const pc = parseRateLimit(config.value.RATE_LIMIT_PARTY_CREATION || '5 per hour')
  partyLimitValue.value = pc.value
  partyLimitUnit.value = pc.unit
  const api2 = parseRateLimit(config.value.RATE_LIMIT_API_CALLS || '1000 per minute')
  apiLimitValue.value = api2.value
  apiLimitUnit.value = api2.unit
}

function syncRateLimitsToConfig() {
  config.value.RATE_LIMIT_PARTY_CREATION = `${partyLimitValue.value} ${partyLimitUnit.value}`
  config.value.RATE_LIMIT_API_CALLS = `${apiLimitValue.value} ${apiLimitUnit.value}`
}

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
  syncRateLimitsFromConfig()
}

function validate(): string | null {
  const c = config.value
  if (c.MAX_USERS_PER_PARTY < 0 || !Number.isInteger(c.MAX_USERS_PER_PARTY)) return 'Max Users must be a positive integer'
  if (c.HLS_TOKEN_EXPIRY < 300) return 'HLS Token Expiry must be at least 300 seconds'
  if (c.LOG_MAX_SIZE < 1) return 'Max Log Size must be at least 1 MB'
  if (partyLimitValue.value < 1) return 'Party Creation Limit must be at least 1'
  if (apiLimitValue.value < 1) return 'API Rate Limit must be at least 1'
  if (!c.LOG_FILE || !c.LOG_FILE.trim()) return 'Log File path cannot be empty'
  return null
}

async function saveConfig() {
  const err = validate()
  if (err) {
    saveStatus.value = err
    saveClass.value = 'error'
    return
  }
  saveStatus.value = 'Saving...'
  saveClass.value = ''
  syncRateLimitsToConfig()
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
  try {
    const cfg = await api.adminGetConfig()
    if (!cfg.error) {
      authenticated.value = true
      config.value = cfg
      syncRateLimitsFromConfig()
    }
  } catch { /* not authenticated */ }
})
</script>

<template>
  <!-- Admin login -->
  <div v-if="!authenticated" class="login-page">
    <div class="login-card glass">
      <h1>Admin Panel</h1>
      <p class="login-subtitle">Sign in with an Emby administrator account</p>
      <div v-if="loginError" class="error-msg">{{ loginError }}</div>
      <form @submit.prevent="adminLogin">
        <div class="form-group">
          <label>Username</label>
          <input v-model="loginUser" type="text" required autofocus />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input v-model="loginPass" type="password" required />
        </div>
        <button type="submit" class="btn btn-primary btn-full">Sign In</button>
      </form>
      <router-link to="/" class="back-link">Back to Watch Party</router-link>
    </div>
  </div>

  <!-- Admin panel -->
  <div v-else class="admin-page">
    <div class="admin-header">
      <h1>Admin Panel</h1>
      <div class="admin-header-actions">
        <router-link to="/" class="btn btn-ghost btn-small">Back to WatchParty</router-link>
        <button @click="logout" class="btn btn-small btn-danger">Logout</button>
      </div>
    </div>

    <div class="admin-grid">
      <!-- Logging -->
      <div class="admin-card card">
        <h2 class="card-title">Logging</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Log Level</span>
            <span class="setting-hint">Application log verbosity</span>
          </div>
          <select v-model="config.LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Console Log Level</span>
            <span class="setting-hint">Terminal output verbosity</span>
          </div>
          <select v-model="config.CONSOLE_LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Log to File</span>
            <span class="setting-hint">Write logs to disk</span>
          </div>
          <ToggleSwitch v-model="config.LOG_TO_FILE" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Log File</span>
            <span class="setting-hint">Path to log file</span>
          </div>
          <input v-model="config.LOG_FILE" type="text" class="setting-input" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Max Log Size (MB)</span>
            <span class="setting-hint">Log file rotation size</span>
          </div>
          <input type="number" v-model.number="config.LOG_MAX_SIZE" min="1" max="100" step="1" class="setting-input setting-input-sm" />
        </div>
      </div>

      <!-- Security -->
      <div class="admin-card card">
        <h2 class="card-title">Security</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Max Users per Party</span>
            <span class="setting-hint">0 = unlimited</span>
          </div>
          <input type="number" v-model.number="config.MAX_USERS_PER_PARTY" min="0" max="100" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>HLS Token Validation</span>
            <span class="setting-hint">Prevent direct stream access bypass</span>
          </div>
          <ToggleSwitch v-model="config.ENABLE_HLS_TOKEN_VALIDATION" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>HLS Token Expiry (s)</span>
            <span class="setting-hint">Token lifetime (default: 86400 = 24h)</span>
          </div>
          <input type="number" v-model.number="config.HLS_TOKEN_EXPIRY" min="300" max="604800" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Rate Limiting</span>
            <span class="setting-hint">Requires restart to take effect</span>
          </div>
          <ToggleSwitch v-model="config.ENABLE_RATE_LIMITING" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Party Creation Limit</span>
            <span class="setting-hint">Max per IP (requires restart)</span>
          </div>
          <div class="rate-limit-group">
            <input type="number" v-model.number="partyLimitValue" min="1" class="setting-input setting-input-xs" />
            <select v-model="partyLimitUnit">
              <option value="per minute">per minute</option>
              <option value="per hour">per hour</option>
              <option value="per day">per day</option>
            </select>
          </div>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>API Rate Limit</span>
            <span class="setting-hint">Max per IP (requires restart)</span>
          </div>
          <div class="rate-limit-group">
            <input type="number" v-model.number="apiLimitValue" min="1" class="setting-input setting-input-xs" />
            <select v-model="apiLimitUnit">
              <option value="per minute">per minute</option>
              <option value="per hour">per hour</option>
              <option value="per day">per day</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Session -->
      <div class="admin-card card">
        <h2 class="card-title">Session</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Static Session Mode</span>
            <span class="setting-hint">Single persistent party that auto-creates on startup</span>
          </div>
          <ToggleSwitch v-model="config.STATIC_SESSION_ENABLED" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Static Session ID</span>
            <span class="setting-hint">Party code for static session</span>
          </div>
          <input v-model="config.STATIC_SESSION_ID" type="text" class="setting-input setting-input-sm" style="text-transform:uppercase;" />
        </div>
      </div>
    </div>

    <!-- Save bar -->
    <div class="save-bar glass">
      <span :class="['save-status', saveClass]">{{ saveStatus }}</span>
      <button @click="saveConfig" class="btn btn-primary">Save Settings</button>
    </div>
  </div>
</template>

<style scoped>
/* ─── Login ─── */
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-xl);
}

.login-card {
  max-width: 400px;
  width: 100%;
  padding: var(--space-xl);
  text-align: center;
}

.login-card h1 {
  margin-bottom: var(--space-xs);
}

.login-subtitle {
  color: var(--text-secondary);
  margin-bottom: var(--space-lg);
  font-size: 0.9rem;
}

.form-group {
  margin-bottom: var(--space-md);
  text-align: left;
}

.form-group label {
  display: block;
  margin-bottom: var(--space-xs);
  font-weight: 500;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.btn-full {
  width: 100%;
  padding: 0.75rem;
}

.back-link {
  display: block;
  margin-top: var(--space-md);
  font-size: 0.85rem;
  color: var(--text-muted);
}

.error-msg {
  color: var(--color-danger);
  background: var(--color-danger-dim);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-md);
  font-size: 0.9rem;
}

/* ─── Admin Panel ─── */
.admin-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-lg);
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-lg);
}

.admin-header-actions {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
}

.admin-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-md);
}

@media (max-width: 768px) {
  .admin-grid { grid-template-columns: 1fr; }
}

.admin-card {
  padding: var(--space-lg);
}

.card-title {
  color: var(--accent-secondary);
  font-size: 1.05rem;
  margin: 0 0 var(--space-md);
  padding-bottom: var(--space-sm);
  border-bottom: 1px solid var(--border-subtle);
}

.setting-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) 0;
  border-bottom: 1px solid var(--border-subtle);
  gap: var(--space-md);
}

.setting-row:last-child {
  border-bottom: none;
}

.setting-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.setting-label span:first-child {
  font-size: 0.9rem;
  font-weight: 500;
}

.setting-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.setting-input {
  max-width: 220px;
}

.setting-input-sm {
  max-width: 120px;
  text-align: right;
}

.setting-input-xs {
  max-width: 80px;
  text-align: right;
}

.rate-limit-group {
  display: flex;
  gap: var(--space-xs);
  align-items: center;
}

/* Number input spinner fix */
input[type="number"] {
  -moz-appearance: textfield;
}

input[type="number"]::-webkit-outer-spin-button,
input[type="number"]::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

/* ─── Save Bar ─── */
.save-bar {
  position: sticky;
  bottom: var(--space-md);
  margin-top: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.save-status {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.save-status.success {
  color: var(--color-success);
}

.save-status.error {
  color: var(--color-danger);
}
</style>
