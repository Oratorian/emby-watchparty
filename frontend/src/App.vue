<template>
  <TheWelcome v-if="startup.state !== 'ready'" :error="startup.error" @retry="startup.start" />
  <RouterView v-else />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import TheWelcome from '@/components/TheWelcome.vue'
import { useStartupStore } from '@/stores/counter'

const startup = useStartupStore()

onMounted(() => {
  startup.start()
})
</script>
