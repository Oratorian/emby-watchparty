<script setup lang="ts">
import { t } from '@/i18n'
import { computed, ref } from 'vue'
import { useAvatarStore } from '@/stores/avatar'
import { copyToClipboard } from '@/utils/clipboard'

const emit = defineEmits<{
  close: []
}>()

const avatar = useAvatarStore()

// "upload" | "gravatar" | "recover"
const tab = ref<'upload' | 'gravatar' | 'recover'>('upload')
const busy = ref(false)
const error = ref<string | (() => string) | null>(null)
const displayedError = computed(() => typeof error.value === 'function' ? error.value() : error.value)

const file = ref<File | null>(null)
const filePreview = ref<string | null>(null)
const email = ref('')
const recoverCode = ref('')
const copyLabel = ref('interface.avatar_setup.copy')

function readableError(value: unknown, fallback: () => string): string | (() => string) {
  return value instanceof Error ? value.message : fallback
}

function pickFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0] || null
  file.value = f
  filePreview.value = f ? URL.createObjectURL(f) : null
}

async function submitUpload() {
  if (!file.value) {
    error.value = () => t('interface.avatar_setup.pick_an_image_first')
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.uploadImage(file.value)
    if (!res.success) {
      error.value = res.message || (() => t('interface.avatar_setup.upload_failed'))
    }
  } catch (reason: unknown) {
    error.value = readableError(reason, () => t('interface.avatar_setup.upload_failed'))
  } finally {
    busy.value = false
  }
}

async function submitGravatar() {
  if (!email.value.trim()) {
    error.value = () => t('interface.avatar_setup.enter_your_email_address')
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.setGravatar(email.value.trim())
    if (!res.success) {
      error.value = res.message || (() => t('interface.avatar_setup.could_not_register_gravatar'))
    }
  } catch (reason: unknown) {
    error.value = readableError(reason, () => t('interface.avatar_setup.could_not_register_gravatar'))
  } finally {
    busy.value = false
  }
}

async function submitRecover() {
  if (!recoverCode.value.trim()) {
    error.value = () => t('interface.avatar_setup.enter_your_recovery_code')
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.recover(recoverCode.value.trim())
    if (res.success) {
      emit('close')
    } else {
      error.value = res.message || (() => t('interface.avatar_setup.code_not_recognised'))
    }
  } catch (reason: unknown) {
    error.value = readableError(reason, () => t('interface.avatar_setup.code_not_recognised'))
  } finally {
    busy.value = false
  }
}

async function copyCode() {
  if (!avatar.pendingCode) return
  const ok = await copyToClipboard(avatar.pendingCode)
  copyLabel.value = ok ? 'interface.avatar_setup.copied' : 'interface.avatar_setup.failed'
  setTimeout(() => { copyLabel.value = 'interface.avatar_setup.copy' }, 2000)
}

function acknowledge() {
  avatar.acknowledgeCode()
  emit('close')
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <!-- Confirmation screen after a successful create -->
      <template v-if="avatar.pendingCode">
        <h2>{{ t('interface.avatar_setup.save_your_recovery_code') }}</h2>
        <p> {{ t('interface.avatar_setup.this_code_is_the_only_way_to_restore_this_avatar_on_a_different_browser_or_after') }} </p>
        <div class="code-display">{{ avatar.pendingCode }}</div>
        <div class="actions">
          <button class="btn btn-secondary" @click="copyCode">{{ t(copyLabel) }}</button>
          <button class="btn btn-primary" @click="acknowledge">{{ t('interface.avatar_setup.i_saved_it') }}</button>
        </div>
      </template>

      <!-- Setup tabs -->
      <template v-else>
        <h2>{{ t('interface.avatar_setup.profile_avatar') }}</h2>
        <p class="hint">{{ t('interface.avatar_setup.pick_an_image_link_a_gravatar_or_restore_an_avatar_you_set_up_previously') }}</p>

        <div class="tabs">
          <button :class="{ active: tab === 'upload' }" @click="tab = 'upload'">{{ t('interface.avatar_setup.upload') }}</button>
          <button :class="{ active: tab === 'gravatar' }" @click="tab = 'gravatar'">Gravatar</button>
          <button :class="{ active: tab === 'recover' }" @click="tab = 'recover'">{{ t('interface.avatar_setup.i_have_a_code') }}</button>
        </div>

        <div v-if="tab === 'upload'" class="tab-body">
          <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="pickFile" />
          <img v-if="filePreview" :src="filePreview" class="preview" :alt="t('interface.avatar_setup.preview')" />
          <button class="btn btn-primary" :disabled="busy || !file" @click="submitUpload">
            {{ busy ? t('interface.avatar_setup.uploading') : t('interface.avatar_setup.upload') }}
          </button>
        </div>

        <div v-else-if="tab === 'gravatar'" class="tab-body">
          <input v-model="email" type="email" :placeholder="t('interface.avatar_setup.you_example_com')" />
          <p class="hint"> {{ t('interface.avatar_setup.your_address_is_hashed_before_upload_if_you_don_t_have_a_gravatar_account_a_plac') }} </p>
          <button class="btn btn-primary" :disabled="busy" @click="submitGravatar">
            {{ busy ? t('interface.avatar_setup.working') : t('interface.avatar_setup.use_gravatar') }}
          </button>
        </div>

        <div v-else class="tab-body">
          <input v-model="recoverCode" type="text" :placeholder="t('interface.avatar_setup.word_word_word')" />
          <button class="btn btn-primary" :disabled="busy" @click="submitRecover">
            {{ busy ? t('interface.avatar_setup.checking') : t('interface.avatar_setup.restore_avatar') }}
          </button>
        </div>

        <p v-if="displayedError" class="error">{{ displayedError }}</p>

        <div class="footer-actions">
          <button class="btn btn-ghost btn-small" @click="emit('close')">{{ t('interface.avatar_setup.close') }}</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  z-index: 1100;
}

.modal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: var(--space-xl);
  width: min(95vw, 480px);
  box-shadow: var(--shadow-lg);
}

.modal-card h2 {
  margin: 0 0 var(--space-sm);
}

.hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin: 0 0 var(--space-md);
}

.tabs {
  display: flex;
  gap: var(--space-xs);
  margin-bottom: var(--space-md);
}

.tabs button {
  flex: 1;
  padding: 0.4rem 0.6rem;
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.85rem;
}

.tabs button.active {
  background: var(--accent-primary-dim);
  color: var(--accent-primary);
  border-color: var(--accent-primary);
}

.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.preview {
  max-width: 96px;
  max-height: 96px;
  border-radius: var(--radius-full);
  align-self: flex-start;
  object-fit: cover;
}

.error {
  color: var(--color-danger);
  font-size: 0.85rem;
  margin: var(--space-sm) 0 0;
}

.footer-actions {
  margin-top: var(--space-md);
  text-align: right;
}

.code-display {
  font-family: var(--font-mono);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: var(--space-md);
  text-align: center;
  font-size: 1.4rem;
  letter-spacing: 0.05em;
  margin: var(--space-md) 0;
  user-select: all;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}
</style>
