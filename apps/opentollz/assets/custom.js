/* OpenDOT Umami Analytics */
(function () {
    if (document.querySelector(
        'script[data-website-id="c9b247da-2d87-48f7-8b97-8316f4b81c60"]'
    )) return;

    const script = document.createElement("script");
    script.src = "https://collect.open-dot.org/script.js";
    script.async = true;
    script.setAttribute("data-website-id", "c9b247da-2d87-48f7-8b97-8316f4b81c60");
    script.setAttribute("data-host-url", "https://collect.open-dot.org");
    script.setAttribute("data-domains", "tolls.open-dot.org");
    script.setAttribute("data-exclude-search", "true");
    script.setAttribute("data-exclude-hash", "true");
    document.head.appendChild(script);
})();
