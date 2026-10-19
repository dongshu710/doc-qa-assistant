"""原型页面（首页 / 问答 / 评测看板）。

覆盖一条完整使用路径：首页入口、提问输入、答案与引用、多轮追问、
答不出转人工、反馈回流、后台（知识库 + 评测看板）。

设计系统在 theme.py；本文件只放各页面的结构与交互。全部为内联 HTML/CSS/JS，
不依赖 CDN、字体文件或前端框架，断网也能完整打开。
"""
import json

from .theme import BASE_CSS, BRAND, JS_UTIL, MARK, TOPIC, shell  # noqa: F401

EXAMPLES = [
    "稳盈系列的起购金额是多少",
    "R3 及以上产品首次购买有什么要求",
    "大额存单可以转让吗",
]

_EXAMPLES_JS = "var EXAMPLES = " + json.dumps(EXAMPLES, ensure_ascii=False) + ";"


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
.hero .lead{color:#a7b6d6;font-size:15px;line-height:1.85;max-width:470px;margin:18px 0 26px;}
.hero-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
.btn.ghost-dark{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.2);color:#e6ecff;box-shadow:none;}
.btn.ghost-dark:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.34);color:#fff;}
.hero-examples{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin-top:26px;font-size:12.5px;color:#7d8dae;}
.hero-examples a{color:#a8b8dc;border-bottom:1px dashed rgba(168,184,220,.32);padding-bottom:1px;transition:color .15s,border-color .15s;}
.hero-examples a:hover{color:#fff;border-color:rgba(255,255,255,.6);}

/* 右侧产品示意，静态不放真实数据 */
.mock-wrap{position:relative;min-width:0;}
.mock{position:relative;max-width:100%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.16);border-radius:20px;padding:14px;
  box-shadow:0 50px 90px -40px rgba(0,0,0,.85), inset 0 1px 0 rgba(255,255,255,.12);}
.mock-card{background:#fff;border-radius:13px;padding:15px 16px;box-shadow:0 18px 40px -30px rgba(0,0,0,.6);}
.mock-top{display:flex;align-items:center;gap:7px;font-size:10.5px;color:#8792a8;padding-bottom:10px;margin-bottom:12px;border-bottom:1px solid #eef1f7;}
.mock-top .d{width:7px;height:7px;border-radius:50%;background:#e2e6ef;}
.mock-top .d:nth-child(1){background:#ffc9c4;} .mock-top .d:nth-child(2){background:#ffe1a8;} .mock-top .d:nth-child(3){background:#b7ebc9;}
.mock-top b{margin-left:auto;font-weight:600;color:#7b879c;font-size:10.5px;}
.mock-q{background:#f3f6fd;border-radius:9px;padding:9px 11px;font-size:12.5px;color:#334155;line-height:1.6;}
.mock-a{font-size:12.5px;line-height:1.8;color:#3b4657;margin-top:10px;}
.mock-a .cite{display:inline-flex;align-items:center;justify-content:center;min-width:15px;height:15px;border-radius:4px;background:var(--brand-soft);color:#2a49c8;font-size:9.5px;font-weight:700;padding:0 3px;vertical-align:1px;margin:0 1px;}
.mock-refs{display:flex;flex-wrap:wrap;gap:5px;margin-top:11px;}
.mock-refs span{font-size:10px;color:#34457a;background:var(--brand-tint);border:1px solid #e4eafd;border-radius:6px;padding:2px 7px;}
.mock-foot{display:flex;gap:6px;margin-top:11px;font-size:10px;color:#98a2b3;flex-wrap:wrap;}
.mock-foot span{padding:2px 7px;border:1px solid #eef1f7;border-radius:999px;}
.mock-float{position:absolute;left:-24px;bottom:-20px;display:flex;align-items:center;gap:8px;
  background:#0b1430;border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:9px 12px;
  font-size:11px;color:#cdd8f5;box-shadow:0 24px 50px -24px rgba(0,0,0,.9);}
.mock-float svg{color:#fbbf24;flex:none;}
.mock-badge{position:absolute;right:-14px;top:-14px;background:#0b1430;border:1px solid rgba(255,255,255,.18);border-radius:999px;
  padding:5px 11px;font-size:10.5px;color:#cdd8f5;display:flex;align-items:center;gap:6px;box-shadow:0 14px 30px -18px rgba(0,0,0,.9);}
.mock-badge i{width:6px;height:6px;border-radius:50%;background:#34d399;box-shadow:0 0 0 3px rgba(52,211,153,.18);}

/* 指标条，压在 hero 上 */
.stat-strip{position:relative;z-index:3;margin-top:-40px;background:#fff;border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--sh-2);display:grid;grid-template-columns:repeat(4,1fr);padding:20px 6px;}
.stat{padding:2px 20px;border-left:1px solid var(--line);min-width:0;}
.stat:first-child{border-left:none;}
.stat .v{font-size:25px;font-weight:700;color:var(--ink);letter-spacing:-.035em;line-height:1.2;font-variant-numeric:tabular-nums;}
.stat .v small{font-size:12px;font-weight:500;color:var(--faint);letter-spacing:0;margin-left:3px;}
.stat .k{font-size:11.5px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

@media (max-width:960px){
  .hero .wrap{grid-template-columns:1fr;gap:40px;padding-top:44px;padding-bottom:78px;}
  .mock-wrap{max-width:520px;}
}
@media (max-width:760px){
  .stat-strip{grid-template-columns:1fr 1fr;row-gap:16px;padding:18px 4px;}
  .stat{padding:2px 16px;}
  .stat:nth-child(3){border-left:none;}
  .mock-float{left:-6px;bottom:-16px;}
  .mock-badge{right:-4px;}
}
@media (max-width:560px){
  .hero h1{font-size:29px;}
  .mock{padding:10px;border-radius:16px;}
  .mock-card{padding:13px;}
  .mock-float{font-size:10.5px;padding:8px 10px;}
}
"""

HOME_BODY = """
<main>
  <section class="hero">
    <div class="wrap">
      <div class="hero-copy">
        <div class="eyebrow hero-eyebrow">RAG · 文档问答</div>
        <h1>把文档变成<br><span>有出处的答案</span></h1>
        <p class="lead">放进一份文档，就能用自然语言提问。答案逐条标注来源；资料里没有的，直接说不知道。</p>
        <div class="hero-actions">
          <a class="btn lg" href="/ask">开始提问 <span aria-hidden="true">→</span></a>
          <a class="btn ghost-dark lg" href="/dashboard">评测看板</a>
        </div>
        <div class="hero-examples"><span>试试：</span><span id="examples" style="display:contents"></span></div>
      </div>

      <div class="mock-wrap" aria-hidden="true">
        <div class="mock">
          <div class="mock-card">
            <div class="mock-top"><span class="d"></span><span class="d"></span><span class="d"></span><b>知识库 · 已索引</b></div>
            <div class="mock-q">首次购买 R3 及以上产品有什么要求？</div>
            <div class="mock-a">首次购买 R3 及以上风险等级产品，须在营业网点临柜办理并完成录音录像<span class="cite">1</span>；
              未完成风险测评或测评过期的客户，不得购买 R2 及以上产品<span class="cite">2</span>。</div>
            <div class="mock-refs"><span>1 销售适当性实施细则 · 四、双录管理</span><span>2 客户适当性管理制度 · 一、风险测评</span></div>
            <div class="mock-foot"><span>deepseek-chat</span><span>1.4s</span><span>2 条引用</span></div>
          </div>
        </div>
        <div class="mock-badge"><i></i>引用校验通过</div>
        <div class="mock-float">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 17h.01"/></svg>
          低置信度 → 转人工
        </div>
      </div>
    </div>
  </section>

  <div class="wrap">
    <section class="stat-strip" aria-label="项目实时指标">
      <div class="stat"><div class="v"><span id="s-chunks">—</span><small id="s-files"></small></div><div class="k">知识块</div></div>
      <div class="stat"><div class="v" id="s-cases">—</div><div class="k">评测用例</div></div>
      <div class="stat"><div class="v" id="s-cov">—</div><div class="k">引用覆盖率</div></div>
      <div class="stat"><div class="v" id="s-faith">—</div><div class="k">L3 忠实度</div></div>
    </section>
  </div>
</main>
"""

HOME_SCRIPT = _EXAMPLES_JS + """
var exBox=document.getElementById('examples');
EXAMPLES.forEach(function(t){
  var a=document.createElement('a'); a.href='/ask?q='+encodeURIComponent(t); a.textContent=t; exBox.appendChild(a);
});
function setT(id,v){var e=document.getElementById(id); if(e&&v!=null&&v!=='') e.textContent=v;}
function fmtScore(v){
  if(v==null) return null;
  var s=String(Math.round(Number(v)*100)/100);
  return s.indexOf('.')<0?s+'.0':s;
}
Promise.all([
  fetch('/api/health').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/knowledge').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/cases').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/metrics').then(function(r){return r.json();}).catch(function(){return null;}),
  fetch('/api/l3').then(function(r){return r.json();}).catch(function(){return null;})
]).then(function(res){
  var h=res[0],k=res[1],c=res[2],m=res[3],l3=res[4];
  if(h){ setT('s-chunks', h.chunks); }
  if(k){ setT('s-files',' / '+k.files.length+' 份'); }
  if(c){ setT('s-cases', c.total); }
  if(m&&m.avg_citation_coverage!=null){ setT('s-cov', m.avg_citation_coverage); }
  if(l3&&l3.available&&l3.avg&&l3.avg.faithfulness!=null){ setT('s-faith', fmtScore(l3.avg.faithfulness)); }
}).catch(function(){});
"""

HOME_HTML = shell("home", BRAND + " · 有出处的文档问答", HOME_BODY, HOME_SCRIPT, HOME_CSS)


# ======================================================================
# 问答页
# ======================================================================
ASK_CSS = """
.ask-wrap{max-width:1180px;}
.ask-grid{display:grid;grid-template-columns:276px minmax(0,1fr);gap:16px;align-items:start;}
.side{position:sticky;top:calc(var(--nav-h) + 16px);display:flex;flex-direction:column;gap:12px;}
.side .card{padding:16px;}
.side .side-title{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#8b95a8;margin-bottom:11px;display:flex;align-items:center;gap:6px;}
.side .side-title .ic{color:#a9b3c6;}
.kb-stat{display:flex;align-items:baseline;gap:6px;}
.kb-stat b{font-size:28px;letter-spacing:-.035em;color:var(--ink);font-variant-numeric:tabular-nums;line-height:1;}
.kb-stat span{font-size:12px;color:var(--muted);}
.kb-stat i{font-style:normal;color:var(--text);font-weight:600;}
.kb-lines{margin-top:12px;display:flex;flex-direction:column;gap:7px;font-size:12px;color:var(--muted);}
.kb-lines .row{justify-content:space-between;gap:8px;}
.kb-lines b{color:var(--text);font-weight:600;font-size:11.5px;text-align:right;word-break:break-all;}
.kb-lines .pill{font-size:10.5px;padding:2px 7px;}
.side-link{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border:1px solid var(--line);
  border-radius:11px;background:#fff;font-size:12.5px;color:var(--muted);box-shadow:var(--sh-1);transition:color .15s,border-color .15s;}
.side-link:hover{color:var(--brand-600);border-color:#dbe3f7;}
.ex-list{display:flex;flex-direction:column;gap:1px;margin:0 -6px;}
.ex-list button{display:flex;align-items:flex-start;gap:7px;width:100%;text-align:left;padding:8px;border:none;background:none;
  border-radius:8px;font-size:12.5px;color:#475467;cursor:pointer;line-height:1.55;transition:background .14s,color .14s;}
.ex-list button:hover{background:var(--brand-tint);color:var(--brand-600);}
.ex-list button .ic{margin-left:auto;flex:none;opacity:0;transition:opacity .14s;margin-top:2px;}
.ex-list button:hover .ic{opacity:1;}
.chat-shell{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--sh-1);
  display:flex;flex-direction:column;height:min(calc(100vh - var(--nav-h) - 92px),880px);min-height:560px;overflow:hidden;}
.chat-head{display:flex;align-items:center;gap:10px;padding:12px 18px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#fff,#fcfdff);flex-wrap:wrap;}
.chat-head .t{display:flex;flex-direction:column;line-height:1.3;}
.chat-head h1{font-size:14.5px;}
.chat-head .sub{font-size:11px;color:var(--faint);margin-top:2px;}
.live{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:#0a7a4d;background:var(--ok-soft);
  border:1px solid #c8f0dc;padding:3px 9px;border-radius:999px;white-space:nowrap;}
.live i{width:6px;height:6px;border-radius:50%;background:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.18);}
.chat-head .spacer{flex:1;}

.chat-list{flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:16px;}
.chat-list::-webkit-scrollbar{width:8px;}
.chat-list::-webkit-scrollbar-thumb{background:#e3e8f2;border-radius:8px;}
.chat-list::-webkit-scrollbar-track{background:transparent;}

.empty-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:28px 20px 34px;}
.empty-chat .art{width:92px;height:92px;border-radius:24px;background:linear-gradient(160deg,#eef3ff,#f9fbff);
  border:1px solid #e2e9fd;display:flex;align-items:center;justify-content:center;color:var(--brand);margin-bottom:16px;
  box-shadow:inset 0 1px 0 #fff,0 18px 34px -26px rgba(47,92,246,.6);}
.empty-chat h2{font-size:18px;letter-spacing:-.02em;}
.empty-chat p{color:var(--muted);font-size:12.5px;max-width:430px;margin-top:7px;line-height:1.8;}
.ex-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;width:100%;max-width:620px;margin-top:20px;}
.ex-card{text-align:left;padding:11px 12px;border:1px solid var(--line);border-radius:11px;background:#fff;cursor:pointer;
  font-size:12px;color:#475467;line-height:1.55;transition:border .15s,box-shadow .15s,transform .15s;font-family:inherit;}
.ex-card:hover{border-color:#c3d0f8;box-shadow:0 8px 20px -14px rgba(47,92,246,.7);transform:translateY(-1px);}
.ex-card b{display:block;font-size:9.5px;color:var(--faint);font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;}

.msg{display:flex;gap:10px;max-width:100%;animation:rise .24s ease both;}
.chat-list > .msg:first-child{margin-top:auto;}
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
.answer strong{font-weight:650;color:#0a1020;}
.answer .cite-n{display:inline-flex;align-items:center;justify-content:center;min-width:15px;height:15px;
  border-radius:4px;background:var(--brand-soft);color:#2a49c8;font-size:9.5px;font-weight:700;padding:0 3px;
  vertical-align:1px;margin:0 1px;}
.refs{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px;}
.ref{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;background:var(--brand-tint);border:1px solid #e4eafd;
  color:#34457a;padding:3px 9px 3px 4px;border-radius:8px;line-height:1.5;}
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

.handoff{background:var(--warn-soft);border:1px solid #f6e4c3;border-radius:4px 14px 14px 14px;padding:16px 17px;}
.handoff h4{font-size:13.5px;color:#7a4b00;margin-bottom:6px;display:flex;align-items:center;gap:7px;}
.handoff p{font-size:13px;color:#8a5a10;line-height:1.8;white-space:pre-wrap;}
.handoff form{display:flex;gap:7px;margin-top:13px;flex-wrap:wrap;}
.handoff input{flex:1;min-width:180px;padding:8px 11px;border:1px solid #eddbb9;border-radius:8px;font-size:12.5px;
  outline:none;background:#fff;font-family:inherit;}
.handoff input:focus{border-color:#d9a94a;box-shadow:0 0 0 3px rgba(217,169,74,.16);}
.handoff .hint{font-size:10.5px;color:#a97a33;margin-top:9px;line-height:1.6;}

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
.send:active{transform:translateY(1px);}
.send[disabled]{opacity:.5;cursor:not-allowed;}
.composer-hint{display:flex;justify-content:space-between;gap:10px;font-size:10.5px;color:var(--faint);margin-top:7px;padding:0 2px;}
.composer-hint kbd{font-family:var(--mono);font-size:9.5px;background:#f3f5fa;border:1px solid var(--line);border-radius:4px;padding:1px 4px;color:#667085;}

@media (max-width:960px){
  .ask-grid{grid-template-columns:1fr;}
  .side{position:static;order:2;display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .side .card:last-child{grid-column:1 / -1;}
  .chat-shell{height:calc(100vh - var(--nav-h) - 88px);max-height:none;min-height:520px;}
  .ex-cards{grid-template-columns:1fr;}
}
@media (max-width:640px){
  .ask-wrap{padding:14px 12px 40px;}
  .side{grid-template-columns:1fr;}
  .chat-shell{height:calc(100vh - 190px);max-height:none;min-height:480px;}
  .chat-list{padding:14px;gap:14px;}
  .bubble{max-width:86%;}
  .composer{padding:9px 12px 11px;}
  .composer textarea{font-size:16px;}
  .composer-hint{display:none;}
  .dash-link{display:none;}
  .chat-head{padding:11px 14px;gap:8px;}
  .chat-head h1{font-size:14px;}
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
  <div class="ask-grid">
    <aside class="side">
      <section class="card">
        <div class="side-title">知识库</div>
        <div class="kb-stat"><b id="sideChunks">—</b><span>个知识块 · <i id="sideFiles">—</i> 份文档</span></div>
        <div class="kb-lines">
          <div class="row"><span>端点</span><b id="sideChannel">—</b></div>
          <div class="row"><span>状态</span><span class="pill ok" id="sideState"><span class="dot"></span>连接中</span></div>
        </div>
      </section>
      <section class="card">
        <div class="side-title">示例问题</div>
        <div class="ex-list" id="sideExamples"></div>
      </section>
      <a class="side-link" href="/dashboard">评测看板 <span aria-hidden="true">→</span></a>
    </aside>

    <section class="chat-shell">
      <header class="chat-head">
        <div class="t">
          <h1>对话</h1>
          <div class="sub">只依据知识库作答，逐条标注出处</div>
        </div>
        <span class="live" id="health"><i></i><span>连接中…</span></span>
        <span class="spacer"></span>
        <button class="btn quiet sm" id="clear" type="button">清空对话</button>
        <a class="btn ghost sm dash-link" href="/dashboard">评测看板</a>
      </header>
      <div id="list" class="chat-list" aria-live="polite"></div>
      <div class="composer">
        <div class="composer-box">
          <textarea id="q" rows="1" placeholder="输入问题，例如：R3 及以上产品首次购买有什么要求？" autocomplete="off"></textarea>
          <button class="send" id="send" type="button" aria-label="发送">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13"/><path d="m12 5 7 7-7 7"/></svg>
          </button>
        </div>
        <div class="composer-hint">
          <span><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
        </div>
      </div>
    </section>
  </div>
</main>
"""

ASK_SCRIPT = _EXAMPLES_JS + JS_UTIL + """
var qEl=document.getElementById('q'), sendBtn=document.getElementById('send'), list=document.getElementById('list');
var busy=false;
var MODE={llm:'模型生成',extractive:'抽取式',extractive_fallback:'降级抽取'};
var BEHAVIOR={answer:['作答','ok'],ask_clarify:['追问澄清','brand'],no_answer:['转人工','warn'],refuse:['拒答','bad']};
var ART='""" + _ASK_ART.replace("'", "\\'") + """';

function setText(id,v){ var e=document.getElementById(id); if(e) e.textContent=(v==null||v==='')?'—':v; }
function scrollBottom(){ list.scrollTop=list.scrollHeight; }
function autoGrow(){ qEl.style.height='auto'; qEl.style.height=Math.min(qEl.scrollHeight,124)+'px'; }

function renderEmpty(){
  list.innerHTML='<div class="empty-chat">'
    +'<div class="art">'+ART+'</div>'
    +'<h2>从知识库开始提问</h2>'
    +'<p>助手只依据知识库作答，每条结论标注出处。资料里没有的，会转人工而不是猜。</p>'
    +'<div class="ex-cards" id="exCards"></div>'
    +'</div>';
  var box=document.getElementById('exCards');
  EXAMPLES.forEach(function(t,i){
    var b=document.createElement('button'); b.type='button'; b.className='ex-card';
    b.innerHTML='<b>示例 0'+(i+1)+'</b><span></span>';
    b.querySelector('span').textContent=t;
    b.onclick=function(){ qEl.value=t; autoGrow(); ask(); };
    box.appendChild(b);
  });
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
  var html='<div class="ans-foot">'
    +'<span class="pill brand">'+esc(d.channel||'-')+' / '+esc(d.model||'-')+'</span>'
    +pill('模式 '+(MODE[d.mode]||d.mode||'-'))
    +pill((d.latency_ms==null?'-':Math.round(d.latency_ms))+' ms');
  if(d.degraded){ html+=pill('降级','warn'); }
  if(d.citation_exempt_reason){ html+=pill('引用豁免'); }
  return html+'</div>';
}
function answerHTML(d){
  var h='<div class="ans-card"><div class="ans-label"><span>回答</span>'
    +(d.behavior&&BEHAVIOR[d.behavior]?'<span class="pill '+BEHAVIOR[d.behavior][1]+'">'+BEHAVIOR[d.behavior][0]+'</span>':'')
    +'</div>';
  h+='<div class="answer">'+fmtAnswer(d.answer)+'</div>';
  if(d.citations&&d.citations.length){
    h+='<div class="refs">'+d.citations.map(function(c){
      return '<span class="ref"><b>'+esc(c.ref)+'</b>'+esc(c.title)+' · '+esc(c.section)+'</span>';
    }).join('')+'</div>';
  }
  if(d.retrieved&&d.retrieved.length){
    h+='<details class="src"><summary>'
      +'<svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>'
      +'检索依据 '+d.retrieved.length+' 条</summary><div class="src-list">'
      +d.retrieved.map(function(x,i){
        var sc=(x.score==null)?'-':(Math.round(x.score*1000)/1000);
        return '<div class="src-row"><span class="rank">'+String(i+1).padStart(2,'0')+'</span>'
          +'<span>'+esc(x.title)+' · '+esc(x.section)+'</span><span class="sc">score '+sc+'</span></div>';
      }).join('')+'</div></details>';
  }
  h+=footHTML(d)+'</div>';
  return h;
}
function handoffHTML(d){
  return '<div class="handoff"><h4>'
    +'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 17h.01"/></svg>'
    +'这个问题资料里没有确切答案</h4>'
    +'<p>'+esc(d.answer)+'</p>'
    +'<form><input name="contact" placeholder="联系方式（选填，便于回电）" autocomplete="off">'
    +'<button class="btn sm" type="submit">提交工单</button></form>'
    +'<div class="hint">已按「答不出就转人工」处理：不编造答案，工单会带上本次 trace 供同事复核。</div></div>';
}
function bindHandoff(body,d,query){
  var form=body.querySelector('.handoff form');
  if(!form) return;
  form.onsubmit=async function(ev){
    ev.preventDefault();
    var btn=form.querySelector('button'); btn.disabled=true; btn.textContent='提交中…';
    try{
      var r=await (await fetch('/api/handoff',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({trace_id:d.trace_id,query:query,contact:form.contact.value})})).json();
      if(r.ok){
        form.innerHTML='<span class="pill ok"><span class="dot"></span>已提交 · 工单号 '+esc(r.ticket)+'</span>';
        toast('工单已创建：'+r.ticket);
      }else{
        btn.disabled=false; btn.textContent='提交工单'; toast('提交失败：'+(r.error||''),true);
      }
    }catch(e){ btn.disabled=false; btn.textContent='提交工单'; toast('提交失败：'+e,true); }
  };
}
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

async function ask(){
  var query=qEl.value.trim();
  if(!query){ qEl.focus(); return; }
  if(busy) return;
  busy=true; sendBtn.disabled=true;
  var empty=list.querySelector('.empty-chat'); if(empty) list.innerHTML='';

  addUser(query);
  var body=addBot();
  body.innerHTML=thinkingHTML('正在检索知识库…');
  scrollBottom();
  qEl.value=''; autoGrow();

  var timer=setTimeout(function(){
    var t=body.querySelector('.think-text'); if(t) t.textContent='正在组织答案并校验引用…';
  },900);

  try{
    var resp=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:query})});
    var data=await resp.json();
    clearTimeout(timer);
    if(!resp.ok) throw new Error(data.error||('HTTP '+resp.status));
    if(data.behavior==='answer'){
      body.innerHTML=answerHTML(data);
      bindFeedback(body,data);
    }else{
      body.innerHTML=handoffHTML(data);
      bindHandoff(body,data,query);
    }
  }catch(err){
    clearTimeout(timer);
    body.innerHTML='<div class="ans-card" style="border-color:#f6d3d0"><div class="ans-label"><span>请求失败</span></div>'
      +'<div class="answer">'+esc(err.message||String(err))+'</div></div>';
  }finally{
    busy=false; sendBtn.disabled=false; qEl.focus(); scrollBottom();
  }
}

function bindExamples(){
  var box=document.getElementById('sideExamples');
  EXAMPLES.forEach(function(t){
    var b=document.createElement('button'); b.type='button';
    b.innerHTML='<span></span><svg class="ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>';
    b.querySelector('span').textContent=t;
    b.onclick=function(){ qEl.value=t; autoGrow(); qEl.focus(); };
    box.appendChild(b);
  });
}

sendBtn.onclick=ask;
qEl.addEventListener('input',autoGrow);
qEl.addEventListener('keydown',function(e){
  if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); ask(); }
});
document.getElementById('clear').onclick=function(){
  if(!list.querySelector('.msg')){ return; }
  list.innerHTML=''; renderEmpty(); toast('已清空本轮对话');
};
document.getElementById('health').addEventListener('click',function(){ location.href='/dashboard'; });
document.getElementById('health').style.cursor='pointer';

fetch('/api/health').then(function(r){return r.json();}).then(function(h){
  var box=document.getElementById('health');
  box.querySelector('span').textContent=(h.llm_ready?'在线 · ':'离线抽取 · ')+h.model;
  setText('sideChunks',h.chunks);
  setText('sideChannel',h.channel+' / '+h.model);
  var state=document.getElementById('sideState');
  if(h.llm_ready){ state.className='pill ok'; state.innerHTML='<span class="dot"></span>正常'; }
  else { state.className='pill'; state.innerHTML='<span class="dot" style="background:#c58b00"></span>离线抽取'; }
}).catch(function(){
  var box=document.getElementById('health');
  box.querySelector('span').textContent='服务未就绪';
  box.style.color='#a91e13'; box.style.background='var(--bad-soft)'; box.style.borderColor='#f6d3d0';
  var state=document.getElementById('sideState');
  state.className='pill bad'; state.innerHTML='<span class="dot"></span>未连接';
});
fetch('/api/knowledge').then(function(r){return r.json();}).then(function(k){
  setText('sideFiles',k.files.length);
}).catch(function(){});

bindExamples();
renderEmpty();
var pre=new URLSearchParams(location.search).get('q');
if(pre){ qEl.value=pre; autoGrow(); ask(); }
"""

ASK_HTML = shell("ask", "问答 · " + BRAND, ASK_BODY, ASK_SCRIPT, ASK_CSS)


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

.drop{border:1.5px dashed #cfd8ea;border-radius:13px;background:linear-gradient(180deg,#fbfcff,#fff);
  padding:22px 18px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;
  text-align:center;cursor:pointer;transition:border .16s,background .16s,box-shadow .16s;}
.drop:hover,.drop.over{border-color:#9db2f2;background:var(--brand-tint);box-shadow:0 0 0 4px rgba(47,92,246,.06);}
.drop .dic{width:36px;height:36px;border-radius:10px;background:var(--brand-soft);color:var(--brand);
  display:flex;align-items:center;justify-content:center;margin-bottom:3px;}
.drop b{font-size:13px;color:var(--ink);font-weight:600;}
.drop span{font-size:11px;color:var(--faint);line-height:1.6;}
.kb-status{font-size:11.5px;color:var(--faint);margin-top:9px;min-height:17px;line-height:1.65;word-break:break-word;}
.kb-status.ok{color:var(--ok);font-weight:500;}
.kb-status.err{color:var(--bad);font-weight:500;}
.fname{display:flex;align-items:center;gap:9px;min-width:0;}
.ftype{font-family:var(--mono);font-size:9.5px;font-weight:600;padding:2px 5px;border-radius:4px;flex:none;
  background:#eef1f7;color:#667085;letter-spacing:.02em;}
.ftype.pdf{background:#fef1f0;color:#b42318;} .ftype.docx{background:#eef2ff;color:#2a49c8;}
.ftype.md{background:#e9f9f1;color:#0a7a4d;} .ftype.txt{background:#f4f6fa;color:#54617a;}
.fname .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;}
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
    <a href="#p-kb">知识库</a>
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
  </section>

  <section class="panel card" id="p-quality">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/><path d="m9 12 2 2 4-4"/></svg>
      <h3>语义质量 L3</h3><span class="hint">裁判模型评分，非确定性</span>
      <span class="spacer"></span><span class="pill brand" id="l3Judge">—</span>
    </div>
    <div id="l3"></div>
  </section>

  <section class="panel card" id="p-kb">
    <div class="card-head">
      <svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z"/><path d="M8 3v18"/></svg>
      <h3>知识库</h3>
      <span class="spacer"></span><span class="pill" id="kbMeta">—</span>
    </div>
    <div class="drop" id="drop">
      <div class="dic">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
      </div>
      <b>拖拽文件到这里，或点击选择</b>
      <span>.md / .txt / .pdf / .docx · 文本 ≤ 512 KB，PDF/DOCX ≤ 6 MB<br>PDF 与 Word 由服务端解析成 Markdown 后入库</span>
      <input type="file" id="kbFile" accept=".md,.txt,.pdf,.docx" hidden>
    </div>
    <div class="kb-status" id="kbMsg"></div>
    <div class="table-wrap" style="margin-top:12px">
      <table>
        <thead><tr><th>文件</th><th class="num">知识块</th><th style="text-align:right">操作</th></tr></thead>
        <tbody id="kbBody"></tbody>
      </table>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="btn ghost sm" id="reload" type="button">重新加载索引</button>
      <span class="kb-status" id="reloadMsg" style="margin-top:0"></span>
    </div>
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
        <option value="no_answer">no_answer · 资料不足转人工</option>
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
var BEHAVIOR={answer:'作答',ask_clarify:'追问澄清',no_answer:'转人工',refuse:'拒答'};
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
    kpi('alert','转人工',bb.no_answer||0,'置信度不足')+
    kpi('target','引用覆盖率',m.avg_citation_coverage==null?'—':m.avg_citation_coverage,'近 500 条均值');
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

/* ---------- 知识库 ---------- */
function typeOf(name){
  var ext=(name.split('.').pop()||'').toLowerCase();
  return {ext:ext.toUpperCase(),cls:ext};
}
function setKb(text,cls){
  var el=$('kbMsg'); el.textContent=text; el.className='kb-status'+(cls?' '+cls:'');
}
function renderKb(kb){
  var files=kb.files||[];
  $('kbMeta').textContent=files.length+' 份 / '+(kb.total_chunks||0)+' 块';
  if(!files.length){
    $('kbBody').innerHTML=emptyRow(3,'还没有文档，先上传一份 .md 或 .pdf');
    return;
  }
  $('kbBody').innerHTML=files.map(function(f){
    var t=typeOf(f.name);
    return '<tr><td><div class="fname"><span class="ftype '+esc(t.cls)+'">'+esc(t.ext)+'</span>'
      +'<span class="nm" title="'+esc(f.name)+'">'+esc(f.name)+'</span></div></td>'
      +'<td class="num"><span class="pill">'+f.chunks+'</span></td>'
      +'<td><div class="row-actions">'
      +'<button class="btn ghost sm gen" data-name="'+esc(f.name)+'">出题</button>'
      +'<button class="btn danger-ghost sm del" data-name="'+esc(f.name)+'">删除</button>'
      +'</div></td></tr>';
  }).join('');
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
    $('caseBody').innerHTML=emptyRow(5,'还没有文档用例：在知识库里点「出题」，或从差评一键生成');
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

/* ---------- 加载 ---------- */
async function loadAll(){
  try{
    var res=await Promise.all([
      fetch('/api/metrics').then(function(r){return r.json();}),
      fetch('/api/cases').then(function(r){return r.json();}),
      fetch('/api/l3').then(function(r){return r.json();}).catch(function(){return {};}),
      fetch('/api/knowledge').then(function(r){return r.json();}),
      fetch('/api/feedback/list?limit=20').then(function(r){return r.json();}),
      fetch('/api/trace?limit=20').then(function(r){return r.json();})
    ]);
    renderKpis(res[0],res[1],res[2]);
    renderBehavior(res[0]);
    renderMode(res[0]);
    renderL3(res[2]);
    renderKb(res[3]);
    renderCases(res[1]);
    renderFeedback(res[4]);
    renderTrace(res[5]);
    var d=new Date();
    $('stamp').textContent='更新于 '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  }catch(e){ toast('看板加载失败：'+(e.message||e),true); }
}

/* ---------- 上传 ---------- */
function b64(buf){
  var bytes=new Uint8Array(buf), chunk=0x8000, out='';
  for(var i=0;i<bytes.length;i+=chunk){ out+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk)); }
  return btoa(out);
}
async function upload(f){
  var name=f.name||'upload';
  var ext=(name.split('.').pop()||'').toLowerCase();
  if(['md','txt','pdf','docx'].indexOf(ext)<0){ setKb('不支持 .'+ext+'：只接受 .md / .txt / .pdf / .docx','err'); return; }
  var isDoc=(ext==='pdf'||ext==='docx');
  if(isDoc&&f.size>6*1024*1024){ setKb('文件 '+Math.round(f.size/1024/1024*10)/10+' MB，超过 6 MB 上限','err'); return; }
  if(!isDoc&&f.size>512*1024){ setKb('文本文件 '+Math.round(f.size/1024)+' KB，超过 512 KB 上限','err'); return; }
  setKb('上传中…'+(isDoc?'（服务端解析文档，大文件可能要十几秒）':''));
  $('drop').classList.remove('over');
  try{
    var payload;
    if(isDoc){
      var buf=await f.arrayBuffer();
      payload=await (await fetch('/api/knowledge/upload_file',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:name,data_b64:b64(buf)})})).json();
    }else{
      var text=await f.text();
      payload=await (await fetch('/api/knowledge/upload',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:name,content:text})})).json();
    }
    if(payload.ok){
      var extra=payload.pages?(payload.pages+' 页'):(payload.paragraphs?(payload.paragraphs+' 段'):'');
      setKb('已入库 '+payload.name+'：'+(extra?extra+' / ':'')+payload.chars+' 字 → 新增 '+payload.added_chunks
        +' 块（共 '+payload.files+' 份 / '+payload.chunks+' 块，引擎 '+payload.engine+'）'+(payload.note?('｜'+payload.note):''),'ok');
      toast('已入库：'+payload.name+'（+'+payload.added_chunks+' 块）');
      await loadAll();
    }else{
      setKb('上传失败：'+(payload.error||'未知错误'),'err');
      toast('上传失败：'+(payload.error||''),true);
    }
  }catch(e){ setKb('上传失败：'+(e.message||e),'err'); toast('上传失败',true); }
}

/* ---------- 事件 ---------- */
$('refresh').onclick=loadAll;
$('runDocs').onclick=function(){ runCases('docs'); };
$('runAll').onclick=function(){ runCases('all'); };

$('kbFile').onchange=function(){
  var f=this.files&&this.files[0]; this.value='';
  if(f) upload(f);
};
$('drop').onclick=function(e){ if(e.target.id!=='kbFile') $('kbFile').click(); };
['dragenter','dragover'].forEach(function(ev){
  $('drop').addEventListener(ev,function(e){ e.preventDefault(); $('drop').classList.add('over'); });
});
['dragleave','drop'].forEach(function(ev){
  $('drop').addEventListener(ev,function(e){ e.preventDefault(); $('drop').classList.remove('over'); });
});
$('drop').addEventListener('drop',function(e){
  var f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];
  if(f) upload(f);
});

$('kbBody').onclick=async function(ev){
  var g=ev.target.closest('.gen');
  if(g){
    setKb('正在为「'+g.dataset.name+'」出题…（读文档 → 提炼可断言事实 → 写用例）');
    try{
      var n=parseInt(window.prompt('为「'+g.dataset.name+'」生成几条评测用例？（1-8）','3'),10)||3;
      var r=await (await fetch('/api/cases/from_doc',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:g.dataset.name,n:n})})).json();
      if(r.ok){
        setKb('已生成 '+r.added+' 条文档用例（'+r.mode+'），在下方「评测用例」里运行','ok');
        toast('已生成 '+r.added+' 条用例');
        await loadAll();
      }else{ setKb('出题失败：'+(r.error||''),'err'); }
    }catch(e){ setKb('出题失败：'+(e.message||e),'err'); }
    return;
  }
  var b=ev.target.closest('.del');
  if(!b) return;
  if(!confirm('确认从知识库删除「'+b.dataset.name+'」？删除后会立即重建索引，对应文档用例会在下次运行时跳过。')) return;
  try{
    var d=await (await fetch('/api/knowledge/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:b.dataset.name})})).json();
    if(d.ok){
      setKb('已删除 '+d.name+'（对应文档用例会在下次运行时自动跳过）','ok');
      toast('已删除：'+d.name);
      await loadAll();
    }else{ setKb('删除失败：'+(d.error||''),'err'); }
  }catch(e){ setKb('删除失败：'+(e.message||e),'err'); }
};

$('reload').onclick=async function(){
  var el=$('reloadMsg'); el.className='kb-status'; el.textContent='重新加载中…';
  try{
    var r=await (await fetch('/api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    el.textContent=r.ok?('已加载 '+r.chunks+' 个知识块'):('失败：'+r.error);
    el.className='kb-status '+(r.ok?'ok':'err');
    if(r.ok){ toast('索引已重建：'+r.chunks+' 块'); await loadAll(); }
  }catch(e){ el.textContent='失败：'+e; el.className='kb-status err'; }
};

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
