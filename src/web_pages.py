"""原型页面（首页 / 问答 / 知识库 / 评测看板）。

覆盖一条完整使用路径：首页入口、提问输入、答案与引用、多轮追问、
答不出明确说明、反馈回流、后台（知识库 + 评测看板）。

设计系统在 theme.py；本文件只放各页面的结构与交互。全部为内联 HTML/CSS/JS，
不依赖 CDN、字体文件或前端框架，断网也能完整打开。
"""
from .theme import BRAND, JS_UTIL, shell

# ======================================================================
# 首页
# ======================================================================
HOME_CSS = """
.hero{position:relative;overflow:hidden;background:#070c1b;color:#eaf0ff;isolation:isolate;}
.hero::before{
  content:"";position:absolute;inset:0;z-index:-2;
  background:
    radial-gradient(760px 400px at 10% 0%,rgba(47,92,246,.42),transparent 62%),
    radial-gradient(600px 420px at 88% 12%,rgba(122,92,251,.34),transparent 66%),
    radial-gradient(760px 340px at 52% 118%,rgba(13,148,136,.18),transparent 72%);
}
.hero::after{
  content:"";position:absolute;inset:0;z-index:-1;
  background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
  background-size:46px 46px;
  -webkit-mask-image:radial-gradient(680px 420px at 26% 18%,#000 10%,transparent 78%);
  mask-image:radial-gradient(680px 420px at 26% 18%,#000 10%,transparent 78%);
}
.hero .wrap{position:relative;display:grid;grid-template-columns:1.06fr .94fr;gap:52px;align-items:center;padding-top:64px;padding-bottom:86px;}
.hero-eyebrow{color:#9db4ff;}
.hero-eyebrow::before{background:#7f9cff;}
.hero h1{color:#fff;font-size:clamp(31px,3.5vw,46px);line-height:1.16;letter-spacing:-.035em;font-weight:750;margin-top:16px;}
.hero h1 span{background:linear-gradient(100deg,#a9bcff 0%,#cdbbff 52%,#8fe6e0 100%);-webkit-background-clip:text;background-clip:text;color:transparent;}
.hero-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:30px;}
.btn.ghost-dark{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.2);color:#e6ecff;box-shadow:none;}
.btn.ghost-dark:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.34);color:#fff;}

/* 右侧两条回答路径，静态示意 */
.flow-wrap{position:relative;min-width:0;}
.flow-card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.16);border-radius:18px;padding:18px;
  box-shadow:0 50px 90px -40px rgba(0,0,0,.85), inset 0 1px 0 rgba(255,255,255,.12);}
.flow-head{display:flex;align-items:center;gap:8px;font-size:11px;color:#9db4ff;padding:0 2px 13px;}
.flow-head .dot{width:6px;height:6px;border-radius:50%;background:#34d399;box-shadow:0 0 0 3px rgba(52,211,153,.18);}
.flow-row{display:grid;grid-template-columns:58px minmax(0,1fr) auto;gap:12px;align-items:center;
  background:#fff;border-radius:11px;padding:13px 14px;margin-top:9px;}
.flow-k{font-size:10.5px;font-weight:700;text-align:center;padding:4px 0;border-radius:6px;
  background:var(--brand-soft);color:var(--brand-600);}
.flow-k.rag{background:#eef1f7;color:#54617a;}
.flow-txt b{display:block;font-size:12.5px;color:#0a1020;font-weight:600;}
.flow-txt small{display:block;font-size:11px;color:#8a94a6;margin-top:2px;}
.flow-v{font-size:11px;color:#0a7a4d;background:#e9f9f1;border-radius:999px;padding:3px 8px;white-space:nowrap;}
.flow-foot{font-size:10.5px;color:#8ea0c8;text-align:center;padding-top:12px;}

/* 指标条，压在 hero 上 */
.stat-strip{position:relative;z-index:3;margin-top:-40px;background:#fff;border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--sh-2);display:grid;grid-template-columns:repeat(3,1fr);padding:20px 6px;}
.stat{padding:2px 20px;border-left:1px solid var(--line);min-width:0;}
.stat:first-child{border-left:none;}
.stat .v{font-size:25px;font-weight:700;color:var(--ink);letter-spacing:-.035em;line-height:1.2;font-variant-numeric:tabular-nums;}
.stat .v small{font-size:12px;font-weight:500;color:var(--faint);letter-spacing:0;margin-left:3px;}
.stat .k{font-size:11.5px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

@media (max-width:960px){
  .hero .wrap{grid-template-columns:1fr;gap:40px;padding-top:44px;padding-bottom:78px;}
  .flow-wrap{max-width:520px;}
}
@media (max-width:760px){
  .stat-strip{grid-template-columns:repeat(3,1fr);row-gap:16px;padding:18px 4px;}
  .stat{padding:2px 10px;}
  .stat .v{font-size:21px;}
  .stat .k{font-size:11px;}
}
@media (max-width:560px){
  .hero h1{font-size:29px;}
  .flow-card{padding:14px;}
  .flow-row{grid-template-columns:52px minmax(0,1fr);row-gap:6px;padding:11px 12px;}
  .flow-v{grid-column:2;justify-self:start;}
}
"""

HOME_BODY = """
<main>
  <section class="hero">
    <div class="wrap">
      <div class="hero-copy">
        <div class="eyebrow hero-eyebrow">RAG · 文档问答</div>
        <h1>把文档变成<br><span>有出处的答案</span></h1>
        <div class="hero-actions">
          <a class="btn lg" href="/ask">开始提问 <span aria-hidden="true">→</span></a>
          <a class="btn ghost-dark lg" href="/kb">上传文档</a>
        </div>
      </div>

      <div class="flow-wrap" aria-hidden="true">
        <div class="flow-card">
          <div class="flow-head"><span class="dot"></span>文档进来，两条路出去</div>
          <div class="flow-row">
            <span class="flow-k">关键词</span>
            <div class="flow-txt"><b>命中清单 / 标签条目</b><small>原文片段直接返回</small></div>
            <span class="flow-v">0 调用</span>
          </div>
          <div class="flow-row">
            <span class="flow-k rag">检索</span>
            <div class="flow-txt"><b>未命中或需要推理</b><small>召回 → 生成 → 引用校验</small></div>
            <span class="flow-v">带出处</span>
          </div>
          <div class="flow-foot">同一份知识库，按问题自动切换</div>
        </div>
      </div>
    </div>
  </section>

  <div class="wrap">
    <section class="stat-strip" aria-label="项目实时指标">
      <div class="stat"><div class="v" id="s-cases">—</div><div class="k">评测用例</div></div>
      <div class="stat"><div class="v" id="s-cov">—</div><div class="k">引用覆盖率</div></div>
      <div class="stat"><div class="v" id="s-faith">—</div><div class="k">L3 忠实度</div></div>
    </section>
  </div>
</main>
"""

HOME_SCRIPT = """
function setT(id,v){var e=document.getElementById(id); if(e&&v!=null&&v!=='') e.textContent=v;}
function fmtScore(v){
  if(v==null) return null;
  var s=String(Math.round(Number(v)*100)/100);
  return s.indexOf('.')<0?s+'.0':s;
}
Promise.all([
  fetch('/api/cases').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/metrics').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/l3').then(function(r){return r.json();}).catch(function(){return null;})
]).then(function(res){
  var c=res[0],m=res[1],l3=res[2];
  if(c){ setT('s-cases', c.total); }
  if(m&&m.avg_citation_coverage!=null){ setT('s-cov', Math.round(m.avg_citation_coverage*100)+'%'); }
  if(l3&&l3.available&&l3.avg&&l3.avg.faithfulness!=null){ setT('s-faith', fmtScore(l3.avg.faithfulness)); }
}).catch(function(){});
"""

HOME_HTML = shell("home", BRAND + " · 有出处的文档问答", HOME_BODY, HOME_SCRIPT, HOME_CSS)


