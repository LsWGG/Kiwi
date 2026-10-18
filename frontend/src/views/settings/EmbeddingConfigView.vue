<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { request } from '@/api/client'
import { toast } from '@/components/ui/toast'

interface EmbeddingConfig {
  provider: 'local' | 'openai'
  api_base: string
  api_model: string
  api_timeout: number
  api_batch_size: number
  api_concurrency: number
  has_api_key: boolean
  source: 'saved' | 'env'
  active_space: string
  env_provider: 'local' | 'openai'
  env_api_base: string
  env_api_model: string
  env_has_api_key: boolean
}

interface TestResult {
  ok: boolean
  message: string
  dimensions: number | null
  latency_ms: number | null
}

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const resetting = ref(false)
const showAdvanced = ref(false)
const clearKey = ref(false)
const testResult = ref<TestResult | null>(null)

const config = ref<EmbeddingConfig | null>(null)
const form = ref({
  provider: 'local' as 'local' | 'openai',
  api_base: '',
  api_key: '',
  api_model: 'text-embedding-3-small',
  api_timeout: 60,
  api_batch_size: 64,
  api_concurrency: 4,
})

function hydrate(c: EmbeddingConfig) {
  config.value = c
  form.value = {
    provider: c.provider,
    api_base: c.api_base,
    api_key: '',
    api_model: c.api_model || 'text-embedding-3-small',
    api_timeout: c.api_timeout,
    api_batch_size: c.api_batch_size,
    api_concurrency: c.api_concurrency,
  }
  clearKey.value = false
  testResult.value = null
}

