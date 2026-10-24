<script setup lang="ts">
/** 公开只读分享页：无需登录，可选访问密码。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import SharedLinkCard from '@/components/share/SharedLinkCard.vue'
import SharedDatabaseView from '@/components/share/SharedDatabaseView.vue'
import SharedSheetView from '@/components/share/SharedSheetView.vue'
import SharedCanvasView from '@/components/share/SharedCanvasView.vue'
import SharedNotebookView from '@/components/share/SharedNotebookView.vue'

interface SharedPagePrefs {
  width?: string
  fontSize?: number
  lineHeight?: number
  background?: string
}

interface SharedNote {
  title: string
  body_md: string
  kind: string
  updated_at: string
  expires_at: string
  has_password: boolean
  emoji?: string | null
  page_prefs?: SharedPagePrefs | null
  media_expires_at: number
  payload?: Record<string, any> | null
}

const KIND_LABEL: Record<string, string> = {
  doc: '文档',
  import: '导入文档',
  link: '链接',
  database: '数据表',
  canvas: '画布',
  notebook: 'Notebook',
  sheet: '表格',
}

/** 与编辑器「页面设置」保持一致的纸宽 / 底色取值。 */
const PAGE_WIDTHS: Record<string, number> = { standard: 800, wide: 980, full: 1280 }
const PAGE_BACKGROUNDS: Record<string, string> = {
  white: '#ffffff',
  warm: '#fbf7ee',
  gray: '#f8fafc',
  green: '#cce8cf',
}

/** 结构化笔记沿用工作区面板的类型标签配色。 */
const KIND_CHIP: Record<string, string> = {
  database: 'border-slate-200 bg-slate-50 text-slate-500',
  sheet: 'border-emerald-100 bg-emerald-50 text-emerald-600',
  canvas: 'border-violet-100 bg-violet-50 text-violet-500',
  notebook: 'border-indigo-100 bg-indigo-50 text-indigo-500',
}

const route = useRoute()
const token = computed(() => String(route.params.token || ''))

const data = ref<SharedNote | null>(null)
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const errorCode = ref('')
const needsPassword = ref(false)
const password = ref('')
const passwordAttempted = ref(false)
const copied = ref(false)

const kind = computed(() => data.value?.kind || 'doc')
const kindLabel = computed(() => KIND_LABEL[kind.value] || '文档')
const kindChipClass = computed(
  () => KIND_CHIP[kind.value] || 'border-slate-200 bg-slate-50 text-slate-500',
)
const emoji = computed(() => data.value?.emoji || '')
const payload = computed<Record<string, any>>(() =>
  data.value?.payload && typeof data.value.payload === 'object' ? data.value.payload : {},
)
// 数据表 / 表格 / 画布 / Notebook 需要更宽的画布来展示结构化内容。
const wide = computed(() =>
  ['database', 'sheet', 'canvas', 'notebook'].includes(kind.value),
)

const pagePrefs = computed<SharedPagePrefs>(() => data.value?.page_prefs || {})
const pageWidth = computed(
  () => PAGE_WIDTHS[String(pagePrefs.value.width || 'standard')] || PAGE_WIDTHS.standard,
)
const pageBackground = computed(
  () => PAGE_BACKGROUNDS[String(pagePrefs.value.background || 'white')] || '#ffffff',
)
const docFontSize = computed(() => {
  const value = Number(pagePrefs.value.fontSize)
  return Number.isFinite(value) ? Math.min(17, Math.max(14, value)) : 15
})
const docLineHeight = computed(() => {
  const value = Number(pagePrefs.value.lineHeight)
  return Number.isFinite(value) ? Math.min(2, Math.max(1.6, value)) : 1.8
})
const shellMax = computed(() => (wide.value ? 1280 : pageWidth.value))
const paperStyle = computed(() => {
  const style: Record<string, string> = {}
  if (wide.value) return style
  style.background = pageBackground.value
  style['--share-doc-size'] = `${docFontSize.value}px`
  style['--share-doc-line'] = String(docLineHeight.value)
  return style
})

// 链接笔记编译出的 Markdown 在无正文时会用摘要兜底；摘要已由书签卡展示。
const linkBody = computed(() => {
  if (kind.value !== 'link') return ''
  const raw = (data.value?.body_md || '').trim()
  const excerpt = String(payload.value.link?.excerpt || '').trim()
  if (!raw) return ''
  if (excerpt && raw.endsWith(excerpt) && raw.split('\n').length <= 4) return ''
  return raw
})

