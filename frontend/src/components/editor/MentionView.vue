<script setup lang="ts">
/**
 * @ 提及节点视图：行内提及 / 标题超链接 / 独占一行的大内容卡片 / 嵌入内容。
 * 支持全部笔记类型（文档、数据表、导入、链接、画布）与 Wiki 页面。
 * 卡片右上角与附件一致提供：大屏预览、分栏打开、切换展示形式。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, type NodeViewProps } from '@tiptap/vue-3'
import { useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import NotePreviewDialog from '@/components/notes/NotePreviewDialog.vue'
import { useKbsStore } from '@/stores/kbs'
import { usePaneOpen } from '@/components/notes/workspace/usePaneOpen'
import {
  attachmentsOf,
  databaseCellText,
  fetchNotePreview,
  type NotePreviewData,
  type NotePreviewField,
  type NotePreviewRow,
} from '@/components/notes/notePreviewData'
import {
  mentionText,
  normalizeMentionDisplay,
  type MentionDisplay,
} from './extensions/mentionTypes'

type MentionKind = NotePreviewData['kind']
type MentionTarget = 'note' | 'wiki'

const props = defineProps<NodeViewProps>()

const router = useRouter()
const kbs = useKbsStore()
const paneOpen = usePaneOpen()

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

const cache = new Map<string, NotePreviewData>()
const detail = ref<NotePreviewData | null>(cache.get(cacheKey.value) ?? null)
const loading = ref(false)
const failed = ref(false)
/** 大屏预览窗口：与附件预览一致的遮罩层。 */
const notePreviewOpen = ref(false)

const editable = computed(() => props.editor.isEditable)

function openPreview() {
  if (!itemId.value) return
  notePreviewOpen.value = true
}

function closePreview() {
  notePreviewOpen.value = false
}

/** 在分栏工作区中并排打开这条 @ 提及的笔记。 */
function openInPane() {
  if (target.value !== 'note') return
  if (paneOpen.openNotePane(itemId.value, kbs.currentKbId || undefined)) {
    notePreviewOpen.value = false
  }
}

/** 卡片 / 标题 / 嵌入之间切换，沿用提及序列化里的 display 属性。 */
function setDisplay(next: MentionDisplay) {
  if (next === display.value) return
  const pos = props.getPos()
  const ed = props.editor
  if (typeof pos !== 'number' || !ed) {
    props.updateAttributes({ display: next })
    return
  }
  const { state, view } = ed
  const node = state.doc.nodeAt(pos)
  if (!node || node.type.name !== 'mention') {
    props.updateAttributes({ display: next })
    return
  }
  const tr = state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, display: next })
  const afterPos = pos + node.nodeSize
  const after = tr.doc.nodeAt(afterPos)
  if (next === 'mention') {
    // 从独占一行的卡片切回行内时补一个空格，避免与后文粘连
    if (after?.isText && after.text && !/^\s/.test(after.text)) {
      tr.insertText(' ', afterPos)
    }
  } else if (after?.isText && after.text?.startsWith(' ')) {
    // 卡片 / 嵌入自带外边距，去掉插入时留下的空格
    tr.delete(afterPos, afterPos + 1)
  }
  view.dispatch(tr)
}

/** 行内提及悬浮预览：按需加载一次，鼠标移开后延迟关闭。 */
const hovered = ref(false)
let hideTimer: number | null = null
const previewOpen = computed(
  () =>
    display.value === 'mention' &&
    hovered.value &&
    (loading.value || failed.value || !!detail.value),
)

function onMentionEnter() {
  if (display.value !== 'mention') return
  if (hideTimer !== null) {
    window.clearTimeout(hideTimer)
    hideTimer = null
  }
  hovered.value = true
}

function onMentionLeave() {
  if (display.value !== 'mention') return
  if (hideTimer !== null) window.clearTimeout(hideTimer)
  hideTimer = window.setTimeout(() => {
    hovered.value = false
    hideTimer = null
  }, 140)
}

watch(hovered, (value) => {
  if (value) void load()
})

