<script setup lang="ts">
/**
 * 颜色选择器：预设色板 + 面板内自定义取色 + 清除。
 * 工具栏、选区气泡菜单与设置页共用；面板挂到 html 下，避免被工具栏或气泡菜单裁剪。
 *
 * 自定义取色完全由组件绘制（明度/饱和度面板 + 色相条 + Hex 输入），
 * 不调用浏览器原生 `input[type=color]`，避免系统默认取色弹窗破坏统一 UI。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { normalizeColor } from './extensions/textStyle'

const props = withDefaults(
  defineProps<{
    value?: string | null
    /** 当前选区 / 光标处是否已有颜色 */
    active?: boolean
    variant?: 'toolbar' | 'bubble'
    title?: string
    /** 触发按钮与面板标题使用的图标 */
    icon?: string
    /** 面板分组标题，如「文字颜色」「填充颜色」 */
    label?: string
    /** 无颜色时触发按钮与取色器的兜底颜色 */
    fallback?: string
    clearLabel?: string
    clearHint?: string
    /** 是否显示「清除颜色」条目（设置页等场景可关闭） */
    clearable?: boolean
  }>(),
  {
    value: '#1F2937',
    active: false,
    variant: 'toolbar',
    title: '文字颜色',
    icon: 'type',
    label: '文字颜色',
    fallback: '#1F2937',
    clearLabel: '清除颜色',
    clearHint: '恢复默认文字色',
    clearable: true,
  },
)

const emit = defineEmits<{
  (e: 'select', color: string): void
  (e: 'clear'): void
}>()

const PALETTE = [
  { value: '#1F2937', label: '深灰' },
  { value: '#4B5563', label: '灰色' },
  { value: '#9CA3AF', label: '浅灰' },
  { value: '#DC2626', label: '红色' },
  { value: '#EA580C', label: '橙色' },
  { value: '#CA8A04', label: '琥珀' },
  { value: '#16A34A', label: '绿色' },
  { value: '#0D9488', label: '青色' },
  { value: '#0891B2', label: '天蓝' },
  { value: '#2563EB', label: '蓝色' },
  { value: '#4F46E5', label: '靛蓝' },
  { value: '#9333EA', label: '紫色' },
  { value: '#DB2777', label: '品红' },
  { value: '#E11D48', label: '玫红' },
]

const current = computed(() => normalizeColor(props.value) ?? props.fallback)
const hasColor = computed(() => !!normalizeColor(props.value))
const triggerClass = computed(() => [
  props.variant === 'bubble'
    ? 'relative grid h-6 w-6 place-items-center rounded-md text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700'
    : 'relative grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700',
  props.active ? 'bg-kiwi-50 text-kiwi-700' : '',
])

// ---------- 自定义取色（HSV，全自绘） ----------

const customOpen = ref(false)
const hue = ref(0)
const saturation = ref(0)
const brightness = ref(100)
const hexInput = ref('')
const svArea = ref<HTMLElement | null>(null)
const hueBar = ref<HTMLElement | null>(null)

/**
 * 给定 HSV 生成十六进制颜色；h 允许 360（拖动到色相条最右端）。
 */
function hsvToHex(h: number, s: number, v: number) {
  const hh = ((h % 360) + 360) % 360
  const sat = s / 100
  const val = v / 100
  const c = val * sat
  const x = c * (1 - Math.abs(((hh / 60) % 2) - 1))
  const m = val - c
  let rgb: [number, number, number]
  if (hh < 60) rgb = [c, x, 0]
  else if (hh < 120) rgb = [x, c, 0]
  else if (hh < 180) rgb = [0, c, x]
  else if (hh < 240) rgb = [0, x, c]
  else if (hh < 300) rgb = [x, 0, c]
  else rgb = [c, 0, x]
  return `#${rgb
    .map((channel) =>
      Math.round((channel + m) * 255)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`.toUpperCase()
}

