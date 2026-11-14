// Laço do worker: pede um job à ponte local (long-poll), abre a URL de busca numa
// aba, espera o hook.js capturar a resposta da API de disponibilidade, devolve o
// JSON cru à ponte e fecha a aba. Um job por vez; entre duas buscas da mesma
// companhia, um intervalo aleatório (cada site tem seu próprio ritmo).
//
// Bloqueio anti-bot: avisa a ponte (o job falha), deixa a aba aberta, pausa o
// provider e notifica. Quando a pessoa resolve e a página carrega normal na
// mesma aba, o provider volta sozinho (ou pelo botão "Retomar" nas opções).
//
// O service worker do MV3 pode ser descarregado a qualquer hora: o que precisa
// sobreviver fica em chrome.storage.local, e um alarme a cada 30 s religa o laço.
import {
  EXTENSION_VERSION, PROVIDERS, bridgeUrlAllowed, jobUrlAllowed, loadSettings,
} from "./config.js";

const ALARM = "miles-tick";
const RUNTIME_KEY = "runtime";
const POLL_WAIT_S = 20; // < 30 s de ociosidade do service worker

let looping = false;
const waiters = new Map(); // tabId → { capture, resolve }

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ── Estado persistente ────────────────────────────────────────────────────
async function loadRuntime() {
  const { [RUNTIME_KEY]: runtime } = await chrome.storage.local.get(RUNTIME_KEY);
  const merged = {
    paused: {},        // provider → { since, tabId, url }
    nextAllowedAt: {}, // provider → ms: ritmo entre buscas da mesma companhia
    pageTimes: [],     // ms das buscas da última hora
    lastPollAt: null,
    lastJob: null,     // { id, provider, url, at, outcome }
    lastError: null,   // { at, message }
    counters: { done: 0, failed: 0, blocked: 0 },
    ...(runtime || {}),
  };
  // 0.1.x guardava um número só.
  if (typeof merged.nextAllowedAt !== "object" || merged.nextAllowedAt === null) merged.nextAllowedAt = {};
  return merged;
}

async function saveRuntime(runtime) {
  await chrome.storage.local.set({ [RUNTIME_KEY]: runtime });
}

