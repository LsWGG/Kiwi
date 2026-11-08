<script setup lang="ts">
/**
 * 画布块：非编辑态展示静态 SVG，点击后加载 jvs-draw 白板。
 * 预览区不显示滚动条：100% 完整显示整张画布，放大后用拖拽平移查看。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import DrawEditor from '@/components/draw/DrawEditor.vue'
import DrawSettings from '@/components/draw/DrawSettings.vue'
import { drawDocToSvg } from '@/components/draw/drawSvgExport'
import { drawDocToBestPng, drawDocToBestSvg } from '@/components/draw/drawFidelityExport'
import {
  DRAW_PREFERENCE_DEFAULTS,
  drawDocHasContent,
  drawDocStats,
  emptyDrawDoc,
  normalizeDrawDoc,
  type DrawPreferences,
  type JvsDrawDoc,
} from '@/components/draw/types'
import { useEditorEditable } from './useEditorEditable'

const props = defineProps(nodeViewProps)

const editable = useEditorEditable(props.editor)
const editing = ref(false)
// NodeViewWrapper 是组件，模板 ref 拿到的是组件实例，DOM 在 $el 上。
const root = ref<any>(null)
const drawRef = ref<any>(null)
const showPrefs = ref(false)
const fullscreen = ref(false)
const prefs = ref<DrawPreferences>(DRAW_PREFERENCE_DEFAULTS)
const previewEl = ref<HTMLElement | null>(null)
/** 预览缩放：100% 为完整显示整张画布，50%–200% 由用户自定义。 */
const previewZoom = ref(1)
const ZOOM_MIN = 50
const ZOOM_MAX = 200
const ZOOM_STEP = 10
const zoomPct = computed(() => Math.round(previewZoom.value * 100))
/** 预览框最大高度，与样式里的 max-height 保持一致。 */
const PREVIEW_MAX_HEIGHT = 440
/** 预览框可用宽度，随布局变化更新。 */
const previewBoxWidth = ref(0)
/**
 * 高保真预览图：jvs-draw 渲染器输出，与画布 / 导出图片一致。
 * 运行时加载完成前先显示静态 SVG，避免预览区空白。
 */
const fidelitySrc = ref('')
const fidelitySize = ref<{ width: number; height: number } | null>(null)
let fidelityToken = 0
/** 内容超出预览框时允许拖拽平移（不出现滚动条）。 */
const previewOverflow = ref(false)
const panning = ref(false)
let previewObserver: ResizeObserver | null = null
let panStart: { x: number; y: number; left: number; top: number } | null = null
let panMoved = false
let bodyOverflow = ''

const doc = computed<JvsDrawDoc>(
  () => normalizeDrawDoc(props.node.attrs.doc) ?? emptyDrawDoc(),
)
const stats = computed(() => drawDocStats(doc.value))
const hasContent = computed(() => drawDocHasContent(doc.value))
const svg = computed(() => {
  if (!hasContent.value) return ''
  try {
    return drawDocToSvg(doc.value)
  } catch {
    return ''
  }
})

/** 静态 SVG 的原始尺寸；高保真图片就绪前用它计算基准缩放。 */
const svgSize = computed(() => {
  const viewBox = /viewBox="([^"]+)"/.exec(svg.value)?.[1]
  if (!viewBox) return null
  const parts = viewBox.trim().split(/[\s,]+/).map(Number)
  const width = parts[2]
  const height = parts[3]
  return width > 0 && height > 0 ? { width, height } : null
})

const intrinsicSize = computed(() => fidelitySize.value ?? svgSize.value)

/**
 * 100% 缩放时的基准宽度：整张画布完整放进预览框（宽高都不超出）。
 * 只读预览没有高度限制，直接铺满正文宽度。
 */
const fitWidth = computed(() => {
  const box = previewBoxWidth.value
  const size = intrinsicSize.value
  if (!box || !size) return 0
  if (!editable.value) return box
  return Math.min(box, (PREVIEW_MAX_HEIGHT * size.width) / size.height)
})

const canvasStyle = computed(() => {
  if (!fitWidth.value) return { width: '100%' }
  return { width: `${Math.floor(fitWidth.value * previewZoom.value)}px` }
})

