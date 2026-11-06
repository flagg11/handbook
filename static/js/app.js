/* Handbook: клиент. Всё берёт с сервера (flask api) */
(() => {
'use strict';

const INBOX = 'inbox';
const ROOT = 'root';
const state = {
  folders: [], docs: [], cur: ROOT, expanded: new Set(), auto: true,
  prevDocs: new Map(), pollTimer: null,
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, attrs = {}, html = '') => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v; else if (k === 'text') n.textContent = v; else n.setAttribute(k, v);
  }
  if (html) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* приватное окно */ } },
};

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(url, opt);
  let data = null;
  try { data = await res.json(); } catch { /* пустой ответ - не беда */ }
  if (!res.ok) throw new Error((data && data.error) || `Ошибка ${res.status}`);
  return data;
}

let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : ''); t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, isErr ? 5200 : 3600);
}

const ICON = {
  folder: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M3.5 7.2c0-1.5 1.2-2.7 2.7-2.7h3.6c.6 0 1.1.2 1.5.6l1.2 1.1h5.3c1.5 0 2.7 1.2 2.7 2.7v7.4c0 1.5-1.2 2.7-2.7 2.7H6.2c-1.5 0-2.7-1.2-2.7-2.7V7.2z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  inbox: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 13l2-7h12l2 7v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5zM4 13h4.5l1 2h5l1-2H20" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  home: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 11l8-6.5 8 6.5v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1v-8z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  pdf: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M7 3.5h7l4.5 4.5v11A1.5 1.5 0 0 1 17 20.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M14 3.5V8h4.5M8.5 13h7M8.5 16.5h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  chev: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none"><path d="M8 5l8 7-8 7" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  move: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M4 8.5C4 7.1 5.1 6 6.5 6H10l2 2h5.5C18.9 8 20 9.1 20 10.5v6c0 1.4-1.1 2.5-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5v-8z" stroke="currentColor" stroke-width="1.6"/><path d="M10 13h5m0 0l-2-2m2 2l-2 2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  edit: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5 19l1-4L16.5 4.5a1.7 1.7 0 0 1 2.4 2.4L8.5 17.5 5 19z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  trash: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12M10 11v5M14 11v5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  up: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M6 15l6-6 6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  redo: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M19 12a7 7 0 1 1-2.2-5.1M19 4.5v4h-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  clock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.2" stroke="currentColor" stroke-width="1.6"/><path d="M12 7.5V12l3 2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  close: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5 5l14 14M19 5L5 19" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  left: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 6l-6 6 6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  right: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

/* ---- папки ---- */
const fById = () => new Map(state.folders.map((f) => [f.id, f]));
const childrenOf = (pid) => state.folders.filter((f) => (f.parent || null) === pid);
function pathOf(id) {
  const m = fById(); const out = [];
  while (id && m.has(id)) { out.push(m.get(id)); id = m.get(id).parent; }
  return out.reverse();
}
const pathText = (id) => pathOf(id).map((f) => f.name).join(' / ');
function descendantsOf(id) {
  const out = new Set([id]); const stack = [id];
  while (stack.length) { const c = stack.pop(); for (const f of childrenOf(c)) { if (!out.has(f.id)) { out.add(f.id); stack.push(f.id); } } }
  return out;
}
const docsIn = (fid) => state.docs.filter((d) => d.folder === fid);
const docsUnder = (fid) => { const set = fid ? descendantsOf(fid) : null; return state.docs.filter((d) => !set || set.has(d.folder)); };

/* ---- перераспознать ---- */
async function reparseDocRow(d) {
  if (d.status === 'processing') { toast('Файл уже обрабатывается'); return; }
  const ok = await dialog({ title: 'Перераспознать файл?', ok: 'Перераспознать',
    bodyHtml: `<p style="margin:0;line-height:1.5">«${esc(d.name)}» будет разобран заново текущей версией распознавания. Ручные правки текста в этом файле будут потеряны. Файл в папке не меняется.</p>` });
  if (!ok) return;
  try { await api('POST', `/api/docs/${d.id}/reparse`); await refresh({ quiet: true }); toast('Файл поставлен на распознавание'); }
  catch (e) { toast(e.message, true); }
}
async function reparseFolder(fid, name) {
  const n = docsUnder(fid).filter((d) => d.status !== 'processing').length;
  if (!n) { toast('Здесь нет файлов для перераспознавания'); return; }
  const where = fid ? `в папке «${esc(name)}» и вложенных` : 'во всём хранилище';
  const ok = await dialog({ title: 'Перераспознать файлы?', ok: 'Перераспознать',
    bodyHtml: `<p style="margin:0;line-height:1.5">Заново будут разобраны все файлы ${where}: ${n} ${plural(n, 'файл', 'файла', 'файлов')}. Для больших наборов это может занять несколько минут. Ручные правки текста в этих файлах будут потеряны. Сами файлы не меняются.</p>` });
  if (!ok) return;
  try { const r = await api('POST', '/api/reparse', { folder: fid || null }); await refresh({ quiet: true }); toast(`Поставлено на распознавание: ${r.count}`); }
  catch (e) { toast(e.message, true); }
}


/* ---- диалоги ---- */
function dialog({ title, bodyHtml = '', ok = 'Готово', cancel = 'Отмена', danger = false, onMount, validate }) {
  return new Promise((resolve) => {
    const host = $('#dialogHost');
    const ov = el('div', { class: 'overlay' });
    const dlg = el('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true' });
    dlg.innerHTML = `<h3>${esc(title)}</h3><div class="dlg-body">${bodyHtml}<div class="dlg-err"></div></div>
      <div class="dlg-foot"><button class="btn btn-ghost" data-x="cancel">${esc(cancel)}</button>
      <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-x="ok">${esc(ok)}</button></div>`;
    ov.appendChild(dlg); host.appendChild(ov);
    const done = (v) => { document.removeEventListener('keydown', onKey, true); ov.remove(); resolve(v); };
    let busy = false;
    const submit = async () => {
      if (busy) return;
      busy = true;
      const err = validate ? await validate(dlg) : null;
      busy = false;
      if (err) { $('.dlg-err', dlg).textContent = err; return; }
      done(dlg._value !== undefined ? dlg._value : true);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done(null); }
      else if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); e.stopPropagation(); submit(); }
    };
    document.addEventListener('keydown', onKey, true);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) done(null); });
    $('[data-x=cancel]', dlg).onclick = () => done(null);
    $('[data-x=ok]', dlg).onclick = submit;
    if (onMount) onMount(dlg);
    const inp = $('input', dlg); if (inp) { inp.focus(); inp.select(); } else $('[data-x=ok]', dlg).focus();
  });
}

/* action(name) сохраняет; если сервер отказал - ошибка показывается прямо в диалоге */
async function askText(title, value = '', placeholder = '', action = null) {
  return dialog({
    title, ok: 'Сохранить',
    bodyHtml: `<input class="dlg-input" value="${esc(value)}" placeholder="${esc(placeholder)}" maxlength="120">`,
    validate: async (d) => {
      const v = $('input', d).value.trim();
      if (!v) return 'Введите название';
      if (action) { try { await action(v); } catch (e) { return e.message; } }
      d._value = v; return null;
    },
  });
}

/* выбор папки */
function pickFolder({ title, current = null, exclude = new Set(), allowRoot = false }) {
  let selected = current;
  return dialog({
    title, ok: 'Выбрать',
    bodyHtml: '<div class="pick"></div>',
    onMount(dlg) {
      const box = $('.pick', dlg);
      const draw = () => {
        box.innerHTML = '';
        const add = (id, name, depth, icon, disabled) => {
          const b = el('button', { type: 'button' });
          b.style.paddingLeft = (8 + depth * 18) + 'px';
          b.innerHTML = `${icon}<span>${esc(name)}</span>`;
          if (selected === id) b.classList.add('sel');
          b.disabled = !!disabled;
          b.onclick = () => { selected = id; draw(); };
          box.appendChild(b);
        };
        if (allowRoot) add(ROOT, 'Все файлы (корень)', 0, ICON.home, false);
        const walk = (pid, depth) => {
          for (const f of childrenOf(pid)) {
            add(f.id, f.name, depth, f.id === INBOX ? ICON.inbox : ICON.folder, exclude.has(f.id));
            walk(f.id, depth + 1);
          }
        };
        walk(null, allowRoot ? 1 : 0);
      };
      draw();
    },
    validate: (d) => { if (!selected) return 'Выберите папку'; d._value = selected; return null; },
  });
}

/* ---- данные ---- */
const isBusy = (d) => d.status === 'processing' || d.status === 'queued' || (d.want_sort && !d.auto && d.status !== 'error');

async function refresh({ quiet = false } = {}) {
  const [folders, docs] = await Promise.all([api('GET', '/api/folders'), api('GET', '/api/uploads')]);
  state.folders = folders;
  const prev = state.prevDocs;
  state.docs = docs;
  if (!quiet) {
    for (const d of docs) {
      const p = prev.get(d.id);
      if (p && p.want_sort && !p.auto && d.auto && d.status === 'indexed') {
        toast(d.folder === INBOX ? `«${d.name}»: папка не определена, файл остался во «Входящих»` :
          `«${d.name}» → ${pathText(d.folder)} (${Math.round(d.confidence * 100)}%)`);
      }
      if (p && p.status === 'processing' && d.status === 'error') toast(`Не удалось обработать «${d.name}»: ${d.error}`, true);
    }
  }
  state.prevDocs = new Map(docs.map((d) => [d.id, d]));
  if (state.cur !== ROOT && !state.folders.some((f) => f.id === state.cur)) state.cur = ROOT;
  render();
  schedulePoll();
}

function schedulePoll() {
  if (state.docs.some(isBusy) && !state.pollTimer) {
    state.pollTimer = setInterval(async () => {
      try { await refresh(); } catch { /* сервер перезапускается */ }
      if (!state.docs.some(isBusy)) { clearInterval(state.pollTimer); state.pollTimer = null; }
    }, 1500);
  }
}

/* ---- отрисовка ---- */
function render() { renderSidebar(); renderMain(); }

function renderSidebar() {
  const box = $('#folderList');
  box.innerHTML = '';
  const row = (f, depth) => {
    const kids = childrenOf(f.id);
    const open = state.expanded.has(f.id);
    const d = el('div', { class: 'folder-item' + (state.cur === f.id ? ' active' : ''), 'data-id': f.id });
    d.style.paddingLeft = (4 + depth * 16) + 'px';
    if (!f.system) d.draggable = true;
    const attn = f.id === INBOX && f.total > 0;
    d.innerHTML = `<span class="fi-toggle ${open ? 'open' : ''}" ${kids.length ? '' : 'style="visibility:hidden"'}>${ICON.chev}</span>
      <span class="fi-icon">${f.id === INBOX ? ICON.inbox : ICON.folder}</span><span class="fi-name">${esc(f.name)}</span>
      <span class="fi-count ${attn ? 'attn' : ''}">${f.total || ''}</span>`;
    $('.fi-toggle', d).onclick = (e) => { e.stopPropagation(); toggleExpand(f.id); };
    d.onclick = () => { navigate(f.id); };
    wireFolderDnD(d, f);
    box.appendChild(d);
    if (open) for (const k of kids) row(k, depth + 1);
  };
  const rootItem = el('div', { class: 'folder-item' + (state.cur === ROOT ? ' active' : ''), 'data-id': ROOT });
  rootItem.innerHTML = `<span class="fi-toggle" style="visibility:hidden">${ICON.chev}</span><span class="fi-icon">${ICON.home}</span><span class="fi-name">Все файлы</span><span class="fi-count">${state.docs.length}</span>`;
  rootItem.onclick = () => navigate(ROOT);
  wireFolderDnD(rootItem, { id: ROOT });
  box.appendChild(rootItem);
  for (const f of childrenOf(null).filter((x) => x.id !== INBOX)) row(f, 0);
  const inbox = state.folders.find((f) => f.id === INBOX);
  if (inbox) { box.appendChild(el('div', { class: 'folder-sep' })); row(inbox, 0); }
}

function toggleExpand(id) {
  if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id);
  store.set('expanded', [...state.expanded]);
  renderSidebar();
}

function navigate(id) {
  state.cur = id;
  for (const f of pathOf(id).slice(0, -1)) state.expanded.add(f.id);
  if (childrenOf(id).length) state.expanded.add(id);
  store.set('expanded', [...state.expanded]);
  store.set('cur', id);
  render();
}

