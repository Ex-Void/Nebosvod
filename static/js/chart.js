/* График температуры и осадков на canvas с анимацией прорисовки и подсказками. */
(function () {
  "use strict";
  var canvas = document.getElementById("temp-chart");
  var dataEl = document.getElementById("weather-data");
  if (!canvas || !dataEl) return;
  var days = JSON.parse(dataEl.textContent).forecast || [];
  if (!days.length) return;
  var tip = document.getElementById("chart-tip");
  var ctx = canvas.getContext("2d");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var W, H, pad = { l: 46, r: 24, t: 34, b: 52 }, progress = reduce ? 1 : 0, hover = -1, pts = null;
  var fmt = window.UI ? window.UI.fmtTemp : function (v) { return Math.round(v) + "°"; };

  function layout() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var lo = Math.min.apply(null, days.map(function (d) { return d.temp_min; }));
    var hi = Math.max.apply(null, days.map(function (d) { return d.temp_max; }));
    lo = Math.floor(lo - 2); hi = Math.ceil(hi + 2);
    var iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    var step = days.length > 1 ? iw / (days.length - 1) : 0;
    var y = function (v) { return pad.t + ih * (1 - (v - lo) / (hi - lo || 1)); };
    pts = {
      lo: lo, hi: hi, y: y, ih: ih, step: step,
      x: days.map(function (d, i) { return days.length > 1 ? pad.l + i * step : pad.l + iw / 2; }),
      max: days.map(function (d) { return y(d.temp_max); }),
      min: days.map(function (d) { return y(d.temp_min); })
    };
  }

  // плавная кривая через точки (кардинальный сплайн)
  function curve(xs, ys) {
    ctx.moveTo(xs[0], ys[0]);
    for (var i = 0; i < xs.length - 1; i++) {
      var x0 = xs[i - 1] !== undefined ? xs[i - 1] : xs[i], y0 = ys[i - 1] !== undefined ? ys[i - 1] : ys[i];
      var x3 = xs[i + 2] !== undefined ? xs[i + 2] : xs[i + 1], y3 = ys[i + 2] !== undefined ? ys[i + 2] : ys[i + 1];
      var t = .18;
      ctx.bezierCurveTo(xs[i] + (xs[i + 1] - x0) * t, ys[i] + (ys[i + 1] - y0) * t,
                        xs[i + 1] - (x3 - xs[i]) * t, ys[i + 1] - (y3 - ys[i]) * t, xs[i + 1], ys[i + 1]);
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    var p = pts, e = 1 - Math.pow(1 - progress, 3);
    // сетка
    ctx.font = "12px Segoe UI, system-ui, sans-serif";
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    var gstep = Math.max(1, Math.ceil((p.hi - p.lo) / 5));
    for (var v = Math.ceil(p.lo / gstep) * gstep; v <= p.hi; v += gstep) {
      var gy = p.y(v);
      ctx.strokeStyle = v === 0 ? "rgba(255,255,255,.35)" : "rgba(255,255,255,.1)";
      ctx.setLineDash(v === 0 ? [4, 4] : []);
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(W - pad.r, gy); ctx.stroke();
      ctx.fillStyle = "rgba(255,255,255,.6)"; ctx.fillText(fmt(v), pad.l - 8, gy);
    }
    ctx.setLineDash([]);

    // осадки — столбики снизу
    var barW = Math.min(34, (p.step || 60) * .45);
    days.forEach(function (d, i) {
      var h = (p.ih * .32) * (d.precipitation / 100) * e;
      ctx.fillStyle = i === hover ? "rgba(143,211,255,.55)" : "rgba(255,255,255,.18)";
      var bx = p.x[i] - barW / 2, by = H - pad.b - h;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(bx, by, barW, h, [6, 6, 0, 0]); else ctx.rect(bx, by, barW, h);
      ctx.fill();
    });

    // линии — постепенная прорисовка слева направо
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, pad.l + (W - pad.l) * e + 2, H); ctx.clip();
    var grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
    grad.addColorStop(0, "rgba(255,209,102,.35)"); grad.addColorStop(1, "rgba(255,209,102,0)");
    ctx.beginPath(); curve(p.x, p.max);
    ctx.lineTo(p.x[p.x.length - 1], H - pad.b); ctx.lineTo(p.x[0], H - pad.b); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    [["max", "#ffd166"], ["min", "#8fd3ff"]].forEach(function (s) {
      ctx.beginPath(); curve(p.x, p[s[0]]);
      ctx.strokeStyle = s[1]; ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.stroke();
    });
    ctx.restore();

    // точки и подписи
    ctx.textAlign = "center";
    days.forEach(function (d, i) {
      var shown = (p.x[i] - pad.l) / (W - pad.l) <= e + .001;
      if (shown) {
        [["max", "#ffd166", -14], ["min", "#8fd3ff", 16]].forEach(function (s) {
          var r = i === hover ? 7 : 4.5;
          ctx.beginPath(); ctx.arc(p.x[i], p[s[0]][i], r, 0, 6.283);
          ctx.fillStyle = s[1]; ctx.fill();
          ctx.lineWidth = 2; ctx.strokeStyle = "rgba(20,30,60,.6)"; ctx.stroke();
          ctx.fillStyle = "#fff"; ctx.font = (i === hover ? "600 13px" : "12px") + " Segoe UI, system-ui, sans-serif";
          ctx.fillText(fmt(d[s[0] === "max" ? "temp_max" : "temp_min"]), p.x[i], p[s[0]][i] + s[2]);
        });
      }
      ctx.fillStyle = i === hover ? "#fff" : "rgba(255,255,255,.75)";
      ctx.font = "600 13px Segoe UI, system-ui, sans-serif";
      ctx.fillText(d.short, p.x[i], H - pad.b + 18);
      ctx.font = "11px Segoe UI, system-ui, sans-serif";
      ctx.fillStyle = "rgba(255,255,255,.55)";
      ctx.fillText(d.day_month, p.x[i], H - pad.b + 34);
    });

    if (hover > -1) {
      ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(p.x[hover], pad.t - 10); ctx.lineTo(p.x[hover], H - pad.b); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function animate() {
    var start = null, dur = 1500;
    function frame(ts) {
      if (start === null) start = ts;
      progress = Math.min((ts - start) / dur, 1);
      draw();
      if (progress < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  canvas.addEventListener("mousemove", function (ev) {
    var r = canvas.getBoundingClientRect(), mx = ev.clientX - r.left, best = -1, bd = 1e9;
    pts.x.forEach(function (x, i) { var dd = Math.abs(x - mx); if (dd < bd) { bd = dd; best = i; } });
    if (best !== hover) {
      hover = best; draw();
      var d = days[best];
      tip.innerHTML = "<b></b><br><span></span><br><span></span>";
      tip.children[0].textContent = d.label + ", " + d.day_month;
      tip.children[2].textContent = d.condition_label + " · " + d.temp_min_text + " … " + d.temp_max_text;
      tip.children[4].textContent = "Осадки: " + d.precipitation + "%";
      tip.style.left = pts.x[best] + "px";
      tip.style.top = Math.min(pts.max[best], pts.min[best]) - 8 + "px";
      tip.classList.add("show");
    }
  });
  canvas.addEventListener("mouseleave", function () { hover = -1; tip.classList.remove("show"); draw(); });
  window.addEventListener("resize", function () { layout(); draw(); });

  layout();
  if (reduce) { draw(); return; }
  draw();
  // запускаем анимацию, когда график попадает в поле зрения
  if ("IntersectionObserver" in window) {
    var ob = new IntersectionObserver(function (en) { if (en[0].isIntersecting) { ob.disconnect(); animate(); } }, { threshold: .3 });
    ob.observe(canvas);
  } else animate();
})();
