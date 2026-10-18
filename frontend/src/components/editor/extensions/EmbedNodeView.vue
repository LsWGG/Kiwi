<script setup lang="ts">
/**
 * 文档内嵌块：链接卡片 / 附件内容预览。
 * - 链接：标题 + 站点 + 摘要卡片；
 * - 附件：图片、视频、音频、PDF、Word/Excel/PPT、文本内联预览；
 * - 右上角操作：下载 / 大屏预览 / 删除（只读模式隐藏删除）。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import OfficeFilePreview from '@/components/attachments/OfficeFilePreview.vue'
import AttachmentPreview from '@/components/notes/database/AttachmentPreview.vue'
import type { DbAttachment } from '@/stores/noteDatabase'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const MAX_TEXT_BYTES = 512 * 1024

const attrs = computed(() => props.node.attrs as Record<string, any>)
const isLink = computed(() => attrs.value.kind === 'link')
const url = computed(() => String(attrs.value.url ?? ''))
const title = computed(() => String(attrs.value.title ?? attrs.value.filename ?? url.value))
const filename = computed(() => String(attrs.value.filename ?? attrs.value.title ?? url.value.split('/').pop() ?? ''))
const contentType = computed(() => String(attrs.value.contentType ?? ''))
const size = computed(() => Number(attrs.value.size) || 0)
const editable = useEditorEditable(props.editor)

/** 展示方式在正文中随时切换：内容卡片 / 标题超链接 / 网页嵌入。 */
type EmbedDisplay = 'content' | 'title' | 'web'
const display = computed<EmbedDisplay>(() => {
  const value = String(attrs.value.display ?? 'content')
  if (value === 'title') return 'title'
  if (value === 'web' && isLink.value) return 'web'
  return 'content'
})

function setDisplay(value: EmbedDisplay) {
  if (value === display.value) return
  const pos = props.getPos()
  if (typeof pos !== 'number') return
  const { state, view } = props.editor
  const node = state.doc.nodeAt(pos)
  if (!node || node.type.name !== 'embedBlock') return
  view.dispatch(state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, display: value }))
}

/* ---------- 嵌入窗口高度：拖动底边调整，双击恢复自动 ---------- */
function heightValue(value: unknown): number {
  const height = Number(value)
  return Number.isFinite(height) && height > 0 ? Math.min(1600, Math.max(160, Math.round(height))) : 0
}

const draftHeight = ref(heightValue(attrs.value.height))
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
  () => attrs.value.height,
  (value) => {
    if (!resizing.value) draftHeight.value = heightValue(value)
  },
)

function onResizeMove(event: MouseEvent) {
  if (!resizing.value) return
  draftHeight.value = heightValue(
    resizeStartHeight + (event.clientY - resizeStartY) / uiScale(),
  )
}

function commitHeight(value: number) {
  const pos = props.getPos()
  if (typeof pos !== 'number') return
  const { state, view } = props.editor
  const node = state.doc.nodeAt(pos)
  if (!node || node.type.name !== 'embedBlock') return
  view.dispatch(
    state.tr.setNodeMarkup(pos, undefined, {
      ...node.attrs,
      height: value > 0 ? Math.round(value) : 0,
    }),
  )
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
  commitHeight(draftHeight.value)
}

function startResize(event: MouseEvent) {
  if (event.button !== 0) return
  const handle = event.currentTarget as HTMLElement | null
  const container = handle?.closest('.embed-web, .embed-file') as HTMLElement | null
  if (!container) return
  resizeStartY = event.clientY
  resizeStartHeight = container.getBoundingClientRect().height / uiScale()
  resizing.value = true
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', stopResize)
}

function resetHeight() {
  draftHeight.value = 0
  commitHeight(0)
}

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
})

const ext = computed(() => filename.value.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? '')
const viewKind = computed(() => {
  const mime = contentType.value.toLowerCase()
  if (mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg'].includes(ext.value)) {
    return 'image'
  }
  if (mime.startsWith('video/') || ['mp4', 'webm', 'mov', 'm4v'].includes(ext.value)) return 'video'
  if (mime.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext.value)) return 'audio'
  if (mime === 'application/pdf' || ext.value === 'pdf') return 'pdf'
  if (ext.value === 'docx' || mime.includes('wordprocessingml.document')) return 'word'
  if (['xlsx', 'xlsm', 'xlsb', 'xls'].includes(ext.value) || mime.includes('spreadsheetml')) return 'excel'
  if (ext.value === 'pptx' || mime.includes('presentationml.presentation')) return 'ppt'
  if (
    mime.startsWith('text/') ||
    mime.includes('json') ||
    mime.includes('xml') ||
    ['txt', 'md', 'markdown', 'csv', 'tsv', 'log', 'json', 'yaml', 'yml', 'xml', 'js', 'ts', 'vue', 'py', 'sh', 'sql', 'css', 'html'].includes(ext.value)
  ) {
    return 'text'
  }
  return 'other'
})

