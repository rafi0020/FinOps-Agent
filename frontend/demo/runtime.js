/*
 * Demo runtime. Injected into the GitHub Pages build only; the real deployment never loads it.
 *
 * The page talks to the same /api/... URLs it always does. This script answers those requests in the browser
 * from fixtures.json, which was recorded from the real system (API, database, worker and model) by record.mjs.
 * Sign-in is checked against the recorded demo accounts, runs and events are replayed with their original
 * timing, and anything that would change data is acknowledged but not stored.
 */
(function () {
  "use strict";
  var cfg = window.__DEMO__ || {};
  var BASE = cfg.base || "";
  var USER_KEY = "demo.user";
  var realFetch = window.fetch.bind(window);
  var fixtures = null;
  var ready = realFetch(BASE + "/demo/fixtures.json").then(function (r) { return r.json(); }).then(function (f) { fixtures = f; return f; });
  var seqStart = {};

  function store(get, set) {
    try { return get ? localStorage.getItem(USER_KEY) : set === null ? localStorage.removeItem(USER_KEY) : localStorage.setItem(USER_KEY, set); } catch (e) { return null; }
  }
  function currentUser() { var u = store(true); return u && fixtures.users[u] ? u : null; }

  /** "/x/api/runs?b=2&a=1" -> {path: "/api/runs", key: "/api/runs?a=1&b=2"}; null when it is not an API call. */
  function parse(input) {
    var url;
    try { url = new URL(typeof input === "string" ? input : input.url, location.href); } catch (e) { return null; }
    var i = url.pathname.indexOf("/api/");
    if (i < 0) return null;
    var path = url.pathname.slice(i);
    var params = Array.from(url.searchParams.entries()).sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1; });
    var query = params.map(function (p) { return encodeURIComponent(p[0]) + "=" + encodeURIComponent(p[1]); }).join("&");
    return { path: path, key: query ? path + "?" + query : path };
  }

  function respond(status, body, extra) {
    var headers = { "Content-Type": "application/json" };
    if (extra) for (var k in extra) headers[k] = extra[k];
    if (status === 204 || status === 205) return new Response(null, { status: status });
    return new Response(JSON.stringify(body === undefined ? null : body), { status: status, headers: headers });
  }
  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /** A recorded GET may be one body or a timeline of bodies (a run that was still working when first read). */
  function pick(entry, id) {
    if (!entry) return null;
    if (!entry.seq) return entry;
    if (!seqStart[id]) seqStart[id] = Date.now();
    var elapsed = (Date.now() - seqStart[id]) / (entry.scale || 1);
    var chosen = entry.seq[0];
    for (var i = 0; i < entry.seq.length; i++) if (entry.seq[i].t <= elapsed) chosen = entry.seq[i];
    return chosen;
  }

  function tokens(value) {
    return String(typeof value === "string" ? value : JSON.stringify(value || "")).toLowerCase().match(/[a-z0-9]{3,}/g) || [];
  }
  function similarity(a, b) {
    var ta = tokens(a), tb = tokens(b);
    if (!ta.length || !tb.length) return 0;
    var set = {}; tb.forEach(function (t) { set[t] = 1; });
    var hit = ta.filter(function (t) { return set[t]; }).length;
    return hit / Math.max(ta.length, tb.length);
  }
  function bestWrite(list, body) {
    var best = list[0], score = -1;
    list.forEach(function (w) {
      var s = JSON.stringify(w.req) === JSON.stringify(body) ? 2 : similarity(w.req, body);
      if (s > score) { score = s; best = w; }
    });
    return best;
  }

  function sources() {
    var u = currentUser();
    return u ? [fixtures.users[u], fixtures.anon] : [fixtures.anon];
  }

  async function handle(method, req, init, input) {
    await ready;
    var login = fixtures.login || {};
    var body = null;
    if (init && typeof init.body === "string") { try { body = JSON.parse(init.body); } catch (e) { body = init.body; } }
    else if (input && typeof input !== "string" && input.clone && method !== "GET") { try { body = await input.clone().json(); } catch (e) { body = null; } }

    if (method === "POST" && req.path === login.path) {
      var email = String((body && (body.email || body.username)) || "").trim().toLowerCase();
      var account = fixtures.users[email];
      await delay(250);
      if (account && body && body.password === account.password) { store(false, email); return respond(account.login.status, account.login.body); }
      return respond(401, { detail: "Incorrect e-mail or password." });
    }
    if (method === "POST" && req.path === login.logout) { store(false, null); return respond(204); }
    if (req.path.indexOf("/auth/signup") > 0 && method === "POST") return respond(403, { detail: "Sign-up is turned off in the demo. Use one of the demo accounts." });

    await delay(40 + Math.random() * 60);
    var scopes = sources();

    if (method === "GET" || method === "HEAD") {
      for (var i = 0; i < scopes.length; i++) {
        var routes = scopes[i].routes || {};
        var hit = routes[req.key] || routes[req.path];
        if (hit) { var chosen = pick(hit, (currentUser() || "anon") + req.key); return respond(chosen.status, chosen.body); }
      }
      if (!currentUser() && req.path.indexOf("/auth/") < 0) return respond(401, { detail: "Not signed in." });
      if (req.path.indexOf("/auth/me") > 0) return respond(401, { detail: "Not signed in." });
      return respond(404, { detail: "That is not part of the recorded demo." });
    }

    for (var j = 0; j < scopes.length; j++) {
      var list = (scopes[j].writes || {})[method + " " + req.path];
      if (list && list.length) { var w = bestWrite(list, body); return respond(w.status, w.body); }
    }
    if (!currentUser()) return respond(401, { detail: "Not signed in." });
    return respond(200, { ok: true, demo: true });
  }

  window.fetch = function (input, init) {
    var req = parse(input);
    if (!req) return realFetch(input, init);
    var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    return handle(method, req, init, input);
  };

  /** Server-sent events: replay the recorded stream for the same path, at the pace it was recorded. */
  function DemoEventSource(url) {
    var self = this;
    this.url = String(url);
    this.readyState = 0;
    this.withCredentials = true;
    this.onopen = this.onmessage = this.onerror = null;
    this._listeners = {};
    this._timers = [];
    ready.then(function () {
      if (self.readyState === 2) return;
      var req = parse(self.url);
      var rec = null;
      var scopes = sources();
      var all = Object.keys(fixtures.users).map(function (k) { return fixtures.users[k]; });
      scopes.concat(all).forEach(function (s) { if (!rec && req && s.sse && s.sse[req.path]) rec = s.sse[req.path]; });
      self.readyState = 1;
      if (self.onopen) self.onopen(new Event("open"));
      if (!rec) return;
      rec.events.forEach(function (ev) {
        self._timers.push(setTimeout(function () {
          if (self.readyState === 2) return;
          self._emit(ev.type || "message", ev.data, ev.id);
        }, Math.round(ev.t * (rec.scale || 1))));
      });
    });
  }
  DemoEventSource.CONNECTING = 0; DemoEventSource.OPEN = 1; DemoEventSource.CLOSED = 2;
  DemoEventSource.prototype.addEventListener = function (type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); };
  DemoEventSource.prototype.removeEventListener = function (type, fn) { this._listeners[type] = (this._listeners[type] || []).filter(function (f) { return f !== fn; }); };
  DemoEventSource.prototype._emit = function (type, data, id) {
    var event = new MessageEvent(type, { data: data, lastEventId: id || "" });
    (this._listeners[type] || []).slice().forEach(function (fn) { fn.call(this, event); }, this);
    if (type === "message" && this.onmessage) this.onmessage(event);
  };
  DemoEventSource.prototype.close = function () { this.readyState = 2; this._timers.forEach(clearTimeout); };
  window.EventSource = DemoEventSource;

  /* ---- the pages link to "/ask/" and similar; on Pages the site lives under /<repository>/, so add that prefix ---- */
  function fixLinks() {
    if (!BASE) return;
    var links = document.querySelectorAll('a[href^="/"]');
    for (var i = 0; i < links.length; i++) {
      var h = links[i].getAttribute("href");
      if (h.indexOf("//") !== 0 && h !== BASE && h.indexOf(BASE + "/") !== 0) links[i].setAttribute("href", BASE + h);
    }
  }
  function watchLinks() {
    fixLinks();
    new MutationObserver(fixLinks).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["href"] });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watchLinks); else watchLinks();

  /* ---- a small, dismissible note so nobody mistakes the demo for a live deployment ---- */
  function note() {
    if (document.getElementById("demo-note")) return;
    var box = document.createElement("div");
    box.id = "demo-note";
    box.setAttribute("role", "note");
    box.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2147483000;max-width:min(360px,calc(100vw - 24px));font:12px/1.45 system-ui,sans-serif;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:10px;padding:9px 30px 9px 12px;box-shadow:0 6px 24px rgba(0,0,0,.35)";
    var text = document.createElement("span");
    text.textContent = (cfg.title || "This") + " demo replays data recorded from the running system. Changes are not saved. ";
    var link = document.createElement("a");
    link.href = cfg.repo || "#"; link.target = "_blank"; link.rel = "noopener";
    link.textContent = "Source on GitHub";
    link.style.cssText = "color:#7dd3fc;text-decoration:underline";
    var close = document.createElement("button");
    close.type = "button"; close.setAttribute("aria-label", "Dismiss"); close.textContent = "×";
    close.style.cssText = "position:absolute;top:4px;right:6px;border:0;background:transparent;color:#94a3b8;font-size:18px;cursor:pointer;line-height:1";
    close.onclick = function () { box.remove(); try { sessionStorage.setItem("demo.note", "off"); } catch (e) {} };
    box.appendChild(text); box.appendChild(link); box.appendChild(close);
    document.body.appendChild(box);
  }
  function start() { try { if (sessionStorage.getItem("demo.note") === "off") return; } catch (e) {} note(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
