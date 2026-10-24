// 轻量 icon 集：内联 SVG（24×24，stroke 风格）。
// 用法：<Icon name="database" class="w-4 h-4" />
const PATHS: Record<string, string[]> = {
  puzzle: [
    '<path d="M19.4 14.6a2 2 0 0 0 0-2.8l-.3-.3h1.4a1.5 1.5 0 0 0 0-3h-1.4l.3-.3a2 2 0 0 0-2.8-2.8l-.3.3V4.3a1.5 1.5 0 0 0-3 0v1.4l-.3-.3a2 2 0 0 0-2.8 2.8l.3.3H8.1a1.5 1.5 0 0 0 0 3h1.4l-.3.3a2 2 0 0 0 2.8 2.8l.3-.3v1.4a1.5 1.5 0 0 0 3 0v-1.4l.3.3a2 2 0 0 0 2.8 0Z"/>',
  ],
  database: [
    '<ellipse cx="12" cy="5" rx="9" ry="3"/>',
    '<path d="M3 5v14a9 3 0 0 0 18 0V5"/>',
    '<path d="M3 12a9 3 0 0 0 18 0"/>',
  ],
  cloud: [
    '<path d="M17.5 19a4.5 4.5 0 0 0 .5-8.98A6 6 0 0 0 6.2 9.1 4.5 4.5 0 0 0 6.5 19Z"/>',
  ],
  server: [
    '<rect x="2" y="3" width="20" height="8" rx="2"/>',
    '<rect x="2" y="13" width="20" height="8" rx="2"/>',
    '<line x1="6" y1="7" x2="6.01" y2="7"/>',
    '<line x1="6" y1="17" x2="6.01" y2="17"/>',
    '<line x1="10" y1="7" x2="18" y2="7"/>',
    '<line x1="10" y1="17" x2="18" y2="17"/>',
  ],
  router: [
    '<rect x="2" y="14" width="20" height="7" rx="2"/>',
    '<path d="M12 14V7"/>',
    '<path d="m8 7 4-4 4 4"/>',
    '<line x1="6" y1="17.5" x2="6.01" y2="17.5"/>',
    '<line x1="10" y1="17.5" x2="10.01" y2="17.5"/>',
  ],
  firewall: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<path d="M3 9h18M3 15h18"/>',
    '<path d="M9 3v6M15 9v6M9 15v6"/>',
  ],
  monitor: [
    '<rect x="2" y="3" width="20" height="14" rx="2"/>',
    '<line x1="8" y1="21" x2="16" y2="21"/>',
    '<line x1="12" y1="17" x2="12" y2="21"/>',
  ],
  switch: [
    '<rect x="2" y="8" width="20" height="9" rx="2"/>',
    '<path d="m7 5 3-3 3 3M17 5l-3-3-3 3"/>',
    '<line x1="6" y1="13" x2="6.01" y2="13"/>',
    '<line x1="10" y1="13" x2="10.01" y2="13"/>',
    '<line x1="14" y1="13" x2="14.01" y2="13"/>',
    '<line x1="18" y1="13" x2="18.01" y2="13"/>',
  ],
  storage: [
    '<ellipse cx="12" cy="5" rx="8" ry="3"/>',
    '<path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>',
    '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  ],
  layers: [
    '<polygon points="12 2 2 7 12 12 22 7 12 2"/>',
    '<polyline points="2 17 12 22 22 17"/>',
    '<polyline points="2 12 12 17 22 12"/>',
  ],
  file: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
  ],
  fileText: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
    '<line x1="8" y1="13" x2="16" y2="13"/>',
    '<line x1="8" y1="17" x2="13" y2="17"/>',
  ],
  /** 分页符：纸张 + 虚线 */
  pageBreak: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
    '<line x1="4" y1="14" x2="20" y2="14" stroke-dasharray="3 3"/>',
  ],
  /** 导入文档：带向下箭头的文件，与普通文档图标区分 */
  fileImport: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
    '<polyline points="9 12 12 15 15 12"/>',
    '<line x1="12" y1="9" x2="12" y2="15"/>',
  ],
  /** 置顶图钉 */
  pin: [
    '<path d="M12 17v5"/>',
    '<path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
  ],
  /** 下载文件：带向下箭头的便签纸（从系统下载到本地） */
  fileDown: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
    '<line x1="12" y1="11" x2="12" y2="17"/>',
    '<polyline points="9 14 12 17 15 14"/>',
  ],
  /** 导出文件：带向上箭头的文件，表示把内容导出为文件 */
  fileExport: [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>',
    '<polyline points="14 2 14 8 20 8"/>',
    '<line x1="12" y1="17" x2="12" y2="11"/>',
    '<polyline points="9 14 12 11 15 14"/>',
  ],
  wiki: [
    '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>',
    '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  ],
  note: [
    '<path d="M12 20h9"/>',
    '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  ],
  upload: [
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    '<polyline points="17 8 12 3 7 8"/>',
    '<line x1="12" y1="3" x2="12" y2="15"/>',
  ],
  chat: [
    '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  ],
  settings: [
    '<circle cx="12" cy="12" r="3"/>',
    '<path d="M19.4 13.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V20a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V4a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z"/>',
  ],
  search: [
    '<circle cx="11" cy="11" r="8"/>',
    '<line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  ],
  edit: [
    '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  ],
  learn: [
    '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>',
    '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  ],
  sparkle: [
    '<path d="M12 3l1.9 5.7 5.7 1.9-5.7 1.9L12 18.2l-1.9-5.7-5.7-1.9 5.7-1.9Z"/>',
    '<path d="M19 2l.7 2.1 2.1.7-2.1.7L19 7.6l-.7-2.1-2.1-.7 2.1-.7Z"/>',
  ],
  plus: ['<line x1="12" y1="5" x2="12" y2="19"/>', '<line x1="5" y1="12" x2="19" y2="12"/>'],
  copy: [
    '<rect x="9" y="9" width="12" height="12" rx="2"/>',
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  ],
  trash: [
    '<polyline points="3 6 5 6 21 6"/>',
    '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  ],
  close: ['<line x1="18" y1="6" x2="6" y2="18"/>', '<line x1="6" y1="6" x2="18" y2="18"/>'],
  send: ['<line x1="22" y1="2" x2="11" y2="13"/>', '<polygon points="22 2 15 22 11 13 2 9 22 2"/>'],
  refresh: [
    '<polyline points="23 4 23 10 17 10"/>',
    '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
  ],
  chevron: ['<polyline points="6 9 12 15 18 9"/>'],
  chevronLeft: ['<polyline points="15 18 9 12 15 6"/>'],
  clock: ['<circle cx="12" cy="12" r="9"/>', '<polyline points="12 7 12 12 15 14"/>'],
  chevronsDown: [
    '<polyline points="7 6 12 11 17 6"/>',
    '<polyline points="7 13 12 18 17 13"/>',
  ],
  chevronsUp: [
    '<polyline points="7 18 12 13 17 18"/>',
    '<polyline points="7 11 12 6 17 11"/>',
  ],
  at: [
    '<circle cx="12" cy="12" r="4"/>',
    '<path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.9 7.9"/>',
  ],
  smile: [
    '<circle cx="12" cy="12" r="9"/>',
    '<path d="M8 14s1.5 2 4 2 4-2 4-2"/>',
    '<line x1="9" y1="9" x2="9.01" y2="9"/>',
    '<line x1="15" y1="9" x2="15.01" y2="9"/>',
  ],
  arrowLeft: ['<line x1="19" y1="12" x2="5" y2="12"/>', '<polyline points="12 19 5 12 12 5"/>'],
  arrowRight: ['<line x1="5" y1="12" x2="19" y2="12"/>', '<polyline points="12 5 19 12 12 19"/>'],
  check: ['<polyline points="20 6 9 17 4 12"/>'],
  alert: [
    '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>',
    '<line x1="12" y1="9" x2="12" y2="13"/>',
    '<line x1="12" y1="17" x2="12.01" y2="17"/>',
  ],
  link2: [
    '<path d="M9 17H7A5 5 0 0 1 7 7h2"/>',
    '<path d="M15 7h2a5 5 0 1 1 0 10h-2"/>',
    '<line x1="8" y1="12" x2="16" y2="12"/>',
  ],
  external: [
    '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    '<polyline points="15 3 21 3 21 9"/>',
    '<line x1="10" y1="14" x2="21" y2="3"/>',
  ],
  globe: [
    '<circle cx="12" cy="12" r="9"/>',
    '<line x1="3" y1="12" x2="21" y2="12"/>',
    '<path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>',
  ],
  kebab: [
    '<circle cx="12" cy="5" r="1"/>',
    '<circle cx="12" cy="12" r="1"/>',
    '<circle cx="12" cy="19" r="1"/>',
  ],
  book: [
    '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>',
    '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  ],
  loader: [
    '<line x1="12" y1="2" x2="12" y2="6"/>',
    '<line x1="12" y1="18" x2="12" y2="22"/>',
    '<line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/>',
    '<line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/>',
    '<line x1="2" y1="12" x2="6" y2="12"/>',
    '<line x1="18" y1="12" x2="22" y2="12"/>',
    '<line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/>',
    '<line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/>',
  ],
  graph: [
    '<circle cx="18" cy="5" r="3"/>',
    '<circle cx="6" cy="12" r="3"/>',
    '<circle cx="18" cy="19" r="3"/>',
    '<line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>',
    '<line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
  ],
  expand: [
    '<polyline points="15 3 21 3 21 9"/>',
    '<polyline points="9 21 3 21 3 15"/>',
    '<line x1="21" y1="3" x2="14" y2="10"/>',
    '<line x1="3" y1="21" x2="10" y2="14"/>',
  ],
  shrink: [
    '<polyline points="4 14 10 14 10 20"/>',
    '<polyline points="20 10 14 10 14 4"/>',
    '<line x1="14" y1="10" x2="21" y2="3"/>',
    '<line x1="3" y1="21" x2="10" y2="14"/>',
  ],
  target: [
    '<circle cx="12" cy="12" r="10"/>',
    '<circle cx="12" cy="12" r="6"/>',
    '<circle cx="12" cy="12" r="2"/>',
  ],
  bookOpen: [
    '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>',
    '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  ],
  notebook: [
    '<rect x="4" y="3" width="16" height="18" rx="2"/>',
    '<line x1="8" y1="3" x2="8" y2="21"/>',
    '<path d="m12.5 9 3.5 3-3.5 3z"/>',
  ],
  shield: [
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  ],
  lock: [
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>',
    '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  ],
  unlock: [
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>',
    '<path d="M7 11V7a5 5 0 0 1 9.33-2.5"/>',
  ],
  folder: [
    '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  ],
  folderOpen: [
    '<path d="M6 14l1.45-2.9A2 2 0 0 1 9.24 10H22l-2.75 5.5A2 2 0 0 1 17.5 17H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v2"/>',
  ],
  chevronRight: ['<polyline points="9 18 15 12 9 6"/>'],
  table: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="3" y1="9" x2="21" y2="9"/>',
    '<line x1="3" y1="15" x2="21" y2="15"/>',
    '<line x1="9" y1="3" x2="9" y2="21"/>',
  ],
  kanban: [
    '<rect x="3" y="3" width="5" height="18" rx="1"/>',
    '<rect x="9.5" y="3" width="5" height="12" rx="1"/>',
    '<rect x="16" y="3" width="5" height="8" rx="1"/>',
  ],
  gallery: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<circle cx="8.5" cy="8.5" r="1.5"/>',
    '<polyline points="21 15 16 10 5 21"/>',
  ],
  calendar: [
    '<rect x="3" y="4" width="18" height="18" rx="2"/>',
    '<line x1="16" y1="2" x2="16" y2="6"/>',
    '<line x1="8" y1="2" x2="8" y2="6"/>',
    '<line x1="3" y1="10" x2="21" y2="10"/>',
  ],
  image: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<circle cx="8.5" cy="8.5" r="1.5"/>',
    '<polyline points="21 15 16 10 5 21"/>',
  ],
  paperclip: [
    '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  ],
  code: [
    '<polyline points="16 18 22 12 16 6"/>',
    '<polyline points="8 6 2 12 8 18"/>',
  ],
  play: ['<path d="M6 3l14 9-14 9V3z"/>'],
  terminal: [
    '<polyline points="4 17 10 11 4 5"/>',
    '<line x1="12" y1="19" x2="20" y2="19"/>',
  ],
  list: [
    '<line x1="8" y1="6" x2="21" y2="6"/>',
    '<line x1="8" y1="12" x2="21" y2="12"/>',
    '<line x1="8" y1="18" x2="21" y2="18"/>',
    '<line x1="3" y1="6" x2="3.01" y2="6"/>',
    '<line x1="3" y1="12" x2="3.01" y2="12"/>',
    '<line x1="3" y1="18" x2="3.01" y2="18"/>',
  ],
  listOrdered: [
    '<line x1="10" y1="6" x2="21" y2="6"/>',
    '<line x1="10" y1="12" x2="21" y2="12"/>',
    '<line x1="10" y1="18" x2="21" y2="18"/>',
    '<path d="M4 6h1v4"/>',
    '<path d="M4 10h2"/>',
    '<path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
  ],
  checkSquare: [
    '<polyline points="9 11 12 14 22 4"/>',
    '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  ],
  quote: [
    '<path d="M3 21c3 0 7-1 7-8V5c0-1.25-.75-2-2-2H4c-1.25 0-2 .75-2 2v6c0 1.25.75 2 2 2h3c0 3-1 5-4 6z"/>',
    '<path d="M15 21c3 0 7-1 7-8V5c0-1.25-.75-2-2-2h-4c-1.25 0-2 .75-2 2v6c0 1.25.75 2 2 2h3c0 3-1 5-4 6z"/>',
  ],
  bold: [
    '<path d="M6 4h8a4 4 0 0 1 0 8H6z"/>',
    '<path d="M6 12h9a4 4 0 0 1 0 8H6z"/>',
  ],
  italic: [
    '<line x1="19" y1="4" x2="10" y2="4"/>',
    '<line x1="14" y1="20" x2="5" y2="20"/>',
    '<line x1="15" y1="4" x2="9" y2="20"/>',
  ],
  underline: [
    '<path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"/>',
    '<line x1="4" y1="21" x2="20" y2="21"/>',
  ],
  strike: [
    '<line x1="4" y1="12" x2="20" y2="12"/>',
    '<path d="M17.5 7.5a5 5 0 0 0-9.4-1.5"/>',
    '<path d="M7 16.5a5 5 0 0 0 9.5 1"/>',
  ],
  highlight: [
    '<path d="M9 11l-6 6v3h9l3-3"/>',
    '<path d="M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
  ],
  undo: [
    '<polyline points="9 14 4 9 9 4"/>',
    '<path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
  ],
  redo: [
    '<polyline points="15 14 20 9 15 4"/>',
    '<path d="M4 20v-7a4 4 0 0 1 4-4h12"/>',
  ],
  columns: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="12" y1="3" x2="12" y2="21"/>',
  ],
  alignLeft: [
    '<line x1="21" y1="6" x2="3" y2="6"/>',
    '<line x1="15" y1="12" x2="3" y2="12"/>',
    '<line x1="17" y1="18" x2="3" y2="18"/>',
  ],
  alignCenter: [
    '<line x1="21" y1="6" x2="3" y2="6"/>',
    '<line x1="17" y1="12" x2="7" y2="12"/>',
    '<line x1="19" y1="18" x2="5" y2="18"/>',
  ],
  alignRight: [
    '<line x1="21" y1="6" x2="3" y2="6"/>',
    '<line x1="21" y1="12" x2="9" y2="12"/>',
    '<line x1="21" y1="18" x2="7" y2="18"/>',
  ],
  star: [
    '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  ],
  hash: [
    '<line x1="4" y1="9" x2="20" y2="9"/>',
    '<line x1="4" y1="15" x2="20" y2="15"/>',
    '<line x1="10" y1="3" x2="8" y2="21"/>',
    '<line x1="16" y1="3" x2="14" y2="21"/>',
  ],
  filter: [
    '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  ],
  sort: [
    '<path d="m21 16-4 4-4-4"/>',
    '<path d="M17 20V4"/>',
    '<path d="m3 8 4-4 4 4"/>',
    '<path d="M7 4v16"/>',
  ],
  arrowUp: ['<line x1="12" y1="19" x2="12" y2="5"/>', '<polyline points="5 12 12 5 19 12"/>'],
  arrowDown: ['<line x1="12" y1="5" x2="12" y2="19"/>', '<polyline points="19 12 12 19 5 12"/>'],
  arrowUpRight: [
    '<line x1="7" y1="17" x2="17" y2="7"/>',
    '<polyline points="7 7 17 7 17 17"/>',
  ],
  maximize: [
    '<path d="M8 3H5a2 2 0 0 0-2 2v3"/>',
    '<path d="M21 8V5a2 2 0 0 0-2-2h-3"/>',
    '<path d="M3 16v3a2 2 0 0 0 2 2h3"/>',
    '<path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  ],
  minimize: [
    '<path d="M8 3v3a2 2 0 0 1-2 2H3"/>',
    '<path d="M21 8h-3a2 2 0 0 1-2-2V3"/>',
    '<path d="M3 16h3a2 2 0 0 1 2 2v3"/>',
    '<path d="M16 21v-3a2 2 0 0 1 2-2h3"/>',
  ],
  pen: [
    '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    '<path d="m15 5 4 4"/>',
  ],
  eraser: [
    '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/>',
    '<path d="M22 21H7"/>',
    '<path d="m5 11 9 9"/>',
  ],
  square: ['<rect x="4" y="4" width="16" height="16" rx="2"/>'],
  circle: ['<circle cx="12" cy="12" r="9"/>'],
  /** 画布：菱形判断节点 */
  diamond: ['<path d="M12 2 22 12 12 22 2 12Z"/>'],
  /** 画布：选择工具 */
  cursor: ['<path d="M3 3l7.5 18 2.6-7.9L21 10.5Z"/>'],
  /** 画布：文本工具 */
  type: [
    '<polyline points="4 7 4 4 20 4 20 7"/>',
    '<line x1="9" y1="20" x2="15" y2="20"/>',
    '<line x1="12" y1="4" x2="12" y2="20"/>',
  ],
  /** 画布：抓手工具 */
  hand: [
    '<path d="M18 11V6a2 2 0 0 0-4 0v5"/>',
    '<path d="M14 10V4a2 2 0 0 0-4 0v6"/>',
    '<path d="M10 10.5V6a2 2 0 0 0-4 0v8"/>',
    '<path d="M18 8a2 2 0 0 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
  ],
  /** 画布：模板 */
  layoutTemplate: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="3" y1="9" x2="21" y2="9"/>',
    '<line x1="9" y1="9" x2="9" y2="21"/>',
  ],
  /** 画布：主题 / 调色板 */
  palette: [
    '<circle cx="13.5" cy="6.5" r="1"/>',
    '<circle cx="17.5" cy="10.5" r="1"/>',
    '<circle cx="8.5" cy="7.5" r="1"/>',
    '<circle cx="6.5" cy="12.5" r="1"/>',
    '<path d="M12 2a10 10 0 0 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.2 0-1.1.9-2 2-2h2.3A4.7 4.7 0 0 0 22 10.8 10 10 0 0 0 12 2z"/>',
  ],
  /** 画布：智能吸附 */
  magnet: [
    '<path d="M6 15V6a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v6"/>',
    '<path d="M13 12V6a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v9a5 5 0 0 1-10 0"/>',
    '<line x1="6" y1="8" x2="11" y2="8"/>',
    '<line x1="13" y1="8" x2="18" y2="8"/>',
  ],
  grip: [
    '<circle cx="9" cy="6" r="1"/>',
    '<circle cx="15" cy="6" r="1"/>',
    '<circle cx="9" cy="12" r="1"/>',
    '<circle cx="15" cy="12" r="1"/>',
    '<circle cx="9" cy="18" r="1"/>',
    '<circle cx="15" cy="18" r="1"/>',
  ],
  download: [
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    '<polyline points="7 10 12 15 17 10"/>',
    '<line x1="12" y1="15" x2="12" y2="3"/>',
  ],
  bot: [
    '<rect x="3" y="8" width="18" height="12" rx="3"/>',
    '<path d="M12 8V4"/>',
    '<circle cx="12" cy="3" r="1"/>',
    '<circle cx="8.5" cy="14" r="1"/>',
    '<circle cx="15.5" cy="14" r="1"/>',
  ],
  minus: ['<line x1="5" y1="12" x2="19" y2="12"/>'],
  panelLeft: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="9" y1="3" x2="9" y2="21"/>',
  ],
  panelLeftClose: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="9" y1="3" x2="9" y2="21"/>',
    '<polyline points="16 9 13 12 16 15"/>',
  ],
  panelLeftOpen: [
    '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    '<line x1="9" y1="3" x2="9" y2="21"/>',
    '<polyline points="13 9 16 12 13 15"/>',
  ],
  video: [
    '<rect x="2" y="5" width="14" height="14" rx="2"/>',
    '<polygon points="22 7 16 11 16 13 22 17 22 7"/>',
  ],
  scanText: [
    '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>',
    '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>',
    '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>',
    '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
    '<line x1="7" y1="9" x2="17" y2="9"/>',
    '<line x1="7" y1="13" x2="17" y2="13"/>',
    '<line x1="7" y1="17" x2="13" y2="17"/>',
  ],
  eye: [
    '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/>',
    '<circle cx="12" cy="12" r="3"/>',
  ],
  listTree: [
    '<line x1="8" y1="6" x2="21" y2="6"/>',
    '<line x1="8" y1="12" x2="21" y2="12"/>',
    '<line x1="8" y1="18" x2="21" y2="18"/>',
    '<line x1="3" y1="6" x2="3.01" y2="6"/>',
    '<line x1="3" y1="12" x2="3.01" y2="12"/>',
    '<line x1="3" y1="18" x2="3.01" y2="18"/>',
  ],
  keyboard: [
    '<rect x="2" y="5" width="20" height="14" rx="2"/>',
    '<path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 12.5h.01M10 12.5h.01M14 12.5h.01M18 12.5h.01"/>',
    '<path d="M8 16h8"/>',
  ],
  trendingUp: [
    '<polyline points="3 17 9 11 13 15 21 7"/>',
    '<polyline points="15 7 21 7 21 13"/>',
  ],
  bell: [
    '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>',
    '<path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  ],
  smartphone: [
    '<rect x="5" y="2" width="14" height="20" rx="2"/>',
    '<line x1="12" y1="18" x2="12.01" y2="18"/>',
  ],
  mic: [
    '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>',
    '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>',
    '<line x1="12" y1="19" x2="12" y2="23"/>',
    '<line x1="8" y1="23" x2="16" y2="23"/>',
  ],
}

export function iconSVG(name: string): string {
  const paths = PATHS[name]
  if (!paths) return ''
  return paths.join('')
}