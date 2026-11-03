/* Интерфейс сайта: вкладки, анимации появления, смена города без перезагрузки,
   фильтр городов, уведомления, подтверждения, админские мелочи. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function fmtTemp(v) {
    var n = Math.round(v);
    return n > 0 ? "+" + n + "°" : n < 0 ? "−" + Math.abs(n) + "°" : "0°";
  }

  /* ---------- вкладки с «плавающим» индикатором ---------- */
  var tabs = $("#tabs"), indicator = $(".tab-indicator");
  function moveIndicator(el, instant) {
    if (!tabs || !indicator) return;
    if (!el) { indicator.style.width = "0"; return; }
    if (instant) indicator.style.transition = "none";
    indicator.style.width = el.offsetWidth + "px";
    indicator.style.transform = "translateX(" + el.offsetLeft + "px)";
    if (instant) { void indicator.offsetWidth; indicator.style.transition = ""; }
  }
  if (tabs) {
    var active = $(".tab.active", tabs);
    moveIndicator(active, true);
    $$(".tab", tabs).forEach(function (t) {
      t.addEventListener("mouseenter", function () { moveIndicator(t); });
    });
    tabs.addEventListener("mouseleave", function () { moveIndicator(active); });
    window.addEventListener("resize", function () { moveIndicator(active, true); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { moveIndicator(active, true); });
  }

  /* ---------- плавный уход со страницы ---------- */
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || a.target) return;
    var url = new URL(a.href, location.href);
    if (url.origin !== location.origin || a.hasAttribute("download") || url.pathname.indexOf("/backup") > -1 ||
        url.protocol === "mailto:" || (url.pathname === location.pathname && url.search === location.search && url.hash)) return;
    e.preventDefault();
    if (a.classList.contains("tab")) moveIndicator(a);
    document.body.classList.add("leaving");
    setTimeout(function () { location.href = a.href; }, reduce ? 0 : 230);
  });
  window.addEventListener("pageshow", function () { document.body.classList.remove("leaving"); });

  /* ---------- появление при прокрутке + счётчики ---------- */
  function countUp(el) {
    var target = parseFloat(el.dataset.count);
    if (isNaN(target)) return;
    var isTemp = el.textContent.indexOf("°") > -1;
    var dec = parseInt(el.dataset.decimals || "0", 10);
    var from = parseFloat(el.dataset.from || "0");
    var dur = 1200, start = null;
    if (reduce) { el.textContent = isTemp ? fmtTemp(target) : target.toFixed(dec); return; }
    function frame(ts) {
      if (start === null) start = ts;
      var k = Math.min((ts - start) / dur, 1), e = 1 - Math.pow(1 - k, 3);
      var v = from + (target - from) * e;
      el.textContent = isTemp ? fmtTemp(v) : v.toFixed(dec);
      if (k < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (!en.isIntersecting) return;
      var el = en.target;
      el.classList.add("in");
      $$("[data-count]", el).forEach(countUp);
      $$("[data-ring],[data-gauge]", el).forEach(function (x) { x.classList.add("in"); });
      io.unobserve(el);
    });
  }, { threshold: .12 }) : null;
  $$(".reveal, .stats, .facts").forEach(function (el) { io ? io.observe(el) : el.classList.add("in"); });
  if (!io) $$("[data-ring],[data-gauge]").forEach(function (x) { x.classList.add("in"); });

  /* ---------- уведомления ---------- */
  function hideToast(t) { t.classList.add("hide"); setTimeout(function () { t.remove(); }, 400); }
  function toast(msg, kind) {
    var box = $("#toasts"); if (!box) return;
    var t = document.createElement("div");
    t.className = "toast toast-" + (kind || "info");
    t.innerHTML = '<span></span><button type="button" class="toast-close" aria-label="Закрыть">×</button>';
    t.firstChild.textContent = msg;
    box.appendChild(t); bindToast(t);
  }
  function bindToast(t) {
    $(".toast-close", t).addEventListener("click", function () { hideToast(t); });
    setTimeout(function () { if (t.isConnected) hideToast(t); }, t.classList.contains("toast-error") ? 9000 : 5000);
  }
  $$(".toast").forEach(bindToast);

  /* ---------- волна при нажатии на кнопку ---------- */
  document.addEventListener("pointerdown", function (e) {
    var b = e.target.closest && e.target.closest(".btn, .chip, .tab");
    if (!b || reduce) return;
    var r = b.getBoundingClientRect(), s = Math.max(r.width, r.height);
    var w = document.createElement("span");
    w.className = "ripple";
    w.style.cssText = "width:" + s + "px;height:" + s + "px;left:" + (e.clientX - r.left - s / 2) + "px;top:" + (e.clientY - r.top - s / 2) + "px";
    if (getComputedStyle(b).position === "static") b.style.position = "relative";
    b.style.overflow = "hidden";
    b.appendChild(w); setTimeout(function () { w.remove(); }, 650);
  });

  /* ---------- подтверждение удаления ---------- */
  function confirmBox(text) {
    return new Promise(function (resolve) {
      var back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = '<div class="modal glass" role="dialog" aria-modal="true"><p></p><div class="row-actions">' +
        '<button type="button" class="btn btn-ghost" data-no>Отмена</button>' +
        '<button type="button" class="btn btn-danger" data-yes>Да, выполнить</button></div></div>';
      $("p", back).textContent = text;
      document.body.appendChild(back);
      var done = function (v) {
        back.classList.add("closing");
        setTimeout(function () { back.remove(); }, 200);
        document.removeEventListener("keydown", onKey);
        resolve(v);
      };
      var onKey = function (e) { if (e.key === "Escape") done(false); if (e.key === "Enter") done(true); };
      document.addEventListener("keydown", onKey);
      back.addEventListener("click", function (e) { if (e.target === back) done(false); });
      $("[data-no]", back).addEventListener("click", function () { done(false); });
      $("[data-yes]", back).addEventListener("click", function () { done(true); });
      $("[data-yes]", back).focus();
    });
  }
  $$("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.confirmed) return;
      e.preventDefault();
      confirmBox(f.dataset.confirm).then(function (ok) {
        if (ok) { f.dataset.confirmed = "1"; var b = $("button[type=submit]", f); if (b) b.classList.add("loading"); f.submit(); }
      });
    });
  });
  $$("form[data-loading]").forEach(function (f) {
    f.addEventListener("submit", function () { var b = $("button[type=submit]", f); if (b) b.classList.add("loading"); });
  });

  /* ---------- главная: смена города без перезагрузки ---------- */
  var citySelect = $("[data-switch-city]");
  if (citySelect) {
    var grid = $("[data-swap]");
    var bind = function (name) { return $('[data-bind="' + name + '"]'); };
    var setText = function (name, v) { var el = bind(name); if (el) el.textContent = v; };

    var iconFor = function (cond, size, cls) {
      var tpl = document.getElementById("icon-" + cond) || document.getElementById("icon-cloudy");
      var svg = tpl.content.firstElementChild.cloneNode(true);
      svg.setAttribute("width", size); svg.setAttribute("height", size);
      if (cls) svg.classList.add(cls);
      return svg;
    };

    var render = function (d) {
      var c = d.current;
      setText("city", d.city.name);
      setText("description", d.city.description || "");
      setText("condition", c.condition_label);
      setText("feels", c.feels_like_text);
      setText("updated", c.updated_at);
      setText("source", c.source);
      var icon = bind("icon"); icon.innerHTML = ""; icon.appendChild(iconFor(c.condition, 190, "float"));

      var t = bind("temp"); t.dataset.from = t.dataset.count; t.dataset.count = c.temperature; countUp(t);
      [["humidity", c.humidity, 0], ["wind", c.wind_speed, 1], ["pressure", c.pressure, 0]].forEach(function (x) {
        var el = bind(x[0]); el.dataset.from = el.dataset.count; el.dataset.count = x[1]; el.dataset.decimals = x[2]; countUp(el);
      });
      var ring = $("[data-ring]"); if (ring) ring.style.setProperty("--p", c.humidity);
      var gauge = $("[data-gauge]");
      if (gauge) gauge.style.setProperty("--a", Math.max(-90, Math.min(90, (c.pressure - 720) / 60 * 180 - 90)) + "deg");
      var wind = $("[data-bind-wind]"); if (wind) wind.style.setProperty("--speed", Math.max(8 / (c.wind_speed + .5), .25) + "s");

      var days = bind("days");
      days.innerHTML = "";
      d.forecast.slice(0, 5).forEach(function (f, i) {
        var el = document.createElement("div");
        el.className = "day stagger"; el.style.setProperty("--i", i);
        el.innerHTML = '<span class="day-name"></span><span class="muted small"></span><span class="ic"></span>' +
                       '<span class="day-temps"><b></b> <span class="muted"></span></span>';
        el.children[0].textContent = f.label;
        el.children[1].textContent = f.day_month;
        el.children[2].replaceWith(iconFor(f.condition, 54));
        $("b", el).textContent = f.temp_max_text;
        $(".day-temps .muted", el).textContent = f.temp_min_text;
        days.appendChild(el);
      });
      if (!d.forecast.length) days.innerHTML = '<p class="muted">Прогноз пока не заполнен.</p>';

      document.body.dataset.sky = c.condition;
      if (window.Sky) window.Sky.set(c.condition);
      document.title = "Погода: " + d.city.name + " · Небосвод";
    };

    citySelect.addEventListener("change", function () {
      var id = citySelect.value;
      if (!bind("humidity")) { location.href = "/?city=" + id; return; }
      grid.classList.add("swapping");
      Promise.all([fetch("/api/weather/" + id).then(function (r) { if (!r.ok) throw r; return r.json(); }), wait(reduce ? 0 : 320)])
        .then(function (res) {
          var d = res[0];
          if (!d.current) { location.href = "/?city=" + id; return; }
          render(d);
          history.replaceState(null, "", "/?city=" + id);
          grid.classList.remove("swapping");
        })
        .catch(function () { grid.classList.remove("swapping"); toast("Не удалось загрузить данные города", "error"); });
    });

    // начальное положение стрелки давления (с ограничением шкалы)
    var g0 = $("[data-gauge]"), p0 = bind("pressure");
    if (g0 && p0) g0.style.setProperty("--a", Math.max(-90, Math.min(90, (parseFloat(p0.dataset.count) - 720) / 60 * 180 - 90)) + "deg");
  }

  /* ---------- города: поиск и сортировка ---------- */
  var cityGrid = $("#city-grid");
  if (cityGrid) {
    var cards = $$(".city-card", cityGrid), search = $("#city-search"), none = $("#no-cities");
    var filter = function () {
      var q = search.value.trim().toLowerCase(), shown = 0;
      cards.forEach(function (c) {
        var ok = c.dataset.name.indexOf(q) > -1;
        c.classList.toggle("filtered-out", !ok);
        if (ok) shown++;
      });
      none.classList.toggle("hidden", shown > 0);
    };
    search.addEventListener("input", filter);
    $$("#city-sort button").forEach(function (b) {
      b.addEventListener("click", function () {
        $$("#city-sort button").forEach(function (x) { x.classList.toggle("active", x === b); });
        var key = b.dataset.sort;
        // FLIP-анимация перестановки карточек
        var before = new Map(cards.map(function (c) { return [c, c.getBoundingClientRect()]; }));
        cards.sort(function (a, z) {
          if (key === "name") return a.dataset.name.localeCompare(z.dataset.name, "ru");
          var ta = parseFloat(a.dataset.temp), tz = parseFloat(z.dataset.temp);
          return key === "warm" ? tz - ta : ta - tz;
        });
        cards.forEach(function (c) { cityGrid.appendChild(c); });
        if (reduce) return;
        cards.forEach(function (c) {
          var r0 = before.get(c), r1 = c.getBoundingClientRect();
          var dx = r0.left - r1.left, dy = r0.top - r1.top;
          if (!dx && !dy) return;
          c.style.animation = "none"; c.style.opacity = "1";
          c.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }],
                    { duration: 600, easing: "cubic-bezier(.22,1,.36,1)" });
        });
      });
    });
  }

  /* ---------- обратная связь: счётчик символов и проверка ---------- */
  $$("[data-counter-for]").forEach(function (c) {
    var t = document.getElementById(c.dataset.counterFor);
    var upd = function () { c.textContent = t.value.length + " / 2000"; };
    t.addEventListener("input", upd); upd();
  });
  $$("form[data-validate]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var bad = false;
      $$(".field", f).forEach(function (fl) {
        var inp = $("input, textarea", fl), err = $(".field-error", fl);
        if (!inp) return;
        var msg = "";
        if (inp.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(inp.value.trim())) msg = "Укажите корректный e-mail.";
        else if (inp.minLength > 0 && inp.value.trim().length < inp.minLength) msg = "Слишком коротко (минимум " + inp.minLength + " симв.).";
        fl.classList.remove("has-error"); void fl.offsetWidth;
        if (msg) { bad = true; fl.classList.add("has-error"); }
        if (err) err.textContent = msg;
      });
      if (bad) e.preventDefault(); else { var b = $("button[type=submit]", f); if (b) b.classList.add("loading"); }
    });
  });

  /* ---------- админ: SQL-консоль ---------- */
  var sqlForm = $("#sql-form");
  if (sqlForm) {
    var ta = $("textarea", sqlForm);
    $$("[data-sql]").forEach(function (b) {
      b.addEventListener("click", function () { ta.value = b.dataset.sql; ta.focus(); });
    });
    ta.addEventListener("keydown", function (e) { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sqlForm.submit(); } });
  }

  /* ---------- админ: поиск координат города ---------- */
  var geoBtn = $("#geocode-btn");
  if (geoBtn) {
    var box = $("#geo-results");
    geoBtn.addEventListener("click", function () {
      var name = $("#c-name").value.trim();
      if (!name) { toast("Сначала введите название города", "error"); return; }
      geoBtn.classList.add("loading"); box.innerHTML = "";
      fetch(geoBtn.dataset.url + "?name=" + encodeURIComponent(name))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error) { toast(d.error, "error"); return; }
          if (!d.results.length) { toast("Город не найден, введите координаты вручную", "error"); return; }
          d.results.forEach(function (r) {
            var b = document.createElement("button");
            b.type = "button"; b.className = "chip";
            b.textContent = r.name + (r.region ? ", " + r.region : "") + (r.country ? " (" + r.country + ")" : "");
            b.addEventListener("click", function () {
              $("#c-name").value = r.name; $("#c-country").value = r.country || "";
              $("#c-lat").value = r.latitude; $("#c-lon").value = r.longitude;
              box.innerHTML = ""; toast("Координаты подставлены", "success");
            });
            box.appendChild(b);
          });
        })
        .catch(function () { toast("Нет связи с сервером", "error"); })
        .then(function () { geoBtn.classList.remove("loading"); });
    });
  }

  window.UI = { toast: toast, fmtTemp: fmtTemp };
})();
