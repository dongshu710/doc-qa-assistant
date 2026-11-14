
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

/* ---------- 快捷键总表 ----------
   快捷键原来只活在 title 属性里：Ctrl+K 写在新对话按钮上，Ctrl+Shift+F 写在文件按钮上，
   Ctrl+B 哪都没写。发现不了的快捷键等于没有。这里按 ? 或 F1 摊开一张表，
   表里的每一条都必须真在代码里绑过，否则就是另一种形式的骗人。 */
(function(){
  /* 只列这一页真正能用的：汇报页没有侧栏也没有输入框，
     把 Ctrl+K 列上去等于教用户按一个没反应的键。 */
  var rows=[];
  if(document.getElementById('newChat')){
    rows.push(['Ctrl / Cmd + K','新对话'],
              ['Ctrl / Cmd + B','收起或展开侧栏'],
              ['Ctrl / Cmd + Shift + F','打开笔记与附件']);
  }
  if(document.getElementById('q')){
    rows.push(['Enter','发送'],['Shift + Enter','换行']);
  }
  rows.push(['Esc','关闭当前浮层'],['? / F1','打开这张表']);
  var mask=null, panel=null;
  function close(){
    if(!panel) return;
    closeOverlay('kbd');
    panel.hidden=true; if(mask) mask.hidden=true;
  }
  function build(){
    mask=document.createElement('div'); mask.className='kbd-mask'; mask.hidden=true;
    panel=document.createElement('div'); panel.className='kbd-modal'; panel.hidden=true;
    panel.setAttribute('role','dialog'); panel.setAttribute('aria-modal','true');
    panel.setAttribute('aria-label','快捷键');
    panel.innerHTML='<div class="kbd-head"><b>快捷键</b>'
      +'<button type="button" class="kbd-x" aria-label="关闭">×</button></div>'
      +'<div class="kbd-body">'+rows.map(function(r){
          return '<div class="kbd-row"><kbd>'+r[0]+'</kbd><span>'+r[1]+'</span></div>';
        }).join('')+'</div>'
      +'<div class="kbd-foot">按 Esc 关闭</div>';
    document.body.appendChild(mask); document.body.appendChild(panel);
    mask.onclick=close;
    panel.querySelector('.kbd-x').onclick=close;
  }
  function toggle(){
    if(!panel) build();
    var open=!panel.hidden;
    if(open){ close(); return; }
    panel.hidden=false; mask.hidden=false;
    openOverlay('kbd');
  }
  document.addEventListener('keydown',function(e){
    var tag=(document.activeElement&&document.activeElement.tagName)||'';
    var typing=/^(INPUT|TEXTAREA|SELECT)$/.test(tag);
    // 在输入框里打问号是正常打字，不能弹窗
    if(e.key==='?'&&!typing&&!e.ctrlKey&&!e.metaKey){ e.preventDefault(); toggle(); return; }
    if(e.key==='F1'){ e.preventDefault(); toggle(); return; }
    if(e.key==='Escape'&&panel&&!panel.hidden&&isTopOverlay('kbd')){ close(); }
  });
})();
