<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useStudyStore } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = withDefaults(defineProps<{ learn?: boolean }>(), { learn: false })

const kbs = useKbsStore()
const study = useStudyStore()
const route = useRoute()
const open = ref(false)
const rootEl = ref<HTMLDivElement | null>(null)

/** 学习模式使用独立记忆的知识库，切换不影响编辑模式。 */
const activeKbId = computed(() =>
  props.learn ? kbs.activeLearnKbId : kbs.currentKbId,
)
// 学习空间只列出开启学习模式的知识库；编辑模式展示全部
const visibleKbs = computed(() =>
  props.learn ? kbs.kbs.filter((k) => k.learning_enabled !== false) : kbs.kbs,
)
const current = computed(
  () => visibleKbs.value.find((k) => k.id === activeKbId.value) ?? null,
)

function toggle() {
  open.value = !open.value
}
function pick(id: string) {
  if (props.learn) {
    if (id !== kbs.activeLearnKbId) {
      kbs.learnKbId = id
      // StudyView 会自行重置学习状态；在设置 / Wiki 等共享页则需在这里重置，
      // 否则侧栏冷启动门禁会沿用上一个知识库的画像。
      if (route.name !== 'learn') {
        study.resetForKb()
        void study.loadProfile()
      }
    }
  } else {
    kbs.currentKbId = id
  }
  open.value = false
}

// 点击外部关闭
function onDocClick(e: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(e.target as Node)) {
    open.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="rootEl" class="relative">
    <!-- 触发器 -->
    <button
      class="group flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-xl bg-white/70 border border-slate-200/70 shadow-soft hover:border-kiwi-200 hover:shadow-sm transition-all duration-200"
      @click="toggle"
    >
      <span class="w-4 h-4 grid place-items-center rounded-md bg-kiwi-100 text-kiwi-600 shrink-0">
        <KiwiIcon name="wiki" :size="10" />
      </span>
      <span class="text-sm text-slate-700 max-w-[10rem] truncate">
        {{ current?.name ?? '选择知识库' }}
      </span>
      <span
        class="px-1.5 py-0.5 rounded-md bg-slate-100 text-[10px] font-medium text-slate-500 whitespace-nowrap"
      >
        {{ current?.wiki_count ?? 0 }} wiki
      </span>
      <KiwiIcon
        name="chevron"
        :size="13"
        class="text-slate-400 transition-transform duration-200"
        :class="open ? 'rotate-180' : 'group-hover:translate-y-px'"
      />
    </button>

    <!-- 浮动面板 -->
    <Transition
      enter-active-class="transition-all duration-200 ease-spring"
      enter-from-class="opacity-0 -translate-y-1.5 scale-95"
      leave-active-class="transition-all duration-150"
      leave-to-class="opacity-0 -translate-y-1 scale-95"
    >
      <div
        v-if="open"
        class="absolute right-0 mt-2 w-72 max-h-80 overflow-y-auto rounded-2xl glass-strong p-2 shadow-lifted z-40"
      >
        <p class="px-3 py-1.5 text-[11px] text-slate-400 tracking-wide">切换知识空间</p>
        <button
          v-for="k in visibleKbs"
          :key="k.id"
          class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all duration-150 hover:bg-white/70"
          :class="k.id === activeKbId ? 'bg-white/80 text-kiwi-700' : 'text-slate-600'"
          @click="pick(k.id)"
        >
          <span
            class="w-9 h-9 shrink-0 grid place-items-center rounded-xl font-semibold text-sm transition-colors"
            :class="
              k.id === activeKbId
                ? 'bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-glow'
                : 'bg-slate-100 text-slate-500'
            "
          >
            {{ k.name.slice(0, 1) }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium truncate">{{ k.name }}</span>
            <span class="block text-xs text-slate-400 truncate">
              {{ k.source_count }} 素材 · {{ k.wiki_count }} Wiki · {{ k.note_count }} 笔记
            </span>
          </span>
          <KiwiIcon v-if="k.id === activeKbId" name="check" :size="14" class="text-kiwi-500 shrink-0" />
        </button>

        <div v-if="!visibleKbs.length" class="px-3 py-4 text-center text-sm text-slate-400">
          {{ learn ? '暂无开启学习模式的知识库' : '暂无知识库' }}
        </div>
      </div>
    </Transition>
  </div>
</template>