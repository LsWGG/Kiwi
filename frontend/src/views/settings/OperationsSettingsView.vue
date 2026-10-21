<script setup lang="ts">
/**
 * 运维设置：前后端构建一致性、持久化任务、审计日志与自动备份。
 *
 * 任务与备份均来自后台队列；备份在服务端执行，前端只负责触发与展示，
 * 不提供覆盖式恢复入口（恢复属于不可逆操作，由 scripts/restore_backup.sh 完成）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'
import {
  auditExportUrl,
  cancelJob,
  getBackendBuildInfo,
  getFrontendBuildInfo,
  listAudit,
  listBackups,
  listJobs,
  retryJob,
  triggerBackup,
  type AuditEntry,
  type BackupEntry,
  type BackupList,
  type BuildInfo,
  type Job,
  type JobStatus,
} from '@/api/operations'

const jobs = ref<Job[]>([])
const jobsTotal = ref(0)
const statusFilter = ref<'' | JobStatus>('')
const jobsLoading = ref(false)
const jobActionId = ref<string | null>(null)

const auditEntries = ref<AuditEntry[]>([])
const auditTotal = ref(0)
const auditAction = ref('')
const auditLoading = ref(false)
const expandedAudit = ref<string | null>(null)

const backups = ref<BackupList | null>(null)
const backupsLoading = ref(false)
const triggeringBackup = ref(false)

const backendBuild = ref<BuildInfo | null>(null)
const frontendBuild = ref<BuildInfo | null>(null)

const activeCount = computed(
  () => jobs.value.filter((job) => job.status === 'pending' || job.status === 'running').length,
)
const failedCount = computed(() => jobs.value.filter((job) => job.status === 'failed').length)

const buildMismatch = computed(() => {
  const backend = backendBuild.value?.commit
  const frontend = frontendBuild.value?.commit
  if (!backend || !frontend) return false
  if (backend === 'unknown' || frontend === 'unknown') return false
  return backend !== frontend
})

const JOB_KIND: Record<string, string> = {
  ingest: '素材摄入',
  note_compile: '笔记编译',
  kb_import: '知识库导入',
  backup: '数据备份',
}

const JOB_STATUS: Record<JobStatus, { label: string; tone: string; dot: string }> = {
  pending: {
    label: '等待中',
    tone: 'bg-slate-100 text-slate-500 ring-slate-200/70',
    dot: 'bg-slate-400',
  },
  running: {
    label: '运行中',
    tone: 'bg-kiwi-50 text-kiwi-600 ring-kiwi-200/70',
    dot: 'bg-kiwi-500',
  },
  succeeded: {
    label: '已完成',
    tone: 'bg-emerald-50 text-emerald-600 ring-emerald-200/70',
    dot: 'bg-emerald-500',
  },
  failed: {
    label: '失败',
    tone: 'bg-rose-50 text-rose-600 ring-rose-200/70',
    dot: 'bg-rose-500',
  },
  cancelled: {
    label: '已取消',
    tone: 'bg-amber-50 text-amber-600 ring-amber-200/70',
    dot: 'bg-amber-400',
  },
}

const AUDIT_ACTION: Record<string, string> = {
  'kb.delete': '删除知识库',
  'kb.export': '导出知识库',
  'kb.import': '导入知识库',
  'note.delete': '删除笔记',
  'note.revision.delete': '删除笔记版本',
  'note.transfer': '转移笔记',
  'note.trash.empty': '清空回收站',
  'wiki.rebuild': '重建 Wiki',
}

const STATUS_OPTIONS: Array<{ value: '' | JobStatus; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

function jobStatusMeta(status: string) {
  return JOB_STATUS[status as JobStatus] || JOB_STATUS.pending
}

function jobKindLabel(kind: string) {
  return JOB_KIND[kind] || kind
}

function auditActionLabel(action: string) {
  return AUDIT_ACTION[action] || action
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatSize(bytes?: number) {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function backupSize(item: BackupEntry) {
  const files = item.files || []
  return files.reduce((sum, file) => sum + (Number(file.size) || 0), 0)
}

function auditSummary(entry: AuditEntry) {
  const detail = entry.detail || {}
  const parts: string[] = []
  for (const key of ['title', 'name', 'filename', 'count', 'mode']) {
    const value = detail[key]
    if (value === undefined || value === null || value === '') continue
    parts.push(`${key === 'count' ? '数量' : key === 'mode' ? '方式' : key === 'name' ? '名称' : key === 'title' ? '标题' : '文件'}：${String(value)}`)
  }
  return entry.note || parts.join(' · ')
}

/** 进度后端按 0–1 存储，展示时转换为百分比。 */
function jobProgress(job: Job) {
  return Math.max(0, Math.min(100, Math.round((Number(job.progress) || 0) * 100)))
}

