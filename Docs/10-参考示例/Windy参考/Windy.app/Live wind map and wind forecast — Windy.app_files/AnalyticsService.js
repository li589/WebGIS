"use strict";
(self.webpackChunk = self.webpackChunk || []).push([
    [343], {
        3278: (__unused_webpack_module, __webpack_exports__, __webpack_require__) => {
            __webpack_require__.d(__webpack_exports__, {
                default: () => __WEBPACK_DEFAULT_EXPORT__
            });
            class AnalyticsService {
                constructor(e) {
                    this.userID = this.getOrCreateUserId(), this.amplitude = "function" == typeof e.logEvent ? e : e.amplitude, this.amplitude && this.amplitude.setUserId(this.userID), this.GTM = e.GTM, this.GTMProxy = e.GTMProxy ? e.GTMProxy : "https://t.windyapp.co/proxy/route/https/d3d3Lmdvb2dsZXRhZ21hbmFnZXIuY29t/Z3RtLmpzP2lkPUdUTS1URlI5RjQ3UA==", this.GTMInitialized = !1, this.useBackendLogs = !1 !== e.useBackendLogs, addEventListener("windyapp_site_analytics_refresh", e => {
                        this.initializeAnalytics()
                    })
                }
                isMobile() {
                    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
                }
                getOrCreateUserId() {
                    var e = "" != window.userID ? window.userID : localStorage.getItem("analyticsUserId");
                    return e || (e = `web-${(new Date).getTime()}_${Math.random().toString(36).substr(2,9)}`), localStorage.setItem("analyticsUserId", e), e
                }
                logAmplitudeEvent(e, t = {}) {
                    if (this.amplitude) {
                        try {
                            this.amplitude.track(e, t)
                        } catch (e) {}
                        return !0
                    }
                }
                logBackendEvent(e, t) {
                    if (!1 !== this.useBackendLogs) {
                        var a = {
                            eventName: e
                        };
                        null != t && (a.eventParams = t), fetch("/proxy/apiV9.php?method=analyticsLogEvent&userID=" + this.userID, {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/x-www-form-urlencoded"
                            },
                            body: "eventData=" + encodeURIComponent(JSON.stringify(a))
                        }).then(e => e.json()).catch(e => {})
                    }
                }
                logEvent(e, t, a = ["amplitude", "backend"]) {
                    return a.forEach(a => {
                        switch (a) {
                            case "amplitude":
                                this.logAmplitudeEvent(e, t);
                                break;
                            case "backend":
                                this.logBackendEvent(e, t)
                        }
                    }), !0
                }
                chooseVariant(e) {
                    const t = Math.random();
                    let a = 0;
                    return e.findIndex(e => (a += e.probability / 100, a > t))
                }
                chooseAndStoreVariant(e, t) {
                    const a = this.chooseVariant(t);
                    return localStorage.setItem(e, a), a
                }
                getVariant(e) {
                    return localStorage.getItem(e.id) ?? this.chooseAndStoreVariant(e.id, e.variants)
                }
                startTests(e, t) {
                    t.forEach(t => {
                        if (t.condition && "isMobile" === t.condition)
                            if (!isMobile()) return;
                        const a = this.getVariant(t),
                            r = t.variants[a].setAttributes;
                        switch (Object.keys(r).forEach(t => {
                                e.setAttribute(t, r[t])
                            }), t.type) {
                            case "href":
                                e.href = t.variants[a].href;
                                break;
                            case "onClick":
                                e.onClick = t.variants[a].onClick
                        }
                        e.addEventListener("click", () => {
                            this.pushToDataLayer({
                                event: "analyticsEvent",
                                eventCategory: "feature_flag",
                                eventAction: "experiment_view",
                                eventLabel: "analytics_service",
                                eventProperty: {
                                    exp_id: t.id,
                                    var_id: t.variants[a].eventName
                                },
                                eventValue: 0
                            })
                        })
                    })
                }
                doAction(e, t) {
                    switch (t.action) {
                        case "setVariable":
                            localStorage.setItem(t.name, t.value);
                            break;
                        case "unsetVariable":
                            localStorage.removeItem(t.name);
                            break;
                        case "sendEvent":
                            this.sendEvent(t.name);
                            break;
                        case "toggleDeferredEvent":
                            this.toggleDeferredEvent(t.name);
                            break;
                        case "sendDeferredEvents":
                            this.sendDeferredEvents(t.name);
                            break;
                        case "pushToDataLayer":
                            this.pushToDataLayer(t.value, t.preventDouble);
                            break;
                        case "initGTM":
                            this.initGTM()
                    }
                }
                setWaitingActions(e, t) {
                    const a = Date.now();
                    t.forEach(e => {
                        const t = setInterval(() => {
                            const r = document.querySelector(e.selector);
                            r ? (clearInterval(t), this.startActions(r, e.actions)) : Date.now() - a > 3e4 && clearInterval(t)
                        }, 1e3)
                    })
                }
                startActions(el, actions) {
                    actions.forEach(action => {
                        action && ("onClick" == action.type ? el.addEventListener("click", () => {
                            action.condition && !eval(action.condition) || this.doAction(el, action)
                        }) : this.doAction(el, action))
                    })
                }
                sendPurchaseAddToCartEvent() {
                    const e = {
                        referred_screen: localStorage.getItem("referred_screen2") || localStorage.getItem("referred_screen"),
                        buy_pro_screen_id: localStorage.getItem("buy_pro_screen_id2") || localStorage.getItem("buy_pro_screen_id"),
                        product_ids: localStorage.getItem("product_ids2") || localStorage.getItem("product_ids")
                    };
                    this.logEvent("purchase_addToCart", e, ["backend"])
                }
                sendPurchasePurchasedEvent() {
                    const e = localStorage.getItem("referred_screen2") || localStorage.getItem("referred_screen"),
                        t = localStorage.getItem("buy_pro_screen_id2") || localStorage.getItem("buy_pro_screen_id"),
                        a = localStorage.getItem("payment_method"),
                        r = localStorage.getItem("purchase_inapp_id");
                    if (!e && !t && !r) return;
                    const s = {
                        referred_screen: e,
                        buy_pro_screen_id: t,
                        purchase_inappID: a ? `${a}.${r}` : r
                    };
                    this.logEvent("purchase_purchased", s, ["backend"]), localStorage.removeItem("referred_screen"), localStorage.removeItem("referred_screen2"), localStorage.removeItem("buy_pro_screen_id"), localStorage.removeItem("buy_pro_screen_id2"), localStorage.removeItem("payment_method"), localStorage.removeItem("purchase_inapp_id")
                }
                sendEvent(e, t = {}) {
                    switch (e) {
                        case "purchase_addToCart":
                            this.sendPurchaseAddToCartEvent();
                            break;
                        case "purchase_purchased":
                            this.sendPurchasePurchasedEvent();
                            break;
                        default:
                            this.logEvent(e, t)
                    }
                }
                createDeferredEvent(e) {
                    const t = JSON.parse(localStorage.getItem("deferred_events")) || [];
                    t.indexOf(e) > -1 || (t.push(e), localStorage.setItem("deferred_events", JSON.stringify(t)))
                }
                deleteDeferredEvent(e) {
                    const t = JSON.parse(localStorage.getItem("deferred_events")) || [],
                        a = t.indexOf(e); - 1 != a && (t.splice(a, 1), localStorage.setItem("deferred_events", JSON.stringify(t)))
                }
                toggleDeferredEvent(e) {
                    -1 == (JSON.parse(localStorage.getItem("deferred_events")) || []).indexOf(e) ? this.createDeferredEvent(e) : this.deleteDeferredEvent(e)
                }
                sendDeferredEvents() {
                    const e = JSON.parse(localStorage.getItem("deferred_events")) || [];
                    if ((this.amplitude || this.useBackendLogs) && e.forEach(e => {
                            this.sendEvent(e)
                        }), e.length > 0) {
                        const t = e[0].split(".")[0],
                            a = {};
                        e.forEach(e => {
                            const [t, r, s] = e.split(".");
                            a[r] || (a[r] = []), a[r].push(s)
                        }), window.dataLayer.push({
                            event: "analyticsEvent",
                            eventCategory: "settings",
                            eventAction: "confirm",
                            eventLabel: t,
                            eventProperty: a,
                            eventValue: 0
                        })
                    }
                    localStorage.removeItem("deferred_events")
                }
                getCookie(e) {
                    var t = document.cookie.split("; ").map(e => e.split("=")).find(t => t[0] == e);
                    return t && t[1]
                }
                handleFbUserData() {
                    const e = JSON.stringify({
                            fbc: this.getCookie("_fbc"),
                            fbp: this.getCookie("_fbp"),
                            user_agent: navigator.userAgent,
                            ip: window.ip,
                            user_id: window.userID
                        }),
                        t = localStorage.getItem("fbDataSent");
                    t && t == e || (fetch("https://windyapp.co/v10/analytics/facebook/ads", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: e
                    }).then(e => e.json()).catch(e => {}), localStorage.setItem("fbDataSent", e))
                }
                handleUserData() {
                    this.handleFbUserData()
                }
                initializeAnalytics() {
                    this.handleUserData();
                    document.querySelectorAll("[data-analytics]").forEach(e => {
                        if (e.getAttribute("data-analytics-done")) return;
                        const t = JSON.parse(e.dataset.analytics);
                        t.tests && this.startTests(e, t.tests), t.actions && this.startActions(e, t.actions), t.waitingActions && this.setWaitingActions(e, t.waitingActions), e.setAttribute("data-analytics-done", !0)
                    })
                }
                updateJsonValues(e) {
                    const t = new URLSearchParams(window.location.search),
                        a = JSON.stringify(e).replace(/"(val|urlparam|ls):(.+?)"/g, (e, a, r) => "val" === a ? `"${document.querySelector(r).value}"` : "urlparam" === a ? `"${t.get(r)}"` : "ls" === a ? `"${localStorage.getItem(r)}"` : e);
                    return JSON.parse(a)
                }
                pushToDataLayer(e, t = !1) {
                    window.dataLayer || (window.dataLayer = []);
                    const a = this.updateJsonValues(e);
                    if (t) {
                        const e = "preventDoubleDataLayerValues",
                            t = JSON.parse(localStorage.getItem(e)) || [];
                        if (t.some(e => JSON.stringify(e) === JSON.stringify(a))) return;
                        t.push(a), localStorage.setItem(e, JSON.stringify(t))
                    }
                    window.dataLayer.push(a)
                }
                initGTM() {
                    this.GTMInitialized || null != window.google_tag_manager || (! function(e, t, a, r, s, n) {
                        e[r] = e[r] || [], e[r].push({
                            "gtm.start": (new Date).getTime(),
                            event: "gtm.js"
                        });
                        var o = t.getElementsByTagName(a)[0],
                            i = t.createElement(a);
                        i.async = !0, i.src = n + "?id=" + s, i.onerror = function() {
                            var e = t.createElement(a);
                            e.async = !0, e.src = "https://www.googletagmanager.com/gtm.js?id=" + s, o.parentNode.insertBefore(e, o)
                        }, o.parentNode.insertBefore(i, o)
                    }(window, document, "script", "dataLayer", this.GTM, this.GTMProxy), this.GTMInitialized = !0)
                }
            }
            const __WEBPACK_DEFAULT_EXPORT__ = AnalyticsService
        }
    },
    e => {
        var t, a = (t = 3278, e(e.s = t));
        window.AnalyticsService = a.default
    }
]);