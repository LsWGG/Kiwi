<script setup lang="ts">
import { computed, ref } from 'vue'
import { useModeStore } from '@/stores/mode'
import { useKbsStore } from '@/stores/kbs'
import { useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const mode = useModeStore()
const kbs = useKbsStore()
const router = useRouter()

// README：空知识库 / 尚无 Wiki 页面 / 未开启学习模式时，学习模式入口可见但置灰。
const activeKb = computed(() =>
  mode.mode === 'learn'
    ? kbs.kbs.find((k) => k.id === kbs.activeLearnKbId) ?? null
    : kbs.currentKb,
)
/**
 * 仅记录的知识库没有学习入口，顶栏不再展示「编辑 / 学习」切换，
 * 避免给出一个永远不可用的控件。
 */
const hidden = computed(
  () => mode.mode === 'edit' && activeKb.value?.learning_enabled === false,
)
const locked = ref(false)
const hint = ref('')

function isLocked() {
  if (!activeKb.value) return true
  if (activeKb.value.learning_enabled === false) return true
  return (activeKb.value.wiki_count ?? 0) === 0
}

function whyLocked() {
  if (!activeKb.value) return '请先创建一个知识库并导入素材'
  if (activeKb.value.learning_enabled === false) {
    return '该知识库未开启学习模式，仅用于记录'
  }
  return '请先在编辑模式导入素材并完成编译'
}

let hintTimer: number | undefined
function showLockedHint() {
  locked.value = true
  hint.value = whyLocked()
  window.clearTimeout(hintTimer)
  hintTimer = window.setTimeout(() => {
    locked.value = false
    hint.value = ''
  }, 2800)
}

async function switchMode(m: 'edit' | 'learn') {
  if (m === 'learn' && mode.mode !== 'learn') {
    // 计数可能因刚才的编译而过期，锁定前刷新一次
    if (isLocked()) await kbs.fetchKbs()
    if (isLocked()) {
      showLockedHint()
      return
    }
  }
  mode.setMode(m)
  if (m === 'learn') router.push('/learn')
  else router.push('/kbs')
}

const opts = [
  { key: 'edit' as const, icon: 'edit', label: '编辑', activeCls: 'text-kiwi-700' },
  { key: 'learn' as const, icon: 'learn', label: '学习', activeCls: 'text-emerald-600' },
]

function optionLocked(key: 'edit' | 'learn') {
  return key === 'learn' && mode.mode !== 'learn' && isLocked()
}
</script>

<template>
  <div v-if="!hidden" class="relative">
    <div
      class="flex items-center gap-1 p-1 rounded-full bg-slate-100/70 border border-slate-200/70 backdrop-blur"
    >
      <!-- 滑胶背景 -->
      <span
        class="absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-full bg-white shadow-soft border border-slate-200/60 transition-all duration-300 ease-spring"
        :class="mode.mode === 'edit' ? 'left-1' : 'left-[calc(50%)]'"
      />
      <button
        v-for="o in opts"
        :key="o.key"
        class="relative z-[1] flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium transition-colors duration-200"
        :class="[
          mode.mode === o.key ? o.activeCls : 'text-slate-500 hover:text-slate-700',
          optionLocked(o.key) ? 'opacity-40 hover:text-slate-500' : '',
        ]"
        :title="optionLocked(o.key) ? whyLocked() : undefined"
        :aria-disabled="optionLocked(o.key) || undefined"
        @click="switchMode(o.key)"
      >
        <KiwiIcon :name="o.icon" :size="14" />
        {{ o.label }}
      </button>
    </div>

    <!-- 置灰提示气泡 -->
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div
        v-if="locked"
        class="absolute left-1/2 -translate-x-1/2 top-full mt-2 z-50 whitespace-nowrap rounded-lg bg-slate-800/95 text-white text-xs px-3 py-1.5 shadow-lg"
      >
        {{ hint }}
      </div>
    </Transition>
  </div>
</template>
