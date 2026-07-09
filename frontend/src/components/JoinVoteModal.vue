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

const hasVoted = computed(() => party.pendingVote?.myVote !== null)

const tallyText = computed(() => {
  if (!party.pendingVote) return ''
  const total = party.pendingVote.eligibleVoters.length
  const voted = Object.keys(party.pendingVote.votes).length
  return `${voted} of ${total} voted`
})

function vote(choice: 'yes' | 'no') {
  party.submitVote(choice)
}
</script>

<template>
  <div v-if="party.pendingVote && !party.pendingVote.isPending" class="vote-modal-backdrop">
    <div class="vote-modal">
      <h2>{{ party.pendingVote.lateJoinerUsername }} wants to join</h2>
      <p class="explain">
        Accepting will restart the video from the beginning so everyone stays in sync.
      </p>

      <div class="timer">Vote ends in <strong>{{ timerLabel }}</strong></div>

      <div v-if="!hasVoted" class="actions">
        <button class="accept" @click="vote('yes')">Accept</button>
        <button class="decline" @click="vote('no')">Decline</button>
      </div>
      <div v-else class="waiting">
        Your vote was recorded. Waiting for others...
      </div>

      <div class="tally">{{ tallyText }}</div>
      <ul class="voters">
        <li
          v-for="voter in party.pendingVote.eligibleVoters"
          :key="voter"
          :class="{
            voted: party.pendingVote.votes[voter] !== undefined,
            yes: party.pendingVote.votes[voter] === 'yes',
            no: party.pendingVote.votes[voter] === 'no',
          }"
        >
          {{ voter }}
          <span v-if="party.pendingVote.votes[voter] === 'yes'" class="mark yes">yes</span>
          <span v-else-if="party.pendingVote.votes[voter] === 'no'" class="mark no">no</span>
          <span v-else class="mark pending">waiting...</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.vote-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
}

.vote-modal {
  background: var(--color-background, #1a1a1a);
  color: var(--color-text, #e8e8e8);
  border-radius: 10px;
  padding: 32px 28px;
  min-width: 360px;
  max-width: 480px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6);
}

.vote-modal h2 {
  margin: 0 0 8px;
  font-size: 1.35rem;
}

.explain {
  margin: 0 0 16px;
  color: var(--color-text-muted, #aaa);
  font-size: 0.95rem;
}

.timer {
  font-size: 0.95rem;
  margin-bottom: 16px;
  color: var(--color-accent, #6b9fff);
}

.timer strong {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 1.1rem;
}

.actions {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.actions button {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s;
}

.actions button:hover {
  filter: brightness(1.1);
}

.accept {
  background: #2d8a5c;
  color: white;
}

.decline {
  background: #8a2d3a;
  color: white;
}

.waiting {
  padding: 12px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  text-align: center;
  color: var(--color-text-muted, #aaa);
  margin-bottom: 16px;
}

.tally {
  font-size: 0.85rem;
  color: var(--color-text-muted, #aaa);
  margin-bottom: 8px;
}

.voters {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.voters li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  font-size: 0.9rem;
}

.voters li.voted {
  background: var(--bg-surface-hover);
}

/* Vote pills mirror the chip language used everywhere else: rounded
   surface bg, cyan / pink dim tints, no flat saturated rectangles. */
.mark {
  font-size: 0.7rem;
  text-transform: uppercase;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  letter-spacing: 0.04em;
}

.mark.yes {
  background: var(--accent-green-dim);
  color: var(--accent-green);
  border: 1px solid rgba(52, 211, 153, 0.25);
}

.mark.no {
  background: rgba(244, 63, 94, 0.12);
  color: #fb7185;
  border: 1px solid rgba(244, 63, 94, 0.25);
}

.mark.pending {
  background: var(--bg-surface);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
}
</style>