const expiryText = computed(() =>
  data.value
    ? new Date(data.value.expires_at).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '',
)

const updatedText = computed(() => {
  if (!data.value) return ''
  const date = new Date(data.value.updated_at)
  const day = date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return `${day} ${time}`
})

function passwordError(): string {
  // 首次进入只展示密码框，不把「需要密码」当成错误提示。
  return passwordAttempted.value && needsPassword.value ? error.value : ''
}

async function load(withPassword = false) {
  if (!token.value) {
    error.value = '分享链接无效'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  errorCode.value = ''
  const headers: Record<string, string> = {}
  if (withPassword) headers['X-Share-Password'] = password.value
  try {
    const res = await fetch(`/api/share/${encodeURIComponent(token.value)}`, { headers })
    const body = await res.json().catch(() => null)
    if (!res.ok) {
      const detail = body?.detail
      const code = typeof detail === 'object' && detail ? detail.code : ''
      const message =
        typeof detail === 'string'
          ? detail
          : (detail?.message as string) || '无法加载分享内容'
      errorCode.value = code || ''
      error.value = message
      needsPassword.value = ['share_password_required', 'share_password_invalid'].includes(code)
      data.value = null
      return
    }
    data.value = body as SharedNote
    needsPassword.value = false
    document.title = `${body.title || '只读分享'} · Kiwi`
  } catch {
    error.value = '网络异常，请检查连接后重试'
  } finally {
    loading.value = false
  }
}

async function unlock() {
  submitting.value = true
  passwordAttempted.value = true
  try {
    await load(true)
  } finally {
    submitting.value = false
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(window.location.href)
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1600)
  } catch {
    window.prompt('复制分享链接', window.location.href)
  }
}

function retry() {
  needsPassword.value = false
  passwordAttempted.value = false
  password.value = ''
  void load()
}

onMounted(() => load())
watch(token, () => {
  data.value = null
  password.value = ''
  needsPassword.value = false
  passwordAttempted.value = false
  void load()
})
</script>

