<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  title?: string
  description?: string
  submitLabel?: string
  busy?: boolean
  errorMessage?: string | null
}>()

const emit = defineEmits<{
  submit: [{ username: string; password: string }]
  cancel: []
}>()

const username = ref('')
const password = ref('')

function submit() {
  if (!username.value || !password.value) return
  emit('submit', { username: username.value, password: password.value })
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('cancel')">
    <div class="modal-card">
      <h2>{{ props.title || 'Emby Login' }}</h2>
      <p v-if="props.description">{{ props.description }}</p>

      <form @submit.prevent="submit">
        <input
          v-model="username"
          type="text"
          placeholder="Emby username"
          autocomplete="username"
          autofocus
          :disabled="props.busy"
        />
        <input
          v-model="password"
          type="password"
          placeholder="Emby password"
          autocomplete="current-password"
          :disabled="props.busy"
        />

        <p v-if="props.errorMessage" class="error">{{ props.errorMessage }}</p>

        <div class="actions">
          <button
            type="button"
            class="btn btn-secondary"
            @click="emit('cancel')"
            :disabled="props.busy"
          >
            Cancel
          </button>
          <button type="submit" class="btn btn-primary" :disabled="props.busy">
            {{ props.busy ? 'Working...' : (props.submitLabel || 'Sign in') }}
          </button>
        </div>
      </form>
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
  max-width: 420px;
  width: 90%;
  box-shadow: var(--shadow-lg);
}

.modal-card h2 {
  margin: 0 0 var(--space-sm);
}

.modal-card p {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin: 0 0 var(--space-md);
}

form {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.error {
  color: var(--danger, #e25555);
  font-size: 0.85rem;
  margin: 0;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
}
</style>
