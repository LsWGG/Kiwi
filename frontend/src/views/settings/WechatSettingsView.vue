<script setup lang="ts">
/**
 * ClawBot 设置：扫码登录、知识库绑定与定时推送。
 *
 * ClawBot 是单联系人渠道，不需要维护联系人 ID；知识库支持多选。
 * 定时计划支持系统时间选择器、5 段 cron 与自然语言转 cron（由后端大模型解析）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiMultiSelect from '@/components/ui/KiwiMultiSelect.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
import KiwiTimePicker from '@/components/ui/KiwiTimePicker.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'
import { copyTextToClipboard } from '@/utils/clipboard'
import qrcode from 'qrcode-generator'
import { useKbsStore } from '@/stores/kbs'
import {
  createWeChatSchedule,
  deleteWeChatSchedule,
  getWeChatStatus,
  logoutWeChat,
  previewWeChatSchedule,
  sendWeChatTest,
  startWeChatLogin,
  toggleWeChatSchedule,
  updateWeChatSettings,
  type WeChatSchedule,
  type WeChatSchedulePreview,
  type WeChatStatus,
} from '@/api/wechat'

const kbs = useKbsStore()
const status = ref<WeChatStatus | null>(null)
const loading = ref(true)
const loginBusy = ref(false)
const testText = ref('')
const scheduleBusy = ref(false)
const previewBusy = ref(false)
const schedulePreview = ref<WeChatSchedulePreview | null>(null)

const form = reactive({
  enabled: false,
})

type ScheduleMode = 'common' | 'cron'
const scheduleForm = reactive({
  mode: 'common' as ScheduleMode,
  frequency: 'daily',
  time: '09:00',
  cron: '0 9 * * *',
  natural: '',
  prompt: '',
  kb_ids: [] as string[],
})

let pollTimer: number | undefined

const FREQUENCIES = [
  { value: 'daily', label: '每天' },
  { value: 'weekdays', label: '工作日（周一至周五）' },
  { value: 'weekly:1', label: '每周一' },
  { value: 'weekly:2', label: '每周二' },
  { value: 'weekly:3', label: '每周三' },
  { value: 'weekly:4', label: '每周四' },
  { value: 'weekly:5', label: '每周五' },
  { value: 'weekly:6', label: '每周六' },
  { value: 'weekly:0', label: '每周日' },
  { value: 'monthly:1', label: '每月 1 号' },
  { value: 'monthly:15', label: '每月 15 号' },
]

const connected = computed(() => !!status.value?.connected)
const login = computed(() => status.value?.login ?? { status: 'disconnected' })
const remainingLabel = computed(() => {
  const seconds = status.value?.remaining_seconds ?? 0
  if (!seconds) return ''
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`
})

const connectedStyle = computed(() =>
  connected.value
    ? {
        color: 'rgb(var(--theme-success, 34 197 94))',
        backgroundColor: 'rgb(var(--theme-success, 34 197 94) / 0.12)',
      }
    : {
        color: 'rgb(var(--theme-text-secondary, 100 116 139))',
        backgroundColor: 'rgb(var(--theme-surface-strong, 226 232 240) / 0.45)',
      },
)
const warningBoxStyle = {
  borderColor: 'rgb(var(--theme-warning, 245 158 11) / 0.32)',
  backgroundColor: 'rgb(var(--theme-warning, 245 158 11) / 0.08)',
}
const warningTextStyle = { color: 'rgb(var(--theme-warning, 245 158 11))' }

const kbOptions = computed(() =>
  kbs.kbs.map((kb) => ({ value: kb.id, label: kb.name })),
)

const qrRaw = computed(() => String(login.value.qr || '').trim())
const qrDirect = computed(() => {
  const raw = qrRaw.value
  if (!raw) return ''
  if (raw.startsWith('data:image/')) return raw
  if (raw.startsWith('<svg')) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(raw)}`
  }
  if (!raw.startsWith('http')) return `data:image/png;base64,${raw}`
  return ''
})
const qrLink = computed(() => (qrRaw.value.startsWith('http') ? qrRaw.value : ''))
const generatedQr = ref('')
watch(
  qrRaw,
  (raw) => {
    generatedQr.value = ''
    if (!raw.startsWith('http')) return
    try {
      const code = qrcode(0, 'M')
      code.addData(raw)
      code.make()
      generatedQr.value = code.createDataURL(6, 2)
    } catch {
      generatedQr.value = ''
    }
  },
  { immediate: true },
)
const qrSrc = computed(() => qrDirect.value || generatedQr.value)

const frequencyOptions = FREQUENCIES.map((item) => ({
  value: item.value,
  label: item.label,
}))
const frequencyLabel = computed(
  () => FREQUENCIES.find((item) => item.value === scheduleForm.frequency)?.label || '每天',
)

const commonCron = computed(() => {
  const [hourText, minuteText] = scheduleForm.time.split(':')
  const hour = Math.min(23, Math.max(0, Number(hourText) || 0))
  const minute = Math.min(59, Math.max(0, Number(minuteText) || 0))
  const base = `${minute} ${hour}`
  const value = scheduleForm.frequency
  if (value === 'weekdays') return `${base} * * 1-5`
  if (value.startsWith('weekly:')) {
    return `${base} * * ${value.slice('weekly:'.length)}`
  }
  if (value.startsWith('monthly:')) {
    return `${base} ${value.slice('monthly:'.length)} * *`
  }
  return `${base} * * *`
})
const commonDescription = computed(() => `${frequencyLabel.value} ${scheduleForm.time}`)
const activeCron = computed(() =>
  scheduleForm.mode === 'common' ? commonCron.value : scheduleForm.cron.trim(),
)

function kbNames(ids: string[]) {
  return ids
    .map((id) => kbs.kbs.find((kb) => kb.id === id)?.name || id.slice(0, 8))
    .join('、')
}

function formatNextRun(value: string) {
  return value.replace('T', ' ').slice(0, 16)
}

async function copyLoginLink() {
  if (!qrLink.value) return
  const ok = await copyTextToClipboard(qrLink.value)
  if (ok) toast.success('登录链接已复制')
  else toast.error('复制失败，请手动选择链接')
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    await refresh(true)
    const value = login.value.status
    if (value === 'connected') {
      stopPolling()
      toast.success('ClawBot 连接成功')
    } else if (value === 'expired' || value === 'error') {
      stopPolling()
      toast.error(login.value.message || '二维码已失效，请重新获取')
    }
  }, 2000)
}

async function refresh(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await getWeChatStatus()
    status.value = data
    form.enabled = data.enabled
    if (data.login.status === 'pending') startPolling()
  } catch (e: any) {
    if (!silent) toast.error(e.message || '读取 ClawBot 状态失败')
  } finally {
    loading.value = false
  }
}

async function startLogin() {
  if (loginBusy.value) return
  loginBusy.value = true
  try {
    const result = await startWeChatLogin()
    await refresh(true)
    if (result.login.status === 'pending') startPolling()
  } catch (e: any) {
    toast.error(e.message || '获取二维码失败')
  } finally {
    loginBusy.value = false
  }
}

async function disconnect() {
  if (!window.confirm('断开 ClawBot 连接？断开后需要重新扫码才能继续使用。')) return
  try {
    status.value = await logoutWeChat()
    stopPolling()
    toast.success('已断开 ClawBot 连接')
  } catch (e: any) {
    toast.error(e.message || '断开失败')
  }
}

async function toggleEnabled() {
  try {
    status.value = await updateWeChatSettings({ enabled: !form.enabled })
    form.enabled = status.value.enabled
    if (form.enabled && !status.value.connected) {
      toast.info('已启用，请扫码登录')
    }
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  }
}

async function parseNatural() {
  if (previewBusy.value) return
  const text = scheduleForm.natural.trim() || scheduleForm.cron.trim()
  if (!text) {
    toast.info('请输入计划，例如「每天早上九点」')
    return
  }
  previewBusy.value = true
  try {
    const result = await previewWeChatSchedule(text)
    schedulePreview.value = result
    scheduleForm.cron = result.cron
    toast.success(`已解析：${result.description}`)
  } catch (e: any) {
    toast.error(e.message || '解析计划失败')
  } finally {
    previewBusy.value = false
  }
}

async function addSchedule() {
  const prompt = scheduleForm.prompt.trim()
  if (!prompt) {
    toast.info('请填写推送内容')
    return
  }
  let cron = activeCron.value
  if (!cron && scheduleForm.natural.trim()) {
    await parseNatural()
    cron = scheduleForm.cron.trim()
  }
  if (!cron) {
    toast.info('请设置执行计划（常用时间或 cron）')
    return
  }
  scheduleBusy.value = true
  try {
    await createWeChatSchedule({
      cron,
      prompt,
      kb_ids: scheduleForm.kb_ids,
    })
    scheduleForm.prompt = ''
    await refresh(true)
    toast.success('定时推送已创建')
  } catch (e: any) {
    toast.error(e.message || '创建定时推送失败')
  } finally {
    scheduleBusy.value = false
  }
}

async function toggleSchedule(item: WeChatSchedule) {
  try {
    await toggleWeChatSchedule(item.id, !item.enabled)
    item.enabled = !item.enabled
  } catch (e: any) {
    toast.error(e.message || '更新失败')
  }
}

async function removeSchedule(item: WeChatSchedule) {
  if (!window.confirm(`删除「${item.description || item.cron}」的定时推送？`)) return
  try {
    await deleteWeChatSchedule(item.id)
    await refresh(true)
    toast.success('已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

async function sendTest() {
  const text = testText.value.trim()
  if (!text) return
  try {
    const result = await sendWeChatTest(text)
    testText.value = ''
    if (result.ok) toast.success('测试消息已发送')
    else toast.info('当前离线/窗口过期，消息已排队，下次互动时补发')
  } catch (e: any) {
    toast.error(e.message || '发送失败')
  }
}

onMounted(async () => {
  if (!kbs.kbs.length) {
    await kbs.fetchKbs().catch(() => undefined)
  }
  await refresh()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page-wrap-slim px-3 py-4 sm:px-8 sm:py-8">
    <SettingsTabs />

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="mx-auto mb-2" />
      正在读取 ClawBot 状态…
    </div>

    <div v-else class="space-y-4">
      <section
        v-if="!status?.system_enabled"
        class="rounded-2xl border p-4 text-[12px] leading-relaxed"
        :style="warningBoxStyle"
      >
        <p class="flex items-center gap-2 font-medium" :style="warningTextStyle">
          <KiwiIcon name="alert" :size="14" />
          服务端尚未启用 ClawBot 渠道
        </p>
        <p class="mt-1" :style="warningTextStyle">
          请在 <code class="rounded bg-white/50 px-1">.env</code> 设置
          <code class="rounded bg-white/50 px-1">KIWI_WECHAT_ENABLED=true</code>
          并重启后端，然后回到本页扫码登录。
        </p>
      </section>

      <!-- 页面头部 / 连接状态 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex min-w-0 items-start gap-3">
            <span class="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-600">
              <KiwiIcon name="chat" :size="20" />
            </span>
            <div class="min-w-0">
              <p class="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-400">
                消息渠道
              </p>
              <h1 class="mt-0.5 text-[17px] font-semibold text-slate-800">ClawBot</h1>
              <p class="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-slate-500">
                在手机上直接向 Kiwi 提问，或让系统定时推送待办、周报；写操作会在对话里二次确认。
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                <span
                  class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium"
                  :style="connectedStyle"
                >
                  <span
                    class="h-1.5 w-1.5 rounded-full"
                    :style="{
                      backgroundColor: connected
                        ? 'rgb(var(--theme-success, 34 197 94))'
                        : 'rgb(var(--theme-text-subtle, 148 163 184))',
                    }"
                  />
                  {{ connected ? '已连接' : '未连接' }}
                </span>
                <span v-if="connected && remainingLabel" class="text-slate-400">
                  剩余 {{ remainingLabel }}
                </span>
              </div>
              <p class="mt-1 text-[10.5px] leading-relaxed text-slate-400">
                默认全库可读可写；发送 <code class="rounded bg-white/50 px-1">/kb 名称</code>
                或在对话里说「切换到 XXX 知识库」即可切换。
              </p>
            </div>
          </div>

          <div class="flex w-full flex-col items-end gap-2.5 sm:w-auto">
            <div class="flex items-center gap-2">
              <span class="text-[10.5px] text-slate-400">
                {{ form.enabled ? '已启用' : '已停用' }}
              </span>
              <button
                type="button"
                role="switch"
                :aria-checked="form.enabled"
                :disabled="!status?.system_enabled"
                class="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                :class="form.enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
                :title="form.enabled ? '停用 ClawBot 渠道' : '启用 ClawBot 渠道'"
                @click="toggleEnabled"
              >
                <span
                  class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
                  :class="form.enabled ? 'left-[18px]' : 'left-0.5'"
                />
              </button>
            </div>
            <div class="flex flex-wrap items-center justify-end gap-2">
              <button
                v-if="!connected"
                type="button"
                class="kiwi-btn-primary"
                :disabled="loginBusy || !status?.system_enabled"
                @click="startLogin"
              >
                <KiwiIcon
                  :name="loginBusy ? 'loader' : 'refresh'"
                  :size="13"
                  :spin="loginBusy"
                />
                扫码登录
              </button>
              <button
                v-else
                type="button"
                class="kiwi-btn-secondary"
                :disabled="loginBusy"
                @click="startLogin"
              >
                <KiwiIcon
                  :name="loginBusy ? 'loader' : 'refresh'"
                  :size="13"
                  :spin="loginBusy"
                />
                重新扫码
              </button>
              <button
                v-if="connected"
                type="button"
                class="kiwi-btn-ghost !px-2 text-[11px] text-slate-400 hover:text-rose-500"
                @click="disconnect"
              >
                断开
              </button>
            </div>
          </div>
        </div>

        <div
          v-if="login.status === 'pending'"
          class="mt-4 flex flex-col gap-4 rounded-xl border border-slate-200/70 bg-white/55 p-4 sm:flex-row sm:items-center"
        >
          <div class="mx-auto shrink-0 rounded-xl border border-slate-200/70 bg-white p-2 shadow-sm sm:mx-0">
            <img
              v-if="qrSrc"
              :src="qrSrc"
              alt="扫码登录二维码"
              class="h-40 w-40 rounded-lg"
            />
            <div v-else class="grid h-40 w-40 place-items-center text-[11px] text-slate-400">
              二维码加载中…
            </div>
          </div>
          <div class="min-w-0 text-[11.5px] leading-relaxed text-slate-600">
            <p class="text-[12.5px] font-medium text-slate-700">用手机扫码并确认</p>
            <p class="mt-1 text-slate-400">
              扫码后本页会自动更新；二维码约 10 分钟内有效。
            </p>
            <div v-if="qrLink" class="mt-2 flex flex-wrap gap-2">
              <a
                :href="qrLink"
                target="_blank"
                rel="noopener noreferrer"
                class="rounded-md bg-white/80 px-2 py-1 text-kiwi-700 shadow-sm hover:bg-white"
              >
                在手机中打开登录链接
              </a>
              <button
                type="button"
                class="rounded-md bg-white/80 px-2 py-1 text-slate-500 shadow-sm hover:bg-white"
                @click="copyLoginLink"
              >
                复制链接
              </button>
            </div>
            <p v-else class="mt-2 text-[11px] text-slate-400">
              如果二维码没有显示，请刷新页面重新获取。
            </p>
          </div>
        </div>
        <p
          v-else-if="login.status !== 'connected' && login.message"
          class="mt-3 rounded-lg border border-slate-200/70 bg-white/50 px-3 py-2 text-[11px] text-slate-500"
        >
          {{ login.message }}
        </p>
      </section>

      <!-- 定时主动推送 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4 sm:p-5">
        <div class="flex items-start gap-3">
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="clock" :size="16" />
          </span>
          <div class="min-w-0">
            <h2 class="text-[14px] font-semibold text-slate-800">定时主动推送</h2>
            <p class="mt-0.5 text-[11px] leading-relaxed text-slate-500">
              支持每天 / 工作日 / 每周 / 每月，或直接写 cron 与自然语言计划。官方 24 小时会话窗口过期时，内容会排队到下次互动补发。
            </p>
          </div>
        </div>

        <div class="mt-4 rounded-xl border border-slate-200/70 bg-white/50 p-3">
          <div class="inline-flex rounded-xl bg-slate-100/80 p-1">
            <button
              type="button"
              class="rounded-lg px-3 py-1 text-[11.5px] font-medium transition-colors"
              :class="scheduleForm.mode === 'common' ? 'bg-white text-kiwi-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
              @click="scheduleForm.mode = 'common'"
            >
              常用
            </button>
            <button
              type="button"
              class="rounded-lg px-3 py-1 text-[11.5px] font-medium transition-colors"
              :class="scheduleForm.mode === 'cron' ? 'bg-white text-kiwi-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
              @click="scheduleForm.mode = 'cron'"
            >
              Cron / 自然语言
            </button>
          </div>

          <div v-if="scheduleForm.mode === 'common'" class="mt-3 grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_150px_auto]">
            <label class="block">
              <span class="mb-1 block text-[10.5px] font-medium text-slate-500">频率</span>
              <KiwiSelect
                v-model="scheduleForm.frequency"
                :options="frequencyOptions"
                variant="input"
                width="w-full"
                aria-label="推送频率"
              />
            </label>
            <label class="block">
              <span class="mb-1 block text-[10.5px] font-medium text-slate-500">时间</span>
              <KiwiTimePicker
                v-model="scheduleForm.time"
                aria-label="推送时间"
              />
            </label>
            <div class="rounded-lg bg-slate-50/80 px-3 py-1.5 text-[11px] text-slate-500">
              <div>
                <span class="text-slate-400">计划：</span>
                <span class="font-medium text-slate-600">{{ commonDescription }}</span>
              </div>
              <div class="font-mono text-[10px] text-slate-400">{{ commonCron }}</div>
            </div>
          </div>

          <div v-else class="mt-3 space-y-3">
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="block">
                <span class="mb-1 block text-[10.5px] font-medium text-slate-500">Cron 表达式</span>
                <input
                  v-model="scheduleForm.cron"
                  class="kiwi-input h-9 font-mono text-[12px]"
                  placeholder="0 9 * * *"
                  aria-label="Cron 表达式"
                  @input="schedulePreview = null"
                />
              </label>
              <label class="block">
                <span class="mb-1 block text-[10.5px] font-medium text-slate-500">自然语言转 Cron</span>
                <div class="flex gap-2">
                  <input
                    v-model="scheduleForm.natural"
                    class="kiwi-input h-9 flex-1"
                    placeholder="例如：每天早上九点"
                    aria-label="自然语言计划"
                    @keydown.enter.prevent="parseNatural"
                    @input="schedulePreview = null"
                  />
                  <button
                    type="button"
                    class="kiwi-btn-secondary shrink-0"
                    :disabled="previewBusy"
                    @click="parseNatural"
                  >
                    <KiwiIcon :name="previewBusy ? 'loader' : 'sparkle'" :size="13" :spin="previewBusy" />
                    解析
                  </button>
                </div>
              </label>
            </div>
            <div
              v-if="schedulePreview"
              class="rounded-lg border border-kiwi-100 bg-kiwi-50/50 px-3 py-2 text-[11px] text-slate-600"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-kiwi-700">{{ schedulePreview.description }}</span>
                <span class="font-mono text-[10px] text-slate-400">{{ schedulePreview.cron }}</span>
              </div>
              <p v-if="schedulePreview.next_runs.length" class="mt-1 text-[10px] text-slate-400">
                最近运行：{{ schedulePreview.next_runs.map(formatNextRun).join(' · ') }}
              </p>
            </div>
            <p v-else class="text-[10.5px] text-slate-400">
              可直接填写 5 段 cron，或输入自然语言后点「解析」；解析优先使用已配置的大模型。
            </p>
          </div>

          <div class="mt-3">
            <span class="mb-1 block text-[10.5px] font-medium text-slate-500">知识库（可多选）</span>
            <KiwiMultiSelect
              v-model="scheduleForm.kb_ids"
              :options="kbOptions"
              aria-label="推送知识库"
              placeholder="使用全部知识库（可多选）"
              width="w-full"
            />
          </div>

          <div class="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              v-model="scheduleForm.prompt"
              class="kiwi-input h-9 flex-1"
              placeholder="推送内容，例如：总结今天的待办，按优先级列出"
              aria-label="推送内容"
            />
            <button
              type="button"
              class="kiwi-btn-primary shrink-0"
              :disabled="scheduleBusy || !scheduleForm.prompt.trim()"
              @click="addSchedule"
            >
              <KiwiIcon :name="scheduleBusy ? 'loader' : 'plus'" :size="13" :spin="scheduleBusy" />
              添加
            </button>
          </div>
        </div>

        <div v-if="status?.schedules?.length" class="mt-3 space-y-1.5">
          <div
            v-for="item in status.schedules"
            :key="item.id"
            class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/70 bg-white/50 px-3 py-2 transition-colors hover:bg-white/75"
          >
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
              <KiwiIcon name="clock" :size="13" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="text-[11px] font-medium text-kiwi-700">
                  {{ item.description || item.cron }}
                </span>
                <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                  {{ kbNames(item.kb_ids || []) || '全部知识库' }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-[12px] text-slate-600" :title="item.prompt">
                {{ item.prompt }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <button
                type="button"
                role="switch"
                :aria-checked="item.enabled"
                class="relative h-4 w-7 shrink-0 rounded-full transition-colors"
                :class="item.enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
                @click="toggleSchedule(item)"
              >
                <span
                  class="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all"
                  :class="item.enabled ? 'left-[14px]' : 'left-0.5'"
                />
              </button>
              <button
                type="button"
                class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-white hover:text-rose-500"
                title="删除定时推送"
                @click="removeSchedule(item)"
              >
                <KiwiIcon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </div>
        <div
          v-else
          class="mt-3 rounded-xl border border-dashed border-slate-200/80 bg-white/40 px-4 py-8 text-center"
        >
          <div class="mx-auto mb-2 grid h-10 w-10 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-500">
            <KiwiIcon name="clock" :size="18" />
          </div>
          <p class="text-[12px] font-medium text-slate-600">还没有定时推送</p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">
            设置一个计划，Kiwi 会按时把结果发给你。
          </p>
        </div>
      </section>

      <!-- 测试消息 -->
      <section class="animate-fade-up rounded-2xl glass-strong p-4 sm:p-5">
        <div class="flex items-start gap-3">
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="send" :size="16" />
          </span>
          <div class="min-w-0">
            <h2 class="text-[14px] font-semibold text-slate-800">发送测试消息</h2>
            <p class="mt-0.5 text-[11px] leading-relaxed text-slate-500">
              发到最近一次互动的对话；如果窗口已过期，会排队到下次互动。
            </p>
          </div>
        </div>
        <div class="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            v-model="testText"
            class="kiwi-input h-9 flex-1"
            placeholder="测试消息内容"
            @keydown.enter.prevent="sendTest"
          />
          <button
            type="button"
            class="kiwi-btn-secondary shrink-0"
            :disabled="!testText.trim()"
            @click="sendTest"
          >
            <KiwiIcon name="send" :size="13" />
            发送
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
