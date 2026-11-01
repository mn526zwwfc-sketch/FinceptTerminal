/* Fincept Lite — gráfico canvas propio (velas + volumen + SMA, o línea). Sin dependencias. */
(function () {
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  function fmtPx(v) {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    const d = a >= 1000 ? 2 : a >= 10 ? 2 : a >= 1 ? 4 : 6;
    return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  window.fmtPx = fmtPx;
  /** Variación con los mismos decimales que el precio de referencia (como un terminal real). */
  window.fmtChg = function (chg, ref) {
    if (chg == null || !isFinite(chg)) return "—";
    const a = Math.abs(ref ?? chg);
    const d = a >= 10 ? 2 : a >= 1 ? 4 : 6;
    return (chg >= 0 ? "+" : "") + chg.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  };

  function niceTicks(min, max, n) {
    const span = max - min || Math.abs(max) || 1;
    const step0 = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.abs(v) < step * 1e-6 ? 0 : v);
    out.step = step;
    return out;
  }
  /** Etiqueta de eje con los decimales que pide el paso de la rejilla (5.00, 0.25, 1.0850…). */
  function axisFmt(v, step) {
    const d = Math.min(6, Math.max(0, -Math.floor(Math.log10(step)) + (step / 10 ** Math.floor(Math.log10(step)) === 2.5 ? 1 : 0)));
    return v.toLocaleString("en-US", { minimumFractionDigits: Math.max(d, step >= 1 ? 2 : d), maximumFractionDigits: Math.max(d, step >= 1 ? 2 : d) });
  }

  function sma(vals, n) {
    const out = []; let s = 0;
    vals.forEach((v, i) => { s += v; if (i >= n) s -= vals[i - n]; out.push(i >= n - 1 ? s / n : null); });
    return out;
  }

  class FChart {
    constructor(canvas) {
      this.c = canvas; this.ctx = canvas.getContext("2d");
      this.rows = []; this.type = "candle"; this.opts = {}; this.hover = -1;
      new ResizeObserver(() => this.draw()).observe(canvas);
      canvas.addEventListener("mousemove", (e) => this.onMove(e));
      canvas.addEventListener("mouseleave", () => { this.hover = -1; this.draw(); });
    }
    setCandles(candles, opts = {}) {
      this.type = opts.type || "candle"; this.opts = opts;
      this.rows = candles.map((c) => ({ t: c.t, o: c.o, h: c.h, l: c.l, c: c.c, v: c.v }));
      const closes = this.rows.map((r) => r.c);
      this.smas = (opts.sma || []).map((n, i) => ({ n, vals: sma(closes, n), color: [css("--cyan"), "#a855f7", css("--warn")][i % 3] }));
      this.draw();
    }
    setLine(points, opts = {}) {
      this.type = "line"; this.opts = { ...opts, volume: false };
      this.rows = points.map((p) => ({ t: p.t, o: p.v, h: p.v, l: p.v, c: p.v, v: 0 }));
      // Serie de comparación opcional (p. ej. buy & hold): misma longitud, línea gris discontinua.
      this.smas = points.some((p) => p.b != null)
        ? [{ n: opts.compareLabel || "B&H", vals: points.map((p) => p.b ?? null), color: css("--text-2"), dashed: true, label: opts.compareLabel || "B&H" }]
        : [];
      this.draw();
    }
    layout() {
      const dpr = window.devicePixelRatio || 1;
      const w = this.c.clientWidth, h = this.c.clientHeight;
      if (this.c.width !== Math.round(w * dpr) || this.c.height !== Math.round(h * dpr)) {
        this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr);
      }
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const vol = this.type === "candle" && this.opts.volume !== false;
      const pad = { l: 6, r: 64, t: 18, b: 18 };
      const ph = h - pad.t - pad.b;
      return { w, h, pad, priceH: vol ? ph * 0.8 : ph, volTop: pad.t + ph * 0.82, volH: ph * 0.18, vol };
    }
    onMove(e) {
      if (!this.rows.length) return;
      const r = this.c.getBoundingClientRect();
      const L = this.layout();
      const x = e.clientX - r.left - L.pad.l;
      const cw = (L.w - L.pad.l - L.pad.r) / this.rows.length;
      this.hover = Math.max(0, Math.min(this.rows.length - 1, Math.floor(x / cw)));
      this.mouseY = e.clientY - r.top;
      this.draw();
    }
    tfmt(t, span) {
      const d = new Date(t * 1000);
      if (span < 3 * 86400) return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
      if (span < 400 * 86400) return d.toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
      return d.toLocaleDateString("es-ES", { month: "short", year: "2-digit" });
    }
    draw() {
      const ctx = this.ctx, L = this.layout(), rows = this.rows;
      ctx.clearRect(0, 0, L.w, L.h);
      ctx.font = "10px " + css("--mono");
      if (!rows.length) { ctx.fillStyle = css("--text-3"); ctx.fillText("Sin datos", 10, 20); return; }
      const extra = (this.smas || []).filter((s) => s.dashed).flatMap((s) => s.vals.filter((v) => v != null));
      const lo = Math.min(...rows.map((r) => r.l), ...extra), hi = Math.max(...rows.map((r) => r.h), ...extra);
      const padv = (hi - lo) * 0.06 || Math.abs(hi) * 0.01 || 1;
      const min = lo - padv, max = hi + padv;
      const plotW = L.w - L.pad.l - L.pad.r, cw = plotW / rows.length;
      const y = (v) => L.pad.t + (max - v) / (max - min) * L.priceH;
      const x = (i) => L.pad.l + i * cw + cw / 2;
      // rejilla + eje de precios
      ctx.strokeStyle = css("--border-dim"); ctx.fillStyle = css("--text-3"); ctx.lineWidth = 1;
      ctx.setLineDash([2, 3]);
      const ticks = niceTicks(min, max, 6);
      for (const v of ticks) {
        const yy = Math.round(y(v)) + 0.5;
        ctx.beginPath(); ctx.moveTo(L.pad.l, yy); ctx.lineTo(L.w - L.pad.r, yy); ctx.stroke();
        ctx.fillText(axisFmt(v, ticks.step), L.w - L.pad.r + 6, yy + 3);
      }
      const span = rows[rows.length - 1].t - rows[0].t;
      const every = Math.max(1, Math.floor(rows.length / 6));
      for (let i = 0; i < rows.length; i += every) {
        const xx = Math.round(x(i)) + 0.5;
        ctx.beginPath(); ctx.moveTo(xx, L.pad.t); ctx.lineTo(xx, L.h - L.pad.b); ctx.stroke();
        ctx.fillText(this.tfmt(rows[i].t, span), xx - 18, L.h - 5);
      }
      ctx.setLineDash([]);
      const up = css("--pos"), dn = css("--neg");
      // volumen
      if (L.vol) {
        const vmax = Math.max(...rows.map((r) => r.v)) || 1;
        rows.forEach((r, i) => {
          const hh = r.v / vmax * L.volH;
          ctx.fillStyle = (r.c >= r.o ? up : dn) + "55";
          ctx.fillRect(x(i) - Math.max(1, cw * 0.35), L.volTop + L.volH - hh, Math.max(1, cw * 0.7), hh);
        });
      }
      // serie principal
      if (this.type === "candle") {
        rows.forEach((r, i) => {
          const col = r.c >= r.o ? up : dn;
          ctx.strokeStyle = col; ctx.fillStyle = col;
          ctx.beginPath(); ctx.moveTo(Math.round(x(i)) + 0.5, y(r.h)); ctx.lineTo(Math.round(x(i)) + 0.5, y(r.l)); ctx.stroke();
          const bw = Math.max(1, cw * 0.62), top = y(Math.max(r.o, r.c)), bh = Math.max(1, Math.abs(y(r.o) - y(r.c)));
          ctx.fillRect(x(i) - bw / 2, top, bw, bh);
        });
      } else {
        const col = this.opts.color || (rows[rows.length - 1].c >= rows[0].c ? up : dn);
        const grad = ctx.createLinearGradient(0, L.pad.t, 0, L.pad.t + L.priceH);
        grad.addColorStop(0, col + "40"); grad.addColorStop(1, col + "00");
        ctx.beginPath(); rows.forEach((r, i) => (i ? ctx.lineTo(x(i), y(r.c)) : ctx.moveTo(x(i), y(r.c))));
        ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.lineTo(x(rows.length - 1), L.pad.t + L.priceH); ctx.lineTo(x(0), L.pad.t + L.priceH); ctx.closePath();
        ctx.fillStyle = grad; ctx.fill(); ctx.lineWidth = 1;
      }
      for (const s of this.smas || []) {
        ctx.beginPath(); let started = false;
        s.vals.forEach((v, i) => { if (v == null) return; started ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)); started = true; });
        ctx.strokeStyle = s.color; if (s.dashed) ctx.setLineDash([4, 3]); ctx.stroke(); ctx.setLineDash([]);
      }
      // último precio
      const last = rows[rows.length - 1].c, ly = y(last);
      const lcol = last >= (this.opts.prevClose ?? rows[0].o) ? up : dn;
      ctx.strokeStyle = lcol; ctx.setLineDash([1, 2]);
      ctx.beginPath(); ctx.moveTo(L.pad.l, ly); ctx.lineTo(L.w - L.pad.r, ly); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = lcol; ctx.fillRect(L.w - L.pad.r + 1, ly - 7, L.pad.r - 2, 14);
      ctx.fillStyle = "#000"; ctx.fillText(fmtPx(last), L.w - L.pad.r + 5, ly + 3);
      // leyenda / crosshair
      const i = this.hover >= 0 ? this.hover : rows.length - 1, r = rows[i];
      ctx.fillStyle = css("--text-2");
      let legend = this.opts.label ? this.opts.label + "  " : "";
      legend += this.type === "candle"
        ? `${this.tfmt(r.t, span < 3 * 86400 ? 0 : 86400 * 10)}  O ${fmtPx(r.o)}  H ${fmtPx(r.h)}  L ${fmtPx(r.l)}  C ${fmtPx(r.c)}`
        : `${new Date(r.t * 1000).toLocaleDateString("es-ES")}  ${fmtPx(r.c)}`;
      ctx.fillText(legend, L.pad.l + 2, 12);
      let lx = L.pad.l + 8 + ctx.measureText(legend).width;
      for (const s of this.smas || []) {
        ctx.fillStyle = s.color; const t = `${s.label || "SMA" + s.n} ${fmtPx(s.vals[i])}`;
        ctx.fillText(t, lx + 10, 12); lx += ctx.measureText(t).width + 10;
      }
      if (this.hover >= 0) {
        ctx.strokeStyle = css("--text-3"); ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(Math.round(x(i)) + 0.5, L.pad.t); ctx.lineTo(Math.round(x(i)) + 0.5, L.h - L.pad.b); ctx.stroke();
        if (this.mouseY > L.pad.t && this.mouseY < L.pad.t + L.priceH) {
          ctx.beginPath(); ctx.moveTo(L.pad.l, this.mouseY); ctx.lineTo(L.w - L.pad.r, this.mouseY); ctx.stroke();
          const v = max - (this.mouseY - L.pad.t) / L.priceH * (max - min);
          ctx.fillStyle = css("--bg-hover"); ctx.fillRect(L.w - L.pad.r + 1, this.mouseY - 7, L.pad.r - 2, 14);
          ctx.fillStyle = css("--text"); ctx.fillText(fmtPx(v), L.w - L.pad.r + 5, this.mouseY + 3);
        }
        ctx.setLineDash([]);
      }
    }
  }
  window.FChart = FChart;
})();
