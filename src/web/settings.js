
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
    if(markOpen) markOpen(mask);
    openOverlay('settings');
    document.body.classList.add('set-open');
    if(!state.loaded) load();
    var first=$('setBase');
    if(first) setTimeout(function(){ try{ first.focus(); }catch(e){} },60);
  }
  function closePanel(){
    // 先落盘再隐藏：Esc 关面板时输入框的 blur 不一定先到，
    // 不然「填完直接按 Esc」会丢掉这一笔改动。
    if(apiSave && apiSave.dirty) flushApi();
    var wrap=$('setHomeWrap');
    if(wrap && !wrap.hidden) flushHome();
    closeOverlay('settings');
    panel.hidden=true; if(mask) mask.hidden=true;
    document.body.classList.remove('set-open');
  }
  if(gear) gear.addEventListener('click',openPanel);
  var closeBtn=$('setClose'); if(closeBtn) closeBtn.addEventListener('click',closePanel);
  if(mask) mask.addEventListener('click',function(){
    // 连点齿轮时，第二下落在刚出现的遮罩上：不设冷静期就会「打开又立刻关上」
    if(window.tooSoon&&tooSoon(mask)) return;
    closePanel();
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden&&isTopOverlay('settings')) closePanel();
  });

  function selectTab(name){
    if(!tabs) return;
    [].forEach.call(tabs.children,function(x){ x.classList.toggle('on',x.getAttribute('data-tab')===name); });
    [].forEach.call(panel.querySelectorAll('.set-pane'),function(p){
      p.classList.toggle('on',p.getAttribute('data-pane')===name);
    });
  }
  /* 焦点陷阱：面板是模态的，Tab 到最后一个控件后应该回到第一个，
     否则焦点会跑到背后的页面上，键盘用户看着高亮消失、不知道自己在哪。 */
  panel.addEventListener('keydown',function(e){
    if(e.key!=='Tab') return;
    var items=[].slice.call(panel.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]):not([type=hidden]), select, textarea, summary'
    )).filter(function(el){ return el.offsetParent!==null; });
    if(!items.length) return;
    var first=items[0], last=items[items.length-1];
    if(e.shiftKey&&document.activeElement===first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey&&document.activeElement===last){ e.preventDefault(); first.focus(); }
  });
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
    /* 即时保存会在你打字的中途回写表单：正在编辑且已有内容的框不能被覆盖，
       否则「保存上一笔」会把这一笔顶掉。空框照旧回填（首次加载靠的就是它）。 */
    function fill(id,v){
      var el=$(id); if(!el) return;
      if(document.activeElement===el && el.value) return;
      /* dataset.dirty = 「用户改过、但这次回写还没确认它」。
         少了这一条会丢字：A 框失焦触发保存，用户在 B 框继续打字，
         保存回来把 B 框回写成旧值，接着的保存就「没有变化」可提交了。 */
      if(el.dataset.dirty==='1') return;
      el.value=v;
    }
    fill('setBase', d.llm.base_url||d.llm.effective_base_url||'');
    if($('setBase')) $('setBase').placeholder=d.llm.base_url_default||'';
    fill('setModel', d.llm.model||d.llm.effective_model||'');
    if($('setModel')) $('setModel').placeholder=d.llm.model_default||'';
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
    renderMcpClients(d.mcp_targets||[]);
    renderApiState(d.llm||{});
    fillTools();
    renderStorage(d.storage||{});
  }
  /* 原来的「智能体」侧栏面板并入这里：它唯一多出来的信息就是接出了几个工具。
     面板本身与这份 MCP 配置重复，删掉了。 */
  function fillTools(){
    var el=$('setTools'); if(!el) return;
    fetch('/tools.json').then(function(r){ return r.json(); }).then(function(d){
      var n=((d&&d.tools)||[]).length;
      el.textContent=n?('已接出 '+n+' 个工具，智能体读写的是同一个笔记目录'):'暂未接出工具';
    }).catch(function(){ el.textContent='工具清单读取失败'; });
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
    var notes=(st.notes||{}), idx=(st.index||{}), threads=(st.threads||{}), assets=(st.assets||{});
    // 只报几件事：文档 / 会话 / 附件多大、缓存多大、磁盘还剩多少。
    // 面积条不画了——几个数字并排比「占比」更好读，也不用解释颜色。
    if($('stNotes')) $('stNotes').textContent=fmtBytes(notes.bytes)+(notes.files?(' · '+notes.files+' 篇'):'');
    if($('stThreads')) $('stThreads').textContent=fmtBytes(threads.bytes)+(threads.files?(' · '+threads.files+' 条'):'');
    if($('stAssets')) $('stAssets').textContent=fmtBytes(assets.bytes)+(assets.files?(' · '+assets.files+' 个'):'');
    if($('stIndex')) $('stIndex').textContent=fmtBytes(Number(idx.bytes||0)+Number((st.embedding||{}).bytes||0));
    if($('stFree')) $('stFree').textContent=fmtBytes((st.disk||{}).free);
    if($('stKeep')) $('stKeep').value=String(st.keep_versions==null?30:st.keep_versions);
    var cost=$('stCost');
    if(cost){
      // 数字后面写清「这次是扫出来的还是上面那次的」：用户抱怨过设置面板打开要等一下
      var ms=Number(st.took_ms||0);
      // 缓存与否是实现细节：只在真扫了一遍时给耗时，缓存命中就不显示
      cost.textContent='本次统计用时 '+ms+' ms';
      cost.hidden=!!st.cached;
    }
  }
  if($('stClean')) $('stClean').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    var keep=Number($('stKeep').value||0);
    // 这条不可撤销：旧版本快照删掉就没了。先让人看清「保留几版」再动手。
    if(!confirm('将删除知识库的旧版本快照，只保留最近 '+keep+' 版。\n\n删掉的版本无法恢复（当前文档不受影响）。继续？')) return;
    btn.disabled=true; btn.textContent='清理中…';
    note('stMsg','正在清理，索引会重建一次…','');
    api('POST','/api/settings/storage/clean',{keep:Number($('stKeep').value||0)}).then(function(d){
      if(!d||!d.ok){ note('stMsg',(d&&d.message)||'清理失败',true); return; }
      renderStorage(d.storage||{});
      var freed=fmtBytes(d.freed_bytes||0);
      var removed=(d.removed||[]).length;
      note('stMsg','已清理 '+(removed?removed+' 个旧版本':'旧版本')+'，释放 '+freed
        +'；当前保留 '+d.keep+' 版。',false);
    }).catch(function(e){
      note('stMsg','清理失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  if($('stBackup')) $('stBackup').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='备份中…';
    api('POST','/api/storage/backup',{}).then(function(d){
      if(!d||!d.ok){ note('stMsg',(d&&d.message)||'备份失败',true); return; }
      var msg='已备份 '+(d.files||0)+' 个文件（'+fmtBytes(d.bytes||0)+'）';
      // 附件超限是「跳过」而不是失败，不显示出来用户会照着成功提示去恢复，才发现图没了
      var warn=(d.warnings||[]).join('；');
      note('stMsg',warn?(msg+'，但附件没进全：'+warn):(msg+'。'),!!warn);
      load();
    }).catch(function(e){
      note('stMsg','备份失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  function load(){
    api('GET','/api/settings').then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'读取设置失败',true); return; }
      applyView(d);
    });
  }

  /* 保存模型统一为「即时」。
     改之前这个面板有四套模型：接口要按「保存并启用」、存储要按「应用」、
     对话开关是选了就生效、安装分区又是另一个按钮。用户改完一项不知道要不要点，
     结果是不敢改。现在：文本框离开焦点（或按 Enter）就写盘，开关/下拉选了就写盘，
     全程没有保存按钮。安装分区的「写入配置」是往别人家的配置文件里写，属于动作，
     不属于保存，仍然单独一步 + 确认。 */
  var apiSave={dirty:false, saving:false, queued:false};

  function apiValues(){
    return {
      base:($('setBase')?$('setBase').value:'').trim(),
      model:($('setModel')?$('setModel').value:'').trim(),
      key:($('setKey')?$('setKey').value:'').trim()
    };
  }
  function apiChanged(){
    var v=apiValues(), cur=(state.view&&state.view.llm)||{};
    if(v.key) return true;
    return v.base!==(cur.base_url||'') || v.model!==(cur.model||'');
  }
  function restoreApi(){
    var cur=(state.view&&state.view.llm)||{};
    ['setBase','setModel','setKey'].forEach(function(id){
      var el=$(id); if(el) delete el.dataset.dirty;
    });
    if($('setBase')) $('setBase').value=cur.base_url||cur.effective_base_url||'';
    if($('setModel')) $('setModel').value=cur.model||cur.effective_model||'';
    if($('setKey')) $('setKey').value='';
  }
  function flushApi(){
    if(apiSave.saving){ apiSave.queued=true; return; }
    var v=apiValues();
    // 清空输入框不等于「清掉配置」：地址和模型是必填项，空着就还原并说清楚。
    // 静默 400 会让人以为改坏了。
    if(!v.base||!v.model){
      if(apiSave.dirty){ restoreApi(); note('setApiNote','接口地址与模型不能为空，已恢复原值',true); }
      apiSave.dirty=false;
      return;
    }
    /* 300 字够放下任何正常端点；更长的多半是粘错了整段配置，
       存进去会让之后每次请求都拿它去解析，错误还很难看出来。 */
    if(v.base.length>300){
      restoreApi();
      note('setApiNote','接口地址过长（'+v.base.length+' 字），已恢复原值',true);
      apiSave.dirty=false;
      return;
    }
    if(!apiChanged()){ apiSave.dirty=false; return; }
    var body={llm:{base_url:v.base, model:v.model}};
    if(v.key) body.llm.api_key=v.key;
    apiSave.saving=true; apiSave.dirty=false;
    note('setApiNote','保存中…',false);
    api('POST','/api/settings',body).then(function(d){
      apiSave.saving=false;
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'保存失败',true); return; }
      applyView(d);
      // 提交出去的字段若与框里一致，就说明这次编辑已被服务端确认，清掉未确认标记
      if($('setBase') && $('setBase').value.trim()===body.llm.base_url) delete $('setBase').dataset.dirty;
      if($('setModel') && $('setModel').value.trim()===body.llm.model) delete $('setModel').dataset.dirty;
      note('setApiNote','已保存，下一次提问就用新配置',false);
      if(apiSave.queued){ apiSave.queued=false; apiSave.dirty=true; flushApi(); }
    },function(){
      apiSave.saving=false;
      note('setApiNote','保存失败：连不上本地服务',true);
    });
  }
  ['setBase','setModel','setKey'].forEach(function(id){
    var el=$(id); if(!el) return;
    el.addEventListener('input',function(){ apiSave.dirty=true; el.dataset.dirty='1'; });
    el.addEventListener('blur',flushApi);
    el.addEventListener('keydown',function(e){
      if(e.key==='Enter'){ e.preventDefault(); el.blur(); }
    });
  });

  if($('setTest')) $('setTest').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    // 连点三次会真发三次探测请求（每次都等 15 秒），没有意义
    btn.disabled=true; btn.textContent='测试中…';
    note('setApiNote','测试中（最多等 15 秒）…',false);
    api('POST','/api/settings/test',{
      base_url:$('setBase').value.trim(),
      model:$('setModel').value.trim(),
      api_key:$('setKey').value.trim()
    }).then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'测试失败',true); return; }
      note('setApiNote','连接正常，往返 '+d.latency_ms+' ms',false);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
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

  /* 目录同样是即时：填完离开输入框就切，切失败会保留原位置并把原因写出来。 */
  var homeSaving=false;
  function flushHome(){
    if(homeSaving) return;
    var v=($('setHome')?$('setHome').value:'').trim();
    // 清空不提交：那通常是「正在重打一遍路径」，不是「回到默认位置」
    if(!v) return;
    var cur=((state.view&&state.view.notes&&state.view.notes.home_effective)||'').trim();
    if(v===cur) return;
    homeSaving=true;
    applyHome(v).then(function(){ homeSaving=false; },function(){ homeSaving=false; });
  }
  if($('setHome')){
    $('setHome').addEventListener('input',function(){ homeSaving=false; });
    $('setHome').addEventListener('blur',flushHome);
    $('setHome').addEventListener('keydown',function(e){
      if(e.key==='Enter'){ e.preventDefault(); this.blur(); }
    });
  }

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

  var chatSeq=0;
  if($('setStoreChat')) $('setStoreChat').addEventListener('change',function(){
    var on=this.checked, seq=++chatSeq;
    api('POST','/api/settings',{notes:{store_chat:on}}).then(function(d){
      // 连点开关时请求会并行：只有最后一次的结果能改界面，
      // 否则先发的响应回来会把开关拨回上一次的值，看着像「点了没反应」。
      if(seq!==chatSeq) return;
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

  function renderMcpClients(items){
    var box=$('setMcpClient'); if(!box) return;
    box.innerHTML=items.map(function(t){
      var tag=t.exists?'（已有配置，会合并）':'（将新建）';
      return '<option value="'+esc(t.id)+'">'+esc(t.name)+tag+'</option>';
    }).join('');
    if(!items.length){
      box.innerHTML='<option value="claude">Claude Desktop</option>';
      if($('setMcpNote')) $('setMcpNote').textContent='当前系统没找到已知客户端，只能手动复制配置。';
    }
  }

  if($('setMcpCopy')) $('setMcpCopy').addEventListener('click',function(){
    var text=$('setMcpPre')?$('setMcpPre').textContent:'';
    function done(){ note('setMcpNote','已复制，粘贴到客户端的 mcpServers 里',false); }
    function fail(){ note('setMcpNote','复制失败，请手动选中复制',true); }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(done,fail);
    } else { fail(); }
  });

  if($('setMcpInstall')) $('setMcpInstall').addEventListener('click',function(){
    var sel=$('setMcpClient');
    var client=sel?sel.value:'claude';
    var label=sel&&sel.selectedIndex>=0?sel.options[sel.selectedIndex].text:client;
    if(!confirm('会写入 '+label+' 的配置，原文件先备份。继续？')) return;
    api('POST','/api/settings/mcp/install',{client:client}).then(function(d){
      if(!d||!d.ok){ note('setMcpNote',(d&&d.message)||'写入失败',true); return; }
      note('setMcpNote',d.message+'（'+d.target+'）',false);
    });
  });

  // 每页加载都先拉一次：问答页要靠 store_chat 决定「存为笔记」是否出现，
  // 不能等用户打开设置面板才拿到状态。
  load();
})();
