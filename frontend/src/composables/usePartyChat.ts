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
  const announcement = ref('')
  const input = ref('')
  const showParticipants = ref(false)
  const showMobileChat = ref(false)

  const receiveMessage = (data: ServerToClientPayloads['chat_message']) => {
    messages.value.push(data)
    void nextTick(() => {
      const element = document.querySelector('.chat-messages')
      if (element) element.scrollTop = element.scrollHeight
    })
  }

  function attach() {
    socket.off('chat_message', receiveMessage)
    socket.on('chat_message', receiveMessage)
  }

  function dispose() {
    socket.off('chat_message', receiveMessage)
  }

  function send() {
    const message = input.value.trim()
    if (!message || !party.partyId) return
    socket.emit('chat_message', { party_id: party.partyId, message })
    input.value = ''
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
    announcement.value = message
  }

  return {
    messages,
    announcement,
    input,
    showParticipants,
    showMobileChat,
    attach,
    dispose,
    send,
    insertEmoji,
    addSystemMessage,
  }
}
