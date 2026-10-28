<script setup lang="ts">
/** 图片节点视图：拖动缩放、裁剪、点击放大、下载、图注。 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import ImageCropDialog from './ImageCropDialog.vue'
import { toast } from '@/components/ui/toast'
import { isBlockedExternalAsset } from '@/desktop/env'

const props = defineProps(nodeViewProps)

const src = computed(() => String(props.node.attrs.src || ''))
/** 桌面版不加载远程图片，改为本地占位，且不提供裁剪 / 下载等会发起请求的操作。 */
const externalBlocked = computed(() => isBlockedExternalAsset(src.value))
const alt = computed(() => String(props.node.attrs.alt || ''))
const caption = computed(() => String(props.node.attrs.title || ''))
const width = computed(() => {
  const value = Number(props.node.attrs.width)
  return Number.isFinite(value) && value > 0 ? value : null
})

const figureEl = ref<HTMLElement | null>(null)
const imageEl = ref<HTMLImageElement | null>(null)
const captionInput = ref<HTMLInputElement | null>(null)
const captionDraft = ref(caption.value)
const captionEditing = ref(false)
const resizing = ref(false)
const previewWidth = ref<number | null>(null)
const lightboxOpen = ref(false)
const cropOpen = ref(false)

watch(caption, (value) => {
  if (!captionEditing.value) captionDraft.value = value
})

const displayWidth = computed(() => previewWidth.value ?? width.value)
const figureStyle = computed(() => {
  if (!displayWidth.value) return undefined
  return { width: `${displayWidth.value}px`, maxWidth: '100%' }
})
const imageStyle = computed(() => {
  if (!displayWidth.value) return undefined
  return { width: '100%' }
})

function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

// ---------- 拖动缩放 ----------
let resizeStartX = 0
let resizeStartWidth = 0

function startResize(event: PointerEvent) {
  if (!imageEl.value) return
  event.preventDefault()
  event.stopPropagation()
  resizeStartX = event.clientX
  resizeStartWidth = imageEl.value.getBoundingClientRect().width / uiScale()
  previewWidth.value = Math.round(resizeStartWidth)
  resizing.value = true
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', stopResize)
}

function onResizeMove(event: PointerEvent) {
  if (!resizing.value) return
  const delta = (event.clientX - resizeStartX) / uiScale()
  const parentWidth =
    (figureEl.value?.parentElement?.getBoundingClientRect().width ?? 1200) / uiScale()
  previewWidth.value = Math.min(
    Math.round(Math.max(80, parentWidth)),
    Math.round(Math.max(80, resizeStartWidth + delta)),
  )
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', stopResize)
  if (previewWidth.value) {
    props.updateAttributes({ width: previewWidth.value })
  }
  previewWidth.value = null
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('keydown', onLightboxKey)
})

// ---------- 图注 ----------
async function startCaptionEdit() {
  captionDraft.value = caption.value
  captionEditing.value = true
  await nextTick()
  captionInput.value?.focus()
  captionInput.value?.select()
}

function commitCaption() {
  if (!captionEditing.value) return
  captionEditing.value = false
  const value = captionDraft.value.trim()
  if (value !== caption.value) props.updateAttributes({ title: value })
}

function cancelCaption() {
  captionEditing.value = false
  captionDraft.value = caption.value
}

// ---------- 放大 / 下载 ----------
function openLightbox() {
  if (resizing.value || externalBlocked.value) return
  lightboxOpen.value = true
}

function onLightboxKey(event: KeyboardEvent) {
  if (event.key === 'Escape') lightboxOpen.value = false
}

watch(lightboxOpen, (open) => {
  if (open) window.addEventListener('keydown', onLightboxKey)
  else window.removeEventListener('keydown', onLightboxKey)
})

async function download() {
  if (externalBlocked.value) {
    toast.error('桌面版不加载外部图片')
    return
  }
  try {
    const res = await fetch(src.value)
    if (!res.ok) throw new Error()
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = imageFileName()
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    toast.success('已开始下载图片')
  } catch {
    window.open(src.value, '_blank', 'noopener')
  }
}

function imageFileName(): string {
  const path = src.value.split('?')[0]
  const name = path.slice(path.lastIndexOf('/') + 1)
  return name || 'image.png'
}

function onCropped(file: File) {
  const upload = (props.extension.options as any)?.upload as
    | ((file: File) => Promise<{ url: string; filename?: string }>)
    | undefined
  if (!upload) {
    toast.error('当前编辑器未配置文件上传')
    return
  }
  void (async () => {
    try {
      const result = await upload(file)
      props.updateAttributes({ src: result.url, width: null })
      toast.success('已应用裁剪')
    } catch (e: any) {
      toast.error(e.message || '上传裁剪图片失败')
    }
  })()
}
</script>

