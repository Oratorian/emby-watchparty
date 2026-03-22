<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'

const router = useRouter()
const partyCode = ref('')
const status = ref('')

async function createParty() {
  status.value = 'Creating party...'
  const data = await api.createParty()
  if (data.party_id) {
    router.push(`/party/${data.party_id}`)
  } else {
    status.value = 'Error creating party'
  }
}

function joinParty() {
  const code = partyCode.value.trim().replace(/[^a-zA-Z0-9]/g, '')
  if (!code) {
    status.value = 'Please enter a valid party code'
    return
  }
  router.push(`/party/${code}`)
}
</script>

<template>
  <div class="index-container">
    <header>
      <h1>Emby Watch Party</h1>
      <p>Watch together, wherever you are</p>
    </header>

    <main class="action-cards">
      <div class="card">
        <h2>Create Watch Party</h2>
        <p>Start a new watch party and invite friends to join</p>
        <button @click="createParty" class="btn btn-primary">Create Party</button>
      </div>

      <div class="card">
        <h2>Join Watch Party</h2>
        <p>Enter a party code to join an existing watch party</p>
        <input v-model="partyCode" @keypress.enter="joinParty" placeholder="Enter party code" />
        <button @click="joinParty" class="btn btn-secondary">Join Party</button>
      </div>
    </main>

    <div v-if="status" class="status">{{ status }}</div>

    <footer>
      <router-link to="/version">Version Info</router-link>
      &middot;
      <a href="https://ko-fi.com/jedziah" target="_blank">Support on Ko-fi</a>
    </footer>
  </div>
</template>

<style scoped>
.index-container {
  max-width: 800px;
  margin: 2rem auto;
  text-align: center;
  padding: 0 1rem;
}
.action-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin: 2rem 0;
}
@media (max-width: 600px) {
  .action-cards { grid-template-columns: 1fr; }
}
.card {
  background: var(--bg-secondary, #1a1a2e);
  border-radius: 8px;
  padding: 2rem;
}
.card input {
  width: 100%;
  padding: 0.75rem;
  margin-bottom: 1rem;
  box-sizing: border-box;
  border: 1px solid var(--cyber-primary, #6c63ff);
  border-radius: 4px;
  background: var(--bg-primary, #0f0f23);
  color: var(--text-primary, #fff);
}
footer {
  margin-top: 2rem;
  opacity: 0.7;
  font-size: 0.85rem;
}
footer a { color: var(--cyber-primary, #6c63ff); text-decoration: none; }
.status { margin-top: 1rem; color: var(--text-secondary, #888); }
</style>
