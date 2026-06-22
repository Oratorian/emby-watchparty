<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { usePartyStore } from '@/stores/party'

const party = usePartyStore()

const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  tick = setInterval(() => {
    now.value = Date.now()
  }, 200)
})

onUnmounted(() => {
  if (tick) clearInterval(tick)
})

const secondsRemaining = computed(() => {
  if (!party.pendingAutoAdvance) return 0
  return Math.max(0, Math.ceil((party.pendingAutoAdvance.timeoutAt - now.value) / 1000))
})

const progressPercent = computed(() => {
  if (!party.pendingAutoAdvance) return 0
  const remaining = party.pendingAutoAdvance.timeoutAt - now.value
  const total = remaining + (Date.now() - now.value) || 1
  // total is wonky on first tick; fall back to seconds-based bar.
  if (secondsRemaining.value <= 0) return 100
  return Math.max(0, Math.min(100, (1 - remaining / 4000) * 100))
})

function cancel() {
  party.cancelAutoAdvance()
}
</script>

<template>
  <div v-if="party.pendingAutoAdvance" class="autoadvance-backdrop">
    <div class="autoadvance-modal">
      <div class="label">Up next</div>
      <h2 class="title">{{ party.pendingAutoAdvance.nextTitle }}</h2>
      <div class="meta">
        Episode {{ party.pendingAutoAdvance.nextIndexNumber }}
        of {{ party.pendingAutoAdvance.totalEpisodes }}
      </div>

      <div class="countdown">
        Playing in <strong>{{ secondsRemaining }}s</strong>
      </div>
      <div class="progress" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100" role="progressbar">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
      </div>

      <div class="actions">
        <button class="cancel" @click="cancel">Cancel</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Centered over the video element. Mounted inside .video-wrapper
   (PartyView), which is position:relative, so absolute positioning
   pins us to that container -- not to the viewport. That keeps the
   modal off the chat panel, the topbar, and the seekbar regardless
   of how the surrounding layout flexes. inset:0 + flex centring
   handles both axes without a transform translate (which can blur
   text on some retina displays). */
.autoadvance-backdrop {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 30;
  pointer-events: none;
}

.autoadvance-modal {
  background: var(--bg-surface, #181820);
  color: var(--color-text, #e8e8e8);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 18px 22px;
  min-width: 320px;
  max-width: 460px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6),
              0 0 0 1px rgba(0, 224, 255, 0.08) inset;
  pointer-events: auto;
}

.label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-accent-cyan, #00e0ff);
  margin-bottom: 4px;
}

.title {
  margin: 0 0 4px;
  font-size: 1.1rem;
  font-weight: 600;
  line-height: 1.25;
}

.meta {
  font-size: 0.85rem;
  color: var(--color-text-muted, #9aa);
  margin-bottom: 12px;
}

.countdown {
  font-size: 0.9rem;
  margin-bottom: 6px;
  color: var(--color-text-muted, #aaa);
}

.countdown strong {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 1rem;
  color: var(--color-text, #e8e8e8);
}

.progress {
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 14px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #00e0ff, #ff3ed6);
  transition: width 200ms linear;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.cancel {
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text, #e8e8e8);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  padding: 7px 14px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.cancel:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--color-accent-magenta, #ff3ed6);
}
</style>
