<script setup lang="ts">
/**
 * 语音转写：实时录音（本地实时字幕 → 停止后自动转写）或上传音频。
 * 转写通道由系统设置决定：飞书妙记或本地 faster-whisper，完成后生成会议笔记。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { request, upload } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', noteId: string): void
}>()

const ACCEPT = '.mp3,.wav,.m4a,.aac,.ogg,.oga,.flac,.webm,.mp4,.opus'
const MAX_BYTES = 500 * 1024 * 1024
const POLL_MS = 1500
const PREVIEW_INTERVAL_MS = 12_000
const LEVEL_BARS = 16

interface TranscribeStatus {
  enabled: boolean
  provider: string
  provider_setting: string
  provider_ready: boolean
  feishu_configured: boolean
  preview_enabled: boolean
  local: { enabled: boolean; model: string; loaded: boolean }
}

interface Segment {
  start: number
  end: number
  text: string
}

interface PreviewOut {
  text: string
  segments: Segment[]
  language: string
  duration: number
  offset: number
}

interface JobOut {
  id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: number
  error: string | null
  message: string | null
  result: {
    note_id?: string | null
    provider?: string
    minute_url?: string
    fallback_reason?: string
  } & Record<string, unknown>
}

const kbs = useKbsStore()
const mode = ref<'record' | 'upload'>('record')
const status = ref<TranscribeStatus | null>(null)
const language = ref('auto')
const summarize = ref(true)
const title = ref('')
const error = ref('')

// --- 上传 ---
const file = ref<File | null>(null)
const dragOver = ref(false)
const input = ref<HTMLInputElement | null>(null)

// --- 录音 ---
const recording = ref(false)
const paused = ref(false)
const elapsedMs = ref(0)
const levelBars = ref<number[]>(Array(LEVEL_BARS).fill(0.06))
const transcript = ref<{ start: number; text: string }[]>([])
const previewBusy = ref(false)
const previewRounds = ref(0)
const previewError = ref('')
const recordedUrl = ref('')
const recordedBlob = ref<Blob | null>(null)
const recordedName = ref('')

let stream: MediaStream | null = null
let audioCtx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let finalRecorder: MediaRecorder | null = null
let previewRecorder: MediaRecorder | null = null
let finalChunks: BlobPart[] = []
let recordedMime = 'audio/webm'
let finalizeDone = false
let sessionId = 0
let startedAt = 0
let accumulatedMs = 0
let lastRotateAt = 0
let tickTimer: number | null = null
let pollTimer: number | null = null

const uploading = ref(false)
const jobId = ref('')
const jobStatus = ref<JobOut['status'] | ''>('')
const jobProvider = ref('')
const progress = ref(0)

const providerLabel = computed(() => {
  const value = status.value
  if (!value) return ''
  if (value.provider === 'feishu') return '飞书妙记'
  return '本地 faster-whisper'
})

const providerHint = computed(() => {
  const value = status.value
  if (!value) return ''
  if (value.provider === 'feishu') {
    return `音频会上传到飞书生成妙记，逐字稿整理为笔记${value.preview_enabled ? '；本地模型同时提供实时字幕' : ''}`
  }
  if (value.provider_setting === 'feishu' && !value.provider_ready) {
    return '飞书妙记尚未授权，请到「设置 → 模型 → 语音转写」扫码登录'
  }
  return '音频仅在本机识别，不会上传；首次转写会加载 whisper 模型'
})

const canRecord = computed(() => !!status.value?.enabled)
const canLivePreview = computed(() => !!status.value?.preview_enabled)
const elapsedLabel = computed(() => formatMs(elapsedMs.value))

watch(
  () => props.open,
  (open) => {
    if (open) {
      resetAll()
      void loadStatus()
    } else {
      abortSession()
    }
  },
)

onBeforeUnmount(abortSession)

async function loadStatus() {
  try {
    status.value = await request<TranscribeStatus>('/transcribe/status')
  } catch {
    status.value = null
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function revokeRecordedUrl() {
  if (recordedUrl.value) {
    URL.revokeObjectURL(recordedUrl.value)
    recordedUrl.value = ''
  }
}

function resetAll() {
  stopPolling()
  revokeRecordedUrl()
  mode.value = 'record'
  file.value = null
  title.value = ''
  language.value = 'auto'
  summarize.value = true
  uploading.value = false
  jobId.value = ''
  jobStatus.value = ''
  jobProvider.value = ''
  progress.value = 0
  error.value = ''
  transcript.value = []
  previewRounds.value = 0
  previewError.value = ''
  elapsedMs.value = 0
  recordedUrl.value = ''
  recordedBlob.value = null
  recordedName.value = ''
  levelBars.value = Array(LEVEL_BARS).fill(0.06)
}

function close() {
  abortSession()
  stopPolling()
  emit('close')
}

function switchMode(next: 'record' | 'upload') {
  if (recording.value || uploading.value) return
  mode.value = next
  error.value = ''
}

// --- 上传 ---

function pickFile() {
  input.value?.click()
}

function onFileChange(event: Event) {
  const selected = (event.target as HTMLInputElement).files?.[0]
  if (selected) acceptFile(selected)
  ;(event.target as HTMLInputElement).value = ''
}

function acceptFile(selected: File) {
  if (selected.size > MAX_BYTES) {
    error.value = '音频不能超过 500MB'
    return
  }
  error.value = ''
  file.value = selected
  if (!title.value) title.value = selected.name.replace(/\.[^.]+$/, '')
}

function onDrop(event: DragEvent) {
  dragOver.value = false
  const dropped = event.dataTransfer?.files?.[0]
  if (dropped) acceptFile(dropped)
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

async function submitFile() {
  if (!file.value || uploading.value) return
  await submitBlob(file.value, file.value.name)
}

// --- 录音 ---

function pickMime(): string {
  if (typeof MediaRecorder === 'undefined') return ''
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const item of candidates) {
    if (MediaRecorder.isTypeSupported(item)) return item
  }
  return ''
}

function extFromMime(type: string): string {
  if (type.includes('mp4')) return 'm4a'
  if (type.includes('ogg')) return 'ogg'
  return 'webm'
}

function defaultRecordingTitle(): string {
  const now = new Date()
  const pad = (v: number) => String(v).padStart(2, '0')
  return `录音笔记 ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
}

function formatMs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function formatStamp(seconds: number): string {
  return formatMs(seconds * 1000)
}

function currentElapsedMs(): number {
  if (!recording.value) return elapsedMs.value
  return accumulatedMs + (paused.value ? 0 : Date.now() - startedAt)
}

function setupAnalyser() {
  try {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    audioCtx = new Ctor()
    if (!stream) return
    const source = audioCtx.createMediaStreamSource(stream)
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 64
    analyser.smoothingTimeConstant = 0.7
    source.connect(analyser)
  } catch {
    analyser = null
  }
}

function updateLevel() {
  if (!analyser || paused.value) {
    levelBars.value = Array(LEVEL_BARS).fill(0.06)
    return
  }
  const data = new Uint8Array(analyser.frequencyBinCount)
  analyser.getByteFrequencyData(data)
  levelBars.value = Array.from({ length: LEVEL_BARS }, (_, index) => {
    const value = data[Math.min(data.length - 1, 1 + index * 2)] / 255
    return Math.max(0.06, Math.min(1, value))
  })
}

function tick() {
  elapsedMs.value = currentElapsedMs()
  updateLevel()
  if (
    recording.value &&
    !paused.value &&
    canLivePreview.value &&
    Date.now() - lastRotateAt >= PREVIEW_INTERVAL_MS
  ) {
    rotatePreview()
  }
}

async function startRecording() {
  if (recording.value) return
  if (!canRecord.value) {
    error.value = '语音转写不可用，请先完成转写配置'
    return
  }
  error.value = ''
  previewError.value = ''
  transcript.value = []
  previewRounds.value = 0
  elapsedMs.value = 0
  recordedUrl.value = ''
  recordedBlob.value = null
  recordedName.value = ''
  jobId.value = ''
  jobStatus.value = ''
  progress.value = 0
  accumulatedMs = 0
  finalizeDone = false
  sessionId += 1
  const sid = sessionId
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
  } catch {
    error.value = '无法访问麦克风，请检查浏览器权限或换用 Chrome / Edge'
    return
  }
  setupAnalyser()

  const mime = pickMime()
  finalChunks = []
  try {
    finalRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  } catch {
    error.value = '当前浏览器不支持录音'
    teardownStream()
    return
  }
  recordedMime = finalRecorder.mimeType || mime || 'audio/webm'
  finalRecorder.ondataavailable = (event) => {
    if (event.data.size) finalChunks.push(event.data)
  }
  finalRecorder.onstop = () => {
    if (sid !== sessionId) return
    finalizeRecording()
  }
  finalRecorder.start()
  recording.value = true
  paused.value = false
  startedAt = Date.now()
  lastRotateAt = Date.now()
  if (canLivePreview.value) startPreviewRecorder(sid)
  tickTimer = window.setInterval(tick, 500)
}

function startPreviewRecorder(sid: number) {
  if (!stream) return
  const chunks: BlobPart[] = []
  const base = currentElapsedMs() / 1000
  const mime = recordedMime
  let recorder: MediaRecorder
  try {
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  } catch {
    previewRecorder = null
    return
  }
  previewRecorder = recorder
  recorder.ondataavailable = (event) => {
    if (event.data.size) chunks.push(event.data)
  }
  recorder.onstop = () => {
    if (sid === sessionId && !paused.value) {
      const blob = new Blob(chunks, { type: mime })
      if (blob.size > 512) void sendPreview(blob, base, sid)
    }
    if (sid === sessionId && recording.value && !paused.value) {
      lastRotateAt = Date.now()
      startPreviewRecorder(sid)
    }
  }
  recorder.start()
  if (paused.value) recorder.pause()
}

function rotatePreview() {
  const recorder = previewRecorder
  previewRecorder = null
  if (recorder && recorder.state === 'recording') {
    try {
      recorder.stop()
    } catch {
      // ignore
    }
  }
}

async function sendPreview(blob: Blob, base: number, sid: number) {
  if (previewBusy.value || sid !== sessionId) return
  previewBusy.value = true
  try {
    const form = new FormData()
    form.append('file', new File([blob], `chunk.${extFromMime(blob.type)}`, { type: blob.type }))
    form.append('language', language.value)
    form.append('offset', String(base))
    const result = await upload<PreviewOut>('/transcribe/preview', form)
    if (sid !== sessionId) return
    previewRounds.value += 1
    mergePreview(result, base)
    previewError.value = ''
  } catch (e) {
    if (sid === sessionId) {
      previewError.value = e instanceof Error ? e.message : '实时预览失败'
    }
  } finally {
    previewBusy.value = false
  }
}

function mergePreview(result: PreviewOut, base: number) {
  const merged = new Map<string, { start: number; text: string }>()
  for (const item of transcript.value) merged.set(item.start.toFixed(2), item)
  const segments = result.segments || []
  if (segments.length) {
    for (const segment of segments) {
      const text = (segment.text || '').trim()
      if (!text) continue
      merged.set(Number(segment.start || 0).toFixed(2), {
        start: Number(segment.start || 0),
        text,
      })
    }
  } else if (result.text?.trim()) {
    merged.set(base.toFixed(2), { start: base, text: result.text.trim() })
  }
  transcript.value = [...merged.values()].sort((a, b) => a.start - b.start)
}

function pauseRecording() {
  if (!recording.value || paused.value) return
  accumulatedMs += Date.now() - startedAt
  paused.value = true
  elapsedMs.value = accumulatedMs
  try {
    finalRecorder?.pause()
    if (previewRecorder?.state === 'recording') previewRecorder.pause()
  } catch {
    // ignore
  }
  updateLevel()
}

function resumeRecording() {
  if (!recording.value || !paused.value) return
  paused.value = false
  startedAt = Date.now()
  try {
    finalRecorder?.resume()
    if (previewRecorder?.state === 'paused') previewRecorder.resume()
  } catch {
    // ignore
  }
}

function stopRecording() {
  if (!recording.value) return
  elapsedMs.value = currentElapsedMs()
  recording.value = false
  paused.value = false
  stopTimers()
  const preview = previewRecorder
  previewRecorder = null
  if (preview && preview.state === 'recording') {
    try {
      preview.stop()
    } catch {
      // ignore
    }
  }
  if (finalRecorder && finalRecorder.state !== 'inactive') {
    try {
      finalRecorder.stop()
    } catch {
      finalizeRecording()
    }
  } else {
    finalizeRecording()
  }
}

function finalizeRecording() {
  if (finalizeDone) return
  finalizeDone = true
  recording.value = false
  paused.value = false
  stopTimers()
  const blob = new Blob(finalChunks, { type: recordedMime })
  finalChunks = []
  teardownStream()
  levelBars.value = Array(LEVEL_BARS).fill(0.06)
  if (!blob.size) {
    error.value = '没有录到音频，请检查麦克风后重试'
    return
  }
  recordedBlob.value = blob
  revokeRecordedUrl()
  recordedUrl.value = URL.createObjectURL(blob)
  const stamp = new Date()
  const pad = (v: number) => String(v).padStart(2, '0')
  recordedName.value = `录音 ${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())} ${pad(stamp.getHours())}-${pad(stamp.getMinutes())}.${extFromMime(recordedMime)}`
  if (!title.value.trim()) title.value = defaultRecordingTitle()
  void submitBlob(blob, recordedName.value)
}

function abortSession() {
  sessionId += 1
  finalizeDone = true
  stopTimers()
  const preview = previewRecorder
  previewRecorder = null
  if (preview && preview.state === 'recording') {
    try {
      preview.stop()
    } catch {
      // ignore
    }
  }
  const final = finalRecorder
  finalRecorder = null
  if (final && final.state !== 'inactive') {
    try {
      final.stop()
    } catch {
      // ignore
    }
  }
  finalChunks = []
  recording.value = false
  paused.value = false
  uploadedReset()
  revokeRecordedUrl()
  teardownStream()
}

function uploadedReset() {
  uploading.value = false
}

function stopTimers() {
  if (tickTimer !== null) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function teardownStream() {
  if (stream) {
    for (const track of stream.getTracks()) track.stop()
  }
  stream = null
  analyser = null
  if (audioCtx) {
    void audioCtx.close().catch(() => undefined)
    audioCtx = null
  }
}

// --- 任务提交与轮询 ---

function retryUpload() {
  if (recordedBlob.value) void submitBlob(recordedBlob.value, recordedName.value)
}

async function submitBlob(blob: Blob, name: string) {
  if (uploading.value) return
  const kbId = kbs.currentKbId
  if (!kbId) {
    error.value = '请先选择知识库'
    return
  }
  uploading.value = true
  error.value = ''
  jobStatus.value = ''
  progress.value = 0
  jobProvider.value = ''
  try {
    const form = new FormData()
    form.append('file', new File([blob], name, { type: blob.type || 'audio/webm' }))
    form.append('language', language.value)
    form.append('title', title.value.trim())
    form.append('summarize', summarize.value ? 'true' : 'false')
    const resp = await upload<{ job_id: string; provider?: string }>('/transcribe', form, kbId)
    jobId.value = resp.job_id
    jobProvider.value = resp.provider || ''
    jobStatus.value = 'pending'
    pollTimer = window.setTimeout(() => void poll(resp.job_id), 600)
  } catch (e) {
    uploading.value = false
    error.value = e instanceof Error ? e.message : '上传音频失败'
  }
}

async function poll(id: string) {
  try {
    const job = await request<JobOut>(`/jobs/${id}`)
    jobStatus.value = job.status
    progress.value = job.progress || 0
    if (job.result?.provider) jobProvider.value = String(job.result.provider)
    if (job.status === 'succeeded') {
      stopPolling()
      uploading.value = false
      const noteId = job.result?.note_id
      if (noteId) {
        const engine = job.result?.provider === 'feishu' ? '飞书妙记' : '本地模型'
        toast.success(`转写完成（${engine}），已生成会议笔记`)
        emit('created', String(noteId))
        emit('close')
      } else {
        error.value = '转写完成，但没有生成笔记'
      }
      return
    }
    if (job.status === 'failed' || job.status === 'cancelled') {
      stopPolling()
      uploading.value = false
      error.value = job.error || (job.status === 'cancelled' ? '任务已取消' : '转写失败')
      return
    }
    pollTimer = window.setTimeout(() => void poll(id), POLL_MS)
  } catch (e) {
    stopPolling()
    uploading.value = false
    error.value = e instanceof Error ? e.message : '查询转写进度失败'
  }
}

const jobStatusLabel = computed(() => {
  if (jobStatus.value === 'pending') return '任务排队中…'
  if (jobStatus.value === 'running') return '正在转写并整理笔记…'
  return '正在上传音频…'
})
</script>

<template>
  <KiwiModal :open="open" title="语音转写" max-w="max-w-2xl" @close="close">
    <div class="space-y-3">
      <!-- 模式切换 -->
      <div class="flex w-fit items-center gap-1 rounded-xl border border-slate-200/70 bg-white/70 p-1">
        <button
          v-for="tab in [
            { key: 'record', label: '实时录音', icon: 'mic' },
            { key: 'upload', label: '上传音频', icon: 'upload' },
          ]"
          :key="tab.key"
          type="button"
          class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-medium transition-all"
          :class="
            mode === tab.key
              ? 'bg-kiwi-50 text-kiwi-700 shadow-sm ring-1 ring-kiwi-100'
              : 'text-slate-500 hover:text-slate-700'
          "
          :disabled="recording || uploading"
          @click="switchMode(tab.key as 'record' | 'upload')"
        >
          <KiwiIcon :name="tab.icon" :size="13" />
          {{ tab.label }}
        </button>
      </div>

      <div
        v-if="status"
        class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-1.5 text-[10.5px] text-slate-500"
      >
        <span
          class="rounded-full px-2 py-[1px] font-medium"
          :class="
            status.provider === 'feishu'
              ? 'bg-sky-50 text-sky-600'
              : 'bg-emerald-50 text-emerald-600'
          "
        >{{ providerLabel }}</span>
        <span class="min-w-0 leading-relaxed">{{ providerHint }}</span>
      </div>

      <div>
        <label class="mb-1.5 block text-[11px] font-medium text-slate-500">笔记标题（可选）</label>
        <input v-model="title" class="kiwi-input" placeholder="留空则按录音时间或文件名生成" />
      </div>

      <!-- 录音模式 -->
      <div v-if="mode === 'record'" class="space-y-3">
        <div class="rounded-2xl border border-slate-200/80 bg-white/70 p-4">
          <div class="flex items-center gap-3">
            <button
              v-if="!recording"
              type="button"
              class="grid h-11 w-11 place-items-center rounded-full bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white shadow-glow transition-transform hover:scale-105 disabled:opacity-50"
              :disabled="!canRecord || uploading"
              title="开始录音"
              @click="startRecording"
            >
              <KiwiIcon name="mic" :size="19" />
            </button>
            <template v-else>
              <span class="relative grid h-11 w-11 place-items-center rounded-full bg-rose-50 text-rose-500">
                <span class="absolute inset-0 animate-ping rounded-full bg-rose-200/60" />
                <KiwiIcon name="mic" :size="18" />
              </span>
            </template>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="font-mono text-xl font-semibold tabular-nums text-slate-700">
                  {{ elapsedLabel }}
                </span>
                <span
                  v-if="recording"
                  class="rounded-full px-2 py-[1px] text-[10px] font-medium"
                  :class="paused ? 'bg-amber-50 text-amber-600' : 'bg-rose-50 text-rose-500'"
                >
                  {{ paused ? '已暂停' : '录音中' }}
                </span>
              </div>
              <div class="mt-1.5 flex h-6 items-end gap-[3px]" aria-hidden="true">
                <span
                  v-for="(level, index) in levelBars"
                  :key="index"
                  class="w-full max-w-[10px] rounded-sm bg-kiwi-300 transition-[height] duration-150"
                  :style="{ height: `${Math.max(6, level * 24)}px` }"
                />
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <template v-if="recording">
                <button class="kiwi-btn-secondary !px-2.5 !py-1.5 !text-[11px]" @click="paused ? resumeRecording() : pauseRecording()">
                  <KiwiIcon :name="paused ? 'play' : 'square'" :size="12" />
                  {{ paused ? '继续' : '暂停' }}
                </button>
                <button class="kiwi-btn-primary !px-3 !py-1.5 !text-[11px]" @click="stopRecording">
                  <KiwiIcon name="check" :size="12" />
                  完成并转写
                </button>
              </template>
              <span v-else-if="!uploading" class="text-[10.5px] text-slate-400">
                点击麦克风开始
              </span>
            </div>
          </div>

          <!-- 实时字幕 -->
          <div
            v-if="canLivePreview"
            class="mt-3 max-h-52 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2"
          >
            <div v-if="transcript.length" class="space-y-1">
              <p
                v-for="item in transcript"
                :key="item.start"
                class="text-[11.5px] leading-relaxed text-slate-600"
              >
                <span class="mr-2 font-mono text-[10px] text-slate-400">{{ formatStamp(item.start) }}</span>
                {{ item.text }}
              </p>
            </div>
            <p v-else class="py-3 text-center text-[11px] text-slate-400">
              <template v-if="!recording">开始录音后，这里会显示实时转写</template>
              <template v-else-if="previewBusy">正在进行实时识别…</template>
              <template v-else-if="previewRounds">
                已实时识别 {{ previewRounds }} 段，暂未识别到语音文字
              </template>
              <template v-else>正在等待第一段实时字幕…（首次使用需先加载本地模型）</template>
            </p>
            <p v-if="previewError" class="mt-1 text-[10.5px] text-amber-600">{{ previewError }}</p>
          </div>
          <p v-else class="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-[10.5px] text-slate-400">
            本地模型未启用，录音时无法显示实时字幕；停止后仍会通过飞书妙记转写。
          </p>
        </div>

        <p class="text-[10.5px] leading-relaxed text-slate-400">
          录音完成后会自动上传并转写为会议笔记；长录音可关闭窗口，任务在后台继续。
        </p>
      </div>

      <!-- 上传模式 -->
      <div v-else class="space-y-3">
        <input ref="input" type="file" :accept="ACCEPT" class="hidden" @change="onFileChange" />
        <div
          class="rounded-xl border border-dashed px-4 py-5 text-center transition-colors"
          :class="dragOver ? 'border-kiwi-400 bg-kiwi-50/60' : 'border-slate-200 bg-slate-50/50'"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >
          <div class="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-white text-kiwi-500 shadow-sm">
            <KiwiIcon name="upload" :size="18" />
          </div>
          <p class="mt-2 text-[12.5px] font-medium text-slate-700">
            {{ file ? file.name : '拖入音频，或点击选择文件' }}
          </p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">
            {{ file ? formatSize(file.size) : 'mp3 / wav / m4a / ogg / flac / webm，最大 500MB' }}
          </p>
          <button class="kiwi-btn-ghost mt-2 !px-2.5 !py-1 !text-[11px]" type="button" :disabled="uploading" @click="pickFile">
            {{ file ? '重新选择' : '选择音频' }}
          </button>
        </div>

        <div class="flex justify-end">
          <button class="kiwi-btn-primary" :disabled="!file || uploading" @click="submitFile">
            <KiwiIcon :name="uploading ? 'loader' : 'mic'" :size="14" :spin="uploading" />
            {{ uploading ? '转写中…' : '开始转写' }}
          </button>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label class="mb-1.5 block text-[11px] font-medium text-slate-500">音频语言</label>
          <select v-model="language" class="kiwi-input" :disabled="recording || uploading">
            <option value="auto">自动识别</option>
            <option value="zh">中文</option>
            <option value="en">英语</option>
            <option value="ja">日语</option>
            <option value="ko">韩语</option>
          </select>
        </div>
        <label
          class="flex items-start gap-2 self-end rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 text-[11.5px] text-slate-600"
        >
          <input v-model="summarize" type="checkbox" class="mt-0.5 rounded border-slate-300" :disabled="uploading" />
          <span>
            整理 AI 会议纪要
            <span class="block text-[10px] leading-relaxed text-slate-400">
              提炼摘要、讨论点与待办；未配置大模型时只保留转写全文。
            </span>
          </span>
        </label>
      </div>

      <div
        v-if="uploading"
        class="flex items-start gap-2 rounded-lg border border-kiwi-100 bg-kiwi-50/60 px-3 py-2.5 text-[11.5px] text-kiwi-700"
      >
        <KiwiIcon name="loader" :size="14" :spin="true" class="mt-0.5 shrink-0" />
        <div class="min-w-0 flex-1">
          <p class="font-medium">
            {{ jobStatusLabel }}
            <span v-if="jobProvider" class="ml-1 font-normal text-kiwi-600/80">
              · {{ jobProvider === 'feishu' ? '飞书妙记' : '本地模型' }}
            </span>
          </p>
          <p class="mt-0.5 text-[10.5px] leading-relaxed text-kiwi-600/80">
            飞书妙记整理长音频可能需要几分钟，可以关闭窗口，任务会在后台继续。
          </p>
          <div class="mt-1.5 h-1 overflow-hidden rounded-full bg-white/70">
            <div
              class="h-full rounded-full bg-kiwi-400 transition-[width] duration-500"
              :style="{ width: `${Math.max(6, Math.round(progress * 100))}%` }"
            />
          </div>
        </div>
      </div>

      <audio v-if="recordedUrl" :src="recordedUrl" controls class="h-9 w-full" />

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>
      <div v-if="error && recordedBlob && !uploading" class="flex justify-end">
        <button class="kiwi-btn-secondary !py-1.5 !text-[11px]" @click="retryUpload">
          <KiwiIcon name="upload" :size="12" />
          重新上传录音
        </button>
      </div>
    </div>

    <div class="mt-5 flex items-center justify-between gap-2">
      <p class="text-[10px] leading-relaxed text-slate-400">
        {{ status?.provider === 'feishu' ? '音频会上传到飞书，仅用于生成妙记。' : '转写在本机完成，音频仅用于本次识别。' }}
      </p>
      <button class="kiwi-btn-secondary" @click="close">
        {{ uploading ? '后台继续' : '关闭' }}
      </button>
    </div>
  </KiwiModal>
</template>
