<script setup lang="ts">
/** 只读分享链接：有效期、可选访问密码、复制与撤销。 */
import { computed, ref, watch } from 'vue'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore } from '@/stores/notes'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

/** 目录树摘要与详情页共用的最小字段集，避免为打开分享面板再拉全文。 */
interface NoteShareTarget {
  id: string
  title: string
  is_locked?: boolean
}

const props = defineProps<{ open: boolean; note: NoteShareTarget | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

interface NoteShare {
  id: string
  note_id: string
  token: string
  path: string
  url?: string | null
  expires_at: string
  has_password: boolean
  view_count: number
  last_viewed_at: string | null
  revoked_at: string | null
  created_at: string
  active: boolean
}

const kbs = useKbsStore()
const notes = useNotesStore()

const shares = ref<NoteShare[]>([])
const loading = ref(false)
const creating = ref(false)
const copiedId = ref('')
const expiry = ref('168')
const usePassword = ref(false)
const password = ref('')
const revokeTarget = ref<NoteShare | null>(null)

const EXPIRY_OPTIONS = [
  { value: '1', label: '1 小时' },
  { value: '24', label: '1 天' },
  { value: '168', label: '7 天' },
  { value: '720', label: '30 天' },
]

const canCreate = computed(
  () => !creating.value && !props.note?.is_locked && (!usePassword.value || password.value.length >= 4),
)

function linkFor(share: NoteShare): string {
  // 配置了公网分享域名时后端直接返回完整地址；否则退回当前访问地址。
  return share.url || `${window.location.origin}${share.path}`
}

function expiryLabel(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function load() {
  const note = props.note
  if (!kbs.currentKbId || !note) return
  loading.value = true
  try {
    shares.value = await request<NoteShare[]>(`/notes/${note.id}/shares`, {
      kbId: kbs.currentKbId,
      headers: notes.noteHeaders(note.id),
    })
  } catch (e: any) {
    toast.error(e.message || '加载分享链接失败')
  } finally {
    loading.value = false
  }
}

async function create() {
  const note = props.note
  if (!canCreate.value || !kbs.currentKbId || !note) return
  creating.value = true
  try {
    const share = await request<NoteShare>(`/notes/${note.id}/shares`, {
      method: 'POST',
      kbId: kbs.currentKbId,
      headers: notes.noteHeaders(note.id),
      body: JSON.stringify({
        expires_in_hours: Number(expiry.value),
        password: usePassword.value ? password.value : null,
      }),
    })
    shares.value = [share, ...shares.value]
    password.value = ''
    usePassword.value = false
    await copy(share)
    toast.success('分享链接已创建并复制')
  } catch (e: any) {
    toast.error(e.message || '创建分享链接失败')
  } finally {
    creating.value = false
  }
}

async function copy(share: NoteShare) {
  const text = linkFor(share)
  try {
    await navigator.clipboard.writeText(text)
    copiedId.value = share.id
    window.setTimeout(() => {
      if (copiedId.value === share.id) copiedId.value = ''
    }, 1800)
  } catch {
    // 非安全上下文（http + 内网 IP）可能没有剪贴板权限，退回手动复制。
    window.prompt('复制分享链接', text)
  }
}

async function revoke() {
  const share = revokeTarget.value
  const note = props.note
  if (!share || !kbs.currentKbId || !note) return
  try {
    await request(`/notes/${note.id}/shares/${share.id}`, {
      method: 'DELETE',
      kbId: kbs.currentKbId,
      headers: notes.noteHeaders(note.id),
    })
    shares.value = shares.value.filter((item) => item.id !== share.id)
    revokeTarget.value = null
    toast.success('分享链接已撤销')
  } catch (e: any) {
    toast.error(e.message || '撤销失败')
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    expiry.value = '168'
    usePassword.value = false
    password.value = ''
    copiedId.value = ''
    revokeTarget.value = null
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <KiwiModal :open="open" title="分享只读链接" max-w="max-w-lg" @close="emit('close')">
    <template v-if="note">
    <p class="mb-4 text-[12px] leading-relaxed text-slate-500">
      获得链接的人无需登录即可阅读《{{ note.title || '无标题' }}》。链接只读，
      可设置有效期与访问密码，随时撤销。
    </p>

    <div
      v-if="note.is_locked"
      class="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2.5 text-[11.5px] text-amber-700"
    >
      <KiwiIcon name="lock" :size="14" class="mt-0.5 shrink-0" />
      该笔记已上锁，暂不支持分享。请先在笔记菜单中移除密码锁。
    </div>

    <!-- 创建表单 -->
    <div class="rounded-xl border border-slate-200/70 bg-white/60 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <label class="text-[11.5px] text-slate-500">有效期</label>
        <select v-model="expiry" class="kiwi-input !w-auto !py-1 !text-[11.5px]">
          <option v-for="option in EXPIRY_OPTIONS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <label class="ml-1 inline-flex cursor-pointer items-center gap-1.5 text-[11.5px] text-slate-500">
          <input v-model="usePassword" type="checkbox" class="accent-kiwi-600" />
          访问密码
        </label>
        <input
          v-if="usePassword"
          v-model="password"
          type="password"
          maxlength="128"
          autocomplete="new-password"
          class="kiwi-input !min-w-[120px] flex-1 !py-1 !text-[11.5px]"
          placeholder="至少 4 位"
          @keydown.enter.prevent="create"
        />
        <div class="flex-1" />
        <button class="kiwi-btn-primary !px-3 !py-1.5 !text-[11.5px]" :disabled="!canCreate" @click="create">
          <KiwiIcon :name="creating ? 'loader' : 'link2'" :size="12" :spin="creating" />
          {{ creating ? '创建中…' : '创建链接' }}
        </button>
      </div>
      <p v-if="usePassword && password.length > 0 && password.length < 4" class="mt-1.5 text-[10.5px] text-rose-500">
        密码至少需要 4 位。
      </p>
    </div>

    <!-- 已有链接 -->
    <div class="mt-4">
      <div class="mb-2 flex items-center justify-between">
        <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-400">有效链接</h4>
        <span v-if="loading" class="text-[10px] text-slate-400">加载中…</span>
      </div>
      <p v-if="!loading && !shares.length" class="rounded-lg bg-slate-50/70 px-3 py-3 text-[11px] text-slate-400">
        还没有分享链接。
      </p>
      <div v-else class="space-y-2">
        <div
          v-for="share in shares"
          :key="share.id"
          class="rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2.5"
        >
          <div class="flex items-center gap-2">
            <KiwiIcon name="link2" :size="12" class="shrink-0 text-kiwi-500" />
            <a
              :href="share.path"
              target="_blank"
              rel="noopener noreferrer"
              class="min-w-0 flex-1 truncate text-[11.5px] text-kiwi-700 hover:underline"
              :title="linkFor(share)"
            >
              {{ linkFor(share) }}
            </a>
            <button
              class="kiwi-btn-ghost shrink-0 !px-2 !py-1 !text-[10.5px]"
              :title="copiedId === share.id ? '已复制' : '复制链接'"
              @click="copy(share)"
            >
              <KiwiIcon :name="copiedId === share.id ? 'check' : 'copy'" :size="11" />
              {{ copiedId === share.id ? '已复制' : '复制' }}
            </button>
            <button
              class="shrink-0 rounded-md px-1.5 py-1 text-[10.5px] text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
              title="撤销链接"
              @click="revokeTarget = share"
            >
              <KiwiIcon name="trash" :size="11" />
            </button>
          </div>
          <div class="mt-1.5 flex flex-wrap items-center gap-2 pl-[20px] text-[10px] text-slate-400">
            <span>到期 {{ expiryLabel(share.expires_at) }}</span>
            <span v-if="share.has_password" class="inline-flex items-center gap-0.5 text-amber-600">
              <KiwiIcon name="lock" :size="9" /> 密码
            </span>
            <span>浏览 {{ share.view_count }} 次</span>
          </div>
        </div>
      </div>
    </div>

    <KiwiConfirm
      :model-value="!!revokeTarget"
      danger
      title="撤销分享链接"
      message="撤销后该链接立即失效，已打开过页面的人刷新后也无法继续访问。"
      confirm-text="撤销"
      @update:model-value="(value: boolean) => { if (!value) revokeTarget = null }"
      @confirm="revoke"
    />
    </template>
  </KiwiModal>
</template>
