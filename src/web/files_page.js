
(function(){
  var $=function(id){ return document.getElementById(id); };
  var list=$('pfList'); if(!list) return;
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function req(p){
    if(window.__notesFetch) return window.__notesFetch(p);
    return fetch(p,{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); });
  }
  function fmt(iso){ return String(iso||'').slice(0,16).replace('T',' '); }

  function load(){
    list.innerHTML='<p class="files-empty">加载中…</p>';
    req('/api/notes?limit=100').then(function(d){
      if(!d||!d.ok){ list.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      if($('pfTotal')) $('pfTotal').textContent='共 '+(d.count||0)+' 篇';
      var rows=d.items||[];
      if(!rows.length){
        list.innerHTML='<p class="files-empty">还没有文件。在问答里点「存为笔记」，或让智能体通过 MCP 保存。</p>';
        return;
      }
      list.innerHTML='';
      rows.forEach(function(it){
        var b=document.createElement('button');
        b.type='button'; b.className='file-item'; b.setAttribute('data-id',it.id);
        b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmt(it.created))+'</span>';
        list.appendChild(b);
      });
      var first=list.querySelector('.file-item'); if(first) first.click();
    }).catch(function(){
      list.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  list.addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    [].forEach.call(list.querySelectorAll('.file-item'),function(x){ x.classList.toggle('on',x===b); });
    var box=$('pfDetail'); box.innerHTML='<p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(b.getAttribute('data-id'))).then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      box.innerHTML=window.__notesDetailHtml?window.__notesDetailHtml(d):'';
      box.scrollTop=0;
    }).catch(function(){ box.innerHTML='<p class="files-empty">读取失败。</p>'; });
  });

  if($('pfExport')) $('pfExport').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    req('/api/notes/export?format=json').then(function(d){
      if(!d||!d.ok){ if(window.toast) window.toast((d&&d.message)||'导出失败',true); return; }
      var blob=new Blob([d.content],{type:d.mime||'application/json;charset=utf-8'});
      var url=URL.createObjectURL(blob), a=document.createElement('a');
      a.href=url; a.download=d.filename||'notes.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      if(window.toast) window.toast('已导出 '+(d.count||0)+' 篇');
    }).catch(function(e){
      if(window.toast) window.toast('导出失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  load();
})();
