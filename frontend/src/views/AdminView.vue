<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { api } from '@/api/client'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

// "Back to WatchParty" should return to the party the admin came from,
// not bounce them to the create-a-party screen. auth.partyId is bound
// when the caller has a party-bound session cookie (most common path
// for host-as-admin); fall back to the index for the standalone login
// flow where there is no party context yet.
const backToWatchPartyTarget = computed(() => {
  return auth.partyId ? `/party/${auth.partyId}` : '/'
})

const authenticated = ref(false)
const loginUser = ref('')
const loginPass = ref('')
const loginError = ref('')
const config = ref<Record<string, any>>({})
const saveStatus = ref('')
const saveClass = ref('')

// Resolution tiers offered by the quality dropdown. Each tier has a
// master checkbox (= "is this resolution enabled at all?") and, when
// it has bitrate buckets, a child set of bitrate checkboxes that only
// appear once the master is ticked. The shape must mirror QUALITY_TIERS
// in backend/src/quality.py -- if either side adds a bitrate, both
// need updating.
const resolutionTiers: Array<{ resolution: string; bitrates: number[] }> = [
  {
    resolution: '1080p',
    bitrates: [60000, 50000, 40000, 30000, 25000, 20000, 15000, 12000, 10000, 8000, 6000, 5000, 4000],
  },
  { resolution: '720p', bitrates: [4000, 3000, 2000, 1500, 1000] },
  { resolution: '480p', bitrates: [1000, 720, 420] },
  { resolution: '360p', bitrates: [] },
  { resolution: '240p', bitrates: [] },
  { resolution: '144p', bitrates: [] },
]

function formatBitrate(kbps: number): string {
  // Mirror backend/src/quality.py::_format_bitrate so the dropdown and
  // the admin checkboxes show the same label for the same bitrate.
  if (kbps >= 1000 && kbps % 1000 === 0) return `${kbps / 1000} Mbps`
  if (kbps >= 1000) return `${kbps / 1000} Mbps`
  return `${kbps} kbps`
}

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

function ensureQualityDict(cfg: Record<string, any>) {
  // Default a missing or wrong-shaped config to "everything enabled" so
  // the master/child checkbox grid has something to bind to. A list-shape
  // value (left over from the older ENABLED_QUALITY_RESOLUTIONS field)
  // is also replaced -- no migration on purpose, dev box only.
  const cur = cfg.ENABLED_QUALITY_OPTIONS
  if (!cur || typeof cur !== 'object' || Array.isArray(cur)) {
    const defaults: Record<string, number[]> = {}
    for (const tier of resolutionTiers) defaults[tier.resolution] = [...tier.bitrates]
    cfg.ENABLED_QUALITY_OPTIONS = defaults
  }
}

function isResolutionEnabled(res: string): boolean {
  const dict = config.value.ENABLED_QUALITY_OPTIONS
  return !!dict && Object.prototype.hasOwnProperty.call(dict, res)
}

function setResolutionEnabled(res: string, enabled: boolean) {
  const dict = config.value.ENABLED_QUALITY_OPTIONS || {}
  if (enabled) {
    if (Object.prototype.hasOwnProperty.call(dict, res)) return
    // Newly enabled -- seed with the full bitrate set so a single flip
    // is "expose this resolution at every bitrate". The admin can then
    // untoggle individual bitrates from the disclosure list below.
    const tier = resolutionTiers.find((t) => t.resolution === res)
    dict[res] = tier ? [...tier.bitrates] : []
  } else {
    if (!Object.prototype.hasOwnProperty.call(dict, res)) return
    delete dict[res]
  }
  config.value.ENABLED_QUALITY_OPTIONS = { ...dict }
}

function isBitrateEnabled(res: string, kbps: number): boolean {
  const arr = config.value.ENABLED_QUALITY_OPTIONS?.[res]
  return Array.isArray(arr) && arr.includes(kbps)
}

function setBitrateEnabled(res: string, kbps: number, enabled: boolean) {
  const dict = config.value.ENABLED_QUALITY_OPTIONS || {}
  if (!Array.isArray(dict[res])) dict[res] = []
  const idx = dict[res].indexOf(kbps)
  if (enabled && idx < 0) {
    dict[res].push(kbps)
    // Keep the saved order matching the canonical tier order (highest
    // first) so config.json reads tidy and diffs predictably.
    const tier = resolutionTiers.find((t) => t.resolution === res)
    if (tier) {
      dict[res].sort((a: number, b: number) => tier.bitrates.indexOf(a) - tier.bitrates.indexOf(b))
    }
  } else if (!enabled && idx >= 0) {
    dict[res].splice(idx, 1)
  } else {
    return
  }
  config.value.ENABLED_QUALITY_OPTIONS = { ...dict }
}

