
var qEl=document.getElementById('q'), sendBtn=document.getElementById('send'), list=document.getElementById('list');
var busy=false, LLM_READY=null;
var SESSION_KEY='rag_session_id';
function newSessionId(){
  try{ if(window.crypto&&crypto.randomUUID) return crypto.randomUUID(); }catch(e){}
  return 's'+Date.now().toString(36)+Math.random().toString(16).slice(2,10);
}
function loadSessionId(){
  try{ return sessionStorage.getItem(SESSION_KEY)||newSessionId(); }catch(e){ return newSessionId(); }
}
function saveSessionId(id){ try{ sessionStorage.setItem(SESSION_KEY,id); }catch(e){} }
var SESSION_ID=loadSessionId(); saveSessionId(SESSION_ID);

/* ---------- API Key ----------
   配置 API_KEYS 后，问答接口需要 Key；页面把 Key 放 sessionStorage，
   只在当前标签页有效，关闭即清。 */
var KEY_STORE='rag_api_key';
function apiKey(){ return ragApiKey(); }
function showKeyBar(msg){
  var bar=document.getElementById('keyBar'); if(!bar) return;
  bar.hidden=false;
  if(msg) document.getElementById('keyNote').textContent=msg;
}
function bindKeyBar(){
  var bar=document.getElementById('keyBar'), input=document.getElementById('apiKey');
  if(!bar||!input) return;
  input.value=apiKey();
  document.getElementById('keySave').onclick=function(){
    var v=(input.value||'').trim();
    try{ if(v) sessionStorage.setItem(KEY_STORE,v); else sessionStorage.removeItem(KEY_STORE); }catch(e){}
    document.getElementById('keyNote').textContent=v?'已保存，下次请求携带':'已清除';
    if(v) bar.hidden=true;
  };
  input.onkeydown=function(e){ if(e.key==='Enter'){ e.preventDefault(); document.getElementById('keySave').click(); } };
  fetch('/api/health').then(function(r){ return r.json(); }).then(function(h){
    if(h.auth&&h.auth.mode==='key'&&!apiKey()) showKeyBar('需填写 API Key 才能提问');
  }).catch(function(){});
}
var MODE={llm:'模型生成',extractive:'抽取式',extractive_fallback:'降级抽取',keyword_local:'本地关键词'};
var BEHAVIOR={answer:['作答','ok'],ask_clarify:['追问澄清','brand'],no_answer:['未找到','warn'],refuse:['拒答','bad']};
var ART='{{_ASK_ART}}';

function scrollBottom(){ list.scrollTop=list.scrollHeight; }
function autoGrow(){ qEl.style.height='auto'; qEl.style.height=Math.min(qEl.scrollHeight,124)+'px'; }

var heroEl=document.getElementById('hero'), exLoaded=false;
function renderEmpty(){
  if(heroEl) heroEl.hidden=false;
  if(!exLoaded) loadExamples();
}
async function loadExamples(){
  var box=document.getElementById('exCards');
  if(!box||exLoaded) return;
  exLoaded=true;
  try{
    var r=await (await fetch('/api/examples?n=4')).json();
    (r.items||[]).slice(0,4).forEach(function(t){
      var b=document.createElement('button'); b.type='button'; b.className='ex-card';
      b.textContent=t;
      b.onclick=function(){ qEl.value=t; autoGrow(); ask(); };
      box.appendChild(b);
    });
  }catch(e){ exLoaded=false; }
}

