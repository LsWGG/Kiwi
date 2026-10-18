<script setup lang="ts">
/** 通用确认弹层。 */
import KiwiIcon from './KiwiIcon.vue'

withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    message?: string
    confirmText?: string
    danger?: boolean
  }>(),
  { title: '确认操作', message: '', confirmText: '确认', danger: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm'): void
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="modelValue"
        class="fixed inset-0 z-[90] grid place-items-center bg-slate-900/25 backdrop-blur-sm p-4"
        @mousedown.self="emit('update:modelValue', false)"
      >
        <div class="w-full max-w-sm rounded-2xl bg-white/95 backdrop-blur-xl border border-white/70 shadow-lifted p-5 animate-fade-up">
          <div class="flex items-start gap-3">
            <div
              class="w-9 h-9 shrink-0 rounded-xl grid place-items-center"
              :class="danger ? 'bg-rose-50 text-rose-500' : 'bg-kiwi-50 text-kiwi-500'"
            >
              <KiwiIcon :name="danger ? 'alert' : 'check'" :size="17" />
            </div>
            <div class="min-w-0">
              <h3 class="text-sm font-semibold text-slate-800">{{ title }}</h3>
              <p v-if="message" class="text-xs text-slate-500 mt-1 leading-relaxed">{{ message }}</p>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-5">
            <button class="kiwi-btn-secondary !py-1.5" @click="emit('update:modelValue', false)">
              取消
            </button>
            <button
              :class="danger ? 'kiwi-btn-danger !py-1.5' : 'kiwi-btn-primary !py-1.5'"
              @click="emit('confirm'); emit('update:modelValue', false)"
            >
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
