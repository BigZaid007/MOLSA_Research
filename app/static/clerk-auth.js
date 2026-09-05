(function () {
    const originalFetch = window.fetch.bind(window);

    function revealApp() {
        document.documentElement.classList.remove("clerk-booting");
    }

    function t(path, fallback) {
        const parts = path.split(".");
        let value = window.I18N;
        for (const part of parts) {
            value = value && value[part];
        }
        return value || fallback;
    }

    function loadScript(src, attrs) {
        return new Promise(function (resolve, reject) {
            const existing = document.querySelector('script[src="' + src + '"]');
            if (existing) {
                if (window.Clerk) {
                    resolve();
                    return;
                }
                existing.addEventListener("load", function () { resolve(); });
                existing.addEventListener("error", function () { reject(new Error("script")); });
                return;
            }
            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.crossOrigin = "anonymous";
            if (attrs) {
                Object.keys(attrs).forEach(function (key) {
                    script.setAttribute(key, attrs[key]);
                });
            }
            script.onload = function () { resolve(); };
            script.onerror = function () { reject(new Error("Failed to load " + src)); };
            document.head.appendChild(script);
        });
    }

    function waitForClerk(ms) {
        const deadline = Date.now() + ms;
        return new Promise(function (resolve) {
            (function tick() {
                if (window.Clerk) {
                    resolve(window.Clerk);
                    return;
                }
                if (Date.now() >= deadline) {
                    resolve(null);
                    return;
                }
                setTimeout(tick, 50);
            })();
        });
    }

    async function ensureClerk() {
        if (window.Clerk) return window.Clerk;
        const pk = window.CLERK_PUBLISHABLE_KEY;
        if (!pk) return null;
        const host = window.CLERK_FRONTEND_HOST || "";
        const fapiJs = host ? "https://" + host + "/npm/@clerk/clerk-js@5/dist/clerk.browser.js" : "";
        const cdnJs = "https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js";
        if (fapiJs) {
            try {
                await loadScript(fapiJs, { "data-clerk-publishable-key": pk });
            } catch (error) { /* fall through */ }
        }
        if (!window.Clerk) {
            await loadScript(cdnJs, { "data-clerk-publishable-key": pk });
        }
        return waitForClerk(4000);
    }

    function tokenWithTimeout(ms) {
        if (!window.Clerk || !Clerk.session || !Clerk.session.getToken) {
            return Promise.resolve(null);
        }
        return Promise.race([
            Clerk.session.getToken(),
            new Promise(function (resolve) {
                setTimeout(function () { resolve(null); }, ms);
            }),
        ]).catch(function () { return null; });
    }

    function isSameOriginApi(input) {
        const raw = typeof input === "string" ? input : (input && input.url) || "";
        if (!raw) return false;
        try {
            const url = new URL(raw, window.location.origin);
            return url.origin === window.location.origin && url.pathname.startsWith("/api/");
        } catch (error) {
            return raw.startsWith("/api/");
        }
    }

    window.fetch = async function (input, init) {
        if (!isSameOriginApi(input)) {
            return originalFetch(input, init);
        }
        const options = Object.assign({}, init || {});
        const headers = new Headers(options.headers || undefined);
        const token = await tokenWithTimeout(1500);
        if (token && !headers.has("Authorization")) {
            headers.set("Authorization", "Bearer " + token);
        }
        options.headers = headers;
        options.credentials = options.credentials || "same-origin";
        return originalFetch(input, options);
    };

    async function establishSession() {
        const token = await tokenWithTimeout(4000);
        if (!token) return false;
        const response = await originalFetch("/api/session", {
            method: "POST",
            headers: { Authorization: "Bearer " + token },
            credentials: "same-origin",
        });
        return response.ok;
    }

    async function clearAppSession() {
        try {
            await originalFetch("/api/logout", { method: "POST", credentials: "same-origin" });
        } catch (error) { /* ignore */ }
        if (window.Clerk && Clerk.signOut) {
            try { await Clerk.signOut(); } catch (error) { /* ignore */ }
        }
    }

    function setFormBusy(busy) {
        const button = document.getElementById("login-submit");
        const error = document.getElementById("login-error");
        if (button) {
            button.disabled = busy;
            button.textContent = busy ? t("auth.signingIn", "Signing in…") : t("auth.signIn", "Sign in");
        }
        if (error && busy) error.hidden = true;
    }

    function showFormError(message) {
        const error = document.getElementById("login-error");
        if (!error) return;
        error.hidden = false;
        error.textContent = message || t("auth.invalid", "Incorrect username or password.");
    }

    async function signInWithPassword(username, password) {
        const client = Clerk.client;
        if (!client || !client.signIn) {
            throw new Error(t("auth.clerkLoadError", "Could not load sign-in."));
        }
        const attempt = await client.signIn.create({
            identifier: username,
            password: password,
        });
        if (attempt.status === "complete" && attempt.createdSessionId) {
            await Clerk.setActive({ session: attempt.createdSessionId });
            return true;
        }
        throw new Error(t("auth.invalid", "Incorrect username or password."));
    }

    function bindLoginForm(safeNext) {
        const form = document.getElementById("app-login-form");
        if (!form) return;
        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            const username = (document.getElementById("login-username") || {}).value || "";
            const password = (document.getElementById("login-password") || {}).value || "";
            if (!username.trim() || !password) {
                showFormError(t("auth.invalid", "Incorrect username or password."));
                return;
            }
            setFormBusy(true);
            try {
                await signInWithPassword(username.trim(), password);
                const ok = await establishSession();
                if (!ok) throw new Error(t("auth.invalid", "Incorrect username or password."));
                window.location.replace(safeNext);
            } catch (error) {
                const message = (error && (error.errors && error.errors[0] && error.errors[0].longMessage))
                    || (error && error.message)
                    || t("auth.invalid", "Incorrect username or password.");
                showFormError(message);
                setFormBusy(false);
            }
        });
    }

    function bindSignOut() {
        document.querySelectorAll("[data-app-sign-out]").forEach(function (button) {
            button.addEventListener("click", async function (event) {
                event.preventDefault();
                button.disabled = true;
                await clearAppSession();
                window.location.replace("/sign-in");
            });
        });
    }

    async function bootClerk() {
        const page = document.body.dataset.clerkPage || "";
        const params = new URLSearchParams(window.location.search);
        const next = params.get("next") || "/";
        const safeNext = next.startsWith("/") && next !== "/sign-in" ? next : "/";

        bindSignOut();

        if (!window.CLERK_PUBLISHABLE_KEY) {
            if (page === "sign-in") {
                showFormError(t("auth.clerkLoadError", "Could not load sign-in."));
            }
            revealApp();
            return;
        }

        let clerk;
        try {
            clerk = await ensureClerk();
            if (clerk) {
                await clerk.load();
            }
        } catch (error) {
            clerk = null;
        }

        if (!clerk) {
            if (page === "sign-in") {
                showFormError(t("auth.clerkLoadError", "Could not load sign-in."));
            }
            revealApp();
            return;
        }

        if (page === "sign-in") {
            if (clerk.isSignedIn) {
                try { await clerk.signOut(); } catch (error) { /* leftover browser session */ }
            }
            bindLoginForm(safeNext);
        }

        revealApp();
    }

    window.addEventListener("DOMContentLoaded", function () {
        bootClerk().catch(function () {
            revealApp();
        });
    });
})();
