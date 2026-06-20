import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

/**
 * Avatar identity store.
 *
 * The user's persistent identifier (`uuid`) lives in IndexedDB when
 * available (survives Safari's localStorage clears) with a
 * localStorage fallback. The recovery code is never persisted -- it
 * is shown once after upload/gravatar creation and the user copies
 * it to safe storage themselves.
 */

const IDB_NAME = 'emby-watchparty-avatar'
const IDB_STORE = 'avatar'
const IDB_KEY = 'uuid'
const LS_KEY = 'emby-watchparty-avatar-uuid'
const LS_CODE_SAVED_KEY = 'emby-watchparty-avatar-code-saved'

function idbAvailable(): boolean {
  return typeof indexedDB !== 'undefined'
}

async function idbOpen(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(IDB_STORE)) {
        db.createObjectStore(IDB_STORE)
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function idbGet(): Promise<string | null> {
  try {
    const db = await idbOpen()
    return await new Promise((resolve) => {
      const tx = db.transaction(IDB_STORE, 'readonly')
      const req = tx.objectStore(IDB_STORE).get(IDB_KEY)
      req.onsuccess = () => resolve((req.result as string) ?? null)
      req.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

async function idbPut(uuid: string): Promise<void> {
  try {
    const db = await idbOpen()
    await new Promise<void>((resolve) => {
      const tx = db.transaction(IDB_STORE, 'readwrite')
      tx.objectStore(IDB_STORE).put(uuid, IDB_KEY)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    /* swallow */
  }
}

async function idbClear(): Promise<void> {
  try {
    const db = await idbOpen()
    await new Promise<void>((resolve) => {
      const tx = db.transaction(IDB_STORE, 'readwrite')
      tx.objectStore(IDB_STORE).delete(IDB_KEY)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    /* swallow */
  }
}

async function persistUuid(uuid: string) {
  localStorage.setItem(LS_KEY, uuid)
  if (idbAvailable()) await idbPut(uuid)
}

async function clearUuid() {
  localStorage.removeItem(LS_KEY)
  localStorage.removeItem(LS_CODE_SAVED_KEY)
  if (idbAvailable()) await idbClear()
}

export const useAvatarStore = defineStore('avatar', () => {
  const uuid = ref<string | null>(null)
  // Plaintext code held in memory only after creation, so the
  // confirmation screen can show it. Cleared when the user
  // acknowledges they have saved it.
  const pendingCode = ref<string | null>(null)
  const codeAcknowledged = ref<boolean>(
    localStorage.getItem(LS_CODE_SAVED_KEY) === '1'
  )

  /** Read the saved uuid into memory. Call this once at app start. */
  async function load(): Promise<string | null> {
    if (idbAvailable()) {
      const fromIdb = await idbGet()
      if (fromIdb) {
        uuid.value = fromIdb
        // Mirror to localStorage so cross-tab code stays in sync.
        localStorage.setItem(LS_KEY, fromIdb)
        return fromIdb
      }
    }
    const fromLs = localStorage.getItem(LS_KEY)
    if (fromLs) {
      uuid.value = fromLs
      if (idbAvailable()) await idbPut(fromLs)
    }
    return uuid.value
  }

  async function uploadImage(file: File): Promise<{ success: boolean; message?: string }> {
    const data = await api.avatarUpload(file)
    if (data.success && data.uuid) {
      uuid.value = data.uuid
      pendingCode.value = data.code ?? null
      codeAcknowledged.value = false
      localStorage.removeItem(LS_CODE_SAVED_KEY)
      await persistUuid(data.uuid)
      return { success: true }
    }
    return { success: false, message: data.message }
  }

  async function setGravatar(email: string): Promise<{ success: boolean; message?: string }> {
    const data = await api.avatarGravatar(email)
    if (data.success && data.uuid) {
      uuid.value = data.uuid
      pendingCode.value = data.code ?? null
      codeAcknowledged.value = false
      localStorage.removeItem(LS_CODE_SAVED_KEY)
      await persistUuid(data.uuid)
      return { success: true }
    }
    return { success: false, message: data.message }
  }

  async function recover(code: string): Promise<{ success: boolean; message?: string }> {
    const data = await api.avatarRecover(code)
    if (data.success && data.uuid) {
      uuid.value = data.uuid
      pendingCode.value = null
      codeAcknowledged.value = true
      localStorage.setItem(LS_CODE_SAVED_KEY, '1')
      await persistUuid(data.uuid)
      return { success: true }
    }
    return { success: false, message: data.message || 'Code not recognised' }
  }

  function acknowledgeCode() {
    pendingCode.value = null
    codeAcknowledged.value = true
    localStorage.setItem(LS_CODE_SAVED_KEY, '1')
  }

  async function reset() {
    uuid.value = null
    pendingCode.value = null
    codeAcknowledged.value = false
    await clearUuid()
  }

  /** Source URL for the current user's avatar in image tags. */
  function avatarSrcForUuid(u: string | null | undefined): string | null {
    if (!u) return null
    return api.avatarSrc(u)
  }

  return {
    uuid,
    pendingCode,
    codeAcknowledged,
    load,
    uploadImage,
    setGravatar,
    recover,
    acknowledgeCode,
    reset,
    avatarSrcForUuid,
  }
})
