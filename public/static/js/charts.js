(function () {
  if (typeof Chart === "undefined") {
    document.querySelectorAll("canvas[data-chart]").forEach(function (c) {
      var p = document.createElement("p"); p.className = "muted small";
      p.textContent = window.t ? window.t("offline_chart", "Chart unavailable offline (Chart.js could not load).") : "Chart unavailable offline (Chart.js could not load).";
      c.replaceWith(p);
    });
    return;
  }
  var colors = ["#16A34A", "#E0A81B", "#14532D", "#65A30D", "#B7860B", "#4ADE80", "#92400E", "#0F766E"];
  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    var cfg = JSON.parse(canvas.dataset.chart);
    if (!cfg.data.length || cfg.data.every(function (v) { return v === 0; })) {
      var p = document.createElement("p"); p.className = "muted small";
      p.textContent = window.t ? window.t("no_chart_data", "No data to chart yet.") : "No data to chart yet.";
      canvas.replaceWith(p); return;
    }
    var rupee = /₹/.test(cfg.label);
    new Chart(canvas, {
      type: cfg.type,
      data: { labels: cfg.labels, datasets: [{ label: cfg.label, data: cfg.data, backgroundColor: colors, borderWidth: 0, borderRadius: cfg.type === "bar" ? 8 : 0 }] },
      options: { responsive: true, plugins: { legend: { display: cfg.type === "doughnut" },
        tooltip: { callbacks: { label: function (c) { var v = c.parsed.y !== undefined ? c.parsed.y : c.parsed;
          return (rupee ? "₹" + Number(v).toLocaleString("en-IN") : v); } } } },
        scales: cfg.type === "bar" ? { y: { beginAtZero: true, ticks: { precision: 0 } } } : {} }
    });
  });
})();