# ======================================================================
# 问答页
# ======================================================================
ASK_CSS = """
.ask-wrap{max-width:920px;}
.chat-shell{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--sh-1);
  display:flex;flex-direction:column;height:min(calc(100vh - var(--nav-h) - 92px),820px);min-height:560px;overflow:hidden;}

.chat-list{flex:1;overflow:auto;padding:22px;display:flex;flex-direction:column;gap:16px;}
.chat-list::-webkit-scrollbar{width:8px;}
.chat-list::-webkit-scrollbar-thumb{background:#e3e8f2;border-radius:8px;}
.chat-list::-webkit-scrollbar-track{background:transparent;}

.empty-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:28px 20px 34px;}
.empty-chat .art{width:88px;height:88px;border-radius:24px;background:linear-gradient(160deg,#eef3ff,#f9fbff);
  border:1px solid #e2e9fd;display:flex;align-items:center;justify-content:center;color:var(--brand);
  box-shadow:inset 0 1px 0 #fff,0 18px 34px -26px rgba(47,92,246,.6);}
.ex-wrap{margin-top:24px;width:100%;max-width:600px;}
.ex-label{font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);}
.ex-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;}
.ex-card{text-align:left;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;cursor:pointer;
  font-size:12.5px;color:#475467;line-height:1.55;transition:border .15s,box-shadow .15s,transform .15s;font-family:inherit;}
.ex-card:hover{border-color:#c3d0f8;box-shadow:0 8px 20px -14px rgba(47,92,246,.7);transform:translateY(-1px);}

.msg{display:flex;gap:10px;max-width:100%;animation:rise .24s ease both;}
@keyframes rise{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;}}
.msg.user{justify-content:flex-end;}
.bubble{background:linear-gradient(140deg,#3a66ff,#2f5cf6);color:#fff;padding:10px 14px;border-radius:16px 16px 5px 16px;
  max-width:76%;font-size:13.5px;line-height:1.7;white-space:pre-wrap;word-break:break-word;
  box-shadow:0 10px 24px -18px rgba(47,92,246,.95);}
.avatar{width:30px;height:30px;border-radius:9px;flex:none;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(150deg,#eef2ff,#e4ebff);color:var(--brand);border:1px solid #dde5ff;}
.msg-body{flex:1;min-width:0;max-width:calc(100% - 40px);}
.ans-card{background:#fff;border:1px solid var(--line);border-radius:4px 14px 14px 14px;padding:15px 17px;box-shadow:var(--sh-1);}
.ans-label{display:flex;align-items:center;gap:8px;font-size:10px;color:var(--faint);letter-spacing:.1em;
  text-transform:uppercase;font-weight:700;margin-bottom:7px;}
.answer{font-size:13.8px;line-height:1.85;white-space:pre-wrap;word-break:break-word;color:#233044;}
.kw-hit{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 9px;}
.kw-hit-t{font-size:10.5px;color:var(--faint);letter-spacing:.06em;}
.kw-term{font-size:11px;color:var(--brand-600);background:var(--brand-soft);border:1px solid #e1e8fd;
  border-radius:999px;padding:2px 8px;line-height:1.5;}
.answer strong{font-weight:650;color:#0a1020;}
.answer .cite-n{display:inline-flex;align-items:center;justify-content:center;min-width:15px;height:15px;
  border-radius:4px;background:var(--brand-soft);color:#2a49c8;font-size:9.5px;font-weight:700;padding:0 3px;
  vertical-align:1px;margin:0 1px;}
.refs{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px;}
.ref{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;background:var(--brand-tint);border:1px solid #e4eafd;
  color:#34457a;padding:3px 9px 3px 4px;border-radius:8px;line-height:1.5;cursor:pointer;font-family:inherit;transition:all .14s;}
.ref:hover{border-color:#c3d0f8;background:var(--brand-soft);color:var(--brand-600);}
.src-mask{position:fixed;inset:0;background:rgba(10,16,32,.34);z-index:80;}
.src-drawer{position:fixed;top:0;right:0;height:100%;width:min(540px,94vw);background:#fff;z-index:81;
  box-shadow:-24px 0 60px -30px rgba(10,16,32,.55);display:flex;flex-direction:column;
  transform:translateX(8px);opacity:0;transition:transform .18s ease,opacity .18s ease;}
.src-drawer.open{transform:none;opacity:1;}
.src-head{display:flex;align-items:flex-start;gap:12px;padding:16px 18px 13px;border-bottom:1px solid var(--line);}
.src-head b{font-size:14px;color:var(--ink);line-height:1.5;}
.src-sub{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.6;}
.src-close{margin-left:auto;border:none;background:#f3f5fa;width:28px;height:28px;border-radius:8px;
  font-size:17px;line-height:1;color:var(--muted);cursor:pointer;flex:none;}
.src-close:hover{background:#e9edf7;color:var(--ink);}
.src-text{margin:0;padding:18px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  font-size:13px;line-height:1.9;color:#344054;font-family:inherit;flex:1;}
.src-text mark{background:#fff3bf;color:#6b4b00;border-radius:3px;padding:0 1px;}
[hidden]{display:none !important;}
.ref b{width:16px;height:16px;border-radius:5px;background:var(--brand);color:#fff;font-size:9.5px;
  display:flex;align-items:center;justify-content:center;font-weight:600;flex:none;}
.ans-foot{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px;padding-top:11px;border-top:1px dashed #e8ecf5;}
.ans-foot .pill{font-size:10.5px;padding:2px 8px;}

details.src{margin-top:10px;border-top:1px dashed #eef1f7;padding-top:9px;}
details.src summary{cursor:pointer;font-size:11.5px;color:var(--muted);list-style:none;display:flex;align-items:center;gap:5px;user-select:none;}
details.src summary::-webkit-details-marker{display:none;}
details.src summary .ic{transition:transform .18s ease;color:#a9b3c6;}
details.src[open] summary .ic{transform:rotate(90deg);}
.src-list{margin-top:8px;display:flex;flex-direction:column;gap:1px;}
.src-row{display:flex;align-items:baseline;gap:8px;font-size:11.8px;padding:5px 0;color:#4b5565;border-bottom:1px solid #f6f8fc;}
.src-row:last-child{border-bottom:none;}
.src-row .rank{width:16px;flex:none;font-family:var(--mono);font-size:10px;color:var(--faint);}
.src-row .sc{margin-left:auto;font-family:var(--mono);font-size:10px;color:var(--faint);white-space:nowrap;}

.fb{display:flex;gap:6px;margin-top:12px;align-items:center;flex-wrap:wrap;}
.fb-q{font-size:11px;color:var(--faint);margin-right:2px;}
.fb button{display:inline-flex;gap:5px;align-items:center;padding:5px 10px;font-size:11.5px;border:1px solid var(--line);
  background:#fff;color:var(--muted);border-radius:8px;cursor:pointer;transition:all .14s;font-family:inherit;}
.fb button:hover{border-color:#c3d0f8;color:var(--brand-600);background:var(--brand-tint);}
.fb button.on{border-color:#c3d0f8;color:var(--brand-600);background:var(--brand-soft);}
.fb-done{font-size:11.5px;color:var(--ok);display:inline-flex;align-items:center;gap:5px;}
.fb-note{display:none;width:100%;gap:6px;margin-top:2px;}
.fb-note.open{display:flex;}
.fb-note input{flex:1;padding:7px 10px;border:1px solid var(--line-2);border-radius:8px;font-size:12px;outline:none;font-family:inherit;}
.fb-note input:focus{border-color:var(--brand);}

.sim{margin-top:14px;padding-top:12px;border-top:1px dashed #eddbb9;}
.sim-title{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#a97a33;margin-bottom:7px;}
.sim-list{display:flex;flex-direction:column;gap:5px;}
.sim-q{text-align:left;border:1px solid #eddbb9;background:#fff;color:#7a4b00;border-radius:8px;padding:8px 10px;
  font-size:12.5px;line-height:1.55;font-family:inherit;cursor:pointer;transition:border-color .15s,background .15s;}
.sim-q:hover{border-color:#d9a94a;background:#fffdf7;}

.thinking{display:flex;align-items:center;gap:9px;font-size:12.5px;color:var(--muted);}
.dots{display:inline-flex;gap:3px;}
.dots i{width:5px;height:5px;border-radius:50%;background:var(--brand);animation:bounce 1.15s infinite ease-in-out;}
.dots i:nth-child(2){animation-delay:.16s;} .dots i:nth-child(3){animation-delay:.32s;}
@keyframes bounce{0%,70%,100%{transform:translateY(0);opacity:.45;}35%{transform:translateY(-4px);opacity:1;}}
.sk{height:9px;border-radius:6px;background:linear-gradient(90deg,#f2f5fb 0%,#e8edf8 40%,#f2f5fb 80%);
  background-size:220% 100%;animation:shimmer 1.5s infinite linear;}
@keyframes shimmer{from{background-position:120% 0;}to{background-position:-120% 0;}}

.composer{padding:11px 16px 13px;border-top:1px solid var(--line);background:#fff;}
.composer-box{display:flex;align-items:flex-end;gap:8px;border:1px solid var(--line-2);border-radius:14px;
  padding:7px 7px 7px 14px;background:#fff;transition:border .15s,box-shadow .15s;}
.composer-box:focus-within{border-color:#b9c8f7;box-shadow:0 0 0 4px rgba(47,92,246,.08);}
.composer textarea{flex:1;border:none;outline:none;resize:none;font-size:14px;line-height:1.6;max-height:124px;
  min-height:24px;padding:5px 0;font-family:inherit;color:var(--text);background:transparent;}
.composer textarea::placeholder{color:#a9b3c6;}
.send{width:38px;height:38px;border-radius:10px;border:none;background:linear-gradient(180deg,#3a66ff,#2f5cf6);color:#fff;
  display:flex;align-items:center;justify-content:center;cursor:pointer;flex:none;
  box-shadow:0 6px 16px -10px rgba(47,92,246,.95);transition:filter .15s,transform .12s;}
.send:hover{filter:brightness(1.05);}
.send.stop{background:#d92d20;box-shadow:0 6px 16px -10px rgba(217,45,32,.8);}
.send:active{transform:translateY(1px);}
.send[disabled]{opacity:.5;cursor:not-allowed;}
.composer-hint{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:10.5px;color:var(--faint);margin-top:7px;padding:0 2px;}
.composer-hint kbd{font-family:var(--mono);font-size:9.5px;background:#f3f5fa;border:1px solid var(--line);border-radius:4px;padding:1px 4px;color:#667085;}
.clear-link{border:none;background:none;padding:0;font-size:10.5px;color:var(--faint);cursor:pointer;font-family:inherit;}
.clear-link:hover{color:var(--brand-600);text-decoration:underline;}

@media (max-width:960px){
  .chat-shell{height:calc(100vh - var(--nav-h) - 88px);max-height:none;min-height:520px;}
}
@media (max-width:640px){
  .ask-wrap{padding:14px 12px 40px;}
  .chat-shell{height:calc(100vh - 150px);max-height:none;min-height:480px;}
  .chat-list{padding:14px;gap:14px;}
  .bubble{max-width:86%;}
  .composer{padding:9px 12px 11px;}
  .composer textarea{font-size:16px;}
  .composer-hint{justify-content:flex-end;}
  .composer-hint .kbd-hint{display:none;}
  .ex-cards{grid-template-columns:1fr;}
  .msg-body{max-width:calc(100% - 36px);}
}
"""