function revokeFidelity() {
  if (!fidelitySrc.value) return
  URL.revokeObjectURL(fidelitySrc.value)
  fidelitySrc.value = ''
}

/**
 * 用与画布、导出图片相同的 jvs-draw 渲染器生成预览。
 * 运行时按需加载；失败时保留静态 SVG，预览仍可查看。
 */
async function renderFidelityPreview() {
  const token = ++fidelityToken
  // 阅读态不加载 20MB 级白板运行时：静态 SVG 与分享页 / 导出同源，
  // 也避免异步替换 DOM 造成预览闪烁。高保真预览只服务编辑态。
  if (!hasContent.value || editing.value || !editable.value) {
    revokeFidelity()
    fidelitySize.value = null
    return
  }
  try {
    const blob = await drawDocToBestPng(doc.value, 2)
    if (token !== fidelityToken) return
    const bitmap = await createImageBitmap(blob)
    const size = { width: bitmap.width, height: bitmap.height }
    bitmap.close()
    if (token !== fidelityToken) return
    const url = URL.createObjectURL(blob)
    revokeFidelity()
    fidelitySrc.value = url
    fidelitySize.value = size
  } catch (error) {
    // 高保真渲染不可用时继续显示静态 SVG。
    console.warn('画布预览渲染失败，使用静态预览', error)
  }
}

function setPreviewZoom(pct: number) {
  previewZoom.value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(pct))) / 100
}

function zoomIn() {
  setPreviewZoom(zoomPct.value + ZOOM_STEP)
}

function zoomOut() {
  setPreviewZoom(zoomPct.value - ZOOM_STEP)
}

function resetPreviewZoom() {
  previewZoom.value = 1
}

/** 预览滚动区不显示滚动条，用拖拽平移代替。 */
function updatePreviewOverflow() {
  const el = previewEl.value
  previewOverflow.value =
    !!el && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
}

/** body 在 4K 屏带 CSS zoom，指针位移要折算回布局像素，拖拽才跟手。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function onPreviewPointerDown(event: PointerEvent) {
  const el = previewEl.value
  if (!el || event.button !== 0 || !previewOverflow.value) return
  panStart = {
    x: event.clientX,
    y: event.clientY,
    left: el.scrollLeft,
    top: el.scrollTop,
  }
  panMoved = false
  panning.value = true
  try {
    el.setPointerCapture(event.pointerId)
  } catch {
    // 指针已失效时忽略，仍然可以点击进入编辑。
  }
}

function onPreviewPointerMove(event: PointerEvent) {
  const el = previewEl.value
  if (!panStart || !el) return
  const scale = uiScale()
  const dx = (event.clientX - panStart.x) / scale
  const dy = (event.clientY - panStart.y) / scale
  if (!panMoved && Math.hypot(dx, dy) > 3) panMoved = true
  if (!panMoved) return
  event.preventDefault()
  el.scrollLeft = panStart.left - dx
  el.scrollTop = panStart.top - dy
}

function onPreviewPointerUp(event: PointerEvent) {
  if (!panStart) return
  try {
    previewEl.value?.releasePointerCapture(event.pointerId)
  } catch {
    // 未捕获时无需释放。
  }
  panStart = null
  panning.value = false
}

function onPreviewClick() {
  // 拖拽平移结束的那次 click 不触发编辑。
  if (panMoved) {
    panMoved = false
    return
  }
  startEdit()
}

watch(
  [svg, editing, editable],
  () => {
    void nextTick(updatePreviewOverflow)
    void renderFidelityPreview()
  },
  { immediate: true, flush: 'post' },
)

watch(
  [canvasStyle, fidelitySize],
  () => void nextTick(updatePreviewOverflow),
  { flush: 'post' },
)

watch(previewEl, (el) => {
  previewObserver?.disconnect()
  previewObserver = null
  if (!el) return
  previewObserver = new ResizeObserver(() => {
    previewBoxWidth.value = el.clientWidth
    updatePreviewOverflow()
  })
  previewObserver.observe(el)
  previewBoxWidth.value = el.clientWidth
  void nextTick(updatePreviewOverflow)
})

function uploadImage(file: File): Promise<string> | string {
  const upload = (props.extension as any).options?.upload as
    | ((file: File) => Promise<{ url: string } | string>)
    | null
    | undefined
  if (!upload) throw new Error('当前笔记不支持上传图片')
  return Promise.resolve(upload(file)).then((result) =>
    typeof result === 'string' ? result : result.url,
  )
}

function onUpdate(next: JvsDrawDoc) {
  props.updateAttributes({ doc: next })
}

function startEdit() {
  if (!editable.value || editing.value) return
  editing.value = true
}

function finish() {
  drawRef.value?.flush?.()
  showPrefs.value = false
  fullscreen.value = false
  editing.value = false
}

/** 进入全屏白板：内嵌区域太矮，文字 / 连线在弹层里更容易操作。 */
function openFullscreen() {
  if (!editable.value) return
  drawRef.value?.flush?.()
  showPrefs.value = false
  editing.value = true
  fullscreen.value = true
}