const text = ref('')
const textLoading = ref(false)
const textError = ref('')
const textTruncated = ref(false)
const fullscreen = ref(false)

const previewFile = computed<DbAttachment>(() => ({
  id: String(attrs.value.id ?? url.value),
  filename: filename.value,
  url: url.value,
  content_type: contentType.value,
  size: size.value,
}))

function sizeLabel(value: number) {
  if (!value) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function loadText(target: string) {
  text.value = ''
  textError.value = ''
  textTruncated.value = false
  if (!target) return
  textLoading.value = true
  try {
    const res = await fetch(target)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    const blob = await res.blob()
    if (blob.size > MAX_TEXT_BYTES) {
      text.value = await blob.slice(0, MAX_TEXT_BYTES).text()
      textTruncated.value = true
    } else {
      text.value = await blob.text()
    }
  } catch (e: any) {
    textError.value = e?.message || '无法读取文件内容'
  } finally {
    textLoading.value = false
  }
}

let token = 0
watch(
  () => [url.value, viewKind.value, editable.value] as const,
  ([target, kind]) => {
    if (kind === 'text') {
      const run = ++token
      void loadText(target).then(() => {
        if (run !== token) return
      })
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  token += 1
})

function removeNode() {
  const pos = props.getPos()
  if (typeof pos !== 'number') return
  const { state, view } = props.editor
  const node = state.doc.nodeAt(pos)
  if (!node || node.type.name !== 'embedBlock') return
  view.dispatch(state.tr.delete(pos, pos + node.nodeSize))
}

function hideBrokenIcon(event: Event) {
  const el = event.target as HTMLElement | null
  // 隐藏整个图标框，避免加载失败后留下空白方块
  const box = el?.closest('.embed-favicon') as HTMLElement | null
  if (box) box.style.display = 'none'
  else if (el) el.style.display = 'none'
}

function openExternal(event: MouseEvent) {
  if (!isLink.value) return
  // 编辑器内普通点击不拦截，显式在新窗口打开，避免被编辑器选区逻辑吞掉
  event.preventDefault()
  if (url.value) window.open(url.value, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <NodeViewWrapper class="embed-node my-3" contenteditable="false">
    <!-- 链接：内容卡片 / 标题超链接 / 网页嵌入 -->
    <template v-if="isLink">
      <!-- 标题超链接 -->
      <div v-if="display === 'title'" class="embed-title-wrap group/embed">
        <a
          :href="url"
          target="_blank"
          rel="noopener noreferrer"
          class="embed-title-link"
          :title="url"
          @click="openExternal"
          @mousedown.stop
        >
          <span class="embed-title-favicon">
            <img v-if="attrs.favicon" :src="attrs.favicon" alt="" @error="hideBrokenIcon" />
            <KiwiIcon v-else name="link2" :size="13" class="text-sky-500" />
          </span>
          <span class="embed-title-text">{{ title }}</span>
          <KiwiIcon name="external" :size="12" class="shrink-0 text-slate-300" />
        </a>
        <div v-if="editable" class="embed-actions">
          <button type="button" class="embed-action" title="以内容卡片展示" @mousedown.prevent @click="setDisplay('content')">
            <KiwiIcon name="panelLeft" :size="12" />
          </button>
          <button type="button" class="embed-action" title="嵌入网页内容" @mousedown.prevent @click="setDisplay('web')">
            <KiwiIcon name="globe" :size="12" />
          </button>
          <button type="button" class="embed-action" title="删除链接" @mousedown.prevent @click="removeNode">
            <KiwiIcon name="trash" :size="12" />
          </button>
        </div>
      </div>

      <!-- 网页内容嵌入 -->
      <div
        v-else-if="display === 'web'"
        class="embed-web group/embed"
        :class="{ 'is-resized': draftHeight > 0, 'is-resizing': resizing }"
        :style="draftHeight ? { height: `${draftHeight}px` } : undefined"
      >
        <div class="embed-web-bar">
          <span class="embed-web-favicon">
            <img v-if="attrs.favicon" :src="attrs.favicon" alt="" @error="hideBrokenIcon" />
            <KiwiIcon v-else name="globe" :size="13" class="text-sky-500" />
          </span>
          <a
            :href="url"
            target="_blank"
            rel="noopener noreferrer"
            class="min-w-0 flex-1"
            :title="url"
            @click="openExternal"
            @mousedown.stop
          >
            <span class="embed-link-title !text-[12.5px]">{{ title }}</span>
            <span v-if="attrs.site" class="embed-link-site">{{ attrs.site }}</span>
          </a>
          <span class="flex shrink-0 items-center gap-0.5">
            <button type="button" class="embed-action" title="以内容卡片展示" @mousedown.prevent @click="setDisplay('content')">
              <KiwiIcon name="panelLeft" :size="12" />
            </button>
            <button type="button" class="embed-action" title="以标题超链接展示" @mousedown.prevent @click="setDisplay('title')">
              <KiwiIcon name="link2" :size="12" />
            </button>
            <a :href="url" target="_blank" rel="noopener noreferrer" class="embed-action" title="在新窗口打开" @click.stop @mousedown.stop>
              <KiwiIcon name="external" :size="12" />
            </a>
            <button v-if="editable" type="button" class="embed-action" title="删除网页嵌入" @mousedown.prevent @click="removeNode">
              <KiwiIcon name="trash" :size="12" />
            </button>
          </span>
        </div>
        <iframe
          :src="url"
          :title="title"
          class="embed-web-frame"
          referrerpolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          @mousedown.stop
        />
        <p class="embed-web-tip">部分网站禁止被嵌入，若显示空白可点击标题在新窗口打开</p>
        <div
          v-if="editable"
          class="embed-resize-handle"
          title="拖动调整窗口高度，双击恢复自动高度"
          @mousedown.stop.prevent="startResize"
          @dblclick.stop="resetHeight"
        >
          <span v-if="resizing" class="embed-resize-badge">{{ draftHeight }} px</span>
        </div>
      </div>

      <!-- 内容卡片 -->
      <div v-else class="embed-link-wrap group/embed">
        <a
          :href="url"
          target="_blank"
          rel="noopener noreferrer"
          class="embed-link-card"
          :title="url"
          @click="openExternal"
          @mousedown.stop
        >
          <span class="embed-favicon">
            <img v-if="attrs.favicon" :src="attrs.favicon" alt="" @error="hideBrokenIcon" />
            <KiwiIcon v-else name="link2" :size="16" class="text-sky-500" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="embed-link-title">{{ title }}</span>
            <span v-if="attrs.site" class="embed-link-site">{{ attrs.site }}</span>
            <span v-if="attrs.excerpt" class="embed-link-excerpt">{{ attrs.excerpt }}</span>
          </span>
          <KiwiIcon name="external" :size="14" class="mt-0.5 shrink-0 text-slate-300 transition-colors group-hover/embed:text-kiwi-500" />
        </a>
        <div v-if="editable" class="embed-actions">
          <button type="button" class="embed-action" title="以标题超链接展示" @mousedown.prevent @click="setDisplay('title')">
            <KiwiIcon name="link2" :size="12" />
          </button>
          <button type="button" class="embed-action" title="嵌入网页内容" @mousedown.prevent @click="setDisplay('web')">
            <KiwiIcon name="globe" :size="12" />
          </button>
          <button type="button" class="embed-action" title="删除链接卡片" @mousedown.prevent @click="removeNode">
            <KiwiIcon name="trash" :size="12" />
          </button>
        </div>
      </div>
    </template>

    <!-- 附件：内容预览 / 标题超链接 -->
    <template v-else>
      <div v-if="display === 'title'" class="embed-title-wrap group/embed">
        <a
          :href="url"
          :download="filename"
          class="embed-title-link"
          :title="filename"
          @click.stop
          @mousedown.stop
        >
          <span class="embed-title-favicon">
            <KiwiIcon name="paperclip" :size="13" class="text-slate-400" />
          </span>
          <span class="embed-title-text">{{ filename }}</span>
          <span v-if="sizeLabel(size)" class="shrink-0 text-[10.5px] tabular-nums text-slate-400">{{ sizeLabel(size) }}</span>
        </a>
        <div v-if="editable" class="embed-actions">
          <button type="button" class="embed-action" title="展开为内容预览" @mousedown.prevent @click="setDisplay('content')">
            <KiwiIcon name="panelLeft" :size="12" />
          </button>
          <a :href="url" :download="filename" class="embed-action" title="下载文件" @click.stop @mousedown.stop>
            <KiwiIcon name="download" :size="12" />
          </a>
          <button type="button" class="embed-action" title="删除内嵌附件" @mousedown.prevent @click="removeNode">
            <KiwiIcon name="trash" :size="12" />
          </button>
        </div>
      </div>

      <div
        v-else
        class="embed-file group/embed"
        :class="{ 'is-resized': draftHeight > 0, 'is-resizing': resizing }"
        :style="draftHeight ? { height: `${draftHeight}px` } : undefined"
      >
        <div class="embed-file-bar">
          <span class="flex min-w-0 items-center gap-1.5 text-[11.5px] text-slate-500">
            <KiwiIcon name="paperclip" :size="12" class="shrink-0 text-slate-400" />
            <span class="truncate font-medium text-slate-600">{{ filename }}</span>
            <span v-if="sizeLabel(size)" class="shrink-0 text-[10.5px] text-slate-400">{{ sizeLabel(size) }}</span>
          </span>
          <span class="flex shrink-0 items-center gap-0.5">
            <button type="button" class="embed-action" title="以标题超链接展示" @mousedown.prevent @click="setDisplay('title')">
              <KiwiIcon name="link2" :size="12" />
            </button>
            <a
              :href="url"
              :download="filename"
              class="embed-action"
              title="下载文件"
              @click.stop
              @mousedown.stop
            >
              <KiwiIcon name="download" :size="12" />
            </a>
            <button type="button" class="embed-action" title="大屏预览" @mousedown.prevent @click="fullscreen = true">
              <KiwiIcon name="expand" :size="12" />
            </button>
            <button v-if="editable" type="button" class="embed-action" title="删除内嵌附件" @mousedown.prevent @click="removeNode">
              <KiwiIcon name="trash" :size="12" />
            </button>
          </span>
        </div>

      <div class="embed-file-body" :class="`is-${viewKind}`">
        <img
          v-if="viewKind === 'image'"
          :src="url"
          :alt="filename"
          class="embed-image"
          @mousedown.stop
          @click="fullscreen = true"
        />
        <video v-else-if="viewKind === 'video'" :src="url" controls class="embed-video" @mousedown.stop />
        <audio v-else-if="viewKind === 'audio'" :src="url" controls class="w-[min(520px,90%)]" @mousedown.stop />
        <iframe
          v-else-if="viewKind === 'pdf'"
          :src="url"
          class="embed-pdf"
          :title="filename"
          @mousedown.stop
        />
        <OfficeFilePreview
          v-else-if="viewKind === 'word' || viewKind === 'excel' || viewKind === 'ppt'"
          :url="url"
          :filename="filename"
          :content-type="contentType"
          fit="width"
          :class="viewKind === 'ppt' ? 'embed-office-ppt' : 'embed-office'"
        />
        <div v-else-if="viewKind === 'text'" class="embed-text">
          <pre class="m-0">{{ textLoading ? '载入中…' : textError || text }}</pre>
          <p v-if="textTruncated" class="border-t border-slate-200 px-3 py-1 text-[10.5px] text-amber-500">
            文件较大，仅显示前 512 KB，可下载后查看完整内容。
          </p>
        </div>
        <div v-else class="embed-fallback">
          <KiwiIcon name="file" :size="30" class="text-slate-300" />
          <p class="mt-2 text-[12px] text-slate-500">{{ filename }}</p>
          <p class="mt-0.5 text-[11px] text-slate-400">该类型暂不支持内联预览，可下载后查看</p>
          <a :href="url" :download="filename" class="kiwi-btn-primary mt-3 !py-1.5 !text-xs" @click.stop @mousedown.stop>
            <KiwiIcon name="download" :size="12" />
            下载文件
          </a>
        </div>
        </div>
        <div
          v-if="editable"
          class="embed-resize-handle"
          title="拖动调整窗口高度，双击恢复自动高度"
          @mousedown.stop.prevent="startResize"
          @dblclick.stop="resetHeight"
        >
          <span v-if="resizing" class="embed-resize-badge">{{ draftHeight }} px</span>
        </div>
      </div>
    </template>

    <AttachmentPreview
      :open="fullscreen"
      :file="previewFile"
      @close="fullscreen = false"
    />
  </NodeViewWrapper>
</template>

<style scoped>
.embed-node {
  position: relative;
}
.embed-link-wrap {
  position: relative;
}
.embed-title-wrap {
  @apply relative;
}
.embed-title-link {
  @apply flex items-center gap-2 rounded-lg border border-slate-200/70 bg-white px-2.5 py-1.5 no-underline transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/40;
}
.embed-title-favicon {
  @apply grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded;
}
.embed-title-favicon img {
  @apply h-4 w-4 object-contain;
}
.embed-title-text {
  @apply min-w-0 flex-1 truncate text-[12.5px] font-medium text-slate-700;
}
.embed-web {
  @apply relative flex flex-col overflow-hidden rounded-xl border border-slate-200/80 bg-white;
}
.embed-web.is-resized .embed-web-frame {
  height: auto;
  min-height: 0;
  flex: 1 1 auto;
}
.embed-web.is-resized .embed-web-tip {
  flex: 0 0 auto;
}
.embed-web-bar {
  @apply flex items-center gap-2 border-b border-slate-200/70 bg-slate-50/70 px-2.5 py-1.5;
}
.embed-web-favicon {
  @apply grid h-6 w-6 shrink-0 place-items-center overflow-hidden rounded-md border border-slate-200/70 bg-white;
}
.embed-web-favicon img {
  @apply h-4 w-4 object-contain;
}
.embed-web-frame {
  @apply block h-[480px] w-full border-0 bg-white;
}
.embed-web-tip {
  @apply border-t border-slate-100 px-3 py-1 text-[10.5px] text-slate-400;
}
.embed-link-card {
  @apply flex items-start gap-3 rounded-xl border border-slate-200/80 bg-white px-3.5 py-3 no-underline transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/40;
}
.embed-favicon {
  @apply mt-0.5 grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-lg border border-slate-200/70 bg-slate-50;
}
.embed-favicon img {
  @apply h-5 w-5 object-contain;
}
.embed-link-title {
  @apply block truncate text-[13.5px] font-medium text-slate-700;
}
.embed-link-site {
  @apply mt-0.5 block truncate text-[11px] text-slate-400;
}
.embed-link-excerpt {
  @apply mt-1 line-clamp-2 text-[11.5px] leading-relaxed text-slate-500;
}
.embed-file {
  @apply relative flex flex-col overflow-hidden rounded-xl border border-slate-200/80 bg-white;
}
.embed-file.is-resized .embed-file-body {
  min-height: 0;
  flex: 1 1 auto;
  overflow: auto;
  padding-bottom: 12px;
}
.embed-file.is-resized .embed-pdf {
  height: 100%;
}
.embed-file.is-resized .embed-text pre {
  max-height: none;
}
.embed-web.is-resizing,
.embed-file.is-resizing {
  user-select: none;
}
.embed-resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 5;
  display: flex;
  height: 12px;
  cursor: ns-resize;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.embed-web:hover .embed-resize-handle,
.embed-file:hover .embed-resize-handle,
.embed-web.is-resizing .embed-resize-handle,
.embed-file.is-resizing .embed-resize-handle {
  opacity: 1;
}
.embed-resize-handle::after {
  content: '';
  width: 38px;
  height: 4px;
  border-radius: 999px;
  background: #cbd5e1;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.85);
}
.embed-resize-badge {
  position: absolute;
  right: 8px;
  bottom: 14px;
  padding: 1px 6px;
  border-radius: 5px;
  color: #fff;
  font-size: 10px;
  line-height: 1.5;
  background: rgba(51, 65, 85, 0.82);
  pointer-events: none;
}
.embed-file-bar {
  @apply flex h-9 items-center justify-between gap-2 border-b border-slate-200/70 bg-slate-50/70 px-2.5;
}
.embed-action {
  @apply grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white hover:text-kiwi-600;
}
/* 操作按钮放在组件外部的上方，避免遮挡卡片右侧的分享 / 外链图标 */
.embed-actions {
  @apply absolute -top-8 right-0 z-10 flex items-center gap-0.5 rounded-lg border border-slate-200/80 bg-white/95 p-0.5 opacity-0 shadow-sm backdrop-blur transition-opacity group-hover/embed:opacity-100;
}
.embed-actions .embed-action {
  @apply hover:bg-slate-100;
}
.embed-file-body {
  @apply flex justify-center bg-slate-50/40;
}
.embed-file-body.is-image,
.embed-file-body.is-video {
  @apply bg-slate-100/70;
}
.embed-image {
  @apply max-h-[560px] max-w-full cursor-zoom-in object-contain;
}
.embed-video {
  @apply max-h-[560px] w-full bg-black;
}
.embed-pdf {
  @apply h-[560px] w-full border-0 bg-white;
}
.embed-office {
  @apply h-[560px] w-full;
}
/* PPT：高度由幻灯片比例决定，避免固定 560px 高度在下方留白 */
.embed-office-ppt {
  @apply w-full;
}
.embed-text {
  @apply w-full bg-white;
}
.embed-text pre {
  @apply max-h-[560px] overflow-auto p-3 text-[11.5px] leading-relaxed whitespace-pre-wrap break-words text-slate-600;
}
.embed-fallback {
  @apply flex w-full flex-col items-center px-6 py-10;
}
</style>
