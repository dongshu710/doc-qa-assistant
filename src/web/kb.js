
function $(id){ return document.getElementById(id); }
var KB={files:[],total_chunks:0}, FILTER='all', SORT='name', Q='', BUSY=false;
/* 选中集合挂在全局：列表重绘（筛选、排序、刷新）后勾选不能丢。
   用对象而不是 DOM 状态，是因为每次 render 都会整体重写 tbody。 */
var SEL={};
function selCount(){ return Object.keys(SEL).length; }
function clearSel(){ SEL={}; updateBatch(); }
function updateBatch(){
  var n=selCount(), bar=$('kbBatch');
  if(!bar) return;
  bar.hidden=n===0;
  if(n) $('kbBatchCount').textContent='已选 '+n+' 份';
  var all=$('kbAll');
  if(all) all.checked=!!n&&n===visibleFiles().length;
}

function typeOf(name){
  var ext=(name.split('.').pop()||'').toLowerCase();
  return {ext:ext.toUpperCase(),cls:ext};
}
function emptyRow(cols,text){ return '<tr class="empty-row"><td colspan="'+cols+'">'+esc(text)+'</td></tr>'; }
function setMsg(text,cls){ var el=$('kbMsg'); el.textContent=text||''; el.className='kb-status'+(cls?' '+cls:''); }

function visibleFiles(){
  var q=Q.trim().toLowerCase();
  var list=(KB.files||[]).filter(function(f){
    if(FILTER!=='all' && typeOf(f.name).cls!==FILTER) return false;
    if(q && f.name.toLowerCase().indexOf(q)<0) return false;
    return true;
  });
  list.sort(function(a,b){
    if(SORT==='chunks') return (b.chunks||0)-(a.chunks||0);
    if(SORT==='size') return (b.size||0)-(a.size||0);
    if(SORT==='mtime') return String(b.mtime||'').localeCompare(String(a.mtime||''));
    return String(a.name).localeCompare(String(b.name),'zh-Hans-CN');
  });
  return list;
}

function statusOf(f){
  if(f.status==='no_index') return {cls:'no_index',text:'未索引',tip:'还没进检索索引：可能是索引正在重建，或这份文档没有可切分的正文'};
  if(f.status==='no_page') return {cls:'no_page',text:'无页码',tip:'PDF/PPTX 转出来没有页标，引用里点不到「第 N 页」；检索本身不受影响'};
  return {cls:'ok',text:'正常',tip:'已建索引，页码可用'};
}