/** 退出全屏但保留编辑态，回到正文中的画布继续。 */
function closeFullscreen() {
  if (!fullscreen.value) return
  drawRef.value?.flush?.()
  showPrefs.value = false
  fullscreen.value = false
}

function onFullscreenKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !fullscreen.value) return
  const target = event.target as HTMLElement | null
  // 文本编辑、搜索框和 jvs-draw 自己的弹层先用 Esc，避免直接退出全屏。
  if (
    target?.closest(
      'input, textarea, [contenteditable="true"], .el-overlay, .el-dialog, .el-drawer, .el-popper, [role="dialog"], [role="menu"], [role="listbox"]',
    )
  ) {
    return
  }
  event.preventDefault()
  closeFullscreen()
}

watch(fullscreen, (open) => {
  if (open) {
    bodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onFullscreenKeydown)
  } else {
    document.body.style.overflow = bodyOverflow
    window.removeEventListener('keydown', onFullscreenKeydown)
  }
})

/** 白板挂载完成后同步一次偏好，避免面板显示默认值。 */
function syncPrefs() {
  const instance = drawRef.value
  if (typeof instance?.getPreferences === 'function') {
    prefs.value = instance.getPreferences()
  }
}

function onPrefsUpdate(patch: Partial<DrawPreferences>) {
  prefs.value = { ...prefs.value, ...patch }
  drawRef.value?.setPreferences?.(patch)
}

async function downloadSvg() {
  if (!hasContent.value) return
  // 使用与编辑态同一套渲染器，下载后的文件才和画布一致。
  const source = await drawDocToBestSvg(doc.value)
  if (!source) return
  const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'kiwi-canvas.svg'
  a.click()
  URL.revokeObjectURL(url)
}

function remove() {
  props.deleteNode()
}

/** 点击画布外的正文 / 其他块时收起重型编辑器。 */
function onOutsidePointerDown(event: PointerEvent) {
  if (!editing.value || fullscreen.value) return
  const target = event.target as HTMLElement | null
  if (!target) return
  const rootEl = (root.value?.$el ?? root.value) as HTMLElement | null
  if (rootEl?.contains(target)) return
  // jvs-draw / Element Plus 的浮层挂到 body，不能把它们当成「点击外部」。
  if (
    target.closest(
      '.el-popper, .el-overlay, .el-dialog, .el-drawer, .el-message-box, .el-notification, [role="dialog"], [role="menu"], [role="listbox"], [role="tooltip"]',
    )
  ) {
    return
  }
  finish()
}

watch(editing, (value) => {
  document.removeEventListener('pointerdown', onOutsidePointerDown, true)
  if (value) document.addEventListener('pointerdown', onOutsidePointerDown, true)
  if (!value) fullscreen.value = false
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutsidePointerDown, true)
  previewObserver?.disconnect()
  previewObserver = null
  fidelityToken += 1
  revokeFidelity()
  if (fullscreen.value) {
    document.body.style.overflow = bodyOverflow
    window.removeEventListener('keydown', onFullscreenKeydown)
  }
})
</script>

