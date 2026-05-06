<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'

const emit = defineEmits<{
  select: [emoji: string]
}>()

const open = ref(false)
const triggerEl = ref<HTMLButtonElement | null>(null)
const panelStyle = ref<Record<string, string>>({})

const categories = [
  {
    name: 'Smileys',
    emojis: ['😀', '😂', '🤣', '😊', '😍', '🥰', '😘', '😜', '🤪', '😎', '🤓', '🥳', '😱', '😭', '😤', '🤯', '🥺', '😴', '🤔', '🙄'],
  },
  {
    name: 'Reactions',
    emojis: ['👍', '👎', '👏', '🙌', '🤝', '✌️', '🤞', '💪', '🫡', '🫶', '❤️', '🔥', '⭐', '💯', '🎉', '🎊', '💀', '👀', '🤡', '💩'],
  },
  {
    name: 'Food & Fun',
    emojis: ['🍿', '🍕', '🍔', '🌮', '🍩', '🍪', '🎬', '🎥', '📺', '🎮', '🎵', '🎶', '🍺', '🍻', '🥂', '☕', '🧃', '🥤', '🍫', '🎂'],
  },
]

function positionPanel() {
  if (!triggerEl.value) return
  const r = triggerEl.value.getBoundingClientRect()
  // Anchor the panel above the trigger, right-aligned with the
  // trigger so the layout matches the previous position-absolute
  // behaviour. Coordinates are viewport-relative because the panel
  // is teleported to <body> with position: fixed.
  panelStyle.value = {
    right: `${window.innerWidth - r.right}px`,
    bottom: `${window.innerHeight - r.top + 8}px`,
  }
}

async function toggleOpen() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    positionPanel()
    document.addEventListener('mousedown', onDocClick)
    window.addEventListener('resize', positionPanel)
    window.addEventListener('scroll', positionPanel, true)
  } else {
    cleanup()
  }
}

function cleanup() {
  document.removeEventListener('mousedown', onDocClick)
  window.removeEventListener('resize', positionPanel)
  window.removeEventListener('scroll', positionPanel, true)
}

function onDocClick(e: MouseEvent) {
  const target = e.target as Node | null
  if (!target) return
  if (triggerEl.value?.contains(target)) return
  const panel = document.querySelector('.emoji-panel')
  if (panel?.contains(target)) return
  open.value = false
  cleanup()
}

function select(emoji: string) {
  emit('select', emoji)
  open.value = false
  cleanup()
}

onUnmounted(cleanup)
</script>

<template>
  <div class="emoji-picker-wrapper">
    <button ref="triggerEl" @click="toggleOpen" class="emoji-trigger" title="Emoji">
      😀
    </button>
    <Teleport to="body">
      <div v-if="open" class="emoji-panel glass" :style="panelStyle">
        <div class="emoji-panel-inner">
          <div v-for="cat in categories" :key="cat.name" class="emoji-category">
            <div class="emoji-category-name">{{ cat.name }}</div>
            <div class="emoji-grid">
              <button
                v-for="emoji in cat.emojis"
                :key="emoji"
                class="emoji-btn"
                @click="select(emoji)"
              >
                {{ emoji }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.emoji-picker-wrapper {
  position: relative;
}

.emoji-trigger {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0.2rem;
  line-height: 1;
  transition: transform var(--transition-fast);
}

.emoji-trigger:hover {
  transform: scale(1.2);
}

.emoji-panel {
  /* Teleported to <body> with position:fixed so the panel escapes
     .party-content's overflow:hidden. Coordinates (right/bottom) are
     set in JS from the trigger button's bounding rect on open.
     No padding here -- padding lives on .emoji-panel-inner below
     so the scrollbar sits at the panel's true right edge instead of
     inside the right padding (where it would visually shrink one side). */
  position: fixed;
  width: 296px;
  max-height: 300px;
  overflow-y: auto;
  overflow-x: hidden;
  z-index: 1000;
  box-sizing: border-box;
  scrollbar-width: thin;
}

.emoji-panel-inner {
  padding: var(--space-sm);
}

.emoji-panel::-webkit-scrollbar {
  width: 6px;
}

.emoji-panel::-webkit-scrollbar-track {
  background: transparent;
}

.emoji-panel::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 3px;
}

.emoji-panel::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

.emoji-category {
  margin-bottom: var(--space-sm);
}

.emoji-category-name {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  padding: var(--space-xs) 0;
  font-weight: 600;
}

.emoji-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(26px, 1fr));
  gap: 2px;
}

.emoji-btn {
  background: none;
  border: none;
  font-size: 1.15rem;
  cursor: pointer;
  padding: 0.2rem;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
  line-height: 1;
  min-width: 0;
  text-align: center;
}

.emoji-btn:hover {
  background: var(--bg-surface-hover);
}
</style>
