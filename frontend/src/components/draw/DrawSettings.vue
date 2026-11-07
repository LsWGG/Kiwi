<script setup lang="ts">
/**
 * 画布偏好设置：与文本笔记「页面设置」一致的停靠面板。
 *
 * 只负责展示与选择，值来自 jvs-draw 的 appState（由 DrawEditor 读写），
 * 随笔记文档一起持久化。
 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import EditorColorPicker from '@/components/editor/EditorColorPicker.vue'
import { useThemeStore } from '@/stores/theme'
import type { DrawGridType, DrawPreferences, DrawShapeTheme } from './types'

const props = defineProps<{
  prefs: DrawPreferences
  /** 作为布局中的固定侧栏（默认是覆盖式抽屉） */
  docked?: boolean
}>()

const emit = defineEmits<{
  (e: 'update', patch: Partial<DrawPreferences>): void
  (e: 'close'): void
}>()

interface BackgroundOption {
  value: string
  label: string
}

const LIGHT_BACKGROUNDS: BackgroundOption[] = [
  { value: '#ffffff', label: '纯白' },
  { value: '#f8fafc', label: '雾灰' },
  { value: '#f5f3ff', label: '浅紫' },
  { value: '#eff6ff', label: '浅蓝' },
  { value: '#fefce8', label: '米黄' },
  { value: '#f0fdf4', label: '浅绿' },
]

const themeStore = useThemeStore()

const isDark = computed(
  () =>
    themeStore.active?.theme?.mode === 'dark' ||
    (typeof document !== 'undefined' &&
      document.documentElement.dataset.kiwiThemeMode === 'dark'),
)

/** 主题令牌是 `R G B` 三元组，转换成原生颜色选择器可回填的十六进制。 */
function tokenHex(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const match = /^(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})$/.exec(raw)
  if (!match) return fallback
  return `#${match
    .slice(1)
    .map((part) => Math.min(255, Number(part)).toString(16).padStart(2, '0'))
    .join('')}`
}

/**
 * 深色主题默认给出深色画布：主题自身的背景 / 表面 + 常用深灰蓝。
 * 浅色主题保持原来的浅色色板，避免切换主题时默认值突变。
 */
