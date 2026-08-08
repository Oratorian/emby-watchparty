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
      input.value = input.value ? `${draft} ${input.value}` : draft
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
    attach,
    dispose,
    send,
    insertEmoji,
    addSystemMessage,
  }
}
