
(function(){
  var $=function(id){ return document.getElementById(id); };
  var list=$('pfList'); if(!list) return;
  var detail=$('pfDetail'), search=$('pfSearch');
  var current='', timer=null, editorDirty=false, LIMIT=100;

  function api(path, method, body){
    var opt={method:method||'GET', headers:reqHeaders(!!body)};
    if(body) opt.body=JSON.stringify(body);
    return fetch(path,opt).then(function(r){ return r.json(); });
  }

  function render(rows){
    if(!rows.length){
      list.innerHTML='<p class="files-empty">'+(search&&search.value.trim()
        ? '没有匹配的笔记。'
        : '还没有笔记。点「新建笔记」，或在问答里存一条。')+'</p>';
      return;
    }
    list.innerHTML='';
    rows.forEach(function(it){
      var b=document.createElement('button');
      b.type='button'; b.className='file-item'; b.setAttribute('data-id',it.id);
      b.setAttribute('role','option');
      // 来源徽标：智能体写进来的笔记与人写的要在列表里区分开，否则会以为自己梦游写了一条
      var agent=((it.source||{}).agent||'');
      var tag=(agent&&!/^web/i.test(agent))?'<em class="src-tag">智能体</em>':'';
      b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b>'+tag+'<span>'+esc(fmtTime(it.created))+'</span>';
      list.appendChild(b);
    });
  }

  /* 搜索走服务端：与问答页共用同一套笔记索引（标题 + 标签 + 正文），
     在这里再写一遍本地过滤等于两套匹配规则，搜同一句话会给出不同结果。 */
  function load(openId){
    var q=(search&&search.value||'').trim();
    api('/api/notes?limit='+LIMIT+(q?('&q='+encodeURIComponent(q)):'')).then(function(d){
      if(!d||!d.ok){ list.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      var rows=d.items||[];
      if($('pfTotal')) $('pfTotal').textContent=(q?'匹配 ':'共 ')+(d.count||rows.length)+' 篇';
      render(rows);
      // 一次只取 100 篇：第 101 篇以前是「看不见也翻不到」，现在给个明确的出口
      if($('pfMore')){
        var left=(d.count||rows.length)-rows.length;
        $('pfMore').hidden=left<=0;
        $('pfMore').textContent='加载更多（还有 '+left+' 篇）';
      }
      var want=openId||current;
      var target=want?list.querySelector('[data-id="'+want+'"]'):null;
      if(target){ select(target); return; }
      if(q){ current=''; detail.innerHTML='<p class="files-empty">从左侧选一份查看。</p>'; return; }
      var first=list.querySelector('.file-item'); if(first) select(first);
    }).catch(function(){
      list.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  function bodyHtml(d){
    var meta=[fmtTime(d.created), d.kind||'', (d.tags||[]).join(' · ')].filter(Boolean).join(' · ');
    // 文件是用户的，那就得能改：页内改原文，或交给系统里顺手的编辑器；删除放在同一排但用红色区分
    var tools='<div class="files-tools">'
      +'<button class="btn ghost sm" type="button" data-edit="'+esc(d.id||'')+'" data-path="'+esc(d.path||'')+'">编辑原文</button>'
      +'<button class="btn ghost sm" type="button" data-openfile="'+esc(d.path||'')+'">用系统编辑器打开</button>'
      +'<button class="btn ghost sm pf-del" type="button" data-delnote="'+esc(d.id||'')+'" data-title="'+esc(d.title||'')+'">删除这篇</button>'
      +'</div>';
    var html=tools+'<h3>'+esc(d.title||'(无标题)')+'</h3><div class="files-meta">'+esc(meta)+'</div>';
    var secs=(d.sections||[]).filter(function(s){ return s.body&&String(s.body).trim(); });
    if(!secs.length) html+='<p class="files-empty">这篇还没有正文。</p>';
    secs.forEach(function(s){
      html+='<div class="files-sec"><h4>'+esc(s.title)+'</h4><p>'+esc(s.body)+'</p></div>';
    });
    return html+'<div class="pf-assets" id="pfAssets"></div>';
  }

  function select(btn){
    // 编辑区是不可回退的：切走就丢，保存只在点「保存」时发生
    if(editorDirty&&!confirm('这篇还有未保存的改动，切走会丢掉。继续？')) return;
    editorDirty=false;
    [].forEach.call(list.querySelectorAll('.file-item'),function(x){ x.classList.toggle('on',x===btn); });
    var id=btn.getAttribute('data-id'); current=id;
    detail.innerHTML='<p class="files-empty">读取中…</p>';
    api('/api/notes/'+encodeURIComponent(id)).then(function(d){
      if(!d||!d.ok){ detail.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      detail.innerHTML=bodyHtml(d);
      loadAssets(id);
      detail.scrollTop=0;
    }).catch(function(){ detail.innerHTML='<p class="files-empty">读取失败。</p>'; });
  }

  // ---- 附件：列表 / 上传 / 下载 ----
  function loadAssets(id){
    var box=$('pfAssets'); if(!box) return;
    box.innerHTML='<h4>附件</h4><p class="files-empty">读取中…</p>';
    api('/api/notes/'+encodeURIComponent(id)+'/assets').then(function(d){
      var rows=(d&&d.items)||[];
      if(!d||!d.ok){ box.innerHTML=''; return; }
      var head='<div class="pf-assets-hd"><h4>附件'+(rows.length?' · '+rows.length+' 个':'')+'</h4>'
        +'<button type="button" class="btn ghost sm" data-upload>上传附件</button></div>';
      if(!rows.length){ box.innerHTML=head+'<p class="files-empty">还没有附件。单文件 ≤ 8 MB。</p>'; return; }
      box.innerHTML=head+rows.map(function(a){
        return '<button type="button" class="pf-asset" data-asset="'+esc(a.name)+'">'
          +'<span class="nm">'+esc(a.display||a.name)+'</span>'
          +'<span class="sz">'+fmtBytes(a.size)+'</span></button>';
      }).join('');
    }).catch(function(){ box.innerHTML=''; });
  }

  function readBase64(file){
    return new Promise(function(resolve, reject){
      var fr=new FileReader();
      fr.onload=function(){
        var text=String(fr.result||''), comma=text.indexOf(',');
        resolve(comma>=0?text.slice(comma+1):'');
      };
      fr.onerror=function(){ reject(new Error('读取文件失败')); };
      fr.readAsDataURL(file);
    });
  }

  function uploadAssets(files){
    if(!current){ toast('先选一篇笔记', true); return; }
    var arr=[].slice.call(files||[]); if(!arr.length) return;
    var ok=0, fail=[];
    (function next(i){
      if(i>=arr.length){
        if(fail.length) toast('成功 '+ok+' 个，失败 '+fail.length+' 个（'+fail[0]+'）', true);
        else toast('已上传 '+ok+' 个附件');
        loadAssets(current);
        return;
      }
      var f=arr[i];
      // 服务端上限 8 MB，本地先拦一次：传了 6 MB 再失败是白等
      if(f.size>8*1024*1024){ fail.push(f.name+'：超过 8 MB'); next(i+1); return; }
      readBase64(f)
        .then(function(b64){
          return api('/api/notes/'+encodeURIComponent(current)+'/assets','POST',{name:f.name,data:b64});
        })
        .then(function(d){
          if(d&&d.ok) ok++; else fail.push((d&&d.message)||f.name);
          next(i+1);
        })
        .catch(function(e){ fail.push(f.name+'：'+((e&&e.message)||e)); next(i+1); });
    })(0);
  }

  // 附件下载走 fetch 再转 Blob：直接 a[href] 带不上 API Key 头，开了鉴权的实例会 401
  function download(name){
    var url='/api/notes/'+encodeURIComponent(current)+'/assets/'+encodeURIComponent(name);
    fetch(url,{headers:reqHeaders()}).then(function(r){
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

  // ---- 编辑原文 ----
  function openEditor(btn){
    var path=btn.getAttribute('data-path')||'';
    if(!path){ toast('这篇没有对应的磁盘路径',true); return; }
    detail.innerHTML='<p class="files-empty">读取中…</p>';
    api('/api/files/raw?path='+encodeURIComponent(path)).then(function(d){
      if(!d||!d.ok){ detail.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      detail.innerHTML='<div class="files-editor">'
        +'<div class="fe-head"><span class="fe-path">'+esc(d.path)+'</span><span class="fe-rev">rev '+esc(d.rev)+'</span></div>'
        +'<p class="fe-tip">这是磁盘上的原文，含 front matter。删掉头部也能用，但标签、状态、摘要这些字段会丢。</p>'
        +'<textarea class="fe-area" spellcheck="false"></textarea>'
        +'<div class="fe-foot"><span class="fe-msg"></span>'
        +'<button class="btn ghost sm" type="button" data-cancel>取消</button>'
        +'<button class="btn sm" type="button" data-save>保存</button></div></div>';
      var area=detail.querySelector('.fe-area');
      area.value=d.content;
      area.addEventListener('input',function(){ editorDirty=true; });
      area.scrollTop=0;
      try{ area.setSelectionRange(0,0); }catch(e){}
      var msg=detail.querySelector('.fe-msg');
      function say(t,bad){ msg.textContent=t||''; msg.className='fe-msg'+(bad?' err':''); }
      detail.querySelector('[data-cancel]').onclick=function(){
        editorDirty=false;
        var item=list.querySelector('.file-item.on');
        if(item) select(item);
      };
      detail.querySelector('[data-save]').onclick=function(){
        var saveBtn=this; saveBtn.disabled=true; say('保存中…');
        fetch('/api/files/raw',{method:'PUT',headers:reqHeaders(true),body:JSON.stringify({
          path:d.path, content:area.value, base_rev:d.rev})}).then(function(r){
          return r.json().then(function(body){ return {status:r.status, body:body}; });
        }).then(function(res){
          var body=res.body||{};
          if(res.status===409){
            say('文件在你编辑期间被改过（可能是智能体），已拒绝覆盖。复制内容后点取消再看最新版。',true);
            return;
          }
          if(!body.ok){ say(body.message||'保存失败',true); return; }
          editorDirty=false;
          say('已保存 '+body.rev);
          toast('已保存到存储区');
          load(current);      // front matter 里的标题/标签可能改过，列表要跟着刷新
        }).catch(function(e){ say('保存失败：'+((e&&e.message)||e),true); })
          .finally(function(){ saveBtn.disabled=false; });
      };
      area.focus();
    }).catch(function(){
      detail.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  // ---- 新建 / 删除 ----
  function newNote(){
    var wrap=document.createElement('div');
    wrap.className='pf-dlg-mask';
    wrap.innerHTML='<div class="pf-dlg" role="dialog" aria-modal="true" aria-label="新建笔记">'
      +'<h3>新建笔记</h3>'
      +'<label class="pf-f">标题<input id="pfNewTitle" maxlength="120" placeholder="一句话说清这篇记什么"></label>'
      +'<label class="pf-f">正文<textarea id="pfNewBody" rows="6" placeholder="可以先留空，之后再补。"></textarea></label>'
      +'<div class="pf-dlg-foot"><span class="pf-msg"></span>'
      +'<button class="btn ghost sm" type="button" data-cancel>取消</button>'
      +'<button class="btn sm" type="button" data-ok>创建</button></div></div>';
    document.body.appendChild(wrap);
    // 双击「新建笔记」时第二下落在刚出现的遮罩上，会把弹层立刻关掉
    markOpen(wrap); openOverlay('newNote');
    var title=wrap.querySelector('#pfNewTitle'), body=wrap.querySelector('#pfNewBody');
    var msg=wrap.querySelector('.pf-msg'), okBtn=wrap.querySelector('[data-ok]');
    title.focus();
    function close(){ closeOverlay('newNote'); document.removeEventListener('keydown',onEsc); wrap.remove(); }
    wrap.querySelector('[data-cancel]').onclick=close;
    wrap.addEventListener('click',function(e){ if(e.target===wrap && !tooSoon(wrap)) close(); });
    /* Esc 挂在 document 上，不挂在 wrap 上：点过遮罩之后焦点落在 body，
       keydown 不再经过 wrap，挂在里面就会「点了外面之后 Esc 失效」。 */
    var onEsc=function(e){
      if(e.key!=='Escape'||!isTopOverlay('newNote')) return;
      e.stopPropagation(); document.removeEventListener('keydown',onEsc); close();
    };
    document.addEventListener('keydown',onEsc);
    okBtn.onclick=function(){
      var t=title.value.trim();
      if(!t){ msg.textContent='标题不能为空'; title.focus(); return; }
      var b=body.value.trim();
      var msgs=[{role:'user',text:t}];
      if(b) msgs.push({role:'assistant',text:b});
      okBtn.disabled=true; msg.textContent='创建中…';
      api('/api/notes','POST',{messages:msgs,commit:true}).then(function(d){
        if(!d||!d.ok){ msg.textContent=(d&&d.message)||'创建失败'; okBtn.disabled=false; return; }
        close(); toast('已创建');
        load(d.id);
      }).catch(function(e){ msg.textContent='创建失败：'+((e&&e.message)||e); okBtn.disabled=false; });
    };
  }

  function removeNote(btn){
    var id=btn.getAttribute('data-delnote'), title=btn.getAttribute('data-title')||'这篇';
    if(!window.confirm('删除《'+title+'》？\n会移到存储区的 .trash，可以从那里找回；附件也一起删除。')) return;
    btn.disabled=true;
    fetch('/api/notes/'+encodeURIComponent(id)+'?confirm=1',{method:'DELETE',headers:reqHeaders()})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d||!d.ok){ toast((d&&d.message)||'删除失败',true); btn.disabled=false; return; }
        toast('已删除，可在 .trash 找回');
        current='';
        detail.innerHTML='<p class="files-empty">已删除。从左侧选另一份。</p>';
        load();
      }).catch(function(e){ toast('删除失败：'+((e&&e.message)||e),true); btn.disabled=false; });
  }

  // ---- 导出 ----
  function exportAll(fmt, btn){
    var label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    api('/api/notes/export?format='+fmt).then(function(d){
      if(!d||!d.ok){ toast((d&&d.message)||'导出失败',true); return; }
      saveBlob(d.content, d.filename||('notes.'+fmt), d.mime||'');
      toast('已导出 '+(d.count||0)+' 篇');
    }).catch(function(e){
      toast('导出失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  }

  // ---- 事件 ----
  if($('pfMore')) $('pfMore').onclick=function(){
    LIMIT+=200; this.disabled=true; var b=this;
    load(current);
    setTimeout(function(){ b.disabled=false; },200);
  };
  // ↑↓ 在列表里移动焦点：键盘用户不该被逼着用鼠标
  list.addEventListener('keydown',function(e){
    if(e.key!=='ArrowDown'&&e.key!=='ArrowUp') return;
    var items=[].slice.call(list.querySelectorAll('.file-item'));
    if(!items.length) return;
    e.preventDefault();
    var i=items.indexOf(document.activeElement);
    if(i<0){ items[0].focus(); return; }
    (e.key==='ArrowDown'?items[Math.min(items.length-1,i+1)]:items[Math.max(0,i-1)]).focus();
  });
  list.addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(b) select(b);
  });

  detail.addEventListener('click',function(e){
    var del=e.target.closest('[data-delnote]');
    if(del){ e.preventDefault(); removeNote(del); return; }
    var asset=e.target.closest('[data-asset]');
    if(asset){ e.preventDefault(); download(asset.getAttribute('data-asset')); return; }
    var edit=e.target.closest('[data-edit]');
    if(edit){ e.preventDefault(); openEditor(edit); return; }
    var up=e.target.closest('[data-upload]');
    if(up){ e.preventDefault(); if($('pfAssetFile')) $('pfAssetFile').click(); return; }
    var open=e.target.closest('[data-openfile]');
    if(open){
      e.preventDefault();
      var path=open.getAttribute('data-openfile')||''; if(!path) return;
      api('/api/files/open','POST',{path:path}).then(function(d){
        if(!d||!d.ok) toast((d&&d.message)||'打不开',true);
      }).catch(function(){ toast('打不开系统编辑器',true); });
    }
  });

  if($('pfAssetFile')) $('pfAssetFile').addEventListener('change',function(){
    uploadAssets(this.files);
    this.value='';      // 同一个文件连选两次也要能触发 change
  });

  if(search) search.addEventListener('input',function(){
    clearTimeout(timer);
    timer=setTimeout(function(){ load(); },240);   // 防抖：边打边搜会把每次按键都变成一次 BM25
  });

  if($('pfNew')) $('pfNew').addEventListener('click',newNote);
  if($('pfExport')) $('pfExport').addEventListener('click',function(){ exportAll('json',this); });
  if($('pfExportHtml')) $('pfExportHtml').addEventListener('click',function(){ exportAll('html',this); });

  // 抽屉点某篇会带 ?id= 过来，直接选中；没有就选第一篇
  var m=/[?&]id=([^&]+)/.exec(location.search);
  load(m?decodeURIComponent(m[1]):undefined);
})();