/** Hex → HSV（0–360 / 0–100 / 0–100）。 */
function hexToHsv(hex: string) {
  const raw = (normalizeColor(hex) ?? props.fallback).replace('#', '')
  const r = parseInt(raw.slice(0, 2), 16) / 255
  const g = parseInt(raw.slice(2, 4), 16) / 255
  const b = parseInt(raw.slice(4, 6), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const delta = max - min
  let h = 0
  if (delta > 0) {
    if (max === r) h = 60 * (((g - b) / delta) % 6)
    else if (max === g) h = 60 * ((b - r) / delta + 2)
    else h = 60 * ((r - g) / delta + 4)
  }
  if (h < 0) h += 360
  return {
    h: Math.round(h),
    s: Math.round((max > 0 ? delta / max : 0) * 100),
    v: Math.round(max * 100),
  }
}

const draftColor = computed(() =>
  hsvToHex(hue.value, saturation.value, brightness.value),
)
const svBackground = computed(
  () =>
    `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, hsl(${hue.value} 100% 50%))`,
)
const hueBackground =
  'linear-gradient(to right, #FF0000 0%, #FFFF00 17%, #00FF00 33%, #00FFFF 50%, #0000FF 67%, #FF00FF 83%, #FF0000 100%)'
const draftThumbStyle = computed(() => ({
  left: `${saturation.value}%`,
  top: `${100 - brightness.value}%`,
  background: draftColor.value,
}))
const hueThumbStyle = computed(() => ({
  left: `${(hue.value / 360) * 100}%`,
  background: `hsl(${hue.value} 100% 50%)`,
}))

let dragTarget: 'sv' | 'hue' | null = null

function clampRatio(value: number) {
  return Math.max(0, Math.min(1, value))
}

function syncHexInput() {
  hexInput.value = draftColor.value
}

function updateFromPointer(event: PointerEvent) {
  if (dragTarget === 'sv' && svArea.value) {
    const rect = svArea.value.getBoundingClientRect()
    saturation.value = Math.round(
      clampRatio((event.clientX - rect.left) / rect.width) * 100,
    )
    brightness.value = Math.round(
      (1 - clampRatio((event.clientY - rect.top) / rect.height)) * 100,
    )
    syncHexInput()
  } else if (dragTarget === 'hue' && hueBar.value) {
    const rect = hueBar.value.getBoundingClientRect()
    hue.value = Math.round(
      clampRatio((event.clientX - rect.left) / rect.width) * 360,
    )
    syncHexInput()
  }
}

function onPointerMove(event: PointerEvent) {
  updateFromPointer(event)
}

function endDrag() {
  dragTarget = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', endDrag)
}

function beginDrag(target: 'sv' | 'hue', event: PointerEvent) {
  event.preventDefault()
  dragTarget = target
  updateFromPointer(event)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', endDrag)
}

function toggleCustom() {
  if (!customOpen.value) {
    const hsv = hexToHsv(current.value)
    hue.value = hsv.h
    saturation.value = hsv.s
    brightness.value = hsv.v
    syncHexInput()
  }
  customOpen.value = !customOpen.value
}

function onHexInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value.trim()
  hexInput.value = raw
  const normalized = normalizeColor(raw.startsWith('#') ? raw : `#${raw}`)
  if (!normalized) return
  const hsv = hexToHsv(normalized)
  hue.value = hsv.h
  saturation.value = hsv.s
  brightness.value = hsv.v
}

function applyDraft(close: () => void) {
  emit(
    'select',
    normalizeColor(hexInput.value.startsWith('#') ? hexInput.value : `#${hexInput.value}`) ??
      draftColor.value,
  )
  close()
}

onBeforeUnmount(endDrag)

// ---------- 预设色板 ----------

function sameColor(a: string, b: string) {
  return normalizeColor(a)?.toUpperCase() === normalizeColor(b)?.toUpperCase()
}

function isLight(hex: string) {
  const raw = normalizeColor(hex)?.replace('#', '')
  if (!raw || raw.length !== 6) return true
  const r = parseInt(raw.slice(0, 2), 16)
  const g = parseInt(raw.slice(2, 4), 16)
  const b = parseInt(raw.slice(4, 6), 16)
  return (r * 299 + g * 587 + b * 114) / 1000 > 186
}

function choose(color: string, close: () => void) {
  emit('select', normalizeColor(color) ?? color)
  close()
}

function clear(close: () => void) {
  emit('clear')
  close()
}
</script>

