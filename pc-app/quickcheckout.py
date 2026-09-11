#!/usr/bin/env python3
"""
Quick Checkout PC — autocop.app + Vinted autobuy
WebView2-based desktop app, no extension needed.
"""

import webview

# ── Detector: injected on autocop.app ────────────────────────────────────────

DETECTOR_JS = r"""
(function(){
if(window.__qcPCLoaded)return;
window.__qcPCLoaded=true;

// Load settings from localStorage
var cfg={domain:'www.vinted.fr',autobuy:false,token:''};
try{var s=localStorage.getItem('__qcCfg');if(s){var o=JSON.parse(s);for(var k in o)if(o.hasOwnProperty(k))cfg[k]=o[k];}}catch(e){}

// CSS
if(!document.getElementById('qc-style')){
var st=document.createElement('style');st.id='qc-style';
st.textContent='.qc-bc{position:absolute;top:6px;right:6px;z-index:9999;display:flex;flex-direction:column;align-items:flex-end;gap:4px;pointer-events:none}'
+'.qc-cb{pointer-events:all;display:inline-flex;align-items:center;gap:5px;padding:5px 11px;background:linear-gradient(135deg,#6c63ff,#5546d4);color:#fff;border:none;border-radius:18px;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;box-shadow:0 2px 10px rgba(108,99,255,.45);transition:transform .1s,box-shadow .1s;white-space:nowrap;font-family:system-ui,sans-serif}'
+'.qc-cb:hover{transform:translateY(-1px) scale(1.04);box-shadow:0 4px 16px rgba(108,99,255,.6)}'
+'.qc-cb:disabled{opacity:.5;cursor:not-allowed;transform:none}'
+'.qc-sold{background:linear-gradient(135deg,#555,#333)!important;box-shadow:none!important}'
+'.qc-avail{background:linear-gradient(135deg,#2D6A4F,#1a4534)}'
+'.qc-fab{position:fixed;bottom:20px;right:20px;z-index:99998;width:46px;height:46px;border-radius:23px;background:linear-gradient(135deg,#6c63ff,#5546d4);color:#fff;border:none;cursor:pointer;font-size:22px;box-shadow:0 4px 16px rgba(108,99,255,.5);display:flex;align-items:center;justify-content:center}'
+'.qc-panel{position:fixed;bottom:76px;right:20px;z-index:99999;background:#1a1a2e;border-radius:16px;padding:20px;width:272px;color:#fff;font-family:system-ui,sans-serif;box-shadow:0 8px 32px rgba(0,0,0,.6);border:1px solid rgba(108,99,255,.3)}'
+'.qc-panel h4{margin:0 0 14px;font-size:14px;color:#a29bfe;text-transform:uppercase;font-weight:800}'
+'.qc-lbl{display:block;font-size:11px;color:#888;margin:10px 0 3px;font-weight:600}'
+'.qc-sel,.qc-inp{width:100%;padding:7px 10px;border-radius:8px;border:1px solid #2a2a4a;background:#0f0f23;color:#fff;font-size:12px;box-sizing:border-box}'
+'.qc-row{display:flex;align-items:center;gap:8px;margin-top:12px}'
+'.qc-sw{width:38px;height:21px;-webkit-appearance:none;appearance:none;background:#333;border-radius:11px;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0;border:none}'
+'.qc-sw:checked{background:#6c63ff}'
+'.qc-sw::before{content:"";position:absolute;width:17px;height:17px;border-radius:50%;background:#fff;top:2px;left:2px;transition:left .2s}'
+'.qc-sw:checked::before{left:19px}'
+'.qc-btn-save{width:100%;margin-top:14px;padding:9px;border-radius:10px;border:none;background:#6c63ff;color:#fff;font-size:13px;font-weight:700;cursor:pointer}'
+'.qc-close{position:absolute;top:12px;right:14px;background:none;border:none;color:#666;cursor:pointer;font-size:16px}'
+'.qc-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:999999;padding:10px 22px;border-radius:20px;font-family:system-ui,sans-serif;font-size:13px;font-weight:700;color:#fff;pointer-events:none;transition:opacity .3s;white-space:nowrap}';
document.head.appendChild(st);
}

// Scan
var _proc=new WeakSet(),_avc={};

function getId(url){var m=url.match(/\/items\/(\d+)/);if(m)return m[1];m=url.match(/[-\/](\d{7,})/);return m?m[1]:null;}
function isVinted(url){return /vinted\.(fr|be|es|de|it|co\.uk|nl|pl|pt|com)/i.test(url);}
function cardOf(a){var el=a.parentElement,best=a;for(var d=0;d<10&&el;d++){var r=el.getBoundingClientRect();if(r.width>=80&&r.height>=80){best=el;if(el.parentElement&&el.parentElement.querySelectorAll('a[href*="vinted."]').length>3)break;}el=el.parentElement;}return best;}

function checkAvail(id){
if(!cfg.token)return Promise.resolve(null);
var now=Date.now();
if(_avc[id]&&now-_avc[id].ts<30000)return Promise.resolve(_avc[id].ok);
return fetch('https://'+cfg.domain+'/api/v2/items/'+id,{
  headers:{Authorization:'Bearer '+cfg.token,Accept:'application/json'},credentials:'include'
}).then(function(r){
  if(!r.ok)return null;
  return r.json().then(function(d){var item=d.item||d.data;if(!item)return null;
    var ok=item.can_be_sold!==false&&item.is_for_sale!==false&&item.status!=='sold';
    _avc[id]={ok:ok,ts:Date.now()};return ok;
  });
}).catch(function(){return null;});
}

function injectBtn(a,id){
var card=cardOf(a);
if(card.querySelector('[data-qcid="'+id+'"]'))return;
var pe=card.querySelector('[class*="price" i]');
var ps=pe?' '+(pe.textContent||'').replace(/[^0-9,.\s€\xa3]/g,'').trim():'';
var btn=document.createElement('button');
btn.className='qc-cb';btn.dataset.qcid=id;
btn.innerHTML='⚡ CHECKOUT'+ps;
checkAvail(id).then(function(ok){
  if(ok===false){btn.innerHTML='❌ VENDU';btn.classList.add('qc-sold');btn.disabled=true;}
  else if(ok===true)btn.classList.add('qc-avail');
});
btn.addEventListener('click',function(e){
  e.preventDefault();e.stopPropagation();if(btn.disabled)return;
  btn.innerHTML='⏳ ...';btn.disabled=true;
  // Pass autobuy flag via URL query param (avoids cross-origin localStorage)
  var url='https://'+cfg.domain+'/items/'+id;
  if(cfg.autobuy)url+='?_qc_ab=1&_qc_ts='+Date.now();
  window.location.href=url;
});
var wrap=document.createElement('div');wrap.className='qc-bc';wrap.appendChild(btn);
if(getComputedStyle(card).position==='static')card.style.position='relative';
card.appendChild(wrap);
}

function scan(){
var links=document.querySelectorAll('a[href*="vinted."]');
for(var i=0;i<links.length;i++){
  var a=links[i];if(_proc.has(a)||!isVinted(a.href))continue;
  var id=getId(a.href);if(!id)continue;_proc.add(a);injectBtn(a,id);
}
}

function toast(msg,clr){
var t=document.createElement('div');t.className='qc-toast';
t.style.background=clr||'rgba(108,99,255,.92)';t.textContent=msg;
document.body.appendChild(t);
setTimeout(function(){t.style.opacity='0';setTimeout(function(){t.remove();},300);},2500);
}

function showPanel(){
var old=document.getElementById('qc-panel');if(old){old.remove();return;}
var p=document.createElement('div');p.id='qc-panel';p.className='qc-panel';
p.innerHTML='<button class="qc-close" id="qc-close">✕</button><h4>⚡ Quick Checkout</h4>'
+'<label class="qc-lbl">Marché Vinted</label>'
+'<select class="qc-sel" id="qc-dom">'
+'<option value="www.vinted.fr">vinted.fr (France)</option>'
+'<option value="www.vinted.be">vinted.be (Belgique)</option>'
+'<option value="www.vinted.es">vinted.es (Espagne)</option>'
+'<option value="www.vinted.de">vinted.de (Allemagne)</option>'
+'<option value="www.vinted.it">vinted.it (Italie)</option>'
+'<option value="www.vinted.co.uk">vinted.co.uk (UK)</option>'
+'<option value="www.vinted.nl">vinted.nl (Pays-Bas)</option>'
+'<option value="www.vinted.pl">vinted.pl (Pologne)</option>'
+'<option value="www.vinted.pt">vinted.pt (Portugal)</option>'
+'</select>'
+'<div class="qc-row"><input type="checkbox" class="qc-sw" id="qc-ab"><label for="qc-ab" style="font-size:13px;color:#fff;cursor:pointer">Autobuy activé</label></div>'
+'<label class="qc-lbl">Bearer Token (vérif dispo)</label>'
+'<input type="password" class="qc-inp" id="qc-tok" placeholder="Token Vinted...">'
+'<button class="qc-btn-save" id="qc-sv">\U0001f4be Sauvegarder</button>';
document.body.appendChild(p);
document.getElementById('qc-dom').value=cfg.domain;
document.getElementById('qc-ab').checked=cfg.autobuy;
document.getElementById('qc-tok').value=cfg.token;
document.getElementById('qc-close').addEventListener('click',function(){p.remove();});
document.getElementById('qc-sv').addEventListener('click',function(){
  cfg.domain=document.getElementById('qc-dom').value;
  cfg.autobuy=document.getElementById('qc-ab').checked;
  cfg.token=document.getElementById('qc-tok').value.trim();
  try{localStorage.setItem('__qcCfg',JSON.stringify(cfg));}catch(e){}
  toast('✅ Sauvegardé !','rgba(34,197,94,.9)');p.remove();
});
}

function showFAB(){
if(document.getElementById('qc-fab'))return;
var fab=document.createElement('button');
fab.id='qc-fab';fab.className='qc-fab';fab.title='Paramètres Quick Checkout';
fab.textContent='⚡';
fab.addEventListener('click',function(){showPanel();});
document.body.appendChild(fab);
toast('⚡ Quick Checkout activé !');
}

scan();
new MutationObserver(function(){clearTimeout(window.__qcST);window.__qcST=setTimeout(scan,150);})
.observe(document.documentElement,{childList:true,subtree:true});
showFAB();
})();
"""

