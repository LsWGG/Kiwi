<script setup lang="ts">
/** Word 预览：调用后端导出接口生成 .docx，再用 docx-preview 渲染分页效果。 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { docxFontStack, docxPaperLabel, type DocxFont, type DocxPrefs } from './modes'

const props = defineProps<{
  noteId: string
  kbId: string
  active: boolean
  /** 外部递增时触发重新导出 / 渲染 */
  version: number
  docxPrefs?: DocxPrefs
  docTitle?: string
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'rendered'): void
  (e: 'scroll', ratio: number): void
}>()

const host = ref<HTMLElement | null>(null)
const scrollEl = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref('')
let token = 0

function scrollRatio(): number {
  const el = scrollEl.value
  if (!el) return 0
  const max = el.scrollHeight - el.clientHeight
  return max > 0 ? el.scrollTop / max : 0
}

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

/**
 * docx-preview 只在显式分页符处断页，导出文档没有分页符时会渲染成一整页。
 * 这里按纸张内容区高度把 article 顶层块重新分页，生成真实的多页预览。
 */
function paginate(el: HTMLElement) {
  const scale = uiScale()
  for (const section of Array.from(el.querySelectorAll<HTMLElement>('.kiwi-docx-wrapper > section.kiwi-docx'))) {
    if (section.dataset.kiwiPaginated) continue
    const article = section.querySelector<HTMLElement>(':scope > article')
    if (!article || !article.children.length) continue
    const cs = getComputedStyle(section)
    const pageHeight = Number.parseFloat(cs.minHeight) || section.offsetHeight
    const padTop = Number.parseFloat(cs.paddingTop) || 0
    const padBottom = Number.parseFloat(cs.paddingBottom) || 0
    const contentHeight = pageHeight - padTop - padBottom
    if (!(contentHeight > 80)) continue

    const articleTop = article.getBoundingClientRect().top
    const blocks = Array.from(article.children) as HTMLElement[]
    const metrics = blocks.map((block) => {
      const rect = block.getBoundingClientRect()
      return {
        top: (rect.top - articleTop) / scale,
        bottom: (rect.bottom - articleTop) / scale,
        block,
      }
    })

    const groups: HTMLElement[][] = []
    let current: HTMLElement[] = []
    let pageStart = 0
    for (const item of metrics) {
      if (current.length && item.bottom - pageStart > contentHeight) {
        groups.push(current)
        current = []
        pageStart = item.top
      }
      current.push(item.block)
    }
    if (current.length) groups.push(current)
    if (groups.length <= 1) {
      section.dataset.kiwiPaginated = '1'
      continue
    }

    // 首页保留原 section，其余内容按块移动到新页
    const rest = groups.slice(1)
    for (const group of rest) {
      for (const node of group) node.remove()
    }
    let anchor = section
    for (const group of rest) {
      const page = section.cloneNode(false) as HTMLElement
      page.removeAttribute('data-kiwi-paginated')
      for (const child of Array.from(section.children)) {
        if (child.tagName === 'ARTICLE') {
          const nextArticle = document.createElement('article')
          for (const node of group) nextArticle.appendChild(node)
          page.appendChild(nextArticle)
        } else {
          page.appendChild(child.cloneNode(true))
        }
      }
      anchor.after(page)
      anchor = page
    }
    section.dataset.kiwiPaginated = '1'
  }
}

/** DOCX 里的中文字体名在本机未必存在，映射为编辑器同款字体栈。 */
const DOCX_FAMILY_MAP: Record<string, DocxFont> = {
  宋体: 'serif',
  黑体: 'sans',
  楷体: 'kai',
  仿宋: 'fangsong',
  微软雅黑: 'yahei',
  苹方: 'pingfang',
  思源宋体: 'sourceSerif',
  思源黑体: 'sourceSans',
  'Times New Roman': 'times',
  Arial: 'arial',
  Calibri: 'calibri',
  Georgia: 'georgia',
  Consolas: 'mono',
}