/* ---------- 渲染 ---------- */
function addUser(text){
  var d=document.createElement('div'); d.className='msg user';
  var b=document.createElement('div'); b.className='bubble'; b.textContent=text;
  d.appendChild(b); list.appendChild(d);
}
function addBot(){
  var d=document.createElement('div'); d.className='msg bot';
  var a=document.createElement('div'); a.className='avatar';
  a.innerHTML='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 2.2 5.6L20 10.8l-4.4 3.9L16.9 21 12 17.8 7.1 21l1.3-6.3L4 10.8l5.8-2.2z"/></svg>';
  var body=document.createElement('div'); body.className='msg-body';
  d.appendChild(a); d.appendChild(body); list.appendChild(d);
  return body;
}
function thinkingHTML(text){
  return '<div class="ans-card"><div class="thinking"><span class="dots"><i></i><i></i><i></i></span>'
    +'<span class="think-text">'+esc(text)+'</span></div>'
    +'<div class="sk" style="margin-top:13px;width:92%"></div>'
    +'<div class="sk" style="margin-top:7px;width:72%"></div></div>';
}
function pill(text,cls){
  return '<span class="pill'+(cls?' '+cls:'')+'">'+esc(text)+'</span>';
}
/* 轻量 Markdown：只处理 **加粗** 与 [n] 引用，其余按纯文本保留换行 */
function fmtAnswer(t){
  var s=esc(t);
  s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/\[(\d+)\]/g,'<span class="cite-n">$1</span>');
  return s;
}
function round(v,digits){
  if(v==null||v===''||isNaN(v)) return '-';
  var p=Math.pow(10,digits==null?2:digits);
  return String(Math.round(Number(v)*p)/p);
}
/* 元信息：这条答案出自哪版文档、引了几条、覆盖多少、检索分多少。
   没有这些，用户只能“相信”答案；有了这些，能判断该不该信。 */
