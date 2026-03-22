<script setup lang="ts">
const model = defineModel<boolean>()
</script>

<template>
  <label class="toggle">
    <input type="checkbox" v-model="model" />
    <span class="toggle-track">
      <span class="toggle-knob" />
    </span>
  </label>
</template>

<style scoped>
.toggle {
  position: relative;
  display: inline-flex;
  cursor: pointer;
}

.toggle input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-track {
  width: 40px;
  height: 22px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  transition: all var(--transition-fast);
  display: flex;
  align-items: center;
  padding: 2px;
}

.toggle input:checked + .toggle-track {
  background: var(--accent-primary-dim);
  border-color: var(--accent-primary);
}

.toggle-knob {
  width: 16px;
  height: 16px;
  background: var(--text-muted);
  border-radius: 50%;
  transition: all var(--transition-fast);
}

.toggle input:checked + .toggle-track .toggle-knob {
  transform: translateX(18px);
  background: var(--accent-primary);
}
</style>