// ── Ponte ─────────────────────────────────────────────────────────────────
async function bridge(settings, method, path, body) {
  if (!bridgeUrlAllowed(settings.bridgeUrl)) {
    throw new Error("URL da ponte recusada: use https (http só em 127.0.0.1/localhost)");
  }
  const response = await fetch(settings.bridgeUrl.replace(/\/+$/, "") + path, {
    method,
    headers: { Authorization: `Bearer ${settings.token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 300);
    throw new Error(`${method} ${path}: HTTP ${response.status} ${detail}`);
  }
  return response.json();
}

// ── Mensagens das abas ────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender) => {
  const tabId = sender.tab && sender.tab.id;
  if (tabId == null || !message) return;
  const waiter = waiters.get(tabId);
  if (message.type === "captured" && waiter && String(message.url).includes(waiter.capture)) {
    waiters.delete(tabId);
    waiter.resolve({ kind: "captured", url: message.url, status: message.status, body: message.body });
  } else if (message.type === "blocked" && waiter) {
    waiters.delete(tabId);
    waiter.resolve({ kind: "blocked", url: message.url });
  } else if (message.type === "page-ok") {
    resumeIfBlockedTab(tabId).catch(() => {});
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const waiter = waiters.get(tabId);
  if (waiter) {
    waiters.delete(tabId);
    waiter.resolve({ kind: "closed" });
  }
});

async function resumeIfBlockedTab(tabId) {
  const runtime = await loadRuntime();
  const providers = Object.keys(runtime.paused).filter((p) => runtime.paused[p].tabId === tabId);
  if (!providers.length) return;
  for (const p of providers) delete runtime.paused[p];
  await saveRuntime(runtime);
  notify(`resumed:${tabId}`, "Miles Fetcher retomado", `Verificação resolvida: ${providers.join(", ")} volta à fila.`);
  setTimeout(() => chrome.tabs.remove(tabId).catch(() => {}), 3000);
  loop();
}

// ── Avisos ────────────────────────────────────────────────────────────────
function notify(id, title, message) {
  chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
    priority: 2,
    requireInteraction: id.startsWith("blocked:"),
  }, () => void chrome.runtime.lastError);
}

chrome.notifications.onClicked.addListener(async (id) => {
  if (!id.startsWith("blocked:")) return;
  const runtime = await loadRuntime();
  const entry = runtime.paused[id.slice("blocked:".length)];
  if (!entry) return;
  const tab = await chrome.tabs.update(entry.tabId, { active: true }).catch(() => null);
  if (tab) await chrome.windows.update(tab.windowId, { focused: true });
});

// ── Job ───────────────────────────────────────────────────────────────────
function randomDelayMs(settings) {
  const low = Math.max(0, Number(settings.delayMinS) || 0);
  const high = Math.max(low, Number(settings.delayMaxS) || 0);
  return 1000 * (low + Math.random() * (high - low));
}

async function openAndCapture(settings, job) {
  const provider = PROVIDERS[job.provider];
  // Abre em branco, registra a espera e só então navega: nenhuma resposta escapa.
  const tab = await chrome.tabs.create({ url: "about:blank", active: Boolean(settings.foreground) });
  const outcome = await new Promise((resolve) => {
    const timer = setTimeout(() => {
      waiters.delete(tab.id);
      resolve({ kind: "timeout" });
    }, provider.pageTimeoutMs);
    waiters.set(tab.id, {
      capture: job.capture,
      resolve: (value) => {
        clearTimeout(timer);
        resolve(value);
      },
    });
    chrome.tabs.update(tab.id, { url: job.url }).catch((error) => {
      waiters.delete(tab.id);
      clearTimeout(timer);
      resolve({ kind: "error", message: String(error) });
    });
  });
  return { tab, outcome };
}

async function processJob(settings, runtime, job) {
  const now = Date.now();
  runtime.pageTimes.push(now);
  runtime.nextAllowedAt[job.provider] = now + randomDelayMs(settings);
  runtime.lastJob = { id: job.id, provider: job.provider, url: job.url, at: now, outcome: "running" };
  await saveRuntime(runtime);

  if (!jobUrlAllowed(job)) {
    const message = `URL fora do site de ${job.provider}: ${String(job.url).slice(0, 200)}`;
    await bridge(settings, "POST", `/jobs/${job.id}/failed`, { error: message }).catch(() => {});
    runtime.lastJob.outcome = "failed";
    runtime.lastError = { at: Date.now(), message };
    runtime.counters.failed += 1;
    return;
  }

  const { tab, outcome } = await openAndCapture(settings, job);
  let closeTab = true;
  try {
    if (outcome.kind === "captured" && outcome.status < 400) {
      await bridge(settings, "POST", `/jobs/${job.id}/result`, {
        url: outcome.url,
        payload: outcome.body,
        captured_at: new Date().toISOString(),
        extension_version: EXTENSION_VERSION,
      });
      runtime.lastJob.outcome = "done";
      runtime.counters.done += 1;
    } else if (outcome.kind === "blocked") {
      closeTab = false;
      runtime.paused[job.provider] = { since: Date.now(), tabId: tab.id, url: outcome.url };
      runtime.lastJob.outcome = "blocked";
      runtime.counters.blocked += 1;
      await bridge(settings, "POST", `/jobs/${job.id}/blocked`, { url: outcome.url }).catch(() => {});
      notify(`blocked:${job.provider}`, `Verificação em ${PROVIDERS[job.provider].label}`,
        "Resolva na aba aberta (recarregue quando o site liberar). A fila volta sozinha depois.");
    } else {
      const message = {
        captured: `a API respondeu HTTP ${outcome.status}`,
        timeout: `a resposta de disponibilidade não chegou em ${PROVIDERS[job.provider].pageTimeoutMs / 1000} s`,
        closed: "a aba foi fechada antes da resposta",
        error: outcome.message,
      }[outcome.kind] || outcome.kind;
      runtime.lastJob.outcome = "failed";
      runtime.lastError = { at: Date.now(), message: `job ${job.id}: ${message}` };
      runtime.counters.failed += 1;
      await bridge(settings, "POST", `/jobs/${job.id}/failed`, { error: message }).catch(() => {});
    }
  } finally {
    if (closeTab) await chrome.tabs.remove(tab.id).catch(() => {});
  }
}

// ── Laço ──────────────────────────────────────────────────────────────────
async function loop() {
  if (looping) return;
  looping = true;
  try {
    for (;;) {
      const settings = await loadSettings();
      if (!settings.enabled || !settings.token) break;
      const runtime = await loadRuntime();
      const now = Date.now();
      runtime.pageTimes = runtime.pageTimes.filter((t) => now - t < 3_600_000);

      if (runtime.pageTimes.length >= settings.maxPerHour) {
        runtime.lastError = { at: now, message: `limite de ${settings.maxPerHour} buscas/hora atingido` };
        await saveRuntime(runtime);
        break; // o alarme tenta de novo
      }
      const active = settings.providers.filter((p) => PROVIDERS[p] && !runtime.paused[p]);
      if (!active.length) break;
      const providers = active.filter((p) => now >= (runtime.nextAllowedAt[p] || 0));
      if (!providers.length) {
        const nextAt = Math.min(...active.map((p) => runtime.nextAllowedAt[p] || 0));
        await sleep(Math.min(Math.max(nextAt - now, 500), 20_000));
        continue;
      }

      let job = null;
      try {
        for (const provider of providers) {
          const wait = providers.length > 1 ? 5 : POLL_WAIT_S;
          job = await bridge(settings, "GET", `/jobs/next?provider=${encodeURIComponent(provider)}&wait=${wait}`);
          runtime.lastPollAt = Date.now();
          if (job) break;
        }
      } catch (error) {
        runtime.lastError = { at: Date.now(), message: `ponte: ${error.message || error}` };
        await saveRuntime(runtime);
        break; // ponte fora do ar: o alarme tenta de novo em 30 s
      }
      if (!job) {
        await saveRuntime(runtime);
        continue;
      }
      try {
        await processJob(settings, runtime, job);
      } catch (error) {
        runtime.lastError = { at: Date.now(), message: `job ${job.id}: ${error.message || error}` };
      }
      await saveRuntime(runtime);
    }
  } finally {
    looping = false;
  }
}

function ensureAlarm() {
  chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
}

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
  chrome.runtime.openOptionsPage().catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
  loop();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) loop();
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.settings) loop();
});
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

// Mensagens da página de opções.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !String(sender.url || "").startsWith(chrome.runtime.getURL(""))) return;
  if (message.type === "resume") {
    loadRuntime().then(async (runtime) => {
      runtime.paused = {};
      runtime.lastError = null;
      await saveRuntime(runtime);
      loop();
      sendResponse({ ok: true });
    });
    return true;
  }
  if (message.type === "health") {
    loadSettings().then(async (settings) => {
      try {
        if (!bridgeUrlAllowed(settings.bridgeUrl)) throw new Error("URL da ponte recusada");
        const r = await fetch(settings.bridgeUrl.replace(/\/+$/, "") + "/health");
        sendResponse({ ok: r.ok, body: await r.json() });
      } catch (error) {
        sendResponse({ ok: false, error: String(error.message || error) });
      }
    });
    return true;
  }
});

ensureAlarm();
loop();
