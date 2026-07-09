<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { api } from '@/api/client'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{
  (e: 'unauthorized'): void
}>()

const auth = useAuthStore()

const config = ref<Record<string, any>>({})
const saveStatus = ref('')
const saveClass = ref('')

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
  if (kbps >= 1000 && kbps % 1000 === 0) return `${kbps / 1000} Mbps`
  if (kbps >= 1000) return `${kbps / 1000} Mbps`
  return `${kbps} kbps`
}

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

function ensureQualityDict(cfg: Record<string, any>) {
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

// Unmount guard: an in-flight save/load must not touch refs after the
// panel closes (the modal path can unmount mid-request).
let unmounted = false
onBeforeUnmount(() => { unmounted = true })

async function loadConfig() {
  try {
    const cfg = await api.adminGetConfig()
    if (unmounted) return
    if (cfg && cfg.error) {
      emit('unauthorized')
      return
    }
    if (cfg && typeof cfg === 'object' && 'error' in cfg) {
      delete cfg.error
    }
    ensureQualityDict(cfg)
    config.value = cfg
    syncRateLimitsFromConfig()
  } catch {
    if (!unmounted) emit('unauthorized')
  }
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
  if (unmounted) return
  if (result.success) {
    const changed = result.changed || []
    const rejected = result.rejected || []
    const restart = result.restart_required || []
    const parts: string[] = []
    if (changed.length) {
      parts.push(`Saved: ${changed.join(', ')}`)
    } else {
      parts.push('No changes')
    }
    if (restart.length) {
      parts.push(`Restart required for: ${restart.join(', ')}`)
    }
    if (rejected.length) {
      parts.push(
        `Not applied: ${rejected.map((r: any) => `${r.key} (${r.reason})`).join('; ')}`,
      )
    }
    saveStatus.value = parts.join(' | ')
    saveClass.value = rejected.length ? 'warning' : 'success'
    if (result.config) {
      ensureQualityDict(result.config)
      config.value = result.config
    }
    if (changed.includes('REQUIRE_LOGIN')) {
      auth.refresh().catch(() => { /* ignore */ })
    }
  } else {
    saveStatus.value = result.error || 'Save failed'
    saveClass.value = 'error'
  }
}

loadConfig()
</script>

<template>
  <div class="admin-panel-body">
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
        <div class="setting-row">
          <div class="setting-label">
            <span>Binge-Watch</span>
            <span class="setting-hint">
              Off (default): the binge-watch button is hidden from the host's
              control strip entirely; episodes never auto-advance.
              <br /><br />
              On: the host gets a "Binge ON/OFF" pill in the control strip
              while an Episode is playing. When the host turns it on, the
              next episode in the same season auto-plays after the current
              one ends (with a countdown that any user can cancel). Movies
              and standalone items never auto-advance, regardless of this
              setting.
              <br /><br />
              Turning this off mid-session hides the button in every active
              party and cancels any countdown that's already running.
            </span>
          </div>
          <ToggleSwitch v-model="config.BINGE_WATCH_ENABLED" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>Binge Countdown (s)</span>
            <span class="setting-hint">
              Seconds shown to the room before the next episode auto-plays.
              Any user can hit Cancel during this window. 4 seconds is the
              1.x default; shorter feels snappier, longer gives more time
              to grab the remote.
            </span>
          </div>
          <input type="number" v-model.number="config.BINGE_WATCH_COUNTDOWN_SECONDS" min="1" max="30" step="1" class="setting-input setting-input-sm" />
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

    <div class="admin-panel-footer">
      <span :class="['save-status', saveClass]">{{ saveStatus }}</span>
      <button @click="saveConfig" class="btn btn-primary">Save Settings</button>
    </div>
  </div>
</template>

<style scoped>
.admin-panel-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
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

input[type="number"] {
  -moz-appearance: textfield;
}

input[type="number"]::-webkit-outer-spin-button,
input[type="number"]::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.admin-panel-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid var(--border-subtle);
}

.save-status {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.save-status.success {
  color: var(--color-success);
}

.save-status.warning {
  color: var(--color-warning, #f0b429);
}

.save-status.error {
  color: var(--color-danger);
}
</style>