<template>
  <KiwiDropdown width="w-60" align="left">
    <template #trigger="{ open }">
      <button
        type="button"
        :class="triggerClass"
        :title="title"
        data-color-trigger
        :aria-expanded="open"
      >
        <KiwiIcon :name="icon" :size="variant === 'bubble' ? 13 : 14" />
        <span
          class="absolute rounded-full"
          :class="
            variant === 'bubble'
              ? 'bottom-0.5 left-1 right-1 h-[3px]'
              : 'bottom-[3px] left-1.5 right-1.5 h-[3px]'
          "
          :style="{ background: hasColor ? current : fallback }"
        />
      </button>
    </template>
    <template #default="{ close }">
      <!-- 与「扩展组件」菜单保持同一套视觉：分组标题 + 图标磁贴条目 -->
      <p class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
        {{ label }}
      </p>
      <div class="grid grid-cols-7 gap-1.5 px-2 pb-2 pt-1">
        <button
          v-for="item in PALETTE"
          :key="item.value"
          type="button"
          class="relative grid h-6 w-6 place-items-center rounded-full border border-black/5 shadow-sm transition-transform hover:scale-110 focus:outline-none"
          :class="
            sameColor(item.value, current)
              ? 'ring-2 ring-kiwi-400 ring-offset-1 ring-offset-white'
              : ''
          "
          :style="{ background: item.value }"
          :title="item.label"
          :data-color-swatch="item.value"
          @mousedown.prevent
          @click="choose(item.value, close)"
        >
          <KiwiIcon
            v-if="sameColor(item.value, current)"
            name="check"
            :size="11"
            :class="isLight(item.value) ? 'text-slate-700' : 'text-white'"
          />
        </button>
      </div>
      <div class="border-t border-slate-100 pt-1">
        <button
          type="button"
          class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-kiwi-50"
          title="自定义颜色"
          data-color-custom
          @mousedown.prevent
          @click="toggleCustom"
        >
          <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100">
            <span
              class="h-3.5 w-3.5 rounded-full border border-slate-200"
              style="
                background: conic-gradient(
                  from 0deg,
                  #ef4444,
                  #f59e0b,
                  #22c55e,
                  #06b6d4,
                  #6366f1,
                  #d946ef,
                  #ef4444
                );
              "
            />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block text-[12px] font-medium text-slate-700">自定义颜色</span>
            <span class="block text-[10px] text-slate-400">
              {{ current.toUpperCase() }} · 面板内取色
            </span>
          </span>
          <KiwiIcon
            name="chevron"
            :size="12"
            class="shrink-0 text-slate-400 transition-transform"
            :class="customOpen ? 'rotate-180' : ''"
          />
        </button>

        <!-- 全自绘取色面板：不使用浏览器原生 color 控件 -->
        <div
          v-if="customOpen"
          class="mx-1 mb-1 mt-1 rounded-lg border border-slate-200/80 bg-white/50 p-2"
          data-color-custom-panel
          @mousedown.stop
        >
          <div
            ref="svArea"
            class="relative h-24 w-full cursor-crosshair touch-none overflow-hidden rounded-md border border-black/5"
            :style="{ background: svBackground }"
            data-color-sv
            @pointerdown="beginDrag('sv', $event)"
          >
            <span
              class="pointer-events-none absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(15,23,42,0.35)]"
              :style="draftThumbStyle"
            />
          </div>
          <div
            ref="hueBar"
            class="relative mt-2.5 h-3 w-full cursor-pointer touch-none rounded-full border border-black/5"
            :style="{ background: hueBackground }"
            data-color-hue
            @pointerdown="beginDrag('hue', $event)"
          >
            <span
              class="pointer-events-none absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(15,23,42,0.35)]"
              :style="hueThumbStyle"
            />
          </div>
          <div class="mt-2 flex items-center gap-1.5">
            <span
              class="h-7 w-7 shrink-0 rounded-md border border-slate-200"
              :style="{ background: draftColor }"
              data-color-preview
            />
            <input
              :value="hexInput"
              class="h-7 min-w-0 flex-1 rounded-md border border-slate-200/80 bg-white/70 px-2 font-mono text-[11px] uppercase text-slate-600 outline-none transition-colors focus:border-kiwi-300"
              maxlength="7"
              spellcheck="false"
              aria-label="Hex 颜色值"
              data-color-hex
              @input="onHexInput"
              @keydown.enter.prevent="applyDraft(close)"
            />
            <button
              type="button"
              class="h-7 shrink-0 rounded-md px-2 text-[11px] text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
              @mousedown.prevent
              @click="customOpen = false"
            >
              取消
            </button>
            <button
              type="button"
              class="h-7 shrink-0 rounded-md bg-kiwi-600 px-2.5 text-[11px] font-medium text-white transition-colors hover:bg-kiwi-700"
              data-color-apply
              @mousedown.prevent
              @click="applyDraft(close)"
            >
              应用
            </button>
          </div>
        </div>

        <button
          v-if="clearable"
          type="button"
          class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-kiwi-50 disabled:cursor-default disabled:opacity-40"
          :disabled="!active"
          :title="clearLabel"
          data-color-clear
          @mousedown.prevent
          @click="clear(close)"
        >
          <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
            <KiwiIcon name="eraser" :size="13" />
          </span>
          <span class="min-w-0">
            <span class="block text-[12px] font-medium text-slate-700">{{ clearLabel }}</span>
            <span class="block text-[10px] text-slate-400">{{ clearHint }}</span>
          </span>
        </button>
      </div>
    </template>
  </KiwiDropdown>
</template>
