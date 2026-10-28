"use strict";
// Relatório de resultados (RCB-35). `REL` reúne as funções puras, sem DOM: o
// pytest as executa com o QuickJS (tests/test_report_page.py). A interface, no
// fim do arquivo, só roda no navegador. Os dados (execuções, pares, ordens e as
// tabelas do analyze) vêm de `riscvcnnbench relatorio`.

const REL = (() => {
  // Métricas por execução: chave, rótulo e se menor é melhor.
  const METRICS = [
    { key: "cycles", label: "Ciclos", lower: true },
    { key: "insts", label: "Instruções", lower: true },
    { key: "ipc", label: "IPC", lower: false },
    { key: "cyc_work", label: "Ciclos por MAC (ou elemento)", lower: true },
    { key: "inst_work", label: "Instruções por MAC (ou elemento)", lower: true },
    { key: "l1d_mpki", label: "Faltas na L1d por mil instruções", lower: true },
    { key: "l2_mpki", label: "Faltas na L2 por mil instruções", lower: true },
    { key: "l1d_misses", label: "Faltas na L1d", lower: true },
    { key: "l2_misses", label: "Faltas na L2", lower: true },
    { key: "dram_reads", label: "Leituras da DRAM", lower: true },
  ];
  const INTEGER_METRICS = new Set(["insts", "cycles", "l1d_misses", "l2_misses", "dram_reads"]);
  const SIZES = ["S", "L"];
  // Pares mais lidos primeiro no seletor do gráfico.
  const PAIR_ORDER = ["ref→custom", "ref→rvv", "custom→rvv"];
  // Os filtros e a coluna de cada um nas execuções.
  const FILTERS = { ops: "bench", sizes: "size", cpus: "cpu", scenarios: "scenario", series: "series" };

  // Números ---------------------------------------------------------------------

  const missing = (value) => value === null || value === undefined || Number.isNaN(value);

  function integer(value) {
    if (missing(value)) return "-";
    const digits = String(Math.round(Math.abs(value)));
    const groups = [];
    for (let end = digits.length; end > 0; end -= 3) groups.unshift(digits.slice(Math.max(0, end - 3), end));
    return (value < 0 ? "-" : "") + groups.join(".");
  }

  function decimal(value, digits = 2) {
    return missing(value) ? "-" : value.toFixed(digits).replace(".", ",");
  }

  function metricText(key, value) {
    if (INTEGER_METRICS.has(key)) return integer(value);
    return decimal(value, key.endsWith("mpki") ? 1 : 2);
  }

  const ratioText = (value) => (missing(value) ? "-" : `${decimal(value)}×`);

  // Ordens ------------------------------------------------------------------------

  function rank(list, value) {
    const index = list.indexOf(value);
    return index < 0 ? list.length : index;
  }

  function orderedValues(values, known) {
    return [...new Set(values)].sort((a, b) => rank(known, a) - rank(known, b) || String(a).localeCompare(String(b)));
  }

  const opsOrder = (data) => Object.keys(data.operations);

  function sortByOperation(items, data) {
    const ops = opsOrder(data);
    return items.sort(
      (a, b) =>
        rank(ops, a.bench) - rank(ops, b.bench) ||
        rank(SIZES, a.size) - rank(SIZES, b.size) ||
        String(a.params).localeCompare(String(b.params)) ||
        rank(data.order.series, a.series) - rank(data.order.series, b.series)
    );
  }

  // Seleção e filtros ------------------------------------------------------------------

  // As execuções e os pares que entram na análise: a seleção do plot e do analyze.
  const used = (items) => items.filter((item) => !item.skip);

  function matches(item, filters, keys = Object.keys(FILTERS)) {
    for (const key of keys) {
      const allowed = filters[key];
      const column = FILTERS[key];
      if (allowed && column in item && !allowed.includes(item[column])) return false;
    }
    return true;
  }

  function summary(data) {
    const chosen = used(data.runs);
    const reasons = {};
    for (const run of data.runs) if (run.skip) reasons[run.skip] = (reasons[run.skip] || 0) + 1;
    const values = (key, known) => orderedValues(chosen.map((run) => run[key]), known);
    return {
      runs: data.runs.length,
      valid: data.runs.filter((run) => !run.problem).length,
      used: chosen.length,
      skipped: Object.entries(reasons).sort((a, b) => b[1] - a[1]),
      pairs: data.pairs.length,
      pairsUsed: used(data.pairs).length,
      ops: values("bench", opsOrder(data)),
      sizes: values("size", SIZES),
      cpus: values("cpu", data.order.cpus),
      scenarios: values("scenario", data.order.scenarios),
      series: values("series", data.order.series),
      problems: data.runs.filter((run) => run.problem),
    };
  }

  function runsTable(data, filters, sortKey = null, descending = false) {
    const rows = sortByOperation(used(data.runs).filter((run) => matches(run, filters)), data);
    if (!sortKey) return rows;
    const value = (run) => (missing(run[sortKey]) ? -Infinity : run[sortKey]);
    return rows.sort((a, b) => (descending ? value(b) - value(a) : value(a) - value(b)));
  }

  // Configurações e comparação --------------------------------------------------------

  // Uma configuração é tudo o que não é operação, tamanho nem variante.
  const configKey = (run) => [run.cpu, run.clock, run.scenario, run.flags, run.data].join("|");

  function configLabel(run) {
    const parts = [run.cpu, run.scenario];
    if (run.flags !== "-O2") parts.push(run.flags);
    if (run.data !== "random") parts.push(`dados ${run.data}`);
    if (run.clock !== "1GHz") parts.push(run.clock);
    return parts.join(" · ");
  }

  function configs(data) {
    const found = new Map();
    for (const run of used(data.runs)) {
      const key = configKey(run);
      if (!found.has(key)) found.set(key, { key, label: configLabel(run), cpu: run.cpu, scenario: run.scenario, runs: 0 });
      found.get(key).runs += 1;
    }
    return [...found.values()].sort(
      (a, b) =>
        rank(data.order.cpus, a.cpu) - rank(data.order.cpus, b.cpu) ||
        rank(data.order.scenarios, a.scenario) - rank(data.order.scenarios, b.scenario) ||
        a.label.localeCompare(b.label)
    );
  }

  // A métrica de cada operação, tamanho e série nas configurações `keys`, e a razão
  // de cada uma sobre a primeira (a base). Os filtros de CPU e cenário não valem
  // aqui: as configurações já os escolhem.
  function compare(data, keys, metric, filters = {}) {
    const rows = new Map();
    let repeated = 0;
    for (const run of used(data.runs)) {
      const index = keys.indexOf(configKey(run));
      if (index < 0 || !matches(run, filters, ["ops", "sizes", "series"])) continue;
      const key = [run.bench, run.params, run.series].join("|");
      if (!rows.has(key)) {
        rows.set(key, {
          bench: run.bench,
          size: run.size,
          params: run.params,
          series: run.series,
          values: keys.map(() => null),
        });
      }
      const row = rows.get(key);
      if (row.values[index] !== null) repeated += 1;
      row.values[index] = missing(run[metric]) ? null : run[metric];
    }
    const list = sortByOperation([...rows.values()], data);
    for (const row of list) {
      const base = row.values[0];
      row.ratios = row.values.map((value) => (value === null || !base ? null : value / base));
    }
    const geomean = keys.map((_, index) => {
      const ratios = list.map((row) => row.ratios[index]).filter((value) => value !== null && value > 0);
      if (!ratios.length) return { value: null, count: 0 };
      const mean = ratios.reduce((sum, value) => sum + Math.log(value), 0) / ratios.length;
      return { value: Math.exp(mean), count: ratios.length };
    });
    return { rows: list, geomean, repeated };
  }

  // Gráfico de speedup ----------------------------------------------------------------

  function pairNames(data) {
    const names = [...new Set(used(data.pairs).map((pair) => pair.pair))];
    return names.sort((a, b) => rank(PAIR_ORDER, a) - rank(PAIR_ORDER, b) || a.localeCompare(b));
  }

  // S_C de um par, por CPU (um painel cada), operação e tamanho (um grupo) e cenário
  // (uma barra). A cor de cada cenário é a posição dele na ordem de todos os
  // cenários, para não mudar quando um filtro tira outros.
  function chart(data, pairName, filters) {
    const pairs = used(data.pairs).filter(
      (pair) => pair.pair === pairName && matches(pair, filters, ["ops", "sizes", "cpus", "scenarios"])
    );
    const panels = [];
    for (const cpu of orderedValues(pairs.map((pair) => pair.cpu), data.order.cpus)) {
      const mine = pairs.filter((pair) => pair.cpu === cpu);
      const groups = new Map();
      for (const pair of sortByOperation(mine.map((pair) => ({ ...pair, series: "" })), data)) {
        const key = [pair.bench, pair.params].join("|");
        if (!groups.has(key)) {
          const name = data.operations[pair.bench] || pair.bench;
          const short = (data.shortOperations || {})[pair.bench] || pair.bench;
          groups.set(key, {
            bench: pair.bench,
            size: pair.size,
            label: `${name} ${pair.size}`.trim(),
            short,
            r_i: pair.r_i,
            bars: [],
          });
        }
        groups.get(key).bars.push({
          scenario: pair.scenario,
          color: data.order.scenarios.indexOf(pair.scenario),
          s_c: pair.s_c,
          r_i: pair.r_i,
          eff: pair.eff,
        });
      }
      for (const group of groups.values()) {
        group.bars.sort((a, b) => a.color - b.color);
      }
      panels.push({ cpu, groups: [...groups.values()] });
    }
    return panels;
  }

  // Markdown das tabelas do analyze ----------------------------------------------------

  const escape = (text) =>
    String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const inline = (text) => escape(text).replace(/`([^`]+)`/g, "<code>$1</code>");
  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

  // Só o que o tables.md usa: títulos, parágrafos e tabelas.
  function markdown(text) {
    const html = [];
    const lines = text.split("\n");
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        const level = Math.min(heading[1].length + 1, 6);
        html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      } else if (line.startsWith("|")) {
        const header = cells(line);
        const body = [];
        i += 2; // a linha de separadores
        while (i < lines.length && lines[i].startsWith("|")) {
          body.push(cells(lines[i]));
          i += 1;
        }
        i -= 1;
        html.push(
          `<div class="table-wrap"><table><thead><tr>${header.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>` +
            `<tbody>${body.map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
        );
      } else if (line.trim()) {
        html.push(`<p>${inline(line)}</p>`);
      }
    }
    return html.join("\n");
  }

  return {
    METRICS,
    integer,
    decimal,
    metricText,
    ratioText,
    summary,
    matches,
    runsTable,
    configKey,
    configLabel,
    configs,
    compare,
    pairNames,
    chart,
    markdown,
    escape,
  };
})();

