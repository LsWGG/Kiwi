<script setup lang="ts">
/**
 * ClawBot 设置：扫码登录、允许联系人、知识库绑定与定时推送。
 *
 * 登录二维码直接显示在页面里；未登录时轮询 /api/wechat/status 直到扫码完成。
 * 主动推送受官方 24 小时 context_token 窗口限制，过期内容会在下一次互动时补发。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
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
  sendWeChatTest,
  startWeChatLogin,
  toggleWeChatSchedule,
  updateWeChatSettings,
  type WeChatSchedule,
  type WeChatStatus,
} from '@/api/wechat'

const kbs = useKbsStore()
const status = ref<WeChatStatus | null>(null)
const loading = ref(true)
const loginBusy = ref(false)
const saving = ref(false)
const newUser = ref('')
const testText = ref('')
const scheduleBusy = ref(false)

const form = reactive({
  enabled: false,
  default_kb_id: '',
  allow_write: false,
  allowed_users: [] as string[],
})

const scheduleForm = reactive({
  time: '09:00',
  prompt: '',
  kb_id: '',
  sender: '',
})

let pollTimer: number | undefined

const connected = computed(() => !!status.value?.connected)
const login = computed(() => status.value?.login ?? { status: 'disconnected' })
const remainingLabel = computed(() => {
  const seconds = status.value?.remaining_seconds ?? 0
  if (!seconds) return ''
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`
})

const kbOptions = computed(() =>
  kbs.kbs.map((kb) => ({ value: kb.id, label: kb.name })),
)
const senderOptions = computed(() =>
  (status.value?.allowed_users ?? []).map((item) => ({ value: item, label: item })),
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
    form.default_kb_id = data.default_kb_id || ''
    form.allow_write = data.allow_write
    form.allowed_users = [...data.allowed_users]
    if (!scheduleForm.kb_id) scheduleForm.kb_id = data.default_kb_id || ''
    if (!scheduleForm.sender) {
      scheduleForm.sender =
        data.last_contact?.sender || data.allowed_users[0] || ''
    }
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

async function saveSettings() {
  if (saving.value) return
  saving.value = true
  try {
    status.value = await updateWeChatSettings({
      default_kb_id: form.default_kb_id || null,
      allow_write: form.allow_write,
      allowed_users: form.allowed_users,
    })
    scheduleForm.kb_id = scheduleForm.kb_id || status.value.default_kb_id
    toast.success('ClawBot 设置已保存')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function addUser(sender?: string) {
  const value = (sender ?? newUser.value).trim()
  if (!value) return
  if (!form.allowed_users.includes(value)) {
    form.allowed_users.push(value)
  }
  if (!sender) newUser.value = ''
}

function removeUser(sender: string) {
  form.allowed_users = form.allowed_users.filter((item) => item !== sender)
}

async function approveUser(sender: string) {
  addUser(sender)
  await saveSettings()
}

async function addSchedule() {
  if (!scheduleForm.time || !scheduleForm.prompt.trim()) {
    toast.info('请填写推送时间和推送内容')
    return
  }
  if (!scheduleForm.sender) {
    toast.info('请选择联系人；先让用户给 Bot 发一条消息')
    return
  }
  scheduleBusy.value = true
  try {
    await createWeChatSchedule({
      time: scheduleForm.time,
      prompt: scheduleForm.prompt.trim(),
      kb_id: scheduleForm.kb_id || status.value?.default_kb_id || undefined,
      sender: scheduleForm.sender,
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
  if (!window.confirm(`删除每天 ${item.time} 的定时推送？`)) return
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
    toast[result.ok ? 'success' : 'info'](
      result.ok ? '测试消息已发送' : '当前离线/窗口过期，消息已排队，下次互动时补发',
    )
  } catch (e: any) {
    toast.error(e.message || '发送失败')
  }
}

function kbName(id: string) {
  return kbs.kbs.find((kb) => kb.id === id)?.name || id.slice(0, 8)
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
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div>
        <h1 class="flex items-center gap-2 text-[19px] font-semibold text-slate-800">
          <KiwiIcon name="chat" :size="18" class="text-kiwi-500" />
          ClawBot
        </h1>
        <p class="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-slate-500">
          在手机上直接向 Kiwi 提问，或让系统定时推送待办、周报；写操作会在对话里二次确认。
        </p>
      </div>
    </div>

    <SettingsTabs />

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="mx-auto mb-2" />
      正在读取 ClawBot 状态…
    </div>

    <div v-else class="space-y-5">
      <section
        v-if="!status?.system_enabled"
        class="rounded-2xl border border-amber-200/80 bg-amber-50/70 p-4 text-[12px] leading-relaxed text-amber-800"
      >
        服务端尚未启用 ClawBot 渠道：请在 <code class="rounded bg-amber-100 px-1">.env</code>
        设置 <code class="rounded bg-amber-100 px-1">KIWI_WECHAT_ENABLED=true</code>
        并重启后端，然后回到本页扫码登录。
      </section>

      <section class="animate-fade-up rounded-2xl glass-strong p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex min-w-0 items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-600">
              <KiwiIcon name="chat" :size="18" />
            </span>
            <div class="min-w-0">
              <h2 class="text-[14px] font-semibold text-slate-800">连接状态</h2>
              <p class="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
                扫码登录后，Bot 会持续接收消息；登录有效期约 24 小时，到期前会提醒续连。
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"
                  :class="
                    connected
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-slate-100 text-slate-500'
                  "
                >
                  <span
                    class="h-1.5 w-1.5 rounded-full"
                    :class="connected ? 'bg-emerald-500' : 'bg-slate-400'"
                  />
                  {{ connected ? '已连接' : '未连接' }}
                </span>
                <span v-if="connected && remainingLabel" class="text-slate-400">
                  剩余 {{ remainingLabel }}
                </span>
                <span v-if="status?.last_contact" class="text-slate-400">
                  最近联系：{{ status.last_contact.sender }}
                </span>
              </div>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
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
            <button
              v-if="!connected"
              type="button"
              class="kiwi-btn-primary"
              :disabled="loginBusy || !status?.system_enabled"
              @click="startLogin"
            >
              <KiwiIcon :name="loginBusy ? 'loader' : 'refresh'" :size="13" :spin="loginBusy" />
              扫码登录
            </button>
            <button
              v-else
              type="button"
              class="kiwi-btn-secondary"
              :disabled="loginBusy"
              @click="startLogin"
            >
              <KiwiIcon :name="loginBusy ? 'loader' : 'refresh'" :size="13" :spin="loginBusy" />
              重新扫码
            </button>
            <button v-if="connected" type="button" class="kiwi-btn-ghost" @click="disconnect">
              断开
            </button>
          </div>
        </div>

        <div
          v-if="login.status === 'pending'"
          class="mt-4 flex flex-wrap items-center gap-4 rounded-xl border border-slate-200/70 bg-white/60 p-4"
        >
          <img
            v-if="qrSrc"
            :src="qrSrc"
            alt="扫码登录二维码"
            class="h-44 w-44 rounded-lg border border-slate-200/70 bg-white p-1"
          />
          <div class="min-w-0 text-[12px] leading-relaxed text-slate-600">
            <p class="font-medium text-slate-700">用手机扫码并确认</p>
            <p class="mt-1 text-slate-400">扫码后本页会自动更新；二维码约 10 分钟内有效。</p>
            <p v-if="qrLink" class="mt-2 flex flex-wrap gap-2 text-[11px]">
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
            </p>
            <p v-else class="mt-2 text-[11px] text-slate-400">
              如果二维码没有显示，请刷新页面重新获取。
            </p>
          </div>
        </div>
        <p
          v-else-if="login.message"
          class="mt-3 rounded-lg border border-slate-200/70 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500"
        >
          {{ login.message }}
        </p>
      </section>

      <section class="animate-fade-up rounded-2xl glass-strong p-5">
        <h2 class="text-[14px] font-semibold text-slate-800">问答权限</h2>
        <p class="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
          未授权的联系人无法使用知识库；写操作默认关闭，开启后也必须在对话里回复「确认」。
        </p>

        <div class="mt-4 grid gap-4 md:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[11.5px] font-medium text-slate-500">默认知识库</span>
            <KiwiSelect
              v-model="form.default_kb_id"
              :options="kbOptions"
              variant="input"
              width="w-full"
              aria-label="默认知识库"
              placeholder="选择知识库"
            />
          </label>
          <div class="flex items-center justify-between rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2">
            <div>
              <p class="text-[12px] font-medium text-slate-700">允许写操作</p>
              <p class="mt-0.5 text-[10.5px] text-slate-400">新建 / 修改 / 删除笔记前仍需在对话中确认</p>
            </div>
            <button
              type="button"
              role="switch"
              :aria-checked="form.allow_write"
              class="relative h-5 w-9 shrink-0 rounded-full transition-colors"
              :class="form.allow_write ? 'bg-kiwi-500' : 'bg-slate-300'"
              @click="form.allow_write = !form.allow_write"
            >
              <span
                class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
                :class="form.allow_write ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
          </div>
        </div>

        <div class="mt-4">
          <p class="text-[11.5px] font-medium text-slate-500">允许的联系人</p>
          <div class="mt-1.5 flex flex-wrap gap-1.5">
            <span
              v-for="user in form.allowed_users"
              :key="user"
              class="inline-flex items-center gap-1 rounded-full border border-slate-200/70 bg-white/70 px-2 py-0.5 font-mono text-[10.5px] text-slate-600"
            >
              {{ user }}
              <button type="button" class="text-slate-400 hover:text-rose-500" @click="removeUser(user)">
                <KiwiIcon name="close" :size="10" />
              </button>
            </span>
            <span v-if="!form.allowed_users.length" class="text-[11px] text-slate-400">
              还没有允许的联系人
            </span>
          </div>
          <div class="mt-2 flex gap-2">
            <input
              v-model="newUser"
              class="kiwi-input h-9 flex-1"
              placeholder="联系人 ID，例如 xxx@im.wechat"
              @keydown.enter.prevent="addUser()"
            />
            <button type="button" class="kiwi-btn-secondary" @click="addUser()">添加</button>
          </div>
        </div>

        <div v-if="status?.unknown_users?.length" class="mt-4 rounded-xl border border-amber-200/70 bg-amber-50/60 p-3">
          <p class="text-[11.5px] font-medium text-amber-800">待授权联系人</p>
          <div class="mt-2 space-y-1.5">
            <div
              v-for="item in status.unknown_users"
              :key="item.sender"
              class="flex flex-wrap items-center gap-2 text-[11px] text-amber-800"
            >
              <span class="font-mono">{{ item.sender }}</span>
              <button
                type="button"
                class="rounded-md bg-white/70 px-2 py-0.5 text-[10.5px] text-amber-700 hover:bg-white"
                @click="approveUser(item.sender)"
              >
                允许
              </button>
            </div>
          </div>
        </div>

        <div class="mt-4 flex justify-end">
          <button type="button" class="kiwi-btn-primary" :disabled="saving" @click="saveSettings">
            <KiwiIcon :name="saving ? 'loader' : 'check'" :size="13" :spin="saving" />
            保存设置
          </button>
        </div>
      </section>

      <section class="animate-fade-up rounded-2xl glass-strong p-5">
        <h2 class="text-[14px] font-semibold text-slate-800">定时主动推送</h2>
        <p class="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
          例如「每天早上 9 点总结 XXX 知识库的待办」。官方 24 小时会话窗口过期时，内容会排队到下次互动补发。
        </p>

        <div class="mt-4 grid gap-2.5 md:grid-cols-[120px_1fr_180px_220px_auto]">
          <input v-model="scheduleForm.time" type="time" class="kiwi-input h-9" aria-label="推送时间" />
          <input
            v-model="scheduleForm.prompt"
            class="kiwi-input h-9"
            placeholder="推送内容，例如：总结今天的待办，按优先级列出"
            aria-label="推送内容"
          />
          <KiwiSelect
            v-model="scheduleForm.kb_id"
            :options="kbOptions"
            variant="input"
            width="w-full"
            aria-label="推送知识库"
            placeholder="知识库"
          />
          <KiwiSelect
            v-if="senderOptions.length"
            v-model="scheduleForm.sender"
            :options="senderOptions"
            variant="input"
            width="w-full"
            aria-label="推送联系人"
            placeholder="联系人"
          />
          <input
            v-else
            v-model="scheduleForm.sender"
            class="kiwi-input h-9"
            placeholder="联系人 ID"
            aria-label="推送联系人"
          />
          <button
            type="button"
            class="kiwi-btn-primary"
            :disabled="scheduleBusy || !scheduleForm.prompt.trim()"
            @click="addSchedule"
          >
            <KiwiIcon :name="scheduleBusy ? 'loader' : 'plus'" :size="13" :spin="scheduleBusy" />
            添加
          </button>
        </div>

        <div v-if="status?.schedules?.length" class="mt-4 space-y-1.5">
          <div
            v-for="item in status.schedules"
            :key="item.id"
            class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2"
          >
            <span class="rounded-lg bg-kiwi-50 px-2 py-0.5 font-mono text-[11px] text-kiwi-700">
              {{ item.time }}
            </span>
            <span class="min-w-0 flex-1 truncate text-[12px] text-slate-600" :title="item.prompt">
              {{ item.prompt }}
            </span>
            <span class="text-[10.5px] text-slate-400">{{ kbName(item.kb_id) }}</span>
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
              class="text-slate-400 transition-colors hover:text-rose-500"
              title="删除定时推送"
              @click="removeSchedule(item)"
            >
              <KiwiIcon name="trash" :size="13" />
            </button>
          </div>
        </div>
        <p v-else class="mt-4 text-[11px] text-slate-400">还没有定时推送。</p>
      </section>

      <section class="animate-fade-up rounded-2xl glass-strong p-5">
        <h2 class="text-[14px] font-semibold text-slate-800">发送测试消息</h2>
        <p class="mt-0.5 text-[11.5px] text-slate-500">
          发到最近一次互动的联系人；如果窗口已过期，会排队到下次互动。
        </p>
        <div class="mt-3 flex gap-2">
          <input
            v-model="testText"
            class="kiwi-input h-9 flex-1"
            placeholder="测试消息内容"
            @keydown.enter.prevent="sendTest"
          />
          <button type="button" class="kiwi-btn-secondary" :disabled="!testText.trim()" @click="sendTest">
            发送
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
