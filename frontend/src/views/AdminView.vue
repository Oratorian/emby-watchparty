<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { api } from '@/api/client'
import AdminPanel from '@/components/AdminPanel.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

// "Back to WatchParty" should return to the party the admin came from,
// not bounce them to the create-a-party screen. auth.partyId is bound
// when the caller has a party-bound session cookie (most common path
// for host-as-admin); fall back to the index for the standalone login
// flow where there is no party context yet.
const backToWatchPartyTarget = computed(() => {
  return auth.partyId ? `/party/${auth.partyId}` : '/'
})

const authenticated = ref(false)
const loginUser = ref('')
const loginPass = ref('')
const loginError = ref('')

async function adminLogin() {
  loginError.value = ''
  const result = await api.adminLogin(loginUser.value, loginPass.value)
  if (result.success) {
    authenticated.value = true
  } else {
    loginError.value = result.message || 'Login failed'
  }
}

async function logout() {
  await api.adminLogout()
  authenticated.value = false
}

function onPanelUnauthorized() {
  authenticated.value = false
}

onMounted(async () => {
  try {
    const cfg = await api.adminGetConfig()
    if (cfg && !cfg.error) {
      authenticated.value = true
    }
  } catch { /* not authenticated */ }
})
</script>

<template>
  <!-- Admin login -->
  <div v-if="!authenticated" class="login-page">
    <div class="login-card glass">
      <h1>Admin Panel</h1>
      <p class="login-subtitle">Sign in with an Emby administrator account</p>
      <div v-if="loginError" class="error-msg">{{ loginError }}</div>
      <form @submit.prevent="adminLogin">
        <div class="form-group">
          <label>Username</label>
          <input v-model="loginUser" type="text" required autofocus />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input v-model="loginPass" type="password" required />
        </div>
        <button type="submit" class="btn btn-primary btn-full">Sign In</button>
      </form>
      <router-link :to="backToWatchPartyTarget" class="back-link">Back to Watch Party</router-link>
    </div>
  </div>

  <!-- Admin panel -->
  <div v-else class="admin-page">
    <div class="admin-header">
      <h1>Admin Panel</h1>
      <div class="admin-header-actions">
        <router-link :to="backToWatchPartyTarget" class="btn btn-ghost btn-small">Back to WatchParty</router-link>
        <button @click="logout" class="btn btn-small btn-danger">Logout</button>
      </div>
    </div>
    <AdminPanel @unauthorized="onPanelUnauthorized" />
  </div>
</template>

<style scoped>
/* Login */
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  min-height: 100dvh;
  padding: max(var(--space-xl), env(safe-area-inset-top))
    max(var(--space-xl), env(safe-area-inset-right))
    max(var(--space-xl), env(safe-area-inset-bottom))
    max(var(--space-xl), env(safe-area-inset-left));
}

.login-card {
  max-width: 400px;
  width: 100%;
  padding: var(--space-xl);
  text-align: center;
}

.login-card h1 {
  margin-bottom: var(--space-xs);
}

.login-subtitle {
  color: var(--text-secondary);
  margin-bottom: var(--space-lg);
  font-size: 0.9rem;
}

.form-group {
  margin-bottom: var(--space-md);
  text-align: left;
}

.form-group label {
  display: block;
  margin-bottom: var(--space-xs);
  font-weight: 500;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.btn-full {
  width: 100%;
  padding: 0.75rem;
}

.back-link {
  display: block;
  margin-top: var(--space-md);
  font-size: 0.85rem;
  color: var(--text-muted);
}

.error-msg {
  color: var(--color-danger);
  background: var(--color-danger-dim);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-md);
  font-size: 0.9rem;
}

/* Admin Panel */
.admin-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-lg);
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-lg);
}

.admin-header-actions {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
}
</style>
