/* OpenDOT Umami Analytics */
(function () {
    if (document.querySelector(
        'script[data-website-id="7b996f33-6074-4a9c-91b9-4602b2a1464c"]'
    )) return;

    const script = document.createElement("script");
    script.src = "https://collect.open-dot.org/script.js";
    script.async = true;
    script.setAttribute("data-website-id", "7b996f33-6074-4a9c-91b9-4602b2a1464c");
    script.setAttribute("data-host-url", "https://collect.open-dot.org");
    script.setAttribute("data-domains", "selections.open-dot.org");
    script.setAttribute("data-exclude-search", "true");
    script.setAttribute("data-exclude-hash", "true");
    document.head.appendChild(script);
})();
