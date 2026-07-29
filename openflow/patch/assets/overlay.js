(function () {
  if (window.__OF_OVERLAY__) return;
  window.__OF_OVERLAY__ = true;
  function clear() {
    try {
      document.documentElement.style.setProperty("background", "transparent", "important");
      document.documentElement.style.setProperty("background-color", "transparent", "important");
      if (document.body) {
        document.body.style.setProperty("background", "transparent", "important");
        document.body.style.setProperty("background-color", "transparent", "important");
      }
    } catch (e) {}
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", clear);
  else clear();
})();
