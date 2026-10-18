/**
 * DOCX 模式分页：按纸张高度把连续文档切成多页。
 * 通过 ProseMirror 的 widget 装饰在跨页处插入「页间距」占位，
 * 占位内部画出纸张下边距、灰色页缝和下一页上边距；
 * 文档模型不变，光标与撤销历史不受影响。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export interface PagedMetrics {
  /** 整页高度（CSS px） */
  pageHeight: number
  /** 页内可排版高度（扣除上下边距） */
  contentHeight: number
  topMargin: number
  bottomMargin: number
  leftMargin: number
  rightMargin: number
  /** 纸张之间的灰色间隙 */
  gap: number
}

interface PagedDocOptions {
  enabled: () => boolean
  metrics: () => PagedMetrics
  /** 排版页数变化时通知外部（页脚页码） */
  onPages?: (pages: number) => void
}

const PAGE_GAP_ATTR = 'data-kiwi-page-gap'

interface GapSpec {
  pos: number
  /** 占位总高度（CSS px） */
  height: number
  /** 占位顶部到当前纸张底边的白色区域 */
  paperHeight: number
  /** 灰色页缝高度 */
  bandHeight: number
  /** 下一页上边距 */
  nextTop: number
  pageNumber: number
  leftMargin: number
  rightMargin: number
}

function sameGaps(a: GapSpec[], b: GapSpec[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    const x = a[i]
    const y = b[i]
    if (
      x.pos !== y.pos ||
      Math.abs(x.height - y.height) > 0.6 ||
      Math.abs(x.paperHeight - y.paperHeight) > 0.6 ||
      Math.abs(x.bandHeight - y.bandHeight) > 0.6
    ) {
      return false
    }
  }
  return true
}

function gapElement(spec: GapSpec): HTMLElement {
  const el = document.createElement('div')
  el.setAttribute(PAGE_GAP_ATTR, 'true')
  el.setAttribute('data-pos', String(spec.pos))
  el.setAttribute('contenteditable', 'false')
  el.setAttribute('aria-hidden', 'true')
  el.className = 'kiwi-page-gap'
  el.style.height = `${spec.height}px`
  el.style.marginLeft = `${-spec.leftMargin}px`
  el.style.marginRight = `${-spec.rightMargin}px`

  const paper1 = document.createElement('div')
  paper1.className = 'kiwi-page-gap-paper'
  paper1.style.height = `${Math.max(0, spec.paperHeight)}px`

  const band = document.createElement('div')
  band.className = 'kiwi-page-gap-band'
  band.style.height = `${Math.max(0, spec.bandHeight)}px`
  if (spec.bandHeight >= 18) {
    const label = document.createElement('span')
    label.textContent = `第 ${spec.pageNumber} 页结束`
    band.append(label)
  }

  const paper2 = document.createElement('div')
  paper2.className = 'kiwi-page-gap-paper'
  paper2.style.height = `${Math.max(0, spec.nextTop)}px`

  el.append(paper1, band, paper2)
  return el
}

