<script setup lang="ts">
/**
 * jvs-draw 编辑宿主。
 *
 * - 只在前台 / 编辑态挂载；同一时刻最多一个画布响应全局快捷键。
 * - 通过 getContentObject() 轮询 + 交互事件回写文档，父组件负责防抖保存。
 * - 内部按键事件在输入框 / 文本域内停止冒泡，避免 ProseMirror 误删画布节点；
 *   画布上的 Backspace / Delete / Enter 由扩展的 ProseMirror 插件拦截。
 */
import {
  createApp,
  defineComponent,
  h,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
  type App,
} from 'vue'
import { createPinia, type Pinia } from 'pinia'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  cloneDrawDoc,
  drawDocFingerprint,
  emptyDrawDoc,
  normalizeDrawDoc,
  readDrawPreferences,
  type DrawPreferences,
  type DrawShapeTheme,
  type JvsDrawDoc,
} from './types'
import { loadDrawRuntime, type DrawRuntime } from './drawRuntime'
import {
  drawDocUsesHandFont,
  HAND_FONT_STACK,
  isHandFont,
  loadHandFont,
} from './handFont'
import { acquireDrawTheme, releaseDrawTheme } from './drawTheme'
import { acquireDrawPopperLayer, releaseDrawPopperLayer } from './drawPopperLayer'
import {
  DRAW_THEMES,
  createRandomDrawTheme,
  drawThemePatch,
  type DrawThemePalette,
  type DrawThemableElement,
} from './drawThemes'

const props = withDefaults(
  defineProps<{
    modelValue: JvsDrawDoc
    editable?: boolean
    /** 首次挂载时自动缩放并居中到内容。 */
    autoFit?: boolean
    /** 图片上传：返回可公开访问的 URL。 */
    upload?: (file: File) => Promise<string | { url: string }> | string
  }>(),
  { editable: true, autoFit: true, upload: undefined },
)

const emit = defineEmits<{
  'update:modelValue': [doc: JvsDrawDoc]
  /** 白板运行时挂载完成，可以读取 / 修改偏好设置。 */
  ready: []
}>()

const host = ref<HTMLElement | null>(null)
const mountHost = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref('')
const drawRef = shallowRef<any>(null)
const wandOpen = ref(false)
const wandPanel = ref<HTMLElement | null>(null)
const appliedThemeId = ref('')
const wandMessage = ref('')
const randomPreview = ref<DrawThemePalette | null>(null)

let app: App | null = null
/** 保留画布自己的 Pinia，魔法棒需要直接读 store 才能保留撤销历史。 */
let drawPinia: Pinia | null = null
let runtime: DrawRuntime | null = null
let pollTimer: number | undefined
let checkTimer: number | undefined
let lastFingerprint = ''
let lastDoc: JvsDrawDoc | null = null
let disposed = false
/** 鼠标坐标折算缓存的界面缩放与画布元素（缩放变化时才重新读取）。 */
let pointerScale = 1
let pointerCanvas: HTMLCanvasElement | null = null
let iconObserver: MutationObserver | null = null
let iconObserverTimer: number | undefined
let wandButton: HTMLElement | null = null

function currentDoc(): JvsDrawDoc {
  return cloneDrawDoc(normalizeDrawDoc(props.modelValue) ?? emptyDrawDoc())
}

function readDoc(): JvsDrawDoc | null {
  const instance = drawRef.value
  if (!instance) return null
  try {
    let doc: JvsDrawDoc | null = null
    if (typeof instance.getContentObject === 'function') {
      doc = normalizeDrawDoc(instance.getContentObject())
    }
    if (typeof instance.getCanvasData === 'function') {
      const data = instance.getCanvasData()
      if (doc) {
        // getContentObject 的 viewBackgroundColor 会停留在初始值，
        // getCanvasData 的 appState 才与偏好设置实时同步，这里合并两者。
        doc = normalizeDrawDoc({
          ...doc,
          appState: { ...doc.appState, ...(data?.appState ?? {}) },
          files: doc.files ?? data?.files ?? {},
        })
      } else {
        doc = normalizeDrawDoc({
          ...data,
          type: 'jvs-draw',
          version: 1,
          files: lastDoc?.files ?? {},
        })
      }
    }
    return doc
  } catch {
    /* 渲染中途读取失败时等下一次轮询 */
  }
  return null
}

function check() {
  if (disposed) return
  ensureWandButton()
  if (loading.value) return
  const doc = readDoc()
  if (!doc) return
  const fingerprint = drawDocFingerprint(doc)
  if (fingerprint === lastFingerprint) return
  lastFingerprint = fingerprint
  lastDoc = doc
  emit('update:modelValue', doc)
}

function scheduleCheck(delay = 260) {
  window.clearTimeout(checkTimer)
  checkTimer = window.setTimeout(check, delay)
}

function flush() {
  window.clearTimeout(checkTimer)
  check()
}

function getPreferences(): DrawPreferences {
  const instance = drawRef.value
  let appState: unknown
  try {
    appState = instance?.getCanvasData?.()?.appState
  } catch {
    appState = undefined
  }
  return readDrawPreferences(appState ?? lastDoc?.appState ?? currentDoc().appState)
}

/** 偏好设置写入 appState；normalizeDrawDoc 会保留这些键，随笔记自动保存。 */
/** 形状主题：默认保持平滑描边，经典切换为 Excalidraw 手绘描边。 */
const SHAPE_THEME_ROUGHNESS: Record<DrawShapeTheme, number> = {
  default: 0,
  classic: 2,
}

function isDefaultFont(value: unknown): boolean {
  return typeof value !== 'string' || !value || value === 'sans-serif'
}

