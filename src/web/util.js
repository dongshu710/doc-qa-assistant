
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function ragApiKey(){ try{ return sessionStorage.getItem('rag_api_key')||''; }catch(e){ return ''; } }
function apiHeaders(base){
  var h=base||{}, k=ragApiKey();
  if(k) h['X-API-Key']=k;
  return h;
}
function toast(msg,isErr){
  var box=document.getElementById('toasts'); if(!box) return;
  var d=document.createElement('div'); d.className='toast'+(isErr?' err':'');
  d.innerHTML='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="'+((isErr)?'M18 6 6 18M6 6l12 12':'m20 6-11 11-5-5')+'"/></svg><span></span>';
  d.querySelector('span').textContent=msg||'';
  box.appendChild(d);
  setTimeout(function(){ d.style.transition='opacity .25s, transform .25s'; d.style.opacity='0'; d.style.transform='translateY(6px)'; setTimeout(function(){d.remove();},260); }, 2600);
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
