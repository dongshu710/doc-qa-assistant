
(function(){
  var panel=document.getElementById('setPanel');
  if(!panel) return;
  var mask=document.getElementById('setMask');
  var gear=document.getElementById('setBtn');
  var tabs=document.getElementById('setTabs');
  var state={loaded:false, view:null};

  function $(id){ return document.getElementById(id); }
  // 转义统一用 JS_UTIL 里的那份：两处各写一套，改漏一处就是 XSS 缺口
  var esc=window.esc;
  function note(id,msg,bad){
    var el=$(id); if(!el) return;
    el.textContent=msg||'';
    el.className='set-note'+(msg?(bad?' err':' ok'):'');
  }
  // 更新结果里要放链接，textContent 装不下；进来的一律先转义
  function noteHtml(id,html,bad){
    var el=$(id); if(!el) return;
    el.innerHTML=html||'';
    el.className='set-note'+(html?(bad?' err':' ok'):'');
  }
  function outLink(href,text){
    if(!href) return '';
    return '<a href="'+esc(href)+'" target="_blank" rel="noopener">'+esc(text)+'</a>';
  }
  function api(method,path,body){
    var opt={method:method,headers:{'Content-Type':'application/json'}};
    if(body) opt.body=JSON.stringify(body);
    return fetch(path,opt).then(function(r){
      return r.json().catch(function(){ return {ok:false,message:'服务端返回了非 JSON 内容'}; });
    },function(){ return {ok:false,message:'连不上本地服务'}; });
  }

  function openPanel(){
    // 移动端上侧栏可能正开着：它 z-index 更高，不收起会把弹窗整个挡住
    if(window.__closeSide) window.__closeSide();
    panel.hidden=false; if(mask) mask.hidden=false;
    document.body.classList.add('set-open');
    if(!state.loaded) load();
    var first=$('setBase');
    if(first) setTimeout(function(){ try{ first.focus(); }catch(e){} },60);
  }
  function closePanel(){
    panel.hidden=true; if(mask) mask.hidden=true;
    document.body.classList.remove('set-open');
  }
  if(gear) gear.addEventListener('click',openPanel);
  var closeBtn=$('setClose'); if(closeBtn) closeBtn.addEventListener('click',closePanel);
  if(mask) mask.addEventListener('click',closePanel);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden) closePanel();
  });

  function selectTab(name){
    if(!tabs) return;
    [].forEach.call(tabs.children,function(x){ x.classList.toggle('on',x.getAttribute('data-tab')===name); });
    [].forEach.call(panel.querySelectorAll('.set-pane'),function(p){
      p.classList.toggle('on',p.getAttribute('data-pane')===name);
    });
  }
  if(tabs) tabs.addEventListener('click',function(e){
    var btn=e.target.closest('button[data-tab]'); if(!btn) return;
    selectTab(btn.getAttribute('data-tab'));
  });
  // 给别的脚本一个入口：输入框里的「接口」标签点开就要落在对应分区
  window.__openSettings=function(tab){ openPanel(); if(tab) selectTab(tab); };
  // 页脚版本号点开就是「安装」分区：想看版本的人，下一个动作通常是查更新
  var footVer=$('footVer');
  if(footVer) footVer.addEventListener('click',function(){
    openPanel(); selectTab('install');
  });

  // 存储区位置默认只显示路径，点「更换」才展开输入框：日常不需要看这一堆
  function showHomeEditor(show){
    var wrap=$('setHomeWrap'); if(!wrap) return;
    wrap.hidden=!show;
    if(show&&$('setHome')){ $('setHome').focus(); try{ $('setHome').select(); }catch(e){} }
  }

  function renderBackup(bk){
    bk=bk||{};
    // 红点规则收在 FILES_JS 里（含「点过就消」的本地标记），这里只转发，避免两处各判一次
    if(window.__filesBackup){ window.__filesBackup(bk); return; }
    if($('filesBackup')){
      $('filesBackup').textContent=bk.text?(bk.text+(bk.due?' · 建议导出一次':'')):'';
      $('filesBackup').className='files-note'+(bk.due?' err':'');
    }
  }

  function refreshBackup(){
    // 只刷红点与文案，不碰用户正在填的输入框——存完笔记立刻看到提醒才有意义
    api('GET','/api/settings').then(function(d){
      if(d&&d.ok) renderBackup(d.notes&&d.notes.backup);
    });
  }

  function applyView(d){
    state.view=d; state.loaded=true;
    if($('setCfgWarn')){
      // 配置写坏时界面显示的是默认值，必须说清楚，否则用户以为密钥自己没了
      var cfgWarn=d.config_error
        ? ('配置文件无法解析（'+d.config_error+'），下面显示的是默认值；修好后重新打开面板')
        : (d.config_backup ? ('原配置无法解析，保存前已备份到 '+d.config_backup) : '');
      $('setCfgWarn').hidden=!cfgWarn;
      $('setCfgWarn').textContent=cfgWarn;
    }
    // 输入框填「配置值」，没配过就填当前生效值：否则空表单点保存会被校验拦下（配置写坏时直接死锁）
    if($('setBase')){ $('setBase').value=d.llm.base_url||d.llm.effective_base_url||''; $('setBase').placeholder=d.llm.base_url_default||''; }
    if($('setModel')){ $('setModel').value=d.llm.model||d.llm.effective_model||''; $('setModel').placeholder=d.llm.model_default||''; }
    if($('setKey')){
      $('setKey').value='';
      $('setKey').placeholder=d.llm.api_key_set
        ? ('已保存 '+d.llm.api_key_masked+'，留空不改')
        : '粘贴密钥';
    }
    // 离线不是错误：只在「已接入」时用成功色，未接入保持中性灰
    if($('setApiNote')){
      $('setApiNote').textContent = d.llm.key_ready
        ? ('当前生效：'+(d.llm.effective_model||'')+' @ '+(d.llm.effective_base_url||''))
        : '还没配密钥，问答会走本地抽取，不调用模型';
      $('setApiNote').className = 'set-note' + (d.llm.key_ready ? ' ok' : '');
    }

    showHomeEditor(false);
    if($('stHome')) $('stHome').textContent=d.notes.home_effective||'—';
    if($('setHome')) $('setHome').value=d.notes.home||'';
    // 路径已经在上面那行显示过了，这里只在出错时说话，避免同一句写两遍
    note('setHomeNote', d.notes.error ? ('存储区不可用：'+d.notes.error) : '', !!d.notes.error);

    var mig=$('setMigrate');
    if(mig){
      var pending=d.pending_migration;
      if(pending&&pending.count){
        mig.hidden=false;
        mig.setAttribute('data-from',pending.from||'');
        if($('setMigrateText')) $('setMigrateText').textContent=
          '原位置还有 '+pending.count+' 篇笔记，要复制到新位置吗？';
      } else {
        mig.hidden=true;
        mig.removeAttribute('data-from');
      }
    }

    var bk=(d.notes&&d.notes.backup)||{};
    renderBackup(bk);

    if($('setStoreChat')) $('setStoreChat').checked=!!d.notes.store_chat;
    window.__storeChat=!!d.notes.store_chat;
    try{ document.dispatchEvent(new CustomEvent('storechat:change',{detail:window.__storeChat})); }catch(e){}

    var dl=d.downloads||{};
    var page=(d.repo_url||'')+'/releases/latest';
    if($('setDownload')) $('setDownload').href=dl.app||page;
    if($('setDownloadPlugin')) $('setDownloadPlugin').href=dl.plugin||page;
    if($('setMcpPre')) $('setMcpPre').textContent=JSON.stringify(d.mcp||{},null,2);
    renderApiState(d.llm||{});
    renderStorage(d.storage||{});
  }

  function sizeText(n){
    n=Number(n)||0;
    if(n<1024) return n+' B';
    var units=['KB','MB','GB','TB'], i=-1, v=n;
    do{ v/=1024; i++; }while(v>=1024&&i<units.length-1);
    return (v>=10?v.toFixed(0):v.toFixed(1))+' '+units[i];
  }
  function renderApiState(llm){
    var box=$('apiState'); if(!box) return;
    llm=llm||{};
    var ready=!!llm.key_ready;
    box.classList.toggle('on',ready);
    if($('apiStateTitle')) $('apiStateTitle').textContent=
      ready?('已接入 '+(llm.effective_model||llm.model||'')):'未接入模型';
    if($('apiStateText')) $('apiStateText').textContent=ready
      ? ('请求发往 '+(llm.effective_base_url||'')+'，密钥已保存在本机。')
      : '当前使用离线抽取：直接从文档里摘录原句，不调用模型。';
  }
  function renderStorage(st){
    st=st||{};
    var notes=(st.notes||{}), idx=(st.index||{}), threads=(st.threads||{});
    // 只报四件事：文档多大、会话多大、缓存多大、磁盘还剩多少。
    // 面积条不画了——三个数字并排比「占比」更好读，也不用解释颜色。
    if($('stNotes')) $('stNotes').textContent=sizeText(notes.bytes)+(notes.files?(' · '+notes.files+' 篇'):'');
    if($('stThreads')) $('stThreads').textContent=sizeText(threads.bytes)+(threads.files?(' · '+threads.files+' 条'):'');
    if($('stIndex')) $('stIndex').textContent=sizeText(Number(idx.bytes||0)+Number((st.embedding||{}).bytes||0));
    if($('stFree')) $('stFree').textContent=sizeText((st.disk||{}).free);
    if($('stKeep')) $('stKeep').value=String(st.keep_versions==null?30:st.keep_versions);
    var cost=$('stCost');
    if(cost){
      // 数字后面写清「这次是扫出来的还是上面那次的」：用户抱怨过设置面板打开要等一下
      var ms=Number(st.took_ms||0);
      cost.textContent=st.cached
        ? '沿用 30 秒内的统计结果（笔记 '+((notes.files||0))+' 篇无变化）'
        : '本次统计用时 '+ms+' ms';
      cost.hidden=false;
    }
  }
  if($('stClean')) $('stClean').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='清理中…';
    note('stMsg','正在清理，索引会重建一次…','');
    api('POST','/api/settings/storage/clean',{keep:Number($('stKeep').value||0)}).then(function(d){
      if(!d||!d.ok){ note('stMsg',(d&&d.message)||'清理失败',true); return; }
      renderStorage(d.storage||{});
      var freed=sizeText(d.freed_bytes||0);
      var removed=(d.removed||[]).length;
      note('stMsg','已清理 '+(removed?removed+' 个旧版本':'旧版本')+'，释放 '+freed
        +'；当前保留 '+d.keep+' 版。',false);
    }).catch(function(e){
      note('stMsg','清理失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  function load(){
    api('GET','/api/settings').then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'读取设置失败',true); return; }
      applyView(d);
    });
  }

  if($('setSave')) $('setSave').addEventListener('click',function(){
    var body={llm:{base_url:$('setBase').value.trim(),model:$('setModel').value.trim()}};
    var key=$('setKey').value.trim();
    if(key) body.llm.api_key=key;
    note('setApiNote','保存中…',false);
    api('POST','/api/settings',body).then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'保存失败',true); return; }
      applyView(d);
      note('setApiNote','已保存，下一次提问就用新配置',false);
    });
  });

  if($('setTest')) $('setTest').addEventListener('click',function(){
    note('setApiNote','测试中（最多等 15 秒）…',false);
    api('POST','/api/settings/test',{
      base_url:$('setBase').value.trim(),
      model:$('setModel').value.trim(),
      api_key:$('setKey').value.trim()
    }).then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'测试失败',true); return; }
      note('setApiNote','连接正常，往返 '+d.latency_ms+' ms',false);
    });
  });

  // 检查更新：只读一次 GitHub 的 latest Release，不下载、不落盘、不改配置。
  // 离线、被代理拦、仓库没发过 Release 都要说清楚是哪一种，而不是笼统地「失败」。
  if($('setUpdate')) $('setUpdate').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='检查中…';
    note('setUpdateNote','正在查 GitHub…','');
    api('GET','/api/update/check?force=1').then(function(d){
      if(!d||!d.ok){
        var url=(d&&d.url)||'';
        noteHtml('setUpdateNote',esc((d&&d.message)||'检查失败')
          +(url?' · '+outLink(url,'打开发布页'):''),true);
        return;
      }
      if(!d.has_update){
        noteHtml('setUpdateNote','已是最新：v'+esc(d.latest)+'（本地 v'+esc(d.current)+'）');
        return;
      }
      var dl=d.downloads||{};
      var links=[outLink(dl.app,'下载应用包'),outLink(dl.plugin,'下载插件包'),
                 outLink(d.url,'更新说明')].filter(Boolean).join(' · ');
      noteHtml('setUpdateNote','发现新版本 v'+esc(d.latest)
        +(d.published_at?'（'+esc(d.published_at)+'）':'')+'：'+links);
    }).catch(function(e){
      note('setUpdateNote','检查失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  if($('stToggleHome')) $('stToggleHome').addEventListener('click',function(){
    var wrap=$('setHomeWrap');
    showHomeEditor(!!(wrap&&wrap.hidden));
  });
  if($('setHomeReset')) $('setHomeReset').addEventListener('click',function(){
    if($('setHome')) $('setHome').value='';
    applyHome('');
  });

  function applyHome(home){
    note('setHomeNote','切换中…',false);
    return api('POST','/api/settings',{notes:{home:home}}).then(function(d){
      if(!d||!d.ok){ note('setHomeNote',(d&&d.message)||'切换失败',true); return d; }
      applyView(d);
      note('setHomeNote','已切换：'+(d.notes.home_effective||''),false);
      if(window.__afterHomeChange) window.__afterHomeChange();
      return d;
    });
  }

  if($('setHomeSave')) $('setHomeSave').addEventListener('click',function(){
    var home=$('setHome').value.trim();
    if(!home){ note('setHomeNote','先填一个目录，或用「用默认位置」',true); return; }
    applyHome(home);
  });

  if($('setPick')) $('setPick').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='等待选择…';
    note('setHomeNote','已弹出系统窗口，选好目录会自动应用',false);
    api('POST','/api/settings/pick-folder',{}).then(function(d){
      btn.disabled=false; btn.textContent=label;
      if(!d||!d.ok){
        var kind=d&&d.error;
        note('setHomeNote', kind==='cancelled' ? '已取消'
          : ((d&&d.message)||'选择失败，请手动填路径'), !(kind==='cancelled'));
        return;
      }
      segHome('custom');
      if($('setHome')) $('setHome').value=d.path;
      // 选中即应用：对话框本身就是一次确认，再要求点「应用」是多余的一步
      applyHome(d.path);
    },function(){
      btn.disabled=false; btn.textContent=label;
      note('setHomeNote','请求超时，请手动填路径',true);
    });
  });

  if($('setMigrateGo')) $('setMigrateGo').addEventListener('click',function(){
    var mig=$('setMigrate');
    var from=mig&&mig.getAttribute('data-from');
    if(!from){ if(mig) mig.hidden=true; return; }
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='复制中…';
    api('POST','/api/settings/notes/migrate',{from:from}).then(function(d){
      btn.disabled=false; btn.textContent=label;
      if(!d||!d.ok){ note('setHomeNote',(d&&d.message)||'复制失败',true); return; }
      if(mig) mig.hidden=true;
      var msg='已复制 '+d.copied+' 篇';
      if(d.skipped) msg+='，跳过 '+d.skipped+' 篇同名';
      if(d.failed&&d.failed.length) msg+='，失败 '+d.failed.length+' 篇';
      note('setHomeNote',msg,!!(d.failed&&d.failed.length));
      if(window.__afterHomeChange) window.__afterHomeChange();
    });
  });

  if($('setMigrateNo')) $('setMigrateNo').addEventListener('click',function(){
    var mig=$('setMigrate'); if(mig) mig.hidden=true;
  });

  if($('setOpen')) $('setOpen').addEventListener('click',function(){
    api('POST','/api/settings/open',{}).then(function(d){
      if(!d||!d.ok) note('setHomeNote',(d&&d.message)||'打不开文件夹',true);
    });
  });

  if($('setStoreChat')) $('setStoreChat').addEventListener('change',function(){
    var on=this.checked;
    api('POST','/api/settings',{notes:{store_chat:on}}).then(function(d){
      if(!d||!d.ok){
        $('setStoreChat').checked=!on;
        note('setChatNote',(d&&d.message)||'保存失败',true);
        return;
      }
      window.__storeChat=on;
      note('setChatNote', on
        ? '已开启：问答里会出现「存为笔记」'
        : '已关闭：不再写入任何对话内容，已有笔记不受影响', false);
      try{ document.dispatchEvent(new CustomEvent('storechat:change',{detail:on})); }catch(e){}
    });
  });

  if($('setMcpCopy')) $('setMcpCopy').addEventListener('click',function(){
    var text=$('setMcpPre')?$('setMcpPre').textContent:'';
    function done(){ note('setMcpNote','已复制，粘贴到客户端的 mcpServers 里',false); }
    function fail(){ note('setMcpNote','复制失败，请手动选中复制',true); }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(done,fail);
    } else { fail(); }
  });

  if($('setMcpInstall')) $('setMcpInstall').addEventListener('click',function(){
    if(!confirm('会写入 Claude Desktop 的配置，原文件先备份。继续？')) return;
    api('POST','/api/settings/mcp/install',{}).then(function(d){
      if(!d||!d.ok){ note('setMcpNote',(d&&d.message)||'写入失败',true); return; }
      note('setMcpNote',d.message+'（'+d.target+'）',false);
    });
  });

  // 每页加载都先拉一次：问答页要靠 store_chat 决定「存为笔记」是否出现，
  // 不能等用户打开设置面板才拿到状态。
  load();
})();
