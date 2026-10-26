
(function(){
  var root=document.documentElement;
  var btn=document.getElementById('themeToggle');
  function current(){return root.getAttribute('data-theme')==='dark'?'dark':'light';}
  function apply(t){
    root.setAttribute('data-theme',t);
    try{ localStorage.setItem('rag_theme',t); }catch(e){}
    if(btn) btn.setAttribute('aria-label',t==='dark'?'切换到浅色模式':'切换到深色模式');
  }
  if(btn) btn.addEventListener('click',function(){ apply(current()==='dark'?'light':'dark'); });
})();

// 页面一加载就同步「储存对话内容」开关。
// 之前只在打开设置抽屉时才知道开关状态：开关明明是开的，「存为笔记」也要先点一次设置才出现，
// 用户会以为功能坏了（e2e 在干净环境里也正因此超时）。
(function(){
  if(!window.fetch) return;
  fetch('/api/settings').then(function(r){ return r.json(); }).then(function(d){
    if(d&&d.ok){ window.__storeChat=!!d.notes.store_chat; }
  }).catch(function(){});
})();
