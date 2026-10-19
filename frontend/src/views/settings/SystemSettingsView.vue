<script setup lang="ts">
/**
 * 系统设置：品牌名称 / 描述 / Logo / 主题色，以及扫描件线上 OCR。
 * 保存后立即写入全局状态，顶栏、浏览器标题和主题色同步更新。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiLogo from '@/components/ui/KiwiLogo.vue'
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

/** 品牌与 OCR 是两个互不相关的设置域，按路由拆成独立页面。 */
const props = withDefaults(
  defineProps<{ section?: 'brand' | 'ocr' }>(),
  { section: 'brand' },
)
const isOcr = computed(() => props.section === 'ocr')
const pageMeta = computed(() =>
  isOcr.value
    ? {
        icon: 'scanText',
        title: 'OCR 设置',
        description: '为扫描件与图片配置 OpenAI 兼容的视觉识别接口。',
      }
    : {
        icon: 'palette',
        title: '品牌设置',
        description: '自定义系统名称、描述、Logo 与主题色，显示在顶栏与浏览器标签。',
      },
)

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
const testing = ref(false)
const uploadingLogo = ref(false)
const resettingLogo = ref(false)
const logoInput = ref<HTMLInputElement | null>(null)
const keyTouched = ref(false)
const testResult = ref<{ ok: boolean; message: string; sample_text: string } | null>(null)

const form = ref({
  app_name: DEFAULT_SYSTEM_SETTINGS.app_name,
  app_description: DEFAULT_SYSTEM_SETTINGS.app_description,
  logo_url: '',
  theme_color: DEFAULT_THEME_COLOR,
  learn_theme_color: DEFAULT_LEARN_THEME_COLOR,
  ocr_enabled: false,
  ocr_provider: 'openai',
  ocr_api_base: '',
  ocr_api_model: '',
  ocr_api_key: '',
  ocr_timeout: 120,
  ocr_language: 'auto',
})

const THEME_PRESETS = [
  { label: '冷紫', value: '#5a55c7' },
  { label: '靛蓝', value: '#2563eb' },
  { label: '青绿', value: '#059669' },
  { label: '琥珀', value: '#d97706' },
  { label: '玫红', value: '#db2777' },
  { label: '石墨', value: '#475569' },
]

const OCR_LANGUAGES = [
  { value: 'auto', label: '自动识别' },
  { value: '中文', label: '中文' },
  { value: 'English', label: 'English' },
  { value: '日本語', label: '日本語' },
  { value: '한국어', label: '한국어' },
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

const hasSavedKey = ref(false)
const appOrigin = computed(() => (import.meta.env.DEV ? 'http://localhost:5173' : window.location.origin))

function hydrate(settings: SystemSettings) {
  form.value = {
    app_name: settings.app_name,
    app_description: settings.app_description,
    logo_url: settings.logo_url,
    theme_color: settings.theme_color,
    learn_theme_color: settings.learn_theme_color || DEFAULT_LEARN_THEME_COLOR,
    ocr_enabled: settings.ocr_enabled,
    ocr_provider: settings.ocr_provider || 'openai',
    ocr_api_base: settings.ocr_api_base,
    ocr_api_model: settings.ocr_api_model,
    ocr_api_key: '',
    ocr_timeout: settings.ocr_timeout,
    ocr_language: settings.ocr_language || 'auto',
  }
  hasSavedKey.value = settings.has_ocr_api_key
  keyTouched.value = false
  testResult.value = null
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
    form.value.logo_url = await system.uploadLogo(file)
    toast.success('Logo 已上传，保存后生效')
  } catch (e: any) {
    toast.error(e.message || '上传 Logo 失败')
  } finally {
    uploadingLogo.value = false
  }
}

/** 一键恢复默认 Logo：立即清空自定义 Logo 并同步顶栏。 */
async function restoreDefaultLogo() {
  if (!form.value.logo_url || resettingLogo.value) return
  resettingLogo.value = true
  try {
    await system.resetLogo()
    form.value.logo_url = ''
    toast.success('已恢复默认 Logo')
  } catch (e: any) {
    toast.error(e.message || '恢复默认 Logo 失败')
  } finally {
    resettingLogo.value = false
  }
}

function clearKey() {
  form.value.ocr_api_key = ''
  keyTouched.value = true
  hasSavedKey.value = false
  toast.info('保存后将清除已保存的 OCR 密钥')
}

