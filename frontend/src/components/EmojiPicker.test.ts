import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EmojiPicker from './EmojiPicker.vue'

const mounted = new Map<VueWrapper, HTMLElement>()

function mountPicker() {
  const host = document.createElement('div')
  document.body.append(host)
  const wrapper = mount(EmojiPicker, { attachTo: host })
  mounted.set(wrapper, host)
  const trigger = wrapper.get<HTMLButtonElement>('.emoji-trigger')
  const popup = () => document.querySelector<HTMLElement>('.emoji-panel')
  async function action(name: string) {
    const button = Array.from(popup()!.querySelectorAll<HTMLButtonElement>('.chat-menu-action'))
      .find(element => element.textContent?.includes(name))!
    button.click()
    await nextTick()
    await nextTick()
  }
  return { wrapper, trigger, popup, action }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  for (const [wrapper, host] of mounted) {
    wrapper.unmount()
    host.remove()
  }
  mounted.clear()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('chat options menu', () => {
  it('lets a pointer cross the hover gap and dismisses the menu after leaving', async () => {
    const { trigger, popup } = mountPicker()
    await trigger.trigger('pointerenter', { pointerType: 'mouse' })
    expect(popup()?.textContent).toContain('Chat settings')
    expect(popup()?.textContent).toContain('Emojis')
    expect(document.activeElement).not.toBe(trigger.element)

    await trigger.trigger('pointerleave')
    vi.advanceTimersByTime(100)
    popup()!.dispatchEvent(new Event('pointerenter'))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(popup()).not.toBeNull()
    popup()!.dispatchEvent(new Event('pointerleave'))
    vi.advanceTimersByTime(251)
    await nextTick()
    expect(popup()).toBeNull()
  })

  it('pins an already hovered menu on click and closes it on an outside pointer', async () => {
    const { trigger, popup } = mountPicker()
    await trigger.trigger('pointerenter', { pointerType: 'mouse' })
    await trigger.trigger('click')
    await trigger.trigger('pointerleave')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(popup()).not.toBeNull()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await nextTick()
    expect(popup()).toBeNull()
  })

  it('ignores touch hover and supports keyboard opening, selection and Escape focus restoration', async () => {
    const { trigger, popup, action } = mountPicker()
    await trigger.trigger('pointerenter', { pointerType: 'touch' })
    expect(popup()).toBeNull()
    trigger.element.focus()
    await trigger.trigger('keydown', { key: 'ArrowUp' })
    await nextTick()
    expect(document.activeElement?.textContent).toContain('Chat settings')
    await action('Chat settings')
    expect(popup()?.getAttribute('aria-label')).toBe('Chat settings')
    expect(document.activeElement?.tagName).toBe('SELECT')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(popup()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })

  it('keeps settings open while selecting a font and emits appearance changes and reset', async () => {
    const { wrapper, trigger, popup, action } = mountPicker()
    await trigger.trigger('click')
    await action('Chat settings')
    popup()!.dispatchEvent(new Event('pointerleave'))
    vi.advanceTimersByTime(300)
    await nextTick()
    const font = popup()!.querySelector<HTMLSelectElement>('select')!
    font.value = 'oxanium'
    font.dispatchEvent(new Event('change', { bubbles: true }))
    const size = popup()!.querySelector<HTMLInputElement>('input[type="range"]')!
    size.value = '22'
    size.dispatchEvent(new Event('input', { bubbles: true }))
    popup()!.querySelector<HTMLButtonElement>('.chat-settings-reset')!.click()
    expect(wrapper.emitted('update:font')).toEqual([['oxanium']])
    expect(wrapper.emitted('update:size')).toEqual([[22]])
    expect(wrapper.emitted('reset')).toHaveLength(1)
    expect(popup()).not.toBeNull()
  })

  it('selects an emoji and cleans up a pending hover dismissal on unmount', async () => {
    const { wrapper, trigger, popup, action } = mountPicker()
    await trigger.trigger('click')
    await action('Emojis')
    popup()!.querySelector<HTMLButtonElement>('.emoji-btn')!.click()
    await nextTick()
    expect(wrapper.emitted('select')).toEqual([['😀']])
    expect(popup()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)

    trigger.element.blur()
    await trigger.trigger('pointerenter', { pointerType: 'mouse' })
    await trigger.trigger('pointerleave')
    const remove = vi.spyOn(document, 'removeEventListener')
    wrapper.unmount()
    mounted.get(wrapper)!.remove()
    mounted.delete(wrapper)
    expect(remove).toHaveBeenCalledWith('pointerdown', expect.any(Function))
    expect(remove).toHaveBeenCalledWith('keydown', expect.any(Function))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(popup()).toBeNull()
  })
})
