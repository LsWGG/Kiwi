/**
 * 画布数据模型：直接持久化 jvs-draw（Excalidraw 系）文档。
 *
 * 编辑器扩展以 ```kiwi-draw 围栏保存 JSON；画布笔记保存在
 * note.props_json.draw_doc。两者共用本模块的容错读取与统计逻辑。
 */
import { legacyCanvasToDraw } from './legacyCanvas'

export interface DrawAppState {
  viewBackgroundColor?: string
  [key: string]: unknown
}

export interface DrawElement {
  id: string
  type: string
  x: number
  y: number
  width: number
  height: number
  isDeleted?: boolean
  [key: string]: unknown
}

export interface JvsDrawDoc {
  type: 'jvs-draw'
  version: 1
  elements: DrawElement[]
  appState: DrawAppState
  files: Record<string, string>
  updatedAt?: number
}

export type DrawGridType = 'none' | 'solid' | 'dot'
export type DrawShapeTheme = 'default' | 'classic'

/** 画布偏好设置：映射到 jvs-draw 的 appState，随文档一起持久化。 */
export interface DrawPreferences {
  /** 画布背景色（appState.viewBackgroundColor） */
  backgroundColor: string
  /** 背景网格（appState.gridType） */
  gridType: DrawGridType
  /** 形状主题（appState.activeTheme） */
  shapeTheme: DrawShapeTheme
  /** 滚轮直接缩放画布（默认关闭，关闭时滚轮平移） */
  wheelZoom: boolean
  /** 右键拖拽平移画布 */
  rightClickPan: boolean
  /** 选中图形后显示快捷创建按钮 */
  quickCreate: boolean
  /** 选中 / 绘制时显示尺寸标签 */
  showSize: boolean
}

export const DRAW_PREFERENCE_DEFAULTS: DrawPreferences = {
  backgroundColor: '#ffffff',
  gridType: 'none',
  shapeTheme: 'default',
  wheelZoom: false,
  rightClickPan: true,
  quickCreate: true,
  showSize: true,
}

/**
 * 当前主题下的默认画布底色。
 *
 * 深色主题如果仍用纯白画布，画布会和周围的深色界面割裂，连线标签、
 * 浅色文字也会失去对比。这里跟随主题的应用底色；浅色主题保持纯白。
 */
export function defaultDrawBackground(): string {
  if (typeof document === 'undefined') return '#ffffff'
  const root = document.documentElement
  if (root.dataset.kiwiThemeMode !== 'dark') return '#ffffff'
  const raw = getComputedStyle(root).getPropertyValue('--theme-app').trim()
  const match = /^(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})$/.exec(raw)
  if (!match) return '#0b1f3a'
  const hex = match
    .slice(1)
    .map((part) => Math.min(255, Number(part)).toString(16).padStart(2, '0'))
    .join('')
  return `#${hex}`
}

function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

export function readDrawPreferences(appState: unknown): DrawPreferences {
  const state = isRecord(appState) ? appState : {}
  const background =
    typeof state.viewBackgroundColor === 'string' && state.viewBackgroundColor
      ? state.viewBackgroundColor
      : defaultDrawBackground()
  const gridType = state.gridType
  const shapeTheme = state.activeTheme
  return {
    backgroundColor: background,
    gridType:
      gridType === 'solid' || gridType === 'dot' || gridType === 'none'
        ? gridType
        : DRAW_PREFERENCE_DEFAULTS.gridType,
    shapeTheme:
      shapeTheme === 'classic' || shapeTheme === 'default'
        ? shapeTheme
        : DRAW_PREFERENCE_DEFAULTS.shapeTheme,
    wheelZoom: readBoolean(state.useWheelZoom, DRAW_PREFERENCE_DEFAULTS.wheelZoom),
    rightClickPan: readBoolean(state.rightClickPan, DRAW_PREFERENCE_DEFAULTS.rightClickPan),
    quickCreate: readBoolean(state.showQuickCreate, DRAW_PREFERENCE_DEFAULTS.quickCreate),
    showSize: readBoolean(state.showElementSize, DRAW_PREFERENCE_DEFAULTS.showSize),
  }
}

const CONNECTOR_TYPES = new Set(['arrow', 'line', 'freedraw'])
/**
 * 连线标签的自动底色标记：保存在元素 customData 中，记录上一次自动同步的
 * 画布底色。标记仍等于当前标签底色时说明用户没改过，可以继续跟随画布；
 * 用户手动改过标签底色后标记会被清掉，之后不再覆盖。
 */
