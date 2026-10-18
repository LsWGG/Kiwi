/** HTML / JS 代码块的渲染文档：统一给正文内嵌与弹层预览使用。 */

/**
 * 预览页与父页面之间的桥：
 * - Esc 通知父页面关闭弹层（正文内嵌时无副作用）
 * - 上报正文高度，父页面据此自适应 iframe 高度
 */
export const PREVIEW_BRIDGE_SCRIPT = `<script>
(function(){
  function report(){
    try {
      var b=document.body;
      if(!b) return;
      var cs=getComputedStyle(b);
      var rect=b.getBoundingClientRect();
      // 取实际绘制底边（含外边距折叠造成的偏移），html.scrollHeight 不能用于收缩
      var h=Math.max(b.offsetHeight,b.scrollHeight,rect.bottom+(window.scrollY||0));
      h += parseFloat(cs.marginBottom)||0;
      parent.postMessage({type:'kiwi-code-preview-height',height:Math.ceil(h)+2},'*');
    } catch(_){}
  }
  window.addEventListener('load',report);
  window.addEventListener('resize',report);
  setTimeout(report,50);
  setTimeout(report,300);
  if (window.ResizeObserver) {
    try {
      var ro=new ResizeObserver(report);
      ro.observe(document.documentElement);
      if(document.body) ro.observe(document.body);
      var box=document.getElementById('__kiwi_console');
      if(box) ro.observe(box);
    } catch(_){}
  }
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){try{parent.postMessage('kiwi-code-run-close','*')}catch(_){}}
  });
})();
<\/script>`

/** 兼容旧命名。 */
export const PREVIEW_ESCAPE_SCRIPT = PREVIEW_BRIDGE_SCRIPT

/** JS 预览页：把 console 输出与运行时错误固定显示在底部。 */
export function jsPreviewDocument(code: string): string {
  const safe = code.replace(/<\/script/gi, '<\\/script')
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  html,body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#0f172a;background:#fff}
  body{padding:16px}
  #__kiwi_console{position:fixed;left:0;right:0;bottom:0;margin:0;max-height:45%;overflow:auto;background:#0f172a;color:#e2e8f0;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;padding:8px 12px;white-space:pre-wrap;display:none;z-index:2147483647}
  #__kiwi_console .err{color:#fca5a5}
  #__kiwi_console .warn{color:#fcd34d}
</style></head><body>
<pre id="__kiwi_console"></pre>
<script>
(function(){
  var box=document.getElementById('__kiwi_console');
  function line(kind,args){
    if(!box)return;
    var text=Array.prototype.map.call(args,function(v){
      if(typeof v==='string')return v;
      try{return JSON.stringify(v)}catch(e){return String(v)}
    }).join(' ');
    var el=document.createElement('div');
    if(kind==='error')el.className='err';
    if(kind==='warn')el.className='warn';
    el.textContent=(kind==='error'?'✖ ':kind==='warn'?'⚠ ':'')+text;
    box.appendChild(el);
    box.style.display='block';
    box.scrollTop=box.scrollHeight;
    // 预留固定控制台占用的高度，避免遮挡正文（等布局完成后再量）
    requestAnimationFrame(function(){
      document.body.style.paddingBottom=(box.offsetHeight+16)+'px';
    });
  }
  var log=console.log.bind(console), info=console.info.bind(console), warn=console.warn.bind(console);
  console.log=function(){line('log',arguments);log.apply(console,arguments)};
  console.info=function(){line('log',arguments);info.apply(console,arguments)};
  console.warn=function(){line('warn',arguments);warn.apply(console,arguments)};
  console.error=function(){line('error',arguments)};
  window.addEventListener('error',function(e){line('error',[e.message+(e.lineno?'（第 '+e.lineno+' 行）':'')])});
  window.addEventListener('unhandledrejection',function(e){line('error',['未处理的 Promise 错误：'+e.reason])});
})();
<\/script>
<script>${safe}<\/script>
${PREVIEW_BRIDGE_SCRIPT}
</body></html>`
}

export function buildPreviewDocument(language: 'html' | 'js', code: string): string {
  return language === 'html' ? code + PREVIEW_BRIDGE_SCRIPT : jsPreviewDocument(code)
}