async function loadJobs(silent = false) {
  if (jobsLoading.value) return
  jobsLoading.value = true
  try {
    const data = await listJobs({ limit: 50, status: statusFilter.value || undefined })
    jobs.value = data.items
    jobsTotal.value = data.total
  } catch (e: any) {
    if (!silent) toast.error(e.message || '读取任务列表失败')
  } finally {
    jobsLoading.value = false
    schedulePoll()
  }
}

async function loadAudit() {
  if (auditLoading.value) return
  auditLoading.value = true
  try {
    const data = await listAudit({ limit: 50, action: auditAction.value || undefined })
    auditEntries.value = data.items
    auditTotal.value = data.total
  } catch (e: any) {
    toast.error(e.message || '读取审计日志失败')
  } finally {
    auditLoading.value = false
  }
}

async function loadBackups() {
  if (backupsLoading.value) return
  backupsLoading.value = true
  try {
    backups.value = await listBackups()
  } catch (e: any) {
    toast.error(e.message || '读取备份列表失败')
  } finally {
    backupsLoading.value = false
  }
}

async function loadBuildInfo() {
  try {
    backendBuild.value = await getBackendBuildInfo()
  } catch (e: any) {
    toast.error(e.message || '读取后端构建信息失败')
  }
  frontendBuild.value = await getFrontendBuildInfo()
}

async function refreshAll() {
  await Promise.allSettled([loadJobs(true), loadAudit(), loadBackups(), loadBuildInfo()])
}

async function onStatusChange() {
  await loadJobs()
}

async function onAuditActionChange() {
  await loadAudit()
}

async function handleRetry(job: Job) {
  if (jobActionId.value) return
  jobActionId.value = job.id
  try {
    await retryJob(job.id)
    toast.success('任务已重新入队')
    await loadJobs(true)
  } catch (e: any) {
    toast.error(e.message || '重试任务失败')
  } finally {
    jobActionId.value = null
  }
}

async function handleCancel(job: Job) {
  if (jobActionId.value) return
  jobActionId.value = job.id
  try {
    await cancelJob(job.id)
    toast.success('已请求取消任务')
    await loadJobs(true)
  } catch (e: any) {
    toast.error(e.message || '取消任务失败')
  } finally {
    jobActionId.value = null
  }
}

async function handleBackup() {
  if (triggeringBackup.value) return
  triggeringBackup.value = true
  try {
    await triggerBackup()
    toast.success('备份任务已创建，完成后可在下方查看')
    await Promise.allSettled([loadJobs(true), loadBackups()])
  } catch (e: any) {
    toast.error(e.message || '创建备份任务失败')
  } finally {
    triggeringBackup.value = false
  }
}

function toggleAuditDetail(entry: AuditEntry) {
  expandedAudit.value = expandedAudit.value === entry.id ? null : entry.id
}

/** 有进行中的任务时每 5 秒刷新一次；页面隐藏或任务结束后自动停止。 */
let pollTimer: ReturnType<typeof setTimeout> | null = null
function schedulePoll() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  if (!activeCount.value) return
  pollTimer = setTimeout(async () => {
    pollTimer = null
    if (document.visibilityState === 'visible') await loadJobs(true)
    else schedulePoll()
  }, 5000)
}

onMounted(async () => {
  await refreshAll()
})

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
})

const cardClass = 'animate-fade-up rounded-2xl glass-strong p-5'
const selectClass =
  'rounded-xl border border-slate-200/80 bg-white/80 px-2.5 py-1.5 text-[12px] text-slate-600 outline-none transition-colors focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60'
</script>

