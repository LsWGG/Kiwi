/**
 * 引用锚点：问答引用跳转后，在正文中定位并高亮对应段落。
 *
 * 使用 CSS Custom Highlight API 只影响绘制层，不修改 ProseMirror / Vue
 * 管理的 DOM，因此不会破坏编辑器状态。找不到 quote 时退化为按标题定位。
 */
import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'

const HIGHLIGHT_NAME = 'kiwi-citation'

interface CharRef {
  node: Text
  offset: number
}

function textNodes(root: HTMLElement): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!(node instanceof Text)) return NodeFilter.FILTER_REJECT
      const parent = node.parentElement
      if (!parent) return NodeFilter.FILTER_REJECT
      const tag = parent.tagName
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') {
        return NodeFilter.FILTER_REJECT
      }
      return node.data.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    },
  })
  const nodes: Text[] = []
  let current = walker.nextNode()
  while (current) {
    nodes.push(current as Text)
    current = walker.nextNode()
  }
  return nodes
}

function normalize(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase()
}

/**
 * 在容器内跨文本节点查找一段文本。
 * 返回的 Range 已处理空白折叠与大小写差异。
 */
function findRange(root: HTMLElement, quote: string): Range | null {
  const target = normalize(quote)
  if (!target) return null

  const refs: CharRef[] = []
  let buffer = ''
  let lastWasSpace = true
  for (const node of textNodes(root)) {
    for (let i = 0; i < node.data.length; i += 1) {
      const char = node.data[i]
      if (/\s/.test(char)) {
        if (lastWasSpace) continue
        buffer += ' '
        refs.push({ node, offset: i })
        lastWasSpace = true
        continue
      }
      buffer += char.toLowerCase()
      refs.push({ node, offset: i })
      lastWasSpace = false
    }
  }
  if (!buffer) return null

  // 分块 / 渲染可能截断引用：依次尝试完整文本与前缀，最短 24 字符。
  const limits = [target.length, 120, 80, 48, 24].filter(
    (length, index, all) => length <= target.length && all.indexOf(length) === index,
  )
  for (const length of limits) {
    if (length < 8) continue
    const needle = target.slice(0, length).trim()
    const index = buffer.indexOf(needle)
    if (index < 0 || !refs[index]) continue
    const endIndex = index + needle.length - 1
    const start = refs[index]
    const end = refs[endIndex]
    if (!start || !end) continue
    const range = document.createRange()
    range.setStart(start.node, start.offset)
    range.setEnd(end.node, end.offset + 1)
    return range
  }
  return null
}

function findHeadingRange(root: HTMLElement, heading: string): Range | null {
  const target = normalize(heading)
  if (!target) return null
  const headings = root.querySelectorAll<HTMLElement>(
    'h1,h2,h3,h4,h5,h6,[data-type="heading"]',
  )
  for (const item of headings) {
    if (normalize(item.textContent || '').includes(target)) {
      const range = document.createRange()
      range.selectNodeContents(item)
      return range
    }
  }
  return null
}

function clearHighlight() {
  const highlights = (CSS as any)?.highlights
  highlights?.delete?.(HIGHLIGHT_NAME)
}

function applyHighlight(range: Range) {
  const HighlightCtor = (window as any).Highlight
  const highlights = (CSS as any)?.highlights
  if (!HighlightCtor || !highlights) return
  const highlight = new HighlightCtor(range)
  // 同名 Highlight 会覆盖旧值，无需手动清理。
  highlights.set(HIGHLIGHT_NAME, highlight)
}

function scrollToRange(range: Range) {
  const element =
    range.startContainer.parentElement instanceof HTMLElement
      ? range.startContainer.parentElement
      : null
  element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

export function useCitationAnchor(container: Ref<HTMLElement | null>) {
  const route = useRoute()
  let observer: MutationObserver | null = null
  let timer: number | undefined

  function stop() {
    observer?.disconnect()
    observer = null
    window.clearTimeout(timer)
    timer = undefined
  }

  function tryLocate() {
    stop()
    clearHighlight()
    const root = container.value
    if (!root) return
    const quote = typeof route.query.quote === 'string' ? route.query.quote : ''
    const heading = typeof route.query.heading === 'string' ? route.query.heading : ''
    if (!quote && !heading) return

    const run = () => {
      const range = findRange(root, quote) || findHeadingRange(root, heading)
      if (range) {
        applyHighlight(range)
        scrollToRange(range)
        return true
      }
      return false
    }

    if (run()) return
    // 正文可能在异步加载 / Markdown 渲染后出现：观察 DOM 变化并重试，
    // 5 秒后放弃，避免离开页面后仍持续消耗。
    observer = new MutationObserver(() => {
      if (run()) stop()
    })
    observer.observe(root, { childList: true, subtree: true, characterData: true })
    timer = window.setTimeout(stop, 5000)
  }

  onMounted(tryLocate)
  watch(
    () => [route.query.quote, route.query.heading, route.name, route.params.id],
    () => {
      tryLocate()
    },
  )
  watch(container, () => {
    tryLocate()
  })
  onBeforeUnmount(() => {
    stop()
    clearHighlight()
  })
}
