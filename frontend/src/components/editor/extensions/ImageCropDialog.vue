<script setup lang="ts">
/** 图片裁剪：拖拽选框 / 四角缩放 / 常用比例，确认后在画布中裁剪并输出新文件。 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ open: boolean; src: string; filename?: string }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'cropped', file: File): void
}>()

interface CropRect {
  x: number
  y: number
  w: number
  h: number
}

const imageEl = ref<HTMLImageElement | null>(null)
const imageReady = ref(false)
const natural = ref({ width: 0, height: 0 })
const crop = ref<CropRect>({ x: 0.06, y: 0.06, w: 0.88, h: 0.88 })
const activeAspect = ref<number | null>(null)
const applying = ref(false)

type DragMode = 'move' | 'nw' | 'ne' | 'sw' | 'se'
const drag = ref<{
  mode: DragMode
  startX: number
  startY: number
  rect: CropRect
} | null>(null)

const fileName = computed(() => {
  const raw = props.filename || 'image'
  const dot = raw.lastIndexOf('.')
  const stem = dot > 0 ? raw.slice(0, dot) : raw
  return `${stem}-cropped.png`
})

const outputSize = computed(() => {
  const w = Math.max(1, Math.round(crop.value.w * natural.value.width))
  const h = Math.max(1, Math.round(crop.value.h * natural.value.height))
  return `${w} × ${h}px`
})

const cropStyle = computed(() => ({
  left: `${crop.value.x * 100}%`,
  top: `${crop.value.y * 100}%`,
  width: `${crop.value.w * 100}%`,
  height: `${crop.value.h * 100}%`,
}))

watch(
  () => props.open,
  (open) => {
    if (!open) {
      drag.value = null
      applying.value = false
      return
    }
    crop.value = { x: 0.06, y: 0.06, w: 0.88, h: 0.88 }
    activeAspect.value = null
    imageReady.value = false
  },
)

async function onImageLoad(event: Event) {
  const img = event.target as HTMLImageElement
  natural.value = { width: img.naturalWidth || img.width, height: img.naturalHeight || img.height }
  imageReady.value = true
  await nextTick()
}

function imageRect(): DOMRect | null {
  return imageEl.value?.getBoundingClientRect() ?? null
}

function beginDrag(event: PointerEvent, mode: DragMode) {
  if (!imageReady.value) return
  event.preventDefault()
  event.stopPropagation()
  const rect = imageRect()
  if (!rect) return
  drag.value = {
    mode,
    startX: event.clientX,
    startY: event.clientY,
    rect: { ...crop.value },
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', endDrag)
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function onDragMove(event: PointerEvent) {
  const state = drag.value
  const rect = imageRect()
  if (!state || !rect) return
  const dx = (event.clientX - state.startX) / Math.max(rect.width, 1)
  const dy = (event.clientY - state.startY) / Math.max(rect.height, 1)
  const min = 0.05
  const start = state.rect
  let { x, y, w, h } = start

  if (state.mode === 'move') {
    x = clamp(start.x + dx, 0, 1 - start.w)
    y = clamp(start.y + dy, 0, 1 - start.h)
  } else {
    if (state.mode.includes('w')) {
      const right = start.x + start.w
      x = clamp(start.x + dx, 0, right - min)
      w = right - x
    }
    if (state.mode.includes('e')) {
      const right = clamp(start.x + start.w + dx, start.x + min, 1)
      w = right - start.x
    }
    if (state.mode.includes('n')) {
      const bottom = start.y + start.h
      y = clamp(start.y + dy, 0, bottom - min)
      h = bottom - y
    }
    if (state.mode.includes('s')) {
      const bottom = clamp(start.y + start.h + dy, start.y + min, 1)
      h = bottom - start.y
    }
  }

  crop.value = { x, y, w, h }
  activeAspect.value = null
}

function endDrag() {
  drag.value = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', endDrag)
}

function applyAspect(ratio: number | null) {
  activeAspect.value = ratio
  if (!ratio || !natural.value.width || !natural.value.height) return
  const { width: nw, height: nh } = natural.value
  const centerX = crop.value.x + crop.value.w / 2
  const centerY = crop.value.y + crop.value.h / 2
  // 目标像素比例 ratio = (w * nw) / (h * nh)
  let w = crop.value.w
  let h = (w * nw) / ratio / nh
  if (h > 1) {
    h = 1
    w = (h * nh * ratio) / nw
  }
  if (w > 1) {
    w = 1
    h = (w * nw) / ratio / nh
  }
  const x = clamp(centerX - w / 2, 0, 1 - w)
  const y = clamp(centerY - h / 2, 0, 1 - h)
  crop.value = { x, y, w, h }
}

function resetCrop() {
  crop.value = { x: 0, y: 0, w: 1, h: 1 }
  activeAspect.value = null
}

async function apply() {
  const img = imageEl.value
  const nw = natural.value.width
  const nh = natural.value.height
  if (!img || !nw || !nh) return
  applying.value = true
  try {
    const sx = Math.round(crop.value.x * nw)
    const sy = Math.round(crop.value.y * nh)
    const sw = Math.max(1, Math.round(crop.value.w * nw))
    const sh = Math.max(1, Math.round(crop.value.h * nh))
    const canvas = document.createElement('canvas')
    canvas.width = sw
    canvas.height = sh
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('浏览器不支持画布裁剪')
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('裁剪失败，请重试')
    emit('cropped', new File([blob], fileName.value, { type: 'image/png' }))
    emit('close')
  } catch (e: any) {
    toast.error(e?.message || '裁剪失败，图片可能来自跨域地址')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <KiwiModal :open="open" title="裁剪图片" max-w="max-w-3xl" @close="emit('close')">
    <div class="space-y-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="preset in [
            { label: '自由', value: null },
            { label: '1:1', value: 1 },
            { label: '4:3', value: 4 / 3 },
            { label: '16:9', value: 16 / 9 },
            { label: '3:4', value: 3 / 4 },
          ]"
          :key="preset.label"
          type="button"
          class="rounded-md border px-2 py-1 text-[10.5px] transition-colors"
          :class="
            activeAspect === preset.value
              ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
              : 'border-slate-200 bg-white/70 text-slate-500 hover:border-kiwi-200 hover:text-kiwi-600'
          "
          @click="applyAspect(preset.value)"
        >
          {{ preset.label }}
        </button>
        <button
          type="button"
          class="ml-auto rounded-md px-2 py-1 text-[10.5px] text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-600"
          @click="resetCrop"
        >
          重置
        </button>
        <span class="text-[10px] tabular-nums text-slate-400">{{ outputSize }}</span>
      </div>

      <div class="grid max-h-[58vh] place-items-center overflow-auto rounded-xl bg-slate-900/90 p-4">
        <div class="relative inline-block max-h-full select-none">
          <img
            ref="imageEl"
            :src="src"
            alt="待裁剪图片"
            class="block max-h-[52vh] max-w-full"
            draggable="false"
            @load="onImageLoad"
          />
          <template v-if="imageReady">
            <div class="pointer-events-none absolute inset-0 bg-slate-900/45" />
            <div
              class="absolute cursor-move border border-white/90 shadow-[0_0_0_9999px_rgba(15,23,42,0.45)]"
              :style="cropStyle"
              @pointerdown="beginDrag($event, 'move')"
            >
              <!-- 三分构图辅助线 -->
              <span class="pointer-events-none absolute inset-y-0 left-1/3 w-px bg-white/25" />
              <span class="pointer-events-none absolute inset-y-0 left-2/3 w-px bg-white/25" />
              <span class="pointer-events-none absolute inset-x-0 top-1/3 h-px bg-white/25" />
              <span class="pointer-events-none absolute inset-x-0 top-2/3 h-px bg-white/25" />
              <button
                type="button"
                class="absolute -left-1.5 -top-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-slate-500 bg-white"
                @pointerdown="beginDrag($event, 'nw')"
              />
              <button
                type="button"
                class="absolute -right-1.5 -top-1.5 h-3.5 w-3.5 cursor-nesw-resize rounded-sm border border-slate-500 bg-white"
                @pointerdown="beginDrag($event, 'ne')"
              />
              <button
                type="button"
                class="absolute -bottom-1.5 -left-1.5 h-3.5 w-3.5 cursor-nesw-resize rounded-sm border border-slate-500 bg-white"
                @pointerdown="beginDrag($event, 'sw')"
              />
              <button
                type="button"
                class="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-slate-500 bg-white"
                @pointerdown="beginDrag($event, 'se')"
              />
            </div>
          </template>
        </div>
      </div>
      <p class="text-[10.5px] leading-relaxed text-slate-400">
        拖动画框移动裁剪范围，拖动四角调整大小。裁剪会生成一张新图片并上传，原图保留在附件中。
      </p>
    </div>

    <div class="mt-4 flex justify-end gap-2">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button
        class="kiwi-btn-primary"
        :disabled="!imageReady || applying"
        @click="apply"
      >
        <KiwiIcon :name="applying ? 'loader' : 'check'" :size="13" :spin="applying" />
        {{ applying ? '处理中…' : '应用裁剪' }}
      </button>
    </div>
  </KiwiModal>
</template>
