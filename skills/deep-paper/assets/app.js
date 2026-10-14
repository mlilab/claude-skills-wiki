// deep-paper site: split view with a PDF.js viewer, page jumps, index filters, math.
(function () {
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  // ---------------------------------------------------------------- math
  function renderMath() {
    if (!window.renderMathInElement || document.body.dataset.math) return;
    document.body.dataset.math = '1';
    renderMathInElement(document.body, {
      delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }],
      throwOnError: false, ignoredClasses: ['pdf-pages']
    });
  }
  // KaTeX is loaded before this script; the load event may already be over when a host injects
  // the page (e.g. a password-protected site that decrypts it), so try now and again on load.
  renderMath();
  window.addEventListener('load', renderMath);

  // ---------------------------------------------------------------- index page
  var table = document.querySelector('table.db');
  if (table) {
    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var search = document.querySelector('.search');
    var cat = '';
    function apply() {
      var q = (search.value || '').trim().toLowerCase();
      rows.forEach(function (r) {
        var okCat = !cat || (r.dataset.cats || '').split('|').indexOf(cat) >= 0;
        var okQ = !q || (r.dataset.search || '').indexOf(q) >= 0;
        r.hidden = !(okCat && okQ);
      });
    }
    document.querySelectorAll('.filter').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('.filter').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on'); cat = b.dataset.cat || ''; apply();
      });
    });
    search.addEventListener('input', apply);
    table.querySelectorAll('th[data-col]').forEach(function (th) {
      var asc = false;
      th.addEventListener('click', function () {
        var col = +th.dataset.col; asc = !asc;
        rows.sort(function (a, b) {
          var x = a.cells[col].dataset.sort || a.cells[col].textContent;
          var y = b.cells[col].dataset.sort || b.cells[col].textContent;
          return asc ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
    return;
  }

  // ---------------------------------------------------------------- paper page
  var main = document.querySelector('main.split');
  if (!main) return;
  var left = document.querySelector('.pane.left');
  var right = document.querySelector('.pane.right');
  var gutter = document.querySelector('.gutter');
  var pagesEl = document.querySelector('.pdf-pages');
  var pageLabel = document.querySelector('.pdf-page');
  var narrow = window.matchMedia('(max-width: 900px)');

  // view modes: split | summary | pdf (narrow screens: summary | pdf)
  var modeBtns = document.querySelectorAll('.modes button');
  function setMode(m) {
    if (narrow.matches && m === 'split') m = 'summary';
    main.dataset.mode = m;
    modeBtns.forEach(function (b) { b.classList.toggle('on', b.dataset.mode === m); });
    store('dp-mode', m);
    if (m !== 'summary') ensurePdf();
  }
  modeBtns.forEach(function (b) { b.addEventListener('click', function () { setMode(b.dataset.mode); }); });

  // resizable split
  var ratio = parseFloat(load('dp-split') || '0.5');
  function applyRatio() { main.style.setProperty('--left', (ratio * 100).toFixed(1) + '%'); }
  applyRatio();
  if (gutter) {
    gutter.addEventListener('pointerdown', function (ev) {
      ev.preventDefault();
      gutter.setPointerCapture(ev.pointerId);
      function move(e) {
        var r = main.getBoundingClientRect();
        ratio = Math.min(0.8, Math.max(0.2, (e.clientX - r.left) / r.width));
        applyRatio();
      }
      function up() {
        gutter.removeEventListener('pointermove', move);
        gutter.removeEventListener('pointerup', up);
        store('dp-split', ratio.toFixed(3));
        rerender();
      }
      gutter.addEventListener('pointermove', move);
      gutter.addEventListener('pointerup', up);
    });
  }

  // ---------------------------------------------------------------- PDF.js viewer
  var pdfDoc = null, started = false, pageEls = [], renderedWidth = {};
  function ensurePdf() {
    if (started) return;
    started = true;
    var url = main.dataset.pdf;
    var lib = window['pdfjs-dist/build/pdf'];
    if (!url || !lib) { pagesEl.textContent = pagesEl.dataset.fail; return; }
    var worker = document.querySelector('meta[name="pdfjs-worker"]');
    // a cross-origin worker URL is refused by browsers; wrap the CDN script in a same-origin blob
    var src = worker ? worker.content : '';
    try {
      src = URL.createObjectURL(new Blob(['importScripts("' + src + '");'], { type: 'application/javascript' }));
    } catch (e) {}
    lib.GlobalWorkerOptions.workerSrc = src;
    pagesEl.textContent = pagesEl.dataset.loading;
    lib.getDocument({ url: url }).promise.then(function (doc) {
      pdfDoc = doc;
      pagesEl.textContent = '';
      for (var i = 1; i <= doc.numPages; i++) {
        var d = document.createElement('div');
        d.className = 'pdf-pg'; d.dataset.page = i;
        d.style.aspectRatio = '0.773';
        pagesEl.appendChild(d); pageEls.push(d);
      }
      observe();
      if (pendingJump) { jump(pendingJump); pendingJump = null; }
    }).catch(function () {
      pagesEl.innerHTML = '<p class="pdf-fail">' + pagesEl.dataset.fail + ' <a target="_blank" rel="noopener" href="' +
        url + '">' + url + '</a></p>';
    });
  }

  function renderPage(el) {
    var n = +el.dataset.page, w = Math.floor(pagesEl.clientWidth - 16);
    if (!pdfDoc || w <= 0 || renderedWidth[n] === w) return;
    renderedWidth[n] = w;
    pdfDoc.getPage(n).then(function (page) {
      var v1 = page.getViewport({ scale: 1 });
      var scale = w / v1.width, dpr = window.devicePixelRatio || 1;
      var vp = page.getViewport({ scale: scale * dpr });
      var c = document.createElement('canvas');
      c.width = vp.width; c.height = vp.height;
      c.style.width = w + 'px'; c.style.height = (vp.height / dpr) + 'px';
      el.style.aspectRatio = '';
      page.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise.then(function () {
        el.textContent = ''; el.appendChild(c);
      });
    });
  }

  var io = null;
  function observe() {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) renderPage(e.target);
      });
    }, { root: pagesEl, rootMargin: '600px 0px' });
    pageEls.forEach(function (el) { io.observe(el); });
    pagesEl.addEventListener('scroll', updateLabel, { passive: true });
    updateLabel();
  }
  function updateLabel() {  // the page at the top third of the viewer
    if (!pageLabel || !pdfDoc) return;
    var y = pagesEl.scrollTop + pagesEl.clientHeight / 3, n = 1;
    for (var i = 0; i < pageEls.length; i++) { if (pageEls[i].offsetTop <= y) n = i + 1; else break; }
    pageLabel.textContent = n + ' / ' + pdfDoc.numPages;
  }
  var rt = null;
  function rerender() {
    clearTimeout(rt);
    rt = setTimeout(function () {
      renderedWidth = {};
      pageEls.forEach(function (el) {
        var r = el.getBoundingClientRect(), p = pagesEl.getBoundingClientRect();
        if (r.bottom > p.top - 600 && r.top < p.bottom + 600) renderPage(el);
      });
    }, 200);
  }
  window.addEventListener('resize', rerender);

  var pendingJump = null;
  function jump(n) {
    if (!pdfDoc) { pendingJump = n; ensurePdf(); return; }
    var el = pageEls[n - 1];
    if (el) pagesEl.scrollTo({ top: el.offsetTop - 8, behavior: 'smooth' });  // .pdf-pages is position:relative
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button.pg');
    if (!b) return;
    var n = +b.dataset.page;
    if (main.dataset.mode === 'summary') setMode(narrow.matches ? 'pdf' : 'split');
    jump(n);
  });

  setMode(load('dp-mode') || 'split');
})();
