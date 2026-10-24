(function () {
  "use strict";
  var TOKEN = new URLSearchParams(location.search).get("t") || "";
  var $ = function (id) { return document.getElementById(id); };
  var log = $("log"), steps = $("steps"), pending = [], lastSeq = 0, working = false;
  var cards = {}, stepEls = {};

  function api(path, body) {
    return fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (j) { j._status = r.status; return j; }); });
  }

  // safe text renderer: paragraphs, "- " lists, **bold**; no innerHTML anywhere
  function inline(el, s) {
    s.split(/(\*\*[^*]+\*\*)/).forEach(function (p) {
      if (/^\*\*.+\*\*$/.test(p)) { var b = document.createElement("b"); b.textContent = p.slice(2, -2); el.appendChild(b); }
      else if (p) el.appendChild(document.createTextNode(p));
    });
  }
  function render(el, text) {
    var ul = null;
    String(text || "").split("\n").forEach(function (line) {
      var m = /^\s*[-*]\s+(.*)$/.exec(line);
      if (m) {
        if (!ul) { ul = document.createElement("ul"); el.appendChild(ul); }
        var li = document.createElement("li"); inline(li, m[1]); ul.appendChild(li);
      } else if (line.trim()) {
        ul = null; var p = document.createElement("p"); inline(p, line); el.appendChild(p);
      } else ul = null;
    });
  }
  function add(node) {
    var e = $("empty"); if (e) e.remove();
    log.appendChild(node); log.scrollTop = log.scrollHeight;
  }
  function msg(kind, text) {
    var d = document.createElement("div"); d.className = "msg " + kind; render(d, text); add(d);
  }

  var LABEL = { get_state: "Состояние слайсера", set_print_mode: "Режим печати", set_material: "Материал",
    set_quality: "Профиль качества", search_settings: "Поиск параметров", set_settings: "Настройки печати",
    get_material_recipe: "Рецепт материала", load_model: "Загрузка модели", list_objects: "Объекты на столе",
    transform_model: "Преобразование модели", delete_model: "Удаление модели", arrange_all: "Расстановка",
    analyze_orientation: "Анализ ориентации", apply_orientation: "Применение ориентации", slice: "Нарезка",
    export_gcode: "Экспорт G-code", save_project_3mf: "Сохранение проекта 3MF" };

  function toolCall(e) {
    var d = document.createElement("details"); d.className = "tool run";
    var s = document.createElement("summary");
    var n = document.createElement("span"); n.className = "n"; n.textContent = LABEL[e.name] || e.name;
    var st = document.createElement("span"); st.className = "st"; st.textContent = "выполняется";
    s.appendChild(n); s.appendChild(st); d.appendChild(s);
    var pre = document.createElement("pre"); pre.textContent = JSON.stringify(e.args, null, 2); d.appendChild(pre);
    add(d); cards[e.id] = { d: d, st: st, pre: pre };
    var li = document.createElement("li"); li.className = "run";
    var dot = document.createElement("span"); dot.className = "d"; var lab = document.createElement("span"); lab.textContent = LABEL[e.name] || e.name; li.appendChild(dot); li.appendChild(lab);
    steps.appendChild(li); stepEls[e.id] = li; $("bar").hidden = false;
  }
  function toolResult(e) {
    var bad = e.result && e.result.error, c = cards[e.id], li = stepEls[e.id];
    if (c) {
      c.d.className = "tool " + (bad ? "err" : "ok"); c.st.textContent = bad ? "ошибка" : "готово";
      var out = document.createElement("pre"); out.textContent = JSON.stringify(e.result, null, 2); c.d.appendChild(out);
    }
    if (li) li.className = bad ? "err" : "ok";
    if (e.name === "slice" && !bad) showResult(e.result);
    if ((e.name === "export_gcode" || e.name === "save_project_3mf") && !bad) addPath(e.result.path);
  }
  function showResult(r) {
    var res = $("result"); res.textContent = "";
    var dl = document.createElement("dl");
    [["Время печати", r.print_time_min != null ? Math.floor(r.print_time_min / 60) + " ч " + (r.print_time_min % 60) + " мин" : "—"],
     ["Материал", r.material_g != null ? r.material_g + " г" : "—"]].forEach(function (p) {
      var a = document.createElement("dt"), b = document.createElement("dd"); a.textContent = p[0]; b.textContent = p[1]; dl.appendChild(a); dl.appendChild(b);
    });
    res.appendChild(dl);
  }
  function addPath(p) {
    var res = $("result"), d = document.createElement("div"); d.className = "path"; d.textContent = p; res.appendChild(d);
  }

  function setWorking(w) { working = w; $("send").disabled = w; $("send").textContent = w ? "Работаю…" : "Отправить"; if (!w) $("bar").hidden = true; }

  function onEvent(e) {
    lastSeq = e.seq || lastSeq;
    if (e.type === "user") msg("user", e.text + (e.files && e.files.length ? "\n[Файлы: " + e.files.join(", ") + "]" : ""));
    else if (e.type === "assistant") msg("assistant", e.text);
    else if (e.type === "error") msg("error", e.text);
    else if (e.type === "tool_call") toolCall(e);
    else if (e.type === "tool_result") toolResult(e);
    else if (e.type === "progress") { $("barfill").style.width = Math.round(e.value * 100) + "%"; $("bar").hidden = false; }
    else if (e.type === "status") setWorking(e.state === "working");
  }

  function connect() {
    var es = new EventSource("/api/events?t=" + encodeURIComponent(TOKEN) + "&after=" + lastSeq);
    es.onopen = function () { $("conn").textContent = "связь есть"; $("conn").className = "conn on"; };
    es.onmessage = function (m) { try { onEvent(JSON.parse(m.data)); } catch (x) { /* ignore malformed */ } };
    es.onerror = function () { $("conn").textContent = "нет связи"; $("conn").className = "conn"; };
  }

  function readFile(f) {
    return new Promise(function (ok, fail) {
      var r = new FileReader();
      r.onload = function () { ok({ name: f.name, mime: f.type, b64: String(r.result).split(",")[1] }); };
      r.onerror = fail; r.readAsDataURL(f);
    });
  }
  function drawFiles() {
    var box = $("files"); box.textContent = "";
    pending.forEach(function (f, i) {
      var s = document.createElement("span"); s.textContent = f.name;
      var x = document.createElement("button"); x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Убрать " + f.name);
      x.onclick = function () { pending.splice(i, 1); drawFiles(); };
      s.appendChild(x); box.appendChild(s);
    });
  }
  $("file").onchange = function (ev) {
    Promise.all(Array.prototype.map.call(ev.target.files, readFile)).then(function (arr) { pending = pending.concat(arr); drawFiles(); });
    ev.target.value = "";
  };

  function send() {
    var text = $("text").value.trim();
    if (working || (!text && !pending.length)) return;
    var body = { text: text, attachments: pending };
    $("text").value = ""; pending = []; drawFiles(); steps.textContent = ""; $("result").textContent = "Появится после нарезки.";
    api("/api/message", body).then(function (r) { if (r.error) msg("error", r.error); });
  }
  $("send").onclick = send;
  $("text").onkeydown = function (e) { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); };
  Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (c) { c.onclick = function () { $("text").value = c.textContent; $("text").focus(); }; });
  $("btn-reset").onclick = function () { api("/api/reset", {}).then(function () { log.textContent = ""; steps.textContent = ""; lastSeq = 0; cards = {}; stepEls = {}; msg("assistant", "Новый диалог."); }); };

  var dlg = $("dlg");
  function openSettings() {
    api("/api/settings").then(function (s) {
      $("s-url").value = s.base_url || ""; $("s-model").value = s.model || ""; $("s-out").value = s.output_dir || ""; $("s-key").value = "";
      $("s-msg").textContent = s.has_key ? "Ключ сохранён." : "Ключ не задан."; dlg.showModal();
    });
  }
  function saveSettings() {
    return api("/api/settings", { base_url: $("s-url").value, model: $("s-model").value, output_dir: $("s-out").value, api_key: $("s-key").value })
      .then(function (s) { $("s-key").value = ""; $("s-msg").textContent = s.has_key ? "Сохранено. Ключ задан." : "Сохранено. Ключ не задан."; });
  }
  $("btn-settings").onclick = openSettings;
  $("s-save").onclick = function () { saveSettings().then(function () { dlg.close(); }); };
  $("s-test").onclick = function () {
    $("s-msg").textContent = "Проверяю…";
    saveSettings().then(function () { return api("/api/test", {}); }).then(function (r) {
      $("s-msg").textContent = r.ok ? "Соединение работает." : "Ошибка: " + r.error;
    });
  };

  connect();
  api("/api/settings").then(function (s) { if (!s.has_key) msg("error", "Не задан API-ключ. Откройте «Настройки» и введите ключ."); });
})();
