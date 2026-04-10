<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { usePartyStore } from '@/stores/party'

const party = usePartyStore()

const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  tick = setInterval(() => {
    now.value = Date.now()
  }, 500)
})

onUnmounted(() => {
  if (tick) clearInterval(tick)
})

const secondsRemaining = computed(() => {
  if (!party.pendingVote) return 0
  return Math.max(0, Math.ceil((party.pendingVote.timeoutAt - now.value) / 1000))
})

const timerLabel = computed(() => {
  const s = secondsRemaining.value
  const mm = Math.floor(s / 60).toString().padStart(2, '0')
  const ss = (s % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
})

// Show anonymized progress to the late joiner. We don't leak which
// individual user voted which way -- only the aggregate count. This
// keeps the experience less awkward if the vote fails.
const progressText = computed(() => {
  if (!party.pendingVote) return ''
  const total = party.pendingVote.eligibleVoters.length
  const voted = Object.keys(party.pendingVote.votes).length
  return `${voted} of ${total} have voted`
})
</script>

<template>
  <div v-if="party.pendingVote && party.pendingVote.isPending" class="waiting-room">
    <div class="waiting-content">
      <div class="spinner"></div>
      <h2>Waiting for party approval</h2>
      <p class="explain">
        Your request to join is being reviewed. The party will decide
        whether to restart the video so you can join in sync.
      </p>

      <div class="timer">
        Vote ends in <strong>{{ timerLabel }}</strong>
      </div>

      <div class="progress">{{ progressText }}</div>
    </div>
  </div>
</template>

<style scoped>
.waiting-room {
  position: fixed;
  inset: 0;
  background: var(--color-background, #0a0a0a);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9500;
}

.waiting-content {
  text-align: center;
  max-width: 440px;
  padding: 40px;
  color: var(--color-text, #e8e8e8);
}

.spinner {
  width: 64px;
  height: 64px;
  border: 4px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--color-accent, #6b9fff);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
  margin: 0 auto 24px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

h2 {
  margin: 0 0 12px;
  font-size: 1.5rem;
}

.explain {
  margin: 0 0 24px;
  color: var(--color-text-muted, #aaa);
  font-size: 0.95rem;
  line-height: 1.5;
}

.timer {
  font-size: 1rem;
  color: var(--color-accent, #6b9fff);
  margin-bottom: 8px;
}

.timer strong {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 1.2rem;
}

.progress {
  font-size: 0.9rem;
  color: var(--color-text-muted, #888);
}
</style>
