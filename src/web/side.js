/* ============ 会话列表（存在项目的存储区，不在浏览器） ============
   以前放 localStorage：换浏览器、换端口、清缓存就全没了，智能体也读不到。
   现在一条会话一个 JSON 文件，落在 <存储区>/threads/ 下：
   页面只是它的一个视图，用户和智能体看到的是同一份。

   浏览器里只剩两样东西：
   - jy_current_v1：上次打开的是哪条（纯界面状态，丢了不影响数据）；
   - jy_side_mini：侧栏收没收（同上）。
   老版本的 jy_threads_v1 会在第一次加载时一次性搬进存储区，然后删掉。 */
(function(){
  var LEGACY='jy_threads_v1', POINTER='jy_current_v1', MAX=60;
  var state={threads:[], current:'', ready:null};
  var timers={};

  function now(){ return new Date().toISOString(); }
  function uid(){ return 't'+Date.now().toString(36)+Math.random().toString(36).slice(2,8); }
  function titleOf(q){
    var t=String(q||'').replace(/\s+/g,' ').trim();
    return t?t.slice(0,28):'新对话';
  }
  function headers(extra){
    var h={'Accept':'application/json'};
    if(extra) h['Content-Type']='application/json';
    return (window.apiHeaders?window.apiHeaders(h):h);
  }
  function call(method,path,body){
    return fetch(path,{method:method,headers:headers(!!body),
      body:body?JSON.stringify(body):undefined}).then(function(r){ return r.json(); });
  }
  function find(id){
    for(var i=0;i<state.threads.length;i++){
      if(state.threads[i].id===id) return state.threads[i];
    }
    return null;
  }
  function loadPointer(){
    try{ return localStorage.getItem(POINTER)||''; }catch(e){ return ''; }
  }
  function savePointer(id){
    try{ localStorage.setItem(POINTER,id||''); }catch(e){}
  }
  function group(iso){
    var d=new Date(iso||''), t=new Date();
    if(isNaN(d.getTime())) return '更早';
    var a=new Date(t.getFullYear(),t.getMonth(),t.getDate()).getTime();
    var b=new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime();
    var days=Math.round((a-b)/86400000);
    if(days<=0) return '今天';
    if(days===1) return '昨天';
    if(days<7) return '7 天内';
    return '更早';
  }

  // 合并写：一轮问答会连续改标题和 sid，别为一次改动打三次请求
  function persist(thread, delay){
    if(!thread) return;
    clearTimeout(timers[thread.id]);
    timers[thread.id]=setTimeout(function(){
      delete timers[thread.id];
      var body={title:thread.title,created:thread.created,sid:thread.sid||'',turns:thread.turns||[]};
      call('PUT','/api/threads/'+encodeURIComponent(thread.id),body).catch(function(){
        if(window.toast) window.toast('会话没能存进存储区，检查服务是否还在运行',true);
      });
    }, delay==null?250:delay);
  }
  function flushAll(){
    // 关页面前把还没落盘的写掉：keepalive 让请求在页面卸载后仍然发出
    state.threads.forEach(function(t){
      if(!timers[t.id]) return;
      clearTimeout(timers[t.id]); delete timers[t.id];
      try{
        fetch('/api/threads/'+encodeURIComponent(t.id),{
          method:'PUT',keepalive:true,headers:headers(true),
          body:JSON.stringify({title:t.title,created:t.created,sid:t.sid||'',turns:t.turns||[]})
        });
      }catch(e){}
    });
  }

  function migrateLegacy(){
    var raw='';
    try{ raw=localStorage.getItem(LEGACY)||''; }catch(e){ return Promise.resolve(0); }
    if(!raw) return Promise.resolve(0);
    var rows=[];
    try{
      var data=JSON.parse(raw);
      rows=(data&&data.threads)||[];
    }catch(e){ rows=[]; }
    if(!rows.length){ try{ localStorage.removeItem(LEGACY); }catch(e){} return Promise.resolve(0); }
    return call('POST','/api/threads/import',{threads:rows.slice(0,MAX)}).then(function(res){
      try{ localStorage.removeItem(LEGACY); }catch(e){}
      if(res&&res.ok&&res.imported&&window.toast){
        window.toast('已把浏览器里的 '+res.imported+' 条会话搬进存储区');
      }
      return (res&&res.imported)||0;
    }).catch(function(){ return 0; });
  }

  function fetchThread(id){
    return call('GET','/api/threads/'+encodeURIComponent(id)).then(function(res){
      var t=find(id);
      if(!res||!res.ok||!res.thread){ return null; }
      var remote=res.thread;
      if(!t){ t={id:id}; state.threads.unshift(t); }
      t.title=remote.title||t.title||'新对话';
      t.created=remote.created||t.created;
      t.updated=remote.updated||t.updated;
      t.sid=remote.sid||t.sid||'';
      t.turns=remote.turns||[];
      t.loaded=true;
      document.dispatchEvent(new CustomEvent('jy:loaded',{detail:id}));
      return t;
    }).catch(function(){ return null; });
  }

  function reload(){
    return call('GET','/api/threads?limit='+MAX).then(function(res){
      if(!res||!res.ok){ return; }
      var prev={};
      state.threads.forEach(function(t){ prev[t.id]=t; });
      state.threads=(res.items||[]).map(function(it){
        var keep=prev[it.id];
        // 已经取过正文的保留在内存里，列表只更新元数据
        if(keep&&keep.loaded){ keep.title=it.title; keep.updated=it.updated; return keep; }
        return {id:it.id,title:it.title,created:it.created,updated:it.updated,
                sid:it.sid,turns:[],loaded:false,count:it.turns};
      });
      if(!find(state.current)) state.current='';
      JY.render();
    }).catch(function(){});
  }

  var JY={
    list:function(){
      return state.threads.slice().sort(function(a,b){
        return String(b.updated||'').localeCompare(String(a.updated||''));
      });
    },
    currentId:function(){ return state.current; },
    currentThread:function(){ return find(state.current); },
    reload:reload,
    create:function(){
      var t={id:uid(),title:'新对话',created:now(),updated:now(),sid:'',turns:[],loaded:true};
      state.threads.unshift(t); state.current=t.id; savePointer(t.id);
      persist(t,0);
      JY.render();
      return t;
    },
    open:function(id){
      var t=find(id);
      if(!t) return null;
      state.current=id; savePointer(id);
      if(!t.loaded) fetchThread(id);
      JY.render();
      return t;
    },
    append:function(turn){
      var t=find(state.current);
      if(!t){
        t={id:uid(),title:titleOf(turn&&turn.q),created:now(),updated:now(),sid:'',turns:[],loaded:true};
        state.threads.unshift(t); state.current=t.id; savePointer(t.id);
      }
      if(!t.turns) t.turns=[];
      t.turns.push(turn);
      if(t.title==='新对话'||!t.title) t.title=titleOf(turn&&turn.q);
      t.updated=now();
      var i=state.threads.indexOf(t);
      if(i>0){ state.threads.splice(i,1); state.threads.unshift(t); }
      persist(t);
      JY.render();
      return t;
    },
    touch:function(patch){
      var t=find(state.current); if(!t) return null;
      Object.assign(t,patch||{}); t.updated=now();
      persist(t);
      JY.render();
      return t;
    },
    remove:function(id){
      state.threads=state.threads.filter(function(t){ return t.id!==id; });
      if(state.current===id){
        state.current=(state.threads[0]||{}).id||'';
        savePointer(state.current);
      }
      clearTimeout(timers[id]); delete timers[id];
      call('DELETE','/api/threads/'+encodeURIComponent(id)).catch(function(){});
      JY.render();
    },
    clearCurrent:function(){
      var t=find(state.current); if(!t) return null;
      t.turns=[]; t.title='新对话'; t.updated=now();
      persist(t,0);
      JY.render();
      return t;
    },
    render:function(){
      var box=document.getElementById('convList'); if(!box) return;
      var q=(document.getElementById('convSearch')||{}).value||'';
      q=q.trim().toLowerCase();
      var rows=JY.list().filter(function(t){
        return !q||String(t.title||'').toLowerCase().indexOf(q)>=0;
      });
      var html='', last='';
      rows.forEach(function(t){
        var g=group(t.updated);
        if(g!==last){ html+='<div class="conv-group">'+g+'</div>'; last=g; }
        var on=t.id===JY.currentId()?' on':'';
        html+='<button type="button" class="conv'+on+'" data-id="'+t.id+'" title="'+esc(t.title||'')+'">'
          +'<span class="t">'+esc(t.title||'新对话')+'</span>'
          +'<span class="x" data-del="'+t.id+'" role="button" aria-label="删除这条会话">×</span></button>';
      });
      if(!rows.length){
        html='<div class="side-empty">'+(q?'没有匹配的对话。'
          :'还没有对话记录。提问一次就会出现在这里——记录存在你的存储区，换浏览器也还在。')+'</div>';
      }
      box.innerHTML=html;
    }
  };
  window.JY=JY;

  // 首屏：先取列表，列表为空才迁移旧数据（顺序不能反，否则会先把磁盘上的覆盖成空）
  state.ready=call('GET','/api/threads?limit='+MAX).then(function(res){
    if(res&&res.ok&&(res.items||[]).length){
      state.threads=(res.items||[]).map(function(it){
        return {id:it.id,title:it.title,created:it.created,updated:it.updated,
                sid:it.sid,turns:[],loaded:false,count:it.turns};
      });
      state.current=loadPointer();
      if(!find(state.current)) state.current='';
      JY.render();
      return null;
    }
    return migrateLegacy().then(function(){ return reload(); });
  }).catch(function(){
    if(window.toast) window.toast('会话存储区读不到，先当成空列表',true);
  }).then(function(){
    // 上次打开的会话自动取正文；没有就留空，等用户点
    var t=find(state.current);
    if(t&&!t.loaded) fetchThread(state.current);
  });

  window.addEventListener('pagehide',flushAll);

  // ---------- 侧栏交互 ----------
  function el(id){ return document.getElementById(id); }
  window.__closeSide=closeSide;
  function openSide(){
    document.body.classList.add('side-open');
    var s=el('sideScrim'); if(s) s.hidden=false;
  }
  function closeSide(){
    document.body.classList.remove('side-open');
    var s=el('sideScrim'); if(s) s.hidden=true;
  }
  if(el('sideOpen')) el('sideOpen').onclick=openSide;
  if(el('sideScrim')) el('sideScrim').onclick=closeSide;
  if(el('sideMini')) el('sideMini').onclick=function(){
    if(window.innerWidth<=900){ closeSide(); return; }
    document.body.classList.toggle('side-mini');
    try{ localStorage.setItem('jy_side_mini',document.body.classList.contains('side-mini')?'1':'0'); }catch(e){}
  };
  try{ if(localStorage.getItem('jy_side_mini')==='1') document.body.classList.add('side-mini'); }catch(e){}
  if(el('convSearch')) el('convSearch').oninput=function(){ JY.render(); };

  document.addEventListener('click',function(e){
    var del=e.target.closest('[data-del]');
    if(del){
      e.stopPropagation();
      var id=del.getAttribute('data-del');
      var t=find(id)||{};
      if(window.confirm('删除「'+(t.title||'新对话')+'」？只删这条会话记录，已存的笔记不受影响。')){
        JY.remove(id);
        document.dispatchEvent(new CustomEvent('jy:removed',{detail:id}));
      }
      return;
    }
    var item=e.target.closest('.conv');
    if(!item) return;
    var tid=item.getAttribute('data-id');
    if(document.body.classList.contains('page-ask')){
      document.dispatchEvent(new CustomEvent('jy:thread',{detail:tid}));
    }else{
      location.href='/ask?t='+encodeURIComponent(tid);
    }
    closeSide();
  });

  if(!document.body.classList.contains('page-ask') && el('newChat')){
    el('newChat').onclick=function(){ location.href='/ask?new=1'; };
  }
  document.addEventListener('keydown',function(e){
    var meta=e.ctrlKey||e.metaKey;
    if(meta&&(e.key==='k'||e.key==='K')){
      e.preventDefault();
      if(el('newChat')) el('newChat').click(); else location.href='/ask?new=1';
      return;
    }
    if(meta&&(e.key==='b'||e.key==='B')){
      e.preventDefault(); document.body.classList.toggle('side-mini'); return;
    }
    if(e.key==='Escape') closeSide();
  });
})();
