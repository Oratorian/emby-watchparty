import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const authenticated = ref(false)
  const username = ref<string | null>(null)
  const isAdmin = ref(false)
  const requireLogin = ref(false)

  async function checkStatus() {
    const data = await api.authStatus()
    authenticated.value = data.authenticated
    username.value = data.username
    isAdmin.value = data.is_admin
    requireLogin.value = data.require_login
  }

  async function login(user: string, pass: string) {
    const data = await api.login(user, pass)
    if (data.success) {
      await checkStatus()
    }
    return data
  }

  async function logout() {
    await api.logout()
    authenticated.value = false
    username.value = null
    isAdmin.value = false
  }

  return { authenticated, username, isAdmin, requireLogin, checkStatus, login, logout }
})
