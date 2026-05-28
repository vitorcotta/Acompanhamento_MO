const fmt = (n) =>
  n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

const fmtShort = (n) => {
  const v = Number(n);
  if (!v) return "";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `R$ ${(v / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1_000) return `R$ ${(v / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}k`;
  return fmt(v);
};

const DIVISAO_COLORS = [
  "#3d8bfd",
  "#10b981",
  "#f59e0b",
  "#a78bfa",
  "#f472b6",
  "#38bdf8",
  "#fb923c",
];

if (window.ChartDataLabels) {
  Chart.register(ChartDataLabels);
  Chart.defaults.set("plugins.datalabels", { display: false });
}

let charts = {};
let divCharts = {};
let orcCharts = {};
let exercicioAtual = null;
let divisaoAtual = null;
let orcDivisaoFiltro = "";

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function divisaoQuery(divisao) {
  return divisao ? `?divisao=${encodeURIComponent(divisao)}` : "";
}

function destroyChartSet(set) {
  Object.values(set).forEach((c) => c.destroy());
  Object.keys(set).forEach((k) => delete set[k]);
}

function chartDefaults({ currencyY = true } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: "#8b9cb3" } },
    },
    scales: {
      x: { ticks: { color: "#8b9cb3" }, grid: { color: "#2d3a4f33" } },
      y: {
        ticks: {
          color: "#8b9cb3",
          callback: currencyY ? (v) => fmtShort(v) : (v) => v,
        },
        grid: { color: "#2d3a4f33" },
      },
    },
  };
}

function stackedBarTotal(ctx) {
  return ctx.chart.data.datasets.reduce(
    (sum, ds) => sum + (Number(ds.data[ctx.dataIndex]) || 0),
    0
  );
}

function datalabelsStacked(minShare = 0.07) {
  return {
    display: (ctx) => {
      const value = Number(ctx.dataset.data[ctx.dataIndex]);
      if (!value) return false;
      const total = stackedBarTotal(ctx);
      return total > 0 && value / total >= minShare;
    },
    color: "#fff",
    font: { size: 9, weight: "600" },
    formatter: (value) => fmtShort(value),
  };
}

function renderDashboardCharts(resumo, divisoesData) {
  destroyChartSet(charts);
  const labels = resumo.map((m) => m.mes_label);
  const defaults = chartDefaults();

  charts.total = new Chart(document.getElementById("chart-total"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Total",
          data: resumo.map((m) => m.total),
          borderColor: "#3d8bfd",
          backgroundColor: "#3d8bfd33",
          fill: true,
          tension: 0.3,
          datalabels: { align: "top", anchor: "end" },
        },
      ],
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: {
          display: true,
          color: "#e7ecf3",
          font: { size: 10, weight: "600" },
          formatter: (v) => fmtShort(v),
        },
      },
    },
  });

  charts.admPct = new Chart(document.getElementById("chart-adm-pct"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "% ADM",
          data: resumo.map((m) => m.pct_adm),
          backgroundColor: "#f59e0b",
        },
      ],
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: {
          display: true,
          color: "#fff",
          font: { size: 10, weight: "600" },
          formatter: (v) => `${v}%`,
        },
      },
      scales: {
        ...defaults.scales,
        y: {
          ticks: { color: "#8b9cb3", callback: (v) => `${v}%` },
          grid: { color: "#2d3a4f33" },
          max: 100,
        },
      },
    },
  });

  charts.stack = new Chart(document.getElementById("chart-stack"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Time (não ADM)",
          data: resumo.map((m) => m.time),
          backgroundColor: "#10b981",
          stack: "s",
        },
        {
          label: "ADM",
          data: resumo.map((m) => m.adm),
          backgroundColor: "#f59e0b",
          stack: "s",
        },
      ],
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: datalabelsStacked(0.08),
      },
      scales: {
        ...defaults.scales,
        x: { ...defaults.scales.x, stacked: true },
        y: { ...defaults.scales.y, stacked: true },
      },
    },
  });

  const divLabels = divisoesData.meses.map((m) => m.label);
  charts.divisoes = new Chart(document.getElementById("chart-divisoes"), {
    type: "bar",
    data: {
      labels: divLabels,
      datasets: divisoesData.series.map((s, i) => ({
        label: `${s.divisao} (${s.pct_ano}%)`,
        data: s.valores,
        backgroundColor: DIVISAO_COLORS[i % DIVISAO_COLORS.length],
        stack: "div",
      })),
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: datalabelsStacked(0.06),
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = stackedBarTotal(ctx);
              const v = ctx.raw;
              const pct = total ? ((v / total) * 100).toFixed(1) : 0;
              return `${ctx.dataset.label}: ${fmt(v)} (${pct}%)`;
            },
          },
        },
      },
      scales: {
        ...defaults.scales,
        x: { ...defaults.scales.x, stacked: true },
        y: { ...defaults.scales.y, stacked: true },
      },
    },
  });
}

function renderCards(containerId, resumo) {
  const el = document.getElementById(containerId);
  el.innerHTML = resumo
    .map(
      (m) => `
    <div class="card">
      <div class="label">${m.mes_label}</div>
      <div class="value">${fmt(m.total)}</div>
      <div class="meta">ADM <strong>${m.pct_adm}%</strong> · ${fmt(m.adm)}</div>
      ${
        m.variacao_total_pct != null
          ? `<div class="meta">vs mês ant.: ${m.variacao_total_pct > 0 ? "+" : ""}${m.variacao_total_pct}%</div>`
          : ""
      }
    </div>`
    )
    .join("");
}

function renderCharts(chartSet, ids, resumo) {
  destroyChartSet(chartSet);
  const labels = resumo.map((m) => m.mes_label);
  const defaults = { ...chartDefaults(), maintainAspectRatio: true };

  chartSet.total = new Chart(document.getElementById(ids.total), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Total",
          data: resumo.map((m) => m.total),
          borderColor: "#3d8bfd",
          backgroundColor: "#3d8bfd33",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: defaults,
  });

  chartSet.admPct = new Chart(document.getElementById(ids.admPct), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "% ADM",
          data: resumo.map((m) => m.pct_adm),
          backgroundColor: "#f59e0b",
        },
      ],
    },
    options: {
      ...defaults,
      scales: {
        ...defaults.scales,
        y: {
          ticks: { color: "#8b9cb3", callback: (v) => `${v}%` },
          grid: { color: "#2d3a4f33" },
          max: 100,
        },
      },
    },
  });

  chartSet.stack = new Chart(document.getElementById(ids.stack), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Time (não ADM)",
          data: resumo.map((m) => m.time),
          backgroundColor: "#10b981",
          stack: "s",
        },
        {
          label: "ADM",
          data: resumo.map((m) => m.adm),
          backgroundColor: "#f59e0b",
          stack: "s",
        },
      ],
    },
    options: {
      ...defaults,
      scales: {
        ...defaults.scales,
        x: { ...defaults.scales.x, stacked: true },
        y: { ...defaults.scales.y, stacked: true },
      },
    },
  });
}

function renderPivotTable(tableEl, data, rowHeader = "Equipe (Descrição Despesa)") {
  const linhas = data.linhas || data.equipes || data.colaboradores || [];
  const thead = tableEl.querySelector("thead");
  const tbody = tableEl.querySelector("tbody");
  const monthHeaders = data.meses
    .map((m) => `<th>${m.label}<br><span class="sub">total / var%</span></th>`)
    .join("");
  thead.innerHTML = `<tr><th>${rowHeader}</th>${monthHeaders}<th>Total ano</th></tr>`;

  tbody.innerHTML = linhas
    .map((linha) => {
      const row = data.grid[linha];
      const cells = data.meses
        .map((m) => {
          const cell = row.meses[m.num];
          const variacao = data.variacoes[linha][m.num];
          let varHtml = "";
          if (variacao != null) {
            const cls = variacao > 0 ? "var-up" : variacao < 0 ? "var-down" : "";
            varHtml = `<span class="${cls}">${variacao > 0 ? "+" : ""}${variacao}%</span>`;
          }
          const pctAdm = cell.total ? ((cell.adm / cell.total) * 100).toFixed(0) : 0;
          return `<td>
            ${fmt(cell.total)}
            <span class="sub">ADM ${pctAdm}%</span>
            ${varHtml}
          </td>`;
        })
        .join("");
      const tot = row.total_ano;
      const pctAno = tot.total ? ((tot.adm / tot.total) * 100).toFixed(0) : 0;
      return `<tr>
        <td class="pivot-row-name">${linha}</td>
        ${cells}
        <td>${fmt(tot.total)}<span class="sub">ADM ${pctAno}%</span></td>
      </tr>`;
    })
    .join("");
}

async function loadExercicios() {
  const { exercicios } = await api("/api/exercicios");
  const sel = document.getElementById("exercicio");
  sel.innerHTML = "";
  if (!exercicios.length) {
    sel.innerHTML = "<option value=''>Sem dados</option>";
    return;
  }
  exercicios.forEach((ex) => {
    const opt = document.createElement("option");
    opt.value = ex;
    opt.textContent = ex;
    sel.appendChild(opt);
  });
  exercicioAtual = exercicios[0];
  sel.value = exercicioAtual;
  sel.onchange = async () => {
    exercicioAtual = Number(sel.value);
    await loadDivisoes();
    await refreshAll();
  };
}

async function loadDivisoes() {
  const sel = document.getElementById("divisao-filtro");
  if (!exercicioAtual) {
    sel.innerHTML = "";
    return;
  }
  const { divisoes } = await api(`/api/divisoes/${exercicioAtual}`);
  sel.innerHTML = "";
  if (!divisoes.length) {
    sel.innerHTML = "<option value=''>Sem divisões</option>";
    divisaoAtual = null;
    return;
  }
  divisoes.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    sel.appendChild(opt);
  });
  divisaoAtual = divisoes[0];
  sel.value = divisaoAtual;
}

async function loadDashboard() {
  const [{ resumo }, divisoesData] = await Promise.all([
    api(`/api/resumo/${exercicioAtual}`),
    api(`/api/divisoes-mensal/${exercicioAtual}`),
  ]);
  renderCards("cards-mes", resumo);
  renderDashboardCharts(resumo, divisoesData);
}

async function loadPivot() {
  const data = await api(`/api/pivot/${exercicioAtual}`);
  renderPivotTable(document.getElementById("pivot-table"), data);
}

async function loadPivotPessoas() {
  const data = await api(`/api/pivot-pessoas/${exercicioAtual}`);
  renderPivotTable(
    document.getElementById("pessoas-pivot-table"),
    data,
    "Colaborador (Nome)"
  );
}

async function loadDivisaoPage() {
  if (!exercicioAtual || !divisaoAtual) return;
  const q = divisaoQuery(divisaoAtual);
  const [{ resumo }, pivot] = await Promise.all([
    api(`/api/resumo/${exercicioAtual}${q}`),
    api(`/api/pivot/${exercicioAtual}${q}`),
  ]);
  renderCards("div-cards-mes", resumo);
  renderCharts(divCharts, {
    total: "div-chart-total",
    admPct: "div-chart-adm-pct",
    stack: "div-chart-stack",
  }, resumo);
  renderPivotTable(document.getElementById("div-pivot-table"), pivot);
}

async function deleteArquivo(id, nome, tipo) {
  const msg =
    tipo === "orcamento"
      ? `Excluir o orçamento "${nome}"?\n\nOs valores orçados serão removidos. Use Upload para enviar uma nova versão.`
      : `Excluir "${nome}"?\n\nOs lançamentos importados deste arquivo serão removidos do sistema.`;
  if (!confirm(msg)) {
    return;
  }
  await api(`/api/arquivos/${id}?tipo=${tipo}`, { method: "DELETE" });
  await loadExercicios();
  await loadDivisoes();
  await refreshAll();
}

async function loadArquivos() {
  const { arquivos } = await api("/api/arquivos");
  const tbody = document.querySelector("#arquivos-table tbody");
  if (!arquivos.length) {
    tbody.innerHTML = `<tr><td colspan="7">Nenhum arquivo importado ainda.</td></tr>`;
    return;
  }
  tbody.innerHTML = arquivos
    .map(
      (a) => `<tr>
        <td>${a.nome}</td>
        <td>${a.tipo === "orcamento" ? "Orçamento" : "Realizado"}</td>
        <td>${a.exercicio ?? "—"}</td>
        <td>${a.meses || "—"}</td>
        <td>${a.total_linhas}</td>
        <td>${new Date(a.importado_em).toLocaleString("pt-BR")}</td>
        <td>
          <button type="button" class="btn danger" data-delete-id="${a.id}" data-delete-tipo="${a.tipo}" data-delete-nome="${escapeHtml(a.nome)}">
            Excluir
          </button>
        </td>
      </tr>`
    )
    .join("");
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function setupArquivosTable() {
  document.querySelector("#arquivos-table tbody").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-delete-id]");
    if (!btn) return;
    const id = Number(btn.dataset.deleteId);
    const nome = btn.dataset.deleteNome;
    const tipo = btn.dataset.deleteTipo;
    try {
      await deleteArquivo(id, nome, tipo);
    } catch (err) {
      alert(err.message);
    }
  });
}

function consumoClass(pct) {
  if (pct == null) return "";
  if (pct > 100) return "consumo-over";
  if (pct >= 90) return "consumo-warn";
  return "consumo-ok";
}

async function loadOrcDivisoes() {
  const sel = document.getElementById("orc-divisao-filtro");
  const current = sel.value;
  sel.innerHTML = '<option value="">Todas</option>';
  if (!exercicioAtual) return;
  const { divisoes } = await api(`/api/divisoes/${exercicioAtual}`);
  divisoes.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    sel.appendChild(opt);
  });
  sel.value = current || "";
  orcDivisaoFiltro = sel.value;
}

async function loadOrcamentoPage() {
  if (!exercicioAtual) return;
  const q = orcDivisaoFiltro ? `?divisao=${encodeURIComponent(orcDivisaoFiltro)}` : "";
  const data = await api(`/api/orcamento/${exercicioAtual}${q}`);
  const emptyEl = document.getElementById("orc-empty");
  const tableWrap = document.querySelector("#orc-table").closest(".table-scroll");
  const cardsEl = document.getElementById("orc-cards");
  const gridEl = document.querySelector("#panel-orcamento .charts-grid");

  if (!data.tem_orcamento) {
    emptyEl.classList.remove("hidden");
    tableWrap.classList.add("hidden");
    gridEl.classList.add("hidden");
    cardsEl.innerHTML = "";
    destroyChartSet(orcCharts);
    return;
  }

  emptyEl.classList.add("hidden");
  tableWrap.classList.remove("hidden");
  gridEl.classList.remove("hidden");

  const t = data.totais;
  cardsEl.innerHTML = `
    <div class="card"><div class="label">Orçado (ano)</div><div class="value">${fmt(t.orcado)}</div></div>
    <div class="card"><div class="label">Realizado (ano)</div><div class="value">${fmt(t.realizado)}</div></div>
    <div class="card"><div class="label">Saldo</div><div class="value">${fmt(t.saldo)}</div></div>
    <div class="card"><div class="label">Consumo</div><div class="value ${consumoClass(t.consumo_pct)}">${t.consumo_pct ?? "—"}%</div></div>
  `;

  destroyChartSet(orcCharts);
  const labels = data.resumo_mensal.map((m) => m.mes_label);
  const defaults = chartDefaults();

  orcCharts.compare = new Chart(document.getElementById("orc-chart-compare"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Orçado",
          data: data.resumo_mensal.map((m) => m.orcado),
          backgroundColor: "#3d8bfd",
        },
        {
          label: "Realizado",
          data: data.resumo_mensal.map((m) => m.realizado),
          backgroundColor: "#10b981",
        },
      ],
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: {
          display: true,
          anchor: "end",
          align: "top",
          color: "#e7ecf3",
          font: { size: 9, weight: "600" },
          formatter: (v) => fmtShort(v),
        },
      },
    },
  });

  orcCharts.consumo = new Chart(document.getElementById("orc-chart-consumo"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "% consumo",
          data: data.resumo_mensal.map((m) => m.consumo_pct),
          borderColor: "#f59e0b",
          backgroundColor: "#f59e0b33",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      ...defaults,
      plugins: {
        ...defaults.plugins,
        datalabels: {
          display: true,
          align: "top",
          anchor: "end",
          color: "#e7ecf3",
          font: { size: 10, weight: "600" },
          formatter: (v) => (v != null ? `${v}%` : ""),
        },
      },
      scales: {
        ...defaults.scales,
        y: {
          ticks: { color: "#8b9cb3", callback: (v) => `${v}%` },
          grid: { color: "#2d3a4f33" },
        },
      },
    },
  });

  const thead = document.querySelector("#orc-table thead");
  const tbody = document.querySelector("#orc-table tbody");
  const monthHeaders = data.meses
    .map((m) => `<th>${m.label}<br><span class="sub">orc / real / %</span></th>`)
    .join("");
  thead.innerHTML = `<tr>
    <th>Despesa</th><th>Divisão</th><th>Equipe</th>
    ${monthHeaders}
    <th>Total<br><span class="sub">orc / real / %</span></th>
  </tr>`;

  tbody.innerHTML = data.linhas
    .map((linha) => {
      const cells = data.meses
        .map((m) => {
          const c = linha.meses[m.num];
          const pct =
            c.orcado > 0 ? Math.round((c.realizado / c.orcado) * 1000) / 10 : null;
          return `<td>
            <span class="sub">${fmtShort(c.orcado)} / ${fmtShort(c.realizado)}</span>
            <span class="${consumoClass(pct)}">${pct != null ? `${pct}%` : "—"}</span>
          </td>`;
        })
        .join("");
      const tot = linha.total_ano;
      return `<tr>
        <td>${linha.despesa}</td>
        <td>${linha.divisao}</td>
        <td>${linha.equipe}</td>
        ${cells}
        <td>
          <span class="sub">${fmtShort(tot.orcado)} / ${fmtShort(tot.realizado)}</span>
          <span class="${consumoClass(tot.consumo_pct)}">${tot.consumo_pct != null ? `${tot.consumo_pct}%` : "—"}</span>
        </td>
      </tr>`;
    })
    .join("");
}

async function refreshAll() {
  if (!exercicioAtual) return;
  await Promise.all([loadDashboard(), loadPivot(), loadPivotPessoas(), loadArquivos()]);
  const divisaoPanel = document.getElementById("panel-divisao");
  if (divisaoPanel.classList.contains("active")) {
    await loadDivisaoPage();
  }
  const orcPanel = document.getElementById("panel-orcamento");
  if (orcPanel.classList.contains("active")) {
    await loadOrcamentoPage();
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", async () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = document.getElementById(`panel-${tab.dataset.tab}`);
      panel.classList.add("active");
      if (tab.dataset.tab === "divisao") {
        await loadDivisaoPage();
      }
      if (tab.dataset.tab === "orcamento") {
        await loadOrcamentoPage();
      }
    });
  });
}

function setupOrcamentoFilter() {
  document.getElementById("orc-divisao-filtro").addEventListener("change", async (e) => {
    orcDivisaoFiltro = e.target.value;
    await loadOrcamentoPage();
  });
}

function setupDivisaoFilter() {
  document.getElementById("divisao-filtro").addEventListener("change", async (e) => {
    divisaoAtual = e.target.value;
    await loadDivisaoPage();
  });
}

function setupUpload() {
  const zone = document.getElementById("drop-zone");
  const input = document.getElementById("file-input");
  const status = document.getElementById("upload-status");

  const showStatus = (msg, ok) => {
    status.textContent = msg;
    status.className = `status ${ok ? "ok" : "err"}`;
  };

  const upload = async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    showStatus("Enviando…", true);
    try {
      const res = await api("/api/upload", { method: "POST", body: fd });
      const detalhe =
        res.tipo === "orcamento"
          ? `orçamento · ${res.arquivo.total_linhas} linhas`
          : `realizado · meses ${res.arquivo.meses}`;
      showStatus(`Importado: ${res.arquivo.nome} (${detalhe})`, true);
      await loadExercicios();
      await loadDivisoes();
      await loadOrcDivisoes();
      await refreshAll();
    } catch (e) {
      showStatus(e.message, false);
    }
  };

  document.getElementById("btn-pick").onclick = () => input.click();
  input.onchange = () => input.files[0] && upload(input.files[0]);

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) upload(file);
  });
}

document.getElementById("btn-reimport").addEventListener("click", async () => {
  await api("/api/reimport", { method: "POST" });
  await loadExercicios();
  await loadDivisoes();
  await loadOrcDivisoes();
  await refreshAll();
});

setupTabs();
setupUpload();
setupDivisaoFilter();
setupOrcamentoFilter();
setupArquivosTable();

(async () => {
  await loadExercicios();
  await loadDivisoes();
  await loadOrcDivisoes();
  await refreshAll();
})();