function renderMain() {
  const cur = state.cur === ROOT ? null : state.folders.find((f) => f.id === state.cur);
  const bc = $('#breadcrumb'); bc.innerHTML = '';
  const crumbs = [{ id: ROOT, name: 'Все файлы' }, ...pathOf(state.cur === ROOT ? null : state.cur)];
  crumbs.forEach((c, i) => {
    if (i) bc.appendChild(el('span', { text: '/' }));
    if (i === crumbs.length - 1) bc.appendChild(el('span', { class: 'cur', text: c.name }));
    else { const b = el('button', { type: 'button', text: c.name }); b.onclick = () => navigate(c.id); bc.appendChild(b); }
  });
  const title = $('#pageTitle'); title.textContent = cur ? cur.name : 'Все файлы';
  if (cur && !cur.system) {
    const r = el('button', { class: 'icon-btn', type: 'button', title: 'Переименовать папку' }, ICON.edit);
    r.onclick = () => renameFolder(cur);
    const d = el('button', { class: 'icon-btn', type: 'button', title: 'Удалить папку' }, ICON.trash);
    d.onclick = () => deleteFolder(cur);
    title.append(' ', r, d);
  }
  $('#sortInboxBtn').hidden = state.cur !== INBOX || !docsIn(INBOX).some((d) => d.status === 'indexed');

  const subs = childrenOf(state.cur === ROOT ? null : state.cur);
  const docs = state.cur === ROOT ? [] : docsIn(state.cur);
  const pending = state.docs.filter((d) => d.status === 'processing').length;
  const review = state.docs.filter((d) => d.needs_review).length;
  const info = $('#toolbarInfo');
  info.innerHTML = '';
  info.append(`Папок: ${subs.length} · файлов: ${docs.length}`);
  if (pending) info.appendChild(el('span', { class: 'chip chip-ocr' }, `<span class="spinner"></span> обрабатывается: ${pending}`));
  if (review) info.appendChild(el('span', { class: 'chip chip-warn', title: 'Файлы, которые автосортировка не смогла уверенно определить' }, `требуют проверки: ${review}`));

  const rows = $('#fileRows'); rows.innerHTML = '';
  if (!subs.length && !docs.length) {
    rows.appendChild(el('div', { class: 'empty' }, state.cur === ROOT ? '<b>Здесь пока пусто</b>Перетащите PDF в окно или нажмите «Загрузить».' :
      '<b>Папка пуста</b>Перетащите сюда файлы или нажмите «Загрузить».'));
    return;
  }
  for (const f of subs) rows.appendChild(folderRow(f));
  for (const d of docs) rows.appendChild(docRow(d));
}

function folderRow(f) {
  const r = el('div', { class: 'file-row', 'data-id': f.id });
  if (!f.system) r.draggable = true;
  r.innerHTML = `<div class="col-name"><span class="fr-icon">${f.id === INBOX ? ICON.inbox : ICON.folder}</span>
    <div class="fr-text"><div class="fr-name">${esc(f.name)}</div></div></div>
    <div class="col-type">Папка</div><div class="col-size">${f.total} ${plural(f.total, 'файл', 'файла', 'файлов')}</div><div class="col-date"></div>
    <div class="col-actions"></div>`;
  const act = $('.col-actions', r);
  act.append(iconBtn(ICON.redo, 'Перераспознать файлы в папке', () => reparseFolder(f.id, f.name)));
  if (!f.system) {
    act.append(iconBtn(ICON.move, 'Переместить', async () => {
      const t = await pickFolder({ title: `Переместить папку «${f.name}»`, current: f.parent || ROOT, exclude: descendantsOf(f.id), allowRoot: true });
      if (t) moveFolder(f.id, t === ROOT ? null : t);
    }), iconBtn(ICON.edit, 'Переименовать', () => renameFolder(f)), iconBtn(ICON.trash, 'Удалить', () => deleteFolder(f)));
  }
  r.onclick = (e) => { if (!e.target.closest('button')) navigate(f.id); };
  wireFolderDnD(r, f);
  return r;
}

function docRow(d) {
  const r = el('div', { class: 'file-row', 'data-doc': d.id, draggable: 'true' });
  const chips = [];
  if (d.kind === 'docx') chips.push('<span class="chip" title="Документ Word: читается через преобразование в страницы">Word</span>');
  if (d.ocr_pages) chips.push(`<span class="chip chip-ocr" title="Страниц, распознанных через OCR: ${d.ocr_pages}">OCR</span>`);
  if (d.tables) chips.push(`<span class="chip" title="Таблиц, разобранных на ячейки">таблиц: ${d.tables}</span>`);
  if (d.auto && d.folder !== INBOX && !d.needs_review) chips.push(`<span class="chip chip-ok" title="${esc(d.reason)}">автосортировка · ${Math.round(d.confidence * 100)}%</span>`);
  if (d.needs_review) chips.push(`<button class="chip chip-warn" type="button" data-review title="${esc(d.reason)}">проверить${d.confidence ? ' · ' + Math.round(d.confidence * 100) + '%' : ''}</button>`);
  if (d.warnings.length) chips.push(`<span class="chip chip-warn" title="${esc(d.warnings.join('\n'))}">предупреждение</span>`);
  let status = `${d.pages || '—'} стр.`;
  if (d.status === 'processing' || d.status === 'queued') status = '<span class="spinner"></span> Обработка…';
  else if (d.status === 'error') status = `<span class="chip chip-bad" title="${esc(d.error)}">ошибка</span>`;
  r.innerHTML = `<div class="col-name"><span class="fr-icon ${d.kind === 'docx' ? 'docx' : 'pdf'}">${ICON.pdf}</span>
    <div class="fr-text"><div class="fr-name" title="${esc(d.name)}">${esc(d.name)}</div><div class="fr-sub">${chips.join('')}</div></div></div>
    <div class="col-type">${status}</div><div class="col-size">${esc(d.size)}</div><div class="col-date">${esc(d.date)}</div><div class="col-actions"></div>`;
  const act = $('.col-actions', r);
  act.append(iconBtn(ICON.redo, 'Перераспознать', () => reparseDocRow(d)),
    iconBtn(ICON.move, 'Переместить', () => moveDocDialog(d)),
    iconBtn(ICON.edit, 'Переименовать', () => renameDoc(d)),
    iconBtn(ICON.trash, 'Удалить', () => deleteDoc(d)));
  const rv = $('[data-review]', r);
  if (rv) rv.onclick = (e) => { e.stopPropagation(); moveDocDialog(d); };
  r.onclick = (e) => {
    if (e.target.closest('button')) return;
    if (d.status === 'indexed') openViewer(d.id, { q: $('#searchInput').value.trim() });
    else if (d.status === 'error') toast(`Ошибка разбора: ${d.error || 'неизвестная'}. Исправьте причину и нажмите «Перераспознать» справа в строке`, true);
    else toast('Файл ещё обрабатывается');
  };
  r.addEventListener('dragstart', (e) => { drag = { type: 'doc', id: d.id }; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', d.name); r.classList.add('dragging'); });
  r.addEventListener('dragend', () => { drag = null; r.classList.remove('dragging'); });
  return r;
}

function iconBtn(svg, title, fn) {
  const b = el('button', { class: 'icon-btn', type: 'button', title, 'aria-label': title }, svg);
  b.onclick = (e) => { e.stopPropagation(); fn(); };
  return b;
}
function plural(n, a, b, c) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return a;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return b;
  return c;
}

/* ---- действия с папками и файлами ---- */
async function createFolder() {
  const parent = state.cur === ROOT ? null : state.cur;
  let created = null;
  const name = await askText('Новая папка', '', 'Название папки', async (n) => { created = await api('POST', '/api/folders', { name: n, parent }); });
  if (!name || !created) return;
  if (parent) state.expanded.add(parent);
  await refresh({ quiet: true });
  toast(`Папка «${created.name}» создана`);
}
async function renameFolder(f) {
  let done = false;
  const name = await askText('Переименовать папку', f.name, '', async (n) => { if (n !== f.name) { await api('PATCH', `/api/folders/${f.id}`, { name: n }); done = true; } });
  if (!name || !done) return;
  await refresh({ quiet: true }); toast('Папка переименована');
}
async function moveFolder(id, parent) {
  try { await api('PATCH', `/api/folders/${id}`, { parent }); if (parent) state.expanded.add(parent); await refresh({ quiet: true }); toast('Папка перемещена'); }
  catch (e) { toast(e.message, true); }
}
async function deleteFolder(f) {
  const total = f.total;
  const ok = await dialog({
    title: `Удалить папку «${f.name}»?`, ok: 'Удалить', danger: true,
    bodyHtml: total ? `Вместе с папкой будут безвозвратно удалены вложенные папки и файлы: ${total} ${plural(total, 'файл', 'файла', 'файлов')}.` : 'Папка пуста.',
  });
  if (!ok) return;
  try {
    const wasInside = descendantsOf(f.id).has(state.cur);
    await api('DELETE', `/api/folders/${f.id}`);
    if (wasInside) state.cur = f.parent || ROOT;
    await refresh({ quiet: true });
    toast(`Папка «${f.name}» удалена`);
  } catch (e) { toast(e.message, true); }
}
async function moveDocDialog(d) {
  const t = await pickFolder({ title: `Переместить «${d.name}»`, current: d.folder });
  if (t) moveDoc(d.id, t);
}
async function moveDoc(id, folder) {
  try { await api('PATCH', `/api/docs/${id}`, { folder }); await refresh({ quiet: true }); toast(`Перемещено в «${pathText(folder)}»`); }
  catch (e) { toast(e.message, true); }
}
async function renameDoc(d) {
  const base = d.name.replace(/\.(pdf|docx)$/i, '');
  let done = false;
  const name = await askText('Переименовать файл', base, '', async (n) => { if (n !== base) { await api('PATCH', `/api/docs/${d.id}`, { name: n }); done = true; } });
  if (!name || !done) return;
  await refresh({ quiet: true });
}
async function deleteDoc(d) {
  const ok = await dialog({ title: 'Удалить файл?', ok: 'Удалить', danger: true, bodyHtml: `«${esc(d.name)}» будет безвозвратно удалён вместе с индексом поиска.` });
  if (!ok) return;
  try { await api('DELETE', `/api/upload/${d.id}`); await refresh({ quiet: true }); toast('Файл удалён'); }
  catch (e) { toast(e.message, true); }
}

/* ---- drag and drop ---- */
let drag = null;
function wireFolderDnD(node, f) {
  if (!f.system && f.id !== ROOT && node.draggable) {
    node.addEventListener('dragstart', (e) => { drag = { type: 'folder', id: f.id }; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', f.name); e.stopPropagation(); });
    node.addEventListener('dragend', () => { drag = null; });
  }
  const canDrop = (e) => {
    if (e.dataTransfer.types.includes('Files')) return f.id !== ROOT;
    if (!drag) return false;
    if (drag.type === 'doc') return f.id !== ROOT;
    return drag.id !== f.id && !descendantsOf(drag.id).has(f.id);
  };
  node.addEventListener('dragover', (e) => { if (canDrop(e)) { e.preventDefault(); e.stopPropagation(); node.classList.add('drop'); } });
  node.addEventListener('dragleave', () => node.classList.remove('drop'));
  node.addEventListener('drop', async (e) => {
    node.classList.remove('drop');
    if (!canDrop(e)) return;
    e.preventDefault(); e.stopPropagation();
    if (e.dataTransfer.files && e.dataTransfer.files.length) { uploadFiles([...e.dataTransfer.files], { folder: f.id }); return; }
    const d = drag; drag = null;
    if (!d) return;
    if (d.type === 'doc') moveDoc(d.id, f.id);
    else moveFolder(d.id, f.id === ROOT ? null : f.id);
  });
}

function wireContentDrop() {
  const area = $('#content'), hint = $('#dropHint');
  let depth = 0;
  area.addEventListener('dragenter', (e) => { if (e.dataTransfer.types.includes('Files')) { depth++; hint.hidden = false; } });
  area.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); });
  area.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) hint.hidden = true; });
  area.addEventListener('drop', (e) => {
    depth = 0; hint.hidden = true;
    if (e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); uploadFiles([...e.dataTransfer.files]); }
  });
  window.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); });
  window.addEventListener('drop', (e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); });
}