function render(){
  var total=(KB.files||[]).length, chunks=KB.total_chunks||0;
  $('kbMeta').textContent=total+' 份 · '+chunks+' 块'+(KB.rebuilding?' · 索引重建中':'')
    +(KB.pending_changes?(' · 待审批 '+KB.pending_changes):'');
  $('kbVersion').textContent=KB.version?('版本 '+KB.version):'单目录模式';
  var list=visibleFiles();
  $('kbFoot').textContent='显示 '+list.length+' / '+total+' 份';
  $('kbHint').textContent=total?('合计 '+chunks+' 个知识块'):'';
  if($('kbSeed')) $('kbSeed').hidden=total>0;
  if(!list.length){
    $('kbBody').innerHTML=emptyRow(7,total?'没有匹配的文档':'还没有文档，先上传一份 .md / .pdf / .docx / .xlsx');
    updateBatch();
    return;
  }
  $('kbBody').innerHTML=list.map(function(f){
    var t=typeOf(f.name), kws=f.keywords||[], kc=(f.keyword_count!=null?f.keyword_count:kws.length);
    var st=statusOf(f);
    return '<tr data-name="'+esc(f.name)+'"><td class="sel"><input type="checkbox" class="pick" data-name="'+esc(f.name)+'"'
      +(SEL[f.name]?' checked':'')+' aria-label="选择 '+esc(f.name)+'"></td>'
      +'<td><div class="fname"><span class="ftype '+esc(t.cls)+'">'+esc(t.ext)+'</span>'
      +'<span class="nm" title="'+esc(f.name)+'">'+esc(f.name)+'</span>'
      +'<span class="fstat '+st.cls+'" title="'+esc(st.tip)+'">'+esc(st.text)+'</span></div></td>'
      +'<td class="num"><span class="pill">'+f.chunks+'</span></td>'
      +'<td class="num"><button class="kw-btn" type="button" data-kw="'+esc(f.name)+'" title="'+(kws.length?esc(kws.join(' · ')):'暂无关键词')+'">'+(kc?kc:'—')+'</button></td>'
      +'<td class="num mono" style="font-size:12px;color:var(--muted)">'+fmtBytes(f.size)+'</td>'
      +'<td class="ts">'+esc(f.mtime||'—')+'</td>'
      +'<td><div class="row-actions">'
      +'<button class="btn ghost sm chk" data-name="'+esc(f.name)+'">分段</button>'
      +'<button class="btn ghost sm hist" data-name="'+esc(f.name)+'">历史</button>'
      +'<button class="btn ghost sm gen" data-name="'+esc(f.name)+'">出题</button>'
      +'<button class="btn danger-ghost sm del" data-name="'+esc(f.name)+'">删除</button>'
      +'</div></td></tr>';
  }).join('');
  renderKwMeta();
  updateBatch();
}
function renderKwMeta(){
  var kw=KB.keywords||{}, n=kw.terms||0;
  $('kbMeta').textContent=(KB.files||[]).length+' 份 · '+(KB.total_chunks||0)+' 块'
    +(KB.rebuilding?' · 索引重建中':'')
    +(n?(' · 关键词 '+n):'')+(KB.pending_changes?(' · 待审批 '+KB.pending_changes):'');
}
function closeKw(){
  var row=document.querySelector('.kw-row'); if(row) row.remove();
}
async function toggleKw(name,btn){
  var open=document.querySelector('.kw-row');
  if(open&&open.dataset.name===name){ open.remove(); return; }
  if(open) open.remove();
  var tr=document.createElement('tr'); tr.className='kw-row'; tr.dataset.name=name;
  tr.innerHTML='<td colspan="7"><div class="kw-box"><span class="kw-load">读取关键词…</span></div></td>';
  (btn.closest('tr')||btn.parentNode.parentNode).after(tr);
  try{
    var d=await (await fetch('/api/keywords?name='+encodeURIComponent(name))).json();
    var terms=(d.terms||[]).filter(function(t){ return t.kind!=='heading'; });
    var chips=terms.map(function(t){ return '<span class="kw-chip" title="'+esc(t.section)+'">'+esc(t.term)+'</span>'; }).join('');
    tr.querySelector('.kw-box').innerHTML=(d.summary?'<div class="kw-sum">'+esc(d.summary)+'</div>':'')
      +'<div class="kw-chips">'+(chips||'<span class="kw-empty">这份文档没有可直出的条目</span>')+'</div>';
  }catch(e){
    tr.querySelector('.kw-box').innerHTML='<span class="kw-empty">读取失败：'+esc(e.message||e)+'</span>';
  }
}


