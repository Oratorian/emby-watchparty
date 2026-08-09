<template>
  <section class="library-filters" aria-label="Library filters">
    <button
      class="filter-toggle"
      type="button"
      :aria-expanded="open"
      @click="open = !open"
    >
      Filters <span v-if="activeCount">{{ activeCount }} active</span>
    </button>

    <div v-if="open" class="filter-panel">
      <div v-for="control in controls" :key="control.id" class="filter-control">
        <label v-if="control.kind === 'select'">
          {{ control.label }}
          <select
            :aria-label="control.label"
            :value="selectedScalar(control.id)"
            @change="setScalar(control.id, ($event.target as HTMLSelectElement).value)"
          >
            <option v-if="needsAnyOption(control)" value="">Any</option>
            <option v-for="option in control.values" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>

        <label v-else-if="control.kind === 'toggle'">
          <input
            type="checkbox"
            :checked="selectedScalar(control.id) === 'true'"
            @change="setToggle(control.id, ($event.target as HTMLInputElement).checked)"
          />
          {{ control.label }}
        </label>

        <fieldset v-else>
          <legend>{{ control.label }}</legend>
          <label v-for="option in control.values" :key="option.value">
            <input
              type="checkbox"
              :value="option.value"
              :checked="selectedList(control.id).includes(option.value)"
              @change="setListValue(control.id, option.value, ($event.target as HTMLInputElement).checked)"
            />
            {{ option.label }}
          </label>
        </fieldset>
      </div>
    </div>

    <div v-if="chips.length" class="active-filters" aria-live="polite">
      <span v-for="chip in chips" :key="chip.key" class="filter-chip">{{ chip.label }}</span>
      <button class="reset-all" type="button" @click="reset">Reset All</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { FilterControl, LibraryFilterState } from '@/api/client'

const props = defineProps<{
  controls: FilterControl[]
  modelValue: LibraryFilterState
}>()
const emit = defineEmits<{ 'update:modelValue': [value: LibraryFilterState] }>()

const open = ref(false)
const selected = ref<LibraryFilterState>({ ...props.modelValue })

watch(() => props.modelValue, (value) => {
  selected.value = { ...value }
}, { deep: true })

function selectedScalar(id: string): string {
  const value = selected.value[id]
  return Array.isArray(value) ? '' : String(value ?? (id === 'playstate' ? 'any' : ''))
}

function selectedList(id: string): string[] {
  const value = selected.value[id]
  return Array.isArray(value) ? value : []
}

function needsAnyOption(control: FilterControl): boolean {
  return !control.values.some((option) => option.value === '' || option.value === 'any')
}

function publish(next: LibraryFilterState) {
  selected.value = next
  emit('update:modelValue', next)
}

function setScalar(id: string, value: string) {
  const next = { ...selected.value }
  if (!value || value === 'any') delete next[id]
  else next[id] = value
  publish(next)
}

function setToggle(id: string, checked: boolean) {
  const next = { ...selected.value }
  if (checked) next[id] = 'true'
  else delete next[id]
  publish(next)
}

function setListValue(id: string, value: string, checked: boolean) {
  const values = new Set(selectedList(id))
  if (checked) values.add(value)
  else values.delete(value)
  const next = { ...selected.value }
  if (values.size) next[id] = [...values]
  else delete next[id]
  publish(next)
}

function optionLabel(control: FilterControl, value: string): string {
  return control.values.find((option) => option.value === value)?.label ?? value
}

const chips = computed(() => props.controls.flatMap((control) => {
  const value = selected.value[control.id]
  const values = Array.isArray(value) ? value : value ? [value] : []
  return values.map((entry) => ({
    key: `${control.id}:${entry}`,
    label: `${control.label}: ${control.kind === 'toggle' ? 'Yes' : optionLabel(control, entry)}`,
  }))
}))
const activeCount = computed(() => chips.value.length)

function reset() {
  publish({})
}
</script>

<style scoped>
.library-filters { display: grid; gap: .6rem; }
.filter-toggle, .reset-all {
  justify-self: start;
  padding: .45rem .75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font: 600 .8rem var(--font-sans);
  cursor: pointer;
}
.filter-toggle:hover, .reset-all:hover { background: var(--bg-surface-hover); border-color: var(--border-hover); }
.filter-toggle:focus-visible, .reset-all:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.filter-panel { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: .75rem; }
.filter-control fieldset { border: 0; padding: 0; margin: 0; }
.filter-control label { display: block; margin: .25rem 0; }
.active-filters { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; }
.filter-chip { padding: .25rem .55rem; border-radius: 999px; background: var(--bg-surface); }
</style>
