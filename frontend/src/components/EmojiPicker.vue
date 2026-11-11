<script setup lang="ts">
import { t } from '@/i18n'
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue'
import {
  CHAT_FONTS, MAX_CHAT_FONT_SIZE, MIN_CHAT_FONT_SIZE, type ChatFont,
} from '@/composables/useChatAppearance'

const props = withDefaults(defineProps<{ font?: ChatFont; size?: number }>(), {
  font: 'default',
  size: 14,
})
const emit = defineEmits<{
  select: [emoji: string]
  'update:font': [font: ChatFont]
  'update:size': [size: number]
  reset: []
}>()

type View = 'menu' | 'emoji' | 'settings'
const open = ref(false)
const view = ref<View>('menu')
const triggerEl = ref<HTMLButtonElement | null>(null)
const panelEl = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})
const panelId = `chat-options-${useId()}`
let pinned = false
let closeTimer: ReturnType<typeof setTimeout> | undefined

const panelTitle = computed(() => view.value === 'menu' ? t('party.chat_options')
  : view.value === 'emoji' ? t('party.chat_emojis') : t('party.chat_settings'))
const previewStyle = computed(() => ({
  fontFamily: CHAT_FONTS.find(font => font.id === props.font)?.family,
  fontSize: `${props.size}px`,
}))
const categories = computed(() => [
  {
    name: t('interface.emoji_picker.smileys'),
    emojis: ['😀', '😂', '🤣', '😊', '😍', '🥰', '😘', '😜', '🤪', '😎', '🤓', '🥳', '😱', '😭', '😤', '🤯', '🥺', '😴', '🤔', '🙄'],
  },
  {
    name: t('interface.emoji_picker.reactions'),
    emojis: ['👍', '👎', '👏', '🙌', '🤝', '✌️', '🤞', '💪', '🫡', '🫶', '❤️', '🔥', '⭐', '💯', '🎉', '🎊', '💀', '👀', '🤡', '💩'],
  },
  {
    name: t('interface.emoji_picker.food_fun'),
    emojis: ['🍿', '🍕', '🍔', '🌮', '🍩', '🍪', '🎬', '🎥', '📺', '🎮', '🎵', '🎶', '🍺', '🍻', '🥂', '☕', '🧃', '🥤', '🍫', '🎂'],
  },
])

function cancelClose() {
  if (closeTimer) clearTimeout(closeTimer)
  closeTimer = undefined
}

function positionPanel() {
  if (!triggerEl.value || !open.value) return
  const r = triggerEl.value.getBoundingClientRect()
  const viewport = window.visualViewport
  const leftEdge = viewport?.offsetLeft ?? 0
  const topEdge = viewport?.offsetTop ?? 0
  const viewportWidth = viewport?.width ?? window.innerWidth
  const viewportHeight = viewport?.height ?? window.innerHeight
  const width = Math.min(view.value === 'menu' ? 232 : 320, viewportWidth - 24)
  const above = Math.max(0, r.top - topEdge - 20)
  const below = Math.max(0, topEdge + viewportHeight - r.bottom - 20)
  const placeAbove = above >= below
  panelStyle.value = {
    position: 'fixed',
    left: `${Math.max(leftEdge + 12, Math.min(r.left, leftEdge + viewportWidth - width - 12))}px`,
    ...(placeAbove
      ? { bottom: `${window.innerHeight - r.top + 8}px` }
      : { top: `${r.bottom + 8}px` }),
    width: `${width}px`,
    maxHeight: `${Math.min(420, placeAbove ? above : below)}px`,
    overflowY: 'auto',
    overflowX: 'hidden',
    boxSizing: 'border-box',
    zIndex: '1100',
  }
}

function contains(target: Node | null) {
  return !!target && (triggerEl.value?.contains(target) || panelEl.value?.contains(target))
}

function cleanup() {
  cancelClose()
  document.removeEventListener('pointerdown', onOutsidePointer)
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('focusin', onDocumentFocus)
  window.removeEventListener('resize', positionPanel)
  window.removeEventListener('scroll', positionPanel)
  window.visualViewport?.removeEventListener('resize', positionPanel)
  window.visualViewport?.removeEventListener('scroll', positionPanel)
}

function close(restoreFocus = false) {
  open.value = false
  pinned = false
  cleanup()
  if (restoreFocus) triggerEl.value?.focus()
}

function onOutsidePointer(event: PointerEvent) {
  if (!contains(event.target as Node | null)) close()
}

function onDocumentFocus(event: FocusEvent) {
  if (!contains(event.target as Node | null)) close()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close(true)
  }
}