function setPreferences(patch: Partial<DrawPreferences>) {
  const instance = drawRef.value
  if (!instance) return
  const appState: Record<string, unknown> = {}
  if (patch.backgroundColor !== undefined) appState.viewBackgroundColor = patch.backgroundColor
  if (patch.gridType !== undefined) appState.gridType = patch.gridType
  if (patch.shapeTheme !== undefined) {
    appState.activeTheme = patch.shapeTheme
    // 新建图形 / 文字取 currentItem*；activeTheme 里只有填充 / 颜色，没有手绘抖动和字体。
    appState.currentItemRoughness = SHAPE_THEME_ROUGHNESS[patch.shapeTheme]
    appState.currentItemFontFamily =
      patch.shapeTheme === 'classic' ? HAND_FONT_STACK : 'sans-serif'
  }
  if (patch.wheelZoom !== undefined) appState.useWheelZoom = patch.wheelZoom
  if (patch.rightClickPan !== undefined) appState.rightClickPan = patch.rightClickPan
  if (patch.quickCreate !== undefined) appState.showQuickCreate = patch.quickCreate
  if (patch.showSize !== undefined) appState.showElementSize = patch.showSize
  try {
    instance.setCanvasData?.({ appState })
  } catch {
    return
  }
  if (patch.shapeTheme !== undefined) void applyShapeStyle(patch.shapeTheme)
  scheduleCheck(0)
}

/** 主题切换可能等待字体加载；用序号丢弃中途切回默认的旧任务。 */
let shapeStyleToken = 0

/**
 * 切换形状主题时把已有图形 / 文字一起改掉，否则设置面板看起来毫无变化。
 * 只改描边抖动和字体（不改颜色 / 填充 / 圆角），并记入撤销历史。
 */
async function applyShapeStyle(theme: DrawShapeTheme) {
  const token = ++shapeStyleToken
  // 手绘字体是随应用分发的本地字体，先等它就绪再改文字，避免画布按回退字体排版。
  if (theme === 'classic') await loadHandFont()
  if (token !== shapeStyleToken || disposed) return

  const roughness = SHAPE_THEME_ROUGHNESS[theme]
  const elements = canvasElements()
  const SKIP = new Set(['image', 'frame', 'embeddable', 'freedraw'])
  const updates: Array<{ id: string; patch: Record<string, unknown> }> = []

  for (const element of elements) {
    if (element.isDeleted || typeof element.id !== 'string') continue

    if (element.type === 'text') {
      const current = element.fontFamily
      if (current === 'iconfont') continue
      const wanted =
        theme === 'classic' && isDefaultFont(current)
          ? HAND_FONT_STACK
          : theme === 'default' && isHandFont(current)
            ? 'sans-serif'
            : null
      if (wanted) updates.push({ id: element.id, patch: { fontFamily: wanted } })
      continue
    }

    if (SKIP.has(element.type ?? '')) continue
    if (element.roughness !== roughness) {
      updates.push({ id: element.id, patch: { roughness } })
    }
  }

  if (!updates.length) return

  const store = drawStore()
  if (store && typeof store.recordHistory === 'function' && typeof store.updateElement === 'function') {
    try {
      store.recordHistory()
      for (const { id, patch } of updates) {
        store.updateElement(id, patch)
      }
      return
    } catch {
      /* Pinia 尚未就绪时退回实例接口 */
    }
  }
  const patches = new Map(updates.map(({ id, patch }) => [id, patch]))
  const next = elements.map((element) => {
    const patch = patches.get(element.id ?? '')
    return patch ? { ...element, ...patch } : element
  })
  try {
    drawRef.value?.setCanvasData?.({ elements: next })
  } catch {
    /* 画布尚未就绪时忽略 */
  }
}

/**
 * jvs-draw 的图标是内联 SVG sprite，选中态图标把填充色写死成蓝色 / 深灰，
 * <use> 影子树里的 presentation attribute 无法用 CSS 覆盖。挂载后把这些
 * 填充改成 currentColor，按钮选中时图标就会跟随 Kiwi 的系统主题色。
 *
 * 主工具栏与「素材库」来自两段 sprite（后者由 iconfont.js 后注入），
 * 这里支持只处理新插入的 symbol，避免反复扫描整页。
 */
function themeDrawIcons(root: ParentNode = document) {
  const symbols =
    root instanceof Element && root.tagName.toLowerCase() === 'symbol'
      ? [root as SVGSymbolElement]
      : Array.from(root.querySelectorAll?.<SVGSymbolElement>('symbol') ?? [])
  for (const symbol of symbols) {
    const selected = symbol.id.includes('xuanzhong')
    for (const path of symbol.querySelectorAll<SVGPathElement>('path')) {
      const fill = (path.getAttribute('fill') || '').toUpperCase()
      if (!fill) continue
      if (selected) {
        if (fill === '#1E6FFF' || fill === '#363B4C') {
          path.setAttribute('fill', 'currentColor')
        } else if (fill === '#8EB7FF') {
          path.setAttribute('fill', 'currentColor')
          path.setAttribute('fill-opacity', '0.45')
        }
      } else if (symbol.id.startsWith('icon-') && fill === '#363B4C') {
        path.setAttribute('fill', 'currentColor')
      }
    }
  }
}

/** 图标 sprite 由 jvs-draw 与 iconfont.js 先后注入，持续给新增的部分改色。 */
function themeDrawIconsWhenReady() {
  themeDrawIcons()
  iconObserver?.disconnect()
  iconObserver = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue
        if (node.tagName.toLowerCase() === 'symbol' || node.querySelector('symbol')) {
          themeDrawIcons(node)
        }
      }
    }
  })
  iconObserver.observe(document.documentElement, { childList: true, subtree: true })
  window.clearTimeout(iconObserverTimer)
  iconObserverTimer = window.setTimeout(() => {
    iconObserver?.disconnect()
    iconObserver = null
  }, 8000)
}

function readUiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function syncPointerScale() {
  pointerScale = readUiScale()
}

function canvasForPointer(): HTMLCanvasElement | null {
  if (pointerCanvas?.isConnected) return pointerCanvas
  pointerCanvas = host.value?.querySelector('canvas') ?? null
  return pointerCanvas
}

/**
 * Kiwi 用 CSS zoom 缩放界面，而 Excalidraw 直接拿 clientX/clientY 当场景坐标，
 * 界面放大 S 倍后指针位置也被放大 S 倍（鼠标在左上、图形落在右下）。在宿主捕获
 * 阶段把坐标按 1/S 折算回未缩放坐标，绘制、选中、平移与滚轮缩放锚点一起对齐。
 */
