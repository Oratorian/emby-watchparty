<script setup lang="ts">
import { languagePreference, setLanguagePreference, t } from '@/i18n'
import type { LanguagePreference } from '@/i18n'

function changeLanguage(event: Event) {
  setLanguagePreference((event.target as HTMLSelectElement).value as LanguagePreference)
}
</script>

<template>
  <label class="language-selector">
    <span>{{ t('core.language') }}</span>
    <select :value="languagePreference" @change="changeLanguage">
      <option value="auto">{{ t('core.browser_language') }}</option>
      <option value="en" lang="en">English</option>
      <option value="de" lang="de">Deutsch</option>
    </select>
  </label>
</template>

<style scoped>
.language-selector {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  color: var(--text-secondary);
  font-size: 0.8rem;
  max-width: 100%;
}
.language-selector select {
  max-width: 100%;
  min-width: 0;
  padding: 0.3rem 0.4rem;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font: inherit;
}
</style>