function mapFontFamily(value: string): string {
  let changed = false
  const parts = value.split(',').map((part) => {
    const raw = part.trim()
    const name = raw.replace(/^['"]|['"]$/g, '')
    const font = DOCX_FAMILY_MAP[name]
    if (!font) return raw
    changed = true
    return docxFontStack(font)
  })
  return changed ? parts.join(', ') : value
}

function applyFontStacks(el: HTMLElement) {
  for (const node of Array.from(el.querySelectorAll<HTMLElement>('[style*="font-family"]'))) {
    const family = node.style.fontFamily
    if (family) node.style.fontFamily = mapFontFamily(family)
  }
  for (const styleEl of Array.from(el.querySelectorAll('style'))) {
    const css = styleEl.textContent || ''
    const next = css.replace(/font-family\s*:\s*([^;}]+)/gi, (_match, value: string) => {
      return `font-family: ${mapFontFamily(value.trim())}`
    })
    if (next !== css) styleEl.textContent = next
  }
}

/**
 * docx-preview 的页眉 / 页脚只显示域缓存值（所有页都是第 1 页），
 * 移除后由 decoratePages 按页重绘；导出的 DOCX 本身仍保留真实页眉页脚。
 */
function stripDocxChrome(el: HTMLElement) {
  const selector =
    '.kiwi-docx-wrapper > section.kiwi-docx > header, .kiwi-docx-wrapper > section.kiwi-docx > footer'
  for (const node of Array.from(el.querySelectorAll<HTMLElement>(selector))) {
    node.remove()
  }
}

/** 与编辑器 Word 纸张一致的页眉 / 页脚。 */
function decoratePages(el: HTMLElement) {
  const prefs = props.docxPrefs
  if (!prefs) return
  const pages = Array.from(
    el.querySelectorAll<HTMLElement>('.kiwi-docx-wrapper > section.kiwi-docx'),
  )
  const total = pages.length
  const title = props.docTitle?.trim() || '无标题文档'

  pages.forEach((section, index) => {
    const first = index === 0 && prefs.differentFirstPage
    const headerText = first
      ? prefs.firstHeaderText.trim()
      : prefs.headerText.trim() || title
    const footerTemplate = first
      ? prefs.firstFooterText.trim()
      : prefs.footerText.trim()
    const fallback = first ? '' : `${docxPaperLabel(prefs)}  ·  第 ${index + 1} 页`
    const footerText = (footerTemplate || fallback)
      .replace(/\{page\}/gi, String(index + 1))
      .replace(/\{pages\}/gi, String(total))
      .replace(/\{total\}/gi, String(total))

    if (prefs.showHeader && headerText && !section.querySelector(':scope > header')) {
      const bar = document.createElement('div')
      bar.className = 'kiwi-preview-page-head'
      Object.assign(bar.style, {
        position: 'absolute',
        top: `${prefs.headerDistance}cm`,
        left: `${prefs.margins.left}cm`,
        right: `${prefs.margins.right}cm`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        paddingBottom: '12px',
        borderBottom: '1px dashed rgba(203, 213, 225, 0.7)',
        fontSize: '11px',
        color: '#94a3b8',
        pointerEvents: 'none',
        zIndex: '1',
      })
      const left = document.createElement('span')
      left.textContent = headerText
      left.style.overflow = 'hidden'
      left.style.textOverflow = 'ellipsis'
      left.style.whiteSpace = 'nowrap'
      const brand = document.createElement('span')
      brand.textContent = 'KIWI DOCX'
      Object.assign(brand.style, {
        flexShrink: '0',
        fontSize: '9px',
        fontWeight: '500',
        letterSpacing: '0.18em',
        textTransform: 'uppercase',
        color: '#cbd5e1',
      })
      bar.append(left, brand)
      section.append(bar)
    }

    if (prefs.showFooter && footerText && !section.querySelector(':scope > footer')) {
      const bar = document.createElement('div')
      bar.className = 'kiwi-preview-page-foot'
      Object.assign(bar.style, {
        position: 'absolute',
        bottom: `${prefs.footerDistance}cm`,
        left: `${prefs.margins.left}cm`,
        right: `${prefs.margins.right}cm`,
        fontSize: '11px',
        color: '#94a3b8',
        pointerEvents: 'none',
        zIndex: '1',
      })
      bar.textContent = footerText
      section.append(bar)
    }
  })
}

function waitForImages(el: HTMLElement): Promise<void> {
  const images = Array.from(el.querySelectorAll('img')).filter((img) => !img.complete)
  if (!images.length) return Promise.resolve()
  return Promise.race([
    Promise.all(
      images.map(
        (img) =>
          new Promise<void>((resolve) => {
            img.addEventListener('load', () => resolve(), { once: true })
            img.addEventListener('error', () => resolve(), { once: true })
          }),
      ),
    ).then(() => undefined),
    new Promise<void>((resolve) => window.setTimeout(resolve, 1500)),
  ])
}

defineExpose({ scrollEl })

async function render() {
  const current = ++token
  loading.value = true
  error.value = ''
  try {
    await nextTick()
    const el = host.value
    if (!el) return
    el.innerHTML = ''
    const res = await fetch(
      `/api/notes/${props.noteId}/export/docx?kb_id=${encodeURIComponent(props.kbId)}`,
    )
    if (!res.ok) throw new Error(`生成 Word 预览失败（${res.status}）`)
    const buffer = await res.arrayBuffer()
    if (current !== token) return
    const { renderAsync } = await import('docx-preview')
    await renderAsync(buffer, el, el, {
      className: 'kiwi-docx',
      inWrapper: true,
      breakPages: true,
      ignoreLastRenderedPageBreak: true,
      useBase64URL: true,
      renderHeaders: true,
      renderFooters: true,
    })
    if (current === token) {
      await waitForImages(el)
      if (current !== token) return
      applyFontStacks(el)
      stripDocxChrome(el)
      await nextTick()
      paginate(el)
      decoratePages(el)
      await nextTick()
      emit('rendered')
      // 让编辑器目录在大纲打开时重新定位当前章节
      window.dispatchEvent(new CustomEvent('kiwi:word-preview-rendered'))
    }
  } catch (e: any) {
    if (current === token) error.value = e?.message || '无法生成 Word 预览'
  } finally {
    if (current === token) loading.value = false
  }
}

watch(
  () => [props.active, props.version, props.noteId] as const,
  ([active]) => {
    if (active) void render()
  },
  { immediate: true, flush: 'post' },
)

onBeforeUnmount(() => {
  token += 1
})
</script>

<template>
  <aside
    v-if="active"
    class="word-preview-pane flex h-full min-h-0 w-full min-w-0 shrink-0 flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-slate-100/80"
  >
    <header class="flex h-9 shrink-0 items-center gap-2 px-3">
      <KiwiIcon name="fileText" :size="13" class="shrink-0 text-sky-500" />
      <span class="shrink-0 text-[11.5px] font-medium text-slate-500">Word 预览</span>
      <span class="truncate text-[10px] text-slate-400">导出后的分页效果</span>
      <div class="flex-1" />
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white/70 hover:text-kiwi-600"
        title="刷新预览"
        :disabled="loading"
        @click="render"
      >
        <KiwiIcon name="refresh" :size="12" :spin="loading" />
      </button>
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white/70 hover:text-slate-700"
        title="关闭预览"
        @click="emit('close')"
      >
        <KiwiIcon name="close" :size="12" />
      </button>
    </header>

    <div
      ref="scrollEl"
      class="relative min-h-0 flex-1 overflow-auto"
      @scroll.passive="emit('scroll', scrollRatio())"
    >
      <div ref="host" class="word-preview-host" />
      <div
        v-if="loading"
        class="pointer-events-none absolute inset-0 grid place-items-center bg-slate-100/70"
      >
        <span class="inline-flex items-center gap-2 text-[11.5px] text-slate-500">
          <KiwiIcon name="loader" :size="14" spin />
          正在生成 Word 预览…
        </span>
      </div>
      <div v-if="error" class="absolute inset-0 grid place-items-center bg-slate-50 px-5">
        <div class="text-center">
          <KiwiIcon name="alert" :size="22" class="mx-auto text-amber-400" />
          <p class="mt-2 text-[11.5px] leading-relaxed text-slate-500">{{ error }}</p>
          <button type="button" class="kiwi-btn-primary mt-3 !py-1.5 !text-xs" @click="render">
            重试
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* 与左侧正文画布一致的灰底点阵，避免分栏像独立应用 */
.word-preview-pane {
  background-image:
    radial-gradient(circle at 1px 1px, rgba(148, 163, 184, 0.16) 1px, transparent 0);
  background-size: 18px 18px;
}
.word-preview-host {
  min-height: 100%;
}
.word-preview-host :deep(.kiwi-docx-wrapper) {
  padding: 14px;
  background: #eef2f7;
  min-width: min-content;
  min-height: 100%;
  box-sizing: border-box;
}
.word-preview-host :deep(.kiwi-docx-wrapper > section.kiwi-docx) {
  margin: 0 auto 14px;
  box-shadow: 0 6px 22px rgba(15, 23, 42, 0.08);
}
</style>