function onPointerCoordinateCapture(event: MouseEvent) {
  if (event.type === 'pointerdown' || event.type === 'mousedown' || event.type === 'wheel') {
    syncPointerScale()
  }
  if (pointerScale === 1) return
  const canvas = canvasForPointer()
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  if (!rect.width) return
  try {
    Object.defineProperty(event, 'clientX', {
      configurable: true,
      value: rect.left + (event.clientX - rect.left) / pointerScale,
    })
    Object.defineProperty(event, 'clientY', {
      configurable: true,
      value: rect.top + (event.clientY - rect.top) / pointerScale,
    })
  } catch {
    /* 个别环境不允许覆写只读属性时保持原坐标 */
  }
}

const COORDINATE_EVENTS = [
  'pointerdown',
  'pointermove',
  'pointerup',
  'pointercancel',
  'mousedown',
  'mousemove',
  'mouseup',
  'click',
  'dblclick',
  'contextmenu',
  'wheel',
] as const

function bindPointerRemap() {
  const element = host.value
  if (!element) return
  syncPointerScale()
  for (const type of COORDINATE_EVENTS) {
    element.addEventListener(type, onPointerCoordinateCapture as EventListener, true)
  }
  window.addEventListener('resize', syncPointerScale)
}

function unbindPointerRemap() {
  const element = host.value
  if (!element) return
  for (const type of COORDINATE_EVENTS) {
    element.removeEventListener(type, onPointerCoordinateCapture as EventListener, true)
  }
  window.removeEventListener('resize', syncPointerScale)
}

function unmountApp() {
  window.clearInterval(pollTimer)
  pollTimer = undefined
  setWandOpen(false)
  wandButton = null
  if (app) {
    try {
      app.unmount()
    } catch {
      /* 忽略重复卸载 */
    }
    app = null
  }
  drawRef.value = null
  runtime = null
  mountHost.value?.replaceChildren()
}

async function mount() {
  if (disposed) return
  unmountApp()
  loading.value = true
  error.value = ''
  try {
    runtime = await loadDrawRuntime()
    await nextTick()
    if (disposed || !mountHost.value) return

    const initial = currentDoc()
    lastDoc = initial
    lastFingerprint = drawDocFingerprint(initial)
    // 画布用 canvas 绘制文字，字体未加载时不会自动重排，先等内置手写体就绪。
    if (drawDocUsesHandFont(initial)) await loadHandFont()
    if (disposed) return
    const mountEl = document.createElement('div')
    mountEl.className = 'kiwi-draw-mount'
    mountHost.value.replaceChildren(mountEl)
    const drawRuntime = runtime
    const editable = props.editable
    const upload = props.upload

    const Root = defineComponent({
      name: 'KiwiDrawRuntime',
      setup() {
        return () =>
          h(drawRuntime.JvsDraw, {
            ref: (instance: any) => {
              drawRef.value = instance
            },
            initialData: initial,
            loadFromLocal: false,
            autoFit: props.autoFit,
            editable,
            config: {
              language: 'zh-CN',
              enableImageUpload: !!upload,
              uploadImageFn: upload
                ? async (file: File) => {
                    const result = await upload(file)
                    return typeof result === 'string' ? result : result.url
                  }
                : undefined,
              showSaveBtn: false,
            },
            showAI: false,
            showAi: false,
            // 模板库与信息图都是 jvs-draw 内置的本地能力（模板随包分发，
            // 信息图用 DSL 在浏览器内排版），不需要额外的后端或 AI 服务。
            showTemplate: true,
            showInfographic: true,
            showWatermark: false,
            showOpenSource: false,
            showTechSupport: false,
            showExport: false,
            showImportPPTX: false,
            showImportData: false,
            showImportAIData: false,
            showBoardName: false,
            // 保留官方右下角的抓手 / 小地图 / 缩放 / 清空画布工具条。
            showFooter: true,
            showLanguageMenu: false,
            showSaveBtn: false,
            showSearch: true,
            // 快捷键与偏好设置统一收进 Kiwi 自己的界面。
            showShortcuts: false,
            showPreferences: false,
            showShapeLibrary: true,
            showMinimap: true,
            showPropertiesPanel: true,
            showToolbar: true,
            showGlobalSettings: false,
          })
      },
    })

    app = createApp(Root)
    drawPinia = createPinia()
    app.use(drawPinia)
    app.use(drawRuntime.ElementPlus)
    app.config.errorHandler = (err) => {
      console.error('[kiwi-draw]', err)
      error.value = err instanceof Error ? err.message : String(err)
    }
    app.mount(mountEl)
    loading.value = false
    await nextTick()
    if (disposed) {
      unmountApp()
      return
    }
    themeDrawIconsWhenReady()
    ensureWandButton()
    emit('ready')
    window.clearInterval(pollTimer)
    pollTimer = window.setInterval(check, 900)
  } catch (e: any) {
    loading.value = false
    error.value = e?.message || '画布组件加载失败'
    unmountApp()
  }
}

function retry() {
  void mount()
}

function focus() {
  const canvas = host.value?.querySelector('canvas')
  if (canvas instanceof HTMLElement) {
    canvas.scrollIntoView({ block: 'nearest' })
    canvas.focus()
  }
}

/** 模板库 / 信息图对话框由 jvs-draw 内部维护，点击它自己的入口即可打开。 */
function openTemplates() {
  host.value
    ?.querySelector<HTMLElement>('.top-right-actions .template-btn[title="模板库"]')
    ?.click()
}

function openInfographic() {
  host.value
    ?.querySelector<HTMLElement>('.top-right-actions .template-btn[title="信息图"]')
    ?.click()
}

function drawStore(): any {
  try {
    const stores = (drawPinia as any)?._s
    if (!stores) return null
    // JvsDraw 会 provide 一个随机的 instance id，store 名不一定是 "excalidraw"；
    // 按能力识别画布 store，避免依赖内部 id。
    const direct = stores.get?.('excalidraw')
    if (direct) return direct
    for (const store of stores.values?.() ?? []) {
      if (Array.isArray(store?.elements) && typeof store.recordHistory === 'function') {
        return store
      }
    }
  } catch {
    /* Pinia 尚未注册时回退到实例接口 */
  }
  return null
}

function canvasElements(): DrawThemableElement[] {
  const elements = drawStore()?.elements
  if (Array.isArray(elements)) return elements
  try {
    const data = drawRef.value?.getCanvasData?.()
    if (Array.isArray(data?.elements)) return data.elements
  } catch {
    /* 实例尚未就绪时回退到最近一次轮询结果 */
  }
  return Array.isArray(lastDoc?.elements) ? lastDoc.elements : []
}

