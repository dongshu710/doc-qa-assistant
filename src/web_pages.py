"""原型页面（问答 / 知识库）。

只保留两个页面：提问与引用（/ask）、文档上传与知识库管理（/kb）。
对话内容的整理与保存由 src/notes 承担，不再占用页面。

设计系统在 theme.py；本文件只放各页面的结构与交互。全部为内联 HTML/CSS/JS，
不依赖 CDN、字体文件或前端框架，断网也能完整打开。
"""
from .theme import BRAND, JS_UTIL, MARK, shell

ASK_CSS = """
/* ============ 对话页 ============
   一列到底：标题栏、对话流、输入框。中间列宽 768px，和 DeepSeek 一致，
   窗口再宽也不再拉长行宽——长行难读，留白比放大更有用。 */
.stage-ask{display:flex;flex-direction:column;min-height:0;overflow:hidden;}
.ask-main{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;padding:0 20px;}
.hero{flex:1;display:flex;align-items:center;justify-content:center;width:100%;padding:4vh 0 20px;}
.hero-inner{width:100%;max-width:720px;text-align:center;}
.hero-mark{width:48px;height:48px;border-radius:15px;background:var(--brand);color:#fff;
  display:flex;align-items:center;justify-content:center;margin:0 auto 18px;}
.hero-mark .mark{width:48px;height:48px;border-radius:15px;background:transparent;box-shadow:none;}
.hero-mark .mark svg{width:26px;height:26px;}
.hero h1{font-size:26px;font-weight:600;letter-spacing:-.02em;color:var(--ink);}
.hero-sub{margin-top:10px;font-size:13px;color:var(--muted);}

.chat-list{flex:1;min-height:0;overflow-y:auto;width:100%;max-width:768px;padding:8px 0 18px;
  display:flex;flex-direction:column;gap:26px;}
.chat-list:empty{display:none;}
.chat-list::-webkit-scrollbar{width:8px;}
.chat-list::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:8px;}
.chat-list::-webkit-scrollbar-track{background:transparent;}

.ex-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:18px;}
.ex-card{text-align:left;padding:11px 13px;border:1px solid var(--line);border-radius:12px;
  background:var(--surface);cursor:pointer;font-size:12.8px;color:var(--text);line-height:1.6;
  font-family:inherit;transition:background .14s,border-color .14s;}
.ex-card:hover{border-color:var(--line-2);background:var(--surface-2);}
@media (max-width:560px){.ex-cards{grid-template-columns:1fr;}}

/* 消息：用户右侧浅灰气泡，助手不分卡片、直接排正文——这样长答案不会被框切碎 */
.msg{display:flex;max-width:100%;animation:rise .2s ease both;}
@keyframes rise{from{opacity:0;transform:translateY(5px);}to{opacity:1;transform:none;}}
.msg.user{justify-content:flex-end;}
.bubble{background:#f2f3f5;color:var(--ink);padding:9px 14px;border-radius:18px;
  max-width:78%;font-size:14px;line-height:1.75;white-space:pre-wrap;word-break:break-word;}
.msg.bot .avatar{display:none;}
.msg-body{flex:1;min-width:0;}
.ans-card{background:transparent;border:0;border-radius:0;padding:0;box-shadow:none;}
.ans-label{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--faint);
  font-weight:500;margin-bottom:8px;}
.answer{font-size:14.5px;line-height:1.9;white-space:pre-wrap;word-break:break-word;color:var(--text);}
.answer.streaming::after{content:"";display:inline-block;width:6px;height:15px;margin-left:3px;
  vertical-align:-2px;background:var(--brand);border-radius:1px;animation:blink 1s steps(2) infinite;}
@keyframes blink{50%{opacity:0;}}
.kw-hit{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 9px;}
.kw-hit-t{font-size:12px;color:var(--faint);}
.kw-term{font-size:12px;color:var(--brand);background:var(--brand-soft);border:1px solid var(--line);
  border-radius:999px;padding:2px 8px;line-height:1.5;}
.answer strong{font-weight:600;color:var(--ink);}
.answer .cite-n{display:inline-flex;align-items:center;justify-content:center;min-width:15px;height:15px;
  border-radius:4px;background:var(--brand-soft);color:var(--brand-600);font-size:11.5px;font-weight:600;
  padding:0 3px;vertical-align:1px;margin:0 1px;}
.refs{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;}
.ref{display:inline-flex;align-items:center;gap:6px;font-size:12px;background:var(--surface);
  border:1px solid var(--line);color:var(--muted);padding:3px 9px 3px 4px;border-radius:8px;
  line-height:1.5;cursor:pointer;font-family:inherit;transition:all .14s;}
.ref:hover{border-color:var(--brand);background:var(--brand-tint);color:var(--brand);}

/* 输入框：DeepSeek 的做法是一个大圆角浮层，工具项收在框内底部一行 */
.composer{flex:none;width:100%;max-width:768px;padding:4px 0 14px;}
.composer-box{border:1px solid var(--line-2);border-radius:22px;padding:10px 10px 8px 16px;
  background:var(--surface);transition:border-color .15s,box-shadow .15s;}
.composer-box:focus-within{border-color:#cfd3dc;box-shadow:0 2px 12px -8px rgba(17,18,22,.35);}
.composer textarea{width:100%;min-height:26px;max-height:160px;border:0;outline:none;resize:none;
  background:transparent;font:14.5px/1.7 var(--font);color:var(--text);padding:2px 0;display:block;}
.composer textarea::placeholder{color:var(--faint);}
.composer-bar{display:flex;align-items:center;gap:6px;margin-top:6px;}
.composer-bar .spacer{flex:1;}
.chip{height:28px;padding:0 10px;border:1px solid var(--line);border-radius:14px;background:var(--surface);
  color:var(--muted);font-size:12px;font-family:inherit;cursor:pointer;
  display:inline-flex;align-items:center;gap:6px;transition:background .14s,border-color .14s;}
.chip:hover{background:var(--surface-2);color:var(--ink);}
.chip .dot{width:5px;height:5px;border-radius:50%;background:var(--ok);flex:none;}
.chip.warn .dot{background:#e0a100;}
.chip.on{border-color:#c9d3ff;background:var(--brand-tint);color:var(--brand-600);}
.send{flex:none;width:32px;height:32px;border:0;border-radius:50%;background:var(--brand);color:#fff;
  display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:background .14s;}
.send:hover{background:var(--brand-600);}
.send:disabled{background:#e6e8ec;cursor:not-allowed;}
.send.stop{background:var(--ink);}
.composer-hint{display:flex;justify-content:center;gap:12px;margin-top:8px;font-size:11.5px;color:var(--faint);}
.composer-hint span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.keybar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;padding:8px 12px;
  border:1px solid var(--line);border-radius:12px;background:var(--surface-2);font-size:12px;color:var(--muted);}
.keybar input{flex:1;min-width:140px;height:28px;padding:0 9px;border:1px solid var(--line-2);
  border-radius:7px;font-size:12.5px;background:var(--surface);color:var(--text);}
.key-note{color:var(--faint);}
@media (max-width:900px){
  .stage-ask{overflow:auto;}
  .ask-main{padding:0 12px;min-height:calc(100vh - 52px);}
  .hero{padding:8vh 0 16px;}
  .chat-list{overflow:visible;}
  .composer{position:sticky;bottom:0;background:var(--surface);padding-bottom:10px;}
}

.src-mask{position:fixed;inset:0;background:rgba(10,16,32,.34);z-index:80;}
.src-drawer{position:fixed;top:0;right:0;height:100%;width:min(540px,94vw);background:#fff;z-index:81;
  box-shadow:-24px 0 60px -30px rgba(10,16,32,.55);display:flex;flex-direction:column;
  transform:translateX(8px);opacity:0;transition:transform .18s ease,opacity .18s ease;}
.src-drawer.open{transform:none;opacity:1;}
.src-head{display:flex;align-items:flex-start;gap:12px;padding:16px 18px 13px;border-bottom:1px solid var(--line);}
.src-head b{font-size:14px;color:var(--ink);line-height:1.5;}
.src-sub{font-size:12px;color:var(--muted);margin-top:3px;line-height:1.6;}
.src-close{margin-left:auto;border:none;background:#f3f5fa;width:28px;height:28px;border-radius:8px;
  font-size:17px;line-height:1;color:var(--muted);cursor:pointer;flex:none;}
.src-close:hover{background:#e9edf7;color:var(--ink);}
.src-text{margin:0;padding:18px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  font-size:13px;line-height:1.9;color:#344054;font-family:inherit;flex:1;}
.src-text mark{background:#fff3bf;color:#6b4b00;border-radius:3px;padding:0 1px;}
.ref b{width:16px;height:16px;border-radius:5px;background:var(--brand);color:#fff;font-size:12px;
  display:flex;align-items:center;justify-content:center;font-weight:600;flex:none;}
.ans-foot{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px;padding-top:11px;border-top:1px dashed #e8ecf5;}
.ans-foot .pill{font-size:12px;padding:2px 8px;}

details.src{margin-top:10px;border-top:1px dashed #eef1f7;padding-top:9px;}
details.src summary{cursor:pointer;font-size:12px;color:var(--muted);list-style:none;display:flex;align-items:center;gap:5px;user-select:none;}
details.src summary::-webkit-details-marker{display:none;}
details.src summary .ic{transition:transform .18s ease;color:#a9b3c6;}
details.src[open] summary .ic{transform:rotate(90deg);}
.src-list{margin-top:8px;display:flex;flex-direction:column;gap:1px;}
.src-row{display:flex;align-items:baseline;gap:8px;font-size:12px;padding:5px 0;color:#4b5565;border-bottom:1px solid #f6f8fc;}
.src-row:last-child{border-bottom:none;}
.src-row .rank{width:16px;flex:none;font-family:var(--mono);font-size:12px;color:var(--faint);}
.src-row .sc{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--faint);white-space:nowrap;}

.fb{display:flex;gap:6px;margin-top:12px;align-items:center;flex-wrap:wrap;}
.fb-q{font-size:12px;color:var(--faint);margin-right:2px;}
.fb button{display:inline-flex;gap:5px;align-items:center;padding:5px 10px;font-size:12px;border:1px solid var(--line);
  background:#fff;color:var(--muted);border-radius:8px;cursor:pointer;transition:all .14s;font-family:inherit;}
.fb button:hover{border-color:#c3d0f8;color:var(--brand-600);background:var(--brand-tint);}
.fb button.on{border-color:#c3d0f8;color:var(--brand-600);background:var(--brand-soft);}
.fb-done{font-size:12px;color:var(--ok);display:inline-flex;align-items:center;gap:5px;}
.fb-note{display:none;width:100%;gap:6px;margin-top:2px;flex-wrap:wrap;}
.fb-note.open{display:flex;}
.fb-note input{flex:1;min-width:150px;padding:7px 10px;border:1px solid var(--line-2);border-radius:8px;font-size:12px;outline:none;font-family:inherit;}
.fb-note input:focus{border-color:var(--brand);}

.sim{margin-top:14px;padding-top:12px;border-top:1px dashed #eddbb9;}
.sim-title{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#a97a33;margin-bottom:7px;}
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
"""