_ASK_ART = (
    '<svg width="50" height="50" viewBox="0 0 48 48" fill="none" aria-hidden="true">'
    '<rect x="8.5" y="5" width="23" height="31" rx="4" stroke="currentColor" stroke-width="1.7"/>'
    '<path d="M15 13.5h10M15 19.5h10M15 25.5h6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    '<circle cx="32.5" cy="31.5" r="7" fill="#f9fbff" stroke="currentColor" stroke-width="1.7"/>'
    '<path d="m37.6 36.6 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    "</svg>"
)

ASK_BODY = """
<main class="wrap ask-wrap">
  <section class="chat-shell">
    <div id="list" class="chat-list" aria-live="polite"></div>
    <div class="composer">
      <div class="composer-box">
        <textarea id="q" rows="1" placeholder="输入问题…" autocomplete="off"></textarea>
        <button class="send" id="send" type="button" aria-label="发送">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13"/><path d="m12 5 7 7-7 7"/></svg>
        </button>
      </div>
      <div class="composer-hint">
        <span class="kbd-hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
        <button class="clear-link" id="clear" type="button">清空对话</button>
      </div>
    </div>
  </section>
  <div class="src-mask" id="srcMask" hidden></div>
  <aside class="src-drawer" id="srcDrawer" hidden aria-label="引用原文">
    <div class="src-head">
      <div><b id="srcTitle">原文</b><div class="src-sub" id="srcSub"></div></div>
      <button class="src-close" id="srcClose" type="button" aria-label="关闭">×</button>
    </div>
    <pre class="src-text" id="srcText"></pre>
  </aside>
</main>
"""

ASK_SCRIPT = JS_UTIL + """
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
var MODE={llm:'模型生成',extractive:'抽取式',extractive_fallback:'降级抽取',keyword_local:'本地关键词'};
var BEHAVIOR={answer:['作答','ok'],ask_clarify:['追问澄清','brand'],no_answer:['未找到','warn'],refuse:['拒答','bad']};
var ART='""" + _ASK_ART.replace("'", "\\'") + """';

function scrollBottom(){ list.scrollTop=list.scrollHeight; }
function autoGrow(){ qEl.style.height='auto'; qEl.style.height=Math.min(qEl.scrollHeight,124)+'px'; }

function renderEmpty(){
  list.innerHTML='<div class="empty-chat"><div class="art">'+ART+'</div>'
    +'<div class="ex-wrap"><div class="ex-label">可以这样问</div>'
    +'<div class="ex-cards" id="exCards"></div></div></div>';
  loadExamples();
}
async function loadExamples(){
  var box=document.getElementById('exCards');
  if(!box) return;
  try{
    var r=await (await fetch('/api/examples?n=4')).json();
    (r.items||[]).forEach(function(t){
      var b=document.createElement('button'); b.type='button'; b.className='ex-card';
      b.textContent=t;
      b.onclick=function(){ qEl.value=t; autoGrow(); ask(); };
      box.appendChild(b);
    });
  }catch(e){}
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
  s=s.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/\\[(\\d+)\\]/g,'<span class="cite-n">$1</span>');
  return s;
}
function footHTML(d){
  var html='<div class="ans-foot">';
  if(d.behavior!=='answer'){
    return html+pill((d.latency_ms==null?'-':Math.round(d.latency_ms))+' ms')+'</div>';
  }
  if(d.path==='keyword'){
    html+=pill('本地直出 · 未调用模型','ok')+pill((d.latency_ms==null?'-':Math.round(d.latency_ms))+' ms');
    return html+'</div>';
  }
  if(LLM_READY===false){ html+=pill('离线抽取','warn'); }
  else { html+='<span class="pill brand">'+esc(d.channel||'-')+' / '+esc(d.model||'-')+'</span>'; }
  html+=pill('模式 '+(MODE[d.mode]||d.mode||'-'))
    +pill((d.latency_ms==null?'-':Math.round(d.latency_ms))+' ms');
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
  var h='<div class="ans-card"><div class="ans-label"><span>'+head+'</span>'
    +(d.behavior&&BEHAVIOR[d.behavior]?'<span class="pill '+BEHAVIOR[d.behavior][1]+'">'+BEHAVIOR[d.behavior][0]+'</span>':'')
    +(d.turn>1?'<span class="pill">第 '+d.turn+' 轮</span>':'')
    +'</div>';
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

function bindFeedback(body,d){
  var fb=document.createElement('div'); fb.className='fb';
  fb.innerHTML='<span class="fb-q">这条回答对你有帮助吗？</span>'
    +'<button type="button" class="fb-up">👍 有用</button>'
    +'<button type="button" class="fb-down">👎 有问题</button>'
    +'<button type="button" class="fb-copy">复制</button>'
    +'<div class="fb-note"><input placeholder="哪里不对？可留空，用于 badcase 复盘"><button type="button" class="btn sm fb-send">提交</button></div>';
  body.querySelector('.ans-card').appendChild(fb);

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
  fb.querySelector('.fb-copy').onclick=function(){
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(d.answer).then(function(){toast('答案已复制');},function(){toast('复制失败',true);});
    }else{ toast('当前浏览器不支持剪贴板',true); }
  };
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
    while((cut=buf.indexOf('\\n\\n'))>=0){
      var block=buf.slice(0,cut); buf=buf.slice(cut+2);
      var name='message', data='';
      block.split('\\n').forEach(function(line){
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
  var empty=list.querySelector('.empty-chat'); if(empty) list.innerHTML='';

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
    if(data.behavior==='answer'){ bindFeedback(body,data); }
  }

  var timer=setTimeout(function(){
    var t=body.querySelector('.think-text'); if(t) t.textContent='正在组织答案并校验引用…';
  },900);

  try{
    var resp=await fetch('/api/ask/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:query,session_id:SESSION_ID}),signal:controller.signal});
    if(!resp.ok){
      var errData={};
      try{ errData=await resp.json(); }catch(e){}
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
      if(answerEl){ answerEl.textContent += '\\n\\n（已停止生成）'; }
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
  list.innerHTML=''; renderEmpty(); toast('已清空对话');
};

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
renderEmpty();
var pre=new URLSearchParams(location.search).get('q');
if(pre){ qEl.value=pre; autoGrow(); ask(); }
"""

ASK_HTML = shell("ask", "问答 · " + BRAND, ASK_BODY, ASK_SCRIPT, ASK_CSS)


