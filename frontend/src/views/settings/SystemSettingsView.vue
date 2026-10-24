<script setup lang="ts">
/**
 * 品牌设置：品牌名称 / 描述 / Logo / 主题色。
 * 保存后立即写入全局状态，顶栏、浏览器标题和主题色同步更新。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiLogo from '@/components/ui/KiwiLogo.vue'
import EditorColorPicker from '@/components/editor/EditorColorPicker.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'
import { useModeStore } from '@/stores/mode'
import {
  DEFAULT_LEARN_THEME_COLOR,
  DEFAULT_SYSTEM_SETTINGS,
  DEFAULT_THEME_COLOR,
  applyLearnThemeColor,
  applyThemeColor,
  useSystemStore,
  type SystemSettings,
} from '@/stores/system'

const pageMeta = {
  icon: 'palette',
  title: '品牌设置',
  description: '自定义系统名称、描述、Logo 与主题色，显示在顶栏与浏览器标签。',
}

const system = useSystemStore()
const mode = useModeStore()

/**
 * 编辑 / 学习是两套视觉语言：品牌名称、Logo 全站共用，
 * 主题色则分别配置。默认编辑当前所处模式的配色。
 */
type ThemeMode = 'edit' | 'learn'
const themeMode = ref<ThemeMode>(mode.mode === 'learn' ? 'learn' : 'edit')

const loading = ref(true)
const saving = ref(false)
const uploadingLogo = ref(false)
const resettingLogo = ref(false)
const logoInput = ref<HTMLInputElement | null>(null)

const form = ref({
  app_name: DEFAULT_SYSTEM_SETTINGS.app_name,
  app_description: DEFAULT_SYSTEM_SETTINGS.app_description,
  logo_url: '',
  theme_color: DEFAULT_THEME_COLOR,
  learn_theme_color: DEFAULT_LEARN_THEME_COLOR,
  learn_logo_url: '',
  learn_description: DEFAULT_SYSTEM_SETTINGS.learn_description,
})

const THEME_PRESETS = [
  { label: '冷紫', value: '#5a55c7' },
  { label: '靛蓝', value: '#2563eb' },
  { label: '青绿', value: '#059669' },
  // 学习模式默认主题色，内置为预设以便回显选中态。
  { label: '翠绿', value: '#10b981' },
  { label: '琥珀', value: '#d97706' },
  { label: '玫红', value: '#db2777' },
  { label: '石墨', value: '#475569' },
]

const themeColor = computed({
  get: () =>
    themeMode.value === 'learn'
      ? form.value.learn_theme_color
      : form.value.theme_color,
  set: (value: string) => {
    if (themeMode.value === 'learn') form.value.learn_theme_color = value
    else form.value.theme_color = value
  },
})

/** Logo 按模式回显：学习模式可单独上传，未上传时沿用品牌 Logo。 */
const logoPreview = computed(() =>
  themeMode.value === 'learn'
    ? form.value.learn_logo_url || form.value.logo_url
    : form.value.logo_url,
)
const hasOwnLogo = computed(() =>
  themeMode.value === 'learn'
    ? !!form.value.learn_logo_url
    : !!form.value.logo_url,
)

/** 名称全站共用；一句话描述按模式独立保存，表单行位置保持一致。 */
const descriptionField = computed({
  get: () =>
    themeMode.value === 'learn'
      ? form.value.learn_description
      : form.value.app_description,
  set: (value: string) => {
    if (themeMode.value === 'learn') form.value.learn_description = value
    else form.value.app_description = value
  },
})

/** 当前主题色是否为预设色：都未命中时高亮右侧自定义取色入口。 */
const isPresetColor = computed(() =>
  THEME_PRESETS.some((preset) => preset.value.toLowerCase() === themeColor.value.toLowerCase()),
)
const isCustomTheme = computed(() => !isPresetColor.value)

const appOrigin = computed(() => (import.meta.env.DEV ? 'http://localhost:5173' : window.location.origin))

function hydrate(settings: SystemSettings) {
  form.value = {
    app_name: settings.app_name,
    app_description: settings.app_description,
    logo_url: settings.logo_url,
    theme_color: settings.theme_color,
    learn_theme_color: settings.learn_theme_color || DEFAULT_LEARN_THEME_COLOR,
    learn_logo_url: settings.learn_logo_url || '',
    learn_description:
      settings.learn_description ?? DEFAULT_SYSTEM_SETTINGS.learn_description,
  }
}