function footHTML(d){
  var html='<div class="ans-foot">';
  var ms=(d.latency_ms==null?'-':Math.round(d.latency_ms))+' ms';
  if(d.behavior!=='answer'){
    if(d.behavior==='no_answer'&&d.gate_score!=null){
      html+=pill('最高分 '+round(d.gate_score,3)+' / 阈值 '+round(d.min_score,2),'warn');
    }
    if(d.kb_version){ html+=pill('知识库 '+d.kb_version); }
    return html+pill(ms)+'</div>';
  }
  if(d.path==='keyword'){
    html+=pill('本地直出 · 未调用模型','ok')+pill(ms);
  }else{
    if(LLM_READY===false){ html+=pill('离线抽取','warn'); }
    else { html+='<span class="pill brand">'+esc(d.channel||'-')+' / '+esc(d.model||'-')+'</span>'; }
    html+=pill('模式 '+(MODE[d.mode]||d.mode||'-'))+pill(ms);
    if(d.retrieval_score!=null){ html+=pill('检索分 '+round(d.retrieval_score,3)); }
  }
  if(d.citations&&d.citations.length){ html+=pill('引用 '+d.citations.length+' 条'); }
  if(d.citation_coverage!=null&&d.citation_coverage<0.999){
    html+=pill('引用覆盖 '+Math.round(d.citation_coverage*100)+'%','warn');
  }
  if(d.kb_version){ html+=pill('知识库 '+d.kb_version); }
  if(d.degraded){ html+=pill('降级','warn'); }
  if(d.degrade_reason==='budget_exceeded'){ html+=pill('预算上限','warn'); }
  if(d.citation_exempt_reason){ html+=pill('引用豁免'); }
  return html+'</div>';
}
function similarHTML(items){
  if(!items||!items.length) return '';
  return '<div class="sim"><div class="sim-title">相似问题</div><div class="sim-list">'
    +items.map(function(t){ return '<button type="button" class="sim-q">'+esc(t)+'</button>'; }).join('')
    +'</div></div>';
}
function answerHTML(d){
  var local=d.path==='keyword';
  var head=d.behavior==='no_answer'?'未找到答案':(d.behavior==='refuse'?'拒答':(d.behavior==='ask_clarify'?'需要澄清':(local?'本地直出':'回答')));
  // 正常作答时不加标题：用户已经知道这是回答，「回答/作答」两个标签只是噪音。
  // 未找到、拒答、澄清这类需要区分的结果才露一行。
  var label='';
  if(d.behavior!=='answer'&&d.behavior&&BEHAVIOR[d.behavior]){
    label='<span class="pill '+BEHAVIOR[d.behavior][1]+'">'+BEHAVIOR[d.behavior][0]+'</span>';
  }
  if(d.turn>1) label+='<span class="pill">第 '+d.turn+' 轮</span>';
  var h='<div class="ans-card">'+(label?'<div class="ans-label">'+label+'</div>':'')+'<div class="ans-label-sr" hidden>'+head+'</div>';
  if(local&&d.keyword_terms&&d.keyword_terms.length){
    h+='<div class="kw-hit"><span class="kw-hit-t">命中</span>'
      +d.keyword_terms.map(function(t){ return '<span class="kw-term">'+esc(t)+'</span>'; }).join('')+'</div>';
  }
  h+='<div class="answer">'+fmtAnswer(d.answer)+'</div>';
  if(d.citations&&d.citations.length){
    h+='<div class="refs">'+d.citations.map(function(c){
      return '<button type="button" class="ref" data-doc="'+esc(c.doc_id||'')+'" data-chunk="'+(c.chunk_index==null?'':c.chunk_index)+'"'
        +' data-snippet="'+esc(c.snippet||'')+'" title="查看原文"><b>'+esc(c.ref)+'</b>'+esc(c.title)+' · '+esc(c.section)+'</button>';
    }).join('')+'</div>';
  }
  if(d.retrieved&&d.retrieved.length){
    h+='<details class="src"><summary>'
      +'<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>'
      +(local?'命中依据':'检索依据')+' '+d.retrieved.length+' 条</summary><div class="src-list">'
      +d.retrieved.map(function(x,i){
        var sc=(x.score==null)?'-':(Math.round(x.score*1000)/1000);
        return '<div class="src-row"><span class="rank">'+String(i+1).padStart(2,'0')+'</span>'
          +'<span>'+esc(x.title)+' · '+esc(x.section)+'</span><span class="sc">score '+sc+'</span></div>';
      }).join('')+'</div></details>';
  }
  h+=similarHTML(d.similar_questions);
  h+=footHTML(d)+'</div>';
  return h;
}
function bindSource(){
  var drawer=document.getElementById('srcDrawer'), mask=document.getElementById('srcMask');
  var titleEl=document.getElementById('srcTitle'), subEl=document.getElementById('srcSub');
  var textEl=document.getElementById('srcText');
  function close(){
    drawer.classList.remove('open');
    drawer.hidden=true; mask.hidden=true; textEl.textContent='';
  }
  async function open(btn){
    var doc=btn.dataset.doc, chunk=btn.dataset.chunk, snippet=btn.dataset.snippet||'';
    if(!doc||chunk===''){ toast('这条引用缺少原文定位',true); return; }
    mask.hidden=false; drawer.hidden=false;
    requestAnimationFrame(function(){ drawer.classList.add('open'); });
    titleEl.textContent='读取原文…'; subEl.textContent=''; textEl.textContent='';
    try{
      var r=await fetch('/api/source?doc='+encodeURIComponent(doc)+'&chunk='+encodeURIComponent(chunk));
      var d=await r.json();
      if(!r.ok) throw new Error(d.error||('HTTP '+r.status));
      titleEl.textContent=d.title||doc;
      subEl.textContent=(d.section||'')+' · 第 '+(d.chunk_index+1)+'/'+d.doc_chunks+' 块'+(d.version?' · '+d.version:'');
      var safe=esc(d.text||'');
      var needle=esc(snippet);
      if(needle && safe.indexOf(needle)>=0){ safe=safe.replace(needle,'<mark>'+needle+'</mark>'); }
      textEl.innerHTML=safe;
    }catch(e){
      titleEl.textContent='读取失败'; textEl.textContent=String(e.message||e);
    }
  }
  document.getElementById('srcClose').onclick=close;
  mask.onclick=close;
  return {open:open, close:close};
}
var sourceView=bindSource();

var NL=String.fromCharCode(10);
function copyText(text,okMsg){
  if(!text){ toast('没有可复制的内容',true); return; }
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){toast(okMsg||'已复制');},function(){toast('复制失败',true);});
  }else{ toast('当前浏览器不支持剪贴板',true); }
}
function downloadText(name,text,mime){
  try{
    var blob=new Blob([text],{type:(mime||'text/markdown')+';charset=utf-8'});
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=name;
    document.body.appendChild(a); a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); },1000);
  }catch(e){ toast('导出失败：'+(e.message||e),true); }
}

/* ---------- 会话历史：刷新不丢 ----------
   页面上的对话是本地记录，和服务端 3 轮上下文是两件事：
   前者为了「回看/导出」，后者为了「追问改写」。所以 history 存 localStorage，
   只保留渲染需要的字段，并对长答案截断，避免把 localStorage 写满。 */
