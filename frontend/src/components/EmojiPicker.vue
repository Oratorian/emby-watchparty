<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  select: [emoji: string]
}>()

const open = ref(false)

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

function select(emoji: string) {
  emit('select', emoji)
  open.value = false
}
</script>

<template>
  <div class="emoji-picker-wrapper">
    <button @click="open = !open" class="emoji-trigger" title="Emoji">
      😀
    </button>
    <div v-if="open" class="emoji-panel glass">
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
  position: absolute;
  bottom: 100%;
  right: 0;
  margin-bottom: var(--space-sm);
  width: 280px;
  max-height: 300px;
  overflow-y: auto;
  padding: var(--space-sm);
  z-index: 100;
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
  grid-template-columns: repeat(10, 1fr);
  gap: 1px;
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
}

.emoji-btn:hover {
  background: var(--bg-surface-hover);
}
</style>
