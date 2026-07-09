<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  resumeSeconds: number
  runTimeSeconds: number | null
}>()

const emit = defineEmits<{
  resume: []
  startOver: []
  cancel: []
}>()

function formatTimestamp(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const hh = Math.floor(s / 3600)
  const mm = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (hh > 0) {
    return `${hh}:${mm.toString().padStart(2, '0')}:${ss.toString().padStart(2, '0')}`
  }
  return `${mm}:${ss.toString().padStart(2, '0')}`
}

const resumeLabel = computed(() => formatTimestamp(props.resumeSeconds))
const progressPercent = computed(() => {
  if (!props.runTimeSeconds || props.runTimeSeconds <= 0) return 0
  return Math.min(100, Math.max(0, (props.resumeSeconds / props.runTimeSeconds) * 100))
})
</script>

<template>
  <div class="resume-backdrop" @click.self="emit('cancel')">
    <div class="resume-modal" role="dialog" aria-label="Resume playback">
      <div class="label">Continue watching?</div>
      <h2 class="title">{{ title }}</h2>
      <div class="meta">
        You stopped at <strong>{{ resumeLabel }}</strong>
        <span v-if="progressPercent > 0" class="meta-pct">({{ Math.round(progressPercent) }}%)</span>
      </div>

      <div class="progress" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100" role="progressbar">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
      </div>

      <div class="actions">
        <button class="resume" @click="emit('resume')">Resume from {{ resumeLabel }}</button>
        <button class="start-over" @click="emit('startOver')">Start over</button>
      </div>
      <button class="cancel" @click="emit('cancel')">Cancel</button>
    </div>
  </div>
</template>

<style scoped>
.resume-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
}

.resume-modal {
  /* Solid (not glass) -- the host needs to read the title cleanly
     and earlier the library cards bled through .bg-surface, which
     uses a translucent treatment shared with the topbar / library
     panel. .bg-secondary is the same solid token VersionPickerModal
     uses, so the two pickers read as members of the same family. */
  background: var(--bg-secondary, #181820);
  color: var(--color-text, #e8e8e8);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 28px 30px 22px;
  min-width: 360px;
  max-width: 520px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6),
              0 0 0 1px rgba(0, 224, 255, 0.08) inset;
}

.label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-accent-cyan, #00e0ff);
  margin-bottom: 6px;
}

.title {
  margin: 0 0 8px;
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.25;
}

.meta {
  font-size: 0.95rem;
  color: var(--color-text-muted, #aaa);
  margin-bottom: 14px;
}

.meta strong {
  font-family: 'Monaco', 'Consolas', monospace;
  color: var(--color-text, #e8e8e8);
}

.meta-pct {
  margin-left: 6px;
  opacity: 0.7;
}

.progress {
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 18px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #00e0ff, #ff3ed6);
}

.actions {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}

.resume,
.start-over,
.cancel {
  flex: 1;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, filter 0.15s;
  border: 1px solid var(--border-subtle);
  font-family: var(--font-sans);
}

.resume {
  background: linear-gradient(90deg, rgba(0, 224, 255, 0.22), rgba(255, 62, 214, 0.22));
  border-color: rgba(0, 224, 255, 0.6);
  color: var(--text-primary, #fff);
  box-shadow: 0 0 12px rgba(0, 224, 255, 0.18);
}

.resume:hover {
  filter: brightness(1.1);
}

.start-over {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary, #fff);
}

.start-over:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--border-hover);
}

.cancel {
  flex: none;
  width: 100%;
  background: transparent;
  border-color: transparent;
  color: var(--color-text-muted, #aaa);
  font-weight: 500;
  padding: 6px 12px;
}

.cancel:hover {
  color: var(--color-text, #e8e8e8);
}
</style>
