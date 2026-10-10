// English / Hindi switch for the whole page. Sends the page's visible text to
// /api/translate (built-in dictionary, then Amazon Translate) and swaps it in
// place; switching back restores the original English.
(function () {
  var api = document.currentScript.dataset.api;
  var status = document.getElementById("lang-status");
  var KEY = "saans-lang";
  var originals = new Map();   // text node -> English text
  var placeholders = new Map(); // element -> English placeholder
  var SKIP = "script,style,code,textarea,[translate=no]";
  var MSG = {busy: "अनुवाद हो रहा है…", partial: "कुछ हिस्से अंग्रेज़ी में ही रहेंगे।", fail: "अनुवाद अभी उपलब्ध नहीं है।"};

  function textNodes() {
    var out = [];
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!/[A-Za-z]{2}/.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
        if (n.parentElement && n.parentElement.closest(SKIP)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (walker.nextNode()) out.push(walker.currentNode);
    return out;
  }

  function setPressed(lang) {
    document.querySelectorAll("[data-setlang]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.setlang === lang);
    });
  }

  function remember(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) {}
  }

  function toEnglish() {
    originals.forEach(function (text, node) { node.nodeValue = text; });
    placeholders.forEach(function (text, el) { el.placeholder = text; });
    document.documentElement.lang = "en";
    status.textContent = "";
    setPressed("en");
  }

  function toHindi() {
    document.documentElement.lang = "hi";
    setPressed("hi");
    var nodes = textNodes();
    var fields = Array.prototype.filter.call(document.querySelectorAll("[placeholder]"), function (el) {
      return !el.closest("[translate=no]");
    });
    var items = [];
    nodes.forEach(function (n) {
      if (!originals.has(n)) originals.set(n, n.nodeValue);
      items.push({node: n, text: originals.get(n)});
    });
    fields.forEach(function (el) {
      if (!placeholders.has(el)) placeholders.set(el, el.placeholder);
      items.push({field: el, text: placeholders.get(el)});
    });
    function key(t) { return t.replace(/\s+/g, " ").trim(); }
    var unique = Array.from(new Set(items.map(function (i) { return key(i.text); })));
    var batches = [];
    for (var i = 0; i < unique.length; i += 300) batches.push(unique.slice(i, i + 300));
    status.textContent = MSG.busy;
    return Promise.all(batches.map(function (batch) {
      return fetch(api, {method: "POST", headers: {"Content-Type": "application/json"},
                         body: JSON.stringify({to: "hi", texts: batch})})
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) { return {src: batch, dst: d.texts, complete: d.complete}; });
    })).then(function (results) {
      if (document.documentElement.lang !== "hi") return;  // switched back meanwhile
      var map = new Map(), partial = false;
      results.forEach(function (r) {
        if (!r.complete) partial = true;
        r.src.forEach(function (s, k) { map.set(s, r.dst[k]); });
      });
      items.forEach(function (it) {
        var t = it.text, hi = map.get(key(t));
        if (!hi) return;
        var lead = /^\s*/.exec(t)[0], tail = /\s*$/.exec(t)[0];
        if (it.node) it.node.nodeValue = lead + hi + tail; else it.field.placeholder = hi;
      });
      status.textContent = partial ? MSG.partial : "";
    }).catch(function () { status.textContent = MSG.fail; });
  }

  document.querySelectorAll("[data-setlang]").forEach(function (b) {
    b.addEventListener("click", function () {
      var lang = b.dataset.setlang;
      if (document.documentElement.lang === lang) return;
      remember(lang);
      if (lang === "hi") toHindi(); else toEnglish();
      document.dispatchEvent(new CustomEvent("saans:lang", {detail: lang}));
    });
  });

  // The head script already set lang="hi" from the link or the saved choice.
  if (document.documentElement.lang === "hi") toHindi(); else setPressed("en");
})();