# ======================================================================
# 知识库
# ======================================================================
KB_CSS = """
.kb-wrap{max-width:1060px;}
.kb-head{display:flex;align-items:flex-end;gap:18px;flex-wrap:wrap;margin-bottom:18px;}
.kb-head h1{font-size:27px;letter-spacing:-.03em;margin-top:8px;}
.kb-head .sub{font-size:12.5px;color:var(--muted);margin-top:6px;}
.kb-head .actions{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.kb-layout{display:grid;grid-template-columns:318px minmax(0,1fr);gap:16px;align-items:start;}
.kb-side{display:flex;flex-direction:column;gap:12px;position:sticky;top:calc(var(--nav-h) + 16px);}
.kb-side .card{padding:16px;}
.kb-side .side-title{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#8b95a8;margin-bottom:11px;}

.drop{border:1.5px dashed #cfd8ea;border-radius:13px;background:linear-gradient(180deg,#fbfcff,#fff);
  padding:24px 16px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;
  text-align:center;cursor:pointer;transition:border .16s,background .16s,box-shadow .16s;}
.drop:hover,.drop.over{border-color:#9db2f2;background:var(--brand-tint);box-shadow:0 0 0 4px rgba(47,92,246,.06);}
.drop .dic{width:38px;height:38px;border-radius:11px;background:var(--brand-soft);color:var(--brand);
  display:flex;align-items:center;justify-content:center;margin-bottom:4px;}
.drop b{font-size:13px;color:var(--ink);font-weight:600;}
.drop span{font-size:11px;color:var(--faint);line-height:1.65;}
.kb-status{font-size:11.5px;color:var(--faint);margin-top:10px;min-height:17px;line-height:1.65;word-break:break-word;}
.kb-status.ok{color:var(--ok);font-weight:500;}
.kb-status.err{color:var(--bad);font-weight:500;}

.tips{font-size:11.5px;color:var(--muted);line-height:1.75;}
.tips div{display:flex;gap:7px;padding:4px 0;}
.tips i{flex:none;width:4px;height:4px;border-radius:50%;background:#c3ccdd;margin-top:8px;}

.kb-list{padding:16px;}
.kb-list table{table-layout:fixed;}
.kb-list th:nth-child(1){width:auto;}
.kb-list th:nth-child(2){width:60px;}
.kb-list th:nth-child(3){width:70px;}
.kb-list th:nth-child(4){width:70px;}
.kb-list th:nth-child(5){width:112px;}
.kb-list th:nth-child(6){width:112px;}
.kb-list td{white-space:nowrap;}
.kb-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;}
.search{position:relative;flex:1;min-width:150px;}
.search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);color:#a9b3c6;}
.search input{width:100%;padding:7px 10px 7px 29px;border:1px solid var(--line-2);border-radius:8px;
  font-size:12px;font-family:inherit;outline:none;background:#fff;color:var(--text);}
.search input:focus{border-color:#b9c8f7;box-shadow:0 0 0 3px rgba(47,92,246,.07);}
.chips{display:flex;gap:2px;}
.chips button{border:none;background:none;padding:5px 8px;border-radius:7px;font-size:11.5px;font-family:inherit;
  color:var(--muted);cursor:pointer;}
.chips button:hover{background:#f2f5fb;color:var(--ink);}
.chips button.on{background:var(--brand-soft);color:var(--brand-600);font-weight:600;}
.kb-sort{padding:6px 8px;border:1px solid var(--line-2);border-radius:8px;font-size:11.5px;font-family:inherit;
  color:var(--muted);background:#fff;outline:none;cursor:pointer;}
.kb-foot{font-size:11px;color:var(--faint);margin-top:10px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;}

.fname{display:flex;align-items:center;gap:9px;min-width:0;}
.ftype{font-family:var(--mono);font-size:9.5px;font-weight:600;padding:2px 5px;border-radius:4px;flex:none;
  background:#eef1f7;color:#667085;letter-spacing:.02em;}
.ftype.pdf{background:#fef1f0;color:#b42318;} .ftype.docx{background:#eef2ff;color:#2a49c8;}
.ftype.md{background:#e9f9f1;color:#0a7a4d;} .ftype.txt{background:#f4f6fa;color:#54617a;}
.fname .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;}
.row-actions{display:flex;gap:5px;justify-content:flex-end;}
.row-actions button{padding:4px 8px;font-size:11.5px;}
.empty-row td{padding:30px 14px !important;text-align:center;color:var(--faint);font-size:12.5px;}
.ts{font-family:var(--mono);font-size:11px;color:var(--faint);white-space:nowrap;}
.kw-btn{border:none;background:none;padding:2px 4px;font:inherit;font-size:12px;color:var(--brand-600);
  cursor:pointer;border-bottom:1px dashed #c6d3fa;font-variant-numeric:tabular-nums;}
.kw-btn:hover{color:var(--brand);border-bottom-color:var(--brand);}
.kw-row td{padding:0 !important;background:#fafbff;}
.kw-box{padding:13px 16px 15px;border-top:1px solid #eef2fb;}
.kw-sum{font-size:12px;color:var(--muted);line-height:1.7;margin-bottom:9px;}
.kw-chips{display:flex;flex-wrap:wrap;gap:6px;}
.kw-chip{font-size:11.5px;color:#334155;background:#fff;border:1px solid var(--line-2);border-radius:999px;
  padding:3px 9px;line-height:1.5;}
.kw-chip.hit{background:var(--brand-soft);border-color:#dbe4fd;color:var(--brand-600);font-weight:600;}
.kw-empty{font-size:12px;color:var(--faint);}
.kw-load{font-size:12px;color:var(--faint);}

.approve{margin:0 0 12px;padding:0 13px 13px;border:1px solid #f0dfc0;background:#fffdf7;border-radius:12px;}
.approve-head{display:flex;align-items:center;gap:8px;padding:10px 0;border-bottom:1px dashed #f0e2c8;}
.approve-head b{font-size:12.5px;color:#7a4b00;}
.approve-head .sp{margin-left:auto;display:flex;gap:6px;}
.appr-item{padding:10px 0;border-bottom:1px solid #f7edda;}
.appr-item:last-of-type{border-bottom:none;}
.appr-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.appr-top b{font-size:12px;font-family:var(--mono);color:#6b4b00;}
.appr-files{font-size:11.5px;color:#8a6a33;margin-top:4px;line-height:1.7;word-break:break-word;}
.appr-actions{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;}
.appr-token{display:flex;gap:6px;margin-top:10px;align-items:center;font-size:11.5px;color:#8a6a33;flex-wrap:wrap;}
.appr-token input{flex:1;min-width:160px;padding:6px 9px;border:1px solid #e8d7b6;border-radius:7px;font-size:12px;
  font-family:inherit;outline:none;background:#fff;}
.kb-mask{position:fixed;inset:0;background:rgba(10,16,32,.35);z-index:80;}
.kb-modal{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(780px,94vw);max-height:86vh;
  background:#fff;border-radius:14px;z-index:81;display:flex;flex-direction:column;
  box-shadow:0 30px 80px -30px rgba(10,16,32,.55);}
.kb-modal-head{display:flex;align-items:center;gap:10px;padding:14px 17px;border-bottom:1px solid var(--line);}
.kb-modal-head b{font-size:14px;color:var(--ink);}
.kb-modal-head button{margin-left:auto;border:none;background:#f3f5fa;width:28px;height:28px;border-radius:8px;
  font-size:17px;line-height:1;color:var(--muted);cursor:pointer;}
.kb-modal-body{padding:14px 17px;overflow:auto;}
.diff{background:#0f172a;color:#dbe4f3;border-radius:10px;padding:12px;font-family:var(--mono);font-size:11.5px;
  line-height:1.65;white-space:pre-wrap;overflow:auto;max-height:52vh;}
.diff .add{color:#7ee2a8;} .diff .del{color:#ff9b9b;} .diff .meta{color:#93a4c3;}
.diff-title{display:flex;align-items:center;gap:8px;margin:12px 0 6px;font-size:12px;color:var(--muted);}
.hist-item{display:flex;align-items:center;gap:9px;padding:9px 0;border-bottom:1px solid var(--line);font-size:12px;flex-wrap:wrap;}
.hist-item:last-child{border-bottom:none;}
[hidden]{display:none !important;}

@media (max-width:900px){
  .kb-layout{grid-template-columns:1fr;}
  .kb-side{position:static;display:grid;grid-template-columns:1fr 1fr;}
  .kb-head h1{font-size:23px;}
}
@media (max-width:640px){
  .kb-head .actions{margin-left:0;}
  .kb-side{grid-template-columns:1fr;}
  .kb-list{padding:14px;}
  .kb-toolbar .search{flex-basis:100%;}
  .chips{order:2;width:auto;flex:1;}
  .kb-sort{order:3;margin-left:auto;}
  .kb-list th:nth-child(4), .kb-list td:nth-child(4),
  .kb-list th:nth-child(5), .kb-list td:nth-child(5){display:none;}
  .kb-list th:nth-child(2){width:54px;}
  .kb-list th:nth-child(3){width:64px;}
  .kb-list th:nth-child(6){width:104px;}
}
"""

