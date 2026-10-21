<script setup lang="ts">
/** 访问令牌登录页：仅在服务端启用 KIWI_ACCESS_TOKEN 时出现。 */
import { nextTick, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiLogo from '@/components/ui/KiwiLogo.vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{ (e: 'success'): void }>()
const auth = useAuthStore()
const token = ref('')
const error = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

onMounted(() => {
  void nextTick(() => inputRef.value?.focus())
})

async function submit() {
  if (auth.loggingIn) return
  const value = token.value.trim()
  if (!value) {
    error.value = '请输入访问令牌'
    inputRef.value?.focus()
    return
  }
  error.value = ''
  try {
    await auth.login(value)
    token.value = ''
    emit('success')
  } catch (e: any) {
    error.value = e.message || '访问令牌不正确'
    token.value = ''
    inputRef.value?.focus()
  }
}
</script>

<template>
  <div class="relative grid min-h-full place-items-center overflow-hidden px-6 py-12">
    <!-- 与主界面一致的柔光背景 -->
    <div class="pointer-events-none absolute inset-0 -z-10">
      <div class="absolute -left-32 -top-24 h-96 w-96 rounded-full bg-kiwi-300/30 blur-3xl" />
      <div class="absolute -bottom-28 -right-24 h-[28rem] w-[28rem] rounded-full bg-sky-300/25 blur-3xl" />
      <div class="absolute left-1/2 top-1/3 h-72 w-72 -translate-x-1/2 rounded-full bg-fuchsia-200/20 blur-3xl" />
    </div>

    <form
      class="w-full max-w-sm rounded-2xl glass-strong p-7 shadow-lifted animate-scale-in"
      @submit.prevent="submit"
    >
      <div class="flex flex-col items-center text-center">
        <KiwiLogo mode="edit" :size="56" class="rounded-2xl shadow-glow" />
        <h1 class="mt-4 text-xl font-semibold tracking-wide text-slate-800">Kiwi</h1>
        <p class="mt-1 text-xs text-slate-400">该实例已开启访问控制，请输入访问令牌</p>
      </div>

      <label class="mt-6 block text-[11px] font-medium text-slate-500" for="access-token">
        访问令牌
      </label>
      <input
        id="access-token"
        ref="inputRef"
        v-model="token"
        type="password"
        autocomplete="current-password"
        class="kiwi-input mt-1.5 w-full"
        placeholder="由管理员在部署配置中设置"
        :disabled="auth.loggingIn"
      />
      <p v-if="error" class="mt-2 text-[11.5px] text-rose-500">{{ error }}</p>

      <button type="submit" class="kiwi-btn-primary mt-4 w-full justify-center" :disabled="auth.loggingIn">
        <KiwiIcon :name="auth.loggingIn ? 'loader' : 'unlock'" :size="14" :spin="auth.loggingIn" />
        {{ auth.loggingIn ? '验证中…' : '进入工作区' }}
      </button>
      <p class="mt-3 text-center text-[10.5px] leading-relaxed text-slate-400">
        登录状态通过 HttpOnly Cookie 保存 30 天；清除浏览器 Cookie 后可切换令牌。
      </p>
    </form>
  </div>
</template>