<template>
  <!-- body 全局 overflow:hidden，分享页需要自己作为滚动容器 -->
  <div class="share-page h-full overflow-y-auto">
    <header class="sticky top-0 z-20 border-b border-slate-200/60 bg-white/75 backdrop-blur-xl">
      <div class="mx-auto flex h-12 max-w-[1400px] items-center gap-2.5 px-5 max-sm:px-4">
        <span class="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-sm">
          <KiwiIcon name="shield" :size="14" />
        </span>
        <span class="text-[13px] font-semibold tracking-wide text-slate-700">Kiwi</span>
        <span class="rounded-full bg-kiwi-50 px-2 py-0.5 text-[10px] font-medium text-kiwi-700">
          只读分享
        </span>
        <div class="flex-1" />
        <button
          class="kiwi-btn-ghost !px-2 !py-1 !text-[11px]"
          :title="copied ? '已复制' : '复制当前链接'"
          @click="copyLink"
        >
          <KiwiIcon :name="copied ? 'check' : 'copy'" :size="12" />
          {{ copied ? '已复制' : '复制链接' }}
        </button>
      </div>
    </header>

    <main class="px-4 py-6 max-sm:px-3 max-sm:py-4 sm:px-6 sm:py-8">
      <div class="mx-auto" :style="{ maxWidth: `${shellMax}px` }">
        <!-- 加载 -->
        <div v-if="loading && !data && !needsPassword" class="kiwi-card flex items-center justify-center gap-2 p-16 text-[12px] text-slate-400">
          <KiwiIcon name="loader" :size="15" :spin="true" />
          正在加载分享内容…
        </div>

        <!-- 密码 -->
        <div v-else-if="needsPassword" class="mx-auto mt-10 max-w-sm">
          <div class="kiwi-card p-6 text-center">
            <div class="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-amber-50 text-amber-500">
              <KiwiIcon name="lock" :size="20" />
            </div>
            <h1 class="mt-4 text-base font-semibold text-slate-800">此分享受密码保护</h1>
            <p class="mt-1 text-[11.5px] leading-relaxed text-slate-400">
              请输入分享者提供的访问密码后查看内容。
            </p>
            <form class="mt-4 space-y-2" @submit.prevent="unlock">
              <input
                v-model="password"
                type="password"
                autocomplete="current-password"
                autofocus
                class="kiwi-input text-center"
                placeholder="访问密码"
              />
              <p v-if="passwordError()" class="text-[11px] text-rose-500">{{ passwordError() }}</p>
              <button
                type="submit"
                class="kiwi-btn-primary w-full !py-2"
                :disabled="!password || submitting"
              >
                <KiwiIcon :name="submitting ? 'loader' : 'unlock'" :size="13" :spin="submitting" />
                {{ submitting ? '验证中…' : '查看内容' }}
              </button>
            </form>
          </div>
        </div>

        <!-- 失效 / 错误 -->
        <div v-else-if="error" class="mx-auto mt-10 max-w-sm">
          <div class="kiwi-card p-6 text-center">
            <div class="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-rose-50 text-rose-400">
              <KiwiIcon :name="errorCode === 'share_expired' ? 'clock' : 'alert'" :size="20" />
            </div>
            <h1 class="mt-4 text-base font-semibold text-slate-800">无法查看此分享</h1>
            <p class="mt-1 text-[11.5px] leading-relaxed text-slate-400">{{ error }}</p>
            <button
              v-if="errorCode !== 'share_expired' && errorCode !== 'share_revoked'"
              class="kiwi-btn-secondary mt-4 !text-[11.5px]"
              @click="retry"
            >
              重新加载
            </button>
          </div>
        </div>

        <!-- 正文：文档 / 链接沿用阅读纸张；数据表等沿用工作区面板 -->
        <article v-else-if="data" :class="wide ? 'share-pane' : 'share-sheet'" :style="paperStyle">
          <!-- 结构化笔记：工作区面板式标题栏 -->
          <header v-if="wide" class="share-pane-head">
            <span v-if="emoji" class="shrink-0 text-[18px] leading-none">{{ emoji }}</span>
            <h1 class="min-w-0 truncate text-[15px] font-semibold text-slate-800">
              {{ data.title || '无标题' }}
            </h1>
            <span
              class="shrink-0 rounded-md border px-1.5 py-0.5 text-[10px]"
              :class="kindChipClass"
            >
              {{ kindLabel }}
            </span>
            <div class="flex-1" />
            <span class="shrink-0 text-[10.5px] text-slate-400">更新于 {{ updatedText }}</span>
          </header>

          <!-- 文档 / 链接：与阅读态一致的标题区 -->
          <header v-else class="share-doc-head">
            <div class="flex items-start gap-2">
              <span
                v-if="emoji"
                class="w-9 shrink-0 text-center text-[24px] leading-none"
              >{{ emoji }}</span>
              <h1 class="min-w-0 flex-1 text-[27px] leading-[1.22] font-semibold tracking-[-0.022em] text-slate-900 max-sm:text-[23px]">
                {{ data.title || '无标题' }}
              </h1>
            </div>
            <p class="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-400">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-br from-kiwi-300 to-kiwi-500"
                aria-hidden="true"
              />
              <span>更新于 {{ updatedText }}</span>
            </p>
          </header>

          <div :class="wide ? 'share-pane-body' : 'share-doc-body'">
            <!-- 链接：书签卡 + 抓取正文 -->
            <template v-if="kind === 'link'">
              <SharedLinkCard :payload="payload.link" :title="data.title" />
              <MarkdownView v-if="linkBody" :content="linkBody" />
            </template>

            <!-- 数据表：只读记录表格 -->
            <template v-else-if="kind === 'database'">
              <SharedDatabaseView v-if="payload.database" :payload="payload.database" />
              <MarkdownView v-else-if="data.body_md" :content="data.body_md" />
              <p v-else class="py-10 text-center text-[12px] text-slate-400">
                数据表还没有内容。
              </p>
            </template>

            <!-- 表格：只读工作簿 -->
            <SharedSheetView v-else-if="kind === 'sheet'" :payload="payload" />

            <!-- 画布：静态 SVG -->
            <SharedCanvasView v-else-if="kind === 'canvas'" :doc="payload.doc" />

            <!-- Notebook：Markdown / 代码单元格与输出 -->
            <SharedNotebookView v-else-if="kind === 'notebook'" :doc="payload.notebook_doc" />

            <!-- 文档 / 导入及其它类型：Markdown 正文 -->
            <template v-else>
              <MarkdownView v-if="data.body_md" :content="data.body_md" />
              <p v-else class="py-10 text-center text-[12px] text-slate-400">
                这篇笔记还没有正文。
              </p>
            </template>
          </div>

          <footer :class="wide ? 'share-pane-foot' : 'share-doc-foot'">
            <span>本页面由 Kiwi 生成，内容仅供阅读，无法编辑。</span>
            <span>
              链接有效至 {{ expiryText }}
              <template v-if="data.has_password"> · 已通过密码验证</template>
              · 分享者可随时撤销
            </span>
          </footer>
        </article>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* 与笔记工作区的编辑画布同一套底纹：冷灰底 + 环境光 + 细点阵 */
