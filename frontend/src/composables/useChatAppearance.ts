import { computed, ref } from 'vue'
import '@/assets/fonts/chat/fonts.css'

const STORAGE_KEY = 'watchparty-chat-appearance'
const DEFAULT_SIZE = 14
export const MIN_CHAT_FONT_SIZE = 12
export const MAX_CHAT_FONT_SIZE = 24
export const CHAT_FONTS = [
  { id: 'default', name: 'Default', family: 'var(--font-sans)' },
  { id: 'rajdhani', name: 'Rajdhani', family: '"EWP Rajdhani", var(--font-sans)' },
  { id: 'oxanium', name: 'Oxanium', family: '"EWP Oxanium", var(--font-sans)' },
  { id: 'space-grotesk', name: 'Space Grotesk', family: '"EWP Space Grotesk", var(--font-sans)' },
] as const
export type ChatFont = typeof CHAT_FONTS[number]['id']

function isFont(value: unknown): value is ChatFont {
  return CHAT_FONTS.some(font => font.id === value)
}

function isSize(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value)
    && value >= MIN_CHAT_FONT_SIZE && value <= MAX_CHAT_FONT_SIZE
}

function readAppearance(): { font: ChatFont; size: number } {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (saved && typeof saved === 'object') {
      const { font, size } = saved as Record<string, unknown>
      return { font: isFont(font) ? font : 'default', size: isSize(size) ? size : DEFAULT_SIZE }
    }
  } catch { /* A blocked store or invalid preference must not prevent joining. */ }
  return { font: 'default', size: DEFAULT_SIZE }
}

export function useChatAppearance() {
  const appearance = ref(readAppearance())
  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance.value))
    } catch { /* The appearance still works for this visit without storage. */ }
  }
  const font = computed({
    get: () => appearance.value.font,
    set: (value: ChatFont) => {
      if (!isFont(value)) return
      appearance.value.font = value
      save()
    },
  })
  const size = computed({
    get: () => appearance.value.size,
    set: (value: number) => {
      if (!isSize(value)) return
      appearance.value.size = value
      save()
    },
  })
  const style = computed(() => ({
    '--chat-font-family': CHAT_FONTS.find(option => option.id === font.value)!.family,
    '--chat-font-size': `${size.value}px`,
  }))
  function reset() {
    appearance.value = { font: 'default', size: DEFAULT_SIZE }
    save()
  }
  return { font, size, style, reset }
}
