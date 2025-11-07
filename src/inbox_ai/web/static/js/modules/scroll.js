export function installScrollRestore({ forms, storageKey }) {
    if (!forms || typeof storageKey !== "string") {
        return;
    }

    forms.forEach((form) => {
        if (form.hasAttribute("data-scroll-restore-bound")) {
            return;
        }
        form.setAttribute("data-scroll-restore-bound", "true");
        form.addEventListener("submit", () => {
            try {
                const position = {
                    x: window.pageXOffset || document.documentElement.scrollLeft || 0,
                    y: window.pageYOffset || document.documentElement.scrollTop || 0,
                };
                sessionStorage.setItem(storageKey, JSON.stringify(position));
            } catch (error) {
                console.warn("Unable to persist scroll position", error);
            }
        });
    });

    try {
        const stored = sessionStorage.getItem(storageKey);
        if (!stored) {
            return;
        }
        sessionStorage.removeItem(storageKey);
        const parsed = JSON.parse(stored);
        if (
            parsed &&
            Number.isFinite(parsed.x) &&
            Number.isFinite(parsed.y)
        ) {
            window.scrollTo({ left: parsed.x, top: parsed.y, behavior: "auto" });
        }
    } catch (error) {
        console.warn("Unable to restore scroll position", error);
    }
}

export default installScrollRestore;
