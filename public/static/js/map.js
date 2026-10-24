/* Leaflet + OpenStreetMap helpers. All popup content is built with textContent (no HTML injection). */
(function () {
  "use strict";
  var TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  var ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  var DEFAULT_CENTER = [28.4744, 77.5040]; // Greater Noida
  function inr(n) { return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }); }
  function osmUrl(lat, lng) { return "https://www.openstreetmap.org/?mlat=" + lat + "&mlon=" + lng + "#map=14/" + lat + "/" + lng; }
  function el(tag, props, kids) {
    var e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) { if (k === "text") e.textContent = props[k]; else e.setAttribute(k, props[k]); });
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  var _activeMaps = {};
  function pin(cls, text) {
    if (text !== undefined && text !== null && text !== "") {
      return L.divIcon({ className: "", html: '<div class="pin ' + (cls || "") + '">' + text + '</div>', iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -14] });
    }
    return L.divIcon({ className: "", html: '<div class="pin ' + (cls || "") + '"></div>', iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -28] });
  }
  function baseMap(id, center, zoom) {
    var box = document.getElementById(id), fb = document.getElementById(id + "-fallback");
    if (!box) return null;
    if (typeof L === "undefined") {
      box.style.display = "none";
      if (fb) {
        fb.style.display = "block";
        fb.textContent = window.t ? window.t("leaflet_offline", "Map library could not load offline. Route optimization and calculations continue to function.") : "Map library could not load offline. Route optimization and calculations continue to function.";
      }
      return null;
    }
    // Cleanly destroy any existing Leaflet map on this container to prevent "Map container is already initialized"
    if (_activeMaps[id]) {
      try {
        _activeMaps[id].remove();
      } catch (err) {
        console.warn("Could not remove previous map for " + id, err);
      }
      delete _activeMaps[id];
    }
    if (box._leaflet_id) {
      box._leaflet_id = null;
    }
    box.style.display = "block";
    if (fb) fb.style.display = "none";

    var map = L.map(id, { scrollWheelZoom: true }).setView(center, zoom);
    _activeMaps[id] = map;

    var errors = 0, shown = false;
    var layer = L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTR });
    layer.on("tileerror", function () {
      errors++;
      if (errors > 3 && !shown && fb) {
        shown = true;
        fb.style.display = "block";
        fb.textContent = window.t ? window.t("map_tiles_offline", "Map tiles could not be loaded (are you offline?). Waypoints and route calculations are still shown.") : "Map tiles could not be loaded (are you offline?). Waypoints and route calculations are still shown.";
      }
    });
    layer.addTo(map);

    setTimeout(function () {
      try { map.invalidateSize(); } catch (e) {}
    }, 150);

    return map;
  }

  window.AgriMap = {
    farmers: function (id, data) {
      var map = baseMap(id, data.user ? [data.user.lat, data.user.lng] : DEFAULT_CENTER, 10);
      if (!map) return;
      var markers = [], bounds = [], active = null;
      data.markers.forEach(function (m) {
        var box = el("div", { "class": "popup" });
        box.appendChild(el("h4", { text: m.farmer }));
        var distText = "";
        if (m.distance_km != null) {
          var tpl = window.t ? window.t("straight_line_dist", "about {km} km away (straight line)") : "about {km} km away (straight line)";
          distText = " · " + tpl.replace("{km}", m.distance_km.toFixed(1));
        }
        box.appendChild(el("div", { "class": "small", text: m.place + distText }));
        var ul = el("ul");
        m.crops.forEach(function (c) { ul.appendChild(el("li", { text: c.crop + " — " + inr(c.price) + "/kg · " + c.quantity + " kg · " + c.quality })); });
        box.appendChild(ul);
        box.appendChild(el("a", { "class": "btn btn-primary", href: "/marketplace?farmer=" + encodeURIComponent(m.farmer_id), text: window.t ? window.t("view_listings", "View listings") : "View listings" }));
        box.appendChild(el("a", { "class": "btn btn-outline", href: osmUrl(m.lat, m.lng), target: "_blank", rel: "noopener", text: window.t ? window.t("open_osm", "Open in OpenStreetMap") : "Open in OpenStreetMap" }));
        var mk = L.marker([m.lat, m.lng], { icon: pin(), title: m.farmer, alt: "Farmer " + m.farmer }).bindPopup(box).addTo(map);
        markers.push({ marker: mk, crops: m.crops.map(function (c) { return c.crop.toLowerCase(); }) });
        bounds.push([m.lat, m.lng]);
      });
      var userMarker = null, latI = document.getElementById("lat"), lngI = document.getElementById("lng");
      function setUser(lat, lng) {
        var userLbl = window.t ? window.t("your_location", "Your location") : "Your location";
        if (userMarker) userMarker.setLatLng([lat, lng]);
        else userMarker = L.marker([lat, lng], { icon: pin("you"), title: userLbl }).addTo(map).bindPopup(userLbl);
      }
      if (data.user) { setUser(data.user.lat, data.user.lng); bounds.push([data.user.lat, data.user.lng]); }
      if (bounds.length > 1) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
      else if (bounds.length === 1) map.setView(bounds[0], 11);

      map.on("click", function (e) {
        if (!latI || !lngI) return;
        latI.value = e.latlng.lat.toFixed(5); lngI.value = e.latlng.lng.toFixed(5);
        var lbl = document.getElementById("loc_label"); if (lbl) lbl.value = window.t ? window.t("point_on_map", "Point on map") : "Point on map";
        setUser(e.latlng.lat, e.latlng.lng);
        var msg = document.getElementById("loc-msg"); if (msg) msg.textContent = window.t ? window.t("location_set", "Location set from the map. Press Find farmers to rank by distance.") : "Location set from the map. Press Find farmers to rank by distance.";
      });
      document.querySelectorAll(".chip[data-crop]").forEach(function (chip) {
        chip.addEventListener("click", function () {
          var crop = chip.dataset.crop; active = (active === crop) ? null : crop;
          document.querySelectorAll(".chip[data-crop]").forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.crop === active ? "true" : "false"); });
          markers.forEach(function (m) {
            var show = !active || m.crops.indexOf(active) !== -1;
            if (show && !map.hasLayer(m.marker)) m.marker.addTo(map);
            if (!show && map.hasLayer(m.marker)) map.removeLayer(m.marker);
          });
        });
      });
      var geo = document.getElementById("use-geo"), msg2 = document.getElementById("loc-msg");
      if (geo && latI && lngI) geo.addEventListener("click", function () {
        if (!navigator.geolocation) {
          msg2.textContent = window.t ? window.t("location_unsupported", "Your browser does not support location. Choose a place or enter coordinates.") : "Your browser does not support location. Choose a place or enter coordinates.";
          return;
        }
        msg2.textContent = window.t ? window.t("waiting_permission", "Waiting for your permission…") : "Waiting for your permission…";
        navigator.geolocation.getCurrentPosition(function (p) {
          latI.value = p.coords.latitude.toFixed(5); lngI.value = p.coords.longitude.toFixed(5);
          var lbl = document.getElementById("loc_label");
          if (lbl) lbl.value = window.t ? window.t("my_location", "My location") : "My location";
          setUser(p.coords.latitude, p.coords.longitude); map.setView([p.coords.latitude, p.coords.longitude], 11);
          msg2.textContent = window.t ? window.t("location_captured", "Location captured. Press Find farmers.") : "Location captured. Press Find farmers.";
        }, function () {
          msg2.textContent = window.t ? window.t("location_denied", "Location permission was not granted. Choose a place below or enter coordinates manually.") : "Location permission was not granted. Choose a place below or enter coordinates manually.";
        }, { timeout: 10000 });
      });
      var preset = document.getElementById("preset");
      if (preset && latI && lngI) preset.addEventListener("change", function () {
        if (!preset.value) return;
        var p = preset.value.split(",");
        latI.value = p[0]; lngI.value = p[1];
        var lbl = document.getElementById("loc_label"); if (lbl) lbl.value = preset.options[preset.selectedIndex].text;
        setUser(parseFloat(p[0]), parseFloat(p[1])); map.setView([parseFloat(p[0]), parseFloat(p[1])], 11);
      });
    },
    single: function (id, lat, lng, title) {
      var map = baseMap(id, [lat, lng], 12);
      if (!map) return;
      L.marker([lat, lng], { icon: pin(), title: title }).addTo(map).bindPopup(title);
    },
    routeMap: function (id, waypoints) {
      if (!waypoints || !waypoints.length) return;
      var origin = waypoints[0];
      var map = baseMap(id, [origin.lat, origin.lng], 11);
      if (!map) return;

      var bounds = [], latlngs = [];
      waypoints.forEach(function (w, idx) {
        var p;
        if (w.role === "origin") {
          p = pin("", "🌾");
        } else if (w.role === "hub") {
          p = pin("hub", "🏢");
        } else {
          p = pin("stop", w.stop_num != null ? w.stop_num : idx);
        }
        var m = L.marker([w.lat, w.lng], { icon: p, title: w.label }).addTo(map);
        var popupContent = el("div", { "class": "popup" });
        var prefix = "";
        if (w.role === "origin") {
          prefix = (window.t ? window.t("origin_label", "Origin") : "Origin") + ": ";
        } else {
          var stopTpl = window.t ? window.t("stop_label", "Stop {num}") : "Stop {num}";
          prefix = stopTpl.replace("{num}", (w.stop_num != null ? w.stop_num : idx)) + ": ";
        }
        popupContent.appendChild(el("strong", { text: prefix + w.label }));
        m.bindPopup(popupContent);

        bounds.push([w.lat, w.lng]);
        latlngs.push([w.lat, w.lng]);
      });

      if (latlngs.length > 1) {
        // Draw straight-line approximation path
        L.polyline(latlngs, {
          color: "#16A34A",
          weight: 4,
          opacity: 0.85,
          dashArray: "6, 8"
        }).addTo(map);
      }

      if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
      } else if (bounds.length === 1) {
        map.setView(bounds[0], 12);
      }

      if (typeof window.onRouteMapClick === "function") {
        map.on("click", window.onRouteMapClick);
      }

      return map;
    },
    hubsMap: function (id, hubs, userLoc) {
      var center = userLoc ? [userLoc.lat, userLoc.lng] : DEFAULT_CENTER;
      var map = baseMap(id, center, 11);
      if (!map) return;

      var bounds = [];
      if (userLoc) {
        var yourLoc = window.t ? window.t("your_location", "Your Location") : "Your Location";
        L.marker([userLoc.lat, userLoc.lng], { icon: pin("you"), title: yourLoc }).addTo(map).bindPopup(yourLoc + ": " + (userLoc.label || "Custom Point"));
        bounds.push([userLoc.lat, userLoc.lng]);
      }

      (hubs || []).forEach(function (h) {
        var m = L.marker([h.latitude, h.longitude], { icon: pin("hub", "🏢"), title: h.name }).addTo(map);
        var box = el("div", { "class": "popup" });
        box.appendChild(el("h4", { text: h.name }));
        box.appendChild(el("p", { "class": "small", text: h.address + ", " + h.city }));
        var hrs = window.t ? window.t("hours", "Hours") : "Hours";
        var cnt = window.t ? window.t("contact", "Contact") : "Contact";
        box.appendChild(el("div", { "class": "small", text: hrs + ": " + h.operating_hours + " · " + cnt + ": " + h.contact_phone }));
        box.appendChild(el("a", { "class": "btn btn-primary btn-sm", href: "/transport-optimizer/collection-points?hub=" + h.id, text: window.t ? window.t("view_produce", "View Nearby Produce") : "View Nearby Produce" }));
        m.bindPopup(box);
        bounds.push([h.latitude, h.longitude]);
      });

      if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
      }
    }
  };
})();
