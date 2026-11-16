
/* OpenDOT Umami Visitor Analytics — OpenBidz */
(function () {
    if (document.querySelector('script[data-website-id="5990ef73-687e-482e-8eaa-41baafaa256a"]')) {
        return;
    }

    const script = document.createElement("script");
    script.src = "https://collect.open-dot.org/script.js";
    script.async = true;

    script.setAttribute(
        "data-website-id",
        "5990ef73-687e-482e-8eaa-41baafaa256a"
    );

    script.setAttribute(
        "data-host-url",
        "https://collect.open-dot.org"
    );

    script.setAttribute(
        "data-domains",
        "bids.open-dot.org"
    );

    // Do not collect URL search parameters or fragments.
    script.setAttribute("data-exclude-search", "true");
    script.setAttribute("data-exclude-hash", "true");

    document.head.appendChild(script);
})();
