// Content script isolado: recebe o que o hook.js capturou e repassa ao
// background; também diz se a página é a tela de bloqueio do anti-bot.
(() => {
  const TAG = "miles-fetcher";

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.source !== TAG) return;
    const { url, status, body } = event.data;
    chrome.runtime.sendMessage({ type: "captured", url, status, body }).catch(() => {});
  });

  // Tela do Akamai da Azul: "Ops! Só um momento. Identificamos um comportamento
  // incomum vindo do seu IP. O acesso foi limitado momentaneamente."
  const BLOCK_PATTERNS = [/comportamento incomum/i, /acesso foi limitado/i, /^\s*access denied/im];

  function report() {
    const text = (document.body && document.body.innerText) || "";
    const blocked = BLOCK_PATTERNS.some((re) => re.test(text.slice(0, 4000)));
    chrome.runtime.sendMessage({ type: blocked ? "blocked" : "page-ok", url: location.href }).catch(() => {});
  }

  const later = () => setTimeout(report, 2000);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", later, { once: true });
  else later();
})();