onBeforeUnmount(() => {
  if (hideTimer !== null) window.clearTimeout(hideTimer)
})

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
  sheet: { icon: 'table', label: '表格' },
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
  if (kind.value === 'sheet') {
    const sheets = Array.isArray(detail.value?.sheet?.sheets) ? detail.value.sheet.sheets : []
    const cells = sheets.reduce(
      (sum, sheet) => sum + Object.keys(sheet.cells ?? {}).length,
      0,
    )
    return `表格 · ${sheets.length} 张工作表 · ${cells} 个单元格`
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

/** 悬浮预览与卡片里的迷你表格：只取前几列 / 几行，保持轻盈。 */
const previewFields = computed(() => embedFields.value.slice(0, 4))
const previewRows = computed(() => embedRows.value.slice(0, 3))
const hasDbPreview = computed(
  () => kind.value === 'database' && previewFields.value.length > 0 && previewRows.value.length > 0,
)

/** 按字段类型给列一个合理的最小宽度，内容多时再横向滚动。 */
function fieldMinWidth(field: NotePreviewField): string {
  if (field.type === 'attachment') return '80px'
  if (field.type === 'date') return '96px'
  if (field.type === 'rating' || field.type === 'number') return '60px'
  if (field.type === 'progress') return '104px'
  if (field.type === 'checkbox') return '56px'
  if (field.type === 'select' || field.type === 'multi_select') return '80px'
  if (field.type === 'url') return '140px'
  return '110px'
}

const attachments = attachmentsOf
const cellText = databaseCellText

/** 附件在嵌入预览里只显示数量，悬停可看到文件名，避免撑高整行。 */
function attachmentTitle(row: NotePreviewRow, field: NotePreviewField): string {
  return attachments(row, field)
    .map((file) => String(file.filename ?? file.name ?? ''))
    .filter(Boolean)
    .join('\n')
}

function openLink() {
  const meta = detail.value?.link
  const url = meta?.final_url || meta?.url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

async function load() {
  if (detail.value || loading.value || !itemId.value) return
  // 行内提及平时只显示标题，悬停预览时才按需拉取正文。
  if (display.value === 'mention' && !hovered.value) return
  const kbId = kbs.currentKbId
  if (!kbId) return
  loading.value = true
  failed.value = false
  try {
    const data = await fetchNotePreview(kbId, itemId.value, target.value)
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

watch([itemId, target, display, () => kbs.currentKbId], () => {
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
    class="kiwi-mention-node group/mention"
    :class="[`is-${display}`, target === 'wiki' ? 'is-wiki' : '']"
    data-type="mention"
    :data-target="target"
    :data-id="itemId"
    :data-label="label"
    :data-display="display"
    @click="onMentionClick"
    @mouseenter="onMentionEnter"
    @mouseleave="onMentionLeave"
  >
    <template v-if="display === 'mention'">
      <span
        class="kiwi-mention is-mention"
        :title="`Ctrl/⌘ + 点击打开《${label}》`"
      >
        {{ mentionText(display, label) }}
      </span>

      <!-- 行内提及悬浮预览：鼠标停留时拉取笔记内容，表格显示迷你数据 -->
      <span
        v-if="previewOpen"
      class="kiwi-mention-preview"
      contenteditable="false"
      @mouseenter="onMentionEnter"
      @mouseleave="onMentionLeave"
      @click.stop
    >
      <span class="kiwi-mention-preview-head">
        <span class="kiwi-note-card-icon" :data-kind="kind">
          <KiwiIcon :name="kindMeta.icon" :size="14" />
        </span>
        <span class="kiwi-mention-preview-title">{{ title }}</span>
        <span class="kiwi-note-kind">{{ kindMeta.label }}</span>
      </span>
      <span v-if="loading && !detail" class="kiwi-mention-preview-state">正在读取内容…</span>
      <span v-else-if="failed && !detail" class="kiwi-mention-preview-state">
        无法读取{{ target === 'wiki' ? '该 Wiki 页面' : '该笔记' }}
      </span>
      <template v-else>
        <span v-if="hasDbPreview" class="kiwi-mention-preview-db">
          <span class="kiwi-mention-db">
            <span class="kiwi-mention-db-scroll">
              <table>
                <thead>
                  <tr>
                    <th v-for="field in previewFields" :key="field.id">{{ field.name }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in previewRows" :key="row.id">
                    <td v-for="field in previewFields" :key="field.id">
                      <template v-if="field.type === 'attachment'">
                        <span v-if="attachments(row, field).length" class="kiwi-mention-attach">
                          <KiwiIcon name="paperclip" :size="10" />
                          {{ attachments(row, field).length }}
                        </span>
                        <template v-else>—</template>
                      </template>
                      <template v-else>{{ cellText(row, field) }}</template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </span>
          </span>
          <span class="kiwi-mention-preview-more">
            共 {{ embedRows.length }} 条记录 · {{ embedFields.length }} 个字段
          </span>
        </span>
        <span v-else class="kiwi-mention-preview-text">{{ excerpt }}</span>
      </template>
      <span class="kiwi-mention-preview-foot">
        <span>{{ target === 'wiki' ? 'Wiki 页面' : '笔记' }} · Ctrl/⌘ + 点击打开</span>
        <button type="button" class="kiwi-mention-preview-open" @click.stop="openPreview">
          <KiwiIcon name="expand" :size="10" />
          大屏预览
        </button>
      </span>
      </span>
    </template>

    <!-- 标题超链接：只显示图标 + 标题，右键或右上角可切换形式 -->
    <div v-else-if="display === 'title'" class="kiwi-note-title-wrap">
      <a
        class="kiwi-note-title-link"
        :href="target === 'wiki' ? `/wiki/${itemId}` : `/notes/${itemId}`"
        :title="`打开《${title}》`"
        @click.prevent.stop="openItem"
        @mousedown.stop
      >
        <span class="kiwi-note-title-icon">
          <KiwiIcon :name="kindMeta.icon" :size="13" />
        </span>
        <span class="kiwi-note-title-text">{{ title }}</span>
        <span class="kiwi-note-kind">{{ kindMeta.label }}</span>
        <KiwiIcon name="external" :size="12" class="shrink-0 text-slate-300" />
      </a>
      <div v-if="editable" class="kiwi-note-actions">
        <button type="button" class="kiwi-note-action" title="大屏预览" @mousedown.prevent @click.stop="openPreview">
          <KiwiIcon name="expand" :size="12" />
        </button>
        <button
          v-if="target === 'note'"
          type="button"
          class="kiwi-note-action"
          title="在分栏中打开"
          @mousedown.prevent
          @click.stop="openInPane"
        >
          <KiwiIcon name="columns" :size="12" />
        </button>
        <button type="button" class="kiwi-note-action" title="以卡片展示" @mousedown.prevent @click.stop="setDisplay('card')">
          <KiwiIcon name="panelLeft" :size="12" />
        </button>
        <button type="button" class="kiwi-note-action" title="嵌入正文" @mousedown.prevent @click.stop="setDisplay('embed')">
          <KiwiIcon name="layoutTemplate" :size="12" />
        </button>
      </div>
    </div>

    <template v-else-if="display === 'card'">
      <div
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
          <span v-if="hasDbPreview" class="kiwi-note-card-db">
            <span class="kiwi-mention-db">
              <span class="kiwi-mention-db-scroll">
                <table>
                  <thead>
                    <tr>
                      <th v-for="field in previewFields" :key="field.id">{{ field.name }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in previewRows" :key="row.id">
                      <td v-for="field in previewFields" :key="field.id">
                        <template v-if="field.type === 'attachment'">
                          <span v-if="attachments(row, field).length" class="kiwi-mention-attach">
                            <KiwiIcon name="paperclip" :size="10" />
                            {{ attachments(row, field).length }}
                          </span>
                          <template v-else>—</template>
                        </template>
                        <template v-else>{{ cellText(row, field) }}</template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </span>
            </span>
          </span>
        </span>
        <span class="kiwi-note-card-arrow">
          <KiwiIcon name="arrowUpRight" :size="14" />
        </span>
      </div>
      <div v-if="editable" class="kiwi-note-actions">
        <button type="button" class="kiwi-note-action" title="大屏预览" @mousedown.prevent @click.stop="openPreview">
          <KiwiIcon name="expand" :size="12" />
        </button>
        <button
          v-if="target === 'note'"
          type="button"
          class="kiwi-note-action"
          title="在分栏中打开"
          @mousedown.prevent
          @click.stop="openInPane"
        >
          <KiwiIcon name="columns" :size="12" />
        </button>
        <button type="button" class="kiwi-note-action" title="以标题超链接展示" @mousedown.prevent @click.stop="setDisplay('title')">
          <KiwiIcon name="link2" :size="12" />
        </button>
        <button type="button" class="kiwi-note-action" title="嵌入正文" @mousedown.prevent @click.stop="setDisplay('embed')">
          <KiwiIcon name="layoutTemplate" :size="12" />
        </button>
      </div>
    </template>

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
        <span v-if="editable" class="kiwi-note-embed-actions">
          <button type="button" class="kiwi-note-embed-action" title="大屏预览" @mousedown.prevent @click.stop="openPreview">
            <KiwiIcon name="expand" :size="12" />
          </button>
          <button
            v-if="target === 'note'"
            type="button"
            class="kiwi-note-embed-action"
            title="在分栏中打开"
            @mousedown.prevent
            @click.stop="openInPane"
          >
            <KiwiIcon name="columns" :size="12" />
          </button>
          <button type="button" class="kiwi-note-embed-action" title="以卡片展示" @mousedown.prevent @click.stop="setDisplay('card')">
            <KiwiIcon name="panelLeft" :size="12" />
          </button>
          <button type="button" class="kiwi-note-embed-action" title="以标题超链接展示" @mousedown.prevent @click.stop="setDisplay('title')">
            <KiwiIcon name="link2" :size="12" />
          </button>
        </span>
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

        <!-- 表格：嵌入只给入口，避免把完整工作簿塞进正文 -->
        <template v-else-if="kind === 'sheet'">
          <div class="kiwi-note-embed-state kiwi-note-canvas-state">
            <KiwiIcon name="table" :size="18" />
            <span>{{ excerpt }}。请打开笔记查看与编辑。</span>
            <button type="button" class="kiwi-note-embed-open" @click.stop="openItem">
              打开表格
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

    <!-- 大屏预览：与附件预览一致的遮罩窗口，按笔记类型渲染只读内容 -->
    <NotePreviewDialog
      :open="notePreviewOpen"
      :note-id="itemId"
      :target="target"
      :label="label"
      :preload="detail"
      @close="closePreview"
    />
  </NodeViewWrapper>
</template>

<style scoped>
/* 标题超链接：与附件「标题超链接」保持同一视觉 */
.kiwi-note-title-wrap {
  @apply relative;
}
.kiwi-note-title-link {
  @apply flex items-center gap-2 rounded-lg border border-slate-200/70 bg-gradient-to-r from-kiwi-50/70 via-white to-white px-2.5 py-1.5 no-underline shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-all hover:border-kiwi-300 hover:shadow-[0_4px_14px_-8px_rgba(15,23,42,0.25)];
}
.kiwi-note-title-icon {
  @apply grid h-6 w-6 shrink-0 place-items-center rounded-md border border-kiwi-100 bg-white text-kiwi-600;
}
.kiwi-note-title-text {
  @apply min-w-0 flex-1 truncate text-[12.5px] font-medium text-slate-700;
}

/* 卡片 / 标题右上角的悬浮操作，与内嵌附件卡片一致 */
.kiwi-note-actions {
  @apply absolute -top-8 right-0 z-10 flex items-center gap-0.5 rounded-lg border border-slate-200/80 bg-white/95 p-0.5 opacity-0 shadow-sm backdrop-blur transition-opacity group-hover/mention:opacity-100;
}
.kiwi-note-action {
  @apply grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-kiwi-600;
}

/* 嵌入窗口标题栏的常驻操作 */
.kiwi-note-embed-actions {
  @apply flex shrink-0 items-center gap-0.5;
}
.kiwi-note-embed-action {
  @apply grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white hover:text-kiwi-600;
}

.kiwi-mention-preview-foot {
  @apply flex items-center justify-between gap-2;
}
.kiwi-mention-preview-open {
  @apply inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[10px] text-kiwi-600 transition-colors hover:bg-kiwi-50;
}
</style>
