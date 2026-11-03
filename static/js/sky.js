/* Анимированное небо на canvas: дождь, снег, звёзды, облака, туман, молнии. */
(function () {
  "use strict";
  var canvas = document.getElementById("sky-canvas");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var flash = document.querySelector(".flash-overlay");
  var W = 0, H = 0, dpr = 1, mode = document.body.dataset.sky || "clear";
  var parts = [], last = 0, nextBolt = 0, running = true;

  function night() { return document.documentElement.classList.contains("is-night"); }
  function rand(a, b) { return a + Math.random() * (b - a); }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    build();
  }

  function add(n, factory) { for (var i = 0; i < n; i++) parts.push(factory(true)); }
  var area = function (k) { return Math.round((W * H) / k); };

  var F = {
    drop: function () { return { t: "drop", x: rand(-50, W + 50), y: rand(-H, H), len: rand(12, 26), v: rand(700, 1100), a: rand(.25, .55) }; },
    flake: function () { return { t: "flake", x: rand(0, W), y: rand(-H, H), r: rand(1.2, 3.6), v: rand(30, 90), ph: rand(0, 6.3), a: rand(.5, .95) }; },
    star: function () { return { t: "star", x: rand(0, W), y: rand(0, H * .75), r: rand(.4, 1.6), ph: rand(0, 6.3), sp: rand(.6, 2) }; },
    puff: function (init) { var r = rand(90, 220); return { t: "puff", x: init ? rand(-r, W + r) : -r * 2, y: rand(-40, H * .5), r: r, v: rand(6, 22), a: rand(.06, .16) }; },
    fog: function (init) { var r = rand(220, 420); return { t: "puff", x: init ? rand(-r, W + r) : -r * 2, y: rand(H * .2, H), r: r, v: rand(8, 26), a: rand(.07, .15) }; },
    mote: function () { return { t: "mote", x: rand(0, W), y: rand(0, H), r: rand(1, 2.6), vy: rand(-14, -4), vx: rand(-6, 6), a: rand(.15, .45), ph: rand(0, 6.3) }; }
  };

  function build() {
    parts = [];
    var n = night();
    switch (mode) {
      case "rain": add(area(9000), F.drop); add(3, F.puff); break;
      case "storm": add(area(5500), F.drop); add(5, F.puff); break;
      case "snow": add(area(7000), F.flake); add(3, F.puff); break;
      case "fog": add(9, F.fog); add(area(60000), F.mote); break;
      case "cloudy": add(9, F.puff); if (n) add(area(40000), F.star); break;
      case "partly": add(5, F.puff); n ? add(area(9000), F.star) : add(area(40000), F.mote); break;
      case "admin": add(area(14000), F.star); break;
      default: n ? add(area(6000), F.star) : add(area(26000), F.mote);
    }
  }

  function step(dt, time) {
    ctx.clearRect(0, 0, W, H);
    var wind = mode === "storm" ? 0.32 : 0.16;
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p.t === "drop") {
        p.y += p.v * dt; p.x += p.v * wind * dt;
        if (p.y > H + 30) { p.y = rand(-80, -10); p.x = rand(-100, W); }
        ctx.strokeStyle = "rgba(200,230,255," + p.a + ")"; ctx.lineWidth = 1.3;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.len * wind, p.y - p.len); ctx.stroke();
      } else if (p.t === "flake") {
        p.ph += dt; p.y += p.v * dt; p.x += Math.sin(p.ph) * 18 * dt;
        if (p.y > H + 10) { p.y = -10; p.x = rand(0, W); }
        ctx.fillStyle = "rgba(255,255,255," + p.a + ")";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      } else if (p.t === "star") {
        var tw = .45 + .55 * Math.abs(Math.sin(time / 1000 * p.sp + p.ph));
        ctx.fillStyle = "rgba(255,255,255," + (tw * .85) + ")";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      } else if (p.t === "puff") {
        p.x += p.v * dt;
        if (p.x - p.r > W) { var np = (p.r > 220 ? F.fog : F.puff)(false); for (var k in np) p[k] = np[k]; }
        var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
        g.addColorStop(0, "rgba(255,255,255," + p.a + ")"); g.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      } else if (p.t === "mote") {
        p.ph += dt; p.y += p.vy * dt; p.x += (p.vx + Math.sin(p.ph) * 6) * dt;
        if (p.y < -10) { p.y = H + 10; p.x = rand(0, W); }
        ctx.fillStyle = "rgba(255,250,220," + (p.a * (.6 + .4 * Math.sin(p.ph * 2))) + ")";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      }
    }
    if (mode === "storm" && flash && time > nextBolt) {
      nextBolt = time + rand(4000, 9000);
      flash.classList.remove("flash"); void flash.offsetWidth; flash.classList.add("flash");
    }
  }

  function loop(time) {
    if (!running) return;
    var dt = Math.min((time - last) / 1000, .05); last = time;
    step(dt, time);
    requestAnimationFrame(loop);
  }

  window.Sky = {
    set: function (m) { if (m === mode) return; mode = m; nextBolt = performance.now() + 1500; build(); if (reduce) step(0, 0); }
  };

  window.addEventListener("resize", function () { clearTimeout(resize._t); resize._t = setTimeout(resize, 150); });
  document.addEventListener("visibilitychange", function () {
    running = !document.hidden && !reduce;
    if (running) { last = performance.now(); requestAnimationFrame(loop); }
  });
  resize();
  nextBolt = performance.now() + 2000;
  if (reduce) { running = false; step(0, 0); } else { last = performance.now(); requestAnimationFrame(loop); }
})();