/* ---------- 审批与文档历史 ---------- */
var TOKEN_KEY='rag_admin_token';
function adminToken(){ try{ return sessionStorage.getItem(TOKEN_KEY)||''; }catch(e){ return ''; } }
function adminHeaders(){
  var h={'Content-Type':'application/json'}, t=adminToken();
  if(t) h['X-Admin-Token']=t;
  return h;
}
function openKbModal(title,html){
  $('kbModalTitle').textContent=title;
  $('kbModalBody').innerHTML=html;
  $('kbMask').hidden=false; $('kbModal').hidden=false;
}
function closeKbModal(){
  $('kbMask').hidden=true; $('kbModal').hidden=true; $('kbModalBody').innerHTML='';
}
function diffHtml(text){
  var nl=String.fromCharCode(10);
  return esc(text||'').split(nl).map(function(line){
    var cls='';
    if(line.indexOf('+++')===0||line.indexOf('---')===0) cls='meta';
    else if(line.charAt(0)==='+') cls='add';
    else if(line.charAt(0)==='-') cls='del';
    return '<span class="'+cls+'">'+line+'</span>';
  }).join(nl);
}
function actionText(a){ return a==='add'?'新增':(a==='delete'?'删除':'修改'); }
function renderApprovals(items){
  var panel=$('approvePanel');
  if(!items.length){ panel.hidden=true; $('apprList').innerHTML=''; return; }
  panel.hidden=false; $('apprCount').textContent=items.length;
  $('apprList').innerHTML=items.map(function(c){
    var files=(c.files||[]).map(function(f){ return actionText(f.action)+' '+f.name; });
    var dels=(c.deletes||[]).map(function(n){ return '删除 '+n; });
    var warn=(c.warnings||[]).length?'<div class="appr-files">注意：'+esc((c.warnings||[]).join('；'))+'</div>':'';
    return '<div class="appr-item">'
      +'<div class="appr-top"><b>'+esc(c.change_id||'')+'</b>'
      +'<span class="pill">'+esc(c.author||'—')+'</span>'
      +'<span class="ts">'+esc(String(c.created_at||'').replace('T',' ').slice(0,19))+'</span></div>'
      +'<div class="appr-files">'+esc(files.concat(dels).join('；')||'—')+(c.note?(' · '+esc(c.note)):'')+'</div>'+warn
      +'<div class="appr-actions">'
      +'<button class="btn ghost sm appr-diff" type="button" data-id="'+esc(c.change_id||'')+'">查看 diff</button>'
      +'<button class="btn sm appr-ok" type="button" data-id="'+esc(c.change_id||'')+'">通过</button>'
      +'<button class="btn danger-ghost sm appr-no" type="button" data-id="'+esc(c.change_id||'')+'">驳回</button>'
      +'</div></div>';
  }).join('');
}
async function loadApprovals(){
  try{
    var r=await (await fetch('/api/kb/changes?status=pending')).json();
    if(r.error){ $('approvePanel').hidden=true; return; }
    renderApprovals(r.items||[]);
  }catch(e){ $('approvePanel').hidden=true; }
}
async function showDiff(changeId){
  openKbModal('变更 '+changeId,'<div class="kw-load">读取 diff…</div>');
  try{
    var d=await (await fetch('/api/kb/change?id='+encodeURIComponent(changeId))).json();
    if(d.error){ $('kbModalBody').innerHTML='<div class="kw-empty">'+esc(d.error)+'</div>'; return; }
    var html=(d.diffs||[]).map(function(x){
      return '<div class="diff-title"><span class="pill">'+esc(actionText(x.action))+'</span><span class="mono">'+esc(x.name)+'</span>'
        +'<span class="muted">+'+x.added+' / -'+x.removed+'</span></div>'
        +'<pre class="diff">'+diffHtml(x.diff)+'</pre>';
    }).join('');
    $('kbModalBody').innerHTML=html||'<div class="kw-empty">没有文本差异</div>';
  }catch(e){ $('kbModalBody').innerHTML='<div class="kw-empty">读取失败：'+esc(e.message||e)+'</div>'; }
}
async function decide(changeId,kind){
  var body={change_id:changeId};
  if(kind==='reject'){
    var reason=window.prompt('驳回原因（可选）','')||'';
    body.reason=reason;
  }
  setMsg(kind==='approve'?'正在通过 '+changeId+'…':'正在驳回 '+changeId+'…');
  try{
    var resp=await fetch(kind==='approve'?'/api/kb/approve':'/api/kb/reject',
      {method:'POST',headers:adminHeaders(),body:JSON.stringify(body)});
    var d=await resp.json();
    if(resp.status===403){ $('apprToken').hidden=false; setMsg('需要管理员令牌，请在面板下方填写','err'); return; }
    if(!resp.ok){ setMsg('操作失败：'+(d.error||('HTTP '+resp.status)),'err'); return; }
    setMsg(kind==='approve'?('已通过，新版本 '+(d.version||'')):'已驳回','ok');
    toast(kind==='approve'?'变更已通过':'变更已驳回');
    await settleIndex(kind==='approve'&&d.rebuilding, kind==='approve'?'变更已通过':'已驳回');
  }catch(e){ setMsg('操作失败：'+(e.message||e),'err'); }
}
async function openHistory(name){
  openKbModal('历史版本 · '+name,'<div class="kw-load">读取中…</div>');
  try{
    var d=await (await fetch('/api/kb/doc_history?name='+encodeURIComponent(name))).json();
    if(d.error){ $('kbModalBody').innerHTML='<div class="kw-empty">'+esc(d.error)+'</div>'; return; }
    var items=(d.items||[]).slice().reverse();
    $('kbModalBody').innerHTML=items.length?items.map(function(v){
      var cur=(v.version===KB.version);
      return '<div class="hist-item"><b class="mono">'+esc(v.version)+'</b>'
        +'<span class="ts">'+esc(String(v.created_at||'').slice(0,10))+'</span>'
        +'<span class="pill">'+esc(v.kind||'')+'</span>'
        +'<span class="muted">'+fmtBytes(v.size)+'</span>'
        +'<span style="margin-left:auto"><button class="btn ghost sm hist-rb" type="button" data-name="'+esc(name)+'" data-v="'+esc(v.version)+'"'
        +(cur?' disabled':'')+'>'+(cur?'当前版本':'回滚到此版本')+'</button></span></div>';
    }).join(''):'<div class="kw-empty">没有历史版本</div>';
  }catch(e){ $('kbModalBody').innerHTML='<div class="kw-empty">读取失败：'+esc(e.message||e)+'</div>'; }
}
async function rollbackTo(name,version){
  if(!confirm('把「'+name+'」回滚到 '+version+'？会生成一个新版本，历史不改。')) return;
  try{
    var resp=await fetch('/api/kb/rollback_doc',{method:'POST',headers:adminHeaders(),
      body:JSON.stringify({name:name,to_version:version})});
    var d=await resp.json();
    if(resp.status===403){ $('apprToken').hidden=false; closeKbModal(); setMsg('需要管理员令牌','err'); return; }
    if(!resp.ok){ toast('回滚失败：'+(d.error||''),true); return; }
    closeKbModal(); setMsg('已回滚到 '+version+'，新版本 '+(d.version||''),'ok');
    toast('已回滚，新版本 '+(d.version||''));
    await settleIndex(d.rebuilding, '已回滚');
  }catch(e){ toast('回滚失败：'+(e.message||e),true); }
}

