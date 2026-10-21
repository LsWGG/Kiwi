/** 编辑器模式：标准编辑（语雀式）与 DOCX 纸张排版。 */

export type EditorMode = 'simple' | 'notion' | 'docx' | 'agent'

export interface EditorModeMeta {
  id: EditorMode
  label: string
  icon: string
  hint: string
}

export const EDITOR_MODES: EditorModeMeta[] = [
  {
    id: 'simple',
    label: '标准编辑',
    icon: 'edit',
    hint: '工具栏 + 斜杠命令 + 气泡菜单',
  },
  { id: 'docx', label: 'DOCX', icon: 'bookOpen', hint: 'A4 纸张排版，可导出 Word' },
]

/** 模式下拉顺序：标准编辑（默认）→ DOCX。 */
export const EDITOR_MODE_TABS: EditorMode[] = ['simple', 'docx']

const OFFICIAL_LABELS: Record<EditorMode, string> = {
  agent: '标准编辑',
  docx: 'DOCX editor',
  notion: '标准编辑',
  simple: '标准编辑',
}

export function editorModeTabLabel(mode: EditorMode): string {
  return OFFICIAL_LABELS[mode]
}

const VALID = new Set<EditorMode>(['simple', 'notion', 'docx', 'agent'])

export function isEditorMode(value: unknown): value is EditorMode {
  return typeof value === 'string' && VALID.has(value as EditorMode)
}

/** 默认使用标准编辑；历史 Simple / Notion / Agent 模式统一归并为标准编辑。 */
export function resolveEditorMode(
  _kind: string | null | undefined,
  props?: Record<string, unknown> | null,
): EditorMode {
  const saved = props?.editor_mode
  if (saved === 'docx') return 'docx'
  return 'simple'
}

export function editorModeMeta(mode: EditorMode): EditorModeMeta {
  return EDITOR_MODES.find((m) => m.id === mode) ?? EDITOR_MODES[0]
}

// ---------- DOCX 页面偏好（随笔记 props_json.docx_prefs 持久化） ----------

export type DocxFont =
  | 'serif'
  | 'sans'
  | 'kai'
  | 'yahei'
  | 'pingfang'
  | 'fangsong'
  | 'sourceSerif'
  | 'sourceSans'
  | 'times'
  | 'arial'
  | 'calibri'
  | 'georgia'
  | 'mono'
export type DocxPaper = 'a4' | 'letter' | 'a5'
export type DocxOrientation = 'portrait' | 'landscape'
export type DocxBackground = 'default' | 'white' | 'warm' | 'gray' | 'green'

export interface DocxMargins {
  top: number
  right: number
  bottom: number
  left: number
}

export type DocxLineHeightMode = 'multiple' | 'fixed'

export interface DocxPrefs {
  font: DocxFont
  size: number
  lineHeight: number
  /** 行距单位：倍数 / 固定值 */
  lineHeightMode: DocxLineHeightMode
  /** 固定行距，单位 pt */
  lineHeightFixed: number
  /** 段前间距，单位 px */
  spaceBefore: number
  /** 段后间距，单位 px */
  spaceAfter: number
  /** 左 / 右缩进，单位字符 */
  indentLeft: number
  indentRight: number
  /** 特殊格式缩进值，单位字符 */
  firstLineIndent: number
  /** true = 悬挂缩进，false = 首行缩进 */
  hangingIndent: boolean
  /** 字间距，单位 px */
  letterSpacing: number
  /** 纸张尺寸 */
  paper: DocxPaper
  orientation: DocxOrientation
  /** 页边距，单位 cm */
  margins: DocxMargins
  /** 纸张之间的间隙（画布留白），单位 px */
  pageGap: number
  /** 纸张背景 */
  background: DocxBackground
  /** 页眉文本，留空时使用文档标题 */
  headerText: string
  /** 页脚文本，留空时显示纸张规格与页码；支持 {page} / {pages} 占位符 */
  footerText: string
  showHeader: boolean
  showFooter: boolean
  /** 页眉距纸张顶端 / 页脚距纸张底端，单位 cm */
  headerDistance: number
  footerDistance: number
  /** 首页使用不同的页眉页脚 */
  differentFirstPage: boolean
  firstHeaderText: string
  firstFooterText: string
}