export const PagedDoc = Extension.create<PagedDocOptions>({
  name: 'pagedDoc',

  addStorage() {
    return {
      refresh: () => {
        /* 由视图插件覆盖 */
      },
    }
  },

  addProseMirrorPlugins() {
    const options = this.options
    const editor = this.editor
    const key = new PluginKey<DecorationSet>('kiwi-paged-doc')

    return [
      new Plugin<DecorationSet>({
        key,

        state: {
          init: () => DecorationSet.empty,
          apply(tr, value) {
            const meta = tr.getMeta(key)
            if (meta instanceof DecorationSet) return meta
            return value.map(tr.mapping, tr.doc)
          },
        },

        props: {
          decorations(state) {
            return this.getState(state)
          },
        },

        view(view) {
          let timer: number | null = null
          let current: GapSpec[] = []
          let running = false

          const clear = () => {
            if (!current.length) return
            current = []
            view.dispatch(view.state.tr.setMeta(key, DecorationSet.empty))
          }

          const measure = () => {
            if (running) return
            running = true
            try {
              if (!options.enabled()) {
                clear()
                return
              }
              const metrics = options.metrics()
              const pm = view.dom
              const pmRect = pm.getBoundingClientRect()
              if (!pmRect.width || !pmRect.height) return
              const cssWidth = pm.offsetWidth || pmRect.width
              const scale = pmRect.width / cssWidth || 1

              // 已有占位会影响后续块的视觉位置，测量时按文档顺序减去其高度
              const gapEls = Array.from(
                pm.querySelectorAll<HTMLElement>(`:scope > [${PAGE_GAP_ATTR}]`),
              )
              const gapsInDom = gapEls
                .map((el) => ({
                  pos: Number(el.getAttribute('data-pos') ?? '-1'),
                  height: el.getBoundingClientRect().height / scale,
                }))
                .sort((a, b) => a.pos - b.pos)

              const blocks = Array.from(pm.children).filter(
                (el) => !(el as HTMLElement).hasAttribute(PAGE_GAP_ATTR),
              )

              const next: GapSpec[] = []
              const pitch = metrics.pageHeight + metrics.gap
              let gapIndex = 0
              let removed = 0
              let shift = 0
              let page = 0
              let forceBreak = false
              let blockIndex = 0
              let lastRawBottom = 0

              view.state.doc.forEach((node, offset) => {
                while (gapIndex < gapsInDom.length && gapsInDom[gapIndex].pos <= offset) {
                  removed += gapsInDom[gapIndex].height
                  gapIndex += 1
                }
                const dom = blocks[blockIndex] as HTMLElement | undefined
                blockIndex += 1
                if (!dom) return

                const rect = dom.getBoundingClientRect()
                const rawTop = (rect.top - pmRect.top) / scale - removed
                const height = rect.height / scale
                lastRawBottom = rawTop + height
                const top = rawTop + shift
                const onPage = top - page * pitch
                const fits = !forceBreak && onPage + height <= metrics.contentHeight + 0.5

                if (!fits) {
                  let nextStart = (page + 1) * pitch
                  // 超长块可能已经越过下一页起点，继续向后找
                  while (nextStart < top - 0.5) nextStart += pitch
                  const heightGap = nextStart - top
                  const paperBottom = page * pitch + metrics.pageHeight - metrics.topMargin
                  const paperHeight = Math.max(0, paperBottom - top)
                  next.push({
                    pos: offset,
                    height: heightGap,
                    paperHeight,
                    bandHeight: metrics.gap,
                    nextTop: metrics.topMargin,
                    pageNumber: page + 1,
                    leftMargin: metrics.leftMargin,
                    rightMargin: metrics.rightMargin,
                  })
                  shift += heightGap
                  page = Math.round(nextStart / pitch)
                  forceBreak = false
                }
                if (node.type.name === 'pageBreak') forceBreak = true
              })

              // 文末分页符：先补出真正的页缝，再补足末页
              if (forceBreak) {
                const boundaryTop = shift + lastRawBottom
                let nextStart = (page + 1) * pitch
                while (nextStart < boundaryTop - 0.5) nextStart += pitch
                const heightGap = nextStart - boundaryTop
                const paperBottom = page * pitch + metrics.pageHeight - metrics.topMargin
                next.push({
                  pos: view.state.doc.content.size,
                  height: heightGap,
                  paperHeight: Math.max(0, paperBottom - boundaryTop),
                  bandHeight: metrics.gap,
                  nextTop: metrics.topMargin,
                  pageNumber: page + 1,
                  leftMargin: metrics.leftMargin,
                  rightMargin: metrics.rightMargin,
                })
                shift += heightGap
                page = Math.round(nextStart / pitch)
                forceBreak = false
              }

              // 末页补足整页高度：纸张高度由设置决定，不随内容多少收缩
              const lastBottom = shift + lastRawBottom
              const desired = page * pitch + metrics.contentHeight
              if (desired - lastBottom > 1) {
                next.push({
                  pos: view.state.doc.content.size,
                  height: desired - lastBottom,
                  paperHeight: desired - lastBottom,
                  bandHeight: 0,
                  nextTop: 0,
                  pageNumber: 0,
                  leftMargin: metrics.leftMargin,
                  rightMargin: metrics.rightMargin,
                })
              }

              options.onPages?.(page + 1)

              if (sameGaps(current, next)) return

              current = next
              const decorations = next.map((spec) =>
                Decoration.widget(spec.pos, () => gapElement(spec), {
                  side: -1,
                  key: `page-gap-${spec.pos}-${Math.round(spec.height)}`,
                  stopEvent: () => true,
                  ignoreSelection: true,
                }),
              )
              view.dispatch(
                view.state.tr.setMeta(key, DecorationSet.create(view.state.doc, decorations)),
              )
            } finally {
              running = false
            }
          }

          const schedule = (delay = 60) => {
            if (timer !== null) window.clearTimeout(timer)
            timer = window.setTimeout(() => {
              timer = null
              measure()
            }, delay)
          }

          // 首次排版在字体加载完成后再测量一次
          requestAnimationFrame(() => schedule(0))
          if (document.fonts?.ready) {
            void document.fonts.ready.then(() => schedule(30))
          }

          const observer = new ResizeObserver(() => schedule(80))
          observer.observe(view.dom)

          const refresh = () => schedule(0)
          editor.storage.pagedDoc.refresh = refresh

          return {
            update(_view, prevState) {
              if (!view.state.doc.eq(prevState.doc)) schedule(70)
            },
            destroy() {
              observer.disconnect()
              if (timer !== null) window.clearTimeout(timer)
            },
          }
        },
      }),
    ]
  },
})
