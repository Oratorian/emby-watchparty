<template>
  <RouterView />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

onMounted(() => {
  auth.refresh()
})
</script>

<style>
:root {
  --bg-primary: #0f0f23;
  --bg-secondary: #1a1a2e;
  --text-primary: #e0e0e0;
  --text-secondary: #888;
  --cyber-primary: #6c63ff;
  --cyber-secondary: #00ffff;
  --cyber-gold: #ffbe0b;
  --cyber-border: #333;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  min-height: 100vh;
}
a { color: var(--cyber-primary); }
h1, h2, h3 { color: var(--text-primary); }
.btn {
  padding: 0.5rem 1.5rem; border: 1px solid var(--cyber-primary);
  border-radius: 4px; background: transparent; color: var(--text-primary);
  cursor: pointer; font-size: 0.9rem; transition: all 0.2s;
}
.btn:hover { background: rgba(108,99,255,0.2); }
.btn-primary { background: var(--cyber-primary); color: white; }
.btn-primary:hover { background: #5a52d5; }
.btn-secondary { border-color: var(--cyber-secondary); }
.btn-danger { background: rgba(255,68,68,0.2); border-color: #ff4444; color: #ff4444; }
.btn-small { padding: 0.3rem 0.75rem; font-size: 0.8rem; }
</style>