export const CONNECTOR_LABEL_BG_KEY = 'kiwiLabelBg'
/** 旧版本把画布底色写进标签但没有留下标记，这些历史值按自动底色迁移。 */
const LEGACY_CONNECTOR_LABEL_BACKGROUNDS = new Set([
  '#ffffff',
  '#f8fafc',
  '#fbf7ef',
  '#f5f3ff',
  '#eff6ff',
  '#fefce8',
  '#f0fdf4',
  '#0b1f3a',
  '#0f172a',
  '#1e293b',
])
const TRANSIENT_STATE_KEYS = [
  'scrollX',
  'scrollY',
  'zoom',
  'activeTool',
  'activeToolType',
  'showHelp',
  'isPanningCanvas',
  'isDraggingElement',
  'isBoxSelecting',
  'showGrid',
  'isPropertiesPanelOpen',
  'isShapeLibraryOpen',
  'floatingToolbarOffset',
  'selectedElementIds',
]

let fallbackSeq = 0

function newElementId(): string {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return `el-${uuid.slice(0, 12)}`
  fallbackSeq += 1
  return `el-${Date.now().toString(36)}-${fallbackSeq}`
}

function finite(value: unknown, fallback = 0): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** 读取笔记 props 中的画布：优先 draw_doc，旧笔记回退到 canvas_doc。 */
export function readDrawDoc(props: unknown): JvsDrawDoc | null {
  if (!isRecord(props)) return null
  return normalizeDrawDoc(props.draw_doc) ?? normalizeDrawDoc(legacyCanvasToDraw(props.canvas_doc))
}

function connectorLabelMarker(element: DrawElement): string {
  const data = element.customData
  if (!isRecord(data)) return ''
  const marker = data[CONNECTOR_LABEL_BG_KEY]
  return typeof marker === 'string' ? marker.trim().toLowerCase() : ''
}

/**
 * 连线标签底色是否由画布自动托管。
 *
 * jvs-draw 在 fontBgColor 为 transparent 时固定画白底，深色画布上会出现
 * 「白底 + 浅色字」；因此标签底色必须显式写成画布底色。只有自动写入的
 * 底色才跟随画布变化，用户在属性面板里自定义过的底色保持不动。
 */
function isAutoConnectorLabel(element: DrawElement, canvasBackground: string): boolean {
  const labelBg =
    typeof element.fontBgColor === 'string' ? element.fontBgColor.trim().toLowerCase() : ''
  if (!labelBg || labelBg === 'transparent') return true
  const marker = connectorLabelMarker(element)
  if (marker) return marker === labelBg
  // 没有标记：底色正好是当前画布色或旧版本写入过的值，按自动底色迁移。
  return (
    labelBg === canvasBackground.trim().toLowerCase() ||
    LEGACY_CONNECTOR_LABEL_BACKGROUNDS.has(labelBg)
  )
}

