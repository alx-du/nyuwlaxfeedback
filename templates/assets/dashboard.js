// Staff dashboard: decrypts staff.json with the passphrase in the browser and renders it.
var Dash = (function () {
  function b64(s) { return Uint8Array.from(atob(s), function (c) { return c.charCodeAt(0); }); }

  async function decrypt(p, pass) {
    var base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
    var key = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: b64(p.salt), iterations: p.iter, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    var plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.iv) }, key, b64(p.ct));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }

  function render(root, data) {
    var entries = data.entries;  // newest first
    var seasons = [];
    entries.forEach(function (e) { if (seasons.indexOf(e.season) < 0) seasons.push(e.season); });

    var bar = el("div", undefined, "toolbar");
    function labeled(text, node) { var l = el("label", text + " "); l.appendChild(node); return l; }
    var seasonSel = el("select"), dateSel = el("select");
    var search = el("input"); search.type = "search"; search.placeholder = "Search name or notes";
    var lbl = el("label"); var cb = document.createElement("input"); cb.type = "checkbox";
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(" Only players with no feedback"));
    bar.appendChild(labeled("Season", seasonSel)); bar.appendChild(labeled("Date", dateSel));
    bar.appendChild(search); bar.appendChild(lbl);
    root.appendChild(bar);

    var table = el("table"), thead = el("thead"), tbody = el("tbody");
    table.appendChild(thead); table.appendChild(tbody); root.appendChild(table);

    function current() {
      return entries.filter(function (e) { return e.season === seasonSel.value && e.date === dateSel.value; })[0];
    }
    function fillDates() {
      dateSel.textContent = "";
      entries.filter(function (e) { return e.season === seasonSel.value; }).forEach(function (e) {
        var o = el("option", e.display); o.value = e.date; dateSel.appendChild(o);
      });
      draw();
    }
    function draw() {
      var e = current(), q = search.value.toLowerCase();
      thead.textContent = "";
      var hr = el("tr");
      ["Name"].concat(e.contributors).forEach(function (h) { hr.appendChild(el("th", h)); });
      thead.appendChild(hr);
      tbody.textContent = "";
      e.rows.forEach(function (r) {
        var text = (r.name + " " + r.notes.join(" ")).toLowerCase();
        if (q && text.indexOf(q) < 0) return;
        if (cb.checked && (r.team || r.notes.some(function (n) { return n; }))) return;
        var tr = el("tr");
        tr.appendChild(el("td", r.name + (r.team ? " (team)" : ""), "name"));
        r.notes.forEach(function (n, i) {
          var td = el("td", n); td.setAttribute("data-label", e.contributors[i]); tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    seasons.forEach(function (s) { var o = el("option", s); o.value = s; seasonSel.appendChild(o); });
    seasonSel.addEventListener("change", fillDates);
    dateSel.addEventListener("change", draw);
    search.addEventListener("input", draw); cb.addEventListener("change", draw);
    fillDates();
  }

  return { decrypt: decrypt, render: render };
})();
