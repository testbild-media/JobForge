/* JobForge – kleine, abhängigkeitsfreie Oberflächenlogik. */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // Navigation (mobil)
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-toggle-nav]")) {
      document.body.classList.toggle("nav-open");
    } else if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  // Klickbare Tabellenzeilen
  document.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-href]");
    if (!row || e.target.closest("a, button, input, select, textarea, label, form")) return;
    if (e.ctrlKey || e.metaKey) window.open(row.dataset.href, "_blank");
    else window.location = row.dataset.href;
  });

  // Bestätigungsdialoge
  document.addEventListener("submit", (e) => {
    const form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) e.preventDefault();
  }, true);

  // Dropdowns schließen bei Klick außerhalb
  document.addEventListener("click", (e) => {
    $$("details.dropdown[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // Tabs
  const tabs = $("[data-tabs]");
  if (tabs) {
    const show = (id) => {
      const panel = document.getElementById(id);
      if (!panel) return false;
      $$(".tab-panel").forEach((p) => p.classList.toggle("active", p === panel));
      $$("a", tabs).forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + id));
      return true;
    };
    tabs.addEventListener("click", (e) => {
      const a = e.target.closest("a[href^='#']");
      if (!a) return;
      e.preventDefault();
      const id = a.getAttribute("href").slice(1);
      show(id);
      history.replaceState(null, "", "#" + id);
    });
    document.addEventListener("click", (e) => {
      const link = e.target.closest("[data-tab-link]");
      if (link) { show("tab-" + link.dataset.tabLink); }
    });
    if (location.hash) show(location.hash.slice(1));
  }

  // Generische Inline-Formsets (Ansprechpartner, Set-Bestandteile …)
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-add-form]");
    if (!btn) return;
    const prefix = btn.dataset.addForm;
    const box = btn.closest("[data-formset]");
    const total = $(`#id_${prefix}-TOTAL_FORMS`);
    const tpl = $(`template[data-empty-form="${prefix}"]`, box);
    const idx = parseInt(total.value, 10);
    const html = tpl.innerHTML.replace(/__prefix__/g, idx);
    $(".formset-forms", box).insertAdjacentHTML("beforeend", html);
    total.value = idx + 1;
  });

  // Positionseditor ------------------------------------------------------
  const editor = $("form[data-positions]");
  if (editor) initPositions(editor);

  function num(v) {
    const n = parseFloat(String(v || "0").replace(",", "."));
    return isNaN(n) ? 0 : n;
  }
  function money(v) {
    return v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
  }

  function initPositions(form) {
    const body = $("[data-pos-body]", form);
    const tpl = $("template[data-pos-template]", form);
    const total = $("input[name$='-TOTAL_FORMS']", form);
    const defFactor = form.dataset.defaultFactor || "1";
    const defTax = form.dataset.defaultTax || "19";
    const lookup = form.dataset.lookup;
    const priced = ["rental", "sale", "service", "staff"];

    const field = (row, name) => $(`[data-f='${name}']`, row) || $(`[name$='-${name}']`, row);

    function rowState(row) {
      const kind = field(row, "kind").value;
      row.classList.toggle("pos-heading", kind === "heading");
      const isPriced = priced.includes(kind);
      ["quantity", "unit", "unit_price", "factor", "discount", "tax_rate", "article"].forEach((n) => {
        const el = field(row, n);
        if (el) el.style.visibility = isPriced ? "" : "hidden";
      });
      const del = $("[data-delete]", row);
      row.classList.toggle("deleted", !!(del && del.checked));
    }

    function recalc() {
      let net = 0, tax = 0;
      $$("[data-pos-row]", body).forEach((row) => {
        rowState(row);
        const kind = field(row, "kind").value;
        const cell = $("[data-line-total]", row);
        const del = $("[data-delete]", row);
        if (!priced.includes(kind)) { cell.textContent = ""; return; }
        const line = Math.round(num(field(row, "quantity").value) * num(field(row, "unit_price").value) *
          num(field(row, "factor").value) * (1 - num(field(row, "discount").value) / 100) * 100) / 100;
        cell.textContent = money(line);
        if (del && del.checked) return;
        net += line;
        tax += line * num(field(row, "tax_rate").value) / 100;
      });
      $("[data-sum-net]", form).textContent = money(net);
      $("[data-sum-tax]", form).textContent = money(Math.round(tax * 100) / 100);
      $("[data-sum-gross]", form).textContent = money(Math.round((net + tax) * 100) / 100);
    }

    function renumber() {
      $$("[data-pos-row]", body).forEach((row, i) => { field(row, "order").value = (i + 1) * 10; });
    }

    function addRow(kind) {
      const idx = parseInt(total.value, 10);
      const html = tpl.innerHTML.replace(/__prefix__/g, idx);
      body.insertAdjacentHTML("beforeend", html);
      total.value = idx + 1;
      const row = body.lastElementChild;
      field(row, "kind").value = kind;
      field(row, "tax_rate").value = defTax;
      field(row, "factor").value = kind === "rental" ? defFactor : "1";
      field(row, "unit").value = { staff: "Std", service: "pauschal", rental: "Stk", sale: "Stk" }[kind] || "";
      const empty = $("[data-pos-empty]", form);
      if (empty) empty.remove();
      renumber();
      recalc();
      (kind === "heading" || kind === "text" ? field(row, "description") : field(row, "article")).focus();
    }

    form.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add-pos]");
      if (add) { addRow(add.dataset.addPos); return; }
      const mv = e.target.closest("[data-move]");
      if (mv) {
        const row = mv.closest("[data-pos-row]");
        if (mv.dataset.move === "-1" && row.previousElementSibling) body.insertBefore(row, row.previousElementSibling);
        if (mv.dataset.move === "1" && row.nextElementSibling) body.insertBefore(row.nextElementSibling, row);
        renumber();
      }
    });

    form.addEventListener("input", recalc);
    form.addEventListener("change", (e) => {
      if (e.target.matches("[data-delete]")) recalc();
      if (e.target.matches("[data-f='article']") && e.target.value && lookup) {
        const row = e.target.closest("[data-pos-row]");
        fetch(`${lookup}?id=${encodeURIComponent(e.target.value)}`, { credentials: "same-origin" })
          .then((r) => r.json())
          .then((a) => {
            const kind = field(row, "kind").value;
            const desc = field(row, "description");
            if (!desc.value.trim()) desc.value = a.name + (a.description ? "\n" + a.description : "");
            field(row, "unit").value = a.unit || field(row, "unit").value;
            const price = kind === "rental" ? a.rental_price : a.sale_price;
            if (num(price) > 0 || num(field(row, "unit_price").value) === 0) field(row, "unit_price").value = price;
            if (a.tax_rate !== null) field(row, "tax_rate").value = a.tax_rate;
            recalc();
          })
          .catch(() => {});
      }
      recalc();
    });
    recalc();
  }

  // Service Worker (PWA)
  const isDev = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if ("serviceWorker" in navigator && location.protocol !== "file:" && !isDev) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();
