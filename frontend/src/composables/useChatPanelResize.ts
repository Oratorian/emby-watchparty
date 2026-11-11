import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const STORAGE_KEY = 'watchparty-chat-width'
const DEFAULT_WIDTH = 320
const MIN_WIDTH = 260
const MAX_WIDTH = 560
const MIN_VIDEO_WIDTH = 640

function savedWidth(): number {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY))
    if (Number.isFinite(value) && value >= MIN_WIDTH && value <= MAX_WIDTH) return value
  } catch { /* Storage can be disabled; resizing still works for this visit. */ }
  return DEFAULT_WIDTH
}

export function useChatPanelResize() {
  const videoArea = ref<HTMLElement | null>(null)
  const chatPanel = ref<HTMLElement | null>(null)
  const preferredWidth = ref(savedWidth())
  const maxWidth = ref(MAX_WIDTH)
  const desktop = ref(false)
  const resizing = ref(false)
  const width = computed(() => Math.min(preferredWidth.value, maxWidth.value))
  const style = computed(() => ({ '--chat-panel-width': `${width.value}px` }))
  let observer: ResizeObserver | undefined
  let media: MediaQueryList | undefined
  let pointer: { id: number; x: number; width: number; handle: HTMLElement } | undefined

  function finishResize() {
    const previous = pointer
    pointer = undefined
    resizing.value = false
    if (previous?.handle.hasPointerCapture(previous.id)) {
      previous.handle.releasePointerCapture(previous.id)
    }
  }

  function updateBounds() {
    desktop.value = media?.matches ?? window.innerWidth > 1280
    if (!desktop.value) {
      finishResize()
      return
    }
    if (!videoArea.value || !chatPanel.value) return
    // Measure only the video and chat, so the open library is already excluded.
    const available = videoArea.value.getBoundingClientRect().width
      + chatPanel.value.getBoundingClientRect().width
    if (!available) return
    maxWidth.value = Math.max(MIN_WIDTH, Math.min(
      MAX_WIDTH,
      Math.floor(available * 0.4),
      Math.floor(available - MIN_VIDEO_WIDTH),
    ))
  }

  function setWidth(value: number) {
    preferredWidth.value = Math.max(MIN_WIDTH, Math.min(maxWidth.value, Math.round(value)))
    try {
      localStorage.setItem(STORAGE_KEY, String(preferredWidth.value))
    } catch { /* Keep the current width even when the preference cannot be saved. */ }
  }

  function startResize(event: PointerEvent) {
    if (!desktop.value || event.button !== 0 || pointer) return
    updateBounds()
    const handle = event.currentTarget as HTMLElement
    handle.setPointerCapture(event.pointerId)
    pointer = { id: event.pointerId, x: event.clientX, width: width.value, handle }
    resizing.value = true
    event.preventDefault()
    handle.focus()
  }

  function moveResize(event: PointerEvent) {
    if (!pointer || pointer.id !== event.pointerId) return
    event.preventDefault()
    setWidth(pointer.width + pointer.x - event.clientX)
  }

  function endResize(event: PointerEvent) {
    if (pointer?.id === event.pointerId) finishResize()
  }

  function resetWidth() {
    if (desktop.value) setWidth(DEFAULT_WIDTH)
  }

  function resizeWithKeyboard(event: KeyboardEvent) {
    if (!desktop.value) return
    updateBounds()
    switch (event.key) {
      case 'ArrowLeft': setWidth(width.value + 20); break
      case 'ArrowRight': setWidth(width.value - 20); break
      case 'Home': setWidth(MIN_WIDTH); break
      case 'End': setWidth(maxWidth.value); break
      default: return
    }
    event.preventDefault()
  }

  // The room renders after joining, so its elements may not exist at mount.
  watch([videoArea, chatPanel], ([video, chat]) => {
    observer?.disconnect()
    if (video && chat && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateBounds)
      observer.observe(video)
      observer.observe(chat)
    }
    updateBounds()
  }, { flush: 'post' })

  onMounted(() => {
    media = window.matchMedia?.('(min-width: 1281px)')
    media?.addEventListener('change', updateBounds)
    window.addEventListener('resize', updateBounds)
    window.addEventListener('blur', finishResize)
    updateBounds()
  })
  onUnmounted(() => {
    observer?.disconnect()
    media?.removeEventListener('change', updateBounds)
    window.removeEventListener('resize', updateBounds)
    window.removeEventListener('blur', finishResize)
    finishResize()
  })

  return {
    videoArea, chatPanel, width, minWidth: MIN_WIDTH, maxWidth, style, resizing,
    startResize, moveResize, endResize, resetWidth, resizeWithKeyboard,
  }
}
