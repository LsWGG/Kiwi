/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 桌面构建（vite --mode desktop）为 '1'；Docker / Web 构建不设置。 */
  readonly VITE_KIWI_DESKTOP?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}