async function loadKb(){
  try{
    var r=await (await fetch('/api/knowledge')).json();
    KB=r;
    // 文档被别处删掉后，残留的勾选会让「删除选中」带上已经不存在的文件名
    var alive={};
    (KB.files||[]).forEach(function(f){ alive[f.name]=true; });
    Object.keys(SEL).forEach(function(n){ if(!alive[n]) delete SEL[n]; });
    render(); await loadApprovals();
  }catch(e){ setMsg('加载失败：'+(e.message||e),'err'); }
}

/* ---------- 后台重建索引 ----------
   入库接口只等版本落盘，索引在后台建；轮询到重建结束再刷新列表，
   否则刚上传的文档会短暂显示 0 块，像是没入库。 */
async function waitRebuild(timeoutMs){
  var deadline=Date.now()+(timeoutMs||90000);
  while(Date.now()<deadline){
    try{
      var h=await (await fetch('/api/health')).json();
      var ix=h.index||{};
      if(!ix.rebuilding) return ix;
    }catch(e){}
    await new Promise(function(r){setTimeout(r,700);});
  }
  return null;
}
async function settleIndex(rebuilding,label){
  if(rebuilding){
    setMsg((label||'已入库')+'，正在后台重建索引…');
    var ix=await waitRebuild();
    if(!ix){ setMsg((label||'已入库')+'；索引仍在重建，请稍后刷新',''); return; }
    if(ix.last_error){ setMsg('索引重建失败：'+ix.last_error,'err'); toast('索引重建失败，旧索引仍在服务',true); }
    else{ toast('索引已重建：'+(ix.chunks||0)+' 块'); }
  }
  await loadKb();
}