async function save() {
  const name = form.value.app_name.trim()
  if (!isOcr.value && !name) {
    toast.info('请填写系统名称')
    return
  }
  if (form.value.ocr_enabled && (!form.value.ocr_api_base.trim() || !form.value.ocr_api_model.trim())) {
    toast.info('启用线上 OCR 前请填写接口地址与模型名')
    return
  }
  if (form.value.ocr_api_base && !/^https?:\/\//i.test(form.value.ocr_api_base.trim())) {
    toast.info('OCR 接口地址必须以 http:// 或 https:// 开头')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      app_name: name,
      app_description: form.value.app_description.trim(),
      logo_url: form.value.logo_url,
      theme_color: form.value.theme_color,
      learn_theme_color: form.value.learn_theme_color,
      ocr_enabled: form.value.ocr_enabled,
      ocr_provider: form.value.ocr_provider,
      ocr_api_base: form.value.ocr_api_base.trim(),
      ocr_api_model: form.value.ocr_api_model.trim(),
      ocr_timeout: form.value.ocr_timeout,
      ocr_language: form.value.ocr_language,
    }
    if (keyTouched.value) payload.ocr_api_key = form.value.ocr_api_key
    const saved = await system.saveSettings(payload as Partial<SystemSettings>)
    hydrate(saved)
    toast.success('系统设置已保存')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testOcr() {
  if (!form.value.ocr_api_base.trim() || !form.value.ocr_api_model.trim()) {
    toast.info('请先填写 OCR 接口地址与模型名')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const payload: Record<string, unknown> = {
      api_base: form.value.ocr_api_base.trim(),
      api_model: form.value.ocr_api_model.trim(),
      timeout: form.value.ocr_timeout,
      language: form.value.ocr_language,
    }
    // 未重新输入密钥时让后端使用已保存的密钥。
    if (keyTouched.value && form.value.ocr_api_key) payload.api_key = form.value.ocr_api_key
    const result = await system.testOcr(payload)
    testResult.value = result
    if (result.ok) toast.success('OCR 接口连接成功')
    else toast.error(result.message || 'OCR 接口连接失败')
  } catch (e: any) {
    testResult.value = { ok: false, message: e.message || '测试失败', sample_text: '' }
    toast.error(e.message || '测试失败')
  } finally {
    testing.value = false
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
      <section v-if="!isOcr" class="animate-fade-up rounded-2xl glass-strong p-5">
        <div class="mb-4 flex items-center gap-2">
          <KiwiIcon name="sparkle" :size="15" class="text-kiwi-500" />
          <h2 class="text-[14px] font-semibold text-slate-700">品牌信息</h2>
          <span class="text-[10px] text-slate-400">显示在顶栏、浏览器标签与说明文字中</span>
        </div>

        <div class="grid gap-5 md:grid-cols-[180px_minmax(0,1fr)]">
          <div>
            <span :class="labelClass">Logo</span>
            <div class="rounded-2xl border border-dashed border-slate-200 bg-white/60 p-3 text-center">
              <img
                v-if="form.logo_url"
                :src="form.logo_url"
                alt="系统 Logo"
                class="mx-auto h-20 w-20 rounded-2xl object-cover shadow-soft"
              />
              <!-- 未上传时直接回显顶栏实际使用的默认品牌标记 -->
              <KiwiLogo
                v-else
                :mode="mode.mode === 'learn' ? 'learn' : 'edit'"
                :size="80"
                class="mx-auto h-20 w-20 rounded-2xl shadow-soft"
              />
              <div class="mt-3 flex items-center justify-center gap-1.5">
                <button class="kiwi-btn-secondary !px-2.5 !py-1 !text-[11px]" :disabled="uploadingLogo" @click="pickLogo">
                  <KiwiIcon :name="uploadingLogo ? 'loader' : 'upload'" :size="12" :spin="uploadingLogo" />
                  {{ uploadingLogo ? '上传中' : '上传' }}
                </button>
                <button
                  v-if="form.logo_url"
                  class="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
                  :disabled="resettingLogo"
                  title="立即恢复系统默认 Logo"
                  @click="restoreDefaultLogo"
                >
                  <KiwiIcon :name="resettingLogo ? 'loader' : 'refresh'" :size="12" :spin="resettingLogo" />
                  {{ resettingLogo ? '恢复中' : '恢复默认' }}
                </button>
              </div>
              <p class="mt-2 text-[10px] leading-relaxed text-slate-400">
                {{ form.logo_url ? '当前为自定义 Logo，PNG / JPG / WebP，2MB 以内' : '当前为系统默认 Logo，可上传图片替换' }}
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
            <div class="grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span :class="labelClass">系统名称</span>
                <input v-model="form.app_name" :class="inputClass" maxlength="100" placeholder="Kiwi" />
              </label>
              <label class="block">
                <span :class="labelClass">一句话描述</span>
                <input
                  v-model="form.app_description"
                  :class="inputClass"
                  maxlength="500"
                  placeholder="知识编译与检索系统"
                />
              </label>
            </div>

            <div>
              <div class="mb-2 flex flex-wrap items-center gap-2">
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
                  两种模式的配色独立保存，名称、描述与 Logo 全站共用。
                </span>
              </div>
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
                      ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                      : 'border-slate-200 bg-white/70 text-slate-500 hover:border-kiwi-200'
                  "
                  @click="choosePreset(preset.value)"
                >
                  <span
                    class="h-3 w-3 rounded-full border border-black/10"
                    :style="{ backgroundColor: preset.value }"
                  />
                  {{ preset.label }}
                </button>
                <label class="ml-1 flex items-center gap-2 rounded-lg border border-slate-200 bg-white/70 px-2 py-1">
                  <input
                    v-model="themeColor"
                    type="color"
                    class="h-5 w-7 cursor-pointer rounded border-0 bg-transparent p-0"
                    @input="previewTheme"
                  />
                  <span class="font-mono text-[11px] uppercase text-slate-500">{{ themeColor }}</span>
                </label>
              </div>
              <p class="mt-2 text-[10.5px] leading-relaxed text-slate-400">
                主题色会生成 50–900 色阶，统一应用到按钮、选中态、图表与背景光晕。
                切换上方模式即可分别配置编辑与学习空间。
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- OCR -->
      <section v-else class="animate-fade-up rounded-2xl glass-strong p-5">
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-2">
            <KiwiIcon name="scanText" :size="15" class="text-kiwi-500" />
            <h2 class="text-[14px] font-semibold text-slate-700">扫描件 OCR</h2>
          </div>
          <span class="text-[10px] text-slate-400">
            调用 OpenAI 兼容的视觉模型识别扫描 PDF / 图片；未启用时回退到本地 tesseract。
          </span>
          <label class="ml-auto flex cursor-pointer items-center gap-2 text-[11.5px] text-slate-600">
            <button
              type="button"
              role="switch"
              :aria-checked="form.ocr_enabled"
              class="relative h-5 w-9 rounded-full transition-colors"
              :class="form.ocr_enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
              @click="form.ocr_enabled = !form.ocr_enabled"
            >
              <span
                class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
                :class="form.ocr_enabled ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
            {{ form.ocr_enabled ? '已启用' : '未启用' }}
          </label>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="block">
            <span :class="labelClass">接口地址</span>
            <input
              v-model="form.ocr_api_base"
              :class="inputClass"
              placeholder="https://api.openai.com/v1 或中转地址"
            />
          </label>
          <label class="block">
            <span :class="labelClass">模型名称</span>
            <input v-model="form.ocr_api_model" :class="inputClass" placeholder="gpt-4o-mini" />
          </label>
          <label class="block">
            <span :class="labelClass">
              API Key
              <span v-if="hasSavedKey && !keyTouched" class="ml-1 text-[10px] font-normal text-emerald-600">
                已保存 · 留空保持不变
              </span>
            </span>
            <div class="flex items-center gap-2">
              <input
                v-model="form.ocr_api_key"
                type="password"
                :class="inputClass"
                autocomplete="new-password"
                :placeholder="hasSavedKey ? '••••••••（留空保持不变）' : 'sk-…'"
                @input="keyTouched = true"
              />
              <button
                v-if="hasSavedKey || form.ocr_api_key"
                class="shrink-0 rounded-lg px-2 py-1.5 text-[10.5px] text-rose-500 transition-colors hover:bg-rose-50"
                @click="clearKey"
              >
                清除
              </button>
            </div>
          </label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block">
              <span :class="labelClass">超时（秒）</span>
              <input v-model.number="form.ocr_timeout" type="number" min="5" max="600" :class="inputClass" />
            </label>
            <label class="block">
              <span :class="labelClass">文档语言</span>
              <select v-model="form.ocr_language" :class="inputClass">
                <option v-for="item in OCR_LANGUAGES" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <button class="kiwi-btn-secondary" :disabled="testing" @click="testOcr">
            <KiwiIcon :name="testing ? 'loader' : 'play'" :size="13" :spin="testing" />
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <span class="text-[10.5px] text-slate-400">
            测试会发送一张内置测试图；超时时间按实际接口响应调整。
          </span>
        </div>

        <div
          v-if="testResult"
          class="mt-3 rounded-xl border px-3 py-2.5 text-[11.5px] leading-relaxed"
          :class="
            testResult.ok
              ? 'border-emerald-200 bg-emerald-50/70 text-emerald-700'
              : 'border-rose-200 bg-rose-50/70 text-rose-600'
          "
        >
          <p class="flex items-center gap-1.5 font-medium">
            <KiwiIcon :name="testResult.ok ? 'check' : 'alert'" :size="13" />
            {{ testResult.message }}
          </p>
          <pre
            v-if="testResult.sample_text"
            class="mt-1.5 max-h-24 overflow-auto whitespace-pre-wrap rounded-lg bg-white/70 p-2 font-mono text-[10.5px] text-slate-500"
          >{{ testResult.sample_text }}</pre>
        </div>
      </section>

      <div class="flex items-center justify-between rounded-xl border border-slate-200/70 bg-white/50 px-4 py-3">
        <p class="text-[10.5px] text-slate-400">
          当前访问地址：{{ appOrigin }} · 设置保存后立即生效，无需重启服务。
        </p>
        <button class="kiwi-btn-primary" :disabled="saving" @click="save">
          <KiwiIcon :name="saving ? 'loader' : 'check'" :size="14" :spin="saving" />
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </div>
    </div>
  </div>
</template>