function cutText(v,n){
  var t=String(v==null?'':v);
  return t.length>n?(t.slice(0,n)+'…'):t;
}
function slimTurn(q,d){
  return {
    q:cutText(q,300),
    ts:d.ts||new Date().toISOString(),
    d:{
      trace_id:d.trace_id, behavior:d.behavior, path:d.path, mode:d.mode,
      answer:cutText(d.answer,6000),
      citations:(d.citations||[]).slice(0,8),
      retrieved:(d.retrieved||[]).slice(0,4),
      similar_questions:(d.similar_questions||[]).slice(0,3),
      keyword_terms:(d.keyword_terms||[]).slice(0,6),
      latency_ms:d.latency_ms, turn:d.turn, channel:d.channel, model:d.model,
      degraded:d.degraded, degrade_reason:d.degrade_reason,
      citation_coverage:d.citation_coverage, citation_exempt_reason:d.citation_exempt_reason,
      retrieval_score:d.retrieval_score, gate_score:d.gate_score, min_score:d.min_score,
      kb_version:d.kb_version, session_id:d.session_id
    }
  };
}
function threadTurns(){
  var t=window.JY?JY.currentThread():null;
  return (t&&Array.isArray(t.turns))?t.turns:[];
}
function setTitle(t){
  var name=(t&&t.title)?t.title:'新对话';
  var el=document.getElementById('tbTitle'); if(el) el.textContent=name;
  var sub=document.getElementById('tbSub');
  var n=(t&&t.turns)?t.turns.length:0;
  if(sub) sub.textContent=n?(n+' 轮 · 只依据知识库作答'):'';
}
function renderThread(){
  var t=window.JY?JY.currentThread():null;
  var turns=(t&&t.turns)||[];
  list.innerHTML='';
  if(!turns.length){ setTitle(t); renderEmpty(); return; }
  if(heroEl) heroEl.hidden=true;
  turns.slice(-12).forEach(function(x){
    if(!x||!x.d) return;
    addUser(x.q);
    var body=addBot();
    body.innerHTML=answerHTML(x.d);
    if(x.d.behavior==='answer'){ bindFeedback(body,x.d,x.q); }
    else if(x.d.behavior==='no_answer'){ bindMissFeedback(body,x.d,x.q); }
  });
  setTitle(t);
  scrollBottom();
}
function rememberTurn(q,d){
  if(!d||!d.behavior||d.behavior==='ask_clarify') return;
  if(!window.JY) return;
  JY.append(slimTurn(q,d));
  if(d.session_id) JY.touch({sid:d.session_id});
  setTitle(JY.currentThread());
}
function stamp(){
  var d=new Date();
  function p(n){ return (n<10?'0':'')+n; }
  return d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+'-'+p(d.getHours())+p(d.getMinutes());
}
function exportMarkdown(){
  var rows=threadTurns();
  if(!rows.length){ toast('还没有对话可以导出',true); return; }
  var out=['# 问答记录','','导出时间：'+new Date().toLocaleString(),'轮次：'+rows.length,''];
  rows.forEach(function(t,i){
    var d=t.d||{};
    out.push('## '+(i+1)+'. '+t.q,'');
    var meta=[d.behavior||'',d.mode||'',d.kb_version||'',t.ts||''].filter(Boolean).join(' · ');
    if(meta) out.push('> '+meta,'');
    out.push(d.answer||'','');
    if(d.citations&&d.citations.length){
      out.push('**引用**','');
      d.citations.forEach(function(c){
        out.push('- ['+c.ref+'] '+c.title+' · '+c.section+(c.version?'（'+c.version+'）':''));
      });
      out.push('');
    }
  });
  downloadText('qa-'+stamp()+'.md', out.join(NL));
  toast('已导出 Markdown');
}

/* ---------- 未命中的反馈 ----------
   答不上来时，「应该答什么」和「缺哪份文档」比「有没有用」有价值得多：
   前者能补评测集，后者直接指向要补的资料。 */
