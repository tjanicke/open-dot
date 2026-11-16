/* OpenDOT Umami Analytics */
(function () {
    if (document.querySelector(
        'script[data-website-id="e0086da3-e43e-44f4-88f8-4e2f6d505dd6"]'
    )) return;

    const script = document.createElement("script");
    script.src = "https://collect.open-dot.org/script.js";
    script.async = true;
    script.setAttribute("data-website-id", "e0086da3-e43e-44f4-88f8-4e2f6d505dd6");
    script.setAttribute("data-host-url", "https://collect.open-dot.org");
    script.setAttribute("data-domains", "tollselections.open-dot.org");
    script.setAttribute("data-exclude-search", "true");
    script.setAttribute("data-exclude-hash", "true");
    document.head.appendChild(script);
})();
