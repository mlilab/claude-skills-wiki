function GAI_LAYER(A) {
  if (window.__gai) return; window.__gai = 1;
  A = Object.assign({ css: '', gates: [], resolve: [], commands: [], search: null, skip: '', home: '/', pager: '.pagination,.paging,[class*=pagination],[class*=paging]', toc: 'h1,h2,h3,.gai-sec', stopTimers: false, state: null, onPage: null }, A || {});
  const d = document, W = window;
  const q = (s, r) => { try { return [...(r || d).querySelectorAll(s)]; } catch (e) { return []; } };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const own = el => !!(el.closest && el.closest('#gai-bar,#gai-marks'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (!el.checkVisibility || el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })); };
  const OPS = 'a[href],button,input:not([type=hidden]),select:not(.gai-select),textarea,summary,[role=button],[role=link],[role=tab],[onclick]';
  const near = el => { let p = el.parentElement; for (let i = 0; i < 3 && p; i++, p = p.parentElement) { const t = txt(p); if (t) return t.length <= 40 ? t : ''; } return ''; };
  const name = el => String(el.getAttribute('aria-label') || txt(el) || q('img[alt]', el).map(i => i.alt).join(' ').trim() || el.getAttribute('title') || el.getAttribute('placeholder') || near(el) ||
    (/^(submit|button)$/.test(el.type) && el.value) || (el.getAttribute('href') || '').replace(/^javascript:.*/, '').split(/[?#]/)[0].split('/').filter(Boolean).pop() ||
    ((q('img', el)[0] && q('img', el)[0].getAttribute('src')) || '').split('/').pop().replace(/\.\w+$/, '') || el.name || el.id || el.className || el.tagName).trim().slice(0, 60);
  let lastUser = Date.now() - 9e3, timer = 0;
  ['pointerdown', 'keydown'].forEach(t => d.addEventListener(t, e => { if (e.isTrusted && !own(e.target)) lastUser = Date.now(); }, true));

  const st = d.createElement('style'); st.id = 'gai-style';
  st.textContent = '*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}' +
    'body{padding-bottom:104px!important}.gai-hidden{display:none!important}.gai-cf::after{content:"";display:table;clear:both}::highlight(gai-find){background:#FFE100;color:#000}.gai-select{position:absolute!important;opacity:0!important;pointer-events:none!important;width:1px!important;height:1px!important}' +
    '#gai-bar{position:fixed;left:0;right:0;bottom:0;z-index:2147483646;background:#14181F;color:#fff;font:15px/1.3 system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;padding:6px 10px;box-sizing:border-box;text-align:left}' +
    '#gai-bar *{box-sizing:border-box;font-family:inherit}#gai-form{display:flex;gap:8px;align-items:center;margin:0}#gai-form b{font-size:16px}' +
    '#gai-cmd{flex:0 0 340px;height:38px;font-size:18px;padding:0 10px;border:2px solid #fff;border-radius:8px;background:#fff;color:#111}' +
    '#gai-form button{height:38px;padding:0 14px;border:0;border-radius:8px;background:#D7263D;color:#fff;font-weight:700;font-size:15px;cursor:pointer}' +
    '#gai-status{flex:1;min-width:0;font-weight:700;line-height:19px;max-height:38px;overflow:hidden}#gai-url{flex:0 1 auto;max-width:46%;color:#B8C1CC;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
    '#gai-pin{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin-top:5px;min-height:28px;max-height:62px;overflow:hidden;font-size:13px;color:#B8C1CC}' +
    '.gai-opts{display:flex;flex-wrap:wrap;gap:4px 26px;margin:4px 0 4px 24px;position:relative;z-index:1}#gai-pin{gap:4px 26px;padding-left:4px}#gai-pin .gai-opt{margin-left:22px}' +
    '.gai-opt{font:600 14px/1.2 system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;min-height:28px;padding:3px 10px;border:1.5px solid #14181F;border-radius:999px;background:#fff;color:#14181F;cursor:pointer}' +
    '.gai-opt[aria-pressed="true"]{background:#14181F;color:#fff}#gai-pin .gai-opt{border-color:#fff}#gai-pin .gai-opt[aria-pressed="true"]{background:#D7263D;border-color:#D7263D}' +
    '#gai-marks{position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none}' +
    '.gai-m{position:fixed;background:#D7263D;color:#fff;font:700 12px/15px system-ui,sans-serif;padding:0 3px;border-radius:3px;white-space:nowrap;box-shadow:0 0 0 1px #fff}' + A.css;
  d.documentElement.appendChild(st);
  const bar = d.createElement('div'); bar.id = 'gai-bar';
  bar.innerHTML = '<form id="gai-form"><b>GAI</b><input id="gai-cmd" autocomplete="off" spellcheck="false" placeholder="번호, 찾을 글자, q 검색어, ?"><button type="submit">실행</button><span id="gai-status" role="status"></span><span id="gai-url"></span></form><div id="gai-pin"></div>';
  const marks = d.createElement('div'); marks.id = 'gai-marks';
  d.body.appendChild(bar); d.body.appendChild(marks);
  const cmd = bar.querySelector('#gai-cmd'), status = bar.querySelector('#gai-status'), pin = bar.querySelector('#gai-pin');
  const say = (t, keepIt) => { status.textContent = t; if (keepIt) { try { sessionStorage.setItem('gai_last', Date.now() + '|' + t); } catch (e) {} } };
  const HELP = '번호: 그 요소 누르기 | 번호 글자: 그 입력칸에 넣고 제출 | 글자: 이 화면에서 찾기 (단추가 없으면 본문 글자, /글자 는 본문만) | q 글자: 사이트 검색 | n p t e: 화면 넘김 | b 뒤로 | h 홈 | popups: 숨긴 팝업';

  const ids = new WeakMap(), byN = new Map(); let seq = 0;
  const idOf = el => { if (!ids.has(el)) { ids.set(el, ++seq); byN.set(seq, el); } return ids.get(el); };
  const gateOf = el => { for (const g of A.gates) if (el.matches(g.sel)) return g.label; return /\/(login|signin)/i.test(el.getAttribute('href') || '') ? '로그인' : ''; };
  const dead = el => el.tagName === 'A' && /^(#|javascript:\s*(void\(0\))?;?\s*)$/i.test(el.getAttribute('href') || '') && !el.getAttribute('onclick');
  let soft = [];
  const targets = () => q(OPS + ',.gai-opt').concat(soft).filter(el => (!own(el) || el.classList.contains('gai-opt')) && vis(el) && !(A.skip && el.matches(A.skip)) && !(dead(el) && el.querySelector(OPS + ',[onclick]')));
  const anchor = el => { const tw = d.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n; while ((n = tw.nextNode())) { if (!n.nodeValue.trim()) continue; const rg = d.createRange(); rg.selectNodeContents(n); for (const c of rg.getClientRects()) if (c.width > 0 && c.height > 0) return c; } return null; };
  const dest = el => { const h = el.getAttribute('href') || '', m = (el.getAttribute('onclick') || '').match(/location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/); return m ? m[1] : (/^(#|javascript:|$)/i.test(h) ? '' : h); };
  const boxId = (() => { const m = new WeakMap(); let n = 0; return el => m.get(el) || (m.set(el, ++n), n); })();
  function draw() {
    const H = W.innerHeight - bar.offsetHeight, placed = [], seen = {}, frag = d.createDocumentFragment();
    const hit = (x, y, w) => placed.some(p => x < p[0] + p[2] && x + w > p[0] && y < p[1] + 15 && y + 15 > p[1]);
    targets().forEach(el => {
      const r = el.getBoundingClientRect(), inBar = own(el), field = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName);
      if (!inBar && (r.bottom < 2 || r.top > H - 4 || r.right < 0 || r.left > W.innerWidth)) return;
      if (!inBar) { const t = d.elementFromPoint(Math.min(W.innerWidth - 1, Math.max(0, r.left + r.width / 2)), Math.max(0, Math.min(H - 1, r.top + r.height / 2))), lb = t && t.closest('label'); if (t && !own(t) && !el.contains(t) && !t.contains(el) && !(lb && (lb.control === el || lb.contains(el)))) return; }
      const g = gateOf(el), bare = !txt(el) && !field, to = dest(el);
      if (bare && to && !el.getAttribute('title') && !el.getAttribute('aria-label')) {
        const box = (el.parentElement && el.parentElement.parentElement) || el.parentElement || d.body, k = to + '|' + boxId(box);
        if (seen[k] || q('a[href]', box).some(o => o !== el && txt(o) && dest(o) === to)) return; seen[k] = 1;
      }
      const m = d.createElement('span'); m.className = 'gai-m'; m.textContent = idOf(el) + (g ? ' ' + g : '') + (bare ? ' ' + name(el).slice(0, 14) : '');
      const w = [...m.textContent].reduce((n, c) => n + (c > '\u2e80' ? 12 : 7), 8), a = (!field && !bare && anchor(el)) || r;
      let x = Math.round(a === r ? (bare ? r.left + 2 : r.left - w - 1) : a.left - w - 1), y = Math.round(a === r ? r.top + Math.min(6, Math.max(0, (r.height - 15) / 2)) : a.top + (Math.min(a.height, 24) - 15) / 2);
      if (field && /^(radio|checkbox)$/.test(el.type)) { x = Math.round(r.left - 2); y = Math.round(r.top - 14); }
      if (!inBar && !bare && a !== r && x < r.left - 2) { const bad = px => { const t = d.elementFromPoint(Math.max(0, px), Math.max(0, Math.min(H - 1, y + 7))); return t && !own(t) && t !== el && !t.contains(el) && !el.contains(t) && txt(t); }; if (bad(x + 2) || bad(x + w / 2)) { x = Math.round(r.left); y = Math.round(r.top - 14); } }
      if (!inBar) y = Math.max(0, Math.min(y, H - 16));
      if (x < 0) x = Math.max(0, Math.round(a.left));
      x = Math.max(0, Math.min(x, d.documentElement.clientWidth - w - 2));
      for (let i = 0; i < 6 && hit(x, y, w); i++) { if (i % 2 === 0 && !hit(x, y + 16, w)) y += 16; else if (!hit(x, y - 16, w)) y -= 16; else x += w + 2; }
      placed.push([x, y, w]); m.style.left = x + 'px'; m.style.top = y + 'px'; frag.appendChild(m);
    });
    marks.textContent = ''; marks.appendChild(frag);
    const st = stNow;
    bar.querySelector('#gai-url').textContent = (st ? '선택: ' + st + ' | ' : '') + decodeURIComponent(location.pathname + location.search + location.hash).slice(0, 90);
  }

  const hidden = [], opened = new WeakSet();
  function unblock() {
    const byUser = Date.now() - lastUser < 1500, area = W.innerWidth * W.innerHeight;
    q('[role=dialog],[aria-modal],dialog,[class*=modal],[class*=popup],[class*=Popup],[class*=layer],[class*=dimm],[class*=backdrop],[class*=overlay],[id*=modal],[id*=popup],[id*=Pop]').forEach(el => {
      if (own(el) || opened.has(el) || !vis(el)) return;
      const s = getComputedStyle(el), r = el.getBoundingClientRect();
      if ((s.position !== 'fixed' && s.position !== 'absolute') || r.width * r.height < area * 0.12) return;
      if (byUser) return void opened.add(el);
      el.classList.add('gai-hidden'); hidden.push(el);
    });
    if (hidden.length) { d.body.classList.remove('modal-open'); d.body.style.setProperty('overflow', 'auto', 'important'); d.documentElement.style.setProperty('overflow', 'auto', 'important'); }
  }
  function options() {
    q('select').forEach(sel => {
      const sig = [...sel.options].map(o => o.text).join('|');
      if (sel.__gaiBox) { sel.__gaiBox.classList.toggle('gai-hidden', getComputedStyle(sel).display === 'none'); q('.gai-opt', sel.__gaiBox).forEach((x, j) => x.setAttribute('aria-pressed', j === sel.selectedIndex)); }
      if (own(sel) || sel.options.length < 2 || sel.options.length > 60 || sel.__gaiSig === sig || (!sel.__gaiSig && !vis(sel))) return;
      if (sel.__gaiBox) sel.__gaiBox.remove();
      const box = d.createElement('div'); box.className = 'gai-opts'; sel.__gaiSig = sig; sel.__gaiBox = box;
      [...sel.options].forEach((o, i) => {
        const b = d.createElement('button'); b.type = 'button'; b.className = 'gai-opt'; b.textContent = txt(o) || o.value || '(빈 값)'; b.setAttribute('aria-pressed', i === sel.selectedIndex);
        b.addEventListener('click', () => { lastUser = Date.now(); sel.selectedIndex = i; ['input', 'change'].forEach(t => sel.dispatchEvent(new Event(t, { bubbles: true })));
          q('.gai-opt', box).forEach((x, j) => x.setAttribute('aria-pressed', j === i)); say('‘' + b.textContent + '’을 골랐습니다.'); });
        box.appendChild(b);
      });
      sel.insertAdjacentElement('afterend', box); sel.classList.add('gai-select');
      if (sel.options.length > 4) for (let p = box.parentElement, i = 0; p && i < 3 && p !== d.body; p = p.parentElement, i++) { const pw = p.getBoundingClientRect().width, ow = p.parentElement ? p.parentElement.getBoundingClientRect().width : 0; if (pw < 420 && ow > pw * 1.4) { [['width', '100%'], ['max-width', 'none'], ['float', 'none'], ['flex', '1 1 100%']].forEach(x => p.style.setProperty(x[0], x[1], 'important')); break; } }
      for (let p = box.parentElement, i = 0; p && i < 6 && p !== d.body; p = p.parentElement, i++) { const cs = getComputedStyle(p); if (p.scrollHeight > p.clientHeight + 4 && cs.overflowY === 'visible') { p.style.setProperty('height', 'auto', 'important'); if (cs.display === 'block') p.classList.add('gai-cf'); } }
    });
  }
  function links() {
    q('a[target]').forEach(a => a.removeAttribute('target'));
    if (A.resolve.length) q('a,[onclick]').forEach(el => {
      const code = (el.getAttribute('href') || '') + ' ' + (el.getAttribute('onclick') || '');
      if (el.__gaiR || !/javascript:|\(/.test(code)) return; el.__gaiR = 1;
      for (const [re, to] of A.resolve) { const m = code.match(re); if (m) { const u = to.replace(/\$(\d)/g, (_, i) => encodeURIComponent(m[i])); if (el.tagName === 'A') el.setAttribute('href', u); el.setAttribute('data-gai-href', u); break; } }
    });
  }
  let pinSig = '', stNow = '';
  function pins() {
    const pg = q(A.pager).filter(p => !own(p) && vis(p) && q('a,button', p).length > 1)[0], items = pg ? q('a,button', pg).filter(vis).slice(0, 16) : [];
    const heads = d.documentElement.scrollHeight > W.innerHeight * 2.5 ? q(A.toc).filter(h => !own(h) && vis(h) && txt(h)).slice(0, 14) : [];
    const sig = hidden.length + '/' + (hidden[0] ? hidden[0].classList.contains('gai-hidden') : '') + '/' + items.map(a => txt(a) + (a.closest('.active,.on,.current,[aria-current]') ? '*' : '')).join(',') + '/' + heads.map(h => txt(h) + (h.getAttribute('data-gai-n') || '')).join(',');
    if (sig === pinSig) return; pinSig = sig;
    pin.textContent = '';
    const add = (label, pressed, fn) => { const b = d.createElement('button'); b.type = 'button'; b.className = 'gai-opt'; b.textContent = label; if (pressed != null) b.setAttribute('aria-pressed', pressed); b.addEventListener('click', fn); pin.appendChild(b); };
    if (hidden.length) add('숨긴 팝업 ' + hidden.length + '개 ' + (hidden[0].classList.contains('gai-hidden') ? '보기' : '숨기기'), null, () => run('popups'));
    if (pg) { pin.appendChild(d.createTextNode('쪽')); items.forEach(a => add(txt(a) || name(a), !!a.closest('.active,.on,.current,[aria-current]'), () => { lastUser = Date.now(); a.click(); say('쪽 ‘' + (txt(a) || name(a)) + '’을 눌렀습니다.'); })); }
    if (heads.length > 2) { pin.appendChild(d.createTextNode('목차')); heads.forEach(h => add(txt(h).slice(0, 16) + (h.getAttribute('data-gai-n') ? ' (' + h.getAttribute('data-gai-n') + ')' : ''), null, () => { lastUser = Date.now(); h.scrollIntoView({ block: 'start' }); W.scrollBy(0, -70); draw(); say('‘' + txt(h).slice(0, 30) + '’ 위치로 갔습니다.'); })); }
  }
  function quiet() {
    q('[class*=swiper]').forEach(el => { try { el.swiper && el.swiper.autoplay && el.swiper.autoplay.stop(); } catch (e) {} });
    try { W.jQuery && W.jQuery('.slick-slider').slick('slickPause'); } catch (e) {}
    if (A.stopTimers) { const top = setTimeout(() => {}, 0); for (let i = 1; i <= top; i++) clearInterval(i); }
  }
  function lift() { const bh = bar.offsetHeight; q('body *').forEach(el => { if (own(el) || el.__gaiLift) return; const s = getComputedStyle(el), b = parseFloat(s.bottom); if (s.position !== 'fixed' || s.display === 'none' || !(b >= 0 && b < bh) || el.getBoundingClientRect().height > W.innerHeight * 0.6) return; el.__gaiLift = 1; el.style.setProperty('bottom', (b + bh) + 'px', 'important'); }); }
  function refresh() { unblock(); options(); links(); if (A.onPage) { try { A.onPage(api); } catch (e) {} } pins(); try { soft = q('div,span,li,td,p,img,i,em,strong,dd,dt').filter(el => !own(el) && !el.matches(OPS) && getComputedStyle(el).cursor === 'pointer' && !(el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer') && !el.closest('a[href],button,label,[onclick]') && !el.querySelector(OPS)); } catch (e) {} try { stNow = [A.state ? A.state(api) : ''].concat(q('select.gai-select').filter(s => s.selectedIndex > 0).map(s => txt(s.options[s.selectedIndex]))).filter(Boolean).join(', '); } catch (e) {} draw(); keep(); }

  function activate(n) {
    const el = byN.get(n); if (!el || !d.contains(el) || !vis(el)) return say(n + '번은 지금 이 화면에 없습니다. 화면의 빨간 번호를 다시 확인하세요.');
    lastUser = Date.now(); if (!own(el)) el.scrollIntoView({ block: 'center' });
    if (/^(INPUT|TEXTAREA)$/.test(el.tagName) && !/^(checkbox|radio|button|submit|image)$/.test(el.type)) return say(n + '번은 입력칸입니다. ‘' + n + ' 넣을글자’처럼 입력하면 넣고 제출합니다.');
    say(n + '번을 눌렀습니다: ' + name(el).slice(0, 40), 1); el.click();
  }
  function fill(n, t) {
    const el = byN.get(n); if (!el || !d.contains(el) || !/^(INPUT|TEXTAREA)$/.test(el.tagName)) return say(n + '번은 입력칸이 아닙니다.');
    lastUser = Date.now();
    Object.getOwnPropertyDescriptor(el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype, 'value').set.call(el, t);
    ['input', 'change'].forEach(k => el.dispatchEvent(new Event(k, { bubbles: true })));
    say(n + '번에 ‘' + t + '’를 넣고 Enter를 보냈습니다.', 1);
    ['keydown', 'keypress', 'keyup'].forEach(k => el.dispatchEvent(new KeyboardEvent(k, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true })));
    if (el.form && el.form.getAttribute('action')) setTimeout(() => { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); }, 300);
  }
  let tf = { k: '', i: -1 };
  function textFind(t) {
    const k = t.toLowerCase(), hits = [], tw = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT); let n;
    while ((n = tw.nextNode())) { const p = n.parentElement; if (!p || own(p) || /^(SCRIPT|STYLE|NOSCRIPT)$/.test(p.tagName)) continue; const i = n.nodeValue.toLowerCase().indexOf(k); if (i >= 0 && vis(p)) hits.push([n, i]); }
    if (!hits.length) return false;
    tf = { k, i: tf.k === k ? (tf.i + 1) % hits.length : 0 };
    const node = hits[tf.i][0], at = hits[tf.i][1], rg = d.createRange(); rg.setStart(node, at); rg.setEnd(node, at + k.length);
    node.parentElement.scrollIntoView({ block: 'center' });
    try { CSS.highlights.set('gai-find', new Highlight(rg)); } catch (e) {}
    draw(); say('글자 ‘' + t + '’ ' + hits.length + '곳 중 ' + (tf.i + 1) + '번째: ' + txt(node.parentElement).slice(0, 70) + (hits.length > 1 ? ' | 같은 글자를 다시 치면 다음 곳' : ''));
    return true;
  }
  function find(t) {
    const k = t.toLowerCase().replace(/\s+/g, ''), hits = targets().filter(el => name(el).toLowerCase().replace(/\s+/g, '').includes(k));
    if (!hits.length) return textFind(t) || say('‘' + t + '’가 이 화면에 없습니다. q ' + t + ' 로 사이트 검색을 해 보세요.');
    if (!own(hits[0])) hits[0].scrollIntoView({ block: 'center' }); draw();
    say('‘' + t + '’ ' + hits.length + '개: ' + hits.slice(0, 8).map(el => idOf(el) + ' ' + name(el).slice(0, 18)).join(' | '));
  }
  function run(s) {
    s = String(s || '').trim(); let m; const page = W.innerHeight - bar.offsetHeight - 60;
    const where = () => say('화면 위치 ' + Math.round(W.scrollY) + ' / ' + Math.max(0, d.documentElement.scrollHeight - W.innerHeight));
    if (!s) return say('명령이 비어 있습니다. ' + HELP);
    if ((m = s.match(/^(\d+)$/))) return activate(+m[1]);
    if ((m = s.match(/^(\d+)\s+(.+)$/))) return fill(+m[1], m[2]);
    if (s === '?') return say(HELP);
    if ((m = s.match(/^\/(.+)$/))) return textFind(m[1]) || say('글자 ‘' + m[1] + '’가 이 화면에 없습니다.');
    if (s === 'b') return history.back();
    if (s === 'h') return void (location.href = A.home);
    if (/^[npte]$/.test(s)) { s === 'n' ? W.scrollBy(0, page) : s === 'p' ? W.scrollBy(0, -page) : W.scrollTo(0, s === 't' ? 0 : d.documentElement.scrollHeight); draw(); return where(); }
    if (s === 'popups') { const show = hidden[0] && hidden[0].classList.contains('gai-hidden'); hidden.forEach(el => el.classList.toggle('gai-hidden', !show)); lastUser = Date.now(); pins(); draw(); return say(hidden.length ? '팝업 ' + hidden.length + '개를 ' + (show ? '다시 보였습니다.' : '숨겼습니다.') : '숨긴 팝업이 없습니다.'); }
    for (const [re, fn] of A.commands) if ((m = s.match(re))) return fn(m, api);
    if ((m = s.match(/^q\s+(.+)$/))) {
      if (A.search) { say('‘' + m[1] + '’ 사이트 검색을 열었습니다.', 1); return void (location.href = A.search.replace('{q}', encodeURIComponent(m[1]))); }
      const box = q('input[type=search],input[name*=search i],input[id*=search i],input[placeholder*="검색"],input[placeholder*=search i]').filter(vis)[0];
      return box ? fill(idOf(box), m[1]) : say('이 화면에서 검색창을 찾지 못했습니다.');
    }
    return find(s);
  }
  const api = { q, txt, vis, say, run, idOf, name, adapter: A };
  bar.querySelector('#gai-form').addEventListener('submit', e => { e.preventDefault(); const v = cmd.value; cmd.value = ''; run(v); setTimeout(() => { refresh(); cmd.focus(); }, 350); });
  d.addEventListener('keydown', e => { if (e.key === 'Escape') cmd.focus(); }, true);
  let auto = 0; cmd.addEventListener('input', () => { clearTimeout(auto); const ok = () => /^(\d+|[npte])$/.test(cmd.value.trim()); if (ok()) auto = setTimeout(() => { if (ok()) bar.querySelector('#gai-form').requestSubmit(); }, 700); });
  const keep = () => setTimeout(() => { const a = d.activeElement; if (!a || a === d.body || a === d.documentElement) cmd.focus({ preventScroll: true }); }, 0);
  d.addEventListener('focusout', keep, true); W.addEventListener('focus', keep);
  let raf = 0; const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
  W.addEventListener('scroll', redraw, true); W.addEventListener('resize', redraw);
  new MutationObserver(recs => { if (recs.every(r => own(r.target) || (r.target.classList && r.target.classList.contains('gai-opts')))) return; clearTimeout(timer); timer = setTimeout(refresh, 250); }).observe(d.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'hidden'] });
  W.GAI = { run, state: () => ({ url: location.href, title: d.title, marks: q('.gai-m', marks).length, hiddenPopups: hidden.length, status: status.textContent }), marks: () => targets().map(el => ({ n: idOf(el), name: name(el), tag: el.tagName.toLowerCase(), href: el.getAttribute('href') })) };
  let last = ''; try { const v = (sessionStorage.getItem('gai_last') || '').split('|'); sessionStorage.removeItem('gai_last'); if (Date.now() - v[0] < 10000) last = v.slice(1).join('|'); } catch (e) {}
  refresh(); say(last ? '직전: ' + last + ' → 지금 이 화면.' : 'GAI 켜짐. 빨간 번호는 바로 오른쪽 요소의 번호입니다. 번호만 치면 그 요소를 누릅니다. ? 는 도움말.');
  cmd.focus(); lift(); setTimeout(() => { quiet(); lift(); refresh(); }, 2500); setTimeout(lift, 6000);
}