onMounted(async () => {
  try {
    hydrate(await system.fetchSettings(true))
  } catch (e: any) {
    toast.error(e.message || '读取系统设置失败')
    hydrate(system.settings)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  // 未保存的主题预览在离开页面时回退到已保存值。
  applyThemeColor(system.settings.theme_color)
  applyLearnThemeColor(system.settings.learn_theme_color)
  document.body.classList.toggle('theme-learn', mode.mode === 'learn')
})

function previewTheme() {
  if (themeMode.value === 'learn') applyLearnThemeColor(form.value.learn_theme_color)
  else applyThemeColor(form.value.theme_color)
}

function choosePreset(color: string) {
  themeColor.value = color
  previewTheme()
}

function switchThemeMode(value: ThemeMode) {
  themeMode.value = value
  // 设置页在两种模式下共用；切换目标配色时同步预览整页效果。
  document.body.classList.toggle('theme-learn', value === 'learn')
  previewTheme()
}

function pickLogo() {
  logoInput.value?.click()
}

async function onLogoFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    toast.info('请选择 PNG / JPG / WebP / GIF / BMP 图片')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    toast.info('Logo 不能超过 2MB')
    return
  }
  uploadingLogo.value = true
  try {
    const url = await system.uploadLogo(file)
    if (themeMode.value === 'learn') form.value.learn_logo_url = url
    else form.value.logo_url = url
    toast.success('Logo 已上传，保存后生效')
  } catch (e: any) {
    toast.error(e.message || '上传 Logo 失败')
  } finally {
    uploadingLogo.value = false
  }
}

/** 一键恢复默认 Logo：清空当前模式的 Logo；学习模式回退品牌 Logo。 */
async function restoreDefaultLogo() {
  if (!hasOwnLogo.value || resettingLogo.value) return
  resettingLogo.value = true
  try {
    if (themeMode.value === 'learn') {
      form.value.learn_logo_url = ''
      await system.saveSettings({ learn_logo_url: '' })
      toast.success('已恢复学习模式默认 Logo')
    } else {
      await system.resetLogo()
      form.value.logo_url = ''
      toast.success('已恢复默认 Logo')
    }
  } catch (e: any) {
    toast.error(e.message || '恢复默认 Logo 失败')
  } finally {
    resettingLogo.value = false
  }
}

