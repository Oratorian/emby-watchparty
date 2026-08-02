import { nextTick, onUnmounted, ref, watch } from 'vue'
import type { usePartyStore } from '@/stores/party'

type PartyStore = ReturnType<typeof usePartyStore>

export function usePartyAdmin(party: PartyStore) {
  const showAdminModal = ref(false)
  const adminTriggerBtn = ref<HTMLButtonElement | null>(null)
  const adminModalShellRef = ref<HTMLElement | null>(null)

  const onEscape = (event: KeyboardEvent) => {
    if (!showAdminModal.value) return
    if (event.key === 'Escape') {
      event.preventDefault()
      showAdminModal.value = false
      return
    }
    if (event.key !== 'Tab' || !adminModalShellRef.value) return
    const focusable = Array.from(
      adminModalShellRef.value.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), '
        + 'textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      ),
    )
    if (!focusable.length) {
      event.preventDefault()
      adminModalShellRef.value.focus()
      return
    }
    const first = focusable[0]!
    const last = focusable[focusable.length - 1]!
    const active = document.activeElement
    if (event.shiftKey && (active === first || active === adminModalShellRef.value)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
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

  return {
    showAdminModal,
    adminTriggerBtn,
    adminModalShellRef,
    handleAdminModalKeydown: onEscape,
  }
}
