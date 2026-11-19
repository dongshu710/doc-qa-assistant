
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function ragApiKey(){ try{ return sessionStorage.getItem('rag_api_key')||''; }catch(e){ return ''; } }
function apiHeaders(base){
  var h=base||{}, k=ragApiKey();
  if(k) h['X-API-Key']=k;
  return h;
}
/* 状态播报：屏幕阅读器用户看不到右下角的 toast，只能靠 live region。
   容器必须**页面加载时就在 DOM 里**——读屏是先索引再监听，后插入的区域
   可能永远不播报。所以它写在 theme.py 的骨架里，这里只负责填字。
   同一句话连播两次时读屏不会重念，先清空再写，强制它当成新消息。 */
function live(msg){
  var box=document.getElementById('live'); if(!box) return;
  box.textContent='';
  setTimeout(function(){ box.textContent=msg||''; },30);
}

function toast(msg,isErr){
  var box=document.getElementById('toasts'); if(!box) return;
  var d=document.createElement('div'); d.className='toast'+(isErr?' err':'');
  // role 决定读屏怎么念：出错要打断当前朗读（alert），普通提示排队念（status）
  d.setAttribute('role', isErr?'alert':'status');
  d.innerHTML='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+((isErr)?'M18 6 6 18M6 6l12 12':'m20 6-11 11-5-5')+'"/></svg><span></span>';
  d.querySelector('span').textContent=msg||'';
  box.appendChild(d);
  live(msg);
  setTimeout(function(){ d.style.transition='opacity .25s, transform .25s'; d.style.opacity='0'; d.style.transform='translateY(6px)'; setTimeout(function(){d.remove();},260); }, 2600);
}

/* 带动作的**持久**通知（清空对话的撤销就是它）。
   为什么不复用 toast：WCAG 2.2.1 的要求是「带交互控件的提示不能自己消失」——
   2.6 秒后连按钮一起没了，等于给了个假的后悔药。这条常驻到用户点关闭、
   点动作或按 Esc；同一时刻只有一条，新的顶掉旧的（避免两条撤销叠在一起）。
   注意它不进 live region 的自动播报：文案里带「可按撤销」这类操作提示，
   读屏用户需要的是能 Tab 到那个按钮，而不是听一遍再去找。 */
var __notice=null;
function notice(opt){
  opt=opt||{};
  var box=document.getElementById('toasts'); if(!box) return null;
  dismissNotice();
  var d=document.createElement('div');
  d.className='notice'; d.setAttribute('role','group');
  d.setAttribute('aria-label', opt.text||'操作提示');
  var span=document.createElement('span'); span.className='nt-text';
  span.textContent=opt.text||'';
  d.appendChild(span);
  if(opt.action){
    var act=document.createElement('button');
    act.type='button'; act.className='nt-act'; act.textContent=opt.action;
    act.onclick=function(){ dismissNotice(); if(opt.onAction) opt.onAction(); };
    d.appendChild(act);
  }
  var close=document.createElement('button');
  close.type='button'; close.className='nt-x';
  close.setAttribute('aria-label','关闭提示'); close.textContent='×';
  close.onclick=function(){ dismissNotice(); if(opt.onClose) opt.onClose(); };
  d.appendChild(close);
  box.appendChild(d);
  __notice=d;
  live(opt.text||'');
  // 让键盘用户能立刻够到动作按钮：这是「刚做了一个可撤销的操作」唯一的路
  if(opt.focus && opt.action){
    setTimeout(function(){ try{ act.focus(); }catch(e){} },0);
  }
  return d;
}
function dismissNotice(){
  if(__notice){ var el=__notice; __notice=null; el.remove(); }
}

/* 写请求统一带上站内标记。
   为什么需要：服务端分不清「本页面发的」和「别的网站发的」——浏览器里两者对端都是 127.0.0.1。
   自定义头跨站无法伪造：它会触发 CORS 预检，而本项目默认不开放跨域，预检必然失败。
   包在 fetch 上而不是逐个调用点加，是为了避免以后新增接口时忘掉。 */
