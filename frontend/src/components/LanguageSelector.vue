<script setup lang="ts">
import { computed } from 'vue'
import {
  availableLanguages, languagePackError, languagePackLoading, languagePreference,
  refreshLanguagePacks, setLanguagePreference, t,
} from '@/i18n'
import type { LanguagePreference } from '@/i18n'

function changeLanguage(event: Event) {
  setLanguagePreference((event.target as HTMLSelectElement).value as LanguagePreference)
}

const unknownPreference = computed(() => languagePreference.value !== 'auto'
  && !availableLanguages.value.some(language => language.locale === languagePreference.value))
</script>

<template>
  <div class="language-control">
  <label class="language-selector">
    <span>{{ t('core.language') }}</span>
    <select :value="languagePreference" @change="changeLanguage">
      <option value="auto">{{ t('core.browser_language') }}</option>
      <option v-if="unknownPreference" :value="languagePreference">{{ languagePreference }}</option>
      <option v-for="language in availableLanguages" :key="language.locale" :value="language.locale" :lang="language.locale">{{ language.name }}</option>
    </select>
  </label>
  <span v-if="languagePackLoading" class="language-status" role="status">{{ t('languageRuntime.loading') }}</span>
  <span v-else-if="languagePackError" class="language-status" role="status">
    {{ t('languageRuntime.unavailable') }}
    <button type="button" @click="refreshLanguagePacks()">{{ t('languageRuntime.retry') }}</button>
  </span>
  </div>
</template>

<style scoped>
.language-control { display: inline-flex; flex-direction: column; align-items: center; max-width: 100%; gap: .3rem; }
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
.language-status { display: block; max-width: 24rem; color: var(--text-secondary); font-size: .75rem; }
.language-status button { margin-left: .4rem; color: var(--accent-primary); font: inherit; }
</style>
