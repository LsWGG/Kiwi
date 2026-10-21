<script setup lang="ts">
/** 上锁笔记的解锁门：未输入正确密码前不挂载任何编辑器 / 阅读组件。 */
import { nextTick, onMounted, ref } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = defineProps<{ note: NoteOut }>()
const emit = defineEmits<{ (e: 'unlocked'): void }>()

const notes = useNotesStore()
const password = ref('')
const error = ref('')
const busy = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)

onMounted(() => {
  void nextTick(() => inputRef.value?.focus())
})

async function submit() {
  if (busy.value) return
  const value = password.value
  if (!value) {
    error.value = '请输入密码'
    inputRef.value?.focus()
    return
  }
  busy.value = true
  error.value = ''
  try {
    await notes.unlockNote(props.note.id, value)
    // 重新拉取正文：上锁状态下后端只返回标题与提示。
    await notes.getNote(props.note.id)
    password.value = ''
    emit('unlocked')
  } catch (e: any) {
    error.value = e.message || '解锁失败，请重试'
    password.value = ''
    inputRef.value?.focus()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex-1 grid place-items-center px-6 py-10">
    <form
      class="w-full max-w-sm rounded-2xl glass-strong p-7 shadow-lifted animate-scale-in"
      @submit.prevent="submit"
    >
      <div class="flex flex-col items-center text-center">
        <span
          class="grid h-14 w-14 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-600 ring-1 ring-kiwi-100"
        >
          <KiwiIcon name="lock" :size="26" />
        </span>
        <h2 class="mt-4 truncate text-lg font-semibold text-slate-800" :title="note.title">
          {{ note.title || '无标题文档' }}
        </h2>
        <p class="mt-1 text-xs text-slate-400">这篇笔记已上锁，输入密码后查看内容</p>
        <p
          v-if="note.encrypted"
          class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-medium text-rose-500 ring-1 ring-rose-100"
        >
          <KiwiIcon name="shield" :size="11" />
          正文已加密存储
        </p>
        <p
          v-if="note.lock_hint"
          class="mt-3 w-full rounded-lg bg-amber-50/80 px-3 py-2 text-left text-[11.5px] text-amber-700 ring-1 ring-amber-100"
        >
          <span class="font-medium">密码提示：</span>{{ note.lock_hint }}
        </p>
      </div>

      <label class="mt-5 block text-[11px] font-medium text-slate-500" for="note-lock-password">
        密码
      </label>
      <input
        id="note-lock-password"
        ref="inputRef"
        v-model="password"
        type="password"
        autocomplete="current-password"
        class="kiwi-input mt-1.5 w-full"
        placeholder="输入笔记密码"
        :disabled="busy"
      />
      <p v-if="error" class="mt-2 text-[11.5px] text-rose-500">{{ error }}</p>

      <button type="submit" class="kiwi-btn-primary mt-4 w-full justify-center" :disabled="busy">
        <KiwiIcon :name="busy ? 'loader' : 'unlock'" :size="14" :spin="busy" />
        {{ busy ? '解锁中…' : '解锁查看' }}
      </button>
      <p class="mt-3 text-center text-[10.5px] leading-relaxed text-slate-400">
        解锁状态在当前页面内有效，刷新或关闭页面后需要重新输入密码。
      </p>
    </form>
  </div>
</template>
