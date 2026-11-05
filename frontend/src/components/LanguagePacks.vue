<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, api, type LanguagePackSummary } from '@/api/client'
import { languagePackError, refreshLanguagePacks, t } from '@/i18n'

const emit = defineEmits<{ unauthorized: [] }>()
const MAX_UPLOAD_BYTES = 1024 * 1024
const open = ref(false)
const loading = ref(false)
const loaded = ref(false)
const busy = ref(false)
const downloading = ref(false)
const packs = ref<LanguagePackSummary[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const pendingRemoval = ref<string | null>(null)
const error = ref<string | (() => string)>('')
const status = ref<(() => string) | null>(null)
const refreshPending = ref(false)
const displayedError = computed(() => typeof error.value === 'function' ? error.value() : error.value)
const displayedStatus = computed(() => status.value?.() || '')
const controllers = new Set<AbortController>()
let disposed = false
let listRevision = 0

function controller() {
  const current = new AbortController()
  controllers.add(current)
  return current
}

function failure(cause: unknown, key: string) {
  if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
    emit('unauthorized')
    return
  }
  error.value = cause instanceof ApiError ? cause.message : () => t(key)
}

async function load() {
  const revision = ++listRevision
  const request = controller()
  loading.value = true
  error.value = ''
  try {
    const result = await api.languagePacks(request.signal)
    if (disposed || revision !== listRevision) return
    if (!result || !Array.isArray(result.languages)
      || result.languages.some(pack => !pack || ['locale', 'name', 'author', 'version', 'revision']
        .some(key => typeof (pack as unknown as Record<string, unknown>)[key] !== 'string'))) {
      throw new Error('Invalid language list')
    }
    packs.value = result.languages
    loaded.value = true
  } catch (cause) {
    if (!disposed && revision === listRevision && !request.signal.aborted) {
      failure(cause, 'languagePacks.list_failed')
    }
  } finally {
    controllers.delete(request)
    if (!disposed && revision === listRevision) loading.value = false
  }
}

function toggle() {
  if (busy.value) return
  open.value = !open.value
  if (open.value) {
    void load()
  } else {
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
  }
}

function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  selectedFile.value = null
  error.value = ''
  status.value = null
  refreshPending.value = false
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    error.value = () => t('languagePacks.zip_required')
  } else if (file.size === 0 || file.size > MAX_UPLOAD_BYTES) {
    error.value = () => t('languagePacks.size_limit')
  } else {
    selectedFile.value = file
  }
}

async function refreshViewers() {
  try {
    await refreshLanguagePacks(true)
    if (!disposed) refreshPending.value = languagePackError.value
  } catch {
    if (!disposed) refreshPending.value = true
  }
}

watch(languagePackError, failed => {
  if (!failed) refreshPending.value = false
})

async function upload() {
  const file = selectedFile.value
  if (!file || busy.value) return
  const request = controller()
  busy.value = true
  error.value = ''
  status.value = null
  refreshPending.value = false
  ++listRevision
  loading.value = false
  try {
    const pack = await api.languagePackUpload(file, request.signal)
    if (disposed) return
    ++listRevision
    packs.value = [...packs.value.filter(existing => existing.locale !== pack.locale), pack]
      .sort((left, right) => left.name.localeCompare(right.name))
    loaded.value = true
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    pendingRemoval.value = null
    status.value = () => t('languagePacks.installed', { name: pack.name })
    await refreshViewers()
  } catch (cause) {
    if (!disposed && !request.signal.aborted) failure(cause, 'languagePacks.upload_failed')
  } finally {
    controllers.delete(request)
    if (!disposed) busy.value = false
  }
}

async function remove(pack: LanguagePackSummary) {
  if (busy.value || pendingRemoval.value !== pack.locale) return
  const request = controller()
  busy.value = true
  error.value = ''
  status.value = null
  refreshPending.value = false
  ++listRevision
  loading.value = false
  try {
    const result = await api.languagePackRemove(pack.locale, request.signal)
    if (disposed) return
    if (result?.success !== true) throw new Error('Language pack removal failed')
    ++listRevision
    packs.value = packs.value.filter(existing => existing.locale !== pack.locale)
    loaded.value = true
    pendingRemoval.value = null
    status.value = () => t('languagePacks.removed', { name: pack.name })
    await refreshViewers()
  } catch (cause) {
    if (!disposed && !request.signal.aborted) failure(cause, 'languagePacks.remove_failed')
  } finally {
    controllers.delete(request)
    if (!disposed) busy.value = false
  }
}

async function downloadTemplate() {
  if (downloading.value) return
  const request = controller()
  downloading.value = true
  error.value = ''
  try {
    const blob = await api.languagePackTemplate(request.signal)
    if (disposed) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'watchparty-language-template.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  } catch (cause) {
    if (!disposed && !request.signal.aborted) failure(cause, 'languagePacks.template_failed')
  } finally {
    controllers.delete(request)
    if (!disposed) downloading.value = false
  }
}