/* ---------- 上传 ---------- */
function b64(buf){
  var bytes=new Uint8Array(buf), chunk=0x8000, out='';
  for(var i=0;i<bytes.length;i+=chunk){ out+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk)); }
  return btoa(out);
}
async function uploadOne(f){
  var name=f.name||'upload';
  var ext=(name.split('.').pop()||'').toLowerCase();
  if(['md','txt','pdf','docx','xlsx','csv','tsv'].indexOf(ext)<0){
    throw new Error('不支持 .'+ext+'，只接受 .md / .txt / .pdf / .docx / .xlsx / .csv / .tsv');
  }
  var isDoc=(['pdf','docx','xlsx'].indexOf(ext)>=0);
  if(isDoc&&f.size>6*1024*1024) throw new Error('超过 6 MB 上限');
  if(!isDoc&&f.size>512*1024) throw new Error('超过 512 KB 上限');
  if(isDoc){
    var buf=await f.arrayBuffer();
    return await (await fetch('/api/knowledge/upload_file',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:name,data_b64:b64(buf)})})).json();
  }
  var text=await f.text();
  return await (await fetch('/api/knowledge/upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name,content:text})})).json();
}
async function uploadFiles(files){
  var arr=[].slice.call(files||[]);
  if(!arr.length||BUSY) return;
  BUSY=true;
  var ok=0, fail=0, added=0, pend=0, rebuilding=false, firstErr='', notes=[], warns=[];
  for(var i=0;i<arr.length;i++){
    setMsg('上传中 '+(i+1)+'/'+arr.length+'：'+arr[i].name);
    try{
      var r=await uploadOne(arr[i]);
      if(r&&r.ok){
        ok++; added+=r.added_chunks||0; if(r.pending) pend++;
        if(r.rebuilding) rebuilding=true;
        /* 同名覆盖是"写成功了但旧内容没了"，比失败更需要说清楚 */
        if(r.warnings&&r.warnings.length){ [].push.apply(warns, r.warnings); }
        var bits=[];
        if(r.format) bits.push(String(r.format).toUpperCase());
        if(r.rows) bits.push(r.rows+' 行');
        else if(r.pages) bits.push(r.pages+' 页');
        if(r.sheets&&r.sheets.length) bits.push(r.sheets.length+' 个表');
        if(bits.length) notes.push(arr[i].name+'（'+bits.join(' · ')+'）');
      }
      else{ fail++; if(!firstErr) firstErr=(r&&r.error)||'未知错误'; }
    }catch(e){ fail++; if(!firstErr) firstErr=e.message||String(e); }
  }
  BUSY=false;
  if(ok){
    if(pend){
      setMsg('已提交 '+pend+' 份待审批'+(fail?('，失败 '+fail+' 份（'+firstErr+'）'):'')+'；审批通过后才会进入检索', fail?'':'ok');
      toast('已提交 '+pend+' 份，等待审批');
    }else{
      var tail=(ok===1&&notes.length)?('：'+notes[0]):'';
      var count=rebuilding?'':('，新增 '+added+' 块');
      setMsg('已入库 '+ok+' 份'+tail+count+(fail?('，失败 '+fail+' 份（'+firstErr+'）'):''), fail?'':'ok');
      toast('已入库 '+ok+' 份'+(rebuilding?'，索引重建中':'，新增 '+added+' 块'));
    }
    await settleIndex(rebuilding&&!pend, '已入库 '+ok+' 份');
    if(warns.length){
      /* 覆盖提示单独一条，且用 warn 样式：它不会自动消失，用户必须看到"旧版本被替换了" */
      setMsg(warns.join('；')+'。旧版本在「版本」里可以回滚。','warn');
      toast('已覆盖同名文档，可在版本历史回滚', true);
    }
  }else{
    setMsg('上传失败：'+firstErr,'err');
    toast('上传失败：'+firstErr,true);
  }
}

/* ---------- 分段抽屉 ----------
   分段是「切分结果」的唯一可见形态：用户要判断的是「这块切得对不对」，
   所以序号、页码、字数、正文开头缺一样都不行。整页跳转太重，抽屉刚好。 */
var CK={name:'', items:[]};
function ckOpen(){
  $('ckMask').hidden=false; $('ckDrawer').hidden=false;
  requestAnimationFrame(function(){ $('ckDrawer').classList.add('open'); });
}
function ckClose(){
  $('ckDrawer').classList.remove('open');
  $('ckDrawer').hidden=true; $('ckMask').hidden=true;
  $('ckResult').hidden=true; $('ckResult').innerHTML='';
}
async function openChunks(name){
  CK={name:name, items:[]};
  $('ckTitle').textContent=name;
  $('ckSub').textContent='读取分段…';
  $('ckList').innerHTML='<div class="ck-empty">读取中…</div>';
  $('ckResult').hidden=true;
  ckOpen();
  try{
    var r=await fetch('/api/knowledge/chunks?name='+encodeURIComponent(name));
    var d=await r.json();
    if(!r.ok) throw new Error(d.error||('HTTP '+r.status));
    CK.items=d.items||[];
    var avg=0;
    if(CK.items.length){
      var sum=0; CK.items.forEach(function(x){ sum+=x.chars; }); avg=Math.round(sum/CK.items.length);
    }
    $('ckSub').textContent=CK.items.length+' 块 · '+(d.page_count?d.page_count+' 页 · ':'')+'平均 '+avg+' 字/块'
      +(d.truncated?'':'');
    if(!CK.items.length){ $('ckList').innerHTML='<div class="ck-empty">这份文档没有可显示的分段</div>'; return; }
    $('ckList').innerHTML=CK.items.map(function(x){
      return '<div class="ck-item"><button type="button" class="ck-row" data-i="'+x.chunk_index+'">'
        +'<span class="ck-no">#'+(x.chunk_index+1)+'</span>'
        +'<span class="ck-meta">'+(x.page?'第 '+x.page+' 页 · ':'')+x.chars+' 字</span>'
        +'<span class="ck-sec">'+esc(x.section||'')+'</span></button>'
        +'<pre class="ck-text" hidden>'+esc(x.text)+(x.truncated?'\n…（已截断，完整原文点引用查看）':'')+'</pre></div>';
    }).join('');
  }catch(e){
    $('ckSub').textContent='读取失败';
    $('ckList').innerHTML='<div class="ck-empty">'+esc(e.message||e)
      +'<br>文档刚上传时索引可能还在重建，等几秒再试。</div>';
  }
}
/* 「用这份文档测一次」：不是全库检索，而是把 doc 交给检索调试，
   这样「这份文档能不能答这个问题」才有确定答案。 */
async function runDocTest(){
  var q=($('ckQ').value||'').trim();
  if(!q){ toast('先写一个要试的问题',true); return; }
  var box=$('ckResult');
  box.hidden=false; box.innerHTML='<div class="ck-empty">检索中…</div>';
  try{
    var r=await fetch('/api/search/debug',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:q,doc:CK.name})});
    var d=await r.json();
    if(!r.ok) throw new Error(d.message||d.error||('HTTP '+r.status));
    var rows=(d.candidates||[]).map(function(c){
      return '<div class="ck-hit'+(c.kept?'':' off')+'"><span class="ck-h-sc">'+esc(Math.round(c.score*1000)/1000)+'</span>'
        +'<span class="ck-h-sec">#'+(c.chunk_index+1)+(c.page?' · 第 '+c.page+' 页':'')+' '+esc(c.section||'')+'</span>'
        +'<span class="ck-h-tag">'+(c.kept?'采用':'被挡')+'</span></div>';
    }).join('');
    box.innerHTML='<div class="ck-h-head">本文档命中 '+d.kept+' / '+d.recalled+' 块 · 阈值 '+esc(d.min_score)
      +(d.degraded?' · <span class="warn">检索降级：'+esc(d.degrade_reason||'')+'</span>':'')+'</div>'
      +(rows||'<div class="ck-empty">这份文档里没有相关分段——要么切分没切到，要么文档确实没写这件事</div>');
  }catch(e){
    box.innerHTML='<div class="ck-empty">检索失败：'+esc(e.message||e)+'</div>';
  }
}