// Interface ---------------------------------------------------------------------------

if (typeof document !== "undefined") {
  const DATA = JSON.parse(document.getElementById("rcb-data").textContent);
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const LOG_TICKS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
  const view = { sortKey: null, descending: false };

  const opLabel = (bench) => DATA.operations[bench] || bench;
  const seriesLabel = (series) => DATA.seriesLabels[series] || series;

  function checkboxes(container, name, items) {
    container.innerHTML = "";
    for (const item of items) {
      const label = document.createElement("label");
      label.className = "choice";
      label.innerHTML = `<input type="checkbox" name="${name}" value="${REL.escape(item.value)}" checked> <span>${REL.escape(item.label)}</span>`;
      label.querySelector("input").addEventListener("change", update);
      container.append(label);
    }
  }

  const picked = (name) => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);

  function filters() {
    return { ops: picked("ops"), sizes: picked("sizes"), cpus: picked("cpus"), scenarios: picked("scenarios"), series: picked("series") };
  }

  function overview(info) {
    const cards = [
      ["Execuções", REL.integer(info.runs)],
      ["Válidas", REL.integer(info.valid)],
      ["Na análise", REL.integer(info.used)],
      ["Pares na análise", `${REL.integer(info.pairsUsed)} de ${REL.integer(info.pairs)}`],
    ];
    $("cards").innerHTML = cards.map(([k, v]) => `<div class="card"><div class="card-value">${v}</div><div class="card-label">${k}</div></div>`).join("");
    const lists = [
      ["Operações", info.ops.map(opLabel)],
      ["Tamanhos", info.sizes],
      ["CPUs", info.cpus],
      ["Cenários", info.scenarios],
      ["Séries", info.series.map(seriesLabel)],
    ];
    $("lists").innerHTML = lists.map(([k, v]) => `<div><strong>${k}</strong> <span class="muted">${REL.escape(v.join(", ") || "-")}</span></div>`).join("");
    $("skipped").innerHTML = info.skipped.length
      ? `<p class="muted">Fora da análise: ${info.skipped.map(([reason, n]) => `${REL.escape(reason)} (${n})`).join("; ")}.</p>`
      : "";
    $("problems").innerHTML = info.problems.length
      ? `<h3>Execuções com problema</h3><div class="table-wrap"><table><thead><tr><th>Experimento</th><th>Execução</th><th>Problema</th></tr></thead><tbody>${info.problems
          .slice(0, 50)
          .map((r) => `<tr><td>${REL.escape(r.experiment)}</td><td><code>${REL.escape(r.id)}</code></td><td>${REL.escape(r.problem)}</td></tr>`)
          .join("")}</tbody></table></div>`
      : "";
  }

  function setup() {
    const info = REL.summary(DATA);
    $("source").textContent = `${DATA.sources.runs.path} e ${DATA.sources.pairs.path}`;
    $("version").textContent = DATA.version;
    overview(info);
    checkboxes($("f-ops"), "ops", info.ops.map((op) => ({ value: op, label: opLabel(op) })));
    checkboxes($("f-sizes"), "sizes", info.sizes.map((s) => ({ value: s, label: s || "sem tamanho" })));
    checkboxes($("f-cpus"), "cpus", info.cpus.map((c) => ({ value: c, label: c })));
    checkboxes($("f-scenarios"), "scenarios", info.scenarios.map((s) => ({ value: s, label: s })));
    checkboxes($("f-series"), "series", info.series.map((s) => ({ value: s, label: seriesLabel(s) })));
    for (const name of REL.pairNames(DATA)) {
      const option = document.createElement("option");
      option.value = option.textContent = name;
      $("pair").append(option);
    }
    for (const metric of REL.METRICS) {
      const option = document.createElement("option");
      option.value = metric.key;
      option.textContent = metric.label;
      $("metric").append(option);
    }
    const list = REL.configs(DATA);
    $("configs").innerHTML = list
      .map(
        (c, i) =>
          `<label class="choice config"><input type="checkbox" name="config" value="${REL.escape(c.key)}" ${i < 2 ? "checked" : ""}>` +
          `<input type="radio" name="base" value="${REL.escape(c.key)}" ${i === 0 ? "checked" : ""} title="base">` +
          `<span>${REL.escape(c.label)} <small>${c.runs} execuções</small></span></label>`
      )
      .join("");
    for (const input of document.querySelectorAll('#configs input, #pair, #metric')) input.addEventListener("change", update);
    for (const th of document.querySelectorAll("#runs th[data-key]")) {
      th.addEventListener("click", () => {
        view.descending = view.sortKey === th.dataset.key ? !view.descending : true;
        view.sortKey = th.dataset.key;
        update();
      });
    }
    if (DATA.analysis) {
      $("analysis").innerHTML = REL.markdown(DATA.analysis);
    } else {
      $("analysis").innerHTML = '<p class="muted">Esta pasta não tem analysis/tables.md. Gere com <code>make analyze DIR=&lt;pasta&gt;</code> e depois o relatório de novo.</p>';
    }
    update();
  }

  function update() {
    const current = filters();
    renderRuns(current);
    renderChart(current);
    renderCompare(current);
  }

  function renderRuns(current) {
    const rows = REL.runsTable(DATA, current, view.sortKey, view.descending);
    $("runs-count").textContent = `${REL.integer(rows.length)} execuções`;
    $("runs-body").innerHTML = rows
      .map(
        (r) =>
          `<tr><td>${REL.escape(opLabel(r.bench))}</td><td>${REL.escape(r.size || r.params)}</td><td>${REL.escape(r.cpu)}</td>` +
          `<td>${REL.escape(r.scenario)}</td><td>${REL.escape(seriesLabel(r.series))}</td><td>${REL.escape(extras(r))}</td>` +
          ["insts", "cycles", "ipc", "inst_work", "cyc_work", "l1d_mpki", "l2_mpki"].map((k) => `<td class="num">${REL.metricText(k, r[k])}</td>`).join("") +
          "</tr>"
      )
      .join("");
  }

  // O que a configuração tem de diferente do padrão: flags, dados e clock.
  function extras(run) {
    const parts = [];
    if (run.flags !== "-O2") parts.push(run.flags);
    if (run.data !== "random") parts.push(run.data);
    if (run.clock !== "1GHz") parts.push(run.clock);
    return parts.join(" ");
  }

  function renderCompare(current) {
    const chosen = picked("config");
    const base = (document.querySelector('input[name="base"]:checked') || {}).value;
    const keys = chosen.includes(base) ? [base, ...chosen.filter((k) => k !== base)] : chosen;
    const metric = $("metric").value;
    const info = REL.METRICS.find((m) => m.key === metric);
    if (keys.length < 2) {
      $("compare").innerHTML = '<p class="muted">Marque pelo menos duas configurações.</p>';
      return;
    }
    const labels = Object.fromEntries(REL.configs(DATA).map((c) => [c.key, c.label]));
    const result = REL.compare(DATA, keys, metric, current);
    const head = keys
      .map((k, i) => `<th colspan="${i ? 2 : 1}">${REL.escape(labels[k])}${i ? "" : " <small>(base)</small>"}</th>`)
      .join("");
    const sub = keys.map((_, i) => (i ? "<th>valor</th><th>÷ base</th>" : "<th>valor</th>")).join("");
    const body = result.rows
      .map(
        (row) =>
          `<tr><td>${REL.escape(opLabel(row.bench))}</td><td>${REL.escape(row.size || row.params)}</td><td>${REL.escape(seriesLabel(row.series))}</td>` +
          row.values
            .map((v, i) => `<td class="num">${REL.metricText(metric, v)}</td>` + (i ? `<td class="num ratio ${tone(row.ratios[i], info.lower)}">${REL.ratioText(row.ratios[i])}</td>` : ""))
            .join("") +
          "</tr>"
      )
      .join("");
    const mean = result.geomean
      .map((g, i) => (i ? `<td></td><td class="num"><strong>${REL.ratioText(g.value)}</strong></td>` : "<td></td>"))
      .join("");
    $("compare").innerHTML =
      `<p class="muted">${REL.escape(info.label)}: o valor em cada configuração e a razão sobre a base. ` +
      `${info.lower ? "Para esta métrica, menor é melhor: abaixo de 1×, a configuração ganha da base." : "Para esta métrica, maior é melhor: acima de 1×, a configuração ganha da base."}</p>` +
      `<div class="table-wrap"><table><thead><tr><th rowspan="2">Operação</th><th rowspan="2">Tam.</th><th rowspan="2">Série</th>${head}</tr><tr>${sub}</tr></thead>` +
      `<tbody>${body}</tbody><tfoot><tr><td colspan="3">Média geométrica das razões</td>${mean}</tr></tfoot></table></div>` +
      (result.repeated ? `<p class="muted">${result.repeated} execução(ões) repetida(s) na mesma configuração: vale a última lida.</p>` : "");
  }

  function tone(ratio, lower) {
    if (ratio === null || Math.abs(ratio - 1) < 0.005) return "";
    return (ratio < 1) === lower ? "better" : "worse";
  }

  // Gráfico: um painel por CPU, grupos por operação, barras por cenário a partir
  // de 1× (eixo logarítmico), e a redução de instruções (R_I) como traço.
  function renderChart(current) {
    const pairName = $("pair").value;
    const panels = REL.chart(DATA, pairName, current);
    const host = $("chart");
    host.innerHTML = "";
    const scenarios = [...new Set(panels.flatMap((p) => p.groups.flatMap((g) => g.bars.map((b) => b.scenario))))].sort(
      (a, b) => DATA.order.scenarios.indexOf(a) - DATA.order.scenarios.indexOf(b)
    );
    $("legend").innerHTML =
      scenarios
        .map((s) => `<span class="key"><span class="swatch" style="background:${color(DATA.order.scenarios.indexOf(s))}"></span>${REL.escape(s)}</span>`)
        .join("") + '<span class="key"><span class="ri-swatch"></span>R_I (redução de instruções)</span>';
    if (!panels.length) {
      host.innerHTML = '<p class="muted">Nenhum par com estes filtros.</p>';
      return;
    }
    const values = panels.flatMap((p) => p.groups.flatMap((g) => [g.r_i, ...g.bars.map((b) => b.s_c)])).filter((v) => v > 0);
    const low = Math.min(0.5, ...values.map((v) => v / 1.2));
    const high = Math.max(2, ...values.map((v) => v * 1.2));
    for (const panel of panels) host.append(panelSvg(panel, low, high));
  }

  function color(index) {
    return index >= 0 && index < 8 ? `var(--series-${index + 1})` : "var(--series-other)";
  }

  function panelSvg(panel, low, high) {
    const width = 760;
    const height = 230;
    const margin = { left: 52, right: 12, top: 26, bottom: 44 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const y = (v) => margin.top + plotH * (1 - (Math.log(v) - Math.log(low)) / (Math.log(high) - Math.log(low)));
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("class", "panel");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Speedup em ciclos na CPU ${panel.cpu}`);
    const add = (tag, attrs, text) => {
      const node = document.createElementNS(SVG, tag);
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      if (text !== undefined) node.textContent = text;
      svg.append(node);
      return node;
    };
    add("text", { x: margin.left, y: 16, class: "panel-title" }, `CPU ${panel.cpu}`);
    for (const tick of LOG_TICKS.filter((t) => t >= low && t <= high)) {
      add("line", { x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick), class: tick === 1 ? "baseline" : "grid" });
      add("text", { x: margin.left - 6, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, `${REL.decimal(tick, tick < 1 ? 1 : 0)}×`);
    }
    const groupW = plotW / panel.groups.length;
    panel.groups.forEach((group, gi) => {
      const x0 = margin.left + gi * groupW;
      const inner = groupW * 0.78;
      const barW = Math.max(3, (inner - 2 * (group.bars.length - 1)) / group.bars.length);
      group.bars.forEach((bar, bi) => {
        if (!(bar.s_c > 0)) return;
        const x = x0 + (groupW - inner) / 2 + bi * (barW + 2);
        const top = Math.min(y(bar.s_c), y(1));
        const rect = add("rect", {
          x,
          y: top,
          width: barW,
          height: Math.max(1, Math.abs(y(bar.s_c) - y(1))),
          rx: Math.min(2, barW / 2),
          fill: color(bar.color),
          class: "bar",
        });
        rect.addEventListener("mousemove", (event) =>
          tooltip(event, `${group.label} · ${panel.cpu} · ${bar.scenario}<br>S_C ${REL.ratioText(bar.s_c)} · R_I ${REL.ratioText(bar.r_i)} · eficiência ${REL.decimal(bar.eff)}`)
        );
        rect.addEventListener("mouseleave", () => tooltip(null));
      });
      if (group.r_i > 0) {
        add("line", { x1: x0 + (groupW - inner) / 2 - 3, x2: x0 + (groupW + inner) / 2 + 3, y1: y(group.r_i), y2: y(group.r_i), class: "ri" });
      }
      add("text", { x: x0 + groupW / 2, y: height - margin.bottom + 16, class: "tick", "text-anchor": "middle" }, group.short);
      add("text", { x: x0 + groupW / 2, y: height - margin.bottom + 30, class: "tick", "text-anchor": "middle" }, group.size);
    });
    add("text", { x: 14, y: margin.top + plotH / 2, class: "axis-label", transform: `rotate(-90 14 ${margin.top + plotH / 2})`, "text-anchor": "middle" }, "S_C (×, log)");
    return svg;
  }

  function tooltip(event, html) {
    const tip = $("tooltip");
    if (!event) {
      tip.hidden = true;
      return;
    }
    tip.innerHTML = html;
    tip.hidden = false;
    tip.style.left = `${event.clientX + 12}px`;
    tip.style.top = `${event.clientY + 12}px`;
  }

  setup();
}
