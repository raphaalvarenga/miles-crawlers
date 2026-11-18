// Roda no mundo da PÁGINA (world: MAIN), antes dos scripts do site: embrulha
// fetch e XMLHttpRequest e repassa ao relay.js o corpo JSON das respostas de
// disponibilidade. Não altera requisição nem resposta: só lê uma cópia.
(() => {
  if (window.__milesFetcherHook) return;
  window.__milesFetcherHook = true;

  // Mantenha em sincronia com o `capture` de cada provider em crawler/src/worker/extension_bridge.py.
  const FRAGMENTS = [
    "/tudoazul/reservation/availability/",          // Azul (tudoazul_parser.py)
    "/bff/air-offers/v2/offers/search/redemption",  // LATAM (latam_parser.py)
    "/v1/airlines/search?",                         // Smiles (smiles_parser.py)
  ];
  const TAG = "miles-fetcher";

  const matches = (url) => typeof url === "string" && FRAGMENTS.some((f) => url.includes(f));

  const emit = (url, status, text) => {
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      return;
    }
    window.postMessage({ source: TAG, url, status, body }, window.location.origin);
  };

  const originalFetch = window.fetch;
  window.fetch = function (input, init) {
    const promise = originalFetch.apply(this, arguments);
    promise.then((response) => {
      try {
        const url = response.url || (typeof input === "string" ? input : input && input.url);
        if (matches(url)) {
          response.clone().text().then((text) => emit(url, response.status, text)).catch(() => {});
        }
      } catch {}
    }).catch(() => {});
    return promise;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__milesUrl = String(url);
    return originalOpen.apply(this, arguments);
  };

  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    if (matches(this.__milesUrl)) {
      this.addEventListener("load", () => {
        try {
          const url = this.responseURL || this.__milesUrl;
          let text = null;
          if (this.responseType === "" || this.responseType === "text") text = this.responseText;
          else if (this.responseType === "json") text = JSON.stringify(this.response);
          if (text) emit(url, this.status, text);
        } catch {}
      });
    }
    return originalSend.apply(this, arguments);
  };
})();