/* ---------- 空库模板 ----------
   空库只给一个上传框，用户不知道该放什么。模板直接复用仓库里的演示文档，
   与 docs/README 里截图示意的内容是同一份，不会出现「示例和实际对不上」。 */
async function seedTemplate(tpl,btn){
  if(BUSY) return;
  BUSY=true; btn.disabled=true;
  setMsg('正在导入模板…');
  try{
    var r=await (await fetch('/api/kb/seed',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({template:tpl})})).json();
    if(!r.ok){ setMsg('导入失败：'+(r.message||r.error||''),'err'); btn.disabled=false; BUSY=false; return; }
    var msg=r.added&&r.added.length?('已导入 '+r.added.length+' 份'):(r.message||'已在库中');
    setMsg(msg+(r.pending?'，等待审批':'')+'。',r.pending?'':'ok');
    toast(msg);
    btn.disabled=false; BUSY=false;
    await settleIndex(r.rebuilding&&!r.pending, msg);
  }catch(e){
    setMsg('导入失败：'+(e.message||e),'err'); toast('导入失败',true); btn.disabled=false; BUSY=false;
  }
}

/* ---------- 批量操作 ----------
   批量删除逐份调用单删接口：一次失败不会连坐，进度和失败原因都能说清。
   整体回滚在这里反而是错的——已删的文档在版本库里仍可找回。 */
