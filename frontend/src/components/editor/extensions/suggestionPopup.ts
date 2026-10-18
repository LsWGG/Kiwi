/**
 * 通用浮动建议菜单（@ 提及 / : 表情共用）。
 * 外层 fixed 挂到 <html> 下，内层随 --ui-scale 缩放，避免 body 的 4K zoom 放大坐标。
 */

export interface SuggestionPopupConfig<T> {
  /** 外层固定定位容器类名 */
  menuClass: string
  /** 内层视觉盒子类名 */
  boxClass: string
  /** 渲染菜单内容；按钮需带 data-i 索引 */
  render: (items: T[], active: number) => string
}

export function createSuggestionPopup<T>(config: SuggestionPopupConfig<T>) {
  return () => {
    let el: HTMLDivElement | null = null
    let box: HTMLDivElement | null = null
    let items: T[] = []
    let index = 0
    let pick: ((item: T) => void) | null = null
    let getRect: (() => DOMRect | null) | null = null

    const caretRect = (): DOMRect | null => {
      const sel = window.getSelection()
      if (!sel || !sel.rangeCount) return null
      const rect = sel.getRangeAt(0).getBoundingClientRect()
      return rect.width || rect.height ? rect : null
    }

    const destroy = () => {
      window.removeEventListener('scroll', reflow, true)
      window.removeEventListener('resize', reflow)
      el?.remove()
      el = null
      box = null
      getRect = null
      pick = null
    }

    const ensure = () => {
      if (el) return
      el = document.createElement('div')
      el.className = `kiwi-suggest-menu ${config.menuClass}`
      el.addEventListener('mousedown', (e) => e.preventDefault())
      el.addEventListener('click', (e) => {
        const btn = (e.target as HTMLElement).closest('[data-i]') as HTMLElement | null
        if (!btn) return
        const i = Number(btn.dataset.i)
        if (Number.isInteger(i) && items[i]) pick?.(items[i])
      })
      box = document.createElement('div')
      box.className = `kiwi-suggest-box ${config.boxClass}`
      el.appendChild(box)
      document.documentElement.appendChild(el)
      window.addEventListener('scroll', reflow, true)
      window.addEventListener('resize', reflow)
    }

    const paint = () => {
      if (!box) return
      box.innerHTML = items.length ? config.render(items, index) : ''
      box
        .querySelector<HTMLElement>(`[data-i="${index}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    }

    const position = (rect?: DOMRect | null) => {
      if (!el || !box) return
      const anchor = rect ?? getRect?.() ?? caretRect()
      if (!anchor) return
      const boxRect = box.getBoundingClientRect()
      const width = boxRect.width || 280
      const height = Math.min(boxRect.height || 300, window.innerHeight - 16)
      let top = anchor.bottom + 6
      if (top + height > window.innerHeight - 8) {
        top = Math.max(8, anchor.top - height - 6)
      }
      const left = Math.min(
        Math.max(8, anchor.left),
        Math.max(8, window.innerWidth - width - 8),
      )
      el.style.top = `${top}px`
      el.style.left = `${left}px`
    }

    function reflow() {
      position()
    }

    const refresh = (props: any) => {
      items = Array.isArray(props.items) ? [...props.items] : []
      pick = props.command ?? null
      getRect = typeof props.clientRect === 'function' ? props.clientRect : null
      if (!items.length) {
        destroy()
        return
      }
      ensure()
      paint()
      position(props.clientRect?.() ?? null)
    }

    return {
      onStart(props: any) {
        index = 0
        refresh(props)
      },
      onUpdate(props: any) {
        const previous = items[index]
        index = 0
        refresh(props)
        // 尽量保持当前项，避免输入时选中项跳动
        if (items.length && previous) {
          const keep = items.indexOf(previous)
          if (keep >= 0) index = keep
          paint()
        }
      },
      onKeyDown(props: any) {
        if (!items.length) return false
        if (props.event.key === 'ArrowDown') {
          index = (index + 1) % items.length
          paint()
          return true
        }
        if (props.event.key === 'ArrowUp') {
          index = (index - 1 + items.length) % items.length
          paint()
          return true
        }
        if (props.event.key === 'Enter' || props.event.key === 'Tab') {
          pick?.(items[index])
          return true
        }
        return false
      },
      onExit() {
        destroy()
      },
    }
  }
}