<template>
  <div class="page-wrap-slim px-8 py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-500 to-kiwi-600 text-white shadow-glow">
          <KiwiIcon name="server" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">运维与安全</h1>
          <p class="mt-1 text-sm text-slate-500">
            查看构建版本、后台任务、审计记录与自动备份状态。
          </p>
        </div>
      </div>
      <button class="kiwi-btn-secondary" :disabled="jobsLoading || auditLoading" @click="refreshAll">
        <KiwiIcon name="refresh" :size="14" />
        刷新
      </button>
    </div>

    <SettingsTabs />

    <div class="space-y-6">
      <!-- 构建与版本 -->
      <section :class="cardClass">
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-2">
            <KiwiIcon name="monitor" :size="15" class="text-kiwi-500" />
            <h2 class="text-[14px] font-semibold text-slate-700">构建与版本</h2>
          </div>
          <span class="text-[10px] text-slate-400">
            部署后若前后端提交不一致，说明静态资源与后端代码不同步。
          </span>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <div class="rounded-xl border border-slate-200/70 bg-white/60 p-4">
            <div class="mb-2 flex items-center gap-2 text-[12px] font-medium text-slate-600">
              <KiwiIcon name="monitor" :size="13" class="text-slate-400" />
              前端静态资源
            </div>
            <dl class="space-y-1.5 text-[11.5px]">
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">版本</dt>
                <dd class="font-mono text-slate-700">{{ frontendBuild?.version || '—' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">提交</dt>
                <dd class="font-mono text-slate-700">{{ frontendBuild?.commit || '未获取到' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">构建时间</dt>
                <dd class="text-slate-600">{{ formatTime(frontendBuild?.built_at) }}</dd>
              </div>
            </dl>
          </div>

          <div class="rounded-xl border border-slate-200/70 bg-white/60 p-4">
            <div class="mb-2 flex items-center gap-2 text-[12px] font-medium text-slate-600">
              <KiwiIcon name="server" :size="13" class="text-slate-400" />
              后端服务
            </div>
            <dl class="space-y-1.5 text-[11.5px]">
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">版本</dt>
                <dd class="font-mono text-slate-700">{{ backendBuild?.version || '—' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">提交</dt>
                <dd class="font-mono text-slate-700">{{ backendBuild?.commit || '未获取到' }}</dd>
              </div>
              <div class="flex items-center justify-between gap-3">
                <dt class="text-slate-400">启动时间</dt>
                <dd class="text-slate-600">{{ formatTime(backendBuild?.started_at) }}</dd>
              </div>
            </dl>
          </div>
        </div>

        <div
          v-if="buildMismatch"
          class="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2.5 text-[11.5px] leading-relaxed text-amber-700"
        >
          <KiwiIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
          <span>
            前后端提交不一致（前端 {{ frontendBuild?.commit }} / 后端 {{ backendBuild?.commit }}），
            请重新执行 <code class="rounded bg-white/70 px-1 font-mono">npm run build</code> 并重启后端，避免页面与接口行为不匹配。
          </span>
        </div>
      </section>

      <!-- 持久化任务 -->
      <section :class="cardClass">
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-2">
            <KiwiIcon name="loader" :size="15" class="text-kiwi-500" />
            <h2 class="text-[14px] font-semibold text-slate-700">后台任务</h2>
          </div>
          <span class="text-[10px] text-slate-400">
            共 {{ jobsTotal }} 条 · 进行中 {{ activeCount }} · 失败 {{ failedCount }}
          </span>
          <div class="ml-auto flex items-center gap-2">
            <select v-model="statusFilter" :class="selectClass" @change="onStatusChange">
              <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
            <button
              class="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              :disabled="jobsLoading"
              title="刷新任务"
              @click="loadJobs()"
            >
              <KiwiIcon name="refresh" :size="14" :spin="jobsLoading" />
            </button>
          </div>
        </div>

        <div v-if="!jobs.length" class="rounded-xl border border-dashed border-slate-200 bg-white/40 px-4 py-10 text-center text-[12px] text-slate-400">
          {{ jobsLoading ? '读取任务…' : '暂无后台任务' }}
        </div>

        <div v-else class="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200/70 bg-white/50">
          <div
            v-for="job in jobs"
            :key="job.id"
            class="px-4 py-3"
            :data-job-row="job.id"
            :data-job-kind="job.kind"
            :data-job-status="job.status"
          >
            <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span
                class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] font-medium ring-1"
                :class="jobStatusMeta(job.status).tone"
              >
                <span class="h-1.5 w-1.5 rounded-full" :class="jobStatusMeta(job.status).dot" />
                {{ jobStatusMeta(job.status).label }}
              </span>
              <span class="text-[12.5px] font-medium text-slate-700">{{ jobKindLabel(job.kind) }}</span>
              <span class="font-mono text-[10.5px] text-slate-400" :title="job.id">
                {{ job.id.slice(0, 8) }}
              </span>
              <span class="text-[10.5px] text-slate-400">
                尝试 {{ job.attempts }}/{{ job.max_attempts }}
              </span>
              <span class="ml-auto text-[10.5px] text-slate-400">{{ formatTime(job.created_at) }}</span>

              <button
                v-if="job.status === 'pending' || job.status === 'running'"
                class="flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-rose-500 transition-colors hover:bg-rose-50 disabled:opacity-50"
                :disabled="jobActionId === job.id"
                @click="handleCancel(job)"
              >
                <KiwiIcon name="close" :size="11" />
                取消
              </button>
              <button
                v-else-if="job.status === 'failed' || job.status === 'cancelled'"
                class="flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-kiwi-600 transition-colors hover:bg-kiwi-50 disabled:opacity-50"
                :disabled="jobActionId === job.id"
                @click="handleRetry(job)"
              >
                <KiwiIcon name="refresh" :size="11" />
                重试
              </button>
            </div>

            <div v-if="job.status === 'running'" class="mt-2 flex items-center gap-2">
              <div class="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-kiwi-400 to-kiwi-600 transition-all"
                  :style="{ width: `${jobProgress(job)}%` }"
                />
              </div>
              <span class="w-9 text-right font-mono text-[10px] text-slate-400">{{ jobProgress(job) }}%</span>
            </div>

            <p v-if="job.message" class="mt-1.5 text-[11px] leading-relaxed text-slate-500">
              {{ job.message }}
            </p>
            <p
              v-if="job.error"
              class="mt-1.5 line-clamp-2 break-all text-[11px] leading-relaxed text-rose-500"
              :title="job.error"
            >
              {{ job.error }}
            </p>
          </div>
        </div>

        <p v-if="jobsTotal > jobs.length" class="mt-2 text-[10.5px] text-slate-400">
          仅显示最近 {{ jobs.length }} 条，可通过状态筛选缩小范围。
        </p>
      </section>

      <!-- 审计日志 -->
      <section :class="cardClass">
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-2">
            <KiwiIcon name="shield" :size="15" class="text-kiwi-500" />
            <h2 class="text-[14px] font-semibold text-slate-700">审计日志</h2>
          </div>
          <span class="text-[10px] text-slate-400">共 {{ auditTotal }} 条 · 记录删除、转移、导出等敏感操作</span>
          <div class="ml-auto flex items-center gap-2">
            <select v-model="auditAction" :class="selectClass" @change="onAuditActionChange">
              <option value="">全部操作</option>
              <option v-for="(label, action) in AUDIT_ACTION" :key="action" :value="action">
                {{ label }}
              </option>
            </select>
            <a
              :href="auditExportUrl(undefined, auditAction || undefined)"
              class="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5 text-[11px] text-slate-500 transition-colors hover:border-kiwi-200 hover:text-kiwi-600"
              download
            >
              <KiwiIcon name="download" :size="12" />
              导出 CSV
            </a>
          </div>
        </div>

        <div v-if="!auditEntries.length" class="rounded-xl border border-dashed border-slate-200 bg-white/40 px-4 py-10 text-center text-[12px] text-slate-400">
          {{ auditLoading ? '读取审计日志…' : '暂无审计记录' }}
        </div>

        <div v-else class="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200/70 bg-white/50">
          <div v-for="entry in auditEntries" :key="entry.id">
            <button
              type="button"
              class="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left transition-colors hover:bg-slate-50/70"
              :aria-expanded="expandedAudit === entry.id"
              @click="toggleAuditDetail(entry)"
            >
              <span class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-600">
                {{ auditActionLabel(entry.action) }}
              </span>
              <span class="min-w-0 flex-1 truncate text-[11.5px] text-slate-600">
                {{ auditSummary(entry) || entry.target_type + ' · ' + entry.target_id }}
              </span>
              <span class="text-[10.5px] text-slate-400">{{ entry.actor || 'local' }}</span>
              <span class="text-[10.5px] text-slate-400">{{ formatTime(entry.created_at) }}</span>
              <KiwiIcon
                :name="expandedAudit === entry.id ? 'chevronsUp' : 'chevronsDown'"
                :size="12"
                class="text-slate-300"
              />
            </button>
            <div
              v-if="expandedAudit === entry.id"
              class="border-t border-slate-100 bg-slate-50/60 px-4 py-2.5 text-[10.5px] text-slate-500"
            >
              <p>操作 ID：<span class="font-mono">{{ entry.id }}</span></p>
              <p v-if="entry.request_id">请求 ID：<span class="font-mono">{{ entry.request_id }}</span></p>
              <p v-if="entry.ip">来源 IP：<span class="font-mono">{{ entry.ip }}</span></p>
              <pre class="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white/80 p-2 font-mono text-[10px] text-slate-500">{{ JSON.stringify(entry.detail, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </section>

      <!-- 自动备份 -->
      <section :class="cardClass">
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-2">
            <KiwiIcon name="database" :size="15" class="text-kiwi-500" />
            <h2 class="text-[14px] font-semibold text-slate-700">自动备份</h2>
          </div>
          <span class="text-[10px] text-slate-400">
            {{ backups?.enabled ? `每 ${backups.interval_hours} 小时自动执行，保留 ${backups.retention_days} 天` : '自动备份未启用，仍可手动触发' }}
          </span>
          <button
            class="kiwi-btn-secondary ml-auto !px-3 !py-1.5 !text-[11.5px]"
            :disabled="triggeringBackup"
            @click="handleBackup"
          >
            <KiwiIcon :name="triggeringBackup ? 'loader' : 'play'" :size="12" :spin="triggeringBackup" />
            {{ triggeringBackup ? '创建中…' : '立即备份' }}
          </button>
        </div>

        <div class="mb-3 grid gap-2 text-[10.5px] text-slate-400 sm:grid-cols-2">
          <p v-if="backups?.directory" class="truncate" :title="backups.directory">
            备份目录：<span class="font-mono text-slate-500">{{ backups.directory }}</span>
          </p>
          <p class="sm:text-right">
            恢复请使用 <code class="rounded bg-slate-100 px-1 font-mono text-slate-500">scripts/restore_backup.sh</code>，应用内不提供一键覆盖。
          </p>
        </div>

        <div v-if="!backups?.items?.length" class="rounded-xl border border-dashed border-slate-200 bg-white/40 px-4 py-10 text-center text-[12px] text-slate-400">
          {{ backupsLoading ? '读取备份列表…' : '还没有备份。点击「立即备份」创建第一份快照。' }}
        </div>

        <div v-else class="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200/70 bg-white/50">
          <div
            v-for="item in backups.items"
            :key="item.name"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[11.5px]"
          >
            <KiwiIcon name="folder" :size="13" class="text-slate-300" />
            <span class="font-mono text-[11px] text-slate-700">{{ item.name }}</span>
            <span
              v-if="item.trigger"
              class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
            >
              {{ item.trigger === 'manual' ? '手动' : item.trigger === 'job' ? '任务' : item.trigger }}
            </span>
            <span class="text-[10.5px] text-slate-400">{{ formatSize(backupSize(item)) }}</span>
            <span class="text-[10.5px] text-slate-400">
              {{ item.uploads_included ? '含附件' : '仅数据库' }}
            </span>
            <span class="ml-auto text-[10.5px] text-slate-400">{{ formatTime(item.created_at) }}</span>
          </div>
        </div>

        <p class="mt-2 text-[10.5px] leading-relaxed text-slate-400">
          备份包含 PostgreSQL 自定义格式转储、uploads 归档与 manifest 校验文件；
          大库备份可能耗时较久，执行期间可继续使用系统。
        </p>
      </section>
    </div>
  </div>
</template>
