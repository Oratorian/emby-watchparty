import { onUnmounted } from 'vue'
import { hideParty } from '@/utils/hiddenParties'
import type { ServerToClientPayloads } from '@/types/socket.generated'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

const events = [
  'join_vote_started',
  'join_vote_pending',
  'join_vote_update',
  'join_vote_resolved',
  'join_rejected',
] as const

export function usePartyVoting(socket: SocketStore, party: PartyStore) {
  const voteStarted = (data: ServerToClientPayloads['join_vote_started']) => {
    party.pendingVote = {
      active: true,
      isPending: false,
      lateJoinerUsername: data.username,
      eligibleVoters: data.eligible_voters,
      votes: {},
      myVote: null,
      timeoutAt: Date.now() + data.timeout_seconds * 1000,
      requiredMajority: data.required_majority,
    }
  }
  const votePending = (data: ServerToClientPayloads['join_vote_pending']) => {
    party.pendingVote = {
      active: true,
      isPending: true,
      lateJoinerUsername: party.username,
      eligibleVoters: data.eligible_voters,
      votes: {},
      myVote: null,
      timeoutAt: Date.now() + data.timeout_seconds * 1000,
      requiredMajority: data.required_majority,
    }
  }
  const voteUpdated = (data: ServerToClientPayloads['join_vote_update']) => {
    if (party.pendingVote) party.pendingVote.votes = data.votes
  }
  const voteResolved = (data: ServerToClientPayloads['join_vote_resolved']) => {
    const wasPending = party.pendingVote?.isPending === true
    party.pendingVote = null
    if (data.result === 'fail' && wasPending) {
      hideParty(party.partyId)
      void party.leave()
    }
  }
  const joinRejected = () => {
    party.pendingVote = null
    void party.leave()
  }

  function attach() {
    dispose()
    socket.on('join_vote_started', voteStarted)
    socket.on('join_vote_pending', votePending)
    socket.on('join_vote_update', voteUpdated)
    socket.on('join_vote_resolved', voteResolved)
    socket.on('join_rejected', joinRejected)
  }

  function dispose() {
    for (const event of events) socket.off(event)
  }

  onUnmounted(dispose)
  return { attach, dispose }
}
