<template>
  <section class="library-filters" aria-label="Library filters">
    <button
      class="filter-toggle"
      type="button"
      :aria-expanded="open"
      @click="togglePanel"
    >
      Filters <span v-if="activeCount">{{ activeCount }} active</span>
    </button>

    <div v-if="open" class="filter-panel">
      <section v-for="section in filterSections" :key="section.id" class="filter-section">
        <button
          v-if="section.id === 'advanced'"
          type="button"
          class="advanced-toggle"
          :aria-expanded="advancedOpen"
          @click="toggleAdvanced"
        >
          <span>More filters</span>
          <span class="advanced-summary">
            {{ advancedActiveCount ? `${advancedActiveCount} active` : `${advancedControls.length} available` }}
            <span class="disclosure-icon" aria-hidden="true">⌄</span>
          </span>
        </button>

        <div v-if="section.id === 'quick' || advancedOpen" class="filter-grid">
          <div v-for="control in section.controls" :key="control.id" class="filter-control">
            <div v-if="control.id === 'year'" class="filter-multi">
              <button
                type="button"
                class="filter-choice"
                :aria-label="`${activeGroup === control.id ? 'Close' : 'Open'} ${control.label} filter`"
                :aria-expanded="activeGroup === control.id"
                @click="toggleGroup(control.id)"
              >
                <span>{{ control.label }}</span>
                <span>{{ yearSummary || 'Any' }}</span>
              </button>
              <div v-if="activeGroup === control.id" class="option-popover year-popover">
                <div class="year-modes" aria-label="Year filter mode">
                  <button
                    v-for="mode in YEAR_MODES"
                    :key="mode.id"
                    type="button"
                    :aria-label="mode.ariaLabel"
                    :aria-pressed="yearMode === mode.id"
                    @click="yearMode = mode.id"
                  >
                    {{ mode.label }}
                  </button>
                </div>
                <label v-if="yearMode === 'exact'" class="year-field">
                  <span>Year</span>
                  <input v-model="exactYear" aria-label="Exact year" type="number" :min="MIN_YEAR" :max="MAX_YEAR">
                </label>
                <div v-else-if="yearMode === 'range'" class="year-range">
                  <label class="year-field">
                    <span>Start</span>
                    <input v-model="rangeStart" aria-label="Start year" type="number" :min="MIN_YEAR" :max="MAX_YEAR">
                  </label>
                  <label class="year-field">
                    <span>End</span>
                    <input v-model="rangeEnd" aria-label="End year" type="number" :min="MIN_YEAR" :max="MAX_YEAR">
                  </label>
                </div>
                <label v-else class="year-field">
                  <span>Decade</span>
                  <select v-model="decadeStart" aria-label="Year decade">
                    <option v-for="decade in decades" :key="decade" :value="String(decade)">
                      {{ decade }}–{{ Math.min(decade + 9, MAX_YEAR) }}
                    </option>
                  </select>
                </label>
                <p v-if="yearMode === 'range' && !yearSelectionValid" class="option-hint">
                  Start year must not be later than end year.
                </p>
                <div class="year-actions">
                  <button type="button" aria-label="Clear year filter" @click="clearYear">Clear</button>
                  <button
                    type="button"
                    aria-label="Apply year filter"
                    :disabled="!yearSelectionValid"
                    @click="applyYear"
                  >
                    Apply
                  </button>
                </div>
              </div>
            </div>

            <label v-else-if="control.kind === 'select'" class="filter-select">
              <span>{{ control.label }}</span>
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

            <button
              v-else-if="control.kind === 'toggle'"
              type="button"
              class="filter-choice"
              :aria-pressed="selectedScalar(control.id) === 'true'"
              @click="setToggle(control.id, selectedScalar(control.id) !== 'true')"
            >
              <span>{{ control.label }}</span>
              <span>{{ selectedScalar(control.id) === 'true' ? 'Yes' : 'Any' }}</span>
            </button>

            <div v-else class="filter-multi">
              <button
                type="button"
                class="filter-choice"
                :aria-label="`${activeGroup === control.id ? 'Close' : 'Open'} ${control.label} filter`"
                :aria-expanded="activeGroup === control.id"
                @click="toggleGroup(control.id)"
              >
                <span>{{ control.label }}</span>
                <span>{{ selectedList(control.id).length ? `${selectedList(control.id).length} selected` : 'Any' }}</span>
              </button>
              <div v-if="activeGroup === control.id" class="option-popover">
                <input
                  v-if="control.values.length > OPTION_PREVIEW_LIMIT"
                  v-model="optionQueries[control.id]"
                  type="search"
                  :aria-label="`Search ${control.label} options`"
                  :placeholder="`Search ${control.label.toLowerCase()}…`"
                  autocomplete="off"
                />
                <div class="option-list">
                  <label v-for="option in displayedOptions(control)" :key="option.value">
                    <input
                      type="checkbox"
                      :value="option.value"
                      :checked="selectedList(control.id).includes(option.value)"
                      @change="setListValue(control.id, option.value, ($event.target as HTMLInputElement).checked)"
                    />
                    <span>{{ option.label }}</span>
                  </label>
                  <p v-if="hiddenOptionCount(control)" class="option-hint">
                    {{ hiddenOptionCount(control) }} more options — search to narrow
                  </p>
                  <p v-if="!displayedOptions(control).length" class="option-hint">No matching options.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
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
const advancedOpen = ref(false)
const selected = ref<LibraryFilterState>({ ...props.modelValue })
const activeGroup = ref<string | null>(null)
const optionQueries = ref<Record<string, string>>({})
const OPTION_PREVIEW_LIMIT = 8
const MIN_YEAR = 1888
const MAX_YEAR = new Date().getFullYear()
type YearMode = 'exact' | 'range' | 'decade'
const YEAR_MODES: { id: YearMode, label: string, ariaLabel: string }[] = [
  { id: 'exact', label: 'Exact', ariaLabel: 'Exact year mode' },
  { id: 'range', label: 'Range', ariaLabel: 'Year range mode' },
  { id: 'decade', label: 'Decade', ariaLabel: 'Decade mode' },
]
const yearMode = ref<YearMode>('exact')
const exactYear = ref(String(MAX_YEAR))
const rangeStart = ref(String(MAX_YEAR - 9))
const rangeEnd = ref(String(MAX_YEAR))
const decadeStart = ref(String(Math.floor(MAX_YEAR / 10) * 10))
const decades = Array.from(
  { length: Math.floor(MAX_YEAR / 10) - Math.floor(MIN_YEAR / 10) + 1 },
  (_, index) => Math.floor(MAX_YEAR / 10) * 10 - (index * 10),
)
const QUICK_FILTER_IDS = new Set([
  'playstate', 'favorite', 'genre', 'year', 'official_rating', 'resolution',
])