export const DOCX_PAPERS: { id: DocxPaper; label: string; width: number; height: number }[] = [
  { id: 'a4', label: 'A4', width: 21, height: 29.7 },
  { id: 'letter', label: 'Letter', width: 21.59, height: 27.94 },
  { id: 'a5', label: 'A5', width: 14.8, height: 21 },
]

export const DOCX_BACKGROUNDS: { id: DocxBackground; label: string; color: string }[] = [
  { id: 'default', label: '默认（白色）', color: '#ffffff' },
  { id: 'white', label: '纯白', color: '#ffffff' },
  { id: 'warm', label: '米色', color: '#fbf7ee' },
  { id: 'gray', label: '浅灰', color: '#f8fafc' },
  { id: 'green', label: '护眼绿', color: '#cce8cf' },
]

export const DEFAULT_DOCX_MARGINS: DocxMargins = { top: 2.54, right: 2.54, bottom: 2.54, left: 2.54 }

export const DEFAULT_DOCX_PREFS: DocxPrefs = {
  font: 'serif',
  size: 15,
  lineHeight: 1.9,
  lineHeightMode: 'multiple',
  lineHeightFixed: 20,
  spaceBefore: 0,
  spaceAfter: 8,
  indentLeft: 0,
  indentRight: 0,
  firstLineIndent: 0,
  hangingIndent: false,
  letterSpacing: 0,
  paper: 'a4',
  orientation: 'portrait',
  margins: { ...DEFAULT_DOCX_MARGINS },
  pageGap: 16,
  background: 'default',
  headerText: '',
  footerText: '',
  showHeader: true,
  showFooter: true,
  headerDistance: 1.25,
  footerDistance: 1.25,
  differentFirstPage: false,
  firstHeaderText: '',
  firstFooterText: '',
}

export const DOCX_FONTS: { id: DocxFont; label: string }[] = [
  { id: 'serif', label: '宋体' },
  { id: 'sans', label: '黑体' },
  { id: 'kai', label: '楷体' },
  { id: 'fangsong', label: '仿宋' },
  { id: 'yahei', label: '微软雅黑' },
  { id: 'pingfang', label: '苹方' },
  { id: 'sourceSerif', label: '思源宋体' },
  { id: 'sourceSans', label: '思源黑体' },
  { id: 'times', label: 'Times New Roman' },
  { id: 'arial', label: 'Arial' },
  { id: 'calibri', label: 'Calibri' },
  { id: 'georgia', label: 'Georgia' },
  { id: 'mono', label: '等宽' },
]

export const DOCX_SIZES = [12, 13, 14, 15, 16, 17, 18, 20, 22, 24, 26, 28, 32]
export const DOCX_LINE_HEIGHTS = [
  { value: 1.0, label: '单倍' },
  { value: 1.15, label: '1.15 倍' },
  { value: 1.5, label: '1.5 倍' },
  { value: 1.6, label: '紧凑' },
  { value: 1.75, label: '1.75 倍' },
  { value: 1.9, label: '标准' },
  { value: 2.0, label: '双倍' },
  { value: 2.2, label: '宽松' },
  { value: 2.5, label: '2.5 倍' },
  { value: 3.0, label: '3 倍' },
]