/* ---- загрузка ---- */
async function uploadFiles(files, { folder = null } = {}) {
  const pdfs = files.filter((f) => /\.(pdf|docx)$/i.test(f.name));
  if (!pdfs.length) { toast('Можно загружать только PDF и Word (.docx)', true); return; }
  if (pdfs.length < files.length) toast(`Пропущено файлов не в формате PDF или Word: ${files.length - pdfs.length}`, true);
  const auto = folder === null && state.auto;
  const target = folder || (state.cur === ROOT ? INBOX : state.cur);
  let ok = 0;
  for (const f of pdfs) {
    const fd = new FormData();
    fd.append('file', f); fd.append('folder', target); fd.append('auto', auto ? '1' : '0');
    try { await api('POST', '/api/upload', fd); ok++; } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  if (ok) {
    await refresh({ quiet: true });
    toast(auto ? `Загружено: ${ok}. После распознавания файлы будут разложены по содержанию` :
      `Загружено: ${ok} → «${pathText(target)}»`);
  }
}

/* ---- поиск ---- */
const searchInput = () => $('#searchInput');
let searchTimer = null, searchSeq = 0, searchItems = [], searchActive = -1;

function wordsOf(q) { return (q.match(/[0-9A-Za-zА-Яа-яЁё]+/g) || []).filter((w) => w.length > 1 || /\d/.test(w)); }
function highlight(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  if (/^\d{1,2}(\.\d{1,3})+\.?$/.test(q.trim())) {
    const num = q.trim().replace(/\.$/, '').replace(/\./g, '\\.');
    return safe.replace(new RegExp('(?<![\\d.])(' + num + ')(?![\\d])', 'g'), '<mark>$1</mark>');
  }
  const stop = new Set(['и', 'в', 'во', 'на', 'с', 'со', 'по', 'при', 'для', 'из', 'к', 'о', 'об', 'от', 'до', 'не', 'за']);
  const parts = wordsOf(q).filter((w) => !stop.has(w.toLowerCase()))
    .map((w) => { const lw = w.toLowerCase().replace(/ё/g, 'е'); return lw.length >= 5 ? lw.slice(0, lw.length - 2) : lw; })
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/е/g, '[её]'));
  if (!parts.length) return safe;
  const re = new RegExp('(?<![\\p{L}\\d])(' + parts.join('|') + ')[\\p{L}\\d]*', 'giu');
  return safe.replace(re, (m) => '<mark>' + m + '</mark>');
}

function hideResults() { $('#searchResults').hidden = true; searchActive = -1; }

/* история поиска, лежит только в этом браузере */
const HIST_KEY = 'hb_search_history';
const HIST_MAX = 12;
function histGet() {
  try { const v = JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; } catch (e) { return []; }
}
function histSet(list) { try { localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, HIST_MAX))); } catch (e) { /* нет хранилища - история не сохранится */ } }
function histAdd(q) {
  q = (q || '').trim();
  if (q.length < 2) return;
  histSet([q, ...histGet().filter((x) => x.toLowerCase() !== q.toLowerCase())]);
}
function histRemove(q) { histSet(histGet().filter((x) => x !== q)); }
function showHistory() {
  const box = $('#searchResults');
  const list = histGet();
  if (!list.length) { hideResults(); return; }
  ++searchSeq;
  box.innerHTML = ''; searchItems = []; searchActive = -1;
  box.appendChild(el('div', { class: 'sr-head', text: 'Недавние запросы' }));
  for (const q of list) {
    const row = el('div', { class: 'sr-item sr-hist', role: 'button', tabindex: '-1' },
      `<div class="sr-top"><span class="fi-icon">${ICON.clock}</span><span class="sr-doc">${esc(q)}</span><button class="icon-btn sr-del" type="button" title="Убрать из истории" aria-label="Убрать из истории">${ICON.close}</button></div>`);
    row.onclick = (e) => {
      if (e.target.closest('.sr-del')) { e.stopPropagation(); histRemove(q); showHistory(); return; }
      searchInput().value = q; searchInput().focus(); runSearch();
    };
    box.appendChild(row); searchItems.push(row);
  }
  const clr = el('button', { class: 'sr-clear', type: 'button', text: 'Очистить историю' });
  clr.onclick = () => { histSet([]); hideResults(); };
  box.appendChild(clr);
  box.hidden = false;
}

async function runSearch() {
  const q = searchInput().value.trim();
  const box = $('#searchResults');
  if (!q) { showHistory(); return; }
  const seq = ++searchSeq;
  let data;
  try { data = await api('GET', '/api/search?q=' + encodeURIComponent(q)); } catch (e) { return; }
  if (seq !== searchSeq) return;
  box.innerHTML = ''; searchItems = []; searchActive = -1;
  if (data.folders && data.folders.length) {
    box.appendChild(el('div', { class: 'sr-head', text: 'Папки' }));
    for (const f of data.folders) {
      const b = el('button', { class: 'sr-item', type: 'button' }, `<div class="sr-top"><span class="fi-icon">${ICON.folder}</span><span class="sr-doc">${highlight(f.name, q)}</span><span class="sr-path">${esc(f.path)} · файлов: ${f.total}</span></div>`);
      b.onclick = () => { histAdd(q); hideResults(); navigate(f.id); };
      box.appendChild(b); searchItems.push(b);
    }
  }
  if (data.results.length) {
    box.appendChild(el('div', { class: 'sr-head', text: 'Документы' }));
    for (const r of data.results) {
      const badges = [];
      if (r.kind === 'name') badges.push('<span class="chip chip-ok">по названию</span>');
      if (r.chunk_kind === 'table') badges.push('<span class="chip">таблица</span>');
      if (r.source === 'ocr') badges.push('<span class="chip chip-ocr">скан · OCR</span>');
      const sec = r.section ? `<span class="sr-sec">п. ${esc(r.section)}</span>` : '';
      const pageTxt = r.page === r.page_to || !r.page_to ? `стр. ${r.page}` : `стр. ${r.page}–${r.page_to}`;
      const b = el('button', { class: 'sr-item', type: 'button' },
        `<div class="sr-top"><span class="sr-doc">${highlight(r.doc_name, q)}</span><span class="sr-path">${esc(r.folder_path)}</span></div>
         <div class="sr-meta">${sec}<span>${esc(r.title || '')}</span><span>· ${pageTxt}</span>${badges.join('')}</div>
         ${r.snippet ? `<div class="sr-snip">${r.snippet}</div>` : ''}`);
      b.onclick = () => { histAdd(q); hideResults(); openViewer(r.doc_id, { q, chunk: r.chunk_id }); };
      box.appendChild(b); searchItems.push(b);
    }
  }
  if (!searchItems.length) box.appendChild(el('div', { class: 'sr-empty' }, `По запросу «${esc(q)}» ничего не найдено. Файлы, которые ещё обрабатываются, появятся в поиске после распознавания.`));
  box.hidden = false;
}

function setActiveResult(i) {
  searchItems.forEach((b, k) => b.classList.toggle('active', k === i));
  searchActive = i;
  if (searchItems[i]) searchItems[i].scrollIntoView({ block: 'nearest' });
}

function wireSearch() {
  const inp = searchInput();
  inp.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 220); });
  inp.addEventListener('focus', () => { if (!inp.value.trim()) showHistory(); else if (searchItems.length) $('#searchResults').hidden = false; });
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (searchItems.length) setActiveResult((searchActive + 1) % searchItems.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (searchItems.length) setActiveResult((searchActive - 1 + searchItems.length) % searchItems.length); }
    else if (e.key === 'Enter') { e.preventDefault(); clearTimeout(searchTimer); if (searchActive >= 0) searchItems[searchActive].click(); else { histAdd(inp.value); runSearch(); } }
    else if (e.key === 'Escape') { hideResults(); inp.blur(); }
  });
  document.addEventListener('mousedown', (e) => { if (!e.target.closest('.searchwrap')) hideResults(); });
}

/* ---- просмотрщик ---- */
let V = null;   // состояние открытого просмотрщика

async function openViewer(docId, { q = '', chunk = null } = {}) {
  closeViewer();
  const host = $('#viewerHost');
  host.innerHTML = '<div class="viewer"><div class="page-loading">Открываю документ…</div></div>';
  let data;
  try { data = await api('GET', `/api/docs/${docId}`); } catch (e) { host.innerHTML = ''; toast(e.message, true); return; }
  V = {
    doc: data.doc, chunks: data.chunks, sizes: data.sizes || [], figures: data.figures || [], q, hits: [], idx: 0,
    page: 1, active: null, editing: null, findSeq: 0, startChunk: chunk, mode: '', anchors: [], ign: new Map(),
  };
  buildViewer();
  const ch = chunk && V.chunks.find((c) => c.id === chunk);
  if (ch) { V.active = ch.id; markActive(); scrollToChunk(ch.id); }
  if (q) await runFind(true); else updateCount();
}

function closeViewer() {
  if (!V) return;
  document.removeEventListener('keydown', viewerKey, true);
  if (V.ro) V.ro.disconnect();
  if (V.io) V.io.disconnect();
  $('#viewerHost').innerHTML = '';
  V = null;
}

function buildViewer() {
  const d = V.doc;
  const host = $('#viewerHost');
  const sub = [pathText(d.folder), `${d.pages} стр.`, d.ocr_pages ? `OCR: ${d.ocr_pages}` : (d.empty_pages ? (d.empty_pages >= d.pages ? 'скан без распознавания' : `без распознавания: ${d.empty_pages} стр.`) : 'текстовый слой'), ...(d.warnings || [])].join(' · ');
  host.innerHTML = `<div class="viewer" role="dialog" aria-modal="true">
    <div class="v-top">
      <div class="v-title"><div class="v-name" title="${esc(d.name)}">${esc(d.name)}</div><div class="v-sub">${esc(sub)}</div></div>
      <div class="v-find"><input id="vFind" type="search" placeholder="Найти в документе…" value="${esc(V.q)}" autocomplete="off" aria-label="Поиск по документу">
        <span class="v-count" id="vCount"></span>
        <button class="icon-btn" id="vPrev" type="button" title="Предыдущее (Shift+Enter, ↑)" aria-label="Предыдущее совпадение">${ICON.up}</button>
        <button class="icon-btn" id="vNext" type="button" title="Следующее (Enter, ↓)" aria-label="Следующее совпадение">${ICON.down}</button></div>
      <div class="v-pager"><button class="icon-btn" id="vPgPrev" type="button" aria-label="Предыдущая страница">${ICON.left}</button>
        <span id="vPg"></span><button class="icon-btn" id="vPgNext" type="button" aria-label="Следующая страница">${ICON.right}</button></div>
      <button class="btn btn-ghost btn-sm" id="vReparse" type="button" title="Распознать документ заново (правки будут потеряны)">Перераспознать</button>
      <a class="btn btn-ghost btn-sm" id="vWord" href="/api/docs/${esc(d.id)}/export.docx" title="Скачать распознанный текст (с вашими правками) в Word">Скачать в Word</a>
      <a class="btn btn-ghost btn-sm" href="${esc(d.url)}" ${d.kind === 'docx' ? 'download' : 'target="_blank" rel="noopener"'}>${d.kind === 'docx' ? 'Оригинал (Word)' : 'Оригинал PDF'}</a>
      <button class="icon-btn" id="vClose" type="button" title="Закрыть (Esc)" aria-label="Закрыть">${ICON.close}</button>
    </div>
    <div class="v-body">
      <section class="v-pane v-parse"><div class="v-pane-head"><b>Распознанный текст</b><span>чтобы исправить, наведите на абзац и нажмите ✎</span></div>
        <div class="v-scroll" id="vParse"></div></section>
      <section class="v-pane v-pagepane"><div class="v-pane-head"><b>Документ</b><span id="vPageNote"></span></div>
        <div class="v-scroll" id="vPageScroll"></div></section>
    </div></div>`;
  $('#vClose').onclick = closeViewer;
  $('#vReparse').onclick = reparseDoc;
  wireCopy();
  $('#vPrev').onclick = () => stepHit(-1);
  $('#vNext').onclick = () => stepHit(1);
  $('#vPgPrev').onclick = () => gotoPage(curPage() - 1);
  $('#vPgNext').onclick = () => gotoPage(curPage() + 1);
  const f = $('#vFind');
  let t = null;
  f.addEventListener('input', () => { V.q = f.value.trim(); clearTimeout(t); t = setTimeout(() => runFind(false), 250); });
  f.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); stepHit(e.shiftKey ? -1 : 1); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); stepHit(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); stepHit(-1); }
  });
  document.addEventListener('keydown', viewerKey, true);
  buildPages();
  renderFlow();
  wireSync();
}