function bindMissFeedback(body,d,query){
  var card=body.querySelector('.ans-card'); if(!card) return;
  var fb=document.createElement('div'); fb.className='fb';
  fb.innerHTML='<span class="fb-q">没找到需要的答案？</span>'
    +'<button type="button" class="fb-miss">补充线索</button>'
    +'<button type="button" class="fb-copy">复制问题</button>'
    +'<div class="fb-note"><input class="exp" placeholder="应该怎么答？（可留空）">'
    +'<input class="doc" placeholder="哪份文档有答案？（可留空）">'
    +'<button type="button" class="btn sm fb-send">提交</button></div>';
  card.appendChild(fb);
  var note=fb.querySelector('.fb-note');
  fb.querySelector('.fb-miss').onclick=function(){
    this.classList.add('on');
    note.classList.add('open');
    fb.querySelector('.exp').focus();
  };
  fb.querySelector('.fb-copy').onclick=function(){ copyText(query||d.query||'','问题已复制'); };
  fb.querySelector('.exp').onkeydown=function(e){ if(e.key==='Enter'){ e.preventDefault(); fb.querySelector('.fb-send').click(); } };
  fb.querySelector('.fb-send').onclick=async function(){
    var expected=fb.querySelector('.exp').value.trim();
    var document=fb.querySelector('.doc').value.trim();
    try{
      await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({trace_id:d.trace_id,useful:false,behavior:d.behavior||'no_answer',
          query:query||d.query||'',expected:expected,document:document,
          session_id:SESSION_ID,kb_version:d.kb_version||''})});
      fb.innerHTML='<span class="fb-done">已记录，会补进知识库或评测集</span>';
      toast(document?'已记录：缺少 '+document:'已记录：未命中线索');
    }catch(e){ toast('提交失败：'+e,true); }
  };
}

var ICON_NOTE='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3.5h7.5L18 8v12.5H6z"/><path d="M13.5 3.5V8H18"/><path d="M9 12.5h6M9 16h4"/></svg>';
function bindFeedback(body,d,query){
  var fb=document.createElement('div'); fb.className='fb';
  var up='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v9H4v-9z"/><path d="M7 10l3.6-7a1.8 1.8 0 0 1 3.1 1.6L13 9h5a2 2 0 0 1 2 2.3l-1.1 6A2 2 0 0 1 17 19H7z"/></svg>';
  var down='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><g transform="rotate(180 12 12)"><path d="M7 10v9H4v-9z"/><path d="M7 10l3.6-7a1.8 1.8 0 0 1 3.1 1.6L13 9h5a2 2 0 0 1 2 2.3l-1.1 6A2 2 0 0 1 17 19H7z"/></g></svg>';
  // 关掉「储存对话内容」时按钮根本不出现：默认就不该有保存入口
  var noteBtn=(window.__storeChat===true)
    ? ('<button type="button" class="fb-save">'+ICON_NOTE+' 存为笔记</button>') : '';
  fb.innerHTML='<span class="fb-q">这条回答对你有帮助吗？</span>'
    +'<button type="button" class="fb-up">'+up+' 有用</button>'
    +'<button type="button" class="fb-down">'+down+' 有问题</button>'
    +'<button type="button" class="fb-copy">复制</button>'
    +noteBtn
    +'<div class="fb-note"><input placeholder="哪里不对？可留空，用于 badcase 复盘"><button type="button" class="btn sm fb-send">提交</button></div>';
  body.querySelector('.ans-card').appendChild(fb);
  var saveBtn=fb.querySelector('.fb-save');
  if(saveBtn){ saveBtn.onclick=function(){ openNoteDialog(query||d.query||'', d); }; }

  async function send(useful,comment){
    try{
      await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({trace_id:d.trace_id,useful:useful,comment:comment||''})});
      fb.innerHTML='<span class="fb-done"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m20 6-11 11-5-5"/></svg>'
        +'已记录，可在评测看板一键转成用例</span>';
      toast(useful?'已记录：有用':'已记录：有问题，感谢复盘');
    }catch(e){ toast('反馈失败：'+e,true); }
  }
  fb.querySelector('.fb-up').onclick=function(){
    this.classList.add('on'); send(true,'');
  };
  fb.querySelector('.fb-down').onclick=function(){
    this.classList.add('on'); fb.querySelector('.fb-note').classList.add('open'); fb.querySelector('.fb-note input').focus();
  };
  fb.querySelector('.fb-send').onclick=function(){
    send(false, fb.querySelector('.fb-note input').value);
  };
  fb.querySelector('.fb-note input').onkeydown=function(e){
    if(e.key==='Enter'){ e.preventDefault(); fb.querySelector('.fb-send').click(); }
  };
  fb.querySelector('.fb-copy').onclick=function(){ copyText(d.answer,'答案已复制'); };
}

