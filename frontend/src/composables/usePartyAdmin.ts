import { nextTick, onUnmounted, ref, watch } from 'vue'
import type { usePartyStore } from '@/stores/party'

type PartyStore = ReturnType<typeof usePartyStore>

export function usePartyAdmin(party: PartyStore) {
  const showAdminModal = ref(false)
  const adminTriggerBtn = ref<HTMLButtonElement | null>(null)
  const adminModalShellRef = ref<HTMLElement | null>(null)

  const onEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && showAdminModal.value) showAdminModal.value = false
  }

  const stopModalWatch = watch(showAdminModal, (open, wasOpen) => {
    if (open) {
      document.addEventListener('keydown', onEscape)
      void nextTick(() => adminModalShellRef.value?.focus())
    } else {
      document.removeEventListener('keydown', onEscape)
      if (wasOpen) void nextTick(() => adminTriggerBtn.value?.focus())
    }
  })
  const stopVoteWatch = watch(() => party.pendingVote, (vote) => {
    if (vote && showAdminModal.value) showAdminModal.value = false
  })
  const stopReadyWatch = watch(() => party.readyCheckActive, (active) => {
    if (active && showAdminModal.value) showAdminModal.value = false
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', onEscape)
    stopModalWatch()
    stopVoteWatch()
    stopReadyWatch()
  })

  return { showAdminModal, adminTriggerBtn, adminModalShellRef }
}
