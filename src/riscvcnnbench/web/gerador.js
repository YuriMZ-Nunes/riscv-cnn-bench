"use strict";
// Gerador de experimentos (RCB-31). `RCB` reúne as funções puras, sem DOM: o
// pytest as executa com o QuickJS e confere o YAML gerado com o validador do
// framework (tests/test_generator.py). A interface, no fim do arquivo, só roda
// no navegador. Os dados (operações, cenários, CPUs, limites) vêm de
// `riscvcnnbench gerador`, tirados do código.

const RCB = (() => {
  const RESERVED = new Set(["true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"]);
  const PLAIN = /^[A-Za-z_][A-Za-z0-9_.@-]*$/;
  const LEVELS = ["l1i", "l1d", "l2"];
  const LEVEL_NAMES = { l1i: "L1i", l1d: "L1d", l2: "L2" };
  // Ajustes das caches e o nome curto no rótulo do cenário (metric.CACHE_TUNING).
  const TUNING = [
    ["latency", "lat"],
    ["mshrs", "mshrs"],
    ["targets", "tgts"],
    ["prefetcher", "pf"],
  ];
  const UNITS = { KiB: 1024, MiB: 1024 ** 2, GiB: 1024 ** 3 };

  // YAML ------------------------------------------------------------------------

  function scalar(value) {
    if (value === null) return "null";
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    const text = String(value);
    return PLAIN.test(text) && !RESERVED.has(text.toLowerCase()) ? text : JSON.stringify(text);
  }

  function flow(list) {
    return "[" + list.map((item) => (Array.isArray(item) ? flow(item) : scalar(item))).join(", ") + "]";
  }

  function isEmpty(value) {
    return (
      value === undefined ||
      value === null ||
      (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)
    );
  }

  function toYaml(doc, indent = "") {
    const lines = [];
    for (const [key, value] of Object.entries(doc)) {
      if (isEmpty(value)) continue;
      const mappings = value.length && value[0] !== null && typeof value[0] === "object";
      if (Array.isArray(value) && mappings && !Array.isArray(value[0])) {
        lines.push(`${indent}${key}:`);
        for (const item of value) {
          const body = toYaml(item, indent + "    ").split("\n");
          lines.push(`${indent}  - ${body[0].trimStart()}`, ...body.slice(1));
        }
      } else if (Array.isArray(value)) {
        lines.push(`${indent}${key}: ${flow(value)}`);
      } else if (typeof value === "object") {
        lines.push(`${indent}${key}:`, toYaml(value, indent + "  "));
      } else {
        lines.push(`${indent}${key}: ${scalar(value)}`);
      }
    }
    return lines.join("\n");
  }

  // Memória -------------------------------------------------------------------------

  const cpuInfo = (data, id) => data.cpus.find((cpu) => cpu.id === id) || {};
  const scenarioInfo = (data, id) => data.scenarios.find((s) => s.id === id) || {};
  const opInfo = (data, id) => data.ops.find((op) => op.id === id);
  const datasetInfo = (data, id) => data.datasets.find((d) => d.id === id) || {};

  function bytes(size) {
    const match = /^(\d+)(KiB|MiB|GiB)$/.exec(size);
    return match ? Number(match[1]) * UNITS[match[2]] : null;
  }

  function product(lists) {
    return lists.reduce((acc, list) => acc.flatMap((prefix) => list.map((v) => [...prefix, v])), [[]]);
  }

  // Um nível da memória personalizada como fica na configuração resolvida: os
  // ajustes iguais ao padrão saem (config.CacheLevelConfig).
  function levelConfig(level, size, prefetcher, config, data) {
    const defaults = data.memory.custom[level];
    const found = { size, assoc: config.assoc };
    for (const key of ["latency", "mshrs", "targets"]) {
      if (config[key] !== undefined && config[key] !== null && config[key] !== defaults[key]) {
        found[key] = config[key];
      }
    }
    if (prefetcher !== data.memory.noPrefetcher) found.prefetcher = prefetcher;
    return found;
  }

  const prefetchersOf = (config, data) => config.prefetchers || [data.memory.noPrefetcher];

  // As configurações de memória escolhidas: os cenários nomeados, "sem cenário" e
  // cada combinação de tamanhos e prefetchers da memória personalizada.
  function memories(state, data) {
    const found = state.scenarios.map((id) => ({
      scenario: id,
      cache: null,
      line: null,
      memoryType: scenarioInfo(data, id).memory,
      memorySize: data.memory.default.size,
    }));
    const custom = state.custom;
    if (custom) {
      const levels = LEVELS.filter((level) => custom[level]);
      const options = levels.map((level) => product([custom[level].sizes, prefetchersOf(custom[level], data)]));
      const line = custom.line && custom.line !== data.memory.line ? custom.line : null;
      for (const picks of product(options)) {
        const cache = {};
        levels.forEach((level, index) => {
          const [size, prefetcher] = picks[index];
          cache[level] = levelConfig(level, size, prefetcher, custom[level], data);
        });
        found.push({ scenario: "", cache, line, memoryType: custom.memoryType, memorySize: custom.memorySize });
      }
    }
    return found;
  }

  function memoryLabel(memory) {
    if (memory.scenario) return memory.scenario;
    if (!memory.cache) return "sem cenário";
    const levels = LEVELS.filter((level) => memory.cache[level]).map((l) => `${l}=${memory.cache[l].size}`);
    return [...(levels.length ? levels : ["sem caches"]), memory.memoryType].join(",");
  }

  const hasCaches = (memory, data) =>
    memory.cache ? Object.keys(memory.cache).length > 0 : Boolean(scenarioInfo(data, memory.scenario).l1d);

  // Combinações ---------------------------------------------------------------------

  function latencyMatters(state, data) {
    return state.variants.includes("custom") && state.cpus.some((id) => cpuInfo(data, id).latency);
  }

  function flagLists(state, data) {
    return product([state.flags, state.datasets]).map(([flag, dataset]) => {
      const extra = datasetInfo(data, dataset).flag;
      return extra ? [flag, extra] : [flag];
    });
  }

  // Uma combinação por configuração distinta, com a mesma normalização da campanha:
  // a latência só vale para a custom nas CPUs com unidades funcionais, e a VLEN só
  // para a rvv; fora disso ficam no padrão e as repetidas somem.
  function combinations(state, data) {
    const found = new Map();
    const lists = [
      state.ops,
      state.sizes,
      state.variants,
      state.cpus,
      memories(state, data),
      latencyMatters(state, data) ? state.latencies : [data.latency.default],
      latencyMatters(state, data) ? state.units : [null],
      latencyMatters(state, data) ? state.pipelined : [true],
      state.variants.includes("rvv") ? state.vlens : [data.vlen.default],
      flagLists(state, data),
      state.cacheStates,
    ];
    for (const [op, size, variant, cpu, memory, latency, units, pipelined, vlen, flags, cacheState] of product(lists)) {
      const info = opInfo(data, op);
      if (!info || !info.sizes[size] || !info.variants.includes(variant)) continue;
      const combo = {
        op,
        size,
        variant,
        cpu,
        scenario: memory.scenario,
        cache: memory.cache,
        line: memory.line,
        memoryType: memory.memoryType,
        memorySize: memory.memorySize,
        cacheState,
        clock: state.clock,
        flags,
        latency: variant === "custom" && cpuInfo(data, cpu).latency ? latency : data.latency.default,
        // Unidades e pipeline (RCB-33): só na custom com unidades funcionais; na
        // minor, 1 unidade é a montagem padrão.
        units: variant === "custom" && cpuInfo(data, cpu).latency && !(cpu === "minor" && units === 1) ? units : null,
        pipelined: variant === "custom" && cpuInfo(data, cpu).latency ? pipelined : true,
        vlen: variant === "rvv" ? vlen : data.vlen.default,
      };
      found.set(JSON.stringify(combo), combo);
    }
    return [...found.values()];
  }

  function customProblems(custom, data) {
    const found = [];
    const line = custom.line || data.memory.line;
    if (!data.memory.lines.includes(line)) found.push(`Linha: use ${data.memory.lines.join(", ")} bytes.`);
    for (const level of LEVELS) {
      const config = custom[level];
      if (!config) continue;
      const name = LEVEL_NAMES[level];
      if (!config.sizes.length) found.push(`${name}: informe pelo menos um tamanho.`);
      if (!prefetchersOf(config, data).length) found.push(`${name}: escolha pelo menos um prefetcher (ou nenhum).`);
      const labels = { latency: "latência", mshrs: "MSHRs", targets: "alvos por MSHR" };
      for (const [key, label] of Object.entries(labels)) {
        const value = config[key];
        const [low, high] = data.memory.bounds[key];
        if (value !== undefined && value !== null && !(Number.isInteger(value) && value >= low && value <= high)) {
          found.push(`${name}: ${label} deve ser um inteiro de ${low} a ${high}.`);
        }
      }
      if (!Number.isInteger(config.assoc) || config.assoc < 1) {
        found.push(`${name}: a associatividade deve ser um inteiro a partir de 1.`);
      }
      for (const size of config.sizes) {
        const total = bytes(size);
        if (!new RegExp(data.patterns.size).test(size) || total === null) {
          found.push(`${name}: "${size}": ${data.hints.size}.`);
          continue;
        }
        const sets = total / (line * config.assoc);
        if (Number.isInteger(config.assoc) && config.assoc >= 1 && !(Number.isInteger(sets) && sets >= 1 && (sets & (sets - 1)) === 0)) {
          found.push(
            `${name}: ${size} com associatividade ${config.assoc} e linha de ${line} bytes não dá um ` +
              "número de conjuntos potência de 2 (tamanho ÷ (linha × associatividade))."
          );
        }
      }
    }
    if (custom.l2 && !(custom.l1i && custom.l1d)) found.push("A L2 exige a L1i e a L1d.");
    if (!new RegExp(data.patterns.size).test(custom.memorySize)) {
      found.push(`Tamanho da memória: ${data.hints.size}.`);
    }
    return found;
  }

  function problems(state, data) {
    const found = [];
    if (!new RegExp(data.patterns.name).test(state.name)) {
      found.push(`Nome: ${data.hints.name} (por exemplo, meu_teste).`);
    }
    const required = [
      ["ops", "uma operação"],
      ["sizes", "um tamanho"],
      ["variants", "uma implementação"],
      ["cpus", "uma CPU"],
      ["flags", "um nível de otimização"],
      ["datasets", "um conjunto de dados"],
      ["cacheStates", "um estado das caches"],
    ];
    for (const [key, what] of required) {
      if (!state[key].length) found.push(`Escolha pelo menos ${what}.`);
    }
    if (!state.scenarios.length && !state.custom) found.push("Escolha pelo menos uma configuração de memória.");
    if (latencyMatters(state, data) && !state.latencies.length) {
      found.push("Escolha pelo menos uma latência para as instruções personalizadas.");
    }
    if (latencyMatters(state, data) && !state.units.length) {
      found.push("Escolha pelo menos uma opção de unidades para as instruções personalizadas.");
    }
    if (latencyMatters(state, data) && !state.pipelined.length) {
      found.push("Escolha com ou sem pipeline para as instruções personalizadas.");
    }
    if (state.variants.includes("rvv") && !state.vlens.length) found.push("Escolha pelo menos uma VLEN.");
    for (const latency of state.latencies) {
      if (!Number.isInteger(latency) || latency < data.latency.min || latency > data.latency.max) {
        found.push(`Latência: use um inteiro de ${data.latency.min} a ${data.latency.max}.`);
      }
    }
    if (!new RegExp(data.patterns.clock).test(state.clock)) found.push(`Clock: ${data.hints.clock}.`);
    if (state.scenarios.includes("") && (state.scenarios.length > 1 || state.custom)) {
      found.push("\"Sem cenário\" só pode ser escolhido sozinho.");
    }
    if (state.custom) found.push(...customProblems(state.custom, data));
    if (state.cacheStates.includes("cold") && !found.length) {
      const without = memories(state, data).filter((memory) => !hasCaches(memory, data));
      if (without.length) {
        const names = [...new Set(without.map((m) => (m.scenario ? m.scenario : `"${memoryLabel(m)}"`)))];
        found.push(`Caches frias exigem caches: tire ${names.join(" e ")} ou use só caches aquecidas.`);
      }
    }
    for (const op of state.ops) {
      const info = opInfo(data, op);
      for (const variant of state.variants) {
        if (info && !info.variants.includes(variant)) found.push(`${info.label} não tem a variante ${variant}.`);
      }
      for (const size of state.sizes) {
        if (info && !info.sizes[size]) found.push(`${info.label} não tem o tamanho ${size}.`);
      }
    }
    return found;
  }

  // Documento ---------------------------------------------------------------------

  function memoryDocument(memory, data) {
    if (memory.scenario || !memory.cache) return {};
    const memoryFields = {
      type: memory.memoryType !== data.memory.default.type ? memory.memoryType : undefined,
      size: memory.memorySize !== data.memory.default.size ? memory.memorySize : undefined,
    };
    return { cache: { line: memory.line || undefined, ...memory.cache }, memory: memoryFields };
  }

  function experimentDocument(state, data, combo) {
    const size = opInfo(data, combo.op).sizes[combo.size];
    return {
      name: state.name,
      description: state.description || undefined,
      scenario: combo.scenario || undefined,
      benchmark: {
        name: combo.op,
        args: size.args,
        variant: combo.variant,
        cache_state: combo.cacheState !== "warm" ? combo.cacheState : undefined,
      },
      compiler: JSON.stringify(combo.flags) !== JSON.stringify([data.flags.default]) ? { flags: combo.flags } : undefined,
      cpu: {
        model: combo.cpu,
        clock: combo.clock !== data.clock.default ? combo.clock : undefined,
        vlen: combo.vlen !== data.vlen.default ? combo.vlen : undefined,
        custom_latency: combo.latency !== data.latency.default ? combo.latency : undefined,
        custom_units: combo.units !== null ? combo.units : undefined,
        custom_pipelined: combo.pipelined ? undefined : false,
      },
      ...memoryDocument(combo, data),
    };
  }

  // set para um valor só (quando não é o padrão), vary para vários.
  function assign(fields) {
    const set = {};
    const vary = {};
    for (const [path, values, standard] of fields) {
      if (values.length > 1) vary[path] = values;
      else if (values.length === 1 && JSON.stringify(values[0]) !== JSON.stringify(standard)) set[path] = values[0];
    }
    return { set, vary };
  }

  function campaignDocument(state, data) {
    const experiments = [];
    for (const op of state.ops) {
      for (const size of state.sizes) experiments.push(opInfo(data, op).sizes[size].experiment);
    }
    const common = [
      ["benchmark.variant", state.variants, null],
      ["cpu.model", state.cpus, null],
      ["cpu.custom_latency", latencyMatters(state, data) ? state.latencies : [], data.latency.default],
      ["cpu.custom_units", latencyMatters(state, data) ? state.units : [], null],
      ["cpu.custom_pipelined", latencyMatters(state, data) ? state.pipelined : [], true],
      ["cpu.vlen", state.variants.includes("rvv") ? state.vlens : [], data.vlen.default],
      ["compiler.flags", flagLists(state, data), [data.flags.default]],
      ["benchmark.cache_state", state.cacheStates, "warm"],
      ["cpu.clock", [state.clock], data.clock.default],
    ];
    const groups = [];
    if (state.scenarios.length) {
      const named = state.scenarios.filter((id) => id);
      groups.push({ name: "principal", experiments, ...assign([...common, ["scenario", named, null]]) });
    }
    const custom = state.custom;
    if (custom) {
      const memory = [["cache.line", [custom.line || data.memory.line], data.memory.line]];
      for (const level of LEVELS) {
        const config = custom[level];
        if (!config) continue;
        const defaults = data.memory.custom[level];
        memory.push([`cache.${level}.size`, config.sizes, null]);
        memory.push([`cache.${level}.assoc`, [config.assoc], null]);
        for (const key of ["latency", "mshrs", "targets"]) {
          const value = config[key] === undefined || config[key] === null ? defaults[key] : config[key];
          memory.push([`cache.${level}.${key}`, [value], defaults[key]]);
        }
        memory.push([`cache.${level}.prefetcher`, prefetchersOf(config, data), data.memory.noPrefetcher]);
      }
      memory.push(["memory.type", [custom.memoryType], data.memory.default.type]);
      memory.push(["memory.size", [custom.memorySize], data.memory.default.size]);
      const name = groups.length ? "memoria" : "principal";
      groups.push({ name, experiments, ...assign([...common, ...memory]) });
    }
    return { name: state.name, description: state.description || undefined, groups };
  }

  function build(state, data) {
    const found = problems(state, data);
    const combos = found.length ? [] : combinations(state, data);
    const single = combos.length === 1 && state.ops.length === 1 && state.sizes.length === 1;
    const kind = single ? "experiment" : "campaign";
    const document = found.length
      ? null
      : single
        ? experimentDocument(state, data, combos[0])
        : campaignDocument(state, data);
    const header = single
      ? `# Experimento (riscvcnnbench gerador ${data.version}); formato em docs/experiments.md`
      : `# Campanha (riscvcnnbench gerador ${data.version}); formato em docs/campaigns.md`;
    return {
      kind,
      problems: found,
      combinations: combos,
      yaml: document ? `${header}\n${toYaml(document)}\n` : "",
    };
  }

  // Estimativa e onde ficam os dados --------------------------------------------------

  function binaryKey(combo, data) {
    const args = opInfo(data, combo.op).sizes[combo.size].args.map(String).join(",");
    const vlen = combo.variant === "rvv" ? String(combo.vlen) : "";
    return [combo.op, args, combo.variant, combo.flags.join(" "), vlen].join("|");
  }

  // O rótulo do cenário de `metric.scenario_label`: o nome, ou os tamanhos e a memória.
  function scenarioLabel(combo, data) {
    let label = combo.scenario;
    if (!label && !combo.cache) label = data.noScenarioLabel;
    if (!label) {
      const levels = LEVELS.filter((level) => combo.cache[level]).map((l) => `${l}=${combo.cache[l].size}`);
      const tuning = combo.line ? [`line=${combo.line}`] : [];
      for (const level of LEVELS) {
        for (const [key, short] of TUNING) {
          const value = combo.cache[level] && combo.cache[level][key];
          if (value !== undefined && value !== null && value !== data.memory.noPrefetcher) {
            tuning.push(`${level}.${short}=${value}`);
          }
        }
      }
      label = [...(levels.length ? levels : ["sem-cache"]), combo.memoryType, ...tuning].join(",");
    }
    return label + (combo.cacheState === "cold" ? ",cold" : "");
  }

  function speedKey(combo, data) {
    return [combo.cpu, combo.clock, scenarioLabel(combo, data)].join("|");
  }

  // Mesmo modelo do `campaign estimate`: a + b · W por CPU, clock e cenário.
  function estimate(combos, data, jobs) {
    if (!data.estimate) return null;
    const times = [];
    for (const combo of combos) {
      const work = data.estimate.works[binaryKey(combo, data)];
      const line = data.estimate.fits[speedKey(combo, data)];
      if (work !== undefined && line) times.push(Math.max(0, line[0] + line[1] * work));
    }
    const workers = new Array(Math.max(1, jobs)).fill(0);
    for (const seconds of times) {
      const next = workers.indexOf(Math.min(...workers));
      workers[next] += seconds;
    }
    return {
      known: times.length,
      total: combos.length,
      serial: times.reduce((sum, value) => sum + value, 0),
      makespan: Math.max(...workers),
    };
  }

  // Onde ficam os dados da região de interesse, por capacidade (docs/scenarios.md).
  // `memory` é um cenário nomeado (texto) ou uma configuração de `memories`.
  function residence(op, size, memory, data) {
    const total = opInfo(data, op).sizes[size].bytes;
    const config = typeof memory === "string" ? { scenario: memory, cache: null } : memory;
    let l1d = null;
    let l2 = null;
    let type = "simple";
    if (config.cache) {
      l1d = config.cache.l1d ? bytes(config.cache.l1d.size) : null;
      l2 = config.cache.l2 ? bytes(config.cache.l2.size) : null;
      type = config.memoryType;
    } else {
      const info = scenarioInfo(data, config.scenario);
      l1d = info.l1d;
      l2 = info.l2;
      type = info.memory;
    }
    if (total === null || total === undefined) return null;
    const beyond = type === "simple" ? "memória" : "DRAM";
    if (l1d && total <= l1d) return "L1d";
    if (l1d && l2 && total <= l2) return "L2";
    return beyond;
  }

  return {
    build,
    combinations,
    memories,
    memoryLabel,
    problems,
    toYaml,
    estimate,
    residence,
    binaryKey,
    speedKey,
  };
})();

