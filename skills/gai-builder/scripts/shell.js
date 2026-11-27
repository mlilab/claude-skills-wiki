// Measurement harness. Store this text in localStorage as gai_shell (with gai_layer and gai_adapter), open a light
// real page of the site (not a 404 page: its CSP may forbid frames), then run eval(localStorage.getItem('gai_shell')). It shows the real site in a
// same-origin frame, puts the layer on every page the frame loads, keeps key presses going to the frame, and logs
// commands, clicks and scrolls to localStorage.gai_log. Start page: localStorage.gai_start (default "/").
document.documentElement.innerHTML = '<head><title>GAI</title></head><body style="margin:0;overflow:hidden"><iframe id="gai-frame" style="border:0;width:100vw;height:100vh;display:block"></iframe></body>';
var f = document.getElementById('gai-frame');
function inner() { try { return f.contentWindow.document ? f.contentWindow : null; } catch (e) { return null; } }
f.addEventListener('load', function () { try {
  var w = f.contentWindow; window.__gaiLog = window.__gaiLog || [];
  var L = function (t) { window.__gaiLog.push(Date.now() + ' ' + t); try { localStorage.setItem('gai_log', JSON.stringify(window.__gaiLog)); } catch (e) {} };
  L('load ' + w.location.pathname);
  w.document.addEventListener('submit', function (e) { if (e.target.id === 'gai-form') L('cmd ' + w.document.getElementById('gai-cmd').value); }, true);
  w.document.addEventListener('pointerdown', function (e) { if (e.isTrusted) L('click ' + e.clientX + ',' + e.clientY + ' ' + (e.target.id || e.target.tagName)); }, true);
  w.addEventListener('wheel', function () { L('wheel'); }, { capture: true, passive: true });
  w.eval(localStorage.getItem('gai_layer') + '\n' + localStorage.getItem('gai_adapter') + '\nGAI_LAYER(GAI_ADAPTER());');
  document.title = 'GAI | ' + w.document.title; f.focus(); w.focus();
} catch (e) { console.log('[GAI shell]', String(e)); } });
setInterval(function () { var w = inner(); if (w && !w.document.hasFocus()) { f.focus(); w.focus(); } }, 150);
document.addEventListener('keydown', function (e) { var w = inner(), c = w && w.document.getElementById('gai-cmd'); if (!c) return; e.preventDefault(); w.focus(); c.focus(); if (e.key === 'Enter') w.document.getElementById('gai-form').requestSubmit(); else if (e.key === 'Backspace') c.value = c.value.slice(0, -1); else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) c.value += e.key; }, true);
f.src = localStorage.getItem('gai_start') || '/';