<template>
  <NodeViewWrapper
    class="kiwi-image-node my-3 flex justify-center"
    :class="{ 'is-selected': selected, 'is-resizing': resizing }"
    data-type="kiwi-image"
  >
    <figure
      ref="figureEl"
      class="group/image relative max-w-full"
      :style="figureStyle"
    >
      <!-- 悬浮工具栏：外部图片被阻止时不提供任何会发起请求的操作 -->
      <div
        v-if="!externalBlocked"
        class="absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-lg border border-white/20 bg-slate-900/70 p-0.5 opacity-0 shadow-lifted backdrop-blur transition-opacity group-hover/image:opacity-100"
        :class="selected || resizing ? '!opacity-100' : ''"
        contenteditable="false"
      >
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-white/80 transition-colors hover:bg-white/15 hover:text-white"
          title="添加图注 / 图片注解"
          @mousedown.prevent.stop
          @click.stop="startCaptionEdit"
        >
          <KiwiIcon name="type" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-white/80 transition-colors hover:bg-white/15 hover:text-white"
          title="裁剪图片"
          @mousedown.prevent.stop
          @click.stop="cropOpen = true"
        >
          <KiwiIcon name="shrink" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-white/80 transition-colors hover:bg-white/15 hover:text-white"
          title="点击放大"
          @mousedown.prevent.stop
          @click.stop="openLightbox"
        >
          <KiwiIcon name="maximize" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-white/80 transition-colors hover:bg-white/15 hover:text-white"
          title="下载原图"
          @mousedown.prevent.stop
          @click.stop="download"
        >
          <KiwiIcon name="download" :size="12" />
        </button>
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-white/80 transition-colors hover:bg-rose-500/80 hover:text-white"
          title="删除图片"
          @mousedown.prevent.stop
          @click.stop="props.deleteNode()"
        >
          <KiwiIcon name="trash" :size="12" />
        </button>
      </div>

      <img
        v-if="!externalBlocked"
        ref="imageEl"
        :src="src"
        :alt="alt"
        :title="caption"
        class="block h-auto max-w-full cursor-zoom-in rounded-lg"
        :style="imageStyle"
        draggable="false"
        @click.stop="openLightbox"
      />
      <div
        v-else
        class="flex min-h-[120px] w-full min-w-[240px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-6 text-center"
        data-external-blocked="image"
        role="img"
        :aria-label="alt ? `外部图片已禁用：${alt}` : '外部图片已禁用'"
      >
        <KiwiIcon name="image" :size="22" class="text-slate-300" />
        <span class="text-[12px] font-medium text-slate-500">外部图片已禁用</span>
        <span v-if="alt" class="max-w-full truncate text-[11px] text-slate-400">{{ alt }}</span>
        <span class="text-[10.5px] text-slate-400">桌面版只加载本机与笔记内的图片</span>
      </div>

      <figcaption
        v-if="caption && !captionEditing"
        class="mt-1.5 cursor-text text-center text-[11px] leading-relaxed text-slate-400"
        @mousedown.prevent.stop
        @click.stop="startCaptionEdit"
      >
        {{ caption }}
      </figcaption>
      <input
        v-if="captionEditing"
        ref="captionInput"
        v-model="captionDraft"
        class="mt-1.5 w-full rounded-md border border-kiwi-300 bg-white/90 px-2 py-1 text-center text-[11px] text-slate-600 outline-none focus:ring-2 focus:ring-kiwi-200"
        placeholder="输入图注或图片注解，按 Enter 保存"
        contenteditable="false"
        @keydown.enter.prevent="commitCaption"
        @keydown.esc.prevent="cancelCaption"
        @blur="commitCaption"
        @mousedown.stop
        @click.stop
      />

      <!-- 右下角缩放柄 -->
      <button
        v-if="!externalBlocked"
        type="button"
        class="absolute -bottom-1.5 -right-1.5 grid h-4 w-4 cursor-nwse-resize place-items-center rounded-sm border border-white bg-kiwi-500 text-white opacity-0 shadow transition-opacity group-hover/image:opacity-100"
        :class="selected || resizing ? '!opacity-100' : ''"
        title="拖动调整图片宽度"
        contenteditable="false"
        @pointerdown="startResize"
      >
        <span class="block h-px w-2 rotate-45 bg-white/90" />
      </button>
      <span
        v-if="resizing && previewWidth"
        class="absolute left-1 top-1 rounded bg-slate-900/75 px-1.5 py-0.5 text-[10px] tabular-nums text-white"
      >
        {{ previewWidth }} px
      </span>
    </figure>

    <!-- 大图预览 -->
    <Teleport to="body">
      <div
        v-if="lightboxOpen"
        class="fixed inset-0 z-[130] flex flex-col bg-slate-950/85 p-5 backdrop-blur-sm"
        @click.self="lightboxOpen = false"
        @keydown.esc="lightboxOpen = false"
      >
        <div class="flex shrink-0 items-center justify-end gap-2">
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            title="下载"
            @click="download"
          >
            <KiwiIcon name="download" :size="15" />
          </button>
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            title="关闭"
            @click="lightboxOpen = false"
          >
            <KiwiIcon name="close" :size="15" />
          </button>
        </div>
        <div class="flex min-h-0 flex-1 items-center justify-center">
          <img
            :src="src"
            :alt="alt"
            class="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
          />
        </div>
        <p v-if="caption" class="mt-3 shrink-0 text-center text-[12px] text-white/60">
          {{ caption }}
        </p>
      </div>
    </Teleport>

    <ImageCropDialog
      :open="cropOpen"
      :src="externalBlocked ? '' : src"
      :filename="imageFileName()"
      @close="cropOpen = false"
      @cropped="onCropped"
    />
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-image-node.is-selected figure > img {
  outline: 2px solid rgb(var(--kiwi-400) / 0.75);
  outline-offset: 2px;
}
</style>
