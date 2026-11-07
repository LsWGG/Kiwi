<script setup lang="ts">
/** 主题插件：画廊、应用、预览、导入导出与个性化微调。 */
import { computed, onMounted, reactive, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
import EditorColorPicker from '@/components/editor/EditorColorPicker.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import ThemePreview from '@/components/settings/ThemePreview.vue'
import { toast } from '@/components/ui/toast'
import { useThemeStore } from '@/stores/theme'
import { resolveThemeAsset } from '@/theme/apply'
import {
  DEFAULT_ACCENT,
  DEFAULT_LEARN_ACCENT,
  DEFAULT_THEME_COLORS,
  EMPTY_THEME_OVERRIDES,
  THEME_COLOR_LABELS,
  normalizeThemeSpec,
  type ThemeBackgroundRepeat,
  type ThemeBackgroundSize,
  type ThemeColorKey,
  type ThemeDevSpec,
  type ThemeInspection,
  type ThemeItem,
  type ThemeOverrides,
} from '@/theme/types'

const theme = useThemeStore()

const loading = ref(true)
const devKitBusy = ref(false)
const exporting = ref('')
const toggling = ref('')
const importing = ref(false)
const overwrite = ref(false)
const pendingFile = ref<File | null>(null)
const inspection = ref<ThemeInspection | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const previewItem = ref<ThemeItem | null>(null)
const removing = ref<ThemeItem | null>(null)
const removingBusy = ref(false)

const specOpen = ref(false)
const spec = ref<ThemeDevSpec | null>(null)

const customOpen = ref(false)
const customBusy = ref(false)
const bgInput = ref<HTMLInputElement | null>(null)

interface CustomDraft {
  background_image: string
  background_size: ThemeBackgroundSize
  background_position: string
  background_repeat: ThemeBackgroundRepeat
  background_dim: number
  background_blur: number
  surface_opacity: number
  surface_blur: number
  useAccent: boolean
  accent: string
  useLearnAccent: boolean
  learnAccent: string
}

const customDraft = reactive<CustomDraft>({
  background_image: '',
  background_size: 'cover',
  background_position: 'center',
  background_repeat: 'no-repeat',
  background_dim: 0,
  background_blur: 0,
  surface_opacity: 1,
  surface_blur: 0,
  useAccent: false,
  accent: DEFAULT_ACCENT,
  useLearnAccent: false,
  learnAccent: DEFAULT_LEARN_ACCENT,
})

const MAX_BACKGROUND_BYTES = 2.5 * 1024 * 1024

/** 背景设置使用统一选择器，避免出现浏览器原生下拉。 */
const BACKGROUND_SIZE_OPTIONS = [
  { value: 'cover', label: '铺满（cover）' },
  { value: 'contain', label: '完整显示（contain）' },
  { value: 'auto', label: '原始尺寸（auto）' },
]
const BACKGROUND_REPEAT_OPTIONS = [
  { value: 'no-repeat', label: '不重复' },
  { value: 'repeat', label: '平铺' },
  { value: 'repeat-x', label: '横向平铺' },
  { value: 'repeat-y', label: '纵向平铺' },
]
const BACKGROUND_POSITION_OPTIONS = [
  { value: 'center', label: '居中' },
  { value: 'top', label: '顶部' },
  { value: 'bottom', label: '底部' },
  { value: 'left', label: '左侧' },
  { value: 'right', label: '右侧' },
  { value: 'top left', label: '左上' },
  { value: 'top right', label: '右上' },
  { value: 'bottom left', label: '左下' },
  { value: 'bottom right', label: '右下' },
]

const specRules = computed(() => spec.value?.rules ?? [])
const specFields = computed(() => Object.entries(spec.value?.fields ?? {}))
const specExample = computed(
  () => spec.value?.examples?.theme ?? spec.value?.example ?? {},
)
const activeSpec = computed(() => normalizeThemeSpec(theme.active?.theme))
const activeModeLabel = computed(() =>
  activeSpec.value.mode === 'dark' ? '深色' : '浅色',
)
const backgroundIsUpload = computed(() =>
  customDraft.background_image.startsWith('data:'),
)
const customPreviewBackground = computed(
  () =>
    customDraft.background_image ||
    resolveThemeAsset(
      theme.active?.asset_base_url || '',
      activeSpec.value.background.image,
    ),
)
const customPreviewAccent = computed(() =>
  customDraft.useAccent ? customDraft.accent : undefined,
)

const SWATCH_KEYS: ThemeColorKey[] = [
  'app.background',
  'surface.background',
  'border.default',
  'text.primary',
  'text.muted',
  'accent',
]

onMounted(async () => {
  // 规范与列表并行加载，打开弹窗时无需等待。
  void theme
    .spec()
    .then((value) => {
      spec.value = value
    })
    .catch(() => {})
  void theme.init()
  try {
    await theme.load()
  } catch (e: any) {
    toast.error(e.message || '加载主题列表失败')
  } finally {
    loading.value = false
  }
})

function specModeLabel(mode: string) {
  return mode === 'dark' ? '深色' : '浅色'
}

function themeMode(item: ThemeItem) {
  return normalizeThemeSpec(item.theme).mode
}

function galleryBackground(item: ThemeItem) {
  return resolveThemeAsset(
    item.asset_base_url,
    normalizeThemeSpec(item.theme).background.image,
  )
}

function swatchColor(item: ThemeItem, key: ThemeColorKey) {
  const value = normalizeThemeSpec(item.theme).colors[key]
  return value || DEFAULT_THEME_COLORS[key] || DEFAULT_ACCENT
}

function swatches(item: ThemeItem) {
  return SWATCH_KEYS.map((key) => ({
    key,
    label: THEME_COLOR_LABELS[key],
    color: swatchColor(item, key),
  }))
}

async function applyTheme(item: ThemeItem) {
  if (theme.applyingKey) return
  try {
    // 切换主题时清空上一主题的个性化覆盖，避免背景/透明度串主题。
    const same = theme.activeKey === item.key
    await theme.activate(
      item.key,
      same ? undefined : { ...EMPTY_THEME_OVERRIDES },
    )
    // 同步预览弹窗里的对象，让「应用」按钮立即变为「当前使用中」。
    const refreshed = theme.themes.find((row) => row.key === item.key)
    if (previewItem.value?.key === item.key && refreshed) {
      previewItem.value = refreshed
    }
    toast.success(`已应用主题「${item.name}」`)
  } catch (e: any) {
    toast.error(e.message || '应用主题失败')
  }
}

async function toggleEnabled(item: ThemeItem) {
  if (toggling.value) return
  toggling.value = item.id
  try {
    await theme.setEnabled(item, !item.enabled)
    toast.success(item.enabled ? `已停用「${item.name}」` : `已启用「${item.name}」`)
  } catch (e: any) {
    toast.error(e.message || '切换主题状态失败')
  } finally {
    toggling.value = ''
  }
}

async function exportTheme(item: ThemeItem) {
  if (exporting.value) return
  exporting.value = item.id
  try {
    const filename = await theme.exportTheme(item)
    toast.success(`已导出 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '导出主题失败')
  } finally {
    exporting.value = ''
  }
}

function exportActive() {
  const item = theme.activeTheme
  if (!item) {
    toast.error('当前主题不在画廊列表中，请刷新后重试')
    return
  }
  void exportTheme(item)
}

async function confirmRemove() {
  if (!removing.value) return
  removingBusy.value = true
  try {
    await theme.remove(removing.value)
    toast.success('主题已删除')
    removing.value = null
  } catch (e: any) {
    toast.error(e.message || '删除主题失败')
  } finally {
    removingBusy.value = false
  }
}

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    toast.error('主题包必须是 .zip 文件')
    return
  }
  importing.value = true
  pendingFile.value = file
  inspection.value = null
  overwrite.value = false
  try {
    inspection.value = await theme.inspectFile(file)
  } catch (e: any) {
    pendingFile.value = null
    toast.error(e.message || '主题包解析失败')
  } finally {
    importing.value = false
  }
}

function closeInspection() {
  inspection.value = null
  pendingFile.value = null
}

async function confirmImport() {
  if (!pendingFile.value || importing.value) return
  importing.value = true
  try {
    const item = await theme.importFile(pendingFile.value, overwrite.value)
    toast.success(`已导入「${item.name}」 v${item.version}`)
    closeInspection()
  } catch (e: any) {
    toast.error(e.message || '导入主题失败')
  } finally {
    importing.value = false
  }
}

async function downloadDevKit() {
  if (devKitBusy.value) return
  devKitBusy.value = true
  try {
    const filename = await theme.downloadDevKit()
    toast.success(`已下载 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '下载开发套件失败')
  } finally {
    devKitBusy.value = false
  }
}

async function openSpec() {
  specOpen.value = true
  if (spec.value) return
  try {
    spec.value = await theme.spec()
  } catch (e: any) {
    toast.error(e.message || '加载主题开发规范失败')
  }
}

async function copyText(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    toast.success(`${label}已复制`)
  } catch {
    toast.error('复制失败，请手动选择文本')
  }
}

