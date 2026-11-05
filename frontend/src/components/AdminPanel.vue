<script setup lang="ts">
import { t } from '@/i18n'
import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, api } from '@/api/client'
import type { AdminConfig } from '@/api/client'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{
  (e: 'unauthorized'): void
}>()

const auth = useAuthStore()

const config = ref<AdminConfig>({} as AdminConfig)
const loadingConfig = ref(false)
const configLoaded = ref(false)
const loadError = ref<string | (() => string)>('')
const displayedLoadError = computed(() => typeof loadError.value === 'function' ? loadError.value() : loadError.value)
const saving = ref(false)
const saveStatus = ref<string | (() => string)>('')
const displayedSaveStatus = computed(() => typeof saveStatus.value === 'function' ? saveStatus.value() : saveStatus.value)
const saveClass = ref('')

// The API can receive a successful HTML proxy response or incomplete JSON.
// Verify the editable fields before showing controls that save the whole config.
const CONFIG_FIELD_TYPES = {
  BINGE_WATCH_COUNTDOWN_SECONDS: 'number',
  BINGE_WATCH_ENABLED: 'boolean',
  CONSOLE_LOG_LEVEL: 'string',
  ENABLE_RATE_LIMITING: 'boolean',
  FORCE_TRANSCODE: 'boolean',
  HLS_TOKEN_EXPIRY: 'number',
  LATE_JOIN_VOTE_COOLDOWN_SECONDS: 'number',
  LATE_JOIN_VOTE_ENABLED: 'boolean',
  LATE_JOIN_VOTE_TIMEOUT_SECONDS: 'number',
  LOG_FILE: 'string',
  LOG_FORMAT: 'string',
  LOG_LEVEL: 'string',
  LOG_MAX_SIZE: 'number',
  LOG_TO_FILE: 'boolean',
  MAX_USERS_PER_PARTY: 'number',
  RATE_LIMIT_API_CALLS: 'string',
  RATE_LIMIT_AVATAR_RECOVERY: 'string',
  RATE_LIMIT_CHAT: 'string',
  RATE_LIMIT_LOGIN: 'string',
  RATE_LIMIT_PARTY_CREATION: 'string',
  RATE_LIMIT_SOCKET_CONNECTIONS: 'string',
  REQUIRE_LOGIN: 'boolean',
  STATIC_SESSION_ENABLED: 'boolean',
  STATIC_SESSION_ID: 'string',
} satisfies Record<Exclude<keyof AdminConfig, 'error' | 'ENABLED_QUALITY_OPTIONS'>, string>

function isAdminConfig(value: unknown): value is AdminConfig {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const fields = value as Record<string, unknown>
  if (!Object.entries(CONFIG_FIELD_TYPES).every(([key, type]) =>
    typeof fields[key] === type && (type !== 'number' || Number.isFinite(fields[key])),
  )) return false
  const quality = fields.ENABLED_QUALITY_OPTIONS
  return !!quality && typeof quality === 'object' && !Array.isArray(quality)
    && Object.values(quality).every((bitrates) => Array.isArray(bitrates)
      && bitrates.every((bitrate) => typeof bitrate === 'number' && Number.isFinite(bitrate)))
}

function isUnauthorizedResponse(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const error = (value as { error?: unknown }).error
  return error === 'Not authenticated' || error === 'Unauthorized'
}

function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403)
}

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

// The four limits below default to windows the old three-option dropdown could
// not express ("per 15 minutes", "per 3 seconds"), which is why they shipped as
// free text. One shared list covers every window in use plus the obvious
// neighbours, so all six controls behave the same way.
const RATE_WINDOWS = [
  'per second',
  'per 3 seconds',
  'per 10 seconds',
  'per 30 seconds',
  'per minute',
  'per 5 minutes',
  'per 15 minutes',
  'per 30 minutes',
  'per hour',
  'per day',
] as const

const TEXT_RATE_FIELDS = [
  ['interface.admin_panel.admin_login_limit', 'RATE_LIMIT_LOGIN'],
  ['interface.admin_panel.avatar_recovery_limit', 'RATE_LIMIT_AVATAR_RECOVERY'],
  ['interface.admin_panel.chat_limit', 'RATE_LIMIT_CHAT'],
  ['interface.admin_panel.socket_connection_limit', 'RATE_LIMIT_SOCKET_CONNECTIONS'],
] as const