async function save() {
  const name = form.value.app_name.trim()
  if (!name) {
    toast.info('请填写系统名称')
    return
  }
  saving.value = true
  try {
    const saved = await system.saveSettings({
      app_name: name,
      app_description: form.value.app_description.trim(),
      logo_url: form.value.logo_url,
      theme_color: form.value.theme_color,
      learn_theme_color: form.value.learn_theme_color,
      learn_logo_url: form.value.learn_logo_url,
      learn_description: form.value.learn_description.trim(),
    })
    hydrate(saved)
    toast.success('系统设置已保存')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const inputClass =
  'w-full rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2 text-[13px] text-slate-700 outline-none transition-colors focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60'
const labelClass = 'mb-1.5 block text-[11.5px] font-medium text-slate-600'
</script>

<template>
  <div class="page-wrap-slim px-8 py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-500 to-kiwi-600 text-white shadow-glow">
          <KiwiIcon :name="pageMeta.icon" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">{{ pageMeta.title }}</h1>
          <p class="mt-1 text-sm text-slate-500">{{ pageMeta.description }}</p>
        </div>
      </div>
      <button class="kiwi-btn-primary" :disabled="saving || loading" @click="save">
        <KiwiIcon :name="saving ? 'loader' : 'check'" :size="14" :spin="saving" />
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
    </div>

    <SettingsTabs />

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取系统设置…
    </div>

    <div v-else class="space-y-6">
      <!-- 品牌信息 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-5">
        <div class="mb-4 flex items-center gap-2">
          <KiwiIcon name="sparkle" :size="15" class="text-kiwi-500" />
          <h2 class="text-[14px] font-semibold text-slate-700">品牌信息</h2>
          <span class="text-[10px] text-slate-400">显示在顶栏、浏览器标签与说明文字中</span>
        </div>

        <div class="grid gap-5 md:grid-cols-[180px_minmax(0,1fr)]">
          <div>
            <span :class="labelClass">
              Logo · {{ themeMode === 'learn' ? '学习模式' : '编辑模式' }}
            </span>
            <div class="rounded-2xl border border-dashed border-slate-200 bg-white/60 p-3 text-center">
              <img
                v-if="logoPreview"
                :src="logoPreview"
                alt="系统 Logo"
                class="mx-auto h-20 w-20 rounded-2xl object-cover shadow-soft"
                data-logo-preview
              />
              <!-- 未上传时直接回显顶栏实际使用的默认品牌标记 -->
              <KiwiLogo
                v-else
                :mode="themeMode"
                :size="80"
                class="mx-auto h-20 w-20 rounded-2xl shadow-soft"
                data-logo-preview
              />
              <div class="mt-3 flex items-center justify-center gap-1.5">
                <button class="kiwi-btn-secondary !px-2.5 !py-1 !text-[11px]" :disabled="uploadingLogo" @click="pickLogo">
                  <KiwiIcon :name="uploadingLogo ? 'loader' : 'upload'" :size="12" :spin="uploadingLogo" />
                  {{ uploadingLogo ? '上传中' : '上传' }}
                </button>
                <button
                  v-if="hasOwnLogo"
                  class="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
                  :disabled="resettingLogo"
                  title="恢复系统默认 Logo"
                  @click="restoreDefaultLogo"
                >
                  <KiwiIcon :name="resettingLogo ? 'loader' : 'refresh'" :size="12" :spin="resettingLogo" />
                  {{ resettingLogo ? '恢复中' : '恢复默认' }}
                </button>
              </div>
              <p class="mt-2 text-[10px] leading-relaxed text-slate-400">
                <template v-if="themeMode === 'learn'">
                  {{ form.learn_logo_url ? '当前为学习模式自定义 Logo，未上传时沿用品牌 Logo' : '学习模式未单独上传，沿用品牌 Logo' }}
                </template>
                <template v-else>
                  {{ form.logo_url ? '当前为品牌自定义 Logo，PNG / JPG / WebP，2MB 以内' : '当前为系统默认 Logo，可上传图片替换' }}
                </template>
              </p>
            </div>
            <input
              ref="logoInput"
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
              class="hidden"
              @change="onLogoFile"
            />
          </div>

          <div class="space-y-4">
            <!-- 模式切换放在名称上方：两种模式沿用同一套表单布局。 -->
            <div class="flex flex-wrap items-center gap-2">
              <div class="inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white/70 p-0.5">
                <button
                  v-for="item in [
                    { value: 'edit', label: '编辑模式', icon: 'note' },
                    { value: 'learn', label: '学习模式', icon: 'learn' },
                  ]"
                  :key="item.value"
                  type="button"
                  class="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] transition-colors"
                  :class="
                    themeMode === item.value
                      ? 'bg-kiwi-50 text-kiwi-700 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700'
                  "
                  @click="switchThemeMode(item.value as ThemeMode)"
                >
                  <KiwiIcon :name="item.icon" :size="12" />
                  {{ item.label }}
                </button>
              </div>
              <span class="text-[10.5px] text-slate-400">
                配色、Logo 与描述按模式独立保存，名称全站共用。
              </span>
            </div>

            <div class="grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span :class="labelClass">系统名称</span>
                <input v-model="form.app_name" :class="inputClass" maxlength="100" placeholder="Kiwi" />
              </label>
              <label class="block">
                <span :class="labelClass">
                  一句话描述 · {{ themeMode === 'learn' ? '学习模式' : '编辑模式' }}
                </span>
                <input
                  v-model="descriptionField"
                  :class="inputClass"
                  maxlength="500"
                  :placeholder="themeMode === 'learn' ? '学习训练 · 复习' : '知识编译与检索系统'"
                />
              </label>
            </div>

            <div>
              <span :class="labelClass">
                主题色 · {{ themeMode === 'learn' ? '学习模式' : '编辑模式' }}
              </span>
              <div class="flex flex-wrap items-center gap-2">
                <button
                  v-for="preset in THEME_PRESETS"
                  :key="preset.value"
                  type="button"
                  class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors"
                  :class="
                    themeColor.toLowerCase() === preset.value
                      ? 'border-kiwi-400 bg-kiwi-50 text-kiwi-700 ring-1 ring-kiwi-300/70'
                      : 'border-slate-200 bg-white/70 text-slate-500 hover:border-kiwi-200'
                  "
                  :aria-pressed="themeColor.toLowerCase() === preset.value"
                  @click="choosePreset(preset.value)"
                >
                  <span
                    class="grid h-3.5 w-3.5 place-items-center rounded-full border border-black/10"
                    :style="{ backgroundColor: preset.value }"
                  >
                    <KiwiIcon
                      v-if="themeColor.toLowerCase() === preset.value"
                      name="check"
                      :size="9"
                      class="text-white drop-shadow-[0_1px_1px_rgba(0,0,0,0.35)]"
                    />
                  </span>
                  {{ preset.label }}
                </button>
                <div
                  class="ml-1 flex items-center gap-2 rounded-lg border px-2 py-0.5 transition-colors"
                  :class="
                    isCustomTheme
                      ? 'border-kiwi-400 bg-kiwi-50 ring-1 ring-kiwi-300/70'
                      : 'border-slate-200 bg-white/70'
                  "
                  data-theme-color-custom
                >
                  <EditorColorPicker
                    variant="bubble"
                    icon="palette"
                    title="自定义主题色"
                    label="主题色"
                    :value="themeColor"
                    :fallback="themeColor"
                    :active="isCustomTheme"
                    :clearable="false"
                    @select="choosePreset"
                  />
                  <span
                    class="font-mono text-[11px] uppercase"
                    :class="isCustomTheme ? 'text-kiwi-700' : 'text-slate-500'"
                  >
                    {{ themeColor }}
                  </span>
                </div>
              </div>
              <p class="mt-2 text-[10.5px] leading-relaxed text-slate-400">
                主题色会生成 50–900 色阶，统一应用到按钮、选中态、图表与背景光晕。
                切换上方模式即可分别配置编辑与学习空间。
              </p>
            </div>
          </div>
        </div>
      </section>

      <p class="px-1 text-[10.5px] text-slate-400">
        当前访问地址：{{ appOrigin }} · 设置保存后立即生效，无需重启服务。
      </p>
    </div>
  </div>
</template>