_ASK_ART = (
    '<svg width="50" height="50" viewBox="0 0 48 48" fill="none" aria-hidden="true">'
    '<rect x="8.5" y="5" width="23" height="31" rx="4" stroke="currentColor" stroke-width="1.7"/>'
    '<path d="M15 13.5h10M15 19.5h10M15 25.5h6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    '<circle cx="32.5" cy="31.5" r="7" fill="#f9fbff" stroke="currentColor" stroke-width="1.7"/>'
    '<path d="m37.6 36.6 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    "</svg>"
)

ASK_CSS += """
/* ---------- 存为笔记 ---------- */
.fb-save{display:inline-flex;align-items:center;gap:5px;}
.note-mask{position:fixed;inset:0;background:rgba(10,16,32,.42);z-index:60;backdrop-filter:blur(2px);}
.note-dialog{position:fixed;z-index:61;left:50%;top:50%;transform:translate(-50%,-50%);
  width:min(560px,calc(100vw - 32px));max-height:min(660px,calc(100vh - 60px));display:flex;flex-direction:column;
  background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--sh-3);overflow:hidden;}
.note-dlg-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;
  border-bottom:1px solid var(--line);font-size:14px;}
.note-dlg-head button{border:none;background:none;font-size:20px;line-height:1;color:var(--faint);cursor:pointer;padding:0 4px;}
.note-dlg-head button:hover{color:var(--ink);}
.note-dlg-body{padding:14px 16px;overflow:auto;display:flex;flex-direction:column;gap:10px;}
.nd-field{display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--faint);flex:1;}
.nd-field input,.nd-field select{padding:8px 10px;border:1px solid var(--line-2);border-radius:8px;
  font:13px/1.5 var(--font);color:var(--text);background:var(--surface);outline:none;}
.nd-field input:focus,.nd-field select:focus{border-color:#b9c8f7;box-shadow:0 0 0 3px rgba(47,92,246,.07);}
.nd-row{display:flex;gap:10px;flex-wrap:wrap;}
.nd-preview{margin:0;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);
  font:12px/1.75 var(--mono);color:var(--text);white-space:pre-wrap;word-break:break-word;
  max-height:280px;overflow:auto;}
.nd-hint{font-size:11.5px;color:var(--faint);line-height:1.6;}
.note-dlg-foot{display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;border-top:1px solid var(--line);}
@media (max-width:520px){
  .note-dialog{width:100vw;max-height:88vh;left:0;top:auto;bottom:0;transform:none;border-radius:16px 16px 0 0;}
}
"""