KB_BODY = """
<main class="wrap kb-wrap">
  <div class="kb-head">
    <div>
      <div class="eyebrow">Knowledge</div>
      <h1>知识库</h1>
      <p class="sub">上传什么文档，就回答什么内容。</p>
    </div>
    <div class="actions">
      <span class="pill" id="kbVersion">—</span>
      <span class="pill" id="kbMeta">加载中…</span>
      <button class="btn ghost sm" id="reload" type="button">重建索引</button>
      <a class="btn sm" href="/ask">去提问 <span aria-hidden="true">→</span></a>
    </div>
  </div>

  <div class="kb-layout">
    <div class="kb-side">
      <section class="card">
        <div class="side-title">上传文档</div>
        <div class="drop" id="drop">
          <div class="dic">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
          </div>
          <b>拖拽或点击上传</b>
          <span>.md / .txt / .pdf / .docx<br>可一次选择多份<br>文本 ≤ 512 KB · PDF/Word ≤ 6 MB</span>
          <input type="file" id="kbFile" accept=".md,.txt,.pdf,.docx" multiple hidden>
        </div>
        <div class="kb-status" id="kbMsg"></div>
      </section>

      <section class="card tips">
        <div class="side-title">说明</div>
        <div><i></i><span>审批通过后切分并重建索引；本机管理员直通时立即生效。</span></div>
        <div><i></i><span>清单 / 标签类条目命中后本地直出，不调用模型。</span></div>
        <div><i></i><span>PDF / Word 服务端转 Markdown；扫描件需先 OCR。</span></div>
      </section>
    </div>

    <section class="card kb-list">
      <div class="approve" id="approvePanel" hidden>
        <div class="approve-head">
          <b>待审批变更</b><span class="pill warn" id="apprCount">0</span>
          <span class="sp"><button class="btn ghost sm" id="apprRefresh" type="button">刷新</button></span>
        </div>
        <div id="apprList"></div>
        <div class="appr-token" id="apprToken" hidden>
          <span>管理员令牌</span>
          <input id="adminToken" type="password" placeholder="配置 ADMIN_TOKEN 时需要" autocomplete="off">
          <button class="btn ghost sm" id="adminSave" type="button">保存</button>
        </div>
      </div>

      <div class="kb-toolbar">
        <div class="search">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="kbSearch" placeholder="搜索文档" autocomplete="off">
        </div>
        <div class="chips" id="kbFilters">
          <button type="button" class="on" data-type="all">全部</button>
          <button type="button" data-type="md">MD</button>
          <button type="button" data-type="txt">TXT</button>
          <button type="button" data-type="pdf">PDF</button>
          <button type="button" data-type="docx">DOCX</button>
        </div>
        <select class="kb-sort" id="kbSort">
          <option value="name">按名称</option>
          <option value="chunks">按知识块</option>
          <option value="size">按大小</option>
          <option value="mtime">按更新时间</option>
        </select>
      </div>

      <div class="table-wrap">
        <table>
          <thead><tr><th>文件</th><th class="num">知识块</th><th class="num">关键词</th><th class="num">大小</th><th>更新时间</th><th style="text-align:right">操作</th></tr></thead>
          <tbody id="kbBody"></tbody>
        </table>
      </div>
      <div class="kb-foot"><span id="kbFoot"></span><span id="kbHint"></span></div>
    </section>
  </div>
  <div class="kb-mask" id="kbMask" hidden></div>
  <div class="kb-modal" id="kbModal" hidden>
    <div class="kb-modal-head"><b id="kbModalTitle">版本</b>
      <button id="kbModalClose" type="button" aria-label="关闭">×</button></div>
    <div class="kb-modal-body" id="kbModalBody"></div>
  </div>
</main>
"""

KB_SCRIPT = JS_UTIL + """
function $(id){ return document.getElementById(id); }
var KB={files:[],total_chunks:0}, FILTER='all', SORT='name', Q='', BUSY=false;

function typeOf(name){
  var ext=(name.split('.').pop()||'').toLowerCase();
  return {ext:ext.toUpperCase(),cls:ext};
}
function sizeText(n){
  if(n==null) return '—';
  if(n<1024) return n+' B';
  if(n<1048576) return (Math.round(n/102.4)/10)+' KB';
  return (Math.round(n/104857.6)/10)+' MB';
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

function render(){
  var total=(KB.files||[]).length, chunks=KB.total_chunks||0;
  $('kbMeta').textContent=total+' 份 · '+chunks+' 块'+(KB.pending_changes?(' · 待审批 '+KB.pending_changes):'');
  $('kbVersion').textContent=KB.version?('版本 '+KB.version):'单目录模式';
  var list=visibleFiles();
  $('kbFoot').textContent='显示 '+list.length+' / '+total+' 份';
  $('kbHint').textContent=total?('合计 '+chunks+' 个知识块'):'';
  if(!list.length){
    $('kbBody').innerHTML=emptyRow(6,total?'没有匹配的文档':'还没有文档，先上传一份 .md / .pdf / .docx');
    return;
  }
  $('kbBody').innerHTML=list.map(function(f){
    var t=typeOf(f.name), kws=f.keywords||[], kc=(f.keyword_count!=null?f.keyword_count:kws.length);
    return '<tr data-name="'+esc(f.name)+'"><td><div class="fname"><span class="ftype '+esc(t.cls)+'">'+esc(t.ext)+'</span>'
      +'<span class="nm" title="'+esc(f.name)+'">'+esc(f.name)+'</span></div></td>'
      +'<td class="num"><span class="pill">'+f.chunks+'</span></td>'
      +'<td class="num"><button class="kw-btn" type="button" data-kw="'+esc(f.name)+'" title="'+(kws.length?esc(kws.join(' · ')):'暂无关键词')+'">'+(kc?kc:'—')+'</button></td>'
      +'<td class="num mono" style="font-size:11px;color:var(--muted)">'+sizeText(f.size)+'</td>'
      +'<td class="ts">'+esc(f.mtime||'—')+'</td>'
      +'<td><div class="row-actions">'
      +'<button class="btn ghost sm hist" data-name="'+esc(f.name)+'">历史</button>'
      +'<button class="btn ghost sm gen" data-name="'+esc(f.name)+'">出题</button>'
      +'<button class="btn danger-ghost sm del" data-name="'+esc(f.name)+'">删除</button>'
      +'</div></td></tr>';
  }).join('');
  renderKwMeta();
}
function renderKwMeta(){
  var kw=KB.keywords||{}, n=kw.terms||0;
  $('kbMeta').textContent=(KB.files||[]).length+' 份 · '+(KB.total_chunks||0)+' 块'
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
  tr.innerHTML='<td colspan="6"><div class="kw-box"><span class="kw-load">读取关键词…</span></div></td>';
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
    await loadKb();
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
        +'<span class="muted">'+sizeText(v.size)+'</span>'
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
    await loadKb();
  }catch(e){ toast('回滚失败：'+(e.message||e),true); }
}

async function loadKb(){
  try{
    var r=await (await fetch('/api/knowledge')).json();
    KB=r; render(); await loadApprovals();
  }catch(e){ setMsg('加载失败：'+(e.message||e),'err'); }
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
  if(['md','txt','pdf','docx'].indexOf(ext)<0) throw new Error('不支持 .'+ext+'，只接受 .md / .txt / .pdf / .docx');
  var isDoc=(ext==='pdf'||ext==='docx');
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
  var ok=0, fail=0, added=0, pend=0, firstErr='';
  for(var i=0;i<arr.length;i++){
    setMsg('上传中 '+(i+1)+'/'+arr.length+'：'+arr[i].name);
    try{
      var r=await uploadOne(arr[i]);
      if(r&&r.ok){ ok++; added+=r.added_chunks||0; if(r.pending) pend++; }
      else{ fail++; if(!firstErr) firstErr=(r&&r.error)||'未知错误'; }
    }catch(e){ fail++; if(!firstErr) firstErr=e.message||String(e); }
  }
  BUSY=false;
  if(ok){
    if(pend){
      setMsg('已提交 '+pend+' 份待审批'+(fail?('，失败 '+fail+' 份（'+firstErr+'）'):'')+'；审批通过后才会进入检索', fail?'':'ok');
      toast('已提交 '+pend+' 份，等待审批');
    }else{
      setMsg('已入库 '+ok+' 份'+(fail?('，失败 '+fail+' 份（'+firstErr+'）'):'')+'，新增 '+added+' 块', fail?'':'ok');
      toast('已入库 '+ok+' 份，新增 '+added+' 块');
    }
    await loadKb();
  }else{
    setMsg('上传失败：'+firstErr,'err');
    toast('上传失败：'+firstErr,true);
  }
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
    if(d.ok){ setMsg('已删除 '+d.name,'ok'); toast('已删除：'+d.name); await loadKb(); }
    else{ setMsg('删除失败：'+(d.error||''),'err'); }
  }catch(e){ setMsg('删除失败：'+(e.message||e),'err'); }
};

$('apprRefresh').onclick=loadApprovals;
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
document.addEventListener('keydown',function(e){ if(e.key==='Escape') closeKbModal(); });

$('reload').onclick=async function(){
  var btn=this; btn.disabled=true; setMsg('正在重建索引…');
  try{
    var r=await (await fetch('/api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    if(r.ok){ setMsg('索引已重建：'+r.chunks+' 个知识块','ok'); toast('已加载 '+r.chunks+' 块'); await loadKb(); }
    else{ setMsg('重建失败：'+r.error,'err'); }
  }catch(e){ setMsg('重建失败：'+(e.message||e),'err'); }
  finally{ btn.disabled=false; }
};

loadKb();
"""

KB_HTML = shell("kb", "知识库 · " + BRAND, KB_BODY, KB_SCRIPT, KB_CSS)


