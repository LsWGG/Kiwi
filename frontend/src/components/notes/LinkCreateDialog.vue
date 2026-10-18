<script setup lang="ts">
/** 新建链接笔记：服务端抓取正文，失败降级为书签。 */
import { ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { toast } from '@/components/ui/toast'

const props = withDefaults(
  defineProps<{ open: boolean; folderId?: string | null }>(),
  { folderId: null },
)

const emit = defineEmits<{ (e: 'close'): void; (e: 'created', note: NoteOut): void }>()

const notes = useNotesStore()
const url = ref('')
const title = ref('')
const loading = ref(false)
const error = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    url.value = ''
    title.value = ''
    error.value = ''
    loading.value = false
  },
)

async function submit() {
  const raw = url.value.trim()
  if (!raw) {
    error.value = '请输入链接地址'
    return
  }
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    error.value = '链接格式不正确'
    return
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    error.value = '仅支持 http / https 链接'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const note = await notes.createLink({
      url: parsed.toString(),
      title: title.value.trim() || undefined,
      folder_id: props.folderId,
    })
    const ok = note.props_json?.link?.fetch_status === 'ok'
    toast[ok ? 'success' : 'info'](
      ok ? '已抓取网页正文' : '暂时无法抓取正文，已保存为书签',
    )
    emit('created', note)
    emit('close')
  } catch (e: any) {
    error.value = e.message || '创建失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <KiwiModal :open="open" title="新建链接" max-w="max-w-md" @close="emit('close')">
    <div class="space-y-3">
      <div>
        <label class="block text-[11px] font-medium text-slate-500 mb-1.5">链接地址</label>
        <div class="relative">
          <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-300">
            <KiwiIcon name="link2" :size="14" />
          </span>
          <input
            v-model="url"
            class="kiwi-input !pl-9"
            placeholder="https://example.com/article"
            autofocus
            @keyup.enter="submit"
          />
        </div>
      </div>
      <div>
        <label class="block text-[11px] font-medium text-slate-500 mb-1.5">标题（可选）</label>
        <input v-model="title" class="kiwi-input" placeholder="留空则使用网页标题" @keyup.enter="submit" />
      </div>
      <p class="flex items-start gap-1.5 text-[11px] leading-relaxed text-slate-400">
        <KiwiIcon name="sparkle" :size="12" class="mt-0.5 shrink-0" />
        服务器会抓取网页正文并转为 Markdown；抓取失败时仍会保存书签卡片。
      </p>
      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>
    </div>
    <div class="flex justify-end gap-2 mt-5">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" :disabled="loading" @click="submit">
        <KiwiIcon v-if="loading" name="loader" :size="14" spin />
        {{ loading ? '抓取中…' : '创建链接' }}
      </button>
    </div>
  </KiwiModal>
</template>
