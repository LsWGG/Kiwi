<script setup lang="ts">
/** 设置 / 移除笔记密码锁。密码只在请求中传输，不会写入本地存储。 */
import { computed, ref, watch } from 'vue'
import { useNotesStore } from '@/stores/notes'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

type LockTarget = {
  id: string
  title?: string
  is_locked?: boolean
  lock_hint?: string | null
  encrypted?: boolean
}

const props = defineProps<{ open: boolean; note: LockTarget | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'changed', locked: boolean): void
}>()

const notes = useNotesStore()
const password = ref('')
const confirm = ref('')
const hint = ref('')
const encrypt = ref(false)
const error = ref('')
const busy = ref(false)

const locked = computed(() => !!props.note?.is_locked)
const encrypted = computed(() => !!props.note?.encrypted)
const hasToken = computed(() => (props.note ? notes.hasUnlockToken(props.note.id) : false))
const canRemoveWithoutPassword = computed(() => locked.value && hasToken.value)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    password.value = ''
    confirm.value = ''
    hint.value = ''
    encrypt.value = false
    error.value = ''
    busy.value = false
  },
)

async function submitLock() {
  if (!props.note || busy.value) return
  if (password.value.length < 4) {
    error.value = '密码至少 4 位'
    return
  }
  if (password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await notes.setNoteLock(
      props.note.id,
      password.value,
      hint.value.trim() || null,
      encrypt.value,
    )
    toast.success(
      encrypt.value
        ? '已设置密码锁并加密正文，请妥善保管密码'
        : '已设置密码锁，刷新页面后需要密码才能查看',
    )
    emit('changed', true)
    emit('close')
  } catch (e: any) {
    error.value = e.message || '设置失败'
  } finally {
    busy.value = false
  }
}

async function removeLock() {
  if (!props.note || busy.value) return
  if (!canRemoveWithoutPassword.value && !password.value) {
    error.value = '请输入当前密码'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await notes.removeNoteLock(
      props.note.id,
      canRemoveWithoutPassword.value ? undefined : password.value,
    )
    toast.success('已移除密码锁')
    emit('changed', false)
    emit('close')
  } catch (e: any) {
    error.value = e.message || '移除失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <KiwiModal
    :open="open"
    :title="locked ? '笔记密码锁' : '设置笔记密码锁'"
    max-w="max-w-md"
    @close="emit('close')"
  >
    <div v-if="note" class="space-y-4">
      <div class="flex items-start gap-3 rounded-xl bg-slate-50/80 p-3 ring-1 ring-slate-100">
        <span
          class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg"
          :class="locked ? 'bg-amber-50 text-amber-600' : 'bg-kiwi-50 text-kiwi-600'"
        >
          <KiwiIcon :name="locked ? 'lock' : 'unlock'" :size="16" />
        </span>
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-slate-700">{{ note.title || '无标题文档' }}</p>
          <p class="mt-0.5 text-[11.5px] leading-relaxed text-slate-400">
            {{
              locked
                ? '这篇笔记已上锁。移除密码后，搜索、AI 检索与待办同步会重新收录其内容。'
                : '设置后，正文不会出现在目录预览、搜索、AI 问答与待办汇总中；打开笔记需要输入密码。'
            }}
          </p>
        </div>
      </div>

      <template v-if="locked">
        <div
          v-if="encrypted"
          class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50/70 px-3 py-2.5 text-[11px] leading-relaxed text-rose-600"
        >
          <KiwiIcon name="shield" :size="14" class="mt-0.5 shrink-0" />
          <span>
            正文已加密存储，检索与版本记录均不包含明文；密码丢失后正文无法恢复。
            移除密码锁时会先解密并恢复为明文存储。
          </span>
        </div>
        <p
          v-if="note.lock_hint"
          class="rounded-lg bg-amber-50/80 px-3 py-2 text-[11.5px] text-amber-700 ring-1 ring-amber-100"
        >
          <span class="font-medium">密码提示：</span>{{ note.lock_hint }}
        </p>
        <div v-if="!canRemoveWithoutPassword">
          <label class="text-[11px] font-medium text-slate-500" for="lock-remove-password">
            当前密码
          </label>
          <input
            id="lock-remove-password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="kiwi-input mt-1.5 w-full"
            placeholder="输入当前密码后移除"
            :disabled="busy"
            @keydown.enter.prevent="removeLock"
          />
        </div>
        <p v-else class="text-[11px] text-emerald-600">当前会话已解锁，可以直接移除密码锁。</p>
      </template>

      <template v-else>
        <div>
          <label class="text-[11px] font-medium text-slate-500" for="lock-new-password">密码</label>
          <input
            id="lock-new-password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            class="kiwi-input mt-1.5 w-full"
            placeholder="至少 4 位"
            :disabled="busy"
          />
        </div>
        <div>
          <label class="text-[11px] font-medium text-slate-500" for="lock-confirm-password">
            确认密码
          </label>
          <input
            id="lock-confirm-password"
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            class="kiwi-input mt-1.5 w-full"
            placeholder="再次输入密码"
            :disabled="busy"
            @keydown.enter.prevent="submitLock"
          />
        </div>
        <div>
          <label class="text-[11px] font-medium text-slate-500" for="lock-hint">
            密码提示 <span class="font-normal text-slate-400">（可选）</span>
          </label>
          <input
            id="lock-hint"
            v-model="hint"
            maxlength="120"
            class="kiwi-input mt-1.5 w-full"
            placeholder="例如：常用设备型号"
            :disabled="busy"
          />
        </div>
        <label
          class="flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition-colors"
          :class="encrypt ? 'border-kiwi-300 bg-kiwi-50/70' : 'border-slate-200 bg-white/60'"
        >
          <input
            v-model="encrypt"
            type="checkbox"
            class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-kiwi-600"
            :disabled="busy"
          />
          <span class="min-w-0">
            <span class="block text-[12px] font-medium text-slate-700">加密存储正文（推荐）</span>
            <span class="mt-0.5 block text-[10.5px] leading-relaxed text-slate-400">
              正文以密码派生的密钥加密后写入数据库，即使直接读取数据库也无法看到内容。
              上锁期间搜索、AI 问答与待办同步不会收录这篇笔记。
            </span>
          </span>
        </label>
        <div
          v-if="encrypt"
          class="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2.5 text-[11px] leading-relaxed text-amber-700"
        >
          <KiwiIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
          <span>
            密码丢失后正文<strong class="font-semibold">无法恢复</strong>，且将清除已有历史版本。
            请先确认已将密码保存在安全的地方。
          </span>
        </div>
      </template>

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button type="button" class="kiwi-btn-secondary" :disabled="busy" @click="emit('close')">
          取消
        </button>
        <button
          v-if="locked"
          type="button"
          class="kiwi-btn-primary !bg-rose-500 hover:!bg-rose-600"
          :disabled="busy"
          @click="removeLock"
        >
          <KiwiIcon :name="busy ? 'loader' : 'unlock'" :size="14" :spin="busy" />
          移除密码锁
        </button>
        <button v-else type="button" class="kiwi-btn-primary" :disabled="busy" @click="submitLock">
          <KiwiIcon :name="busy ? 'loader' : 'lock'" :size="14" :spin="busy" />
          设置密码锁
        </button>
      </div>
    </div>
  </KiwiModal>
</template>
