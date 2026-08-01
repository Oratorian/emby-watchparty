<script setup lang="ts">
import HelloWorld from './HelloWorld.vue'
import WelcomeItem from './WelcomeItem.vue'
import ToolingIcon from './icons/IconTooling.vue'

defineProps<{ error?: string | null }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <main class="startup" role="status" aria-live="polite">
    <HelloWorld msg="Starting WatchParty">Vue is connecting to your WatchParty server.</HelloWorld>
    <WelcomeItem>
    <template #icon>
      <ToolingIcon />
    </template>
      <template #heading>{{ error ? 'Server unavailable' : 'Loading session' }}</template>
      <template v-if="error">
        <span class="startup-error">{{ error }}</span>
        <button class="btn btn-primary" type="button" @click="$emit('retry')">Retry</button>
      </template>
      <span v-else>Checking authentication and runtime configuration…</span>
    </WelcomeItem>
  </main>
</template>

<style scoped>
.startup { min-height: 100vh; display: grid; place-content: center; gap: 1.5rem; padding: 2rem; }
.startup-error { display: block; color: var(--color-danger); margin-bottom: 1rem; }
</style>
