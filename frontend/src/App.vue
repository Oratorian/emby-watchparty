<template>
  <TheWelcome v-if="startup.state !== 'ready'" :error="startup.error" @retry="startup.start" />
  <RouterView v-else />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'
import TheWelcome from '@/components/TheWelcome.vue'
import { useStartupStore } from '@/stores/counter'
import { startLanguagePackRefresh } from '@/i18n'

const startup = useStartupStore()
let stopLanguagePacks: (() => void) | undefined

onMounted(() => {
  startup.start()
  stopLanguagePacks = startLanguagePackRefresh()
})

onUnmounted(() => stopLanguagePacks?.())
</script>