async function reparseDoc() {
  const d = V.doc;
  const edited = V.chunks.filter((c) => c.edited).length;
  const ok = await dialog({
    title: 'Перераспознать документ?', ok: 'Перераспознать', danger: edited > 0,
    bodyHtml: `<p style="margin:0;line-height:1.5">Файл будет разобран заново текущей версией распознавания.${edited ? ` Ручные правки (${edited}) будут потеряны.` : ''} Папка не изменится.</p>`,
  });
  if (!ok) return;
  const id = d.id;
  const host = $('#viewerHost');
  if (V.ro) V.ro.disconnect();
  if (V.io) V.io.disconnect();
  host.innerHTML = '<div class="viewer"><div class="page-loading">Распознаю заново, для больших документов это занимает до пары минут…</div></div>';
  try { await api('POST', `/api/docs/${id}/reparse`); } catch (e) { toast(e.message, true); closeViewer(); return; }
  const stop = V;
  for (let i = 0; i < 240; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    if (V !== stop) return;                                  // окно закрыли
    const list = await api('GET', '/api/uploads');
    const cur = list.find((x) => x.id === id);
    if (cur && cur.status !== 'processing') { await refresh({ quiet: true }); await openViewer(id, { q: stop.q }); return; }
  }
  toast('Распознавание занимает слишком долго, откройте файл позже', true);
  closeViewer();
}

/* копирование слева: сплошной текст без разрывов между страницами */
function seamlessCopy(range) {
  const tmp = document.createElement('div');
  tmp.appendChild(range.cloneContents());
  const blocks = [...tmp.querySelectorAll('.blk')];
  if (!blocks.length) return null;                       // выделили в одном абзаце - пусть копируется как обычно
  const items = [];
  const clean = (t) => t.replace(/\s+/g, ' ').trim();
  for (const blk of blocks) {
    const id = blk.dataset.id;
    const last = () => items[items.length - 1];
    const tbl = blk.querySelector('table');
    if (tbl) {
      const rows = [...tbl.rows].map((r) => [...r.cells].map((c) => clean(c.textContent)));
      const cap = blk.querySelector('.tbl-cap');
      const capText = cap ? clean(cap.textContent) : '';
      const prev = last();
      if (prev && prev.t === 'tbl' && prev.id === id) {            // продолжение таблицы на след. странице
        if (rows.length && prev.rows.length && JSON.stringify(rows[0]) === JSON.stringify(prev.rows[0])) rows.shift();
        prev.rows.push(...rows);
      } else {
        if (capText) items.push({ t: 'p', id, text: capText, hd: false });
        items.push({ t: 'tbl', id, rows });
      }
      continue;
    }
    [...blk.querySelectorAll('p.ln')].forEach((p, i) => {
      const text = clean(p.textContent);
      if (!text) return;
      const prev = last();
      const hd = p.classList.contains('hd');
      if (i === 0 && prev && prev.t === 'p' && prev.id === id && !prev.hd && !hd && !/[.!?:;]$/.test(prev.text)) {
        prev.text = /[а-яё]-$/i.test(prev.text) && /^[а-яё]/.test(text) ? prev.text.slice(0, -1) + text : prev.text + ' ' + text;
      } else items.push({ t: 'p', id, text, hd });
    });
  }
  if (!items.length) return null;
  const text = items.map((it) => it.t === 'p' ? it.text : it.rows.map((r) => r.join('\t')).join('\n')).join('\n');
  const html = items.map((it) => it.t === 'p' ? `<p>${esc(it.text)}</p>`
    : `<table border="1" cellspacing="0" cellpadding="3" style="border-collapse:collapse">${it.rows.map((r) => '<tr>' + r.map((c) => `<td>${esc(c)}</td>`).join('') + '</tr>').join('')}</table>`).join('');
  return { text, html };
}

function wireCopy() {
  $('#vParse').addEventListener('copy', (e) => {
    if (V && V.editing) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    let out = null;
    try { out = seamlessCopy(sel.getRangeAt(0)); } catch (err) { out = null; }
    if (!out) return;
    e.clipboardData.setData('text/plain', out.text);
    e.clipboardData.setData('text/html', out.html);
    e.preventDefault();
  });
}

function viewerKey(e) {
  if (!V) return;
  if ($('#dialogHost').children.length) return;
  if (e.key === 'Escape') {
    e.stopPropagation();
    if (V.editing) cancelEdit(); else closeViewer();
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') { e.preventDefault(); const f = $('#vFind'); f.focus(); f.select(); }
}

/* правая панель */
function buildPages() {
  const sc = $('#vPageScroll');
  sc.innerHTML = '';
  const wrap = el('div', { class: 'pages' });
  const total = V.doc.pages || V.sizes.length || 1;
  for (let n = 1; n <= total; n++) {
    const [w, h] = V.sizes[n - 1] || [595, 842];
    const pg = el('div', { class: 'pg', 'data-page': n });
    pg.style.aspectRatio = `${w} / ${h}`;
    pg.appendChild(el('div', { class: 'pg-num', text: String(n) }));
    pg.appendChild(el('div', { class: 'page-boxes' }));
    wrap.appendChild(pg);
  }
  sc.appendChild(wrap);
  V.io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      const pg = en.target;
      if (pg.dataset.loaded) continue;
      pg.dataset.loaded = '1';
      const img = el('img', { alt: `Страница ${pg.dataset.page}`, decoding: 'async' });
      img.onload = () => pg.classList.add('ready');
      img.src = `/api/docs/${V.doc.id}/page/${pg.dataset.page}.png`;
      pg.insertBefore(img, pg.firstChild);
    }
  }, { root: sc, rootMargin: '1400px 0px' });
  for (const pg of $$('.pg', sc)) V.io.observe(pg);
}
const pgEl = (n) => $(`.pg[data-page="${n}"]`, $('#vPageScroll'));

/* левая панель */
const CAPTION_RE = /^(рисунок|рис\.)\s/i;

function chunkPos(c, prev) {
  let y = c.y;
  if (y == null) y = prev && prev.page === c.page ? prev.y + 0.0005 : 0;
  return { page: c.page, y };
}

// у каждого куска позиция в страницах: 0 - верх 1-й страницы, 1 - верх 2-й
function flowItems() {
  const items = [];
  let prev = null;
  V.chunks.forEach((c, i) => {
    if (c.kind === 'table' && c.data && c.geom && c.geom.length) {
      // таблица знает где начинается и кончается на каждой странице
      c.geom.forEach((g, k) => {
        let pos = g.page - 1 + g.box[1];
        if (prev && pos < prev.pos) pos = prev.pos;
        prev = { page: g.page, y: g.box[1], pos };
        items.push({ kind: 'chunk', pos, pr: 2, seq: i + k * 1e-3, chunk: c, seg: g, segIdx: k, y: pos - (g.page - 1) });
      });
      return;
    }
    if (c.kind !== 'table' && c.geom && c.geom.length) {
      // у текста так же: какие строки на какой странице
      c.geom.forEach((g, k) => {
        let y = g.y0;
        if (y == null) y = (k === 0 && c.y != null && g.page === c.page) ? c.y : (prev && prev.page === g.page ? prev.y + 0.0005 : 0);
        let pos = g.page - 1 + y;
        if (prev && pos < prev.pos) pos = prev.pos;
        prev = { page: g.page, y, pos };
        items.push({ kind: 'chunk', pos, pr: 2, seq: i + k * 1e-3, chunk: c, seg: g, segIdx: k, y: pos - (g.page - 1) });
      });
      return;
    }
    const p = chunkPos(c, prev);
    let pos = p.page - 1 + p.y;
    if (prev && pos < prev.pos) pos = prev.pos;
    prev = { page: p.page, y: p.y, pos };
    items.push({ kind: 'chunk', pos, pr: 2, seq: i, chunk: c, y: pos - (p.page - 1) });
  });
  V.figures.forEach((f, i) => {
    let pos = f.page - 1 + f.box[1];
    let y = f.box[1];
    const whole = (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]) > 0.9;   // чертёж на весь лист: после его заголовка
    if (whole) {
      const first = items.find((x) => x.kind === 'chunk' && x.chunk.page === f.page);
      pos = first ? first.pos + 1e-6 : f.page - 1 + 0.001;
      y = pos - (f.page - 1);
    }
    items.push({ kind: 'fig', pos, pr: 3, seq: i, fig: f, y });
  });
  items.sort((a, b) => a.pos - b.pos || a.pr - b.pr || a.seq - b.seq);
  return items;
}

function sheetCount() { return V.doc.pages || V.sizes.length || 1; }

function renderFlow() {
  const box = $('#vParse');
  box.innerHTML = '';
  const inner = el('div', { class: 'pages sheets' });
  box.appendChild(inner);
  const total = sheetCount();
  V.sheets = [];
  for (let n = 1; n <= total; n++) {
    const sh = el('div', { class: 'pg sheet', 'data-page': n });
    sh.appendChild(el('div', { class: 'pg-num', text: String(n) }));
    inner.appendChild(sh);
    V.sheets.push(sh);
  }
  const body = flowItems();
  V.items = V.sheets.map((sh, i) => ({ kind: 'sheet', pos: i, page: i + 1, node: sh }));
  V.attach = {};
  let lastChunk = null, lastSheet = -1;
  for (const it of body) {
    const si = Math.max(0, Math.min(total - 1, Math.floor(it.pos + 1e-6)));
    const sh = V.sheets[si];
    if (si !== lastSheet) { lastChunk = null; lastSheet = si; }
    it.sheet = si;
    if (it.kind === 'chunk') {
      lastChunk = it;
      it.node = blockEl(it.chunk, it);
      sh.appendChild(it.node);
    } else {
      const fig = figureEl(it.fig);
      it.node = fig;
      if (lastChunk) {                     // рисунок сразу за текстом - подпись остаётся под ним
        (V.attach[lastChunk.chunk.id] = V.attach[lastChunk.chunk.id] || []).push(it);
        const anchor = $('.cap-line', lastChunk.node);
        if (anchor) anchor.before(fig); else lastChunk.node.appendChild(fig);
      } else sh.appendChild(fig);
    }
    V.items.push(it);
  }
  // пустая страница - подпись по центру
  V.sheets.forEach((sh, i) => {
    if (!$('.blk, .doc-fig', sh)) {
      const spanned = V.chunks.some((c) => c.page < i + 1 && (c.page_to || c.page) >= i + 1);
      sh.appendChild(el('div', { class: 'pg-empty', text: spanned ? 'Продолжение текста со страницы выше' : 'На странице нет распознанного текста' }));
    }
  });
  inner.appendChild(el('div', { class: 'v-note', text: 'Правки меняют текст в поиске. Подсветка на странице справа привязана к исходному распознаванию и после правки не пересчитывается.' }));
  alignAll();
  markActive();
}

/* Листы слева такого же размера как справа, блоки стоят на высоте оригинала.
   Короткая и пустая страница занимает столько же места, сколько справа, поэтому прокрутка не «прыгает». */
const GAP = 14;
function pageWidthPx() {
  const sc = $('#vPageScroll');
  const pg = sc && $('.pg:not(.sheet)', sc);
  return pg ? pg.getBoundingClientRect().width : 700;
}
function alignAll() {
  if (!V || !V.sheets || !$('#vParse') || !$('#vPageScroll')) return;
  const pw = pageWidthPx();
  const host = $('#vParse');
  host.style.setProperty('--pw', pw + 'px');
  V.pw = pw;
  const hs = V.sheets.map((_sh, i) => { const [w, h] = V.sizes[i] || [595, 842]; return pw * h / w; });
  let ideal = 0;
  const base = V.sheets[0].offsetTop;
  const top0 = () => V.sheets[0].getBoundingClientRect().top;
  for (let i = 0; i < V.sheets.length; i++) {
    const sh = V.sheets[i], H = hs[i];
    const baseSw = pw * 595 / ((V.sizes[i] || [595])[0] || 595);       // шрифт от размера страницы (а3 вдвое шире а4)
    const mine = V.items.filter((it) => it.sheet === i && it.node && it.node.isConnected && it.node.parentElement === sh && !it.node.hidden);
    // не влезает по высоте - чуть ужимаем шрифт, но не меньше 70%
    let scale = 1;
    for (let attempt = 0; attempt < 9; attempt++) {
      sh.style.setProperty('--sw', (baseSw * scale) + 'px');
      for (const ch of sh.children) { ch.style.marginTop = ''; }
      sh.style.minHeight = '0px';
      const actualTop = sh.offsetTop - base;
      // то, что не влезло на прошлых листах, съедает высоту этого - низ листа не должен уехать
      sh.style.minHeight = Math.max(48, ideal + H - actualTop) + 'px';
      let over = 0;
      for (const it of mine) {
        const want = ideal + it.y * H;
        const tbl = it.kind === 'chunk' && it.chunk.kind === 'table' ? $('.tbl', it.node) : null;
        const grid = tbl && !tbl.classList.contains('te-grid');
        // кегль и интервал как в оригинале
        const sfs = it.seg && it.seg.fs;
        it.node.style.fontSize = sfs ? (sfs * pw * scale) + 'px' : '';
        it.node.style.lineHeight = it.seg && it.seg.lh ? String(Math.max(1, it.seg.lh)) : '';
        it.node.classList.toggle('has-fs', !!sfs);
        const tbase = sfs ? 1 : 0.86;
        if (it.seg && it.seg.box) {            // у таблицы известна рамка - берём из неё край, ширину и высоту
          const sw = sh.clientWidth, padL = parseFloat(getComputedStyle(sh).paddingLeft) || 0;
          const [x0, y0, x1, y1] = it.seg.box;
          it.node.style.boxSizing = 'border-box';
          it.node.style.marginLeft = Math.round(x0 * sw - padL - 13) + 'px';
          it.node.style.width = Math.round((x1 - x0) * sw + 43) + 'px';
          if (grid) {
            // таблица не должна вылезти за рамку - ужимаем шрифт
            const target = Math.max(0, (y1 - y0) * H);
            tbl.style.height = ''; tbl.style.fontSize = sfs ? '1em' : '';
            let fs = 1;
            while (tbl.offsetHeight > target + 2 && fs > 0.55) { fs -= 0.05; tbl.style.fontSize = (tbase * fs) + 'em'; }
            tbl.style.height = target + 'px';
          }
        }
        // выравниваем по верху самой таблицы (заголовок над ней выше рамки)
        const ref = (it.seg && grid) ? tbl : it.node;
        const have = ref.getBoundingClientRect().top - top0();
        if (have < want - 1) it.node.style.marginTop = Math.round(want - have) + 'px';
        else over = Math.max(over, have - want);
        if (!it.seg && tbl && grid && it.chunk.y1 != null) tbl.style.height = Math.max(0, (it.chunk.y1 - it.y) * H) + 'px';
      }
      let bottom = 0;
      for (const it of mine) bottom = Math.max(bottom, it.node.getBoundingClientRect().bottom - top0());
      const spill = bottom + (parseFloat(getComputedStyle(sh).paddingBottom) || 0) - (ideal + H);
      if ((over <= 3 && spill <= 2) || scale <= 0.7) break;
      scale = Math.max(0.7, scale * 0.95);
    }
    ideal += H + GAP;
  }
}