const backgrounds = computed<BackgroundOption[]>(() => {
  if (!isDark.value) return LIGHT_BACKGROUNDS
  const seen = new Set<string>()
  return [
    { value: tokenHex('--theme-app', '#0b1020'), label: '主题背景' },
    { value: tokenHex('--theme-surface', '#121a30'), label: '主题表面' },
    { value: tokenHex('--theme-surface-muted', '#1a2540'), label: '主题表面深' },
    { value: '#4b5563', label: '石墨灰' },
    { value: '#0b1f3a', label: '蓝图' },
    { value: '#020617', label: '午夜' },
  ].filter((item) => {
    const key = item.value.toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})

const GRIDS: { value: DrawGridType; label: string }[] = [
  { value: 'none', label: '无' },
  { value: 'solid', label: '方格' },
  { value: 'dot', label: '点阵' },
]

const THEMES: { value: DrawShapeTheme; label: string; hint: string }[] = [
  { value: 'default', label: '默认', hint: '平滑描边 · 系统字体' },
  { value: 'classic', label: '经典', hint: '手绘描边 · 内置手写体' },
]

type DrawSwitchKey = 'wheelZoom' | 'rightClickPan' | 'quickCreate' | 'showSize'

const SWITCHES: { key: DrawSwitchKey; label: string; hint: string }[] = [
  {
    key: 'wheelZoom',
    label: '滚轮缩放画布',
    hint: '关闭时滚轮平移画布，按住 Ctrl / Cmd 仍可缩放',
  },
  {
    key: 'rightClickPan',
    label: '右键拖拽平移',
    hint: '在画布上按住右键拖动即可移动视图',
  },
  {
    key: 'quickCreate',
    label: '快捷创建按钮',
    hint: '选中图形后显示快速连线与复制按钮',
  },
  {
    key: 'showSize',
    label: '显示尺寸标签',
    hint: '绘制或调整图形时显示宽高',
  },
]

const section = 'text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400'

function sameColor(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

function update<K extends keyof DrawPreferences>(key: K, value: DrawPreferences[K]) {
  emit('update', { [key]: value } as Partial<DrawPreferences>)
}
</script>

<template>
  <aside
    class="flex w-[304px] flex-col border-l border-slate-200/80 bg-white/95 backdrop-blur-xl"
    :class="
      docked
        ? 'relative z-20 h-full shrink-0'
        : 'absolute inset-y-0 right-0 z-30 shadow-[-18px_0_45px_-30px_rgba(15,23,42,0.35)]'
    "
    aria-label="画布偏好设置"
  >
    <div class="flex items-center justify-between border-b border-slate-200/70 px-4 py-3">
      <div>
        <p class="text-[12.5px] font-semibold text-slate-700">画布偏好设置</p>
        <p class="mt-0.5 text-[10px] text-slate-400">偏好会随当前笔记一起保存</p>
      </div>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
        title="关闭"
        @click="emit('close')"
      >
        <KiwiIcon name="close" :size="13" />
      </button>
    </div>

    <div class="flex-1 overflow-y-auto px-4 py-4">
      <section>
        <p :class="section">画布背景</p>
        <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
          <button
            v-for="item in backgrounds"
            :key="item.value"
            type="button"
            class="h-7 w-7 rounded-lg border transition"
            :class="
              sameColor(prefs.backgroundColor, item.value)
                ? 'border-kiwi-300 ring-2 ring-kiwi-200/70'
                : 'border-slate-200/90 hover:border-kiwi-300'
            "
            :style="{ backgroundColor: item.value }"
            :title="item.label"
            :aria-label="item.label"
            :aria-pressed="sameColor(prefs.backgroundColor, item.value)"
            @click="update('backgroundColor', item.value)"
          />
          <EditorColorPicker
            variant="swatch"
            :value="prefs.backgroundColor || '#ffffff'"
            :clearable="false"
            icon="palette"
            label="自定义画布背景"
            title="自定义画布背景色"
            @select="update('backgroundColor', $event)"
          />
          <span class="ml-1 rounded-md bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] uppercase text-slate-400">
            {{ prefs.backgroundColor }}
          </span>
        </div>
      </section>

      <section class="mt-5 border-t border-slate-100 pt-4">
        <p :class="section">背景网格</p>
        <div class="mt-2 flex rounded-lg bg-slate-100/80 p-0.5">
          <button
            v-for="grid in GRIDS"
            :key="grid.value"
            type="button"
            class="flex-1 rounded-md py-1.5 text-[11px] transition"
            :class="
              prefs.gridType === grid.value
                ? 'bg-white font-medium text-slate-700 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            "
            @click="update('gridType', grid.value)"
          >
            {{ grid.label }}
          </button>
        </div>
      </section>

      <section class="mt-5 border-t border-slate-100 pt-4">
        <p :class="section">形状主题</p>
        <div class="mt-2 grid grid-cols-2 gap-2">
          <button
            v-for="theme in THEMES"
            :key="theme.value"
            type="button"
            class="rounded-lg border px-2.5 py-2 text-left transition"
            :class="
              prefs.shapeTheme === theme.value
                ? 'border-kiwi-200 bg-kiwi-50/80'
                : 'border-slate-200/90 bg-white hover:border-kiwi-200'
            "
            @click="update('shapeTheme', theme.value)"
          >
            <span
              class="block text-[11.5px] font-medium"
              :class="prefs.shapeTheme === theme.value ? 'text-kiwi-700' : 'text-slate-600'"
            >
              {{ theme.label }}
            </span>
            <span class="mt-0.5 block text-[10px] leading-relaxed text-slate-400">
              {{ theme.hint }}
            </span>
          </button>
        </div>
        <p class="mt-2 text-[10px] leading-relaxed text-slate-400">
          切换会同步已有图形与文字，只改描边和字体，保留现有配色；可随时撤销。
        </p>
      </section>

      <section class="mt-5 border-t border-slate-100 pt-4">
        <p :class="section">交互</p>
        <div class="mt-1.5 divide-y divide-slate-100">
          <div
            v-for="item in SWITCHES"
            :key="item.key"
            class="flex items-center justify-between gap-3 py-2.5"
          >
            <div class="min-w-0">
              <p class="text-[11.5px] text-slate-600">{{ item.label }}</p>
              <p class="mt-0.5 text-[10px] leading-relaxed text-slate-400">{{ item.hint }}</p>
            </div>
            <button
              type="button"
              class="relative h-4 w-7 shrink-0 rounded-full transition"
              :class="prefs[item.key] ? 'bg-kiwi-500' : 'bg-slate-200'"
              :aria-pressed="prefs[item.key]"
              :aria-label="item.label"
              @click="update(item.key, !prefs[item.key])"
            >
              <span
                class="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-all"
                :class="prefs[item.key] ? 'left-3.5' : 'left-0.5'"
              />
            </button>
          </div>
        </div>
      </section>

      <p class="mt-4 rounded-lg bg-slate-50 px-2.5 py-2 text-[10.5px] leading-relaxed text-slate-400">
        背景色与网格会一并写入笔记；只读预览和 SVG 导出沿用背景色。快捷键说明见「帮助 → 快捷键」。
      </p>
    </div>
  </aside>
</template>
