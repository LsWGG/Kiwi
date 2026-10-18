<script setup lang="ts">
/**
 * @ 提及节点视图：行内提及 / 独占一行的大内容卡片 / 嵌入内容。
 * 支持全部笔记类型（文档、数据表、导入、链接、画布）与 Wiki 页面。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, type NodeViewProps } from '@tiptap/vue-3'
import { useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import {
  mentionText,
  normalizeMentionDisplay,
  type MentionDisplay,
} from './extensions/mentionTypes'

type MentionKind = 'doc' | 'database' | 'link' | 'import' | 'canvas' | 'notebook' | 'wiki'
type MentionTarget = 'note' | 'wiki'

const props = defineProps<NodeViewProps>()

const router = useRouter()
const kbs = useKbsStore()

const target = computed<MentionTarget>(() =>
  props.node.attrs.target === 'wiki' ? 'wiki' : 'note',
)
const itemId = computed(() => String(props.node.attrs.id ?? ''))
const cacheKey = computed(() => `${target.value}:${itemId.value}`)
const label = computed(() => String(props.node.attrs.label ?? itemId.value))
const display = computed<MentionDisplay>(() =>
  normalizeMentionDisplay(props.node.attrs.display),
)

function normalizeHeight(value: unknown): number | null {
  const height = Number(value)
  return Number.isFinite(height) && height > 0 ? Math.round(height) : null
}

/** 嵌入窗口高度：拖动底边调整，双击恢复自动高度。 */
const embedEl = ref<HTMLElement | null>(null)
const embedHeight = ref<number | null>(normalizeHeight(props.node.attrs.height))
const resizing = ref(false)
let resizeStartY = 0
let resizeStartHeight = 0

/** 页面在 4K 下整体 zoom，拖动距离需要换算回未缩放尺寸。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

watch(
  () => props.node.attrs.height,
  (value) => {
    if (!resizing.value) embedHeight.value = normalizeHeight(value)
  },
)

function onResizeMove(event: MouseEvent) {
  if (!resizing.value) return
  const next = resizeStartHeight + (event.clientY - resizeStartY) / uiScale()
  embedHeight.value = Math.min(1600, Math.max(160, Math.round(next)))
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
  props.updateAttributes({ height: embedHeight.value })
}

function startResize(event: MouseEvent) {
  if (event.button !== 0) return
  resizeStartY = event.clientY
  resizeStartHeight = embedEl.value
    ? embedEl.value.getBoundingClientRect().height / uiScale()
    : 320
  resizing.value = true
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', stopResize)
}

function resetHeight() {
  embedHeight.value = null
  props.updateAttributes({ height: null })
}

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
})

interface LinkMeta {
  url?: string
  final_url?: string
  site?: string
  excerpt?: string
  fetch_status?: string
}

interface DbOption {
  id: string
  name?: string
  label?: string
}

interface DbField {
  id: string
  name: string
  type: string
  options?: DbOption[]
}

interface DbRow {
  id: string
  data: Record<string, any>
}

interface NotebookCellLite {
  type?: string
  source?: string
}

interface NoteCache {
  title: string
  body_md: string
  kind: MentionKind
  link?: LinkMeta
  fields?: DbField[]
  rows?: DbRow[]
  notebook?: { cells?: NotebookCellLite[] }
}

const cache = new Map<string, NoteCache>()
const detail = ref<NoteCache | null>(cache.get(cacheKey.value) ?? null)
const loading = ref(false)
const failed = ref(false)

const title = computed(() => detail.value?.title || label.value || itemId.value)
const kind = computed<MentionKind>(() =>
  target.value === 'wiki' ? 'wiki' : detail.value?.kind || 'doc',
)

const KIND_META: Record<MentionKind, { icon: string; label: string }> = {
  doc: { icon: 'fileText', label: '文档' },
  database: { icon: 'database', label: '数据表' },
  link: { icon: 'link2', label: '链接' },
  import: { icon: 'fileImport', label: '导入' },
  canvas: { icon: 'pen', label: '画布' },
  notebook: { icon: 'notebook', label: 'Notebook' },
  wiki: { icon: 'wiki', label: 'Wiki 页面' },
}
const kindMeta = computed(() => KIND_META[kind.value] || KIND_META.doc)

function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[#>*_`~|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const excerpt = computed(() => {
  if (kind.value === 'database') {
    return `数据表 · ${detail.value?.rows?.length ?? 0} 条记录 · ${detail.value?.fields?.length ?? 0} 个字段`
  }
  if (kind.value === 'canvas') {
    return '画布 · 打开笔记查看工程图 / 思维导图'
  }
  if (kind.value === 'notebook') {
    const cells = detail.value?.notebook?.cells ?? []
    const code = cells.filter((cell) => cell.type === 'code').length
    return `Notebook · ${cells.length} 个单元格 · ${code} 个代码单元格`
  }
  if (kind.value === 'link') {
    const link = detail.value?.link
    const body = plainText(detail.value?.body_md || '')
    const source = link?.site || link?.final_url || link?.url || ''
    if (body) return body.length > 140 ? `${body.slice(0, 140)}…` : body
    if (link?.excerpt) {
      return link.excerpt.length > 140 ? `${link.excerpt.slice(0, 140)}…` : link.excerpt
    }
    return source || '链接笔记'
  }
  const text = plainText(detail.value?.body_md || '')
  if (!text) return '暂无正文内容'
  return text.length > 140 ? `${text.slice(0, 140)}…` : text
})

/** 嵌入展示完整正文，窗口放不下时由容器滚动。 */
const embedSource = computed(() => detail.value?.body_md || '')

