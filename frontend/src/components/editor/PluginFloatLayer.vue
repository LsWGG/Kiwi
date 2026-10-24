<script setup lang="ts">
/** 组件插件置顶窗口层：挂在 App 根部，跨路由保留。 */
import { onBeforeUnmount, onMounted } from 'vue'
import { usePluginWindowsStore } from '@/stores/pluginWindows'
import PluginFloatWindow from './PluginFloatWindow.vue'

const pluginWindows = usePluginWindowsStore()

const onResize = () => pluginWindows.clampAll()
onMounted(() => {
  pluginWindows.clampAll()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<template>
  <!-- 挂到 <html> 下：坐标使用视口像素，不受 body 的 --ui-scale zoom 影响。 -->
  <Teleport to="html">
    <PluginFloatWindow v-for="win in pluginWindows.windows" :key="win.id" :win="win" />
  </Teleport>
</template>
