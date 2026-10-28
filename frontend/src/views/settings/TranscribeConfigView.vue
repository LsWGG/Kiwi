<script setup lang="ts">
/**
 * 语音转写配置：选择本地 faster-whisper 或飞书妙记。
 * 飞书妙记通过扫码授权（OAuth）获取用户令牌，密钥全部加密存储。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { request } from '@/api/client'
import { IS_DESKTOP } from '@/desktop/env'
import { toast } from '@/components/ui/toast'
import { useSystemStore, type SystemSettings } from '@/stores/system'

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

interface TranscribeStatus {
  enabled: boolean
  provider: string
  provider_setting: string
  provider_ready: boolean
  feishu_configured: boolean
  preview_enabled: boolean
  local: {
    enabled: boolean
    model: string
    device: string
    compute_type: string
    loaded: boolean
  }
}

interface AuthStart {
  authorize_url: string
  state: string
  redirect_uri: string
}

interface AuthStatus {
  status: 'pending' | 'done' | 'error' | 'expired'
  message: string
}

const PROVIDERS = [
  { value: 'auto', label: '自动', hint: '已配置飞书妙记时走线上，否则用本地模型' },
  { value: 'local', label: '本地模型', hint: 'faster-whisper 在本机转写，音频不出设备' },
  { value: 'feishu', label: '飞书妙记', hint: '上传到飞书生成妙记，逐字稿回填为笔记' },
]

const system = useSystemStore()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const authorizing = ref(false)
const authMessage = ref('')
const showManualToken = ref(false)
const secretTouched = ref(false)
const tokenTouched = ref(false)
const testResult = ref<{ ok: boolean; message: string } | null>(null)
const status = ref<TranscribeStatus | null>(null)
const saved = ref<SystemSettings | null>(null)

const form = ref({
  provider: 'auto',
  app_id: '',
  app_secret: '',
  user_token: '',
  folder_token: '',
  redirect_uri: '',
})

let pollTimer: number | null = null

const defaultCallback = computed(
  () => `${window.location.origin}/api/transcribe/feishu/oauth/callback`,
)

const hasSecret = computed(() => !!saved.value?.has_feishu_app_secret)
const hasUserToken = computed(() => !!saved.value?.has_feishu_user_token)
const hasRefreshToken = computed(() => !!saved.value?.has_feishu_refresh_token)
const authorized = computed(() => hasUserToken.value || hasRefreshToken.value)
const feishuReady = computed(
  () => status.value?.feishu_configured ?? false,
)

const dirty = computed(() => {
  const current = saved.value
  if (!current) return true
  return (
    form.value.provider !== current.transcribe_provider ||
    form.value.app_id.trim() !== current.feishu_app_id ||
    form.value.folder_token.trim() !== current.feishu_folder_token ||
    form.value.redirect_uri.trim() !== current.feishu_redirect_uri ||
    (secretTouched.value && form.value.app_secret !== '') ||
    (tokenTouched.value && form.value.user_token !== '')
  )
})

function hydrate(settings: SystemSettings) {
  saved.value = settings
  form.value = {
    provider: settings.transcribe_provider || 'auto',
    app_id: settings.feishu_app_id || '',
    app_secret: '',
    user_token: '',
    folder_token: settings.feishu_folder_token || '',
    redirect_uri: settings.feishu_redirect_uri || '',
  }
  secretTouched.value = false
  tokenTouched.value = false
  testResult.value = null
}

async function loadStatus() {
  try {
    status.value = await request<TranscribeStatus>('/transcribe/status')
  } catch {
    status.value = null
  }
}

async function load() {
  loading.value = true
  try {
    hydrate(await system.fetchSettings(true))
    await loadStatus()
    if (saved.value?.has_feishu_app_secret && !saved.value?.has_feishu_user_token && !saved.value?.has_feishu_refresh_token) {
      authMessage.value = '应用凭据已保存，等待飞书扫码授权'
    }
  } catch (e: any) {
    toast.error(e.message || '读取转写配置失败')
    hydrate(system.settings)
  } finally {
    loading.value = false
  }
}

onMounted(load)

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})

async function save(silent = false) {
  const appId = form.value.app_id.trim()
  if (form.value.provider === 'feishu' && !appId) {
    toast.info('启用飞书妙记前请填写应用 App ID')
    return false
  }
  if (form.value.provider === 'feishu' && !hasSecret.value && !form.value.app_secret.trim()) {
    toast.info('启用飞书妙记前请填写应用 App Secret')
    return false
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      transcribe_provider: form.value.provider,
      feishu_app_id: appId,
      feishu_folder_token: form.value.folder_token.trim(),
      feishu_redirect_uri: form.value.redirect_uri.trim(),
    }
    if (secretTouched.value) payload.feishu_app_secret = form.value.app_secret
    if (tokenTouched.value) payload.feishu_user_token = form.value.user_token
    const updated = await system.saveSettings(payload as Partial<SystemSettings>)
    hydrate(updated)
    await loadStatus()
    if (!silent) toast.success('转写配置已保存')
    return true
  } catch (e: any) {
    toast.error(e.message || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  if (IS_DESKTOP) {
    toast.error('桌面版已禁用语音转写，无法测试飞书妙记')
    return
  }
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return
  }
  testing.value = true
  testResult.value = null
  try {
    const result = await request<{ ok: boolean; message: string }>(
      '/transcribe/feishu/test',
      { method: 'POST' },
    )
    testResult.value = result
    if (result.ok) toast.success(result.message)
    else toast.error(result.message)
  } catch (e: any) {
    testResult.value = { ok: false, message: e.message || '测试失败' }
    toast.error(e.message || '测试失败')
  } finally {
    testing.value = false
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function pollAuth(
  state: string,
  startedAt: number,
  popup: Window | null = null,
  closedPolls = 0,
) {
  try {
    const result = await request<AuthStatus>(
      `/transcribe/feishu/oauth/status?state=${encodeURIComponent(state)}`,
    )
    authMessage.value = result.message
    if (result.status === 'done') {
      authorizing.value = false
      toast.success(result.message || '飞书授权成功')
      const updated = await system.fetchSettings(true)
      hydrate(updated)
      await loadStatus()
      return
    }
    if (result.status === 'error' || result.status === 'expired') {
      authorizing.value = false
      toast.error(result.message || '飞书授权失败')
      return
    }
    // 用户手动关掉授权窗口后，再等几个轮询周期（防止刚完成回调）就结束等待。
    if (popup?.closed) {
      closedPolls += 1
      if (closedPolls >= 3) {
        authorizing.value = false
        authMessage.value = '授权窗口已关闭，可重新发起扫码'
        return
      }
    } else {
      closedPolls = 0
    }
  } catch {
    // 网络抖动时继续轮询
  }
  if (Date.now() - startedAt > 10 * 60_000) {
    authorizing.value = false
    authMessage.value = '授权超时，请重新发起扫码'
    return
  }
  pollTimer = window.setTimeout(
    () => void pollAuth(state, startedAt, popup, closedPolls),
    2000,
  )
}

async function startAuth() {
  if (IS_DESKTOP) {
    toast.error('桌面版已禁用飞书妙记授权')
    return
  }
  if (authorizing.value) return
  const popup = window.open(
    'about:blank',
    'kiwi-feishu-oauth',
    'popup=yes,width=520,height=720',
  )
  if (!popup) {
    toast.error('浏览器阻止了授权弹窗，请允许弹窗后重试')
    return
  }
  authorizing.value = true
  authMessage.value = '正在打开飞书授权页…'
  stopPolling()
  try {
    if (dirty.value || !saved.value?.has_feishu_app_secret) {
      const ok = await save(true)
      if (!ok) {
        popup.close()
        authorizing.value = false
        authMessage.value = ''
        return
      }
    }
    const result = await request<AuthStart>('/transcribe/feishu/oauth/start', {
      method: 'POST',
      body: JSON.stringify({ origin: window.location.origin }),
    })
    popup.location.href = result.authorize_url
    authMessage.value = '请在弹窗中用飞书扫码，完成后自动同步'
    void pollAuth(result.state, Date.now(), popup)
  } catch (e: any) {
    popup.close()
    authorizing.value = false
    authMessage.value = ''
    toast.error(e.message || '发起飞书授权失败')
  }
}

function useCurrentOrigin() {
  form.value.redirect_uri = defaultCallback.value
}
</script>

<template>
  <div class="space-y-5">
    <!-- 桌面版不下载 whisper 模型，也不连接飞书妙记 -->
    <div
      v-if="IS_DESKTOP"
      class="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-[11.5px] leading-relaxed text-amber-700"
    >
      桌面版已禁用语音转写：不下载 faster-whisper 模型，也不连接飞书妙记。
      已有转写笔记仍可阅读；如需转写，请使用 Docker / Web 部署。
    </div>

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取转写配置…
    </div>

    <template v-else-if="!IS_DESKTOP">
      <!-- 通道选择 -->
      <div class="grid gap-2 sm:grid-cols-3">
        <button
          v-for="item in PROVIDERS"
          :key="item.value"
          type="button"
          class="rounded-2xl border p-3 text-left transition-all"
          :class="
            form.provider === item.value
              ? 'border-kiwi-200 bg-white shadow-soft ring-1 ring-kiwi-100'
              : 'border-slate-200/70 bg-white/50 hover:border-kiwi-200'
          "
          :aria-pressed="form.provider === item.value"
          @click="form.provider = item.value"
        >
          <span class="flex items-center gap-1.5">
            <span
              class="text-[12.5px] font-semibold"
              :class="form.provider === item.value ? 'text-kiwi-700' : 'text-slate-700'"
            >{{ item.label }}</span>
            <KiwiIcon
              v-if="form.provider === item.value"
              name="check"
              :size="11"
              class="text-kiwi-500"
            />
          </span>
          <span class="mt-1 block text-[10.5px] leading-relaxed text-slate-400">
            {{ item.hint }}
          </span>
        </button>
      </div>

      <!-- 本地模型状态 -->
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-slate-200/70 bg-white/60 px-3.5 py-2.5 text-[11px] text-slate-500">
        <span class="flex items-center gap-1.5">
          <KiwiIcon name="layers" :size="12" class="text-slate-400" />
          本地 faster-whisper
        </span>
        <span v-if="status?.local">
          模型 <span class="font-mono text-slate-600">{{ status.local.model }}</span>
          · {{ status.local.device }} / {{ status.local.compute_type }}
          · {{ status.local.loaded ? '已加载' : '首次使用时加载' }}
          · {{ status.local.enabled ? '可用' : '已关闭' }}
        </span>
        <span
          class="ml-auto flex items-center gap-1"
          :class="status?.provider === 'feishu' ? 'text-sky-600' : 'text-emerald-600'"
        >
          <KiwiIcon name="check" :size="12" />
          当前通道：{{ status?.provider === 'feishu' ? '飞书妙记' : '本地模型' }}
        </span>
      </div>

      <!-- 飞书妙记配置 -->
      <div
        v-if="form.provider !== 'local'"
        class="space-y-4 rounded-2xl glass-strong p-5 animate-scale-in"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-100 to-white text-sky-600">
              <KiwiIcon name="mic" :size="16" />
            </span>
            <div>
              <p class="text-sm font-semibold text-slate-700">飞书妙记</p>
              <p class="text-[10.5px] text-slate-400">
                在飞书开放平台创建企业自建应用，开启云空间与妙记权限
              </p>
            </div>
          </div>
          <span
            class="rounded-full px-2 py-[2px] text-[10px] font-medium"
            :class="
              feishuReady
                ? 'bg-emerald-50 text-emerald-600'
                : authorized
                  ? 'bg-amber-50 text-amber-600'
                  : 'bg-slate-100 text-slate-500'
            "
          >
            {{ feishuReady ? '已授权可用' : authorized ? '授权待校验' : '未授权' }}
          </span>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">App ID</span>
            <input
              v-model="form.app_id"
              class="kiwi-input"
              placeholder="cli_xxxxxxxxxxxxxxxx"
              maxlength="100"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">
              App Secret
              <span
                v-if="hasSecret && !secretTouched"
                class="ml-1 text-[10px] font-normal text-emerald-600"
              >已保存 · 留空保持不变</span>
            </span>
            <input
              v-model="form.app_secret"
              type="password"
              class="kiwi-input"
              autocomplete="new-password"
              :placeholder="hasSecret ? '••••••••（留空保持不变）' : '应用密钥'"
              @input="secretTouched = true"
            />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">云空间文件夹 Token（可选）</span>
            <input
              v-model="form.folder_token"
              class="kiwi-input"
              placeholder="留空使用应用可访问的根目录"
              maxlength="200"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span class="mb-1.5 flex items-center justify-between text-[11.5px] font-medium text-slate-600">
              OAuth 回调地址（可选）
              <button type="button" class="text-[10px] font-normal text-kiwi-600 hover:underline" @click="useCurrentOrigin">
                使用当前域名
              </button>
            </span>
            <input
              v-model="form.redirect_uri"
              class="kiwi-input font-mono !text-[11px]"
              :placeholder="defaultCallback"
              maxlength="500"
              spellcheck="false"
            />
          </label>
        </div>
        <p class="text-[10.5px] leading-relaxed text-slate-400">
          回调地址需与开放平台「安全设置 → 重定向 URL」完全一致；留空时按当前访问域名自动推导。
        </p>

        <div class="flex flex-wrap items-center gap-2 rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2.5">
          <KiwiIcon
            :name="authorized ? 'check' : 'alert'"
            :size="14"
            :class="authorized ? 'text-emerald-500' : 'text-slate-400'"
          />
          <span class="text-[11.5px] text-slate-600">
            {{ authorizing ? authMessage : authorized ? '已获取飞书用户授权' : '尚未扫码授权' }}
          </span>
          <span v-if="hasRefreshToken && !authorizing" class="text-[10.5px] text-slate-400">
            刷新令牌已加密保存，可自动续期
          </span>
          <button
            class="kiwi-btn-secondary ml-auto !py-1.5 !text-xs"
            :disabled="authorizing || saving"
            @click="startAuth"
          >
            <KiwiIcon :name="authorizing ? 'loader' : 'mic'" :size="13" :spin="authorizing" />
            {{ authorizing ? '等待扫码…' : authorized ? '重新扫码授权' : '飞书扫码授权' }}
          </button>
        </div>

        <button
          type="button"
          class="text-[10.5px] text-slate-400 transition-colors hover:text-slate-600"
          @click="showManualToken = !showManualToken"
        >
          {{ showManualToken ? '隐藏手动令牌' : '已有用户访问令牌？手动粘贴' }}
        </button>
        <label v-if="showManualToken" class="block">
          <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">
            user_access_token
            <span v-if="hasUserToken && !tokenTouched" class="ml-1 text-[10px] font-normal text-emerald-600">
              已保存 · 留空保持不变
            </span>
          </span>
          <input
            v-model="form.user_token"
            type="password"
            class="kiwi-input font-mono !text-[11px]"
            autocomplete="new-password"
            placeholder="u-xxxxxxxxxxxxxxxx"
            @input="tokenTouched = true"
          />
          <span class="mt-1 block text-[10.5px] text-slate-400">
            手动令牌不会自动续期，约 2 小时后失效；推荐使用扫码授权。
          </span>
        </label>

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
        </div>
      </div>

      <p
        v-else
        class="rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2.5 text-[10.5px] leading-relaxed text-slate-400"
      >
        本地模式不会上传音频；首次转写会下载并加载 whisper 模型，耗时取决于网络与 CPU。
      </p>

      <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
        <p class="text-[10.5px] leading-relaxed text-slate-400">
          录音弹窗会实时显示本地转写结果，停止后按当前通道生成会议笔记。
        </p>
        <div class="flex items-center gap-2">
          <button
            v-if="form.provider !== 'local'"
            class="kiwi-btn-secondary"
            :disabled="testing || saving"
            @click="testConnection"
          >
            <KiwiIcon name="loader" :size="13" :spin="testing" />
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <button class="kiwi-btn-primary" :disabled="saving" @click="save()">
            <KiwiIcon :name="saving ? 'loader' : 'check'" :size="14" :spin="saving" />
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