function figureEl(f) {
  const fig = el('figure', { class: 'doc-fig' + ((f.box[2] - f.box[0]) * (f.box[3] - f.box[1]) > 0.9 ? ' whole' : '') });
  const img = el('img', { src: f.url, alt: `Рисунок на стр. ${f.page}`, loading: 'lazy' });
  const frac = Math.max(0.3, Math.min(1, (f.box[2] - f.box[0]) * 1.05));
  fig.style.maxWidth = (frac * 100) + '%';
  img.style.aspectRatio = `${f.w} / ${f.h}`;
  fig.appendChild(img);
  return fig;
}

function blockEl(c, it) {
  const blk = el('section', { class: 'blk' + (V.active === c.id ? ' active' : '') + (V.editing === c.id ? ' editing' : '') + (c.kind === 'table' ? ' blk-tbl' : ''), 'data-id': c.id });
  const body = el('div', { class: 'blk-body' });
  blk.appendChild(body);
  const seg = it && it.seg;
  if (seg && V.editing === c.id && it.segIdx > 0) { blk.hidden = true; return blk; }     // редактор в первом куске
  if (seg && V.editing !== c.id) { if (c.kind === 'table') fillSegment(body, c, seg, it.segIdx); else fillView(body, c, seg, it.segIdx); }
  else if (V.editing === c.id) fillEditor(body, c); else fillView(body, c);
  if (seg && it.segIdx > 0) return blk;
  const edit = el('button', { class: 'icon-btn blk-edit', type: 'button', title: 'Исправить', 'aria-label': 'Исправить' }, ICON.edit);
  edit.onclick = (e) => { e.stopPropagation(); startEdit(c.id); };
  blk.appendChild(edit);
  const tags = [];
  if (c.source === 'ocr') tags.push('<span class="chip chip-ocr">OCR</span>');
  if (c.page_to && c.page_to > c.page) tags.push(`<span class="chip">стр. ${c.page}–${c.page_to}</span>`);
  if (c.edited) tags.push('<span class="chip chip-ok">исправлено</span>');
  if (tags.length) blk.appendChild(el('div', { class: 'blk-tags' }, tags.join('')));
  blk.addEventListener('click', (ev) => {
    if (V.editing === c.id || ev.target.closest('button,input,textarea,a')) return;
    V.active = c.id; markActive();
  });
  return blk;
}

function headingLevel(c) {
  if (!c.section) return 0;
  if (c.section.startsWith('Прил')) return 1;
  return c.section.split('.').length;
}


// строки в pdf рваные - склеиваем в абзацы и убираем переносы
function paragraphs(text) {
  const raw = text.split('\n').map((l) => l.trim()).filter(Boolean);
  if (raw.length < 2) return raw;
  const maxLen = Math.max(...raw.map((l) => l.length));
  const out = [];
  for (const line of raw) {
    const prev = out.length ? out[out.length - 1] : null;
    const bullet = /^([-–—•]\s|\d{1,2}[.)]\s|[а-яa-z]\)\s|(рисунок|рис\.|таблица)\s*[А-ЯA-Z]?\.?\d)/i.test(line);
    const endsSentence = prev && /[.!?:;]$/.test(prev.text);
    const shortPrev = prev && prev.lastLen < maxLen * 0.72;
    const upper = /^[A-ZА-ЯЁ0-9]/.test(line);
    if (!prev || bullet || (shortPrev && (endsSentence || upper))) {
      out.push({ text: line, lastLen: line.length });
    } else if (/[а-яё]-$/i.test(prev.text) && /^[а-яё]/.test(line)) {
      prev.text = prev.text.slice(0, -1) + line; prev.lastLen = line.length;
    } else {
      prev.text += ' ' + line; prev.lastLen = line.length;
    }
  }
  return out.map((o) => o.text);
}

function fillSegment(body, c, seg, k) {
  const q = V.q;
  let caption = c.title;
  if (k > 0) {
    const m = /таблиц\w*\s+([^\s.,:;]+)/i.exec(c.title || '');
    caption = 'Продолжение таблицы' + (m ? ' ' + m[1] : '');
  }
  if (caption) body.appendChild(el('div', { class: 'tbl-cap' }, highlight(caption, q)));
  const rows = c.data.slice(seg.r0, seg.r1);
  if (k > 0 && seg.hdr && c.data.length) rows.unshift(c.data[0]);
  const head = (k === 0 || seg.hdr) ? 1 : 0;
  const html = rows.map((r, i) => `<tr>${r.map((cell) => (i < head ? '<th>' : '<td>') + highlight(cell, q) + (i < head ? '</th>' : '</td>')).join('')}</tr>`).join('');
  const wrap = el('div', { class: 'tbl-scroll' });
  wrap.innerHTML = `<table class="tbl">${html}</table>`;
  body.appendChild(wrap);
}

function fillView(body, c, seg = null, k = 0) {
  const q = V.q;
  if (c.kind === 'table' && c.data) {
    if (c.title) body.appendChild(el('div', { class: 'tbl-cap' }, highlight(c.title, q)));
    const wrap = el('div', { class: 'tbl-scroll' });
    const rows = c.data.map((r, i) => `<tr>${r.map((cell) => (i === 0 ? '<th>' : '<td>') + highlight(cell, q) + (i === 0 ? '</th>' : '</td>')).join('')}</tr>`).join('');
    wrap.innerHTML = `<table class="tbl">${rows}</table>`;
    body.appendChild(wrap);
    return;
  }
  const tocMode = k === 0 && /^(содержание|оглавление)$/i.test((c.title || '').trim());
  let txt = String(c.text || '');
  if (seg) txt = txt.split('\n').filter((l) => l.trim()).slice(seg.r0, seg.r1).join('\n');
  const lines = tocMode ? txt.split('\n').filter((l) => l.trim()) : paragraphs(txt);
  const lvl = k > 0 ? 0 : headingLevel(c);
  const single = lines.length === 1 && lines[0].length <= 130 && !/[.;,:]$/.test(lines[0].trim());
  const isHead = (lvl > 0 && single) || (!c.section && single && /^(содержание|оглавление)$/i.test(lines[0].trim()));
  const leadHead = lvl > 0 && lines.length > 1 && lines[0].length <= 110 && !/[.;,:]$/.test(lines[0].trim());
  lines.forEach((line, i) => {
    const p = el('p', { class: 'ln' });
    let html = highlight(line, q);
    if (i === 0 && k === 0 && c.section) html = `<span class="num">${highlight(c.section, q)}</span> ` + html;
    p.innerHTML = html;
    if (/^[-–—•]\s/.test(line)) p.classList.add('li');
    if (tocMode) p.classList.add('toc');
    if (isHead || (leadHead && i === 0)) { p.classList.add('hd', 'hd' + Math.min(lvl || 1, 4)); }
    if (i === lines.length - 1 && CAPTION_RE.test(line.trim())) p.classList.add('cap-line');
    body.appendChild(p);
  });
}

function fillEditor(body, c) {
  if (c.kind === 'table' && c.data) {
    teInit(body, c);
  } else {
    const ta = el('textarea', { class: 'ck-edit', spellcheck: 'false' });
    ta.value = c.text;
    body.appendChild(ta);
    const fit = () => { ta.style.height = 'auto'; ta.style.height = Math.min(520, ta.scrollHeight + 4) + 'px'; };
    ta.addEventListener('input', fit); setTimeout(fit, 0);
    ta.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); saveEdit(c.id); } });
  }
  const act = el('div', { class: 'ck-actions' }, '<button class="btn btn-primary btn-sm" type="button" data-save>Сохранить</button><button class="btn btn-ghost btn-sm" type="button" data-cancel>Отмена</button><span class="ck-err"></span>');
  $('[data-save]', act).onclick = () => saveEdit(c.id);
  $('[data-cancel]', act).onclick = cancelEdit;
  body.appendChild(act);
}

/* редактор таблицы */
const TE_OPS = [
  ['Строка', [
    ['rowAbove', '+ выше', 'Добавить строку выше'], ['rowBelow', '+ ниже', 'Добавить строку ниже'],
    ['rowUp', '↑', 'Переместить строку вверх'], ['rowDown', '↓', 'Переместить строку вниз'],
    ['mergeUp', 'Склеить с верхней', 'Объединить текст с верхней строкой, эту строку убрать'],
    ['mergeDown', 'Склеить с нижней', 'Объединить текст с нижней строкой, эту строку убрать'],
    ['splitRow', 'Разделить', 'Разделить строку на несколько: значения выбранной ячейки через пробел или перенос становятся отдельными строками'],
    ['rowDel', 'Удалить', 'Удалить строку']]],
  ['Столбец', [
    ['colLeft', '+ слева', 'Добавить столбец слева'], ['colRight', '+ справа', 'Добавить столбец справа'],
    ['colMoveL', '←', 'Переместить столбец влево'], ['colMoveR', '→', 'Переместить столбец вправо'],
    ['mergeLeft', 'Склеить с левым', 'Объединить текст с левым столбцом, этот столбец убрать'],
    ['mergeRight', 'Склеить с правым', 'Объединить текст с правым столбцом, этот столбец убрать'],
    ['colDel', 'Удалить', 'Удалить столбец']]],
];

function teInit(body, c) {
  if (!V.te || V.te.id !== c.id) V.te = { id: c.id, rows: c.data.map((r) => r.slice()), sel: { r: 0, c: 0 }, undo: [], orig: JSON.stringify(c.data) };
  const host = el('div', { class: 'te' });
  body.appendChild(host);
  teRender(host);
}

function teWidth() { return Math.max(1, ...V.te.rows.map((r) => r.length)); }
function teNormalize() {
  const w = teWidth();
  V.te.rows = V.te.rows.map((r) => { const x = r.slice(); while (x.length < w) x.push(''); return x; });
}
function teSync(host) {
  for (const t of $$('textarea.tc', host || $('.te'))) V.te.rows[+t.dataset.r][+t.dataset.c] = t.value;
}
function teFit(t) { t.style.height = 'auto'; t.style.height = (t.scrollHeight + 2) + 'px'; }
function teMarkSel(host) {
  const { r, c } = V.te.sel;
  for (const t of $$('textarea.tc', host)) {
    t.parentElement.classList.toggle('sel-r', +t.dataset.r === r);
    t.parentElement.classList.toggle('sel-c', +t.dataset.c === c);
    t.parentElement.classList.toggle('sel', +t.dataset.r === r && +t.dataset.c === c);
  }
  const info = $('.te-info', host);
  if (info) info.textContent = `Выбрана ячейка: строка ${r + 1} из ${V.te.rows.length}, столбец ${c + 1} из ${teWidth()}`;
}