# ── Checkout: injected on vinted.* pages ─────────────────────────────────────

CHECKOUT_JS = r"""
(function(){
if(window.__qcChkLoaded)return;
window.__qcChkLoaded=true;

// Read autobuy flag from URL (set by detector, avoids cross-origin localStorage)
var params=new URLSearchParams(location.search);
var autobuy=params.get('_qc_ab')==='1';
var ts=parseInt(params.get('_qc_ts')||'0',10);
var fresh=ts>0&&(Date.now()-ts<60000);

// CSS
if(!document.getElementById('qc-chk-style')){
var s=document.createElement('style');s.id='qc-chk-style';
s.textContent='.qc-ov{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.78);z-index:999999;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif}'
+'.qc-ob{background:#1a1a2e;border-radius:20px;padding:36px 52px;text-align:center;min-width:260px;border:1px solid rgba(108,99,255,.3)}'
+'.qc-ot{font-size:22px;font-weight:900;color:#fff;margin-bottom:6px}'
+'.qc-os{font-size:14px;color:#a29bfe;margin-bottom:20px;min-height:20px}'
+'.qc-pb{width:200px;height:6px;background:#2a2a4a;border-radius:3px;overflow:hidden;margin:0 auto}'
+'.qc-pf{height:100%;background:linear-gradient(90deg,#6c63ff,#a29bfe);border-radius:3px;transition:width .4s}'
+'.qc-vt{position:fixed;bottom:20px;right:20px;z-index:99999;padding:12px 20px;border-radius:12px;font-family:system-ui,sans-serif;font-size:13px;font-weight:700;color:#fff;pointer-events:none;background:rgba(108,99,255,.9)}';
document.head.appendChild(s);
}

if(!autobuy||!fresh){
var vt=document.createElement('div');vt.className='qc-vt';
vt.textContent=autobuy?'⚡ QC: lien expiré':'⚡ Quick Checkout prêt — cliquez Acheter';
document.body.appendChild(vt);setTimeout(function(){vt.remove();},4000);
return;
}

// Autobuy
var _ov=null,_pf=null;

function showOv(step,pct){
if(!_ov){
  _ov=document.createElement('div');_ov.className='qc-ov';
  _ov.innerHTML='<div class="qc-ob"><div class="qc-ot">⚡ Quick Checkout</div><div class="qc-os" id="qcs"></div><div class="qc-pb"><div class="qc-pf" id="qcp" style="width:0"></div></div></div>';
  document.body.appendChild(_ov);_pf=document.getElementById('qcp');
}
var el=document.getElementById('qcs');if(el)el.textContent=step;
if(_pf)_pf.style.width=pct+'%';
}

function hideOv(ok,msg){
var el=document.getElementById('qcs');if(el)el.textContent=msg;
if(_pf)_pf.style.width='100%';
var box=_ov&&_ov.querySelector('.qc-ob');
if(box)box.style.borderTop='3px solid '+(ok?'#22c55e':'#ef4444');
setTimeout(function(){if(_ov){_ov.remove();_ov=null;}},2500);
}

function waitFor(fn,ms){
return new Promise(function(res,rej){
  var t=Date.now()+ms;
  function tick(){var el=fn();if(el)return res(el);if(Date.now()>t)return rej(new Error('Timeout'));requestAnimationFrame(tick);}
  tick();
});
}

function tap(el){
el.scrollIntoView({behavior:'smooth',block:'center'});el.focus();
['pointerdown','pointerup','click'].forEach(function(type){
  try{el.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true}));}
  catch(e){el.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true}));}
});
}

function findBtn(re){
var els=document.querySelectorAll('button,[role="button"],input[type="submit"]');
for(var i=0;i<els.length;i++){
  var el=els[i],txt=(el.textContent||el.value||'').trim();
  if(re.test(txt)&&el.offsetParent!==null&&!el.disabled)return el;
}return null;
}

function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}

showOv('Recherche bouton Acheter…',8);
waitFor(function(){return findBtn(/acheter|buy|kaufen|comprar|acquista|kopen|kup|acquérir/i);},9000)
.then(function(b){showOv('Clic Acheter…',28);return sleep(300).then(function(){tap(b);return sleep(200);});})
.then(function(){showOv('Sélection livraison…',50);return waitFor(function(){return findBtn(/continuer|continue|suivant|next|weiter|siguiente|avanti|volgende|dalej|continuar/i);},14000);})
.then(function(b){showOv('Confirmer livraison…',72);return sleep(350).then(function(){tap(b);return sleep(200);});})
.then(function(){showOv('Confirmation paiement…',85);return waitFor(function(){return findBtn(/payer|pay\b|zahlen|pagar|pagare|betalen|zap/i);},14000);})
.then(function(b){showOv('Finalisation…',95);return sleep(350).then(function(){tap(b);});})
.then(function(){hideOv(true,'✅ Checkout terminé !');})
.catch(function(e){hideOv(false,'❌ '+e.message);});
})();
"""


def inject_scripts(window):
    try:
        url = window.get_current_url() or ''
    except Exception:
        return
    if 'autocop.app' in url or 'autocop' in url.lower():
        try:
            window.evaluate_js(DETECTOR_JS)
        except Exception as e:
            print(f'[QC] Detector error: {e}')
    elif 'vinted.' in url:
        try:
            window.evaluate_js(CHECKOUT_JS)
        except Exception as e:
            print(f'[QC] Checkout error: {e}')


def main():
    window = webview.create_window(
        title='⚡ Quick Checkout',
        url='https://autocop.app',
        width=1440,
        height=900,
        min_size=(900, 600),
        confirm_close=False,
        background_color='#0a0a1a',
    )

    window.events.loaded += lambda: inject_scripts(window)

    webview.start(debug=False, private_mode=False)


if __name__ == '__main__':
    main()