(function(){
  var raw=window.fetch;
  if(!raw) return;
  window.fetch=function(input,init){
    init=init||{};
    var method=String((init.method||(input&&input.method)||'GET')).toUpperCase();
    if(method!=='GET'&&method!=='HEAD'){
      try{
        var h=new Headers(init.headers||{});
        if(!h.has('X-Jiyi-Client')) h.set('X-Jiyi-Client','web');
        init.headers=h;
      }catch(e){
        var base=init.headers||{}, copy={};
        for(var k in base){ if(Object.prototype.hasOwnProperty.call(base,k)) copy[k]=base[k]; }
        copy['X-Jiyi-Client']='web';
        init.headers=copy;
      }
    }
    return raw.call(this,input,init);
  };
})();

/* ---------- 跨页面通用的小工具：各页面不再各写一份 ---------- */

/* 时间：列表里只需要到分钟，秒与毫秒只会占宽 */
function fmtTime(iso){ return String(iso==null?'':iso).slice(0,16).replace('T',' '); }

/* 字节：小于 10 保留一位小数（5.0 KB 比 5 KB 有信息量），KB 以上自动进位 */
function fmtBytes(n){
  if(n==null||n==='') return '—';
  n=Number(n)||0;
  if(n<1024) return n+' B';
  var units=['KB','MB','GB','TB'], i=-1, v=n;
  do{ v/=1024; i++; }while(v>=1024&&i<units.length-1);
  return (v>=10?v.toFixed(0):v.toFixed(1))+' '+units[i];
}

/* 请求头：JSON 请求只从这里出，API Key 与站内标记只在一个地方加 */
function reqHeaders(extra){
  var h={'Accept':'application/json'};
  if(extra) h['Content-Type']='application/json';
  return apiHeaders(h);
}

/* 下载：先 fetch 再转 Blob——直接给 a[href] 带不上鉴权头，开了 Key 的实例会 401 */
function saveBlob(content, filename, mime){
  try{
    var blob=new Blob([content],{type:mime||'application/octet-stream'});
    var url=URL.createObjectURL(blob), a=document.createElement('a');
    a.href=url; a.download=filename||'download';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function(){ URL.revokeObjectURL(url); },1000);
  }catch(e){ toast('导出失败：'+((e&&e.message)||e), true); }
}

/* 双击与手抖连点的止损：第一次点击打开浮层，第二次点击正好落在刚出现的
   遮罩上，于是浮层被自己关掉——用户看到的是「点了没反应」。
   统一给遮罩一个 300ms 冷静期：这段时间内的遮罩点击不算「关闭意图」。
   关闭按钮与 Esc 不受影响，想关随时能关。 */
function markOpen(el){ if(el) el.setAttribute('data-opened', String(Date.now())); }
function tooSoon(el, ms){
  var t=Number((el&&el.getAttribute('data-opened'))||0);
  return Date.now()-t < (ms||300);
}

/* 长任务：服务端超过 20 秒的操作会回 202 + {id,state:'running'}，结果要轮询取。
   为什么不在服务端死等：浏览器与中间代理 60 秒左右会掐断连接，用户看到「请求失败」，
   而任务其实跑完了——白跑一次，结果也没人拿到。轮询把等待变成可见进度。
   传进来的不是任务（没有 id，或已经结束）就原样返回，调用方不用先判断。 */
async function waitTask(data, onTick){
  if(!data || !data.id || data.state!=='running') return data;
  var id=data.id, started=Date.now();
  while(true){
    await new Promise(function(r){ setTimeout(r, 700); });
    var s=null;
    try{
      var resp=await fetch('/api/tasks/'+encodeURIComponent(id),{cache:'no-store',headers:reqHeaders(false)});
      s=await resp.json();
    }catch(e){ s=null; }
    if(onTick) onTick(s||{}, Math.round((Date.now()-started)/1000));
    if(!s) continue;                       // 一次网络抖动不该让等待直接失败
    if(s.state==='done') return s.result||{};
    if(s.state==='error') throw new Error(s.error||'后台任务失败');
    // 上限兜底：任务表只保留 1 小时，再等下去只会拿到 404
    if(Date.now()-started>30*60*1000) throw new Error('任务超过 30 分钟仍未完成');
  }
}

/* ---------- 模态浮层：层级 + 焦点 ----------
   层级表解决「Esc 关哪一层」：以前每个浮层各监听各关，设置 + 版本弹层同时
   开着时一次 Esc 两层一起消失。压栈顺序按打开时间，与用户心智一致。

   焦点陷阱解决「Tab 跑到背后去」：模态浮层后面的页面虽然看不见，但只要还能
   聚焦，键盘和读屏用户就会走进一片没有视觉反馈的区域，表现出来就是"焦点没了"。
   两个能力合在一个 openOverlay 里，是因为它们共用同一份「谁开着」的状态。 */
