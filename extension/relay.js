// Content script isolado: recebe o que o hook.js capturou e repassa ao
// background; também diz se a página é a tela de verificação do anti-bot.
(() => {
  const TAG = "miles-fetcher";

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.source !== TAG) return;
    const { url, status, body } = event.data;
    chrome.runtime.sendMessage({ type: "captured", url, status, body }).catch(() => {});
  });

  const BLOCK_PATTERNS = [
    // Azul (Akamai): "Ops! Só um momento. Identificamos um comportamento incomum
    // vindo do seu IP. O acesso foi limitado momentaneamente."
    /comportamento incomum/i,
    /acesso foi limitado/i,
    /^\s*access denied/im,
    // Smiles: "Validação de segurança · Só um instante! Estamos fazendo uma rápida
    // validação de segurança [...] clique na caixa abaixo. Eu sou humano"
    /valida[çc][ãa]o de seguran[çc]a/i,
    /eu sou humano/i,
  ];

  function isBlocked() {
    const text = `${document.title}\n${(document.body && document.body.innerText) || ""}`;
    return BLOCK_PATTERNS.some((re) => re.test(text.slice(0, 4000)));
  }

  // Avisa o background a cada mudança de estado. A verificação pode aparecer depois
  // que a página monta (SPA) e sumir sem recarregar quando a pessoa resolve, então
  // a página é conferida por alguns minutos, não só uma vez.
  let last = null;
  function report() {
    const state = isBlocked() ? "blocked" : "page-ok";
    if (state === last) return;
    last = state;
    chrome.runtime.sendMessage({ type: state, url: location.href }).catch(() => {});
  }

  const CHECK_EVERY_MS = 3000;
  const CHECK_FOR_MS = 10 * 60 * 1000;
  function start() {
    setTimeout(report, 2000);
    const timer = setInterval(report, CHECK_EVERY_MS);
    setTimeout(() => clearInterval(timer), CHECK_FOR_MS);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
