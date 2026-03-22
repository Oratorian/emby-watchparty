<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'

const version = ref({ current_version: '', codename: '', latest_version: null as string | null, update_available: false, release_url: null as string | null })

onMounted(async () => {
  version.value = await api.version()
})
</script>

<template>
  <div class="version-container">
    <h1>Emby Watch Party</h1>
    <div class="version-card">
      <div class="version-number">v{{ version.current_version }}</div>
      <div class="version-codename">"{{ version.codename }}"</div>
      <div v-if="version.update_available" class="badge badge-update">
        Update available: <a :href="version.release_url || '#'" target="_blank">v{{ version.latest_version }}</a>
      </div>
      <div v-else-if="version.latest_version" class="badge badge-ok">Up to date</div>
    </div>
    <div style="margin-top:2rem;text-align:center;">
      <router-link to="/" style="color:var(--cyber-primary,#6c63ff);text-decoration:none;">Back to Home</router-link>
      &middot;
      <a href="https://ko-fi.com/jedziah" target="_blank" style="color:#ff5e5b;text-decoration:none;">Support on Ko-fi</a>
    </div>
  </div>
</template>

<style scoped>
.version-container { max-width: 500px; margin: 3rem auto; text-align: center; padding: 1rem; }
.version-card { background: var(--bg-secondary, #1a1a2e); border-radius: 8px; padding: 2rem; margin-top: 1.5rem; }
.version-number { font-size: 2rem; font-weight: bold; font-family: monospace; }
.version-codename { color: var(--cyber-gold, #ffbe0b); margin-top: 0.25rem; }
.badge { display: inline-block; padding: 0.3rem 0.8rem; border-radius: 20px; font-size: 0.85rem; margin-top: 1rem; }
.badge-ok { background: rgba(72,187,120,0.2); color: #48bb78; }
.badge-update { background: rgba(255,190,11,0.2); color: var(--cyber-gold, #ffbe0b); }
.badge-update a { color: inherit; text-decoration: underline; }
</style>
