
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