// Interface ---------------------------------------------------------------------------

if (typeof document !== "undefined") {
  const DATA = JSON.parse(document.getElementById("rcb-data").textContent);
  const $ = (id) => document.getElementById(id);
  const kib = (bytes) => `${(bytes / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KiB`;
  const minutes = (seconds) =>
    seconds < 90
      ? `${Math.round(seconds)} s`
      : seconds < 5400
        ? `${(seconds / 60).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} min`
        : `${(seconds / 3600).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h`;

  function choice(container, type, name, items, checked) {
    for (const item of items) {
      const label = document.createElement("label");
      label.className = "choice";
      const input = document.createElement("input");
      input.type = type;
      input.name = name;
      input.value = item.value;
      input.checked = checked.includes(item.value);
      input.addEventListener("change", update);
      const text = document.createElement("span");
      text.innerHTML = `<strong>${item.title}</strong>${item.detail ? `<small>${item.detail}</small>` : ""}`;
      label.append(input, text);
      container.append(label);
    }
  }

  const picked = (name) => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);
  const list = (text) =>
    text
      .split(/[,;\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);

  function setup() {
    choice($("ops"), "checkbox", "ops", DATA.ops.map((op) => ({ value: op.id, title: op.label, detail: op.id })), [
      DATA.ops[DATA.ops.length - 1].id,
    ]);
    choice(
      $("sizes"),
      "checkbox",
      "sizes",
      [
        { value: "S", title: "S (pequeno)", detail: "cabe na L1d de 32 KiB" },
        { value: "L", title: "L (grande)", detail: "maior que a L1d" },
      ],
      ["S"]
    );
    choice($("variants"), "checkbox", "variants", DATA.variants, ["ref", "custom", "rvv"]);
    choice(
      $("cpus"),
      "checkbox",
      "cpus",
      DATA.cpus.map((cpu) => ({ value: cpu.id, title: cpu.id, detail: cpu.description })),
      ["minor"]
    );
    choice(
      $("latencies"),
      "checkbox",
      "latencies",
      DATA.latency.options.map((v) => ({ value: String(v.value), title: `${v.value} ciclos`, detail: v.detail })),
      [String(DATA.latency.default)]
    );
    choice(
      $("units"),
      "checkbox",
      "units",
      DATA.units.options.map((v) => ({
        value: v === null ? "" : String(v),
        title: v === null ? "padrão" : `${v} própria${v === 1 ? "" : "s"}`,
        detail: v === null ? DATA.units.default : "",
      })),
      [""]
    );
    choice(
      $("pipelined"),
      "checkbox",
      "pipelined",
      [
        { value: "true", title: "com pipeline", detail: "aceita uma instrução por ciclo (padrão)" },
        { value: "false", title: "sem pipeline", detail: "só aceita outra depois da latência inteira" },
      ],
      ["true"]
    );
    choice(
      $("vlens"),
      "checkbox",
      "vlens",
      DATA.vlen.options.map((v) => ({ value: String(v), title: `${v} bits`, detail: v === DATA.vlen.default ? "padrão" : "" })),
      [String(DATA.vlen.default)]
    );
    choice(
      $("scenarios"),
      "checkbox",
      "scenarios",
      DATA.scenarios.map((s) => ({ value: s.id, title: s.id || "sem cenário", detail: s.description })),
      ["l1-l2"]
    );
    choice(
      $("cacheStates"),
      "checkbox",
      "cacheStates",
      [
        { value: "warm", title: "aquecidas", detail: "os dados já estão nas caches no início da medição (padrão)" },
        { value: "cold", title: "frias", detail: "o gem5 esvazia as caches antes da medição" },
      ],
      ["warm"]
    );
    choice(
      $("flags"),
      "checkbox",
      "flags",
      DATA.flags.options.map((f) => ({ value: f, title: f, detail: f === DATA.flags.default ? "padrão" : "" })),
      [DATA.flags.default]
    );
    choice(
      $("datasets"),
      "checkbox",
      "datasets",
      DATA.datasets.map((d) => ({ value: d.id, title: d.id, detail: d.detail })),
      [DATA.datasets[0].id]
    );
    const defaults = DATA.memory.custom;
    for (const level of ["l1i", "l1d", "l2"]) {
      for (const key of ["size", "assoc", "latency", "mshrs", "targets"]) {
        $(`${level}${key[0].toUpperCase()}${key.slice(1)}`).value = defaults[level][key];
      }
      choice(
        $(`${level}Prefetchers`),
        "checkbox",
        `${level}Prefetcher`,
        DATA.memory.prefetchers.map((p) => ({ value: p, title: p === DATA.memory.noPrefetcher ? "sem prefetcher" : p })),
        [DATA.memory.noPrefetcher]
      );
    }
    for (const line of DATA.memory.lines) {
      const option = document.createElement("option");
      option.value = line;
      option.textContent = `${line} bytes${line === DATA.memory.line ? " (padrão)" : ""}`;
      $("cacheLine").append(option);
    }
    $("cacheLine").value = DATA.memory.line;
    for (const type of DATA.memory.types) {
      const option = document.createElement("option");
      option.value = option.textContent = type;
      $("memoryType").append(option);
    }
    $("memoryType").value = defaults.type;
    $("memorySize").value = DATA.memory.default.size;
    $("clock").value = DATA.clock.default;
    const inputs = ["name", "description", "clock", "extraLatency", "jobs", "useCustom", "memoryType", "memorySize", "cacheLine"];
    for (const level of ["l1i", "l1d", "l2"]) {
      inputs.push(`${level}On`, `${level}Size`, `${level}Assoc`, `${level}Latency`, `${level}Mshrs`, `${level}Targets`);
    }
    for (const id of inputs) {
      $(id).addEventListener("input", update);
      $(id).addEventListener("change", update);
    }
    $("download").addEventListener("click", download);
    $("copy").addEventListener("click", () => navigator.clipboard.writeText($("yaml").textContent));
    $("version").textContent = DATA.version;
    update();
  }

  function customState() {
    if (!$("useCustom").checked) return null;
    const custom = {
      memoryType: $("memoryType").value,
      memorySize: $("memorySize").value.trim(),
      line: Number($("cacheLine").value),
    };
    for (const level of ["l1i", "l1d", "l2"]) {
      custom[level] = $(`${level}On`).checked
        ? {
            sizes: list($(`${level}Size`).value),
            assoc: Number($(`${level}Assoc`).value),
            latency: Number($(`${level}Latency`).value),
            mshrs: Number($(`${level}Mshrs`).value),
            targets: Number($(`${level}Targets`).value),
            prefetchers: picked(`${level}Prefetcher`),
          }
        : null;
    }
    return custom;
  }

  function state() {
    const latencies = picked("latencies").map(Number);
    const extra = $("extraLatency").value.trim();
    if (extra) latencies.push(Number(extra));
    return {
      name: $("name").value.trim(),
      description: $("description").value.trim(),
      ops: picked("ops"),
      sizes: picked("sizes"),
      variants: picked("variants"),
      cpus: picked("cpus"),
      scenarios: picked("scenarios"),
      custom: customState(),
      latencies: [...new Set(latencies)],
      units: picked("units").map((v) => (v === "" ? null : Number(v))),
      pipelined: picked("pipelined").map((v) => v === "true"),
      vlens: picked("vlens").map(Number),
      flags: picked("flags"),
      datasets: picked("datasets"),
      cacheStates: picked("cacheStates"),
      clock: $("clock").value.trim(),
    };
  }

  function update() {
    const current = state();
    $("latencyBox").hidden = !(
      current.variants.includes("custom") && current.cpus.some((id) => DATA.cpus.find((c) => c.id === id).latency)
    );
    $("vlenBox").hidden = !current.variants.includes("rvv");
    $("customBox").hidden = !$("useCustom").checked;
    for (const level of ["l1i", "l1d", "l2"]) {
      const off = !$(`${level}On`).checked;
      for (const key of ["Size", "Assoc", "Latency", "Mshrs", "Targets"]) $(`${level}${key}`).disabled = off;
      for (const input of document.querySelectorAll(`input[name="${level}Prefetcher"]`)) input.disabled = off;
    }
    const result = RCB.build(current, DATA);
    const file = `build/meus/${current.name || "nome"}.yaml`;
    $("problems").innerHTML = result.problems.map((p) => `<li>${p}</li>`).join("");
    $("problems").hidden = !result.problems.length;
    $("yaml").textContent = result.yaml || "# Corrija os itens acima para ver o YAML.";
    $("download").disabled = $("copy").disabled = !result.yaml;
    const count = result.combinations.length;
    const isExperiment = result.kind === "experiment";
    $("count").textContent = result.problems.length
      ? "—"
      : `${count} ${count === 1 ? "simulação" : "simulações"} · ${isExperiment ? "experimento" : "campanha"}`;
    const jobs = Math.max(1, Number($("jobs").value) || 1);
    const time = RCB.estimate(result.combinations, DATA, jobs);
    $("estimate").textContent = !time
      ? "Sem estimativa de tempo (gere a página com --measured <pasta com execuções medidas>)."
      : time.known === 0
        ? "Sem estimativa: nenhuma combinação parecida foi medida."
        : `≈ ${minutes(time.serial)} em série; ≈ ${minutes(time.makespan)} com ${jobs} tarefa(s)` +
          (time.known < time.total ? ` (estimadas ${time.known} de ${time.total})` : "");
    $("commands").textContent = result.yaml
      ? isExperiment
        ? `# Salve o arquivo como ${file} (dentro da pasta do projeto)\nmake run EXPERIMENT=${file}\nmake runs DIR=results/${current.name}`
        : `# Salve o arquivo como ${file} (dentro da pasta do projeto)\nmake campaign-plan MATRIX=${file}\nmake campaign MATRIX=${file} JOBS=${jobs}\nmake report DIR=results/campaigns/${current.name}\nmake plot DIR=results/campaigns/${current.name}\nmake analyze DIR=results/campaigns/${current.name}`
      : "";
    renderResidence(current, result.problems.length === 0);
  }

  function renderResidence(current, valid) {
    const configs = valid ? RCB.memories(current, DATA) : [];
    const rows = [];
    for (const op of current.ops) {
      const info = DATA.ops.find((o) => o.id === op);
      for (const size of current.sizes) {
        if (!info.sizes[size]) continue;
        const cells = configs.map((m) => RCB.residence(op, size, m, DATA) || "?");
        const bytes = info.sizes[size].bytes;
        rows.push(
          `<tr><td>${info.label} ${size}</td><td>${bytes ? kib(bytes) : "?"}</td>${cells.map((c) => `<td class="${c}">${c}</td>`).join("")}</tr>`
        );
      }
    }
    $("residence").innerHTML =
      rows.length && configs.length
        ? `<thead><tr><th>Operação</th><th>Dados</th>${configs.map((m) => `<th>${shortLabel(m)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody>`
        : "";
  }

  // Rótulo curto da coluna: o cenário, ou só a L1d e a L2 da memória personalizada.
  function shortLabel(memory) {
    if (!memory.cache) return memory.scenario || "sem cenário";
    const level = (name) => {
      const config = memory.cache[name];
      if (!config) return "—";
      return config.prefetcher ? `${config.size} (${config.prefetcher})` : config.size;
    };
    const line = memory.line ? `<br>linha ${memory.line}` : "";
    return `L1d ${level("l1d")}<br>L2 ${level("l2")}${line}`;
  }

  function download() {
    const blob = new Blob([$("yaml").textContent], { type: "text/yaml" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${$("name").value.trim() || "experimento"}.yaml`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  setup();
}