type RateFieldKey = (typeof TEXT_RATE_FIELDS)[number][1]

const rateValues = ref<Record<string, number>>({})
const rateUnits = ref<Record<string, string>>({})

/** Windows offered for a field, including one the config already holds.
 *
 * An operator can set any window through the environment, and dropping an
 * unrecognised one would silently rewrite their configuration the first time
 * the panel was saved. Keeping it as an option means the value round-trips.
 */
function windowsFor(current: string): string[] {
  return RATE_WINDOWS.includes(current as (typeof RATE_WINDOWS)[number])
    ? [...RATE_WINDOWS]
    : [current, ...RATE_WINDOWS]
}

function rateWindowLabel(window: string): string {
  const match = window.match(/^per(?: (\d+))? (second|minute|hour|day)s?$/)
  if (!match) return window
  const count = Number(match[1] || 1)
  if (!match[1]) {
    const singles: Record<string, string> = { minute: 'per_minute', hour: 'per_hour', day: 'per_day' }
    if (singles[match[2]!]) return t(`interface.admin_panel.${singles[match[2]!]}`)
  }
  return t(`interface.admin_panel.per_${match[2]}s`, { count })
}

function parseRateLimit(str: string): { value: number; unit: string } {
  // The tail is captured whole rather than as a single word, so a multiplied
  // window ("per 15 minutes") survives. Matching \w+ dropped the number and
  // turned every one of these into "per minute".
  const match = (str || '').match(/^\s*(\d+)\s+(per\s+.+?)\s*$/i)
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
  for (const [, key] of TEXT_RATE_FIELDS) {
    const parsed = parseRateLimit(config.value[key as RateFieldKey] || '')
    rateValues.value[key] = parsed.value
    rateUnits.value[key] = parsed.unit
  }
}

