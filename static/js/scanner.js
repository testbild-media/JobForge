/* JobForge Kamera-Scanner: native BarcodeDetector, sonst ZXing (wird bei Bedarf nachgeladen). */
(function () {
  "use strict";
  const view = document.querySelector("[data-scanner-view]");
  const startBtn = document.querySelector("[data-scanner-start]");
  const form = document.querySelector("[data-scan-form]");
  if (!view || !startBtn || !form) return;
  const input = form.querySelector("input[name='code']");
  const video = view.querySelector("video");
  let stream = null, running = false, lastCode = "", lastTime = 0, zxingReader = null;

  const FORMATS = ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e", "data_matrix", "itf"];

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator();
      o.frequency.value = 880;
      o.connect(ctx.destination);
      o.start();
      setTimeout(() => { o.stop(); ctx.close(); }, 120);
    } catch (e) { /* ohne Ton */ }
    if (navigator.vibrate) navigator.vibrate(60);
  }

  function found(code) {
    const now = Date.now();
    if (!code || (code === lastCode && now - lastTime < 2500)) return;
    lastCode = code; lastTime = now;
    beep();
    input.value = code;
    form.classList.add("flash-ok");
    setTimeout(() => form.classList.remove("flash-ok"), 600);
    sessionStorage.setItem("jf-scanner", "on");
    form.requestSubmit ? form.requestSubmit() : form.submit();
  }

  async function startNative() {
    const detector = new window.BarcodeDetector({ formats: FORMATS });
    const loop = async () => {
      if (!running) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length) found(codes[0].rawValue);
      } catch (e) { /* Frame übersprungen */ }
      requestAnimationFrame(loop);
    };
    loop();
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  async function startZxing() {
    if (!window.ZXing) await loadScript("https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js");
    zxingReader = new window.ZXing.BrowserMultiFormatReader();
    zxingReader.decodeFromStream(stream, video, (result) => { if (result) found(result.getText()); });
  }

  async function start() {
    if (running) return stop();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    } catch (e) {
      alert("Kamera nicht verfügbar: " + e.message + "\nHinweis: Kamerazugriff erfordert HTTPS.");
      return;
    }
    view.classList.remove("hidden");
    video.srcObject = stream;
    await video.play();
    running = true;
    startBtn.classList.add("btn-primary");
    try {
      if ("BarcodeDetector" in window) await startNative();
      else await startZxing();
    } catch (e) {
      alert("Scanner konnte nicht gestartet werden: " + e.message);
      stop();
    }
  }

  function stop() {
    running = false;
    sessionStorage.removeItem("jf-scanner");
    if (zxingReader) { try { zxingReader.reset(); } catch (e) { /* ignore */ } zxingReader = null; }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    view.classList.add("hidden");
    startBtn.classList.remove("btn-primary");
  }

  startBtn.addEventListener("click", start);
  // Nach dem Buchen (Seitenneuladen) Kamera automatisch wieder starten
  if (sessionStorage.getItem("jf-scanner") === "on" && navigator.mediaDevices) {
    start().catch(() => {});
  }
  input && input.focus();
})();