function openCustomize() {
  const activeValue = theme.active
  if (!activeValue) return
  const specValue = normalizeThemeSpec(activeValue.theme)
  const overrides = theme.overrides
  customDraft.background_image = overrides.background_image || ''
  customDraft.background_size =
    overrides.background_size || specValue.background.size
  customDraft.background_position =
    overrides.background_position || specValue.background.position || 'center'
  customDraft.background_repeat =
    overrides.background_repeat || specValue.background.repeat
  customDraft.background_dim = overrides.background_dim ?? specValue.background.dim
  customDraft.background_blur = overrides.background_blur ?? specValue.background.blur
  customDraft.surface_opacity =
    overrides.surface_opacity ?? specValue.surface.opacity
  customDraft.surface_blur = overrides.surface_blur ?? specValue.surface.blur
  customDraft.useAccent = Boolean(overrides.accent)
  customDraft.accent =
    overrides.accent || specValue.colors.accent || DEFAULT_ACCENT
  customDraft.useLearnAccent = Boolean(overrides.learn_accent)
  customDraft.learnAccent =
    overrides.learn_accent ||
    specValue.colors.accent ||
    (activeValue.builtin ? DEFAULT_LEARN_ACCENT : DEFAULT_ACCENT)
  customOpen.value = true
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

async function onBackgroundFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    toast.error('请选择图片文件')
    return
  }
  if (file.size > MAX_BACKGROUND_BYTES) {
    toast.error('背景图不能超过 2.5MB')
    return
  }
  try {
    customDraft.background_image = await readFileAsDataUrl(file)
  } catch (e: any) {
    toast.error(e.message || '读取图片失败')
  }
}