<template>
  <NodeViewWrapper
    ref="root"
    class="kiwi-draw-block"
    :class="{ 'is-selected': selected, 'is-editing': editing, 'is-readonly': !editable }"
    data-type="kiwi-draw"
    contenteditable="false"
  >
    <div v-if="editable" class="kiwi-draw-toolbar" contenteditable="false">
      <span class="kiwi-draw-tag"><KiwiIcon name="pen" :size="11" />画布</span>
      <span class="kiwi-draw-stats">
        {{ stats.nodes }} 个节点 · {{ stats.edges }} 条连线
      </span>
      <template v-if="editing">
        <button
          type="button"
          class="kiwi-draw-action"
          title="模板库"
          aria-label="模板库"
          @mousedown.prevent
          @click="drawRef?.openTemplates?.()"
        >
          <KiwiIcon name="layoutTemplate" :size="12" />
        </button>
        <button
          type="button"
          class="kiwi-draw-action"
          title="信息图"
          aria-label="信息图"
          @mousedown.prevent
          @click="drawRef?.openInfographic?.()"
        >
          <KiwiIcon name="infographic" :size="12" />
        </button>
      </template>
      <div class="ml-auto flex items-center gap-1">
        <template v-if="!editing && hasContent">
          <button
            type="button"
            class="kiwi-draw-action"
            title="缩小预览"
            aria-label="缩小预览"
            :disabled="zoomPct <= ZOOM_MIN"
            @mousedown.prevent
            @click="zoomOut"
          >
            <KiwiIcon name="minus" :size="12" />
          </button>
          <button
            type="button"
            class="kiwi-draw-zoom"
            :title="zoomPct === 100 ? '完整显示画布' : '恢复完整显示画布'"
            @mousedown.prevent
            @click="resetPreviewZoom"
          >
            {{ zoomPct }}%
          </button>
          <button
            type="button"
            class="kiwi-draw-action"
            title="放大预览"
            aria-label="放大预览"
            :disabled="zoomPct >= ZOOM_MAX"
            @mousedown.prevent
            @click="zoomIn"
          >
            <KiwiIcon name="plus" :size="12" />
          </button>
          <span class="kiwi-draw-sep" aria-hidden="true" />
        </template>
        <button
          v-if="editing"
          type="button"
          class="kiwi-draw-action"
          :class="{ 'is-active': showPrefs }"
          title="画布偏好设置"
          @mousedown.prevent
          @click="showPrefs = !showPrefs"
        >
          <KiwiIcon name="settings" :size="12" />
        </button>
        <button
          type="button"
          class="kiwi-draw-action"
          title="全屏编辑"
          aria-label="全屏编辑"
          @mousedown.prevent
          @click.stop="openFullscreen"
        >
          <KiwiIcon name="expand" :size="12" />
        </button>
        <button
          type="button"
          class="kiwi-draw-action"
          title="下载 SVG"
          @mousedown.prevent
          @click="downloadSvg"
        >
          <KiwiIcon name="download" :size="12" />
        </button>
        <template v-if="editing">
          <button
            type="button"
            class="kiwi-draw-btn is-primary"
            @mousedown.prevent
            @click="finish"
          >
            完成
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            class="kiwi-draw-action"
            title="编辑画布"
            @mousedown.prevent
            @click="startEdit"
          >
            <KiwiIcon name="edit" :size="12" />
          </button>
          <button
            type="button"
            class="kiwi-draw-action is-danger"
            title="删除画布"
            @mousedown.prevent
            @click="remove"
          >
            <KiwiIcon name="trash" :size="12" />
          </button>
        </template>
      </div>
    </div>

    <div v-if="editing && !fullscreen" class="kiwi-draw-edit" contenteditable="false">
      <DrawEditor
        ref="drawRef"
        :model-value="doc"
        :upload="uploadImage"
        @ready="syncPrefs"
        @update:model-value="onUpdate"
      />
      <DrawSettings
        v-if="showPrefs"
        :prefs="prefs"
        @update="onPrefsUpdate"
        @close="showPrefs = false"
      />
    </div>
    <div
      v-else-if="!fullscreen"
      ref="previewEl"
      class="kiwi-draw-view"
      :class="{
        'is-empty': !hasContent,
        'is-clickable': editable,
        'is-pannable': previewOverflow,
        'is-panning': panning,
      }"
      @mousedown.stop
      @click="onPreviewClick"
      @pointerdown="onPreviewPointerDown"
      @pointermove="onPreviewPointerMove"
      @pointerup="onPreviewPointerUp"
      @pointercancel="onPreviewPointerUp"
    >
      <div v-if="fidelitySrc" class="kiwi-draw-canvas" :style="canvasStyle">
        <img
          class="kiwi-draw-image"
          :src="fidelitySrc"
          alt="画布预览"
          draggable="false"
        />
      </div>
      <div v-else-if="svg" class="kiwi-draw-canvas" :style="canvasStyle">
        <div class="kiwi-draw-svg" v-html="svg" />
      </div>
      <div v-else-if="editable" class="kiwi-draw-empty">
        <span class="kiwi-draw-empty-icon"><KiwiIcon name="pen" :size="18" /></span>
        <span class="kiwi-draw-empty-title">点击开始绘制</span>
        <span class="kiwi-draw-empty-hint">拖拽图形、连线与文字，像白板一样自由排版</span>
      </div>
      <span v-else class="kiwi-draw-empty-text">这张画布还没有内容</span>
    </div>

    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-200"
        enter-from-class="opacity-0"
        leave-active-class="transition-opacity duration-150"
        leave-to-class="opacity-0"
      >
        <div
          v-if="fullscreen"
          class="kiwi-draw-fullscreen fixed inset-0 z-[320] flex flex-col bg-white"
          contenteditable="false"
        >
          <header
            class="flex h-12 shrink-0 items-center gap-2 border-b border-slate-200/80 px-4"
            contenteditable="false"
          >
            <span class="kiwi-draw-tag"><KiwiIcon name="pen" :size="11" />画布</span>
            <span class="kiwi-draw-stats">
              {{ stats.nodes }} 个节点 · {{ stats.edges }} 条连线
            </span>
            <div class="ml-auto flex items-center gap-1">
              <button
                type="button"
                class="kiwi-draw-action"
                title="模板库"
                aria-label="模板库"
                @mousedown.prevent
                @click="drawRef?.openTemplates?.()"
              >
                <KiwiIcon name="layoutTemplate" :size="12" />
              </button>
              <button
                type="button"
                class="kiwi-draw-action"
                title="信息图"
                aria-label="信息图"
                @mousedown.prevent
                @click="drawRef?.openInfographic?.()"
              >
                <KiwiIcon name="infographic" :size="12" />
              </button>
              <button
                type="button"
                class="kiwi-draw-action"
                :class="{ 'is-active': showPrefs }"
                title="画布偏好设置"
                aria-label="画布偏好设置"
                @mousedown.prevent
                @click="showPrefs = !showPrefs"
              >
                <KiwiIcon name="settings" :size="12" />
              </button>
              <button
                type="button"
                class="kiwi-draw-action"
                title="下载 SVG"
                aria-label="下载 SVG"
                @mousedown.prevent
                @click="downloadSvg"
              >
                <KiwiIcon name="download" :size="12" />
              </button>
              <button
                type="button"
                class="kiwi-draw-btn is-primary"
                @mousedown.prevent
                @click="finish"
              >
                完成
              </button>
              <button
                type="button"
                class="kiwi-draw-action"
                title="退出全屏（Esc）"
                aria-label="退出全屏"
                @mousedown.prevent
                @click="closeFullscreen"
              >
                <KiwiIcon name="close" :size="14" />
              </button>
            </div>
          </header>
          <div class="relative min-h-0 flex-1" contenteditable="false">
            <DrawEditor
              ref="drawRef"
              :model-value="doc"
              :upload="uploadImage"
              @ready="syncPrefs"
              @update:model-value="onUpdate"
            />
            <DrawSettings
              v-if="showPrefs"
              :prefs="prefs"
              @update="onPrefsUpdate"
              @close="showPrefs = false"
            />
          </div>
        </div>
      </Transition>
    </Teleport>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-draw-block {
  margin: 0.75rem 0;
  border-radius: 12px;
  border: 1px solid rgb(var(--theme-border));
  background: rgb(var(--theme-app) / calc(0.75 * var(--theme-surface-opacity)));
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.kiwi-draw-block.is-readonly {
  margin: 0.9rem 0;
  border: 0;
  background: transparent;
  border-radius: 0;
}
.kiwi-draw-block.is-selected,
.kiwi-draw-block.is-editing {
  border-color: rgb(var(--kiwi-300));
  box-shadow: 0 0 0 3px rgb(var(--kiwi-100) / 0.55);
}
.kiwi-draw-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 10px;
  border-bottom: 1px solid rgb(226 232 240 / 0.8);
  color: rgb(100 116 139);
  font-size: 11px;
}
.kiwi-draw-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  color: rgb(var(--theme-text-secondary));
}
.kiwi-draw-stats {
  color: rgb(148 163 184);
  font-variant-numeric: tabular-nums;
}
.kiwi-draw-action {
  padding: 3px;
  border-radius: 6px;
  color: rgb(148 163 184);
}
.kiwi-draw-action:hover,
.kiwi-draw-action.is-active {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-draw-action:disabled {
  opacity: 0.35;
  pointer-events: none;
}
.kiwi-draw-action.is-danger:hover {
  color: rgb(220 38 38);
  background: rgb(254 242 242);
}
.kiwi-draw-zoom {
  min-width: 34px;
  padding: 2px 2px;
  border-radius: 6px;
  color: rgb(100 116 139);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.kiwi-draw-zoom:hover {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-draw-sep {
  width: 1px;
  height: 14px;
  margin: 0 2px;
  background: rgb(var(--theme-border));
}
.kiwi-draw-btn {
  border-radius: 6px;
  padding: 2px 9px;
  color: rgb(var(--theme-text-secondary));
  border: 1px solid rgb(var(--theme-border));
  background: rgb(var(--theme-surface));
}
.kiwi-draw-btn.is-primary {
  color: #fff;
  border-color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-600));
}
.kiwi-draw-btn:hover {
  opacity: 0.86;
}
.kiwi-draw-edit {
  position: relative;
  height: 600px;
  max-height: 72vh;
  min-height: 460px;
  overflow: hidden;
  border-radius: 0 0 12px 12px;
}
.kiwi-draw-view {
  position: relative;
  display: block;
  min-height: 120px;
  max-height: 440px;
  padding: 0;
  /* 不显示滚动条：超出部分通过缩放 / 拖拽平移查看。 */
  overflow: hidden;
  background: rgb(var(--theme-surface));
}
.kiwi-draw-view.is-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
}
.kiwi-draw-view.is-clickable {
  cursor: pointer;
}
.kiwi-draw-view.is-clickable:hover {
  background: rgb(var(--theme-app) / calc(0.9 * var(--theme-surface-opacity)));
}
.kiwi-draw-view.is-pannable {
  cursor: grab;
}
.kiwi-draw-view.is-panning {
  cursor: grabbing;
}
.kiwi-draw-block.is-readonly .kiwi-draw-view {
  min-height: 0;
  max-height: none;
  padding: 4px 0;
  cursor: default;
}
.kiwi-draw-canvas {
  width: 100%;
  margin: 0 auto;
}
.kiwi-draw-svg {
  width: 100%;
  overflow: hidden;
  line-height: 0;
  user-select: none;
}
/* 选择器要比 `.kiwi-editor .ProseMirror img` 更具体，覆盖正文图片的边距与描边。 */
.kiwi-draw-view .kiwi-draw-image {
  display: block;
  width: 100%;
  height: auto;
  margin: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  user-select: none;
  -webkit-user-drag: none;
}
/* 预览铺满正文宽度：SVG 按自身比例缩放，避免四周留出灰色空带。 */
.kiwi-draw-svg :deep(svg) {
  display: block;
  width: 100%;
  height: auto;
  margin: 0 auto;
}
.kiwi-draw-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 26px 16px;
  color: rgb(100 116 139);
}
.kiwi-draw-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}
.kiwi-draw-empty-title {
  font-size: 13px;
  font-weight: 500;
  color: rgb(51 65 85);
}
.kiwi-draw-empty-hint {
  font-size: 11px;
  color: rgb(148 163 184);
}
.kiwi-draw-empty-text {
  color: rgb(148 163 184);
  font-size: 12px;
}
</style>
