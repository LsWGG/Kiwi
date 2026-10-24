<script setup lang="ts">
/**
 * 向量模型配置：与大模型 / OCR 共用「配置卡片 → 编辑表单 → 测试连接 → 保存」
 * 的操作模式；向量模型只有一份配置，以「恢复环境变量」代替删除。
 */
import { computed, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
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

/** embedded：作为「模型配置」子页渲染时隐藏独立页头与设置导航。 */
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const resetting = ref(false)
const showAdvanced = ref(false)
const clearKey = ref(false)
const editing = ref(false)
const showReset = ref(false)
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

function startEdit() {
  if (!config.value) return
  const current = config.value
  hydrate(current)
  editing.value = true
}

function cancelEdit() {
  if (config.value) hydrate(config.value)
  editing.value = false
}

const isRemote = computed(() => form.value.provider === 'openai')
const displayName = computed(() =>
  config.value?.provider === 'openai'
    ? config.value.api_model || '线上向量模型'
    : '本地 fastembed',
)
const displayEndpoint = computed(() =>
  config.value?.provider === 'openai'
    ? config.value.api_base.replace(/^https?:\/\//, '')
    : '本地 ONNX · 数据不出本机',
)
const sourceLabel = computed(() =>
  config.value?.source === 'saved' ? '应用内配置' : '环境变量',
)
const hasKey = computed(() =>
  config.value?.source === 'saved'
    ? config.value.has_api_key
    : config.value?.env_has_api_key,
)

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
    editing.value = false
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
    editing.value = false
    showReset.value = false
    toast.success('已恢复为环境变量配置')
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div :class="embedded ? '' : 'page-wrap-slim px-8 py-8'">
    <!-- 页头 -->
    <div v-if="!embedded" class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-400 to-kiwi-600 text-white shadow-glow">
          <KiwiIcon name="layers" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">向量模型</h1>
          <p class="mt-1 text-sm text-slate-500">
            选择本地 fastembed 或任意 OpenAI 兼容的线上 embedding 接口。
          </p>
        </div>
      </div>
      <button v-if="!editing && config" class="kiwi-btn-primary" @click="startEdit">
        <KiwiIcon name="edit" :size="15" />
        编辑配置
      </button>
    </div>

    <SettingsTabs v-if="!embedded" />

    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-xs leading-relaxed text-slate-500">
        本地 fastembed 数据不出本机；线上接口兼容 OpenAI、Ollama、硅基流动等。
      </p>
      <button
        v-if="!editing && config && embedded"
        class="kiwi-btn-primary !py-1.5 !text-xs"
        @click="startEdit"
      >
        <KiwiIcon name="edit" :size="13" />
        编辑配置
      </button>
    </div>

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取配置…
    </div>

    <template v-else-if="config">
      <!-- 配置卡片 -->
      <div
        v-if="!editing"
        class="group flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200/70 bg-white/70 p-4 shadow-soft transition-colors hover:border-kiwi-200"
      >
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-slate-200/60 bg-gradient-to-br from-slate-100 to-white text-slate-500 transition-colors group-hover:border-kiwi-200 group-hover:text-kiwi-600">
          <KiwiIcon :name="config.provider === 'openai' ? 'cloud' : 'server'" :size="16" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="truncate font-medium text-slate-700">{{ displayName }}</p>
            <span
              class="rounded-full px-2 py-[1px] text-[10px] font-medium"
              :class="
                config.source === 'saved'
                  ? 'bg-gradient-to-r from-kiwi-500 to-kiwi-700 text-white'
                  : 'bg-amber-50 text-amber-700 ring-1 ring-amber-100'
              "
              :title="config.source === 'env' ? '来自 KIWI_EMBED_* 环境变量' : '来自应用内保存的配置'"
            >
              {{ sourceLabel }}
            </span>
          </div>
          <p class="mt-0.5 truncate font-mono text-xs text-slate-400">
            {{ displayEndpoint }}
          </p>
          <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10.5px] text-slate-400">
            <span class="inline-flex items-center gap-1">
              向量空间
              <code class="rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-500">{{ config.active_space }}</code>
            </span>
            <span v-if="config.provider === 'openai'">
              批量 {{ config.api_batch_size }} / 并发 {{ config.api_concurrency }} / 超时 {{ config.api_timeout }}s
            </span>
          </p>
        </div>
        <span
          v-if="config.provider === 'openai'"
          class="flex shrink-0 items-center gap-1 text-xs text-slate-400"
          :title="hasKey ? '已配置密钥' : '无密钥'"
        >
          <KiwiIcon
            :name="hasKey ? 'check' : 'close'"
            :size="12"
            :class="hasKey ? 'text-emerald-500' : 'text-slate-300'"
          />
          {{ hasKey ? '有 Key' : '无 Key' }}
        </span>
        <button class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0" @click="startEdit">
          <KiwiIcon name="edit" :size="13" />
          编辑
        </button>
        <button
          v-if="config.source === 'saved'"
          class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0 !text-slate-400 hover:!text-red-500"
          title="恢复环境变量配置"
          @click="showReset = true"
        >
          <KiwiIcon name="refresh" :size="13" />
        </button>
      </div>

      <!-- 编辑表单 -->
      <div v-if="editing" class="space-y-5 rounded-2xl glass-strong p-6 animate-scale-in">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <span class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-100 to-white text-slate-500">
              <KiwiIcon name="layers" :size="16" />
            </span>
            <div>
              <p class="text-sm font-semibold text-slate-700">向量模型配置</p>
              <p class="text-[10.5px] text-slate-400">
                当前生效的向量空间：{{ config.active_space }}
              </p>
            </div>
          </div>
          <span
            v-if="config.source === 'env'"
            class="rounded-full bg-amber-50 px-2 py-[1px] text-[10px] text-amber-700 ring-1 ring-amber-100"
          >
            环境变量 · 保存后使用应用内配置
          </span>
        </div>

        <!-- 模式选择 -->
        <div class="grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            class="rounded-2xl border p-4 text-left transition-all"
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
            <span class="mt-1.5 block text-xs leading-relaxed text-slate-500">
              fastembed ONNX，数据不出本机。模型按知识库单独选择。
            </span>
          </button>
          <button
            type="button"
            class="rounded-2xl border p-4 text-left transition-all"
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
            <span class="mt-1.5 block text-xs leading-relaxed text-slate-500">
              调用 OpenAI 兼容的 <code>/embeddings</code>，所有知识库共用。
            </span>
          </button>
        </div>

        <!-- 本地说明 -->
        <div v-if="form.provider === 'local'" class="rounded-xl border border-slate-200/70 bg-white/60 p-4">
          <p class="text-sm leading-relaxed text-slate-600">
            本地模式无需填写接口地址。每个知识库可在
            <RouterLink to="/kbs" class="text-kiwi-700 hover:underline">知识库管理</RouterLink>
            中选择自己的 fastembed 模型，并使用独立向量空间。
          </p>
          <p class="mt-2 text-xs leading-relaxed text-slate-400">
            若部署环境无法运行 ONNX / 无法下载模型，请切换到「线上接口」；保存后所有知识库统一使用线上模型。
          </p>
        </div>

        <!-- 线上配置 -->
        <template v-else>
          <div>
            <label class="text-xs font-medium text-slate-500">接口地址（Base URL）</label>
            <input
              v-model="form.api_base"
              class="kiwi-input mt-1.5"
              placeholder="https://api.openai.com/v1"
              maxlength="300"
              spellcheck="false"
            />
            <p class="mt-1.5 text-[11px] text-slate-400">
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
              class="mt-2 inline-flex cursor-pointer select-none items-center gap-1.5 text-[11px] text-slate-500"
            >
              <input v-model="clearKey" type="checkbox" class="h-3.5 w-3.5 accent-kiwi-600" />
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
            <p class="mt-1.5 text-[11px] text-slate-400">
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
                <KiwiIcon name="chevron" :size="12" :class="showAdvanced ? 'rotate-90' : ''" />
                高级参数
              </button>
              <span v-if="!advancedValid" class="text-[11px] text-red-500">
                参数超出允许范围，修正后才能保存
              </span>
            </div>
            <p v-if="showAdvanced" class="mt-3 text-[11px] leading-relaxed text-slate-400">
              批大小是每次请求携带的文本数，并发数是同时发出的请求数。默认 64 / 4 适合大多数服务；调高可提升吞吐，但更容易触发服务商的单请求上限或 429 限流。
            </p>
            <div v-if="showAdvanced" class="mt-2 grid gap-3 sm:grid-cols-3">
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
                <p v-if="advancedErrors.timeout" class="mt-1 text-[11px] text-red-500">
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
                <p v-if="advancedErrors.batch" class="mt-1 text-[11px] text-red-500">
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
                <p v-if="advancedErrors.concurrency" class="mt-1 text-[11px] text-red-500">
                  {{ advancedErrors.concurrency }}
                </p>
              </div>
            </div>
          </div>
        </template>

        <p
          v-if="testResult"
          class="flex items-start gap-1.5 text-sm"
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

        <!-- 切换提示 -->
        <div
          v-if="isRemote"
          class="rounded-xl border border-amber-200/70 bg-amber-50/60 px-4 py-3 text-xs leading-relaxed text-amber-800"
        >
          <strong>注意：</strong>线上模式下所有知识库共用同一向量模型；保存后若模型或服务商变化，会切换到新的向量空间，
          已有素材需要重新导入，Wiki 页可在「Wiki → 重建索引」中重新向量化。
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div>
            <button
              v-if="config.source === 'saved'"
              class="kiwi-btn-ghost !text-slate-500 hover:!text-red-500"
              :disabled="resetting"
              @click="showReset = true"
            >
              <KiwiIcon name="refresh" :size="14" />
              恢复环境变量配置
            </button>
            <p v-else class="text-[11px] text-slate-400">
              当前生效：{{ config.env_provider === 'openai' ? '环境变量 · 线上' : '环境变量 · 本地' }}
              <span v-if="config.env_api_base"> · {{ config.env_api_base }}</span>
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button class="kiwi-btn-ghost" @click="cancelEdit">取消</button>
            <button
              v-if="isRemote"
              class="kiwi-btn-secondary"
              :disabled="testing"
              @click="testConnection"
            >
              <KiwiIcon name="loader" :size="13" :spin="testing" />
              {{ testing ? '测试中…' : '测试连接' }}
            </button>
            <button class="kiwi-btn-primary" :disabled="saving || !canSave" @click="save">
              <KiwiIcon :name="saving ? 'loader' : 'check'" :size="13" :spin="saving" />
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
        <p class="text-[11px] text-slate-400">保存前可先「测试连接」；更新配置时不填 Key 则保留原值。</p>
      </div>
    </template>

    <!-- 恢复环境变量确认 -->
    <KiwiModal :open="showReset" title="恢复环境变量配置" @close="showReset = false">
      <div class="space-y-4">
        <p class="text-sm text-slate-600">
          确定删除应用内保存的向量模型配置吗？删除后将回退到 KIWI_EMBED_* 环境变量。
        </p>
        <div class="flex justify-end gap-2">
          <button class="kiwi-btn-ghost" @click="showReset = false">取消</button>
          <button class="kiwi-btn-danger" :disabled="resetting" @click="resetToEnv">
            {{ resetting ? '恢复中…' : '确认恢复' }}
          </button>
        </div>
      </div>
    </KiwiModal>
  </div>
</template>