const quickControls = computed(() => props.controls.filter((control) => QUICK_FILTER_IDS.has(control.id)))
const advancedControls = computed(() => props.controls.filter((control) => !QUICK_FILTER_IDS.has(control.id)))
const filterSections = computed(() => [
  { id: 'quick', controls: quickControls.value },
  { id: 'advanced', controls: advancedControls.value },
].filter((section) => section.controls.length))

watch(() => props.modelValue, (value) => {
  selected.value = { ...value }
}, { deep: true })

function selectedScalar(id: string): string {
  const value = selected.value[id]
  const control = props.controls.find((candidate) => candidate.id === id)
  const fallback = control?.values.some((option) => option.value === 'any') ? 'any' : ''
  return Array.isArray(value) ? '' : String(value ?? fallback)
}

function selectedList(id: string): string[] {
  const value = selected.value[id]
  return Array.isArray(value) ? value : []
}

function togglePanel() {
  open.value = !open.value
  if (!open.value) {
    activeGroup.value = null
    advancedOpen.value = false
  }
}

function toggleAdvanced() {
  advancedOpen.value = !advancedOpen.value
  if (!advancedOpen.value && advancedControls.value.some((control) => control.id === activeGroup.value)) {
    activeGroup.value = null
  }
}

function toggleGroup(id: string) {
  if (id === 'year' && activeGroup.value !== id) hydrateYearDraft()
  activeGroup.value = activeGroup.value === id ? null : id
}

