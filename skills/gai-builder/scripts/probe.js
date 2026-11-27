// DOM probe. Paste into the browser's run-JavaScript tool on each page type; returns counts and a few samples per check.
// Tool output is often cut near 1,000 characters: assign the result to a window variable and read it in slices.
(() => {
  const q = (s, r = document) => [...r.querySelectorAll(s)];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (!el.checkVisibility || el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })); };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const name = el => (el.getAttribute('aria-label') || txt(el) || q('img[alt]', el).map(i => i.alt).join(' ').trim() || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
  const sel = el => el.id ? '#' + el.id : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '');
  const pick = (els, f = el => txt(el).slice(0, 24)) => ({ n: els.length, eg: els.slice(0, 4).map(el => sel(el) + (f(el) ? ' "' + f(el) + '"' : '')) });
  const OPS = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],[onclick]';
  const V = q(OPS).filter(vis), A = q('a'), href = a => (a.getAttribute('href') || '').trim();
  const fake = A.filter(a => !href(a) || href(a) === '#' || /^javascript:/i.test(href(a)));
  const ptr = el => getComputedStyle(el).cursor === 'pointer';
  const soft = q('div,span,li,td,p,img,i').filter(el => ptr(el) && !(el.parentElement && ptr(el.parentElement)) && !el.closest(OPS + ',label') && !el.querySelector(OPS) && vis(el));
  const area = innerWidth * innerHeight;
  const over = q('body *').filter(el => { const s = getComputedStyle(el); if (s.position !== 'fixed' && !(s.position === 'absolute' && +s.zIndex > 10)) return false; const r = el.getBoundingClientRect(); return vis(el) && r.width * r.height > area * 0.1; });
  return {
    size: { links: A.length, operableVisible: V.length, pageHeight: document.documentElement.scrollHeight, viewport: [innerWidth, innerHeight] },
    find: { linksWithoutAddress: fake.length, softClickables: pick(soft), unnamed: pick(V.filter(el => !name(el)), el => el.outerHTML.slice(0, 60)) },
    see: { imagesNoAlt: q('img:not([alt]),img[alt=""]').length + '/' + q('img').length, targetsUnder24px: pick(V.filter(el => { const r = el.getBoundingClientRect(); return r.width < 24 || r.height < 24; })), overlays: pick(over, el => Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height)) },
    act: { selects: q('select').map(s => (s.id || s.name) + ':' + s.options.length), newWindowLinks: A.filter(a => a.target === '_blank').length, carousels: q('[class*=swiper],[class*=slick],[class*=carousel]').length },
    forms: q('form').map(f => ({ action: (f.getAttribute('action') || '').replace(/\?.*$/, ''), fields: q('input:not([type=hidden]),select,textarea', f).map(i => i.name || i.id || i.type) }))
  };
})()