const FONT_STACKS: Record<DocxFont, string> = {
  serif:
    "'Noto Serif CJK SC', 'Source Han Serif SC', 'Songti SC', 'AR PL UMing CN', Georgia, serif",
  sans: "'Noto Sans CJK SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  kai: "'AR PL UKai CN', 'Kaiti SC', 'KaiTi', 'Noto Serif CJK SC', serif",
  fangsong: "FangSong, 'STFangsong', 'AR PL UKai CN', 'Noto Serif CJK SC', serif",
  yahei: "'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif",
  pingfang: "'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif",
  sourceSerif:
    "'Source Han Serif SC', 'Noto Serif CJK SC', 'Songti SC', 'Noto Serif', serif",
  sourceSans:
    "'Source Han Sans SC', 'Noto Sans CJK SC', 'PingFang SC', 'Noto Sans', sans-serif",
  times: "'Times New Roman', 'Noto Serif CJK SC', 'Songti SC', serif",
  arial: "Arial, 'Noto Sans CJK SC', 'PingFang SC', sans-serif",
  calibri: "Calibri, 'Noto Sans CJK SC', 'PingFang SC', sans-serif",
  georgia: "Georgia, 'Noto Serif CJK SC', 'Songti SC', serif",
  mono: "'JetBrains Mono', 'Cascadia Code', Consolas, 'Noto Sans Mono CJK SC', monospace",
}

export function docxFontStack(font: DocxFont): string {
  return FONT_STACKS[font] ?? FONT_STACKS.serif
}

/** 纸张预览尺寸（cm），按横向/纵向交换宽高。 */
export function docxPaperSize(
  paper: DocxPaper,
  orientation: DocxOrientation,
): { width: number; height: number; label: string } {
  const meta = DOCX_PAPERS.find((p) => p.id === paper) ?? DOCX_PAPERS[0]
  const landscape = orientation === 'landscape'
  return {
    width: landscape ? meta.height : meta.width,
    height: landscape ? meta.width : meta.height,
    label: meta.label,
  }
}

export function docxPaperLabel(prefs: DocxPrefs): string {
  const size = docxPaperSize(prefs.paper, prefs.orientation)
  return `${size.label} · ${size.width} × ${size.height} cm`
}

export function docxBackgroundColor(background: DocxBackground): string {
  return DOCX_BACKGROUNDS.find((b) => b.id === background)?.color ?? '#ffffff'
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, Math.round(value * 100) / 100))
}

function limitText(value: unknown, fallback: string, max = 120): string {
  return typeof value === 'string' ? value.slice(0, max) : fallback
}

