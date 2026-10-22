(function () {
  function paint() {
    if (document.getElementById("addon-badge")) return;
    if (!document.body) return;
    const b = document.createElement("div");
    b.id = "addon-badge";
    b.textContent = "надстройка ON";
    b.title = "AutoCell_addon активна. Выключить: remove_addon.bat";
    b.style.cssText =
      "position:fixed;right:8px;bottom:8px;z-index:9999;background:#1b6df1;" +
      "color:#fff;padding:4px 8px;font:12px sans-serif;border-radius:4px;opacity:0.85;";
    document.body.appendChild(b);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", paint);
  } else {
    paint();
  }
})();
