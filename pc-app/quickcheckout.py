#!/usr/bin/env python3
"""
Quick Checkout PC — autocop.app + Vinted autobuy
"""

import sys
import json
import os
import threading
import time

SETTINGS_FILE = os.path.join(os.path.expanduser('~'), '.quickcheckout.json')
_settings = {'domain': 'www.vinted.fr', 'autobuy': False, 'token': ''}
_window_ref = [None]  # mutable container for window reference


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            _settings.update(json.load(f))
    except Exception:
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(_settings, f, indent=2)
    except Exception:
        pass


def _show_error(title, msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        print(f'\n[ERREUR] {title}\n{msg}')
        input('Appuyez sur Entrée pour quitter...')


try:
    import webview
except ImportError:
    _show_error(
        'Quick Checkout — Module manquant',
        'pywebview n\'est pas installé.\n\nUtilisez run.bat ou lancez :\n    pip install pywebview'
    )
    sys.exit(1)


# ── OAuth fix: redirect window.open() to same-window navigation ──────────────
# Prevents login popups from opening in the default browser (DuckDuckGo, etc.)

OAUTH_FIX_JS = r"""
(function(){
if(window.__qcOAuthFixed)return;
window.__qcOAuthFixed=true;
var _open=window.open;
window.open=function(url,target,features){
  if(!url||url==='about:blank')return _open.apply(this,arguments);
  // Redirect all popups (OAuth, etc.) to the same window
  window.location.href=url;
  var fake={closed:false,location:{href:url},
    close:function(){window.history.back();},
    postMessage:function(){}};
  return fake;
};
// Prevent JS window.close() from closing the entire app
var _close=window.close;
window.close=function(){
  try{window.history.back();}catch(e){}
};
})();
"""

# ── Detector: injected on autocop.app ────────────────────────────────────────

DETECTOR_JS = r"""
(function(){
if(window.__qcPCLoaded)return;
window.__qcPCLoaded=true;

var cfg={domain:'www.vinted.fr',autobuy:false,token:''};
try{var s=localStorage.getItem('__qcCfg');if(s){var o=JSON.parse(s);for(var k in o)if(o.hasOwnProperty(k))cfg[k]=o[k];}}catch(e){}

if(!document.getElementById('qc-style')){
var st=document.createElement('style');st.id='qc-style';
st.textContent=
'.qc-bc{position:absolute;top:6px;right:6px;z-index:9999;display:flex;flex-direction:column;align-items:flex-end;gap:4px;pointer-events:none}'
+'.qc-cb{pointer-events:all;display:inline-flex;align-items:center;gap:5px;padding:5px 11px;background:linear-gradient(135deg,#6c63ff,#5546d4);color:#fff;border:none;border-radius:18px;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;box-shadow:0 2px 10px rgba(108,99,255,.45);transition:transform .1s,box-shadow .1s;white-space:nowrap;font-family:system-ui,sans-serif}'
+'.qc-cb:hover{transform:translateY(-1px) scale(1.04)}'
+'.qc-cb:disabled{opacity:.5;cursor:not-allowed;transform:none}'
+'.qc-sold{background:linear-gradient(135deg,#555,#333)!important;box-shadow:none!important}'
+'.qc-avail{background:linear-gradient(135deg,#2D6A4F,#1a4534)}'
+'.qc-fab{position:fixed;bottom:20px;right:20px;z-index:99998;width:46px;height:46px;border-radius:23px;background:linear-gradient(135deg,#6c63ff,#5546d4);color:#fff;border:none;cursor:pointer;font-size:22px;box-shadow:0 4px 16px rgba(108,99,255,.5);display:flex;align-items:center;justify-content:center}'
+'.qc-panel{position:fixed;bottom:76px;right:20px;z-index:99999;background:#1a1a2e;border-radius:16px;padding:20px;width:280px;color:#fff;font-family:system-ui,sans-serif;box-shadow:0 8px 32px rgba(0,0,0,.6);border:1px solid rgba(108,99,255,.3)}'
+'.qc-panel h4{margin:0 0 14px;font-size:14px;color:#a29bfe;text-transform:uppercase;font-weight:800}'
+'.qc-lbl{display:block;font-size:11px;color:#888;margin:10px 0 3px;font-weight:600}'
+'.qc-sel,.qc-inp{width:100%;padding:7px 10px;border-radius:8px;border:1px solid #2a2a4a;background:#0f0f23;color:#fff;font-size:12px;box-sizing:border-box}'
+'.qc-row{display:flex;align-items:center;gap:8px;margin-top:12px}'
+'.qc-sw{width:38px;height:21px;-webkit-appearance:none;appearance:none;background:#333;border-radius:11px;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0;border:none}'
+'.qc-sw:checked{background:#6c63ff}'
+'.qc-sw::before{content:"";position:absolute;width:17px;height:17px;border-radius:50%;background:#fff;top:2px;left:2px;transition:left .2s}'
+'.qc-sw:checked::before{left:19px}'
+'.qc-divider{border:none;border-top:1px solid rgba(255,255,255,.08);margin:14px 0 10px}'
+'.qc-nav-btn{width:100%;padding:9px;border-radius:10px;border:none;font-size:12px;font-weight:700;cursor:pointer;margin-top:6px}'
+'.qc-save-btn{background:#6c63ff;color:#fff}'
+'.qc-vinted-btn{background:#2D6A4F;color:#fff}'
+'.qc-autocop-btn{background:rgba(108,99,255,.2);color:#a29bfe}'
+'.qc-close{position:absolute;top:12px;right:14px;background:none;border:none;color:#666;cursor:pointer;font-size:16px}'
+'.qc-tok-ok{margin-top:4px;padding:3px 8px;border-radius:6px;font-size:10px;background:rgba(34,197,94,.15);color:#22c55e;border:1px solid rgba(34,197,94,.3);display:none}'
+'.qc-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:999999;padding:10px 22px;border-radius:20px;font-family:system-ui,sans-serif;font-size:13px;font-weight:700;color:#fff;pointer-events:none;transition:opacity .3s;white-space:nowrap}';
document.head.appendChild(st);
}

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
  return r.json().then(function(d){
    var item=d.item||d.data;if(!item)return null;
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

// Reload cfg from localStorage (called after saving token from Python)
function reloadCfg(){
try{var s=localStorage.getItem('__qcCfg');if(s){var o=JSON.parse(s);for(var k in o)if(o.hasOwnProperty(k))cfg[k]=o[k];}}catch(e){}
}

function showPanel(){
var old=document.getElementById('qc-panel');if(old){old.remove();return;}
reloadCfg();
var hasToken=cfg.token&&cfg.token.length>4;
var p=document.createElement('div');p.id='qc-panel';p.className='qc-panel';
p.innerHTML='<button class="qc-close" id="qc-close">✕</button>'
+'<h4>⚡ Quick Checkout</h4>'
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
+'<label class="qc-lbl">Token Bearer</label>'
+'<input type="password" class="qc-inp" id="qc-tok" placeholder="Ou connectez-vous à Vinted ci-dessous...">'
+'<div class="qc-tok-ok" id="qc-tok-status" style="display:'+(hasToken?'block':'none')+'">✅ Token enregistré</div>'
+'<button class="qc-nav-btn qc-save-btn" id="qc-sv">💾 Sauvegarder</button>'
+'<hr class="qc-divider">'
+'<button class="qc-nav-btn qc-vinted-btn" id="qc-vinted-login">🔑 Se connecter à Vinted</button>'
+'<button class="qc-nav-btn qc-autocop-btn" id="qc-back-autocop" style="margin-top:4px">⬅ Retour autocop.app</button>';
document.body.appendChild(p);
document.getElementById('qc-dom').value=cfg.domain;
document.getElementById('qc-ab').checked=cfg.autobuy;
document.getElementById('qc-tok').value=cfg.token||'';
document.getElementById('qc-close').addEventListener('click',function(){p.remove();});
document.getElementById('qc-sv').addEventListener('click',function(){
  cfg.domain=document.getElementById('qc-dom').value;
  cfg.autobuy=document.getElementById('qc-ab').checked;
  var tok=document.getElementById('qc-tok').value.trim();
  if(tok)cfg.token=tok;
  try{localStorage.setItem('__qcCfg',JSON.stringify(cfg));}catch(e){}
  toast('✅ Sauvegardé !','rgba(34,197,94,.9)');p.remove();
});
document.getElementById('qc-vinted-login').addEventListener('click',function(){
  p.remove();
  window.location.href='https://'+cfg.domain+'/login';
});
document.getElementById('qc-back-autocop').addEventListener('click',function(){
  p.remove();window.location.href='https://autocop.app';
});
}

function showFAB(){
if(document.getElementById('qc-fab'))return;
var fab=document.createElement('button');
fab.id='qc-fab';fab.className='qc-fab';fab.title='Quick Checkout';
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

var params=new URLSearchParams(location.search);
var autobuy=params.get('_qc_ab')==='1';
var ts=parseInt(params.get('_qc_ts')||'0',10);
var fresh=ts>0&&(Date.now()-ts<90000);

if(!document.getElementById('qc-chk-style')){
var s=document.createElement('style');s.id='qc-chk-style';
s.textContent=
'.qc-ov{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.78);z-index:999999;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif}'
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
vt.textContent=autobuy?'⚡ QC: lien expiré — relancez depuis autocop':'⚡ Quick Checkout prêt — cliquez Acheter';
document.body.appendChild(vt);setTimeout(function(){vt.remove();},4000);
return;
}

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
  function tick(){
    var el=fn();
    if(el)return res(el);
    if(Date.now()>t)return rej(new Error('Timeout (bouton non trouvé)'));
    requestAnimationFrame(tick);
  }
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
// Also search by data-testid for robustness
var els=document.querySelectorAll('button,[role="button"],input[type="submit"],[data-testid*="buy"],[data-testid*="checkout"]');
for(var i=0;i<els.length;i++){
  var el=els[i];
  var txt=(el.textContent||el.value||el.getAttribute('aria-label')||'').trim();
  if(re.test(txt)&&el.offsetParent!==null&&!el.disabled)return el;
}
return null;
}

function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}

// Autobuy flow: Acheter → Livraison → Payer
showOv('Recherche bouton Acheter…',8);
waitFor(function(){
  return findBtn(/^(acheter|buy now|buy|kaufen|comprar|acquista|kopen|kup|acheter maintenant)/i);
},10000)
.then(function(b){showOv('Clic Acheter…',28);return sleep(400).then(function(){tap(b);return sleep(300);});})
.then(function(){
  showOv('Sélection livraison…',50);
  return waitFor(function(){
    return findBtn(/(continuer|continue|suivant|next|weiter|siguiente|avanti|volgende|dalej|continuar|choisir)/i);
  },15000);
})
.then(function(b){showOv('Confirmer livraison…',72);return sleep(450).then(function(){tap(b);return sleep(300);});})
.then(function(){
  showOv('Confirmation paiement…',85);
  return waitFor(function(){
    return findBtn(/(payer|pay now|pay|zahlen|pagar|pagare|betalen|zapłać|pagar|confirmer|confirm)/i);
  },15000);
})
.then(function(b){showOv('Finalisation…',95);return sleep(400).then(function(){tap(b);});})
.then(function(){hideOv(true,'✅ Checkout terminé !');})
.catch(function(e){hideOv(false,'❌ '+e.message);});
})();
"""

# ── Vinted login page: auto-detect token notification ────────────────────────

VINTED_LOGIN_JS = r"""
(function(){
if(window.__qcLoginLoaded)return;
window.__qcLoginLoaded=true;
if(!document.getElementById('qc-login-style')){
var s=document.createElement('style');s.id='qc-login-style';
s.textContent='.qc-vt{position:fixed;top:0;left:0;right:0;z-index:99999;padding:12px 20px;font-family:system-ui;font-size:13px;font-weight:700;color:#fff;text-align:center;background:rgba(108,99,255,.95)}';
document.head.appendChild(s);
}
var bar=document.createElement('div');bar.className='qc-vt';
bar.textContent='⚡ Quick Checkout — Connectez-vous à Vinted, le token sera détecté automatiquement';
document.body.prepend(bar);
})();
"""


def try_extract_token(window):
    """Extract Vinted access_token_web from cookies (runs in background thread)."""
    def _extract():
        time.sleep(2)  # wait for cookies to be set after page load
        try:
            cookies = window.get_cookies()
            for c in cookies:
                # pywebview cookies can be dicts or cookie objects
                if isinstance(c, dict):
                    name = c.get('name', '')
                    value = c.get('value', '')
                else:
                    name = getattr(c, 'name', getattr(c, '_name', ''))
                    value = getattr(c, 'value', getattr(c, '_value', ''))

                if name == 'access_token_web' and value and len(value) > 10:
                    if _settings.get('token') != value:
                        _settings['token'] = value
                        save_settings()
                        # Push token into localStorage so detector can use it
                        cfg_json = json.dumps({
                            'domain': _settings['domain'],
                            'autobuy': _settings['autobuy'],
                            'token': value,
                        })
                        window.evaluate_js(
                            "localStorage.setItem('__qcCfg'," + json.dumps(cfg_json) + ");"
                            "var _t=document.createElement('div');"
                            "_t.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999999;padding:14px;background:rgba(34,197,94,.95);color:#fff;font-family:system-ui;font-size:14px;font-weight:700;text-align:center';"
                            "_t.textContent='✅ Token Vinted détecté et enregistré ! Retournez sur autocop.app ⚡';"
                            "document.body.prepend(_t);"
                            "setTimeout(function(){_t.remove();},5000);"
                        )
                    break
        except Exception:
            pass

    threading.Thread(target=_extract, daemon=True).start()


def inject_scripts(window):
    try:
        url = window.get_current_url() or ''
    except Exception:
        return

    # Always patch window.open so OAuth stays inside the app
    try:
        window.evaluate_js(OAUTH_FIX_JS)
    except Exception:
        pass

    if 'autocop.app' in url or url.endswith('autocop.app') or '/autocop' in url:
        try:
            window.evaluate_js(DETECTOR_JS)
        except Exception as e:
            print(f'[QC] Detector error: {e}')

    elif 'vinted.' in url:
        # If coming from CHECKOUT (autobuy params in URL), inject checkout flow
        if '_qc_ab=1' in url:
            try:
                window.evaluate_js(CHECKOUT_JS)
            except Exception as e:
                print(f'[QC] Checkout error: {e}')

        # Check if this is a login page — show helper banner
        if '/login' in url or '/register' in url:
            try:
                window.evaluate_js(VINTED_LOGIN_JS)
            except Exception:
                pass

        # Always try to extract token after any Vinted page loads
        try_extract_token(window)


def main():
    load_settings()

    try:
        window = webview.create_window(
            title='⚡ Quick Checkout',
            url='https://autocop.app',
            width=1440,
            height=900,
            min_size=(900, 600),
            confirm_close=False,
            background_color='#0a0a1a',
        )
        _window_ref[0] = window

        def on_loaded():
            inject_scripts(window)

        try:
            window.events.loaded += on_loaded
        except AttributeError:
            pass

        def on_start(w):
            try:
                w.events.loaded += on_loaded
            except AttributeError:
                pass

        webview.start(on_start, window, debug=False, private_mode=False)

    except Exception as e:
        _show_error(
            'Quick Checkout — Erreur de démarrage',
            f'L\'application n\'a pas pu démarrer :\n\n{e}\n\n'
            'Essayez :\n  pip install --upgrade pywebview\n\n'
            'Vérifiez que Microsoft Edge est installé (Windows 10/11).'
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
