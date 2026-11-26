import {
  DEFAULT_SETTINGS, PROVIDERS, bridgeOriginPattern, bridgeUrlAllowed, consumerId, hourLimit, loadSettings, saveSettings,
} from "./config.js";

const $ = (id) => document.getElementById(id);
const say = (text) => {
  $("msg").textContent = text;
  setTimeout(() => { if ($("msg").textContent === text) $("msg").textContent = ""; }, 4000);
};
const when = (ms) => (ms ? new Date(ms).toLocaleString("pt-BR") : "—");

async function fill() {
  const s = await loadSettings();
  $("enabled").checked = s.enabled;
  $("bridgeUrl").value = s.bridgeUrl;
  $("token").value = s.token;
  $("consumerName").value = s.consumerName;
  $("delayMinS").value = s.delayMinS;
  $("delayMaxS").value = s.delayMaxS;
  $("foreground").checked = s.foreground;
  $("providers").innerHTML = "";
  for (const [id, p] of Object.entries(PROVIDERS)) {
    const label = document.createElement("label");
    label.className = "check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = id;
    box.checked = s.providers.includes(id);
    label.append(box, ` ${p.label}`);
    const limit = document.createElement("input");
    limit.type = "number";
    limit.min = "1";
    limit.dataset.limit = id;
    limit.value = hourLimit(s, id);
    limit.title = `Máx. buscas/hora em ${p.label}`;
    const row = document.createElement("div");
    row.className = "provider";
    row.append(label, limit);
    $("providers").append(row);
  }
}

async function save() {
  const bridgeUrl = $("bridgeUrl").value.trim() || DEFAULT_SETTINGS.bridgeUrl;
  if (!bridgeUrlAllowed(bridgeUrl)) return say("URL recusada: https, ou http só em 127.0.0.1/localhost ou IP da rede local.");
  // Ponte fora desta máquina (ex.: homelab): o Chrome pede para liberar o endereço. Precisa vir do clique em Salvar.
  const origins = [bridgeOriginPattern(bridgeUrl)];
  if (!(await chrome.permissions.contains({ origins }))) {
    let granted = false;
    try {
      granted = await chrome.permissions.request({ origins });
    } catch (e) {
      return say(`Não deu para pedir acesso a ${origins[0]}: ${e.message}`);
    }
    if (!granted) return say(`Sem acesso a ${origins[0]} a extensão não fala com a ponte. Nada foi salvo.`);
  }
  const num = (id, fallback) => {
    const v = Number($(id).value);
    return Number.isFinite(v) && v >= 0 ? v : fallback;
  };
  await saveSettings({
    enabled: $("enabled").checked,
    bridgeUrl,
    token: $("token").value.trim(),
    consumerName: $("consumerName").value.trim().slice(0, 60),
    providers: [...$("providers").querySelectorAll("input:checked")].map((b) => b.value),
    delayMinS: num("delayMinS", DEFAULT_SETTINGS.delayMinS),
    delayMaxS: num("delayMaxS", DEFAULT_SETTINGS.delayMaxS),
    maxPerHourBy: Object.fromEntries([...$("providers").querySelectorAll("input[data-limit]")].map((input) => {
      const v = Number(input.value);
      const id = input.dataset.limit;
      return [id, Number.isFinite(v) && v >= 1 ? Math.round(v) : DEFAULT_SETTINGS.maxPerHourBy[id]];
    })),
    foreground: $("foreground").checked,
  });
  say("Salvo.");
}

async function showStatus() {
  const { runtime } = await chrome.storage.local.get("runtime");
  const settings = await loadSettings();
  if (!runtime) {
    $("status").textContent = "Ainda não rodou. Configure o token e salve.";
    return;
  }
  const paused = Object.entries(runtime.paused || {})
    .map(([p, v]) => `${p} desde ${when(v.since)} (aba ${v.tabId})`).join("; ") || "nenhuma";
  const jobs = Object.entries(runtime.lastJobs || {});
  const jobLines = jobs.length
    ? jobs.map(([p, j]) => `  ${PROVIDERS[p]?.label ?? p}: ${j.id} ${j.outcome} em ${when(j.at)}`)
    : [`  ${runtime.lastJob ? `${runtime.lastJob.id} ${runtime.lastJob.outcome} em ${when(runtime.lastJob.at)}` : "—"}`];
  $("status").textContent = [
    `Identificador desta extensão: ${await consumerId()}`,
    `Última consulta à ponte: ${when(runtime.lastPollAt)}`,
    "Último job de cada programa:",
    ...jobLines,
    "Buscas na última hora:",
    ...Object.entries(PROVIDERS).map(([p, info]) => {
      const used = ((runtime.pageTimesBy || {})[p] || []).filter((t) => Date.now() - t < 3_600_000).length;
      const until = (runtime.limitedUntil || {})[p];
      const stop = until && until > Date.now() ? ` · parada pelo teto até ${new Date(until).toLocaleTimeString("pt-BR")}` : "";
      return `  ${info.label}: ${used}/${hourLimit(settings, p)}${stop}`;
    }),
    `Concluídos ${runtime.counters?.done ?? 0} · falhas ${runtime.counters?.failed ?? 0} · bloqueios ${runtime.counters?.blocked ?? 0}`,
    `Pausas: ${paused}`,
    `Último erro: ${runtime.lastError ? `${when(runtime.lastError.at)} — ${runtime.lastError.message}` : "—"}`,
  ].join("\n");
}

$("save").addEventListener("click", save);
$("resume").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "resume" });
  say("Pausas removidas.");
  showStatus();
});
$("health").addEventListener("click", async () => {
  const r = await chrome.runtime.sendMessage({ type: "health" });
  say(r && r.ok ? `Ponte ok: aguardando ${JSON.stringify(r.body.waiting)}` : `Ponte inacessível: ${r && r.error}`);
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.runtime) showStatus();
});

fill();
showStatus();
