/**
 * 文本类笔记 → 与网页阅读界面一致的 PDF。
 *
 * 在离屏 iframe 中打开真实的笔记路由，等阅读态渲染完成后用 html2canvas
 * 截取 `.editor-sheet`（标题、正文、自定义块、表格、代码、公式、图片都来自
 * 实际 DOM），再按内容块边界切成多页，避免只导出 Markdown 近似排版。
 */
import html2canvas from 'html2canvas'
import {
  buildImagePdfPages,
  type PdfPageImage,
} from './canvas/canvasRasterExport'

const A4_WIDTH_PT = 595.28
const A4_HEIGHT_PT = 841.89
const A4_RATIO = A4_HEIGHT_PT / A4_WIDTH_PT
const CM_TO_PT = 72 / 2.54
const CAPTURE_SCALE = 2
/** 续页顶部留白，避免正文紧贴纸张边缘。 */
const PAGE_TOP_GAP = 26
/** 单次截图的最大 CSS 高度；过长的笔记分块截图，规避浏览器 canvas 尺寸上限。 */
const MAX_CHUNK_CSS = 3400
const MAX_PAGES = 200
/**
 * html2canvas 绘制文字时的基线比布局盒低 ~9px（中文回退字体 + 正文 line-height）。
 * 切片起点按这段偏移下移，让文字重新对齐布局坐标，避免页尾最后一行被裁掉字尾。
 */
const TEXT_BASELINE_SHIFT = 12
const FRAME_WIDTH = 1500
const FRAME_HEIGHT = 1000
const SHEET_TIMEOUT_MS = 20_000

const IGNORE_SELECTOR = [
  '.code-tools',
  '.code-run-btn',
  '.code-preview-actions',
  '.code-output-actions',
  '.editor-outline',
  '.editor-outline-slot',
  '.editor-meta-bar',
  '.ProseMirror-gapcursor',
].join(',')

const BLOCK_DISPLAYS = new Set([
  'block',
  'flow-root',
  'flex',
  'grid',
  'list-item',
  'table',
  'table-row',
  'table-row-group',
  'table-header-group',
  'table-footer-group',
])

export interface NotePdfSource {
  id: string
  title: string
  kind: string
  /** 上锁笔记在已解锁会话中的令牌，用于 iframe 内加载正文。 */
  unlockToken?: string | null
}

interface PageSize {
  widthPt: number
  heightPt: number
  /** 高 / 宽 */
  ratio: number
}

interface SheetMetrics {
  width: number
  height: number
  page: PageSize
  background: string
  breaks: number[]
  /** 阅读态纸张顶部内边距，决定首页能安全上移多少。 */
  paddingTop: number
  isDocx: boolean
}

interface PagePlan {
  top: number
  bottom: number
  /** 续页顶部留白（CSS px） */
  gap: number
}

interface ChunkPlan {
  top: number
  bottom: number
  pages: PagePlan[]
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下忽略 */
  }
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function hexChannel(value: number): string {
  return Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0')
}

/** 把浏览器计算出的颜色统一成 #rrggbb，透明色按白底合成。 */
function normalizeBackground(color: string): string {
  if (!color || color === 'transparent') return '#ffffff'
  if (/^#[0-9a-f]{6}$/i.test(color)) return color
  const match = /^rgba?\(([^)]+)\)$/i.exec(color)
  if (!match) return '#ffffff'
  const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()))
  const [r = 255, g = 255, b = 255, a = 1] = parts
  const alpha = Number.isFinite(a) ? Math.max(0, Math.min(1, a)) : 1
  return `#${hexChannel(r * alpha + 255 * (1 - alpha))}${hexChannel(
    g * alpha + 255 * (1 - alpha),
  )}${hexChannel(b * alpha + 255 * (1 - alpha))}`
}

function noteUrl(source: NotePdfSource): string {
  const url = new URL(`/notes/${encodeURIComponent(source.id)}`, window.location.origin)
  url.searchParams.set('pdf_export', '1')
  if (source.unlockToken) url.searchParams.set('note_token', source.unlockToken)
  return url.toString()
}

