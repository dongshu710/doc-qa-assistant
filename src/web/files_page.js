
(function(){
  var $=function(id){ return document.getElementById(id); };
  var list=$('pfList'); if(!list) return;
  var detail=$('pfDetail'), search=$('pfSearch');
  var current='', timer=null;

  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function headers(extra){
    var h={'Accept':'application/json'};
    if(extra) h['Content-Type']='application/json';
    return window.apiHeaders?window.apiHeaders(h):h;
  }
  function req(p){
    if(window.__notesFetch) return window.__notesFetch(p);
    return fetch(p,{headers:headers()}).then(function(r){ return r.json(); });
  }
  function fmt(iso){ return String(iso||'').slice(0,16).replace('T',' '); }
  function size(n){
    n=Number(n)||0;
    if(n<1024) return n+' B';
    if(n<1048576) return Math.round(n/1024)+' KB';
    return (n/1048576).toFixed(1)+' MB';
  }
  function toast(t,bad){ if(window.toast) window.toast(t,bad); }

  function render(rows){
    if(!rows.length){
      list.innerHTML='<p class="files-empty">'+(search&&search.value.trim()
        ? '没有匹配的笔记。'
        : '还没有文件。在问答里点「存为笔记」，或让智能体通过 MCP 保存。')+'</p>';
      return;
    }
    list.innerHTML='';
    rows.forEach(function(it){
      var b=document.createElement('button');
      b.type='button'; b.className='file-item'; b.setAttribute('data-id',it.id);
      b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmt(it.created))+'</span>';
      list.appendChild(b);
    });
  }

  /* 搜索走服务端：/files 与问答页共用同一套笔记索引（标题 + 标签 + 正文），
     在这里再写一遍本地过滤等于两套匹配规则，搜同一句话会给出不同结果。 */
  function load(openId){
    var q=(search&&search.value||'').trim();
    var url='/api/notes?limit=100'+(q?('&q='+encodeURIComponent(q)):'');
    req(url).then(function(d){
      if(!d||!d.ok){ list.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      var rows=d.items||[];
      if($('pfTotal')) $('pfTotal').textContent=(q?'匹配 ':'共 ')+(d.count||rows.length)+' 篇';
      render(rows);
      var want=openId||current;
      var target=want?list.querySelector('[data-id="'+want+'"]'):null;
      if(target){ target.click(); return; }
      if(q){ current=''; detail.innerHTML='<p class="files-empty">从左侧选一份查看。</p>'; return; }
      var first=list.querySelector('.file-item'); if(first) first.click();
    }).catch(function(){
      list.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  function loadAssets(id){
    var box=$('pfAssets'); if(!box) return;
    box.innerHTML='<h4>附件</h4><p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(id)+'/assets').then(function(d){
      var rows=(d&&d.items)||[];
      if(!d||!d.ok){ box.innerHTML=''; return; }
      if(!rows.length){ box.innerHTML='<h4>附件</h4><p class="files-empty">这篇没有附件。</p>'; return; }
      box.innerHTML='<h4>附件 · '+rows.length+' 个</h4>'+rows.map(function(a){
        return '<button type="button" class="pf-asset" data-asset="'+esc(a.name)+'">'
          +'<span class="nm">'+esc(a.display||a.name)+'</span>'
          +'<span class="sz">'+size(a.size)+'</span></button>';
      }).join('');
    }).catch(function(){ box.innerHTML=''; });
  }

  // 正文渲染复用 files.js 里那一份（抽屉与 /files 页共用，两处各写一套迟早长歪）
  function renderDetail(d){
    var html=window.__notesDetailHtml?window.__notesDetailHtml(d):'';
    detail.innerHTML=html+'<div class="pf-assets" id="pfAssets"></div>';
    var tools=detail.querySelector('.files-tools');
    if(tools){
      var b=document.createElement('button');
      b.type='button'; b.className='btn ghost sm pf-del';
      b.setAttribute('data-delnote',d.id);
      b.setAttribute('data-title',d.title||'');
      b.textContent='删除这篇';
      tools.appendChild(b);
    }
    loadAssets(d.id);
  }

  function removeNote(btn){
    var id=btn.getAttribute('data-delnote'), title=btn.getAttribute('data-title')||'这篇';
    if(!window.confirm('删除《'+title+'》？\n会移到存储区的 .trash，可以从那里找回；附件也一起删除。')) return;
    btn.disabled=true;
    fetch('/api/notes/'+encodeURIComponent(id)+'?confirm=1',{method:'DELETE',headers:headers()})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d||!d.ok){ toast((d&&d.message)||'删除失败',true); btn.disabled=false; return; }
        toast('已删除，可在 .trash 找回');
        current='';
        detail.innerHTML='<p class="files-empty">已删除。从左侧选另一份。</p>';
        load();
      }).catch(function(e){ toast('删除失败：'+((e&&e.message)||e),true); btn.disabled=false; });
  }

  // 附件下载必须走 fetch 再转 Blob：直接 a[href] 带不上 API Key 头，开了鉴权的实例会 401
  function download(name){
    var url='/api/notes/'+encodeURIComponent(current)+'/assets/'+encodeURIComponent(name);
    fetch(url,{headers:headers()}).then(function(r){
      if(!r.ok) throw new Error('HTTP '+r.status);
      return r.blob();
    }).then(function(blob){
      var a=document.createElement('a'), u=URL.createObjectURL(blob);
      a.href=u;
      a.download=name.replace(/^[0-9a-f]{8}-/,'')||name;   // 去掉哈希前缀，还给用户原来的名字
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(u); },1000);
    }).catch(function(){ toast('下载失败',true); });
  }

  list.addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    [].forEach.call(list.querySelectorAll('.file-item'),function(x){ x.classList.toggle('on',x===b); });
    var id=b.getAttribute('data-id'); current=id;
    detail.innerHTML='<p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(id)).then(function(d){
      if(!d||!d.ok){ detail.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      renderDetail(d);
      detail.scrollTop=0;
    }).catch(function(){ detail.innerHTML='<p class="files-empty">读取失败。</p>'; });
  });

  detail.addEventListener('click',function(e){
    var del=e.target.closest('[data-delnote]');
    if(del){ e.preventDefault(); removeNote(del); return; }
    var a=e.target.closest('[data-asset]');
    if(a){ e.preventDefault(); download(a.getAttribute('data-asset')); }
  });

  if(search) search.addEventListener('input',function(){
    clearTimeout(timer);
    timer=setTimeout(function(){ load(); },240);   // 防抖：边打边搜会把每次按键都变成一次 BM25
  });

  if($('pfExport')) $('pfExport').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    req('/api/notes/export?format=json').then(function(d){
      if(!d||!d.ok){ toast((d&&d.message)||'导出失败',true); return; }
      var blob=new Blob([d.content],{type:d.mime||'application/json;charset=utf-8'});
      var url=URL.createObjectURL(blob), a=document.createElement('a');
      a.href=url; a.download=d.filename||'notes.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      toast('已导出 '+(d.count||0)+' 篇');
    }).catch(function(e){
      toast('导出失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  load();
})();