function validYear(value: string): number | null {
  if (!/^\d{4}$/.test(value)) return null
  const year = Number(value)
  return year >= MIN_YEAR && year <= MAX_YEAR ? year : null
}

function hydrateYearDraft() {
  const value = selected.value.year
  if (Array.isArray(value) && value.length) {
    const years = value.map(Number).filter(Number.isInteger).sort((left, right) => left - right)
    if (years.length === 1) {
      yearMode.value = 'exact'
      exactYear.value = String(years[0])
    } else if (years.length) {
      yearMode.value = 'range'
      rangeStart.value = String(years[0])
      rangeEnd.value = String(years.at(-1))
    }
    return
  }
  if (typeof value !== 'string') return
  const parts = value.split(':')
  if (parts[0] === 'exact' && parts[1]) {
    yearMode.value = 'exact'
    exactYear.value = parts[1]
  } else if (parts[0] === 'range' && parts[1] && parts[2]) {
    yearMode.value = 'range'
    rangeStart.value = parts[1]
    rangeEnd.value = parts[2]
  } else if (parts[0] === 'decade' && parts[1]) {
    yearMode.value = 'decade'
    decadeStart.value = parts[1]
  }
}

const yearSelectionValid = computed(() => {
  if (yearMode.value === 'exact') return validYear(exactYear.value) !== null
  if (yearMode.value === 'decade') return validYear(decadeStart.value) !== null
  const start = validYear(rangeStart.value)
  const end = validYear(rangeEnd.value)
  return start !== null && end !== null && start <= end
})

function applyYear() {
  if (!yearSelectionValid.value) return
  const value = yearMode.value === 'exact'
    ? `exact:${exactYear.value}`
    : yearMode.value === 'range'
      ? `range:${rangeStart.value}:${rangeEnd.value}`
      : `decade:${decadeStart.value}`
  publish({ ...selected.value, year: value })
}

function clearYear() {
  const next = { ...selected.value }
  delete next.year
  publish(next)
}

const yearSummary = computed(() => {
  const value = selected.value.year
  if (Array.isArray(value)) {
    if (value.length === 1) return value[0]
    if (value.length > 1) return `${value[0]}–${value.at(-1)}`
    return ''
  }
  if (typeof value !== 'string') return ''
  const [mode, first, second] = value.split(':')
  if (mode === 'exact') return first ?? ''
  if (mode === 'range') return first && second ? `${first}–${second}` : ''
  if (mode === 'decade' && first) return `${first}–${Math.min(Number(first) + 9, MAX_YEAR)}`
  return value
})

function displayedOptions(control: FilterControl) {
  const query = (optionQueries.value[control.id] ?? '').trim().toLocaleLowerCase()
  if (query) {
    return control.values.filter((option) => option.label.toLocaleLowerCase().includes(query))
  }
  const selectedValues = new Set(selectedList(control.id))
  return [
    ...control.values.filter((option) => selectedValues.has(option.value)),
    ...control.values.filter((option) => !selectedValues.has(option.value)),
  ].slice(0, OPTION_PREVIEW_LIMIT)
}

function hiddenOptionCount(control: FilterControl): number {
  if ((optionQueries.value[control.id] ?? '').trim()) return 0
  return Math.max(0, control.values.length - displayedOptions(control).length)
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
  if (control.id === 'year' && yearSummary.value) {
    return [{ key: `year:${String(value)}`, label: `Year: ${yearSummary.value}` }]
  }
  const values = Array.isArray(value) ? value : value ? [value] : []
  return values.map((entry) => ({
    key: `${control.id}:${entry}`,
    label: `${control.label}: ${control.kind === 'toggle' ? 'Yes' : optionLabel(control, entry)}`,
  }))
}))
const activeCount = computed(() => chips.value.length)
const advancedActiveCount = computed(() => advancedControls.value.reduce((count, control) => {
  const value = selected.value[control.id]
  if (Array.isArray(value)) return count + value.length
  return count + (value && value !== 'any' ? 1 : 0)
}, 0))

function reset() {
  publish({})
}
</script>

