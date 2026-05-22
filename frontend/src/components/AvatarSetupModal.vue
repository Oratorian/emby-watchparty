<script setup lang="ts">
import { ref } from 'vue'
import { useAvatarStore } from '@/stores/avatar'
import { copyToClipboard } from '@/utils/clipboard'

const emit = defineEmits<{
  close: []
}>()

const avatar = useAvatarStore()

// "upload" | "gravatar" | "recover"
const tab = ref<'upload' | 'gravatar' | 'recover'>('upload')
const busy = ref(false)
const error = ref<string | null>(null)

const file = ref<File | null>(null)
const filePreview = ref<string | null>(null)
const email = ref('')
const recoverCode = ref('')
const copyLabel = ref('Copy')

function pickFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0] || null
  file.value = f
  filePreview.value = f ? URL.createObjectURL(f) : null
}

async function submitUpload() {
  if (!file.value) {
    error.value = 'Pick an image first'
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.uploadImage(file.value)
    if (!res.success) {
      error.value = res.message || 'Upload failed'
    }
  } finally {
    busy.value = false
  }
}

async function submitGravatar() {
  if (!email.value.trim()) {
    error.value = 'Enter your email address'
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.setGravatar(email.value.trim())
    if (!res.success) {
      error.value = res.message || 'Could not register Gravatar'
    }
  } finally {
    busy.value = false
  }
}

async function submitRecover() {
  if (!recoverCode.value.trim()) {
    error.value = 'Enter your recovery code'
    return
  }
  busy.value = true
  error.value = null
  try {
    const res = await avatar.recover(recoverCode.value.trim())
    if (res.success) {
      emit('close')
    } else {
      error.value = res.message || 'Code not recognised'
    }
  } finally {
    busy.value = false
  }
}

async function copyCode() {
  if (!avatar.pendingCode) return
  const ok = await copyToClipboard(avatar.pendingCode)
  copyLabel.value = ok ? 'Copied!' : 'Failed'
  setTimeout(() => { copyLabel.value = 'Copy' }, 2000)
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
        <h2>Save your recovery code</h2>
        <p>
          This code is the only way to restore this avatar on a different
          browser or after clearing site data. We don't store it anywhere
          you can read.
        </p>
        <div class="code-display">{{ avatar.pendingCode }}</div>
        <div class="actions">
          <button class="btn btn-secondary" @click="copyCode">{{ copyLabel }}</button>
          <button class="btn btn-primary" @click="acknowledge">I saved it</button>
        </div>
      </template>

      <!-- Setup tabs -->
      <template v-else>
        <h2>Profile avatar</h2>
        <p class="hint">Pick an image, link a Gravatar, or restore an avatar you set up previously.</p>

        <div class="tabs">
          <button :class="{ active: tab === 'upload' }" @click="tab = 'upload'">Upload</button>
          <button :class="{ active: tab === 'gravatar' }" @click="tab = 'gravatar'">Gravatar</button>
          <button :class="{ active: tab === 'recover' }" @click="tab = 'recover'">I have a code</button>
        </div>

        <div v-if="tab === 'upload'" class="tab-body">
          <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="pickFile" />
          <img v-if="filePreview" :src="filePreview" class="preview" alt="preview" />
          <button class="btn btn-primary" :disabled="busy || !file" @click="submitUpload">
            {{ busy ? 'Uploading...' : 'Upload' }}
          </button>
        </div>

        <div v-else-if="tab === 'gravatar'" class="tab-body">
          <input v-model="email" type="email" placeholder="you@example.com" />
          <p class="hint">
            Your address is hashed before upload. If you don't have a Gravatar account,
            a placeholder identicon is used.
          </p>
          <button class="btn btn-primary" :disabled="busy" @click="submitGravatar">
            {{ busy ? 'Working...' : 'Use Gravatar' }}
          </button>
        </div>

        <div v-else class="tab-body">
          <input v-model="recoverCode" type="text" placeholder="word-word-word" />
          <button class="btn btn-primary" :disabled="busy" @click="submitRecover">
            {{ busy ? 'Checking...' : 'Restore avatar' }}
          </button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <div class="footer-actions">
          <button class="btn btn-ghost btn-small" @click="emit('close')">Close</button>
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
  color: var(--danger, #e25555);
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
