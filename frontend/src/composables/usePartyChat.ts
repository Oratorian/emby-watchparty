import { nextTick, ref } from 'vue'
import type { ServerToClientPayloads } from '@/types/socket.generated'
import type { usePartyStore } from '@/stores/party'
import type { useSocketStore } from '@/stores/socket'

type SocketStore = ReturnType<typeof useSocketStore>
type PartyStore = ReturnType<typeof usePartyStore>

export interface ChatMessage {
  username: string
  message: string
  timestamp: string
  avatar_uuid?: string | null
  system?: boolean
}

export function usePartyChat(socket: SocketStore, party: PartyStore) {
  const messages = ref<ChatMessage[]>([])
  const input = ref('')
  const showParticipants = ref(false)
  const showMobileChat = ref(false)
  const rateLimitError = ref<string | null>(null)
  const rateLimitRetryAfter = ref(0)
  // Refused messages that could not go straight back into the composer because
  // the user had already typed something else. FIFO, so they keep the order
  // they were written in. Concatenating them into the composer instead merged
  // two distinct messages into one, and because refusals arrive in send order
  // while each new draft was prepended, the merge came out backwards.
  const unsentDrafts = ref<string[]>([])
  const pendingDrafts = new Map<string, string>()
  const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()
  let rateLimitTimer: ReturnType<typeof setInterval> | null = null

  const receiveMessage = (data: ServerToClientPayloads['chat_message']) => {
    messages.value.push(data)
    void nextTick(() => {
      const element = document.querySelector('.chat-messages')
      if (element) element.scrollTop = element.scrollHeight
    })
  }

  const receiveRateLimit = (data: ServerToClientPayloads['rate_limited']) => {
    if (data.action !== 'chat') return
    const draft = data.request_id ? pendingDrafts.get(data.request_id) : undefined
    if (draft) {
      if (input.value) unsentDrafts.value.push(draft)
      else input.value = draft
      pendingDrafts.delete(data.request_id!)
      const pendingTimer = pendingTimers.get(data.request_id!)
      if (pendingTimer) clearTimeout(pendingTimer)
      pendingTimers.delete(data.request_id!)
    }
    rateLimitError.value = data.message
    rateLimitRetryAfter.value = Math.max(1, Math.ceil(data.retry_after))
    if (rateLimitTimer) clearInterval(rateLimitTimer)
    rateLimitTimer = setInterval(() => {
      rateLimitRetryAfter.value = Math.max(0, rateLimitRetryAfter.value - 1)
      if (rateLimitRetryAfter.value === 0 && rateLimitTimer) {
        clearInterval(rateLimitTimer)
        rateLimitTimer = null
        // Falls with the counter. Left set, the "Message not sent" alert
        // outlived the countdown that explained it and stayed on screen until
        // the next successful send, which is a permanent false error for
        // anyone who simply stops typing.
        rateLimitError.value = null
      }
    }, 1000)
  }

  function attach() {
    socket.off('chat_message', receiveMessage)
    socket.on('chat_message', receiveMessage)
    socket.off('rate_limited', receiveRateLimit)
    socket.on('rate_limited', receiveRateLimit)
  }

  function dispose() {
    socket.off('chat_message', receiveMessage)
    socket.off('rate_limited', receiveRateLimit)
    if (rateLimitTimer) clearInterval(rateLimitTimer)
    rateLimitTimer = null
    for (const timer of pendingTimers.values()) clearTimeout(timer)
    pendingTimers.clear()
    pendingDrafts.clear()
    unsentDrafts.value = []
  }

  function send() {
    const message = input.value.trim()
    if (!message || !party.partyId || rateLimitRetryAfter.value > 0) return
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    pendingDrafts.set(requestId, message)
    pendingTimers.set(requestId, setTimeout(() => {
      pendingDrafts.delete(requestId)
      pendingTimers.delete(requestId)
    }, 60_000))
    socket.emit('chat_message', {
      party_id: party.partyId,
      message,
      request_id: requestId,
    })
    input.value = ''
    rateLimitError.value = null
  }

  /** Put a queued refusal back in the composer, if it is free to take it. */
  function restoreDraft(index: number) {
    if (input.value) return
    const [draft] = unsentDrafts.value.splice(index, 1)
    if (draft !== undefined) input.value = draft
  }

  function insertEmoji(emoji: string) {
    input.value += emoji
  }

  function addSystemMessage(message: string) {
    messages.value.push({
      username: 'System',
      message,
      timestamp: new Date().toISOString(),
      system: true,
    })
  }

  return {
    messages,
    input,
    showParticipants,
    showMobileChat,
    rateLimitError,
    rateLimitRetryAfter,
    unsentDrafts,
    attach,
    dispose,
    send,
    restoreDraft,
    insertEmoji,
    addSystemMessage,
  }
}
