/* Agente Comercial Postobón — lógica del frontend.
   Seguridad: TODO el contenido dinámico se inserta con textContent / createElement.
   Nunca se usa innerHTML con datos del servidor ni del modelo (prevención de XSS). */
(() => {
  'use strict';

  const PALETA = ['#D71920', '#0B2A5B', '#F59E0B', '#10B981', '#6366F1', '#EC4899', '#14B8A6', '#8B5CF6', '#64748B', '#F97316'];
  const $ = (id) => document.getElementById(id);
  const TITULOS = { chat: 'Chat con el agente', analisis: 'Análisis comercial', ventas: 'Archivos de ventas', documentos: 'Documentos y conocimiento', informes: 'Informes comerciales' };
  const SUGERENCIAS = [
    '¿Cuáles son los 5 productos más vendidos?', 'Ventas por canal', 'Compara el último mes con el anterior',
    '¿Qué tendencias comerciales hay por categoría?', 'Oportunidades de mejora', 'Genera un informe comercial',
    '¿Cuál es la misión de Postobón?', '¿Qué marcas tiene en aguas?', '¿Qué dice la política sobre descuentos?',
  ];

  let sessionId = localStorage.getItem('posto_session') || nuevaSesion();
  let charts = { chat: [], dash: [], report: [] };
  let ocupado = false;

  function nuevaSesion() {
    const id = 'web_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
    localStorage.setItem('posto_session', id);
    return id;
  }

  /* ---------- utilidades DOM y formato ---------- */
  function el(tag, cls, texto) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texto !== undefined && texto !== null) n.textContent = String(texto);
    return n;
  }
  const nf = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 1 });
  function fmt(v, formato) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v !== 'number') return String(v);
    if (formato === 'moneda') return '$' + nf.format(v);
    if (formato === 'porcentaje') return nf1.format(v) + '%';
    return nf.format(v);
  }
  function fmtCorto(v) {
    const a = Math.abs(v);
    if (a >= 1e9) return nf1.format(v / 1e9) + ' MM';
    if (a >= 1e6) return nf1.format(v / 1e6) + ' M';
    if (a >= 1e3) return nf1.format(v / 1e3) + ' k';
    return nf.format(v);
  }
  function toast(msg, tipo) {
    const t = el('div', 'toast ' + (tipo || ''), msg);
    $('toasts').appendChild(t);
    setTimeout(() => t.remove(), 5200);
  }
  async function api(ruta, opts) {
    let r;
    try { r = await fetch(ruta, opts); } catch (e) { throw new Error('No hay conexión con el servidor.'); }
    if (!r.ok) {
      let d = r.statusText;
      try {
        const j = await r.json();
        d = j.detail ? (typeof j.detail === 'string' ? j.detail : (j.detail.mensaje || JSON.stringify(j.detail))) : (j.error || d);
        if (Array.isArray(j.detail)) d = j.detail.map((x) => x.msg).join('; ');
      } catch (_) { /* sin cuerpo JSON */ }
      const err = new Error(d); err.status = r.status; throw err;
    }
    return r.json();
  }
  function limpiarCharts(grupo) { (charts[grupo] || []).forEach((c) => c.destroy()); charts[grupo] = []; }
  function rutaInterna(url) { return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//'); }
  function vaciar(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  /* ---------- texto seguro (negritas y listas sin HTML) ---------- */
  function renderTexto(texto) {
    const cont = el('div', 'b-texto');
    const bloques = String(texto || '').split(/\n{2,}/);
    bloques.forEach((bl) => {
      const lineas = bl.split('\n').filter((l) => l.trim() !== '');
      if (!lineas.length) return;
      const esLista = lineas.every((l) => /^\s*([-•*]|\d+[.)])\s+/.test(l));
      if (esLista) {
        const ul = el('ul');
        lineas.forEach((l) => { const li = el('li'); inline(li, l.replace(/^\s*([-•*]|\d+[.)])\s+/, '')); ul.appendChild(li); });
        cont.appendChild(ul);
      } else {
        const p = el('p'); inline(p, lineas.join('\n')); cont.appendChild(p);
      }
    });
    return cont;
  }
  function inline(padre, txt) {
    txt.split(/(\*\*[^*]+\*\*)/g).forEach((parte) => {
      if (/^\*\*[^*]+\*\*$/.test(parte)) padre.appendChild(el('strong', '', parte.slice(2, -2)));
      else if (parte) padre.appendChild(document.createTextNode(parte));
    });
  }

  /* ---------- bloques ---------- */
  function renderBloque(b, grupo) {
    switch (b.tipo) {
      case 'texto': return renderTexto(b.texto);
      case 'resumen': { const d = el('div', 'b-resumen'); d.appendChild(el('h4', '', b.titulo)); d.appendChild(el('p', '', b.texto)); return d; }
      case 'kpis': return renderKpis(b.tarjetas, 'b-kpis');
      case 'tabla': return renderTabla(b);
      case 'grafico': return renderGrafico(b.grafico, grupo);
      case 'alerta': {
        const d = el('div', 'alerta ' + (b.nivel || 'info'));
        d.appendChild(el('b', '', b.titulo)); d.appendChild(document.createTextNode(b.texto || ''));
        if (b.accion) d.appendChild(el('span', 'accion', 'Acción recomendada: ' + b.accion));
        return d;
      }
      case 'lista': {
        const d = el('div', 'b-lista');
        if (b.titulo) d.appendChild(el('h4', '', b.titulo));
        const l = el(b.ordenada ? 'ol' : 'ul');
        (b.items || []).forEach((i) => l.appendChild(el('li', '', i)));
        d.appendChild(l); return d;
      }
      case 'fuentes': {
        const d = el('div', 'fuentes'); d.appendChild(el('span', '', 'Fuentes:'));
        (b.fuentes || []).forEach((f) => d.appendChild(el('span', 'chip', f)));
        return d;
      }
      case 'descarga': {
        if (!rutaInterna(b.url)) return null;
        const a = el('a', 'btn btn-primary descarga', '⬇ ' + b.etiqueta);
        a.href = b.url; a.setAttribute('download', '');
        return a;
      }
      default: return null;
    }
  }
  function renderBloques(bloques, grupo) {
    const frag = document.createDocumentFragment();
    (bloques || []).forEach((b) => { const n = renderBloque(b, grupo); if (n) frag.appendChild(n); });
    return frag;
  }
  function renderKpis(tarjetas, cls) {
    const g = el('div', cls || 'kpi-grid');
    (tarjetas || []).forEach((t) => {
      const k = el('div', 'kpi');
      k.appendChild(el('div', 'k-t', t.titulo));
      k.appendChild(el('div', 'k-v', fmt(t.valor, t.formato)));
      if (t.variacion_pct !== null && t.variacion_pct !== undefined) {
        const up = t.variacion_pct >= 0;
        k.appendChild(el('div', 'k-d ' + (up ? 'up' : 'down'), (up ? '▲ ' : '▼ ') + nf1.format(Math.abs(t.variacion_pct)) + '% vs periodo anterior'));
      }
      g.appendChild(k);
    });
    return g;
  }
  function renderTabla(b) {
    const d = el('div', 'b-tabla');
    if (b.titulo) d.appendChild(el('h4', '', b.titulo));
    const wrap = el('div', 'tabla-wrap'); const t = el('table');
    const thead = el('thead'); const trh = el('tr');
    b.columnas.forEach((c) => trh.appendChild(el('th', '', c.titulo)));
    thead.appendChild(trh); t.appendChild(thead);
    const tb = el('tbody');
    b.filas.forEach((f) => {
      const tr = el('tr');
      b.columnas.forEach((c) => tr.appendChild(el('td', c.formato === 'texto' || c.formato === 'fecha' ? '' : 'num', fmt(f[c.clave], c.formato))));
      tb.appendChild(tr);
    });
    t.appendChild(tb); wrap.appendChild(t); d.appendChild(wrap);
    if (b.nota) d.appendChild(el('div', 'nota', b.nota));
    return d;
  }
  function renderGrafico(spec, grupo) {
    const box = el('div', 'chart-box');
    box.appendChild(el('h4', '', spec.titulo));
    const holder = el('div', 'chart-canvas'); const canvas = el('canvas');
    canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', spec.titulo);
    holder.appendChild(canvas); box.appendChild(holder);
    requestAnimationFrame(() => {
      try { charts[grupo || 'chat'].push(new Chart(canvas, configChart(spec))); } catch (e) { holder.textContent = 'No fue posible dibujar el gráfico.'; }
    });
    return box;
  }
  function configChart(s) {
    const esCirc = s.tipo === 'circular';
    const color = (i) => PALETA[i % PALETA.length];
    const datasets = s.series.map((serie, i) => {
      if (esCirc) return { label: serie.nombre, data: serie.datos, backgroundColor: s.etiquetas.map((_, j) => color(j)), borderColor: '#fff', borderWidth: 2 };
      if (s.tipo === 'linea') return { label: serie.nombre, data: serie.datos, borderColor: color(i), backgroundColor: color(i) + '22', fill: true, tension: .3, pointRadius: 2.5 };
      return { label: serie.nombre, data: serie.datos, backgroundColor: color(i), borderRadius: 4 };
    });
    const fmtV = (v) => (s.formato === 'moneda' ? '$' + fmtCorto(v) : s.formato === 'porcentaje' ? v + '%' : fmtCorto(v));
    const horizontal = s.tipo === 'barras' && s.horizontal;
    const opciones = {
      responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x',
      plugins: {
        legend: { display: esCirc || s.series.length > 1, position: esCirc ? 'right' : 'top', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: (c) => {
          const v = esCirc ? c.parsed : (horizontal ? c.parsed.x : c.parsed.y);
          let t = ' ' + (c.dataset.label || '') + ': ' + fmt(v, s.formato);
          if (esCirc) { const tot = c.dataset.data.reduce((a, b) => a + b, 0); t += ' (' + nf1.format(v / tot * 100) + '%)'; }
          return t;
        } } },
      },
    };
    if (!esCirc) {
      const eje = { ticks: { callback: (v) => fmtV(v) }, grid: { color: '#EEF1F6' }, beginAtZero: true };
      opciones.scales = horizontal ? { x: eje, y: { grid: { display: false } } } : { y: eje, x: { grid: { display: false }, ticks: { maxRotation: 55, autoSkip: true } } };
    }
    return { type: esCirc ? 'doughnut' : (s.tipo === 'linea' ? 'line' : 'bar'), data: { labels: s.etiquetas, datasets }, options: opciones };
  }

  /* ---------- navegación ---------- */
  function mostrarVista(v) {
    document.querySelectorAll('.view').forEach((s) => s.classList.toggle('active', s.id === 'view-' + v));
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
    $('viewTitle').textContent = TITULOS[v];
    $('sidebar').classList.remove('open');
    if (v === 'analisis') cargarDashboard();
    if (v === 'ventas') cargarVentas();
    if (v === 'documentos') cargarDocumentos();
    if (v === 'informes') cargarInformes();
  }

  /* ---------- estado del agente ---------- */
  async function cargarEstado() {
    const lista = $('statusList');
    const fila = (cls, txt) => { const li = el('li'); li.appendChild(el('i', 'dot ' + cls)); li.appendChild(el('span', '', txt)); return li; };
    try {
      const d = await api('/health/detail');
      const a = d.agente;
      vaciar(lista);
      $('agentName').textContent = a.agente;
      lista.appendChild(fila('ok', 'Servidor en línea'));
      const llmCls = a.llm_listo ? 'ok' : (a.config_valida ? 'warn' : 'bad');
      lista.appendChild(fila(llmCls, `${a.proveedor} · ${a.modelo}` + (a.llm_listo ? '' : (a.proveedor === 'ollama' ? (a.ollama_activo ? ' (modelo no instalado)' : ' (Ollama apagado)') : ' (revisar clave)'))));
      lista.appendChild(fila(d.rag.fragmentos ? 'ok' : 'warn', `RAG: ${d.rag.documentos} docs · ${d.rag.fragmentos} fragmentos`));
      lista.appendChild(fila(d.ventas.activa ? (d.ventas.simulada ? 'warn' : 'ok') : 'bad', d.ventas.activa ? `Ventas: ${d.ventas.activa}${d.ventas.simulada ? ' (simulada)' : ''}` : 'Ventas: sin base'));
      lista.appendChild(fila('ok', 'Memoria: ' + a.memoria));
      $('dsBadge').textContent = d.ventas.activa ? 'Base: ' + d.ventas.activa : 'Sin base de ventas';
      $('simBadge').classList.toggle('hidden', !d.ventas.simulada);
    } catch (e) {
      vaciar(lista); lista.appendChild(fila('bad', 'Servidor sin conexión'));
    }
  }

  /* ---------- chat ---------- */
  function agregarMensajeUsuario(texto) {
    const m = el('div', 'msg user'); m.appendChild(el('div', 'bubble-user', texto)); $('messages').appendChild(m); bajar();
  }
  function agregarMensajeAgente(bloques, meta) {
    const m = el('div', 'msg'); m.appendChild(el('div', 'avatar', 'P'));
    const b = el('div', 'bubble-agent');
    b.appendChild(renderBloques(bloques, 'chat'));
    if (meta && (meta.categoria || (meta.herramientas && meta.herramientas.length))) {
      const ml = el('div', 'meta-line');
      if (meta.categoria) ml.appendChild(el('span', 'chip', 'ruta: ' + meta.categoria));
      (meta.herramientas || []).forEach((h) => ml.appendChild(el('span', 'chip', '🔧 ' + h)));
      b.appendChild(ml);
    }
    m.appendChild(b); $('messages').appendChild(m); bajar();
  }
  function bajar() { const c = $('messages'); c.scrollTop = c.scrollHeight; }
  function bienvenida() {
    vaciar($('messages'));
    agregarMensajeAgente([
      { tipo: 'texto', texto: 'Hola, soy **' + $('agentName').textContent + '**, el agente de IA del área comercial de Postobón. Puedo consultar los documentos cargados, analizar la base de ventas, generar gráficos e informes y exportar archivos.' },
      { tipo: 'texto', texto: 'Solo respondo con base en los documentos y datos cargados; si falta información, te lo indicaré.' },
    ]);
  }
  async function enviar(texto) {
    texto = (texto || '').trim();
    if (!texto || ocupado) return;
    ocupado = true; $('send').disabled = true;
    agregarMensajeUsuario(texto); $('input').value = ''; autoResize();
    const typing = el('div', 'msg'); typing.appendChild(el('div', 'avatar', 'P'));
    const tb = el('div', 'bubble-agent'); const ty = el('span', 'typing'); ['i', 'i', 'i'].forEach(() => ty.appendChild(el('i'))); tb.appendChild(ty); typing.appendChild(tb);
    $('messages').appendChild(typing); bajar();
    try {
      const r = await api('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mensaje: texto, session_id: sessionId }) });
      typing.remove(); agregarMensajeAgente(r.bloques, r);
      cargarHistorial(); cargarEstado();
    } catch (e) {
      typing.remove(); agregarMensajeAgente([{ tipo: 'alerta', nivel: 'critica', titulo: 'No se pudo completar la consulta', texto: e.message }]);
    } finally { ocupado = false; $('send').disabled = false; $('input').focus(); }
  }
  function autoResize() { const t = $('input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 140) + 'px'; }

  async function cargarHistorial() {
    try {
      const d = await api('/chat/sessions'); const ul = $('historyList'); vaciar(ul);
      d.sesiones.forEach((s) => {
        const li = el('li', s.session_id === sessionId ? 'active' : '');
        const b = el('button', 'h-title', s.titulo); b.title = s.titulo; b.addEventListener('click', () => abrirSesion(s.session_id));
        const x = el('button', 'h-del', '✕'); x.title = 'Eliminar conversación'; x.addEventListener('click', () => eliminarSesion(s.session_id));
        li.appendChild(b); li.appendChild(x); ul.appendChild(li);
      });
    } catch (_) { /* sin historial */ }
  }
  async function abrirSesion(id) {
    try {
      const d = await api('/chat/' + encodeURIComponent(id) + '/history');
      sessionId = id; localStorage.setItem('posto_session', id); limpiarCharts('chat'); vaciar($('messages'));
      d.mensajes.forEach((m) => (m.rol === 'usuario' ? agregarMensajeUsuario(m.contenido) : agregarMensajeAgente(m.bloques && m.bloques.length ? m.bloques : [{ tipo: 'texto', texto: m.contenido }], { categoria: m.categoria })));
      mostrarVista('chat'); cargarHistorial();
    } catch (e) { toast(e.message, 'err'); }
  }
  async function eliminarSesion(id) {
    try {
      await api('/chat/' + encodeURIComponent(id), { method: 'DELETE' });
      if (id === sessionId) { sessionId = nuevaSesion(); limpiarCharts('chat'); bienvenida(); }
      cargarHistorial();
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ---------- análisis ---------- */
  function filtrosActuales() {
    const p = new URLSearchParams();
    [['desde', 'f-desde'], ['hasta', 'f-hasta'], ['canal', 'f-canal'], ['region', 'f-region'], ['categoria', 'f-categoria']].forEach(([k, id]) => { const v = $(id).value; if (v) p.set(k, v); });
    return p;
  }
  function llenarSelect(id, valores, todos) {
    const s = $(id); const actual = s.value; vaciar(s);
    const o = el('option', '', todos); o.value = ''; s.appendChild(o);
    (valores || []).forEach((v) => { const op = el('option', '', v); op.value = v; s.appendChild(op); });
    if (actual && valores.includes(actual)) s.value = actual;
  }
  async function cargarFiltros() {
    try {
      const f = await api('/sales/filters');
      llenarSelect('f-canal', f.canal, 'Todos'); llenarSelect('f-region', f.region, 'Todas'); llenarSelect('f-categoria', f.categoria, 'Todas'); llenarSelect('v-canal', f.canal, 'Todos');
      $('f-desde').min = $('f-hasta').min = f.fecha_min; $('f-desde').max = $('f-hasta').max = f.fecha_max;
    } catch (_) { /* sin datos */ }
  }
  async function cargarDashboard() {
    limpiarCharts('dash'); const vacio = $('dashEmpty');
    try {
      await cargarFiltros();
      const q = filtrosActuales().toString();
      const d = await api('/sales/dashboard' + (q ? '?' + q : ''));
      vacio.classList.add('hidden');
      const kg = $('kpiGrid'); vaciar(kg); kg.appendChild(renderKpis(d.kpis, 'kpi-grid'));
      const cg = $('chartGrid'); vaciar(cg); d.graficos.forEach((g) => cg.appendChild(renderGrafico(g, 'dash')));
      cargarDetalleDimension(); cargarOportunidades();
    } catch (e) {
      vaciar($('kpiGrid')); vaciar($('chartGrid')); vaciar($('dimTable')); vaciar($('oppList'));
      vacio.classList.remove('hidden'); vacio.textContent = e.message + ' Vaya a «Archivos de ventas» para cargar una base o generar la demostración simulada.';
    }
  }
  async function cargarDetalleDimension() {
    const p = filtrosActuales(); p.set('dimension', $('dimSelect').value); p.set('top', '30');
    try {
      const d = await api('/sales/analysis?' + p.toString()); const dim = d.dimension;
      const cont = $('dimTable'); vaciar(cont);
      cont.appendChild(renderTabla({ titulo: '', nota: d.total_registros > 30 ? 'Mostrando 30 de ' + d.total_registros : null,
        columnas: [{ clave: dim, titulo: dim, formato: 'texto' }, { clave: 'ventas_netas', titulo: 'Ventas netas', formato: 'moneda' }, { clave: 'unidades', titulo: 'Unidades', formato: 'numero' }, { clave: 'participacion_pct', titulo: 'Part. %', formato: 'porcentaje' }, { clave: 'descuento_pct', titulo: 'Desc. %', formato: 'porcentaje' }], filas: d.filas }));
    } catch (e) { $('dimTable').textContent = e.message; }
  }
  async function cargarOportunidades() {
    try {
      const d = await api('/sales/opportunities'); const c = $('oppList'); vaciar(c);
      const nivel = { alerta: 'advertencia', riesgo: 'critica', oportunidad: 'exito' };
      d.hallazgos.forEach((h) => { const a = renderBloque({ tipo: 'alerta', nivel: nivel[h.tipo] || 'info', titulo: h.area, texto: h.hallazgo, accion: h.accion }); a.style.marginBottom = '8px'; c.appendChild(a); });
      if (!d.hallazgos.length) c.textContent = 'Sin hallazgos relevantes.';
    } catch (_) { /* sin datos */ }
  }

  /* ---------- ventas ---------- */
  async function cargarVentas() {
    await cargarFiltros();
    try {
      const d = await api('/sales/datasets'); const c = $('datasetList'); vaciar(c);
      if (!d.datasets.length) c.appendChild(el('div', 'empty', 'No hay bases de ventas. Cargue un archivo o genere la demostración simulada.'));
      d.datasets.forEach((s) => {
        const it = el('div', 'list-item'); const m = el('div', 'li-main');
        m.appendChild(el('b', '', s.id + (s.activo ? '  ✔ activa' : '')));
        m.appendChild(el('span', 'muted', `${nf.format(s.filas)} filas · ${s.fecha_min} → ${s.fecha_max} · archivo: ${s.archivo_original}` + (s.derivado_de ? ' · versión de ' + s.derivado_de : '') + (s.simulado ? ' · SIMULADA' : '')));
        (s.advertencias || []).slice(0, 3).forEach((a) => m.appendChild(el('span', 'muted', '⚠ ' + a)));
        it.appendChild(m);
        if (!s.activo) { const b = el('button', 'btn', 'Activar'); b.addEventListener('click', () => activar(s.id)); it.appendChild(b); }
        c.appendChild(it);
      });
      const q = new URLSearchParams(); const a = d.activo;
      $('dlXlsx').href = '/sales/export?formato=xlsx' + (a ? '&dataset=' + encodeURIComponent(a) : '');
      $('dlCsv').href = '/sales/export?formato=csv' + (a ? '&dataset=' + encodeURIComponent(a) : '');
      const r = await api('/sales/rows?limit=25'); const pv = $('rowsPreview'); vaciar(pv);
      const cols = ['fecha', 'producto', 'categoria', 'cliente', 'canal', 'ciudad', 'unidades', 'precio_unitario', 'descuento_pct', 'valor_bruto', 'valor_neto'];
      const fm = { precio_unitario: 'moneda', valor_bruto: 'moneda', valor_neto: 'moneda', unidades: 'numero', descuento_pct: 'porcentaje' };
      pv.appendChild(renderTabla({ titulo: '', nota: 'Primeras 25 de ' + nf.format(r.total) + ' filas', columnas: cols.map((c2) => ({ clave: c2, titulo: c2.replace('_', ' '), formato: fm[c2] || 'texto' })), filas: r.filas }));
    } catch (e) { $('rowsPreview').textContent = e.message; }
  }
  async function activar(id) {
    try { await api('/sales/activate/' + encodeURIComponent(id), { method: 'POST' }); toast('Base activada: ' + id, 'ok'); refrescarDatos(); } catch (e) { toast(e.message, 'err'); }
  }
  function refrescarDatos() { cargarEstado(); cargarVentas(); }
  async function subirVentas(archivo) {
    const out = $('uploadResult'); vaciar(out);
    const fd = new FormData(); fd.append('archivo', archivo);
    try {
      const d = await api('/sales/upload', { method: 'POST', body: fd });
      const r = el('div', 'result'); r.appendChild(el('div', 'ok', `✔ «${archivo.name}» cargado: ${nf.format(d.filas)} filas válidas.`));
      const rep = d.reporte; const desc = Object.entries(rep.descartadas || {}).map(([k, v]) => `${k}: ${v}`);
      if (desc.length) r.appendChild(el('div', 'err', 'Filas descartadas — ' + desc.join(', ')));
      (rep.advertencias || []).forEach((a) => r.appendChild(el('div', '', '⚠ ' + a)));
      out.appendChild(r); toast('Base de ventas cargada y activada', 'ok'); refrescarDatos();
    } catch (e) { out.appendChild(el('div', 'result err', '✖ ' + e.message)); }
  }
  async function crearVersion() {
    const ops = []; const f = { op: 'filtrar' };
    if ($('v-desde').value) f.desde = $('v-desde').value;
    if ($('v-hasta').value) f.hasta = $('v-hasta').value;
    if ($('v-canal').value) f.campos = { canal: $('v-canal').value };
    if (Object.keys(f).length === 1) { toast('Indique al menos un filtro para la nueva versión.', 'err'); return; }
    ops.push(f);
    try { const d = await api('/sales/transform', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ operaciones: ops }) }); toast(`Nueva versión «${d.id}» con ${nf.format(d.filas)} filas`, 'ok'); refrescarDatos(); } catch (e) { toast(e.message, 'err'); }
  }

  /* ---------- documentos ---------- */
  async function cargarDocumentos() {
    try {
      const d = await api('/documents'); const c = $('docList'); vaciar(c);
      $('ragStats').textContent = `${d.rag.documentos} documentos · ${d.rag.fragmentos} fragmentos · vectores: ${d.rag.proveedor_embeddings}`;
      d.documentos.forEach((x) => {
        const it = el('div', 'list-item'); const m = el('div', 'li-main');
        m.appendChild(el('b', '', x.nombre)); m.appendChild(el('span', 'muted', `${x.tipo.toUpperCase()} · ${x.tamano_kb} KB · ${x.fragmentos} fragmentos`));
        it.appendChild(m); const acc = el('div', 'btn-row');
        const dl = el('a', 'btn', 'Descargar'); dl.href = '/documents/download/' + encodeURIComponent(x.nombre); acc.appendChild(dl);
        const del = el('button', 'btn', 'Eliminar'); del.addEventListener('click', () => eliminarDoc(x.nombre)); acc.appendChild(del);
        it.appendChild(acc); c.appendChild(it);
      });
      if (!d.documentos.length) c.appendChild(el('div', 'empty', 'No hay documentos cargados.'));
    } catch (e) { $('docList').textContent = e.message; }
  }
  async function subirDocs(archivos) {
    const out = $('docResult'); vaciar(out); const fd = new FormData();
    Array.from(archivos).forEach((f) => fd.append('archivos', f));
    try {
      const d = await api('/documents/upload', { method: 'POST', body: fd });
      const r = el('div', 'result'); r.appendChild(el('div', 'ok', '✔ Indexados: ' + d.guardados.join(', ')));
      Object.entries(d.errores || {}).forEach(([k, v]) => r.appendChild(el('div', 'err', `✖ ${k}: ${v}`)));
      Object.entries(d.indexacion.errores || {}).forEach(([k, v]) => r.appendChild(el('div', 'err', `✖ ${k}: ${v}`)));
      out.appendChild(r); toast('Base de conocimiento actualizada', 'ok'); cargarDocumentos(); cargarEstado();
    } catch (e) { out.appendChild(el('div', 'result err', '✖ ' + e.message)); }
  }
  async function eliminarDoc(n) {
    try { await api('/documents/' + encodeURIComponent(n), { method: 'DELETE' }); toast('Documento eliminado', 'ok'); cargarDocumentos(); cargarEstado(); } catch (e) { toast(e.message, 'err'); }
  }
  async function buscarDocs() {
    const q = $('docQuery').value.trim(); const out = $('searchResults'); vaciar(out); if (q.length < 2) return;
    try {
      const d = await api('/documents/search?q=' + encodeURIComponent(q));
      if (!d.resultados.length) out.appendChild(el('div', 'empty', 'Sin resultados relevantes en los documentos.'));
      d.resultados.forEach((r) => { const h = el('div', 'hit'); h.appendChild(el('b', '', r.archivo + ' · pág. ' + r.pagina)); h.appendChild(el('div', '', r.texto.length > 380 ? r.texto.slice(0, 380) + '…' : r.texto)); h.appendChild(el('small', '', 'relevancia ' + r.puntaje)); out.appendChild(h); });
    } catch (e) { out.appendChild(el('div', 'result err', e.message)); }
  }

  /* ---------- informes ---------- */
  async function cargarInformes() {
    try {
      const d = await api('/reports'); const c = $('reportList'); vaciar(c);
      if (!d.informes.length) c.appendChild(el('div', 'empty', 'Aún no hay informes generados.'));
      d.informes.forEach((i) => {
        const it = el('div', 'list-item'); const m = el('div', 'li-main');
        m.appendChild(el('b', '', 'Informe ' + i.generado + (i.simulado ? ' (datos simulados)' : '')));
        m.appendChild(el('span', 'muted', 'Base: ' + i.dataset + ' · ventas netas ' + fmt(i.ventas_netas, 'moneda') + (i.desactualizado ? ' · ⚠ los datos cambiaron: regenere el informe' : '')));
        it.appendChild(m); const acc = el('div', 'btn-row');
        Object.entries(i.archivos).forEach(([f, n]) => { const a = el('a', 'btn', '⬇ ' + f.toUpperCase()); a.href = '/reports/download/' + encodeURIComponent(n); acc.appendChild(a); });
        it.appendChild(acc); c.appendChild(it);
      });
    } catch (e) { $('reportList').textContent = e.message; }
  }
  async function informe(ruta) {
    const v = $('reportView'); limpiarCharts('report'); vaciar(v);
    v.appendChild(el('div', 'empty', 'Calculando informe…'));
    try {
      const d = await api(ruta, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      vaciar(v); const p = el('div', 'panel'); p.appendChild(el('h3', '', 'Informe comercial · ' + d.generado));
      const cuerpo = el('div', 'bubble-agent'); cuerpo.style.boxShadow = 'none'; cuerpo.style.border = '0'; cuerpo.style.padding = '0';
      cuerpo.appendChild(renderBloques(d.bloques, 'report')); p.appendChild(cuerpo); v.appendChild(p);
      if (ruta.endsWith('generate')) { toast('Informe generado', 'ok'); cargarInformes(); }
    } catch (e) { vaciar(v); v.appendChild(el('div', 'empty', e.message)); }
  }

  /* ---------- arrastrar y soltar ---------- */
  function zona(dropId, inputId, manejador, multiple) {
    const d = $(dropId), i = $(inputId);
    d.addEventListener('click', () => i.click());
    d.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); i.click(); } });
    ['dragenter', 'dragover'].forEach((ev) => d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.remove('over'); }));
    d.addEventListener('drop', (e) => { if (e.dataTransfer.files.length) manejador(multiple ? e.dataTransfer.files : e.dataTransfer.files[0]); });
    i.addEventListener('change', () => { if (i.files.length) manejador(multiple ? i.files : i.files[0]); i.value = ''; });
  }

  /* ---------- inicio ---------- */
  function init() {
    const logo = $('logo'); const alt = '/static/assets/logo_postobon.svg';
    const respaldo = () => { if (!logo.src.endsWith('.svg')) logo.src = alt; };
    logo.addEventListener('error', respaldo); if (logo.complete && logo.naturalWidth === 0) respaldo();

    $('nav').addEventListener('click', (e) => { const b = e.target.closest('.nav-item'); if (b) mostrarVista(b.dataset.view); });
    $('hamburger').addEventListener('click', () => $('sidebar').classList.toggle('open'));
    $('send').addEventListener('click', () => enviar($('input').value));
    $('input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar($('input').value); } });
    $('input').addEventListener('input', autoResize);
    $('newChat').addEventListener('click', () => { sessionId = nuevaSesion(); limpiarCharts('chat'); bienvenida(); mostrarVista('chat'); cargarHistorial(); });
    SUGERENCIAS.forEach((s) => { const b = el('button', 'sug', s); b.addEventListener('click', () => enviar(s)); $('suggestions').appendChild(b); });

    $('applyFilters').addEventListener('click', cargarDashboard);
    $('clearFilters').addEventListener('click', () => { ['f-desde', 'f-hasta', 'f-canal', 'f-region', 'f-categoria'].forEach((id) => { $(id).value = ''; }); cargarDashboard(); });
    $('dimSelect').addEventListener('change', cargarDetalleDimension);

    zona('salesDrop', 'salesFile', subirVentas, false);
    zona('docDrop', 'docFile', subirDocs, true);
    $('btnDemo').addEventListener('click', async () => { $('btnDemo').disabled = true; try { const d = await api('/sales/demo', { method: 'POST' }); toast(d.mensaje, 'ok'); refrescarDatos(); } catch (e) { toast(e.message, 'err'); } $('btnDemo').disabled = false; });
    $('btnVersion').addEventListener('click', crearVersion);
    $('btnReindex').addEventListener('click', async () => { try { const d = await api('/documents/reindex?forzar=true', { method: 'POST' }); toast('Índice reconstruido: ' + d.fragmentos + ' fragmentos', 'ok'); cargarDocumentos(); cargarEstado(); } catch (e) { toast(e.message, 'err'); } });
    $('btnSearch').addEventListener('click', buscarDocs);
    $('docQuery').addEventListener('keydown', (e) => { if (e.key === 'Enter') buscarDocs(); });
    $('btnPreview').addEventListener('click', () => informe('/reports/preview'));
    $('btnGenerate').addEventListener('click', () => informe('/reports/generate'));

    cargarEstado().then(() => { bienvenida(); abrirSiExiste(); });
    cargarHistorial();
    setInterval(cargarEstado, 30000);
  }
  async function abrirSiExiste() {
    try { const d = await api('/chat/' + encodeURIComponent(sessionId) + '/history'); if (d.mensajes && d.mensajes.length) abrirSesion(sessionId); } catch (_) { /* sesión nueva */ }
  }
  document.addEventListener('DOMContentLoaded', init);
})();
