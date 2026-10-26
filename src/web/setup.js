/* 首次运行引导：先建存储区，再谈别的。
   为什么不在下载页写一段 README 就完事：用户不会读；而且「存在哪」这件事
   决定了后面能不能备份、智能体读不读得到。放在界面里问他一次，比写十行文档有效。 */
(function(){
  var panel=document.getElementById('setupPanel');
  var mask=document.getElementById('setupMask');
  if(!panel||!mask) return;
  var input=document.getElementById('setupHome');
  var msg=document.getElementById('setupMsg');
  var go=document.getElementById('setupGo');
  var later=document.getElementById('setupLater');
  var pick=document.getElementById('setupPick');
  var SKIP='jy_setup_skip';

  function $(id){ return document.getElementById(id); }
  function say(text, bad){
    if(!msg) return;
    msg.textContent=text||'';
    msg.style.color=bad?'var(--bad)':'var(--muted)';
  }
  function headers(){
    var h={'Content-Type':'application/json','Accept':'application/json'};
    return window.apiHeaders?window.apiHeaders(h):h;
  }
  function open(){ panel.hidden=false; mask.hidden=false; setTimeout(function(){ if(input) input.focus(); },80); }
  function close(){
    panel.hidden=true; mask.hidden=true;
    try{ sessionStorage.setItem(SKIP,'1'); }catch(e){}
  }

  function check(){
    fetch('/api/settings/setup',{headers:headers()}).then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok||!d.needed) return;
      var skipped=false;
      try{ skipped=sessionStorage.getItem(SKIP)==='1'; }catch(e){}
      if(input&&d.default_home) input.value=d.default_home;
      if($('setupHint')&&d.notes>0){
        $('setupHint').textContent='这个位置已经有 '+d.notes+' 篇文档，直接用它继续就行。';
      }
      if(!skipped) open();
    }).catch(function(){});
  }

  if(later) later.addEventListener('click',close);
  if(mask) mask.addEventListener('click',close);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden) close();
  });

  if(pick) pick.addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='选择中…';
    fetch('/api/settings/pick-folder',{method:'POST',headers:headers(),body:'{}'})
      .then(function(r){ return r.json(); }).then(function(d){
        if(d&&d.ok&&d.path&&input) input.value=d.path;
        else if(d&&d.message) say(d.message,true);
      }).catch(function(){ say('打不开系统的选择框，可以直接把路径粘进来',true); })
      .finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  if(go) go.addEventListener('click',function(){
    var home=(input&&input.value||'').trim();
    if(!home){ say('先填一个目录，或点「选择…」',true); return; }
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='正在创建…';
    say('正在建目录…');
    fetch('/api/settings/setup',{method:'POST',headers:headers(),
      body:JSON.stringify({home:home})}).then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok){ say((d&&d.message)||'建存储区失败',true); return; }
      panel.hidden=true; mask.hidden=true;
      if(window.toast) window.toast('存储区已建好：'+d.home);
      // 让页面重新读一遍存储区：会话列表、文件页都指着它
      setTimeout(function(){ location.reload(); },400);
    }).catch(function(e){
      say('建存储区失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  check();
})();
