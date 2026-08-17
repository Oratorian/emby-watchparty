<script setup lang="ts">
import { ref } from 'vue'

import { useAuthStore } from '@/stores/auth'

interface MediaVersion {
  id: string
  name: string
  container: string | null
  run_time_ticks: number | null
}

defineProps<{
  itemName: string
  versions: MediaVersion[]
}>()

// The provider name is browser-visible copy here, so it follows the
// configured server rather than hardcoding Emby.
const auth = useAuthStore()

const emit = defineEmits<{
  select: [mediaSourceId: string]
  cancel: []
}>()

// Pre-select the first version so a quick double-click on "Play this
// version" is enough to confirm. The host can switch to any other
// option before confirming.
const selectedId = ref<string>('')

function formatLabel(v: MediaVersion): string {
  // Mirror what Emby's own clients show. `name` is "mp4" / "mkv" for
  // stacked-by-container files, or whatever custom label the user put
  // in the filename for stacked-by-edition releases (Theatrical /
  // Director's Cut / etc.).
  return v.name || v.container || v.id
}

function formatRuntime(ticks: number | null): string {
  if (!ticks) return ''
  const seconds = Math.floor(ticks / 10_000_000)
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function pick(id: string) {
  selectedId.value = id
}

function confirm() {
  if (selectedId.value) emit('select', selectedId.value)
}
</script>

<template>
  <div class="version-modal-backdrop" @click.self="emit('cancel')">
    <div class="version-modal">
      <h2>Pick a version</h2>
      <p class="subtitle">
        <strong>{{ itemName }}</strong> has multiple versions on your {{ auth.mediaServerName }}
        server. Whatever you pick is what everyone in the party will watch.
      </p>

      <ul class="versions">
        <li
          v-for="v in versions"
          :key="v.id"
          class="version-row"
          :class="{ selected: selectedId === v.id }"
          @click="pick(v.id)"
          tabindex="0"
          @keydown.enter="pick(v.id)"
          @keydown.space.prevent="pick(v.id)"
        >
          <div class="version-name">{{ formatLabel(v) }}</div>
          <div class="version-meta">
            <span v-if="v.container">{{ v.container.toUpperCase() }}</span>
            <span v-if="v.run_time_ticks" class="runtime">{{ formatRuntime(v.run_time_ticks) }}</span>
          </div>
        </li>
      </ul>

      <div class="actions">
        <button class="btn btn-ghost" @click="emit('cancel')">Cancel</button>
        <button
          class="btn btn-primary"
          :disabled="!selectedId"
          @click="confirm"
        >
          Play this version
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.version-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: grid;
  place-items: center;
  z-index: 9000;
  padding: var(--space-md);
}

.version-modal {
  width: min(440px, 100%);
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-xl);
  box-shadow: var(--shadow-lg);
}

.version-modal h2 {
  margin: 0 0 6px;
  font-size: 1.2rem;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin: 0 0 var(--space-md);
  line-height: 1.5;
}

.versions {
  list-style: none;
  margin: 0 0 var(--space-md);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.version-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-md);
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
  outline: none;
}

.version-row:hover,
.version-row:focus {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.version-row.selected {
  background: var(--accent-primary-dim);
  border-color: var(--border-accent);
}

.version-name {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.version-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.version-meta .runtime {
  opacity: 0.85;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