function syncRateLimitsToConfig() {
  config.value.RATE_LIMIT_PARTY_CREATION = `${partyLimitValue.value} ${partyLimitUnit.value}`
  config.value.RATE_LIMIT_API_CALLS = `${apiLimitValue.value} ${apiLimitUnit.value}`
  for (const [, key] of TEXT_RATE_FIELDS) {
    config.value[key as RateFieldKey] = `${rateValues.value[key]} ${rateUnits.value[key]}`
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
const requestController = new AbortController()
onBeforeUnmount(() => {
  unmounted = true
  requestController.abort()
})

async function loadConfig() {
  if (unmounted || loadingConfig.value) return
  loadingConfig.value = true
  loadError.value = ''
  try {
    const cfg = await api.adminGetConfig(requestController.signal)
    if (unmounted) return
    if (isUnauthorizedResponse(cfg)) {
      emit('unauthorized')
      return
    }
    if (!isAdminConfig(cfg) || cfg.error) {
      loadError.value = () => t('interface.admin_panel.could_not_read_the_server_settings_please_try_again')
      return
    }
    config.value = { ...cfg }
    delete config.value.error
    syncRateLimitsFromConfig()
    configLoaded.value = true
  } catch (error: unknown) {
    if (unmounted) return
    if (isUnauthorizedError(error)) {
      emit('unauthorized')
    } else {
      loadError.value = error instanceof Error ? error.message : (() => t('interface.admin_panel.could_not_load_settings_please_try_again'))
    }
  } finally {
    if (!unmounted) loadingConfig.value = false
  }
}

function validate(): (() => string) | null {
  const c = config.value
  const ratePattern = /^\s*[1-9]\d*\s+per(?:\s+[1-9]\d*)?\s+(second|minute|hour|day)s?\s*$/i
  if (c.MAX_USERS_PER_PARTY < 0 || !Number.isInteger(c.MAX_USERS_PER_PARTY)) return () => t('interface.admin_panel.max_users_must_be_a_positive_integer')
  if (c.HLS_TOKEN_EXPIRY < 300) return () => t('interface.admin_panel.hls_token_expiry_must_be_at_least_300_seconds')
  if (c.LOG_MAX_SIZE < 1) return () => t('interface.admin_panel.max_log_size_must_be_at_least_1_mb')
  if (partyLimitValue.value < 1) return () => t('interface.admin_panel.party_creation_limit_must_be_at_least_1')
  if (apiLimitValue.value < 1) return () => t('interface.admin_panel.api_rate_limit_must_be_at_least_1')
  for (const [label, key] of TEXT_RATE_FIELDS) {
    const count = rateValues.value[key]
    if (!count || count < 1) return () => t('interface.admin_panel.minimum_rate', { label: t(label) })
    if (!ratePattern.test(`${count} ${rateUnits.value[key]}`)) {
      return () => t('interface.admin_panel.invalid_rate', { label: t(label) })
    }
  }
  if (!c.LOG_FILE || !c.LOG_FILE.trim()) return () => t('interface.admin_panel.log_file_path_cannot_be_empty')
  return null
}

async function saveConfig() {
  if (!configLoaded.value || loadingConfig.value || saving.value || unmounted) return
  const err = validate()
  if (err) {
    saveStatus.value = err
    saveClass.value = 'error'
    return
  }
  saveStatus.value = () => t('interface.admin_panel.saving')
  saveClass.value = ''
  saving.value = true
  syncRateLimitsToConfig()
  try {
    const result = await api.adminUpdateConfig(config.value, requestController.signal)
    if (unmounted) return
    if (isUnauthorizedResponse(result)) {
      emit('unauthorized')
      return
    }
    if (result.success) {
      const changed = result.changed || []
      const rejected = result.rejected || []
      const restart = result.restart_required || []
      const parts: (() => string)[] = []
      if (changed.length) {
        parts.push(() => t('interface.admin_panel.saved_fields', { fields: changed.join(', ') }))
      } else {
        parts.push(() => t('interface.admin_panel.no_changes'))
      }
      if (restart.length) {
        parts.push(() => t('interface.admin_panel.restart_fields', { fields: restart.join(', ') }))
      }
      if (rejected.length) {
        parts.push(
          () => t('interface.admin_panel.rejected_fields', { fields: rejected.map((r) => `${r.key} (${r.reason})`).join('; ') }),
        )
      }
      saveStatus.value = () => parts.map((part) => part()).join(' | ')
      saveClass.value = rejected.length ? 'warning' : 'success'
      if (isAdminConfig(result.config)) {
        config.value = { ...result.config }
        delete config.value.error
      }
      if (changed.includes('REQUIRE_LOGIN')) {
        auth.refresh().catch(() => { /* ignore */ })
      }
    } else {
      saveStatus.value = result.error || (() => t('interface.admin_panel.save_failed_please_try_again'))
      saveClass.value = 'error'
    }
  } catch (error: unknown) {
    if (unmounted) return
    if (isUnauthorizedError(error)) {
      emit('unauthorized')
      return
    }
    saveStatus.value = error instanceof Error ? error.message : (() => t('interface.admin_panel.could_not_save_settings_please_try_again'))
    saveClass.value = 'error'
  } finally {
    if (!unmounted) saving.value = false
  }
}

loadConfig()
</script>

<template>
  <div class="admin-panel-body">
    <div v-if="loadingConfig" class="admin-config-state" role="status">{{ t('interface.admin_panel.loading_settings') }}</div>
    <div v-else-if="displayedLoadError" class="admin-config-state admin-config-error" role="alert">
      <span>{{ displayedLoadError }}</span>
      <button type="button" class="btn btn-small" @click="loadConfig">{{ t('interface.admin_panel.retry') }}</button>
    </div>
    <div v-if="configLoaded" class="admin-grid">
      <!-- Auth -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.auth') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.require_login_to_create_party') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.login_hint', { provider: auth.mediaServerName }) }}</span>
          </div>
          <ToggleSwitch v-model="config.REQUIRE_LOGIN" :label="t('interface.admin_panel.require_login_to_create_party')" />
        </div>
      </div>

      <!-- Playback -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.playback') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.force_transcode') }}</span>
            <span class="setting-hint">
              {{ t('interface.admin_panel.transcode_off_hint', { provider: auth.mediaServerName }) }}
              <br /><br />
              {{ t('interface.admin_panel.transcode_on_hint', { provider: auth.mediaServerName, flag: 'EnableAutoStreamCopy=false' }) }}
              <br /><br />
              {{ t('interface.admin_panel.transcode_seek_hint', { provider: auth.mediaServerName }) }}
            </span>
          </div>
          <ToggleSwitch v-model="config.FORCE_TRANSCODE" :label="t('interface.admin_panel.force_transcode')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.binge_watch') }}</span>
            <span class="setting-hint"> {{ t('interface.admin_panel.off_default_the_binge_watch_button_is_hidden_from_the_host_s_control_strip_entir') }} <br /><br /> {{ t('interface.admin_panel.on_the_host_gets_a_binge_on_off_pill_in_the_control_strip_while_an_episode_is_pl') }} <br /><br /> {{ t('interface.admin_panel.turning_this_off_mid_session_hides_the_button_in_every_active_party_and_cancels_') }} </span>
          </div>
          <ToggleSwitch v-model="config.BINGE_WATCH_ENABLED" :label="t('interface.admin_panel.binge_watch')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.binge_countdown_s') }}</span>
            <span class="setting-hint"> {{ t('interface.admin_panel.seconds_shown_to_the_room_before_the_next_episode_auto_plays_any_user_can_hit_ca') }} </span>
          </div>
          <input type="number" v-model.number="config.BINGE_WATCH_COUNTDOWN_SECONDS" min="1" max="30" step="1" class="setting-input setting-input-sm" />
        </div>
      </div>

      <!-- Quality -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.quality') }}</h2>
        <div class="setting-row quality-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.enabled_resolutions_bitrates') }}</span>
            <span class="setting-hint"> {{ t('interface.admin_panel.tick_a_resolution_to_expose_it_in_the_per_user_quality_dropdown_the_bitrate_chec') }} <br /><br />
              {{ t('interface.admin_panel.quality_auto_hint', { provider: auth.mediaServerName }) }} </span>
          </div>
          <div class="quality-tier-list">
            <div
              v-for="tier in resolutionTiers"
              :key="tier.resolution"
              class="quality-tier"
            >
              <div class="quality-master">
                <ToggleSwitch
                  :label="t('interface.admin_panel.quality_label', { resolution: tier.resolution })"
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
                    :label="t('interface.admin_panel.bitrate_label', { resolution: tier.resolution, bitrate: formatBitrate(kbps) })"
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
        <h2 class="card-title">{{ t('interface.admin_panel.logging') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.log_level') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.application_log_verbosity') }}</span>
          </div>
          <select v-model="config.LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.console_log_level') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.terminal_output_verbosity') }}</span>
          </div>
          <select v-model="config.CONSOLE_LOG_LEVEL">
            <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.log_to_file') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.write_logs_to_disk') }}</span>
          </div>
          <ToggleSwitch v-model="config.LOG_TO_FILE" :label="t('interface.admin_panel.log_to_file')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.log_file') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.path_to_log_file') }}</span>
          </div>
          <input v-model="config.LOG_FILE" type="text" class="setting-input" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.log_format') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.rsyslog_or_standard') }}</span>
          </div>
          <select v-model="config.LOG_FORMAT">
            <option value="rsyslog">rsyslog</option>
            <option value="standard">standard</option>
          </select>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.max_log_size_mb') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.log_file_rotation_size') }}</span>
          </div>
          <input type="number" v-model.number="config.LOG_MAX_SIZE" min="1" max="100" step="1" class="setting-input setting-input-sm" />
        </div>
      </div>

      <!-- Security -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.security') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.max_users_per_party') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.0_unlimited') }}</span>
          </div>
          <input type="number" v-model.number="config.MAX_USERS_PER_PARTY" min="0" max="100" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.hls_token_expiry_s') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.token_lifetime_default_86400_24h') }}</span>
          </div>
          <input type="number" v-model.number="config.HLS_TOKEN_EXPIRY" min="300" max="604800" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.rate_limiting') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.master_switch_for_http_and_socket_io_limits') }}</span>
          </div>
          <ToggleSwitch v-model="config.ENABLE_RATE_LIMITING" :label="t('interface.admin_panel.rate_limiting')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.party_creation_limit') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.max_per_ip') }}</span>
          </div>
          <div class="rate-limit-group">
            <input type="number" v-model.number="partyLimitValue" min="1" class="setting-input setting-input-xs" />
            <select v-model="partyLimitUnit">
              <option value="per minute">{{ t('interface.admin_panel.per_minute') }}</option>
              <option value="per hour">{{ t('interface.admin_panel.per_hour') }}</option>
              <option value="per day">{{ t('interface.admin_panel.per_day') }}</option>
            </select>
          </div>
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.api_rate_limit') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.max_per_ip') }}</span>
          </div>
          <div class="rate-limit-group">
            <input type="number" v-model.number="apiLimitValue" min="1" class="setting-input setting-input-xs" />
            <select v-model="apiLimitUnit">
              <option value="per minute">{{ t('interface.admin_panel.per_minute') }}</option>
              <option value="per hour">{{ t('interface.admin_panel.per_hour') }}</option>
              <option value="per day">{{ t('interface.admin_panel.per_day') }}</option>
            </select>
          </div>
        </div>
        <div
          v-for="field in TEXT_RATE_FIELDS"
          :key="field[1]"
          class="setting-row"
        >
          <div class="setting-label">
            <span>{{ t(field[0]) }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.max_per_ip') }}</span>
          </div>
          <div class="rate-limit-group">
            <input
              v-model.number="rateValues[field[1]]"
              type="number"
              min="1"
              class="setting-input setting-input-xs"
              :aria-label="t(field[0])"
            />
            <select v-model="rateUnits[field[1]]" :aria-label="t('interface.admin_panel.rate_window_label', { label: t(field[0]) })">
              <option v-for="window in windowsFor(rateUnits[field[1]] || '')" :key="window" :value="window">
                {{ rateWindowLabel(window) }}
              </option>
            </select>
          </div>
        </div>
      </div>

      <!-- Session -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.session') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.static_session_mode') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.single_persistent_party_that_auto_creates_on_startup') }}</span>
          </div>
          <ToggleSwitch v-model="config.STATIC_SESSION_ENABLED" :label="t('interface.admin_panel.static_session_mode')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.static_session_id') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.party_code_for_static_session') }}</span>
          </div>
          <input v-model="config.STATIC_SESSION_ID" type="text" class="setting-input setting-input-sm" style="text-transform:uppercase;" />
        </div>
      </div>

      <!-- Late Join Vote -->
      <div class="admin-card card">
        <h2 class="card-title">{{ t('interface.admin_panel.late_join_vote') }}</h2>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.enable_late_join_vote') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.require_a_majority_vote_to_admit_users_who_join_mid_playback') }}</span>
          </div>
          <ToggleSwitch v-model="config.LATE_JOIN_VOTE_ENABLED" :label="t('interface.admin_panel.enable_late_join_vote')" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.vote_timeout_s') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.seconds_before_selector_tiebreak_kicks_in') }}</span>
          </div>
          <input type="number" v-model.number="config.LATE_JOIN_VOTE_TIMEOUT_SECONDS" min="5" max="300" step="1" class="setting-input setting-input-sm" />
        </div>
        <div class="setting-row">
          <div class="setting-label">
            <span>{{ t('interface.admin_panel.post_vote_cooldown_s') }}</span>
            <span class="setting-hint">{{ t('interface.admin_panel.delay_after_a_failed_vote_before_another_join_attempt_is_allowed_0_disables') }}</span>
          </div>
          <input type="number" v-model.number="config.LATE_JOIN_VOTE_COOLDOWN_SECONDS" min="0" max="600" step="1" class="setting-input setting-input-sm" />
        </div>
      </div>
    </div>

    <div class="admin-panel-footer">
      <span :class="['save-status', saveClass]">{{ displayedSaveStatus }}</span>
      <button @click="saveConfig" :disabled="!configLoaded || loadingConfig || saving" class="btn btn-primary">
        {{ saving ? t('interface.admin_panel.saving') : t('interface.admin_panel.save_settings') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.admin-panel-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

.admin-config-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-md);
}

.admin-config-error {
  color: var(--color-danger);
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
