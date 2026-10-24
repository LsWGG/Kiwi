<script setup lang="ts">
/** 「贴一贴」浮窗层：挂在 App 根部，跨路由保留，可同时打开多个便签。 */
import { onBeforeUnmount, onMounted } from 'vue'
import { useStickyNotesStore } from '@/stores/stickyNotes'
import NoteStickyWindow from './NoteStickyWindow.vue'

const sticky = useStickyNotesStore()

// 浏览器窗口缩放 / 页面缩放后，把落在视口外的便签收回来。
const onResize = () => sticky.clampAll()
onMounted(() => {
  sticky.clampAll()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<template>
  <!-- 挂到 <html> 下：坐标使用视口像素，不受 body 的 --ui-scale zoom 影响。 -->
  <Teleport to="html">
    <NoteStickyWindow v-for="win in sticky.windows" :key="win.id" :win="win" />
  </Teleport>
</template>