# ======================================================================
# 评测看板
# ======================================================================
DASH_CSS = """
.page-head{display:flex;align-items:flex-end;gap:20px;margin-bottom:16px;flex-wrap:wrap;}
.page-head h1{font-size:27px;margin-top:8px;letter-spacing:-.03em;}
.page-head .sub{font-size:12.5px;color:var(--muted);margin-top:6px;line-height:1.75;}
.head-actions{display:flex;gap:8px;align-items:center;margin-left:auto;flex-wrap:wrap;}
.tabs{position:sticky;top:var(--nav-h);z-index:30;display:flex;gap:2px;padding:9px 0;margin:0 0 16px;
  background:linear-gradient(180deg,rgba(246,247,251,.97) 60%,rgba(246,247,251,0));overflow:auto;scrollbar-width:none;}
.tabs::-webkit-scrollbar{display:none;}
.tabs a{padding:6px 12px;border-radius:8px;font-size:12.5px;color:var(--muted);white-space:nowrap;transition:background .15s,color .15s;}
.tabs a:hover{background:#eef1f9;color:var(--ink);}
.tabs a.active{background:#fff;color:var(--brand-600);font-weight:600;box-shadow:var(--sh-1);border:1px solid var(--line);}
.panel{display:none;margin-bottom:20px;}
.panel.on{display:block;}
.panel.card{padding:20px;}
.kpis{margin-bottom:14px;}
.donut-wrap{display:flex;align-items:center;gap:24px;flex-wrap:wrap;}
.donut{position:relative;width:132px;height:132px;border-radius:50%;flex:none;background:#eef1f7;}
.donut::after{content:"";position:absolute;inset:19px;border-radius:50%;background:#fff;box-shadow:0 0 0 1px #f2f5fa inset;}
.donut .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:1;}
.donut .mid b{font-size:23px;letter-spacing:-.03em;color:var(--ink);font-variant-numeric:tabular-nums;line-height:1.1;}
.donut .mid span{font-size:10.5px;color:var(--faint);}
.legend{flex:1;min-width:190px;display:flex;flex-direction:column;gap:9px;}
.legend .li{display:flex;align-items:center;gap:8px;font-size:12.5px;}
.legend .dot{width:8px;height:8px;border-radius:3px;flex:none;}
.legend .nm{color:#475467;}
.legend .vv{margin-left:auto;color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600;}
.legend .pc{width:44px;text-align:right;color:var(--faint);font-variant-numeric:tabular-nums;font-size:11.5px;}
.mode-list{display:flex;flex-direction:column;gap:13px;margin-top:2px;}
.mode-item .top{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#475467;margin-bottom:5px;}
.mode-item .top b{margin-left:auto;color:var(--ink);font-variant-numeric:tabular-nums;}
.mode-item .bar{height:7px;}
.guard-row{display:flex;flex-wrap:wrap;gap:8px;}
.guard-item{display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:8px;padding:6px 10px;
  font-size:11.5px;color:var(--muted);background:#fff;}
.guard-item b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums;}

.l3-body{display:grid;grid-template-columns:1.15fr .85fr;gap:24px;align-items:center;}
.score-tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.score-tile{border:1px solid var(--line);border-radius:12px;padding:13px 14px;background:linear-gradient(180deg,#fff,#fbfcff);}
.score-tile .k{font-size:11.5px;color:var(--muted);}
.score-tile .v{font-size:26px;font-weight:700;color:var(--ink);letter-spacing:-.035em;margin:3px 0 8px;line-height:1.1;font-variant-numeric:tabular-nums;}
.score-tile .v small{font-size:11.5px;color:var(--faint);font-weight:500;letter-spacing:0;margin-left:2px;}
.score-tile .bar{height:5px;}
.l3-side{font-size:12.5px;color:var(--muted);line-height:1.9;}
.l3-side .row{flex-wrap:wrap;gap:6px;margin-bottom:9px;}
.l3-side b{color:var(--ink);font-weight:600;}
.l3-side a{color:var(--brand-600);font-weight:600;}
.l3-side a:hover{text-decoration:underline;}

.row-actions{display:flex;gap:5px;justify-content:flex-end;}
.row-actions button{padding:4px 8px;font-size:11.5px;}

.case-meta{display:flex;gap:7px;flex-wrap:wrap;align-items:center;}
.case-meta .pill{font-size:11px;}
.run-state{font-size:11.5px;color:var(--faint);margin-top:10px;line-height:1.7;word-break:break-word;}
.run-state.ok{color:var(--ok);} .run-state.err{color:var(--bad);}
.spin{display:inline-block;width:11px;height:11px;border:2px solid rgba(47,92,246,.25);border-top-color:var(--brand);
  border-radius:50%;animation:spin .8s linear infinite;vertical-align:-1px;margin-right:5px;}
@keyframes spin{to{transform:rotate(360deg);}}

.ts{font-family:var(--mono);font-size:11px;color:var(--faint);white-space:nowrap;}
.qcell{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.empty-row td{padding:26px 14px !important;text-align:center;color:var(--faint);font-size:12.5px;}

@media (max-width:900px){
  .l3-body{grid-template-columns:1fr;gap:18px;}
  .page-head h1{font-size:23px;}
}
@media (max-width:640px){
  .page-head .head-actions{margin-left:0;}
  .kpis{grid-template-columns:1fr 1fr;}
  .score-tiles{grid-template-columns:1fr 1fr 1fr;gap:7px;}
  .score-tile .v{font-size:21px;}
  .panel.card{padding:16px;}
  .qcell{max-width:150px;}
}
"""

DASHBOARD_BODY = """
<main class="wrap">
  <div class="page-head">
    <div>
      <div class="eyebrow">Operations</div>
      <h1>评测看板</h1>
      <p class="sub">运行指标与评测结果，实时聚合。</p>
    </div>
    <div class="head-actions">
      <span class="pill" id="stamp">加载中…</span>
      <a class="btn ghost sm" href="/report">汇报页</a>
      <button class="btn sm" id="refresh" type="button">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
        刷新
      </button>
    </div>
  </div>

  <nav class="tabs" id="tabs">
    <a href="#p-overview" class="active">概览</a>
    <a href="#p-quality">语义质量</a>
    <a href="#p-cases">评测用例</a>
    <a href="#p-feedback">反馈</a>
    <a href="#p-trace">对话日志</a>
  </nav>

  <section class="panel" id="p-overview">
    <div class="kpis" id="kpis"></div>
    <div class="grid2">
      <div class="card">
        <div class="card-head">
          <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/></svg>
          <h3>行为分布</h3><span class="hint">按请求计的最终动作</span>
        </div>
        <div id="behavior"></div>
      </div>
      <div class="card">
        <div class="card-head">
          <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
          <h3>生成模式</h3><span class="hint">LLM / 抽取 / 降级</span>
        </div>
        <div id="mode"></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head">
        <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/><path d="m9 12 2 2 4-4"/></svg>
        <h3>生产防护</h3><span class="hint">/api/health 实时状态</span>
      </div>
      <div class="guard-row" id="guard"></div>
    </div>
  </section>

  <section class="panel card" id="p-quality">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/><path d="m9 12 2 2 4-4"/></svg>
      <h3>语义质量 L3</h3><span class="hint">裁判模型评分，非确定性</span>
      <span class="spacer"></span><span class="pill brand" id="l3Judge">—</span>
    </div>
    <div id="l3"></div>
  </section>

  <section class="panel card" id="p-cases">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/></svg>
      <h3>评测用例</h3><span class="hint">L1 确定性断言 · 基础 + 反馈 + 文档</span>
      <span class="spacer"></span>
      <button class="btn sm" id="runDocs" type="button">运行文档用例</button>
      <button class="btn ghost sm" id="runAll" type="button">运行全部</button>
    </div>
    <div class="case-meta" id="caseMeta"></div>
    <div class="table-wrap" style="margin-top:12px">
      <table>
        <thead><tr><th>ID</th><th>问题</th><th>来源文档</th><th>出题方式</th><th>断言关键词</th></tr></thead>
        <tbody id="caseBody"></tbody>
      </table>
    </div>
    <div class="run-state" id="runMsg">文档用例可由知识库里的「出题」自动生成，也可由差评一键转换。</div>
  </section>

  <section class="panel card" id="p-feedback">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8"/><path d="M10 21h4"/></svg>
      <h3>反馈 / badcase</h3><span class="hint">差评可一键转成回归用例</span>
      <span class="spacer"></span><span class="pill" id="fbCount">—</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>时间</th><th>评价</th><th>说明</th><th>trace</th><th style="text-align:right">操作</th></tr></thead>
        <tbody id="fbBody"></tbody>
      </table>
    </div>
  </section>

  <section class="panel card" id="p-trace">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/></svg>
      <h3>最近对话</h3><span class="hint">最近 20 条 trace</span>
      <span class="spacer"></span><a class="pill brand" href="/ask">去问答页</a>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>时间</th><th>问题</th><th>行为</th><th>模式</th><th class="num">延迟</th></tr></thead>
        <tbody id="traceBody"></tbody>
      </table>
    </div>
  </section>
</main>

<div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
  <div class="modal-card">
    <h3 id="modalTitle">从反馈生成评测用例</h3>
    <p class="modal-sub" id="modalSub">把这条差评固化成回归用例，后续改动都会跑到它。</p>
    <div class="field">
      <label for="mKeywords">期望答案包含的关键词</label>
      <input id="mKeywords" placeholder="逗号分隔，可留空">
      <div class="hint">留空则只校验行为（该答的答出来 / 该拒的拒掉）。</div>
    </div>
    <div class="field">
      <label for="mBehavior">期望行为</label>
      <select id="mBehavior">
        <option value="answer">answer · 正常作答</option>
        <option value="no_answer">no_answer · 资料不足</option>
        <option value="refuse">refuse · 合规拒答</option>
        <option value="ask_clarify">ask_clarify · 追问澄清</option>
      </select>
    </div>
    <div class="modal-foot">
      <button class="btn ghost" id="mCancel" type="button">取消</button>
      <button class="btn" id="mOk" type="button">生成用例</button>
    </div>
  </div>
</div>
"""

