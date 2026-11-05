<script setup lang="ts">
import { t } from '@/i18n'
import LanguageSelector from '@/components/LanguageSelector.vue'
import HelloWorld from './HelloWorld.vue'
import WelcomeItem from './WelcomeItem.vue'
import ToolingIcon from './icons/IconTooling.vue'

defineProps<{ error?: string | null }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <main class="startup" role="status" aria-live="polite">
      <LanguageSelector />
    <HelloWorld :msg="t('interface.the_welcome.starting_watchparty')">{{ t('interface.the_welcome.vue_is_connecting_to_your_watchparty_server') }}</HelloWorld>
    <WelcomeItem>
    <template #icon>
      <ToolingIcon />
    </template>
      <template #heading>{{ error ? t('interface.the_welcome.server_unavailable') : t('interface.the_welcome.loading_session') }}</template>
      <template v-if="error">
        <span class="startup-error">{{ error }}</span>
        <button class="btn btn-primary" type="button" @click="$emit('retry')">{{ t('interface.the_welcome.retry') }}</button>
      </template>
      <span v-else>{{ t('interface.the_welcome.checking_authentication_and_runtime_configuration') }}</span>
    </WelcomeItem>
  </main>
</template>

<style scoped>
.startup { min-height: 100vh; display: grid; place-content: center; gap: 1.5rem; padding: 2rem; }
.startup-error { display: block; color: var(--color-danger); margin-bottom: 1rem; }
</style>
