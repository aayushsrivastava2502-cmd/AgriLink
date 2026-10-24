(function () {
  "use strict";
  var toggle = document.querySelector(".nav-toggle"), links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  document.querySelectorAll(".flash button").forEach(function (b) {
    b.addEventListener("click", function () { b.parentElement.remove(); });
  });

  // Image upload preview
  var file = document.getElementById("image_file"), preview = document.getElementById("image-preview");
  if (file && preview) {
    file.addEventListener("change", function () {
      var f = file.files[0];
      if (!f) { preview.hidden = true; return; }
      if (f.size > 2 * 1024 * 1024) {
        var msg = window.t ? window.t("image_size_error", "Image must be 2 MB or smaller.") : "Image must be 2 MB or smaller.";
        alert(msg);
        file.value = "";
        return;
      }
      preview.src = URL.createObjectURL(f); preview.hidden = false;
    });
  }

  // Live order total (server re-validates everything)
  function inr(n) { return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: n % 1 ? 2 : 0 }); }
  var form = document.querySelector("[data-order-form]");
  if (form) {
    var price = parseFloat(form.dataset.price), max = parseFloat(form.dataset.max);
    var transport = form.dataset.transport ? parseFloat(form.dataset.transport) : null;
    var qty = form.querySelector("[name=quantity_kg]"), out = document.getElementById("order-total");
    var del = document.getElementById("delivered-total"), warn = document.getElementById("qty-warning");
    var update = function () {
      var q = parseFloat(qty.value);
      if (!(q > 0)) { out.textContent = "—"; if (del) del.textContent = "—"; warn.textContent = ""; return; }
      var warnTpl = window.t ? window.t("only_stock_available", "Only {max} kg is available.") : "Only {max} kg is available.";
      warn.textContent = q > max ? warnTpl.replace("{max}", max) : "";
      var total = Math.round(q * price * 100) / 100;
      out.textContent = inr(total);
      if (del) {
        var pref = form.querySelector("[name=delivery_preference]:checked");
        var isDelivery = pref ? pref.value === "delivery" : false;
        var pickupLbl = window.t ? window.t("pickup_label", "(pickup)") : "(pickup)";
        del.textContent = transport === null ? "—" : (isDelivery ? inr(total + transport) : inr(total) + " " + pickupLbl);
      }
    };
    qty.addEventListener("input", update);
    form.querySelectorAll("[name=delivery_preference]").forEach(function (r) { r.addEventListener("change", update); });
    update();
  }
})();