function mountFrame(source: NotePdfSource): Promise<HTMLIFrameElement> {
  return new Promise((resolve, reject) => {
    const frame = document.createElement('iframe')
    frame.title = 'PDF 导出预览'
    frame.setAttribute('aria-hidden', 'true')
    frame.tabIndex = -1
    frame.style.cssText = [
      'position:fixed',
      'left:-20000px',
      'top:0',
      `width:${FRAME_WIDTH}px`,
      `height:${FRAME_HEIGHT}px`,
      'border:0',
      'pointer-events:none',
      'z-index:-1',
    ].join(';')
    const timer = window.setTimeout(() => {
      frame.remove()
      reject(new Error('导出预览加载超时，请重试'))
    }, SHEET_TIMEOUT_MS)
    frame.addEventListener(
      'load',
      () => {
        window.clearTimeout(timer)
        resolve(frame)
      },
      { once: true },
    )
    frame.src = noteUrl(source)
    document.body.appendChild(frame)
  })
}

async function waitForSheet(win: Window, timeoutMs = SHEET_TIMEOUT_MS): Promise<HTMLElement> {
  const doc = win.document
  const started = performance.now()
  while (performance.now() - started < timeoutMs) {
    if (doc.querySelector('#note-lock-password')) {
      throw new Error('笔记已上锁，请先输入密码解锁后再导出')
    }
    const sheet = doc.querySelector<HTMLElement>('.editor-sheet')
    if (sheet?.querySelector('.ProseMirror')) {
      const height = sheet.getBoundingClientRect().height
      await sleep(120)
      if (Math.abs(sheet.getBoundingClientRect().height - height) < 1) return sheet
      continue
    }
    await sleep(80)
  }
  throw new Error('导出预览加载超时，请重试')
}

/** 阅读态才代表用户看到的最终排版；编辑态下自动点一下「阅读」。 */
async function ensureReadMode(win: Window): Promise<void> {
  const doc = win.document
  const editor = doc.querySelector('.kiwi-editor')
  if (!editor || editor.classList.contains('is-readonly')) return
  const button = Array.from(doc.querySelectorAll<HTMLButtonElement>('button')).find(
    (el) => el.textContent?.trim() === '阅读',
  )
  if (!button) return
  button.click()
  const started = performance.now()
  while (performance.now() - started < 4000) {
    if (doc.querySelector('.kiwi-editor.is-readonly .editor-sheet')) return
    await sleep(60)
  }
}

async function waitForAssets(win: Window): Promise<void> {
  const doc = win.document
  try {
    await Promise.race([doc.fonts.ready, sleep(3000)])
  } catch {
    /* 字体接口不可用时继续 */
  }
  const images = Array.from(doc.querySelectorAll<HTMLImageElement>('.editor-sheet img'))
  for (const image of images) image.loading = 'eager'
  await Promise.race([
    Promise.all(
      images.map((image) =>
        image.decode ? image.decode().catch(() => undefined) : Promise.resolve(),
      ),
    ),
    sleep(5000),
  ])
  // 离屏 iframe 里的 rAF 可能被节流甚至不触发，用定时器等待两帧的等效时间。
  await sleep(120)
}

function resolvePageSize(sheet: HTMLElement, isDocx: boolean): PageSize {
  if (isDocx) {
    const widthCm = Number.parseFloat(sheet.style.width)
    const heightCm = Number.parseFloat(sheet.style.minHeight)
    if (Number.isFinite(widthCm) && widthCm > 0 && Number.isFinite(heightCm) && heightCm > 0) {
      return {
        widthPt: widthCm * CM_TO_PT,
        heightPt: heightCm * CM_TO_PT,
        ratio: heightCm / widthCm,
      }
    }
  }
  return { widthPt: A4_WIDTH_PT, heightPt: A4_HEIGHT_PT, ratio: A4_RATIO }
}

/**
 * 收集可以安全切页的位置：取叶子块级元素的底边（含 margin-bottom）。
 * 这样分页优先落在段落、列表项、表格行之间，而不是把一行文字拦腰截断。
 */
function collectBreaks(sheet: HTMLElement): { breaks: number[]; bottom: number } {
  const win = sheet.ownerDocument.defaultView
  if (!win) return { breaks: [], bottom: sheet.getBoundingClientRect().height }
  const sheetTop = sheet.getBoundingClientRect().top
  const breaks = new Set<number>()
  let bottom = 0
  let budget = 20_000

  const visit = (el: Element) => {
    if (budget-- <= 0) return
    if (!(el instanceof win.HTMLElement)) return
    if (el.matches(IGNORE_SELECTOR)) return
    const style = win.getComputedStyle(el)
    if (style.display === 'none' || style.visibility === 'hidden') return
    if (style.position === 'absolute' || style.position === 'fixed') return
    const rect = el.getBoundingClientRect()
    if (rect.width <= 0 && rect.height <= 0) return

    if (BLOCK_DISPLAYS.has(style.display)) {
      let hasBlockChild = false
      for (const child of Array.from(el.children)) {
        if (!(child instanceof win.HTMLElement)) continue
        const childStyle = win.getComputedStyle(child)
        if (
          BLOCK_DISPLAYS.has(childStyle.display) &&
          child.getBoundingClientRect().height > 0
        ) {
          hasBlockChild = true
          break
        }
      }
      if (!hasBlockChild) {
        const margin = Number.parseFloat(style.marginBottom) || 0
        const y = rect.bottom - sheetTop + Math.max(0, margin)
        if (y > 0) {
          breaks.add(round2(y))
          bottom = Math.max(bottom, y)
        }
      }
    }
    for (const child of Array.from(el.children)) visit(child)
  }

  for (const child of Array.from(sheet.children)) visit(child)
  return { breaks: [...breaks].sort((a, b) => a - b), bottom }
}

