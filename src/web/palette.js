
/* ============ 命令面板（Ctrl+K） ============
   为什么要有：侧栏能放的东西有限，工具越多，"那个开关在哪"的成本越高。
   命令面板把「翻三级菜单找一个开关」压成「打三个字」。

   无障碍照 W3C APG 的 combobox 模式做，而不是逐项 tabindex：
   焦点**永远留在输入框**，当前项用 aria-activedescendant 指过去。
   好处是列表重绘（每敲一个字都会）不会丢焦点，也不用管 Tab 顺序。

   按键归属：Ctrl/Cmd+K 在 ChatGPT、Claude、VS Code、Linear 都是这个面板，
   本项目之前把它占成了「新对话」——迁移过来的人按下去会得到上下文被切走。
   现在让位给面板，新对话改 Ctrl+Shift+O（见 side.js 与快捷键表）。 */
(function(){
  /* 命令清单。group 决定分组与排序，keywords 是额外的口语词——
     用户不会记得按钮叫什么，只会记得「那个能导出对话的」。
     `动态` 标记的项每次打开重新求值（会话列表会变）。 */
  var state={open:false, q:'', items:[], idx:-1};
  var mask=null, panel=null, input=null, list=null, optSeq=0;
  var lastFocus=null;

  function $(id){ return document.getElementById(id); }
  function esc2(s){ return window.esc?window.esc(s):String(s==null?'':s); }

  function staticCommands(){
    var isDark=document.documentElement.getAttribute('data-theme')==='dark';
    var inAsk=document.body.classList.contains('page-ask');
    var out=[
      {id:'new-chat', group:'动作', title:'新对话', desc:'Ctrl+Shift+O',
       keywords:'新建 清空 开一个', run:function(){
         var b=$('newChat');
         if(b) b.click(); else location.href='/ask?new=1';
       }},
      {id:'goto-ask', group:'前往', title:'问答', desc:'/ask', keywords:'聊天 提问 首页',
       run:function(){ location.href='/ask'; }},
      {id:'goto-kb', group:'前往', title:'知识库', desc:'/kb', keywords:'文档 索引 版本',
       run:function(){ location.href='/kb'; }},
      {id:'goto-notes', group:'前往', title:'笔记', desc:'/notes', keywords:'记录 附件',
       run:function(){ location.href='/notes'; }},
      {id:'goto-report', group:'前往', title:'汇报', desc:'/report', keywords:'统计 用量 报告',
       run:function(){ location.href='/report'; }},
      /* 导出 / 清空 / 重命名只在问答页有意义：别的页面没有「当前对话」 */
      {id:'export', group:'当前对话', title:'导出为 Markdown', desc:'把这一轮对话存成文件',
       keywords:'下载 保存 md', hidden:!inAsk,
       run:function(){ var b=$('exportMd'); if(b) b.click(); }},
      {id:'clear', group:'当前对话', title:'清空对话', desc:'10 秒内可撤销',
       keywords:'删除 重置 新开', hidden:!inAsk,
       run:function(){ var b=$('clear'); if(b) b.click(); }},
      {id:'rename', group:'当前对话', title:'重命名对话', desc:'也可以双击侧栏标题',
       keywords:'改名 标题', hidden:!inAsk||!window.JY,
       run:function(){ if(window.JY) JY.rename(); }},
      {id:'settings', group:'设置', title:'打开设置', desc:'接口、存储、对话、安装',
       keywords:'配置 选项 参数 key', run:function(){
         if(window.__openSettings) window.__openSettings(); else if($('setBtn')) $('setBtn').click();
       }},
      {id:'theme', group:'设置', title:isDark?'切换到浅色':'切换到深色',
       desc:'跟随系统以外的手动切换', keywords:'外观 主题 暗色 亮色',
       run:function(){ var b=$('themeToggle'); if(b) b.click(); }},
      {id:'kbd', group:'设置', title:'快捷键一览', desc:'? 或 F1',
       keywords:'帮助 键盘 按键', run:function(){
         document.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true}));
       }},
    ];
    return out.filter(function(c){ return !c.hidden; });
  }

  /* 会话也算命令：「打开那条问过起购金额的对话」比去侧栏翻更快。
     复用侧栏已经拿到的列表（含正文摘要），不额外请求。 */
  function threadCommands(){
    if(!window.JY||!JY.list) return [];
    return JY.list().slice(0,40).map(function(t){
      return {id:'thread:'+t.id, group:'会话', title:t.title||'新对话',
              desc:(t.text||'').slice(0,60), keywords:t.text||'',
              run:function(){
                document.dispatchEvent(new CustomEvent('jy:thread',{detail:t.id}));
              }};
    });
  }

  function allCommands(){
    return staticCommands().concat(threadCommands());
  }

  function matches(cmd,q){
    if(!q) return true;
    var hay=((cmd.title||'')+' '+(cmd.desc||'')+' '+(cmd.keywords||'')).toLowerCase();
    // 多个词按「全都要出现」匹配，空格分隔：`导出 mark` 也能中
    return q.toLowerCase().split(/\s+/).every(function(w){
      return !w||hay.indexOf(w)>=0;
    });
  }

  function build(){
    if(panel) return;
    mask=document.createElement('div'); mask.className='pal-mask'; mask.hidden=true;
    panel=document.createElement('div'); panel.className='pal'; panel.hidden=true;
    panel.setAttribute('role','dialog');
    panel.setAttribute('aria-modal','true');
    panel.setAttribute('aria-label','命令面板');
    panel.innerHTML=
      '<div class="pal-head">'
      +'<span class="pal-ic" aria-hidden="true">'
      +'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/></svg>'
      +'</span>'
      +'<input id="palInput" type="text" role="combobox" autocomplete="off" spellcheck="false"'
      +' aria-expanded="true" aria-controls="palList" aria-autocomplete="list"'
      +' aria-label="搜索命令或对话" placeholder="搜索命令或对话…">'
      +'<kbd class="pal-esc">Esc</kbd>'
      +'</div>'
      +'<div class="pal-list" id="palList" role="listbox" aria-label="命令列表"></div>'
      +'<div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>'
      +'<span><kbd>Enter</kbd> 执行</span>'
      +'<span class="pal-note" id="palNote"></span></div>';
    document.body.appendChild(mask); document.body.appendChild(panel);
    input=panel.querySelector('#palInput');
    list=panel.querySelector('#palList');
    mask.addEventListener('click',close);
    input.addEventListener('input',function(){ state.q=input.value; render(); });
    input.addEventListener('keydown',onKey);
  }

  function render(){
    var q=(state.q||'').trim();
    var matched=allCommands().filter(function(c){ return matches(c,q); });
    state.items=matched;
    state.idx=matched.length?0:-1;
    var html='', lastGroup=null;
    matched.forEach(function(c,i){
      if(c.group!==lastGroup){
        html+='<div class="pal-group" role="presentation">'+esc2(c.group)+'</div>';
        lastGroup=c.group;
      }
      html+='<div class="pal-item'+(i===state.idx?' on':'')+'" id="pal-opt-'+i+'" '
        +'role="option" aria-selected="'+(i===state.idx?'true':'false')+'" '
        +'data-i="'+i+'">'
        +'<span class="pi-title">'+esc2(c.title)+'</span>'
        +(c.desc?'<span class="pi-desc">'+esc2(c.desc)+'</span>':'')
        +'</div>';
    });
    if(!matched.length){
      html='<div class="pal-empty">没有匹配的命令。换个词试试，比如「设置」「导出」。</div>';
    }
    list.innerHTML=html;
    var note=$('palNote');
    if(note) note.textContent=matched.length?(matched.length+' 项'):'';
    syncActive();
  }

  function syncActive(){
    var items=list.querySelectorAll('.pal-item');
    for(var i=0;i<items.length;i++){
      var on=i===state.idx;
      items[i].classList.toggle('on',on);
      items[i].setAttribute('aria-selected',on?'true':'false');
    }
    if(state.idx>=0&&items[state.idx]){
      // activedescendant 指向它：焦点没动，但读屏会念这一项
      input.setAttribute('aria-activedescendant','pal-opt-'+state.idx);
      try{ items[state.idx].scrollIntoView({block:'nearest'}); }catch(e){}
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  function move(delta){
    if(!state.items.length) return;
    var n=state.items.length;
    state.idx=((state.idx+delta)%n+n)%n;   // 循环：到底再按下回到第一条
    syncActive();
  }

  function select(){
    var cmd=state.items[state.idx];
    if(!cmd) return;
    close();
    /* 先关再执行，且**等一拍**：关闭会把焦点还给打开前的元素（trapFocus 用
       setTimeout(0) 做这件事），而「重命名」这类命令自己就要移焦到输入框。
       同步执行的话，还焦会晚一步把光标从刚出现的输入框里抢走。 */
    setTimeout(function(){
      try{ cmd.run(); }catch(e){ if(window.toast) toast('命令执行失败：'+(e&&e.message||e),true); }
    },0);
  }

  function onKey(e){
    if(e.key==='ArrowDown'){ e.preventDefault(); move(1); return; }
    if(e.key==='ArrowUp'){ e.preventDefault(); move(-1); return; }
    if(e.key==='Enter'){ e.preventDefault(); select(); return; }
    if(e.key==='Escape'){ e.preventDefault(); e.stopPropagation(); close(); return; }
    if(e.key==='Tab'){ e.preventDefault(); }   // 面板里只有一个可聚焦元素，Tab 没意义
  }

  function open(){
    build();
    if(state.open) return;
    state.open=true;
    lastFocus=document.activeElement;
    mask.hidden=false; panel.hidden=false;
    input.value=''; state.q=''; state.idx=-1;
    render();
    openOverlay('palette', panel);
    setTimeout(function(){ try{ input.focus(); }catch(e){} },0);
  }

  function close(){
    if(!state.open) return;
    state.open=false;
    closeOverlay('palette');
    if(panel) panel.hidden=true;
    if(mask) mask.hidden=true;
    state.items=[]; state.idx=-1;
    // 还焦交给 trapFocus；这里只在它拿不到目标时兜一下
    if(lastFocus&&document.contains(lastFocus)){ try{ lastFocus.focus(); }catch(e){} }
  }

  function toggle(){ state.open?close():open(); }

  document.addEventListener('keydown',function(e){
    var meta=e.ctrlKey||e.metaKey;
    if(meta&&!e.shiftKey&&!e.altKey&&(e.key==='k'||e.key==='K')){
      /* 输入框里也接管：用户正在打字时按 Ctrl+K 是「我想找点东西」，
         而不是「往输入框里插一个字符」。 */
      e.preventDefault();
      toggle();
      return;
    }
    /* Esc 在捕获阶段就处理：只 stopPropagation 的话，事件根本到不了 input 上的
       keydown（捕获先于目标），面板反而关不掉；同时这也拦住侧栏的 Esc，
       免得关面板顺手把移动端抽屉一起关了。 */
    if(e.key==='Escape'&&state.open){ e.preventDefault(); e.stopPropagation(); close(); return; }
  },true);

  window.__palette={open:open, close:close, toggle:toggle, isOpen:function(){ return state.open; }};
})();