async function loadConfig() {
  const cfg = await api.adminGetConfig()
  ensureQualityDict(cfg)
  config.value = cfg
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
    if (result.config) {
      ensureQualityDict(result.config)
      config.value = result.config
    }
    // Settings like REQUIRE_LOGIN are read by other views via the auth
    // store. Refresh so the new value takes effect immediately without
    // requiring a route remount.
    if (changed.includes('REQUIRE_LOGIN')) {
      auth.refresh().catch(() => { /* ignore */ })
    }
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
      ensureQualityDict(cfg)
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
      <router-link :to="backToWatchPartyTarget" class="back-link">Back to Watch Party</router-link>
    </div>
  </div>

  <!-- Admin panel -->
  <div v-else class="admin-page">
    <div class="admin-header">
      <h1>Admin Panel</h1>
      <div class="admin-header-actions">
        <router-link :to="backToWatchPartyTarget" class="btn btn-ghost btn-small">Back to WatchParty</router-link>
        <button @click="logout" class="btn btn-small btn-danger">Logout</button>
      </div>
    </div>

    <div class="admin-grid">
      <!-- Auth -->
      <div class="admin-card card">
        <h2 class="card-title">Auth</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Require Login to Create Party</span>
            <span class="setting-hint">
              When on, creating a party requires Emby credentials and the creator
              becomes host. When off, anyone can create; any member can later log
              in to host. Browsing always needs a host with a valid session.
            </span>
          </div>
          <ToggleSwitch v-model="config.REQUIRE_LOGIN" />
        </div>
      </div>

      <!-- Playback -->
      <div class="admin-card card">
        <h2 class="card-title">Playback</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Force Transcode</span>
            <span class="setting-hint">
              Off (default): Emby decides per-source. h264 sources within the
              quality bitrate cap get stream-copied (no re-encode, low CPU/GPU
              on the Emby host).
              <br /><br />
              On: every HLS request carries <code>EnableAutoStreamCopy=false</code>,
              so Emby always re-encodes. This produces uniform 6-second segments
              that HLS.js can seek into cleanly at any position.
              <br /><br />
              Turn this on if you see large seeks (Skip Intro, dragging the
              progress bar a long distance) restart the video from the beginning,
              or if stream-copied content stalls during seeking. Cost: extra
              CPU/GPU load on the Emby server.
            </span>
          </div>
          <ToggleSwitch v-model="config.FORCE_TRANSCODE" />
        </div>
      </div>

      <!-- Quality -->
      <div class="admin-card card">
        <h2 class="card-title">Quality</h2>
        <div class="setting-row quality-row">
          <div class="setting-label">
            <span>Enabled Resolutions &amp; Bitrates</span>
            <span class="setting-hint">
              Tick a resolution to expose it in the per-user quality
              dropdown; the bitrate checkboxes only appear once the
              resolution is enabled and let you trim the list further.
              360p / 240p / 144p are resolution-only (no bitrate
              choices).
              <br /><br />
              <code>Auto</code> is always available unless
              <strong>Force Transcode</strong> is on; in that mode it
              would conflict with always-transcode and is replaced by
              the 1080p / 10 Mbps preset as the safe default. Bitrate
              buckets mirror Emby's own table (tuned for software-encode
              safety on the low end).
            </span>
          </div>
          <div class="quality-tier-list">
            <div
              v-for="tier in resolutionTiers"
              :key="tier.resolution"
              class="quality-tier"
            >
              <div class="quality-master">
                <ToggleSwitch
                  :model-value="isResolutionEnabled(tier.resolution)"
                  @update:model-value="(v: boolean) => setResolutionEnabled(tier.resolution, v)"
                />
                <span class="quality-master-label">{{ tier.resolution }}</span>
              </div>
              <div
                v-if="tier.bitrates.length && isResolutionEnabled(tier.resolution)"
                class="quality-bitrates"
              >
                <div
                  v-for="kbps in tier.bitrates"
                  :key="kbps"
                  class="bitrate-row"
                >
                  <ToggleSwitch
                    :model-value="isBitrateEnabled(tier.resolution, kbps)"
                    @update:model-value="(v: boolean) => setBitrateEnabled(tier.resolution, kbps, v)"
                  />
                  <span class="bitrate-label">{{ formatBitrate(kbps) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

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
            <span>Log Format</span>
            <span class="setting-hint">rsyslog or standard</span>
          </div>
          <select v-model="config.LOG_FORMAT">
            <option value="rsyslog">rsyslog</option>
            <option value="standard">standard</option>
          </select>
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

      <!-- Late Join Vote -->
      <div class="admin-card card">
        <h2 class="card-title">Late Join Vote</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>Enable Late Join Vote</span>
            <span class="setting-hint">Require a majority vote to admit users who join mid-playback</span>
          </div>
          <ToggleSwitch v-model="config.LATE_JOIN_VOTE_ENABLED" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Vote Timeout (s)</span>
            <span class="setting-hint">Seconds before selector tiebreak kicks in</span>
          </div>
          <input type="number" v-model.number="config.LATE_JOIN_VOTE_TIMEOUT_SECONDS" min="5" max="300" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Post-Vote Cooldown (s)</span>
            <span class="setting-hint">Delay after a failed vote before another join attempt is allowed (0 disables)</span>
          </div>
          <input type="number" v-model.number="config.LATE_JOIN_VOTE_COOLDOWN_SECONDS" min="0" max="600" step="1" class="setting-input setting-input-sm" />
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

/* Quality section: master checkboxes stack vertically, child bitrate
   grid only renders when its master is ticked. The setting-row default
   is a horizontal flex that crams everything onto one line; for this
   card we override to column so the tier list gets the full width and
   the hint text sits above instead of fighting for horizontal space. */
.quality-row {
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-md);
}

.quality-tier-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.quality-tier {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--border-subtle);
}

.quality-tier:last-child {
  border-bottom: none;
}

.quality-master {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-weight: 500;
  font-size: 0.9rem;
  color: var(--text-primary);
}

.quality-master-label {
  user-select: none;
}

.quality-bitrates {
  display: grid;
  grid-template-columns: repeat(3, max-content);
  gap: 0.5rem 1.2rem;
  padding-left: 1.5rem;
}

.bitrate-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  white-space: nowrap;
}

.bitrate-label {
  font-size: 0.82rem;
  color: var(--text-secondary);
  user-select: none;
}

@media (max-width: 640px) {
  .quality-bitrates {
    grid-template-columns: repeat(2, max-content);
  }
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