function measureSheet(sheet: HTMLElement): SheetMetrics {
  const win = sheet.ownerDocument.defaultView
  const rect = sheet.getBoundingClientRect()
  const style = win?.getComputedStyle(sheet)
  const isDocx = !!sheet
    .closest('.kiwi-editor')
    ?.classList.contains('kiwi-editor-docx')
  const page = resolvePageSize(sheet, isDocx)
  const { breaks, bottom } = collectBreaks(sheet)
  const paddingBottom = Number.parseFloat(style?.paddingBottom ?? '') || 0
  const paddingTop = Number.parseFloat(style?.paddingTop ?? '') || 0
  const contentBottom = Math.max(bottom + paddingBottom, paddingTop + 24)
  return {
    width: rect.width,
    // DOCX 纸张的页脚是绝对定位在纸张底部的，必须保留整张纸；
    // 普通阅读态则是 flex 撑满视口，需要裁掉正文下方的空白。
    height: isDocx ? rect.height : Math.min(rect.height, contentBottom),
    page,
    background: normalizeBackground(style?.backgroundColor ?? ''),
    breaks,
    paddingTop,
    isDocx,
  }
}

function planPages(metrics: SheetMetrics): PagePlan[] {
  const pageHeight = metrics.width * metrics.page.ratio
  const plans: PagePlan[] = []
  let top = 0
  let guard = 0

  while (top < metrics.height - 0.5 && guard < MAX_PAGES) {
    guard += 1
    const gap = plans.length ? PAGE_TOP_GAP : 0
    const capacity = Math.max(120, pageHeight - gap)
    const limit = top + capacity
    let bottom = Math.min(metrics.height, limit)
    if (bottom < metrics.height - 0.5) {
      const minBreak = top + capacity * 0.35
      let chosen = 0
      for (const point of metrics.breaks) {
        if (point > minBreak && point <= limit + 0.01 && point > top + 24) chosen = point
      }
      if (chosen > 0) bottom = chosen
    }
    plans.push({ top, bottom, gap })
    top = bottom
  }

  if (top < metrics.height - 0.5) {
    throw new Error('笔记内容过长，请拆分后导出 PDF')
  }
  return plans.length ? plans : [{ top: 0, bottom: metrics.height, gap: 0 }]
}

function chunkPages(pages: PagePlan[]): ChunkPlan[] {
  const chunks: ChunkPlan[] = []
  let current: ChunkPlan | null = null
  for (const page of pages) {
    if (current && page.bottom - current.top > MAX_CHUNK_CSS) {
      chunks.push(current)
      current = null
    }
    if (!current) current = { top: page.top, bottom: page.bottom, pages: [page] }
    else {
      current.bottom = page.bottom
      current.pages.push(page)
    }
  }
  if (current) chunks.push(current)
  return chunks
}

function injectExportStyles(doc: Document): () => void {
  const style = doc.createElement('style')
  style.dataset.kiwiPdfExport = '1'
  style.textContent = `
    ${IGNORE_SELECTOR} { display: none !important; }
    .ProseMirror { caret-color: transparent !important; }
    *, *::before, *::after {
      transition: none !important;
      animation: none !important;
    }
  `
  doc.head.appendChild(style)
  return () => style.remove()
}

async function captureChunk(
  sheet: HTMLElement,
  chunk: ChunkPlan,
  metrics: SheetMetrics,
): Promise<HTMLCanvasElement> {
  const win = sheet.ownerDocument.defaultView
  if (!win) throw new Error('导出预览不可用')
  return html2canvas(sheet, {
    scale: CAPTURE_SCALE,
    x: 0,
    y: chunk.top,
    width: metrics.width,
    height: chunk.bottom - chunk.top,
    windowWidth: win.innerWidth,
    windowHeight: win.innerHeight,
    backgroundColor: metrics.background,
    useCORS: true,
    logging: false,
    imageTimeout: 15_000,
    ignoreElements: (el) => el.matches(IGNORE_SELECTOR),
  })
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('PDF 页面编码失败'))),
      'image/jpeg',
      0.92,
    )
  })
}

