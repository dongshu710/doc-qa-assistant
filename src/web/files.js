
(function(){
  var $=function(id){ return document.getElementById(id); };
  var panel=$('filesPanel'), mask=$('filesMask');
  if(!panel||!mask) return;

  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function fmt(iso){
    var t=String(iso||'').slice(0,16).replace('T',' ');
    return t||'';
  }
  function req(path){
    return fetch(path,{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); });
  }
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
    req('/api/notes?limit=50').then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      setBadge(d.count);
      var rows=d.items||[];
      if(!rows.length){
        box.innerHTML='<p class="files-empty">还没有文件。在问答里点「存为笔记」，或让智能体通过 MCP 保存。</p>';
        return;
      }
      box.innerHTML='';
      rows.forEach(function(it){
        var b=document.createElement('button');
        b.type='button'; b.className='file-item';
        b.setAttribute('data-id', it.id);
        b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmt(it.created))+'</span>';
        box.appendChild(b);
      });
      // 打开就直接读第一篇：让用户再点一次才看到内容，等于白给一步
      var first=box.querySelector('.file-item');
      if(first) first.click();
    }).catch(function(){
      box.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  // 正文渲染只写一份：抽屉和 /files 页共用，两处各写一套迟早长歪
  function detailHtml(d){
    var meta=[fmt(d.created), d.kind||'', (d.tags||[]).join(' · ')].filter(Boolean).join(' · ');
    // 文件是用户的，那就得能改：给两条路——页内改原文，或交给系统里顺手的编辑器
    var tools='<div class="files-tools">'
      +'<button class="btn ghost sm" type="button" data-edit="'+esc(d.id||'')+'" data-path="'+esc(d.path||'')+'">编辑原文</button>'
      +'<button class="btn ghost sm" type="button" data-openfile="'+esc(d.path||'')+'">用系统编辑器打开</button>'
      +'</div>';
    var html=tools+'<h3>'+esc(d.title||'(无标题)')+'</h3><div class="files-meta">'+esc(meta)+'</div>';
    var secs=(d.sections||[]).filter(function(s){ return s.body&&String(s.body).trim(); });
    if(!secs.length) html+='<p class="files-empty">这篇还没有正文。</p>';
    secs.forEach(function(s){
      html+='<div class="files-sec"><h4>'+esc(s.title)+'</h4><p>'+esc(s.body)+'</p></div>';
    });
    return html;
  }
  window.__notesDetailHtml=detailHtml;
  window.__notesFetch=req;

  // ---- 页内编辑原文 ----
  function headers(extra){
    var h={'Accept':'application/json'};
    if(extra) h['Content-Type']='application/json';
    return window.apiHeaders?window.apiHeaders(h):h;
  }
  function openEditor(btn){
    var path=btn.getAttribute('data-path')||'';
    var host=btn.closest('.files-detail, .pf-detail');
    if(!path||!host){ if(window.toast) window.toast('这篇没有对应的磁盘路径',true); return; }
    host.innerHTML='<p class="files-empty">读取中…</p>';
    fetch('/api/files/raw?path='+encodeURIComponent(path),{headers:headers()}).then(function(r){
      return r.json();
    }).then(function(d){
      if(!d||!d.ok){ host.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      host.innerHTML='<div class="files-editor">'
        +'<div class="fe-head"><span class="fe-path">'+esc(d.path)+'</span><span class="fe-rev">rev '+esc(d.rev)+'</span></div>'
        +'<p class="fe-tip">这是磁盘上的原文，含 front matter。删掉头部也能用，但标签、状态、摘要这些字段会丢。</p>'
        +'<textarea class="fe-area" spellcheck="false"></textarea>'
        +'<div class="fe-foot"><span class="fe-msg"></span>'
        +'<button class="btn ghost sm" type="button" data-cancel>取消</button>'
        +'<button class="btn sm" type="button" data-save>保存</button></div></div>';
      var area=host.querySelector('.fe-area');
      area.value=d.content;
      // 打开时停在文件开头：默认滚到中段会让人以为头部丢了
      area.scrollTop=0;
      try{ area.setSelectionRange(0,0); }catch(e){}
      var msg=host.querySelector('.fe-msg');
      function say(t,bad){ msg.textContent=t||''; msg.className='fe-msg'+(bad?' err':''); }
      host.querySelector('[data-cancel]').onclick=function(){
        var item=document.querySelector('.file-item.on');
        if(item) item.click();
        else if(window.location.pathname==='/files') location.reload();
      };
      host.querySelector('[data-save]').onclick=function(){
        var btnSave=this; btnSave.disabled=true; say('保存中…');
        fetch('/api/files/raw',{method:'PUT',headers:headers(),body:JSON.stringify({
          path:d.path, content:area.value, base_rev:d.rev})}).then(function(r){
          return r.json().then(function(body){ return {status:r.status, body:body}; });
        }).then(function(res){
          var body=res.body||{};
          if(res.status===409){
            say('文件在你编辑期间被改过（可能是智能体），已拒绝覆盖。复制内容后点取消再看最新版。',true);
            return;
          }
          if(!body.ok){ say(body.message||'保存失败',true); return; }
          say('已保存 '+body.rev);
          if(window.toast) window.toast('已保存到存储区');
          var item=document.querySelector('.file-item.on');
          if(item) setTimeout(function(){ item.click(); }, 260);
        }).catch(function(e){ say('保存失败：'+((e&&e.message)||e),true); })
          .finally(function(){ btnSave.disabled=false; });
      };
      area.focus();
    }).catch(function(){
      host.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  document.addEventListener('click',function(e){
    var edit=e.target.closest('[data-edit]');
    if(edit){ e.preventDefault(); openEditor(edit); return; }
    var open=e.target.closest('[data-openfile]');
    if(open){
      e.preventDefault();
      var path=open.getAttribute('data-openfile')||'';
      if(!path) return;
      fetch('/api/files/open',{method:'POST',headers:headers(),body:JSON.stringify({path:path})})
        .then(function(r){ return r.json(); }).then(function(d){
          if(!d||!d.ok){ if(window.toast) window.toast((d&&d.message)||'打不开',true); }
        }).catch(function(){ if(window.toast) window.toast('打不开系统编辑器',true); });
    }
  });

  function show(id, btn){
    [].forEach.call(panel.querySelectorAll('.file-item'), function(x){
      x.classList.toggle('on', x===btn);
    });
    var box=$('filesDetail');
    box.innerHTML='<p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(id)).then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      box.innerHTML=detailHtml(d);
      box.scrollTop=0;
    }).catch(function(){
      box.innerHTML='<p class="files-empty">读取失败。</p>';
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
    if(e.key==='Escape'&&!panel.hidden) close();
  });

  // 红点：点它只消提醒，不打开抽屉——「我知道了」和「我要看」是两个意图
  if($('filesDot')) $('filesDot').addEventListener('click',function(e){
    e.preventDefault(); e.stopPropagation();
    try{ localStorage.setItem(DOT_KEY, this.getAttribute('data-sig')||'none'); }catch(err){}
    this.hidden=true;
    if(window.toast) window.toast('备份提醒已消除');
  });

  // Ctrl/Cmd+Shift+F 开合文件面板；在输入框里不抢按键（那里常按组合键选词）
  document.addEventListener('keydown',function(e){
    if(!(e.ctrlKey||e.metaKey)||!e.shiftKey||(e.key||'').toLowerCase()!=='f') return;
    var tag=(document.activeElement||{}).tagName;
    if(tag==='INPUT'||tag==='TEXTAREA') return;
    e.preventDefault();
    if(panel.hidden) open(); else close();
  });


  if($('filesList')) $('filesList').addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    show(b.getAttribute('data-id'), b);
  });
  if($('filesExport')) $('filesExport').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    fetch('/api/notes/export?format=json').then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok){ if($('filesBackup')) $('filesBackup').textContent=(d&&d.message)||'导出失败'; return; }
      var blob=new Blob([d.content],{type:d.mime||'application/json;charset=utf-8'});
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a');
      a.href=url; a.download=d.filename||'notes.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      if($('filesBackup')){ $('filesBackup').textContent='已导出 '+(d.count||0)+' 篇'; $('filesBackup').className='files-note'; }
      if($('filesDot')) $('filesDot').hidden=true;
    }).catch(function(e){
      if($('filesBackup')) $('filesBackup').textContent='导出失败：'+((e&&e.message)||e);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  // 首屏就把数量与备份状态读出来：入口上的角标不该等打开抽屉才出现
  refreshState();
})();
