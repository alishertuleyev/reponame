(function () {
  function lock(asrsId, empty) {
    const panel = document.getElementById(asrsId);
    const statusBox = document.getElementById("status-" + asrsId);
    if (!panel || !statusBox) return;
    if (statusBox.getAttribute("data-control") !== "manual") return;
    if (empty == null || isNaN(Number(empty))) return;
    const full = Number(empty) <= 0;
    panel.querySelectorAll(".mode-button").forEach(function (btn) {
      const oc = btn.getAttribute("onclick") || "";
      if (oc.indexOf(", 1,") === -1 && oc.indexOf(", 5,") === -1) return;
      if (full) {
        btn.disabled = true;
        btn.setAttribute("data-addon-lock", "1");
        btn.title = "Нет пустых ячеек — вход заблокирован (надстройка)";
        return;
      }
      if (btn.getAttribute("data-addon-lock") === "1") {
        btn.disabled = false;
        btn.removeAttribute("data-addon-lock");
        btn.title = "";
      }
    });
  }

  function tick() {
    fetch("/addon/empty_cells")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        lock("asrs1", d.asrs1);
        lock("asrs2", d.asrs2);
      })
      .catch(function () {});
  }

  function start() {
    if (!document.getElementById("asrs1")) return;
    tick();
    setInterval(tick, 1000);
    if (typeof window.setControlMode === "function") {
      const orig = window.setControlMode;
      window.setControlMode = function () {
        orig.apply(this, arguments);
        setTimeout(tick, 0);
      };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