function teRender(host, focus = false) {
  teNormalize();
  host.innerHTML = '';
  const bar = el('div', { class: 'te-bar' });
  for (const [label, ops] of TE_OPS) {
    const g = el('div', { class: 'te-group' });
    g.appendChild(el('span', { class: 'te-label', text: label }));
    for (const [op, text, hint] of ops) {
      const b = el('button', { class: 'btn btn-ghost btn-sm' + (op.endsWith('Del') ? ' te-del' : ''), type: 'button', title: hint, 'data-op': op, text });
      b.addEventListener('mousedown', (e) => e.preventDefault());       // чтобы фокус не слетал из ячейки
      b.onclick = () => teDo(host, op);
      g.appendChild(b);
    }
    bar.appendChild(g);
  }
  const g = el('div', { class: 'te-group' });
  const undo = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', title: 'Отменить последнее изменение структуры', text: 'Отменить шаг' });
  undo.disabled = !V.te.undo.length;
  undo.onclick = () => teUndo(host);
  undo.addEventListener('mousedown', (e) => e.preventDefault());
  g.appendChild(undo);
  bar.appendChild(g);
  host.appendChild(bar);
  host.appendChild(el('div', { class: 'te-info' }));

  const wrap = el('div', { class: 'tbl-scroll' });
  const tbl = el('table', { class: 'tbl te-grid' });
  const w = teWidth();
  const head = el('tr');
  head.appendChild(el('th', { class: 'te-idx' }));
  for (let ci = 0; ci < w; ci++) {
    const th = el('th', { class: 'te-idx te-col', text: String(ci + 1), title: 'Выбрать столбец' });
    th.onclick = () => teFocus(host, V.te.sel.r, ci);
    head.appendChild(th);
  }
  tbl.appendChild(head);
  V.te.rows.forEach((row, ri) => {
    const tr = el('tr');
    const idx = el('th', { class: 'te-idx te-row', text: String(ri + 1), title: 'Выбрать строку' });
    idx.onclick = () => teFocus(host, ri, V.te.sel.c);
    tr.appendChild(idx);
    row.forEach((cell, ci) => {
      const td = el(ri === 0 ? 'th' : 'td', { class: 'te-cell' });
      const t = el('textarea', { class: 'tc', rows: '1', spellcheck: 'false', 'data-r': ri, 'data-c': ci });
      t.value = cell;
      t.addEventListener('focus', () => { V.te.sel = { r: ri, c: ci }; teMarkSel(host); });
      t.addEventListener('input', () => teFit(t));
      t.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); saveEdit(V.te.id); }
        else if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); teFocus(host, Math.min(V.te.rows.length - 1, ri + 1), ci); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && V.te.undo.length) { e.preventDefault(); teUndo(host); }
      });
      t.addEventListener('paste', (e) => {
        const txt = (e.clipboardData || window.clipboardData).getData('text');
        if (!/[\t\n]/.test(txt.replace(/\n$/, ''))) return;           // обычная вставка текста
        e.preventDefault();
        teSync(host); tePush();
        const grid = txt.replace(/\r/g, '').replace(/\n$/, '').split('\n').map((l) => l.split('\t'));
        grid.forEach((gr, dr) => gr.forEach((val, dc) => {
          while (V.te.rows.length <= ri + dr) V.te.rows.push([]);
          while (V.te.rows[ri + dr].length <= ci + dc) V.te.rows[ri + dr].push('');
          V.te.rows[ri + dr][ci + dc] = val.trim();
        }));
        teNormalize(); teRender(host); teFocus(host, ri, ci);
        toast('Вставлено из буфера обмена');
      });
      td.appendChild(t); tr.appendChild(td);
    });
    tbl.appendChild(tr);
  });
  wrap.appendChild(tbl);
  host.appendChild(wrap);
  for (const t of $$('textarea.tc', host)) teFit(t);
  teMarkSel(host);
  if (focus) teFocus(host, V.te.sel.r, V.te.sel.c);
}

function teFocus(host, r, c) {
  const t = $(`textarea.tc[data-r="${r}"][data-c="${c}"]`, host);
  if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
}
function tePush() { V.te.undo.push(JSON.stringify(V.te.rows)); if (V.te.undo.length > 40) V.te.undo.shift(); }
function teUndo(host) {
  if (!V.te.undo.length) return;
  teSync(host);
  V.te.rows = JSON.parse(V.te.undo.pop());
  V.te.sel.r = Math.min(V.te.sel.r, V.te.rows.length - 1); V.te.sel.c = Math.min(V.te.sel.c, teWidth() - 1);
  teRender(host, true);
}

function teDo(host, op) {
  teSync(host);
  const T = V.te, rows = T.rows;
  let { r, c } = T.sel;
  const w = teWidth();
  const join = (a, b) => [a, b].map((x) => (x || '').trim()).filter(Boolean).join(' ');
  const blank = () => new Array(w).fill('');
  const swap = (arr, i, j) => { [arr[i], arr[j]] = [arr[j], arr[i]]; };
  const cols = (fn) => rows.forEach((row) => fn(row));
  if (op === 'rowDel' && rows.length <= 1) return toast('Нельзя удалить единственную строку', true);
  if (op === 'colDel' && w <= 1) return toast('Нельзя удалить единственный столбец', true);
  if (op === 'rowUp' && r === 0) return;
  if (op === 'rowDown' && r === rows.length - 1) return;
  if (op === 'mergeUp' && r === 0) return toast('Выше строки нет', true);
  if (op === 'mergeDown' && r === rows.length - 1) return toast('Ниже строки нет', true);
  if (op === 'colMoveL' && c === 0) return;
  if (op === 'colMoveR' && c === w - 1) return;
  if (op === 'mergeLeft' && c === 0) return toast('Левее столбца нет', true);
  if (op === 'mergeRight' && c === w - 1) return toast('Правее столбца нет', true);
  let splitParts = null;
  if (op === 'splitRow') {
    const parts = (txt) => (/\n/.test(txt) ? txt.split('\n') : txt.trim().split(/\s+/)).map((x) => x.trim()).filter(Boolean);
    const ref = parts(rows[r][c] || '');
    if (ref.length < 2) return toast('В выбранной ячейке нечего делить: нужно два и больше значений через пробел или перенос', true);
    splitParts = rows[r].map((cell, i) => { const p = parts(cell); return i === c || p.length === ref.length ? p : null; });
    splitParts.k = ref.length;
  }
  tePush();
  switch (op) {
    case 'rowAbove': rows.splice(r, 0, blank()); break;
    case 'rowBelow': rows.splice(r + 1, 0, blank()); r += 1; break;
    case 'splitRow': {
      const k = splitParts.k;
      const made = [];
      for (let j = 0; j < k; j++) made.push(rows[r].map((cell, i) => (splitParts[i] ? splitParts[i][j] : (j === 0 ? cell : ''))));
      rows.splice(r, 1, ...made);
      break;
    }
    case 'rowDel': rows.splice(r, 1); r = Math.min(r, rows.length - 1); break;
    case 'rowUp': swap(rows, r, r - 1); r -= 1; break;
    case 'rowDown': swap(rows, r, r + 1); r += 1; break;
    case 'mergeUp': rows[r - 1] = rows[r - 1].map((v, i) => join(v, rows[r][i])); rows.splice(r, 1); r -= 1; break;
    case 'mergeDown': rows[r + 1] = rows[r + 1].map((v, i) => join(rows[r][i], v)); rows.splice(r, 1); break;
    case 'colLeft': cols((row) => row.splice(c, 0, '')); break;
    case 'colRight': cols((row) => row.splice(c + 1, 0, '')); c += 1; break;
    case 'colDel': cols((row) => row.splice(c, 1)); c = Math.min(c, w - 2); break;
    case 'colMoveL': cols((row) => swap(row, c, c - 1)); c -= 1; break;
    case 'colMoveR': cols((row) => swap(row, c, c + 1)); c += 1; break;
    case 'mergeLeft': cols((row) => { row[c - 1] = join(row[c - 1], row[c]); row.splice(c, 1); }); c -= 1; break;
    case 'mergeRight': cols((row) => { row[c + 1] = join(row[c], row[c + 1]); row.splice(c, 1); }); break;
    default: break;
  }
  T.sel = { r: Math.max(0, Math.min(r, rows.length - 1)), c: Math.max(0, Math.min(c, teWidth() - 1)) };
  teRender(host, true);
}

function blockNode(id) { return $(`.blk[data-id="${id}"]`, $('#vParse')); }

function blockNodes(id) { return $$(`.blk[data-id="${id}"]`, $('#vParse')); }

function replaceBlock(id) {
  const c = V.chunks.find((x) => x.id === id);
  const its = V.items.filter((x) => x.chunk && x.chunk.id === id);
  if (!c || !its.length) return;
  const figs = (V.attach[id] || []).map((it) => it.node);
  // число кусков меняется только при переразборе, при правке куски те же, строки пересчитал сервер
  its.forEach((it, k) => {
    const old = it.node;
    if (!old || !old.isConnected) return;
    if (it.seg && c.geom && c.geom[it.segIdx]) it.seg = c.geom[it.segIdx];
    const fresh = blockEl(c, it);
    old.replaceWith(fresh);
    it.node = fresh;
  });
  const last = its[its.length - 1].node;
  const anchor = $('.cap-line', last);
  for (const f of figs) { if (anchor) anchor.before(f); else last.appendChild(f); }
  alignAll();
}

function startEdit(id) {
  if (V.editing && V.editing !== id) { const prev = V.editing; V.editing = null; replaceBlock(prev); }
  V.te = null;
  V.editing = id; V.active = id;
  replaceBlock(id); markActive();
  const f = $('textarea, input', blockNode(id)); if (f) f.focus();
}
function cancelEdit() { const id = V.editing; V.editing = null; V.te = null; if (id) replaceBlock(id); }
async function saveEdit(id) {
  const blk = blockNode(id);
  const c = V.chunks.find((x) => x.id === id);
  if (c.kind === 'table' && c.data) teSync($('.te', blk));
  const payload = (c.kind === 'table' && c.data) ? { rows: V.te.rows } : { text: $('textarea', blk).value };
  try {
    const upd = await api('PATCH', `/api/chunks/${id}`, payload);
    const y = c.y;
    Object.assign(c, upd); c.y = y;
    V.editing = null; V.te = null;
    replaceBlock(id);
    toast('Сохранено, поиск обновлён');
  } catch (e) { $('.ck-err', blk).textContent = e.message; }
}

function markActive() {
  for (const n of $$('.blk', $('#vParse'))) n.classList.toggle('active', Number(n.dataset.id) === V.active);
}

/* синхронная прокрутка */
function relTop(node, container) {
  return node.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
}

// якоря: (где в левой панели, где в документе в страницах)
function computeAnchors() {
  if (!V || !$('#vParse') || !$('#vPageScroll')) return;
  const left = $('#vParse');
  const pts = [{ top: 0, pos: 0 }];
  for (const it of V.items) {
    if (!it.node || !it.node.isConnected) continue;
    pts.push({ top: relTop(it.node, left), pos: Math.max(0, it.pos), mark: it.kind === 'sheet' });
  }
  // конец левой = конец правой, иначе последние экраны не доезжают
  const right = $('#vPageScroll');
  const endTop = Math.max(1, left.scrollHeight - left.clientHeight + 6);
  const endPos = rightToPos(Math.max(0, right.scrollHeight - right.clientHeight) + 6);
  for (let i = pts.length - 1; i > 0; i--) if (pts[i].top >= endTop) pts.splice(i, 1);
  pts.push({ top: endTop, pos: endPos });
  pts.sort((a, b) => a.top - b.top);
  // метка страницы рядом с абзацем даёт скачок - оставляем только абзац пройдёт страницу
  for (let i = pts.length - 2; i > 0; i--) {
    if (pts[i].mark && pts[i + 1].top - pts[i].top < 60 && pts[i + 1].pos - pts[i].pos > 0.02) pts.splice(i, 1);
  }
  let m = 0;
  for (const p of pts) { m = Math.max(m, p.pos); p.pos = m; }
  V.anchors = pts;
}