<style scoped>
.library-filters { display: grid; gap: .6rem; }
.filter-toggle, .reset-all, .filter-choice {
  justify-self: start;
  padding: .45rem .75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font: 600 .8rem var(--font-sans);
  cursor: pointer;
}
.filter-toggle:hover, .reset-all:hover, .filter-choice:hover { background: var(--bg-surface-hover); border-color: var(--border-hover); }
.filter-toggle:focus-visible, .reset-all:focus-visible, .filter-choice:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.filter-panel {
  padding: .75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--bg-surface);
}
.filter-section { display: grid; gap: .6rem; }
.filter-section + .filter-section {
  margin-top: .75rem;
  padding-top: .75rem;
  border-top: 1px solid var(--border-subtle);
}
.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 10.5rem), 1fr));
  gap: .55rem;
}
.filter-control { min-width: 0; position: relative; }
.filter-select {
  min-height: 2.65rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: .5rem;
  padding: .25rem .35rem .25rem .75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--bg-surface);
  font: 600 .8rem var(--font-sans);
}
.filter-select:focus-within { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.filter-select select {
  min-width: 5.5rem;
  width: auto;
  min-height: 2rem;
  padding-top: .25rem;
  padding-bottom: .25rem;
  border: 0;
  background-color: transparent;
  color: var(--text-secondary);
  font-weight: 500;
}
.filter-choice { width: 100%; min-height: 2.65rem; display: flex; justify-content: space-between; gap: .6rem; text-align: left; }
.filter-choice span:last-child { color: var(--text-secondary); font-weight: 500; white-space: nowrap; }
.filter-choice[aria-pressed="true"] { border-color: var(--accent-primary); background: var(--bg-surface-hover); }
.advanced-toggle {
  width: 100%;
  min-height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  padding: .4rem .15rem;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  font: 600 .8rem var(--font-sans);
  cursor: pointer;
  text-align: left;
}
.advanced-toggle:hover { color: var(--accent-primary); }
.advanced-toggle:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; border-radius: 6px; }
.advanced-summary { color: var(--text-secondary); font-weight: 500; }
.disclosure-icon { display: inline-block; margin-left: .35rem; transition: transform .16s ease; }
.advanced-toggle[aria-expanded="true"] .disclosure-icon { transform: rotate(180deg); }
.option-popover {
  position: absolute;
  z-index: 30;
  top: calc(100% + .35rem);
  left: 0;
  width: min(22rem, 75vw);
  padding: .65rem;
  border: 1px solid var(--border-hover);
  border-radius: 10px;
  background: var(--bg-secondary);
  box-shadow: 0 14px 32px rgba(0, 0, 0, .42);
}
.option-popover > input { width: 100%; min-height: 2.5rem; margin-bottom: .45rem; }
.option-list { display: grid; gap: .15rem; max-height: 16rem; overflow: auto; overscroll-behavior: contain; }
.option-list label { display: flex; align-items: flex-start; gap: .45rem; padding: .38rem .3rem; border-radius: 6px; font-size: max(.8rem, 14px); }
.option-list label:hover { background: var(--bg-surface-hover); }
.option-list input { margin-top: .15rem; flex: 0 0 auto; }
.option-hint { margin: .35rem .3rem .15rem; color: var(--text-secondary); font-size: max(.75rem, 13px); }
.year-popover { display: grid; gap: .65rem; }
.year-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: .3rem; }
.year-modes button, .year-actions button {
  min-height: 2.25rem;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
}
.year-modes button[aria-pressed="true"] { border-color: var(--accent-primary); background: var(--bg-surface-hover); }
.year-field { display: grid; gap: .3rem; color: var(--text-secondary); font-size: max(.75rem, 13px); }
.year-field input, .year-field select { width: 100%; min-height: 2.5rem; }
.year-range { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
.year-actions { display: flex; justify-content: flex-end; gap: .4rem; }
.year-actions button { padding: .35rem .75rem; }
.year-actions button:disabled { cursor: not-allowed; opacity: .5; }
.active-filters { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; }
.filter-chip { padding: .25rem .55rem; border-radius: 999px; background: var(--bg-surface); }
@media (max-width: 640px) {
  .filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .option-popover { position: fixed; inset: auto 1rem 1rem; width: auto; max-height: 65vh; }
  .option-list { max-height: 45vh; }
}
</style>
