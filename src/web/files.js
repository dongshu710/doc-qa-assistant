
/* ============ 最近文件（侧栏抽屉） ============
   这里只做「最近 5 篇 + 去完整页」，不再内嵌详情与编辑。
   完整能力（搜索、新建、删除、附件、导出）都在 /files。两套详情渲染器
   曾经各自维护，改一处漏一处；抽屉只负责让用户瞥一眼并跳过去。 */
(function(){
  var $=function(id){ return document.getElementById(id); };
  var panel=$('filesPanel'), mask=$('filesMask');
  if(!panel||!mask) return;

  var RECENT=5;

  function setBadge(n){
    n=Number(n)||0;
    var c=$('filesCount');
    if(c){ c.textContent=n>99?'99+':String(n); c.hidden=n<=0; }
    var t=$('filesTotal');
    if(t) t.textContent=n?('共 '+n+' 篇'):'';
  }

  function load(){
    var box=$('filesList');
    box.innerHTML='<p class="files-empty">加载中…</p>';
    fetch('/api/notes?limit='+RECENT,{headers:reqHeaders()}).then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      setBadge(d.count);
      var rows=d.items||[];
      if(!rows.length){
        box.innerHTML='<p class="files-empty">还没有笔记。</p>';
        return;
      }
      box.innerHTML='';
      rows.forEach(function(it){
        var b=document.createElement('button');
        b.type='button'; b.className='file-item';
        b.setAttribute('data-id',it.id);
        b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmtTime(it.created))+'</span>';
        box.appendChild(b);
      });
    }).catch(function(){
      box.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  // 红点属于「提醒」，不属于「数据」：点一下就该消失，且刷新后也别回来。
  // 用「上次导出时间」当签名——同一次未备份周期内只消一次，真导出过状态本来就会变。
  var DOT_KEY='rag_dot_off';
  function dotOff(){ try{ return localStorage.getItem(DOT_KEY)||''; }catch(e){ return ''; } }
  function dotSig(bk){ return String((bk&&bk.last_export_at)||'none'); }
  function renderBackup(bk){
    bk=bk||{};
    var dot=$('filesDot'), show=!!bk.due&&dotOff()!==dotSig(bk);
    if(dot){ dot.hidden=!show; dot.setAttribute('data-sig',dotSig(bk)); }
    if($('filesBackup')){
      $('filesBackup').textContent=bk.text?(bk.text+(bk.due?' · 建议导出一次':'')):'';
      $('filesBackup').className='files-note'+(bk.due?' err':'');
    }
  }
  // 设置面板也读同一份备份状态，红点的显示规则只能有一处，否则两边会打架
  window.__filesBackup=renderBackup;

  // 首屏与每次打开都同步一次数量/备份状态：存了新笔记再点进来，角标必须是最新的
  function refreshState(){
    fetch('/api/settings',{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok) return;
      setBadge(d.notes&&d.notes.count);
      renderBackup((d.notes&&d.notes.backup)||{});
    }).catch(function(){});
  }

  function open(){
    if(window.__closeSide) window.__closeSide();
    openOverlay('notesDrawer');
    panel.hidden=false; mask.hidden=false;
    if($('filesBtn')) $('filesBtn').setAttribute('aria-expanded','true');
    document.body.classList.add('set-open');
    requestAnimationFrame(function(){ panel.classList.add('on'); });
    refreshState();
    load();
    var first=panel.querySelector('.file-item')||$('filesClose');
    if(first) first.focus();
  }
  function close(){
    closeOverlay('notesDrawer');
    panel.classList.remove('on');
    panel.hidden=true; mask.hidden=true;
    if($('filesBtn')) $('filesBtn').setAttribute('aria-expanded','false');
    document.body.classList.remove('set-open');
    if($('filesBtn')) $('filesBtn').focus();
  }

  // 问答页存完一篇就刷新角标：否则用户得刷新页面才看得到入口上的数字变了
  var prevSaved=window.__noteSaved;
  window.__noteSaved=function(d){
    if(typeof prevSaved==='function') prevSaved(d);
    refreshState();
  };

  if($('filesBtn')) $('filesBtn').addEventListener('click',open);
  if($('filesClose')) $('filesClose').addEventListener('click',close);
  mask.addEventListener('click',close);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden&&isTopOverlay('notesDrawer')) close();
  });

  // 红点：点它只消提醒，不打开抽屉——「我知道了」和「我要看」是两个意图
  if($('filesDot')) $('filesDot').addEventListener('click',function(e){
    e.preventDefault(); e.stopPropagation();
    try{ localStorage.setItem(DOT_KEY, this.getAttribute('data-sig')||'none'); }catch(err){}
    this.hidden=true;
    if(window.toast) window.toast('已忽略这次备份提醒；下次有新内容还会提醒');
  });

  // Ctrl/Cmd+Shift+F 开合最近文件；在输入框里不抢按键（那里常按组合键选词）
  document.addEventListener('keydown',function(e){
    if(!(e.ctrlKey||e.metaKey)||!e.shiftKey||(e.key||'').toLowerCase()!=='f') return;
    var tag=(document.activeElement||{}).tagName;
    if(tag==='INPUT'||tag==='TEXTAREA') return;
    e.preventDefault();
    if(panel.hidden) open(); else close();
  });

  // 列表项带 id 跳完整页：抽屉里不再渲染详情，避免第二套渲染器
  if($('filesList')) $('filesList').addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    location.href='/notes?id='+encodeURIComponent(b.getAttribute('data-id'));
  });

  // 首屏就把数量与备份状态读出来：入口上的角标不该等打开抽屉才出现
  refreshState();
})();