async function batchDelete(){
  var names=Object.keys(SEL);
  if(!names.length) return;
  if(!confirm('确认删除选中的 '+names.length+' 份文档？索引会重新构建，删掉的仍可在「版本」里找回。\n\n'
    +names.slice(0,8).join('\n')+(names.length>8?'\n…':''))) return;
  var ok=0, fail=[];
  BUSY=true;
  for(var i=0;i<names.length;i++){
    setMsg('删除中 '+(i+1)+'/'+names.length+'：'+names[i]);
    try{
      var d=await (await fetch('/api/knowledge/delete',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:names[i]})})).json();
      if(d.ok){ ok++; delete SEL[names[i]]; } else { fail.push(names[i]+'：'+(d.error||'失败')); }
    }catch(e){ fail.push(names[i]+'：'+(e.message||e)); }
  }
  BUSY=false;
  setMsg('已删除 '+ok+' 份'+(fail.length?('，失败 '+fail.length+' 份（'+fail[0]+'）'):''),fail.length?'err':'ok');
  updateBatch();
  await settleIndex(true,'已删除 '+ok+' 份');
}
async function batchRebuild(){
  if(!Object.keys(SEL).length) return;
  var btn=$('kbBatchRebuild'); btn.disabled=true;
  setMsg('正在按当前文档重建索引…');
  try{
    var r=await (await fetch('/api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    if(r.ok){ await settleIndex(true,'已开始重建'); }
    else{ setMsg('重建失败：'+r.error,'err'); }
  }catch(e){ setMsg('重建失败：'+(e.message||e),'err'); }
  btn.disabled=false;
  clearSel();
}

/* ---------- 事件 ---------- */
$('kbFile').onchange=function(){ var fs=[].slice.call(this.files||[]); this.value=''; uploadFiles(fs); };
$('drop').onclick=function(e){ if(e.target.id!=='kbFile') $('kbFile').click(); };
['dragenter','dragover'].forEach(function(ev){
  $('drop').addEventListener(ev,function(e){ e.preventDefault(); $('drop').classList.add('over'); });
});
['dragleave','drop'].forEach(function(ev){
  $('drop').addEventListener(ev,function(e){ e.preventDefault(); $('drop').classList.remove('over'); });
});
$('drop').addEventListener('drop',function(e){
  if(e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});

$('kbSearch').addEventListener('input',function(){ Q=this.value; render(); });
$('kbFilters').onclick=function(e){
  var b=e.target.closest('button[data-type]'); if(!b) return;
  FILTER=b.dataset.type;
  [].slice.call(this.children).forEach(function(x){ x.classList.toggle('on',x===b); });
  render();
};
$('kbSort').onchange=function(){ SORT=this.value; render(); };

$('kbModalBody').onclick=function(ev){
  var b=ev.target.closest('.hist-rb');
  if(b && !b.disabled){ rollbackTo(b.dataset.name,b.dataset.v); }
};
$('kbBody').onclick=async function(ev){
  var pick=ev.target.closest('.pick');
  if(pick){
    if(pick.checked) SEL[pick.dataset.name]=true; else delete SEL[pick.dataset.name];
    updateBatch();
    return;
  }
  var ck=ev.target.closest('.chk');
  if(ck){ await openChunks(ck.dataset.name); return; }
  var kw=ev.target.closest('.kw-btn');
  if(kw){ await toggleKw(kw.dataset.kw, kw); return; }
  var h=ev.target.closest('.hist');
  if(h){ await openHistory(h.dataset.name); return; }
  var g=ev.target.closest('.gen');
  if(g){
    var n=parseInt(window.prompt('为「'+g.dataset.name+'」生成几条评测用例？（1-8）','3'),10)||3;
    setMsg('正在为「'+g.dataset.name+'」出题…');
    try{
      var r=await (await fetch('/api/cases/from_doc',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:g.dataset.name,n:n})})).json();
      if(r.ok){ setMsg('已生成 '+r.added+' 条用例（'+r.mode+'），可在评测看板运行','ok'); toast('已生成 '+r.added+' 条用例'); }
      else{ setMsg('出题失败：'+(r.error||''),'err'); }
    }catch(e){ setMsg('出题失败：'+(e.message||e),'err'); }
    return;
  }
  var b=ev.target.closest('.del');
  if(!b) return;
  if(!confirm('确认删除「'+b.dataset.name+'」？索引会立即重建，对应文档用例将在下次运行时跳过。')) return;
  try{
    var d=await (await fetch('/api/knowledge/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:b.dataset.name})})).json();
    if(d.ok){ setMsg('已删除 '+d.name,'ok'); toast('已删除：'+d.name); await settleIndex(d.rebuilding,'已删除'); }
    else{ setMsg('删除失败：'+(d.error||''),'err'); }
  }catch(e){ setMsg('删除失败：'+(e.message||e),'err'); }
};

$('apprRefresh').onclick=loadApprovals;
$('kbAll').onchange=function(){
  var on=this.checked;
  visibleFiles().forEach(function(f){ if(on) SEL[f.name]=true; else delete SEL[f.name]; });
  render();
};
$('kbBatchDel').onclick=batchDelete;
$('kbBatchRebuild').onclick=batchRebuild;
$('kbBatchClear').onclick=function(){ clearSel(); render(); };
$('kbSeed').onclick=function(ev){
  var b=ev.target.closest('.seed-card'); if(!b) return;
  seedTemplate(b.dataset.tpl,b);
};
$('ckClose').onclick=ckClose;
$('ckMask').onclick=ckClose;
$('ckRun').onclick=runDocTest;
$('ckQ').addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); runDocTest(); } });
$('ckList').onclick=function(ev){
  var row=ev.target.closest('.ck-row'); if(!row) return;
  var pre=row.nextElementSibling;
  if(pre) pre.hidden=!pre.hidden;
};
$('adminSave').onclick=function(){
  var v=($('adminToken').value||'').trim();
  try{
    if(v) sessionStorage.setItem(TOKEN_KEY,v); else sessionStorage.removeItem(TOKEN_KEY);
  }catch(e){}
  $('apprToken').hidden=true; toast(v?'令牌已保存':'令牌已清除'); loadApprovals();
};
$('apprList').onclick=function(ev){
  var d=ev.target.closest('.appr-diff'); if(d){ showDiff(d.dataset.id); return; }
  var a=ev.target.closest('.appr-ok'); if(a){ decide(a.dataset.id,'approve'); return; }
  var r=ev.target.closest('.appr-no'); if(r){ decide(r.dataset.id,'reject'); }
};
$('kbModalClose').onclick=closeKbModal;
$('kbMask').onclick=closeKbModal;
document.addEventListener('keydown',function(e){ if(e.key==='Escape'){ closeKbModal(); ckClose(); } });