/** 数据表嵌入同样展示全部字段与记录。 */
const embedFields = computed(() => detail.value?.fields ?? [])
const embedRows = computed(() => detail.value?.rows ?? [])

function optionLabel(field: DbField, raw: unknown): string {
  if (raw && typeof raw === 'object') {
    const option = raw as DbOption & Record<string, any>
    return String(
      option.name ??
        option.label ??
        option.filename ??
        option.title ??
        option.id ??
        '',
    )
  }
  const id = String(raw ?? '')
  if (!id) return ''
  const option = field.options?.find((item) => item.id === id)
  return String(option?.name ?? option?.label ?? id)
}

/** 按字段类型给列一个合理的最小宽度，内容多时再横向滚动。 */
function fieldMinWidth(field: DbField): string {
  if (field.type === 'attachment') return '80px'
  if (field.type === 'date') return '96px'
  if (field.type === 'rating' || field.type === 'number') return '60px'
  if (field.type === 'progress') return '104px'
  if (field.type === 'checkbox') return '56px'
  if (field.type === 'select' || field.type === 'multi_select') return '80px'
  if (field.type === 'url') return '140px'
  return '110px'
}

function attachments(row: DbRow, field: DbField): Record<string, any>[] {
  const value = row.data?.[field.id]
  if (!Array.isArray(value)) return []
  return value.filter((item) => item && typeof item === 'object')
}

/** 附件在嵌入预览里只显示数量，悬停可看到文件名，避免撑高整行。 */
function attachmentTitle(row: DbRow, field: DbField): string {
  return attachments(row, field)
    .map((file) => String(file.filename ?? file.name ?? ''))
    .filter(Boolean)
    .join('\n')
}

function cellText(row: DbRow, field: DbField): string {
  const value = row.data?.[field.id]
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) {
    const labels = value.map((item) => optionLabel(field, item)).filter(Boolean)
    return labels.length ? labels.join('、') : '—'
  }
  if (typeof value === 'boolean') return value ? '✓' : '—'
  if (field.type === 'progress') {
    const number = Number(value)
    return Number.isFinite(number)
      ? `${Math.max(0, Math.min(100, Math.round(number)))}%`
      : '—'
  }
  if (field.type === 'select' || field.type === 'multi_select') {
    return optionLabel(field, value) || '—'
  }
  if (typeof value === 'object') {
    return optionLabel(field, value) || JSON.stringify(value)
  }
  return String(value)
}