async function load() {
  loading.value = true
  try {
    hydrate(await request<EmbeddingConfig>('/settings/embedding'))
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const isRemote = computed(() => form.value.provider === 'openai')

const advancedErrors = computed(() => {
  const timeout = Number(form.value.api_timeout)
  const batch = Number(form.value.api_batch_size)
  const concurrency = Number(form.value.api_concurrency)
  return {
    timeout:
      !Number.isFinite(timeout) || timeout < 5 || timeout > 600
        ? '超时需在 5–600 秒之间'
        : '',
    batch:
      !Number.isInteger(batch) || batch < 1 || batch > 512
        ? '批大小需为 1–512 的整数'
        : '',
    concurrency:
      !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 16
        ? '并发数需为 1–16 的整数'
        : '',
  }
})
const advancedValid = computed(() => !Object.values(advancedErrors.value).some(Boolean))
const remoteReady = computed(
  () =>
    form.value.api_base.trim().startsWith('http') && !!form.value.api_model.trim(),
)
const canSave = computed(
  () => !isRemote.value || (remoteReady.value && advancedValid.value),
)
const canTest = computed(
  () =>
    remoteReady.value &&
    !advancedErrors.value.timeout,
)
const hasSavedKey = computed(() => !!config.value?.has_api_key)

function apiKeyForRequest(): string | undefined {
  if (clearKey.value) return ''
  return form.value.api_key.trim() || undefined
}

function friendlyError(message: string): string {
  if (/api_(timeout|batch_size|concurrency)/.test(message)) {
    return '高级参数超出允许范围：超时 5–600 秒、批大小 1–512、并发数 1–16'
  }
  return message
}

function clampField(
  key: 'api_timeout' | 'api_batch_size' | 'api_concurrency',
  min: number,
  max: number,
  fallback: number,
  integer = false,
) {
  const raw = Number(form.value[key])
  if (!Number.isFinite(raw)) {
    form.value[key] = fallback
    return
  }
  const value = integer ? Math.round(raw) : raw
  form.value[key] = Math.min(max, Math.max(min, value))
}

async function testConnection() {
  if (!canTest.value) {
    toast.info(
      advancedErrors.value.timeout || '请先填写以 http:// 或 https:// 开头的接口地址与模型名',
    )
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await request<TestResult>('/settings/embedding/test', {
      method: 'POST',
      body: JSON.stringify({
        provider: form.value.provider,
        api_base: form.value.api_base.trim(),
        api_key: apiKeyForRequest(),
        api_model: form.value.api_model.trim(),
        api_timeout: form.value.api_timeout,
      }),
    })
    testResult.value = res
    if (res.ok) toast.success(res.message)
    else toast.error(res.message)
  } catch (e: any) {
    const message = friendlyError(e.message)
    testResult.value = { ok: false, message, dimensions: null, latency_ms: null }
    toast.error(message)
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!canSave.value) {
    const numeric = Object.values(advancedErrors.value).filter(Boolean)
    toast.info(
      numeric.length
        ? numeric.join('；')
        : '请填写以 http:// 或 https:// 开头的接口地址与模型名',
    )
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      provider: form.value.provider,
      api_base: form.value.api_base.trim(),
      api_model: form.value.api_model.trim(),
      api_timeout: form.value.api_timeout,
      api_batch_size: form.value.api_batch_size,
      api_concurrency: form.value.api_concurrency,
    }
    const key = apiKeyForRequest()
    if (key !== undefined) payload.api_key = key
    hydrate(
      await request<EmbeddingConfig>('/settings/embedding', {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    )
    toast.success('向量模型配置已保存')
  } catch (e: any) {
    toast.error(friendlyError(e.message))
  } finally {
    saving.value = false
  }
}

async function resetToEnv() {
  resetting.value = true
  try {
    await request('/settings/embedding', { method: 'DELETE' })
    await load()
    toast.success('已恢复为环境变量配置')
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div class="page-wrap-slim px-8 py-8">
    <div class="flex items-end justify-between mb-5 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-kiwi-600 grid place-items-center text-white shadow-glow"
        >
          <KiwiIcon name="layers" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">向量模型</h1>
          <p class="text-sm text-slate-500 mt-1">
            选择本地 fastembed 或任意 OpenAI 兼容的线上 embedding 接口。
          </p>
        </div>
      </div>
    </div>

    <SettingsTabs />

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取配置…
    </div>

    <template v-else-if="config">
      <!-- 当前生效状态 -->
      <div
        class="rounded-2xl glass-strong p-5 mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 animate-fade-up"
      >
        <div class="flex items-center gap-2">
          <span
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            :class="
              config.provider === 'openai'
                ? 'bg-indigo-50 text-indigo-600 border border-indigo-100'
                : 'bg-kiwi-50 text-kiwi-700 border border-kiwi-100'
            "
          >
            <KiwiIcon :name="config.provider === 'openai' ? 'cloud' : 'server'" :size="12" />
            {{ config.provider === 'openai' ? '线上接口' : '本地 fastembed' }}
          </span>
          <span
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs"
            :class="
              config.source === 'saved'
                ? 'bg-slate-100 text-slate-600'
                : 'bg-amber-50 text-amber-700 border border-amber-100'
            "
            :title="config.source === 'env' ? '来自 KIWI_EMBED_* 环境变量' : '来自应用内保存的配置'"
          >
            {{ config.source === 'saved' ? '应用内配置' : '环境变量' }}
          </span>
        </div>
        <p class="text-xs text-slate-500">
          {{ form.provider === 'openai' ? '当前向量空间' : '默认向量空间' }}
          <code class="ml-1 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">{{
            config.active_space
          }}</code>
        </p>
        <p v-if="config.provider === 'openai'" class="text-xs text-slate-400">
          {{ config.api_model }} · {{ config.api_base.replace(/^https?:\/\//, '') }}
        </p>
      </div>

      <!-- 模式选择 -->
      <div class="grid sm:grid-cols-2 gap-3 mb-6">
        <button
          type="button"
          class="text-left rounded-2xl border p-5 transition-all"
          :class="
            form.provider === 'local'
              ? 'border-kiwi-300 bg-kiwi-50/60 shadow-soft'
              : 'border-slate-200/70 bg-white/60 hover:border-slate-300'
          "
          @click="form.provider = 'local'"
        >
          <span class="flex items-center gap-2 font-medium text-slate-700">
            <KiwiIcon name="server" :size="16" :class="form.provider === 'local' ? 'text-kiwi-600' : 'text-slate-400'" />
            本地模型
          </span>
          <span class="block text-xs text-slate-500 mt-1.5 leading-relaxed">
            fastembed ONNX，数据不出本机。模型按知识库单独选择，首次使用会下载模型文件。
          </span>
        </button>
        <button
          type="button"
          class="text-left rounded-2xl border p-5 transition-all"
          :class="
            form.provider === 'openai'
              ? 'border-indigo-300 bg-indigo-50/50 shadow-soft'
              : 'border-slate-200/70 bg-white/60 hover:border-slate-300'
          "
          @click="form.provider = 'openai'"
        >
          <span class="flex items-center gap-2 font-medium text-slate-700">
            <KiwiIcon name="cloud" :size="16" :class="form.provider === 'openai' ? 'text-indigo-500' : 'text-slate-400'" />
            线上接口
          </span>
          <span class="block text-xs text-slate-500 mt-1.5 leading-relaxed">
            调用 OpenAI 兼容的 <code>/embeddings</code>，兼容 OpenAI、Ollama、硅基流动等。
          </span>
        </button>
      </div>

      <!-- 本地说明 -->
      <div
        v-if="form.provider === 'local'"
        class="rounded-2xl glass-strong p-6 space-y-3 animate-fade-up"
      >
        <p class="text-sm text-slate-600 leading-relaxed">
          本地模式无需填写接口地址。每个知识库可在
          <RouterLink to="/kbs" class="text-kiwi-700 hover:underline">知识库管理</RouterLink>
          中选择自己的 fastembed 模型，并使用独立向量空间。
        </p>
        <p class="text-xs text-slate-400 leading-relaxed">
          若部署环境无法运行 ONNX / 无法下载模型，请切换到「线上接口」；保存后所有知识库统一使用线上模型。
        </p>
      </div>

      <!-- 线上配置 -->
      <div v-else class="rounded-2xl glass-strong p-6 space-y-5 animate-fade-up">
        <div>
          <label class="text-xs font-medium text-slate-500">接口地址（Base URL）</label>
          <input
            v-model="form.api_base"
            class="kiwi-input mt-1.5"
            placeholder="https://api.openai.com/v1"
            maxlength="300"
            spellcheck="false"
          />
          <p class="text-[11px] text-slate-400 mt-1.5">
            填到 <code>/v1</code> 即可；程序会自动请求 <code>/embeddings</code>。也兼容 Ollama：
            <code>http://host.docker.internal:11434/v1</code>。
          </p>
        </div>

        <div>
          <label class="text-xs font-medium text-slate-500">API Key（本地服务可留空）</label>
          <input
            v-model="form.api_key"
            type="password"
            name="embedding-api-key"
            class="kiwi-input mt-1.5"
            :placeholder="
              hasSavedKey || config.env_has_api_key
                ? '已配置，留空保持不变'
                : 'sk-…（可选）'
            "
            maxlength="500"
            autocomplete="new-password"
            spellcheck="false"
            @input="clearKey = false"
          />
          <label
            v-if="hasSavedKey"
            class="inline-flex items-center gap-1.5 text-[11px] text-slate-500 mt-2 cursor-pointer select-none"
          >
            <input v-model="clearKey" type="checkbox" class="accent-kiwi-600 w-3.5 h-3.5" />
            清除已保存的 Key
          </label>
        </div>

        <div>
          <label class="text-xs font-medium text-slate-500">模型名</label>
          <input
            v-model="form.api_model"
            class="kiwi-input mt-1.5"
            placeholder="text-embedding-3-small"
            maxlength="120"
            spellcheck="false"
          />
          <p class="text-[11px] text-slate-400 mt-1.5">
            例如 <code>text-embedding-3-small</code>、<code>bge-m3</code>、<code>nomic-embed-text</code>。
          </p>
        </div>

        <div>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <button
              type="button"
              class="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700"
              @click="showAdvanced = !showAdvanced"
            >
              <KiwiIcon :name="showAdvanced ? 'chevron' : 'chevron'" :size="12" :class="showAdvanced ? 'rotate-90' : ''" />
              高级参数
            </button>
            <span v-if="!advancedValid" class="text-[11px] text-red-500">
              参数超出允许范围，修正后才能保存
            </span>
          </div>
          <p v-if="showAdvanced" class="text-[11px] text-slate-400 mt-3 leading-relaxed">
            批大小是每次请求携带的文本数，并发数是同时发出的请求数。默认 64 / 4 适合大多数服务；调高可提升吞吐，但更容易触发服务商的单请求上限或 429 限流。
          </p>
          <div v-if="showAdvanced" class="grid sm:grid-cols-3 gap-3 mt-2">
            <div>
              <label class="text-[11px] text-slate-500">超时（秒，5–600）</label>
              <input
                v-model.number="form.api_timeout"
                type="number"
                min="5"
                max="600"
                class="kiwi-input mt-1"
                :class="advancedErrors.timeout ? 'ring-1 ring-red-300' : ''"
                :aria-invalid="!!advancedErrors.timeout"
                @blur="clampField('api_timeout', 5, 600, 60)"
              />
              <p v-if="advancedErrors.timeout" class="text-[11px] text-red-500 mt-1">
                {{ advancedErrors.timeout }}
              </p>
            </div>
            <div>
              <label class="text-[11px] text-slate-500">批大小（每请求文本数，1–512）</label>
              <input
                v-model.number="form.api_batch_size"
                type="number"
                min="1"
                max="512"
                step="1"
                class="kiwi-input mt-1"
                :class="advancedErrors.batch ? 'ring-1 ring-red-300' : ''"
                :aria-invalid="!!advancedErrors.batch"
                @blur="clampField('api_batch_size', 1, 512, 64, true)"
              />
              <p v-if="advancedErrors.batch" class="text-[11px] text-red-500 mt-1">
                {{ advancedErrors.batch }}
              </p>
            </div>
            <div>
              <label class="text-[11px] text-slate-500">并发数（同时请求数，1–16）</label>
              <input
                v-model.number="form.api_concurrency"
                type="number"
                min="1"
                max="16"
                step="1"
                class="kiwi-input mt-1"
                :class="advancedErrors.concurrency ? 'ring-1 ring-red-300' : ''"
                :aria-invalid="!!advancedErrors.concurrency"
                @blur="clampField('api_concurrency', 1, 16, 4, true)"
              />
              <p v-if="advancedErrors.concurrency" class="text-[11px] text-red-500 mt-1">
                {{ advancedErrors.concurrency }}
              </p>
            </div>
          </div>
        </div>

        <p
          v-if="testResult"
          class="text-sm flex items-start gap-1.5"
          :class="testResult.ok ? 'text-emerald-600' : 'text-red-500'"
        >
          <KiwiIcon :name="testResult.ok ? 'check' : 'alert'" :size="14" class="mt-0.5 shrink-0" />
          <span>
            {{ testResult.message }}
            <span v-if="testResult.latency_ms != null" class="text-xs opacity-70">
              · {{ testResult.latency_ms }} ms
            </span>
          </span>
        </p>
      </div>

      <!-- 切换提示 -->
      <div
        v-if="isRemote"
        class="mt-5 rounded-xl border border-amber-200/70 bg-amber-50/60 px-4 py-3 text-xs text-amber-800 leading-relaxed"
      >
        <strong>注意：</strong>线上模式下所有知识库共用同一向量模型；保存后若模型或服务商变化，会切换到新的向量空间，
        已有素材需要重新导入，Wiki 页可在「Wiki → 重建索引」中重新向量化。
      </div>

      <!-- 操作 -->
      <div class="flex flex-wrap items-center justify-between gap-3 mt-6">
        <div>
          <button
            v-if="config.source === 'saved'"
            class="kiwi-btn-ghost !text-slate-500"
            :disabled="resetting"
            @click="resetToEnv"
          >
            <KiwiIcon name="refresh" :size="14" />
            {{ resetting ? '恢复中…' : '恢复环境变量配置' }}
          </button>
          <p v-else class="text-[11px] text-slate-400">
            当前生效：{{ config.env_provider === 'openai' ? '环境变量 · 线上' : '环境变量 · 本地' }}
            <span v-if="config.env_api_base"> · {{ config.env_api_base }}</span>
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="isRemote"
            class="kiwi-btn-secondary"
            :disabled="testing"
            @click="testConnection"
          >
            <KiwiIcon name="loader" :size="13" :spin="testing" />
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <button class="kiwi-btn-primary" :disabled="saving" @click="save">
            <KiwiIcon name="loader" :size="13" :spin="saving" />
            {{ saving ? '保存中…' : '保存配置' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