function pagesGeom() {
  const g = [];
  const sc = $('#vPageScroll');
  for (const pg of $$('.pg', sc)) g.push({ top: relTop(pg, sc), h: pg.offsetHeight });
  return g;
}
function posToRight(pos) {
  const g = pagesGeom(); if (!g.length) return 0;
  const i = Math.max(0, Math.min(g.length - 1, Math.floor(pos)));
  return g[i].top + Math.min(1, Math.max(0, pos - i)) * g[i].h;
}
function rightToPos(top) {
  const g = pagesGeom(); if (!g.length) return 0;
  let i = 0;
  while (i + 1 < g.length && g[i + 1].top <= top) i++;
  return i + Math.min(1, Math.max(0, (top - g[i].top) / (g[i].h || 1)));
}
function leftToPos(top) {
  const a = V.anchors;
  if (a.length < 2) return 0;
  let i = 0;
  while (i + 1 < a.length - 1 && a[i + 1].top <= top) i++;
  const p = a[i], n = a[i + 1];
  const span = n.top - p.top;
  return p.pos + (span > 0 ? Math.min(1, Math.max(0, (top - p.top) / span)) : 0) * (n.pos - p.pos);
}
function posToLeft(pos) {
  const a = V.anchors;
  if (a.length < 2) return 0;
  let i = 0;
  while (i + 1 < a.length - 1 && a[i + 1].pos <= pos) i++;
  const p = a[i], n = a[i + 1];
  const span = n.pos - p.pos;
  return p.top + (span > 0 ? Math.min(1, Math.max(0, (pos - p.pos) / span)) : 0) * (n.top - p.top);
}

function setScroll(elm, top) {
  V.ign.set(elm, performance.now() + 140);
  elm.scrollTop = Math.max(0, top);
}
function curPage() { return Math.max(1, Math.min(V.doc.pages || 1, Math.floor(rightToPos($('#vPageScroll').scrollTop + 4) + 1e-6) + 1)); }

function wireSync() {
  const left = $('#vParse'), right = $('#vPageScroll');
  const guard = (elm) => performance.now() < (V.ign.get(elm) || 0);
  left.addEventListener('scroll', () => {
    if (guard(left)) return;
    setScroll(right, posToRight(leftToPos(left.scrollTop + 6)));
    updatePager();
  }, { passive: true });
  right.addEventListener('scroll', () => {
    if (guard(right)) return;
    setScroll(left, posToLeft(rightToPos(right.scrollTop + 6)));
    updatePager();
  }, { passive: true });
  let raf = 0;
  const recalc = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { computeAnchors(); }); };
  V.ro = new ResizeObserver(() => {
    if (Math.abs(pageWidthPx() - (V.pw || 0)) > 0.5) alignAll();
    recalc();
  });
  V.ro.observe($('.pages.sheets', left));
  V.ro.observe($('.pages', right));
  computeAnchors();
  updatePager();
}

function updatePager() {
  const total = V.doc.pages || 1;
  const n = curPage();
  $('#vPg').textContent = `стр. ${n} / ${total}`;
  $('#vPgPrev').disabled = n <= 1; $('#vPgNext').disabled = n >= total;
}
function gotoPage(n) {
  const total = V.doc.pages || 1;
  n = Math.max(1, Math.min(total, n));
  computeAnchors();
  const mark = V.items.find((x) => x.kind === 'sheet' && x.page === n && x.node && x.node.isConnected);
  const left = $('#vParse');
  setScroll($('#vPageScroll'), posToRight(n - 1));
  setScroll(left, mark ? relTop(mark.node, left) - 6 : posToLeft(n - 1));
  updatePager();
}

function scrollToChunk(id) {
  const it = V.items.find((x) => x.chunk && x.chunk.id === id);
  if (!it) return;
  computeAnchors();
  const left = $('#vParse');
  setScroll(left, relTop(it.node, left) - 14);
  setScroll($('#vPageScroll'), posToRight(it.pos) - 14);
  updatePager();
}

function scrollToHit(h, markEl, blk) {
  computeAnchors();
  const right = $('#vPageScroll'), left = $('#vParse');
  const pg = pgEl(h.page);
  if (pg) setScroll(right, relTop(pg, right) + h.boxes[0][1] * pg.offsetHeight - right.clientHeight / 3);
  const target = markEl || blk;
  if (target) {
    const top = relTop(target, left);
    setScroll(left, top - left.clientHeight / 3);
  }
  updatePager();
}

/* подсветка справа */
function renderBoxes() {
  const note = $('#vPageNote');
  const total = V.hits.length;
  note.textContent = V.q ? (total ? `совпадений в документе: ${total}` : 'совпадений нет') : '';
  for (const b of $$('.page-boxes', $('#vPageScroll'))) b.innerHTML = '';
  V.hits.forEach((h, i) => {
    const pg = pgEl(h.page);
    if (!pg) return;
    const boxes = $('.page-boxes', pg);
    for (const b of h.boxes) {
      const pad = 0.002;
      const d = el('div', { class: 'hit' + (i === V.idx ? ' cur' : '') });
      d.style.left = ((b[0] - pad) * 100) + '%'; d.style.top = ((b[1] - pad) * 100) + '%';
      d.style.width = ((b[2] - b[0] + 2 * pad) * 100) + '%'; d.style.height = ((b[3] - b[1] + 2 * pad) * 100) + '%';
      boxes.appendChild(d);
    }
  });
}

/* поиск внутри документа */
async function runFind(initial) {
  const seq = ++V.findSeq;
  const q = V.q;
  if (!q) { V.hits = []; V.idx = 0; updateCount(); rerenderBlocks(); renderBoxes(); return; }
  const chunkParam = initial && V.startChunk ? `&chunk=${V.startChunk}` : '';
  let data;
  try { data = await api('GET', `/api/docs/${V.doc.id}/find?q=${encodeURIComponent(q)}${chunkParam}`); } catch (e) { return; }
  if (!V || seq !== V.findSeq) return;
  V.hits = data.hits; V.mode = data.mode;
  V.idx = Math.min(data.start || 0, Math.max(0, data.hits.length - 1));
  updateCount();
  rerenderBlocks();
  renderBoxes();
  if (V.hits.length) showHit(V.idx, true);
}
function rerenderBlocks() {
  for (const c of V.chunks) if (c.id !== V.editing) replaceBlock(c.id);
  alignAll();
  markActive();
}
function updateCount() {
  const c = $('#vCount');
  if (!c) return;
  c.classList.remove('none');
  if (!V.q) c.textContent = '';
  else if (!V.hits.length) { c.textContent = 'нет совпадений'; c.classList.add('none'); }
  else c.textContent = `${V.idx + 1} из ${V.hits.length}` + (V.mode === 'any' ? ' (по словам)' : '');
  $('#vPrev').disabled = $('#vNext').disabled = V.hits.length < 2;
}
function stepHit(dir) {
  if (!V.hits.length) return;
  showHit((V.idx + dir + V.hits.length) % V.hits.length, true);
}
function showHit(i, scroll) {
  const h = V.hits[i];
  V.idx = i;
  updateCount();
  if (h.chunk) V.active = h.chunk;
  markActive();
  for (const [k, d] of $$('.page-boxes .hit', $('#vPageScroll')).entries()) d.classList.remove('cur');
  // текущее - оранжевое
  const pg = pgEl(h.page);
  if (pg) {
    const all = V.hits.map((x, k) => ({ x, k })).filter((o) => o.x.page === h.page);
    let nodeIdx = 0;
    for (const o of all) { if (o.k === i) break; nodeIdx += o.x.boxes.length; }
    const nodes = $$('.hit', $('.page-boxes', pg));
    for (let k = 0; k < h.boxes.length; k++) if (nodes[nodeIdx + k]) nodes[nodeIdx + k].classList.add('cur');
  }
  for (const m of $$('mark.cur', $('#vParse'))) m.classList.remove('cur');
  const blk = h.chunk ? blockNode(h.chunk) : null;
  let markEl = null;
  if (blk) {
    const before = V.hits.slice(0, i).filter((x) => x.chunk === h.chunk).length;
    const marks = blockNodes(h.chunk).flatMap((b) => $$('mark', b));
    markEl = marks[Math.min(before, marks.length - 1)] || null;
    if (markEl) markEl.classList.add('cur');
  }
  if (scroll) scrollToHit(h, markEl, blk);
}


/* ---- название, мастер, настройки ---- */
const fmtBytes = (n) => {
  n = Number(n) || 0;
  const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : 1)) + ' ' + u[i];
};

function applyBrand() {
  const name = state.cfg.app_name || 'Хранилище документов';
  const b = $('#brandName'); if (b) b.textContent = name;
  document.title = name;
}

