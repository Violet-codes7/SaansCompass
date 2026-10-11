// The pollution map (home page) and Cleaner route (plan page), drawn with
// MapLibre on Amazon Location Service's base map. Settings, words and the
// base map come from the page (#map-data); colours from the AQI tokens in app.css.
(function () {
  var D = JSON.parse(document.getElementById("map-data").textContent);
  var root = document.documentElement;
  var lib;

  function hi() { return root.lang === "hi"; }
  function say(set, key, vars) {
    var s = (set[key] || {})[hi() ? "hi" : "en"] || "";
    Object.keys(vars || {}).forEach(function (k) { s = s.split("{" + k + "}").join(vars[k]); });
    return s;
  }
  function colour(slug) {
    var v = getComputedStyle(root).getPropertyValue("--" + (slug === "no-data" ? "none" : slug)).trim();
    return v || getComputedStyle(root).getPropertyValue("--none").trim();
  }
  function scheme() { return root.dataset.theme === "dark" ? "dark" : "light"; }
  function baseStyle() { var s = D.styles[scheme()] || D.styles.light; return s.url || s.style; }
  function phone() { return window.matchMedia("(max-width: 600px)").matches; }

  function loadLib() {
    if (lib) return lib;
    lib = new Promise(function (ok, fail) {
      var css = document.createElement("link");
      css.rel = "stylesheet"; css.href = D.lib_css;
      document.head.appendChild(css);
      var js = document.createElement("script");
      js.src = D.lib_js; js.onload = ok; js.onerror = fail;
      document.head.appendChild(js);
    });
    return lib;
  }

  // A map that redraws its own layers whenever the base style loads (first
  // time, and when the light/dark switch changes it).
  function makeMap(el, draw) {
    var map = new maplibregl.Map({container: el, style: baseStyle(), center: D.center,
      zoom: phone() ? D.phone_zoom : D.zoom, minZoom: D.min_zoom, maxZoom: D.max_zoom,
      attributionControl: {compact: true}, cooperativeGestures: true});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");
    map.on("style.load", function () { map.ready = true; draw(); });
    new MutationObserver(function () { map.ready = false; map.setStyle(baseStyle()); })
      .observe(root, {attributes: true, attributeFilter: ["data-theme"]});
    return map;
  }

  function getJSON(url) {
    return fetch(url, {headers: {"Accept": "application/json"}})
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function popupFor(p) {
    var box = document.createElement("div"), b = document.createElement("b"), line = document.createElement("div");
    box.className = "map-pop";
    b.textContent = p.name;
    line.textContent = say(D.text, "aqi", {aqi: p.aqi}) + " · " + p.category + (p.time ? " · " + p.time : "");
    box.appendChild(b); box.appendChild(line);
    return box;
  }

  // Home page: stations around the centre.
  var stationsEl = document.getElementById("air-map");
  if (stationsEl) {
    var status = document.getElementById("air-map-status");
    var geo = null, smap = null;
    var drawStations = function () {
      if (!geo || !smap || !smap.ready) return;
      geo.features.forEach(function (f) { f.properties.colour = colour(f.properties.slug); });
      if (smap.getSource("stations")) { smap.getSource("stations").setData(geo); return; }
      smap.addSource("stations", {type: "geojson", data: geo});
      smap.addLayer({id: "stations", type: "circle", source: "stations", paint: {
        "circle-color": ["get", "colour"], "circle-radius": D.radius,
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5, "circle-opacity": 0.92}});
      if (smap.listening) return;
      smap.listening = true;
      smap.on("click", "stations", function (e) {
        new maplibregl.Popup({closeButton: false}).setLngLat(e.features[0].geometry.coordinates)
          .setDOMContent(popupFor(e.features[0].properties)).addTo(smap);
      });
      smap.on("mouseenter", "stations", function () { smap.getCanvas().style.cursor = "pointer"; });
      smap.on("mouseleave", "stations", function () { smap.getCanvas().style.cursor = ""; });
    };
    Promise.all([loadLib(), getJSON(stationsEl.dataset.api)]).then(function (res) {
      var d = res[1];
      geo = {type: "FeatureCollection", features: d.stations.map(function (s) {
        return {type: "Feature", geometry: {type: "Point", coordinates: [s.lon, s.lat]}, properties: s};
      })};
      smap = makeMap(stationsEl, drawStations);
      var times = d.stations.map(function (s) { return s.time; }).filter(Boolean).sort();
      status.textContent = d.source === "forecast" ? say(D.text, "model")
        : say(D.text, "stations", {count: d.stations.length}) + (times.length ? " · " + say(D.text, "updated", {time: times[times.length - 1]}) : "");
    }).catch(function () {
      stationsEl.hidden = true;
      status.textContent = say(D.text, "failed");
    });
  }

  // Plan page: the routes for the trip, cleanest first on the map.
  var routeBox = document.getElementById("clean-route");
  if (routeBox) {
    var rstatus = routeBox.querySelector(".map-status"), list = routeBox.querySelector(".route-list");
    var R = D.route_text, routes = null, best = null, rmap = null;
    var drawRoutes = function () {
      if (!routes || !rmap || !rmap.ready) return;
      var order = routes.slice().sort(function (a, b) { return (a.n === best) - (b.n === best); });  // cleanest on top
      var other = 0;
      var geo = {type: "FeatureCollection", features: order.map(function (r) {
        var c = r.n === best ? D.line_colours[0] : D.line_colours[Math.min(++other, D.line_colours.length - 1)];
        return {type: "Feature", geometry: {type: "LineString", coordinates: r.coords},
          properties: {colour: c, width: r.n === best ? 6 : 4}};
      })};
      if (rmap.getSource("routes")) { rmap.getSource("routes").setData(geo); return; }
      rmap.addSource("routes", {type: "geojson", data: geo});
      rmap.addLayer({id: "routes", type: "line", source: "routes", layout: {"line-cap": "round", "line-join": "round"},
        paint: {"line-color": ["get", "colour"], "line-width": ["get", "width"], "line-opacity": 0.9}});
    };
    Promise.all([loadLib(), getJSON(routeBox.dataset.api)]).then(function (res) {
      var d = res[1];
      if (!d.suggest) return;  // the usual way's air is fine today: nothing to show
      routeBox.hidden = false;
      routes = d.routes; best = d.best;
      var usual = routes[0], pick = routes.filter(function (r) { return r.n === best; })[0];
      rstatus.textContent = say(R, "lead", {n: best, pct: d.pct, aqi: pick.aqi, usual: usual.aqi});
      routes.forEach(function (r) {
        var li = document.createElement("li"), head = document.createElement("b"), sum = document.createElement("span");
        li.className = "route-item" + (r.n === best ? " best" : "");
        head.textContent = r.n === usual.n ? say(R, "usual") : say(R, "route", {n: r.n});
        if (r.n === best) {
          var tag = document.createElement("span"); tag.className = "chip-best"; tag.textContent = say(R, "cleanest");
          head.appendChild(document.createTextNode(" ")); head.appendChild(tag);
        }
        sum.textContent = say(R, "summary", {km: r.km, min: r.min == null ? "–" : r.min, aqi: r.aqi == null ? "–" : r.aqi});
        li.appendChild(head); li.appendChild(sum);
        if (r.slug) li.style.borderLeftColor = colour(r.slug);
        list.appendChild(li);
      });
      rmap = makeMap(routeBox.querySelector(".route-map"), drawRoutes);
      var b = new maplibregl.LngLatBounds();
      routes.forEach(function (r) { r.coords.forEach(function (c) { b.extend(c); }); });
      rmap.fitBounds(b, {padding: 30, animate: false});
    }).catch(function () { routeBox.hidden = true; });
  }
})();