/** 只提交与主题默认值不同的项，未改动的字段保持 null，避免误标「已微调」。 */
function customOverrides(): ThemeOverrides {
  const defaults = activeSpec.value
  const position = customDraft.background_position.trim() || 'center'
  return {
    background_image: customDraft.background_image.trim(),
    background_size:
      customDraft.background_size !== defaults.background.size
        ? customDraft.background_size
        : null,
    background_position:
      position !== (defaults.background.position || 'center') ? position : null,
    background_repeat:
      customDraft.background_repeat !== defaults.background.repeat
        ? customDraft.background_repeat
        : null,
    background_dim:
      customDraft.background_dim !== defaults.background.dim
        ? customDraft.background_dim
        : null,
    background_blur:
      customDraft.background_blur !== defaults.background.blur
        ? customDraft.background_blur
        : null,
    surface_opacity:
      customDraft.surface_opacity !== defaults.surface.opacity
        ? customDraft.surface_opacity
        : null,
    surface_blur:
      customDraft.surface_blur !== defaults.surface.blur
        ? customDraft.surface_blur
        : null,
    accent: customDraft.useAccent ? customDraft.accent : null,
    learn_accent: customDraft.useLearnAccent ? customDraft.learnAccent : null,
  }
}

function closeRemoveConfirm(value: boolean) {
  if (!value && !removingBusy.value) removing.value = null
}

async function saveCustomize() {
  if (customBusy.value) return
  customBusy.value = true
  try {
    await theme.saveOverrides(customOverrides())
    customOpen.value = false
    toast.success('主题微调已保存')
  } catch (e: any) {
    toast.error(e.message || '保存主题微调失败')
  } finally {
    customBusy.value = false
  }
}

async function resetCustomize() {
  if (customBusy.value) return
  customBusy.value = true
  try {
    await theme.resetOverrides()
    customOpen.value = false
    toast.success('已恢复主题默认外观')
  } catch (e: any) {
    toast.error(e.message || '重置主题微调失败')
  } finally {
    customBusy.value = false
  }
}
</script>

