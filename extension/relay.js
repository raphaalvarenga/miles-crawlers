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

  // Erro do próprio site, sem verificação para resolver: a busca não vai sair.
  // Azul: modal "Ops! Tivemos um problema · Infelizmente não foi possível concluir
  // sua solicitação [...] tente novamente em alguns instantes." (aparece quando o
  // site limita o acesso depois de muitas buscas seguidas).
  const SITE_ERROR_PATTERNS = [
    /tivemos um problema/i,
    /n[ãa]o foi poss[íi]vel concluir sua solicita[çc][ãa]o/i,
  ];

  function pageText() {
    return `${document.title}\n${(document.body && document.body.innerText) || ""}`.slice(0, 4000);
  }

  function pageState() {
    const text = pageText();
    if (BLOCK_PATTERNS.some((re) => re.test(text))) return "blocked";
    if (SITE_ERROR_PATTERNS.some((re) => re.test(text))) return "site-error";
    return "page-ok";
  }

  // Avisa o background a cada mudança de estado. A verificação pode aparecer depois
  // que a página monta (SPA) e sumir sem recarregar quando a pessoa resolve, então
  // a página é conferida por alguns minutos, não só uma vez.
  let last = null;
  function report() {
    const state = pageState();
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
