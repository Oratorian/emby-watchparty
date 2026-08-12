import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ToggleSwitch from './ToggleSwitch.vue'

/**
 * The shared on/off control, used eleven times across the admin panel and the
 * title detail view.
 *
 * Every call site puts its wording in a sibling element, outside this
 * component's <label>, so no native association ever formed: all eleven
 * announced as an unnamed "checkbox, not checked", with nothing saying which
 * setting was about to change. On the admin panel that is nine consecutive
 * identical controls.
 */

describe('ToggleSwitch', () => {
  it('carries the name its caller gave it', () => {
    const wrapper = mount(ToggleSwitch, { props: { label: 'Force Transcode' } })

    const input = wrapper.get('input[type="checkbox"]')
    expect(input.attributes('aria-label')).toBe('Force Transcode')
  })

  it('announces as a switch rather than a checkbox', () => {
    const wrapper = mount(ToggleSwitch, { props: { label: 'Rate Limiting' } })

    // "on"/"off" rather than "checked"/"not checked" for a control whose whole
    // job is on/off. Still a real checkbox input underneath, so the keyboard
    // behaviour and the :checked styling stay the browser's.
    expect(wrapper.get('input').attributes('role')).toBe('switch')
  })

  it('reports its state through the input, not just the styling', () => {
    const wrapper = mount(ToggleSwitch, {
      props: { label: 'Log to File', modelValue: true },
    })

    // The track and knob are painted from :checked, so a component that only
    // moved the knob would look right and tell a screen reader nothing.
    expect((wrapper.get('input').element as HTMLInputElement).checked).toBe(true)
  })

  it('still emits the model update it is there for', async () => {
    const wrapper = mount(ToggleSwitch, {
      props: { label: 'Binge-Watch', modelValue: false },
    })

    await wrapper.get('input').setValue(true)

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([true])
  })
})