DASHBOARD_SCRIPT = JS_UTIL + """
function $(id){ return document.getElementById(id); }
var COLORS={answer:'#2f5cf6',ask_clarify:'#0ea5a5',no_answer:'#d97706',refuse:'#94a3b8'};
var BEHAVIOR={answer:'作答',ask_clarify:'追问澄清',no_answer:'未找到',refuse:'拒答'};
var MODE={llm:'模型生成',extractive:'抽取式',extractive_fallback:'降级抽取'};
var MODE_COLORS={llm:'#2f5cf6',extractive:'#7a5cfb',extractive_fallback:'#d97706'};
var I={
  chat:'<path d="M4 5h16v11H9l-5 4z"/>',
  check:'<path d="m20 6-11 11-5-5"/>',
  alert:'<path d="M12 3 2 21h20z"/><path d="M12 9v5M12 17h.01"/>',
  shield:'<path d="M12 3l7 3v6c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/><path d="m9 12 2 2 4-4"/>',
  target:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  bolt:'<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>'
};
function ic(name,size){ return '<svg class="ic" width="'+(size||13)+'" height="'+(size||13)+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+I[name]+'</svg>'; }
function kpi(iconName,label,value,sub,accent){
  return '<div class="kpi'+(accent?' accent':'')+'"><div class="k">'+ic(iconName)+esc(label)+'</div>'
    +'<div class="v">'+value+'</div>'+(sub?'<div class="sub">'+esc(sub)+'</div>':'')+'</div>';
}
function pct(v){ return Math.round((v||0)*100)+'%'; }
function score(v){
  if(v==null) return '—';
  var s=String(Math.round(Number(v)*100)/100);
  return s.indexOf('.')<0?s+'.0':s;
}
function emptyRow(cols,text){ return '<tr class="empty-row"><td colspan="'+cols+'">'+esc(text)+'</td></tr>'; }

/* ---------- 概览 ---------- */
function renderKpis(m,cs,l3){
  var req=m.requests||0, bb=m.by_behavior||{}, mode=m.by_mode||{};
  var ans=bb.answer||0;
  var rate=req?ans/req:0;
  var ext=(mode.extractive||0)+(mode.extractive_fallback||0);
  $('kpis').innerHTML=
    kpi('chat','请求数',req,'累计处理')+
    kpi('check','答案率',req?pct(rate):'—','正常作答占比',true)+
    kpi('alert','未找到',bb.no_answer||0,'置信度不足')+
    kpi('target','引用覆盖率',m.avg_citation_coverage==null?'—':Math.round(m.avg_citation_coverage*100)+'%','近 500 条均值');
}
function renderBehavior(m){
  var bb=m.by_behavior||{}, keys=Object.keys(bb);
  var total=keys.reduce(function(a,k){return a+bb[k];},0);
  if(!total){ $('behavior').innerHTML='<div class="empty">'+ic('chart',24)+'<div>暂无请求记录</div></div>'; return; }
  var stops=[], p=0;
  var ordered=['answer','ask_clarify','no_answer','refuse'].filter(function(k){return bb[k];});
  Object.keys(bb).forEach(function(k){ if(ordered.indexOf(k)<0&&bb[k]) ordered.push(k); });
  ordered.forEach(function(k){
    var w=bb[k]/total*100;
    stops.push((COLORS[k]||'#94a3b8')+' '+p.toFixed(2)+'% '+(p+w).toFixed(2)+'%');
    p+=w;
  });
  var donut='<div class="donut" style="background:conic-gradient('+stops.join(',')+')">'
    +'<div class="mid"><b>'+total+'</b><span>请求</span></div></div>';
  var legend=ordered.map(function(k){
    return '<div class="li"><span class="dot" style="background:'+(COLORS[k]||'#94a3b8')+'"></span>'
      +'<span class="nm">'+esc(BEHAVIOR[k]||k)+'</span><span class="vv">'+bb[k]+'</span>'
      +'<span class="pc">'+pct(bb[k]/total)+'</span></div>';
  }).join('');
  $('behavior').innerHTML='<div class="donut-wrap">'+donut+'<div class="legend">'+legend+'</div></div>';
}
function renderMode(m){
  var mm=m.by_mode||{}, keys=Object.keys(mm);
  var total=keys.reduce(function(a,k){return a+mm[k];},0);
  if(!total){ $('mode').innerHTML='<div class="empty">'+ic('bolt',24)+'<div>暂无生成记录</div></div>'; return; }
  $('mode').innerHTML='<div class="mode-list">'+keys.map(function(k){
    var w=Math.round(mm[k]/total*100);
    return '<div class="mode-item"><div class="top"><span class="dot" style="width:7px;height:7px;border-radius:3px;background:'+(MODE_COLORS[k]||'#94a3b8')+'"></span>'
      +esc(MODE[k]||k)+'<b>'+mm[k]+' · '+w+'%</b></div>'
      +'<div class="bar"><i style="width:'+w+'%;background:'+(MODE_COLORS[k]||'#94a3b8')+'"></i></div></div>';
  }).join('')+'</div>';
}

/* ---------- L3 ---------- */
function renderL3(l3){
  var judge=$('l3Judge');
  if(!l3||!l3.available||!l3.avg){
    judge.textContent='未运行';
    $('l3').innerHTML='<div class="empty">'+ic('shield',26)
      +'<div>尚未运行 L3 语义评分</div>'
      +'<div class="mono" style="font-size:11.5px;background:#f7f9fd;border:1px solid var(--line);padding:6px 10px;border-radius:8px;margin-top:6px">python tests/eval_l3.py --report tests/report_llm.json</div>'
      +'</div>';
    return;
  }
  judge.textContent=(l3.judge_model||l3.judge_channel||'-');
  var gate=l3.gate||{};
  var gatePill=gate.passed?'<span class="pill ok"><span class="dot"></span>门禁通过</span>':'<span class="pill bad"><span class="dot"></span>门禁未过</span>';
  var tiles=[['faithfulness','忠实度'],['relevance','相关性'],['completeness','完整性']].map(function(d){
    var v=l3.avg[d[0]];
    return '<div class="score-tile"><div class="k">'+d[1]+'</div><div class="v">'+score(v)+'<small>/ 5</small></div>'
      +'<div class="bar"><i style="width:'+((v||0)*20)+'%"></i></div></div>';
  }).join('');
  $('l3').innerHTML='<div class="l3-body"><div class="score-tiles">'+tiles+'</div>'
    +'<div class="l3-side"><div class="row">'+gatePill
    +'<span class="pill">语义通过率 '+pct(l3.pass_rate)+'</span></div>'
    +'<div>样本 <b>'+(l3.answer_cases||0)+'</b> 条答案类 + <b>'+(l3.safety_cases||0)+'</b> 条拒答类；'
    +'编造告警 <b>'+((l3.hallucinations||[]).length)+'</b> 条。</div>'
    +'<div style="margin-top:8px">裁判消耗 '+(l3.total_tokens==null?'—':l3.total_tokens)+' tokens ｜ '
    +'<a href="/report#s-eval">完整汇报与校准 →</a></div>'
    +'<div class="hint" style="margin-top:6px;font-size:11px">L1 是对抗零容忍的发布门禁；L3 用来发现「关键词对了但答案是编的」。</div>'
    +'</div></div>';
}

/* ---------- 用例 ---------- */
function renderCases(cs){
  $('caseMeta').innerHTML=
    '<span class="pill brand">基础 '+cs.curated+'</span>'
    +'<span class="pill">反馈 '+cs.feedback+'</span>'
    +'<span class="pill">文档 '+cs.docs+'</span>'
    +'<span class="pill">共 '+cs.total+'</span>'
    +(cs.last_run?'<span class="pill '+(cs.last_run.pass_rate>=0.9?'ok':'warn')+'">最近 '+cs.last_run.passed+'/'+cs.last_run.total+' · '+pct(cs.last_run.pass_rate)+'</span>':'<span class="pill">尚未运行</span>');
  var items=cs.doc_items||[];
  if(!items.length){
    $('caseBody').innerHTML=emptyRow(5,'还没有文档用例：到「知识库」点「出题」，或从差评一键生成');
  }else{
    $('caseBody').innerHTML=items.map(function(c){
      return '<tr><td class="mono" style="font-size:11.5px">'+esc(c.id)+'</td>'
        +'<td>'+esc(c.input)+'</td><td class="muted" style="font-size:11.5px">'+esc(c.doc_id||'—')+'</td>'
        +'<td><span class="pill">'+esc(c.generated_by||'—')+'</span></td>'
        +'<td class="muted" style="font-size:11.5px">'+esc((c.keywords||[]).join('、')||'—')+'</td></tr>';
    }).join('');
  }
}
function setRun(text,cls){ var el=$('runMsg'); el.innerHTML=text; el.className='run-state'+(cls?' '+cls:''); }

async function runCases(scope){
  var btn=scope==='all'?$('runAll'):$('runDocs');
  var other=scope==='all'?$('runDocs'):$('runAll');
  btn.disabled=true; other.disabled=true;
  var label=btn.innerHTML;
  btn.innerHTML='<span class="spin"></span>运行中';
  setRun((scope==='all'?'正在运行全部用例（含基础集，LLM 模式可能数分钟）…':'正在运行文档用例…'));
  try{
    var r=await (await fetch('/api/cases/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({scope:scope,sleep:0})})).json();
    if(!r.total){
      setRun(r.skipped&&r.skipped.length?('全部 '+r.skipped.length+' 条用例对应的文档已删除，已跳过'):(r.error||'没有可运行的用例'),'err');
    }else{
      var txt='<b>'+r.passed+'/'+r.total+' 通过</b>（'+pct(r.pass_rate)+'），耗时 '+Math.round((r.duration_ms||0)/1000)+'s';
      if(r.skipped&&r.skipped.length) txt+='；跳过 '+r.skipped.length+' 条（文档已删除）';
      if(r.failed&&r.failed.length){
        txt+='<br>失败：'+r.failed.map(function(f){return esc(f.id)+'（'+esc((f.failures||[]).join('；'))+'）';}).join(' / ');
        setRun(txt,'err');
      }else{ setRun(txt,'ok'); }
      toast('评测完成：'+r.passed+'/'+r.total+' 通过');
      await loadAll();
    }
  }catch(e){ setRun('运行失败：'+esc(e.message||e),'err'); }
  finally{ btn.disabled=false; other.disabled=false; btn.innerHTML=label; }
}

/* ---------- 反馈 / 日志 ---------- */
function renderFeedback(fb){
  var items=fb.items||[];
  $('fbCount').textContent=items.length+' 条';
  if(!items.length){ $('fbBody').innerHTML=emptyRow(5,'暂无反馈。到问答页点一下 👎 试试。'); return; }
  $('fbBody').innerHTML=items.map(function(x){
    return '<tr><td class="ts">'+esc((x.ts||'').replace('T',' ').slice(5,19))+'</td>'
      +'<td>'+(x.useful?'<span class="pill ok"><span class="dot"></span>有用</span>':'<span class="pill bad"><span class="dot"></span>有问题</span>')+'</td>'
      +'<td class="muted" style="font-size:12px;max-width:260px">'+esc(x.comment||'—')+'</td>'
      +'<td class="mono" style="font-size:10.5px;color:var(--faint)">'+esc(x.trace_id)+'</td>'
      +'<td><div class="row-actions"><button class="btn ghost sm gen" data-trace="'+esc(x.trace_id)+'" data-note="'+esc(x.comment||'')+'">生成用例</button></div></td></tr>';
  }).join('');
}
function renderTrace(tr){
  var items=tr.items||[];
  if(!items.length){ $('traceBody').innerHTML=emptyRow(5,'暂无对话记录，去问答页问一句。'); return; }
  $('traceBody').innerHTML=items.map(function(x){
    return '<tr><td class="ts">'+esc((x.ts||'').replace('T',' ').slice(5,19))+'</td>'
      +'<td class="qcell" title="'+esc(x.query||'')+'">'+esc(x.query||'—')+'</td>'
      +'<td><span class="pill '+(x.behavior==='answer'?'ok':(x.behavior==='refuse'?'bad':(x.behavior==='no_answer'?'warn':'')))+'">'+esc(BEHAVIOR[x.behavior]||x.behavior||'—')+'</span></td>'
      +'<td class="muted" style="font-size:11.5px">'+esc(MODE[x.mode]||x.mode||'—')+'</td>'
      +'<td class="num mono" style="font-size:11.5px">'+(x.latency_ms==null?'—':Math.round(x.latency_ms)+' ms')+'</td></tr>';
  }).join('');
}

function renderGuard(h){
  var g=(h&&h.guards)||{}, b=g.budget||{}, c=g.canary||{};
  function item(k,v){ return '<span class="guard-item">'+k+' <b>'+esc(v==null?'—':v)+'</b></span>'; }
  $('guard').innerHTML=
    item('检索', h&&h.retrieval||'—')
    +item('限流', (g.rate_limit_rps||'—')+' rps / '+ (g.rate_limit_burst||'—'))
    +item('今日 tokens', (b.used||0)+' / '+(b.limit||0))
    +item('灰度', (c.canary_percent||0)+'%'+(c.canary_model?(' · '+c.canary_model):''));
}

/* ---------- 加载 ---------- */
async function loadAll(){
  try{
    var res=await Promise.all([
      fetch('/api/metrics').then(function(r){return r.json();}),
      fetch('/api/cases').then(function(r){return r.json();}),
      fetch('/api/l3').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/feedback/list?limit=20').then(function(r){return r.json();}),
      fetch('/api/trace?limit=20').then(function(r){return r.json();}),
      fetch('/api/health').then(function(r){return r.json();}).catch(function(){return {};})
    ]);
    renderKpis(res[0],res[1],res[2]);
    renderBehavior(res[0]);
    renderMode(res[0]);
    renderL3(res[2]);
    renderCases(res[1]);
    renderFeedback(res[3]);
    renderTrace(res[4]);
    renderGuard(res[5]);
    var d=new Date();
    $('stamp').textContent='更新于 '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  }catch(e){ toast('看板加载失败：'+(e.message||e),true); }
}

/* 差评转用例 */
var pendingTrace=null;
function openModal(traceId,note){
  pendingTrace=traceId;
  $('modalSub').textContent='trace '+traceId+(note?('｜用户说明：'+note):'')+'。固化后会进入回归集，后续改动都会跑到它。';
  $('mKeywords').value='';
  $('mBehavior').value='answer';
  $('modal').classList.add('open');
  setTimeout(function(){ $('mKeywords').focus(); },50);
}
function closeModal(){ $('modal').classList.remove('open'); pendingTrace=null; }
$('mCancel').onclick=closeModal;
$('modal').onclick=function(e){ if(e.target===$('modal')) closeModal(); };
document.addEventListener('keydown',function(e){ if(e.key==='Escape'&&$('modal').classList.contains('open')) closeModal(); });
$('mOk').onclick=async function(){
  if(!pendingTrace) return;
  var kws=$('mKeywords').value.split(/[,，]/).map(function(s){return s.trim();}).filter(Boolean);
  var behavior=$('mBehavior').value;
  var btn=this; btn.disabled=true; btn.textContent='生成中…';
  try{
    var r=await (await fetch('/api/cases/from_feedback',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({trace_id:pendingTrace,keywords:kws,behavior:behavior,note:''})})).json();
    if(r.ok){
      toast('已生成用例 '+r.case.id+'，累计 '+r.total+' 条');
      closeModal();
      await loadAll();
    }else{ toast('生成失败：'+(r.error||''),true); }
  }catch(e){ toast('生成失败：'+e,true); }
  finally{ btn.disabled=false; btn.textContent='生成用例'; }
};

$('fbBody').onclick=function(ev){
  var b=ev.target.closest('.gen'); if(!b) return;
  openModal(b.dataset.trace,b.dataset.note);
};

/* 标签页：一次只显示一个面板 */
var tabs=[].slice.call(document.querySelectorAll('#tabs a'));
var panels=[].slice.call(document.querySelectorAll('.panel'));
function showPanel(id,scroll){
  var hit=false;
  panels.forEach(function(p){ var on=('#'+p.id)===id; p.classList.toggle('on',on); if(on) hit=true; });
  if(!hit){ panels[0].classList.add('on'); id='#'+panels[0].id; }
  tabs.forEach(function(a){ a.classList.toggle('active', a.getAttribute('href')===id); });
  if(scroll!==false) window.scrollTo({top:0,behavior:'auto'});
}
tabs.forEach(function(a){
  a.onclick=function(e){
    e.preventDefault();
    var id=a.getAttribute('href');
    showPanel(id);
    history.replaceState(null,'',id);
  };
});
window.addEventListener('hashchange',function(){ showPanel(location.hash); });
loadAll().then(function(){ showPanel(location.hash||'#p-overview',false); });
"""

DASHBOARD_HTML = shell("dash", "评测看板 · " + BRAND, DASHBOARD_BODY, DASHBOARD_SCRIPT, DASH_CSS)
