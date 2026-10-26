
/* ============ 会话列表（本地存储） ============
   为什么放浏览器：这些对话只是「看过的记录」，不是要长期保存的资料；
   真正要留的东西走「存为笔记」，落在磁盘上的 Markdown 里。
   两条存储各管一件事，用户才不会以为清了会话就丢了笔记。 */
(function(){
  var KEY='jy_threads_v1', LEGACY='rag_history_v1', MAX=60;
  function now(){ return new Date().toISOString(); }
  function uid(){ return 't'+Date.now().toString(36)+Math.random().toString(36).slice(2,6); }
  function titleOf(q){
    var t=String(q||'').replace(/\s+/g,' ').trim();
    return t?t.slice(0,28):'新对话';
  }
  function read(){
    try{
      var raw=localStorage.getItem(KEY); var d=raw?JSON.parse(raw):null;
      if(d&&Array.isArray(d.threads)) return d;
    }catch(e){}
    return null;
  }
  function write(d){ try{ localStorage.setItem(KEY,JSON.stringify(d)); }catch(e){} }
  function migrate(){
    // 老版本只有一条「当前对话」的流水，升级后包成一条会话，历史不丢
    try{
      var raw=localStorage.getItem(LEGACY); if(!raw) return null;
      var rows=JSON.parse(raw); if(!Array.isArray(rows)||!rows.length) return null;
      var id=uid();
      var t={id:id,title:titleOf(rows[0]&&rows[0].q),
             created:(rows[0]&&rows[0].ts)||now(),
             updated:((rows[rows.length-1]||{}).ts)||now(),turns:rows};
      var d={v:1,current:id,threads:[t]};
      write(d); return d;
    }catch(e){ return null; }
  }
  function ensure(){
    var d=read()||migrate();
    if(!d){ d={v:1,current:'',threads:[]}; }
    if(!Array.isArray(d.threads)) d.threads=[];
    return d;
  }
  function pick(d){
    if(!d) return null;
    for(var i=0;i<d.threads.length;i++){ if(d.threads[i].id===d.current) return d.threads[i]; }
    return null;
  }
  function currentThread(){ return pick(ensure()); }
  function fmt(iso){
    var d=new Date(iso||'');
    if(isNaN(d.getTime())) return '';
    function p(n){ return (n<10?'0':'')+n; }
    return (d.getMonth()+1)+'月'+d.getDate()+'日 '+p(d.getHours())+':'+p(d.getMinutes());
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
  var ORDER=['今天','昨天','7 天内','更早'];

  var JY={
    key:KEY,
    list:function(){
      return ensure().threads.slice().sort(function(a,b){
        return String(b.updated||'').localeCompare(String(a.updated||''));
      });
    },
    currentId:function(){ return ensure().current; },
    currentThread:currentThread,
    create:function(){
      var d=ensure(); var t={id:uid(),title:'新对话',created:now(),updated:now(),turns:[]};
      d.threads.unshift(t); d.current=t.id;
      d.threads=d.threads.slice(0,MAX);
      write(d); JY.render(); return t;
    },
    open:function(id){
      var d=ensure();
      for(var i=0;i<d.threads.length;i++){
        if(d.threads[i].id===id){ d.current=id; write(d); JY.render(); return d.threads[i]; }
      }
      return null;
    },
    append:function(turn){
      // 必须用同一个 d 找当前会话：ensure() 每次都会重新解析 JSON，
      // 再调一次 currentThread() 拿到的是另一份副本，改了也写不回同一个对象。
      var d=ensure(); var t=pick(d);
      if(!t){ t={id:uid(),title:titleOf(turn&&turn.q),created:now(),updated:now(),turns:[]};
        d.threads.unshift(t); d.current=t.id; }
      t.turns.push(turn);
      if(t.title==='新对话'||!t.title) t.title=titleOf(turn&&turn.q);
      t.updated=now();
      var i=d.threads.indexOf(t);
      if(i>0){ d.threads.splice(i,1); d.threads.unshift(t); }
      write(d); JY.render();
      return t;
    },
    touch:function(patch){
      var d=ensure(); var t=pick(d); if(!t) return null;
      Object.assign(t,patch||{}); t.updated=now(); write(d); JY.render(); return t;
    },
    remove:function(id){
      var d=ensure();
      d.threads=d.threads.filter(function(t){ return t.id!==id; });
      if(d.current===id) d.current=(d.threads[0]||{}).id||'';
      write(d); JY.render();
    },
    clearCurrent:function(){
      var d=ensure(); var t=pick(d); if(!t) return null;
      t.turns=[]; t.title='新对话'; t.updated=now(); write(d); JY.render(); return t;
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
        html='<div class="side-empty">'+(q?'没有匹配的对话。':'还没有对话记录。直接在下面提问就会出现在这里。')+'</div>';
      }
      box.innerHTML=html;
    }
  };
  window.JY=JY;

  // ---------- 侧栏交互 ----------
  function el(id){ return document.getElementById(id); }
  // 遮罩带 hidden 属性（桌面端不该占位），打开时要真去掉，否则点不到
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
      var t=JY.list().filter(function(x){ return x.id===id; })[0]||{};
      if(window.confirm('删除「'+(t.title||'新对话')+'」？只删本地记录，已存的笔记不受影响。')){
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
  JY.render();
})();
