<script setup lang="ts">
import { t } from '@/i18n'
import LanguageSelector from '@/components/LanguageSelector.vue'
</script>

<template>
  <div style="text-align:center;padding:4rem 1rem;">
    <h1>404</h1>
      <LanguageSelector />
    <p>{{ t('interface.not_found.the_page_you_re_looking_for_doesn_t_exist') }}</p>
    <router-link to="/" style="color:var(--cyber-primary,#6c63ff);">{{ t('interface.not_found.go_home') }}</router-link>
  </div>
</template>