/**
 * 整张画布统一换色。
 *
 * 直接走 store 的 recordHistory + updateElement：一次记录历史快照，
 * 逐元素改色仍可被画布自己的 Ctrl/⌘+Z 整体撤销。实例接口不可用时
 * 才退回 setCanvasData（会重置画布历史）。
 */
function applyDrawTheme(theme: DrawThemePalette) {
  const elements = canvasElements()
  if (!elements.length) {
    wandMessage.value = '当前画布还没有可配色的图形'
    return
  }
  const updates: Array<{ id: string; patch: Record<string, string> }> = []
  for (const element of elements) {
    const patch = drawThemePatch(element, theme)
    if (patch && typeof element.id === 'string') updates.push({ id: element.id, patch })
  }
  if (!updates.length) {
    wandMessage.value = '当前画布已经是这套配色'
    return
  }

  const store = drawStore()
  let applied = false
  if (store && typeof store.recordHistory === 'function' && typeof store.updateElement === 'function') {
    try {
      store.recordHistory()
      for (const { id, patch } of updates) store.updateElement(id, patch)
      applied = true
    } catch {
      applied = false
    }
  }
  if (!applied) {
    const patches = new Map(updates.map(({ id, patch }) => [id, patch]))
    const next = elements.map((element) => {
      const patch = patches.get(element.id ?? '')
      return patch ? { ...element, ...patch } : element
    })
    try {
      drawRef.value?.setCanvasData?.({ elements: next })
      applied = true
    } catch {
      applied = false
    }
  }
  if (!applied) {
    wandMessage.value = '应用失败，请稍后再试'
    return
  }
  appliedThemeId.value = theme.id
  wandMessage.value = `已应用 · ${theme.name}`
  scheduleCheck(0)
}

function applyRandomDrawTheme() {
  const theme = createRandomDrawTheme()
  randomPreview.value = theme
  applyDrawTheme(theme)
}

function onWandOutside(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Node)) return
  if (wandPanel.value?.contains(target) || wandButton?.contains(target)) return
  setWandOpen(false)
}

function onWandKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.stopPropagation()
  setWandOpen(false)
}

/** 面板贴着工具栏底部的魔法棒按钮展开，避免和按钮隔着一整条工具栏。 */
function positionWandPanel() {
  const hostEl = host.value
  const panel = wandPanel.value
  const button = wandButton
  if (!hostEl || !panel || !button) return
  const scale = readUiScale()
  const hostRect = hostEl.getBoundingClientRect()
  const buttonRect = button.getBoundingClientRect()
  const panelHeight = panel.offsetHeight
  const buttonCenter = (buttonRect.top + buttonRect.height / 2 - hostRect.top) / scale
  const maxTop = Math.max(8, hostEl.clientHeight - panelHeight - 8)
  const top = Math.min(Math.max(8, buttonCenter - panelHeight / 2), maxTop)
  panel.style.top = `${top}px`
  panel.style.transform = 'none'
}

function setWandOpen(open: boolean) {
  wandOpen.value = open
  wandButton?.classList.toggle('active', open)
  document.removeEventListener('pointerdown', onWandOutside, true)
  document.removeEventListener('keydown', onWandKeydown, true)
  window.removeEventListener('resize', positionWandPanel)
  if (open) {
    wandMessage.value = ''
    // 等本次点击结束再监听，否则打开按钮自己的 pointerdown 会立即关闭面板。
    window.setTimeout(() => {
      if (!wandOpen.value) return
      document.addEventListener('pointerdown', onWandOutside, true)
      document.addEventListener('keydown', onWandKeydown, true)
    }, 0)
    window.addEventListener('resize', positionWandPanel)
    void nextTick(() => {
      positionWandPanel()
      window.requestAnimationFrame(positionWandPanel)
    })
  }
}

watch(wandMessage, () => {
  if (!wandOpen.value) return
  void nextTick(positionWandPanel)
})

const WAND_ICON = `
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M4.4 19.1 13.9 9.6l2.1 2.1L6.5 21.2a1.5 1.5 0 0 1-2.1-2.1Z" />
    <path d="m15.3 8.2 1.1-1.1 2.1 2.1-1.1 1.1Z" />
    <path d="M19 2.4 20 4.6l2.2 1L20 6.6 19 8.8l-1-2.2-2.2-1L18 4.6Z" />
    <path d="M7.4 2.4 8.2 4.1l1.7.8-1.7.8-.8 1.7-.8-1.7-1.7-.8 1.7-.8Z" />
    <path d="m20.2 11.4.6 1.3 1.3.6-1.3.6-.6 1.3-.6-1.3-1.3-.6 1.3-.6Z" />
  </svg>
`

/** jvs-draw 没有插件式工具栏 API，把自己的入口追加到工具栏最后一组。 */
function ensureWandButton() {
  if (disposed || !props.editable) return
  const group = host.value?.querySelector<HTMLElement>('.toolbar .tool-group')
  if (!group) return
  const existing = group.querySelector<HTMLElement>('.kiwi-draw-wand')
  if (existing) {
    wandButton = existing
    existing.classList.toggle('active', wandOpen.value)
    return
  }

  const wrap = document.createElement('div')
  wrap.className = 'kiwi-draw-wand-wrap'

  const divider = document.createElement('div')
  divider.className = 'tool-item trand-line kiwi-draw-wand-divider'

  const button = document.createElement('div')
  button.className = 'tool-item kiwi-draw-wand'
  button.title = '魔法棒：一键统一画布配色'
  button.setAttribute('role', 'button')
  button.setAttribute('tabindex', '0')
  button.setAttribute('aria-label', '魔法棒：一键统一画布配色')
  button.innerHTML = WAND_ICON
  button.addEventListener('click', (event) => {
    event.stopPropagation()
    setWandOpen(!wandOpen.value)
  })
  button.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    event.stopPropagation()
    setWandOpen(!wandOpen.value)
  })

  wrap.append(divider, button)
  group.append(wrap)
  wandButton = button
  button.classList.toggle('active', wandOpen.value)
}