export function resolveDocxPrefs(raw: unknown): DocxPrefs {
  const value = (raw ?? {}) as Partial<DocxPrefs>
  const font: DocxFont = DOCX_FONTS.some((f) => f.id === value.font)
    ? (value.font as DocxFont)
    : DEFAULT_DOCX_PREFS.font
  const size =
    typeof value.size === 'number' && DOCX_SIZES.includes(value.size)
      ? value.size
      : DEFAULT_DOCX_PREFS.size
  const lineHeight =
    typeof value.lineHeight === 'number' &&
    DOCX_LINE_HEIGHTS.some((l) => l.value === value.lineHeight)
      ? value.lineHeight
      : DEFAULT_DOCX_PREFS.lineHeight
  const paper: DocxPaper =
    value.paper === 'a4' || value.paper === 'letter' || value.paper === 'a5'
      ? value.paper
      : DEFAULT_DOCX_PREFS.paper
  const orientation: DocxOrientation =
    value.orientation === 'landscape' || value.orientation === 'portrait'
      ? value.orientation
      : DEFAULT_DOCX_PREFS.orientation
  const rawMargins = (value.margins ?? {}) as Partial<DocxMargins>
  const margins: DocxMargins = {
    top: clampNumber(rawMargins.top, 0, 6, DEFAULT_DOCX_MARGINS.top),
    right: clampNumber(rawMargins.right, 0, 6, DEFAULT_DOCX_MARGINS.right),
    bottom: clampNumber(rawMargins.bottom, 0, 6, DEFAULT_DOCX_MARGINS.bottom),
    left: clampNumber(rawMargins.left, 0, 6, DEFAULT_DOCX_MARGINS.left),
  }
  const background: DocxBackground =
    value.background === 'white' ||
    value.background === 'warm' ||
    value.background === 'gray' ||
    value.background === 'green' ||
    value.background === 'default'
      ? value.background
      : DEFAULT_DOCX_PREFS.background
  return {
    font,
    size,
    lineHeight,
    lineHeightMode: value.lineHeightMode === 'fixed' ? 'fixed' : 'multiple',
    lineHeightFixed: clampNumber(
      value.lineHeightFixed,
      8,
      72,
      DEFAULT_DOCX_PREFS.lineHeightFixed,
    ),
    spaceBefore: clampNumber(
      value.spaceBefore,
      0,
      48,
      DEFAULT_DOCX_PREFS.spaceBefore,
    ),
    spaceAfter: clampNumber(
      value.spaceAfter,
      0,
      48,
      DEFAULT_DOCX_PREFS.spaceAfter,
    ),
    indentLeft: clampNumber(
      value.indentLeft,
      0,
      10,
      DEFAULT_DOCX_PREFS.indentLeft,
    ),
    indentRight: clampNumber(
      value.indentRight,
      0,
      10,
      DEFAULT_DOCX_PREFS.indentRight,
    ),
    firstLineIndent: clampNumber(
      value.firstLineIndent,
      0,
      4,
      DEFAULT_DOCX_PREFS.firstLineIndent,
    ),
    hangingIndent: value.hangingIndent === true,
    letterSpacing: clampNumber(
      value.letterSpacing,
      -1,
      8,
      DEFAULT_DOCX_PREFS.letterSpacing,
    ),
    paper,
    orientation,
    margins,
    pageGap: clampNumber(value.pageGap, 0, 64, DEFAULT_DOCX_PREFS.pageGap),
    background,
    headerText: limitText(value.headerText, ''),
    footerText: limitText(value.footerText, ''),
    showHeader: value.showHeader !== false,
    showFooter: value.showFooter !== false,
    headerDistance: clampNumber(
      value.headerDistance,
      0,
      5,
      DEFAULT_DOCX_PREFS.headerDistance,
    ),
    footerDistance: clampNumber(
      value.footerDistance,
      0,
      5,
      DEFAULT_DOCX_PREFS.footerDistance,
    ),
    differentFirstPage: value.differentFirstPage === true,
    firstHeaderText: limitText(value.firstHeaderText, ''),
    firstFooterText: limitText(value.firstFooterText, ''),
  }
}

// ---------- 普通模式的页面偏好（随笔记 props_json.page_prefs 持久化） ----------

export type PageWidth = 'standard' | 'wide' | 'full'
export type PageBackground = 'white' | 'warm' | 'gray' | 'green'

export interface PagePrefs {
  width: PageWidth
  fontSize: number
  lineHeight: number
  background: PageBackground
}

export const DEFAULT_PAGE_PREFS: PagePrefs = {
  width: 'standard',
  fontSize: 15,
  lineHeight: 1.8,
  background: 'white',
}

export const PAGE_WIDTHS: { id: PageWidth; label: string; max: number }[] = [
  { id: 'standard', label: '标准', max: 800 },
  { id: 'wide', label: '宽', max: 980 },
  { id: 'full', label: '全宽', max: 1280 },
]

export const PAGE_FONT_SIZES = [14, 15, 16, 17]
export const PAGE_LINE_HEIGHTS = [1.6, 1.8, 2]

export const PAGE_BACKGROUNDS: { id: PageBackground; label: string; color: string }[] = [
  { id: 'white', label: '纯白', color: '#ffffff' },
  { id: 'warm', label: '米色', color: '#fbf7ee' },
  { id: 'gray', label: '浅灰', color: '#f8fafc' },
  { id: 'green', label: '护眼绿', color: '#cce8cf' },
]

