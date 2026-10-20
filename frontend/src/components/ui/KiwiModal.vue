<script setup lang="ts">
// KiwiModal：玻璃拟态弹窗。点遮罩关闭、Esc 关闭、motion-less 纯 Transition。
import { onMounted, onUnmounted } from 'vue'
import KiwiIcon from './KiwiIcon.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    maxW?: string
    closeOnMask?: boolean
  }>(),
  { open: false, closeOnMask: true, maxW: 'max-w-lg' },
)

const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-150"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 grid place-items-center px-4"
      >
        <!-- 遮罩 -->
        <div
          class="absolute inset-0 bg-slate-900/20 backdrop-blur-sm"
          @click="closeOnMask && emit('close')"
        />
        <!-- 面板 -->
        <div
          class="kiwi-modal-panel relative flex w-full flex-col rounded-2xl glass-strong p-6 shadow-lifted animate-scale-in"
          :class="maxW"
        >
          <div v-if="title" class="mb-4 flex shrink-0 items-center justify-between gap-3">
            <h2 class="text-lg font-semibold text-slate-800">{{ title }}</h2>
            <button class="kiwi-btn-ghost !p-1.5" @click="emit('close')">
              <KiwiIcon name="close" :size="16" />
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-0.5">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>