/** 打开 jvs-draw 的画布搜索；系统 Ctrl/⌘+F 在画布笔记里统一走这里。 */
function openSearch() {
  const hostEl = host.value
  if (!hostEl) return
  const group = hostEl.querySelector<HTMLElement>('.action-group')
  if (group && !group.classList.contains('is-searching')) {
    hostEl.querySelector<HTMLElement>('.search-toggle')?.click()
  }
  window.setTimeout(() => {
    const input = hostEl.querySelector<HTMLInputElement>('.search-input-wrapper input')
    if (input) {
      input.focus()
      input.select()
    }
  }, 50)
}

function isTextTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    target.isContentEditable ||
    !!target.closest('[contenteditable="true"]')
  )
}

/** 输入框内的按键 / 粘贴只交给原生控件，不再冒泡到 ProseMirror。 */
function onKeyDownCapture(event: KeyboardEvent) {
  if (isTextTarget(event.target)) event.stopPropagation()
}

/**
 * 画布内的鼠标按下不能再冒泡到 ProseMirror。
 *
 * 否则点击画布会先选中画布原子块并让编辑器抢走焦点，随后 jvs-draw 创建的
 * 文本输入框立即失焦，键盘输入落回正文并替换掉整个画布块。
 * 用冒泡阶段拦截（而非捕获），保证画布自身的处理器先执行。
 */
function onMouseDown(event: MouseEvent) {
  event.stopPropagation()
}

function onPasteCapture(event: ClipboardEvent) {
  if (isTextTarget(event.target)) event.stopPropagation()
}

watch(
  () => props.editable,
  (editable) => {
    try {
      drawRef.value?.setConfig?.({ editable })
    } catch {
      /* 实例尚未就绪时忽略 */
    }
    if (!editable) {
      setWandOpen(false)
      wandButton?.closest('.kiwi-draw-wand-wrap')?.remove()
      wandButton = null
    } else {
      ensureWandButton()
    }
  },
)

onMounted(() => {
  acquireDrawTheme()
  acquireDrawPopperLayer()
  bindPointerRemap()
  void mount()
})

onBeforeUnmount(() => {
  // 先 flush 再标记 disposed：check() 在 disposed 后会直接返回。
  flush()
  disposed = true
  unbindPointerRemap()
  iconObserver?.disconnect()
  iconObserver = null
  window.clearTimeout(iconObserverTimer)
  unmountApp()
  pointerCanvas = null
  releaseDrawTheme()
  releaseDrawPopperLayer()
})

defineExpose({
  flush,
  focus,
  getDoc: () => lastDoc ?? currentDoc(),
  getRuntime: () => drawRef.value,
  getPreferences,
  setPreferences,
  openSearch,
  openTemplates,
  openInfographic,
  retry,
})
</script>

<template>
  <div
    ref="host"
    class="kiwi-draw-editor"
    :class="{ 'is-loading': loading, 'is-error': !!error }"
    @keydown.capture="onKeyDownCapture"
    @paste.capture="onPasteCapture"
    @mousedown="onMouseDown"
    @pointerup="scheduleCheck()"
    @keyup="scheduleCheck()"
    @focusout="scheduleCheck(400)"
  >
    <div ref="mountHost" class="kiwi-draw-surface" />
    <div v-if="loading" class="kiwi-draw-status">
      <KiwiIcon name="loader" :size="18" spin />
      <span>正在加载画布…</span>
    </div>
    <div v-else-if="error" class="kiwi-draw-status is-error">
      <KiwiIcon name="alert" :size="18" />
      <span class="max-w-[360px] text-center">{{ error }}</span>
      <button type="button" class="kiwi-draw-retry" @click="retry">重新加载</button>
    </div>

    <Transition name="kiwi-wand">
      <div
        v-if="wandOpen"
        ref="wandPanel"
        class="kiwi-draw-wand-panel"
        role="dialog"
        aria-label="魔法棒配色"
      >
        <div class="kiwi-wand-head">
          <div class="min-w-0">
            <div class="kiwi-wand-title">
              <KiwiIcon name="sparkle" :size="15" />
              <span>魔法棒</span>
            </div>
            <p class="kiwi-wand-sub">一键统一当前画布的配色</p>
          </div>
          <button
            type="button"
            class="kiwi-wand-close"
            title="关闭"
            aria-label="关闭魔法棒"
            @mousedown.prevent
            @click="setWandOpen(false)"
          >
            <KiwiIcon name="close" :size="13" />
          </button>
        </div>

        <p class="kiwi-wand-section">同色系主题</p>
        <div class="kiwi-wand-grid">
          <button
            v-for="theme in DRAW_THEMES"
            :key="theme.id"
            type="button"
            class="kiwi-wand-theme"
            :class="{ 'is-active': appliedThemeId === theme.id }"
            :title="`应用「${theme.name}」配色`"
            :aria-pressed="appliedThemeId === theme.id"
            @mousedown.prevent
            @click="applyDrawTheme(theme)"
          >
            <span class="kiwi-wand-swatches">
              <span :style="{ background: theme.stroke }" />
              <span :style="{ background: theme.accent }" />
              <span :style="{ background: theme.fill, borderColor: theme.stroke + '33' }" />
            </span>
            <span class="kiwi-wand-meta">
              <span class="kiwi-wand-name">{{ theme.name }}</span>
              <span v-if="appliedThemeId === theme.id" class="kiwi-wand-check">
                <KiwiIcon name="check" :size="12" />
              </span>
            </span>
          </button>
        </div>

        <button
          type="button"
          class="kiwi-wand-random"
          title="按随机色相现场生成一套新配色"
          @mousedown.prevent
          @click="applyRandomDrawTheme"
        >
          <KiwiIcon name="sparkle" :size="14" />
          <span>随机主题</span>
          <span v-if="randomPreview" class="kiwi-wand-random-swatches" aria-hidden="true">
            <span :style="{ background: randomPreview.stroke }" />
            <span :style="{ background: randomPreview.accent }" />
            <span :style="{ background: randomPreview.fill }" />
          </span>
        </button>

        <p v-if="wandMessage" class="kiwi-wand-message">{{ wandMessage }}</p>
        <p class="kiwi-wand-hint">
          只调整图形、连线与文字颜色；图片和透明填充保持不变。应用后可用 Ctrl/⌘+Z 撤销。
        </p>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.kiwi-draw-editor {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 360px;
  overflow: hidden;
  background: #fff;
}
.kiwi-draw-surface {
  width: 100%;
  height: 100%;
}
.kiwi-draw-editor :deep(.kiwi-draw-mount) {
  width: 100%;
  height: 100%;
}
/* jvs-draw 在容器上声明自己的配色变量，这里覆盖为 Kiwi 主题色与浅色面板。 */
.kiwi-draw-editor :deep(.jvs-draw-container) {
  --color-primary: rgb(var(--kiwi-600));
  --color-primary-light: rgb(var(--kiwi-100));
  --color-bg-canvas: rgb(248 250 252);
  --color-bg-panel: rgb(255 255 255 / 0.92);
  --color-border: rgb(226 232 240);
  --color-text: rgb(30 41 59);
  --color-text-muted: rgb(148 163 184);
}
/* 画布搜索统一从系统 Ctrl/⌘+F 进入，工具栏不再保留重复入口。
   整组一起隐藏，否则 group 自身的白底与阴影会留下一个空的小竖条。 */
