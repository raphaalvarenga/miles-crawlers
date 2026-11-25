export const EXTENSION_VERSION = chrome.runtime.getManifest().version;

export const DEFAULT_SETTINGS = {
  enabled: true,
  bridgeUrl: "http://127.0.0.1:8765",
  token: "",
  providers: ["smiles", "azul", "latam"],
  delayMinS: 8,     // intervalo aleatório entre buscas da mesma companhia
  delayMaxS: 20,
  // Teto de páginas abertas por hora, separado por companhia: uma rodada grande da Smiles
  // não pode gastar a cota da Azul (antes era um teto só para o Chrome todo).
  maxPerHourBy: { smiles: 60, azul: 40, latam: 40 },
  foreground: false // abrir a aba da busca em primeiro plano
};

/** Teto por hora daquela companhia (o padrão cobre companhia sem valor salvo). */
export function hourLimit(settings, provider) {
  const value = Number((settings.maxPerHourBy || {})[provider]);
  return Number.isFinite(value) && value >= 1 ? value : DEFAULT_SETTINGS.maxPerHourBy[provider] ?? 40;
}

// Por provider: de onde a URL do job pode vir e quanto esperar a resposta.
export const PROVIDERS = {
  smiles: {
    label: "Smiles",
    allowedHosts: ["www.smiles.com.br"],
    pageTimeoutMs: 60_000,
  },
  azul: {
    label: "Azul (TudoAzul)",
    allowedHosts: ["www.voeazul.com.br"],
    pageTimeoutMs: 60_000,
  },
  latam: {
    label: "LATAM (LATAM Pass)",
    allowedHosts: ["www.latamairlines.com"],
    pageTimeoutMs: 60_000,
  },
};

export async function loadSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  const merged = { ...DEFAULT_SETTINGS, ...(settings || {}) };
  merged.maxPerHourBy = { ...DEFAULT_SETTINGS.maxPerHourBy, ...(settings?.maxPerHourBy || {}) };
  delete merged.maxPerHour; // até 0.6.x: teto único, substituído pelo de cada companhia
  return merged;
}

export async function saveSettings(settings) {
  await chrome.storage.local.set({ settings });
}

// http só na própria máquina ou num IP de rede local (10/8, 172.16/12, 192.168/16): o token vai sem
// criptografia, então nunca por um endereço público.
export function isLocalHost(hostname) {
  if (["127.0.0.1", "localhost"].includes(hostname)) return true;
  const m = hostname.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return false;
  const [a, b, c, d] = m.slice(1).map(Number);
  if ([a, b, c, d].some((n) => n > 255)) return false;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

// A ponte só em https, ou http na máquina / na rede local.
export function bridgeUrlAllowed(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || (u.protocol === "http:" && isLocalHost(u.hostname));
  } catch {
    return false;
  }
}

// Padrão de permissão do Chrome para o endereço da ponte (sem porta: o padrão vale para todas).
// 127.0.0.1 e localhost já vêm no manifesto; os outros entram como permissão opcional.
export function bridgeOriginPattern(url) {
  const u = new URL(url);
  return `${u.protocol}//${u.hostname}/*`;
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