$('reload').onclick=async function(){
  var btn=this; btn.disabled=true; setMsg('正在重建索引…');
  try{
    var r=await (await fetch('/api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    if(r.ok){
      if(r.rebuilding){ setMsg('正在后台重建索引…'); await settleIndex(true,'已开始重建'); }
      else{ setMsg('索引已重建：'+r.chunks+' 个知识块','ok'); toast('已加载 '+r.chunks+' 块'); await loadKb(); }
      btn.disabled=false;
    }
    else{ setMsg('重建失败：'+r.error,'err'); btn.disabled=false; }
  }catch(e){ setMsg('重建失败：'+(e.message||e),'err'); btn.disabled=false; }
};

/* ---------- 笔记分区 ----------
   数据全部走 /api/notes：列表读索引，编辑走 PATCH + rev 乐观锁，
   删除只进 .trash。页面不缓存笔记内容，避免和磁盘上的手改打架。 */

/* 笔记统一到 /files：知识库只留文档。旧链接 /kb#notes 直接送过去 */
if(location.hash==='#notes'){ location.replace('/notes'); }

loadKb();

// 「接入配置」直接打开智能体面板：文档里写十遍不如点一下看到能粘的东西
(function(){
  var btn=document.getElementById('agOpen');
  if(!btn) return;
  btn.addEventListener('click',function(){
    if(window.__openAgent) window.__openAgent();
  });
})();