# 旧组件里的写死色统一回收成令牌；只保留真正需要覆盖的几条
ASK_CSS += """
.ans-foot{border-top-color:var(--line);}
details.src{border-top-color:var(--line);}
.src-row{color:var(--muted);border-bottom-color:var(--line);}
.src-close{background:var(--surface-2);}
.src-close:hover{background:var(--line);}
.src-text{color:var(--text);}
.fb button:hover{border-color:var(--brand);color:var(--brand);background:var(--brand-tint);}
.fb button.on{border-color:var(--brand);color:var(--brand);background:var(--brand-soft);}
.nd-field input:focus,.nd-field select:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft);}
.sk{background:linear-gradient(90deg,var(--surface-2),var(--line),var(--surface-2));}
[data-theme="dark"] .bubble{background:#2a2b31;color:var(--ink);}
[data-theme="dark"] .composer-box{background:var(--surface);}
"""


ASK_BODY = """
<header class="topbar">
  <div class="tb-title" id="tbTitle">新对话</div>
  <span class="tb-sub" id="tbSub"></span>
  <div class="tb-actions">
    <button class="tb-link" id="exportMd" type="button" title="把当前对话导成 Markdown">导出</button>
    <button class="tb-link" id="clear" type="button" title="清空当前对话">清空</button>
  </div>
</header>
<main class="ask-main">
  <section class="hero" id="hero">
    <div class="hero-inner">
      <div class="hero-mark" aria-hidden="true">__MARK__</div>
      <h1>有什么可以帮你？</h1>
      <p class="hero-sub">只依据知识库作答，每条都给出来源。可以这样问：</p>
      <div class="ex-cards" id="exCards"></div>
    </div>
  </section>
  <div id="list" class="chat-list" aria-live="polite"></div>
  <div class="composer" id="composer">
    <div class="keybar" id="keyBar" hidden>
      <span>接口已启用 API Key</span>
      <input id="apiKey" type="password" placeholder="粘贴 Key 后回车" autocomplete="off">
      <button class="btn sm" id="keySave" type="button">保存</button>
      <span class="key-note" id="keyNote"></span>
    </div>
    <div class="composer-box">
      <textarea id="q" rows="1" placeholder="给记忆文档发送消息…" autocomplete="off"></textarea>
      <div class="composer-bar">
        <button class="chip" id="kbChip" type="button" title="查看知识库版本与文档">
          <span class="dot"></span><span id="kbChipText">知识库</span></button>
        <button class="chip warn" id="apiChip" type="button" title="配置模型接口">
          <span class="dot"></span><span id="apiChipText">离线抽取</span></button>
        <span class="spacer"></span>
        <button class="send" id="send" type="button" aria-label="发送">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>
        </button>
      </div>
    </div>
    <div class="composer-hint">
      <span id="kbdHint">Enter 发送 · Shift + Enter 换行</span>
      <span id="composerNote"></span>
    </div>
  </div>
  <div class="src-mask" id="srcMask" hidden></div>
  <aside class="src-drawer" id="srcDrawer" hidden aria-label="引用原文">
    <div class="src-head">
      <div><b id="srcTitle">原文</b><div class="src-sub" id="srcSub"></div></div>
      <button class="src-close" id="srcClose" type="button" aria-label="关闭">×</button>
    </div>
    <pre class="src-text" id="srcText"></pre>
  </aside>
  <div class="note-mask" id="noteMask" hidden></div>
  <div class="note-dialog" id="noteDialog" hidden role="dialog" aria-modal="true" aria-labelledby="noteDlgTitle">
    <div class="note-dlg-head"><b id="noteDlgTitle">存为笔记</b>
      <button id="noteDlgClose" type="button" aria-label="关闭">×</button></div>
    <div class="note-dlg-body">
      <label class="nd-field">标题<input id="ndTitle" maxlength="120" placeholder="一句话说清留下了什么"></label>
      <div class="nd-row">
        <label class="nd-field">标签<input id="ndTags" placeholder="逗号分隔，可留空"></label>
        <label class="nd-field">类型<select id="ndKind">
          <option value="qa">问答</option><option value="decision">决策</option>
          <option value="howto">做法</option><option value="reference">资料</option>
          <option value="log">记录</option></select></label>
      </div>
      <pre class="nd-preview" id="ndPreview">整理中…</pre>
      <div class="nd-hint" id="ndHint">本地规则整理，不联网。</div>
    </div>
    <div class="note-dlg-foot">
      <button class="btn ghost sm" id="ndCancel" type="button">取消</button>
      <button class="btn sm" id="ndSave" type="button">保存到笔记</button>
    </div>
  </div>
</main>
""".replace("__MARK__", MARK)

