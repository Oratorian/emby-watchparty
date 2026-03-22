<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  error.value = ''
  const result = await auth.login(username.value, password.value)
  loading.value = false
  if (result.success) {
    router.push('/')
  } else {
    error.value = result.message || 'Login failed'
  }
}
</script>

<template>
  <div class="login-container">
    <div class="login-header">
      <h1>Emby Watch Party</h1>
      <p>Login with your Emby account</p>
    </div>
    <div class="login-card">
      <div v-if="error" class="error-msg">{{ error }}</div>
      <form @submit.prevent="submit">
        <div class="form-group">
          <label>Username</label>
          <input v-model="username" autocomplete="username" required autofocus />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </div>
        <button type="submit" class="btn btn-primary login-btn" :disabled="loading">
          {{ loading ? 'Logging in...' : 'Login' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-container { max-width: 400px; margin: 3rem auto; padding: 2rem; }
.login-header { text-align: center; margin-bottom: 2rem; }
.login-header p { color: var(--text-secondary, #888); }
.login-card {
  background: var(--bg-secondary, #1a1a2e); border-radius: 8px;
  padding: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
}
.form-group { margin-bottom: 1.5rem; }
.form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
.form-group input {
  width: 100%; padding: 0.75rem; box-sizing: border-box;
  border: 1px solid var(--cyber-primary, #6c63ff); border-radius: 4px;
  background: var(--bg-primary, #0f0f23); color: var(--text-primary, #fff); font-size: 1rem;
}
.login-btn { width: 100%; padding: 0.75rem; margin-top: 1rem; }
.error-msg {
  color: #ff4444; background: rgba(255,68,68,0.1);
  padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem;
}
</style>