function openLink() {
  const meta = detail.value?.link
  const url = meta?.final_url || meta?.url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

async function load() {
  if (display.value === 'mention' || detail.value || loading.value || !itemId.value) return
  const kbId = kbs.currentKbId
  if (!kbId) return
  loading.value = true
  failed.value = false
  try {
    let data: NoteCache
    if (target.value === 'wiki') {
      const page = await request<{ title: string; body_md: string }>(
        `/wiki/${itemId.value}`,
        { kbId },
      )
      data = {
        title: page.title || '无标题',
        body_md: page.body_md || '',
        kind: 'wiki',
      }
    } else {
      const note = await request<
        NoteCache & { props_json?: Record<string, any> | null }
      >(`/notes/${itemId.value}`, { kbId })
      data = {
        title: note.title || '无标题',
        body_md: note.body_md || '',
        kind: (note.kind as MentionKind) || 'doc',
        link: note.props_json?.link as LinkMeta | undefined,
        notebook: note.props_json?.notebook_doc as
          | { cells?: NotebookCellLite[] }
          | undefined,
      }
      if (data.kind === 'database') {
        const [database, rows] = await Promise.all([
          request<{ fields: DbField[] }>(`/notes/${itemId.value}/database`, { kbId }),
          request<DbRow[]>(`/notes/${itemId.value}/rows`, { kbId }),
        ])
        data.fields = Array.isArray(database?.fields) ? database.fields : []
        data.rows = Array.isArray(rows) ? rows : []
      }
    }
    cache.set(cacheKey.value, data)
    detail.value = data
    // 旧数据曾把 UUID 写进 label，拿到标题后顺手修正
    if (!label.value || label.value === itemId.value || /^[0-9a-f-]{32,}$/i.test(label.value)) {
      props.updateAttributes({ label: data.title })
    }
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

watch([itemId, target, display], () => {
  detail.value = cache.get(cacheKey.value) ?? null
  void load()
}, { immediate: true })

function openItem() {
  if (!itemId.value) return
  if (target.value === 'wiki') void router.push(`/wiki/${itemId.value}`)
  else void router.push(`/notes/${itemId.value}`)
}

/** 行内 @ 提及默认只选中节点；按住 Ctrl/⌘ 点击才跳转，避免误触。 */
function onMentionClick(event: MouseEvent) {
  if (!(event.ctrlKey || event.metaKey)) return
  event.preventDefault()
  event.stopPropagation()
  openItem()
}
</script>

<template>
  <NodeViewWrapper
    as="span"
    class="kiwi-mention-node"
    :class="[`is-${display}`, target === 'wiki' ? 'is-wiki' : '']"
    data-type="mention"
    :data-target="target"
    :data-id="itemId"
    :data-label="label"
    :data-display="display"
    @click="onMentionClick"
  >
    <span
      v-if="display === 'mention'"
      class="kiwi-mention is-mention"
      :title="`Ctrl/⌘ + 点击打开《${label}》`"
    >
      {{ mentionText(display, label) }}
    </span>

    <div
      v-else-if="display === 'card'"
      class="kiwi-note-card"
      role="link"
      tabindex="0"
      :title="`打开《${title}》`"
      @click.stop="openItem"
      @keydown.enter.prevent="openItem"
    >
      <span class="kiwi-note-card-icon" :data-kind="kind">
        <KiwiIcon :name="kindMeta.icon" :size="18" />
      </span>
      <span class="kiwi-note-card-main">
        <span class="kiwi-note-card-title">
          {{ title }}
          <span class="kiwi-note-kind">{{ kindMeta.label }}</span>
        </span>
        <span class="kiwi-note-card-excerpt">
          {{ loading ? '正在读取内容…' : failed ? '无法读取笔记内容' : excerpt }}
        </span>
      </span>
      <span class="kiwi-note-card-arrow">
        <KiwiIcon name="arrowUpRight" :size="14" />
      </span>
    </div>

    <div
      v-else
      ref="embedEl"
      class="kiwi-note-embed"
      :class="{ 'is-resized': embedHeight, 'is-resizing': resizing }"
      :style="embedHeight ? { height: `${embedHeight}px` } : undefined"
    >
      <div class="kiwi-note-embed-head">
        <span class="kiwi-note-embed-icon">
          <KiwiIcon :name="kindMeta.icon" :size="14" />
        </span>
        <span class="kiwi-note-embed-title">{{ title }}</span>
        <span class="kiwi-note-embed-badge">{{ kindMeta.label }} · 嵌入</span>
        <button type="button" class="kiwi-note-embed-open" @click.stop="openItem">
          {{ target === 'wiki' ? '打开页面' : '打开笔记' }}
          <KiwiIcon name="arrowUpRight" :size="12" />
        </button>
      </div>
      <div class="kiwi-note-embed-body">
        <div v-if="loading" class="kiwi-note-embed-state">正在读取内容…</div>
        <div v-else-if="failed" class="kiwi-note-embed-state">
          无法读取{{ target === 'wiki' ? '该 Wiki 页面' : '该笔记' }}，可能已被删除。
        </div>

        <!-- 数据表：迷你表格预览 -->
        <template v-else-if="kind === 'database'">
          <div v-if="!embedRows.length" class="kiwi-note-embed-state">这张数据表还没有记录。</div>
          <div v-else class="kiwi-mention-db">
            <div class="kiwi-mention-db-scroll">
              <table>
                <thead>
                  <tr>
                    <th
                      v-for="field in embedFields"
                      :key="field.id"
                      :style="{ minWidth: fieldMinWidth(field) }"
                    >
                      {{ field.name }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in embedRows" :key="row.id">
                    <td v-for="field in embedFields" :key="field.id">
                      <template v-if="field.type === 'attachment'">
                        <span
                          v-if="attachments(row, field).length"
                          class="kiwi-mention-attach"
                          :title="attachmentTitle(row, field)"
                        >
                          <KiwiIcon name="paperclip" :size="11" />
                          {{ attachments(row, field).length }} 个附件
                        </span>
                        <template v-else>—</template>
                      </template>
                      <template v-else>{{ cellText(row, field) }}</template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- 链接：正文优先，没有正文时展示书签信息 -->
        <template v-else-if="kind === 'link'">
          <MarkdownView v-if="embedSource.trim()" :content="embedSource" />
          <div v-else class="kiwi-mention-link">
            <div class="kiwi-mention-link-site">
              <KiwiIcon name="globe" :size="13" />
              {{ detail?.link?.site || '外部链接' }}
            </div>
            <a
              v-if="detail?.link?.final_url || detail?.link?.url"
              :href="detail?.link?.final_url || detail?.link?.url"
              target="_blank"
              rel="noopener noreferrer"
              class="kiwi-mention-link-url"
            >
              {{ detail?.link?.final_url || detail?.link?.url }}
            </a>
            <p v-if="detail?.link?.excerpt" class="kiwi-mention-link-excerpt">
              {{ detail.link.excerpt }}
            </p>
            <button
              v-if="detail?.link?.final_url || detail?.link?.url"
              type="button"
              class="kiwi-mention-link-open"
              @click.stop="openLink"
            >
              打开原网页
              <KiwiIcon name="external" :size="12" />
            </button>
          </div>
        </template>

        <!-- Notebook：只读预览单元格内容 -->
        <template v-else-if="kind === 'notebook'">
          <div class="space-y-2">
            <p class="text-[10.5px] text-slate-400">
              {{ excerpt }}
            </p>
            <div
              v-for="(cell, index) in detail?.notebook?.cells ?? []"
              :key="index"
              class="min-w-0"
            >
              <div v-if="cell.type === 'code'" class="rounded-md bg-slate-50 px-2.5 py-1.5">
                <div class="mb-0.5 text-[9px] uppercase tracking-wide text-slate-300">代码</div>
                <pre class="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-700">{{ cell.source || '' }}</pre>
              </div>
              <MarkdownView v-else-if="cell.source?.trim()" :content="cell.source" />
            </div>
            <button type="button" class="kiwi-note-embed-open" @click.stop="openItem">
              打开 Notebook
              <KiwiIcon name="arrowUpRight" :size="12" />
            </button>
          </div>
        </template>

        <!-- 画布：嵌入只给入口，避免把可交互画布塞进正文 -->
        <template v-else-if="kind === 'canvas'">
          <div class="kiwi-note-embed-state kiwi-note-canvas-state">
            <KiwiIcon name="pen" :size="18" />
            <span>画布内容请打开笔记查看与编辑。</span>
            <button type="button" class="kiwi-note-embed-open" @click.stop="openItem">
              打开画布
              <KiwiIcon name="arrowUpRight" :size="12" />
            </button>
          </div>
        </template>

        <template v-else>
          <div v-if="!embedSource.trim()" class="kiwi-note-embed-state">
            {{ target === 'wiki' ? '该页面还没有正文。' : '这篇笔记还没有正文。' }}
          </div>
          <MarkdownView v-else :content="embedSource" />
        </template>
      </div>
      <div
        v-if="props.editor.isEditable"
        class="kiwi-embed-resizer"
        title="拖动调整窗口高度，双击恢复自动高度"
        @mousedown.stop.prevent="startResize"
        @dblclick.stop="resetHeight"
      />
    </div>
  </NodeViewWrapper>
</template>