export function pageBackgroundColor(background: PageBackground): string {
  return PAGE_BACKGROUNDS.find((b) => b.id === background)?.color ?? '#ffffff'
}

export function pageWidthMax(width: PageWidth): number {
  return PAGE_WIDTHS.find((w) => w.id === width)?.max ?? 800
}

export function resolvePagePrefs(raw: unknown): PagePrefs {
  const value = (raw ?? {}) as Partial<PagePrefs>
  const width: PageWidth =
    value.width === 'wide' || value.width === 'full' || value.width === 'standard'
      ? value.width
      : DEFAULT_PAGE_PREFS.width
  const fontSize =
    typeof value.fontSize === 'number' && PAGE_FONT_SIZES.includes(value.fontSize)
      ? value.fontSize
      : DEFAULT_PAGE_PREFS.fontSize
  const lineHeight =
    typeof value.lineHeight === 'number' && PAGE_LINE_HEIGHTS.includes(value.lineHeight)
      ? value.lineHeight
      : DEFAULT_PAGE_PREFS.lineHeight
  const background: PageBackground =
    value.background === 'warm' ||
    value.background === 'gray' ||
    value.background === 'green' ||
    value.background === 'white'
      ? value.background
      : DEFAULT_PAGE_PREFS.background
  return { width, fontSize, lineHeight, background }
}

// ---------- 代码块显示偏好（本地偏好，不写入笔记正文） ----------

export type CodeTheme = 'dark' | 'light'

export interface CodePrefs {
  theme: CodeTheme
  /** 显示行号 */
  lineNumbers: boolean
  /** 长行自动换行 */
  wrap: boolean
}

export const DEFAULT_CODE_PREFS: CodePrefs = {
  theme: 'dark',
  lineNumbers: false,
  wrap: false,
}

export const CODE_THEMES: { id: CodeTheme; label: string }[] = [
  { id: 'dark', label: '深色' },
  { id: 'light', label: '浅色' },
]

/** lowlight common 中已注册、适合作为代码块语言选择的集合。 */
export const CODE_LANGUAGES: { id: string; label: string }[] = [
  { id: 'plaintext', label: '纯文本' },
  { id: 'javascript', label: 'JavaScript' },
  { id: 'typescript', label: 'TypeScript' },
  { id: 'python', label: 'Python' },
  { id: 'java', label: 'Java' },
  { id: 'c', label: 'C' },
  { id: 'cpp', label: 'C++' },
  { id: 'csharp', label: 'C#' },
  { id: 'go', label: 'Go' },
  { id: 'rust', label: 'Rust' },
  { id: 'php', label: 'PHP' },
  { id: 'ruby', label: 'Ruby' },
  { id: 'kotlin', label: 'Kotlin' },
  { id: 'swift', label: 'Swift' },
  { id: 'bash', label: 'Shell' },
  { id: 'sql', label: 'SQL' },
  { id: 'json', label: 'JSON' },
  { id: 'yaml', label: 'YAML' },
  { id: 'html', label: 'HTML' },
  { id: 'css', label: 'CSS' },
  { id: 'scss', label: 'SCSS' },
  { id: 'markdown', label: 'Markdown' },
  { id: 'xml', label: 'XML' },
  { id: 'ini', label: 'INI' },
  { id: 'diff', label: 'Diff' },
]

export function resolveCodePrefs(raw: unknown): CodePrefs {
  const value = (raw ?? {}) as Partial<CodePrefs>
  return {
    theme: value.theme === 'light' ? 'light' : DEFAULT_CODE_PREFS.theme,
    lineNumbers:
      typeof value.lineNumbers === 'boolean' ? value.lineNumbers : DEFAULT_CODE_PREFS.lineNumbers,
    wrap: typeof value.wrap === 'boolean' ? value.wrap : DEFAULT_CODE_PREFS.wrap,
  }
}