.kiwi-draw-editor :deep(.top-right-actions .action-group:not(.is-searching)) {
  display: none;
}
/* 模板库 / 信息图的入口统一放到画布标题栏，画布内不再重复展示。 */
.kiwi-draw-editor :deep(.top-right-actions .template-btn) {
  display: none;
}
.kiwi-draw-editor :deep(.toolbar) {
  /* 低于右键菜单（z-80），画布工具栏只压在画布上，不能盖住笔记的浮层。 */
  z-index: 30;
  border: 1px solid rgb(226 232 240 / 0.9);
  border-radius: 12px;
  box-shadow: 0 10px 30px rgb(15 23 42 / 0.08);
}
.kiwi-draw-editor :deep(.tool-group .tool-item) {
  border-radius: 8px;
}
.kiwi-draw-editor :deep(.kiwi-draw-wand-wrap) {
  display: contents;
}
.kiwi-draw-editor :deep(.kiwi-draw-wand) {
  display: flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  color: rgb(54 59 76);
  cursor: pointer;
  outline: none;
}
.kiwi-draw-editor :deep(.kiwi-draw-wand:focus-visible) {
  box-shadow: 0 0 0 2px rgb(var(--kiwi-300));
}
.kiwi-draw-editor :deep(.kiwi-draw-wand svg) {
  width: 20px;
  height: 20px;
}
/* 与 jvs-draw 原生 .trand-line 保持一致；注入元素拿不到它的 scoped 样式。 */
.kiwi-draw-editor :deep(.kiwi-draw-wand-divider) {
  width: 36px;
  height: 1px;
  flex-shrink: 0;
  background: #e4e7eb;
  cursor: default;
}
.kiwi-draw-editor :deep(.tool-group .tool-item.kiwi-draw-wand-divider:hover) {
  background: #e4e7eb;
}
.kiwi-draw-editor :deep(.tool-group .tool-item:hover) {
  background: rgb(var(--kiwi-50));
}
.kiwi-draw-editor :deep(.tool-group .active),
.kiwi-draw-editor :deep(.tool-group .active:hover) {
  background: rgb(var(--kiwi-600) / 0.12);
  color: rgb(var(--kiwi-600));
}
/* 右下角官方工具条：保留功能，样式与左侧工具栏、Kiwi 主题保持一致。 */
.kiwi-draw-editor :deep(.footer-controls) {
  z-index: 30;
}
.kiwi-draw-editor :deep(.footer-controls .tool-item) {
  border-radius: 6px;
  color: rgb(54 59 76);
}
.kiwi-draw-editor :deep(.footer-controls .tool-item:hover) {
  background: rgb(var(--kiwi-50));
}
.kiwi-draw-editor :deep(.footer-controls .active),
.kiwi-draw-editor :deep(.footer-controls .active:hover) {
  background: rgb(var(--kiwi-600) / 0.12) !important;
  color: rgb(var(--kiwi-600));
}
.kiwi-draw-editor :deep(.footer-controls .separator) {
  background: rgb(226 232 240);
}
.kiwi-draw-wand-panel {
  position: absolute;
  top: 50%;
  left: 92px;
  z-index: 40;
  width: min(280px, calc(100% - 108px));
  max-height: calc(100% - 32px);
  overflow-y: auto;
  padding: 14px;
  border: 1px solid rgb(226 232 240);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 24px 60px -20px rgb(15 23 42 / 0.35);
  transform: translateY(-50%);
}
.kiwi-wand-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
.kiwi-wand-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: rgb(51 65 85);
  font-size: 12.5px;
  font-weight: 600;
}
.kiwi-wand-title :deep(svg) {
  color: rgb(var(--kiwi-600));
}
.kiwi-wand-sub {
  margin: 3px 0 0;
  color: rgb(148 163 184);
  font-size: 10px;
  line-height: 1.5;
}
.kiwi-wand-close {
  display: inline-flex;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: rgb(148 163 184);
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-wand-close:hover {
  background: rgb(241 245 249);
  color: rgb(51 65 85);
}
.kiwi-wand-section {
  margin: 0 0 7px;
  color: rgb(148 163 184);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
}
.kiwi-wand-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.kiwi-wand-theme {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 9px;
  border: 1px solid rgb(226 232 240 / 0.9);
  border-radius: 10px;
  background: #fff;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.kiwi-wand-theme:hover {
  border-color: rgb(var(--kiwi-300));
  background: rgb(var(--kiwi-50) / 0.6);
}
.kiwi-wand-theme.is-active {
  border-color: rgb(var(--kiwi-200));
  background: rgb(var(--kiwi-50) / 0.8);
}
.kiwi-wand-swatches {
  display: flex;
  gap: 3px;
  height: 11px;
}
.kiwi-wand-swatches > span {
  flex: 1;
  border: 1px solid rgb(15 23 42 / 0.06);
  border-radius: 3px;
}
.kiwi-wand-meta {
  display: flex;
  min-height: 14px;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}
.kiwi-wand-name {
  color: rgb(51 65 85);
  font-size: 12px;
  line-height: 1;
}
.kiwi-wand-theme.is-active .kiwi-wand-name {
  color: rgb(var(--kiwi-700));
  font-weight: 500;
}
.kiwi-wand-check {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  color: rgb(var(--kiwi-600));
}
.kiwi-wand-random {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px dashed rgb(var(--kiwi-300));
  border-radius: 10px;
  background: rgb(var(--kiwi-50) / 0.55);
  color: rgb(var(--kiwi-700));
  font-size: 12px;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.kiwi-wand-random:hover {
  border-color: rgb(var(--kiwi-400));
  background: rgb(var(--kiwi-50));
}
.kiwi-wand-random-swatches {
  display: inline-flex;
  gap: 2px;
  margin-left: 3px;
}
.kiwi-wand-random-swatches > span {
  width: 8px;
  height: 8px;
  border: 1px solid rgb(15 23 42 / 0.08);
  border-radius: 2px;
}
.kiwi-wand-message {
  margin: 10px 0 0;
  color: rgb(var(--kiwi-700));
  font-size: 11px;
  line-height: 1.5;
}
.kiwi-wand-hint {
  margin: 10px 0 0;
  color: rgb(148 163 184);
  font-size: 10.5px;
  line-height: 1.6;
}
.kiwi-wand-enter-active,
.kiwi-wand-leave-active {
  transition: opacity 0.14s ease, scale 0.14s ease;
}
.kiwi-wand-enter-from,
.kiwi-wand-leave-to {
  opacity: 0;
  scale: 0.97;
}
.kiwi-draw-status {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgb(248 250 252);
  color: rgb(100 116 139);
  font-size: 12px;
}
.kiwi-draw-status.is-error {
  color: rgb(185 28 28);
  background: rgb(254 242 242);
}
.kiwi-draw-retry {
  padding: 4px 12px;
  border: 1px solid rgb(254 202 202);
  border-radius: 6px;
  background: #fff;
  color: rgb(185 28 28);
  font-size: 12px;
}
.kiwi-draw-retry:hover {
  background: rgb(254 226 226);
}
</style>

<style>
/* 弹层 teleport 到 body，只能在 body 主题类上覆盖 Element Plus 变量。 */
html.kiwi-draw-theme {
  --el-color-primary: rgb(var(--kiwi-600));
  --el-color-primary-light-3: rgb(var(--kiwi-400));
  --el-color-primary-light-5: rgb(var(--kiwi-300));
  --el-color-primary-light-7: rgb(var(--kiwi-200));
  --el-color-primary-light-8: rgb(var(--kiwi-100));
  --el-color-primary-light-9: rgb(var(--kiwi-50));
  --el-color-primary-dark-2: rgb(var(--kiwi-700));
  --el-font-family: inherit;
  --el-border-radius-base: 8px;
  --el-border-radius-small: 6px;
}
/* 形状库 / 取色器等弹层同样是 teleport 渲染，把硬编码的蓝色选中态改成主题色。 */
html.kiwi-draw-theme .more-shapes-btn {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-600) / 0.08);
}
html.kiwi-draw-theme .more-shapes-btn:hover {
  background: rgb(var(--kiwi-600) / 0.15);
}
html.kiwi-draw-theme .shape-library-drawer .shape-grid .shape-item:hover {
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-600));
  border-color: rgb(var(--kiwi-300));
}
html.kiwi-draw-theme .shape-library-drawer .shape-grid .shape-item.is-selected {
  background: rgb(var(--kiwi-600) / 0.1);
  color: rgb(var(--kiwi-600));
  border-color: rgb(var(--kiwi-600));
}
html.kiwi-draw-theme .shape-library-drawer .drawer-header .tabs .tab.active,
html.kiwi-draw-theme .category-item.active,
html.kiwi-draw-theme .color-format-popover .active,
html.kiwi-draw-theme .gradual-popover .active,
html.kiwi-draw-theme .color-picker-selector .color-picker-selector-box .color-type-active {
  color: rgb(var(--kiwi-600));
}
html.kiwi-draw-theme .category-item.active,
html.kiwi-draw-theme .color-format-popover .active,
html.kiwi-draw-theme .gradual-popover .active {
  background: rgb(var(--kiwi-50));
}
html.kiwi-draw-theme .shape-library-drawer .drawer-header .tabs .tab.active::after {
  background: rgb(var(--kiwi-600));
}
html.kiwi-draw-theme .shape-library-drawer .drawer-search .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-600)) inset;
}
html.kiwi-draw-theme .preferences-list .active {
  background: rgb(var(--kiwi-100)) !important;
  color: rgb(var(--kiwi-600));
}
html.kiwi-draw-theme .settings-btn.active,
html.kiwi-draw-theme .sub-tools-container .sub-tool-item.active,
html.kiwi-draw-theme .overflow-tools .overflow-tool-item.active,
html.kiwi-draw-theme .popover-content .arrow-point-item.active {
  background: rgb(var(--kiwi-600) / 0.12);
  color: rgb(var(--kiwi-600));
}
/* 模板库 / 信息图对话框由 Element Plus teleport 到 body，只能在这里统一主题化。
   模板库高度限制在 720px，4K 屏幕下也不会从顶到底占满。 */
