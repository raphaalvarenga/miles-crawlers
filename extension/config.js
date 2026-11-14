export const EXTENSION_VERSION = chrome.runtime.getManifest().version;

export const DEFAULT_SETTINGS = {
  enabled: true,
  bridgeUrl: "http://127.0.0.1:8765",
  token: "",
  providers: ["azul"],
  delayMinS: 8,     // intervalo aleatório entre buscas
  delayMaxS: 20,
  maxPerHour: 60,   // teto de páginas abertas por hora
  foreground: false // abrir a aba da busca em primeiro plano
};

// Por provider: de onde a URL do job pode vir e quanto esperar a resposta.
export const PROVIDERS = {
  azul: {
    label: "Azul (TudoAzul)",
    allowedHosts: ["www.voeazul.com.br"],
    pageTimeoutMs: 60_000,
  },
};

export async function loadSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

export async function saveSettings(settings) {
  await chrome.storage.local.set({ settings });
}

// A ponte só em https, ou http na própria máquina.
export function bridgeUrlAllowed(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || (u.protocol === "http:" && ["127.0.0.1", "localhost"].includes(u.hostname));
  } catch {
    return false;
  }
}

// A extensão só abre URLs https do site do provider do job.
export function jobUrlAllowed(job) {
  const provider = PROVIDERS[job && job.provider];
  if (!provider) return false;
  try {
    const u = new URL(job.url);
    return u.protocol === "https:" && provider.allowedHosts.includes(u.hostname);
  } catch {
    return false;
  }
}