var __ovStack=[], __ovRelease={};

/* 焦点陷阱。三个监听各管一件事，缺一个都会漏场景：
   - keydown 捕获：Tab 首尾循环（正常路径）
   - focusin 捕获：兜底。脚本 focus()、读屏跳转、iframe 失焦都不产生 Tab 事件，
     只靠 keydown 拦不住，焦点会停在背后那层上
   - 可见性自检：容器一旦隐藏就不再拦。某处忘了调 closeOverlay 时，
     Tab 不会因此被永久吃掉——那种 bug 的表现是"整个页面按 Tab 没反应"，
     光看代码很难查到浮层头上 */
function trapFocus(el){
  if(!el) return function(){};
  var prev=document.activeElement, first=null, last=null;
  var SEL='a[href],button:not([disabled]),input:not([disabled]),'
    +'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  function visible(){ return !!el.getClientRects().length; }
  function refresh(){
    var all=el.querySelectorAll(SEL), out=[];
    for(var i=0;i<all.length;i++){
      /* getClientRects 而不是 offsetParent：浮层多为 position:fixed，
         那条路径下 offsetParent 恒为 null，会把整层判成「没有可聚焦元素」，
         于是一按 Tab 就被 preventDefault 吃掉。 */
      if(all[i].getClientRects().length) out.push(all[i]);
    }
    first=out[0]||null; last=out[out.length-1]||null;
    return out;
  }
  function onKey(e){
    if(e.key!=='Tab'||!visible()) return;
    refresh();
    if(!first){ e.preventDefault(); return; }
    if(e.shiftKey&&document.activeElement===first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey&&document.activeElement===last){ e.preventDefault(); first.focus(); }
  }
  function onFocus(e){
    if(!visible()||el.contains(e.target)) return;
    // 停在这里是刻意的：焦点已经跑到模态层外面，后续处理都没有意义
    e.stopImmediatePropagation();
    refresh();
    try{ (first||el).focus(); }catch(err){}
  }
  function focusInitial(){
    if(!visible()) return;
    refresh();
    /* 三条优先级，从「想让它落在哪」排到「只能随便找个」：
       1. 容器内标了 autofocus 的（设置面板要落在第一个输入框，而不是右上角关闭键）；
       2. 容器自己声明了 tabindex="-1"（分段抽屉这类，读屏念 aria-label 更合适）；
       3. 第一个可聚焦元素。 */
    var t=el.querySelector('[autofocus]')
      || (el.getAttribute('tabindex')==='-1'?el:(first||el));
    try{ t.focus(); }catch(err){}
  }
  document.addEventListener('keydown',onKey,true);
  document.addEventListener('focusin',onFocus,true);
  /* 0ms 才移焦：有的浮层先 openOverlay 再取消 hidden（顺序不一致），
     同步执行时元素还在 display:none 里，focus() 会静默失败。 */
  setTimeout(focusInitial,0);
  return function(){
    document.removeEventListener('keydown',onKey,true);
    document.removeEventListener('focusin',onFocus,true);
    /* 还焦也延后：同步还焦会撞上「触发关闭的那次点击/按键」的后续处理，
       焦点被抢回去。触发元素可能已经被删掉（比如删掉的正是那一行），
       那就别再把它塞回去。 */
    setTimeout(function(){
      try{ if(prev&&document.contains(prev)) prev.focus(); }catch(err){}
    },0);
  };
}

/* el 可选：传了就开焦点陷阱。不传只有层级（侧栏这类非模态的就这样用）。 */
function openOverlay(id, el){
  __ovStack=__ovStack.filter(function(x){ return x!==id; });
  __ovStack.push(id);
  if(__ovRelease[id]){ __ovRelease[id](); delete __ovRelease[id]; }
  if(el) __ovRelease[id]=trapFocus(el);
}
function closeOverlay(id){
  __ovStack=__ovStack.filter(function(x){ return x!==id; });
  if(__ovRelease[id]){ __ovRelease[id](); delete __ovRelease[id]; }
}
function isTopOverlay(id){
  return __ovStack.length>0 && __ovStack[__ovStack.length-1]===id;
}