html.kiwi-draw-theme .template-dialog,
html.kiwi-draw-theme .infographic-dialog {
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 28px 80px -28px rgb(15 23 42 / 0.45);
}
html.kiwi-draw-theme .template-dialog {
  width: min(1180px, calc(100vw - 48px)) !important;
}
html.kiwi-draw-theme .infographic-dialog {
  width: min(760px, calc(100vw - 48px)) !important;
}
html.kiwi-draw-theme .template-dialog .custom-dialog-header,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header {
  height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid rgb(226 232 240 / 0.75);
  background: #fff;
}
html.kiwi-draw-theme .template-dialog .custom-dialog-header .title-box,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header .title-box {
  gap: 0;
  margin: 0;
}
/* 标题前的官方彩色图标统一去掉，标题与系统弹窗一样从左侧开始。 */
html.kiwi-draw-theme .template-dialog .custom-dialog-header .title-box > svg,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header .title-box > svg {
  display: none;
}
html.kiwi-draw-theme .template-dialog .custom-dialog-header .title-box .title,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header .title-box .title {
  color: rgb(30 41 59);
  font-size: 15px;
  font-weight: 600;
}
html.kiwi-draw-theme .template-dialog .custom-dialog-header .close-icon,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header .close-icon {
  width: 18px;
  height: 18px;
  padding: 5px;
  border-radius: 8px;
  cursor: pointer;
}
html.kiwi-draw-theme .template-dialog .custom-dialog-header .close-icon:hover,
html.kiwi-draw-theme .infographic-dialog .custom-dialog-header .close-icon:hover {
  background: rgb(241 245 249);
}
html.kiwi-draw-theme .template-dialog .el-dialog__body {
  max-height: none !important;
}
html.kiwi-draw-theme .template-dialog .template-container {
  height: min(720px, calc(100vh - 176px)) !important;
  max-height: min(720px, calc(100vh - 176px)) !important;
}
html.kiwi-draw-theme .template-dialog .template-sidebar {
  padding: 10px 8px;
  background: rgb(248 250 252);
  border-right: 1px solid rgb(226 232 240 / 0.8);
}
html.kiwi-draw-theme .template-dialog .sidebar-categories {
  padding: 2px 4px 10px;
}
html.kiwi-draw-theme .template-dialog .category-item {
  height: 38px;
  padding: 0 10px;
  border-radius: 8px;
  color: rgb(71 85 105);
  font-size: 12.5px;
}
html.kiwi-draw-theme .template-dialog .category-item:hover {
  background: rgb(241 245 249);
}
html.kiwi-draw-theme .template-dialog .category-item.active {
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
  font-weight: 500;
}
html.kiwi-draw-theme .template-dialog .category-item .cat-badge {
  color: rgb(148 163 184);
  font-size: 11px;
}
html.kiwi-draw-theme .template-dialog .category-item.active .cat-badge {
  color: rgb(var(--kiwi-500));
}
html.kiwi-draw-theme .template-dialog .content-header {
  display: flex;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid rgb(241 245 249);
}
html.kiwi-draw-theme .template-dialog .content-header .search-input {
  width: min(320px, 100%) !important;
}
html.kiwi-draw-theme .template-dialog .content-header .search-input .el-input__wrapper {
  height: 34px;
  border-radius: 8px;
  background: rgb(248 250 252);
  box-shadow: 0 0 0 1px rgb(226 232 240) inset;
}
html.kiwi-draw-theme .template-dialog .content-header .search-input .el-input__wrapper:hover {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-300)) inset;
}
html.kiwi-draw-theme .template-dialog .content-header .search-input .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-600)) inset;
  background: #fff;
}
html.kiwi-draw-theme .template-dialog .template-grid {
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  padding: 16px 20px 20px;
}
html.kiwi-draw-theme .template-dialog .template-card {
  height: 176px;
  border: 1px solid rgb(226 232 240 / 0.9);
  border-radius: 12px;
  background: #fff;
}
html.kiwi-draw-theme .template-dialog .template-card:hover {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 10px 24px -12px rgb(15 23 42 / 0.28);
  transform: translateY(-2px);
}
html.kiwi-draw-theme .template-dialog .template-name {
  color: rgb(51 65 85);
  font-size: 12.5px;
  font-weight: 500;
}
html.kiwi-draw-theme .template-dialog .template-icon-wrapper {
  border-radius: 8px;
  background: rgb(248 250 252);
  overflow: hidden;
}
html.kiwi-draw-theme .infographic-dialog .el-dialog__body {
  max-height: calc(100vh - 240px);
  overflow-y: auto;
}
html.kiwi-draw-theme .infographic-dialog .infographic-body {
  padding: 20px 24px 12px;
}
html.kiwi-draw-theme .infographic-dialog .template-selector {
  gap: 10px;
  margin-bottom: 18px;
}
html.kiwi-draw-theme .infographic-dialog .template-selector .selector-label {
  color: rgb(71 85 105);
  font-size: 12.5px;
  font-weight: 500;
}
html.kiwi-draw-theme .infographic-dialog .template-selector .el-select {
  width: min(360px, 100%) !important;
}
html.kiwi-draw-theme .infographic-dialog .el-select__wrapper {
  min-height: 36px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(226 232 240) inset;
}
html.kiwi-draw-theme .infographic-dialog .el-select__wrapper:hover {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-300)) inset;
}
html.kiwi-draw-theme .infographic-dialog .el-select__wrapper.is-focused {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-600)) inset;
}
html.kiwi-draw-theme .infographic-dialog .editor-label {
  margin-bottom: 8px;
  color: rgb(51 65 85);
  font-size: 12.5px;
  font-weight: 500;
}
html.kiwi-draw-theme .infographic-dialog .editor-label .el-button.is-link {
  color: rgb(var(--kiwi-600));
  font-size: 12.5px;
  font-weight: 500;
}
html.kiwi-draw-theme .infographic-dialog .dsl-textarea .el-textarea__inner {
  min-height: 320px !important;
  border-radius: 10px;
  background: rgb(248 250 252);
  box-shadow: 0 0 0 1px rgb(226 232 240) inset;
  color: rgb(30 41 59);
}
html.kiwi-draw-theme .infographic-dialog .dsl-textarea .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-300)) inset;
}
html.kiwi-draw-theme .infographic-dialog .dsl-textarea .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px rgb(var(--kiwi-600)) inset;
  background: #fff;
}
html.kiwi-draw-theme .infographic-dialog .el-dialog__footer {
  padding: 12px 24px;
  border-top: 1px solid rgb(241 245 249);
  background: rgb(248 250 252 / 0.7);
}
html.kiwi-draw-theme .infographic-dialog .custom-footer .el-button {
  height: 34px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 12.5px;
}
html.kiwi-draw-theme .infographic-dialog .custom-footer .el-button:not(.el-button--primary) {
  border-color: rgb(226 232 240);
  color: rgb(71 85 105);
}
html.kiwi-draw-theme .infographic-dialog .custom-footer .el-button--primary {
  border-color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-600));
  color: #fff;
}
html.kiwi-draw-theme .infographic-dialog .custom-footer .el-button--primary:not(.is-disabled):hover {
  border-color: rgb(var(--kiwi-700));
  background: rgb(var(--kiwi-700));
}
html.kiwi-draw-theme .infographic-dialog .custom-footer .el-button--primary.is-disabled {
  opacity: 0.45;
}
html.kiwi-draw-theme .infographic-dialog .parse-info {
  background: rgb(var(--kiwi-50));
  border-color: rgb(var(--kiwi-200));
}
html.kiwi-draw-theme .infographic-dialog .parse-info .info-value {
  color: rgb(var(--kiwi-700));
}
html.kiwi-draw-theme .infographic-dialog .parse-error {
  color: rgb(185 28 28);
}
</style>
