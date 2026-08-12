<script setup lang="ts">
// Default the model to `false` so the toggle never has an undefined
// state. With no default, defineModel<boolean>() yields Ref<boolean |
// undefined>, which forced every @update:model-value handler at every
// call site to accept (boolean | undefined) -- noisy and incorrect for
// a control that always represents a definite on/off.
const model = defineModel<boolean>({ default: false })

// Required on purpose. Every call site puts its wording in a sibling
// element, outside this component's <label>, so the native association
// never formed and the control announced as an unnamed checkbox -- the
// same "checkbox, not checked" for all eleven of them, with nothing
// saying which setting was being changed. Making it optional would let
// the next call site reintroduce exactly that, silently; required means
// vue-tsc refuses the build instead.
defineProps<{ label: string }>()
</script>

<template>
  <label class="toggle">
    <!-- role="switch" rather than the default checkbox semantics: this is an
         on/off control, and screen readers then say "on"/"off" instead of
         "checked"/"not checked". It stays a real checkbox input so the
         keyboard behaviour and :checked styling below are the browser's. -->
    <input type="checkbox" role="switch" :aria-label="label" v-model="model" />
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
