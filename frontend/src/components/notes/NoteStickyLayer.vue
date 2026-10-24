<script setup lang="ts">
/** 「贴一贴」浮窗层：挂在 App 根部，跨路由保留，可同时打开多个便签。 */
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useStickyNotesStore } from '@/stores/stickyNotes'
import NoteStickyWindow from './NoteStickyWindow.vue'

const sticky = useStickyNotesStore()

// 有便签时预取笔记工作区：打开主窗口的展开动画需要新页面尽早进场，
// 否则懒加载期间会先露出一段空白纸面。
let workspacePreloaded = false
watch(
  () => sticky.windows.length,
  (count) => {
    if (!count || workspacePreloaded) return
    workspacePreloaded = true
    void import('@/views/edit/NotesWorkspaceView.vue')
  },
  { immediate: true },
)

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
