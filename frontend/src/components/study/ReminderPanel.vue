<script setup lang="ts">
/** 提醒设置：每日复习 / 待办提醒、每周学习报告与本设备推送订阅。 */
import { computed, onMounted, ref } from 'vue'
import { usePushStore } from '@/stores/push'
import { IS_DESKTOP } from '@/desktop/env'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const push = usePushStore()
const hour = ref(20)
const weekly = ref(true)
const saving = ref(false)

const hourOptions = Array.from({ length: 24 }, (_, index) => index)
const enabled = computed(() => push.status?.enabled ?? false)
const devices = computed(() => push.devices)
const permissionDenied = computed(() => push.permission === 'denied')

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function formatHour(value: number): string {
  return `${String(value).padStart(2, '0')}:00`
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function deviceName(ua: string): string {
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iPhone / iPad'
  if (/Android/i.test(ua)) return 'Android 设备'
  if (/Macintosh|Mac OS X/i.test(ua)) return 'Mac 浏览器'
  if (/Windows/i.test(ua)) return 'Windows 浏览器'
  if (/Linux/i.test(ua)) return 'Linux 浏览器'
  return '浏览器设备'
}

function deviceBrowser(ua: string): string {
  if (/Edg\//i.test(ua)) return 'Edge'
  if (/Firefox\//i.test(ua)) return 'Firefox'
  if (/Chrome\//i.test(ua)) return 'Chrome'
  if (/Safari\//i.test(ua)) return 'Safari'
  return '未知浏览器'
}

async function toggleEnabled() {
  if (!push.status || saving.value) return
  saving.value = true
  try {
    await push.setEnabled(!push.status.enabled)
  } catch (error) {
    toast.error(messageOf(error, '保存提醒设置失败'))
  } finally {
    saving.value = false
  }
}

async function saveSchedule() {
  if (!push.status || saving.value) return
  saving.value = true
  try {
    await push.saveSchedule(hour.value, weekly.value)
  } catch (error) {
    toast.error(messageOf(error, '保存提醒时间失败'))
  } finally {
    saving.value = false
  }
}

function toggleWeekly() {
  weekly.value = !weekly.value
  void saveSchedule()
}

async function enableDevice() {
  try {
    await push.subscribe()
    toast.success('已在本设备开启通知')
  } catch (error) {
    toast.error(messageOf(error, '开启通知失败'))
  }
}

async function disableDevice() {
  try {
    await push.unsubscribe()
    toast.success('已取消本设备通知')
  } catch (error) {
    toast.error(messageOf(error, '取消通知失败'))
  }
}

async function removeDevice(endpoint: string) {
  try {
    await push.removeDevice(endpoint)
    toast.success('已移除该设备')
  } catch (error) {
    toast.error(messageOf(error, '移除设备失败'))
  }
}

async function sendTest() {
  try {
    const result = await push.sendTest()
    if (result.sent > 0) toast.success(`测试通知已发送到 ${result.sent} 台设备`)
    else toast.error('推送失败，请检查浏览器通知权限')
  } catch (error) {
    toast.error(messageOf(error, '发送测试通知失败'))
  }
}

onMounted(async () => {
  try {
    await push.load()
    if (push.status) {
      hour.value = push.status.reminder_hour
      weekly.value = push.status.weekly_report
    }
  } catch (error) {
    toast.error(messageOf(error, '加载提醒设置失败'))
  }
})
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-4 animate-fade-up">
    <div class="flex items-center gap-2">
      <span
        class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-sm"
      >
        <KiwiIcon name="bell" :size="16" />
      </span>
      <div>
        <h3 class="font-semibold text-slate-800">提醒设置</h3>
        <p class="text-xs text-slate-400">复习到期、未完成待办与每周学习报告</p>
      </div>
    </div>

    <!-- 桌面版没有推送服务：提醒调度与 Web Push 后端均被禁用。 -->
    <section v-if="IS_DESKTOP" class="kiwi-card flex items-start gap-3 p-5">
      <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-400">
        <KiwiIcon name="bell" :size="16" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-[13px] font-medium text-slate-700">桌面版不提供推送提醒</p>
        <p class="mt-1 text-[11.5px] leading-relaxed text-slate-400">
          每日提醒、每周报告与设备通知依赖在线推送服务，桌面版默认不发起外网请求，因此该功能已关闭。
          到期复习与未完成待办仍会显示在「今日复习」和「学习计划」中。
        </p>
      </div>
    </section>

    <div
      v-else-if="push.loading && !push.status"
      class="kiwi-card flex items-center justify-center gap-2 p-12 text-[12px] text-slate-400"
    >
      <KiwiIcon name="loader" :size="15" :spin="true" />
      正在读取提醒配置…
    </div>

    <template v-else-if="push.status">
      <section class="kiwi-card p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-[13px] font-medium text-slate-700">每日提醒</p>
            <p class="mt-0.5 text-[11px] text-slate-400">
              到期复习与未完成待办，每天最多推送一次
            </p>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="enabled"
            :disabled="saving"
            class="relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200"
            :class="enabled ? 'bg-kiwi-500' : 'bg-slate-200'"
            @click="toggleEnabled"
          >
            <span
              class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-all duration-200"
              :class="enabled ? 'left-[22px]' : 'left-0.5'"
            />
          </button>
        </div>

        <div class="mt-4 flex items-center justify-between gap-3 border-t border-slate-100 pt-3.5">
          <div>
            <p class="text-[12.5px] text-slate-600">提醒时间</p>
            <p class="mt-0.5 text-[10.5px] text-slate-400">按本机时区，在设定时间之后送达</p>
          </div>
          <select
            v-model.number="hour"
            :disabled="!enabled || saving"
            class="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] tabular-nums text-slate-600 outline-none transition-colors focus:border-kiwi-400 disabled:cursor-not-allowed disabled:opacity-50"
            @change="saveSchedule"
          >
            <option v-for="value in hourOptions" :key="value" :value="value">
              {{ formatHour(value) }}
            </option>
          </select>
        </div>

        <div class="mt-3 flex items-center justify-between gap-3 border-t border-slate-100 pt-3.5">
          <div>
            <p class="text-[12.5px] text-slate-600">每周学习报告</p>
            <p class="mt-0.5 text-[10.5px] text-slate-400">
              每周一汇总上周答题量、正确率与学习时长
            </p>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="weekly"
            :disabled="saving"
            class="relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200"
            :class="weekly ? 'bg-kiwi-500' : 'bg-slate-200'"
            @click="toggleWeekly"
          >
            <span
              class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-all duration-200"
              :class="weekly ? 'left-[22px]' : 'left-0.5'"
            />
          </button>
        </div>
      </section>

      <section class="kiwi-card p-4">
        <div class="flex items-start gap-3">
          <span class="mt-0.5 grid h-8 w-8 place-items-center rounded-lg bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="smartphone" :size="16" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-[13px] font-medium text-slate-700">本设备通知</p>
            <p v-if="!push.supported" class="mt-0.5 text-[11px] text-amber-600">
              当前浏览器不支持 Web Push；需要通过 HTTPS 或 localhost 访问。
            </p>
            <p v-else-if="permissionDenied" class="mt-0.5 text-[11px] text-amber-600">
              通知权限已被拒绝，请在浏览器站点设置中允许通知后重试。
            </p>
            <p v-else-if="push.subscribed" class="mt-0.5 text-[11px] text-emerald-600">
              已订阅，提醒会通过浏览器推送服务送达。
            </p>
            <p v-else class="mt-0.5 text-[11px] text-slate-400">
              开启后即使关闭 Kiwi 页面，也能收到系统通知。
            </p>
          </div>
          <button
            v-if="push.supported && push.subscribed"
            class="kiwi-btn-ghost shrink-0 !px-2.5 !py-1.5 !text-[11px]"
            :disabled="push.busy"
            @click="disableDevice"
          >
            取消订阅
          </button>
          <button
            v-else-if="push.supported"
            class="kiwi-btn-primary shrink-0 !px-3 !py-1.5 !text-[11px]"
            :disabled="push.busy || permissionDenied"
            @click="enableDevice"
          >
            开启通知
          </button>
        </div>
        <p class="mt-3 border-t border-slate-100 pt-3 text-[10.5px] leading-relaxed text-slate-400">
          iPhone / iPad 需先在 Safari 中「添加到主屏幕」，iOS 16.4 起支持网页推送；桌面端浏览器完全退出后，系统通知仍可送达。
        </p>
      </section>

      <section v-if="devices.length" class="kiwi-card p-4">
        <h4 class="mb-2.5 text-[12px] font-semibold text-slate-700">已订阅设备</h4>
        <ul class="space-y-2">
          <li
            v-for="device in devices"
            :key="device.id"
            class="flex items-center gap-2 rounded-lg bg-slate-50/70 px-2.5 py-2"
          >
            <KiwiIcon name="bell" :size="13" class="shrink-0 text-slate-400" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-[11.5px] text-slate-700">
                {{ deviceName(device.user_agent) }}
              </p>
              <p class="text-[10px] text-slate-400">
                {{ deviceBrowser(device.user_agent) }} · 订阅于 {{ formatDate(device.created_at) }}
                <span v-if="device.failure_count" class="text-amber-500">
                  · 最近失败 {{ device.failure_count }} 次
                </span>
              </p>
            </div>
            <button
              class="kiwi-btn-ghost shrink-0 !p-1"
              title="移除设备"
              :disabled="push.busy"
              @click="removeDevice(device.endpoint)"
            >
              <KiwiIcon name="trash" :size="13" />
            </button>
          </li>
        </ul>
      </section>

      <section class="kiwi-card flex items-center justify-between gap-3 p-4">
        <div>
          <p class="text-[12.5px] text-slate-700">测试推送</p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">
            立即向全部已订阅设备发送一条测试通知
            <span v-if="push.status.last_daily_date">
              ；上次每日提醒 {{ push.status.last_daily_date }}
            </span>
          </p>
        </div>
        <button
          class="kiwi-btn-ghost shrink-0 !px-2.5 !py-1.5 !text-[11px]"
          :disabled="push.busy || !devices.length"
          @click="sendTest"
        >
          发送测试
        </button>
      </section>
    </template>
  </div>
</template>