<template>
  <div class="page-wrap-slim px-4 py-6 sm:px-8 sm:py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-kiwi-500 to-fuchsia-500 text-white shadow-glow"
        >
          <KiwiIcon name="palette" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">主题</h1>
          <p class="mt-1 text-sm text-slate-500">
            应用主题插件，调整背景、透明度与强调色；主题只包含声明式 JSON 与 CSS。
          </p>
        </div>
      </div>
      <div class="grid w-full grid-cols-3 gap-1.5 sm:flex sm:w-auto sm:flex-wrap sm:items-center sm:gap-2">
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          @click="openSpec"
        >
          <span class="hidden sm:inline-flex"><KiwiIcon name="file" :size="14" /></span>
          开发规范
        </button>
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          :disabled="devKitBusy"
          @click="downloadDevKit"
        >
          <span class="hidden sm:inline-flex">
            <KiwiIcon :name="devKitBusy ? 'loader' : 'download'" :size="14" :spin="devKitBusy" />
          </span>
          开发套件
        </button>
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          :disabled="importing"
          @click="pickFile"
        >
          <span class="hidden sm:inline-flex">
            <KiwiIcon :name="importing ? 'loader' : 'fileImport'" :size="14" :spin="importing" />
          </span>
          {{ importing ? '解析中…' : '导入主题' }}
        </button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".zip,application/zip"
        class="hidden"
        @change="onFileChange"
      />
    </div>

    <SettingsTabs />

    <!-- 当前主题 -->
    <section class="mb-5 animate-fade-up rounded-2xl glass-strong p-4">
      <div class="flex flex-wrap items-center gap-3">
        <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
          <KiwiIcon name="palette" :size="18" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-[10.5px] font-medium uppercase tracking-wide text-slate-400">当前主题</p>
          <div class="mt-0.5 flex flex-wrap items-center gap-2">
            <h2 class="text-[15px] font-semibold text-slate-800">
              {{ theme.active?.name || '加载中…' }}
            </h2>
            <span
              v-if="theme.active?.builtin"
              class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
            >
              内置
            </span>
            <span
              v-else-if="theme.active"
              class="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] text-violet-600"
            >
              已安装
            </span>
            <span class="rounded-full bg-kiwi-50 px-2 py-0.5 text-[10px] text-kiwi-600">
              {{ activeModeLabel }}
            </span>
            <span
              v-if="theme.customized"
              class="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-600"
            >
              已微调
            </span>
          </div>
          <p class="mt-1 text-[11px] leading-relaxed text-slate-500">
            {{
              theme.customized
                ? '已应用自定义背景 / 透明度 / 强调色；可继续微调或恢复主题默认外观。'
                : '外观来自主题插件默认配置。微调仅对当前主题生效，切换主题后会清空。'
            }}
          </p>
        </div>
        <div class="flex w-full flex-wrap items-center gap-1.5 sm:ml-auto sm:w-auto">
          <button
            class="kiwi-btn-secondary whitespace-nowrap !py-1.5 text-[11.5px]"
            :disabled="!theme.active"
            @click="openCustomize"
          >
            <KiwiIcon name="palette" :size="12" /> 自定义外观
          </button>
          <button
            v-if="theme.customized"
            class="kiwi-btn-ghost whitespace-nowrap !py-1.5 text-[11.5px]"
            :disabled="customBusy"
            @click="resetCustomize"
          >
            <KiwiIcon name="refresh" :size="12" /> 重置微调
          </button>
          <button
            class="kiwi-btn-ghost whitespace-nowrap !py-1.5 text-[11.5px]"
            :disabled="!theme.activeTheme || !!exporting"
            @click="exportActive"
          >
            <KiwiIcon name="fileExport" :size="12" /> 导出
          </button>
        </div>
      </div>
    </section>

    <!-- 主题画廊 -->
    <div v-if="loading" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <div
        v-for="n in 3"
        :key="n"
        class="h-64 animate-pulse rounded-2xl glass"
      />
    </div>

    <template v-else>
      <div class="mb-2.5 flex flex-wrap items-center gap-2">
        <h2 class="text-[13px] font-semibold text-slate-700">主题画廊</h2>
        <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
          内置 {{ theme.builtinThemes.length }} · 已安装 {{ theme.installedThemes.length }}
        </span>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <article
          v-for="item in theme.themes"
          :key="item.key"
          class="flex flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white/70 shadow-soft backdrop-blur-xl transition-all"
          :class="item.active ? 'ring-1 ring-kiwi-300' : ''"
        >
          <div class="relative p-2.5 pb-0">
            <img
              v-if="item.preview_url"
              :src="item.preview_url"
              :alt="`${item.name} 预览`"
              class="aspect-[16/10] w-full rounded-xl border border-slate-200/60 object-cover"
              loading="lazy"
            />
            <ThemePreview
              v-else
              :theme="item.theme"
              :background-image="galleryBackground(item)"
            />
            <div class="absolute left-4 top-4 flex flex-wrap gap-1">
              <span
                v-if="item.active"
                class="rounded-full bg-kiwi-600/90 px-2 py-0.5 text-[10px] font-medium text-white shadow-soft"
              >
                当前
              </span>
              <span
                v-if="item.builtin"
                class="rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-medium text-slate-600 shadow-soft"
              >
                内置
              </span>
              <span
                v-else-if="!item.enabled"
                class="rounded-full bg-amber-500/90 px-2 py-0.5 text-[10px] font-medium text-white shadow-soft"
              >
                已停用
              </span>
            </div>
          </div>

          <div class="flex flex-1 flex-col gap-1.5 p-3">
            <div class="flex flex-wrap items-center gap-1.5">
              <h3 class="text-[13.5px] font-semibold text-slate-800">{{ item.name }}</h3>
              <span class="text-[10px] text-slate-400">v{{ item.version }}</span>
              <span class="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9.5px] text-slate-500">
                {{ specModeLabel(themeMode(item)) }}
              </span>
            </div>
            <p class="line-clamp-2 text-[11px] leading-relaxed text-slate-500">
              {{ item.description || '未填写简介' }}
            </p>
            <p v-if="item.author" class="text-[10px] text-slate-400">{{ item.author }}</p>

            <div class="mt-auto flex flex-wrap items-center gap-1 pt-1.5">
              <button
                class="kiwi-btn-primary whitespace-nowrap !px-2.5 !py-1.5 text-[11px]"
                :disabled="item.active || theme.applyingKey === item.key"
                @click="applyTheme(item)"
              >
                <KiwiIcon
                  :name="theme.applyingKey === item.key ? 'loader' : 'check'"
                  :size="11"
                  :spin="theme.applyingKey === item.key"
                />
                {{ item.active ? '使用中' : '应用' }}
              </button>
              <button
                class="kiwi-btn-secondary whitespace-nowrap !px-2.5 !py-1.5 text-[11px]"
                @click="previewItem = item"
              >
                <KiwiIcon name="eye" :size="11" /> 预览
              </button>
              <button
                class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1.5 text-[10.5px]"
                :disabled="!!exporting"
                @click="exportTheme(item)"
              >
                <KiwiIcon
                  :name="exporting === item.id ? 'loader' : 'fileExport'"
                  :size="11"
                  :spin="exporting === item.id"
                />
                导出
              </button>
              <button
                v-if="!item.builtin"
                class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1.5 text-[10.5px]"
                :disabled="!!toggling"
                @click="toggleEnabled(item)"
              >
                <KiwiIcon
                  :name="toggling === item.id ? 'loader' : item.enabled ? 'close' : 'check'"
                  :size="11"
                  :spin="toggling === item.id"
                />
                {{ item.enabled ? '停用' : '启用' }}
              </button>
              <button
                v-if="!item.builtin"
                class="kiwi-btn-ghost ml-auto whitespace-nowrap !px-1.5 !py-1.5 text-[10.5px] text-rose-500"
                title="删除主题"
                @click="removing = item"
              >
                <KiwiIcon name="trash" :size="11" />
              </button>
            </div>
          </div>
        </article>
      </div>

      <p
        v-if="!theme.themes.length"
        class="rounded-2xl border border-dashed border-slate-200 bg-white/50 px-4 py-10 text-center text-[12px] text-slate-400"
      >
        还没有主题，点击右上角「导入主题」安装一个。
      </p>
    </template>

    <!-- 预览弹窗 -->
    <KiwiModal
      :open="!!previewItem"
      :title="previewItem ? `预览 · ${previewItem.name}` : '主题预览'"
      max-w="max-w-3xl"
      @close="previewItem = null"
    >
      <div v-if="previewItem" class="space-y-4">
        <img
          v-if="previewItem.preview_url"
          :src="previewItem.preview_url"
          :alt="`${previewItem.name} 预览`"
          class="w-full rounded-xl border border-slate-200/70"
        />
        <ThemePreview
          v-else
          :theme="previewItem.theme"
          :background-image="galleryBackground(previewItem)"
        />

        <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <span class="rounded-full bg-slate-100 px-2 py-0.5">{{ previewItem.key }}</span>
          <span class="rounded-full bg-slate-100 px-2 py-0.5">v{{ previewItem.version }}</span>
          <span class="rounded-full bg-slate-100 px-2 py-0.5">
            {{ specModeLabel(themeMode(previewItem)) }}
          </span>
          <span v-if="previewItem.author">作者 {{ previewItem.author }}</span>
          <span v-if="previewItem.builtin" class="text-kiwi-600">内置主题</span>
        </div>

        <p v-if="previewItem.description" class="text-[12px] leading-relaxed text-slate-600">
          {{ previewItem.description }}
        </p>

        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
          <div v-for="swatch in swatches(previewItem)" :key="swatch.key" class="min-w-0">
            <span
              class="block h-9 rounded-lg border border-slate-200/70"
              :style="{ backgroundColor: swatch.color }"
            />
            <span class="mt-1 block truncate text-[9.5px] text-slate-400">
              {{ swatch.label }}
            </span>
          </div>
        </div>

        <div class="flex flex-wrap justify-end gap-2 pt-1">
          <button class="kiwi-btn-ghost" @click="exportTheme(previewItem)">
            <KiwiIcon name="fileExport" :size="13" /> 导出主题
          </button>
          <button
            class="kiwi-btn-primary"
            :disabled="previewItem.active || theme.applyingKey === previewItem.key"
            @click="applyTheme(previewItem)"
          >
            <KiwiIcon
              :name="theme.applyingKey === previewItem.key ? 'loader' : 'check'"
              :size="13"
              :spin="theme.applyingKey === previewItem.key"
            />
            {{ previewItem.active ? '当前使用中' : '应用该主题' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 自定义外观 -->
    <KiwiModal
      :open="customOpen"
      title="自定义外观"
      max-w="max-w-3xl"
      @close="customOpen = false"
    >
      <div class="space-y-4">
        <ThemePreview
          :theme="theme.active?.theme || activeSpec"
          :background-image="customPreviewBackground"
          :surface-opacity="customDraft.surface_opacity"
          :surface-blur="customDraft.surface_blur"
          :background-dim="customDraft.background_dim"
          :background-blur="customDraft.background_blur"
          :accent="customPreviewAccent"
        />

        <div class="grid gap-4 md:grid-cols-2">
          <!-- 背景 -->
          <section class="space-y-2.5 rounded-xl border border-slate-200/70 bg-white/60 p-3">
            <h3 class="text-[12px] font-semibold text-slate-700">背景图</h3>
            <div class="flex flex-wrap items-center gap-1.5">
              <button class="kiwi-btn-secondary !px-2.5 !py-1.5 text-[11px]" @click="bgInput?.click()">
                <KiwiIcon name="image" :size="11" /> 上传图片
              </button>
              <button
                v-if="customDraft.background_image"
                class="kiwi-btn-ghost !px-2.5 !py-1.5 text-[11px]"
                @click="customDraft.background_image = ''"
              >
                <KiwiIcon name="close" :size="11" /> 清除背景
              </button>
              <span class="text-[10px] text-slate-400">≤ 2.5MB</span>
            </div>
            <input
              ref="bgInput"
              type="file"
              accept="image/*"
              class="hidden"
              @change="onBackgroundFile"
            />
            <div
              v-if="backgroundIsUpload"
              class="rounded-lg bg-slate-50 px-2.5 py-1.5 text-[10.5px] text-slate-500"
            >
              已上传自定义背景图
            </div>
            <input
              v-else
              v-model="customDraft.background_image"
              class="kiwi-input text-[11px]"
              placeholder="或粘贴图片地址：https://… / /uploads/…"
            />
            <div class="grid grid-cols-2 gap-2">
              <div class="block">
                <span class="mb-1 block text-[10.5px] text-slate-500">填充方式</span>
                <KiwiSelect
                  :model-value="customDraft.background_size"
                  :options="BACKGROUND_SIZE_OPTIONS"
                  variant="input"
                  width="w-full"
                  trigger-class="!text-[11px]"
                  title="背景填充方式"
                  @update:model-value="
                    customDraft.background_size = $event as ThemeBackgroundSize
                  "
                />
              </div>
              <div class="block">
                <span class="mb-1 block text-[10.5px] text-slate-500">重复</span>
                <KiwiSelect
                  :model-value="customDraft.background_repeat"
                  :options="BACKGROUND_REPEAT_OPTIONS"
                  variant="input"
                  width="w-full"
                  trigger-class="!text-[11px]"
                  title="背景重复方式"
                  @update:model-value="
                    customDraft.background_repeat = $event as ThemeBackgroundRepeat
                  "
                />
              </div>
            </div>
            <div class="block">
              <span class="mb-1 block text-[10.5px] text-slate-500">对齐位置</span>
              <KiwiSelect
                :model-value="customDraft.background_position"
                :options="BACKGROUND_POSITION_OPTIONS"
                variant="input"
                width="w-full"
                trigger-class="!text-[11px]"
                title="背景对齐位置"
                @update:model-value="customDraft.background_position = String($event)"
              />
            </div>
            <label class="block">
              <span class="flex items-center justify-between text-[10.5px] text-slate-500">
                <span>暗化遮罩</span>
                <span class="font-mono text-slate-400">{{ customDraft.background_dim.toFixed(2) }}</span>
              </span>
              <input
                v-model.number="customDraft.background_dim"
                type="range"
                min="0"
                max="0.9"
                step="0.05"
                class="mt-1 w-full accent-kiwi-600"
              />
            </label>
            <label class="block">
              <span class="flex items-center justify-between text-[10.5px] text-slate-500">
                <span>背景模糊</span>
                <span class="font-mono text-slate-400">{{ customDraft.background_blur }}px</span>
              </span>
              <input
                v-model.number="customDraft.background_blur"
                type="range"
                min="0"
                max="40"
                step="1"
                class="mt-1 w-full accent-kiwi-600"
              />
            </label>
          </section>

          <!-- 面板与强调色 -->
          <section class="space-y-2.5 rounded-xl border border-slate-200/70 bg-white/60 p-3">
            <h3 class="text-[12px] font-semibold text-slate-700">面板与强调色</h3>
            <label class="block">
              <span class="flex items-center justify-between text-[10.5px] text-slate-500">
                <span>面板不透明度</span>
                <span class="font-mono text-slate-400">{{ Math.round(customDraft.surface_opacity * 100) }}%</span>
              </span>
              <input
                v-model.number="customDraft.surface_opacity"
                type="range"
                min="0.35"
                max="1"
                step="0.01"
                class="mt-1 w-full accent-kiwi-600"
              />
              <span class="mt-0.5 block text-[10px] leading-relaxed text-slate-400">
                低于 100% 时面板会透出背景，适合壁纸主题。
              </span>
            </label>
            <label class="block">
              <span class="flex items-center justify-between text-[10.5px] text-slate-500">
                <span>毛玻璃模糊</span>
                <span class="font-mono text-slate-400">{{ customDraft.surface_blur }}px</span>
              </span>
              <input
                v-model.number="customDraft.surface_blur"
                type="range"
                min="0"
                max="40"
                step="1"
                class="mt-1 w-full accent-kiwi-600"
              />
            </label>

            <div class="space-y-2.5 border-t border-slate-200/70 pt-2.5">
              <div class="flex items-center justify-between">
                <span class="text-[10.5px] font-medium text-slate-500">主题强调色</span>
                <span class="text-[10px] text-slate-400">两种模式独立保存</span>
              </div>

              <div>
                <label class="flex cursor-pointer items-center gap-2 text-[11px] text-slate-600">
                  <input
                    v-model="customDraft.useAccent"
                    type="checkbox"
                    class="h-3.5 w-3.5 accent-kiwi-600"
                  />
                  编辑模式
                </label>
                <div class="mt-1.5 flex items-center gap-2">
                  <EditorColorPicker
                    variant="field"
                    class="w-32"
                    :value="customDraft.accent"
                    :disabled="!customDraft.useAccent"
                    :clearable="false"
                    icon="palette"
                    label="编辑模式强调色"
                    title="编辑模式强调色"
                    @select="customDraft.accent = $event"
                  />
                  <input
                    v-model="customDraft.accent"
                    class="kiwi-input w-28 font-mono text-[11px]"
                    :disabled="!customDraft.useAccent"
                    placeholder="#5a55c7"
                  />
                </div>
              </div>

              <div>
                <label class="flex cursor-pointer items-center gap-2 text-[11px] text-slate-600">
                  <input
                    v-model="customDraft.useLearnAccent"
                    type="checkbox"
                    class="h-3.5 w-3.5 accent-kiwi-600"
                  />
                  学习模式
                </label>
                <div class="mt-1.5 flex items-center gap-2">
                  <EditorColorPicker
                    variant="field"
                    class="w-32"
                    :value="customDraft.learnAccent"
                    :disabled="!customDraft.useLearnAccent"
                    :clearable="false"
                    icon="palette"
                    label="学习模式强调色"
                    title="学习模式强调色"
                    @select="customDraft.learnAccent = $event"
                  />
                  <input
                    v-model="customDraft.learnAccent"
                    class="kiwi-input w-28 font-mono text-[11px]"
                    :disabled="!customDraft.useLearnAccent"
                    placeholder="#10b981"
                  />
                </div>
              </div>

              <p class="text-[10px] leading-relaxed text-slate-400">
                不勾选时沿用主题声明的强调色；内置主题默认编辑紫、学习绿。修改任一模式不会影响另一模式。
              </p>
            </div>
          </section>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-2 pt-1">
          <button
            class="kiwi-btn-ghost mr-auto"
            :disabled="customBusy"
            @click="resetCustomize"
          >
            <KiwiIcon name="refresh" :size="13" /> 恢复主题默认
          </button>
          <button class="kiwi-btn-ghost" @click="customOpen = false">取消</button>
          <button class="kiwi-btn-primary" :disabled="customBusy" @click="saveCustomize">
            <KiwiIcon :name="customBusy ? 'loader' : 'check'" :size="13" :spin="customBusy" />
            {{ customBusy ? '保存中…' : '保存微调' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 导入预检 -->
    <KiwiModal
      :open="!!inspection && !!pendingFile"
      title="导入主题"
      max-w="max-w-xl"
      @close="closeInspection"
    >
      <div v-if="inspection" class="space-y-4">
        <div class="flex items-start gap-3">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="palette" :size="19" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-[14px] font-semibold text-slate-800">{{ inspection.name }}</h3>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                v{{ inspection.version }}
              </span>
              <span class="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] text-violet-600">
                主题插件
              </span>
              <span
                v-if="inspection.theme"
                class="rounded-full bg-kiwi-50 px-2 py-0.5 text-[10px] text-kiwi-600"
              >
                {{ specModeLabel(inspection.theme.mode) }}
              </span>
            </div>
            <p v-if="inspection.description" class="mt-1 text-[11.5px] leading-relaxed text-slate-500">
              {{ inspection.description }}
            </p>
            <p class="mt-1 text-[10.5px] text-slate-400">
              文件 {{ pendingFile?.name }} · key
              <code class="rounded bg-slate-100 px-1">{{ inspection.key }}</code>
            </p>
          </div>
        </div>

        <div
          v-if="inspection.theme"
          class="grid grid-cols-3 gap-2 rounded-xl border border-slate-200/80 bg-white/60 p-3 sm:grid-cols-6"
        >
          <div
            v-for="key in SWATCH_KEYS"
            :key="key"
            class="min-w-0"
          >
            <span
              class="block h-8 rounded-lg border border-slate-200/70"
              :style="{
                backgroundColor: inspection.theme.colors[key] || DEFAULT_THEME_COLORS[key],
              }"
            />
            <span class="mt-0.5 block truncate text-[9px] text-slate-400">
              {{ THEME_COLOR_LABELS[key] }}
            </span>
          </div>
        </div>

        <div
          v-if="inspection.theme"
          class="grid gap-2 rounded-xl border border-slate-200/80 bg-white/60 px-3 py-2.5 text-[11px] text-slate-500 sm:grid-cols-2"
        >
          <span>
            背景：
            <strong class="font-medium text-slate-700">
              {{ inspection.theme.background.image || '无' }}
            </strong>
          </span>
          <span>
            面板不透明度：
            <strong class="font-medium text-slate-700">
              {{ Math.round(inspection.theme.surface.opacity * 100) }}%
            </strong>
          </span>
          <span v-if="inspection.has_style">包含 theme.css 装饰样式</span>
          <span v-if="inspection.asset_count">资源 {{ inspection.asset_count }} 个</span>
        </div>

        <div class="rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-2.5">
          <p class="flex items-center gap-1.5 text-[11.5px] font-medium text-emerald-700">
            <KiwiIcon name="shield" :size="13" /> 声明式主题，不执行脚本
          </p>
          <p class="mt-1 text-[10.5px] leading-relaxed text-emerald-700/90">
            主题包只包含 plugin.json、可选 theme.css 与 assets/，不会运行 JavaScript。
            样式会作用于全站界面，请只导入来源可信的主题包。
          </p>
        </div>

        <label class="flex cursor-pointer items-center gap-2 text-[11.5px] text-slate-600">
          <input v-model="overwrite" type="checkbox" class="h-3.5 w-3.5 accent-kiwi-600" />
          覆盖同 key 主题（保留原有启用状态）
        </label>

        <div class="flex justify-end gap-2">
          <button class="kiwi-btn-ghost" @click="closeInspection">取消</button>
          <button class="kiwi-btn-primary" :disabled="importing" @click="confirmImport">
            <KiwiIcon :name="importing ? 'loader' : 'fileImport'" :size="14" :spin="importing" />
            {{ importing ? '导入中…' : '确认导入' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 开发规范 -->
    <KiwiModal
      :open="specOpen"
      title="主题插件开发规范"
      max-w="max-w-4xl"
      @close="specOpen = false"
    >
      <div v-if="!spec" class="py-10 text-center text-sm text-slate-400">
        <KiwiIcon name="loader" :size="16" :spin="true" class="inline-block" /> 读取规范…
      </div>
      <div v-else class="space-y-5">
        <section class="rounded-xl border border-kiwi-100 bg-kiwi-50/50 p-3.5">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 class="text-[13px] font-semibold text-slate-800">声明式主题插件</h3>
              <p class="mt-1 text-[11.5px] leading-relaxed text-slate-600">
                {{ spec.package }}
              </p>
              <p class="mt-1 text-[10.5px] text-slate-500">
                skill：<code class="rounded bg-white/70 px-1">{{ spec.skill }}</code>
                · 套件：<code class="rounded bg-white/70 px-1">{{ spec.dev_kit_url }}</code>
              </p>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button class="kiwi-btn-ghost !px-2.5 !py-1.5 text-[11px]" @click="downloadDevKit">
                <KiwiIcon name="download" :size="11" /> 开发套件
              </button>
              <button
                v-if="spec.ai_prompt"
                class="kiwi-btn-secondary !px-2.5 !py-1.5 text-[11px]"
                @click="copyText(spec.ai_prompt, 'AI 提示词')"
              >
                <KiwiIcon name="file" :size="11" /> 复制 AI 提示词
              </button>
            </div>
          </div>
        </section>

        <section>
          <h3 class="mb-2 text-[12.5px] font-semibold text-slate-700">规则</h3>
          <ul class="space-y-1.5">
            <li
              v-for="rule in specRules"
              :key="rule"
              class="flex gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-600"
            >
              <KiwiIcon name="check" :size="11" class="mt-0.5 shrink-0 text-kiwi-500" />
              {{ rule }}
            </li>
          </ul>
        </section>

        <section>
          <h3 class="mb-2 text-[12.5px] font-semibold text-slate-700">字段</h3>
          <div class="overflow-hidden rounded-xl border border-slate-200/80">
            <div
              v-for="([key, description], index) in specFields"
              :key="key"
              class="grid gap-1 px-3 py-2 text-[11px] sm:grid-cols-[180px_1fr]"
              :class="index % 2 ? 'bg-slate-50/70' : 'bg-white/70'"
            >
              <code class="text-slate-700">{{ key }}</code>
              <span class="text-slate-500">{{ description }}</span>
            </div>
          </div>
        </section>

        <section>
          <h3 class="mb-2 text-[12.5px] font-semibold text-slate-700">示例 plugin.json</h3>
          <div class="relative">
            <button
              class="kiwi-btn-ghost absolute right-2 top-2 z-10 !px-2 !py-1 text-[10px]"
              @click="copyText(JSON.stringify(specExample, null, 2), '示例')"
            >
              复制
            </button>
            <pre
              class="max-h-72 overflow-auto rounded-xl bg-slate-900 p-3 pr-16 text-[10.5px] leading-relaxed text-slate-100"
            >{{ JSON.stringify(specExample, null, 2) }}</pre>
          </div>
        </section>

        <p class="text-[10.5px] leading-relaxed text-slate-400">
          完整文档见仓库 <code class="rounded bg-slate-100 px-1">docs/THEME_SPEC.md</code> 与
          <code class="rounded bg-slate-100 px-1">.claude/skills/kiwi-theme/SKILL.md</code>；
          开发套件内含示例主题 aurora，可直接解压参考。
        </p>
      </div>
    </KiwiModal>

    <!-- 删除确认 -->
    <KiwiConfirm
      :model-value="!!removing"
      title="删除主题"
      :message="removing ? `确定删除主题「${removing.name}」吗？若正在使用，会先回落到内置主题。` : ''"
      confirm-text="删除"
      danger
      @update:model-value="closeRemoveConfirm"
      @confirm="confirmRemove"
    />
  </div>
</template>