var ICON_SEND='<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13"/><path d="m12 5 7 7-7 7"/></svg>';
var ICON_STOP='<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
var controller=null;
function setBusy(on){
  busy=on;
  sendBtn.classList.toggle('stop',on);
  sendBtn.setAttribute('aria-label',on?'停止生成':'发送');
  sendBtn.innerHTML=on?ICON_STOP:ICON_SEND;
}
async function readSSE(resp,onEvent){
  var reader=resp.body.getReader(), decoder=new TextDecoder(), buf='';
  while(true){
    var step=await reader.read();
    if(step.done) break;
    buf+=decoder.decode(step.value,{stream:true});
    var cut;
    while((cut=buf.indexOf('\n\n'))>=0){
      var block=buf.slice(0,cut); buf=buf.slice(cut+2);
      var name='message', data='';
      block.split('\n').forEach(function(line){
        if(line.indexOf('event:')===0) name=line.slice(6).trim();
        else if(line.indexOf('data:')===0) data+=line.slice(5).trim();
      });
      if(data){ onEvent(name, JSON.parse(data)); }
    }
  }
}

async function ask(){
  var query=qEl.value.trim();
  if(!query){ qEl.focus(); return; }
  if(busy) return;
  setBusy(true);
  controller=new AbortController();
  if(heroEl) heroEl.hidden=true;

  addUser(query);
  var body=addBot();
  body.innerHTML=thinkingHTML('正在检索知识库…');
  scrollBottom();
  qEl.value=''; autoGrow();

  var answerEl=null, raw='';
  function ensureAnswer(){
    if(answerEl) return answerEl;
    body.innerHTML='<div class="ans-card"><div class="ans-label"><span>回答中</span></div>'
      +'<div class="answer streaming"></div></div>';
    answerEl=body.querySelector('.answer');
    return answerEl;
  }
  function finish(data){
    if(data.session_id){ SESSION_ID=data.session_id; saveSessionId(SESSION_ID); }
    body.innerHTML=answerHTML(data);
    if(data.behavior==='answer'){ bindFeedback(body,data,query); }
    else if(data.behavior==='no_answer'){ bindMissFeedback(body,data,query); }
    rememberTurn(query,data);
  }

  var timer=setTimeout(function(){
    var t=body.querySelector('.think-text'); if(t) t.textContent='正在组织答案并校验引用…';
  },900);

  try{
    var resp=await fetch('/api/ask/stream',{method:'POST',headers:apiHeaders({'Content-Type':'application/json'}),
      body:JSON.stringify({query:query,session_id:SESSION_ID}),signal:controller.signal});
    if(!resp.ok){
      var errData={};
      try{ errData=await resp.json(); }catch(e){}
      if(resp.status===401){ showKeyBar('Key 无效或已过期，请重新填写'); throw new Error('需要有效的 API Key'); }
      if(resp.status===429) throw new Error('请求太频繁，请 '+(errData.retry_after||1)+' 秒后重试');
      throw new Error(errData.error||('HTTP '+resp.status));
    }
    var ctype=resp.headers.get('Content-Type')||'';
    if(ctype.indexOf('text/event-stream')<0){
      finish(await resp.json());
      return;
    }
    var finalData=null;
    await readSSE(resp,function(name,data){
      if(name==='delta'){
        clearTimeout(timer);
        ensureAnswer().textContent += (data.text||'');
        scrollBottom();
      }else if(name==='replace'){
        ensureAnswer().textContent = (data.text||'');
        scrollBottom();
      }else if(name==='final'){
        finalData=data;
      }else if(name==='error'){
        throw new Error(data.error||'生成失败');
      }
    });
    if(!finalData) throw new Error('流式响应未完成');
    finish(finalData);
  }catch(err){
    clearTimeout(timer);
    if(err && err.name==='AbortError'){
      if(answerEl){ answerEl.textContent += '\n\n（已停止生成）'; }
      else { body.innerHTML='<div class="ans-card"><div class="answer">已停止生成。</div></div>'; }
      toast('已停止生成');
    }else{
      body.innerHTML='<div class="ans-card" style="border-color:#f6d3d0"><div class="ans-label"><span>请求失败</span></div>'
        +'<div class="answer">'+esc(err.message||String(err))+'</div></div>';
    }
  }finally{
    clearTimeout(timer);
    setBusy(false); controller=null; qEl.focus(); scrollBottom();
  }
}

