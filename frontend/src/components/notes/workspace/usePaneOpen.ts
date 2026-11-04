/**
 * 从嵌入内容 / 目录 / @ 提及打开分栏窗口的共用入口。
 *
 * 分栏未开启时以当前笔记为第一栏自动进入；窄屏沿用工作区的挂起策略，
 * 直接提示而不改动布局。
 */
import { useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore } from '@/stores/notes'
import { useNotePanesStore } from '@/stores/notePanes'
import { toast } from '@/components/ui/toast'

export function usePaneOpen() {
  const router = useRouter()
  const kbs = useKbsStore()
  const notes = useNotesStore()
  const panes = useNotePanesStore()

  function isNarrow() {
    return window.matchMedia('(max-width: 767px)').matches
  }

  /** 确保分栏开启；没有布局时以当前笔记起一栏。 */
  function ensureEnabled(kbId: string): boolean {
    if (isNarrow()) {
      toast.info('窄屏不支持分栏，请加宽窗口后重试')
      return false
    }
    if (!panes.enabled || !panes.root) {
      panes.enter(kbId, notes.currentNote?.id ?? null)
    }
    if (!panes.enabled) return false
    return true
  }

  function openNotePane(noteId: string, kbId?: string): boolean {
    const targetKb = kbId || kbs.currentKbId
    if (!targetKb) return false
    if (!ensureEnabled(targetKb)) return false
    if (kbs.currentKbId !== targetKb) kbs.currentKbId = targetKb
    panes.openNote(targetKb, noteId)
    if (notes.currentNote?.id !== noteId) {
      void router.push({ name: 'notes', params: { id: noteId }, query: {} })
    }
    return true
  }

  function openUrlPane(target: { url: string; title: string; site?: string }): boolean {
    if (!kbs.currentKbId || !ensureEnabled(kbs.currentKbId)) return false
    panes.openUrl(target)
    return true
  }

  function openFilePane(target: {
    url: string
    filename: string
    contentType: string
    size?: number
  }): boolean {
    if (!kbs.currentKbId || !ensureEnabled(kbs.currentKbId)) return false
    panes.openFile(target)
    return true
  }

  return { openNotePane, openUrlPane, openFilePane }
}