onBeforeUnmount(() => {
  disposed = true
  ++listRevision
  for (const request of controllers) request.abort()
  controllers.clear()
})
</script>

<template>
  <section class="language-packs card">
    <h2>{{ t('languagePacks.title') }}</h2>
    <p>{{ t('languagePacks.description') }}</p>
    <button type="button" class="btn btn-secondary btn-small" :aria-expanded="open" :disabled="busy" @click="toggle">
      {{ t(open ? 'languagePacks.hide' : 'languagePacks.manage') }}
    </button>
    <div v-if="open" class="pack-management">
      <p class="pack-hint">{{ t('languagePacks.builtins') }}</p>
      <div class="pack-actions">
        <button type="button" class="btn btn-ghost btn-small" :disabled="downloading" @click="downloadTemplate">
          {{ t(downloading ? 'languagePacks.downloading' : 'languagePacks.template') }}
        </button>
        <button type="button" class="btn btn-ghost btn-small" :disabled="loading || busy" @click="load">
          {{ t('languagePacks.refresh') }}
        </button>
      </div>
      <p class="pack-hint">{{ t('languagePacks.format_hint') }}</p>
      <form class="pack-upload" @submit.prevent="upload">
        <label>
          <span>{{ t('languagePacks.choose_zip') }}</span>
          <input ref="fileInput" type="file" accept=".zip,application/zip,application/x-zip-compressed" :disabled="busy" @change="chooseFile" />
        </label>
        <button type="submit" class="btn btn-primary btn-small" :disabled="!selectedFile || busy">
          {{ t(busy ? 'languagePacks.working' : 'languagePacks.upload') }}
        </button>
      </form>
      <p class="pack-hint">{{ t('languagePacks.replacement_hint') }}</p>
      <p v-if="loading" role="status">{{ t('languagePacks.loading') }}</p>
      <p v-else-if="loaded && !packs.length" class="pack-hint">{{ t('languagePacks.empty') }}</p>
      <ul v-if="packs.length" class="pack-list">
        <li v-for="pack in packs" :key="pack.locale">
          <div class="pack-summary">
            <strong>{{ pack.name }}</strong>
            <span lang="en">{{ pack.locale }}</span>
            <span v-if="pack.version">{{ t('languagePacks.version', { version: pack.version }) }}</span>
            <span v-if="pack.author">{{ t('languagePacks.author', { author: pack.author }) }}</span>
          </div>
          <div v-if="pendingRemoval === pack.locale" class="pack-confirmation">
            <p>{{ t('languagePacks.confirm_remove', { name: pack.name }) }}</p>
            <div class="pack-actions">
              <button type="button" class="btn btn-danger btn-small" :disabled="busy" @click="remove(pack)">{{ t('languagePacks.confirm') }}</button>
              <button type="button" class="btn btn-ghost btn-small" :disabled="busy" @click="pendingRemoval = null">{{ t('languagePacks.cancel') }}</button>
            </div>
          </div>
          <button v-else type="button" class="btn btn-ghost btn-small" :disabled="busy" :aria-label="t('languagePacks.remove_named', { name: pack.name })" @click="pendingRemoval = pack.locale">
            {{ t('languagePacks.remove') }}
          </button>
        </li>
      </ul>
      <p v-if="displayedError" class="pack-error" role="alert">{{ displayedError }}</p>
      <p v-if="displayedStatus" class="pack-success" role="status">{{ displayedStatus }}</p>
      <p v-if="refreshPending" class="pack-hint" role="status">{{ t('languagePacks.refresh_pending') }}</p>
    </div>
  </section>
</template>

<style scoped>
.language-packs { min-width: 0; padding: var(--space-lg); }
h2 { color: var(--accent-secondary); font-size: 1.05rem; margin-bottom: var(--space-md); }
p { margin: .7rem 0; font-size: .85rem; overflow-wrap: anywhere; }
.pack-hint { color: var(--text-secondary); font-size: .8rem; }
.pack-management { margin-top: var(--space-md); }
.pack-actions, .pack-upload { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.pack-upload { align-items: flex-end; margin: 1rem 0; }
.pack-upload label { display: grid; gap: .4rem; min-width: 0; max-width: 100%; font-size: .85rem; }
.pack-upload input { max-width: 100%; min-width: 0; font: inherit; }
.pack-list { list-style: none; padding: 0; margin: 1rem 0 0; }
.pack-list li { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: .75rem; padding: .8rem 0; border-top: 1px solid var(--border-subtle); }
.pack-summary { display: flex; align-items: baseline; flex-wrap: wrap; gap: .35rem .6rem; min-width: 0; overflow-wrap: anywhere; }
.pack-summary span { color: var(--text-secondary); font-size: .8rem; }
.pack-confirmation { flex-basis: 100%; }
.pack-error { color: var(--color-danger); }
.pack-success { color: var(--color-success); }
.btn { white-space: normal; }
</style>