sendBtn.onclick=function(){
  if(busy && controller){ controller.abort(); return; }
  ask();
};
qEl.addEventListener('input',autoGrow);
qEl.addEventListener('keydown',function(e){
  if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); ask(); }
});
document.addEventListener('keydown',function(e){ if(e.key==='Escape') sourceView.close(); });
document.getElementById('clear').onclick=function(){
  if(!list.querySelector('.msg')){ return; }
  var old=SESSION_ID;
  SESSION_ID=newSessionId(); saveSessionId(SESSION_ID);
  fetch('/api/session/clear',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:old})}).catch(function(){});
  if(window.JY) JY.clearCurrent();
  list.innerHTML=''; renderEmpty(); toast('已清空对话');
};
document.getElementById('exportMd').onclick=exportMarkdown;

var healthP=fetch('/api/health').then(function(r){return r.json();}).then(function(h){
  LLM_READY=!!h.llm_ready;
}).catch(function(){});

list.addEventListener('click',function(e){
  var ref=e.target.closest('.ref');
  if(ref){ sourceView.open(ref); return; }
  var b=e.target.closest('.sim-q');
  if(!b) return;
  qEl.value=b.textContent; autoGrow(); ask();
});

/* ---------- 存为笔记 ----------
   人也要能「有选择地」把某几轮存下来：这里按「一轮问答」为单位，
   先拿 commit=false 预览，人看着改标题/类型，再决定落盘。 */
var ND={payload:null,ready:false};
function closeNoteDialog(){
  document.getElementById('noteMask').hidden=true;
  document.getElementById('noteDialog').hidden=true;
  ND.payload=null; ND.ready=false;
}
async function openNoteDialog(query,d){
  ND.payload={
    messages:[{role:'user',text:query||'（用户提问）'},{role:'assistant',text:d.answer||''}],
    source:{agent:'web-ui',session:SESSION_ID},
    hint:{title:(query||'').slice(0,60)}
  };
  ND.ready=false;
  document.getElementById('noteMask').hidden=false;
  document.getElementById('noteDialog').hidden=false;
  document.getElementById('ndTitle').value=query||'';
  document.getElementById('ndTags').value=(d.citations||[]).slice(0,2).map(function(c){return c.title;}).join(', ');
  document.getElementById('ndKind').value='qa';
  document.getElementById('ndPreview').textContent='整理中…';
  document.getElementById('ndHint').textContent='本地规则整理，不联网。';
  document.getElementById('ndSave').disabled=true;
  try{
    var r=await fetch('/api/notes',{method:'POST',headers:apiHeaders({'Content-Type':'application/json'}),
      body:JSON.stringify(Object.assign({commit:false},ND.payload))});
    var draft=await r.json();
    if(!r.ok) throw new Error(draft.message||draft.error||('HTTP '+r.status));
    ND.ready=true; ND.payload.hint.title=draft.title||ND.payload.hint.title;
    document.getElementById('ndTitle').value=draft.title||'';
    // 预览只给正文：front matter 是给机器看的，摆出来只会让人以为存了一堆乱码
    var md=String(draft.markdown||'');
    var body=md.replace(/^---[\s\S]*?\n---\n?/,'');
    document.getElementById('ndPreview').textContent=body||md;
    document.getElementById('ndSave').disabled=false;
  }catch(e){
    document.getElementById('ndPreview').textContent='整理失败：'+(e.message||e);
    document.getElementById('ndHint').textContent='接口不可用时可以先去知识库页看已存的笔记。';
  }
}
async function saveNoteDialog(){
  if(!ND.ready) return;
  var btn=document.getElementById('ndSave'); btn.disabled=true;
  var body=Object.assign({},ND.payload,{commit:true,from:'chat'});
  body.hint=Object.assign({},ND.payload.hint,{
    title:document.getElementById('ndTitle').value.trim(),
    kind:document.getElementById('ndKind').value,
    tags:(document.getElementById('ndTags').value||'').split(/[,，]/).map(function(x){return x.trim();}).filter(Boolean)
  });
  try{
    var r=await fetch('/api/notes',{method:'POST',headers:apiHeaders({'Content-Type':'application/json'}),
      body:JSON.stringify(body)});
    var d=await r.json();
    if(!r.ok) throw new Error(d.message||d.error||('HTTP '+r.status));
    closeNoteDialog();
    if(d.duplicate_of){ toast('这段内容已经存过了'); }
    else{ toast('已存为笔记：'+(d.title||'')); }
    if(window.__noteSaved) window.__noteSaved(d);
  }catch(e){ toast('保存失败：'+(e.message||e),true); btn.disabled=false; }
}
document.getElementById('noteDlgClose').onclick=closeNoteDialog;
document.getElementById('ndCancel').onclick=closeNoteDialog;
document.getElementById('noteMask').onclick=closeNoteDialog;
document.getElementById('ndSave').onclick=saveNoteDialog;
document.addEventListener('keydown',function(e){ if(e.key==='Escape') closeNoteDialog(); });

