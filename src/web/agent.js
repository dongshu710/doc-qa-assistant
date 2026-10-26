/* 连接智能体：应用里的实体入口。
   为什么要有这一块：应用给人用、智能体走 MCP，两条路读的是同一批 Markdown，
   但用户看不到这件事——不知道「智能体也能读」，也不知道该粘什么配置。
   所以做成侧栏里的一个常驻按钮，点开就能看到状态、拿到配置、复制走。 */
(function(){
  var panel=document.getElementById('agentPanel');
  var btn=document.getElementById('agentBtn');
  if(!panel||!btn) return;
  var mask=document.getElementById('agentMask');
  var loaded=null;

  function $(id){ return document.getElementById(id); }

  function state(on, title, text){
    var box=$('agentState'); if(!box) return;
    box.classList.toggle('on',!!on);
    if($('agentStateTitle')) $('agentStateTitle').textContent=title||'';
    if($('agentStateText')) $('agentStateText').textContent=text||'';
    var led=$('agentLed'); if(led) led.hidden=!on;
  }

  function note(text, isErr){
    var el=$('agentNote'); if(!el) return;
    el.textContent=text||'';
    el.classList.toggle('err',!!isErr);
  }

  function render(d, tools){
    loaded=d;
    var notes=(d&&d.notes)||{}, mcp=(d&&d.mcp)||{};
    if($('agentHome')) $('agentHome').textContent=notes.home_effective||notes.home_default||'笔记目录';
    if($('agentPre')) $('agentPre').textContent=JSON.stringify(mcp,null,2);
    var count=(tools&&tools.tools&&tools.tools.length)||0;
    var total=Number(notes.count||0);
    state(count>0, count?('已接出 '+count+' 个工具'):'已生成配置',
      count?(total?('智能体可读写笔记；这个目录已有 '+total+' 篇。')
                  :'智能体可读写笔记；目录里还没有笔记。')
           :'把下面的配置贴进 MCP 客户端即可接出笔记工具。');
    if(!notes.available){
      state(false,'笔记服务未就绪', notes.error||'检查笔记目录是否可写');
    }
  }

  function load(){
    Promise.all([
      fetch('/api/settings').then(function(r){ return r.json(); }),
      fetch('/tools.json').then(function(r){ return r.json(); }).catch(function(){ return null; })
    ]).then(function(res){
      var d=res[0]||{}, tools=res[1];
      if(!d.ok){ state(false,'读取配置失败', d.message||''); return; }
      render(d, tools);
    }).catch(function(e){
      state(false,'读取配置失败', (e&&e.message)||String(e));
      note('后端没有响应，确认服务还在跑。', true);
    });
  }

  function open(){
    if(window.__closeSide) window.__closeSide();
    panel.hidden=false;
    if(mask) mask.hidden=false;
    btn.setAttribute('aria-expanded','true');
    if(!loaded) load();
    var close=$('agentClose'); if(close) close.focus();
  }

  function close(){
    panel.hidden=true;
    if(mask) mask.hidden=true;
    btn.setAttribute('aria-expanded','false');
    btn.focus();
  }

  btn.addEventListener('click', function(){
    if(panel.hidden) open(); else close();
  });
  if($('agentClose')) $('agentClose').addEventListener('click', close);
  if(mask) mask.addEventListener('click', close);
  document.addEventListener('keydown', function(e){
    if(e.key==='Escape'&&!panel.hidden){ e.preventDefault(); close(); }
  });

  if($('agentCopy')) $('agentCopy').addEventListener('click', function(){
    var text=($('agentPre')||{}).textContent||'';
    var done=function(ok){ note(ok?'配置已复制，粘到 MCP 客户端的 mcpServers 里。':'复制失败，手动选中上面的文本。',!ok); };
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ done(true); },function(){ done(false); });
      return;
    }
    try{
      var area=document.createElement('textarea');
      area.value=text; document.body.appendChild(area); area.select();
      done(document.execCommand('copy')); area.remove();
    }catch(e){ done(false); }
  });

  if($('agentInstall')) $('agentInstall').addEventListener('click', function(){
    close();
    if(window.__openSettings) window.__openSettings('install');
  });

  // 供其他脚本/测试调用
  window.__openAgent=open;
  window.__closeAgent=close;
})();