.share-page {
  background-color: #eef1f7;
  background-image:
    radial-gradient(900px 420px at 8% -10%, rgb(var(--kiwi-500) / 0.16), transparent 62%),
    radial-gradient(820px 380px at 100% 108%, rgba(94, 183, 214, 0.09), transparent 66%),
    radial-gradient(circle at 1px 1px, rgba(100, 116, 139, 0.17) 1px, transparent 0);
  background-size: auto, auto, 18px 18px;
  background-attachment: fixed;
}

/* 阅读纸张：尺寸、圆角、阴影与编辑器 .editor-sheet 对齐 */
.share-sheet {
  position: relative;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  padding: 2.4rem 2.6rem 2.2rem;
  box-shadow:
    0 0 0 1px rgba(226, 232, 240, 0.55),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px -20px rgba(15, 23, 42, 0.26),
    0 46px 90px -56px rgba(15, 23, 42, 0.4);
}
.share-sheet::before {
  content: '';
  position: absolute;
  top: 0;
  left: 16%;
  right: 16%;
  height: 2px;
  border-radius: 0 0 4px 4px;
  background: linear-gradient(
    90deg,
    rgb(var(--kiwi-400) / 0),
    rgb(var(--kiwi-500) / 0.7),
    rgb(var(--kiwi-400) / 0)
  );
  pointer-events: none;
}

/* 结构化笔记：工作区面板外观 */
.share-pane {
  overflow: hidden;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  background: #fff;
  box-shadow:
    0 0 0 1px rgba(226, 232, 240, 0.55),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px -20px rgba(15, 23, 42, 0.26),
    0 46px 90px -56px rgba(15, 23, 42, 0.4);
}
.share-pane-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  border-bottom: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(255, 255, 255, 0.55);
  padding: 0.6rem 1rem;
}
.share-pane-body {
  padding: 1.1rem;
}
.share-pane-foot,
.share-doc-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem 1rem;
  font-size: 10.5px;
  line-height: 1.7;
  color: #94a3b8;
}
.share-pane-foot {
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  padding: 0.7rem 1rem;
}
.share-doc-foot {
  margin-top: 2.5rem;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  padding-top: 1rem;
}
.share-doc-body {
  margin-top: 1.4rem;
}

/* Markdown 正文：字号 / 行高 / 段落节奏与编辑器阅读态一致 */
.share-sheet :deep(.prose-wiki) {
  font-size: var(--share-doc-size, 15px);
  line-height: var(--share-doc-line, 1.8);
  color: #1e293b;
}
.share-sheet :deep(.prose-wiki > *) {
  margin-top: 0;
  margin-bottom: 0;
}
.share-sheet :deep(.prose-wiki > * + *) {
  margin-top: 0.7em;
}
.share-sheet :deep(.prose-wiki h1) {
  margin-top: 1.4em;
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.35;
}
.share-sheet :deep(.prose-wiki h2) {
  margin-top: 1.2em;
  font-size: 1.3rem;
  font-weight: 600;
  line-height: 1.4;
}
.share-sheet :deep(.prose-wiki h3) {
  margin-top: 1em;
  font-size: 1.1rem;
  font-weight: 600;
}
.share-sheet :deep(.prose-wiki blockquote) {
  border-left: 3px solid rgb(var(--kiwi-300));
  padding-left: 1rem;
  color: #64748b;
  font-style: normal;
}
.share-sheet :deep(.prose-wiki code) {
  border-radius: 5px;
  background: rgb(var(--kiwi-50));
  padding: 1px 5px;
  font-size: 0.88em;
  font-weight: 400;
  color: #4c46a6;
}
/* Tailwind Typography 会给行内代码加反引号，编辑器里没有 */
.share-sheet :deep(.prose-wiki code::before),
.share-sheet :deep(.prose-wiki code::after) {
  content: none;
}

@media (max-width: 767px) {
  .share-sheet {
    padding: 1.25rem 1rem 1.5rem;
  }
  .share-pane-body {
    padding: 0.8rem;
  }
}
</style>
