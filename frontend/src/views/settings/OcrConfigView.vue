<script setup lang="ts">
/**
 * OCR 配置：与大模型 / 向量模型共用「配置卡片 → 编辑表单 → 测试连接 → 保存」
 * 的操作模式；OCR 只有一份配置，因此用编辑 / 清除替代新增 / 删除。
 */
import { computed, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'
import { useSystemStore, type SystemSettings } from '@/stores/system'

/** embedded：作为「模型配置」子页渲染时隐藏独立页头与设置导航。 */
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

interface OcrTestResult {
  ok: boolean
  message: string
  sample_text: string
}

const OCR_LANGUAGES = [
  { value: 'auto', label: '自动识别' },
  { value: '中文', label: '中文' },
  { value: 'English', label: 'English' },
  { value: '日本語', label: '日本語' },
  { value: '한국어', label: '한국어' },
]

const system = useSystemStore()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const clearing = ref(false)
const editing = ref(false)
const showClear = ref(false)
const keyTouched = ref(false)
const testResult = ref<OcrTestResult | null>(null)
const saved = ref<SystemSettings | null>(null)

const form = ref({
  enabled: false,
  api_base: '',
  api_model: '',
  api_key: '',
  timeout: 120,
  language: 'auto',
})

function hydrate(settings: SystemSettings) {
  saved.value = settings
  form.value = {
    enabled: settings.ocr_enabled,
    api_base: settings.ocr_api_base,
    api_model: settings.ocr_api_model,
    api_key: '',
    timeout: settings.ocr_timeout,
    language: settings.ocr_language || 'auto',
  }
  keyTouched.value = false
  testResult.value = null
}

async function load() {
  loading.value = true
  try {
    hydrate(await system.fetchSettings(true))
  } catch (e: any) {
    toast.error(e.message || '读取 OCR 配置失败')
    hydrate(system.settings)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const hasSavedKey = computed(() => !!saved.value?.has_ocr_api_key)
const hasConfig = computed(() => {
  const value = saved.value
  return !!(
    value &&
    (value.ocr_api_base || value.ocr_api_model || value.has_ocr_api_key)
  )
})
const languageLabel = computed(
  () => OCR_LANGUAGES.find((item) => item.value === form.value.language)?.label || form.value.language,
)
const baseValid = computed(
  () => !form.value.api_base.trim() || /^https?:\/\//i.test(form.value.api_base.trim()),
)
const canSave = computed(
  () =>
    baseValid.value &&
    (!form.value.enabled || (!!form.value.api_base.trim() && !!form.value.api_model.trim())),
)

function startEdit() {
  if (!saved.value) return
  hydrate(saved.value)
  editing.value = true
}

function cancelEdit() {
  if (saved.value) hydrate(saved.value)
  editing.value = false
}

function clearApiKey() {
  form.value.api_key = ''
  keyTouched.value = true
  toast.info('保存后将清除已保存的 OCR 密钥')
}

function clampTimeout() {
  const value = Number(form.value.timeout)
  form.value.timeout = Number.isFinite(value)
    ? Math.min(600, Math.max(5, value))
    : 120
}

async function testConnection() {
  if (!baseValid.value) {
    toast.info('接口地址必须以 http:// 或 https:// 开头')
    return
  }
  if (!form.value.api_base.trim() || !form.value.api_model.trim()) {
    toast.info('请先填写 OCR 接口地址与模型名')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const payload: Record<string, unknown> = {
      api_base: form.value.api_base.trim(),
      api_model: form.value.api_model.trim(),
      timeout: form.value.timeout,
      language: form.value.language,
    }
    // 只有用户改动过密钥才随测试发送，否则后端沿用已保存的密钥。
    if (keyTouched.value) payload.api_key = form.value.api_key
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

async function save() {
  if (!canSave.value) {
    toast.info(
      baseValid.value
        ? '启用 OCR 前请填写接口地址与模型名'
        : '接口地址必须以 http:// 或 https:// 开头',
    )
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      ocr_enabled: form.value.enabled,
      ocr_provider: 'openai',
      ocr_api_base: form.value.api_base.trim(),
      ocr_api_model: form.value.api_model.trim(),
      ocr_timeout: form.value.timeout,
      ocr_language: form.value.language,
    }
    if (keyTouched.value) payload.ocr_api_key = form.value.api_key
    const updated = await system.saveSettings(payload as Partial<SystemSettings>)
    hydrate(updated)
    editing.value = false
    toast.success('OCR 配置已保存')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function clearConfig() {
  clearing.value = true
  try {
    const updated = await system.saveSettings({
      ocr_enabled: false,
      ocr_provider: 'openai',
      ocr_api_base: '',
      ocr_api_model: '',
      ocr_api_key: '',
      ocr_timeout: 120,
      ocr_language: 'auto',
    })
    hydrate(updated)
    editing.value = false
    showClear.value = false
    toast.success('已清除 OCR 配置')
  } catch (e: any) {
    toast.error(e.message || '清除 OCR 配置失败')
  } finally {
    clearing.value = false
  }
}

const inputClass =
  'w-full rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2 text-[13px] text-slate-700 outline-none transition-colors focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60'
const labelClass = 'mb-1.5 block text-[11.5px] font-medium text-slate-600'
</script>

<template>
  <div :class="embedded ? '' : 'page-wrap-slim px-8 py-8'">
    <div v-if="!embedded" class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-500 to-kiwi-600 text-white shadow-glow">
          <KiwiIcon name="scanText" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">OCR 设置</h1>
          <p class="mt-1 text-sm text-slate-500">
            为扫描件与图片配置 OpenAI 兼容的视觉识别接口。
          </p>
        </div>
      </div>
      <button v-if="!editing && saved && hasConfig" class="kiwi-btn-primary" @click="startEdit">
        <KiwiIcon name="edit" :size="15" />
        编辑配置
      </button>
    </div>

    <SettingsTabs v-if="!embedded" />

    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-xs leading-relaxed text-slate-500">
        调用 OpenAI 兼容的视觉模型识别扫描 PDF / 图片；未启用时回退到本地 tesseract。
      </p>
      <button
        v-if="!editing && saved && hasConfig && embedded"
        class="kiwi-btn-primary !py-1.5 !text-xs"
        @click="startEdit"
      >
        <KiwiIcon name="edit" :size="13" />
        编辑配置
      </button>
    </div>

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取 OCR 配置…
    </div>

    <template v-else-if="saved">
      <!-- 配置卡片 -->
      <div
        v-if="!editing && hasConfig"
        class="group flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200/70 bg-white/70 p-4 shadow-soft transition-colors hover:border-kiwi-200"
      >
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-slate-200/60 bg-gradient-to-br from-slate-100 to-white text-slate-500 transition-colors group-hover:border-kiwi-200 group-hover:text-kiwi-600">
          <KiwiIcon name="scanText" :size="16" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="truncate font-medium text-slate-700">
              {{ saved.ocr_api_model || '扫描件 OCR' }}
            </p>
            <span
              class="rounded-full px-2 py-[1px] text-[10px] font-medium"
              :class="
                saved.ocr_enabled
                  ? 'bg-gradient-to-r from-kiwi-500 to-kiwi-700 text-white'
                  : 'bg-slate-100 text-slate-500'
              "
            >
              {{ saved.ocr_enabled ? '已启用' : '未启用' }}
            </span>
          </div>
          <p class="mt-0.5 truncate font-mono text-xs text-slate-400">
            {{ saved.ocr_api_base.replace(/^https?:\/\//, '') || '未配置接口地址' }}
            <span v-if="saved.ocr_api_model"> · {{ saved.ocr_api_model }}</span>
          </p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">
            语言 {{ languageLabel }} · 超时 {{ saved.ocr_timeout }} 秒
          </p>
        </div>
        <span
          class="flex shrink-0 items-center gap-1 text-xs text-slate-400"
          :title="saved.has_ocr_api_key ? '已配置密钥' : '无密钥'"
        >
          <KiwiIcon
            :name="saved.has_ocr_api_key ? 'check' : 'close'"
            :size="12"
            :class="saved.has_ocr_api_key ? 'text-emerald-500' : 'text-slate-300'"
          />
          {{ saved.has_ocr_api_key ? '有 Key' : '无 Key' }}
        </span>
        <button class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0" @click="startEdit">
          <KiwiIcon name="edit" :size="13" />
          编辑
        </button>
        <button
          class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0 !text-slate-400 hover:!text-red-500"
          title="清除 OCR 配置"
          @click="showClear = true"
        >
          <KiwiIcon name="trash" :size="13" />
        </button>
      </div>

      <!-- 空态 -->
      <div
        v-else-if="!editing"
        class="rounded-2xl border border-dashed border-slate-200 bg-white/50 py-14 text-center"
      >
        <div class="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl border border-kiwi-100 bg-gradient-to-br from-kiwi-100 to-white text-kiwi-400">
          <KiwiIcon name="scanText" :size="26" />
        </div>
        <p class="text-sm text-slate-500">还没有配置 OCR 接口</p>
        <p class="mb-5 mt-1.5 text-xs text-slate-400">
          配置后可在导入扫描件时启用线上识别，否则使用本地 tesseract。
        </p>
        <button class="kiwi-btn-primary" @click="startEdit">
          <KiwiIcon name="plus" :size="16" />
          添加配置
        </button>
      </div>

      <!-- 编辑表单 -->
      <div v-if="editing" class="space-y-5 rounded-2xl glass-strong p-6 animate-scale-in">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <span class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-100 to-white text-slate-500">
              <KiwiIcon name="scanText" :size="16" />
            </span>
            <div>
              <p class="text-sm font-semibold text-slate-700">扫描件 OCR</p>
              <p class="text-[10.5px] text-slate-400">OpenAI 兼容的视觉识别接口</p>
            </div>
          </div>
          <label class="flex cursor-pointer select-none items-center gap-2 text-[11.5px] text-slate-600">
            <button
              type="button"
              role="switch"
              :aria-checked="form.enabled"
              class="relative h-5 w-9 rounded-full transition-colors"
              :class="form.enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
              @click="form.enabled = !form.enabled"
            >
              <span
                class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
                :class="form.enabled ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
            {{ form.enabled ? '已启用' : '未启用' }}
          </label>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="block">
            <span :class="labelClass">接口地址（Base URL）</span>
            <input
              v-model="form.api_base"
              :class="[inputClass, baseValid ? '' : 'ring-1 ring-red-300']"
              :aria-invalid="!baseValid"
              placeholder="https://api.openai.com/v1 或中转地址"
              maxlength="500"
              spellcheck="false"
            />
            <p v-if="!baseValid" class="mt-1 text-[11px] text-red-500">
              接口地址必须以 http:// 或 https:// 开头
            </p>
          </label>
          <label class="block">
            <span :class="labelClass">模型名称</span>
            <input
              v-model="form.api_model"
              :class="inputClass"
              placeholder="gpt-4o-mini"
              maxlength="200"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span :class="labelClass">
              API Key
              <span
                v-if="hasSavedKey && !keyTouched"
                class="ml-1 text-[10px] font-normal text-emerald-600"
              >
                已保存 · 留空保持不变
              </span>
            </span>
            <div class="flex items-center gap-2">
              <input
                v-model="form.api_key"
                type="password"
                :class="inputClass"
                autocomplete="new-password"
                :placeholder="hasSavedKey ? '••••••••（留空保持不变）' : 'sk-…'"
                @input="keyTouched = true"
              />
              <button
                v-if="hasSavedKey || form.api_key"
                class="shrink-0 rounded-lg px-2 py-1.5 text-[10.5px] text-rose-500 transition-colors hover:bg-rose-50"
                @click="clearApiKey"
              >
                清除
              </button>
            </div>
          </label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block">
              <span :class="labelClass">超时（秒，5–600）</span>
              <input
                v-model.number="form.timeout"
                type="number"
                min="5"
                max="600"
                :class="inputClass"
                @blur="clampTimeout"
              />
            </label>
            <label class="block">
              <span :class="labelClass">文档语言</span>
              <select v-model="form.language" :class="inputClass">
                <option v-for="item in OCR_LANGUAGES" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
          </div>
        </div>

        <div
          v-if="testResult"
          class="rounded-xl border px-3 py-2.5 text-[11.5px] leading-relaxed"
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

        <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div>
            <button
              v-if="hasConfig"
              class="kiwi-btn-ghost !text-slate-500 hover:!text-red-500"
              @click="showClear = true"
            >
              <KiwiIcon name="trash" :size="14" />
              清除配置
            </button>
          </div>
          <div class="flex items-center gap-2">
            <button class="kiwi-btn-ghost" @click="cancelEdit">取消</button>
            <button class="kiwi-btn-secondary" :disabled="testing" @click="testConnection">
              <KiwiIcon name="loader" :size="13" :spin="testing" />
              {{ testing ? '测试中…' : '测试连接' }}
            </button>
            <button class="kiwi-btn-primary" :disabled="!canSave || saving" @click="save">
              <KiwiIcon :name="saving ? 'loader' : 'check'" :size="14" :spin="saving" />
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
        <p class="text-[11px] text-slate-400">
          保存前可先「测试连接」；更新配置时不填 Key 则保留原值。
        </p>
      </div>
    </template>

    <!-- 清除确认 -->
    <KiwiModal :open="showClear" title="清除 OCR 配置" @close="showClear = false">
      <div class="space-y-4">
        <p class="text-sm text-slate-600">
          确定清除 OCR 接口地址、模型与密钥吗？清除后将回退到本地 tesseract。
        </p>
        <div class="flex justify-end gap-2">
          <button class="kiwi-btn-ghost" @click="showClear = false">取消</button>
          <button class="kiwi-btn-danger" :disabled="clearing" @click="clearConfig">
            {{ clearing ? '清除中…' : '确认清除' }}
          </button>
        </div>
      </div>
    </KiwiModal>
  </div>
</template>