function composePage(
  chunkCanvas: HTMLCanvasElement,
  chunk: ChunkPlan,
  plan: PagePlan,
  page: PageSize,
  background: string,
  topShift: number,
): HTMLCanvasElement {
  const width = chunkCanvas.width
  const height = Math.max(1, Math.round(width / page.widthPt * page.heightPt))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('当前浏览器不支持 Canvas 导出')
  ctx.fillStyle = background
  ctx.fillRect(0, 0, width, height)

  // 截图时传入的是 CSS 像素坐标，canvas 上要按实际倍率换算。
  const scale = chunkCanvas.height / (chunk.bottom - chunk.top)
  // html2canvas 把文字画得比布局盒低 topShift，切片起点也相应下移，
  // 让每页的文字重新对齐到布局坐标，页尾不会截断字尾。
  const sourceY = Math.min(
    chunkCanvas.height,
    Math.max(0, (plan.top - chunk.top) * scale + topShift * scale),
  )
  const sourceHeight = Math.min(
    chunkCanvas.height - sourceY,
    (plan.bottom - plan.top) * scale,
  )
  const gap = Math.round(plan.gap * scale)
  const drawHeight = Math.min(sourceHeight, height - gap)
  if (drawHeight > 0) {
    ctx.drawImage(
      chunkCanvas,
      0,
      sourceY,
      width,
      drawHeight,
      0,
      gap,
      width,
      drawHeight,
    )
  }
  return canvas
}

async function capturePageImages(
  sheet: HTMLElement,
  metrics: SheetMetrics,
): Promise<PdfPageImage[]> {
  const chunks = chunkPages(planPages(metrics))
  const images: PdfPageImage[] = []
  for (const chunk of chunks) {
    const chunkCanvas = await captureChunk(sheet, chunk, metrics)
    try {
      for (const plan of chunk.pages) {
        const topShift =
          plan.gap > 0 ? TEXT_BASELINE_SHIFT : Math.min(TEXT_BASELINE_SHIFT, metrics.paddingTop)
        const pageCanvas = composePage(
          chunkCanvas,
          chunk,
          plan,
          metrics.page,
          metrics.background,
          topShift,
        )
        try {
          const blob = await canvasToJpeg(pageCanvas)
          images.push({
            jpeg: new Uint8Array(await blob.arrayBuffer()),
            pixelWidth: pageCanvas.width,
            pixelHeight: pageCanvas.height,
          })
        } finally {
          pageCanvas.width = 0
          pageCanvas.height = 0
        }
      }
    } finally {
      chunkCanvas.width = 0
      chunkCanvas.height = 0
    }
  }
  return images
}

/** 生成与阅读界面一致的 PDF Blob。 */
export async function noteToPdf(source: NotePdfSource): Promise<Blob> {
  const viewKey = `kiwi.note.view.${source.id}`
  const previousView = source.kind === 'link' ? null : safeGet(viewKey)
  if (source.kind !== 'link') safeSet(viewKey, 'read')

  let frame: HTMLIFrameElement | null = null
  let restoreStyles: (() => void) | null = null
  try {
    frame = await mountFrame(source)
    const win = frame.contentWindow
    if (!win) throw new Error('导出预览不可用')
    let sheet = await waitForSheet(win)
    await ensureReadMode(win)
    sheet = await waitForSheet(win)
    await waitForAssets(win)

    // 字体加载或阅读工具栏出现后布局可能再次变化，等高度稳定后再测量。
    const before = sheet.getBoundingClientRect().height
    await sleep(120)
    if (Math.abs(sheet.getBoundingClientRect().height - before) > 1) {
      await sleep(120)
    }

    restoreStyles = injectExportStyles(win.document)
    const metrics = measureSheet(sheet)
    if (metrics.width < 80 || metrics.height < 40) {
      throw new Error('笔记内容为空，无法导出 PDF')
    }
    const pages = await capturePageImages(sheet, metrics)
    return buildImagePdfPages(pages, {
      title: source.title,
      background: metrics.background,
      pageWidth: metrics.page.widthPt,
      pageHeight: metrics.page.heightPt,
    })
  } finally {
    restoreStyles?.()
    frame?.remove()
    if (source.kind !== 'link') safeSet(viewKey, previousView)
  }
}