function runWizard() {
  return new Promise((resolve) => {
    const ov = el('div', { class: 'wiz-overlay' });
    const card = el('div', { class: 'wiz' });
    ov.appendChild(card);
    $('#dialogHost').appendChild(ov);
    const ocrOk = !!(state.cfg.ocr_available && state.cfg.ocr_available.engine);
    const W = { i: 0, mode: 'storage', name: state.cfg.app_name, root: '', probe: null, auto_sort: false, scan_interval: 30, ocr: ocrOk, trash: true };
    const stepsOf = () => (W.mode === 'storage' ? ['name', 'path', 'opts'] : ['name', 'opts']);

    const frame = (title, lead, body, { next = 'Далее', back = true, nextOff = false, onNext } = {}) => {
      const steps = stepsOf();
      card.innerHTML = '';
      card.appendChild(el('div', { class: 'wiz-steps' }, steps.map((_, k) => `<i class="${k <= W.i ? 'on' : ''}"></i>`).join('')));
      card.appendChild(el('h2', { text: title }));
      if (lead) card.appendChild(el('p', { text: lead }));
      card.appendChild(body);
      const err = el('div', { class: 'wiz-err' });
      card.appendChild(err);
      const foot = el('div', { class: 'wiz-foot' });
      const bb = el('button', { class: 'btn btn-ghost', type: 'button', text: 'Назад' });
      bb.style.visibility = back && W.i > 0 ? 'visible' : 'hidden';
      bb.onclick = () => { W.i--; draw(); };
      const nb = el('button', { class: 'btn btn-primary', type: 'button', text: next });
      nb.disabled = nextOff;
      nb.onclick = async () => {
        nb.disabled = true;
        err.textContent = '';
        try { await onNext(err); } catch (e) { err.textContent = e.message; }
        nb.disabled = false;
      };
      foot.appendChild(bb); foot.appendChild(nb);
      card.appendChild(foot);
      return { err, nb };
    };

    const stepName = () => {
      const body = el('div', { style: 'display:flex;flex-direction:column;gap:14px' });
      body.innerHTML = `<label class="fld">Название хранилища (показывается вверху, его можно поменять в настройках)
          <input class="dlg-input" id="wzName" maxlength="40" value="${esc(W.name)}"></label>
        <div class="wiz-choice">
          <div class="wiz-card ${W.mode === 'storage' ? 'sel' : ''}" data-m="storage"><b>Подключить мою папку</b><span>Папки и PDF берутся с диска как есть, файлы не копируются и не меняются. Поиск строится по ним.</span></div>
          <div class="wiz-card ${W.mode === 'demo' ? 'sel' : ''}" data-m="demo"><b>Учебный набор</b><span>Готовые папки и 54 учебных документа, чтобы посмотреть, как всё работает.</span></div>
        </div>`;
      for (const c of $$('.wiz-card', body)) c.onclick = () => { W.name = $('#wzName').value; W.mode = c.dataset.m; W.auto_sort = W.mode === 'demo'; draw(); };
      frame('Первая настройка', 'Хранилище работает как оболочка над обычной папкой: подключите её, и документы будут распознаны, дерево папок повторит дерево на диске, а поиск пойдёт по содержимому.', body, {
        onNext: async (err) => {
          const v = $('#wzName').value.trim();
          if (!v) { err.textContent = 'Введите название'; return; }
          W.name = v; W.i++; draw();
        },
      });
      setTimeout(() => { const i = $('#wzName'); if (i) i.focus(); }, 0);
    };

    const stepPath = () => {
      const body = el('div', { style: 'display:flex;flex-direction:column;gap:10px' });
      body.innerHTML = `<div class="wiz-pathrow"><input class="dlg-input" id="wzPath" placeholder="Например D:\\Документы, \\\\сервер\\общая или /home/user/docs" value="${esc(W.root)}">
          <button class="btn btn-ghost" id="wzGo" type="button">Показать</button></div>
        <div class="wiz-browse" id="wzBrowse"></div><div id="wzProbe"></div>`;
      const fr = frame('Где лежат документы', 'Укажите папку целиком: вложенные папки станут деревом слева, PDF и Word внутри будут распознаны. Можно ввести путь (в том числе сетевой, например \\\\сервер\\общая) или выбрать папку в списке.', body, {
        nextOff: !W.probe,
        onNext: async () => { W.i++; draw(); },
      });
      const box = $('#wzBrowse', body), pr = $('#wzProbe', body);
      const showProbe = (p) => {
        W.probe = p;
        W.root = p.path;
        $('#wzPath').value = p.path;
        pr.innerHTML = `<div class="wiz-probe ${p.writable && p.pdfs ? '' : 'warn'}">Выбрана: <b>${esc(p.path)}</b><br>Найдено: папок ${p.dirs}${p.capped ? '+' : ''}, файлов PDF и Word ${p.pdfs}${p.capped ? '+' : ''} (${fmtBytes(p.size)}).` +
          `${p.pdfs ? '' : ' Документов пока нет, они подхватятся, как только появятся.'}${/^(\\\\|\/\/)/.test(p.path) ? ' Сетевая папка: если связь пропадёт, уже распознанное сохранится, а проверка продолжится после восстановления.' : ''}${p.writable ? '' : ' Папка только для чтения: создавать, переносить и загружать файлы не получится.'}</div>`;
        fr.nb.disabled = false;
      };
      const choose = async (path) => {
        try { showProbe(await api('GET', '/api/fs/probe?path=' + encodeURIComponent(path))); }
        catch (e) { pr.innerHTML = `<div class="wiz-probe warn">${esc(e.message)}</div>`; fr.nb.disabled = true; W.probe = null; }
      };
      const list = async (path) => {
        let r;
        try { r = await api('GET', '/api/fs/list?path=' + encodeURIComponent(path || '')); }
        catch (e) { box.innerHTML = `<div class="br-cur">${esc(e.message)}</div>`; return; }
        box.innerHTML = '';
        box.appendChild(el('div', { class: 'br-cur', text: r.path || 'Диски и домашняя папка' }));
        if (!r.path && r.net_hint) box.appendChild(el('div', { class: 'br-item', style: 'cursor:default;color:var(--fg-faint);white-space:normal' }, 'Сетевая папка: введите путь вида \\\\сервер\\общая в поле выше и нажмите «Показать».'));
        if (r.path) {
          const use = el('div', { class: 'br-item' }, `<b>Выбрать эту папку</b><span style="color:var(--fg-faint)">Файлов здесь: ${r.pdfs}</span>`);
          use.onclick = () => choose(r.path);
          box.appendChild(use);
          const up = el('div', { class: 'br-item' }, ICON.folder + ' ..');
          up.onclick = () => list(r.parent || '');
          box.appendChild(up);
        }
        for (const d of r.dirs) {
          const it = el('div', { class: 'br-item' }, ICON.folder + ' ' + esc(d.name));
          it.onclick = () => list(d.path);
          box.appendChild(it);
        }
        if (!r.dirs.length && r.path) box.appendChild(el('div', { class: 'br-item', style: 'cursor:default;color:var(--fg-faint)' }, 'Вложенных папок нет'));
      };
      $('#wzGo', body).onclick = async () => { const v = $('#wzPath').value.trim(); if (v) { await list(v); await choose(v); } };
      $('#wzPath', body).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#wzGo').click(); } });
      list(W.root || '');
      if (W.probe) showProbe(W.probe);
    };

    const stepOpts = () => {
      const st = W.mode === 'storage';
      const body = el('div', {});
      const opt = (title, hint, ctrl) => `<div class="wiz-opt"><div class="o-txt"><b>${title}</b><small>${hint}</small></div>${ctrl}</div>`;
      body.innerHTML =
        opt('Автосортировка', st ? 'Файлы, которые попадают в папку «Входящие» (загрузкой или копированием), раскладываются по другим папкам хранилища по содержанию. Папка «Входящие» создаётся при необходимости. Выключено: ничего не переносится.' : 'Загруженные файлы раскладываются по папкам по содержанию.',
          `<label class="switch"><input type="checkbox" id="wzAuto" ${W.auto_sort ? 'checked' : ''}></label>`) +
        (st ? opt('Проверять папку на изменения', 'Файлы, добавленные, перенесённые или удалённые снаружи (в проводнике, через синхронизацию), подхватываются сами.',
          `<select id="wzScan">${[[10, 'каждые 10 секунд'], [30, 'каждые 30 секунд'], [300, 'каждые 5 минут'], [0, 'только вручную']].map(([v, t]) => `<option value="${v}" ${W.scan_interval === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`) : '') +
        (st ? opt('Удаление через корзину', 'Удалённые в программе файлы и папки уходят в скрытую папку .handbook_trash внутри хранилища, а не стираются насовсем.',
          `<label class="switch"><input type="checkbox" id="wzTrash" ${W.trash ? 'checked' : ''}></label>`) : '');
      frame('Настройки', 'Всё это можно изменить позже в настройках (шестерёнка вверху).', body, {
        next: st ? 'Подключить и распознать' : 'Запустить учебный набор',
        onNext: async (err) => {
          W.auto_sort = $('#wzAuto').checked;
          if (st) { W.scan_interval = +$('#wzScan').value; W.trash = $('#wzTrash').checked; }
          W.ocr = true;
          try {
            state.cfg = await api('POST', '/api/setup', { mode: W.mode, app_name: W.name, root: W.root, auto_sort: W.auto_sort, scan_interval: W.scan_interval, ocr: W.ocr, trash: W.trash });
            ov.remove();
            resolve();
          } catch (e) { err.textContent = e.message; }
        },
      });
    };

    function draw() {
      const k = stepsOf()[W.i];
      if (k === 'name') stepName(); else if (k === 'path') stepPath(); else stepOpts();
    }
    draw();
  });
}

async function openSettings() {
  const c = state.cfg;
  const st = c.mode === 'storage';
  const ocrOk = !!(c.ocr_available && c.ocr_available.engine);
  const row = (title, hint, ctrl) => `<div class="wiz-opt"><div class="o-txt"><b>${title}</b><small>${hint}</small></div>${ctrl}</div>`;
  const body = `<label class="fld" style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--fg-muted);margin-bottom:8px">Название
      <input class="dlg-input" id="stName" maxlength="40" value="${esc(c.app_name)}"></label>
    <div class="set-info">${st ? 'Подключена папка: <b>' + esc(c.root) + '</b>' : 'Учебный набор документов'}</div>` +
    row('Автосортировка', st ? 'Новые файлы во «Входящих» раскладываются по другим папкам по содержанию.' : 'Загруженные файлы раскладываются по содержанию.',
      `<label class="switch"><input type="checkbox" id="stAuto" ${c.auto_sort ? 'checked' : ''}></label>`) +
    (st ? row('Проверка изменений', 'Как часто смотреть, что изменилось в папке снаружи.',
      `<select id="stScan">${[[10, '10 секунд'], [30, '30 секунд'], [300, '5 минут'], [0, 'вручную']].map(([v, t]) => `<option value="${v}" ${c.scan_interval === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`) : '') +
    row('Распознавание сканов', ocrOk ? 'Действует на файлы, которые обрабатываются дальше. Уже разобранные файлы можно перераспознать в просмотрщике.' : 'Tesseract не найден: сканы остаются картинками и в поиск не попадают.',
      `<label class="switch"><input type="checkbox" id="stOcr" ${c.ocr ? 'checked' : ''} ${ocrOk ? '' : 'disabled'}></label>`) +
    (st ? row('Удаление через корзину', 'Удалённое уходит в .handbook_trash внутри хранилища.',
      `<label class="switch"><input type="checkbox" id="stTrash" ${c.trash ? 'checked' : ''}></label>`) : '') +
    `<div class="set-actions">${st ? '<button class="btn btn-ghost" type="button" id="stRescan">Проверить папку сейчас</button>' : ''}<button class="btn btn-ghost" type="button" id="stChange" style="color:var(--bad-fg)">Сменить хранилище…</button></div>`;
  const ok = await dialog({
    title: 'Настройки', ok: 'Сохранить', bodyHtml: body,
    onMount: (d) => {
      d.classList.add('wide');
      const re = $('#stRescan', d);
      if (re) re.onclick = async () => {
        re.disabled = true;
        try { const r = await api('POST', '/api/storage/rescan'); toast(r.changed ? 'Найдены изменения, список обновлён' : 'Изменений нет'); await refresh({ quiet: true }); } catch (e) { toast(e.message, true); }
        re.disabled = false;
      };
      $('#stChange', d).onclick = async () => {
        const sure = await dialog({ title: 'Сменить хранилище?', ok: 'Отключить', danger: true,
          bodyHtml: '<p style="margin:0;line-height:1.5">Текущее хранилище будет отключено, индекс поиска и ручные правки распознанного удалятся. Сами файлы не затрагиваются. Затем откроется мастер подключения.</p>' });
        if (!sure) return;
        try { await api('POST', '/api/setup/reset'); location.reload(); } catch (e) { toast(e.message, true); }
      };
    },
    validate: async (d) => {
      const payload = { app_name: $('#stName', d).value, auto_sort: $('#stAuto', d).checked };
      if (!$('#stOcr', d).disabled) payload.ocr = $('#stOcr', d).checked;
      if (st) { payload.scan_interval = +$('#stScan', d).value; payload.trash = $('#stTrash', d).checked; }
      try { state.cfg = await api('PATCH', '/api/config', payload); } catch (e) { return e.message; }
      return null;
    },
  });
  if (ok) {
    applyBrand();
    state.auto = state.cfg.auto_sort;
    $('#autoSort').checked = state.auto;
    toast('Настройки сохранены');
  }
}

let lastRev = null;
async function pollStatus() {
  let s;
  try { s = await api('GET', '/api/status'); } catch { return; }
  const u = s.usage || {};
  const fill = $('#stFill'), txt = $('#stText'), path = $('#stPath');
  if (fill && u.total) fill.style.width = Math.min(100, Math.max(1, 100 * (u.total - u.free) / u.total)) + '%';
  const legacy = s.legacy_doc || 0;
  if (txt) {
    txt.textContent = `Документы: ${fmtBytes(u.used)} · свободно на диске ${fmtBytes(u.free)}` + (legacy ? ` · .doc пропущено: ${legacy}` : '');
    txt.title = legacy ? `Старый формат .doc не читается, пересохраните как .docx:\n${(s.legacy_examples || []).join('\n')}${legacy > 5 ? '\n...' : ''}` : '';
  }
  if (legacy && legacy !== state.lastLegacy) toast(`Файлов .doc пропущено: ${legacy}. Пересохраните их как .docx`, true);
  state.lastLegacy = legacy;
  if (path) path.textContent = s.root || '';
  if (s.storage_error && s.storage_error !== state.lastStErr) toast(s.storage_error, true);
  state.lastStErr = s.storage_error;
  if (lastRev !== null && s.rev !== lastRev && !V) await refresh({ quiet: true }).catch(() => {});
  lastRev = s.rev;
}

/* ---- запуск ---- */
async function init() {
  try { state.cfg = await api('GET', '/api/config'); } catch (e) { toast('Не удалось связаться с сервером: ' + e.message, true); return; }
  if (!state.cfg.configured) { await runWizard(); store.set('cur', ROOT); }
  applyBrand();
  state.expanded = new Set(store.get('expanded', ['tk', 'ot']));
  state.auto = !!state.cfg.auto_sort;
  state.cur = store.get('cur', ROOT);
  const sw = $('#autoSort');
  sw.checked = state.auto;
  sw.onchange = async () => {
    state.auto = sw.checked;
    try { state.cfg = await api('PATCH', '/api/config', { auto_sort: state.auto }); } catch (e) { toast(e.message, true); }
    toast(state.auto ? 'Автосортировка включена: файлы раскладываются по содержанию' : 'Автосортировка выключена: файлы попадают в открытую папку');
  };
  $('#settingsBtn').onclick = openSettings;
  $('#newFolderBtn').onclick = createFolder;
  $('#reparseAllBtn').onclick = () => reparseFolder(state.cur === ROOT ? null : state.cur, (state.folders.find((f) => f.id === state.cur) || {}).name);
  $('#uploadBtn').onclick = () => $('#fileInput').click();
  $('#fileInput').onchange = (e) => { const fs = [...e.target.files]; e.target.value = ''; if (fs.length) uploadFiles(fs); };
  $('#sortInboxBtn').onclick = async () => {
    try { const r = await api('POST', '/api/autosort/inbox'); await refresh({ quiet: true }); toast(`Распределено: ${r.moved}, осталось во «Входящих»: ${r.left}`); }
    catch (e) { toast(e.message, true); }
  };
  wireSearch(); wireContentDrop();
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && !V) { e.preventDefault(); searchInput().focus(); searchInput().select(); }
  });
  try { await refresh({ quiet: true }); } catch (e) { toast('Не удалось загрузить данные: ' + e.message, true); }
  await pollStatus();
  setInterval(pollStatus, 6000);
}
init();
})();
