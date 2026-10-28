<script setup lang="ts">
/**
 * 桌面设置：离线运行状态、数据位置、外部模型开关与本机执行策略。
 *
 * 仅在桌面构建注册。默认值全部为「不允许联网 / 不允许本机执行」；
 * 开启任一风险开关都必须经过确认，后端同时校验 acknowledge_risk。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'
import { useDesktopStore, type DesktopSettingsPatch } from '@/stores/desktop'

const desktop = useDesktopStore()
const router = useRouter()

const busy = ref(false)
const confirmOnline = ref(false)
const confirmLocal = ref(false)
const timeoutDraft = ref(60)

const OFFLINE_FEATURES = [
  { key: 'link_fetch', label: '网页链接抓取', hint: '已有链接笔记的正文仍可阅读' },
  { key: 'remote_import', label: '远程 URL 导入', hint: '本地文件上传不受影响' },
  { key: 'online_ocr', label: '在线 OCR', hint: '扫描件回退本地解析 / Tesseract' },
  { key: 'feishu', label: '飞书妙记 / 语音转写', hint: '桌面版不启用远程转写' },
  { key: 'web_push', label: 'Web Push 提醒', hint: '桌面版不注册推送 Service Worker' },
  { key: 'study_web_search', label: '学习联网核查', hint: '出题与复习仍可离线使用' },
  { key: 'youtube_embed', label: 'YouTube 嵌入', hint: '外部 iframe 显示为本地占位' },
  { key: 'external_images', label: '远程图片 / favicon', hint: '只加载本机与同源资源' },
] as const

const llmState = computed(() => {
  if (!desktop.ready) return '读取中…'
  return desktop.llmConfigured ? '已配置' : '未配置'
})

const embeddingState = computed(() => {
  if (!desktop.ready) return '读取中…'
  return desktop.embeddingEnabled
    ? `已启用（${desktop.embeddingProvider}）`
    : '未启用（仅笔记检索可用）'
})

onMounted(async () => {
  await desktop.load()
  timeoutDraft.value = desktop.localCodeTimeout
})

async function apply(
  patch: DesktopSettingsPatch,
  successMessage: string,
): Promise<void> {
  busy.value = true
  try {
    await desktop.updateSettings(patch)
    timeoutDraft.value = desktop.localCodeTimeout
    toast.success(successMessage)
  } catch (e: any) {
    toast.error(e?.message || '保存桌面设置失败')
  } finally {
    busy.value = false
  }
}

function toggleOnlineModels(): void {
  if (busy.value) return
  if (desktop.onlineModelsAllowed) {
    void apply({ allow_online_models: false }, '已关闭外部模型接口')
    return
  }
  confirmOnline.value = true
}

function confirmOnlineModels(): void {
  void apply(
    { allow_online_models: true, acknowledge_risk: true },
    '已允许连接外部模型接口',
  )
}

function toggleLocalCode(): void {
  if (busy.value || !desktop.localCodeAvailable) return
  if (desktop.localCodeEnabled) {
    void apply({ local_code_execution: false }, '已关闭本机代码执行')
    return
  }
  confirmLocal.value = true
}

function confirmLocalCode(): void {
  void apply(
    { local_code_execution: true, acknowledge_risk: true },
    '已开启本机代码执行（非隔离）',
  )
}

function saveTimeout(): void {
  if (busy.value) return
  const value = Number(timeoutDraft.value)
  if (!Number.isFinite(value) || value < 5 || value > 600) {
    timeoutDraft.value = desktop.localCodeTimeout
    toast.error('超时时间需在 5–600 秒之间')
    return
  }
  if (value === desktop.localCodeTimeout) return
  void apply(
    { local_code_timeout_seconds: Math.round(value) },
    '已更新本机执行超时',
  )
}

async function copyPath(value: string, label: string): Promise<void> {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    toast.success(`${label}已复制`)
  } catch {
    toast.error('复制失败，请手动选择路径')
  }
}
</script>

<template>
  <div class="page-wrap-slim px-4 py-6 sm:px-8 sm:py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-600 to-kiwi-600 text-white shadow-glow"
        >
          <KiwiIcon name="monitor" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">桌面</h1>
          <p class="mt-1 text-sm text-slate-500">
            本地运行状态、数据位置与离线安全开关。默认不发起任何外部网络请求。
          </p>
        </div>
      </div>
      <span
        class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium"
        :class="
          desktop.onlineModelsAllowed
            ? 'border-amber-200 bg-amber-50 text-amber-700'
            : 'border-emerald-200 bg-emerald-50 text-emerald-700'
        "
      >
        <KiwiIcon :name="desktop.onlineModelsAllowed ? 'globe' : 'shield'" :size="12" />
        {{ desktop.onlineModelsAllowed ? '外部模型接口已允许' : '离线模式' }}
      </span>
    </div>

    <SettingsTabs />

    <div
      v-if="desktop.loading && !desktop.ready"
      class="py-16 text-center text-sm text-slate-400"
    >
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取桌面状态…
    </div>

    <div
      v-else-if="desktop.error && !desktop.status"
      class="rounded-2xl border border-rose-100 bg-rose-50/60 p-4 text-sm text-rose-600"
    >
      {{ desktop.error }}
      <button class="ml-2 underline" @click="desktop.load(true)">重试</button>
    </div>

    <div v-else class="space-y-4">
      <!-- 运行状态 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4">
        <div class="flex items-center gap-2.5">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-kiwi-50 text-kiwi-500">
            <KiwiIcon name="server" :size="16" />
          </span>
          <div>
            <h2 class="text-[14px] font-semibold text-slate-800">运行状态</h2>
            <p class="mt-0.5 text-[11px] text-slate-500">
              数据库、向量与模型均运行在本机；版本信息来自当前安装包。
            </p>
          </div>
          <span
            v-if="desktop.version"
            class="ml-auto rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500"
          >
            v{{ desktop.version }}
          </span>
        </div>

        <div class="mt-3 grid gap-1.5 sm:grid-cols-3">
          <div class="rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2">
            <p class="text-[10.5px] text-slate-400">大模型</p>
            <p class="mt-0.5 text-[12.5px] font-medium text-slate-700">{{ llmState }}</p>
          </div>
          <div class="rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2">
            <p class="text-[10.5px] text-slate-400">向量检索</p>
            <p class="mt-0.5 text-[12.5px] font-medium text-slate-700">
              {{ embeddingState }}
            </p>
          </div>
          <div class="rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2">
            <p class="text-[10.5px] text-slate-400">笔记检索</p>
            <p class="mt-0.5 text-[12.5px] font-medium text-slate-700">PostgreSQL（可用）</p>
          </div>
        </div>

        <div
          v-if="desktop.ready && !desktop.llmConfigured"
          class="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-kiwi-100 bg-kiwi-50/60 px-3 py-2 text-[11.5px] text-kiwi-700"
        >
          <KiwiIcon name="sparkle" :size="13" />
          尚未配置大模型。桌面版不内置模型，可连接本机 Ollama / LM Studio，或显式允许外部接口。
          <button class="ml-auto underline" @click="router.push('/settings/models')">
            去配置模型
          </button>
        </div>
      </section>

      <!-- 数据位置 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4">
        <div class="flex items-center gap-2.5">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-slate-100 text-slate-500">
            <KiwiIcon name="folder" :size="16" />
          </span>
          <div>
            <h2 class="text-[14px] font-semibold text-slate-800">数据位置</h2>
            <p class="mt-0.5 text-[11px] text-slate-500">
              卸载应用不会删除这些目录；备份时请连同数据目录一起保存。
            </p>
          </div>
        </div>

        <div class="mt-3 space-y-1.5">
          <div
            class="flex items-center gap-2 rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2"
          >
            <span class="w-16 shrink-0 text-[10.5px] text-slate-400">数据目录</span>
            <code class="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-600">
              {{ desktop.dataDir || '—' }}
            </code>
            <button
              type="button"
              class="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-kiwi-600 disabled:opacity-40"
              :disabled="!desktop.dataDir"
              title="复制数据目录"
              @click="copyPath(desktop.dataDir, '数据目录')"
            >
              <KiwiIcon name="copy" :size="13" />
            </button>
          </div>
          <div
            class="flex items-center gap-2 rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2"
          >
            <span class="w-16 shrink-0 text-[10.5px] text-slate-400">日志目录</span>
            <code class="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-600">
              {{ desktop.logDir || '—' }}
            </code>
            <button
              type="button"
              class="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-kiwi-600 disabled:opacity-40"
              :disabled="!desktop.logDir"
              title="复制日志目录"
              @click="copyPath(desktop.logDir, '日志目录')"
            >
              <KiwiIcon name="copy" :size="13" />
            </button>
          </div>
        </div>
      </section>

      <!-- 外部模型接口 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4">
        <div class="flex items-start gap-2.5">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-kiwi-50 text-kiwi-500">
            <KiwiIcon name="cloud" :size="16" />
          </span>
          <div class="min-w-0 flex-1">
            <h2 class="text-[14px] font-semibold text-slate-800">外部模型接口</h2>
            <p class="mt-0.5 text-[11px] leading-relaxed text-slate-500">
              默认只允许 <code class="rounded bg-slate-100 px-1">127.0.0.1</code> /
              <code class="rounded bg-slate-100 px-1">localhost</code> 的本机模型。
              开启后才可以保存、测试并调用外部 OpenAI 兼容接口。
            </p>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="desktop.onlineModelsAllowed"
            :disabled="busy"
            class="relative mt-1 h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-70"
            :class="desktop.onlineModelsAllowed ? 'bg-amber-500' : 'bg-slate-300'"
            :title="desktop.onlineModelsAllowed ? '关闭外部模型接口' : '允许外部模型接口'"
            @click="toggleOnlineModels"
          >
            <span
              class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
              :class="desktop.onlineModelsAllowed ? 'left-[18px]' : 'left-0.5'"
            />
          </button>
        </div>

        <div
          class="mt-3 rounded-xl border px-3 py-2 text-[11px] leading-relaxed"
          :class="
            desktop.onlineModelsAllowed
              ? 'border-amber-200 bg-amber-50/70 text-amber-800'
              : 'border-emerald-100 bg-emerald-50/60 text-emerald-700'
          "
        >
          <template v-if="desktop.onlineModelsAllowed">
            已允许外部接口。配置非本机地址后，笔记正文、选中文本与问题会发送到该服务；
            请只填写你信任、并了解其数据策略的接口。
          </template>
          <template v-else>
            外部请求默认被本机网络防护拦截。本机模型（Ollama / LM Studio）无需开启此开关。
          </template>
        </div>

        <div class="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          <div
            v-for="feature in OFFLINE_FEATURES"
            :key="feature.key"
            class="flex items-center gap-2.5 rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2"
          >
            <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-400">
              <KiwiIcon name="shield" :size="13" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-[12px] font-medium text-slate-700">{{ feature.label }}</p>
              <p class="truncate text-[10.5px] text-slate-400">{{ feature.hint }}</p>
            </div>
            <span
              class="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
            >
              桌面禁用
            </span>
          </div>
        </div>
      </section>

      <!-- 本机代码执行 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4">
        <div class="flex items-start gap-2.5">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-kiwi-50 text-kiwi-500">
            <KiwiIcon name="terminal" :size="16" />
          </span>
          <div class="min-w-0 flex-1">
            <h2 class="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-slate-800">
              本机代码执行
              <span
                v-if="desktop.localCodeEnabled"
                class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-normal text-amber-700"
              >
                本机执行（非隔离）
              </span>
            </h2>
            <p class="mt-0.5 text-[11px] leading-relaxed text-slate-500">
              代码块与 Notebook 的后端运行时。默认关闭；开启后代码以当前用户身份在本机运行，
              <strong class="font-medium text-slate-600">没有文件系统隔离</strong>，只应运行可信代码。
            </p>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="desktop.localCodeEnabled"
            :disabled="busy || (!desktop.localCodeAvailable && !desktop.localCodeEnabled)"
            class="relative mt-1 h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            :class="desktop.localCodeEnabled ? 'bg-amber-500' : 'bg-slate-300'"
            :title="
              desktop.localCodeAvailable
                ? desktop.localCodeEnabled
                  ? '关闭本机代码执行'
                  : '开启本机代码执行'
                : '未找到便携 Python，无法开启'
            "
            @click="toggleLocalCode"
          >
            <span
              class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
              :class="desktop.localCodeEnabled ? 'left-[18px]' : 'left-0.5'"
            />
          </button>
        </div>

        <div class="mt-3 grid gap-1.5 sm:grid-cols-2">
          <div class="rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2">
            <p class="text-[10.5px] text-slate-400">运行时</p>
            <p class="mt-0.5 text-[12px] font-medium text-slate-700">
              {{ desktop.localCodeAvailable ? '便携 Python 已就绪' : '未找到便携 Python' }}
            </p>
            <p class="mt-0.5 font-mono text-[10px] text-slate-400">
              {{ desktop.localCodeImplementation || '—' }}
            </p>
          </div>
          <div class="rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2">
            <label for="desktop-code-timeout" class="text-[10.5px] text-slate-400">
              单次运行超时
            </label>
            <div class="mt-1 flex items-center gap-2">
              <select
                id="desktop-code-timeout"
                v-model.number="timeoutDraft"
                class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[12px] text-slate-700"
                :disabled="busy || !desktop.localCodeEnabled"
                @change="saveTimeout"
              >
                <option :value="30">30 秒</option>
                <option :value="60">60 秒</option>
                <option :value="120">120 秒</option>
                <option :value="300">300 秒</option>
                <option :value="600">600 秒</option>
              </select>
              <span class="text-[10.5px] text-slate-400">超时后终止整棵进程树</span>
            </div>
          </div>
        </div>

        <div
          class="mt-3 rounded-xl border border-rose-100 bg-rose-50/60 px-3 py-2 text-[11px] leading-relaxed text-rose-600"
        >
          Job Object 只限制资源与进程树，不阻止读取你的个人文件，也不是网络沙箱。
          不要在代码中处理来源不明的脚本。
        </div>
      </section>

      <p class="px-1 pb-2 text-[10.5px] leading-relaxed text-slate-400">
        桌面版不内置大模型、向量模型、Whisper 或 OCR 模型，也不会自动下载。
        WebView2 运行时由 Microsoft Edge Update 维护，属于系统组件流量，不属于 Kiwi 数据请求。
      </p>
    </div>

    <KiwiConfirm
      v-model="confirmOnline"
      title="允许连接外部模型接口？"
      message="开启后，配置的非本机模型地址会收到笔记正文、选中文本和你的问题。请确认你信任该服务并了解其数据策略。"
      confirm-text="了解风险并开启"
      danger
      @confirm="confirmOnlineModels"
    />
    <KiwiConfirm
      v-model="confirmLocal"
      title="开启本机代码执行？"
      message="本机执行没有文件系统隔离，代码可以读取当前用户可访问的文件。请只运行你信任的代码。"
      confirm-text="了解风险并开启"
      danger
      @confirm="confirmLocalCode"
    />
  </div>
</template>
