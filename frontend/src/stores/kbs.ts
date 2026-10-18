import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { request } from '@/api/client'

export interface KbOverview {
  id: string
  name: string
  slug: string
  description: string
  embedding_model: string
  llm_config_id: string | null
  pinned: boolean
  /** 是否开启学习模式；关闭后仅用于记录与检索 */
  learning_enabled: boolean
  /** 系统内置演示库：删除为软删除，可还原 */
  is_builtin: boolean
  builtin_key: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
  source_count: number
  wiki_count: number
  note_count: number
  onboarded: boolean
  goal_type: string | null
  attempted_topics: number
  mastered_topics: number
  mastery_coverage: number
  due_reviews: number
  last_activity_at: string | null
}

export interface BuiltinKbStatus {
  key: string
  name: string
  exists: boolean
  deleted: boolean
  kb_id: string | null
}

export const useKbsStore = defineStore('kbs', () => {
  const kbs = ref<KbOverview[]>([])
  // 编辑模式与学习模式各自记住上次使用的知识库（README 双模隔离）
  const currentKbId = ref<string | null>(localStorage.getItem('kiwi.kb.edit'))
  const learnKbId = ref<string | null>(localStorage.getItem('kiwi.kb.learn'))
  const loading = ref(false)
  const builtinStatus = ref<BuiltinKbStatus | null>(null)

  watch(currentKbId, (id) => {
    if (id) localStorage.setItem('kiwi.kb.edit', id)
    else localStorage.removeItem('kiwi.kb.edit')
  })
  watch(learnKbId, (id) => {
    if (id) localStorage.setItem('kiwi.kb.learn', id)
    else localStorage.removeItem('kiwi.kb.learn')
  })

  const currentKb = computed(() =>
    kbs.value.find((k) => k.id === currentKbId.value) ?? null,
  )
  const learnKb = computed(() =>
    kbs.value.find((k) => k.id === learnKbId.value) ?? null,
  )

  /**
   * 学习模式当前知识库：优先独立记忆，其次回落到编辑模式选择。
   * 回落目标必须开启学习模式，否则学习空间会落到只记录知识库并触发 403。
   */
  const activeLearnKbId = computed(() => {
    if (learnKbId.value) return learnKbId.value
    const cur = currentKb.value
    return cur && cur.learning_enabled !== false ? cur.id : null
  })

  async function fetchKbs() {
    loading.value = true
    try {
      kbs.value = await request<KbOverview[]>('/kbs')
      const ids = new Set(kbs.value.map((k) => k.id))
      // 仅开启学习模式的知识库可进入学习空间
      const learnable = kbs.value.filter((k) => k.learning_enabled !== false)
      if (currentKbId.value && !ids.has(currentKbId.value)) currentKbId.value = null
      if (learnKbId.value && !learnable.some((k) => k.id === learnKbId.value)) {
        learnKbId.value = null
      }
      if (!currentKbId.value && kbs.value.length) {
        currentKbId.value = kbs.value[0].id
      }
      if (!learnKbId.value) {
        learnKbId.value =
          learnable.find((k) => k.id === currentKbId.value)?.id ?? learnable[0]?.id ?? null
      }
    } finally {
      loading.value = false
    }
  }

  async function createKb(data: { name: string; description: string }) {
    const kb = await request<KbOverview>('/kbs', { method: 'POST', body: JSON.stringify(data) })
    await fetchKbs()
    currentKbId.value = kb.id
    return kb
  }

  async function deleteKb(id: string) {
    await request(`/kbs/${id}`, { method: 'DELETE' })
    if (currentKbId.value === id) currentKbId.value = null
    if (learnKbId.value === id) learnKbId.value = null
    await Promise.all([fetchKbs(), fetchBuiltinStatus()])
  }

  async function fetchBuiltinStatus() {
    try {
      builtinStatus.value = await request<BuiltinKbStatus>('/kbs/builtin')
    } catch {
      // 老后端 / 离线时静默：不阻塞知识库主流程
      builtinStatus.value = null
    }
  }

  async function restoreBuiltin() {
    const kb = await request<KbOverview>('/kbs/builtin/restore', { method: 'POST' })
    await Promise.all([fetchKbs(), fetchBuiltinStatus()])
    if (!currentKbId.value) currentKbId.value = kb.id
    return kb
  }

  return {
    kbs,
    currentKbId,
    currentKb,
    learnKbId,
    learnKb,
    activeLearnKbId,
    loading,
    builtinStatus,
    fetchKbs,
    fetchBuiltinStatus,
    restoreBuiltin,
    createKb,
    deleteKb,
  }
})