ASK_SCRIPT = """
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
var ART='""" + _ASK_ART.replace("'", "\\'") + """';

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
  s=s.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/\\[(\\d+)\\]/g,'<span class="cite-n">$1</span>');
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
    var body=md.replace(/^---[\\s\\S]*?\\n---\\n?/,'');
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
"""

ASK_HTML = shell("ask", "问答 · " + BRAND, ASK_BODY, ASK_SCRIPT, ASK_CSS)


# ======================================================================
# 知识库
# ======================================================================
KB_CSS = """
.kb-wrap{max-width:1060px;}
.kb-head{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:16px;}
.kb-head h1{font-size:22px;letter-spacing:-.02em;}
.kb-head .actions{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.kb-layout{display:grid;grid-template-columns:300px minmax(0,1fr);gap:14px;align-items:start;}
.kb-side{display:flex;flex-direction:column;gap:12px;position:sticky;top:16px;}
.kb-side .card{padding:16px;}
.kb-side .side-title{font-size:12px;font-weight:600;letter-spacing:.02em;color:var(--faint);margin-bottom:10px;}

.drop{border:1px dashed var(--line-2);border-radius:var(--r);background:var(--surface-2);
  padding:22px 14px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;
  text-align:center;cursor:pointer;transition:border-color .16s,background .16s;}
.drop:hover,.drop.over{border-color:var(--brand);background:var(--brand-tint);}
.drop .dic{width:38px;height:38px;border-radius:11px;background:var(--brand-soft);color:var(--brand);
  display:flex;align-items:center;justify-content:center;margin-bottom:4px;}
.drop b{font-size:13px;color:var(--ink);font-weight:600;}
.drop span{font-size:12px;color:var(--faint);line-height:1.65;}
.kb-status{font-size:12px;color:var(--faint);margin-top:10px;min-height:17px;line-height:1.65;word-break:break-word;}
.kb-status.ok{color:var(--ok);font-weight:500;}
.kb-status.err{color:var(--bad);font-weight:500;}

.kb-list{padding:16px;}
.kb-list table{table-layout:fixed;}
.kb-list th:nth-child(1){width:auto;}
.kb-list th:nth-child(2){width:58px;}
/* 关键词数量属于「有也行没有也行」的元数据，占一列只会挤压文件名；直接不显示 */
.kb-list th:nth-child(3),.kb-list td:nth-child(3){display:none;}
.kb-list th:nth-child(4){width:60px;}
.kb-list th:nth-child(5){width:142px;}
.kb-list th:nth-child(6){width:154px;}
.kb-list td{white-space:nowrap;}
.kb-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;}
.search{position:relative;flex:1;min-width:150px;}
.search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);color:#a9b3c6;}
.search input{width:100%;padding:7px 10px 7px 29px;border:1px solid var(--line-2);border-radius:8px;
  font-size:12px;font-family:inherit;outline:none;background:#fff;color:var(--text);}
.search input:focus{border-color:#b9c8f7;box-shadow:0 0 0 3px rgba(47,92,246,.07);}
.chips{display:flex;gap:2px;}
.chips button{border:none;background:none;padding:5px 8px;border-radius:7px;font-size:12px;font-family:inherit;
  color:var(--muted);cursor:pointer;}
.chips button:hover{background:#f2f5fb;color:var(--ink);}
.chips button.on{background:var(--brand-soft);color:var(--brand-600);font-weight:600;}
.kb-sort{padding:6px 8px;border:1px solid var(--line-2);border-radius:8px;font-size:12px;font-family:inherit;
  color:var(--muted);background:#fff;outline:none;cursor:pointer;}
.kb-foot{font-size:12px;color:var(--faint);margin-top:10px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;}

.fname{display:flex;align-items:center;gap:9px;min-width:0;}
.ftype{font-family:var(--mono);font-size:12px;font-weight:600;padding:2px 5px;border-radius:4px;flex:none;
  background:#eef1f7;color:#667085;letter-spacing:.02em;}
.ftype.pdf{background:#fef1f0;color:#b42318;} .ftype.docx{background:#eef2ff;color:#2a49c8;}
.ftype.md{background:#e9f9f1;color:#0a7a4d;} .ftype.txt{background:#f4f6fa;color:#54617a;}
.fname .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;}
.row-actions{display:flex;gap:5px;justify-content:flex-end;}
.row-actions button{padding:4px 8px;font-size:12px;}
.empty-row td{padding:30px 14px !important;text-align:center;color:var(--faint);font-size:12.5px;}
.ts{font-family:var(--mono);font-size:12px;color:var(--faint);white-space:nowrap;}
.kw-btn{border:none;background:none;padding:2px 4px;font:inherit;font-size:12px;color:var(--brand-600);
  cursor:pointer;border-bottom:1px dashed #c6d3fa;font-variant-numeric:tabular-nums;}
.kw-btn:hover{color:var(--brand);border-bottom-color:var(--brand);}
.kw-row td{padding:0 !important;background:#fafbff;}
.kw-box{padding:13px 16px 15px;border-top:1px solid #eef2fb;}
.kw-sum{font-size:12px;color:var(--muted);line-height:1.7;margin-bottom:9px;}
.kw-chips{display:flex;flex-wrap:wrap;gap:6px;}
.kw-chip{font-size:12px;color:#334155;background:#fff;border:1px solid var(--line-2);border-radius:999px;
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
.appr-files{font-size:12px;color:#8a6a33;margin-top:4px;line-height:1.7;word-break:break-word;}
.appr-actions{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;}
.appr-token{display:flex;gap:6px;margin-top:10px;align-items:center;font-size:12px;color:#8a6a33;flex-wrap:wrap;}
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
.diff{background:#0f172a;color:#dbe4f3;border-radius:10px;padding:12px;font-family:var(--mono);font-size:12px;
  line-height:1.65;white-space:pre-wrap;overflow:auto;max-height:52vh;}
.diff .add{color:#7ee2a8;} .diff .del{color:#ff9b9b;} .diff .meta{color:#93a4c3;}
.diff-title{display:flex;align-items:center;gap:8px;margin:12px 0 6px;font-size:12px;color:var(--muted);}
.hist-item{display:flex;align-items:center;gap:9px;padding:9px 0;border-bottom:1px solid var(--line);font-size:12px;flex-wrap:wrap;}
.hist-item:last-child{border-bottom:none;}

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

KB_CSS += """
/* ---------- 文档 / 笔记 切换 ---------- */
.kb-tabs{display:inline-flex;gap:2px;padding:3px;background:#eef1f7;border-radius:10px;margin-bottom:16px;}
.kb-tabs button{border:none;background:none;padding:7px 18px;border-radius:8px;font-size:13px;
  font-family:inherit;color:var(--muted);cursor:pointer;transition:background .15s,color .15s;}
.kb-tabs button:hover{color:var(--ink);}
.kb-tabs button.on{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(20,30,50,.08);}
[data-theme="dark"] .kb-tabs{background:#0f172a;}
[data-theme="dark"] .kb-tabs button.on{background:#1b2537;box-shadow:none;}

/* ---------- 笔记分区 ---------- */
.notes-layout{display:grid;grid-template-columns:330px minmax(0,1fr);gap:16px;align-items:start;}
.notes-side{padding:14px;display:flex;flex-direction:column;gap:9px;
  position:sticky;top:16px;}
.notes-tools{display:flex;gap:6px;flex-wrap:wrap;}
.notes-tools .search{flex:1 1 130px;}
.notes-tools .kb-sort{flex:1 1 96px;min-width:0;}
.notes-count{font-size:11.5px;color:var(--faint);}
.notes-list{display:flex;flex-direction:column;gap:6px;max-height:min(58vh,560px);overflow:auto;
  padding-right:2px;margin:-2px 0;}
.note-item{text-align:left;border:1px solid var(--line);background:var(--surface);border-radius:10px;
  padding:9px 10px;cursor:pointer;font-family:inherit;transition:border-color .15s,background .15s;}
.note-item:hover{border-color:#c9d6f5;background:var(--brand-tint);}
.note-item.on{border-color:#b9c8f7;background:var(--brand-tint);}
.note-item b{display:block;font-size:12.5px;font-weight:600;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.note-item span{display:block;font-size:11.5px;color:var(--faint);margin-top:3px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.note-item .ntag{color:var(--brand-600);}
.notes-actions{display:flex;gap:6px;padding-top:2px;}
.notes-actions .btn{flex:1;justify-content:center;}
.notes-main{padding:18px;min-height:340px;}
.note-empty{color:var(--faint);font-size:12.5px;line-height:1.9;padding:26px 4px;text-align:center;}
.note-empty b{color:var(--ink);font-weight:600;display:block;margin-bottom:4px;font-size:13px;}
.ne-head{display:flex;align-items:center;gap:10px;}
.ne-title{flex:1;min-width:0;border:none;border-bottom:1px solid transparent;background:transparent;
  font:600 18px/1.4 var(--font);color:var(--ink);padding:4px 2px;outline:none;}
.ne-title:hover{border-color:var(--line);}
.ne-title:focus{border-color:#b9c8f7;}
.ne-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;}
.ne-row label{display:flex;flex-direction:column;gap:4px;font-size:11.5px;color:var(--faint);flex:1 1 120px;}
.ne-row input,.ne-row select{padding:7px 9px;border:1px solid var(--line-2);border-radius:8px;
  font:12.5px/1.5 var(--font);color:var(--text);background:var(--surface);outline:none;min-width:0;}
.ne-row input:focus,.ne-row select:focus{border-color:#b9c8f7;box-shadow:0 0 0 3px rgba(47,92,246,.07);}
.ne-row input[readonly]{color:var(--faint);background:var(--surface-2);}
.ne-sections{margin-top:14px;display:flex;flex-direction:column;gap:9px;}
.ne-sec{border:1px solid var(--line);border-radius:10px;padding:9px 11px;background:var(--surface-2);}
.ne-sec-head{display:flex;align-items:center;justify-content:space-between;font-size:11.5px;
  letter-spacing:.06em;color:var(--faint);font-weight:600;}
.ne-sec-head button{border:none;background:none;color:#b6bfd0;font-size:15px;line-height:1;cursor:pointer;padding:0 2px;}
.ne-sec-head button:hover{color:var(--bad);}
.ne-sec textarea{width:100%;margin-top:5px;border:none;background:transparent;resize:vertical;
  font:13px/1.75 var(--font);color:var(--text);outline:none;min-height:56px;}
.ne-foot{display:flex;gap:8px;align-items:center;margin-top:14px;flex-wrap:wrap;}
.ne-hint{font-size:11.5px;color:var(--faint);margin-right:auto;font-family:var(--mono);}
@media (max-width:860px){
  .kb-layout,.notes-layout{grid-template-columns:1fr;}
  .kb-side,.notes-side{position:static;}
  .notes-list{max-height:240px;}
}
"""


KB_BODY = """
<main class="wrap kb-wrap">
  <div class="kb-head">
    <div>
      <h1>知识库</h1>
    </div>
    <div class="actions">
      <span class="pill" id="kbVersion">—</span>
      <span class="pill" id="kbMeta">加载中…</span>
      <button class="btn ghost sm" id="reload" type="button">重建索引</button>
    </div>
  </div>

  <div class="kb-tabs" role="tablist" aria-label="知识库分区">
    <button type="button" class="on" data-tab="docs" role="tab" aria-selected="true">文档</button>
    <button type="button" data-tab="notes" role="tab" aria-selected="false">笔记</button>
  </div>

  <div id="panelDocs">
  <div class="kb-layout">
    <div class="kb-side">
      <section class="card">
        <div class="side-title">上传文档</div>
        <div class="drop" id="drop">
          <div class="dic">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
          </div>
          <b>拖拽或点击上传</b>
          <span>.md / .txt / .pdf / .docx · 可多选<br>文本 ≤ 512 KB · PDF/Word ≤ 6 MB</span>
          <input type="file" id="kbFile" accept=".md,.txt,.pdf,.docx,.xlsx,.csv,.tsv" multiple hidden>
        </div>
        <div class="kb-status" id="kbMsg"></div>
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
  </div>

  <div class="notes-layout" id="panelNotes" hidden>
    <aside class="card notes-side">
      <div class="notes-tools">
        <div class="search">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="noteSearch" placeholder="搜索标题 / 标签" autocomplete="off">
        </div>
      </div>
      <div class="notes-tools">
        <select class="kb-sort" id="noteKind" aria-label="按类型筛选">
          <option value="">全部类型</option>
          <option value="decision">决策</option><option value="howto">做法</option>
          <option value="reference">资料</option><option value="qa">问答</option>
          <option value="log">记录</option>
        </select>
        <select class="kb-sort" id="noteStatus" aria-label="按状态筛选">
          <option value="">全部状态</option>
          <option value="draft">草稿</option><option value="final">定稿</option>
          <option value="archived">归档</option>
        </select>
      </div>
      <div class="notes-count" id="noteCount">加载中…</div>
      <div class="notes-list" id="noteList"></div>
      <div class="notes-actions">
        <button class="btn ghost sm" id="noteExportHtml" type="button">导出 HTML</button>
        <button class="btn ghost sm" id="noteExportJson" type="button">JSON</button>
      </div>
    </aside>

    <section class="card notes-main">
      <div class="note-empty" id="noteEmpty"><b>还没有选中笔记</b>左侧选一篇；或在问答页点「存为笔记」，让智能体直接存进来。</div>
      <div id="noteEditor" hidden>
        <div class="ne-head">
          <input id="neTitle" class="ne-title" maxlength="120" aria-label="笔记标题">
          <span class="pill" id="neMeta">—</span>
        </div>
        <div class="ne-row">
          <label>标签<input id="neTags" placeholder="逗号分隔"></label>
          <label>类型<select id="neKind">
            <option value="qa">问答</option><option value="decision">决策</option>
            <option value="howto">做法</option><option value="reference">资料</option>
            <option value="log">记录</option></select></label>
          <label>状态<select id="neStatus">
            <option value="draft">草稿</option><option value="final">定稿</option>
            <option value="archived">归档</option></select></label>
          <label>创建<input id="neCreated" readonly></label>
        </div>
        <div class="ne-sections" id="neSections"></div>
        <div class="ne-foot">
          <span class="ne-hint" id="neHint"></span>
          <button class="btn ghost sm" id="neAddSec" type="button">加小节</button>
          <button class="btn ghost sm" id="neDelete" type="button">删除</button>
          <button class="btn sm" id="neSave" type="button">保存</button>
        </div>
      </div>
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

KB_SCRIPT = """
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
  $('kbMeta').textContent=total+' 份 · '+chunks+' 块'+(KB.rebuilding?' · 索引重建中':'')
    +(KB.pending_changes?(' · 待审批 '+KB.pending_changes):'');
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
      +'<td class="num mono" style="font-size:12px;color:var(--muted)">'+sizeText(f.size)+'</td>'
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
    await settleIndex(d.rebuilding, '已回滚');
  }catch(e){ toast('回滚失败：'+(e.message||e),true); }
}

async function loadKb(){
  try{
    var r=await (await fetch('/api/knowledge')).json();
    KB=r; render(); await loadApprovals();
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
  var ok=0, fail=0, added=0, pend=0, rebuilding=false, firstErr='', notes=[];
  for(var i=0;i<arr.length;i++){
    setMsg('上传中 '+(i+1)+'/'+arr.length+'：'+arr[i].name);
    try{
      var r=await uploadOne(arr[i]);
      if(r&&r.ok){
        ok++; added+=r.added_chunks||0; if(r.pending) pend++;
        if(r.rebuilding) rebuilding=true;
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
    if(d.ok){ setMsg('已删除 '+d.name,'ok'); toast('已删除：'+d.name); await settleIndex(d.rebuilding,'已删除'); }
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
var NOTE={items:[],cur:null,loaded:false};
var KIND_LABEL={decision:'决策',howto:'做法',reference:'资料',qa:'问答',log:'记录'};
var STATUS_LABEL={draft:'草稿',final:'定稿',archived:'归档'};

function noteFetch(path,opt){
  var o=opt||{}; o.headers=apiHeaders(o.headers||{});
  return fetch(path,o).then(function(r){
    return r.json().catch(function(){return {};}).then(function(d){
      if(!r.ok) throw new Error(d.message||d.error||('HTTP '+r.status));
      return d;
    });
  });
}

function loadNotes(){
  $('noteCount').textContent='加载中…';
  return noteFetch('/api/notes?limit=200').then(function(d){
    NOTE.items=d.items||[]; NOTE.loaded=true; renderNoteList();
  }).catch(function(e){
    $('noteCount').textContent='加载失败';
    $('noteList').innerHTML='<div class="note-empty">'+esc(e.message||e)+'</div>';
  });
}

function visibleNotes(){
  var q=($('noteSearch').value||'').trim().toLowerCase();
  var kind=$('noteKind').value, status=$('noteStatus').value;
  return NOTE.items.filter(function(n){
    if(kind && n.kind!==kind) return false;
    if(status && n.status!==status) return false;
    if(!q) return true;
    var hay=[n.title||'', (n.tags||[]).join(' '), n.summary||''].join(' ').toLowerCase();
    return hay.indexOf(q)>=0;
  });
}

function renderNoteList(){
  var rows=visibleNotes();
  $('noteCount').textContent=NOTE.items.length
    ? ('共 '+NOTE.items.length+' 篇'+(rows.length!==NOTE.items.length?('，匹配 '+rows.length+' 篇'):''))
    : '还没有笔记';
  if(!rows.length){
    $('noteList').innerHTML='<div class="note-empty">'
      +(NOTE.items.length?'没有匹配的笔记':'还没有笔记。<br>在问答页点「存为笔记」，或让智能体保存一段对话。')+'</div>';
    return;
  }
  $('noteList').innerHTML=rows.map(function(n){
    var tags=(n.tags||[]).slice(0,3).map(function(t){return '#'+t;}).join(' ');
    return '<button type="button" class="note-item'+(NOTE.cur&&NOTE.cur.id===n.id?' on':'')+'" data-id="'+esc(n.id)+'">'
      +'<b>'+esc(n.title||'未命名')+'</b>'
      +'<span>'+esc(String(n.created||'').slice(0,10))+' · '+esc(KIND_LABEL[n.kind]||n.kind||'')
      +(tags?' · <span class="ntag">'+esc(tags)+'</span>':'')+'</span>'
      +'</button>';
  }).join('');
}

function openNote(id){
  return noteFetch('/api/notes/'+encodeURIComponent(id)).then(function(d){
    NOTE.cur=d; renderEditor(d); renderNoteList();
  }).catch(function(e){ toast('读取失败：'+(e.message||e),true); });
}

function renderEditor(d){
  $('noteEmpty').hidden=true; $('noteEditor').hidden=false;
  $('neTitle').value=d.title||'';
  $('neTags').value=(d.tags||[]).join(', ');
  $('neKind').value=d.kind||'qa';
  $('neStatus').value=d.status||'draft';
  $('neCreated').value=String(d.created||'').slice(0,16).replace('T',' ');
  $('neMeta').textContent=(d.digest==='llm'?'模型摘要':'规则摘要')+(d.external?' · 外部文件':'');
  $('neSections').innerHTML=(d.sections||[]).map(function(s){
    return '<div class="ne-sec"><div class="ne-sec-head"><span>'+esc(s.title)+'</span>'
      +'<button type="button" class="ne-del" aria-label="删除这一节" title="删除这一节">×</button></div>'
      +'<textarea data-name="'+esc(s.title)+'" rows="'+(s.title==='摘要'?3:4)+'">'+esc(s.body)+'</textarea></div>';
  }).join('');
  $('neHint').textContent='rev '+d.rev+' · 改完点保存';
}

function collectChanges(){
  var sections={};
  Array.prototype.forEach.call($('neSections').querySelectorAll('.ne-sec'),function(box){
    var t=box.querySelector('textarea'); if(!t) return;
    sections[t.dataset.name]=t.value;
  });
  return {
    title:$('neTitle').value.trim(),
    tags:($('neTags').value||'').split(/[,，]/).map(function(x){return x.trim();}).filter(Boolean),
    kind:$('neKind').value, status:$('neStatus').value, sections:sections
  };
}

function saveNote(){
  if(!NOTE.cur) return;
  var btn=$('neSave'); btn.disabled=true;
  return noteFetch('/api/notes/'+encodeURIComponent(NOTE.cur.id),{method:'PATCH',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({base_rev:NOTE.cur.rev,changes:collectChanges()})
  }).then(function(d){
    NOTE.cur=d; renderEditor(d);
    var row=NOTE.items.filter(function(n){return n.id===d.id;})[0];
    if(row){ row.title=d.title; row.tags=d.tags; row.kind=d.kind; row.status=d.status; row.summary=''; }
    renderNoteList(); toast('已保存');
  }).catch(function(e){
    if(String(e.message||'').indexOf('冲突')>=0){ toast('这篇已被别处改过，正在加载最新版本',true); openNote(NOTE.cur.id); }
    else{ toast('保存失败：'+(e.message||e),true); }
  }).finally(function(){ btn.disabled=false; });
}

function deleteNote(){
  if(!NOTE.cur) return;
  if(!confirm('删除「'+NOTE.cur.title+'」？文件会移到 .trash，可以找回。')) return;
  noteFetch('/api/notes/'+encodeURIComponent(NOTE.cur.id)+'?confirm=1',{method:'DELETE'}).then(function(){
    NOTE.items=NOTE.items.filter(function(n){return n.id!==NOTE.cur.id;});
    NOTE.cur=null; $('noteEditor').hidden=true; $('noteEmpty').hidden=false;
    renderNoteList(); toast('已移入回收站');
  }).catch(function(e){ toast('删除失败：'+(e.message||e),true); });
}

function downloadBlob(name,text,mime){
  try{
    var blob=new Blob([text],{type:(mime||'text/plain')+';charset=utf-8'});
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=name;
    document.body.appendChild(a); a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); },1000);
  }catch(e){ toast('导出失败：'+(e.message||e),true); }
}

function exportNotes(fmt){
  noteFetch('/api/notes/export?format='+fmt).then(function(d){
    downloadBlob(d.filename,d.content,d.mime);
    toast('已导出 '+d.count+' 篇');
  }).catch(function(e){ toast('导出失败：'+(e.message||e),true); });
}

$('noteSearch').oninput=renderNoteList;
$('noteKind').onchange=renderNoteList;
$('noteStatus').onchange=renderNoteList;
$('noteList').onclick=function(ev){
  var item=ev.target.closest('.note-item');
  if(item) openNote(item.dataset.id);
};
$('neSave').onclick=saveNote;
$('neDelete').onclick=deleteNote;
$('noteExportHtml').onclick=function(){ exportNotes('html'); };
$('noteExportJson').onclick=function(){ exportNotes('json'); };
$('neRuleNote') && ($('neRuleNote').onclick=null);
$('neSections').onclick=function(ev){
  var del=ev.target.closest('.ne-del'); if(!del) return;
  del.closest('.ne-sec').remove();
};
$('neAddSec').onclick=function(){
  var name=(window.prompt('新小节名称，例如「风险」「后续」')||'').trim();
  if(!name) return;
  var div=document.createElement('div');
  div.className='ne-sec';
  div.innerHTML='<div class="ne-sec-head"><span>'+esc(name)+'</span>'
    +'<button type="button" class="ne-del" aria-label="删除这一节">×</button></div>'
    +'<textarea data-name="'+esc(name)+'" rows="3"></textarea>';
  $('neSections').appendChild(div);
  div.querySelector('textarea').focus();
};
$('neTitle').onkeydown=function(e){ if(e.key==='Enter'){ e.preventDefault(); saveNote(); } };

/* 文档 / 笔记 切换：笔记按需加载，切回文档不重新请求知识库 */
function setTab(tab){
  Array.prototype.forEach.call(document.querySelectorAll('.kb-tabs button'),function(b){
    var on=b.dataset.tab===tab;
    b.classList.toggle('on',on);
    b.setAttribute('aria-selected',on?'true':'false');
  });
  $('panelDocs').hidden = tab!=='docs';
  $('panelNotes').hidden = tab!=='notes';
  if(tab==='notes' && !NOTE.loaded){ loadNotes(); }
}
Array.prototype.forEach.call(document.querySelectorAll('.kb-tabs button'),function(b){
  b.onclick=function(){ setTab(b.dataset.tab); };
});
if(location.hash==='#notes'){ setTab('notes'); }

loadKb();
"""

KB_HTML = shell("kb", "知识库 · " + BRAND, KB_BODY, KB_SCRIPT, KB_CSS)