async function showMenu(focus = false, last = false) {
  cancelClose()
  if (!open.value) {
    view.value = 'menu'
    open.value = true
    document.addEventListener('pointerdown', onOutsidePointer)
    document.addEventListener('keydown', onDocumentKeydown)
    document.addEventListener('focusin', onDocumentFocus)
    window.addEventListener('resize', positionPanel)
    window.addEventListener('scroll', positionPanel)
    window.visualViewport?.addEventListener('resize', positionPanel)
    window.visualViewport?.addEventListener('scroll', positionPanel)
  }
  await nextTick()
  if (!open.value) return
  positionPanel()
  if (focus) {
    const actions = panelEl.value?.querySelectorAll<HTMLButtonElement>('.chat-menu-action')
    actions?.[last ? actions.length - 1 : 0]?.focus()
  }
}

function openFromHover(event: PointerEvent) {
  if (event.pointerType === 'touch') return
  void showMenu()
}

function scheduleClose() {
  cancelClose()
  // A chosen panel stays open while native controls are in use. Only the
  // initial hover menu dismisses when the pointer leaves the popup and trigger.
  if (pinned || view.value !== 'menu' || contains(document.activeElement)) return
  closeTimer = setTimeout(() => close(), 250)
}

function toggleFromClick() {
  // Hover precedes click with a mouse. Pin the visible menu instead of
  // immediately closing it; a second deliberate click dismisses it.
  if (open.value && pinned) close()
  else {
    pinned = true
    void showMenu(true)
  }
}

function onTriggerKeydown(event: KeyboardEvent) {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  event.preventDefault()
  pinned = true
  void showMenu(true, event.key === 'ArrowUp')
}

async function chooseView(next: View) {
  pinned = true
  cancelClose()
  view.value = next
  await nextTick()
  if (!open.value) return
  positionPanel()
  panelEl.value?.querySelector<HTMLElement>('[data-panel-focus]')?.focus()
}

function onPanelKeydown(event: KeyboardEvent) {
  if (view.value !== 'menu') return
  const buttons = Array.from(panelEl.value?.querySelectorAll<HTMLButtonElement>('.chat-menu-action') ?? [])
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  let next: number
  if (event.key === 'ArrowDown') next = (index + 1) % buttons.length
  else if (event.key === 'ArrowUp') next = (index + buttons.length - 1) % buttons.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = buttons.length - 1
  else return
  event.preventDefault()
  buttons[next]?.focus()
}

function changeFont(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (CHAT_FONTS.some(font => font.id === value)) emit('update:font', value as ChatFont)
}

function changeSize(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (Number.isFinite(value)) emit('update:size', Math.min(MAX_CHAT_FONT_SIZE, Math.max(MIN_CHAT_FONT_SIZE, value)))
}

function select(emoji: string) {
  emit('select', emoji)
  close(true)
}

// Font changes can change the composer's height and move the trigger.
watch([() => props.font, () => props.size], positionPanel, { flush: 'post' })

onUnmounted(cleanup)
</script>