/* ---------- 顶栏、工具条与会话切换 ---------- */
function bindChips(){
  var kb=document.getElementById('kbChip'), api=document.getElementById('apiChip');
  if(kb) kb.onclick=function(){ location.href='/kb'; };
  if(api) api.onclick=function(){
    if(window.__openSettings) window.__openSettings('api');
    else location.href='/kb';
  };
  fetch('/api/health').then(function(r){ return r.json(); }).then(function(h){
    LLM_READY=!!h.llm_ready;
    var kbv=(h.kb&&(h.kb.active||h.kb.version))||'';
    var kt=document.getElementById('kbChipText');
    if(kt) kt.textContent=kbv?('知识库 '+kbv):'知识库';
    if(kb&&kbv) kb.classList.add('on');
    var at=document.getElementById('apiChipText');
    if(at) at.textContent=h.llm_ready?('模型 '+(h.model||'已就绪')):'离线抽取';
    if(api) api.classList.toggle('warn',!h.llm_ready);
  }).catch(function(){});
}
function startNewChat(){
  if(busy){ toast('正在生成，稍等一下',true); return; }
  if(window.JY) JY.create();
  // 新对话要有自己的服务端上下文：沿用旧 session_id 会让模型记得上一段
  SESSION_ID=newSessionId(); saveSessionId(SESSION_ID);
  qEl.value=''; autoGrow();
  list.innerHTML=''; renderThread(); qEl.focus();
  if(window.innerWidth<=900) document.body.classList.remove('side-open');
}
function openThreadById(id){
  if(busy){ toast('正在生成，稍等一下再切换',true); return; }
  var t=window.JY?JY.open(id):null; if(!t) return;
  SESSION_ID=t.sid||newSessionId(); saveSessionId(SESSION_ID);
  renderThread();
  if(window.innerWidth<=900) document.body.classList.remove('side-open');
}
function bindThreadEvents(){
  var nb=document.getElementById('newChat');
  if(nb) nb.onclick=startNewChat;
  document.addEventListener('jy:thread',function(e){ openThreadById(e.detail); });
  document.addEventListener('jy:removed',function(){
    if(window.JY&&!JY.currentThread()){ list.innerHTML=''; renderEmpty(); setTitle(null); }
  });
  var params=new URLSearchParams(location.search);
  var want=params.get('t');
  if(want&&window.JY&&JY.open(want)){
    var t=JY.currentThread();
    if(t&&t.sid){ SESSION_ID=t.sid; saveSessionId(SESSION_ID); }
  }else if(params.get('new')==='1'&&window.JY){
    JY.create();
    // 建完就把参数抹掉：刷新页面不该又多出一条空会话
    try{ history.replaceState(null,'','/ask'); }catch(e){}
  }
  renderThread();
  if(window.innerWidth<=900) document.body.classList.remove('side-open');
}
bindKeyBar();
bindChips();
bindThreadEvents();
var pre=new URLSearchParams(location.search).get('q');
if(pre){ qEl.value=pre; autoGrow(); ask(); }