/** 读取 jvs-draw 的 /getContentObject() 结构；非法数据返回 null。 */
export function normalizeDrawDoc(raw: unknown): JvsDrawDoc | null {
  if (!isRecord(raw) || !Array.isArray(raw.elements)) return null

  const elements: DrawElement[] = []
  for (const item of raw.elements) {
    if (!isRecord(item) || typeof item.type !== 'string') continue
    elements.push({
      ...item,
      id: typeof item.id === 'string' && item.id ? item.id : newElementId(),
      type: item.type,
      x: finite(item.x),
      y: finite(item.y),
      width: Math.max(0, finite(item.width)),
      height: Math.max(0, finite(item.height)),
      isDeleted: item.isDeleted === true,
    })
  }

  const appState: DrawAppState = {}
  if (isRecord(raw.appState)) {
    for (const [key, value] of Object.entries(raw.appState)) {
      if (TRANSIENT_STATE_KEYS.includes(key)) continue
      appState[key] = value
    }
  }
  if (typeof appState.viewBackgroundColor !== 'string' || !appState.viewBackgroundColor) {
    appState.viewBackgroundColor = defaultDrawBackground()
  }
  /* jvs-draw 给连线标签兜底的是固定白底（fontBgColor 为 transparent 时），
     深色画布上会出现「白底 + 浅色字」。这里把标签底色对齐画布底色，
     文字重新变得可读，标签也能正常遮住连线。仅处理绑定在连线上的文本，
     并用 customData.kiwiLabelBg 记录自动值，避免覆盖用户的自行设置。 */
  const canvasBackground = appState.viewBackgroundColor
  const connectors = new Set(
    elements
      .filter((element) => element.type === 'arrow' || element.type === 'line')
      .map((element) => element.id),
  )
  for (const element of elements) {
    if (element.type !== 'text' || !connectors.has(String(element.containerId ?? ''))) continue
    const customData = isRecord(element.customData) ? { ...element.customData } : {}
    if (!isAutoConnectorLabel(element, canvasBackground)) {
      // 用户自定义过底色：清掉旧标记，后续画布换色不再动它。
      if (CONNECTOR_LABEL_BG_KEY in customData) {
        delete customData[CONNECTOR_LABEL_BG_KEY]
        element.customData = customData
      }
      continue
    }
    element.fontBgColor = canvasBackground
    if (customData[CONNECTOR_LABEL_BG_KEY] !== canvasBackground) {
      customData[CONNECTOR_LABEL_BG_KEY] = canvasBackground
      element.customData = customData
    }
  }

  const files: Record<string, string> = {}
  if (isRecord(raw.files)) {
    for (const [key, value] of Object.entries(raw.files)) {
      if (typeof value === 'string' && value) files[key] = value
    }
  }

  return {
    type: 'jvs-draw',
    version: 1,
    elements,
    appState,
    files,
    updatedAt: finite(raw.updatedAt, Date.now()),
  }
}

export function emptyDrawDoc(): JvsDrawDoc {
  return {
    type: 'jvs-draw',
    version: 1,
    elements: [],
    appState: { viewBackgroundColor: defaultDrawBackground() },
    files: {},
  }
}

export function cloneDrawDoc(doc: JvsDrawDoc): JvsDrawDoc {
  return JSON.parse(JSON.stringify(doc)) as JvsDrawDoc
}

/** 只把「有内容」当作画布；空白画布给阅读态展示占位。 */
export function drawDocHasContent(doc: JvsDrawDoc): boolean {
  return doc.elements.some((element) => !element.isDeleted)
}

/** 文档指纹：忽略 updatedAt，用来判断画布是否真的发生变化。 */
export function drawDocFingerprint(doc: JvsDrawDoc): string {
  return JSON.stringify({
    elements: doc.elements,
    appState: doc.appState,
    files: doc.files,
  })
}

export function parseDrawFence(text: string): JvsDrawDoc | null {
  const source = String(text || '').trim()
  if (!source) return null
  try {
    return normalizeDrawDoc(JSON.parse(source))
  } catch {
    return null
  }
}

export interface DrawDocStats {
  /** 图形、文本、图片等节点数（不含连线与容器内文字）。 */
  nodes: number
  /** 箭头 / 连线数。 */
  edges: number
  /** 独立文本块数。 */
  texts: number
  /** 图片数。 */
  images: number
}

export function drawDocStats(doc: JvsDrawDoc): DrawDocStats {
  let nodes = 0
  let edges = 0
  let texts = 0
  let images = 0
  for (const element of doc.elements) {
    if (element.isDeleted) continue
    if (CONNECTOR_TYPES.has(element.type)) {
      edges += 1
      continue
    }
    if (element.type === 'text') {
      const containerId = typeof element.containerId === 'string' ? element.containerId : ''
      if (containerId) continue
      texts += 1
      nodes += 1
      continue
    }
    if (element.type === 'image') images += 1
    nodes += 1
  }
  return { nodes, edges, texts, images }
}

/** 提取画布内可检索 / 可编译的文字。 */
export function drawDocText(doc: JvsDrawDoc): string[] {
  const lines: string[] = []
  for (const element of doc.elements) {
    if (element.isDeleted) continue
    const text =
      typeof element.text === 'string'
        ? element.text
        : typeof element.originalText === 'string'
          ? element.originalText
          : ''
    if (!text.trim()) continue
    lines.push(text.trim())
  }
  return lines
}

export function drawDocBackground(doc: JvsDrawDoc): string {
  const background = doc.appState.viewBackgroundColor
  return typeof background === 'string' && background ? background : '#ffffff'
}