<template>
  <div class="emoji-picker-wrapper">
    <button
      ref="triggerEl"
      type="button"
      class="emoji-trigger"
      :title="t('party.chat_options')"
      :aria-label="t('party.chat_options')"
      :aria-expanded="open"
      :aria-controls="open ? panelId : undefined"
      aria-haspopup="dialog"
      @pointerenter="openFromHover"
      @pointerleave="scheduleClose"
      @click="toggleFromClick"
      @keydown="onTriggerKeydown"
    >
      <span aria-hidden="true">😀</span>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        :id="panelId"
        ref="panelEl"
        class="emoji-panel glass"
        role="dialog"
        :aria-label="panelTitle"
        :style="panelStyle"
        @pointerenter="cancelClose"
        @pointerleave="scheduleClose"
        @keydown="onPanelKeydown"
      >
        <div class="chat-options-header">
          <button v-if="view !== 'menu'" type="button" class="chat-options-back" @click="chooseView('menu')">
            <span aria-hidden="true">‹</span> {{ t('party.chat_menu_back') }}
          </button>
          <span v-else class="chat-options-title">{{ panelTitle }}</span>
          <button type="button" class="chat-options-close" :aria-label="t('party.close')" @click="close(true)">×</button>
        </div>
        <div v-if="view === 'menu'" class="chat-options-menu">
          <button type="button" class="chat-menu-action" data-panel-focus @click="chooseView('emoji')">
            <span aria-hidden="true">😀</span> {{ t('party.chat_emojis') }} <span aria-hidden="true" class="chat-menu-chevron">›</span>
          </button>
          <button type="button" class="chat-menu-action" @click="chooseView('settings')">
            <svg aria-hidden="true" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--bg-secondary)"/><circle cx="15" cy="17" r="3" fill="var(--bg-secondary)"/></svg>
            {{ t('party.chat_settings') }} <span aria-hidden="true" class="chat-menu-chevron">›</span>
          </button>
        </div>
        <div v-else-if="view === 'emoji'" class="emoji-panel-inner">
          <div v-for="cat in categories" :key="cat.name" class="emoji-category">
            <div class="emoji-category-name">{{ cat.name }}</div>
            <div class="emoji-grid">
              <button
                v-for="(emoji, index) in cat.emojis"
                :key="emoji"
                type="button"
                class="emoji-btn"
                :data-panel-focus="index === 0 ? '' : undefined"
                @click="select(emoji)"
              >{{ emoji }}</button>
            </div>
          </div>
        </div>
        <div v-else class="chat-settings">
          <h4>{{ t('party.chat_settings') }}</h4>
          <label class="chat-setting-label">
            <span>{{ t('party.chat_font') }}</span>
            <select :aria-label="t('party.chat_font')" :value="font" data-panel-focus @change="changeFont">
              <option v-for="option in CHAT_FONTS" :key="option.id" :value="option.id">
                {{ option.id === 'default' ? t('party.chat_font_default') : option.name }}
              </option>
            </select>
          </label>
          <label class="chat-setting-label">
            <span class="chat-size-label">{{ t('party.chat_font_size') }} <output>{{ size }}px</output></span>
            <input type="range" :aria-label="t('party.chat_font_size')" :min="MIN_CHAT_FONT_SIZE" :max="MAX_CHAT_FONT_SIZE" step="1" :value="size" @input="changeSize" />
          </label>
          <p class="chat-font-preview" :style="previewStyle">{{ t('party.chat_settings_preview') }}</p>
          <div class="chat-settings-footer">
            <span>{{ t('party.chat_settings_local') }}</span>
            <button type="button" class="chat-settings-reset" @click="emit('reset')">{{ t('party.chat_settings_reset') }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.emoji-picker-wrapper { position: relative; flex-shrink: 0; }
.emoji-trigger {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  background: none;
  border: 0;
  border-radius: 8px;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}
.emoji-trigger:hover, .emoji-trigger[aria-expanded='true'] { background: var(--bg-surface-hover); }
.emoji-trigger:focus-visible, .emoji-panel button:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: -2px; }
.emoji-panel {
  background: linear-gradient(160deg, rgba(17, 22, 43, .97), rgba(8, 10, 22, .97));
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg), 0 0 24px rgba(34, 211, 238, .07);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  color: var(--text-primary);
  font-family: var(--font-sans);
  scrollbar-width: thin;
}
.chat-options-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-bottom: 1px solid var(--border-subtle); }
.chat-options-title { padding-left: 4px; color: var(--text-secondary); font-size: .72rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
.chat-options-back, .chat-options-close { border: 0; border-radius: 6px; background: none; color: var(--text-secondary); cursor: pointer; }
.chat-options-back { padding: 5px 6px; font: 500 12px var(--font-sans); }
.chat-options-back span { color: var(--accent-primary); margin-right: 4px; }
.chat-options-close { width: 28px; height: 28px; font-size: 22px; line-height: 1; }
.chat-options-back:hover, .chat-options-close:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
.chat-options-menu { padding: 6px; }
.chat-menu-action { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 42px; padding: 8px 10px; border: 0; border-radius: 8px; background: none; color: var(--text-primary); cursor: pointer; font: 500 13px var(--font-sans); text-align: left; }
.chat-menu-action:hover { background: var(--accent-primary-dim); }
.chat-menu-action svg { color: var(--accent-primary); }
.chat-menu-chevron { margin-left: auto; color: var(--text-muted); }
.emoji-panel-inner { padding: 10px 12px; }
.emoji-category { margin-bottom: var(--space-sm); }
.emoji-category-name { font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-secondary); padding: var(--space-xs) 0; font-weight: 600; }
.emoji-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(28px, 1fr)); gap: 3px; }
.emoji-btn { background: none; border: 0; font-size: 1.15rem; cursor: pointer; padding: 4px 0; border-radius: var(--radius-sm); line-height: 1; min-width: 0; text-align: center; }
.emoji-btn:hover { background: var(--bg-surface-hover); }
.chat-settings { display: flex; flex-direction: column; gap: 16px; padding: 14px; }
.chat-settings h4 { margin: 0; font-size: .9rem; font-weight: 600; }
.chat-setting-label { display: flex; flex-direction: column; gap: 8px; color: var(--text-secondary); font-size: .78rem; }
.chat-setting-label select { width: 100%; max-width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-secondary); color: var(--text-primary); font: 13px var(--font-sans); }
.chat-size-label { display: flex; justify-content: space-between; align-items: center; }
.chat-size-label output { color: var(--accent-primary); font: 12px var(--font-mono); }
.chat-setting-label input[type='range'] { width: 100%; padding: 0; accent-color: var(--accent-primary); cursor: pointer; }
.chat-font-preview { margin: 0; padding: 12px; border: 1px solid var(--border-accent); border-radius: 10px; background: var(--accent-primary-dim); color: var(--text-primary); line-height: 1.5; overflow-wrap: anywhere; }
.chat-settings-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-size: .7rem; color: var(--text-muted); }
.chat-settings-reset { padding: 6px 8px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-surface); color: var(--text-secondary); cursor: pointer; font: 11px var(--font-sans); }
.chat-settings-reset:hover { border-color: var(--border-accent); color: var(--accent-primary); }
</style>
