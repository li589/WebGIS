import {
    Bounds as e,
    DivIcon as t,
    DomUtil as n,
    GridLayer as r,
    Icon as i,
    KML as a,
    LatLng as o,
    LatLngBounds as s,
    LatLngGraticule as c,
    LeafletGlMap as l,
    LngLat as u,
    LngLatBounds as d,
    Marker as f,
    MercatorCoordinate as p,
    OverscaledTileID as m,
    Point as h,
    ReferenceCountedCache as g,
    TileCache as _,
    TileLayer as v,
    addProtocol as ee,
    falseFn as te,
    getCoordsKey as y,
    isWebGL2 as ne,
    wrappedCoords as re
} from "@leafletGl";
var ie = Object.defineProperty,
    b = (e, t) => {
        let n = {};
        for (var r in e) ie(n, r, {
            get: e[r],
            enumerable: !0
        });
        return t || ie(n, Symbol.toStringTag, {
            value: `Module`
        }), n
    },
    ae = b({
        adjustCssValue: () => oe,
        defaultPluginsAttachPoint: () => le,
        replaceClass: () => ce,
        toggleClass: () => se
    });
const oe = (e, t, n = -1 / 0, r = 1 / 0) => {
        let i = getComputedStyle(document.documentElement).getPropertyValue(e),
            a = i ? parseInt(i.replace(/^\D*(\d+)\D*.*$/, `$1`)) : 0;
        a >= n && a <= r && document.documentElement.style.setProperty(e, ` ${a + t}px`)
    },
    se = (e, t, n) => e.classList[t ? `add` : `remove`](n),
    ce = (e, t, n = document.body) => {
        let r = n.className;
        e.test(r) ? n.className = r.replace(e, t) : n.classList.add(t)
    },
    le = `[data-plugin="plugins"]`;
var ue = b({
    device: () => pe,
    platform: () => fe
});
const de = window.navigator.userAgent,
    fe = /android/i.test(de) ? `android` : /(iPhone|iPod|iPad)/i.test(de) ? `ios` : `desktop`,
    pe = W.detectedDevice;
{
    let e = () => {
        document.body.classList.add(`platform-${fe}`);
        let e = () => document.documentElement.style.setProperty(`--vh`, `${window.innerHeight / 100}px`);
        window.addEventListener(`resize`, e), window.addEventListener(`orientationchange`, e), e()
    };
    document.readyState === `complete` ? e() : window.addEventListener(`load`, e)
}
var me = b({
    airPointProducts: () => Pe,
    airQualityProducts: () => ke,
    assets: () => xe,
    autoOpenArticleImportance: () => Ge,
    device: () => ve,
    globalPointProducts: () => je,
    globalProducts: () => Ee,
    iconsDir: () => Ce,
    isDesktop: () => Ie,
    isDesktopOrTablet: () => Le,
    isMobile: () => x,
    isMobileOrTablet: () => S,
    isRetina: () => Re,
    isTablet: () => Fe,
    isolinesType: () => He,
    levels: () => Se,
    levelsData: () => ze,
    localPointProducts: () => Ae,
    localProducts: () => Te,
    maxFavPoisDesktop: () => 7,
    overlays: () => we,
    platform: () => _e,
    pluginsLocation: () => Ue,
    poiGroups: () => Ve,
    pointProducts: () => Ne,
    pois: () => Be,
    pollenProducts: () => We,
    products: () => Me,
    seaProducts: () => De,
    server: () => be,
    supportedLanguages: () => ye,
    target: () => ge,
    version: () => he,
    waveProducts: () => Oe
});
const he = `50.1.2`,
    ge = `index`,
    _e = fe,
    ve = pe,
    ye = `en.zh-TW.zh.ja.fr.ko.it.ru.nl.cs.tr.pl.sv.fi.ro.el.hu.hr.ca.da.ar.fa.hi.ta.sk.uk.bg.he.is.lt.et.vi.sl.sr.id.th.sq.pt.nb.es.de.bn`.split(`.`),
    be = `https://ims.windy.com`,
    xe = `v/50.1.2.ind.cd28`,
    Se = [`surface`, `100m`, `975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`, `10h`],
    Ce = `/img/icons7`,
    we = `radar.satellite.wind.gust.gustAccu.turbulence.icing.rain.rainAccu.snowAccu.snowcover.ptype.thunder.temp.dewpoint.rh.deg0.wetbulbtemp.solarpower.uvindex.clouds.hclouds.mclouds.lclouds.fog.cloudtop.cbase.visibility.cape.ccl.waves.swell1.swell2.swell3.wwaves.sst.currents.currentsTide.wavePower.aqi.no2.pm2p5.aod550.gtco3.tcso2.go3.cosc.dustsm.pressure.efiTemp.efiWind.efiRain.capAlerts.avalancheDanger.soilMoisture40.soilMoisture100.moistureAnom40.moistureAnom100.drought40.drought100.fwi.dfm10h.heatmaps.topoMap.hurricanes`.split(`.`),
    Te = `nems.namConus.namHawaii.namAlaska.iconEu.iconD2.arome.aromeAntilles.aromeFrance.aromeReunion.canHrdps.canRdwpsWaves.camsEu.czeAladin.iconEuWaves.hrrrAlaska.hrrrConus.bomAccess.bomAccessAd.bomAccessBn.bomAccessDn.bomAccessNq.bomAccessPh.bomAccessSy.bomAccessVt.ukv.jmaMsm.jmaCwmWaves`.split(`.`),
    Ee = [`gfs`, `ecmwf`, `ecmwfAnalysis`, `radar`, `ecmwfWaves`, `gfsWaves`, `icon`, `capAlerts`, `avalancheDanger`, `cams`, `efi`, `satellite`, `cmems`, `drought`, `fireDanger`, `activeFires`, `topoMap`],
    De = [`ecmwfWaves`, `gfsWaves`, `iconEuWaves`, `canRdwpsWaves`, `cmems`, `jmaCwmWaves`],
    Oe = [`ecmwfWaves`, `gfsWaves`, `iconEuWaves`, `jmaCwmWaves`, `canRdwpsWaves`],
    ke = [`cams`, `camsEu`],
    Ae = `namConus.namHawaii.namAlaska.iconD2.iconEu.iconEuWaves.arome.aromeAntilles.aromeFrance.aromeReunion.canHrdps.canRdwpsWaves.czeAladin.hrrrAlaska.hrrrConus.bomAccess.bomAccessAd.bomAccessBn.bomAccessDn.bomAccessNq.bomAccessPh.bomAccessSy.bomAccessVt.ukv.jmaMsm.jmaCwmWaves.camsEu`.split(`.`),
    je = [`gfs`, `ecmwf`, `icon`, `mblue`],
    Me = [...Ee, ...Te, ...ke, `mblue`],
    Ne = [...je, ...Ae],
    Pe = Ne.filter(e => !Oe.includes(e) && !ke.includes(e)),
    x = ve === `mobile`,
    Fe = ve === `tablet`,
    Ie = ve === `desktop`,
    S = x || Fe,
    Le = Ie || Fe,
    Re = !!(window.devicePixelRatio && window.devicePixelRatio > 1),
    ze = {
        "10h": [`10hPa`, `30km FL980`, 3e4, 98e3],
        "150h": [`150hPa`, `13.5km FL450`, 13500, 45e3],
        "200h": [`200hPa`, `11.7km FL390`, 11700, 39e3],
        "250h": [`250hPa`, `10km FL340`, 1e4, 34e3],
        "300h": [`300hPa`, `9000m FL300`, 9e3, 3e4],
        "400h": [`400hPa`, `7000m FL240`, 7e3, 24e3],
        "500h": [`500hPa`, `5500m FL180`, 5500, 18e3],
        "600h": [`600hPa`, `4200m FL140`, 4200, 14e3],
        "700h": [`700hPa`, `3000m FL100`, 3e3, 1e4],
        "800h": [`800hPa`, `2000m 6400ft`, 2e3, 6400],
        "850h": [`850hPa`, `1500m 5000ft`, 1500, 5e3],
        "900h": [`900hPa`, `900m 3000ft`, 900, 3e3],
        "925h": [`925hPa`, `750m 2500ft`, 750, 2500],
        "950h": [`950hPa`, `600m 2000ft`, 600, 2e3],
        "975h": [`975hPa`, `300m 1000ft`, 300, 1e3],
        "100m": [`100m`, `330ft`, 100, 330],
        surface: [``, ``, 0, 0]
    },
    Be = {
        favs: {
            title: `POI_FAVS`,
            icon: `k`
        },
        cities: {
            title: `POI_FCST`,
            icon: `&`
        },
        stations: {
            title: `POI_STATIONS`,
            icon: ``
        },
        wind: {
            title: `POI_WIND`,
            titleShort: `POI_WIND_SHORT`,
            icon: `|`
        },
        temp: {
            title: `POI_TEMP`,
            titleShort: `POI_TEMP_SHORT`,
            icon: ``
        },
        precip: {
            title: `POI_PRECIP`,
            titleShort: `POI_PRECIP_SHORT`,
            icon: `H`
        },
        metars: {
            title: `POI_AD`,
            icon: `Q`
        },
        cams: {
            title: `POI_CAMS`,
            icon: `l`
        },
        pgspots: {
            title: `POI_PG`,
            icon: ``
        },
        kitespots: {
            title: `POI_KITE`,
            icon: ``
        },
        surfspots: {
            title: `POI_SURF`,
            icon: `{`
        },
        tide: {
            title: `POI_TIDE`,
            icon: `q`
        },
        firespots: {
            title: `ACTIVE_FIRES`,
            icon: ``
        },
        airq: {
            title: `POI_AIRQ`,
            icon: ``
        },
        radiosonde: {
            title: `POI_RADIOSONDE`,
            icon: ``
        },
        empty: {
            title: `POI_EMPTY`,
            icon: `t`
        }
    },
    Ve = {
        stations: [`wind`, `temp`, `precip`]
    },
    He = [`pressure`, `gh`, `temp`, `deg0`],
    Ue = `/${xe}/plugins`,
    We = {
        pollenAlder: [`POLLEN_ALDER`, `POLLEN_ALDER_SHORT`],
        pollenBirch: [`POLLEN_BIRCH`, `POLLEN_BIRCH_SHORT`],
        pollenGrass: [`POLLEN_GRASS`, `POLLEN_GRASS_SHORT`],
        pollenMugwort: [`POLLEN_MUGWORT`, `POLLEN_MUGWORT_SHORT`],
        pollenOlive: [`POLLEN_OLIVE`, `POLLEN_OLIVE_SHORT`],
        pollenRagweed: [`POLLEN_RAGWEED`, `POLLEN_RAGWEED_SHORT`]
    },
    Ge = `whatsNew`;
var Ke = b({
        HttpError: () => qe
    }),
    qe = class extends Error {
        constructor(e, t, n) {
            super(t), this.status = e, this.message = t, this.responseText = n
        }
    };

function Je(e) {
    "@babel/helpers - typeof";
    return Je = typeof Symbol == `function` && typeof Symbol.iterator == `symbol` ? function(e) {
        return typeof e
    } : function(e) {
        return e && typeof Symbol == `function` && e.constructor === Symbol && e !== Symbol.prototype ? `symbol` : typeof e
    }, Je(e)
}

function Ye(e, t) {
    if (Je(e) != `object` || !e) return e;
    var n = e[Symbol.toPrimitive];
    if (n !== void 0) {
        var r = n.call(e, t || `default`);
        if (Je(r) != `object`) return r;
        throw TypeError(`@@toPrimitive must return a primitive value.`)
    }
    return (t === `string` ? String : Number)(e)
}

function Xe(e) {
    var t = Ye(e, `string`);
    return Je(t) == `symbol` ? t : t + ``
}

function C(e, t, n) {
    return (t = Xe(t)) in e ? Object.defineProperty(e, t, {
        value: n,
        enumerable: !0,
        configurable: !0,
        writable: !0
    }) : e[t] = n, e
}

function Ze(e, t) {
    var n = Object.keys(e);
    if (Object.getOwnPropertySymbols) {
        var r = Object.getOwnPropertySymbols(e);
        t && (r = r.filter(function(t) {
            return Object.getOwnPropertyDescriptor(e, t).enumerable
        })), n.push.apply(n, r)
    }
    return n
}

function w(e) {
    for (var t = 1; t < arguments.length; t++) {
        var n = arguments[t] == null ? {} : arguments[t];
        t % 2 ? Ze(Object(n), !0).forEach(function(t) {
            C(e, t, n[t])
        }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(n)) : Ze(Object(n)).forEach(function(t) {
            Object.defineProperty(e, t, Object.getOwnPropertyDescriptor(n, t))
        })
    }
    return e
}
var Qe = b({
    $: () => Kt,
    addQs: () => Bt,
    bicubicFiltering: () => Zt,
    c2kelvin: () => un,
    canvasRatio: () => an,
    capitalize: () => mn,
    char2num: () => at,
    clamp: () => D,
    clamp0X: () => Qt,
    clone: () => ht,
    computeDewPointCelsius: () => An,
    computeDewPointKelvin: () => jn,
    copy2clipboard: () => Ut,
    createColorGradient: () => Cn,
    cubicHermite: () => Xt,
    debounce: () => yt,
    deg2rad: () => gt,
    degToRad: () => _t,
    download: () => Wt,
    each: () => mt,
    emptyFun: () => ut,
    emptyGIF: () => dt,
    escapeRegExp: () => Mn,
    extractTileCoordsUrlPositionsFromParametricUrl: () => Dn,
    generateUuidV4: () => xn,
    getAdjustedNow: () => Lt,
    getErrorMessage: () => Sn,
    getNativePlugin: () => Gt,
    getPathFromTs: () => hn,
    getRefs: () => tn,
    hasDirection: () => Tt,
    intersect: () => on,
    isEmptyObject: () => ft,
    isFunction: () => qt,
    isNear: () => Dt,
    isProfessionalStation: () => sn,
    isTouchEvent: () => Jt,
    isValidLang: () => Rt,
    isValidLatLonObj: () => pt,
    isValidNumber: () => ln,
    joinPath: () => zt,
    kelvin2c: () => dn,
    lat01ToYUnit: () => At,
    latDegToYUnit: () => jt,
    latLon2str: () => ct,
    lerp: () => $t,
    lerpColor256: () => en,
    loadScript: () => Ht,
    logError: () => O,
    lonDegToXUnit: () => kt,
    longPressTime: () => 600,
    maxCanvasRatio: () => 2,
    normalizeLatLon: () => E,
    num2char: () => it,
    offsetLeafletZoom: () => On,
    openInApp: () => Tn,
    pad: () => xt,
    parseQueryString: () => gn,
    parseSeoUrl: () => vn,
    preventDefault: () => wn,
    qs: () => Vt,
    radToDeg: () => vt,
    removeDiacritics: () => pn,
    sanitizeHTML: () => nn,
    scaleLinear: () => rn,
    seoLangRegex: () => _n,
    smoothstep: () => Ot,
    spline: () => Yt,
    startupPath: () => bn,
    str2latLon: () => lt,
    subscribeToChange: () => kn,
    template: () => St,
    throttle: () => bt,
    toLocalTime: () => En,
    tsDay: () => tt,
    tsHour: () => T,
    tsMinute: () => et,
    tsSecond: () => $e,
    unitXToLonDeg: () => Mt,
    unitXToLonRad: () => Pt,
    unitYToLatDeg: () => Nt,
    unitYToLatRad: () => Ft,
    vec2dir: () => st,
    vec2size: () => ot,
    wait: () => fn,
    wave2obj: () => wt,
    wind2obj: () => Ct,
    windDir2html: () => Et,
    wrapCoords: () => cn
});
const $e = 1e3,
    et = 60 * $e,
    T = 60 * et,
    tt = 24 * T,
    nt = `bcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789a`,
    rt = nt.split(``),
    it = e => {
        let t = ``;
        do t = nt.charAt(e % 60) + t, e = Math.floor(e / 60); while (e);
        return t
    },
    at = e => {
        let t = 0;
        for (let n = 0; n < e.length; n++) t = t * 60 + rt.indexOf(e.charAt(n));
        return t
    },
    ot = (e, t) => Math.sqrt(e * e + t * t),
    st = (e, t, n = 1) => Math.floor((Math.atan2(e, t) * 180 / Math.PI + 180) / n) * n,
    ct = e => {
        let t = Math.floor((e.lat + 90) * 100),
            n = Math.floor((e.lon + 180) * 100);
        return `${it(t)}a${it(n)}`
    },
    lt = e => {
        let t = e.split(`a`);
        return {
            lat: at(t[0]) / 100 - 90,
            lon: at(t[1]) / 100 - 180
        }
    },
    ut = () => {},
    dt = `data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==`,
    ft = e => Object.keys(e).length === 0,
    pt = e => e && typeof e == `object` && `lat` in e && `lon` in e && !isNaN(+e.lat) && !isNaN(+e.lon) || !1,
    E = e => parseFloat(e).toFixed(3),
    mt = (e, t) => {
        for (let n in e) t(e[n], n)
    },
    ht = (e, t) => {
        if (e === null) return e;
        if (e instanceof Date) return new Date(e.getTime());
        if (e instanceof Array) {
            let t = [];
            return e.forEach(e => {
                t.push(e)
            }), t.map(e => ht(e))
        } else if (typeof e == `object`) {
            let n = w({}, e);
            return Object.keys(n).forEach(e => {
                (!t || t.includes(e)) && (n[e] = ht(n[e]))
            }), n
        }
        return e
    },
    gt = e => e * Math.PI / 180,
    _t = .017453292,
    vt = 57.2957795,
    yt = function(e, t, n) {
        let r;
        return function(...i) {
            let a = this;

            function o() {
                clearTimeout(r), r = 0, n || e.apply(a, i)
            }
            let s = n && !r;
            clearTimeout(r), r = setTimeout(o, t), s && e.apply(a, i)
        }
    },
    bt = function(e, t) {
        let n, r, i = this;

        function a() {
            n = !1, r && (o.apply(i, r), r = !1)
        }

        function o(...o) {
            n ? r = o : (e.apply(i, o), setTimeout(a, t), n = !0)
        }
        return o
    },
    xt = (e, t = 2) => {
        let n = String(e);
        for (; n.length < t;) n = `0` + n;
        return n
    },
    St = (e, t) => e ? e.replace(/\{\{?\s*(.+?)\s*\}?\}/g, (e, n) => t && n in t ? String(t[n]) : ``) : ``,
    Ct = ([e, t]) => ({
        wind: ot(e, t),
        dir: st(e, t, 10)
    }),
    wt = ([e, t, n]) => ({
        period: ot(e, t),
        dir: st(e, t, 10),
        size: n
    }),
    Tt = e => typeof e.dir == `number` && typeof e.wind == `number` && e.dir <= 360 && e.wind >= 0,
    Et = e => Tt(e) ? `<div class="iconfont" style="transform: rotate(${e.dir}deg); -webkit-transform:rotate(${e.dir}deg);">"</div>` : ``,
    Dt = (e, t) => Math.abs(e.lat - +t.lat) < .01 && Math.abs(e.lon - +t.lon) < .01,
    D = (e, t, n) => Math.max(Math.min(e, n), t),
    Ot = (e, t, n) => {
        let r = D((n - e) / (t - e), 0, 1);
        return r * r * r * (r * (r * 6 - 15) + 10)
    },
    kt = e => .5 + .00277777777777777 * e,
    At = e => (Math.PI - Math.log(Math.tan((1 - e) * .5 * Math.PI))) / (2 * Math.PI),
    jt = e => At(.5 - .00555555555555555 * e),
    Mt = e => (e - .5) * 360,
    Nt = e => 180 * (Math.atan(Math.exp(Math.PI - 2 * Math.PI * e)) / (.5 * Math.PI)) - 90,
    Pt = e => (e - .5) * 2 * Math.PI,
    Ft = e => 2 * Math.atan(Math.exp(Math.PI - 2 * e * Math.PI)) - .5 * Math.PI;
let It = 0;
const Lt = e => {
        let t = Date.now() - It,
            n;
        return e && (n = t - e, n < 0 && (It += n), n > 1e4 && (It += n)), t
    },
    Rt = e => ye.includes(e),
    zt = (e, t) => (e.endsWith(`/`) && (e = e.slice(0, -1)), t.startsWith(`/`) ? `${e}${t}` : `${e}/${t}`),
    Bt = (e, t) => `${e}${/\?/.test(e) ? `&` : `?`}${t}`,
    Vt = e => {
        let t = [];
        return mt(e, (e, n) => e !== void 0 && t.push(`${n}=${e}`)), t.sort().join(`&`)
    },
    Ht = (e, t) => new Promise((n, r) => {
        let i = document.createElement(`script`);
        i.type = `text/javascript`, i.async = !0, i.onload = () => {
            n()
        }, i.onerror = e => {
            r(e)
        }, document.head.appendChild(i), t && typeof t == `function` && t(i), i.src = e
    }),
    Ut = e => {
        let t = document.createElement(`textarea`);
        t.value = e, document.body.appendChild(t), t.select(), document.execCommand(`copy`), document.body.removeChild(t)
    },
    Wt = (e, t, n) => {
        let r = document.createElement(`a`),
            i = e instanceof Blob ? e : new Blob([e], {
                type: t
            });
        r.style.display = `none`, document.body.appendChild(r), window.URL && (r.href = window.URL.createObjectURL(i)), r.setAttribute(`download`, n), r.click(), window.URL && window.URL.revokeObjectURL(r.href), document.body.removeChild(r)
    };

function Gt(e) {
    return null
}
const Kt = (e, t) => (t || document).querySelector(e),
    qt = e => typeof e == `function`,
    Jt = e => !!(`touches` in e && e.touches),
    Yt = (e, t, n, r, i) => .5 * (2 * t + (-e + n) * i + (2 * e - 5 * t + 4 * n - r) * i * i + (-e + 3 * t - 3 * n + r) * i * i * i),
    Xt = (e, t, n, r, i) => {
        let a = -e * .5 + 3 * t * .5 - 3 * n * .5 + r * .5,
            o = e - 5 * t * .5 + 2 * n - r * .5,
            s = -e * .5 + n * .5,
            c = t;
        return a * i * i * i + o * i * i + s * i + c
    },
    Zt = (e, t, n) => Xt(Xt(e[0], e[1], e[2], e[3], t), Xt(e[4], e[5], e[6], e[7], t), Xt(e[8], e[9], e[10], e[11], t), Xt(e[12], e[13], e[14], e[15], t), n),
    Qt = (e, t) => Math.min(Math.max(e, 0), t - 1),
    $t = (e, t, n) => e + n * (t - e),
    en = (e, t, n) => e.map((r, i) => D($t(e[i], t[i], n), 0, 255)),
    tn = e => {
        var t;
        let n = typeof e == `string` ? Kt(e) : e,
            r = {};
        return ((t = n == null ? void 0 : n.querySelectorAll(`[data-ref]`)) == null ? [] : t).forEach(e => {
            e.dataset.ref && (r[e.dataset.ref] = e)
        }), {
            node: n,
            refs: r
        }
    },
    nn = e => e.replace(/&/g, `&amp;`).replace(/</g, `&lt;`).replace(/>/g, `&gt;`).replace(/"/g, `&quot;`).replace(/'/g, `&#x27;`).replace(/\//g, `&#x2F;`);

function O(e, t, n, r) {
    let i = new CustomEvent(`windyCustomError`, {
        detail: {
            moduleName: e,
            msg: t,
            errorObject: n,
            additionalInfo: r
        }
    });
    document.dispatchEvent(i), console.error(e, t, n, r)
}
const rn = ({
        domain: e,
        range: t,
        clip: n
    }) => {
        let [r, i] = t, [a, o] = e, s = (i - r) / (o - a), [c, l] = r > i ? [r, i] : [i, r], u = e => (e - a) * s + r, d = e => D(u(e), l, c), [f, p] = a > o ? [a, o] : [o, a], m = e => (e - r) / s + a;
        return {
            get: n ? d : u,
            invert: n ? e => D(m(e), p, f) : m
        }
    },
    an = Math.min(window.devicePixelRatio || 1, 2),
    on = e => {
        let t = new Set(e[0]);
        for (let n of e.slice(1)) {
            let e = new Set(n);
            for (let n of t) e.has(n) || t.delete(n)
        }
        return [...t]
    },
    sn = e => /^(ad|wmo|buoy|ship)$/.test(e),
    cn = e => {
        let t = 1 << e.z;
        return e.x %= t, e.x < 0 && (e.x += t), e
    },
    ln = e => typeof e == `number` && !isNaN(e),
    un = e => e + 273.15,
    dn = e => e - 273.15,
    fn = e => new Promise(t => setTimeout(t, e)),
    pn = e => e.normalize(`NFD`).replace(/[\u0300-\u036f]/g, ``),
    mn = e => e.charAt(0).toUpperCase() + e.slice(1),
    hn = (e, t = `$1$2$3$4`) => new Date(e).toISOString().replace(/(\d\d\d\d)-(\d\d)-(\d\d)T(\d\d):.*/, t),
    gn = e => {
        if (!e || !/\S+=\S+/.test(e)) return;
        e = e.replace(/^\?/, ``);
        let t = e.split(`&`),
            n = {};
        for (let e = 0; e < t.length; e++) {
            let r = t[e].split(`=`);
            try {
                n[decodeURIComponent(r[0])] = decodeURIComponent(r[1] || ``)
            } catch (e) {}
        }
        return n
    },
    _n = /^\/(zh-TW|[a-z]{2})(\/.*)?$/,
    vn = e => {
        let t = null,
            n = e,
            r = _n.exec(e);
        r && (n = r[2]);
        let i;
        return (i = /^\/-(?:[^0-9/][^/]+)(?:-(\w+))(?:[^/]*)$/.exec(n)) ? (t = i[1], n = `/`) : (i = /^\/-(?:[^0-9/][^/]+)?(\/.+)$/.exec(n)) && (n = i[1]), {
            purl: n,
            overlay: t
        }
    };
let yn;
try {
    yn = decodeURIComponent(window.location.pathname)
} catch (e) {
    console.error(e)
}
const bn = yn || `/`,
    xn = () => {
        let e = () => Math.floor((1 + Math.random()) * 65536).toString(16).substring(1);
        return e() + e() + `-` + e() + `-` + e() + `-` + e() + `-` + e() + e() + e()
    },
    Sn = e => {
        if (e instanceof qe) return e.responseText || e.message;
        if (e instanceof Error) return e.message;
        if (typeof e == `string`) return e;
        if (typeof e == `object` && e) {
            if (`message` in e && typeof e.message == `string`) return e.message;
            try {
                return JSON.stringify(e)
            } catch (t) {
                return e.toString()
            }
        }
        return `Unknown error`
    },
    Cn = (e, t) => t.map((t, n) => [t, e[n]]),
    wn = e => t => {
        t.preventDefault(), e(t)
    },
    Tn = () => {
        window.location.href = _e === `ios` ? `https://apps.apple.com/app/apple-store/id1161387262?pt=118417623&ct=webapp&mt=8` : `https://play.google.com/store/apps/details?id=com.windyty.android&utm_source=menu&utm_medium=windy&utm_campaign=openAppLink&utm_content=openAppLink`
    },
    En = (e, t) => {
        let n = new Date(e + t * T);
        return {
            h: n.getUTCHours(),
            m: n.getUTCMinutes(),
            day: n.getUTCDate(),
            weekDay: n.getUTCDay(),
            yearMonthDay: n.toISOString().split(`T`)[0]
        }
    };

function Dn(e) {
    let t = {
        x: -1,
        y: -1,
        z: -1
    };
    return e.split(`/`).forEach((e, n) => {
        switch (e) {
            case `{x}`:
                t.x = n;
                break;
            case `{y}`:
                t.y = n;
                break;
            case `{z}`:
                t.z = n;
                break
        }
    }), t
}
const On = e => e + 1,
    kn = (e, t) => {
        let n = !0,
            r = e.subscribe(e => {
                n || t(e)
            });
        return n = !1, r
    },
    An = (e, t) => {
        let n = 17.62,
            r = 243.12;
        e = D(e, 1e-5, 100);
        let i = Math.log(e / 100) + n * t / (r + t);
        return r * i / (n - i)
    },
    jn = (e, t) => un(An(e, dn(t))),
    Mn = e => e.replace(/[.*+?^${}()|[\]\\]/g, `\\$&`),
    Nn = [],
    Pn = (e, t, n) => {
        Nn.push({
            ts: Date.now(),
            txt: `${e}: ${t}${typeof n == `string` ? ` ` + n : ``}`
        }), Nn.length > 5 && Nn.shift()
    },
    Fn = e => {
        let t = e - 1e3,
            n = Nn.filter(({
                ts: e
            }) => e > t);
        return n.length ? n.map(({
            ts: t,
            txt: n
        }) => `${n} (${e - t}ms ago at ${t})`).join(`
`) : void 0
    };
var In = b({
        Evented: () => Ln
    }),
    Ln = class {
        constructor(e) {
            C(this, `latestId`, void 0), C(this, `_eventedCache`, void 0), C(this, `listenAllMethod`, void 0), C(this, `terminalColor`, void 0), C(this, `ident`, void 0), C(this, `trigger`, void 0), C(this, `fire`, void 0), this.latestId = 1, this._eventedCache = {}, this.trigger = this.emit, this.fire = this.emit, this.ident = e.ident
        }
        emit(e, ...t) {
            Pn(this.ident, String(e), t[0]);
            let n = this._eventedCache[e];
            if (n)
                for (let r = n.length; r--;) {
                    let i = n[r];
                    try {
                        i.callback.call(i.context, ...t), i.once && this.off(i.id)
                    } catch (n) {
                        O(`Evented`, `Failed to call ${String(e)}`, n, {
                            extra: {
                                data: t
                            }
                        })
                    }
                }
            this.listenAllMethod && this.listenAllMethod(e, ...t)
        }
        on(e, t, n, r) {
            return this.latestId = this.latestId || 0, this._eventedCache ? (e in this._eventedCache || (this._eventedCache[e] = []), this._eventedCache[e].push({
                id: ++this.latestId,
                callback: t,
                context: n || this,
                once: r || !1
            }), this.latestId) : this.latestId
        }
        once(e, t, n) {
            return this.on(e, t, n, !0)
        }
        off(e, t, n) {
            if (typeof e == `number`)
                for (let t in this._eventedCache) {
                    let n = this._eventedCache[t];
                    if (n) {
                        for (let t = n.length; t--;) n[t].id === e && n.splice(t, 1);
                        n.length === 0 && delete this._eventedCache[t]
                    }
                } else {
                    let r = this._eventedCache[e];
                    if (r) {
                        for (let e = r.length; e--;) r[e].callback === t && (!n || n === r[e].context) && r.splice(e, 1);
                        this._eventedCache && r.length === 0 && delete this._eventedCache[e]
                    }
                }
        }
        offAll() {
            this._eventedCache = {}
        }
        listenAll(e) {
            this.listenAllMethod = e
        }
    };
const k = [!0, !1],
    Rn = e => typeof + e == `number` && !isNaN(+e),
    zn = e => e !== void 0 && typeof e == `object`,
    Bn = e => pt(e) || e == null,
    Vn = e => e !== null && pt(e) && Number.isInteger(e.zoom) && (e.source === `maps` || e.source === `globe`),
    Hn = e => e !== void 0 && typeof e == `string`,
    Un = e => e === null || Hn(e),
    Wn = e => e === null || !isNaN(Number(e)),
    Gn = e => e.slice().sort().toString(),
    Kn = (e, t) => Gn(e) === Gn(t),
    A = {
        overlay: {
            def: `wind`,
            allowed: we
        },
        level: {
            def: `surface`,
            allowed: Se
        },
        acRange: {
            def: 12,
            allowed: Rn
        },
        timestamp: {
            def: Date.now(),
            allowed: Rn
        },
        isolinesType: {
            def: `pressure`,
            allowed: He,
            save: !0
        },
        isolinesOn: {
            def: !1,
            allowed: k,
            save: !0
        },
        startUpLastProduct: {
            def: null,
            allowed: [...Me, null],
            save: !0,
            nativeSync: !0,
            premiumOnly: !0
        },
        product: {
            def: `ecmwf`,
            allowed: Me
        },
        availProducts: {
            def: [`ecmwf`],
            allowed: Array.isArray,
            compare: Kn,
            readOnly: !0
        },
        visibleProducts: {
            def: [`ecmwf`],
            allowed: Array.isArray,
            compare: Kn
        },
        preferredProduct: {
            def: `ecmwf`,
            allowed: [`ecmwf`, `gfs`, `icon`, `iconEu`],
            readOnly: !0
        },
        animation: {
            def: !1,
            allowed: k
        },
        animationSpeed: {
            def: `normal`,
            allowed: [`normal`, `fast`, `very-fast`],
            save: !0
        },
        calendar: {
            def: null,
            allowed: zn,
            readOnly: !0
        },
        availLevels: {
            def: [...Se],
            allowed: e => e.every(e => Se.includes(e)),
            readOnly: !0
        },
        particlesAnim: {
            def: `on`,
            allowed: [`on`, `off`, `intensive`],
            save: !0
        },
        camsPreviews: {
            def: !0,
            allowed: k,
            save: !0
        },
        graticule: {
            def: !1,
            allowed: k,
            save: !0
        },
        latlon: {
            def: !1,
            allowed: k,
            save: !0
        },
        showPickerElevation: {
            def: !1,
            allowed: k,
            save: !0,
            premiumOnly: !0
        },
        pickerDragging: {
            def: !1,
            allowed: k,
            save: !1
        },
        lang: {
            def: `auto`,
            allowed: e => e === `auto` || Rt(e),
            save: !0,
            sync: !0
        },
        englishLabels: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !0
        },
        numDirection: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !0
        },
        marketingConsent: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !0
        },
        hourFormat: {
            def: `24h`,
            allowed: [`12h`, `24h`],
            save: !0,
            sync: !0,
            nativeSync: !0
        },
        country: {
            def: `xx`,
            save: !0,
            allowed: e => /[a-z][a-z0-9]/.test(e)
        },
        defaultUnits: {
            def: `unset`,
            allowed: [`unset`, `imperial`, `metric`],
            save: !0
        },
        map: {
            def: `sznmap`,
            allowed: [`sznmap`, `sat`, `winter`]
        },
        mapLibrary: {
            def: `leafletGl`,
            allowed: [`leafletGl`, `globe`]
        },
        showWeather: {
            def: !0,
            allowed: k,
            save: !0,
            premiumOnly: !0
        },
        stormSettingsLightning: {
            def: !0,
            allowed: k,
            save: !0
        },
        usedLang: {
            def: `en`,
            allowed: ye,
            save: !0,
            sync: !0
        },
        lastTimezoneOffset: {
            def: new Date().getTimezoneOffset(),
            allowed: Rn,
            save: !0,
            sync: !0
        },
        particles: {
            def: {
                multiplier: 1,
                velocity: 1,
                width: 1,
                blending: 1,
                opacity: 1
            },
            save: !0,
            allowed(e) {
                let t;
                if (!e || typeof e != `object`) return !1;
                for (let n in this.def)
                    if (t = e[n], typeof t != `number` || t > 2 || t < 0) return !1;
                return !0
            }
        },
        startUp: {
            def: `ip`,
            allowed: [`ip`, `gps`, `location`, `last`],
            save: !0,
            nativeSync: !0
        },
        startUpLastPosition: {
            def: {
                lat: 50,
                lon: 14,
                zoom: 4,
                source: `maps`
            },
            allowed: Vn,
            save: !0,
            nativeSync: !0
        },
        homeLocation: {
            def: null,
            allowed: Bn,
            save: !0,
            sync: !0,
            nativeSync: !0
        },
        startUpOverlay: {
            def: `wind`,
            allowed: we,
            save: !0,
            nativeSync: !0,
            premiumOnly: !0
        },
        startUpLastOverlay: {
            def: !1,
            allowed: k,
            save: !0,
            nativeSync: !0,
            premiumOnly: !0
        },
        startUpLastStep: {
            def: null,
            allowed: [1, 3, null],
            save: !0,
            nativeSync: !0,
            premiumOnly: !0
        },
        startUpZoom: {
            def: null,
            allowed: e => e === null || e >= 3 && e <= 11,
            save: !0,
            nativeSync: !0
        },
        ipLocation: {
            def: null,
            allowed: Bn,
            save: !0,
            nativeSync: !0
        },
        gpsLocation: {
            def: null,
            allowed: Bn,
            save: !0,
            nativeSync: !0
        },
        startupReverseName: {
            def: null,
            allowed: zn,
            save: !0
        },
        email: {
            def: ``,
            allowed: e => /\S+@\S+/.test(e),
            save: !0,
            sync: !0
        },
        metarsRAW: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !0
        },
        sessionCounter: {
            def: 0,
            allowed: Rn,
            save: !0
        },
        firstUserSession: {
            def: 0,
            allowed: Rn,
            save: !0
        },
        seenRadarInfo: {
            def: !1,
            save: !0,
            allowed: k
        },
        liveAlertsWarningDismissed: {
            def: !1,
            save: !0,
            allowed: k
        },
        detailLocation: {
            def: null,
            allowed: Bn
        },
        detail1h: {
            def: !1,
            allowed: k
        },
        detailExtended: {
            def: !1,
            save: !0,
            allowed: k
        },
        webcamsDaylight: {
            def: !1,
            allowed: k
        },
        capDisplay: {
            def: `all`,
            allowed: [`all`, `today`, `tomm`, `later`]
        },
        radarTimestamp: {
            def: Date.now(),
            allowed: Rn
        },
        radarCalendar: {
            def: null,
            allowed: zn
        },
        blitzOn: {
            def: !0,
            allowed: k,
            save: !0
        },
        blitzSoundOn: {
            def: !0,
            allowed: k,
            save: !0
        },
        showThickBorders: {
            def: !1,
            allowed: k,
            save: !1
        },
        satelliteTimestamp: {
            def: Date.now(),
            allowed: Rn
        },
        satelliteCalendar: {
            def: null,
            allowed: zn
        },
        radSatFlowOn: {
            def: !0,
            allowed: k,
            save: !0
        },
        radarRenderPType: {
            def: !0,
            allowed: k,
            save: !0
        },
        radsatTimestamp: {
            def: Date.now(),
            allowed: Rn
        },
        archiveOn: {
            def: !1,
            allowed: k
        },
        archiveTimestamp: {
            def: 0,
            allowed: Rn,
            save: !0
        },
        archiveRange: {
            def: 24,
            allowed: Rn,
            save: !0
        },
        pois: {
            def: `favs`,
            allowed: Object.keys(Be),
            save: !0
        },
        subPois: {
            def: {},
            allowed: zn,
            save: !0
        },
        poisTemporary: {
            def: `empty`,
            allowed: Object.keys(Be)
        },
        favPois: {
            def: [`cams`, `cities`, `wind`, `temp`, `metars`, `empty`],
            allowed: e => Array.isArray(e),
            save: !0,
            sync: !0
        },
        visibility: {
            def: !0,
            allowed: k
        },
        displayLocation: {
            def: !0,
            allowed: k,
            save: !0
        },
        vibrate: {
            def: !0,
            allowed: k,
            save: !0
        },
        donations: {
            def: [],
            allowed: Array.isArray,
            compare: Kn,
            save: !0,
            sync: !0
        },
        zuluMode: {
            def: !1,
            allowed: k,
            save: !0,
            premiumOnly: !0
        },
        stationsSort: {
            def: `profi`,
            allowed: [`profi`, `distance`],
            save: !0
        },
        stationCompareModel: {
            def: `noModel`,
            allowed: Hn,
            save: !0
        },
        subscription: {
            def: null,
            allowed: e => !0,
            save: !0,
            nativeSync: !0
        },
        subscriptionInfo: {
            def: null,
            allowed: zn
        },
        pendingSubscription: {
            def: null,
            allowed: Un,
            save: !0
        },
        failedSubscriptionPayment: {
            def: null,
            allowed: Un,
            save: !0
        },
        notifications: {
            def: null,
            allowed: zn,
            save: !0,
            sync: !0
        },
        badgeNumber: {
            def: 0,
            allowed: Rn,
            save: !0
        },
        user: {
            def: null,
            allowed: zn,
            save: !0,
            nativeSync: !0
        },
        userToken: {
            def: null,
            allowed: Hn,
            save: !0,
            nativeSync: !0
        },
        authHash: {
            def: null,
            allowed: Hn,
            save: !0,
            nativeSync: !0,
            watchSync: !0
        },
        lastPoiLocation: {
            def: null,
            allowed: Bn
        },
        pickerLocation: {
            def: null,
            allowed: e => e === null || Bn(e)
        },
        mapCoords: {
            def: null,
            allowed: Bn
        },
        unresolvedErrors: {
            def: [],
            allowed: Array.isArray
        },
        closedErrors: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            nativeSync: !0
        },
        showDailyNotifications: {
            def: !1,
            allowed: k,
            nativeSync: !0,
            save: !0
        },
        appReviewPluginShown: {
            def: null,
            allowed: Wn,
            nativeSync: !0,
            save: !0
        },
        systemAppReviewDialogShown: {
            def: null,
            allowed: Wn,
            nativeSync: !0,
            save: !0
        },
        appReviewLastVersion: {
            def: null,
            allowed: Un,
            nativeSync: !0,
            save: !0
        },
        appReviewDialogLeaveForLater: {
            def: !1,
            allowed: k,
            save: !0
        },
        skipAppReviewNecessaryConditions: {
            def: !1,
            allowed: k,
            save: !0
        },
        favOverlaysMobile: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            sync: !0
        },
        favOverlaysDesktop: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            sync: !0
        },
        favPoisMobile: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            sync: !0
        },
        mobileMenuFilter: {
            def: `all`,
            allowed: [`all`, `wind`, `rain`, `sea`, `airQ`, `drought`, `temp`, `warnings`, `clouds`, `search`]
        },
        connection: {
            def: !0,
            allowed: k
        },
        pickerMobileTimeout: {
            def: `6`,
            allowed: [`3`, `6`, `9`, `12`, `always`],
            save: !0,
            sync: !0
        },
        changeDetailOnMapDrag: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !1
        },
        displayHeliports: {
            def: !1,
            allowed: k,
            save: !0
        },
        displayAirspaces: {
            def: !0,
            allowed: k,
            save: !0
        },
        displayAdStations: {
            def: !0,
            allowed: k,
            save: !0
        },
        displayWMOStations: {
            def: !0,
            allowed: k,
            save: !0
        },
        displayMadisPWStations: {
            def: !0,
            allowed: k,
            save: !0
        },
        displayShipStations: {
            def: !0,
            allowed: k,
            save: !0
        },
        stationCompareHiddenProducts: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            sync: !0
        },
        consent: {
            def: null,
            allowed: zn,
            save: !0,
            sync: !0
        },
        analyticsConsentRequired: {
            def: null,
            allowed: k,
            save: !0
        },
        youtubeConsent: {
            def: null,
            allowed: zn,
            save: !0,
            sync: !0
        },
        twitterConsent: {
            def: null,
            allowed: zn,
            save: !0,
            sync: !0
        },
        soundingIsSkewTlogP: {
            def: !1,
            save: !0,
            allowed: k
        },
        appLocalStorageCounter: {
            def: 0,
            allowed: Rn,
            nativeSync: !1,
            save: !0
        },
        rhMenuArrangeMode: {
            def: !1,
            allowed: k
        },
        userInterests: {
            def: [],
            allowed: Array.isArray,
            save: !0,
            sync: !0
        },
        onboardingFinished: {
            def: !1,
            allowed: k,
            save: !0,
            sync: !0
        },
        locationPermissionsGranted: {
            def: !1,
            allowed: k,
            save: !0
        },
        doNotShowLocationPermissionsPopup: {
            def: !1,
            allowed: k,
            save: !0
        },
        pTypeMultiSampled: {
            def: !1,
            allowed: k
        },
        locationPermissionsPopupShown: {
            def: null,
            allowed: Wn,
            save: !0
        },
        loginAndFinishAction: {
            def: null,
            allowed: zn,
            save: !0
        },
        favsFilter: {
            def: [],
            allowed: Array.isArray,
            save: !0
        },
        pushNotificationsReady: {
            def: !1,
            allowed: k
        },
        rplannerDir: {
            def: `north`,
            allowed: [`horizontal`, `vertical`, `north`],
            save: !0
        },
        rplannerMotionSpeed: {
            def: {
                elevation: 0,
                car: 22.2222,
                boat: 6.17333,
                vfr: 56.5889,
                ifr: 144.044,
                airgram: 22.2222
            },
            allowed: zn,
            save: !0
        },
        suspendSoundAndHaptic: {
            def: !1,
            allowed: k
        },
        advancedDebugConsole: {
            def: !1,
            save: !0,
            allowed: k
        },
        pinMenuActiveTab: {
            def: `layers`,
            allowed: [`models`, `layers`],
            save: !0
        },
        radarPlusSegmentRange: {
            def: `short`,
            allowed: [`short`, `medium`, `long`, `archive`],
            save: !1
        },
        perfOverlayEnabled: {
            def: !1,
            save: !0,
            allowed: k
        },
        tiledPoiLayer: {
            def: null,
            allowed: zn
        },
        airportDebugMode: {
            def: !1,
            save: !0,
            allowed: k
        },
        showMyPosition: {
            def: !1,
            allowed: k
        },
        searchInputValue: {
            def: ``,
            allowed: Hn
        },
        searchInputLoading: {
            def: !1,
            allowed: k
        },
        soundingProduct: {
            def: `ecmwf`,
            allowed: Me,
            save: !0
        }
    },
    qn = {
        isAvbl: !1,
        put: (e, t) => window.localStorage.setItem(e, JSON.stringify(t)),
        hasKey: e => e in window.localStorage,
        get: e => {
            let t = window.localStorage.getItem(e);
            return t ? JSON.parse(t) : null
        },
        remove: e => window.localStorage.removeItem(e)
    },
    Jn = {},
    Yn = {
        isAvbl: !1,
        put: (e, t) => Jn[e] = t,
        hasKey: e => e in Jn,
        get: e => e in Jn ? Jn[e] : null,
        remove: e => delete Jn[e]
    };
try {
    if (window.localStorage.setItem(`test`, `bar`), window.localStorage.getItem(`test`) !== `bar`) throw Error(`Comparsion failed`);
    window.localStorage.removeItem(`test`), qn.isAvbl = !0
} catch (e) {}
var j = qn.isAvbl ? qn : Yn;
const Xn = new Map;
let Zn = !1;
const M = new class extends Ln {
    constructor(...e) {
        super(...e), C(this, `defineProperty`, (e, t, n) => {
            A[e][t] = n
        }), C(this, `remove`, (e, t = {
            doNotCheckValidity: !0
        }) => {
            this.set(e, null, t)
        }), C(this, `insert`, (e, t) => {
            A[e] = t
        })
    }
    setDefault(e, t) {
        A[e].def = t, Xn.delete(e)
    }
    set(e, t, n = {}) {
        let r = A[e];
        if (!r) throw Error(`Cannot find "${e}" key in dataSpecifications`);
        if (!n.doNotCheckValidity && !this.isValid(r, t)) return this.isAsyncStore(r) ? Promise.reject() : !1;
        if (r.syncSet && (n.forceChange || this.wasChanged(e, r, t))) {
            let i = r.syncSet(t);
            if (n.forceChange || this.wasChanged(e, r, i)) return this.setFinally(e, r, n, i), !0
        } else if (this.isAsyncStore(r))
            if (n.forceChange || this.wasChanged(e, r, t)) {
                let i = r.asyncSet(t);
                return i.then(t => {
                    (n.forceChange || this.wasChanged(e, r, t)) && this.setFinally(e, r, n, t)
                }).catch(n => console.error(`store: Unable to change store value ${e}, ${t}`, n)), i
            } else return Promise.resolve(t);
        else if (n.forceChange || this.wasChanged(e, r, t)) return this.setFinally(e, r, n, t), !0;
        return !1
    }
    getDefault(e) {
        return A[e].def
    }
    get(e, t) {
        if (Xn.has(e) && !(t != null && t.forceGet)) return Xn.get(e);
        let {
            premiumOnly: n,
            def: r,
            save: i
        } = A[e];
        if (n && !Zn) return r;
        let a;
        return i && j.isAvbl ? (a = j.get(`settings_${e}`), a === null && !(t != null && t.forceGet) ? a = r : this.isValid(A[e], a) || (console.error(`store: Attempt to get invalid value from localStorage: ${e}`), a = r)) : a = r, t != null && t.forceGet || Xn.set(e, a), a
    }
    isAsyncStore(e) {
        return !!(`asyncSet` in e && e.asyncSet)
    }
    wasChanged(e, t, n) {
        return t.compare ? !t.compare(n, this.get(e)) : Xn.has(e) ? Xn.get(e) !== n : this.getDefault(e) !== n
    }
    isValid(e, t) {
        return typeof e.allowed == `function` ? e.allowed(t) : Array.isArray(e.def) ? Array.isArray(t) && t.every(t => e.allowed.includes(t)) : e.allowed.includes(t)
    }
    setFinally(e, t, n, r) {
        if (r === null ? Xn.delete(e) : Xn.set(e, r), t.save && !n.doNotStore && j.isAvbl) {
            let i = n.update || Date.now();
            j.put(`settings_${e}`, r), t.sync && (t.update = i, j.put(`settings_${e}_ts`, i), j.put(`lastSyncableUpdatedItem`, i)), this.get(`user`) && t.sync && !n.doNotSaveToCloud && this.emit(`_cloudSync`)
        }
        this.emit(e, r === null ? t.def : r, n.UIident)
    }
}({
    ident: `store`
});
Zn = !!M.get(`subscription`), Zn || M.once(`subscription`, e => Zn = !!e);
const N = new Ln({
    ident: `bcast`
});
var Qn = b({
    testNetworkConnection: () => ir
});
let $n = null,
    er = !1;
async function tr() {
    try {
        let {
            status: e
        } = await fetch(`https://www.windy.com/img/favicon.ico`, {
            method: `HEAD`,
            cache: `no-store`
        });
        return e >= 200 && e < 400
    } catch (e) {
        return !1
    }
}

function nr() {
    $n && (clearInterval($n), $n = null)
}

function rr(e) {
    e && (M.set(`connection`, !0), document.body.classList.remove(`connection-is-offline`), er = !1, nr())
}
async function ir() {
    er || (er = !0, await tr() ? rr(!0) : (nr(), M.set(`connection`, !1), document.body.classList.add(`connection-is-offline`), $n = setInterval(async () => {
        rr(await tr())
    }, 2e3)))
}
window.addEventListener(`offline`, ir), window.addEventListener(`online`, ir);
var ar = b({
    generateDeviceId: () => or,
    getDeviceID: () => ur,
    getDeviceInfo: () => dr
});
const or = () => {
    let e = xn();
    return j.put(`UUID`, e), e
};
let sr = null;
const cr = j.get(`UUID`) || or(),
    lr = Gt(`Device`);
lr && lr.getInfo().then(e => {
    sr = e
}), M.get(`firstUserSession`) || M.set(`firstUserSession`, Date.now());
const ur = () => cr,
    dr = () => sr;
var fr = class {
        constructor(e) {
            C(this, `size`, void 0), C(this, `limit`, void 0), C(this, `_keymap`, void 0), C(this, `tail`, void 0), C(this, `head`, void 0), this.size = 0, this.limit = e, this._keymap = {}
        }
        put(e, t) {
            let n = {
                key: e,
                value: t,
                older: void 0
            };
            if (this._keymap[e] = n, this.tail ? (this.tail.newer = n, n.older = this.tail) : this.head = n, this.tail = n, this.size === this.limit) return this.shift();
            this.size++
        }
        toJSON() {
            let e = [],
                t = this.head;
            for (; t;) e.push({
                key: t.key,
                value: t.value
            }), t = t.newer;
            return e
        }
        shift() {
            let e = this.head;
            return e && this.head && (this.head.newer ? (this.head = this.head.newer, this.head.older = void 0) : this.head = void 0, e.newer = e.older = void 0, delete this._keymap[e.key]), e
        }
        get(e) {
            let t = this._keymap[e];
            if (t !== void 0) return t === this.tail ? t.value : (t.newer && (t === this.head && (this.head = t.newer), t.newer.older = t.older), t.older && (t.older.newer = t.newer), t.newer = void 0, t.older = this.tail, this.tail && (this.tail.newer = t), this.tail = t, t.value)
        }
        remove(e) {
            let t = this._keymap[e];
            if (t) return delete this._keymap[t.key], t.newer && t.older ? (t.older.newer = t.newer, t.newer.older = t.older) : t.newer ? (t.newer.older = void 0, this.head = t.newer) : t.older ? (t.older.newer = void 0, this.tail = t.older) : this.head = this.tail = void 0, this.size--, t.value
        }
        removeAll() {
            this.head = this.tail = void 0, this.size = 0, this._keymap = {}
        }
        forEach(e) {
            let t = this.head;
            for (; t;) e(t.value, `${t.key}`), t = t.newer
        }
    },
    pr = `accumulations.airport.alerts.appreview.articles.consent.distance.favs.garmin.hurricanes.info.langs.lib.livealerts.menu.menudesc.notifications.onboarding.picker.products.radsat.register.reportissue.search.settings.sounding.startuppromos.station.subscription.sunmoon.watchface.webcams.widgetspromo`.split(`.`),
    mr = {
        MON: `Monday`,
        TUE: `Tuesday`,
        WED: `Wednesday`,
        THU: `Thursday`,
        FRI: `Friday`,
        SAT: `Saturday`,
        SUN: `Sunday`,
        MON2: `Mon`,
        TUE2: `Tue`,
        WED2: `Wed`,
        THU2: `Thu`,
        FRI2: `Fri`,
        SAT2: `Sat`,
        SUN2: `Sun`,
        MON3: `M`,
        TUE3: `T`,
        WED3: `W`,
        THU3: `T`,
        FRI3: `F`,
        SAT3: `S`,
        SUN3: `S`,
        SMON01: `Jan`,
        SMON02: `Feb`,
        SMON03: `Mar`,
        SMON04: `Apr`,
        SMON05: `May`,
        SMON06: `Jun`,
        SMON07: `Jul`,
        SMON08: `Aug`,
        SMON09: `Sep`,
        SMON10: `Oct`,
        SMON11: `Nov`,
        SMON12: `Dec`,
        YES: `Yes`,
        NO: `No`,
        TODAY: `Today`,
        TOMORROW: `Tomorrow`,
        LATER: `Later`,
        ALL: `All`,
        HOURS_SHORT: `hrs`,
        FOLLOW: `Follow us`,
        EMBED: `Embed widget on page`,
        EMBED2: `Embed widget`,
        MENU: `Menu`,
        MENU_SETTINGS: `Settings`,
        MENU_HELP: `Help`,
        MENU_ABOUT: `About us`,
        MENU_LOCATION: `Find my location`,
        MENU_FULLSCREEN: `Fullscreen mode`,
        MENU_DISTANCE: `Distance & planning`,
        MENU_MOBILE: `Download App`,
        MENU_FAVS: `Favorites`,
        MENU_ALERTS: `Alerts`,
        MENU_FEEDBACK: `Feedback`,
        MENU_VIDEO: `Create video or animated GIF`,
        MENU_ERROR: `Error console`,
        MENU_NEWS: `Weather news`,
        MENU_TUTORIALS: `Tutorials`,
        MENU_SUN_MOON: `Sun/Moon position`,
        MENU_WIND_TRAJECTORIES: `Wind trajectories`,
        NOTIFICATIONS: `Notifications`,
        SHOW_PICKER: `Show weather picker`,
        TOOLBOX_INFO: `info`,
        TOOLBOX_ANIMATION: `animation`,
        TOOLBOX_START: `Hide/show animated particles`,
        MENU_F_MODEL: `Data`,
        MENU_U_INTERVAL: `Update interval`,
        MENU_D_UPDATED: `Updated`,
        OUTDATED: `Outdated`,
        MENU_D_REFTIME: `Reference time`,
        MENU_D_NEXT_UPDATE: `Next update expected at:`,
        ABOUT_OVERLAY: `About`,
        ABOUT_DATA: `About these data`,
        OVERLAY: `Layer`,
        MODEL: `Forecast model`,
        PROVIDER: `Provider`,
        WIND: `Wind`,
        GUST: `Wind gusts`,
        GUSTACCU: `Wind accumulation`,
        TURBULENCE: `Clear air turbulence`,
        TURBULENCE_NONE: `none`,
        TURBULENCE_LIGHT: `light`,
        TURBULENCE_MODERATE: `moderate`,
        TURBULENCE_SEVERE: `severe`,
        TURBULENCE_EXTREME: `extreme`,
        ICING2: `Icing`,
        ICING_TRACE: `trace`,
        ICING_LIGHT: `light`,
        ICING_MODERATE: `moderate`,
        ICING_HEAVY: `heavy`,
        WIND_DIR: `Wind dir.`,
        TEMP: `Temperature`,
        DISTANCE: `Distance`,
        PRESS: `Pressure`,
        CLOUDS: `Clouds, rain`,
        CLOUDS2: `Clouds`,
        CLOUD_ALT: `Cloud base`,
        CLOUDS_AND_AVIATION: `Clouds, aviation`,
        RADAR: `Weather radar`,
        RADAR_SHORT: `Radar`,
        RADAR_BLITZ: `Radar, lightning`,
        SATELLITE: `Satellite`,
        RADAR_PLUS: `Radar+`,
        TOTAL_CLOUDS: `Total clouds`,
        LOW_CLOUDS: `Low clouds`,
        MEDIUM_CLOUDS: `Medium clouds`,
        HIGH_CLOUDS: `High clouds`,
        CAPE: `CAPE Index`,
        RAIN: `Rain, snow`,
        RAIN_THUNDER: `Rain, thunder`,
        RAIN3H: `Precip. past 3h`,
        JUST_RAIN: `Rain`,
        CONVECTIVE_RAIN: `Convective r.`,
        RAINRATE: `Max. rain rate`,
        LIGHT_THUNDER: `Light thunder`,
        THUNDER: `Thunderstorms`,
        HEAVY_THUNDER: `Heavy thunder`,
        SNOW: `Snow`,
        OZONE: `Ozone layer`,
        PM2P5: `PM2.5`,
        AIR_QUALITY: `Air quality`,
        AQI: `Air quality index`,
        NO22: `NO₂`,
        AOD550: `Aerosol`,
        TCSO2: `SO₂`,
        GO3: `Surface Ozone`,
        SHOW_GUST: `force of wind gusts`,
        RH: `Humidity`,
        WAVES: `Waves`,
        WAVES2: `Waves, sea`,
        SWELL: `Swell`,
        SWELL1: `Swell 1`,
        SWELL2: `Swell 2`,
        SWELL3: `Swell 3`,
        WWAVES: `Wind waves`,
        ALL_WAVES: `All waves`,
        SWELLPER: `Swell period`,
        RACCU: `Rain accumulation`,
        RACCU_SHORT: `Rain accu.`,
        SACCU: `Snow accumulation`,
        ACCU: `Accumulations`,
        RAINACCU: `RAIN ACCUMULATION`,
        SNOWACCU: `SNOW ACCUMULATION`,
        SNOWCOVER: `Actual Snow Cover`,
        SST: `Surface sea temperature`,
        SST2: `Sea temperature`,
        WATER_TEMP: `Water temp.`,
        CURRENT: `Currents`,
        CURRENT_TIDE: `Tidal currents`,
        VISIBILITY: `Visibility`,
        SURFACE_VISIBILITY: `Surface visibility`,
        ACTUAL_TEMP: `Actual temperature`,
        SSTAVG: `Average sea temperature`,
        AVAIL_FOR: `Available for:`,
        DEW_POINT: `Dew point`,
        DEW_POINT_SPREAD: `Dew point spread`,
        ISA_DIFFERENCE: `ISA difference`,
        SLP: `Pressure (sea l.)`,
        QFE: `Station pressure`,
        SNOWDEPTH: `Snow depth`,
        NEWSNOW: `New snow`,
        SNOWDENSITY: `Snow density`,
        FLIGHT_RULES: `Flight rules`,
        CTOP: `Cloud tops`,
        FREEZING: `Freezing altitude`,
        COSC: `CO concentration`,
        DUSTSM: `Dust mass`,
        WX_WARNINGS: `Weather warnings`,
        AVALANCHE_DANGER: `Avalanche danger`,
        AVAL_NO_DATA: `No data`,
        AVAL_LOW: `Low`,
        AVAL_MODERATE: `Moderate`,
        AVAL_CONSIDERABLE: `Considerable`,
        AVAL_HIGH: `High`,
        AVAL_VERY_HIGH: `Very high`,
        WARNINGS: `Warnings`,
        PTYPE: `Precipitation type`,
        CCL: `Thermals`,
        FOG: `Fog`,
        HAZE: `Haze`,
        NO_FOG: `No fog`,
        FOG_RIME: `Fog and rime`,
        FLOOD: `Flood`,
        FIRE: `Fire`,
        EFORECAST: `Extreme forecast`,
        FZ_RAIN: `Freezing rain`,
        MX_ICE: `Mixed ice`,
        WET_SN: `Wet snow`,
        RA_SN: `Rain with snow`,
        PELLETS: `Ice pellets`,
        HAIL: `Hail`,
        ELEVATION: `Elevation`,
        LOADING_ELEVATION: `Loading elevation...`,
        MODEL_ELEVATION: `Model elevation`,
        ACTIVE_FIRES: `Active fires`,
        FIRE_INTENSITY: `Fire intensity`,
        SOIL_PROFILE_DEPTH: `Soil profile depth`,
        INTERSUCHO: `Drought monitoring`,
        INTERSUCHO_FIRE_DANGER: `Fire danger`,
        INTERSUCHO_AWD: `Moisture anomaly`,
        INTERSUCHO_AWP: `Drought intensity`,
        INTERSUCHO_AWR: `Soil moisture`,
        INTERSUCHO_FWI: `Fire spread`,
        INTERSUCHO_DFM: `Fuel moisture`,
        INTERSUCHO_40: `0-40cm`,
        INTERSUCHO_100: `0-100cm`,
        INTERSUCHO_AWP_0: `No risk`,
        INTERSUCHO_AWP_1: `Minor`,
        INTERSUCHO_AWP_2: `Mild`,
        INTERSUCHO_AWP_3: `Moderate`,
        INTERSUCHO_AWP_4: `Severe`,
        INTERSUCHO_AWP_5: `Exceptional`,
        INTERSUCHO_AWP_6: `Extreme`,
        INTERSUCHO_FWI_1: `Very low`,
        INTERSUCHO_FWI_2: `Low`,
        INTERSUCHO_FWI_3: `Moderate`,
        INTERSUCHO_FWI_4: `High`,
        INTERSUCHO_FWI_5: `Very high`,
        INTERSUCHO_FWI_6: `Extreme`,
        MORE_LAYERS: `More layers...`,
        MORE_PRODUCTS: `{{count}} more`,
        NONE: `None`,
        ALTITUDE: `Altitude`,
        SFC: `Surface`,
        CLICK_ON_LEGEND: `Click to change units`,
        ALTERNATIVE_UNIT_CHANGE: `Any Layer unit can be changed by clicking on color legend`,
        COPY_TO_C: `Copy to clipboard`,
        JUST_SEARCH: `Search`,
        FILTER: `Filter`,
        NEXT: `Next results...`,
        LOW_PREDICT: `Low predictability of forecast`,
        DAYS_AGO: `{{daysago}} days ago:`,
        SHOW_ACTUAL: `Show actual forecast`,
        SHARE: `Share`,
        COPY_LINK: `Copy link`,
        SHARE_ON: `Share on {{name}}`,
        JUST_EMBED: `Embed`,
        POSITION: `Position`,
        WIDTH: `Width`,
        HEIGHT: `Height`,
        DEFAULT_UNITS: `Default units`,
        NOW: `Now`,
        FORECAST_FOR: `Forecast for`,
        ZOOM_LEVEL: `Zoom level`,
        DETAILED: `Detailed forecast for this location`,
        PERIOD: `Period`,
        D_FCST: `Forecast for this location`,
        D_WEBCAMS: `Webcams in vicinity`,
        D_STATIONS: `Nearest weather stations`,
        D_NO_WEBCAMS: `There are no webcams around this location (or we don't know about them)`,
        D_DAYLIGHT: `image during daylight`,
        D_DISTANCE: `distance`,
        D_MILES: `miles`,
        D_MORE_THAN_HOUR: `more than hour ago`,
        D_MIN_AGO: `{{duration}} minutes ago`,
        D_SUNRISE: `Sunrise`,
        D_SUNSET: `sunset`,
        D_DUSK: `dusk`,
        D_SUN_NEVER_SET: `Sun never set`,
        D_POLAR_NIGHT: `Polar night`,
        D_LT2: `local time`,
        D_FAVORITES: `Add to Favorites`,
        D_FAVORITES2: `Remove from Favorites`,
        D_WAVE_FCST2: `Waves and sea`,
        D_MISSING_CAM: `Add new webcam`,
        D_HOURS: `Hours`,
        D_TEMP2: `Temp.`,
        D_PRECI: `Precip.`,
        D_ABOUT_LOC: `About this location`,
        D_ABOUT_LOC2: `About location`,
        D_TIMEZONE: `Timezone`,
        D_WEBCAMS_24: `Show last 24 hours`,
        D_FORECAST_FOR: `{{duration}} days forecast`,
        D_1H_FORECAST: `1h forecast`,
        D_STEPS_1_HOUR: `1 hour`,
        D_STEPS_3_HOURS: `3 hours`,
        D_STEPS_FORECAST: `forecast`,
        D_DISPLAY_AS: `Display as:`,
        D_FCST_MODEL: `Fcst model:`,
        D_SHOW_SUN_POSITION: `Show sun position on map`,
        DURATION: `Duration`,
        E_MESSAGE: `Awesome weather forecast at`,
        METAR_VAR: `Variable`,
        DURATION_MIN: `{minutes}m`,
        DURATION_HOURS: `{hours}h`,
        DURATION_H_M: `{hours}h {minutes}m`,
        METAR_MIN_AGO: `{DURATION}m ago`,
        METAR_HOURS_AGO: `{DURATION}h ago`,
        METARS_H_M_AGO: `{DURATION}h {DURATIONM}m ago`,
        METARS_DAYS_AGO: `{DURATION} days ago`,
        METAR_MIN_LATER: `in {DURATION}m`,
        METAR_HOURS_LATER: `in {DURATION}h`,
        METARS_H_M_LATER: `in {DURATION}h {DURATIONM}m`,
        METARS_DAYS_LATER: `in {DURATION} days`,
        DEVELOPED: `Developed with`,
        DELETE: `Delete`,
        FAVS_SYNCHRO_ERROR_TITLE: `Favorites sync error`,
        SHOW_ON_MAP: `Display on map`,
        POI_STATIONS: `Weather stations`,
        POI_AD: `Airports`,
        POI_AIRQ: `Air quality stations`,
        POI_CAMS: `Webcams`,
        POI_PG: `Paragliding spots`,
        POI_KITE: `Kite/WS spots`,
        POI_SURF: `Surfing spots`,
        POI_EMPTY: `Empty map`,
        POI_WIND: `Reported wind`,
        POI_WIND_SHORT: `Wind`,
        POI_TEMP: `Reported temp.`,
        POI_TEMP_SHORT: `Temperature`,
        POI_PRECIP: `Recent precip.`,
        POI_PRECIP_SHORT: `Precipitation`,
        POI_FAVS: `My favorites`,
        POI_FCST: `Forecasted weather`,
        POI_TIDE: `Tide forecast`,
        POI_RADIOSONDE: `Radiosondes`,
        P_ANDROID_APP: `Windy for Android, free on Google Play`,
        ND_MODEL: `Forecast model`,
        ND_COMPARE: `Compare forecasts`,
        ND_DISPLAY: `Display`,
        ND_DISPLAY_BASIC: `Basic`,
        S_ADVANCED_SETTINGS: `Advanced settings`,
        S_COLORS: `Customize color scale`,
        S_SAVE: `Save`,
        S_SAVE2: `Login/Register to save all your settings to the cloud`,
        S_SPEED: `Speed`,
        S_DELETE_INFO: `Delete all my data from this device`,
        U_LOGIN: `Login`,
        U_LOGOUT: `Logout`,
        U_PROFILE: `My profile`,
        OVR_RECOMENDED: `Recommended for:`,
        OVR_ALL: `All`,
        OVR_FLYING: `Flying`,
        OVR_WATER: `Water`,
        OVR_SKI: `Ski`,
        MSG_OFFLINE: `WOW it appears that you are offline :-(`,
        MSG_ONLINE_APP: `Online again, click here to reload app :-)`,
        MSG_LOGIN_SUCCESFULL: `You have successfully logged in!`,
        MSG_INSTALLING_NEW_VERSION: `Close other Windy.com tabs and reload to update to the new version`,
        FIELD_CANNOT_BE_EMPTY: `This field can't be empty`,
        FIELD_INVALID_EMAIL: `This doesn't look like an email address`,
        PASSWORD_EMPTY: `Password can't be empty`,
        PASSWORD_SHORT: `Password is too short`,
        PASSWORD_MISSING_DIGIT: `Password is missing a digit (0-9)`,
        PASSWORD_MISSING_UPPERCASE: `Password is missing an uppercase letter (A-Z)`,
        PASSWORD_MISSING_LOWERCASE: `Password is missing a lowercase letter (a-z)`,
        PASSWORD_DO_NOT_MATCH: `Password and confirmation don't match`,
        ALERTS_LINK_SHORT: `Alert for this spot`,
        MY_ALERTS: `My Alerts`,
        MY_LIVE_ALERTS: `Live alerts`,
        MY_FAVS: `My Favorites`,
        FAVS_PIN_HOMEPAGE: `Pin to homepage`,
        FAVS_UNPIN_HOMEPAGE: `Unpin from homepage`,
        ACTIVE_ALERTS: `active alerts`,
        DIRECTION_N: `N`,
        DIRECTION_NE: `NE`,
        DIRECTION_E: `E`,
        DIRECTION_SE: `SE`,
        DIRECTION_S: `S`,
        DIRECTION_SW: `SW`,
        DIRECTION_W: `W`,
        DIRECTION_NW: `NW`,
        DIRECTIONS: `Directions`,
        DIRECTIONS_ANY: `Any direction`,
        DIRECTIONS_SELECT: `Select directions`,
        ACTIVATE: `Activate`,
        DEACTIVATE: `Deactivate`,
        REGISTER: `Register`,
        REGISTER_HERE: `Register here`,
        DONT_HAVE_ACCOUNT: `Don't have an account?`,
        OR: `or`,
        JUST_LOGIN: `Login`,
        MY_ACCOUNT: `My account`,
        EDIT_ALERT: `Edit alert`,
        ADD_ALERT: `Create alert`,
        ALERT_MIGRATE: `Migrate alert`,
        HOME: `Home`,
        MAP: `Map`,
        MORE: `More`,
        LESS: `Less`,
        COMPARE: `Compare`,
        PRESS_ISOLINES: `Pressure isolines`,
        PART_ANIMATION: `Particles animation`,
        CAMS_PREVIEWS: `Webcams previews`,
        R_TIME_RANGE: `Time range`,
        MY_LOCATION: `My location`,
        ARTICLES: `Articles`,
        NEW: `New!`,
        WHAT_IS_NEW: `What is new:`,
        WHATS_NEW_THANK_YOU: `Thank you for using <b>Windy Premium</b> 👑.<br />Awesome people like you make <b>Windy.com</b> possible!`,
        WHATS_NEW_UPGRADE: `Upgrade to Windy Premium and enjoy 3× more daily updates, a 15-day weather forecast, full-year access to radar and satellite history, plus detailed wave and tide forecasts.`,
        PRIVACY: `Privacy protection`,
        CONSENT: `Cookie consent`,
        TERMS_OF_USE: `Terms of Use`,
        PRIVACY_POLICY: `Privacy policy`,
        SOUNDING: `Sounding`,
        SOUND_ON: `Sound`,
        BLITZ_ON: `Show lightning`,
        WFORECAST: `weather forecast`,
        TITLE: `Wind map & weather forecast`,
        HURR_TRACKER: `Hurricane tracker`,
        HURR_TRACKER_SHORT: `Hurr. tracker`,
        TOC: `Terms and conditions`,
        SEND: `Send`,
        SEARCH_LAYER: `Search layer...`,
        CANCEL_SEARCH: `Cancel search`,
        NOTHING_FOUND: `Nothing found`,
        P_LOCATION: `Please allow Windy to use location services (GPS) while using the app, so we can show weather at your location. We do not store your location at our servers.`,
        DONE: `Done`,
        HMAP: `Outdoor map`,
        LICENCE: `Licence`,
        AIRQ_RANGE_GOOD: `Good`,
        AIRQ_RANGE_MODERATE: `Moderate`,
        AIRQ_RANGE_UNHEALTHY_SENSITIVE: `Unhealthy for sensitive`,
        AIRQ_RANGE_UNHEALTHY: `Unhealthy`,
        AIRQ_RANGE_VERY_UNHEALTHY: `Very unhealthy`,
        AIRQ_RANGE_HAZARDOUS: `Hazardous`,
        POI_MAX_LAYERS: `Maximum is {{num}} favorite layers. Remove some to add new ones.`,
        MENU_WATCHFACES: `Apple Watch Faces`,
        MENU_WIDGETS: `Widgets`,
        GARMIN_PLUGIN_TITLE_WATCH: `Garmin Watch`,
        GARMIN_PLUGIN_TITLE_EDGE: `Garmin Edge`,
        MENU_TITLE_ADDONS: `App add-ons`,
        WIND_SPEED: `Wind speed`,
        SOLARPOWER: `Solar power`,
        WAVE_POWER: `Wave power`,
        UVINDEX: `UV Index`,
        WETBULB_TEMP: `Wet-bulb temperature`,
        UV_LOW: `Low`,
        UV_MODERATE: `Moderate`,
        UV_HIGH: `High`,
        UV_VERY_HIGH: `Very high`,
        UV_EXTREME: `Extreme`,
        UV_HIGHEST: `Highest`,
        SUB_GO: `Go Premium`,
        SUB_RENEW: `Renew Premium`,
        SUB_HAVE_REFTIME: `Premium users have just received a new forecast update`,
        SUB_GLOBE_FREE_LIMIT: `Full version of 3D mode is available only to Premium users.`,
        SUB_REASON_TIDES: `<strong>Tide forecast</strong> anywhere in the world`,
        SUB_REASON_FREQUENCY: `Forecast <strong>updates</strong> at least <strong>4 times a day</strong>`,
        SUB_REASON_GRANULARITY: `<strong>1-hour</strong> forecast step`,
        SUB_REASON_LONGTERM: `<strong>10-day forecast</strong> outlook`,
        SUB_OTHER_BENEFITS: `And many other <strong>benefits</strong>`,
        SUB_SEE_DETAILS: `See details`,
        SUB_CUFFS_GRACED: `We're having issues with renewing your subscription`,
        SUB_CUFFS_PAUSED: `Your Premium is paused`,
        SUB_CUFFS_CANCELED_1: `Your subscription ends soon`,
        SUB_CUFFS_CANCELED_2: `Your subscription ends in {{count}} days`,
        SUB_CUFFS_CANCELED_3: `Your subscription ends in {{count}} hours`,
        SUB_CUFFS_CANCELED_4: `Your subscription ends at any moment`,
        SUB_CUFFS_FORECAST: `Soon, you will no longer have access to 10-day forecast`,
        SUB_CUFFS_FEATURE: `Soon, you will no longer have access to this feature.`,
        SUBSCRIPTION: `Subscription`,
        MY_SUBSCRIPTION: `My subscription`,
        RPLANNER: `Route planner`,
        DATA_NOT_AVBL: `Data not available for this location`,
        PROMO_LONG_PRESS_HOME: `Use <strong>long tap</strong> on home button to open detailed forecast for your location.`,
        PROMO_PICKER: `<span class="dotted">Open Settings</span> to change the auto closing time of weather picker.`,
        DETAIL_TIME_ON_MAP: `Time of forecast on map`,
        DETAIL_DRAG_CHECKBOX: `Move the map to change the forecast location`,
        DETAIL_FORECAST_LOADING_FAILED: `Error loading forecast for {{model}}`,
        DETAIL_FORECAST_RETRY: `Retry`,
        DETAIL_MODEL_UNAVAILABLE: `Selected model ({{model}}) is unavailable in current location. Reverting to previous model ({{prevModel}}).`,
        DETAIL_SET_UP_ALERT: `Set up Windy Alert for this location and never miss your desired conditions.`,
        DETAIL_TIDE_FORECAST_NOT_AVAILABLE: `We do not provide tide forecast for this location`,
        DETAIL_ERROR_LOADING_WIND_DATA: `Error loading wind data for this model`,
        METAR_HELIPORTS: `Display heliports`,
        MAP_AIRSPACES: `VFR airspaces map`,
        GETTING_LOCATION: `Getting your location...`,
        GETTING_LOCATION_ERROR: `Failed to determine your location. Make sure Windy.com has permission to access your location`,
        GETTING_LOCATION_TIMEOUT: `Failed to determine your location`,
        GETTING_LOCATION_FALLBACK: `Unable to get current location, using your last known position`,
        WAVESTIDES: `Wave&Tide`,
        WAVESTIDES_LONG: `Waves & Tides`,
        TIDES: `Tides`,
        WAVESTIDES_BROWSER_TITLE: `Wave and tide forecast for {{name}}`,
        PARAGLIDING_BROWSER_TITLE: `Paragliding forecast for {{name}}`,
        WIND_BROWSER_TITLE: `Wind and kitesurfing forecast for {{name}}`,
        VIEWS: `views`,
        ZOOM_IN: `Zoom in`,
        ZOOM_OUT: `Zoom out`,
        MODE_2D3D: `Switch 2D / 3D mode`,
        AREA: `Area`,
        SUB_EXTENDED: `Subscribe to Windy Premium to get access to extended weather forecast.`,
        HEATMAP: `City heatmaps`,
        VIBRATE: `Vibrate`,
        DISPLAY_STYLE: `Display style`,
        ARCHIVE: `Archive`,
        CLOSE_ARCHIVE: `Close archive`,
        MSG_EXTERNAL_PLUGIN_UNPUBLISHED: `Unfortunately, plugin {{title}} was unpublished by the author and is no longer available.`,
        MSG_EXTERNAL_PLUGIN_UPDATE_AVAILABLE: `New version of the plugin {{title}} is available. Do you want to update?`,
        BROWSER_SUPPORT_ERROR: `Your {{platform}} does not support {{technology}}. Some features may not work correctly.`,
        POLLEN_AIRQ: `Pollen&AirQ`,
        POLLEN_AIRQ_LONG: `Pollen & Air Quality`,
        POLLEN_ALDER: `Alder pollen`,
        POLLEN_BIRCH: `Birch pollen`,
        POLLEN_GRASS: `Grass pollen`,
        POLLEN_MUGWORT: `Mugwort pol.`,
        POLLEN_OLIVE: `Olive pollen`,
        POLLEN_RAGWEED: `Ragweed pol.`,
        DUSTSM_SHORT: `Dust`,
        POLLEN_ALDER_SHORT: `Alder`,
        POLLEN_BIRCH_SHORT: `Birch`,
        POLLEN_GRASS_SHORT: `Grass`,
        POLLEN_MUGWORT_SHORT: `Mugwort`,
        POLLEN_OLIVE_SHORT: `Olive`,
        POLLEN_RAGWEED_SHORT: `Ragwe.`,
        TIDE_HIGH: `High Tide`,
        TIDE_LOW: `Low Tide`,
        MAX_EBB: `Max Ebb`,
        MAX_FLOOD: `Max Flood`,
        MIN_EBB: `Min Ebb`,
        MIN_FLOOD: `Min Flood`,
        SLACK_EBB: `Slack, Ebb Begins`,
        SLACK_FLOOD: `Slack, Flood Begins`,
        FLOOD_TIDE: `Flood tide`,
        EBB_TIDE: `Ebb tide`,
        MY_FILES: `My files`,
        LATEST_FILES_FROM_COMMUNITY: `Latest files from Community`,
        LOADING_MORE_UPLOADS: `Loading more uploads`,
        CHOOSE_A_FILE: `Choose a file`,
        OR_DROP_FILE_HERE: `or drop file here.`,
        UPLOAD_KML_GPX: `Upload, display and share your KML, GPX or GeoJSON.`,
        UPLOAD_EXTENSIONS: `Supported extensions: .geojson, .json, .gpx, .kml, .xml`,
        DESCRIPTION: `Description`,
        UPLOAD_DESCRIBE_FILE: `Describe content of your file (required)`,
        FILE_NAME: `File name`,
        SIZE: `Size`,
        TYPE: `Type`,
        SHOW_SPEED_IN_MAP: `Show speed in map`,
        MAKE_DATA_PRIVATE: `Make data private`,
        REQUIRES_PREMIUM: `Requires Premium`,
        UPLOAD_SIZE_LIMIT: `Files larger than 5MB cannot be uploaded to the cloud.`,
        OPEN_IN_RPLANNER: `Open in route planner`,
        SAVE_FILE_TO_CLOUD: `Save file to cloud`,
        UPLOAD_BEING_PROCESSED: `Your upload is being processed.`,
        FILE: `File`,
        UPLOADED: `Uploaded`,
        DOWNLOAD_FILE: `Download file`,
        DEVELOP_PLUGIN: `Develop your own plugin`,
        PLUGINS_DISCUSSION: `Windy Plugins discussion`,
        PLUGINS_ERROR_INSTALLING: `Error installing plugin`,
        PLUGINS_INSTALLED: `Your plugin was installed and added to the main menu`,
        PLUGINS_INSTALL: `Install plugin`,
        PLUGINS_INSTALL_UNTRUSTED: `Install untrusted plugin`,
        PLUGINS_NAME: `Name`,
        PLUGINS_LOAD_URL: `Load plugin directly from URL`,
        PLUGINS_UNINSTALL: `Uninstall plugin`,
        PLUGINS_CONFIRM_UNINSTALL: `Are you sure you want to uninstall this plugin?`,
        PLUGINS_UNTRUSTED: `Installing plugins from untrusted sources can be dangerous. Install plugins only from sources you trust.`,
        PLUGINS_URL: `URL of the plugin`,
        OPEN_PLUGIN: `Open plugin`,
        VERSION: `Version`,
        UPDATED: `Updated`,
        AUTHOR: `Author`,
        SOURCE_CODE: `Source code`,
        INSTALLED: `installed`,
        PROFESSIONAL_FIRST: `Professional first`,
        BY_DISTANCE: `By distance`,
        PLAY_WITH_FORECAST: `Play with forecast`,
        SATELLITE_OUTAGE_MESSAGE: `There is an outage of our data source for some satellites.`,
        NEWSLETTER_CONSENT: `Subscribe to newsletter`,
        SET_NOTIFICATIONS: `Set notifications`,
        REPORT_ISSUE: `Report Issue`,
        TIME: `Time`,
        TRAJECTORIES_INCOMPLETE_DATA: `Data for some altitude levels is missing, try changing parameters (model, timestamp, levels)`,
        TRAJECTORIES_FETCH_ERROR: `Failed to fetch wind trajectories.`,
        TRAJECTORIES_UNSUPPORTED_LAYER: `Wind trajectories are not available on this layer.`,
        TRAJECTORIES_PREMIUM_PROMO: `Go Premium for longer paths`
    },
    hr = b({
        getUrlOfLangFile: () => wr,
        loadLangFile: () => Tr,
        navigatorPreferredLang: () => br,
        supportedLangFiles: () => _r,
        t: () => P,
        translateDocument: () => Dr
    });
const gr = {},
    _r = pr,
    P = mr;
let vr = `en`;
const yr = M.get(`lang`),
    br = (navigator.languages ? navigator.languages[0] : navigator.language) || `en`,
    xr = _n.exec(bn);
let Sr = xr ? xr[1] : br;
yr !== `auto` && Rt(yr) && (Sr = yr), Sr && (Rt(Sr) ? vr = Sr : (Sr = Sr.replace(/-\S+$/, ``), vr = Rt(Sr) ? Sr : `en`));

function Cr(e = ``) {
    return /\|/.test(e) ? e.replace(/(\w+)\|(\w+):(\w+)/, (t, n, r, i) => {
        let a = P[n];
        return a && i ? a.replace(/\{\{[^}]+\}\}/g, i) : e
    }) : P[e] || e
}
const wr = e => `/${xe}/lang/${e === `main` ? `` : `${e}/`}${vr}.js`,
    Tr = e => {
        if (vr === `en` && e === `main`) return Promise.resolve();
        if (e in gr) return gr[e];
        {
            let t = new Promise((t, n) => {
                let r = wr(e);
                import(r).then(e => {
                    Object.assign(P, e.default), t()
                }).catch(t => {
                    O(`trans`, `Failed to load lang file`, t, {
                        tags: {
                            id: e
                        },
                        extra: {
                            filename: r
                        }
                    }), n()
                })
            });
            return gr[e] = t, t
        }
    },
    Er = [`t`, `afterbegin`, `beforeend`, `tooltipsrc`],
    Dr = e => {
        Er.forEach(t => {
            let n = e.querySelectorAll(`[data-${t}]`);
            for (let e = 0, r = n.length; e < r; e++) {
                let r = n[e],
                    i = Cr(r.dataset[t]);
                switch (t) {
                    case `t`:
                        /</.test(i) ? r.innerHTML = i : r.textContent = i;
                        break;
                    case `tooltipsrc`:
                        r.dataset.tooltip = i;
                        break;
                    case `afterbegin`:
                        r.firstChild && r.firstChild.nodeType == 3 && r.removeChild(r.firstChild), r.insertAdjacentHTML(t, i);
                        break;
                    case `beforeend`:
                        r.lastChild && r.lastChild.nodeType == 3 && r.removeChild(r.lastChild), r.insertAdjacentHTML(t, i);
                        break
                }
            }
        })
    };
Tr(`main`).then(() => {
    document.documentElement.lang = vr, Dr(document.body), M.set(`usedLang`, vr, {
        forceChange: !0
    })
});
var Or = b({
        Window: () => kr
    }),
    kr = class e {
        constructor(t) {
            var n, r, i, a, o, s, c, l, u, d;
            C(this, `closingTimer`, null), C(this, `timeoutTimer`, null), C(this, `bindedClose`, void 0), C(this, `ident`, void 0), C(this, `domEl`, void 0), C(this, `attachPoint`, void 0), C(this, `keyboard`, void 0), C(this, `closeOnClick`, void 0), C(this, `timeout`, void 0), C(this, `isOpen`, void 0), C(this, `bodyClass`, void 0), C(this, `node`, void 0), C(this, `className`, void 0), C(this, `htmlID`, void 0), C(this, `html`, void 0), C(this, `noAnimation`, void 0), this.initProperties(), this.ident = t.ident, this.attachPoint = (n = t.attachPoint) == null ? this.attachPoint : n, this.bodyClass = (r = t.bodyClass) == null ? `on${e.iAm}-${this.ident}` : r, this.className = t.className, this.closeOnClick = (i = t.closeOnClick) == null ? this.closeOnClick : i, this.html = t.html, this.domEl = (a = t.domEl) == null ? this.domEl : a, this.htmlID = t.htmlID, this.ident = t.ident, this.keyboard = (o = t.keyboard) == null ? this.keyboard : o, this.timeout = (s = t.timeout) == null ? this.timeout : s, this.noAnimation = t.noAnimation, this.onclose = (c = t.onclose) == null ? this.onclose : c, this.onclosed = (l = t.onclosed) == null ? this.onclosed : l, this.onopen = (u = t.onopen) == null ? this.onopen : u, this.unmount = (d = t.unmount) == null ? this.unmount : d
        }
        close(e) {
            var t, n;
            if (this.isOpen) {
                if (this.isOpen = !1, e != null && e.disableClosingAnimation) {
                    var r;
                    (r = this.node) == null || r.classList.add(`no-animation`)
                }
                document.body.classList.remove(this.bodyClass), (t = this.node) == null || t.classList.remove(`open`), this.onclose(e), e != null && e.disableClosingAnimation ? (this.onclosed(), this.unmount(), setTimeout(() => {
                    var e;
                    (e = this.node) == null || e.classList.remove(`no-animation`)
                }, 50)) : this.closingTimer = setTimeout(() => {
                    this.onclosed(), this.unmount()
                }, 500), this.removeHooks(), !this.closeOnClick && !(e == null || (n = e.ev) == null) && n.stopPropagation && e.ev.stopPropagation()
            }
        }
        open(e) {
            if (this.closingTimer && clearTimeout(this.closingTimer), this.timeoutTimer && clearTimeout(this.timeoutTimer), this.isOpen) return this;
            if (this.mount(), document.body.classList.add(this.bodyClass), this.addHooks(), e != null && e.disableOpeningAnimation) {
                var t;
                (t = this.node) == null || t.classList.add(`no-animation`, `open`), setTimeout(() => {
                    var e;
                    (e = this.node) == null || e.classList.remove(`no-animation`)
                }, 50)
            } else setTimeout(() => {
                var e;
                (e = this.node) == null || e.classList.add(`open`)
            }, 50);
            return this.isOpen = !0, this.timeout && (this.timeoutTimer = setTimeout(this.bindedClose, this.timeout)), this.onopen(), this
        }
        onopen() {}
        onclose(e) {}
        onclosed() {}
        mount() {
            this.node || this.html === void 0 || (this.node = this.createNode(), Dr(this.node))
        }
        unmount() {
            var e;
            this.node && ((e = this.node.parentNode) == null || e.removeChild(this.node), this.node = void 0)
        }
        initProperties() {
            this.domEl = null, this.closingTimer = null, this.timeoutTimer = null, this.attachPoint = le, this.keyboard = !1, this.closeOnClick = !1, this.timeout = 0, this.isOpen = !1, this.bindedClose = e => {
                if (this.closeOnClick === `outside`) {
                    let t = e.target instanceof HTMLElement ? e.target : null;
                    for (; t;) {
                        if (t === this.node) return;
                        t = t.parentElement
                    }
                }
                this.close.call(this, {
                    ev: e
                })
            }
        }
        createNode(t) {
            let n = document.createElement(`div`),
                r = t || this.html || ``;
            n.id = this.htmlID || `${e.iAm}-${this.ident}`, this.className && (n.className = this.className);
            let i = document.createElement(`div`);
            i.className = `closing-x`, i.onclick = this.bindedClose, n.innerHTML = r, n.appendChild(i);
            let a = this.domEl || Kt(this.attachPoint);
            if (!a) throw Error(`Cannot create node for Window ${this.ident}, target element does not exist.`);
            return a.appendChild(n), n
        }
        removeHooks() {
            this.closeOnClick && (document.removeEventListener(`mousedown`, this.bindedClose, !0), document.removeEventListener(`touchstart`, this.bindedClose, !0)), this.keyboard && this.node && this.node.removeEventListener(`keydown`, this.keyCatcher)
        }
        addHooks() {
            this.closeOnClick && (document.addEventListener(`mousedown`, this.bindedClose, !0), document.addEventListener(`touchstart`, this.bindedClose, !0)), this.keyboard && this.node && this.node.addEventListener(`keydown`, this.keyCatcher)
        }
        keyCatcher(e) {
            e.stopImmediatePropagation()
        }
    };
C(kr, `iAm`, `window`);
var Ar = b({
    displayTopMessage: () => Nr
});
let jr = null;
const Mr = {
        success: `bg-ok`,
        error: `bg-error`,
        warning: `bg-orange`
    },
    Nr = async ({
        html: e,
        timeout: t,
        onclick: n,
        type: r
    }) => {
        jr && jr.isOpen && (jr.close({
            disableClosingAnimation: !0
        }), jr = null, await fn(200));
        let i = [`top-message`, `fg-white`, Mr[r]];
        return n && i.push(`clickable`), jr = new kr({
            ident: `top-message`,
            className: i.join(` `),
            html: e,
            timeout: t,
            onopen() {
                n && this.node && (this.node.onclick = () => n())
            },
            onclosed: () => {
                jr && (jr = null)
            }
        }), jr.open(), jr
    };
var Pr = b({
    createEventSource: () => qr,
    del: () => Qr,
    get: () => F,
    getURL: () => Kr,
    head: () => ni,
    patch: () => ti,
    post: () => $r,
    put: () => ei
});
const Fr = new fr(50);
let Ir = ``,
    Lr = 0;
const Rr = ur(),
    zr = M.get(`sessionCounter`),
    Br = RegExp(`^/users/`, `i`),
    Vr = RegExp(`^https://account.windy.com/`, `i`),
    Hr = RegExp(`^/citytile/`, `i`),
    Ur = e => {
        Ir = Vt({
            token2: M.get(`userToken`) || `pending`,
            uid: Rr,
            sc: zr,
            pr: +e,
            v: he
        })
    },
    Wr = e => !e.startsWith(`http`) && !/^v\/\d*/.test(e),
    Gr = e => Wr(e) || Hr.test(e) || e.startsWith(`http://localhost:3000`) || /^https:\/\/(account|dev|node|staging|dev-windy-backend-\S+)\.windy\.com(:\d+)?\//.test(e),
    Kr = e => Gr(e) ? (e.startsWith(`http`) || (e = zt(`https://node.windy.com`, e)), Ir && (e = Bt(e, Ir)), e = Bt(e, `poc=${++Lr}`), e) : e;
Ur(!0), M.on(`userToken`, () => Ur(!1));
const qr = (e, t = {}) => {
        try {
            let n = Kr(e),
                r = new EventSource(n, t);
            return r.addEventListener(`error`, n => {
                console.error(`EventSource error event for url=${e}, options=${JSON.stringify(t)}`, n)
            }), r
        } catch (e) {
            return console.error(`Failed to create EventSource`, e), null
        }
    },
    Jr = e => ({
        status: e.status,
        data: e.data && e.isJSON ? JSON.parse(e.data) : e.data
    }),
    Yr = e => Promise.resolve(e) === e,
    Xr = async (e, t, n, r) => {
        try {
            let a = await e;
            if (a.ok || a.status === 304) {
                let e = {
                    status: a.status,
                    data: void 0
                };
                try {
                    if (t.binary) e.data = await a.arrayBuffer();
                    else if (n) {
                        let t = await a.text();
                        e.data = window.atob(t), e.isJSON = !0
                    } else {
                        var i;
                        e.data = await a.text(), e.isJSON = t.json || ((i = a.headers.get(`content-type`)) == null ? void 0 : i.includes(`application/json`))
                    }
                    return t.cache && (e.expire = (t.ttl || 3e5) + Date.now(), Fr.put(r, e)), Jr(e)
                } catch (e) {
                    throw new qe(a.status, e.message)
                }
            } else {
                let e = await a.text();
                throw new qe(a.status, `Request failed for URL ${r}`, e == null ? a.statusText : e)
            }
        } catch (e) {
            var a;
            t.cache && Fr.remove(r);
            let n = (a = e == null ? void 0 : e.message) == null ? e : a,
                i = e.name === `AbortError` || /abort/.test(n);
            if ((!(e instanceof qe) || i) && ir(), e instanceof qe) throw e;
            var o;
            throw new qe((o = e.status) == null ? 0 : o, n)
        }
    }, Zr = (e, t, n = {}) => {
        var r, i;
        if (typeof n.qs == `object`) {
            let e = Vt(n.qs);
            e && (t = Bt(t, e))
        }
        let a = Br.test(t) || Vr.test(t) || ((r = n.withCredentials) == null ? !1 : r),
            o = t;
        if (n.cache === void 0 && e === `GET` && (n.cache = !0), n.cache) {
            let e = Fr.get(t);
            if (e) {
                if (Yr(e)) return e;
                {
                    let {
                        expire: n
                    } = e;
                    if (n && Date.now() > n) Fr.remove(t);
                    else {
                        let t = Jr(e);
                        return Promise.resolve(t)
                    }
                }
            }
        }
        let s = new Headers(n.customHeaders || {}),
            c, l = !1;
        if (Gr(t) && (t = Kr(t), /^\/?forecast\//.test(o))) {
            let [, e, n, r, i] = /^(.+)\/forecast\/([^/]+)\/([^/]+)\/(.+)$/.exec(t) || [], a = `Zm9yZWNhc3Q/${window.btoa(r).replace(/=/g, ``)}`, o = `${n}/${r}/${i}`;
            t = `${e}/${a}/${window.btoa(o).replace(/=/g, ``)}`, l = !0
        }
        if (t = encodeURI(t), a) {
            c = `include`;
            let e = M.get(`userToken`);
            e && s.set(`Authorization`, `Bearer ${e}`)
        }!(n == null || (i = n.customHeaders) == null) && i.Accept || s.set(`Accept`, `application/json binary/hcadae$indcd28`);
        let u;
        n.data && [`POST`, `PUT`, `PATCH`].includes(e) && (n.data instanceof FormData ? u = n.data : (s.set(`Content-Type`, `application/json; charset=utf-8`), u = JSON.stringify(n.data)));
        let d = Xr(n.ongoingFetchRequest || fetch(t, {
            body: u,
            credentials: c,
            headers: s,
            method: e,
            signal: n.abortSignal
        }), n, l, o);
        return n.cache && Fr.put(o, d), d
    }, F = Zr.bind(null, `GET`), Qr = Zr.bind(null, `DELETE`), $r = Zr.bind(null, `POST`), ei = Zr.bind(null, `PUT`), ti = Zr.bind(null, `PATCH`), ni = Zr.bind(null, `HEAD`);

function ri(e, t, n, r) {
    var i;
    let a = !!t.isDiscrete,
        o = !a && ((i = t.description) == null ? void 0 : i.length) > 1,
        s;
    if (a) s = ai(t);
    else {
        if (o && !r) {
            O(`renderLegend`, `Slected metric is required for legends with more than one metric`);
            return
        } else if (!n) {
            O(`renderLegend`, `Color is required for gradient legends`);
            return
        }
        s = ii(n, t, r)
    }
    e.style.background = s.background, e.innerHTML = s.content, se(e, !o, `one-metric`), se(e, a, `discrete-metric`)
}

function ii(e, t, n) {
    let {
        description: r,
        lines: i
    } = t, a = i.length, o = n ? r.indexOf(n) : 0, s = r[o], c = 100 / (i.length + 1), l = [];
    e.getColor();
    let u = e.color(i[0][0]);
    l.push(u, u, u);
    let d = `<span style="width:${c}%">${s}</span>`;
    for (let t = 0; t < a; t++) {
        let n = i[t][0],
            r = i[Math.min(t + 1, a - 1)][0],
            s = e.color(n),
            u = e.color(.5 * (n + r));
        l.push(s, u), d += `<span style="width: ${c}%">${i[t][1 + o]}</span>`
    }
    return {
        background: `linear-gradient(to right, ${l.join(`,`)})`,
        content: d
    }
}

function ai(e) {
    let {
        labels: t,
        hasEqualItemsWidth: n
    } = e, r = n ? `width: ${100 / t.length}%;` : ``;
    return {
        background: ``,
        content: e.labels.map(e => {
            let [t, i] = e;
            return `<span style="background: ${i}; ${n ? r : ``}">${P[t]}</span>`
        }).join(``)
    }
}
var oi = b({
    DD2DMS: () => Ci,
    animateViews: () => ki,
    countdown: () => bi,
    euTime: () => ci,
    formatElapsedMs: () => xi,
    getDirFunction: () => _i,
    getHoursFunction: () => li,
    hourMinuteUTC: () => fi,
    hourUTC: () => di,
    howOld: () => yi,
    m2feetFormatted: () => Ai,
    obsoleteClass: () => vi,
    seoLang: () => Di,
    seoString: () => Ei,
    seoUrlString: () => Ti,
    stringDir: () => hi,
    thousands: () => pi,
    tsToFormattedTime: () => ui,
    utcOffsetStr: () => wi
});
const si = (e, t) => {
        let n = t === void 0 ? `` : `:` + xt(t);
        return `${e % 12 || 12}${n}${e >= 12 ? ` PM` : ` AM`}`
    },
    ci = (e, t) => e + `:` + (t === void 0 ? `00` : xt(t)),
    li = () => M.get(`hourFormat`) === `12h` ? si : ci,
    ui = e => {
        let t = new Date(e);
        return li()(t.getHours(), t.getMinutes())
    },
    di = e => xt(new Date(e).getUTCHours()) + `:00Z`,
    fi = e => {
        let t = new Date(e);
        return `${xt(t.getUTCHours())}:${xt(t.getUTCMinutes())}Z`
    },
    pi = e => e == null ? `` : e.toString().replace(/\B(?=(\d{3})+(?!\d))/g, `,`),
    mi = [`N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`, `N`],
    hi = e => P[`DIRECTION_${mi[Math.floor((+e + 22.5) / 45)]}`] || `-`,
    gi = e => `${e}°`,
    _i = () => M.get(`numDirection`) ? gi : hi,
    vi = (e, t = 30) => {
        let n = (Date.now() / 1e3 - e) / 60;
        return n < t * .3 ? `fresh` : n < t ? `normal` : `obsolete`
    },
    yi = e => {
        let t = !1,
            n = -1,
            r = 1440;
        if (`diffMin` in e) n = +e.diffMin;
        else if (`ts` in e) n = Math.floor((Date.now() - +e.ts) / 6e4);
        else if (`min` in e) n = Math.floor(Date.now() / 6e4 - e.min);
        else if (`ux` in e) n = Math.floor((Date.now() / 1e3 - e.ux) / 60);
        else return ``;
        if (n < 0) {
            var i;
            (i = e.useFuture) == null || i ? t = !0 : n = 0
        }
        if (n = Math.abs(n), e && e.translate) {
            if (n === 0) return P.NOW;
            if (n < 60) return St(t ? P.METAR_MIN_LATER : P.METAR_MIN_AGO, {
                DURATION: n
            });
            if (n < 240) {
                let e = Math.floor(n / 60),
                    r = n - 60 * e;
                return St(t ? P.METARS_H_M_LATER : P.METARS_H_M_AGO, {
                    DURATION: e,
                    DURATIONM: r
                })
            } else if (n < r) return St(t ? P.METAR_HOURS_LATER : P.METAR_HOURS_AGO, {
                DURATION: Math.floor(n / 60)
            });
            else return St(t ? P.METARS_DAYS_LATER : P.METARS_DAYS_AGO, {
                DURATION: Math.floor(n / r)
            })
        } else {
            let i = n >= r ? `${Math.floor(n / r)}d` : n < 60 ? `${Math.floor(n)}m` : `${Math.floor(n / 60)}h ${Math.floor(n % 60)}m`;
            return (e.useAgo && t ? `in ` : ``) + i + (e.useAgo && !t ? ` ago` : ``)
        }
    },
    bi = (e, t = {}) => {
        let n = Math.abs(e - Date.now()),
            r = Math.floor(n / tt),
            i = Math.floor(n % tt / T),
            a = Math.floor(n % T / et),
            o = Math.floor(n % et / 1e3);
        return t.showSeconds ? !r && !i && !a && !o ? `1s` : `${r ? `${r} days ` : ``}${i || r ? `${i}h ` : ``}${a || i || r ? `${a}m ` : ``}${o}s` : !r && !i && !a ? `1m` : `${r ? `${r} days ` : ``}${i || r ? `${i}h ` : ``}${a || i || r ? `${a}m` : ``}`
    },
    xi = e => {
        let t = Math.round(e / (60 * 1e3)),
            n = Math.floor(t / 60),
            r = t % 60;
        return n === 0 ? St(P.DURATION_MIN, {
            minutes: r
        }) : r === 0 ? St(P.DURATION_HOURS, {
            hours: n
        }) : St(P.DURATION_H_M, {
            hours: n,
            minutes: r
        })
    },
    Si = e => [Math.abs(0 | e), `°`, 0 | (e < 0 ? e = -e : e) % 1 * 60, `'`, 0 | e * 60 % 1 * 60, `"`].join(``),
    Ci = (e, t) => [e < 0 ? `S` : `N`, Si(e), `, `, t < 0 ? `W` : `E`, Si(t)].join(``),
    wi = e => (e < 0 ? `-` : `+`) + xt(Math.abs(Math.round(e))) + `:00`,
    Ti = e => e.replace(/[,.]/g, ` `).replace(/₂/g, `2`).replace(/₃/g, `3`).replace(/\s+/g, `-`).replace(/-+/g, `-`),
    Ei = e => Ti(e).replace(/\/+/g, `-`),
    Di = e => e === `en` ? `` : `${e}/`,
    Oi = (e, t, n) => {
        let r = Date.now(),
            i = r + 4e3,
            a = () => {
                let o = Math.floor(Ot(r, i, Date.now()) * e);
                t && (t.textContent = `${pi(o)}${n ? ` ${P.VIEWS}` : ``}`), t && o < e && window.requestAnimationFrame(a)
            };
        a()
    },
    ki = (e, t, n = !0) => {
        setTimeout(() => Oi(e, t, n), 2e3)
    },
    Ai = (e, t) => {
        let n = Math.round(e * 3.28084);
        return pi(t ? Math.round(e / 100) * 100 : n)
    };
var ji = b({
    Metric: () => Mi,
    rtrnSelf: () => I
});
const I = e => e;
var Mi = class {
        constructor(e) {
            C(this, `key`, void 0), C(this, `cohesion`, void 0), C(this, `conv`, void 0), C(this, `separator`, void 0), C(this, `defaults`, void 0), C(this, `nativeSync`, void 0), C(this, `ident`, void 0), C(this, `backConv`, void 0), C(this, `metric`, void 0), C(this, `legend`, void 0), C(this, `useConvertValue`, void 0), this.initProperties(), Object.assign(this, e), this.key = this.createKey(this.ident);
            let t = this.listMetrics();
            M.insert(this.key, {
                def: this.getDefault(),
                save: !0,
                sync: !0,
                nativeSync: this.nativeSync,
                allowed: t
            }), this.metric = M.get(this.key), M.on(this.key, this.onMetricChanged, this), M.once(`defaultUnits`, this.setDefault, this)
        }
        convertValue(e, t, n, r) {
            if (e === void 0) return ``;
            {
                var i;
                let a = this.convertNumber(e, r);
                return (typeof a == `number` && !isNaN(a) && a >= 1e3 ? pi(a) : a) + (t || this.separator) + (((i = this.conv[this.metric]) == null ? void 0 : i.label) || this.metric) + (n || ``)
            }
        }
        na() {
            var e;
            return ((e = this.conv[this.metric]) == null ? void 0 : e.na) || `-`
        }
        listMetrics() {
            return Object.keys(this.conv)
        }
        howManyMetrics() {
            return this.listMetrics().length
        }
        setMetric(e, t) {
            M.set(this.key, e), this.cohesion && !t && Object.keys(this.cohesion).forEach(t => {
                var n;
                let r = (n = this.cohesion) == null || (n = n[t]) == null ? void 0 : n[e];
                r && M.set(this.createKey(t), r)
            })
        }
        cycleMetric() {
            if (this.legend && !this.legend.isDiscrete) {
                let {
                    description: e
                } = this.legend, t = e.indexOf(this.metric) + 1;
                t === e.length && (t = 0), this.setMetric(e[t])
            } else if (!this.legend) {
                let e = this.listMetrics(),
                    t = e.indexOf(this.metric) + 1;
                t === e.length && (t = 0), this.setMetric(e[t])
            }
        }
        initProperties() {
            this.separator = ``, this.nativeSync = !1
        }
        onMetricChanged(e) {
            this.metric = e, N.emit(`metricChanged`, this.ident, e)
        }
        getDefault() {
            return M.get(`defaultUnits`) === `imperial` && this.defaults.length > 1 ? this.defaults[1] : this.defaults[0]
        }
        setDefault() {
            this.key && (M.setDefault(this.key, this.getDefault()), this.metric = M.get(this.key))
        }
        createKey(e) {
            return `metric_${e}`
        }
    },
    Ni = b({
        DroughtMetric: () => zi,
        FogMetric: () => Hi,
        FwiMetric: () => Vi,
        NumberedMetric: () => L,
        PrecipMetric: () => Ui,
        PtypeMetric: () => Fi,
        RadarPTypeMetric: () => Ii,
        UVIndexMetric: () => Li
    }),
    L = class extends Mi {
        convertNumber(e, t, n, r) {
            let i = r && this.backConv ? this.backConv[n || this.metric] : this.conv[n || this.metric];
            if (!i) return O(`convertNumber`, `Conversion method for ${n || this.metric} is not defined!`), 0;
            let a = i.conversion(e),
                o = 10 ** (t == null ? i.precision : t);
            return Math.round(a * o) / o
        }
    },
    Pi = class extends Mi {
        constructor(...e) {
            super(...e), C(this, `useConvertValue`, !0)
        }
        convertNumber(e) {
            return e
        }
    },
    Fi = class extends Pi {
        convertValue(e) {
            let t = {
                0: `RAIN`,
                1: `JUST_RAIN`,
                2: `THUNDER`,
                3: `FZ_RAIN`,
                4: `MX_ICE`,
                5: `SNOW`,
                6: `WET_SN`,
                7: `RA_SN`,
                8: `PELLETS`,
                9: `LIGHT_THUNDER`,
                10: `THUNDER`,
                11: `HEAVY_THUNDER`
            };
            return e in t ? P[t[e]] : ``
        }
    },
    Ii = class extends Pi {
        convertValue(e) {
            let t = P.JUST_RAIN;
            return e <= 48 ? t = P.SNOW : e >= 200 && (t = P.HAIL), t
        }
    },
    Li = class extends Pi {
        convertValue(e) {
            return e === 0 ? P.NONE : e <= 2 ? P.UV_LOW : e <= 5 ? P.UV_MODERATE : e <= 7 ? P.UV_HIGH : e <= 10 ? P.UV_VERY_HIGH : P.UV_EXTREME
        }
    };
const Ri = {
    0: `INTERSUCHO_AWP_0`,
    1: `INTERSUCHO_AWP_1`,
    2: `INTERSUCHO_AWP_2`,
    3: `INTERSUCHO_AWP_3`,
    4: `INTERSUCHO_AWP_4`,
    5: `INTERSUCHO_AWP_5`,
    6: `INTERSUCHO_AWP_6`
};
var zi = class extends Pi {
    convertValue(e) {
        let t = D(Math.round(e) + 1, 0, 6);
        return t in Ri ? P[Ri[t]] : ``
    }
};
const Bi = {
    1: `INTERSUCHO_FWI_1`,
    2: `INTERSUCHO_FWI_2`,
    3: `INTERSUCHO_FWI_3`,
    4: `INTERSUCHO_FWI_4`,
    5: `INTERSUCHO_FWI_5`,
    6: `INTERSUCHO_FWI_6`
};
var Vi = class extends Pi {
        convertValue(e) {
            let t = D(Math.round(e), 1, 6);
            return t in Bi ? P[Bi[t]] : ``
        }
    },
    Hi = class extends Pi {
        convertValue(e) {
            return e <= .7 ? P.NO_FOG : e <= 1 ? P.FOG : P.FOG_RIME
        }
    },
    Ui = class extends L {
        initProperties() {
            super.initProperties(), this.defaults = [`mm`, `in`], this.nativeSync = !0, this.cohesion = {
                snow: {
                    in: `in`,
                    mm: `cm`
                }
            }, this.conv = {
                mm: {
                    conversion: I,
                    precision: 1
                },
                in: {
                    conversion: e => e * .0394,
                    precision: 2
                }
            }, this.backConv = {
                mm: {
                    conversion: I,
                    precision: 1
                },
                in: {
                    conversion: e => e * 25.4,
                    precision: 2
                }
            }
        }
    };
const Wi = {
        "%": {
            conversion: e => Math.round(100 * e),
            precision: 0
        }
    },
    Gi = new L({
        ident: `temp`,
        separator: ``,
        defaults: [`°C`, `°F`],
        conv: {
            "°C": {
                conversion: e => e - 273.15,
                precision: 0
            },
            "°F": {
                conversion: e => e * 9 / 5 - 459.67,
                precision: 0
            }
        },
        nativeSync: !0,
        legend: {
            description: [`°C`, `°F`],
            lines: [
                [252, -20, -5],
                [262, -10, 15],
                [272, 0, 30],
                [282, 10, 50],
                [292, 20, 70],
                [302, 30, 85],
                [313, 40, 100]
            ]
        },
        backConv: {
            "°C": {
                conversion: e => e + 273.15,
                precision: 0
            },
            "°F": {
                conversion: e => (e + 459.67) * 5 / 9,
                precision: 0
            }
        }
    }),
    Ki = [.3, 1.5, 3.3, 5.5, 8, 10.8, 13.9, 17.2, 20.7, 24.5, 28.4, 32.6],
    qi = new L({
        ident: `wind`,
        defaults: [`kt`],
        nativeSync: !0,
        conv: {
            kt: {
                conversion: e => e * 1.943844,
                precision: 0
            },
            bft: {
                conversion: e => {
                    for (let t = 0; t < Ki.length; t++)
                        if (e < Ki[t]) return t;
                    return 12
                },
                precision: 0
            },
            "m/s": {
                conversion: I,
                precision: 0
            },
            "km/h": {
                conversion: e => e * 3.6,
                precision: 0
            },
            mph: {
                conversion: e => e * 2.236936,
                precision: 0
            }
        },
        backConv: {
            kt: {
                conversion: e => e / 1.943844,
                precision: 0
            },
            bft: {
                conversion: e => {
                    var t;
                    return (t = Ki[Math.floor(e)]) == null ? e < 0 ? Ki[0] : Ki[Ki.length - 1] : t
                },
                precision: 0
            },
            "m/s": {
                conversion: I,
                precision: 0
            },
            "km/h": {
                conversion: e => e / 3.6,
                precision: 0
            },
            mph: {
                conversion: e => e / 2.236936,
                precision: 0
            }
        },
        legend: {
            description: [`kt`, `bft`, `m/s`, `mph`, `km/h`],
            lines: [
                [0, 0, 0, 0, 0, 0],
                [3, 5, 2, 3, 6, 10],
                [5, 10, 3, 5, 10, 20],
                [10, 20, 5, 10, 20, 35],
                [15, 30, 7, 15, 35, 55],
                [20, 40, 8, 20, 45, 70],
                [30, 60, 11, 30, 70, 100]
            ]
        }
    }),
    Ji = new L({
        ident: `rh`,
        defaults: [`%`],
        conv: {
            "%": {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`%`],
            lines: [
                [30, 30],
                [50, 50],
                [80, 80],
                [90, 90],
                [100, 100]
            ]
        }
    }),
    Yi = new L({
        ident: `clouds`,
        defaults: [`rules`],
        conv: {
            rules: {
                conversion: I,
                precision: 0
            },
            "%": {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`rules`, `%`],
            lines: [
                [25, `FEW`, 25],
                [50, `SCT`, 50],
                [70, `BKN`, 70],
                [100, `OVC`, 100]
            ]
        }
    }),
    Xi = new L({
        ident: `pressure`,
        defaults: [`hPa`, `inHg`, `mmHg`],
        nativeSync: !0,
        conv: {
            hPa: {
                conversion: e => e / 100,
                precision: 0
            },
            mmHg: {
                conversion: e => e / 133.322387415,
                precision: 0
            },
            inHg: {
                conversion: e => e / 3386.389,
                precision: 2
            }
        },
        backConv: {
            hPa: {
                conversion: e => e * 100,
                precision: 0
            },
            mmHg: {
                conversion: e => e * 133.322387415,
                precision: 0
            },
            inHg: {
                conversion: e => e * 3386.389,
                precision: 2
            }
        },
        legend: {
            description: [`hPa`, `inHg`, `mmHg`],
            lines: [
                [99e3, 990, 29.2, 742],
                [1e5, 1e3, 29.6, 750],
                [101e3, 1010, 29.8, 757],
                [102e3, 1020, 30.1, 765],
                [103e3, 1030, 30.4, 772]
            ]
        }
    }),
    Zi = new Ui({
        ident: `rain`,
        legend: {
            description: [`mm`, `in`],
            lines: [
                [1.5, 1.5, `.06`],
                [2, 2, `.08`],
                [3, 3, `.11`],
                [7, 7, `.24`],
                [10, 10, `.39`],
                [20, 20, `.78`],
                [30, 30, 1.2]
            ]
        }
    }),
    Qi = new L({
        ident: `snow`,
        defaults: [`cm`, `in`],
        nativeSync: !0,
        conv: {
            cm: {
                conversion: I,
                precision: 1
            },
            in: {
                conversion: e => e * .39,
                precision: 1
            }
        },
        backConv: {
            cm: {
                conversion: I,
                precision: 1
            },
            in: {
                conversion: e => e / .39,
                precision: 1
            }
        },
        legend: {
            description: [`cm`, `in`],
            lines: [
                [2, 2, `.8`],
                [5, 5, 2],
                [10, 10, 4],
                [50, 50, 20],
                [100, `1m`, `3ft`],
                [300, `3m`, `9ft`]
            ]
        },
        cohesion: {
            rain: {
                in: `in`,
                cm: `mm`
            }
        }
    }),
    $i = new L({
        ident: `cape`,
        defaults: [`J/kg`],
        conv: {
            "J/kg": {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`J/kg`],
            lines: [
                [0, 0],
                [500, 500],
                [1500, 1500],
                [2500, 2500],
                [5e3, 5e3]
            ]
        }
    }),
    ea = new L({
        ident: `gtco3`,
        defaults: [`DU`],
        conv: {
            DU: {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`DU`],
            lines: [
                [150, 150],
                [220, 220],
                [280, 280],
                [330, 330],
                [400, 400]
            ]
        }
    }),
    ta = new L({
        ident: `aod550`,
        defaults: [`AOD`],
        conv: {
            AOD: {
                conversion: I,
                precision: 3
            }
        },
        legend: {
            description: [`AOD`],
            lines: [
                [0, 0],
                [.25, .25],
                [.5, .5],
                [1, 1],
                [2, 2],
                [4, 4]
            ]
        }
    }),
    na = new L({
        ident: `pm2p5`,
        defaults: [`µg/m³`],
        conv: {
            "µg/m³": {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`µg/m³`],
            lines: [
                [0, 0],
                [10, 10],
                [20, 20],
                [100, 100],
                [1e3, 1e3]
            ]
        }
    }),
    ra = new L({
        ident: `no2`,
        defaults: [`µg/m³`],
        conv: {
            "µg/m³": {
                conversion: I,
                precision: 2
            }
        },
        legend: {
            description: [`µg/m³`],
            lines: [
                [0, 0],
                [1, 1],
                [5, 5],
                [25, 25],
                [100, 100]
            ]
        }
    }),
    ia = new L({
        ident: `tcso2`,
        defaults: [`mg/m²`],
        conv: {
            "mg/m²": {
                conversion: I,
                precision: 2
            }
        },
        legend: {
            description: [`mg/m²`],
            lines: [
                [0, 0],
                [1, 1],
                [5, 5],
                [25, 25],
                [100, 100]
            ]
        }
    }),
    aa = new L({
        ident: `go3`,
        defaults: [`µg/m³`],
        conv: {
            "µg/m³": {
                conversion: I,
                precision: 2
            }
        },
        legend: {
            description: [`µg/m³`],
            lines: [
                [0, 0],
                [10, 10],
                [20, 20],
                [100, 100],
                [1e3, 1e3]
            ]
        }
    }),
    oa = new L({
        ident: `altitude`,
        defaults: [`m`, `ft`],
        conv: {
            m: {
                conversion: I,
                precision: -2
            },
            ft: {
                conversion: e => Math.round(e * 3.28084),
                precision: -2
            }
        },
        backConv: {
            m: {
                conversion: I,
                precision: -2
            },
            ft: {
                conversion: e => Math.round(e / 3.28084),
                precision: -2
            }
        },
        legend: {
            description: [`m`, `ft`],
            lines: [
                [0, 0, 0],
                [1e3, 1e3, 3e3],
                [1500, 1500, 5e3],
                [5e3, `5k`, `FL150`],
                [9e3, `9k`, `FL300`]
            ]
        }
    }),
    sa = new L({
        ident: `elevation`,
        defaults: [`m`, `ft`],
        conv: {
            m: {
                conversion: I,
                precision: 0
            },
            ft: {
                conversion: e => Math.round(e * 3.28084),
                precision: 0
            }
        },
        backConv: {
            m: {
                conversion: I,
                precision: 0
            },
            ft: {
                conversion: e => Math.round(e / 3.28),
                precision: 0
            }
        }
    }),
    ca = new L({
        ident: `distance`,
        defaults: [`km`, `mi`],
        nativeSync: !0,
        conv: {
            km: {
                conversion: e => e / 1e3,
                precision: 1
            },
            mi: {
                conversion: e => e / 1609.344,
                precision: 1
            },
            NM: {
                conversion: e => e / 1852,
                precision: 1
            }
        },
        backConv: {
            km: {
                conversion: e => e * 1e3,
                precision: 1
            },
            mi: {
                conversion: e => e * 1609.344,
                precision: 1
            },
            NM: {
                conversion: e => e * 1852,
                precision: 1
            }
        }
    }),
    la = new L({
        ident: `speed`,
        defaults: [`kt`],
        conv: {
            "km/h": {
                conversion: e => e * 3.6,
                precision: 0
            },
            mph: {
                conversion: e => e * 2.236936,
                precision: 0
            },
            kt: {
                conversion: e => e * 1.943844,
                precision: 0
            },
            "m/s": {
                conversion: I,
                precision: 0
            }
        }
    }),
    ua = new L({
        ident: `waves`,
        defaults: [`m`, `ft`],
        conv: {
            m: {
                conversion: I,
                precision: 1
            },
            ft: {
                conversion: e => e * 3.28084,
                precision: 0
            }
        },
        legend: {
            description: [`m`, `ft`],
            lines: [
                [.5, .5, 1.6],
                [1, 1, 3.3],
                [1.5, 1.5, 5],
                [2, 2, 6.6],
                [6, 6, 20],
                [9, 9, 30]
            ]
        }
    }),
    da = new L({
        ident: `currents`,
        separator: ` `,
        defaults: [`kt`],
        conv: {
            kt: {
                conversion: e => e * 1.943844,
                precision: 1
            },
            "m/s": {
                conversion: I,
                precision: 2
            },
            "km/h": {
                conversion: e => e * 3.6,
                precision: 1
            },
            mph: {
                conversion: e => e * 2.236936,
                precision: 1
            }
        },
        legend: {
            description: [`kt`, `m/s`, `mph`, `km/h`],
            lines: [
                [0, 0, 0, 0, 0],
                [.2, .4, .2, .4, .7],
                [.4, .8, .4, .9, 1.4],
                [.8, 1.6, .8, 1.8, 2.9],
                [1, 2, 1, 2.2, 3.6],
                [1.6, 3.2, 1.6, 3.6, 5.8]
            ]
        }
    }),
    fa = new L({
        ident: `visibility`,
        defaults: [`km`, `sm`],
        conv: {
            rules: {
                conversion: e => e / 1e3,
                label: `km`,
                precision: 1
            },
            km: {
                conversion: e => e / 1e3,
                precision: 1
            },
            sm: {
                conversion: e => e * 62137e-8,
                precision: 1
            }
        },
        legend: {
            description: [`rules`, `km`, `sm`],
            lines: [
                [0, `LIFR`, `.8`, `.5`],
                [3e3, `IFR`, 2.7, 1.5],
                [7e3, `MVFR`, 6, 4],
                [16e3, `VFR`, 16, 10]
            ]
        }
    }),
    pa = new L({
        ident: `visibilityNoRules`,
        defaults: [`km`, `sm`],
        conv: {
            km: {
                conversion: e => e / 1e3,
                precision: 1
            },
            sm: {
                conversion: e => e * 62137e-8,
                precision: 1
            }
        },
        legend: {
            description: [`km`, `sm`],
            lines: [
                [0, `.8`, `.5`],
                [3e3, 2.7, 1.5],
                [7e3, 6, 4],
                [16e3, 16, 10]
            ]
        }
    }),
    ma = new L({
        ident: `so2`,
        defaults: [`µg/m³`],
        conv: {
            "µg/m³": {
                conversion: I,
                precision: 2
            }
        },
        legend: {
            description: [`µg/m³`],
            lines: [
                [0, 0],
                [1, 1],
                [5, 5],
                [10, 10],
                [80, 80]
            ]
        }
    }),
    ha = new L({
        ident: `dust`,
        defaults: [`µg/m³`],
        conv: {
            "µg/m³": {
                conversion: I,
                precision: 1
            }
        },
        legend: {
            description: [`µg/m³`],
            lines: [
                [0, 0],
                [50, 50],
                [100, 100],
                [500, 500],
                [800, 800]
            ]
        }
    }),
    ga = new L({
        ident: `cosc`,
        defaults: [`ppbv`],
        conv: {
            ppbv: {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            description: [`ppbv`],
            lines: [
                [0, 0],
                [50, 50],
                [100, 100],
                [500, 500],
                [1200, 1200]
            ]
        }
    }),
    _a = e => (10 ** (e * .1) * .005) ** .625,
    va = e => 10 * Math.log10(e ** 1.6 / .005),
    ya = new L({
        ident: `radar`,
        defaults: [`dBZ`, `mm/h`, `in/h`],
        conv: {
            dBZ: {
                conversion: I,
                precision: 0
            },
            "mm/h": {
                conversion: e => _a(e),
                precision: 1
            },
            "in/h": {
                conversion: e => _a(e) / 25.4,
                precision: 2
            }
        },
        backConv: {
            dBZ: {
                conversion: I,
                precision: 0
            },
            "mm/h": {
                conversion: e => va(e),
                precision: 1
            },
            "in/h": {
                conversion: e => va(e * 25.4),
                precision: 2
            }
        },
        legend: {
            description: [`dBZ`, `mm/h`, `in/h`],
            lines: [
                [0, 0, 0, 0],
                [20, 20, .6, .02],
                [30, 30, 3, .1],
                [40, 40, 12, .5],
                [50, 50, 50, 2],
                [60, 60, 200, 8]
            ]
        }
    }),
    ba = 321.75,
    xa = (182.75 - ba) / 255,
    Sa = new L({
        ident: `satellite`,
        defaults: [`K`, `°C`, `°F`],
        conv: {
            K: {
                conversion: e => Math.round(xa * e + ba),
                precision: 0,
                na: ``
            },
            "°C": {
                conversion: e => Math.round(xa * e + ba - 273.15),
                precision: 0,
                na: ``
            },
            "°F": {
                conversion: e => Math.round(9 / 5 * xa * e + 9 / 5 * ba - 459.67),
                precision: 0,
                na: ``
            }
        },
        backConv: {
            K: {
                conversion: e => Math.round((e - ba) / xa),
                precision: 0,
                na: ``
            },
            "°C": {
                conversion: e => Math.round((e - ba + 273.15) / xa),
                precision: 0,
                na: ``
            },
            "°F": {
                conversion: e => Math.round((e - 9 / 5 * ba + 459.67) / (9 / 5 * xa)),
                precision: 0,
                na: ``
            }
        },
        legend: {
            description: [`K`, `°C`, `°F`],
            lines: [
                [150, 240, -33, -28],
                [168, 230, -43, -45],
                [186, 220, -53, -63],
                [205, 210, -63, -82],
                [223, 200, -73, -99]
            ]
        }
    }),
    Ca = new Fi({
        ident: `ptype`,
        defaults: [`ptype`],
        conv: {
            ptype: {
                conversion: I,
                precision: 0,
                label: ``
            }
        },
        legend: {
            isDiscrete: !0,
            labels: [
                [`JUST_RAIN`, `rgb(0,153,182)`],
                [`FZ_RAIN`, `rgb(144,0,150)`],
                [`MX_ICE`, `rgb(81,12,15)`],
                [`SNOW`, `rgb(178,178,178)`],
                [`WET_SN`, `rgb(86,148,86)`],
                [`RA_SN`, `rgb(149,161,9)`]
            ]
        }
    }),
    wa = new Ii({
        ident: `radarPType`,
        defaults: [`ptype`],
        conv: {
            ptype: {
                conversion: I,
                precision: 0,
                label: ``
            }
        }
    }),
    Ta = new L({
        ident: `gh`,
        defaults: [`m`],
        conv: {
            m: {
                conversion: I,
                precision: 0
            }
        }
    }),
    Ea = new Hi({
        ident: `fog`,
        defaults: [`type`],
        conv: {
            type: {
                conversion: I,
                precision: 0
            }
        },
        legend: {
            isDiscrete: !0,
            hasEqualItemsWidth: !0,
            labels: [
                [`FOG`, `rgb(198, 198, 198)`],
                [`FOG_RIME`, `rgb(201, 201, 255)`]
            ]
        }
    }),
    Da = new L({
        ident: `lightDensity`,
        defaults: [`l/km²`],
        conv: {
            "l/km²": {
                conversion: I,
                precision: 2
            }
        },
        legend: {
            description: [`l/km²`],
            lines: [
                [0, 0],
                [.025, `.025`],
                [.1, `.1`],
                [1, 1],
                [10, 10],
                [20, 20]
            ]
        }
    }),
    Oa = new L({
        ident: `efiWind`,
        defaults: [`%`],
        conv: Wi,
        legend: {
            description: [`%`],
            lines: [
                [-1, `unusually`],
                [-.75, `calm`],
                [.25, ``],
                [.75, `extreme`],
                [1, `wind`]
            ]
        }
    }),
    ka = new L({
        ident: `efiTemp`,
        defaults: [`%`],
        conv: Wi,
        legend: {
            description: [`%`],
            lines: [
                [-1, `extreme`],
                [-.75, `cold`],
                [-.25, ``],
                [.25, ``],
                [.75, `extreme`],
                [1, `warm`]
            ]
        }
    }),
    Aa = new L({
        ident: `efiRain`,
        defaults: [`%`],
        conv: Wi,
        legend: {
            description: [`%`],
            lines: [
                [-1, `very dry`],
                [0, ``],
                [.1, ``],
                [.75, `extreme`],
                [1, `precip.`]
            ]
        }
    }),
    ja = new Ui({
        ident: `moistureAnom100`,
        legend: {
            description: [`mm`, `in`],
            lines: [
                [-100, -100, -3.94],
                [-60, -60, -2.36],
                [-30, -30, 1.18],
                [0, 0, 0],
                [30, 30, 1.18],
                [60, 60, 2.36],
                [100, 100, 3.94]
            ]
        }
    }),
    Ma = new Ui({
        ident: `moistureAnom40`,
        legend: {
            description: [`mm`, `in`],
            lines: [
                [-60, -60, -2.36],
                [-30, -30, 1.18],
                [0, 0, 0],
                [30, 30, 1.18],
                [60, 60, 2.36]
            ]
        }
    }),
    R = {
        temp: Gi,
        wind: qi,
        rh: Ji,
        clouds: Yi,
        pressure: Xi,
        rain: Zi,
        snow: Qi,
        cape: $i,
        gtco3: ea,
        aod550: ta,
        pm2p5: na,
        no2: ra,
        tcso2: ia,
        go3: aa,
        altitude: oa,
        elevation: sa,
        distance: ca,
        speed: la,
        waves: ua,
        currents: da,
        visibility: fa,
        visibilityNoRules: pa,
        so2: ma,
        dust: ha,
        cosc: ga,
        radar: ya,
        satellite: Sa,
        ptype: Ca,
        radarPType: wa,
        gh: Ta,
        fog: Ea,
        lightDensity: Da,
        efiWind: Oa,
        efiTemp: ka,
        efiRain: Aa,
        drought: new zi({
            ident: `drought`,
            defaults: [`drought`],
            conv: {
                drought: {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                isDiscrete: !0,
                labels: [
                    [`INTERSUCHO_AWP_1`, `rgb(241,223,120)`],
                    [`INTERSUCHO_AWP_2`, `rgb(236,184,50)`],
                    [`INTERSUCHO_AWP_3`, `rgb(221,144,13)`],
                    [`INTERSUCHO_AWP_4`, `rgb(194,95,0)`],
                    [`INTERSUCHO_AWP_5`, `rgb(158,34,12)`],
                    [`INTERSUCHO_AWP_6`, `rgb(120,0,19)`]
                ]
            }
        }),
        moistureAnom40: Ma,
        moistureAnom100: ja,
        fwi: new Vi({
            ident: `fwi`,
            defaults: [`fwi`],
            conv: {
                fwi: {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                isDiscrete: !0,
                labels: [
                    [`INTERSUCHO_FWI_1`, `rgb(75,168,64)`],
                    [`INTERSUCHO_FWI_2`, `rgb(234,232,63)`],
                    [`INTERSUCHO_FWI_3`, `rgb(236,142,65)`],
                    [`INTERSUCHO_FWI_4`, `rgb(220,60,48)`],
                    [`INTERSUCHO_FWI_5`, `rgb(162,37,30)`],
                    [`INTERSUCHO_FWI_6`, `rgb(131,42,109)`]
                ]
            }
        }),
        dfm10h: new L({
            ident: `dfm10h`,
            defaults: [`%`],
            conv: {
                "%": {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                description: [`%`],
                lines: [
                    [0, 0],
                    [4, 4],
                    [8, 8],
                    [10, 10],
                    [30, 30],
                    [40, 40]
                ]
            }
        }),
        solarpower: new L({
            ident: `solarpower`,
            defaults: [`W/m²`],
            conv: {
                "W/m²": {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                description: [`W/m²`],
                lines: [
                    [0, 0],
                    [250, 250],
                    [500, 500],
                    [750, 750],
                    [1e3, 1e3]
                ]
            }
        }),
        wavePower: new L({
            ident: `wavePower`,
            defaults: [`kW/m`],
            conv: {
                "kW/m": {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                description: [`kW/m`],
                lines: [
                    [0, 0],
                    [5, 5],
                    [10, 10],
                    [15, 15],
                    [20, 20],
                    [300, 300]
                ]
            }
        }),
        uvindex: new Li({
            ident: `uvindex`,
            defaults: [`uvindex`],
            conv: {
                uvindex: {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                isDiscrete: !0,
                hasEqualItemsWidth: !0,
                labels: [
                    [`UV_LOW`, `rgb(41,148,26)`],
                    [`UV_MODERATE`, `rgb(235,224,0)`],
                    [`UV_HIGH`, `rgb(222,120,0)`],
                    [`UV_VERY_HIGH`, `rgb(210,30,0)`],
                    [`UV_EXTREME`, `rgb(162,83,144)`]
                ]
            }
        }),
        turbulence: new L({
            ident: `turbulence`,
            defaults: [`EDR`],
            conv: {
                EDR: {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                description: [`EDR`],
                lines: [
                    [0, 0],
                    [20, 20],
                    [40, 40],
                    [60, 60],
                    [80, 80],
                    [100, 100]
                ]
            }
        }),
        icing: new L({
            ident: `icing`,
            defaults: [`%`],
            conv: {
                "%": {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                description: [`%`],
                lines: [
                    [0, 0],
                    [20, 20],
                    [40, 40],
                    [60, 60],
                    [80, 80],
                    [100, 100]
                ]
            }
        }),
        area: new L({
            ident: `area`,
            defaults: [`km²`, `acres`],
            conv: {
                "km²": {
                    conversion: I,
                    precision: 1
                },
                acres: {
                    conversion: e => e * 247.105,
                    precision: 0
                }
            }
        }),
        aqi: new L({
            ident: `aqi`,
            defaults: [`AQI`],
            conv: {
                AQI: {
                    conversion: I,
                    precision: 0
                }
            },
            legend: {
                isDiscrete: !0,
                hasEqualItemsWidth: !0,
                labels: [
                    [`AIRQ_RANGE_GOOD`, `rgb(20,140,20)`],
                    [`AIRQ_RANGE_MODERATE`, `rgb(188,188,38)`],
                    [`AIRQ_RANGE_UNHEALTHY`, `rgb(201,131,60)`],
                    [`AIRQ_RANGE_HAZARDOUS`, `rgb(186, 47, 87)`]
                ]
            }
        }),
        pollen: new L({
            ident: `pollen`,
            defaults: [`gr./m³`],
            conv: {
                "gr./m³": {
                    conversion: I,
                    precision: 0
                }
            }
        }),
        fallback: new L({
            ident: `fallback`,
            defaults: [`fallback`],
            conv: {
                fallback: {
                    conversion: I,
                    precision: 0
                }
            }
        })
    };
var Na = b({
    IDB: () => Ia,
    allUsedCollections: () => Pa,
    idbEmitter: () => Fa
});
const Pa = [`customColors`, `installedPlugins2`, `likedStoryComments`, `log`, `markedNotams`, `popularLocations`, `searchRecents2`, `upvotedArticles`, `seenPromos`, `slidedCapAlerts`, `userAlerts`, `userFavs`],
    Fa = new Ln({
        ident: `idb`
    });
var Ia = class {
        constructor(e) {
            C(this, `storeId`, void 0), C(this, `memoryCache`, void 0), C(this, `cacheIsValid`, !1), C(this, `connection`, void 0), C(this, `usesBackendSync`, void 0), C(this, `apiEndpoint`, void 0), C(this, `syncToNativeStorage`, void 0), C(this, `lastTimeUpdatedKey`, `__lastTimeUpdated`), this.storeId = e.storeId, this.connection = e.connection, this.connection.onCloseDb(() => {
                this.cacheIsValid = !1, this.memoryCache = []
            }), this.syncToNativeStorage = !!e.syncToNativeStorage, this.usesBackendSync = !!e.backendApiEndpoint, this.usesBackendSync && (this.apiEndpoint = `/users/v1/data/${e.backendApiEndpoint}`)
        }
        async getAll() {
            var e = this;
            if (e.cacheIsValid) return e.memoryCache;
            {
                let t = await e.connection.getDb();
                return new Promise((n, r) => {
                    let i = t.transaction(e.storeId, `readonly`),
                        a = i.objectStore(e.storeId).getAll();
                    i.commit(), a.onsuccess = () => {
                        let {
                            result: t
                        } = a, r = t.filter(e => typeof e == `object`);
                        e.memoryCache = r, e.cacheIsValid = !0, n(r)
                    }, a.onerror = e => {
                        O(`IDB`, `Failed to find items in database`, e), r(e)
                    }
                })
            }
        }
        async removeAll() {
            var e = this;
            e.cacheIsValid = !1;
            let t = await e.connection.getDb();
            return new Promise((n, r) => {
                let i = t.transaction(e.storeId, `readwrite`),
                    a = i.objectStore(e.storeId).clear();
                i.commit(), a.onsuccess = () => {
                    Fa.emit(`_nativeSync`, {
                        storeId: e.storeId,
                        syncToNativeStorage: e.syncToNativeStorage
                    }), n()
                }, a.onerror = e => {
                    O(`IDB`, `Failed to clear store`, e), r(e)
                }
            })
        }
        async hasKey(e) {
            var t = this;
            let n = await t.connection.getDb();
            return new Promise((r, i) => {
                let a = n.transaction(t.storeId, `readonly`),
                    o = a.objectStore(t.storeId).count(e);
                a.commit(), o.onsuccess = () => {
                    r(!!o.result)
                }, o.onerror = e => {
                    O(`IDB`, `Failed to retrieve key`, e), i(e)
                }
            })
        }
        async get(e) {
            var t = this;
            let n = await t.connection.getDb();
            return new Promise((r, i) => {
                let a = n.transaction(t.storeId, `readonly`),
                    o = a.objectStore(t.storeId).get(e);
                a.commit(), o.onsuccess = () => {
                    o.result === void 0 ? r(null) : r(o.result)
                }, o.onerror = e => {
                    O(`IDB`, `Failed to retrieve value from database`, e), i(e)
                }
            })
        }
        async remove(e, t = !1) {
            var n = this;
            n.cacheIsValid = !1;
            let r = await n.connection.getDb();
            if (n.usesBackendSync && !t) try {
                await Qr(`${n.apiEndpoint}/${encodeURIComponent(e)}`)
            } catch (e) {
                if (!(e instanceof qe && e.status === 404)) throw Error(`Failed to remove item from IDB due to network error`)
            }
            return new Promise((t, i) => {
                let a = r.transaction(n.storeId, `readwrite`);
                a.objectStore(n.storeId).delete(e), a.commit(), a.oncomplete = () => {
                    Fa.emit(`_nativeSync`, {
                        storeId: n.storeId,
                        syncToNativeStorage: n.syncToNativeStorage
                    }), t()
                }, a.onerror = e => {
                    O(`IDB`, `Failed to remove key from database`, e), i(e)
                }
            })
        }
        async add(e) {
            var t = this;
            if (!t.usesBackendSync) throw Error(`Cannot add items to IDB without backend sync`);
            t.cacheIsValid = !1;
            let n = await t.connection.getDb(),
                {
                    data: {
                        value: r,
                        id: i
                    }
                } = await $r(t.apiEndpoint, {
                    data: e
                });
            return new Promise((e, a) => {
                let o = n.transaction(t.storeId, `readwrite`);
                o.objectStore(t.storeId).put(r, i), o.commit(), o.oncomplete = () => {
                    Fa.emit(`_nativeSync`, {
                        storeId: t.storeId,
                        syncToNativeStorage: t.syncToNativeStorage
                    }), e(i)
                }, o.onerror = e => {
                    O(`IDB`, `Failed to add item to database`, e), a(e)
                }
            })
        }
        async put(e, t, n = !1) {
            var r = this;
            r.cacheIsValid = !1;
            let i = await r.connection.getDb();
            if (r.usesBackendSync && !n) {
                let n = encodeURIComponent(e);
                await ei(`${r.apiEndpoint}/${n}`, {
                    data: t
                })
            }
            return new Promise((n, a) => {
                let o = i.transaction(r.storeId, `readwrite`);
                o.objectStore(r.storeId).put(t, e), o.commit(), o.oncomplete = () => {
                    Fa.emit(`_nativeSync`, {
                        storeId: r.storeId,
                        syncToNativeStorage: r.syncToNativeStorage
                    }), n()
                }, o.onerror = e => {
                    O(`IDB`, `Failed to put item to database`, e), a(e)
                }
            })
        }
        async loadFromCloud() {
            var e = this;
            let t = await e.get(e.lastTimeUpdatedKey),
                {
                    status: n,
                    data: r
                } = await F(`${e.apiEndpoint}?storeTs=${t || 0}`);
            if (n === 304 || n === 204) return !1;
            let i = await e.getAll(),
                a = r,
                o = a.map(({
                    value: {
                        id: e
                    }
                }) => e);
            for (let t of i) {
                let {
                    id: n
                } = t;
                o.includes(n) || await e.remove(n, !0)
            }
            let s = 0;
            for (let {
                    value: t,
                    updated: n,
                    id: r
                }
                of a) await e.put(r, t, !0), n > s && (s = n);
            return await e.put(e.lastTimeUpdatedKey, s, !0), !0
        }
    },
    La = class {
        constructor(e) {
            this.databaseName = e, C(this, `dbPromise`, null), C(this, `closeDbListeners`, new Set)
        }
        onCloseDb(e) {
            this.closeDbListeners.add(e)
        }
        async getDb() {
            var e = this;
            return e.dbPromise === null && (e.dbPromise = e.connect()), e.dbPromise
        }
        async deleteDb() {
            var e = this;
            await e.closeDb(), await new Promise((t, n) => {
                let r = indexedDB.deleteDatabase(e.databaseName);
                r.onsuccess = () => {
                    t()
                }, r.onerror = e.createFailHandler(n), r.onblocked = e.createFailHandler(n), r.onupgradeneeded = e.createFailHandler(n)
            })
        }
        async closeDb() {
            var e = this;
            e.dbPromise && ((await e.dbPromise).close(), e.dbPromise = null, e.closeDbListeners.forEach(e => e()))
        }
        async connect(e) {
            var t = this;
            return new Promise((n, r) => {
                let i = indexedDB.open(t.databaseName, e);
                i.onerror = t.createFailHandler(r), i.onblocked = t.createFailHandler(r), i.onsuccess = async () => {
                    if (i.result.onversionchange = async () => {
                            await t.closeDb()
                        }, Pa.some(e => !i.result.objectStoreNames.contains(e))) {
                        let e = i.result.version + 1;
                        i.result.close(), n(t.connect(e));
                        return
                    }
                    n(i.result)
                }, i.onupgradeneeded = e => {
                    Pa.filter(e => !i.result.objectStoreNames.contains(e)).forEach(e => {
                        i.result.createObjectStore(e)
                    })
                }
            })
        }
        createFailHandler(e) {
            var t = this;
            return async n => {
                await t.closeDb(), O(`idbConnection`, `IDB operation failed, event type: ${n.type}, event class: ${n.constructor.name}`, n), e(n)
            }
        }
    },
    Ra = b({
        clearIndexedDB: () => Za,
        customColorsIdb: () => Ka,
        installedPluginsIdb: () => Xa,
        logIdb: () => Ja,
        markedNotamsIdb: () => Ua,
        popularLocationsIdb: () => Ya,
        searchRecentsIdb: () => Va,
        seenPromosIdb: () => Ga,
        slidedCapAlertsIdb: () => qa,
        upvotedArticlesIdb: () => Wa,
        userAlertsIdb: () => Ha,
        userFavsIdb: () => Ba
    });
const za = new La(`windy`),
    Ba = new Ia({
        connection: za,
        storeId: `userFavs`,
        backendApiEndpoint: `favs`,
        syncToNativeStorage: !0
    }),
    Va = new Ia({
        connection: za,
        storeId: `searchRecents2`
    }),
    Ha = new Ia({
        connection: za,
        storeId: `userAlerts`,
        backendApiEndpoint: `alerts`
    }),
    Ua = new Ia({
        connection: za,
        storeId: `markedNotams`,
        backendApiEndpoint: `notams`
    }),
    Wa = new Ia({
        connection: za,
        storeId: `upvotedArticles`
    }),
    Ga = new Ia({
        connection: za,
        storeId: `seenPromos`
    }),
    Ka = new Ia({
        connection: za,
        storeId: `customColors`,
        backendApiEndpoint: `colors`
    }),
    qa = new Ia({
        connection: za,
        storeId: `slidedCapAlerts`
    }),
    Ja = new Ia({
        connection: za,
        storeId: `log`
    }),
    Ya = new Ia({
        connection: za,
        storeId: `popularLocations`
    }),
    Xa = new Ia({
        connection: za,
        storeId: `installedPlugins2`,
        backendApiEndpoint: `plugins`
    }),
    Za = async () => {
        await za.deleteDb()
    };
var Qa = b({
        Color: () => z
    }),
    z = class {
        constructor(e) {
            var t, n;
            C(this, `prepare`, void 0), C(this, `opaque`, void 0), C(this, `maxIndex`, void 0), C(this, `step`, void 0), C(this, `neutralGrayIndex`, void 0), C(this, `initialColorGradient`, void 0), C(this, `defaultColorGradient`, void 0), C(this, `customColorGradient`, void 0), C(this, `minMaxValue`, void 0), C(this, `colors`, void 0), C(this, `min`, void 0), C(this, `max`, void 0), C(this, `ident`, void 0), C(this, `qualitative`, void 0), C(this, `steps`, void 0), this.ident = e.ident, this.qualitative = e.qualitative, this.steps = (t = e.steps) == null ? 256 : t, this.initialColorGradient = e.default, this.opaque = (n = e.opaque) == null ? !0 : n, this.prepare = e.prepare, this.minMaxValue = e.minMaxValue, this.prepare && this.getColor(), this.loadCustomColor()
        }
        getColorTable() {
            return this.colors
        }
        async loadCustomColor() {
            var e = this;
            if (await Ka.hasKey(e.ident)) {
                let t = await Ka.get(e.ident);
                e.customColorGradient = t == null ? void 0 : t.gradient, e.regenerateColorTable()
            }
        }
        hasCustomColor() {
            return !!this.customColorGradient
        }
        async setCustomColor(e, t = !0) {
            var n = this;
            t && await Ka.put(n.ident, {
                id: n.ident,
                gradient: e
            }), n.customColorGradient = e, n.regenerateColorTable()
        }
        async removeCustomColor() {
            var e = this;
            await Ka.remove(e.ident), e.customColorGradient = null, e.regenerateColorTable()
        }
        color(e) {
            let [t, n, r] = this.RGBA(e);
            return `rgb(${t},${n},${r})`
        }
        colorDark(e, t) {
            let [n, r, i] = this.RGBA(e);
            return n = D(n - t, 0, 255), r = D(r - t, 0, 255), i = D(i - t, 0, 255), `rgb(${n},${r},${i})`
        }
        RGBA(e) {
            let t = this.value2index(e);
            return [this.colors[t], this.colors[t + 1], this.colors[t + 2], this.colors[t + 3]]
        }
        createGradientArray(e = !0, t = !1, n = 1) {
            var r;
            let i = this.steps + 1,
                a = new Uint8Array(i << 2),
                o = n * (this.max - this.min) / (this.steps - 1),
                s = this.getColorGradient(),
                c = 0,
                l = 1,
                u = s[0],
                d = (r = s[l++]) == null ? s[0] : r,
                f = d[0] - u[0],
                p = f ? 1 / f : 1;
            for (let n = 0; n < this.steps; n++) {
                let r = this.min + o * n;
                for (; r > d[0] && l < s.length;) {
                    u = d, d = s[l++];
                    let e = d[0] - u[0];
                    p = e ? 1 / e : 1
                }
                let i = (r - u[0]) * p,
                    f = this.getGradientColorYUVA(u[1], d[1], i);
                t && this.makePremultiplied(f), a[c++] = Math.round(f[0]), a[c++] = Math.round(f[1]), a[c++] = Math.round(f[2]), a[c++] = e ? 255 : Math.round(f[3])
            }
            return this.neutralGrayIndex = c, a[c++] = a[c++] = a[c++] = 128, a[c++] = 255, a
        }
        getColor() {
            if (this.colors) return this;
            let e = this.getColorGradient();
            return this.min = this.minMaxValue ? this.minMaxValue[0] : e[0][0], this.max = this.minMaxValue ? this.minMaxValue[1] : e[e.length - 1][0], this.colors = this.createGradientArray(this.opaque), this.maxIndex = this.steps - 1 << 2, this.step = (this.max - this.min) / this.steps, this
        }
        value2index(e) {
            return isNaN(e) ? this.neutralGrayIndex : Math.max(0, Math.min(this.maxIndex, (e - this.min) / this.step << 2))
        }
        getColorGradient() {
            return this.customColorGradient || this.defaultColorGradient || (this.defaultColorGradient = this.parseColorGradient(this.initialColorGradient), this.defaultColorGradient)
        }
        static checkValidity(e) {
            if (!Array.isArray(e)) return !1;
            for (let t = 0; t < e.length; t++) {
                let n = e[t];
                if (!Array.isArray(n) || !n.length || !Array.isArray(n[1]) || typeof n[0] != `number` || n[1].length !== 4) return !1
            }
            return !0
        }
        parseRGBAString(e) {
            let t = e.match(/rgba?\(([^)]+)\)/);
            if (!t) throw Error(`Invalid color format: ${e}`);
            let n = t[1].split(`,`).map(Number);
            return n.length === 3 ? n.push(255) : n.length === 4 && (n[3] = Math.min(255, 255 * n[3])), n
        }
        parseColorGradient(e) {
            let t = [];
            for (let n = 0; n < e.length; n++) {
                let r = this.parseRGBAString(e[n][1]);
                t.push([e[n][0], r])
            }
            return t
        }
        getMulArray(e, t) {
            let n = [],
                r = e.length;
            for (let i = 0; i < r; i++) n.push(e[i] * t);
            return n
        }
        lerpArray(e, t, n) {
            let r = 1 - n,
                i = e.length,
                a = [];
            for (let o = 0; o < i; o++) a.push(e[o] * r + t[o] * n);
            return a
        }
        rgba2yuva([e, t, n, r]) {
            let i = .299 * e + .587 * t + .114 * n;
            return [i, (n - i) * .565, (e - i) * .713, r]
        }
        yuva2rgba([e, t, n, r]) {
            return [e + 1.403 * n, e - .344 * t - .714 * n, e + 1.77 * t, r]
        }
        gradYuva(e, t, n, r) {
            let i = this.lerpArray(e, t, n);
            if (r) {
                let r = ot(e[1], e[2]),
                    a = ot(t[1], t[2]);
                if (r > .05 && a > .05) {
                    let e = ot(i[1], i[2]),
                        t = r * (1 - n) + a * n;
                    if (e > .01) {
                        let n = t / e;
                        i[1] *= n, i[2] *= n
                    }
                }
            }
            return i
        }
        getGradientColorYUVA(e, t, n) {
            let r = 1 / 255,
                i = this.getMulArray(e, r),
                a = this.getMulArray(t, r),
                o = this.rgba2yuva(i),
                s = this.rgba2yuva(a),
                c = this.gradYuva(o, s, n, !0),
                l = this.yuva2rgba(c);
            for (let e = 0; e < l.length; e++) l[e] = Math.max(0, Math.min(l[e] * 256, 255));
            return l
        }
        makePremultiplied(e) {
            let t = e[3] / 255;
            for (let n = 0; n < 3; n++) e[n] = Math.max(0, Math.min(t * e[n], 255));
            return e
        }
        regenerateColorTable() {
            this.colors && (this.colors = null, this.getColor())
        }
    };
const $a = [`rgb(79,4,0)`, `rgb(107,45,0)`, `rgb(132,77,0)`, `rgb(153,106,5)`, `rgb(169,131,56)`, `rgb(182,153,85)`, `rgb(192,172,110)`, `rgb(197,186,132)`, `rgb(200,196,152)`, `rgb(200,202,170)`, `rgb(201,201,201)`, `rgb(190,204,179)`, `rgb(173,202,173)`, `rgb(150,197,170)`, `rgb(125,188,168)`, `rgb(97,174,165)`, `rgb(71,157,161)`, `rgb(48,135,153)`, `rgb(49,109,138)`, `rgb(50,80,117)`, `rgb(48,48,94)`],
    eo = [`rgb(0,102,151)`, `rgb(125,182,209)`, `rgb(170,183,189)`, `rgb(194,195,125)`, `rgb(232,83,25)`, `rgb(189,52,19)`, `rgb(75,12,0)`],
    to = [`rgb(166,93,165)`, `rgb(162,97,160)`, `rgb(167,91,91)`, `rgb(167,91,91)`, `rgb(98,122,160)`, `rgb(98,122,160)`, `rgb(90,169,90)`, `rgb(91,167,99)`, `rgb(119,141,120)`],
    B = {
        temp: new z({
            ident: `temp`,
            steps: 2048,
            prepare: !0,
            default: [
                [203, `rgb(115,70,105)`],
                [218, `rgb(202,172,195)`],
                [233, `rgb(162,70,145)`],
                [248, `rgb(143,89,169)`],
                [258, `rgb(157,219,217)`],
                [265, `rgb(106,191,181)`],
                [269, `rgb(100,166,189)`],
                [273.15, `rgb(93,133,198)`],
                [274, `rgb(68,125,99)`],
                [283, `rgb(128,147,24)`],
                [294, `rgb(243,183,4)`],
                [303, `rgb(232,83,25)`],
                [320, `rgb(71,14,0)`]
            ]
        }),
        wind: new z({
            ident: `wind`,
            steps: 2048,
            prepare: !0,
            default: [
                [0, `rgb(98,113,183)`],
                [1, `rgb(57,97,159)`],
                [3, `rgb(74,148,169)`],
                [5, `rgb(77,141,123)`],
                [7, `rgb(83,165,83)`],
                [9, `rgb(53,159,53)`],
                [11, `rgb(167,157,81)`],
                [13, `rgb(159,127,58)`],
                [15, `rgb(161,108,92)`],
                [17, `rgb(129,58,78)`],
                [19, `rgb(175,80,136)`],
                [21, `rgb(117,74,147)`],
                [24, `rgb(109,97,163)`],
                [27, `rgb(68,105,141)`],
                [29, `rgb(92,144,152)`],
                [36, `rgb(125,68,165)`],
                [46, `rgb(231,215,215)`],
                [51, `rgb(219,212,135)`],
                [77, `rgb(205,202,112)`],
                [104, `rgb(128,128,128)`]
            ]
        }),
        rh: new z({
            ident: `rh`,
            steps: 1024,
            default: [
                [0, `rgb(173,85,56)`],
                [30, `rgb(173,110,56)`],
                [40, `rgb(173,146,56)`],
                [50, `rgb(105,173,56)`],
                [60, `rgb(56,173,121)`],
                [70, `rgb(56,174,173)`],
                [75, `rgb(56,160,173)`],
                [80, `rgb(56,157,173)`],
                [83, `rgb(56,148,173)`],
                [87, `rgb(56,135,173)`],
                [90, `rgb(56,132,173)`],
                [93, `rgb(56,123,173)`],
                [97, `rgb(56,98,157)`],
                [100, `rgb(56,70,114)`]
            ]
        }),
        pressure: new z({
            ident: `pressure`,
            steps: 4e3,
            default: [
                [9e4, `rgb(8,16,48)`],
                [95e3, `rgb(0,32,96)`],
                [97600, `rgb(0,52,146)`],
                [98600, `rgb(0,90,148)`],
                [99500, `rgb(0,117,146)`],
                [100200, `rgb(26,140,147)`],
                [100700, `rgb(103,162,155)`],
                [101125, `rgb(155,183,172)`],
                [101325, `rgb(182,182,182)`],
                [101525, `rgb(176,174,152)`],
                [101900, `rgb(167,147,107)`],
                [102400, `rgb(163,116,67)`],
                [103e3, `rgb(159,81,44)`],
                [103800, `rgb(142,47,57)`],
                [104600, `rgb(111,24,64)`],
                [108e3, `rgb(48,8,24)`]
            ]
        }),
        cclAltitude: new z({
            ident: `cclAltitude`,
            steps: 1024,
            default: [
                [0, `rgb(128,128,128)`],
                [500, `rgb(128,128,128)`],
                [1e3, `rgb(213,211,173)`],
                [2e3, `rgb(199,143,32)`],
                [2500, `rgb(201,109,12)`],
                [3e3, `rgb(193,72,16)`],
                [4500, `rgb(159,29,43)`],
                [5e3, `rgb(133,12,12)`],
                [8e3, `rgb(83,5,36)`]
            ]
        }),
        altitude: new z({
            ident: `altitude`,
            steps: 1024,
            default: [
                [0, `rgb(105,83,83)`],
                [500, `rgb(162,82,140)`],
                [750, `rgb(99,174,174)`],
                [1000.15, `rgb(73,106,160)`],
                [1500, `rgb(75,131,70)`],
                [2e3, `rgb(191,193,93)`],
                [3e3, `rgb(184,149,73)`],
                [5e3, `rgb(182,99,83)`],
                [1e4, `rgb(171,81,102)`],
                [15e3, `rgb(108,77,97)`]
            ]
        }),
        deg0: new z({
            ident: `deg0`,
            steps: 1024,
            default: [
                [0, `rgb(188,197,195)`],
                [500, `rgb(155,195,189)`],
                [750, `rgb(93,173,156)`],
                [1000.15, `rgb(80,141,129)`],
                [1500, `rgb(55,122,109)`],
                [2e3, `rgb(39,93,82)`],
                [3e3, `rgb(33,68,73)`],
                [5e3, `rgb(32,55,71)`],
                [1e4, `rgb(28,33,64)`],
                [15e3, `rgb(6,6,6)`]
            ]
        }),
        levels: new z({
            ident: `levels`,
            steps: 2048,
            default: [
                [0, `rgb(105,117,140)`],
                [1e3, `rgb(94,131,150)`],
                [4e3, `rgb(71,145,154)`],
                [8e3, `rgb(78,179,102)`],
                [1e4, `rgb(189,189,68)`],
                [12e3, `rgb(177,80,80)`],
                [15e3, `rgb(178,80,178)`],
                [2e4, `rgb(184,184,184)`]
            ]
        }),
        rain: new z({
            ident: `rain`,
            steps: 1024,
            prepare: !0,
            default: [
                [0, `rgb(111,111,111)`],
                [.6, `rgb(60,116,160)`],
                [6, `rgb(59,161,161)`],
                [8, `rgb(59,161,61)`],
                [10, `rgb(130,161,59)`],
                [15, `rgb(161,161,59)`],
                [20, `rgb(161,59,59)`],
                [31, `rgb(161,59,161)`],
                [50, `rgb(168,168,168)`]
            ]
        }),
        ptype: new z({
            ident: `ptype`,
            steps: 128,
            qualitative: !0,
            default: [
                [0, `rgb(111,111,111)`],
                [1, `rgb(0,208,239)`],
                [2, `rgb(0,0,255)`],
                [3, `rgb(197,27,195)`],
                [4, `rgb(129,63,63)`],
                [5, `rgb(227,227,227)`],
                [6, `rgb(129,195,129)`],
                [7, `rgb(202,211,57)`],
                [8, `rgb(183,119,8)`],
                [9, `rgb(227,73,19)`],
                [10, `rgb(195,63,63)`]
            ]
        }),
        rainClouds: new z({
            ident: `rainClouds`,
            steps: 128,
            opaque: !1,
            default: [
                [0, `rgba(67, 87, 166, 0.2)`],
                [.8, `rgba(70, 102, 163, 0.3)`],
                [2, `rgba(62, 171, 171, 0.4)`],
                [6, `rgba(62, 171, 171, 0.9)`],
                [8, `rgb(62, 142, 62)`],
                [10, `rgb(129, 156, 62)`],
                [15, `rgb(171, 171, 62)`],
                [20, `rgb(169, 62, 62)`],
                [31, `rgb(171, 62, 171)`],
                [50, `rgb(177, 177, 177)`]
            ]
        }),
        clouds: new z({
            ident: `clouds`,
            steps: 800,
            default: [
                [0, `rgb(146,130,70)`],
                [10, `rgb(132,119,70)`],
                [50, `rgb(116,116,116)`],
                [95, `rgb(171,180,179)`],
                [98, `rgb(198,201,201)`],
                [100, `rgb(213,213,205)`]
            ]
        }),
        lclouds: new z({
            ident: `lclouds`,
            steps: 800,
            default: [
                [0, `rgb(156,142,87)`],
                [10, `rgb(143,131,87)`],
                [30, `rgb(129,129,129)`],
                [90, `rgb(137,159,182)`],
                [100, `rgb(187,187,187)`]
            ]
        }),
        hclouds: new z({
            ident: `hclouds`,
            steps: 800,
            default: [
                [0, `rgb(156,142,87)`],
                [10, `rgb(143,131,87)`],
                [30, `rgb(125,157,157)`],
                [90, `rgb(141,169,169)`],
                [100, `rgb(187,187,187)`]
            ]
        }),
        mclouds: new z({
            ident: `mclouds`,
            steps: 800,
            default: [
                [0, `rgba(156, 142, 87, 1)`],
                [10, `rgb(143,131,87)`],
                [30, `rgb(157,192,157)`],
                [90, `rgb(145,171,145)`],
                [100, `rgb(187,187,187)`]
            ]
        }),
        cape: new z({
            ident: `cape`,
            steps: 1024,
            default: [
                [0, `rgb(110,110,110)`],
                [350, `rgb(110,110,110)`],
                [400, `rgb(93,95,127)`],
                [500, `rgb(37,98,145)`],
                [800, `rgb(37,165,37)`],
                [1500, `rgb(163,161,55)`],
                [2e3, `rgb(155,112,63)`],
                [2500, `rgb(162,55,55)`],
                [5001, `rgb(151,68,151)`]
            ]
        }),
        lightDensity: new z({
            ident: `lightDensity`,
            steps: 2048,
            default: [
                [0, `rgb(136,136,136)`],
                [.015, `rgb(136,136,136)`],
                [.025, `rgb(136,200,0)`],
                [.1, `rgb(218,218,0)`],
                [1, `rgb(241,95,0)`],
                [2, `rgb(248,78,120)`],
                [4, `rgb(135,0,0)`],
                [15, `rgb(221,101,255)`]
            ]
        }),
        cbase: new z({
            ident: `cbase`,
            steps: 512,
            default: Cn(to, [0, 129, 149, 279, 299, 879, 914, 1499, 7999])
        }),
        snow: new z({
            ident: `snow`,
            steps: 2048,
            default: [
                [0, `rgb(97,97,97)`],
                [2, `rgb(69,82,152)`],
                [10, `rgb(65,165,167)`],
                [20, `rgb(65,141,65)`],
                [50, `rgb(168,168,65)`],
                [80, `rgb(170,126,63)`],
                [120, `rgb(167,65,65)`],
                [500, `rgb(168,65,168)`]
            ]
        }),
        rainAccu: new z({
            ident: `rainAccu`,
            steps: 12e3,
            default: [
                [0, `rgb(97,97,97)`],
                [1, `rgb(64,64,163)`],
                [5, `rgb(70,106,227)`],
                [10, `rgb(41,187,236)`],
                [30, `rgb(49,241,153)`],
                [50, `rgb(163,253,61)`],
                [80, `rgb(237,208,59)`],
                [120, `rgb(251,128,34)`],
                [200, `rgb(210,49,4)`],
                [320, `rgb(122,4,3)`],
                [600, `rgb(48,0,0)`],
                [8e3, `rgb(24,0,0)`]
            ]
        }),
        waves: new z({
            ident: `waves`,
            steps: 1024,
            default: [
                [0, `rgb(159,185,191)`],
                [.5, `rgb(48,157,185)`],
                [1, `rgb(48,98,141)`],
                [1.5, `rgb(56,104,191)`],
                [2, `rgb(57,60,142)`],
                [2.5, `rgb(187,90,191)`],
                [3, `rgb(154,48,151)`],
                [4, `rgb(133,48,48)`],
                [5, `rgb(191,51,95)`],
                [7, `rgb(191,103,87)`],
                [10, `rgb(191,191,191)`],
                [12, `rgb(154,127,155)`]
            ]
        }),
        currents: new z({
            ident: `currents`,
            steps: 256,
            default: [
                [0, `rgb(64,77,143)`],
                [.02, `rgb(50,86,142)`],
                [.06, `rgb(50,123,142)`],
                [.1, `rgb(64,120,103)`],
                [.15, `rgb(50,133,50)`],
                [.2, `rgb(50,141,50)`],
                [.3, `rgb(142,132,50)`],
                [.4, `rgb(142,113,50)`],
                [.5, `rgb(130,77,61)`],
                [.6, `rgb(115,50,68)`],
                [.7, `rgb(142,50,104)`],
                [.8, `rgb(105,68,131)`],
                [.85, `rgb(81,70,131)`],
                [.9, `rgb(65,98,131)`],
                [1, `rgb(73,122,131)`],
                [1.5, `rgb(143,143,143)`],
                [4, `rgb(143,143,143)`]
            ]
        }),
        visibility: new z({
            ident: `visibility`,
            steps: 1024,
            default: Cn(to, [0, 1600, 2200, 5e3, 6e3, 8e3, 9e3, 15e3, 20004])
        }),
        gtco3: new z({
            ident: `gtco3`,
            steps: 512,
            default: [
                [180, `rgb(53,25,47)`],
                [218, `rgb(162,70,145)`],
                [223, `rgb(110,81,217)`],
                [260, `rgb(79,151,193)`],
                [320, `rgb(82,203,167)`],
                [360, `rgb(59,197,67)`],
                [420, `rgb(231,174,5)`],
                [500, `rgb(232,83,25)`]
            ]
        }),
        aod550: new z({
            ident: `aod550`,
            steps: 4096,
            default: Cn(eo, [0, .25, .5, 1, 2, 3, 4])
        }),
        pm2p5: new z({
            ident: `pm2p5`,
            steps: 4096,
            default: Cn(eo, [0, 10, 15, 25, 150, 200, 300])
        }),
        no2: new z({
            ident: `no2`,
            steps: 4096,
            default: Cn(eo, [0, 1.5, 2, 3, 30, 40, 100])
        }),
        tcso2: new z({
            ident: `tcso2`,
            steps: 4096,
            default: Cn(eo, [0, 1.5, 2, 3, 30, 40, 100])
        }),
        go3: new z({
            ident: `go3`,
            steps: 4096,
            default: Cn(eo, [25, 75, 85, 105, 160, 200, 250])
        }),
        cosc: new z({
            ident: `cosc`,
            steps: 4e3,
            default: [
                [0, `rgb(124,124,124)`],
                [70, `rgb(124,124,108)`],
                [110, `rgb(164,157,72)`],
                [200, `rgb(136,113,47)`],
                [450, `rgb(39,31,31)`],
                [2200, `rgb(255,22,22)`]
            ]
        }),
        dust: new z({
            ident: `dust`,
            steps: 8e3,
            default: [
                [0, `rgb(171,171,171)`],
                [10, `rgb(148,137,118)`],
                [80, `rgb(124,104,59)`],
                [800, `rgb(100,73,0)`],
                [1200, `rgb(74,44,0)`]
            ]
        }),
        radar: new z({
            ident: `radar`,
            opaque: !1,
            default: [
                [0, `rgba(40,16,158,0)`],
                [3, `rgba(40,16,158,0.078)`],
                [8, `rgba(40,16,158,0.392)`],
                [14, `rgba(0,101,154,0.706)`],
                [20, `rgba(0,144,147,0.863)`],
                [26, `rgba(0,179,125,0.941)`],
                [32, `rgba(117,208,89,1)`],
                [36, `rgba(220,220,30,1)`],
                [40, `rgba(244,202,8,1)`],
                [44, `rgba(245,168,24,1)`],
                [48, `rgba(236,130,63,1)`],
                [52, `rgba(205,75,75,1)`],
                [56, `rgba(182,45,100,1)`],
                [60, `rgba(156,16,109,1)`],
                [64, `rgba(125,0,108,1)`],
                [68, `rgba(92,0,100,1)`],
                [100, `rgba(0,0,0,1)`],
                [101, `rgba(0,0,0,0)`],
                [255, `rgba(0,0,0,0)`]
            ],
            minMaxValue: [0, 256]
        }),
        satellite: new z({
            ident: `satellite`,
            steps: 256,
            opaque: !1,
            default: [
                [0, `rgb(24,24,24)`],
                [149, `rgb(240,240,240)`],
                [150, `rgb(64,64,163)`],
                [159, `rgb(70,106,227)`],
                [168, `rgb(41,187,236)`],
                [177, `rgb(49,241,153)`],
                [186, `rgb(163,253,61)`],
                [195, `rgb(237,208,59)`],
                [205, `rgb(251,128,34)`],
                [214, `rgb(210,49,4)`],
                [223, `rgb(122,4,3)`],
                [256, `rgb(48,0,0)`]
            ],
            minMaxValue: [0, 256]
        }),
        fog: new z({
            ident: `fog`,
            steps: 512,
            default: [
                [0, `rgb(110,110,110)`],
                [1, `rgb(200,200,200)`],
                [2, `rgb(200,200,255)`]
            ]
        }),
        justGray: new z({
            ident: `justGray`,
            steps: 4,
            default: [
                [-2e4, `rgb(111,111,111)`],
                [2e4, `rgb(111,111,111)`]
            ]
        }),
        efiWind: new z({
            ident: `efiWind`,
            steps: 256,
            default: [
                [-1, `rgb(5,165,189)`],
                [-.8, `rgb(30,175,119)`],
                [-.4, `rgb(111,111,111)`],
                [.4, `rgb(111,111,111)`],
                [.8, `rgb(187,174,24)`],
                [1, `rgb(189,80,32)`]
            ]
        }),
        efiTemp: new z({
            ident: `efiTemp`,
            steps: 256,
            default: [
                [-1, `rgb(43,54,209)`],
                [-.8, `rgb(60,164,179)`],
                [-.4, `rgb(111,111,111)`],
                [.4, `rgb(111,111,111)`],
                [.8, `rgb(128,147,24)`],
                [1, `rgb(213,0,110)`]
            ]
        }),
        efiRain: new z({
            ident: `efiRain`,
            steps: 256,
            default: [
                [-1, `rgb(151,75,0)`],
                [-.8, `rgb(187,180,0)`],
                [-.4, `rgb(111,111,111)`],
                [.4, `rgb(111,111,111)`],
                [.8, `rgb(1,162,177)`],
                [1, `rgb(4,8,181)`]
            ]
        }),
        moistureAnom40: new z({
            ident: `moistureAnom40`,
            steps: 1024,
            default: Cn($a, [-40, -32, -25, -19, -13, -8, -5, -3, -2, -1, 0, 1, 2, 3, 5, 8, 13, 19, 25, 32, 40])
        }),
        moistureAnom100: new z({
            ident: `moistureAnom100`,
            steps: 1024,
            default: Cn($a, [-100, -80, -55, -40, -25, -16, -10, -6, -4, -2, 0, 2, 4, 6, 10, 16, 25, 40, 55, 80, 100])
        }),
        drought: new z({
            ident: `drought`,
            steps: 1024,
            default: [
                [-1, `rgb(200,200,200)`],
                [-.5, `rgb(200,200,200)`],
                [-.49, `rgb(240,222,120)`],
                [.5, `rgb(240,222,120)`],
                [.51, `rgb(235,183,50)`],
                [1.5, `rgb(235,183,50)`],
                [1.51, `rgb(220,143,13)`],
                [2.5, `rgb(220,143,13)`],
                [2.51, `rgb(193,95,0)`],
                [3.5, `rgb(193,95,0)`],
                [3.51, `rgb(157,34,12)`],
                [4.5, `rgb(157,34,12)`],
                [4.51, `rgb(120,0,19)`],
                [5, `rgb(120,0,19)`]
            ]
        }),
        soilMoisture: new z({
            ident: `soilMoisture`,
            steps: 1024,
            default: [
                [0, `rgb(101,59,9)`],
                [10, `rgb(170,118,79)`],
                [20, `rgb(205,163,137)`],
                [30, `rgb(233,203,187)`],
                [40, `rgb(251,236,228)`],
                [50, `rgb(255,255,255)`],
                [60, `rgb(231,239,253)`],
                [70, `rgb(193,210,236)`],
                [80, `rgb(146,174,212)`],
                [90, `rgb(89,133,182)`],
                [100, `rgb(6,86,141)`]
            ]
        }),
        fwi: new z({
            ident: `fwi`,
            steps: 256,
            default: [
                [.5, `rgb(81,178,55)`],
                [1.49, `rgb(81,178,55)`],
                [1.5, `rgb(234,235,3)`],
                [2.49, `rgb(234,235,3)`],
                [2.5, `rgb(237,151,58)`],
                [3.49, `rgb(237,151,58)`],
                [3.5, `rgb(224,64,47)`],
                [4.49, `rgb(224,64,47)`],
                [4.5, `rgb(171,36,27)`],
                [5.49, `rgb(171,36,27)`],
                [5.5, `rgb(117,55,143)`],
                [6.49, `rgb(117,55,143)`]
            ]
        }),
        dfm10h: new z({
            ident: `dfm10h`,
            steps: 1024,
            default: [
                [2, `rgb(111,11,3)`],
                [4, `rgb(214,81,26)`],
                [6, `rgb(249,159,64)`],
                [8, `rgb(249,229,79)`],
                [10, `rgb(251,255,191)`],
                [11.5, `rgb(239,239,239)`],
                [13, `rgb(205,228,254)`],
                [16, `rgb(139,172,253)`],
                [20, `rgb(82,127,207)`],
                [25, `rgb(44,61,158)`],
                [35, `rgb(26,34,113)`]
            ]
        }),
        solarpower: new z({
            ident: `solarpower`,
            steps: 2e3,
            default: [
                [0, `rgb(110,110,110)`],
                [5, `rgb(122,105,106)`],
                [50, `rgb(194,53,81)`],
                [100, `rgb(199,66,81)`],
                [200, `rgb(208,90,81)`],
                [400, `rgb(226,131,90)`],
                [600, `rgb(242,170,110)`],
                [800, `rgb(255,208,141)`],
                [1e3, `rgb(255,245,180)`],
                [1150, `rgb(255,255,255)`]
            ]
        }),
        uvindex: new z({
            ident: `uvindex`,
            steps: 4096,
            default: [
                [0, `rgb(110,110,110)`],
                [2, `rgb(61,167,46)`],
                [5, `rgb(255,243,0)`],
                [7, `rgb(241,139,1)`],
                [10, `rgb(229,50,17)`],
                [11, `rgb(181,103,164)`],
                [19, `rgb(255,255,255)`]
            ]
        }),
        wetbulbtemp: new z({
            ident: `wetbulbtemp`,
            steps: 2048,
            default: [
                [203, `rgb(128,128,128)`],
                [273.15, `rgb(255,255,255)`],
                [283.2, `rgb(241,236,197)`],
                [291.5, `rgb(229,216,65)`],
                [295.4, `rgb(240,190,0)`],
                [298, `rgb(237,152,0)`],
                [300, `rgb(223,106,0)`],
                [302, `rgb(201,44,44)`],
                [304, `rgb(128,0,0)`],
                [305, `rgb(0,0,0)`]
            ]
        }),
        turbulence: new z({
            ident: `turbulence`,
            steps: 1024,
            default: [
                [0, `rgb(121,121,121)`],
                [10, `rgb(152,228,216)`],
                [20, `rgb(112,215,174)`],
                [30, `rgb(110,197,120)`],
                [40, `rgb(130,174,46)`],
                [50, `rgb(151,149,0)`],
                [60, `rgb(165,121,0)`],
                [70, `rgb(172,89,0)`],
                [80, `rgb(166,57,42)`],
                [90, `rgb(154,13,81)`],
                [100, `rgb(137,0,101)`]
            ]
        }),
        icing: new z({
            ident: `icing`,
            steps: 2048,
            default: [
                [24.9, `rgb(121,121,121)`],
                [25, `rgb(141,212,239)`],
                [29.9, `rgb(141,212,239)`],
                [30, `rgb(89,176,228)`],
                [34.9, `rgb(89,176,228)`],
                [35, `rgb(57,129,207)`],
                [54.9, `rgb(57,129,207)`],
                [55, `rgb(55,68,186)`]
            ]
        }),
        aqi: new z({
            ident: `aqi`,
            steps: 2048,
            default: [
                [0, `rgb(20,140,20)`],
                [30, `rgb(0,114,0)`],
                [50, `rgb(204,243,50)`],
                [60, `rgb(182,182,4)`],
                [80, `rgb(255,197,81)`],
                [100, `rgb(201,131,60)`],
                [150, `rgb(171,50,50)`],
                [200, `rgb(176,78,185)`],
                [300, `rgb(186,47,87)`],
                [1e3, `rgb(47,9,20)`]
            ]
        }),
        dewpoint: new z({
            ident: `dewpoint`,
            steps: 2048,
            prepare: !0,
            default: [
                [203, `rgb(115, 70, 105)`],
                [218, `rgb(202, 172, 195)`],
                [233, `rgb(162, 70, 145)`],
                [248, `rgb(143, 89, 169)`],
                [258, `rgb(157, 219, 217)`],
                [265, `rgb(106, 191, 181)`],
                [269, `rgb(100, 166, 189)`],
                [273.15, `rgb(93, 133, 198)`],
                [274, `rgb(68, 125, 99)`],
                [283, `rgb(128, 147, 24)`],
                [294, `rgb(243, 183, 4)`],
                [303, `rgb(232, 83, 25)`],
                [320, `rgb(71, 14, 0)`]
            ]
        }),
        wavePower: new z({
            ident: `wavePower`,
            steps: 2048,
            default: [
                [0, `rgb(88, 92, 209)`],
                [2, `rgb(91, 140, 196)`],
                [5, `rgb(75, 162, 163)`],
                [8, `rgb(42, 120, 111)`],
                [10, `rgb(56, 133, 104)`],
                [13, `rgb(65, 150, 104)`],
                [16, `rgb(110, 161, 69)`],
                [20, `rgb(167, 191, 71)`],
                [25, `rgb(207, 198, 82)`],
                [30, `rgb(222, 195, 85)`],
                [35, `rgb(212, 166, 69)`],
                [40, `rgb(214, 141, 72)`],
                [70, `rgb(224, 113, 65)`],
                [100, `rgb(250, 55, 178)`],
                [300, `rgb(209, 50, 209)`]
            ]
        }),
        fallback: new z({
            ident: `fallback`,
            steps: 4,
            prepare: !0,
            default: [
                [-2e4, `rgb(111,111,111)`],
                [2e4, `rgb(111,111,111)`]
            ]
        })
    };
var no = b({
        Overlay: () => V
    }),
    V = class {
        constructor(e) {
            var t, n, r, i, a, o, s, c, l, u, d, f, p, m, h, g, _, v, ee, te, y, ne, re, ie, b, ae, oe;
            C(this, `ident`, void 0), C(this, `trans`, void 0), C(this, `transShort`, void 0), C(this, `hasMoreLevels`, void 0), C(this, `icon`, void 0), C(this, `layers`, void 0), C(this, `globeNotSupported`, void 0), C(this, `poiCities`, void 0), C(this, `hidePickerElevation`, void 0), C(this, `shortname`, void 0), C(this, `fullname`, void 0), C(this, `menuIcon`, void 0), C(this, `menuTrans`, void 0), C(this, `partOf`, void 0), C(this, `hideParticles`, void 0), C(this, `isAccu`, void 0), C(this, `allwaysOn`, void 0), C(this, `convertValue`, void 0), C(this, `convertNumber`, void 0), C(this, `setMetric`, void 0), C(this, `cycleMetric`, void 0), C(this, `listMetrics`, void 0), C(this, `overlayMetric`, void 0), C(this, `overlayColor`, void 0), C(this, `alternativeLegend`, void 0), C(this, `hideFromURL`, void 0), C(this, `promoBadge`, void 0), C(this, `promoBadgeColor`, void 0), C(this, `menuImage`, void 0), this.initProperties(), this.ident = e.ident, this.overlayColor = (t = (n = e.overlayColor) == null ? this.overlayColor : n) == null ? B.fallback : t, this.trans = (r = e.trans) == null ? this.trans : r, this.icon = (i = e.icon) == null ? this.icon : i, this.transShort = (a = e.transShort) == null ? this.transShort : a, this.hasMoreLevels = (o = e.hasMoreLevels) == null ? this.hasMoreLevels : o, this.layers = (s = e.layers) == null ? this.layers : s, this.globeNotSupported = (c = e.globeNotSupported) == null ? this.globeNotSupported : c, this.poiCities = (l = e.poiCities) == null ? this.poiCities : l, this.hidePickerElevation = (u = e.hidePickerElevation) == null ? this.hidePickerElevation : u, this.shortname = (d = e.shortname) == null ? this.shortname : d, this.fullname = (f = e.fullname) == null ? this.fullname : f, this.menuIcon = (p = e.menuIcon) == null ? this.menuIcon : p, this.menuTrans = (m = e.menuTrans) == null ? this.menuTrans : m, this.partOf = (h = e.partOf) == null ? this.partOf : h, this.hideParticles = (g = e.hideParticles) == null ? this.hideParticles : g, this.isAccu = (_ = e.isAccu) == null ? this.isAccu : _, this.allwaysOn = (v = e.allwaysOn) == null ? this.allwaysOn : v, this.overlayMetric = (ee = e.overlayMetric) == null ? this.overlayMetric : ee, this.alternativeLegend = (te = e.alternativeLegend) == null ? this.alternativeLegend : te, this.hideFromURL = (y = e.hideFromURL) == null ? this.hideFromURL : y, this.promoBadge = (ne = e.promoBadge) == null ? this.promoBadge : ne, this.promoBadgeColor = (re = e.promoBadgeColor) == null ? this.promoBadgeColor : re, this.menuImage = (ie = e.menuImage) == null ? this.menuImage : ie, this.createPickerHTML = (b = e.createPickerHTML) == null ? this.createPickerHTML : b, this.onClick = (ae = e.onClick) == null ? this.onClick : ae;
            let se = (oe = this.overlayMetric) == null ? R.fallback : oe;
            this.convertValue = se.convertValue.bind(se), this.convertNumber = se.convertNumber.bind(se), this.setMetric = se.setMetric.bind(se), this.cycleMetric = se.cycleMetric.bind(se), this.listMetrics = se.listMetrics.bind(se)
        }
        onClick() {
            M.set(`overlay`, this.ident)
        }
        paintLegend(e) {
            var t;
            let n = this.alternativeLegend || ((t = this.overlayMetric) == null ? void 0 : t.legend);
            if (n) {
                var r;
                ri(e, n, this.overlayColor, (r = this.overlayMetric) == null ? void 0 : r.metric)
            } else e.innerHTML = ``, e.style.background = `transparent`
        }
        getName(e) {
            return (e && this.transShort ? P[this.transShort] : P[this.trans]) || this.ident
        }
        getMenuImagePath() {
            return `/img/menu3/${this.menuImage || this.ident}.jpg`
        }
        getMenuName(e) {
            return this.menuTrans ? this.menuTrans in P && P[this.menuTrans] ? P[this.menuTrans] : this.ident : this.getName(e)
        }
        getMenuIdent() {
            return this.partOf || this.ident
        }
        createPickerHTML(e, t) {
            if (this.convertValue && this.overlayMetric) {
                let [t] = e;
                return `<big class="picker-change-metric">${this.overlayMetric.howManyMetrics() > 1 ? this.convertValue(t, ` <span>`, `</span>`) : this.convertValue(t, ` `)}</big>`
            } else return ``
        }
        get metric() {
            return this.overlayMetric ? this.overlayMetric.metric : ``
        }
        initProperties() {
            this.poiCities = `full`
        }
    },
    ro = b({
        AqiOverlay: () => uo,
        AwpOverlay: () => oo,
        CloudsOverlay: () => lo,
        CurrentOverlay: () => io,
        FwiOverlay: () => so,
        RadarOverlay: () => fo,
        RainPtypeOverlay: () => co,
        SatelliteOverlay: () => po,
        WaveOverlay: () => ao
    }),
    io = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        createPickerHTML(e, t) {
            let n = Ct(e),
                r = Et(n);
            return `<big class="picker-change-metric">${this.convertValue(n.wind, ` <span>`, `</span>`)}<i title="Direction to">${r}${t(Tt(n) ? (n.dir + 180) % 360 : ``)}</i></big>`
        }
    },
    ao = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        initProperties() {
            super.initProperties(), this.overlayColor = B.waves, this.overlayMetric = R.waves
        }
        createPickerHTML(e, t) {
            let n = wt(e);
            return `<big class="picker-change-metric">${this.convertValue(n.size, ` <span>`, `</span>`)}<i title="Direction from, true north" data-dir="${n.dir}">${t(n.dir)}</i></big>
        <div class="picker-subtext">${P.PERIOD} ${Math.round(n.period)} s.</div>`
        }
    },
    oo = class extends V {
        createPickerHTML(e) {
            return `<big>${this.convertValue(e[0])}</big>`
        }
    },
    so = class extends V {
        createPickerHTML(e) {
            return `<big>${this.convertValue(e[0])}</big>`
        }
    },
    co = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        createPickerHTML(e) {
            let t = e[1],
                n = `${R.ptype.convertValue(t) || P.RAIN} (3h)`;
            return `<big class="picker-change-metric">${(t == 5 || t == 6 ? R.snow : R.rain).convertValue(e[0], ` <span>`, `</span>`)}</span></big><div class="picker-subtext">${n}</div>`
        }
    },
    lo = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        createPickerHTML(e) {
            return `<big>${Math.floor(e[0])} %</big>${e[1] > .3 ? `<div class="picker-subtext">${P.D_PRECI}: ${R.rain.convertValue(e[1], ` `)} (3h)</div>` : ``}`
        }
    },
    uo = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0), C(this, `labels`, {
                0: `AIRQ_RANGE_GOOD`,
                1: `AIRQ_RANGE_MODERATE`,
                2: `AIRQ_RANGE_UNHEALTHY_SENSITIVE`,
                3: `AIRQ_RANGE_UNHEALTHY`,
                4: `AIRQ_RANGE_VERY_UNHEALTHY`,
                5: `AIRQ_RANGE_HAZARDOUS`
            })
        }
        getAirQLabel(e) {
            if (e > 301) return P[this.labels[5]];
            if (e > 201) return P[this.labels[4]];
            {
                let t = Math.floor(e / 50);
                return P[this.labels[t]]
            }
        }
        createPickerHTML(e) {
            let t = Math.round(e[0]);
            return `<big>${t} AQI</big>
                <div class="picker-subtext">${this.getAirQLabel(t)}</div>`
        }
    },
    fo = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        createPickerHTML(e) {
            let t = e[2],
                n = M.get(`radarRenderPType`),
                r = document.createElement(`big`);
            r.innerText = this.convertValue(t, ` `);
            let i = document.createElement(`div`);
            if (i.appendChild(r), n) {
                let n = e[1],
                    r = t > 0 ? `${this.categorizePrecipitationValue(n)}` : `&nbsp;`,
                    a = document.createElement(`div`);
                a.classList.add(`picker-subtext`), a.innerHTML = r, i.appendChild(document.createElement(`br`)), i.appendChild(a)
            }
            return i.innerHTML
        }
        categorizePrecipitationValue(e) {
            return `${R.radarPType.convertValue(e) || P.JUST_RAIN}`
        }
    },
    po = class extends V {
        constructor(...e) {
            super(...e), C(this, `hidePickerElevation`, !0)
        }
        createPickerHTML(e) {
            let t = e[2];
            return `<big class="picker-change-metric">${this.convertValue(t, ` <span>`, `</span>`)}</big>`
        }
    };
const mo = {
        description: [`m`, `ft`],
        lines: [
            [0, 0, 0],
            [200, 300, 1e3],
            [500, 500, 1500],
            [1500, `1.5k`, 5e3]
        ]
    },
    ho = {
        description: [`m`, `ft`],
        lines: [
            [0, 0, 0],
            [1e3, `1k`, `3.3k`],
            [2e3, `2k`, `6.6k`],
            [3e3, `3k`, `10k`],
            [4e3, `4k`, `13k`],
            [6e3, `6k`, `20k`],
            [8e3, `8k`, `26k`]
        ]
    },
    go = {
        description: [`°C`, `°F`],
        lines: [
            [272, 0, 30],
            [282, 10, 50],
            [292, 20, 70],
            [302, 30, 85],
            [313, 40, 100]
        ]
    },
    _o = {
        description: [`m`, `ft`],
        lines: [
            [0, 0, 0],
            [5e3, `5k`, `FL150`],
            [9e3, `9k`, `FL300`],
            [12e3, `12k`, `FL400`],
            [15e3, `15k`, `FL500`]
        ]
    },
    vo = {
        description: [`mm`, `in`],
        lines: [
            [3, 3, `.1`],
            [10, 10, `.4`],
            [25, 25, `1.0`],
            [100, 100, `4.0`],
            [300, 300, `1ft`]
        ]
    },
    yo = {
        description: [`°C`, `°F`],
        lines: [
            [273, 0, 32],
            [291, 18, 64],
            [298, 25, 77],
            [302, 29, 84],
            [305, 32, 90]
        ]
    },
    bo = {
        isDiscrete: !0,
        hasEqualItemsWidth: !0,
        labels: [
            [`AVAL_NO_DATA`, `rgb(204,204,204)`],
            [`AVAL_LOW`, `rgb(186,211,124)`],
            [`AVAL_MODERATE`, `rgb(255,255,0)`],
            [`AVAL_CONSIDERABLE`, `rgb(254,152,0)`],
            [`AVAL_HIGH`, `rgb(253,0,0)`],
            [`AVAL_VERY_HIGH`, `rgb(180,0,0)`]
        ]
    },
    xo = {
        isDiscrete: !0,
        hasEqualItemsWidth: !0,
        labels: [
            [`INTERSUCHO_AWP_3`, `rgb(179, 179, 0)`],
            [`INTERSUCHO_AWP_4`, `rgb(193, 125, 0)`],
            [`INTERSUCHO_AWP_6`, `rgb(165, 0, 0)`]
        ]
    },
    So = new V({
        ident: `wind`,
        overlayColor: B.wind,
        overlayMetric: R.wind,
        hasMoreLevels: !0,
        trans: `WIND`,
        icon: `|`,
        layers: [`windParticles`, `wind`],
        globeNotSupported: !1,
        hideFromURL: !0,
        createPickerHTML(e, t) {
            let n = Ct(e),
                r = Et(n);
            return `<big class="picker-change-metric">${this.convertValue(n.wind, ` <span>`, `</span>`)}<i title="Wind direction from true north">${r}${t(n.dir)}</i></big>`
        }
    }),
    Co = new V({
        ident: `temp`,
        overlayColor: B.temp,
        overlayMetric: R.temp,
        trans: `TEMP`,
        icon: ``,
        layers: [`windParticles`, `temp`],
        hasMoreLevels: !0
    }),
    wo = new V({
        ident: `wetbulbtemp`,
        overlayColor: B.wetbulbtemp,
        overlayMetric: R.temp,
        alternativeLegend: yo,
        trans: `WETBULB_TEMP`,
        icon: ``,
        layers: [`windParticles`, `wetbulbtemp`]
    }),
    To = new V({
        ident: `solarpower`,
        overlayColor: B.solarpower,
        overlayMetric: R.solarpower,
        trans: `SOLARPOWER`,
        icon: `z`,
        layers: [`ecmwfWindParticles`, `solarpower`]
    }),
    Eo = new V({
        ident: `uvindex`,
        overlayColor: B.uvindex,
        overlayMetric: R.uvindex,
        trans: `UVINDEX`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `uvindex`]
    }),
    Do = new V({
        ident: `dewpoint`,
        overlayColor: B.dewpoint,
        overlayMetric: R.temp,
        trans: `DEW_POINT`,
        icon: ``,
        layers: [`windParticles`, `dewpoint`],
        hasMoreLevels: !0
    }),
    Oo = new V({
        ident: `gust`,
        overlayColor: B.wind,
        overlayMetric: R.wind,
        trans: `GUST`,
        icon: ``,
        layers: [`windParticles`, `gust`]
    }),
    ko = new V({
        ident: `gustAccu`,
        overlayColor: B.wind,
        overlayMetric: R.wind,
        trans: `GUSTACCU`,
        icon: ``,
        isAccu: !0,
        layers: [`windParticles`, `gustAccu`]
    }),
    Ao = new V({
        ident: `rh`,
        icon: `/`,
        overlayColor: B.rh,
        overlayMetric: R.rh,
        trans: `RH`,
        layers: [`windParticles`, `rh`],
        hasMoreLevels: !0
    }),
    jo = new V({
        ident: `pressure`,
        overlayColor: B.pressure,
        overlayMetric: R.pressure,
        trans: `PRESS`,
        icon: ``,
        layers: [`windParticles`, `pressure`]
    }),
    Mo = new co({
        ident: `rain`,
        overlayColor: B.rain,
        overlayMetric: R.rain,
        trans: `RAIN_THUNDER`,
        transShort: `JUST_RAIN`,
        icon: ``,
        layers: [`windParticles`, `rain`]
    }),
    No = new lo({
        ident: `clouds`,
        overlayColor: B.rainClouds,
        overlayMetric: R.rain,
        trans: `CLOUDS2`,
        icon: `7`,
        layers: [`windParticles`, `clouds`]
    }),
    Po = new lo({
        ident: `lclouds`,
        overlayColor: B.lclouds,
        overlayMetric: R.clouds,
        trans: `LOW_CLOUDS`,
        icon: ``,
        layers: [`windParticles`, `lclouds`]
    }),
    Fo = new lo({
        ident: `mclouds`,
        overlayColor: B.mclouds,
        overlayMetric: R.clouds,
        trans: `MEDIUM_CLOUDS`,
        icon: ``,
        layers: [`windParticles`, `mclouds`]
    }),
    Io = new lo({
        ident: `hclouds`,
        overlayColor: B.hclouds,
        overlayMetric: R.clouds,
        trans: `HIGH_CLOUDS`,
        layers: [`windParticles`, `hclouds`],
        icon: ``
    }),
    Lo = new V({
        ident: `cape`,
        overlayColor: B.cape,
        overlayMetric: R.cape,
        trans: `CAPE`,
        layers: [`windParticles`, `cape`],
        icon: `~`
    }),
    Ro = new V({
        ident: `cbase`,
        overlayColor: B.cbase,
        overlayMetric: R.altitude,
        alternativeLegend: mo,
        trans: `CLOUD_ALT`,
        icon: `:`,
        layers: [`windParticles`, `cbase`]
    }),
    zo = new V({
        ident: `snowAccu`,
        overlayColor: B.snow,
        overlayMetric: R.snow,
        trans: `NEWSNOW`,
        icon: ``,
        isAccu: !0,
        layers: [`snowAccu`],
        hideParticles: !0
    }),
    Bo = new V({
        ident: `rainAccu`,
        overlayColor: B.rainAccu,
        overlayMetric: R.rain,
        alternativeLegend: vo,
        trans: `RACCU`,
        transShort: `RACCU_SHORT`,
        icon: `9`,
        isAccu: !0,
        layers: [`rainAccu`],
        hideParticles: !0,
        menuImage: `rainAccu-v2`
    }),
    Vo = new ao({
        ident: `waves`,
        poiCities: `markers`,
        trans: `WAVES`,
        icon: ``,
        layers: [`waveParticles`, `waves`]
    }),
    Ho = new ao({
        poiCities: `markers`,
        ident: `wwaves`,
        trans: `WWAVES`,
        icon: `|`,
        layers: [`waveParticles`, `wwaves`]
    }),
    Uo = new ao({
        poiCities: `markers`,
        ident: `swell1`,
        trans: `SWELL`,
        icon: `{`,
        layers: [`waveParticles`, `swell1`]
    }),
    Wo = new ao({
        poiCities: `markers`,
        ident: `swell2`,
        trans: `SWELL2`,
        icon: ``,
        layers: [`waveParticles`, `swell2`]
    }),
    Go = new ao({
        poiCities: `markers`,
        ident: `swell3`,
        trans: `SWELL3`,
        icon: ``,
        layers: [`waveParticles`, `swell3`]
    }),
    Ko = Uo,
    qo = new io({
        poiCities: `markers`,
        ident: `currents`,
        overlayColor: B.currents,
        overlayMetric: R.currents,
        trans: `CURRENT`,
        icon: `q`,
        layers: [`currentParticles`, `currents`]
    }),
    Jo = new io({
        poiCities: `markers`,
        ident: `currentsTide`,
        overlayColor: B.currents,
        overlayMetric: R.currents,
        trans: `CURRENT_TIDE`,
        icon: ``,
        layers: [`currentsTideParticles`, `currentsTide`]
    }),
    Yo = new V({
        poiCities: `markers`,
        ident: `wavePower`,
        overlayColor: B.wavePower,
        overlayMetric: R.wavePower,
        trans: `WAVE_POWER`,
        promoBadge: `NEW`,
        icon: ``,
        layers: [`waveParticlesWaves`, `wavePower`]
    }),
    Xo = new V({
        poiCities: `markers`,
        hidePickerElevation: !0,
        ident: `sst`,
        overlayColor: B.temp,
        overlayMetric: R.temp,
        alternativeLegend: go,
        trans: `SST2`,
        icon: ``,
        layers: [`currentParticles`, `sst`]
    }),
    Zo = new V({
        ident: `visibility`,
        overlayColor: B.visibility,
        overlayMetric: R.visibility,
        trans: `VISIBILITY`,
        icon: `c`,
        layers: [`windParticles`, `visibility`]
    }),
    Qo = new V({
        ident: `fog`,
        overlayColor: B.fog,
        overlayMetric: R.fog,
        trans: `FOG`,
        icon: `d`,
        layers: [`fog`],
        hideParticles: !0
    }),
    $o = new V({
        ident: `thunder`,
        overlayColor: B.lightDensity,
        overlayMetric: R.lightDensity,
        trans: `THUNDER`,
        icon: ``,
        layers: [`windParticles`, `thunder`]
    }),
    es = new V({
        ident: `snowcover`,
        overlayColor: B.snow,
        overlayMetric: R.snow,
        trans: `SNOWDEPTH`,
        icon: `N`,
        layers: [`windParticles`, `snowcover`],
        hidePickerElevation: !0,
        createPickerHTML(e) {
            let t = e[0],
                n;
            return n = t > 500 ? `> ${this.overlayMetric.metric === `cm` ? `5m` : `16ft`}` : this.convertValue(t, ` <span>`, `</span>`), `<big class="picker-change-metric">${n}</big><div class="picker-subtext">${t > .5 ? P.SNOWDENSITY + ` ` + Math.round(e[1]) + ` kg/m3` : ``}</div>`
        }
    }),
    ts = new V({
        ident: `cloudtop`,
        overlayColor: B.levels,
        overlayMetric: R.altitude,
        alternativeLegend: _o,
        trans: `CTOP`,
        icon: `Q`,
        layers: [`windParticles`, `cloudtop`]
    }),
    ns = new V({
        ident: `deg0`,
        overlayColor: B.deg0,
        overlayMetric: R.altitude,
        trans: `FREEZING`,
        icon: ``,
        layers: [`windParticles`, `deg0`]
    }),
    rs = new V({
        ident: `gtco3`,
        overlayColor: B.gtco3,
        overlayMetric: R.gtco3,
        trans: `OZONE`,
        icon: ``,
        layers: [`ecmwfWindParticles150h`, `gtco3`]
    }),
    is = new V({
        ident: `pm2p5`,
        overlayColor: B.pm2p5,
        overlayMetric: R.pm2p5,
        trans: `PM2P5`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `pm2p5`]
    }),
    as = new V({
        ident: `no2`,
        overlayColor: B.no2,
        overlayMetric: R.no2,
        trans: `NO22`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `no2`]
    }),
    os = new V({
        ident: `aod550`,
        overlayColor: B.aod550,
        overlayMetric: R.aod550,
        trans: `AOD550`,
        icon: ``,
        layers: [`ecmwfWindParticles600h`, `aod550`]
    }),
    ss = new V({
        ident: `tcso2`,
        overlayColor: B.tcso2,
        overlayMetric: R.tcso2,
        trans: `TCSO2`,
        icon: ``,
        layers: [`ecmwfWindParticles500h`, `tcso2`]
    }),
    cs = new V({
        ident: `go3`,
        overlayColor: B.go3,
        overlayMetric: R.go3,
        trans: `GO3`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `go3`]
    }),
    ls = new V({
        ident: `cosc`,
        overlayColor: B.cosc,
        overlayMetric: R.cosc,
        trans: `COSC`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `cosc`]
    }),
    us = new V({
        ident: `dustsm`,
        overlayColor: B.dust,
        overlayMetric: R.dust,
        trans: `DUSTSM`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `dustsm`]
    }),
    ds = new uo({
        ident: `aqi`,
        overlayColor: B.aqi,
        overlayMetric: R.aqi,
        trans: `AQI`,
        icon: ``,
        layers: [`ecmwfWindParticles`, `aqi`]
    }),
    fs = new co({
        ident: `ptype`,
        overlayColor: B.justGray,
        overlayMetric: R.ptype,
        trans: `PTYPE`,
        icon: ``,
        layers: [`windParticles`, `ptype`]
    }),
    ps = new V({
        ident: `ccl`,
        overlayColor: B.cclAltitude,
        overlayMetric: R.altitude,
        alternativeLegend: ho,
        trans: `CCL`,
        icon: ``,
        layers: [`ccl`, `windParticles`]
    }),
    ms = new fo({
        allwaysOn: !0,
        poiCities: `none`,
        globeNotSupported: !0,
        ident: `radar`,
        overlayColor: B.radar,
        overlayMetric: R.radar,
        trans: `RADAR`,
        transShort: `RADAR_SHORT`,
        icon: ``,
        layers: [`radar`],
        hideParticles: !0
    }),
    hs = new po({
        allwaysOn: !0,
        poiCities: `none`,
        globeNotSupported: !0,
        ident: `satellite`,
        overlayColor: B.satellite,
        overlayMetric: R.satellite,
        trans: `SATELLITE`,
        icon: ``,
        layers: [`satellite`],
        menuImage: `radarPlus`,
        hideParticles: !0
    }),
    gs = new V({
        ident: `capAlerts`,
        trans: `WX_WARNINGS`,
        globeNotSupported: !0,
        icon: ``,
        layers: [`capAlerts`],
        poiCities: `none`,
        alternativeLegend: xo
    }),
    _s = new V({
        ident: `avalancheDanger`,
        trans: `AVALANCHE_DANGER`,
        globeNotSupported: !0,
        promoBadge: `NEW`,
        icon: `n`,
        layers: [`avalancheDanger`],
        poiCities: `none`,
        alternativeLegend: bo,
        createPickerHTML(e) {
            return `<small>Click on region to open avalanche bulletin</small>`
        }
    }),
    vs = {
        menuIcon: ``,
        menuTrans: `EFORECAST`
    },
    ys = new V(w(w({}, vs), {}, {
        icon: ``,
        trans: `TEMP`,
        hideParticles: !0,
        ident: `efiTemp`,
        overlayColor: B.efiTemp,
        overlayMetric: R.efiTemp,
        fullname: `${P.EFORECAST} - ${P.TEMP}`,
        layers: [`efiTemp`]
    })),
    bs = new V(w(w({}, vs), {}, {
        icon: `|`,
        trans: `WIND`,
        hideParticles: !0,
        ident: `efiWind`,
        overlayColor: B.efiWind,
        overlayMetric: R.efiWind,
        fullname: `${P.EFORECAST} - ${P.WIND}`,
        partOf: `efiTemp`,
        layers: [`efiWind`]
    })),
    xs = new V(w(w({}, vs), {}, {
        icon: ``,
        trans: `JUST_RAIN`,
        hideParticles: !0,
        ident: `efiRain`,
        overlayColor: B.efiRain,
        overlayMetric: R.efiRain,
        fullname: `${P.EFORECAST} - ${P.JUST_RAIN}`,
        partOf: `efiTemp`,
        layers: [`efiRain`]
    })),
    Ss = {
        menuIcon: ``,
        menuTrans: `INTERSUCHO`
    },
    Cs = new oo(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWP`,
        fullname: `${P.INTERSUCHO_AWP} - ${P.INTERSUCHO_40}`,
        shortname: P.INTERSUCHO_40,
        hideParticles: !0,
        ident: `drought40`,
        overlayColor: B.drought,
        overlayMetric: R.drought,
        layers: [`drought40`]
    })),
    ws = new oo(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWP`,
        hideParticles: !0,
        ident: `drought100`,
        overlayColor: B.drought,
        overlayMetric: R.drought,
        fullname: `${P.INTERSUCHO_AWP} - ${P.INTERSUCHO_100}`,
        shortname: P.INTERSUCHO_100,
        partOf: `drought40`,
        layers: [`drought100`]
    })),
    Ts = new V(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWD`,
        fullname: `${P.INTERSUCHO_AWD} - ${P.INTERSUCHO_40}`,
        shortname: P.INTERSUCHO_40,
        hideParticles: !0,
        ident: `moistureAnom40`,
        overlayColor: B.moistureAnom40,
        overlayMetric: R.moistureAnom40,
        partOf: `drought40`,
        layers: [`moistureAnom40`]
    })),
    Es = new V(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWD`,
        fullname: `${P.INTERSUCHO_AWD} - ${P.INTERSUCHO_100}`,
        shortname: P.INTERSUCHO_100,
        hideParticles: !0,
        ident: `moistureAnom100`,
        overlayColor: B.moistureAnom100,
        overlayMetric: R.moistureAnom100,
        partOf: `drought40`,
        layers: [`moistureAnom100`]
    })),
    Ds = new V(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWR`,
        fullname: `${P.INTERSUCHO_AWR} - ${P.INTERSUCHO_40}`,
        shortname: P.INTERSUCHO_40,
        hideParticles: !0,
        ident: `soilMoisture40`,
        overlayColor: B.soilMoisture,
        overlayMetric: R.rh,
        partOf: `drought40`,
        layers: [`soilMoisture40`]
    })),
    Os = new V(w(w({}, Ss), {}, {
        icon: ``,
        trans: `INTERSUCHO_AWR`,
        fullname: `${P.INTERSUCHO_AWR} - ${P.INTERSUCHO_100}`,
        shortname: P.INTERSUCHO_100,
        hideParticles: !0,
        ident: `soilMoisture100`,
        overlayColor: B.soilMoisture,
        overlayMetric: R.rh,
        partOf: `drought40`,
        layers: [`soilMoisture100`]
    })),
    ks = {
        menuIcon: ``,
        menuTrans: `INTERSUCHO_FIRE_DANGER`
    },
    As = new so(w(w({}, ks), {}, {
        icon: ``,
        trans: `INTERSUCHO_FWI`,
        hideParticles: !0,
        ident: `fwi`,
        overlayColor: B.fwi,
        overlayMetric: R.fwi,
        layers: [`fwi`]
    })),
    js = new V(w(w({}, ks), {}, {
        icon: ``,
        trans: `INTERSUCHO_DFM`,
        hideParticles: !0,
        ident: `dfm10h`,
        overlayColor: B.dfm10h,
        overlayMetric: R.dfm10h,
        partOf: `fwi`,
        layers: [`dfm10h`]
    })),
    Ms = new V({
        icon: ``,
        trans: `TURBULENCE`,
        ident: `turbulence`,
        overlayColor: B.turbulence,
        overlayMetric: R.turbulence,
        layers: [`turbulence`, `windParticles`],
        hasMoreLevels: !0
    }),
    Ns = new V({
        icon: ``,
        trans: `ICING2`,
        ident: `icing`,
        overlayColor: B.icing,
        overlayMetric: R.icing,
        layers: [`icing`, `windParticles`],
        hasMoreLevels: !0
    }),
    Ps = new V({
        icon: ``,
        trans: `HEATMAP`,
        ident: `heatmaps`,
        hideFromURL: !0,
        promoBadge: `MBLUE`,
        promoBadgeColor: `rgb(107, 107, 107)`,
        onClick() {
            window.open(`https://www.meteoblue.com/products/cityclimate?utm_source=windy.com&utm_medium=referral&utm_campaign=menu-city-heatmaps`, `_blank`)
        }
    }),
    Fs = new V({
        icon: ``,
        trans: `HURR_TRACKER`,
        ident: `hurricanes`,
        layers: [`wind`],
        onClick() {
            N.emit(`rqstOpen`, `hurricanes`)
        }
    }),
    Is = {
        wind: So,
        temp: Co,
        wetbulbtemp: wo,
        solarpower: To,
        wavePower: Yo,
        uvindex: Eo,
        dewpoint: Do,
        gust: Oo,
        gustAccu: ko,
        turbulence: Ms,
        icing: Ns,
        rh: Ao,
        pressure: jo,
        rain: Mo,
        clouds: No,
        lclouds: Po,
        mclouds: Fo,
        hclouds: Io,
        cape: Lo,
        cbase: Ro,
        snowAccu: zo,
        rainAccu: Bo,
        waves: Vo,
        wwaves: Ho,
        swell1: Uo,
        swell2: Wo,
        swell3: Go,
        swell: Ko,
        currents: qo,
        currentsTide: Jo,
        sst: Xo,
        visibility: Zo,
        fog: Qo,
        thunder: $o,
        snowcover: es,
        cloudtop: ts,
        deg0: ns,
        gtco3: rs,
        pm2p5: is,
        no2: as,
        aod550: os,
        tcso2: ss,
        go3: cs,
        cosc: ls,
        dustsm: us,
        ptype: fs,
        ccl: ps,
        radar: ms,
        satellite: hs,
        capAlerts: gs,
        avalancheDanger: _s,
        efiWind: bs,
        efiTemp: ys,
        efiRain: xs,
        moistureAnom40: Ts,
        moistureAnom100: Es,
        drought40: Cs,
        drought100: ws,
        soilMoisture40: Ds,
        soilMoisture100: Os,
        fwi: As,
        dfm10h: js,
        heatmaps: Ps,
        topoMap: new V({
            ident: `topoMap`,
            trans: `HMAP`,
            globeNotSupported: !0,
            hideFromURL: !0,
            poiCities: `none`,
            icon: ``,
            layers: [`topoMap`],
            hideParticles: !0
        }),
        hurricanes: Fs,
        aqi: ds
    };
var Ls = b({
        Layer: () => H
    }),
    H = class {
        constructor(e) {
            var t, n, r, i, a, o, s, c, l, u, d, f, p, m, h, g, _;
            C(this, `c`, void 0), C(this, `ident`, void 0), C(this, `renderer`, void 0), C(this, `filename`, void 0), C(this, `dataQuality`, void 0), C(this, `fileSuffix`, void 0), C(this, `JPGtransparency`, void 0), C(this, `PNGtransparency`, void 0), C(this, `maxTileZoom`, void 0), C(this, `renderParams`, void 0), C(this, `product`, void 0), C(this, `levels`, void 0), C(this, `query`, void 0), C(this, `wTransformR`, void 0), C(this, `cm`, void 0), C(this, `transformR`, void 0), C(this, `transformG`, void 0), C(this, `transformB`, void 0), this.ident = e.ident, this.c = (t = e.c) == null ? this.c : t, this.renderer = (n = e.renderer) == null ? `tileLayer` : n, this.filename = (r = e.filename) == null ? this.filename : r, this.dataQuality = (i = e.dataQuality) == null ? this.dataQuality : i, this.fileSuffix = (a = e.fileSuffix) == null ? this.fileSuffix : a, this.JPGtransparency = (o = e.JPGtransparency) == null ? this.JPGtransparency : o, this.PNGtransparency = (s = e.PNGtransparency) == null ? this.PNGtransparency : s, this.maxTileZoom = (c = e.maxTileZoom) == null ? this.maxTileZoom : c, this.renderParams = (l = e.renderParams) == null ? this.renderParams : l, this.product = (u = e.product) == null ? this.product : u, this.levels = (d = e.levels) == null ? this.levels : d, this.query = (f = e.query) == null ? this.query : f, this.wTransformR = (p = e.wTransformR) == null ? this.wTransformR : p, this.cm = (m = e.cm) == null ? this.cm : m, this.transformR = (h = e.transformR) == null ? this.transformR : h, this.transformG = (g = e.transformG) == null ? this.transformG : g, this.transformB = (_ = e.transformB) == null ? this.transformB : _
        }
        getColor() {
            var e;
            return (e = this.c) == null ? void 0 : e.getColor()
        }
    };
const Rs = e => Math.max(0, 2 ** e - .001),
    zs = e => t => 2 ** t - e,
    Bs = new H({
        ident: `capAlerts`,
        renderer: `capAlerts`,
        levels: [`surface`]
    }),
    Vs = new H({
        ident: `pressureIsolines`,
        renderer: `isolines`,
        levels: [`surface`]
    }),
    Hs = new H({
        ident: `ghIsolines`,
        renderer: `isolines`,
        levels: [`975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`, `10h`]
    }),
    Us = new H({
        ident: `tempIsolines`,
        renderer: `isolines`,
        levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`, `10h`]
    }),
    Ws = new H({
        ident: `deg0Isolines`,
        renderer: `isolines`,
        levels: [`surface`]
    }),
    Gs = new H({
        ident: `windParticles`,
        renderer: `particles`,
        filename: `wind`,
        fileSuffix: `jpg`,
        renderParams: {
            particlesIdent: `wind`
        }
    }),
    Ks = new H({
        ident: `ecmwfWindParticles`,
        renderer: `particles`,
        product: `ecmwf`,
        levels: [`surface`],
        filename: `wind`,
        fileSuffix: `jpg`,
        renderParams: {
            particlesIdent: `wind`
        }
    }),
    qs = new H({
        ident: `ecmwfWindParticles150h`,
        renderer: `particles`,
        product: `ecmwf`,
        levels: [`surface`],
        filename: `wind`,
        fileSuffix: `jpg`,
        renderParams: {
            particlesIdent: `wind`
        }
    }),
    Js = new H({
        ident: `ecmwfWindParticles500h`,
        renderer: `particles`,
        product: `ecmwf`,
        levels: [`surface`],
        filename: `wind`,
        fileSuffix: `jpg`,
        renderParams: {
            particlesIdent: `wind`
        }
    }),
    Ys = new H({
        ident: `ecmwfWindParticles600h`,
        renderer: `particles`,
        product: `ecmwf`,
        levels: [`surface`],
        filename: `wind`,
        fileSuffix: `jpg`,
        renderParams: {
            particlesIdent: `wind`
        }
    }),
    Xs = new H({
        ident: `waveParticles`,
        renderer: `particles`,
        PNGtransparency: !0,
        renderParams: {
            particlesIdent: `waves`,
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    Zs = new H({
        ident: `waveParticlesWaves`,
        renderer: `particles`,
        PNGtransparency: !0,
        filename: `waves`,
        fileSuffix: `png`,
        renderParams: {
            particlesIdent: `waves`,
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    Qs = new H({
        ident: `currentParticles`,
        renderer: `particles`,
        filename: `seacurrents`,
        product: `cmems`,
        renderParams: {
            particlesIdent: `currents`
        }
    }),
    $s = new H({
        ident: `currentsTideParticles`,
        renderer: `particles`,
        filename: `seacurrents_tide`,
        renderParams: {
            particlesIdent: `currents`
        }
    }),
    ec = new H({
        ident: `wind`,
        filename: `wind`,
        renderParams: {
            shaderDefines: [`VECTOR_SIZE`, `BICUBIC`]
        },
        c: B.wind
    }),
    tc = new H({
        ident: `temp`,
        c: B.temp,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    nc = new H({
        ident: `wetbulbtemp`,
        filename: `wbt`,
        c: B.wetbulbtemp,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    rc = new H({
        ident: `solarpower`,
        c: B.solarpower,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    ic = new H({
        ident: `uvindex`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.uvindex,
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    ac = new H({
        ident: `dewpoint`,
        c: B.dewpoint,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    oc = new H({
        ident: `gust`,
        c: B.wind,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    sc = new H({
        ident: `gustAccu`,
        filename: `gust`,
        fileSuffix: `jpg`,
        renderer: `accumulations`,
        JPGtransparency: !0,
        c: B.wind,
        query: `acc=maxip`,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    cc = new H({
        ident: `turbulence`,
        fileSuffix: `png`,
        c: B.turbulence,
        PNGtransparency: !0,
        levels: [`850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    lc = new H({
        ident: `icing`,
        fileSuffix: `png`,
        c: B.icing,
        levels: [`950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`],
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    uc = new H({
        ident: `rh`,
        c: B.rh,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    dc = new H({
        ident: `pressure`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.pressure,
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    fc = new H({
        ident: `ccl`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.cclAltitude,
        renderParams: {
            interpolateNearestG: !0,
            shaderDefines: [`BICUBIC`, `CCL`, `PATT`, `PNG`]
        },
        transformG: e => Math.round(e * 4) / 4
    }),
    pc = new H({
        ident: `rain`,
        filename: `rainlogptype2`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.rain,
        renderParams: {
            shaderDefines: [`BICUBIC`, `RAIN`, `LOG`, `PATT`, `PATT2`, `PNG`],
            interpolateNearestG: !0
        },
        transformR: Rs,
        transformG: e => Math.round(e * 4) / 4,
        wTransformR: `rainLog`
    }),
    mc = new H({
        ident: `ptype`,
        filename: `rainlogptype`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.justGray,
        renderParams: {
            interpolateNearestG: !0,
            shaderDefines: [`PNG`, `LOG`]
        },
        transformR: Rs,
        transformG: Math.round,
        wTransformR: `rainLog`
    }),
    hc = new H({
        ident: `thunder`,
        filename: `lightdens`,
        c: B.lightDensity,
        transformR: Rs,
        wTransformR: `rainLog`,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        }
    }),
    gc = new H({
        ident: `clouds`,
        filename: `cloudsrain`,
        renderParams: {
            shaderDefines: [`BICUBIC`, `CLOUDS`, `PATT`]
        },
        c: B.clouds,
        cm: R.clouds,
        transformG: e => e < 10 ? e : (e - 10) * 10 + 10
    }),
    _c = new H({
        ident: `lclouds`,
        c: B.lclouds,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    vc = new H({
        ident: `mclouds`,
        c: B.mclouds,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    yc = new H({
        ident: `hclouds`,
        c: B.hclouds,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    bc = new H({
        ident: `cape`,
        c: B.cape,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    xc = new H({
        ident: `cbase`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        c: B.cbase,
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    Sc = new H({
        ident: `fog`,
        filename: `fogtype`,
        fileSuffix: `png`,
        c: B.fog,
        PNGtransparency: !0,
        renderParams: {
            shaderDefines: [`PNG`, `BICUBIC`]
        }
    }),
    Cc = new H({
        ident: `snowAccu`,
        filename: `snowaccumulationlog`,
        renderer: `accumulations`,
        fileSuffix: `jpg`,
        JPGtransparency: !0,
        c: B.snow,
        transformR: Rs,
        wTransformR: `rainLog`,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        }
    }),
    wc = new H({
        ident: `rainAccu`,
        filename: `rainaccumulationlog`,
        fileSuffix: `jpg`,
        JPGtransparency: !0,
        transformR: Rs,
        wTransformR: `rainLog`,
        renderer: `accumulations`,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        },
        c: B.rainAccu
    }),
    Tc = new H({
        ident: `waves`,
        c: B.waves,
        fileSuffix: `png`,
        renderParams: {
            shaderDefines: [`USE_BLUE_CHANNEL`, `BICUBIC`, `PNG`],
            sea: !0
        }
    }),
    Ec = new H({
        ident: `wwaves`,
        c: B.waves,
        fileSuffix: `png`,
        renderParams: {
            shaderDefines: [`USE_BLUE_CHANNEL`, `BICUBIC`, `PNG`],
            sea: !0
        }
    }),
    Dc = new H({
        ident: `wavePower`,
        filename: `waves_power`,
        fileSuffix: `png`,
        PNGtransparency: !0,
        renderParams: {
            sea: !0,
            shaderDefines: [`PNG`, `BICUBIC`]
        },
        c: B.wavePower
    }),
    Oc = new H({
        ident: `swell1`,
        c: B.waves,
        fileSuffix: `png`,
        renderParams: {
            sea: !0,
            shaderDefines: [`USE_BLUE_CHANNEL`, `BICUBIC`, `PNG`]
        }
    }),
    kc = new H({
        ident: `swell2`,
        c: B.waves,
        fileSuffix: `png`,
        renderParams: {
            sea: !0,
            shaderDefines: [`USE_BLUE_CHANNEL`, `BICUBIC`, `PNG`]
        }
    }),
    Ac = new H({
        ident: `swell3`,
        c: B.waves,
        fileSuffix: `png`,
        renderParams: {
            sea: !0,
            shaderDefines: [`USE_BLUE_CHANNEL`, `BICUBIC`, `PNG`]
        }
    }),
    jc = Oc,
    Mc = new H({
        ident: `currents`,
        filename: `seacurrents`,
        renderParams: {
            sea: !0,
            shaderDefines: [`VECTOR_SIZE`, `BICUBIC`]
        },
        c: B.currents
    }),
    Nc = new H({
        ident: `currentsTide`,
        filename: `seacurrents_tide`,
        renderParams: {
            sea: !0,
            shaderDefines: [`VECTOR_SIZE`, `BICUBIC`]
        },
        c: B.currents
    }),
    Pc = new H({
        ident: `sst`,
        renderer: `noUserControl`,
        renderParams: {
            sea: !0,
            shaderDefines: [`BICUBIC`]
        },
        levels: [`surface`],
        c: B.temp,
        JPGtransparency: !0
    }),
    Fc = new H({
        ident: `visibility`,
        c: B.visibility,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    Ic = new H({
        ident: `snowcover`,
        filename: `snowcoverlog`,
        transformR: Rs,
        wTransformR: `rainLog`,
        c: B.snow,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        }
    }),
    Lc = new H({
        ident: `cloudtop`,
        levels: [`surface`],
        fileSuffix: `jpg`,
        JPGtransparency: !0,
        c: B.levels,
        renderParams: {
            shaderDefines: [`BILINEAR_ALPHA`]
        }
    }),
    Rc = new H({
        ident: `deg0`,
        levels: [`surface`],
        c: B.deg0,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    zc = new H({
        ident: `cosc`,
        filename: `chem_cosc`,
        c: B.cosc,
        transformR: zs(1),
        wTransformR: 1,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        }
    }),
    Bc = new H({
        ident: `dustsm`,
        filename: `chem_dustsm`,
        c: B.dust,
        transformR: zs(.1),
        wTransformR: .1,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`]
        }
    }),
    Vc = new H({
        ident: `radar`,
        renderer: `radarPlus`,
        c: B.radar,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    Hc = new H({
        ident: `satellite`,
        renderer: `radarPlus`,
        c: B.satellite,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    Uc = new H({
        ident: `gtco3`,
        c: B.gtco3,
        renderParams: {
            shaderDefines: [`BICUBIC`]
        }
    }),
    Wc = new H({
        ident: `pm2p5`,
        c: B.pm2p5,
        transformR: zs(.001),
        wTransformR: .001,
        renderParams: {
            shaderDefines: [`LOG`, `BICUBIC`, `PNG`]
        }
    }),
    Gc = new H({
        ident: `aqi`,
        filename: `aqi_us`,
        c: B.aqi,
        renderParams: {
            shaderDefines: [`BICUBIC`, `PNG`]
        }
    }),
    Kc = {
        capAlerts: Bs,
        pressureIsolines: Vs,
        ghIsolines: Hs,
        tempIsolines: Us,
        deg0Isolines: Ws,
        windParticles: Gs,
        ecmwfWindParticles: Ks,
        ecmwfWindParticles150h: qs,
        ecmwfWindParticles500h: Js,
        ecmwfWindParticles600h: Ys,
        waveParticles: Xs,
        waveParticlesWaves: Zs,
        currentParticles: Qs,
        currentsTideParticles: $s,
        wind: ec,
        temp: tc,
        wetbulbtemp: nc,
        solarpower: rc,
        uvindex: ic,
        dewpoint: ac,
        gust: oc,
        gustAccu: sc,
        rh: uc,
        pressure: dc,
        ccl: fc,
        rain: pc,
        ptype: mc,
        thunder: hc,
        clouds: gc,
        lclouds: _c,
        mclouds: vc,
        hclouds: yc,
        cape: bc,
        cbase: xc,
        fog: Sc,
        snowAccu: Cc,
        rainAccu: wc,
        waves: Tc,
        wwaves: Ec,
        wavePower: Dc,
        swell1: Oc,
        swell2: kc,
        swell3: Ac,
        swell: jc,
        currents: Mc,
        currentsTide: Nc,
        sst: Pc,
        visibility: Fc,
        snowcover: Ic,
        cloudtop: Lc,
        deg0: Rc,
        cosc: zc,
        dustsm: Bc,
        radar: Vc,
        satellite: Hc,
        gtco3: Uc,
        pm2p5: Wc,
        no2: new H({
            ident: `no2`,
            c: B.no2,
            transformR: zs(.001),
            wTransformR: .001,
            renderParams: {
                shaderDefines: [`LOG`, `BICUBIC`, `PNG`]
            }
        }),
        aod550: new H({
            ident: `aod550`,
            c: B.aod550,
            transformR: zs(.001),
            wTransformR: .001,
            renderParams: {
                shaderDefines: [`LOG`, `BICUBIC`]
            }
        }),
        tcso2: new H({
            ident: `tcso2`,
            c: B.tcso2,
            transformR: zs(.001),
            wTransformR: .001,
            renderParams: {
                shaderDefines: [`LOG`, `BICUBIC`]
            }
        }),
        go3: new H({
            ident: `go3`,
            c: B.go3,
            transformR: zs(.001),
            wTransformR: .001,
            renderParams: {
                shaderDefines: [`LOG`, `BICUBIC`, `PNG`]
            }
        }),
        gh: new H({
            ident: `gh`,
            renderParams: {
                shaderDefines: [`BICUBIC`]
            }
        }),
        efiWind: new H({
            ident: `efiWind`,
            filename: `wsi`,
            renderer: `daySwitcher`,
            c: B.efiWind,
            renderParams: {
                shaderDefines: [`BICUBIC`]
            }
        }),
        efiTemp: new H({
            ident: `efiTemp`,
            filename: `ti`,
            renderer: `daySwitcher`,
            c: B.efiTemp,
            renderParams: {
                shaderDefines: [`BICUBIC`]
            }
        }),
        efiRain: new H({
            ident: `efiRain`,
            filename: `tpi`,
            renderer: `daySwitcher`,
            c: B.efiRain,
            renderParams: {
                shaderDefines: [`BICUBIC`]
            }
        }),
        moistureAnom40: new H({
            ident: `moistureAnom40`,
            filename: `awd_0_40`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.moistureAnom40,
            PNGtransparency: !0
        }),
        moistureAnom100: new H({
            ident: `moistureAnom100`,
            filename: `awd_0_100`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.moistureAnom100,
            PNGtransparency: !0
        }),
        drought40: new H({
            ident: `drought40`,
            filename: `awp_0_40`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.drought,
            PNGtransparency: !0
        }),
        drought100: new H({
            ident: `drought100`,
            filename: `awp_0_100`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.drought,
            PNGtransparency: !0
        }),
        soilMoisture40: new H({
            ident: `soilMoisture40`,
            filename: `awr_0_40`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.soilMoisture,
            PNGtransparency: !0
        }),
        soilMoisture100: new H({
            ident: `soilMoisture100`,
            filename: `awr_0_100`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.soilMoisture,
            PNGtransparency: !0
        }),
        fwi: new H({
            ident: `fwi`,
            filename: `fwi_genz`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.fwi,
            PNGtransparency: !0
        }),
        dfm10h: new H({
            ident: `dfm10h`,
            filename: `dfm10h`,
            renderer: `daySwitcher`,
            renderParams: {
                landOnly: !0,
                shaderDefines: [`PNG`, `BICUBIC`]
            },
            c: B.dfm10h,
            PNGtransparency: !0
        }),
        turbulence: cc,
        icing: lc,
        topoMap: new H({
            ident: `topoMap`,
            renderer: `topoMap`
        }),
        aqi: Gc,
        avalancheDanger: new H({
            ident: `avalancheDanger`,
            renderer: `avalancheDanger`
        })
    };

function qc(e, t, n) {
    let r = 0,
        i = e.length - 1;
    if (n) {
        if (t < e[r]) return r;
        if (t > e[i]) return i
    }
    for (; r <= i;) {
        let n = Math.floor((r + i) / 2),
            a = e[n],
            o = e[n + 1];
        if (a === t) return n;
        if (a < t && t < o) return t - a < o - t ? n : n + 1;
        a < t ? r = n + 1 : i = n - 1
    }
}
var Jc = b({
        Calendar: () => Yc
    }),
    Yc = class e {
        constructor({
            productIdent: t,
            minifest: n,
            freeProduct: r,
            minimumHours: i
        }) {
            var a;
            if (C(this, `premiumStartDay`, 6), C(this, `productIdent`, void 0), C(this, `calendarHours`, void 0), C(this, `midnight`, void 0), C(this, `start`, void 0), C(this, `premiumStart`, void 0), C(this, `premiumEnd`, void 0), C(this, `endOfCal`, void 0), C(this, `end`, void 0), C(this, `days`, void 0), C(this, `timestamps`, void 0), C(this, `paths`, void 0), C(this, `updateTs`, void 0), C(this, `refTimeTs`, void 0), !n || typeof n != `object` || !n.ref || !n.dst) throw Error(`Invalid minifest for ${this.productIdent}`);
            let o = n.dst[n.dst.length - 1][2];
            this.productIdent = t, this.midnight = e.getMidnight(), this.start = this.midnight.getTime(), this.refTimeTs = new Date(n.ref).getTime(), this.createTimestamps(o, n), this.calendarHours = Math.floor(Math.max((this.timestamps[this.timestamps.length - 1] - this.start) / T, i)), this.endOfCal = this.add(this.midnight, this.calendarHours).getTime(), this.end = Math.min(this.timestamps[this.timestamps.length - 1], this.endOfCal), this.createDays(r), this.premiumStart = !r && ((a = this.days[this.premiumStartDay]) == null ? void 0 : a.start) || null
        }
        boundTs(e) {
            return D(e, this.start, this.end)
        }
        ts2path(e) {
            let t = qc(this.timestamps, e, !0);
            return this.paths[t]
        }
        createDays(t) {
            let n = this.add(this.midnight, 12);
            this.days = [];
            for (let r = 0; r < this.calendarHours / 24; r++) {
                let i = this.add(n, r, `days`),
                    a = this.add(this.midnight, r, `days`).getTime(),
                    o = this.add(this.midnight, 24),
                    s = this.add(o, r, `days`).getTime(),
                    c = e.weekdays[i.getDay()];
                this.days[r] = {
                    displayShort: `${c}3`,
                    display: `${c}2`,
                    displayLong: c,
                    day: i.getDate(),
                    middayTs: i.getTime(),
                    start: a,
                    end: s,
                    premium: !t && r >= this.premiumStartDay,
                    hasForecast: a <= this.end
                }
            }
        }
        createTimestamps(e, {
            dst: t,
            ref: n
        }) {
            let r = this.add(new Date(n), e, `hours`).getTime();
            this.timestamps = [], this.paths = [], t.forEach(e => {
                for (let t = e[1]; t <= e[2]; t += e[0]) {
                    let e = this.refTimeTs + t * T;
                    if (e <= r) {
                        this.timestamps.push(e);
                        let t = hn(e);
                        this.paths.push(t)
                    }
                }
            })
        }
        add(e, t, n) {
            let r = new Date(e.getTime());
            return r.setTime(e.getTime() + (n === `days` ? 24 : 1) * t * T), r
        }
        static getMidnight(e) {
            let t = e ? new Date(e) : new Date;
            return t.setHours(0), t.setMinutes(0), t.setSeconds(0), t.setMilliseconds(0), t
        }
    };
C(Yc, `weekdays`, [`SUN`, `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`]);
var Xc = b({
    clear: () => $c,
    insert: () => Qc
});
const Zc = () => Kt(`[data-ref="bottomMessages"]`),
    Qc = (e, t) => {
        let n = Zc();
        n && (n.innerHTML = e, n.onclick = t || ut)
    },
    $c = () => {
        let e = Zc();
        e && (e.innerHTML = ``, e.onclick = ut)
    };
var el = b({
    getSedlinaRequestParams: () => ul,
    pageview: () => dl
});
const tl = e => {
        let t = /utm_(source|medium|term|campaign|content)=([^&]+)/g,
            n = {
                source: `cs`,
                medium: `cm`,
                term: `ck`,
                campaign: `cn`,
                content: `cc`
            },
            r = [],
            i;
        for (; i = t.exec(e);) i[1] && i[1] in n && r.push(`${n[i[1]]}=${i[2]}`);
        return r.join(`&`)
    },
    nl = window.screen;
let rl = Vt({
    ul: br,
    sr: `${nl.width}x${nl.height}`,
    cid: ur(),
    an: `Windy`,
    dd: ve,
    uh: String(Date.now().toString(32) + Math.random().toString(16)).replace(/\./g, ``)
});
/utm_/.test(window.location.search) && (rl += `&${tl(window.location.search)}`);
let il = !0,
    al, ol = null;
const sl = () => {
        ol = Date.now()
    },
    cl = () => {
        if (ol && al) {
            let e = ol - Date.now();
            ol = null, al = Math.max(0, al - e)
        }
    };
window.addEventListener(`focus`, cl, !1), window.addEventListener(`blur`, sl, !1), window.addEventListener(`pageshow`, cl, !1), window.addEventListener(`pagehide`, sl, !1), document.addEventListener(`visibilitychange`, () => {
    `hidden` in document && document.hidden ? sl() : cl()
});
const ll = Date.now(),
    ul = e => {
        let t = `dp=${e}&dl=${encodeURIComponent(document.location.href)}&${rl}`;
        if (t += `&fv=${il}&ss=${il}`, t += `&dt=${ll}`, il) {
            let e = document.referrer;
            /www.windy.com/.test(e) || (t += `&dr=${encodeURIComponent(e)}`), il = !1, al = Date.now()
        }
        let n = Date.now(),
            r = n - al;
        return al = n, t += `&et=${r}`, {
            code: 1,
            reqQs: t
        }
    },
    dl = e => {
        let {
            code: t,
            reqQs: n
        } = ul(e);
        ni(`/sedlina/ga/${t}?${n}`, {
            cache: !1
        })
    };
var fl = b({
    logEvent: () => bl,
    logPage: () => yl
});
const pl = new Set([`path`, `isolinesType`, `overlay`, `product`, `level`]),
    ml = {},
    hl = new Set([`plugin/consent`]),
    gl = M.get(`consent`);
let _l = gl ? gl.analytics ? `analytics` : `rejected` : `pending`;
const vl = async e => {
    if (await fn(100), dl(e), ml[e] !== 1 && !e.startsWith(`storyEvent`) && !e.startsWith(`event`)) {
        let t = await Ja.get(e) || 0;
        t++, Ja.put(e, t)
    }
    ml[e] = 1
}, yl = (e, t) => {
    let n = `${e}/${t || ``}`;
    _l === `analytics` || _l === `pending` && hl.has(n) ? vl(n) : _l === `pending` && (ml[n] = 0)
}, bl = (e, t) => yl(`events`, t ? `${e}/${t}` : e);
M.on(`consent`, e => {
    e != null && e.analytics ? (_l = `analytics`, Object.keys(ml).forEach(vl)) : _l = `rejected`
}), N.on(`paramsChanged`, (e, t) => {
    if (!t || !pl.has(t)) return;
    let n;
    n = t === `path` ? `${Math.round((M.get(`timestamp`) - Date.now()) / 864e5)}d` : t === `acRange` ? `${Math.round(M.get(`acRange`) / 24)}d` : e[t], n && yl(t, n)
}), yl(`version`, he);
var xl = b({
    checkAndRenderSubsIssue: () => Al,
    checkPendingSubscription: () => Ol,
    clearPendingSubscription: () => Sl,
    getBaitTitle: () => kl,
    getIssue: () => Dl,
    hasAny: () => U,
    setPendingSubscription: () => Cl,
    setSubsBodyClass: () => Tl,
    setTier: () => El
});
const Sl = () => {
        M.remove(`pendingSubscription`), N.emit(`rqstClose`, `pending-subscription`)
    },
    Cl = e => {
        M.set(`pendingSubscription`, e)
    },
    wl = () => {
        let e = M.get(`subscription`);
        M.set(`detail1h`, !1), M.set(`startUpLastStep`, null), M.set(`subscription`, null), M.set(`subscriptionInfo`, null), e && document.body.classList.remove(`subs-${e}`), yl(`subscription`, `tier/none`)
    },
    Tl = e => document.body.classList.add(`subs-${e}`),
    El = e => {
        if (!e) wl();
        else {
            let {
                state: t,
                platform: n,
                status: r,
                tier: i
            } = e;
            r === `active` ? (M.set(`subscription`, i), M.set(`subscriptionInfo`, e), Tl(i), M.remove(`failedSubscriptionPayment`)) : wl(), yl(`subscription`, `tier/${i}`), yl(`subscription`, `state/${t}`), yl(`subscription`, `platform/${n}`), yl(`subscription`, `status/${r}`)
        }
    },
    U = () => M.get(`subscription`) !== null,
    Dl = () => {
        let e = M.get(`subscriptionInfo`);
        if (!e || !e.isSubscription || e.isTrial) return null;
        if ([`graced`, `onhold`, `paused`].includes(e.state)) return {
            type: e.state
        };
        if (e.state === `canceled`) {
            let t = Math.abs(Math.round((e.expiresAt - Date.now()) / T));
            if (t <= 336) return {
                type: `expiring`,
                expiresInHours: t
            }
        }
        return null
    },
    Ol = () => {
        M.get(`pendingSubscription`) && N.emit(`rqstOpen`, `pending-subscription`)
    },
    kl = e => {
        if (!e) return ``;
        if (e.type === `graced`) return P.SUB_CUFFS_GRACED;
        if (e.type === `onhold`) return P.SUB_RENEW;
        if (e.type === `paused`) return P.SUB_CUFFS_PAUSED;
        if (e.type === `expiring`) {
            if (e.expiresInHours < 2) return P.SUB_CUFFS_CANCELED_4;
            if (e.expiresInHours <= 48) return P.SUB_CUFFS_CANCELED_3.replace(`{{count}}`, String(e.expiresInHours));
            if (e.expiresInHours <= 168) return P.SUB_CUFFS_CANCELED_2.replace(`{{count}}`, String(Math.round(e.expiresInHours / 24)));
            if (e.expiresInHours <= 336) return P.SUB_CUFFS_CANCELED_1
        }
        return ``
    },
    Al = () => {
        let e = Dl(),
            t = e ? kl(e) : null;
        t && Nr({
            type: `warning`,
            html: `<span data-icon="">${t}</span>`,
            timeout: et * 2,
            onclick: () => {
                N.emit(`rqstOpen`, `subscription`)
            }
        })
    };
N.once(`dependenciesResolved`, Ol), N.on(`checkPendingSubscriptions`, Ol);
var jl = b({
        Product: () => G
    }),
    G = class {
        constructor(e) {
            var t, n, r, i, a, o, s, c, l, u, d, f, p, m, h, g, _, v, ee, te, y, ne;
            C(this, `bounds`, void 0), C(this, `minifestExpirationTime`, et * 10), C(this, `loadingPromise`, void 0), C(this, `ident`, void 0), C(this, `maxTileZoom`, void 0), C(this, `animationSpeed`, void 0), C(this, `animationSpeed1h`, void 0), C(this, `fileSuffix`, void 0), C(this, `fileSuffixFallback`, void 0), C(this, `JPGtransparency`, void 0), C(this, `PNGtransparency`, void 0), C(this, `dataQuality`, void 0), C(this, `betterDataQuality`, void 0), C(this, `animation`, void 0), C(this, `calendar`, void 0), C(this, `modelName`, void 0), C(this, `modelResolution`, void 0), C(this, `provider`, void 0), C(this, `modelDescription`, void 0), C(this, `interval`, void 0), C(this, `intervalPremium`, void 0), C(this, `forecastSize`, void 0), C(this, `directory`, void 0), C(this, `category`, void 0), C(this, `modelIdent`, void 0), C(this, `labelsTemp`, void 0), C(this, `logo`, void 0), C(this, `overlays`, void 0), C(this, `levels`, void 0), C(this, `levelsOverride`, void 0), C(this, `isolines`, void 0), C(this, `preferredProduct`, void 0), C(this, `preferredWaveProduct`, void 0), C(this, `preferredAirProduct`, void 0), C(this, `minifest`, void 0), C(this, `server`, void 0), C(this, `hasMinifest`, void 0), C(this, `hasAccumulations`, void 0), C(this, `freeProduct`, void 0), C(this, `hideProductSwitch`, void 0), C(this, `minifestLastUpdate`, void 0), C(this, `supportsMeteogram`, void 0), this.modelName = e.modelName, this.ident = (t = e.ident) == null ? `ecmwf` : t, this.maxTileZoom = (n = e.maxTileZoom) == null ? {
                free: 10,
                premium: 10
            } : n, this.animationSpeed = (r = e.animationSpeed) == null ? 3e3 : r, this.animationSpeed1h = (i = e.animationSpeed1h) == null ? 1e3 : i, this.fileSuffix = (a = e.fileSuffix) == null ? `jpg` : a, this.fileSuffixFallback = (o = e.fileSuffixFallback) == null ? `jpg` : o, this.JPGtransparency = (s = e.JPGtransparency) == null ? !1 : s, this.PNGtransparency = (c = e.PNGtransparency) == null ? !1 : c, this.dataQuality = (l = e.dataQuality) == null ? `normal` : l, this.betterDataQuality = (u = e.betterDataQuality) == null ? [] : u, this.animation = (d = e.animation) == null ? !0 : d, this.forecastSize = (f = e.forecastSize) == null ? 240 : f, this.labelsTemp = (p = e.labelsTemp) == null ? !0 : p, this.overlays = (m = e.overlays) == null ? [] : m, this.hideProductSwitch = (h = e.hideProductSwitch) == null ? !1 : h, this.preferredProduct = (g = e.preferredProduct) == null ? `ecmwf` : g, this.isolines = (_ = e.isolines) == null ? [] : _, this.directory = (v = e.directory) == null ? e.modelIdent && e.category && `${e.category}/${e.modelIdent}` || `` : v, this.modelIdent = e.modelIdent, this.category = e.category, this.provider = e.provider, this.interval = e.interval, this.intervalPremium = e.intervalPremium, this.server = e.server, this.modelResolution = e.modelResolution, this.levels = e.levels, this.levelsOverride = e.levelsOverride, this.bounds = e.bounds, this.logo = e.logo, this.hasAccumulations = e.hasAccumulations, this.modelDescription = e.modelDescription, this.minifest = null, this.loadingPromise = null, this.hasMinifest = (ee = e.hasMinifest) == null ? !0 : ee, this.freeProduct = e.freeProduct, this.preferredAirProduct = (te = e.preferredAirProduct) == null ? `ecmwf` : te, this.preferredWaveProduct = (y = e.preferredWaveProduct) == null ? `ecmwfWaves` : y, this.supportsMeteogram = (ne = e.supportsMeteogram) == null ? !0 : ne
        }
        async getRefTimeISOFormat() {
            var e = this;
            if (e.hasMinifest) {
                if (e.minifest && Date.now() < e.minifestExpirationTime) return e.minifest.ref;
                {
                    let {
                        ref: t
                    } = await e.loadMinifest();
                    return t
                }
            }
        }
        async getRefTime() {
            let e = await this.getRefTimeISOFormat();
            if (e) return e.replace(/(\d+)-(\d+)-(\d+)T(\d+):.*/, `$1$2$3$4`)
        }
        async loadMinifest() {
            var e = this;
            let t = U() ? `?premium=true` : ``,
                {
                    data: n
                } = await F(`/metadata/v1.0/${e.directory}/minifest.json${t}`);
            return e.minifest = n, e.minifestExpirationTime = Date.now() + e.minifestExpirationTime, n
        }
        pointIsInBounds(e) {
            if (!this.bounds) return !0;
            let t = [+e.lat, +e.lon];
            for (let e of this.bounds)
                if (this.isPointInsidePolygon(t, e)) return !0;
            return !1
        }
        boundsAreInViewport(e) {
            if (!this.bounds) return !0;
            let t = x ? .1 : Fe ? .15 : .25,
                n = window.innerWidth * t,
                r = window.innerHeight * t,
                i = e.getBounds(),
                a = e.latLngToContainerPoint(i.getNorthWest()),
                o = e.latLngToContainerPoint(i.getSouthEast()),
                c = new s(e.containerPointToLatLng(new h(a.x + n, a.y + r)), e.containerPointToLatLng(new h(o.x - n, o.y - r)));
            for (let e of this.bounds)
                if (c.intersects(e)) return !0;
            return !1
        }
        close() {
            !S && this.logo && $c()
        }
        open() {
            [`radar`, `satellite`].includes(this.ident) || $c(), this.logo && !S && Qc(this.logo)
        }
        async getCalendar() {
            var e = this;
            if (e.hasMinifest) {
                if (e.calendar && Date.now() < e.minifestExpirationTime) return e.calendar;
                {
                    let t = await e.loadMinifest();
                    return e.calendar = new Yc({
                        productIdent: e.ident,
                        minifest: t,
                        freeProduct: e.freeProduct,
                        minimumHours: e.forecastSize
                    }), e.calendar
                }
            }
        }
        isPointInsidePolygon(e, t) {
            let n = !1;
            for (let r = 0, i = t.length - 1; r < t.length; i = r++) {
                let a = t[r][0],
                    o = t[r][1],
                    s = t[i][0],
                    c = t[i][1];
                o > e[1] != c > e[1] && e[0] < (s - a) * (e[1] - o) / (c - o) + a && (n = !n)
            }
            return !!n
        }
    },
    Ml = class extends G {
        constructor(e) {
            super(w(w({}, e), {}, {
                modelName: `ECMWF`,
                modelResolution: 9,
                provider: `ECMWF`,
                interval: 720,
                intervalPremium: 360,
                maxTileZoom: {
                    free: 3,
                    premium: 4
                },
                dataQuality: `normal`
            }))
        }
    },
    Nl = class extends Ml {
        async loadMinifest() {
            let e = `/metadata/v1.0/forecast/ecmwf-hres/minifest.json${U() ? `?premium=true` : ``}`,
                {
                    preparedFetchRequests: t
                } = W,
                n = U() ? t.minifestPremium : t.minifest;
            n && (W.preparedFetchRequests.minifest = void 0, W.preparedFetchRequests.minifestPremium = void 0);
            let {
                data: r
            } = await F(e, n ? {
                ongoingFetchRequest: n
            } : void 0);
            return r
        }
    },
    Pl = class extends G {
        constructor(e) {
            super(w({
                provider: `NCEP`,
                modelName: `HRRR`,
                dataQuality: `extreme`,
                category: `forecast`,
                maxTileZoom: {
                    free: 4,
                    premium: 6
                },
                betterDataQuality: [`rain`, `clouds`, `lclouds`, `hclouds`, `mclouds`],
                interval: 720,
                JPGtransparency: !0,
                forecastSize: 72,
                levels: [`surface`, `975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
                overlays: [`wind`, `temp`, `wetbulbtemp`, `clouds`, `rh`, `cape`, `gust`, `pressure`, `dewpoint`, `rain`, `lclouds`, `hclouds`, `mclouds`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`, `ccl`, `turbulence`, `icing`],
                hasAccumulations: !0,
                isolines: [`pressure`, `temp`, `gh`]
            }, e))
        }
    };
const Fl = [`snowcover`, `wind`, `temp`, `wetbulbtemp`, `solarpower`, `pressure`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `rh`, `gust`, `cape`, `dewpoint`, `rain`, `deg0`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`, `fog`, `ccl`, `turbulence`];
var Il = class extends G {
        constructor(e) {
            super(w({
                provider: `DWD`,
                interval: 720,
                intervalPremium: 360,
                category: `forecast`,
                preferredProduct: `icon`,
                preferredWaveProduct: `ecmwfWaves`,
                animation: !0,
                betterDataQuality: [`rain`, `clouds`, `lclouds`, `mclouds`, `hclouds`],
                labelsTemp: !0,
                levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
                hasAccumulations: !0,
                isolines: [`pressure`, `gh`, `temp`, `deg0`]
            }, e))
        }
    },
    Ll = class extends G {
        constructor(e) {
            super(e), C(this, `urlSuff`, void 0), C(this, `urlSuffFlow`, void 0), this.hasMinifest = !1, this.urlSuff = e.urlSuff, this.urlSuffFlow = e.urlSuffFlow
        }
    },
    Rl = class extends G {
        constructor(e) {
            super(e), this.levels = [`surface`], this.labelsTemp = !1
        }
        async loadMinifest() {
            var e = this;
            let t = new Date().toISOString();
            return e.minifest = {
                dst: [
                    [1, 0, 1]
                ],
                v: `1.0`,
                info: `fakeMinifest`,
                ref: t,
                update: t
            }, e.minifestExpirationTime = Date.now() + e.minifestExpirationTime, e.minifest
        }
    },
    zl = class extends G {
        constructor(e) {
            super(w({
                provider: `NOAA`,
                interval: 720,
                intervalPremium: 360,
                modelName: `NAM`,
                dataQuality: `ultra`,
                category: `forecast`,
                maxTileZoom: {
                    free: 4,
                    premium: 5
                },
                betterDataQuality: [`rain`, `clouds`, `lclouds`, `hclouds`, `mclouds`],
                JPGtransparency: !0,
                forecastSize: 72,
                levels: [`surface`, `975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
                overlays: [`wind`, `temp`, `wetbulbtemp`, `clouds`, `cape`, `rh`, `gust`, `pressure`, `dewpoint`, `rain`, `lclouds`, `hclouds`, `mclouds`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`, `ccl`, `turbulence`, `icing`],
                hasAccumulations: !0,
                isolines: [`pressure`, `temp`, `gh`]
            }, e))
        }
    },
    Bl = class extends G {
        constructor(e) {
            super(w({
                provider: `BOM`,
                interval: 720,
                intervalPremium: 360,
                modelName: `ACCESS`,
                JPGtransparency: !0,
                category: `forecast`,
                levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
                overlays: [`wind`, `temp`, `wetbulbtemp`, `pressure`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `rh`, `gust`, `dewpoint`, `rain`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`, `ccl`, `turbulence`, `icing`, `visibility`],
                hasAccumulations: !0,
                isolines: [`pressure`, `gh`, `temp`]
            }, e))
        }
    },
    Vl = class extends Bl {
        constructor(e) {
            super(w({
                modelName: ``,
                modelResolution: 1.5,
                dataQuality: `extreme`,
                maxTileZoom: {
                    free: 4,
                    premium: 6
                },
                forecastSize: 36
            }, e))
        }
    },
    Hl = class extends G {
        constructor(e) {
            super(w({
                provider: `MF`,
                interval: 720,
                intervalPremium: 360,
                modelName: `AROME`,
                modelResolution: 2.5,
                JPGtransparency: !0,
                animation: !0,
                dataQuality: `extreme`,
                maxTileZoom: {
                    free: 4,
                    premium: 6
                },
                category: `forecast`,
                forecastSize: 42,
                levels: [`surface`, `100m`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
                overlays: [`wind`, `temp`, `wetbulbtemp`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `rh`, `gust`, `cape`, `dewpoint`, `rain`, `snowAccu`, `rainAccu`, `ptype`, `pressure`, `gustAccu`, `turbulence`, `icing`],
                hasAccumulations: !0,
                isolines: [`pressure`, `gh`, `temp`],
                supportsMeteogram: !1
            }, e))
        }
    };
const Ul = `https://www.windy.com/img/providers`,
    Wl = `<a href="https://www.metoffice.gov.uk/" target="_blank"><img src="${Ul}/metoffice-white-horizontal.svg" /></a>`,
    Gl = `<a href="https://atmosphere.copernicus.eu/" target="_blank"><img src="${Ul}/copernicus-white.svg" /></a>`,
    Kl = `<a href="https://www.droughtimpacts.eu/" target="_blank" class="uiyellow clickable-size flex-container mb-15 rhmessage-with-text">
        <img style="filter:drop-shadow(0 0 3px rgba(0, 0, 0, 0.8));" src="${Ul}/czechglobe.svg" />
        <p style="white-space: break-spaces;">Help us to monitor fire and drought impacts in your region for a safer World - go to www.droughtImpacts.eu</p>
    </a>`,
    ql = `<a href="https://www.jma.go.jp/jma/indexe.html" target="_blank"><img src="${Ul}/jma-white-horizontal.svg" /></a>`,
    Jl = new Nl({
        ident: `ecmwf`,
        category: `forecast`,
        modelIdent: `ecmwf-hres`,
        preferredWaveProduct: `ecmwfWaves`,
        betterDataQuality: [`rain`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `cbase`, `snowAccu`, `rainAccu`, `snowcover`, `ptype`],
        levels: [`surface`, `100m`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`, `10h`],
        overlays: `snowcover.wind.temp.wetbulbtemp.solarpower.pressure.clouds.lclouds.mclouds.hclouds.rh.gust.cbase.cape.dewpoint.rain.visibility.deg0.cloudtop.thunder.snowAccu.rainAccu.ptype.gustAccu.ccl.turbulence.icing`.split(`.`),
        hasAccumulations: !0,
        isolines: [`pressure`, `gh`, `temp`, `deg0`]
    }),
    Yl = new Ml({
        ident: `ecmwfAnalysis`,
        category: `analysis`,
        modelIdent: `ecmwf-hres`,
        betterDataQuality: [`sst`],
        overlays: [`sst`],
        isolines: [],
        labelsTemp: !1,
        animation: !1,
        forecastSize: 0
    }),
    Xl = new G({
        ident: `cams`,
        provider: `Copernicus`,
        interval: 720,
        PNGtransparency: !0,
        modelName: `CAMS`,
        modelResolution: 40,
        fileSuffix: `png`,
        category: `forecast`,
        modelIdent: `cams-global`,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        dataQuality: `low`,
        levels: [`surface`],
        overlays: [`aqi`, `gtco3`, `aod550`, `pm2p5`, `no2`, `tcso2`, `go3`, `uvindex`, `cosc`, `dustsm`],
        labelsTemp: !1,
        supportsMeteogram: !1,
        logo: Gl
    }),
    Zl = new G({
        ident: `camsEu`,
        provider: `Copernicus`,
        interval: 1440,
        PNGtransparency: !0,
        modelName: `CAMS EU`,
        modelResolution: 10,
        fileSuffix: `png`,
        category: `forecast`,
        modelIdent: `cams-eu`,
        bounds: [
            [
                [72, -25],
                [72, 45],
                [30, 45],
                [30, -25]
            ]
        ],
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        dataQuality: `high`,
        levels: [`surface`],
        overlays: [`aqi`, `pm2p5`, `no2`, `go3`],
        labelsTemp: !1,
        supportsMeteogram: !1,
        logo: Gl
    }),
    Ql = new G({
        ident: `cmems`,
        JPGtransparency: !0,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        modelName: `CMEMS`,
        modelResolution: 9,
        provider: `Copernicus`,
        category: `forecast`,
        modelIdent: `cmems`,
        labelsTemp: !1,
        interval: 1440,
        dataQuality: `normal`,
        overlays: [`currents`, `currentsTide`],
        levels: [`surface`],
        logo: Gl,
        hideProductSwitch: !0
    }),
    $l = new G({
        ident: `gfs`,
        preferredProduct: `gfs`,
        provider: `NOAA`,
        interval: 720,
        intervalPremium: 360,
        preferredWaveProduct: `gfsWaves`,
        modelName: `GFS`,
        modelResolution: 22,
        category: `forecast`,
        modelIdent: `gfs`,
        forecastSize: 360,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        dataQuality: `low`,
        betterDataQuality: [`rain`, `clouds`, `lclouds`, `mclouds`, `hclouds`],
        levels: [`surface`, `100m`, `975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`, `10h`],
        overlays: [`wind`, `temp`, `wetbulbtemp`, `pressure`, `clouds`, `rh`, `gust`, `dewpoint`, `rain`, `lclouds`, `mclouds`, `hclouds`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`, `cape`, `ccl`, `turbulence`, `icing`],
        hasAccumulations: !0,
        isolines: [`pressure`, `gh`, `temp`]
    }),
    eu = new Il({
        ident: `icon`,
        modelName: `ICON`,
        modelResolution: 13,
        dataQuality: `normal`,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        modelIdent: `icon-global`,
        forecastSize: 168,
        overlays: [...Fl, `cloudtop`]
    }),
    tu = new Il({
        ident: `iconEu`,
        modelName: `ICON-EU`,
        modelResolution: 7,
        preferredWaveProduct: `iconEuWaves`,
        intervalPremium: 180,
        JPGtransparency: !0,
        dataQuality: `high`,
        maxTileZoom: {
            free: 3,
            premium: 4
        },
        modelIdent: `icon-eu`,
        forecastSize: 120,
        overlays: [...Fl, `cbase`, `cloudtop`, `visibility`],
        bounds: [
            [
                [70.5, -23.5],
                [70.5, 62.5],
                [29.5, 62.5],
                [29.5, -23.5]
            ]
        ]
    }),
    nu = new Il({
        ident: `iconD2`,
        modelName: `ICON-D2`,
        modelResolution: 2.2,
        intervalPremium: 180,
        JPGtransparency: !0,
        dataQuality: `extreme`,
        modelIdent: `icon-d2`,
        preferredProduct: `iconEu`,
        preferredWaveProduct: `iconEuWaves`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        forecastSize: 48,
        overlays: [...Fl, `cbase`, `visibility`],
        bounds: [
            [
                [57.32, -3.88],
                [57.83, 2.23],
                [58.03, 8.64],
                [57.93, 15.41],
                [57.66, 20.27],
                [54.3, 19.48],
                [51.13, 18.84],
                [47.6, 18.24],
                [43.38, 17.56],
                [43.6, 14.16],
                [43.68, 9.15],
                [43.5, 3.7],
                [43.2, -.3],
                [47.6, -1.2],
                [51.13, -2.05],
                [54.3, -2.9]
            ]
        ],
        hasAccumulations: !0
    }),
    ru = new G({
        ident: `iconEuWaves`,
        modelName: `ICON-EU EWAM`,
        modelResolution: 7,
        preferredProduct: `iconEu`,
        preferredAirProduct: `iconEu`,
        bounds: [
            [
                [66, -10.525],
                [66, 42.025],
                [29.95, 42.025],
                [29.95, -10.525]
            ]
        ],
        provider: `DWD`,
        interval: 720,
        labelsTemp: !1,
        category: `forecast`,
        modelIdent: `icon-ewam`,
        fileSuffix: `png`,
        dataQuality: `normal`,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        overlays: [`waves`, `wavePower`, `swell1`, `wwaves`],
        levels: [`surface`]
    }),
    iu = new Bl({
        ident: `bomAccess`,
        modelResolution: 12,
        dataQuality: `normal`,
        modelIdent: `bom-access`,
        maxTileZoom: {
            free: 3,
            premium: 4
        },
        forecastSize: 240,
        bounds: [
            [
                [-65, 65],
                [-65, 180],
                [17, 180],
                [17, 65]
            ],
            [
                [-65, -180],
                [-65, -175],
                [17, -175],
                [17, -180]
            ]
        ]
    }),
    au = new Vl({
        ident: `bomAccessAd`,
        modelIdent: `bom-access-c-ad`,
        modelName: `ACCESS-C AD`,
        bounds: [
            [
                [-29.47, 130],
                [-29.47, 142],
                [-39.5, 142],
                [-39.5, 130]
            ]
        ]
    }),
    ou = new Vl({
        ident: `bomAccessBn`,
        modelIdent: `bom-access-c-bn`,
        modelName: `ACCESS-C BN`,
        bounds: [
            [
                [-21.47, 145],
                [-21.47, 157],
                [-31.5, 157],
                [-31.5, 145]
            ]
        ]
    }),
    su = new Vl({
        ident: `bomAccessDn`,
        modelIdent: `bom-access-c-dn`,
        modelName: `ACCESS-C DN`,
        bounds: [
            [
                [-7.97, 127],
                [-7.97, 139],
                [-18, 139],
                [-18, 127]
            ]
        ]
    }),
    cu = new Vl({
        ident: `bomAccessNq`,
        modelIdent: `bom-access-c-nq`,
        modelName: `ACCESS-C NQ`,
        bounds: [
            [
                [-12.47, 139],
                [-12.47, 151],
                [-22.5, 151],
                [-22.5, 139]
            ]
        ]
    }),
    lu = new Vl({
        ident: `bomAccessPh`,
        modelIdent: `bom-access-c-ph`,
        modelName: `ACCESS-C PH`,
        bounds: [
            [
                [-26.97, 112],
                [-26.97, 124],
                [-37, 124],
                [-37, 112]
            ]
        ]
    }),
    uu = new Vl({
        ident: `bomAccessSy`,
        modelIdent: `bom-access-c-sy`,
        modelName: `ACCESS-C SY`,
        bounds: [
            [
                [-27.97, 144],
                [-27.97, 156],
                [-38, 156],
                [-38, 144]
            ]
        ]
    }),
    du = new Vl({
        ident: `bomAccessVt`,
        modelIdent: `bom-access-c-vt`,
        modelName: `ACCESS-C VT`,
        bounds: [
            [
                [-33, 139],
                [-33, 151],
                [-46, 151],
                [-46, 139]
            ]
        ]
    }),
    fu = [
        [
            [54.676, -11.999],
            [55.248, -4.269],
            [55.389, 2.579],
            [55.209, 9.148],
            [54.679, 15.998],
            [46.483, 13.903],
            [37.5, 12.197],
            [37.85, 7.621],
            [38, 2.208],
            [37.879, -3.009],
            [37.497, -8.173],
            [46.095, -9.792]
        ]
    ],
    pu = new Hl({
        ident: `aromeAntilles`,
        modelIdent: `arome-antilles`,
        modelName: `AROME ANT`,
        bounds: [
            [
                [22.9, -75.3],
                [22.9, -51.7],
                [9.7, -51.7],
                [9.7, -75.3]
            ]
        ]
    }),
    mu = new Hl({
        ident: `aromeFrance`,
        modelIdent: `arome-france`,
        bounds: fu,
        intervalPremium: 180
    }),
    hu = new Hl({
        ident: `aromeReunion`,
        modelIdent: `arome-reunion`,
        modelName: `AROME REU`,
        bounds: [
            [
                [-3.45, 32.73],
                [-3.45, 67.61],
                [-25.9, 67.61],
                [-25.9, 32.73]
            ]
        ]
    }),
    gu = new G({
        ident: `arome`,
        provider: `MF`,
        interval: 720,
        intervalPremium: 180,
        modelName: `AROME-HD`,
        modelResolution: 1.3,
        JPGtransparency: !0,
        animation: !0,
        dataQuality: `extreme`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        category: `forecast`,
        modelIdent: `arome`,
        forecastSize: 42,
        bounds: fu,
        levels: [`surface`],
        overlays: [`wind`, `temp`, `wetbulbtemp`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `rh`, `gust`, `cape`, `dewpoint`, `rain`, `snowAccu`, `rainAccu`, `ptype`, `gustAccu`],
        hasAccumulations: !0,
        isolines: [`temp`],
        supportsMeteogram: !1
    }),
    _u = new G({
        ident: `nems`,
        modelName: `NEMS`,
        modelResolution: 4,
        provider: `Meteoblue.com`,
        interval: 720,
        JPGtransparency: !0,
        animation: !0,
        dataQuality: `ultra`,
        betterDataQuality: [`rain`, `clouds`],
        maxTileZoom: {
            free: 4,
            premium: 5
        },
        category: `forecast`,
        modelIdent: `mbeurope`,
        labelsTemp: !1,
        forecastSize: 72,
        bounds: [
            [
                [58.08, -19.79],
                [58.08, 33.76],
                [32.01, 33.76],
                [32.01, -19.79]
            ]
        ],
        levels: [`surface`, `975h`, `950h`, `925h`, `900h`, `850h`],
        overlays: [`wind`, `temp`, `wetbulbtemp`, `clouds`, `rh`, `gust`, `dewpoint`, `rain`, `rainAccu`, `gustAccu`],
        hasAccumulations: !0,
        logo: `<a href="https://www.meteoblue.com/?utm_source=windy.com&utm_medium=referral&utm_campaign=forecast-model-NEMS-layer" target="_blank" style="white-space: nowrap;">NEMS4 model by <img style="padding-left: 5%;padding-bottom: 2px; max-width:90px;height:auto;" src="https://www.windy.com/img/logo-mb.svg" /></a>`
    }),
    vu = new G({
        ident: `mblue`,
        modelName: x ? `MBLUE` : `METEOBLUE`,
        modelDescription: `AI generated forecast based on all available data for given location. For places with high density of weather stations (where AI model can be trained), surpasses all other models.`,
        interval: 720,
        hideProductSwitch: !0,
        hasMinifest: !1,
        supportsMeteogram: !0
    }),
    yu = [
        [
            [47.78, -134],
            [49.9, -125.15],
            [51.27, -116.89],
            [52.19, -107.7],
            [52.57, -98.94],
            [52.29, -88.68],
            [51.43, -79.14],
            [49.95, -69.97],
            [47.78, -61.1],
            [41.6, -64.6],
            [32, -68.75],
            [21.4, -72.4],
            [23.7, -84.83],
            [24.6, -97.7],
            [23.74, -110],
            [21.4, -122.7],
            [32, -126.2],
            [41.6, -130.5]
        ]
    ],
    bu = new zl({
        ident: `namConus`,
        modelResolution: 5,
        modelIdent: `nam-conus`,
        bounds: yu
    }),
    xu = new zl({
        ident: `namHawaii`,
        modelResolution: 3,
        modelIdent: `nam-hawaii`,
        modelName: `NAM-HI`,
        bounds: [
            [
                [23.09, -161.56],
                [23.09, -153.88],
                [18.08, -153.88],
                [18.08, -161.56]
            ]
        ]
    }),
    Su = new zl({
        ident: `namAlaska`,
        modelResolution: 6,
        modelIdent: `nam-alaska`,
        modelName: `NAM-AK`,
        bounds: [
            [
                [71.3, 171.8],
                [57.7, 160.9],
                [51, 172],
                [47.8, 180],
                [73, 180]
            ],
            [
                [47.8, -180],
                [43.2, -172.1],
                [46.1, -157],
                [45.7, -142.4],
                [49.7, -128.6],
                [51.5, -116.8],
                [53.2, -114.9],
                [66.6, -119],
                [73.6, -124],
                [75.3, -153.4],
                [73, -180]
            ]
        ]
    }),
    Cu = new Pl({
        ident: `hrrrConus`,
        modelResolution: 3,
        dataQuality: `extreme`,
        modelIdent: `hrrr-conus`,
        intervalPremium: 60,
        bounds: yu
    }),
    wu = new Pl({
        ident: `hrrrAlaska`,
        modelName: `HRRR-AK`,
        modelResolution: 3,
        dataQuality: `extreme`,
        modelIdent: `hrrr-alaska`,
        intervalPremium: 180,
        bounds: [
            [
                [55.7, 157],
                [51.2, 170.4],
                [46, 180],
                [71.6, 180],
                [65.8, 167]
            ],
            [
                [46, -180],
                [41.8, -175],
                [48.8, -160],
                [51.7, -145],
                [52, -129],
                [64.9, -125],
                [76, -116.5],
                [76, -158],
                [71.6, -180]
            ]
        ]
    }),
    Tu = new G({
        ident: `drought`,
        modelName: `CzechGlobe`,
        modelResolution: 9,
        provider: `CzechGlobe`,
        interval: 1440,
        fileSuffix: `png`,
        PNGtransparency: !0,
        dataQuality: `normal`,
        category: `forecast`,
        modelIdent: `intersucho`,
        levels: [`surface`],
        hasAccumulations: !0,
        isolines: [],
        labelsTemp: !1,
        logo: Kl,
        overlays: [`moistureAnom40`, `moistureAnom100`, `drought40`, `drought100`, `soilMoisture40`, `soilMoisture100`],
        freeProduct: !0,
        hideProductSwitch: !0
    }),
    Eu = new G({
        ident: `fireDanger`,
        modelName: `CzechGlobe`,
        modelResolution: 9,
        provider: `CzechGlobe`,
        interval: 1440,
        fileSuffix: `png`,
        PNGtransparency: !0,
        dataQuality: `normal`,
        category: `forecast`,
        modelIdent: `intersucho-firerisk`,
        levels: [`surface`],
        hasAccumulations: !0,
        isolines: [],
        labelsTemp: !1,
        logo: Kl,
        overlays: [`fwi`, `dfm10h`],
        freeProduct: !0,
        hideProductSwitch: !0
    }),
    Du = new G({
        ident: `ecmwfWaves`,
        modelName: `ECMWF WAM`,
        modelResolution: 9,
        preferredAirProduct: `ecmwf`,
        provider: `ECMWF`,
        interval: 720,
        intervalPremium: 360,
        labelsTemp: !1,
        maxTileZoom: {
            free: 3,
            premium: 4
        },
        category: `forecast`,
        modelIdent: `ecmwf-wam`,
        fileSuffix: `png`,
        dataQuality: `normal`,
        overlays: [`waves`, `wavePower`, `swell1`, `swell2`, `swell3`, `wwaves`],
        levels: [`surface`]
    }),
    Ou = new G({
        ident: `ukv`,
        provider: `Met Office`,
        interval: 720,
        intervalPremium: 180,
        modelName: `UKV`,
        modelResolution: 2,
        JPGtransparency: !0,
        animation: !0,
        dataQuality: `extreme`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        category: `forecast`,
        modelIdent: `ukv`,
        forecastSize: 120,
        bounds: [
            [
                [61.3, -24.4],
                [62.7, -11],
                [62.9, .1],
                [61.85, 15.1],
                [54.7, 11.85],
                [45.1, 9.1],
                [45.6, .4],
                [45.6, -7.8],
                [44.7, -17],
                [54.7, -20.5]
            ]
        ],
        levels: [`surface`, `975h`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
        overlays: [`wind`, `temp`, `wetbulbtemp`, `pressure`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `fog`, `rh`, `gust`, `cape`, `dewpoint`, `rain`, `ptype`, `visibility`, `deg0`, `snowAccu`, `rainAccu`, `gustAccu`, `ccl`, `turbulence`],
        isolines: [`pressure`, `gh`, `temp`, `deg0`],
        hasAccumulations: !0,
        logo: Wl
    }),
    ku = new G({
        ident: `gfsWaves`,
        modelName: `GFS WAVE`,
        modelResolution: 22,
        preferredAirProduct: `gfs`,
        provider: `NOAA`,
        interval: 720,
        intervalPremium: 360,
        preferredProduct: `gfs`,
        labelsTemp: !1,
        category: `forecast`,
        modelIdent: `gfs-wave`,
        fileSuffix: `png`,
        forecastSize: 360,
        dataQuality: `low`,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        overlays: [`waves`, `wavePower`, `swell1`, `swell2`, `swell3`, `wwaves`],
        levels: [`surface`]
    }),
    Au = new G({
        ident: `activeFires`,
        modelName: `nasa-firms`,
        modelResolution: 22,
        labelsTemp: !1,
        provider: `NASA`,
        interval: 60,
        category: `analysis`,
        modelIdent: `nasa-firms`,
        dataQuality: `normal`,
        maxTileZoom: {
            free: 18,
            premium: 18
        }
    }),
    ju = new Rl({
        ident: `capAlerts`,
        modelName: ``,
        interval: 0,
        provider: `Various providers`,
        overlays: [`capAlerts`],
        hideProductSwitch: !0
    }),
    Mu = new Rl({
        ident: `avalancheDanger`,
        modelName: ``,
        interval: 0,
        provider: `Various providers`,
        overlays: [`avalancheDanger`],
        hideProductSwitch: !0
    }),
    Nu = new G({
        ident: `efi`,
        provider: `ECMWF`,
        interval: 720,
        modelName: `ECMWF`,
        modelResolution: 9,
        labelsTemp: !1,
        maxTileZoom: {
            free: 3,
            premium: 3
        },
        category: `forecast`,
        modelIdent: `ecmwf-efi`,
        dataQuality: `normal`,
        levels: [`surface`],
        overlays: [`efiTemp`, `efiWind`, `efiRain`],
        hideProductSwitch: !0
    }),
    Pu = new G({
        ident: `jmaMsm`,
        provider: `JMA`,
        interval: 720,
        intervalPremium: 180,
        modelName: `MSM`,
        modelResolution: 5,
        preferredWaveProduct: `jmaCwmWaves`,
        JPGtransparency: !0,
        dataQuality: `high`,
        maxTileZoom: {
            free: 3,
            premium: 5
        },
        category: `forecast`,
        modelIdent: `jma-msm`,
        bounds: [
            [
                [47.6, 120],
                [47.6, 150],
                [22.4, 150],
                [22.4, 120]
            ]
        ],
        levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
        levelsOverride: {
            rh: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`]
        },
        overlays: [`wind`, `temp`, `wetbulbtemp`, `pressure`, `clouds`, `lclouds`, `mclouds`, `hclouds`, `rh`, `dewpoint`, `rain`, `rainAccu`],
        isolines: [`pressure`, `gh`, `temp`],
        hasAccumulations: !0,
        logo: ql
    }),
    Fu = new G({
        ident: `jmaCwmWaves`,
        provider: `JMA`,
        interval: 720,
        intervalPremium: 360,
        modelName: `CWM`,
        modelResolution: 5,
        preferredAirProduct: `jmaMsm`,
        dataQuality: `high`,
        fileSuffix: `png`,
        maxTileZoom: {
            free: 3,
            premium: 5
        },
        labelsTemp: !1,
        category: `forecast`,
        modelIdent: `jma-cwm`,
        bounds: [
            [
                [50, 120],
                [50, 150],
                [20, 150],
                [20, 120]
            ]
        ],
        overlays: [`waves`, `wavePower`, `swell1`, `swell2`, `wwaves`],
        levels: [`surface`],
        logo: ql
    }),
    Iu = [
        [
            [66.57, -152.72],
            [69.81, -132.09],
            [70.59, -114.36],
            [68.37, -85.63],
            [64.55, -69.5],
            [59.07, -56.36],
            [47.91, -40.71],
            [39.15, -54.6],
            [27.27, -66.95],
            [36.52, -84.95],
            [40.39, -99.88],
            [41.54, -111.45],
            [39.62, -133.64],
            [55.16, -141.29]
        ]
    ],
    Lu = new G({
        ident: `canHrdps`,
        provider: `MSC`,
        interval: 720,
        intervalPremium: 360,
        modelName: `HRDPS`,
        modelResolution: 2.5,
        preferredProduct: `ecmwf`,
        preferredWaveProduct: `canRdwpsWaves`,
        JPGtransparency: !0,
        dataQuality: `extreme`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        category: `forecast`,
        modelIdent: `can-hrdps`,
        bounds: Iu,
        levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
        overlays: [`cape`, `ccl`, `clouds`, `dewpoint`, `gust`, `gustAccu`, `hclouds`, `lclouds`, `mclouds`, `pressure`, `ptype`, `rain`, `rainAccu`, `rh`, `snowcover`, `temp`, `turbulence`, `wind`, `wetbulbtemp`],
        isolines: [`pressure`, `gh`, `temp`],
        hasAccumulations: !0
    }),
    Ru = new G({
        ident: `canRdwpsWaves`,
        provider: `MSC`,
        interval: 720,
        intervalPremium: 360,
        modelName: `RDWPS`,
        modelResolution: 2.5,
        preferredAirProduct: `canHrdps`,
        dataQuality: `extreme`,
        fileSuffix: `png`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        labelsTemp: !1,
        category: `forecast`,
        modelIdent: `can-rdwps`,
        bounds: Iu,
        overlays: [`waves`, `wavePower`, `swell1`, `swell2`, `wwaves`],
        levels: [`surface`]
    }),
    zu = new G({
        ident: `czeAladin`,
        provider: `CHMI`,
        interval: 720,
        intervalPremium: 360,
        modelName: `ALADIN`,
        modelResolution: 2.3,
        preferredProduct: `ecmwf`,
        preferredWaveProduct: `ecmwfWaves`,
        JPGtransparency: !0,
        dataQuality: `extreme`,
        maxTileZoom: {
            free: 4,
            premium: 6
        },
        category: `forecast`,
        modelIdent: `cze-aladin`,
        bounds: [
            [
                [56.139, 34.244],
                [56.674, 29.323],
                [56.975, 25.126],
                [57.178, 19.589],
                [57.178, 14.381],
                [56.975, 8.844],
                [56.674, 4.647],
                [56.262, .582],
                [55.547, -4.581],
                [52.382, -3.109],
                [48.582, -1.615],
                [44.174, -.143],
                [38.694, 1.373],
                [39.07, 4.01],
                [39.462, 7.614],
                [39.716, 11.019],
                [39.851, 14.337],
                [39.868, 18.402],
                [39.783, 21.61],
                [39.462, 26.378],
                [39.104, 29.432],
                [48.305, 31.608]
            ]
        ],
        levels: [`surface`, `950h`, `925h`, `900h`, `850h`, `800h`, `700h`, `600h`, `500h`, `400h`, `300h`, `250h`, `200h`, `150h`],
        overlays: [`cape`, `clouds`, `dewpoint`, `gust`, `gustAccu`, `hclouds`, `lclouds`, `mclouds`, `pressure`, `ptype`, `rain`, `rainAccu`, `rh`, `snowAccu`, `solarpower`, `temp`, `thunder`, `turbulence`, `visibility`, `wetbulbtemp`, `wind`],
        hasAccumulations: !0,
        isolines: [`pressure`, `gh`, `temp`]
    }),
    Bu = new Ll({
        ident: `satellite`,
        animation: !1,
        modelName: ``,
        provider: `EUMETSAT`,
        interval: 3,
        directory: `satellite/tile`,
        server: `https://sat.windy.com`,
        urlSuff: `visir.jpg?mosaic=true`,
        urlSuffFlow: `visir.jpg`,
        labelsTemp: !1,
        overlays: [`satellite`],
        levels: [`surface`],
        maxTileZoom: {
            free: 7,
            premium: 11
        },
        hideProductSwitch: !0
    }),
    K = {
        bomAccess: iu,
        bomAccessAd: au,
        bomAccessBn: ou,
        bomAccessDn: su,
        bomAccessNq: cu,
        bomAccessPh: lu,
        bomAccessSy: uu,
        bomAccessVt: du,
        mblue: vu,
        ecmwf: Jl,
        ecmwfWaves: Du,
        ecmwfAnalysis: Yl,
        canHrdps: Lu,
        canRdwpsWaves: Ru,
        cams: Xl,
        camsEu: Zl,
        cmems: Ql,
        czeAladin: zu,
        gfs: $l,
        gfsWaves: ku,
        icon: eu,
        iconD2: nu,
        iconEu: tu,
        iconEuWaves: ru,
        arome: gu,
        aromeAntilles: pu,
        aromeFrance: mu,
        aromeReunion: hu,
        nems: _u,
        namAlaska: Su,
        namConus: bu,
        namHawaii: xu,
        capAlerts: ju,
        efi: Nu,
        radar: new Ll({
            ident: `radar`,
            animation: !1,
            hasMinifest: !1,
            modelName: ``,
            provider: ``,
            interval: 3,
            fileSuffix: `webp`,
            fileSuffixFallback: `png`,
            directory: `radar2/composite`,
            server: `https://rdr.windy.com`,
            labelsTemp: !1,
            overlays: [`radar`],
            levels: [`surface`],
            hideProductSwitch: !0,
            urlSuff: ``,
            urlSuffFlow: ``
        }),
        satellite: Bu,
        drought: Tu,
        fireDanger: Eu,
        hrrrAlaska: wu,
        hrrrConus: Cu,
        ukv: Ou,
        activeFires: Au,
        jmaMsm: Pu,
        jmaCwmWaves: Fu,
        topoMap: new Rl({
            ident: `topoMap`,
            modelName: `Outdoor Map`,
            interval: 0,
            provider: `Seznam.cz`,
            overlays: [`topoMap`],
            hideProductSwitch: !0
        }),
        avalancheDanger: Mu
    };
var Vu = b({
    bestModelFromSameGroup: () => Gu,
    betterProducts: () => Ku,
    getAllPointProducts: () => Yu,
    getDefaultProduct: () => $u,
    getPointProducts: () => Xu,
    getProduct: () => Ju,
    hasMoreProducts: () => Qu,
    layer2product: () => Hu,
    overlay2product: () => Uu
});
const Hu = {},
    Uu = {},
    Wu = Object.keys(K);
Object.keys(Kc).forEach(e => {
    let t = [];
    for (let n = 0; n < Wu.length; n++) K[Wu[n]].overlays.includes(e) && t.push(Wu[n]);
    Hu[e] = t
}), Object.keys(Is).forEach(e => {
    let t = [];
    for (let n = 0; n < Wu.length; n++) K[Wu[n]].overlays.includes(e) && t.push(Wu[n]);
    Uu[e] = t
});
const Gu = (e, t) => e === `icon` && t.includes(`iconEu`) ? `iconEu` : e === `iconEu` && t.includes(`icon`) ? `icon` : e.includes(`aromeFrance`) && e.includes(`arome`) ? `arome` : e === `cams` && t.includes(`camsEu`) ? `camsEu` : e === `camsEu` && t.includes(`cams`) ? `cams` : null,
    Ku = (e, t) => {
        let n = t ? Ae : Te,
            r = [];
        for (let i = 0; i < n.length; i++) {
            let a = n[i],
                o = K[a];
            (t && o.pointIsInBounds.call(o, e) || !t && o.boundsAreInViewport.call(o, Z)) && r.push(a)
        }
        return r
    },
    qu = () => {
        let e = Ku(M.get(`mapCoords`)).concat(Ee);
        if (M.set(`visibleProducts`, e) && !e.includes(M.get(`product`))) {
            let t = M.get(`preferredProduct`),
                n = M.get(`overlay`);
            if (K[t].overlays.includes(n)) M.set(`product`, t);
            else {
                let t = e.filter(e => K[e].overlays.includes(n));
                t.length && M.set(`product`, t[0])
            }
        }
    };
N.once(`paramsChanged`, () => {
    qu(), M.on(`mapCoords`, qu)
});
const Ju = (e, t) => {
        let n = Hu[e],
            r = M.get(`preferredProduct`),
            i = K[t];
        if (n.length === 2 && n.includes(`cams`)) {
            let e = M.get(`mapCoords`);
            return K.camsEu.pointIsInBounds(e) && n.includes(`camsEu`) ? `camsEu` : `cams`
        }
        if (n.includes(t)) return t;
        if (n.includes(`iconD2`) && r === `iconEu`) {
            let e = M.get(`mapCoords`);
            if (K.iconD2.pointIsInBounds(e)) return `iconD2`
        }
        if (n.includes(`iconEu`) && r === `icon`) {
            let e = M.get(`mapCoords`);
            if (K.iconEu.pointIsInBounds(e)) return `iconEu`
        }
        if (n.includes(i.preferredAirProduct)) return i.preferredAirProduct;
        if (n.includes(i.preferredWaveProduct)) {
            if (i.preferredWaveProduct === `iconEuWaves`) {
                let e = M.get(`mapCoords`);
                if (K.iconEuWaves.pointIsInBounds(e)) return `iconEuWaves`
            }
            return i.preferredWaveProduct
        }
        if (n.includes(r)) return r;
        if (n.length > 1) {
            let e = M.get(`mapCoords`),
                t = n.filter(t => K[t].pointIsInBounds.call(K[t], e))[0];
            if (t) return t
        }
        return n[0]
    },
    Yu = e => {
        let t = Ku(e, !0).filter(e => Pe.includes(e));
        return [...je, ...t]
    },
    Xu = e => Yu(e).filter(e => Pe.includes(e)),
    Zu = e => {
        var t, n;
        return (t = (n = Hu[e]) == null ? void 0 : n.length) == null ? 0 : t
    },
    Qu = e => Zu(e) > 1,
    $u = e => {
        if (Zu(e) > 0) {
            let t = Hu[e];
            return t.includes(`ecmwf`) ? `ecmwf` : t[0]
        } else return
    };
var ed = b({
        Drag: () => td
    }),
    td = class {
        constructor(e) {
            var t, n, r, i, a, o, s, c, l, u, d;
            C(this, `supportTouch`, void 0), C(this, `preventDefault`, void 0), C(this, `passiveListener`, void 0), C(this, `startXY`, void 0), C(this, `bindedDrag`, void 0), C(this, `bindedEndDrag`, void 0), C(this, `bindedStart`, void 0), C(this, `offsetX`, void 0), C(this, `offsetY`, void 0), C(this, `dragging`, !1), C(this, `el`, void 0), this.el = e.el, this.supportTouch = (t = e.supportTouch) == null ? !0 : t, this.preventDefault = (n = e.preventDefault) == null ? !0 : n, this.passiveListener = (r = e.passiveListener) == null ? !0 : r, this.ondrag = (i = e.ondrag) == null ? this.ondrag : i, this.ondragstart = (a = e.ondragstart) == null ? this.ondragstart : a, this.ondragend = (o = e.ondragend) == null ? this.ondragend : o, this.bindedDrag = (s = e.bindedDrag) == null ? this._drag.bind(this) : s, this.bindedEndDrag = (c = e.bindedEndDrag) == null ? this.endDrag.bind(this) : c, this.bindedStart = (l = e.bindedStart) == null ? this.startDrag.bind(this) : l, this.startDrag = (u = e.startDrag) == null ? this.startDrag : u, this.endDrag = (d = e.endDrag) == null ? this.endDrag : d, this.el.addEventListener(`mousedown`, this.bindedStart), this.supportTouch && this.el.addEventListener(`touchstart`, this.bindedStart)
        }
        destroy() {
            this.el.removeEventListener(`mousedown`, this.bindedStart), this.supportTouch && this.el.removeEventListener(`touchstart`, this.bindedStart)
        }
        startDrag(e) {
            this.preventDefault && e.preventDefault(), this.startXY = this.getXY(e), this.offsetX = this.el.offsetLeft, this.offsetY = this.el.offsetTop, this.dragging = !0, this.ondragstart && this.ondragstart.call(this, this.startXY), window.addEventListener(`mousemove`, this.bindedDrag), window.addEventListener(`mouseup`, this.bindedEndDrag), this.supportTouch && (window.addEventListener(`touchmove`, this.bindedDrag, this.passiveListener ? void 0 : {
                passive: !1
            }), window.addEventListener(`touchend`, this.bindedEndDrag), window.addEventListener(`touchcancel`, this.bindedEndDrag))
        }
        endDrag(e) {
            window.removeEventListener(`mousemove`, this.bindedDrag), window.removeEventListener(`touchmove`, this.bindedDrag, this.passiveListener ? void 0 : {
                passive: !1
            }), window.removeEventListener(`mouseup`, this.bindedEndDrag), window.removeEventListener(`touchend`, this.bindedEndDrag), window.removeEventListener(`touchcancel`, this.bindedEndDrag), this.ondragend && this.ondragend(e), this.dragging = !1
        }
        getXY(e) {
            return Jt(e) ? [e.touches[0].pageX, e.touches[0].pageY] : [e.pageX, e.pageY]
        }
        _drag(e) {
            if (!this.ondrag) return;
            let t = this.getXY(e);
            this.ondrag(t[0] - this.startXY[0] + this.offsetX, t[1] - this.startXY[1] + this.offsetY, e)
        }
    },
    nd = b({
        Swipe: () => rd
    }),
    rd = class {
        constructor(e) {
            var t, n;
            C(this, `el`, void 0), C(this, `threshold`, void 0), C(this, `direction`, void 0), C(this, `isSwipeValid`, void 0), C(this, `x`, void 0), C(this, `y`, void 0), C(this, `xStart`, void 0), C(this, `yStart`, void 0), C(this, `xThrottled`, void 0), C(this, `yThrottled`, void 0), this.el = e.el, this.onswipe = e.onswipe, this.threshold = (t = e.threshold) == null ? 50 : t, this.onswipestart = (n = e.onswipestart) == null ? this.onswipestart : n, this.el.addEventListener(`touchstart`, this.touchStart.bind(this)), this.el.addEventListener(`touchmove`, this.touchMove.bind(this)), this.el.addEventListener(`touchend`, this.touchEnd.bind(this))
        }
        touchStart(e) {
            this.isSwipeValid = !0, this.direction = null, this.x = this.xStart = this.xThrottled = e.touches[0].clientX, this.y = this.yStart = this.yThrottled = e.touches[0].clientY, this.onswipestart(e)
        }
        touchMove(e) {
            this.x = e.touches[0].clientX, this.y = e.touches[0].clientY;
            let t = this.x - this.xThrottled,
                n = this.y - this.yThrottled;
            if (ot(t, n) < this.threshold) return;
            this.xThrottled = this.x, this.yThrottled = this.y;
            let r = null;
            if (Math.abs(n / t) < .2 ? r = t > 0 ? `right` : `left` : Math.abs(t / n) < .2 && (r = n > 0 ? `down` : `up`), r !== null) {
                if (this.direction !== null && this.direction !== r) {
                    this.isSwipeValid = !1;
                    return
                }
                this.direction = r
            }
        }
        touchEnd(e) {
            if (this.direction === null || !this.isSwipeValid) return;
            let t = ot(this.x - this.xStart, this.y - this.yStart),
                n = e.target;
            for (; n && n !== this.el;) {
                if (n.dataset.ignoreSwipe) return;
                n = n.parentElement
            }
            this.onswipe(this.direction, t, e)
        }
        onswipestart(e) {}
        onswipe(e, t, n) {}
    },
    id = b({
        BottomSlide: () => ad
    }),
    ad = class extends td {
        constructor(e) {
            super(w(w({}, e), {}, {
                preventDefault: !1,
                passiveListener: !1
            })), C(this, `pluginEl`, void 0), C(this, `pluginName`, void 0), C(this, `scrollEl`, void 0), C(this, `closeOnSwipeDown`, void 0), C(this, `threshold`, 30), C(this, `swipeHandler`, void 0), C(this, `startY`, void 0), C(this, `transformedY`, void 0), C(this, `throttledY`, void 0), C(this, `difference`, void 0), C(this, `onRqstPluginHalfOpen`, (e, t, n) => {
                e === this.pluginName && this.setHalfOpen(t, n)
            }), this.pluginEl = e.pluginEl, this.pluginName = e.pluginName, this.closeOnSwipeDown = e.closeOnSwipeDown, this.scrollEl = e.scrollEl;
            let t = this.scrollEl || Kt(`.plugin__content`, this.pluginEl);
            if (!t) return;
            let n = !1;
            t.addEventListener(`scroll`, () => {
                t.scrollTop > 20 && !n ? (this.pluginEl.classList.add(`show-header`), n = !0) : t.scrollTop < 21 && n && (this.pluginEl.classList.remove(`show-header`), n = !1)
            }), this.closeOnSwipeDown && this.initCloseOnSwipeDown(t), N.on(`rqstHalfOpen`, this.onRqstPluginHalfOpen)
        }
        ondrag(e, t, n) {
            this.transformedY = this.startY + t, this.updatePosition(Math.max(0, this.transformedY)), Math.abs(this.throttledY - this.transformedY) > this.threshold && (this.difference = this.transformedY - this.throttledY, this.throttledY = this.transformedY), n.preventDefault()
        }
        ondragend() {
            if (!(Math.abs(this.transformedY - this.startY) > this.threshold)) {
                this.updatePosition(this.startY);
                return
            }
            this.pluginEl.style.transition = ``, this.pluginEl.style.transform = ``, this.difference > 0 ? this.closeOnSwipeDown || this.pluginEl.classList.contains(`open-half`) ? N.emit(`rqstClose`, this.pluginName) : this.setHalfOpen(!0) : this.setHalfOpen(!1)
        }
        startDrag(e) {
            super.startDrag(e);
            let {
                transform: t
            } = window.getComputedStyle(this.pluginEl), n = /matrix\(.+,\s*(\S+)\)/.exec(t);
            this.startY = n && n[1] ? +n[1] : 0, this.transformedY = this.startY, this.throttledY = this.startY, this.difference = 0, this.pluginEl.style.transition = `none`
        }
        release() {
            N.off(`rqstHalfOpen`, this.onRqstPluginHalfOpen)
        }
        initCloseOnSwipeDown(e) {
            let t;
            this.swipeHandler = new rd({
                el: this.pluginEl,
                threshold: 80,
                onswipestart() {
                    t = e.scrollTop <= 0
                },
                onswipe: e => {
                    t && e === `down` && N.emit(`rqstClose`, this.pluginName)
                }
            })
        }
        setHalfOpen(e, t = !0) {
            e === void 0 ? e = this.pluginEl.classList.toggle(`open-half`) : e ? this.pluginEl.classList.add(`open-half`) : this.pluginEl.classList.remove(`open-half`), t && N.emit(`pluginHalfOpened`, this.pluginName, e)
        }
        updatePosition(e) {
            this.pluginEl.style.transform = `translate(0px,${Math.floor(e)}px)`
        }
    },
    od = b({
        Plugin: () => sd
    }),
    sd = class {
        constructor(e) {
            var t, n, r, i;
            C(this, `loading`, void 0), C(this, `promise`, void 0), C(this, `ident`, void 0), C(this, `location`, void 0), C(this, `langFiles`, void 0), C(this, `isLoaded`, void 0), C(this, `pane`, void 0), C(this, `isOpen`, void 0), C(this, `neverClose`, void 0), C(this, `isResolved`, void 0), C(this, `plugin`, void 0), C(this, `disableMobilePicker`, void 0), this.initProperties(), this.pane = e.pane, this.ident = e.ident, this.langFiles = e.langFiles || [], this.location = (t = e.location) == null ? zt(Ue, `${this.ident}.js`) : t, this.close = (n = e.close) == null ? this.close : n, this.paramsChanged = (r = e.paramsChanged) == null ? this.paramsChanged : r, this.redraw = (i = e.redraw) == null ? this.redraw : i, this.neverClose = e.neverClose, this.disableMobilePicker = e.disableMobilePicker
        }
        load() {
            return this.isLoaded ? Promise.resolve(!0) : this.loading ? this.promise || Promise.resolve(!0) : (this.loading = !0, new Promise((e, t) => {
                let n = () => {
                        import(this.location).then(t => {
                            this.plugin = t, this.isLoaded = !0, this.loading = !1, e(!0)
                        }).catch(e => {
                            console.error(`Failed to load plugin: ${this.ident}`, e), ir(), t(e)
                        })
                    },
                    r = [`main`, ...this.langFiles].map(e => Tr(e));
                Promise.all(r).then(n).catch(e => {
                    this.loading = !1, O(`plugin`, `Failed to load language dependencies: ${this.ident}`, e), t(e)
                })
            }))
        }
        open(...e) {
            return this.promise = this.load(), this.promise
        }
        close(e) {}
        redraw(...e) {}
        paramsChanged(...e) {}
        onRenderStart(...e) {}
        initProperties() {
            this.loading = !1, this.isLoaded = !1
        }
    };
C(sd, `iAm`, `plugin`);
var cd = b({
    opener: () => md,
    register: () => dd,
    release: () => fd,
    singleclick: () => ud
});
const ld = {
        high: null,
        low: null
    },
    ud = new Ln({
        ident: `singleclick`
    }),
    dd = (e, t) => ld[t] = e,
    fd = (e, t) => {
        ld[t] === e && (ld[t] = null)
    },
    pd = e => ({
        x: e.containerPoint.x,
        y: e.containerPoint.y,
        lat: e.latlng.lat,
        lon: e.latlng.lng,
        source: `singleclick`
    }),
    md = e => {
        let t = e.originalEvent && e.originalEvent.target,
            n = t && t.dataset;
        if (n && n.poi) {
            let e = n.poi;
            ud.emit(`poi-${e}`, t)
        } else {
            let t = pd(e),
                n = ld.high || ld.low || `click`;
            ud.emit(n, t)
        }
    };
var hd = b({
        WindowPlugin: () => gd
    }),
    gd = class extends sd {
        constructor(e) {
            var t, n, r, i, a, o, s, c, l, u, d, f, p, m, h, g;
            super(e), C(this, `window`, void 0), C(this, `isMounted`, void 0), C(this, `cssID`, void 0), C(this, `bottomSlide`, void 0), C(this, `cssInserted`, void 0), C(this, `title`, void 0), C(this, `addMobileSlider`, void 0), C(this, `router`, void 0), C(this, `path`, void 0), C(this, `useSEOurl`, void 0), C(this, `closeOnSwipeDown`, void 0), C(this, `closesOnSwipeRight`, void 0), C(this, `noCloseOnBackButton`, void 0), C(this, `interpolator`, void 0), C(this, `keyboard`, void 0), C(this, `closeOnClick`, void 0), C(this, `logUsage`, void 0), C(this, `noAnimation`, void 0), C(this, `className`, void 0), C(this, `attachPoint`, void 0), C(this, `singleclickPriority`, void 0), C(this, `noHeader`, void 0), C(this, `closingRequested`, void 0), this.ident = e.ident, this.addMobileSlider = (t = e.addMobileSlider) == null ? this.addMobileSlider : t, this.closeOnSwipeDown = (n = e.closeOnSwipeDown) == null ? this.closeOnSwipeDown : n, this.closesOnSwipeRight = (r = e.closesOnSwipeRight) == null ? this.closesOnSwipeRight : r, this.logUsage = (i = e.logUsage) == null ? !0 : i, this.noCloseOnBackButton = e.noCloseOnBackButton, this.interpolator = e.interpolator, this.title = e.title, this.useSEOurl = (a = e.useSEOurl) == null ? !1 : a, this.router = (o = e.router) == null ? this.router : o, this.path = (s = e.path) == null ? typeof this.router == `string` ? this.router : void 0 : s, this.onRouteMatch = (c = e.onRouteMatch) == null ? this.onRouteMatch : c, this.displayURLAndTitle = (l = e.displayURLAndTitle) == null ? this.displayURLAndTitle : l, this.attachPoint = (u = e.attachPoint) == null ? this.attachPoint : u, this.className = (e.className || ``) + (e.noHeader ? ` no-header` : ``), this.closeOnClick = (d = e.closeOnClick) == null ? this.closeOnClick : d, this.keyboard = (f = e.keyboard) == null ? this.keyboard : f, this.noAnimation = e.noAnimation, this.singleclickPriority = (p = e.singleclickPriority) == null ? void 0 : p, this.close = (m = e.close) == null ? this.close : m, this.onopen = (h = e.onopen) == null ? this.onopen : h, this.beforeLoad = (g = e.beforeLoad) == null ? this.beforeLoad : g, this.cssID = `${sd.iAm}-css-${this.ident}`
        }
        open({
            params: e,
            disableOpeningAnimation: t,
            qs: n
        } = {}) {
            this.beforeLoad(e), this.closingRequested = !1, this.logUsage && yl(`plugin`, this.ident);
            let r = () => {
                this.closingRequested || (this.window || (this.window = this.createWindow()), this.isMounted || this.mount(), this.window.open({
                    disableOpeningAnimation: t
                }), this.isOpen = !0, this.singleclickPriority && dd(this.ident, this.singleclickPriority), setTimeout(() => {
                    N.emit(`pluginOpened`, this.ident)
                }, 50), this.onopen(e, n))
            };
            return this.isOpen ? (this.onopen(e, n), Promise.resolve()) : this.isLoaded ? (r(), Promise.resolve()) : ((!this.loading || !this.promise) && (this.promise = this.load(), this.promise.then(r)), this.promise)
        }
        close(e) {
            if (this.isOpen) {
                var t;
                (t = this.window) == null || t.close(e)
            } else this.loading && (this.closingRequested = !0)
        }
        displayURLAndTitle(e) {
            if (this.path) {
                let t = this.title && this.title in P ? P[this.title] : this.title || null;
                t && Fm(t), Pm(this.ident, e, this.useSEOurl && t ? `-${Ei(t)}` : void 0)
            }
        }
        onopen(e, t) {
            if (S && this.disableMobilePicker && N.emit(`rqstClose`, `picker-mobile`), this.displayURLAndTitle(e), `onopen` in this.plugin && typeof this.plugin.onopen == `function`) try {
                var n, r;
                (n = (r = this.plugin).onopen) == null || n.call(r, e)
            } catch (e) {
                console.error(`onopen method of plugin ${this.ident} failed:`, e)
            }
        }
        ondestroy() {
            if (this.isOpen = !1, this.path && Lm(this.ident), this.singleclickPriority && fd(this.ident, this.singleclickPriority), `ondestroy` in this.plugin && typeof this.plugin.ondestroy == `function`) return this.plugin.ondestroy()
        }
        beforeLoad(...e) {}
        onRouteMatch(e, t) {
            return e
        }
        getPluginUrl(e) {
            return this.path ? this.path.replace(/\/:(\w+)(\?)?/g, (t, n, r) => {
                let i = e && e[n];
                return i == null ? `` : n === `lat` || n === `lon` ? `/${E(i)}` : `/${i}`
            }) : ``
        }
        get node() {
            return this.window.node
        }
        createWindow() {
            return new kr({
                bodyClass: `on${this.ident}`,
                ident: this.ident,
                keyboard: this.keyboard,
                className: this.className,
                attachPoint: this.attachPoint,
                closeOnClick: this.closeOnClick,
                noAnimation: this.noAnimation,
                html: ``,
                htmlID: `${sd.iAm}-${this.ident}`,
                onclose: () => this.ondestroy(),
                onclosed: () => this.unmount()
            })
        }
        getCss() {
            let {
                __css: e
            } = this.plugin;
            return e
        }
        initProperties() {
            super.initProperties(), this.addMobileSlider = !1, this.closeOnSwipeDown = !0, this.isMounted = !1
        }
        unmount() {
            var e, t;
            if ((e = this.node) == null || (e = e.parentNode) == null || e.removeChild(this.node), this.cssInserted) {
                let e = Kt(`#${this.cssID}`);
                e && document.head.removeChild(e), this.cssInserted = !1
            }
            this.isMounted = !1, (t = this.bottomSlide) == null || t.release(), x && this.pane === `fullscreen-mobile` && M.set(`suspendSoundAndHaptic`, !1), N.emit(`pluginClosed`, this.ident)
        }
        mountCss() {
            let e = this.getCss();
            e && !this.cssInserted && (document.head.insertAdjacentHTML(`beforeend`, `<style id="${this.cssID}">${e}</style>`), this.cssInserted = !0)
        }
        mount() {
            if (!this.plugin) throw Error(`Trying to mount, but plugin ${this.ident} not loaded`);
            this.mountCss(), this.window.mount(), this.isMounted = !0, this.onmounted()
        }
        onmounted() {
            if (this.addMobileSlider && x && this.node && (this.node.insertAdjacentHTML(`beforeend`, `<div class="sliding-x"></div>`), this.bottomSlide = new ad({
                    el: Kt(`.sliding-x`, this.node),
                    pluginEl: this.node,
                    pluginName: this.ident,
                    closeOnSwipeDown: this.closeOnSwipeDown
                })), this.closesOnSwipeRight && this.node && new rd({
                    el: this.node,
                    threshold: 100,
                    onswipe: e => {
                        e === `right` && this.close()
                    }
                }), `onmount` in this.plugin && typeof this.plugin.onmount == `function`) {
                var e, t;
                let i = {};
                ((e = (t = this.node) == null ? void 0 : t.querySelectorAll(`[data-ref]`)) == null ? [] : e).forEach(e => {
                    e.dataset.ref && (i[e.dataset.ref] = e)
                });
                try {
                    var n, r;
                    (n = (r = this.plugin).onmount) == null || n.call(r, this.node, i)
                } catch (e) {
                    this.unmount(), O(`WindowPlugin`, `Failed to mount ${this.ident} plugin`, e)
                }
            }
            x && this.pane === `fullscreen-mobile` && M.set(`suspendSoundAndHaptic`, !0)
        }
    },
    _d = b({
        SveltePlugin: () => q
    }),
    q = class extends gd {
        constructor(e) {
            super(e), C(this, `svelteApp`, void 0), C(this, `needsPluginRoot`, void 0), C(this, `onRenderStart`, e => {
                super.onRenderStart(e), this.svelteApp && `onRenderStart` in this.svelteApp && this.svelteApp.onRenderStart(e)
            }), this.needsPluginRoot = e.needsPluginRoot
        }
        onopen(e, t) {
            if (this.displayURLAndTitle(e), this.svelteApp && this.svelteApp.onopen) try {
                this.svelteApp.onopen(e)
            } catch (e) {
                console.error(`onopen method of plugin ${this.ident} failed:`, e)
            }
        }
        paramsChanged(e) {
            super.paramsChanged(e), this.svelteApp && `paramsChanged` in this.svelteApp && this.svelteApp.paramsChanged(e)
        }
        mount() {
            this.mountCss(), this.window.mount();
            let e = this.node,
                t = Kt(`.closing-x`, this.node),
                {
                    default: n
                } = this.plugin;
            this.svelteApp = new n({
                target: e,
                anchor: t,
                props: this.needsPluginRoot ? {
                    pluginRootElement: e
                } : {}
            }), this.isMounted = !0, this.onmounted()
        }
        unmount() {
            if (!this.node) {
                O(`SveltePlugin`, `Trying to unmount non existent DOM element ${this.ident}`);
                return
            }
            if (this.svelteApp) {
                var e;
                this.svelteApp.$destroy(), (e = this.node.parentNode) == null || e.removeChild(this.node), this.isMounted = !1, this.svelteApp = null
            }
            super.unmount()
        }
    },
    vd = class extends q {
        constructor(e) {
            e.attachPoint = `[data-plugin="bottom-controls-${S ? `mobile` : `desktop`}"]`, e.className = e.className || `plugin-bottom`, e.noCloseOnBackButton = !0, e.neverClose = !0, e.pane = `small-bottom`, e.noAnimation = !0, super(e)
        }
    },
    yd = class extends q {
        constructor(e) {
            var t, n, r;
            e.attachPoint = (t = e.attachPoint) == null ? `[data-plugin="startup-element"]` : t, e.className = (n = e.className) == null ? `plugin-startup-element dark-content` : n, e.logUsage = (r = e.logUsage) == null ? !1 : r, super(e)
        }
    },
    bd = b({
        SveltePanePlugin: () => J
    });
const xd = x ? `plugin-mobile-bottom-slide top-border` : `plugin-rhpane top-border`,
    Sd = x ? `fullscreen-mobile` : `rhpane`;
var J = class extends q {
        constructor(e) {
            var t, n, r, i, a, o;
            e.className = ((t = e.className) == null ? xd : t) + (e.usesLightContent ? `` : ` dark-content`), e.pane = (n = e.pane) == null ? Sd : n, e.keyboard = (r = e.keyboard) == null ? !0 : r, e.addMobileSlider = (i = e.addMobileSlider) == null ? !0 : i, e.closeOnSwipeDown = (a = e.closeOnSwipeDown) == null ? !0 : a, e.closesOnSwipeRight = (o = e.closesOnSwipeRight) == null ? Fe : o, super(e), C(this, `usesLightContent`, void 0)
        }
    },
    Cd = b({
        TagPlugin: () => wd
    }),
    wd = class extends gd {},
    Td = b({
        loadAndMergeSettingFromCloud: () => Pd,
        storeSettings: () => Nd
    });
let Ed = j.get(`storedSettings`) || 0;
const Dd = e => `settings_${e}`,
    Od = e => `${Dd(e)}_ts`,
    kd = e => !!(e in A && typeof A[e] == `object` && A[e].sync),
    Ad = e => +(A[e].update || j.get(`settings_${e}_ts`) || 0),
    jd = () => {
        let e = {},
            t = 0;
        for (let n in A) {
            let r = n;
            if (kd(r)) {
                let n = Ad(r);
                n > Ed && (e[Dd(r)] = M.get(r, {
                    forceGet: !0
                }), e[Od(r)] = n, t = Math.max(t, n))
            }
        }
        return {
            toStore: e,
            updated: t
        }
    };

function Md(e) {
    for (let t in A) {
        let n = t;
        if (kd(n) && Dd(n) in e) {
            let t = Od(n),
                r = e[t],
                i = j.get(t);
            if (!i || i < r) {
                let t = e[Dd(n)];
                t === null ? M.remove(n, {
                    doNotCheckValidity: !0,
                    doNotSaveToCloud: !0
                }) : M.set(n, t, {
                    update: r,
                    doNotSaveToCloud: !0
                })
            }
        }
    }
}
async function Nd() {
    let {
        toStore: e,
        updated: t
    } = jd();
    if (!t) return !0;
    try {
        let {
            status: n
        } = await $r(`/users/settings`, {
            data: {
                version: 4,
                data: e,
                storeTs: t
            }
        });
        return n < 300 ? (Ed = t, j.put(`storedSettings`, t), !0) : (O(`settings`, `Cant save settings to the cloud. Status code ${n}`), !1)
    } catch (e) {
        return O(`settings`, `Cant save settings to the cloud`, e), !1
    }
}
async function Pd() {
    try {
        let {
            status: e,
            data: t
        } = await F(`/users/settings?storeTs=${Ed}`);
        return (j.get(`lastSyncableUpdatedItem`) || 0) > Ed && Nd(), e === 304 || e === 204 ? !1 : (t && t.data && t.version > 1 && (Md(t.data), t.storeTs > Ed && (Ed = t.storeTs, j.put(`storedSettings`, t.storeTs))), !0)
    } catch (e) {
        return O(`settings`, `Cant load/merge settings from cloud`, e), !1
    }
}
const Fd = yt(Nd, 2e3);
M.on(`_cloudSync`, Fd);
var Id = b({
    deactivateCurrentDevice: () => zd,
    saveCurrentDevice: () => Bd
});
const Ld = async e => {
    M.get(`user`) && await ei(`/users/v3/devices/${e.deviceID}`, {
        data: e
    })
}, Rd = () => {
    let {
        width: e,
        height: t
    } = window.screen, n = M.get(`country`), r = M.get(`subscription`);
    return {
        deviceID: ur(),
        platform: _e,
        target: ge,
        version: he,
        cc: n,
        subscription: r,
        screen: {
            width: e,
            height: t,
            devicePixelRatio: window.devicePixelRatio
        }
    }
}, zd = async () => {
    let e = Rd();
    e.deactivated = !0, await Ld(e), M.remove(`pushNotificationsReady`)
}, Bd = async e => {
    await Ld(Rd()), e && M.set(`pushNotificationsReady`, !0)
};
var Vd = b({
    getLocationEntity: () => Ud,
    sendTestNotification: () => Gd,
    upsertLocationEntity: () => Wd
});
const Hd = `/notif/v1/locations`;
async function Ud(e) {
    return (await F(`${Hd}/${e}`, {
        cache: !1
    })).data
}
async function Wd(e, t, n) {
    return (await ti(`${Hd}/${e}`, w(w({}, n), {}, {
        data: t
    }))).data
}
async function Gd(e) {
    await F(`${Hd}/${e}/testNotification`, {
        cache: !1
    })
}
var Kd = b({
    isForecastAlert: () => qd,
    isLiveAlert: () => Jd,
    normalizeAlertType: () => Yd
});

function qd(e) {
    return e.type === `forecast`
}

function Jd(e) {
    return e.type === `live`
}

function Yd(e) {
    return e.type ? e : w(w({}, e), {}, {
        type: `forecast`
    })
}
var Xd = b({
    add: () => lf,
    createAlert: () => rf,
    deleteAlert: () => of,
    getAlert: () => nf,
    getAlertTimestamps: () => $d,
    getAlerts: () => tf,
    getNearAlert: () => sf,
    getNearAlerts: () => cf,
    updateAlert: () => af,
    userHasAnyAlerts: () => uf
});
let Zd = !1;
setInterval(() => {
    Zd = !1
}, 30 * et);
const Qd = () => N.emit(`alertChanged`);
async function $d(e) {
    let {
        data: t
    } = await F(`/users/v4/alerts/${e}/timestamps`, {
        ttl: et
    });
    return t
}
async function ef() {
    await Ha.loadFromCloud(), Zd = !0, Qd()
}
async function tf() {
    return Zd || await ef(), (await Ha.getAll()).map(Yd)
}
async function nf(e) {
    Zd || await ef();
    let t = await Ha.get(e);
    return t ? Yd(t) : null
}
async function rf(e) {
    await Ha.add(e), Qd()
}
async function af(e) {
    return await Ha.put(e.id, e), Qd(), e
}
async function of(e) {
    await Ha.remove(e), Qd()
}
async function sf(e) {
    return (await cf(e)).at(0)
}
async function cf(e) {
    var t;
    return (t = (await tf()).filter(t => Dt(t, e))) == null ? [] : t
}

function lf(e) {
    let t = w({
        action: `new`
    }, e);
    sp() ? N.emit(`rqstOpen`, `alerts-edit`, t) : _p({
        action: `alerts-edit`,
        params: t
    })
}
async function uf() {
    return (await tf()).length > 0
}
var df = b({
    canReceiveNotifications: () => _f,
    deleteAllNotifications: () => bf,
    loadNotifications: () => vf,
    markNotificationAsReceived: () => Cf,
    markNotificationAsSeen: () => Sf,
    sendTestNotification: () => wf,
    watchChanges: () => yf
});
const ff = Gt(`PushNotifications`),
    pf = Gt(`LocalNotifications`),
    mf = `/notif/v1/notifications`;
let hf = !1,
    gf;
const _f = new Promise(e => {
    gf = e
});
async function vf() {
    let {
        data: {
            newCount: e
        }
    } = await F(mf, {
        cache: !1
    });
    M.set(`badgeNumber`, e)
}

function yf() {
    hf || (hf = !0, gf(), setInterval(vf, et), vf())
}
async function bf() {
    await Qr(mf), await xf()
}
async function xf() {
    if (M.set(`badgeNumber`, 0), ff && ff.removeAllDeliveredNotifications(), pf) {
        let e = await pf.getPending();
        e && e.notifications && e.notifications.length && pf.cancel(e)
    }
}

function Sf(e) {
    return $r(`/notif/v1/interactions/opened`, {
        data: e
    })
}

function Cf(e) {
    return $r(`/notif/v1/interactions/received`, {
        data: e
    })
}

function wf(e, t, n) {
    $r(`/notif/v1/notifications/send-test`, {
        data: {
            registrationHash: t,
            notificationType: e,
            deviceID: n
        }
    }).then(e => {
        console.log(`Sending test notification`, JSON.stringify(e))
    }).catch(e => console.error(JSON.stringify(e)))
}
setTimeout(() => {
    N.once(`alertChanged`, async () => !hf && await uf() && yf())
}, 3e3);
var Tf = b({
    registerDevice: () => Ef
});
const Ef = async () => null;
var Df = b({
    checkConsent: () => Mf,
    setExplicitConsent: () => Af
});
const Of = () => {
        let e = M.get(`consent`),
            t = e ? (Date.now() - e.timestamp) / tt : 0,
            n = e && e.explicit === !1,
            r = e && (!e.analytics && t >= 90 || e.analytics && t >= 365);
        (n || r) && (M.remove(`consent`), e = null), !e && !sp() && N.emit(`rqstOpen`, `consent`)
    },
    kf = `2023/11`,
    Af = e => {
        M.set(`consent`, {
            version: kf,
            timestamp: Date.now(),
            analytics: e,
            explicit: !0
        })
    },
    jf = () => {
        M.set(`consent`, {
            version: kf,
            timestamp: Date.now(),
            analytics: !0,
            explicit: !1
        })
    },
    Mf = e => {
        e != null && e.requiresCookieConsent ? (M.set(`analyticsConsentRequired`, !0), Of()) : (M.set(`analyticsConsentRequired`, !1), M.get(`consent`) || jf())
    };
var Nf = b({
    get: () => Pf
});
const Pf = ({
    lat: e,
    lon: t
}, n) => {
    let r = M.get(`usedLang`),
        i = n || Z.getZoom();
    return new Promise(n => {
        F(`/reverse/v3/${E(e)}/${E(t)}/${i}?lang=${r}`, {
            ttl: 1e3 * 60 * 60 * 24
        }).then(({
            data: i
        }) => {
            let {
                locality: a,
                suburb: o,
                city: s,
                county: c,
                district: l,
                state: u,
                country: d,
                island: f,
                country_code: p
            } = i, m = c || l || u || ``, h = o || a, g = h && s && h !== s ? `${h}, ${s}` : h || o || s || f || m || u && `${u}, ${d}` || d;
            n({
                lat: e,
                lon: t,
                lang: r,
                region: m,
                country: d || ``,
                cc: p,
                name: g || Nh(e, t),
                nameValid: !!g
            })
        }).catch(i => {
            n({
                lat: e,
                lon: t,
                lang: r,
                name: Nh(e, t)
            })
        })
    })
};
var Ff = b({
    add: () => Rf,
    emitChange: () => Lf,
    enhanceWithCountryCode: () => Yf,
    find: () => Uf,
    findOne: () => Wf,
    getAll: () => Gf,
    hasKey: () => Jf,
    isFav: () => Kf,
    remove: () => Bf,
    toggle: () => qf,
    togglePin: () => Vf,
    update: () => zf
});
const If = e => {
        let {
            type: t,
            title: n
        } = e;
        return !!(pt(e) && n.length > 0 && (t === `fav` || t === `airport` && typeof e.icao == `string` || t === `station` && typeof e.stationId == `string` || t === `webcam` && typeof e.webcamId == `number` || t === `route` && typeof e.route == `string`))
    },
    Lf = () => N.emit(`favChanged`),
    Rf = async e => {
        if (!If(e)) return O(`userFavs`, `Trying to insert invalid fav item: ${JSON.stringify(e)}`), null;
        if (!sp()) return _p({
            action: `addFav`,
            params: e
        }), null;
        let t = await Ba.add(e);
        return Lf(), t
    }, zf = async (e, t) => {
        let n = await Ba.get(e);
        if (n) {
            let r = Date.now(),
                i = w(w(w({}, n), t), {}, {
                    updated: r
                });
            return await Ba.put(e, i), Lf(), e
        } else return null
    }, Bf = async e => {
        await Ba.remove(e), Lf()
    }, Vf = async (e, t, n) => {
        if (!sp()) {
            _p();
            return
        }
        let r = await Ba.get(e);
        r && (n ? await zf(e, {
            [t]: n
        }) : await zf(e, {
            [t]: r[t] ? null : Date.now()
        }))
    }, Hf = e => pt(e) ? t => Dt(e, t) && t.type === `fav` : t => {
        for (let n in e)
            if (e[n] != t[n]) return !1;
        return !0
    }, Uf = async e => {
        let t = await Ba.getAll(),
            n = typeof e == `function` ? e : Hf(e);
        return t.filter(n)
    }, Wf = async e => {
        let t = await Ba.getAll(),
            n = typeof e == `function` ? e : Hf(e);
        return t.find(n)
    }, Gf = async () => sp() ? await Ba.getAll() : [], Kf = async e => {
        let t = await Ba.getAll(),
            n = Hf(e);
        return t.some(n)
    }, qf = async (e, t) => await Kf(e) ? (await Bf((await Uf(e))[0].id), !1) : (await Rf(t), !0), Jf = async e => Ba.hasKey(e), Yf = async e => {
        if (e.cc) return e;
        try {
            let {
                lat: t,
                lon: n,
                id: r
            } = e, {
                cc: i
            } = await Pf({
                lat: t,
                lon: n
            }, 14), a = i || `xx`;
            return await zf(r, {
                cc: a
            }), e.cc = a, e
        } catch (t) {
            return console.error(`Error enhancing fav with country code: ${t}`), e
        }
    }, Xf = async () => {
        let e = (await Ba.getAll()).filter(e => {
            var t;
            return e.type === `station` && ((t = e.stationId) == null ? void 0 : t.startsWith(`radiation-`))
        });
        for (let t of e) await Ba.remove(t.id);
        e.length > 0 && Lf()
    };
N.on(`dependenciesResolved`, async () => {
    await hp() && (await Ba.loadFromCloud(), Lf(), await Xf())
});
var Zf = b({
    appsFlyer: () => null,
    appsFlyerPromise: () => Qf,
    logAppsFlyerProductChange: () => ep,
    withAppsFlyer: () => $f
});
const Qf = Promise.resolve();
async function $f(e) {}

function ep() {}
const tp = () => {
        if (M.get(`startUp`) === `last`) {
            let e = M.get(`mapCoords`);
            e && M.set(`startUpLastPosition`, e)
        }
    },
    np = () => {
        if (M.get(`startUpLastOverlay`)) {
            let e = M.get(`overlay`);
            M.set(`startUpOverlay`, e)
        }
    },
    rp = () => {
        if (M.get(`startUpLastOverlay`)) {
            let e = M.get(`product`);
            M.set(`startUpLastProduct`, e)
        }
    },
    ip = () => {
        M.set(`lastTimezoneOffset`, new Date().getTimezoneOffset(), {
            forceChange: !0
        });
        let e = () => {
            let t = M.get(`notifications`);
            t !== null && (t.usedTimezoneName = Intl.DateTimeFormat().resolvedOptions().timeZone, M.off(`notifications`, e), M.set(`notifications`, t, {
                forceChange: !0
            }))
        };
        e(), M.on(`notifications`, e)
    },
    ap = () => {
        tp(), np(), rp()
    };
M.set(`sessionCounter`, M.get(`sessionCounter`) + 1), window.addEventListener(`beforeunload`, ap), window.addEventListener(`visibilitychange`, ap);
var op = b({
    checkAuth: () => wp,
    emptyAvatar: () => lp,
    getAvatar: () => up,
    getEmail: () => dp,
    getInfo: () => cp,
    getUserId: () => pp,
    getUsername: () => fp,
    handleLoginResponse: () => Ep,
    isLoggedIn: () => sp,
    isLoggedInPromise: () => hp,
    login: () => _p,
    logout: () => xp,
    register: () => vp,
    reloadInfo: () => Tp
});
const sp = () => !!M.get(`user`),
    cp = () => M.get(`user`),
    lp = `https://www.windy.com/img/avatar.jpg`,
    up = () => {
        let e = M.get(`user`);
        return e && e.avatar || lp
    },
    dp = () => {
        let e = M.get(`user`);
        return e && e.email || ``
    },
    fp = () => {
        let e = M.get(`user`);
        return e && e.username || ``
    },
    pp = () => {
        var e;
        let t = cp();
        return (e = t == null ? void 0 : t.id) == null ? 0 : e
    };
let mp = !1;
const hp = () => new Promise(e => {
        M.get(`user`) ? e(!0) : mp ? e(!1) : M.once(`user`, t => e(!!t))
    }),
    gp = e => e.split(``).map(e => String.fromCodePoint(255 - e.charCodeAt(0))).join(``),
    _p = e => {
        if (e) {
            let t = Date.now();
            M.set(`loginAndFinishAction`, w({
                updated: t
            }, e))
        }
        N.emit(`rqstOpen`, `login`)
    },
    vp = () => N.emit(`rqstOpen`, `login`, {
        reason: `register`
    }),
    yp = () => F(`https://account.windy.com/api/logout`, {
        cache: !1
    }),
    bp = new BroadcastChannel(`windy-user-change`);
bp.onmessage = e => {
    console.log(`Reloading due to ${e.data} in another tab`), window.document.location.reload()
};
const xp = async () => {
    M.off(`subscription`, Al);
    try {
        await zd()
    } catch (e) {
        O(`user`, `Error while deactivating device:`, e)
    }
    try {
        await Nd()
    } catch (e) {
        O(`user`, `Error while storing settings:`, e)
    }
    try {
        await yp()
    } catch (e) {
        O(`user`, `Error while deactivating device and cloud sync:`, e)
    }
    El(null), M.remove(`user`), M.remove(`userToken`), M.remove(`consent`);
    try {
        await Za()
    } catch (e) {
        O(`user`, `Error while clearing IndexedDB:`, e)
    }
    bl(`logout`), setTimeout(() => {
        window.location.reload(!0), bp.postMessage(`logout`)
    })
}, Sp = () => {
    let e = M.get(`loginAndFinishAction`);
    if (e) {
        let {
            updated: t,
            action: n,
            params: r
        } = e;
        if (M.remove(`loginAndFinishAction`), Date.now() - t < 5 * 6e4) switch (n) {
            case `addFav`:
                Rf(r);
                break;
            case `alerts-edit`:
            case `favs`:
            case `uploader`:
            case `external-plugins`:
            case `colors`:
                N.emit(`rqstOpen`, n, r);
                break;
            case `openExternalPlugin`:
                N.emit(`rqstOpen`, r.name, r.openParams);
                break
        }
        return bl(`login-finish-action`, n), !0
    } else return !1
}, Cp = () => {
    let e = S ? `favOverlaysMobile` : `favOverlaysDesktop`,
        t = M.get(e);
    if (t && t.some(e => we.includes(e))) {
        let n = t.filter(e => we.includes(e));
        M.set(e, n)
    }
}, wp = async (e, t) => {
    if (e.token && M.set(`userToken`, e.token), e != null && e.auth) {
        let {
            subscriptionInfo: n,
            userInfo: r
        } = e;
        El(n == null ? null : n), M.set(`user`, r), mp = !0, await Pd(), ip(), !Sp() && t ? Mf(e.userInfo) : Al();
        let i = await uf();
        return await Bd(i ? await Ef() : null), i && yf(), Cp(), bl(`user-logged`), !0
    } else return t && Mf(e.userInfo), M.remove(`user`), El(null), bl(`user-logged`, `out`), !1
}, Tp = async () => {
    let e = M.get(`country`);
    e === `xx` && M.once(`country`, e => {
        e !== `xx` && Tp()
    });
    let t = ul(gp(atob(`npyckIqRi9CWkZmQ`))),
        n = {};
    try {
        let r = await F(`https://account.windy.com/api/info`, {
            cache: !1,
            qs: {
                country: e
            },
            customHeaders: w({
                [gp(atob(`iJaRm4bSnIyNmQ==`))]: btoa(gp(`${t.code}?${t.reqQs}`))
            }, n)
        });
        return await wp(r.data, !0) ? r : null
    } catch (e) {
        M.get(`connection`) && (await fn(200), M.get(`connection`) && (O(`user`, `Cannot load user info:`, e), await Nr({
            type: `error`,
            html: `Failed to retrieve account info.`,
            timeout: 5e3
        })));
        let t = M.get(`subscription`);
        return t && Tl(t), null
    }
}, Ep = async (e, t) => {
    if (!e) return;
    let {
        status: n,
        data: r
    } = e;
    if (n !== 200 || !(r != null && r.userInfo)) {
        O(`user`, `Login failed, status=${n}, userInfo=${JSON.stringify(r == null ? void 0 : r.userInfo)}`);
        return
    }
    let {
        userInfo: i,
        authHash: a
    } = r, o = await wp(i, !1);
    o ? (N.emit(`rqstClose`, `login`), await Nr({
        type: `success`,
        html: P.MSG_LOGIN_SUCCESFULL,
        timeout: 3e3
    })) : O(`user`, `Login failed, auth=${o}`), bp.postMessage(o ? `login` : `logout`)
};
Tp();
var Dp = b({
    getArticle: () => om,
    getCapAlertsSummary: () => Kp,
    getCitytileData: () => Bp,
    getElevation: () => tm,
    getHurricanesCount: () => qp,
    getHurricanesList: () => em,
    getLatestJson: () => lm,
    getLiveAlerts: () => rm,
    getMeteogramForecastData: () => zp,
    getMeteogramForecastUrl: () => Rp,
    getNearestPoiItemsUrl: () => Vp,
    getNowPointForecastUrl: () => Ip,
    getObservationPoiUrl: () => Gp,
    getObservationsUrl: () => Wp,
    getPointForecastData: () => Lp,
    getPointForecastUrl: () => Fp,
    getPromo: () => sm,
    getRadarArchiveInfo: () => Qp,
    getRadarCoverage: () => $p,
    getRadarInfo: () => Zp,
    getRadarSatImageUrl: () => im,
    getSatelliteArchiveRangeInfo: () => Xp,
    getSatelliteCompositeInfo: () => Yp,
    getSearchWebcamViewsUrl: () => Np,
    getStaticMapImageUrl: () => nm,
    getTideForecastUrl: () => Hp,
    getTidePoiUrl: () => Up,
    getTimezoneInfo: () => cm,
    getWebcamArchiveUrl: () => jp,
    getWebcamDetailUrl: () => kp,
    getWebcamHourlyArchiveUrl: () => Mp,
    getWebcamMetricsUrl: () => Pp,
    getWebcamsListUrl: () => Ap
});
const Op = async e => K[e].getRefTimeISOFormat(), kp = (e, t) => `/webcams/v2.0/detail/${e}?${Vt({ imageSize: t, lang: M.get(`usedLang`) })}`, Ap = ({
    lat: e,
    lon: t,
    limit: n
}, r = `preview`) => `/webcams/v2.0/list?${Vt({ nearby: `${E(e)},${E(t)}`, lang: M.get(`usedLang`), limit: n, imageSize: r })}`, jp = (e, t, n) => `/webcams/v3.0/archive/${e}?${Vt({ imageSize: t, archiveType: n })}`, Mp = e => `/webcams/v2.0/archive/hourly/${e}`, Np = (e, t) => {
    let n = {
        textQuery: e,
        lang: M.get(`usedLang`)
    };
    return t && (n.lat = E(t.lat), n.lon = E(t.lon)), `https://admin.windy.com/webcams/admin/v1.0/views?${Vt(n)}`
}, Pp = e => `/webcams/ping/${e}`, Fp = async (e, {
    lat: t,
    lon: n,
    step: r,
    interpolate: i
}, a) => {
    let o = await Op(e),
        s = Vt(w(w({}, a), {}, {
            refTime: o,
            step: r,
            interpolate: i ? `true` : void 0,
            extended: U() ? `true` : void 0
        })),
        c = e === `cams` || e === `camsEu` ? `airq` : `point`;
    return `/forecast/${c}/${e}/${c === `airq` ? `v1.0` : `v2.9`}/${E(t)}/${E(n)}?${s}`
}, Ip = async (e, {
    lat: t,
    lon: n
}) => {
    let r = await Op(e);
    return `/forecast/point/now/${e}/v1.0/${E(t)}/${E(n)}?refTime=${r}`
}, Lp = async (e, t, n, r) => F(await Fp(e, t, n), r), Rp = async (e, {
    lat: t,
    lon: n,
    step: r
}, i) => {
    let a = await Op(e),
        o = Vt(w(w({}, i), {}, {
            refTime: a,
            step: r
        }));
    return `/forecast/meteogram/${e}/v1.2/${E(t)}/${E(n)}?${o}`
}, zp = async (e, t, n, r) => F(await Rp(e, t, n), r), Bp = async (e, t) => {
    let n = K[e];
    if (!n) return Promise.resolve(null);
    let {
        modelIdent: r,
        calendar: i
    } = n;
    if (!r) return Promise.resolve(null);
    let a = await Op(e);
    if (!a) return Promise.resolve(null);
    let o = {
        labelsVersion: `v2.1`,
        step: U() ? 1 : 3,
        refTime: a,
        hours: i == null ? void 0 : i.calendarHours
    };
    return F(`/citytile/v1.0/${r}/${t}`, {
        qs: o
    })
}, Vp = (e, {
    lat: t,
    lon: n
}, r) => `/pois/v2/${e}/${E(t)}/${E(n)}${r ? `?` + Vt(r) : ``}`, Hp = ({
    lat: e,
    lon: t
}) => `/tides/v1.0/tides/${E(e)}/${E(t)}`, Up = e => `/tides/v1.0/tides/${e}`, Wp = (e, t, n, r = 1) => `/obs/measurement/v3/${e}/${t}/${n}/${r}`, Gp = (e, t) => `/pois/v2/${e}/${t}`, Kp = ({
    lat: e,
    lon: t
}, n = `hp`) => F(`/capalerts/${E(e)}/${E(t)}`, {
    qs: {
        source: n,
        lang: M.get(`usedLang`),
        maxCount: 6
    }
}), qp = () => F(`/tc/v2/storms/active/count`), Jp = () => `noCacheFragment=${new Date().toISOString().replace(/.*T(\d+):(\d+).*/, `$1$2`)}`, Yp = () => F(`https://sat.windy.com/satellite/composite.json?${Jp()}`), Xp = () => F(`https://sat.windy.com/satellite/archive/range.json?${Jp()}`), Zp = () => F(`https://rdr.windy.com/radar2/composite/minifest2.json?${Jp()}`), Qp = () => F(`https://rdr.windy.com/radar2/archive/composite/minifest2.json?${Jp()}`), $p = () => F(`https://rdr.windy.com/radar2/composite/coverage.json`), em = () => F(`/tc/v2/storms`), tm = (e, t, n) => F(`/services/elevation/${E(e)}/${E(t)}`, n), nm = e => `https://node-s.windy.com/imaker/map${e.bounds ? `?bbox=${e.bounds}` : `?c=${e.lat},${e.lon}&z=${e.zoom}&size=${e.size}`}`, rm = ({
    lat: e,
    lon: t
}) => {
    let n = M.get(`usedLang`),
        r = R.distance.metric;
    return F(`/notif/v1/live-alerts/${E(e)}/${E(t)}`, {
        qs: {
            distance: r,
            userLanguage: n
        }
    })
}, im = (e, {
    lat: t,
    lon: n,
    w: r,
    h: i,
    format: a,
    satMode: o,
    radarMode: s
}) => {
    let c = Vt({
        lat: t,
        lon: n,
        w: r,
        h: i,
        format: a
    });
    return `https://node.windy.com/widget/${e}/${e === `satellite` ? o || `blue` : s || `default`}/image?${c}`
}, am = ({
    lat: e,
    lon: t
}) => {
    let n = U() ? `premium` : `free`,
        r = sp() ? `signed-in` : `signed-out`,
        i = M.get(`userInterests`),
        a = {
            language: M.get(`usedLang`),
            country: M.get(`country`),
            target: `index`,
            device: ve,
            version: `50.1.2`,
            platform: _e,
            lat: e,
            lon: t,
            userStatus: n,
            loginStatus: r
        };
    return i.length > 0 && (a.userInterests = i.join(`,`)), a
}, om = async e => F(`/articles/startup/article`, {
    qs: am(e)
}), sm = async (e, t) => F(`/articles/startup/promotion`, {
    qs: w(w({}, am(e)), {}, {
        forceId: t
    })
}), cm = (e, t) => F(`/services/v1/timezone/${E(e.lat)}/${E(e.lon)}?ts=${t}`), lm = () => null, Y = {
    "gl-particles": new sd({
        ident: `gl-particles`
    }),
    isolines: new sd({
        ident: `isolines`
    }),
    accumulations: new vd({
        langFiles: [`accumulations`],
        ident: `accumulations`,
        logUsage: !1
    }),
    "day-switcher": new vd({
        ident: `day-switcher`,
        logUsage: !1
    }),
    "cap-alerts": new vd({
        ident: `cap-alerts`,
        singleclickPriority: S ? void 0 : `low`,
        logUsage: !1
    }),
    "avalanche-danger": new vd({
        ident: `avalanche-danger`,
        singleclickPriority: S ? void 0 : `low`,
        logUsage: !1
    }),
    radar: new q({
        ident: `radar`,
        title: `RADAR`,
        logUsage: !1,
        attachPoint: S ? `[data-plugin="bottom-controls-mobile"]` : `[data-plugin="bottom-controls-desktop"]`,
        displayURLAndTitle: () => {},
        needsPluginRoot: !0,
        beforeLoad() {
            Zp(), Qp(), $p()
        }
    }),
    "radar-plus": new q({
        ident: `radar-plus`,
        title: `RADAR_PLUS`,
        router: `/radarPlus`,
        langFiles: [`radsat`],
        attachPoint: S ? `[data-plugin="bottom-controls-mobile"]` : `[data-plugin="bottom-controls-desktop"]`,
        displayURLAndTitle: () => {},
        needsPluginRoot: !0,
        beforeLoad() {
            Qp(), Zp(), Yp(), Xp()
        }
    }),
    detail: new q({
        ident: `detail`,
        className: S ? `plugin-mobile-bottom-red` : `plugin-desktop-bottom`,
        pane: `bottom`,
        attachPoint: S ? le : `[data-plugin="bottom-pane"]`,
        singleclickPriority: S ? void 0 : `high`,
        disableMobilePicker: !0,
        needsPluginRoot: !0,
        beforeLoad(e) {
            Lp(e.product || `ecmwf`, w({
                step: U() && M.get(`detail1h`) ? 1 : 3
            }, e), {
                source: `detail`
            })
        },
        path: `/:lat/:lon/:model?/:display?`,
        router: (() => {
            let e = Object.keys(K).sort((e, t) => t.length - e.length).join(`|`);
            return RegExp(`^\\/(?<lat>-?\\d+\\.\\d+)/(?<lon>-?\\d+\\.\\d+)(\\/(?<product>(${e})))?(\\/(?<display>(table|meteogram|airgram|waves|wind|airq)))?`)
        })(),
        onRouteMatch: (e, t) => {
            var n;
            let r = t == null || (n = t.model) == null ? void 0 : n.split(`:`)[1],
                i = r in K ? r : void 0,
                a = t != null && t.hrTimestamps ? t == null ? void 0 : t.hrTimestamps.split(`,`).map(e => e * T) : void 0,
                o = parseFloat(e.lat),
                s = parseFloat(e.lon);
            return w(w({}, e), {}, {
                lat: o,
                lon: s,
                timestamps: a,
                name: t == null ? void 0 : t.name,
                moveToTimestamp: !!(t != null && t.moveToTimestamp),
                product: i == null ? e.product : i
            })
        }
    }),
    station: new q({
        ident: `station`,
        pane: `bottom`,
        disableMobilePicker: !0,
        addMobileSlider: !!S,
        closeOnSwipeDown: !0,
        langFiles: [`station`],
        className: S ? `plugin-mobile-bottom-red` : `plugin-desktop-bottom`,
        attachPoint: S ? le : `[data-plugin="bottom-pane"]`,
        router: RegExp(`\\/station\\/(?<id>[^/]+)(\\/(?<view>(basic|wind|compare)))?`, `g`),
        path: `/station/:id/:view?`
    }),
    "nearest-stations": new q({
        ident: `nearest-stations`,
        attachPoint: `[data-plugin="nearest-stations"]`,
        className: `drop-down-window left boxshadow dark-content`,
        pane: `nearest`
    }),
    "nearest-webcams": new q({
        ident: `nearest-webcams`,
        attachPoint: `[data-plugin="nearest-webcams"]`,
        className: `boxshadow dark-content`,
        langFiles: [`webcams`],
        pane: `nearest`
    }),
    "nearest-airq": new q({
        ident: `nearest-airq`,
        className: `drop-down-window left boxshadow dark-content`,
        attachPoint: `[data-plugin="nearest-airq"]`,
        pane: `nearest`
    }),
    "nearest-webcams-mobile": new q({
        ident: `nearest-webcams-mobile`,
        className: `plugin-mobile-bottom-slide top-border auto-height dark-content`,
        addMobileSlider: !0,
        noHeader: !0,
        closeOnSwipeDown: !0,
        langFiles: [`webcams`],
        pane: `nearest`
    }),
    "rhpane-top": new q({
        ident: `rhpane-top`,
        neverClose: !0,
        logUsage: !1,
        attachPoint: `[data-plugin="rhpane-top"]`
    }),
    rhbottom: new q({
        ident: `rhbottom`,
        neverClose: !0,
        logUsage: !1,
        attachPoint: `[data-plugin="rhbottom"]`,
        langFiles: [`menu`]
    }),
    "poi-libs": new wd({
        ident: `poi-libs`
    }),
    sounding: new J({
        ident: `sounding`,
        langFiles: [`sounding`],
        title: `SOUNDING`,
        disableMobilePicker: !0,
        addMobileSlider: !1,
        singleclickPriority: `high`,
        className: x ? `plugin-mobile-bottom-red` : `plugin-rhpane top-border`,
        pane: x ? `bottom` : `rhpane`,
        router: `/sounding/:lat/:lon`,
        needsPluginRoot: !0
    }),
    radiosonde: new J({
        ident: `radiosonde`,
        langFiles: [`sounding`],
        title: `RADIOSONDE`,
        disableMobilePicker: !0,
        addMobileSlider: !0,
        className: x ? `plugin-mobile-bottom-red` : `plugin-rhpane top-border`,
        pane: x ? `bottom` : `rhpane`,
        router: `/radiosonde/:id`,
        needsPluginRoot: !0
    }),
    articles: new J({
        ident: `articles`,
        title: `MENU_NEWS`,
        langFiles: [`articles`],
        disableMobilePicker: !0,
        noHeader: !0,
        closeOnSwipeDown: !1,
        router: `/articles/:id?`
    }),
    settings: new J({
        ident: `settings`,
        langFiles: [`settings`, `notifications`],
        title: `MENU_SETTINGS`,
        router: `/settings`,
        useSEOurl: !0
    }),
    favs: new J({
        ident: `favs`,
        langFiles: [`favs`, `notifications`],
        title: `MY_FAVS`,
        closeOnSwipeDown: !1,
        router: `/favs`,
        useSEOurl: !0
    }),
    "alerts-edit": new J({
        ident: `alerts-edit`,
        langFiles: [`alerts`, `livealerts`, `notifications`, `onboarding`],
        title: `EDIT_ALERT`,
        closeOnSwipeDown: !1,
        closesOnSwipeRight: !1,
        router: `/alerts-edit/:id?`
    }),
    alerts: new J({
        ident: `alerts`,
        langFiles: [`notifications`, `alerts`, `favs`, `livealerts`],
        title: `MY_ALERTS`,
        closeOnSwipeDown: !1,
        router: /^\/alerts(?:\/\S+)?/,
        path: `/alerts`,
        useSEOurl: !0
    }),
    colors: new J({
        ident: `colors`,
        title: `S_COLORS`,
        closeOnSwipeDown: !1,
        router: `/colors`
    }),
    hurricanes: new J({
        ident: `hurricanes`,
        langFiles: [`hurricanes`],
        title: `HURR_TRACKER`,
        attachPoint: S ? `[data-plugin="bottom-below-controls-mobile"]` : le,
        className: S ? `plugin-mobile-bottom-small` : `plugin-rhpane top-border`,
        pane: S ? `small-bottom-bottom` : `rhpane`,
        disableMobilePicker: !0,
        useSEOurl: !0,
        router: `/hurricanes/:id?`
    }),
    debug: new J({
        ident: `debug`,
        router: `/debug`
    }),
    info: new J({
        ident: `info`,
        langFiles: [`info`, `products`],
        title: `ABOUT_DATA`,
        router: `/info`
    }),
    "cap-alerts-detail": new J({
        ident: `cap-alerts-detail`,
        title: `WX_WARNINGS`,
        router: `/cap-alert/:lat/:lon`
    }),
    "avalanche-danger-detail": new J({
        ident: `avalanche-danger-detail`,
        title: `Avalanche Bulletin`,
        router: `/avalanche-bulletin/:regionId`
    }),
    menu: new q({
        ident: `menu`,
        keyboard: !0,
        closesOnSwipeRight: !0,
        className: `plugin-rhpane dark-content top-border`,
        langFiles: [`menu`, `menudesc`, `products`],
        pane: `rhpane`,
        title: `MENU`,
        router: /^\/(menu|overlays|tools|pois|live)$/,
        path: `/menu`,
        useSEOurl: !0,
        beforeLoad() {
            qp()
        }
    }),
    airport: new J({
        ident: `airport`,
        langFiles: [`webcams`, `airport`],
        closeOnSwipeDown: !1,
        closesOnSwipeRight: !1,
        router: RegExp(`^\\/((airport\\/(?<id>\\S+))|(?<icao>[a-zA-Z]{4}))$`, ``),
        onRouteMatch: e => {
            var t;
            return {
                id: (t = e.id) == null ? e.icao : t
            }
        },
        path: `/airport/:id`
    }),
    share: new q({
        ident: `share`,
        noHeader: !0,
        className: x ? `plugin-mobile-bottom-slide top-border auto-height fg-gray` : `plugin-popup`
    }),
    "report-issue": new J({
        ident: `report-issue`,
        langFiles: [`reportissue`],
        title: `REPORT_ISSUE`,
        router: `/report-issue`
    }),
    multimodel: new q({
        ident: `multimodel`,
        className: x ? `plugin-mobile-bottom-slide top-border` : ``,
        addMobileSlider: !0,
        router: `/multimodel/:lat/:lon`
    }),
    login: new q({
        ident: `login`,
        pane: `center`,
        langFiles: [`register`],
        className: x ? `plugin-mobile-bottom-slide top-border dark-content` : `plugin-popup dark-content`,
        addMobileSlider: !!x,
        keyboard: !0,
        router: RegExp(`^\\/(?<reason>register|login)$`, ``),
        path: `/:reason?`
    }),
    rplanner: new q({
        ident: `rplanner`,
        pane: `bottom`,
        className: S ? `detail plugin-mobile-bottom-red` : `detail plugin-desktop-bottom`,
        disableMobilePicker: !0,
        singleclickPriority: S ? void 0 : `high`,
        attachPoint: S ? le : `[data-plugin="bottom-pane"]`,
        title: `RPLANNER`,
        langFiles: [`distance`],
        keyboard: !0,
        path: `/route-planner/:view?/:coords?/:id?`,
        router: RegExp(`^\\/(?:distance|route-planner)\\/?(?<view>vfr|ifr|car|boat|airgram|elevation)?\\/?(?<coords>[^/]+)(?:\\/id:(?<id>\\S+))?`, ``)
    }),
    upload: new q({
        ident: `upload`,
        router: S ? RegExp(`^\\/(?:upload|uploader)\\/(?<id>\\S+)$`, ``) : `/upload/:id`,
        path: `/upload/:id`,
        pane: S ? `small-bottom-bottom` : void 0,
        className: S ? `plugin-mobile-bottom-small` : `top-border`,
        attachPoint: S ? `[data-plugin="bottom-below-controls-mobile"]` : le
    }),
    uploader: new J({
        ident: `uploader`,
        title: `Upload KML, GPX or geoJSON file`,
        router: `/uploader/:id?`
    }),
    subscription: new q({
        ident: `subscription`,
        className: x ? `dark-content plugin-mobile-bottom-slide top-border` : `dark-content plugin-popup`,
        keyboard: !0,
        noHeader: !0,
        addMobileSlider: !!x,
        langFiles: [`subscription`],
        pane: `center`,
        title: `SUBSCRIPTION`,
        onclosed() {
            N.emit(`checkPendingSubscriptions`)
        },
        router: `/subscription`,
        onRouteMatch: () => ({
            subsSource: `url`
        })
    }),
    "pending-subscription": new q({
        ident: `pending-subscription`,
        langFiles: [`subscription`],
        className: `top-message bg-orange fg-white`,
        router: `/pending-subscription`
    }),
    "delete-info": new J({
        ident: `delete-info`,
        langFiles: [`menu`],
        router: `/delete-info`
    }),
    webcams: new J({
        ident: `webcams`,
        langFiles: [`webcams`],
        title: `POI_CAMS`,
        router: `/webcams`,
        noHeader: !0,
        useSEOurl: !0
    }),
    "webcams-detail": new J({
        ident: `webcams-detail`,
        langFiles: [`webcams`],
        beforeLoad(e) {
            !this.isLoaded && !this.loading && F(kp(e.id, S ? `mobile` : `full`))
        },
        router: RegExp(`\\/webcams\\/(?<id>\\d+)$`, ``),
        path: `/webcams/:id`,
        noHeader: !0
    }),
    "webcams-add": new J({
        ident: `webcams-add`,
        langFiles: [`webcams`],
        title: `D_MISSING_CAM`,
        router: `/webcams/add`
    }),
    "webcams-edit": new J({
        ident: `webcams-edit`,
        langFiles: [`webcams`],
        title: `Edit webcam`,
        router: `/webcams/edit/:id`
    }),
    "webcams-remove": new J({
        ident: `webcams-remove`,
        langFiles: [`webcams`],
        title: `Remove webcam`,
        router: `/webcams/remove/:id`
    }),
    search: new q({
        ident: `search`,
        className: `bg-gray-dark dark-content`,
        keyboard: !0,
        pane: `top`,
        attachPoint: `[data-plugin="search"]`,
        langFiles: [`search`, `products`],
        beforeLoad() {
            let e = Kt(`[data-ref="mainSearchInput"]`);
            e == null || e.focus()
        }
    }),
    "search-input": new q({
        ident: `search-input`,
        attachPoint: `[data-plugin="search-input"]`,
        neverClose: !0
    }),
    "search-my-location": new q({
        ident: `search-my-location`,
        className: `bg-gray-dark dark-content`,
        pane: `top`,
        attachPoint: `[data-plugin="search"]`,
        langFiles: [`picker`],
        closeOnClick: `outside`
    }),
    consent: new q({
        ident: `consent`,
        className: x ? `dark-content plugin-mobile-bottom-red` : `dark-content plugin-popup`,
        langFiles: [`consent`],
        disableMobilePicker: !0
    }),
    "map-selector": new q({
        ident: `map-selector`,
        attachPoint: S ? `[data-plugin="bottom-below-controls-mobile"]` : `[data-plugin="below-rhbottom"]`,
        addMobileSlider: !1,
        closeOnSwipeDown: !1
    }),
    "perf-overlay": new q({
        ident: `perf-overlay`
    }),
    "sun-moon": new q({
        ident: `sun-moon`,
        className: S ? `plugin-mobile-bottom-small dark-content` : ``,
        pane: `embedded`,
        attachPoint: S ? `[data-plugin="bottom-below-controls-mobile"]` : `[data-plugin="above-rhbottom"]`,
        langFiles: [`sunmoon`]
    }),
    "wind-trajectories": new q({
        ident: `wind-trajectories`,
        className: S ? `plugin-mobile-bottom-small dark-content` : ``,
        pane: `embedded`,
        attachPoint: S ? `[data-plugin="bottom-below-controls-mobile"]` : `[data-plugin="above-rhbottom"]`
    }),
    "external-plugins": new J({
        ident: `external-plugins`,
        title: `Install Windy plugin`,
        router: `/plugins`
    }),
    "progress-bar": new vd({
        ident: `progress-bar`,
        className: `plugin-bottom dark-content`,
        logUsage: !1
    }),
    picker: new wd({
        ident: `picker`
    }),
    "picker-mobile": new q({
        ident: `picker-mobile`,
        className: `plugin-mobile-transparent-top`,
        langFiles: [`picker`],
        pane: `top`
    }),
    "mobile-calendar": new vd({
        ident: `mobile-calendar`,
        className: `plugin-bottom`,
        logUsage: !1
    }),
    "mobile-ui": new q({
        ident: `mobile-ui`,
        neverClose: !0,
        logUsage: !1,
        attachPoint: `[data-plugin="mobile-ui"]`
    }),
    onboarding: new q({
        ident: `onboarding`,
        langFiles: [`onboarding`],
        className: x ? `plugin-mobile-bottom-slide dark-content` : `plugin-popup dark-content`
    }),
    "location-permission": new q({
        ident: `location-permission`,
        langFiles: [`onboarding`],
        pane: `center`,
        className: `dark-content`
    }),
    distance: new q({
        ident: `distance`,
        title: `MENU_DISTANCE`,
        keyboard: !1,
        disableMobilePicker: !0,
        className: `plugin-mobile-transparent-top`,
        langFiles: [`distance`],
        pane: `top`,
        router: `/distance/:coords?`
    }),
    "fav-layers": new q({
        ident: `fav-layers`,
        attachPoint: `[data-plugin="fav-layers"]`,
        langFiles: [`menu`],
        className: `size-m window transparent-window rh-bottom-pin dark-content`,
        closeOnClick: `outside`
    }),
    contextmenu: new q({
        ident: `contextmenu`,
        className: `drop-down-window dark-content`,
        closeOnClick: !0,
        attachPoint: `[data-plugin="map-container"]`,
        needsPluginRoot: !0
    }),
    globe: new wd({
        ident: `globe`,
        title: `GLOBE`,
        neverClose: !0,
        logUsage: !0,
        attachPoint: `[data-plugin="map-container"]`
    }),
    "startup-weather": new yd({
        ident: `startup-weather`,
        attachPoint: `[data-plugin="startup-weather"]`,
        className: void 0
    }),
    "startup-articles": new yd({
        ident: `startup-articles`
    }),
    "startup-promos": new yd({
        ident: `startup-promos`,
        langFiles: [`startuppromos`]
    }),
    "startup-live-alerts": new yd({
        ident: `startup-live-alerts`
    }),
    "startup-pin2hp": new yd({
        ident: `startup-pin2hp`,
        attachPoint: `[data-plugin="startup-pin2hp"]`,
        logUsage: !0
    }),
    "startup-debug": new yd({
        ident: `startup-debug`,
        neverClose: !0,
        attachPoint: `[data-plugin="startup-debug"]`,
        router: `/startup-debug/:id?`
    }),
    "embed-ui": new q({
        ident: `embed-ui`,
        neverClose: !0,
        attachPoint: `[data-plugin="embed-ui"]`
    }),
    "developer-mode": new q({
        ident: `developer-mode`,
        keyboard: !0,
        className: `top-border dark-content`,
        title: `Developer mode`,
        router: RegExp(`^\\/(dev|developer-mode)(?:\\/(?<url>.+))?$`, ``),
        path: `/developer-mode`
    }),
    "watch-faces": new q({
        ident: `watch-faces`,
        pane: `rhpane`,
        langFiles: [`watchface`],
        addMobileSlider: !0,
        className: `plugin-mobile-bottom-slide top-border`
    }),
    "app-review-dialog": new q({
        ident: `app-review-dialog`,
        langFiles: [`appreview`],
        pane: `center`,
        className: `fg-white`
    }),
    widgets: new q({
        ident: `widgets`,
        pane: `rhpane`,
        langFiles: [`widgetspromo`],
        addMobileSlider: !0,
        router: `/widgets`,
        className: `plugin-mobile-bottom-slide top-border dark-content`
    }),
    garmin: new q({
        ident: `garmin`,
        pane: `rhpane`,
        langFiles: [`garmin`],
        addMobileSlider: !0,
        router: `/garmin`,
        className: `plugin-mobile-bottom-slide top-border dark-content`
    }),
    "garmin-edge": new q({
        ident: `garmin-edge`,
        pane: `rhpane`,
        langFiles: [`garmin`],
        addMobileSlider: !0,
        router: `/garmin-edge`,
        className: `plugin-mobile-bottom-slide top-border dark-content`
    })
};
var um = b({
    description: () => bm,
    getURL: () => Cm,
    reset: () => Lm,
    resetTitle: () => Mm,
    setSearch: () => Im,
    setTitle: () => Fm,
    setUrl: () => Pm
});
const dm = Kt(`meta[name="description"]`) || {},
    fm = dm && dm.content,
    pm = Kt(`link[rel="canonical"]`),
    mm = Date.now();
let hm, gm = ``,
    _m = null,
    vm = !1,
    ym = null;
const bm = e => {
        dm.content = e
    },
    xm = () => _m ? `${Di(M.get(`usedLang`))}-${Ei(_m)}` : ``,
    Sm = e => `${e}${hm ? `?` + hm : ``}`,
    Cm = () => `${`${window.location.origin}${gm && gm.startsWith(`/`) ? `` : `/`}`}${Sm(gm)}`,
    wm = () => {
        if (gm === ``) {
            let e = M.get(`overlay`);
            return e === `wind` || !_m ? `` : `${xm()}-${e}`
        } else if (ym) return zt(`${Di(M.get(`usedLang`))}${Ti(ym)}`, gm);
        return gm
    };
let Tm = ``,
    Em = ``,
    Dm = null;
const Om = yt(() => {
    if (!(Tm === gm && Em === hm && Dm === ym)) {
        {
            let e = wm(),
                t = {
                    url: gm,
                    search: hm
                },
                n = Sm(e);
            gm === Tm ? window.history.replaceState(t, ``, n) : (window.history.pushState(t, ``, Sm(e)), pm.href = zt(`https://www.windy.com`, gm))
        }
        Tm = gm, Em = hm, Dm = ym
    }
}, 200);
let km;

function Am() {
    if (!km) return;
    let e = M.get(`mapCoords`),
        t = [E(e.lat), E(e.lon), e.zoom],
        n = M.get(`timestamp`),
        r = M.get(`calendar`),
        i;
    if (r && Math.abs(mm - n) > 864e5) {
        let e = hn(n, `$1-$2-$3-$4`);
        t.unshift(e)
    }
    Is[km.overlay].hideFromURL || t.unshift(km.overlay), km.level !== `surface` && t.unshift(km.level), !/^ecmwf/.test(km.product) && Qu(km.overlay) && t.unshift(km.product), M.get(`isolinesOn`) && (i = M.get(`isolinesType`)) && t.push(`i:` + i), (i = M.get(`pois`)) !== `empty` && t.push(`p:` + i);
    let a = M.get(`pickerLocation`);
    a && t.push(`m:` + ct(a)), hm = t.join(`,`), Om()
}
const jm = yt(Am, 200 * .25);

function Mm() {
    if (vm) return;
    let e = M.get(`overlay`),
        t = Is[e].getName.call(Is[e]);
    e === `wind` ? (_m = null, document.title = `Windy: ${P.TITLE}`) : (_m = t, document.title = `Windy: ${t}`)
}
let Nm = null;
const Pm = (e, t, n) => {
        let r = Y[e];
        r && (gm = r.getPluginUrl(t), ym = n ? `-${n}` : null, Nm = e, Om())
    },
    Fm = e => {
        _m = e, document.title = `Windy: ${e}`, vm = !0
    },
    Im = e => {
        e && (hm = e, Om())
    },
    Lm = e => {
        e && e !== Nm || (vm = !1, dm && (dm.content = fm), gm = ``, ym = null, Am(), Mm(), Om())
    };
N.on(`paramsChanged`, e => {
    km = e, jm()
}), M.on(`mapCoords`, jm), M.on(`pickerLocation`, jm), M.on(`pois`, jm), M.on(`overlay`, Mm), M.on(`usedLang`, Mm);
var Rm = b({
    getNetworkInformation: () => qm,
    sentErrors: () => Hm,
    suspendErrorLogging: () => Gm
});
const zm = Date.now(),
    Bm = {};
let Vm = `1_loading`;
N.once(`dependenciesResolved`, () => {
    Vm = `2_dependenciesResolved`
}), N.once(`redrawFinished`, () => {
    Vm = `3_redrawFinished`
});
const Hm = [];
let Um = 0,
    Wm = !1;
const Gm = () => {
    Wm = !0
};

function Km(e, t) {
    return e.toString().substring(0, t).toLowerCase().replace(/[^\w\s-]/g, ``).replace(/[\s_-]+/g, `-`).replace(/^-+|-+$/g, ``)
}

function qm() {
    var e;
    let t = (e = window.navigator) == null ? void 0 : e.connection;
    if (typeof t == `object` && t) {
        let {
            downlink: e,
            downlinkMax: n,
            effectiveType: r,
            rtt: i,
            saveData: a,
            type: o
        } = t;
        return {
            downlink: e,
            downlinkMax: n,
            effectiveType: r,
            rtt: i,
            saveData: a,
            type: o
        }
    }
}
async function Jm(e, t, n, r, i) {
    if (!(window.top !== window.self || Wm) && !(++Um > 1e3) && !(r && r instanceof qe && r.status === 0) && M.get(`connection`) && !/UCBrowser/i.test(window.navigator.userAgent)) try {
        let a = Date.now(),
            o, s, c = {};
        switch (e) {
            case `error`: {
                let e = t,
                    n = e.filename;
                if (s = e.message, c = {
                        script: n && n.replace(/.*\//, ``),
                        line: e.lineno,
                        col: e.colno,
                        stack: e.error && e.error.stack
                    }, /leaflet-gl\.js$/.test(n || ``)) {
                    let t = Ym(e);
                    t && (s = t.msg, c.extra = t.customPayload), c.module = `leafletGl`
                }
            }
            break;
            case `unhandledRejection`: {
                let e = t,
                    n = e.sourceURL || e.filename;
                s = e.message, c = {
                    script: n && n.replace(/.*\//, ``),
                    line: e.line || e.lineNumber,
                    col: e.column || e.columnNumber,
                    stack: e.stack
                }
            }
            break;
            case `customLogError`:
                s = t, c = w({
                    module: n,
                    stack: r && `stack` in r && r.stack
                }, i || {});
                break
        }
        if (!s) return;
        let l = Km(s, 60),
            u = Km(s, 20),
            d = 0;
        if (d = u in Bm ? Bm[u]++ : Bm[u] = 0, d % 10 || d > 50) return;
        d > 0 && (s = `${s} (repeated)`, o = d);
        let f = w({
            errorID: l,
            overlay: M.get(`overlay`),
            runningPhase: document.hidden ? `documentIsHidden` : Vm,
            timestamp: a,
            runningMinutes: Math.round((a - zm) / et),
            type: e,
            msg: s,
            repeated: o,
            url: window.location.href,
            ver: he,
            target: ge,
            platform: _e,
            device: ve,
            latestBcast: Fn(a),
            network: qm()
        }, c);
        await fetch(`https://node.windy.com/sedlina/errors`, {
            body: JSON.stringify(f),
            headers: {
                "Content-Type": `application/json; charset=utf-8`
            },
            method: `POST`
        }), Hm.push(f)
    } catch (e) {
        console.error(`onError handler, that should handle 7 report errors, failed as well...`, e)
    }
}
window.addEventListener(`error`, e => Jm(`error`, e)), window.addEventListener(`unhandledrejection`, ({
    reason: e
}) => {
    e instanceof ReferenceError && Jm(`unhandledRejection`, e)
}), document.addEventListener(`windyCustomError`, ({
    detail: e
}) => {
    let {
        moduleName: t,
        msg: n,
        errorObject: r,
        additionalInfo: i
    } = e;
    Jm(`customLogError`, n, t, r, i)
});

function Ym(e) {
    let t = null;
    try {
        let n = JSON.parse(e.error.message),
            r = n.message;
        if (!r) return t;
        let i = n.type,
            a = {
                statusMessage: n.statusMessage,
                type: i
            };
        /webgl/i.test(r) && (i === `webglcontextcreationerror` ? a.webglVersion = `unknown` : a.webglVersion = kv.context), t = {
            msg: r,
            customPayload: a
        }
    } catch (e) {}
    return t
}
var Xm = b({
        ExternalSveltePlugin: () => Zm
    }),
    Zm = class extends q {
        constructor(e, {
            desktopUI: t,
            title: n,
            mobileUI: r,
            desktopWidth: i,
            routerPath: a,
            listenToSingleclick: o,
            addToContextmenu: s,
            url: c,
            version: l
        }) {
            super(e), C(this, `mobileConfig`, {
                fullscreen: {
                    className: `plugin-mobile-bottom-slide top-border`,
                    pane: `fullscreen-mobile`,
                    addMObileSliders: !0
                },
                small: {
                    className: `plugin-mobile-bottom-small dark-content`,
                    attachPoint: `[data-plugin="bottom-below-controls-mobile"]`,
                    pane: `small-bottom-bottom`
                }
            }), C(this, `desktopConfig`, {
                rhpane: {
                    className: `plugin-rhpane top-border`,
                    pane: `rhpane`
                },
                embedded: {
                    className: `fg-white bg-gray-dark rounded-box`,
                    attachPoint: `[data-plugin="above-rhbottom"]`,
                    pane: `embedded`
                }
            }), C(this, `tabletConfig`, {
                rhpane: this.desktopConfig.rhpane,
                embedded: this.mobileConfig.small
            }), C(this, `widthOfRhPane`, void 0), C(this, `version`, void 0), C(this, `listenToSingleclick`, void 0), C(this, `addToContextmenu`, void 0), this.location = c;
            let {
                className: u,
                attachPoint: d,
                pane: f,
                addMObileSliders: p
            } = x ? this.mobileConfig[r] : Fe ? this.tabletConfig[t] : this.desktopConfig[t];
            this.className = `${u} dark-content`, this.pane = f, this.attachPoint = d || this.attachPoint, this.widthOfRhPane = i || 400, this.title = n || `External plugin`, this.logUsage = !0, this.router = a ? zt(`/plugin`, a) : void 0, this.path = this.router, this.listenToSingleclick = o, this.singleclickPriority = o ? `high` : void 0, this.addToContextmenu = s, this.version = l, this.addMobileSlider = p == null ? !1 : p, this.closeOnSwipeDown = !1, this.closesOnSwipeRight = this.pane === `rhpane` && Fe
        }
        async open({
            params: e,
            disableOpeningAnimation: t,
            qs: n
        }) {
            var r = () => super.open,
                i = this;
            Gm();
            try {
                let {
                    data: a
                } = await F(`/plugins/list`), o = a.find(e => e.name === i.ident);
                return o && o.status === `published` ? i.hasNewerVersion(o.version) && await i.showConfirmationWindow() ? (await i.uninstallPlugin(), await $m(zt(o.url, `plugin.min.js`), `gallery`), N.emit(`rqstOpen`, o.name)) : r().call(i, {
                    params: e,
                    disableOpeningAnimation: t,
                    qs: n
                }) : o && o.status === `unpublished` ? (Nr({
                    type: `error`,
                    html: St(P.MSG_EXTERNAL_PLUGIN_UNPUBLISHED, {
                        title: i.title
                    })
                }), await i.uninstallPlugin(), !1) : r().call(i, {
                    params: e,
                    disableOpeningAnimation: t,
                    qs: n
                })
            } catch (a) {
                return r().call(i, {
                    params: e,
                    disableOpeningAnimation: t,
                    qs: n
                })
            }
        }
        hasNewerVersion(e) {
            return e.localeCompare(this.version, void 0, {
                numeric: !0,
                sensitivity: `base`
            }) > 0
        }
        showConfirmationWindow() {
            return new Promise(e => {
                let t = new kr({
                    ident: `message-plugin-update-available`,
                    className: `top-message top-border bg-gray-dark lh-15`,
                    html: `<div style="width: 100%">
                  <p style="text-align: center">
                    ${St(P.MSG_EXTERNAL_PLUGIN_UPDATE_AVAILABLE, { title: this.title })}
                  </p>
                  <footer style="display: flex; justify-content: center">
                    <button class="button button--transparent" id="button-update-no">
                      ${P.NO}
                    </button>
                    <button class="button button--transparent" id="button-update-yes">
                      ${P.YES}
                    </button>
                  </footer>
                </div>`
                }).open();
                document.getElementById(`button-update-yes`).onclick = () => {
                    n(!0)
                }, document.getElementById(`button-update-no`).onclick = () => {
                    n(!1)
                };

                function n(n) {
                    t.close(), e(n)
                }
            })
        }
        getDayDiff(e) {
            let t = (new Date().getTime() - new Date(e).getTime()) / (1440 * 60 * 1e3);
            return Math.floor(t)
        }
        async uninstallPlugin() {
            var e = this;
            N.emit(`rqstClose`, e.ident), await Xa.remove(e.ident)
        }
        getCss() {
            let e = `.on${this.ident}`,
                t = `#plugin-${this.ident}`,
                n = this.widthOfRhPane;
            switch (`${x ? `mobile` : `desktop`}-${this.pane}`) {
                case `desktop-rhpane`:
                    return `
${t} {
    width: ${n}px;
}
${t} .plugin__content {
    padding: 25px 25px 100px 25px;
}
${e} .right-border {
    right: ${n}px;
}
${e} #logo-wrapper {
    left: ${n / 2}px;
}
${e} #map-container {
    transition-delay: .2s;
    transform: translateX(-${n / 2}px)
}`;
                case `desktop-embedded`:
                    return `
${t} {
    position: relative;
    pointer-events: auto;
    width: 320px;
    margin: 0 8px 15px 0;
    padding-right: 40px;
    max-height: 200px !important;
}

${t} > .closing-x {
    display: block;
    background: none;
    font-size: 20px;
    top: -5px;
    right: -3px;
}`;
                case `mobile-fullscreen-mobile`:
                    return `
${t} .plugin__content {
    padding: 0 25px 100px 25px;
}

${e} #map-container {
    transform: scale(0.93) translateY(0);
    transform: scale(0.93) translateY(var(--margin-top));
    border-radius: 8px;
    transform-origin: top center;
}

${e} #search,
${e} #plugin-picker-mobile,
${e} #logo-wrapper,
${e} #go-premium-mobile {
    display: none !important;
}`;
                default:
                    return `/* No CSS for this device and pane */`
            }
        }
    },
    Qm = b({
        installExternalPlugin: () => $m,
        loadExternalPlugins: () => nh,
        removeExternalPlugin: () => rh
    });
const $m = async (e, t) => new Promise((n, r) => {
    if (!sp()) {
        _p({
            action: `external-plugins`,
            params: {}
        }), r({
            type: `installation`,
            msg: `Log in to install the plugin`
        });
        return
    }
    import(e).then(async i => {
        try {
            let {
                __pluginConfig: r
            } = i, {
                name: a,
                internal: o
            } = r;
            if (!(typeof a == `string` && /^windy-plugin-([a-z0-9-]+)$/.test(a))) throw Error(`Plugin name MUST be prefixed with windy-plugin- string and can contain only lowercase letters, numbers and dashes`);
            await Xa.hasKey(a) && await Xa.remove(a);
            let s = w(w({}, r), {}, {
                id: a,
                url: e,
                installedBy: t,
                installed: Date.now()
            });
            Y[a] = new Zm({
                ident: a
            }, s), o || await Xa.put(a, s), n(s)
        } catch (e) {
            r({
                type: `installation`,
                msg: e.message
            })
        }
    }).catch(e => {
        r({
            type: `network`,
            msg: e.message
        })
    })
});
let eh = [],
    th = !1;
const nh = async () => th ? eh : await hp() ? (await Xa.loadFromCloud(), eh = (await Xa.getAll()).map(e => {
    let t = e.name;
    return new Zm({
        ident: t
    }, e)
}), eh.forEach(e => {
    Y[e.ident] = e
}), th = !0, N.emit(`externalPluginChanged`), eh) : [], rh = async e => {
    N.emit(`rqstClose`, e), await Xa.remove(e)
};
N.on(`dependenciesResolved`, nh);
var ih = b({
        hideStartupWeather: () => yh,
        parseSearch: () => fh,
        parsedOverlay: () => bh,
        parsedProduct: () => xh,
        resolveRoute: () => uh,
        sharedCoords: () => _h
    }),
    ah;
let oh = `/`,
    sh;
sh = vn(bn), oh = sh.purl;

function ch() {
    let e = e => e.length > 3 ? e : ``,
        t = e => {
            if (!e) return;
            let t = e.replace(/(^|&)utm_[^&]+/gim, ``);
            return /\S+=\S+/.test(t) || t.length > 8 ? e : ``
        };
    try {
        return {
            path: e(oh),
            search: t(decodeURIComponent(window.location.search.substring(1).replace(/\?.*$/, ``)))
        }
    } catch (t) {
        return {
            path: e(oh || ``)
        }
    }
}

function lh(e) {
    let t = e.split(`/`).map(e => {
        if (e.startsWith(`:`)) {
            let t = e.replace(/:([^?]+)\??/g, `$1`);
            return e.endsWith(`?`) ? `(?:/(?<${t}>[^/]+))?` : `/(?<${t}>[^/]+)`
        }
        return e ? `/${e}` : ``
    });
    return RegExp(`^${t.join(``)}$`)
}

function uh(e, t, n) {
    if (!e) return null;
    if (/^\/plugin\/\S+/.test(e)) return dh(e);
    for (let r of Object.keys(Y)) {
        let i = Y[r];
        if (!i || !(`router` in i) || !i.router) continue;
        let {
            router: a,
            onRouteMatch: o
        } = i, s = (a instanceof RegExp ? a : lh(a)).exec(e);
        if (s) {
            let e = s.groups ? o(s.groups, n) : void 0;
            return e && (e.source = t), {
                ident: r,
                params: e
            }
        }
    }
    return null
}
async function dh(e) {
    let t = await nh(),
        n = !0;
    for (let {
            router: r,
            ident: i
        }
        of t)
        if (r) {
            let t = lh(r).exec(e);
            if (t) return n = !1, {
                ident: i,
                params: t.groups
            }
        } return n ? {
        ident: `external-plugins`
    } : null
}

function fh(e) {
    if (!e) return;
    let t = {
            sharedCoords: null,
            pickerCoords: null,
            product: null,
            overlay: null
        },
        n, r = e.split(`,`);
    for (let e = 0; e < r.length; e++) {
        n = r[e], /^-?\d+\.\d+$/.test(n) && /^-?\d+\.\d+$/.test(r[e + 1]) && /^\d+$/.test(r[e + 2]) && (t.sharedCoords = {
            lat: parseFloat(n),
            lon: parseFloat(r[e + 1]),
            zoom: parseInt(r[e + 2])
        }, e += 2);
        let i;
        Me.includes(n) && (t.product = n), we.includes(n) && (t.overlay = n), Se.includes(n) && M.set(`level`, n), (i = /^(\d\d\d\d)-?(\d\d)-?(\d\d)-?(\d\d)$/.exec(n)) && M.set(`timestamp`, Date.UTC(+i[1], i[2] - 1, +i[3], +i[4], 0, 0, 0)), (i = /^m:([a-zA-Z0-9]{5,})/.exec(n)) && (t.pickerCoords = lt(i[1])), (i = /^i:([a-z0-9]{2,})/.exec(n)) && (M.set(`isolinesType`, i[1]), M.set(`isolinesOn`, !0)), (i = /^p:([a-z0-9]{3,})/.exec(n)) && M.set(`pois`, i[1]), (i = /^d:picker/.exec(n)) && (t.pickerCoords = t.sharedCoords), (i = /^launchedBy:(\S+)/.exec(n)) && (t.hideStartupWeather = !0, yl(`appOpening`, i[1]))
    }
    return t
}
const ph = ch(),
    mh = gn(ph.search),
    hh = fh((ah = ph.search) == null ? void 0 : ah.split(`&`)[0]),
    gh = uh(ph.path, `url`, mh);
N.once(`dependenciesResolved`, async () => {
    let e = await gh,
        t = e == null ? void 0 : e.ident;
    e && N.emit(`rqstOpen`, e.ident, e.params), ph.path && !t ? (Lm(), yl(`404`, bn.replace(/^\//, ``))) : bn !== `/` && yl(`startup`, bn.replace(/^\//, ``))
}), hh && hh.pickerCoords && hh.sharedCoords && N.once(`redrawFinished`, () => {
    N.emit(`rqstOpen`, S ? `picker-mobile` : `picker`, w(w({}, hh.pickerCoords), {}, {
        noEmit: !0
    }))
});
const _h = hh == null ? void 0 : hh.sharedCoords,
    vh = gh !== null && !(gh instanceof Promise),
    yh = (hh == null ? void 0 : hh.hideStartupWeather) || vh,
    bh = we.includes(sh == null ? void 0 : sh.overlay) ? sh.overlay : hh == null ? void 0 : hh.overlay,
    xh = hh == null ? void 0 : hh.product;
var Sh = b({
    add: () => Ch,
    checkError: () => Oh,
    close: () => wh,
    getUnresolvedErrors: () => Dh,
    resolve: () => Th,
    resolveCategory: () => Eh
});
const Ch = e => {},
    wh = e => {},
    Th = e => {},
    Eh = e => {},
    Dh = () => [];

function Oh(e) {}
var kh = b({
    getFallbackName: () => Nh,
    getGPSlocation: () => Mh,
    getHomeLocation: () => Fh,
    getMyLatestPos: () => jh,
    requestLocationPermissions: () => Ih
});
const Ah = () => null,
    jh = () => {
        let e = M.get(`ipLocation`),
            t = M.get(`gpsLocation`);
        return e && t ? e.ts > t.ts ? e : t : t || e || {
            lat: 0,
            lon: -1 * new Date().getTimezoneOffset() / 4,
            cc: `us`,
            source: `fallback`,
            zoom: 3,
            name: ``,
            ts: Date.now()
        }
    },
    Mh = (e = {}) => new Promise(async (t, n) => {
        let r = {
                enableHighAccuracy: e.enableHighAccuracy || _e !== `ios`,
                timeout: e.timeout || 12e3
            },
            i = e => {
                let n = {
                    lat: e.coords.latitude,
                    lon: e.coords.longitude,
                    source: `gps`,
                    ts: Date.now()
                };
                M.set(`gpsLocation`, n), N.emit(`newLocation`, n), t(n)
            },
            a = async (r, i) => {
                let {
                    doNotShowFailureMessage: a,
                    getMeFallbackGps: o
                } = e;
                if (console.error(i), o) {
                    let e = M.get(`gpsLocation`);
                    if (!e) n(i);
                    else {
                        let r = Date.now() - e.ts;
                        if (r < 5 * 6e4) {
                            t(e);
                            return
                        } else r < 864e5 ? t(e) : n(i)
                    }
                } else n(i);
                a || await Nr({
                    type: `error`,
                    html: r ? P.GETTING_LOCATION_ERROR : o ? P.GETTING_LOCATION_FALLBACK : P.GETTING_LOCATION_TIMEOUT,
                    timeout: r ? 7e3 : 5e3
                })
            }, o = Ah();
        if (o) {
            if (!M.get(`locationPermissionsGranted`)) {
                if (!M.get(`onboardingFinished`)) return;
                let e = () => {},
                    t = new Promise(t => {
                        e = t
                    });
                if (N.emit(`rqstOpen`, `location-permission`, {
                        resolve: e
                    }), await t === !1) return
            }
            o.getCurrentPosition(r).then(i).catch(e => {
                e.message, a(!0, e)
            })
        } else navigator.geolocation.getCurrentPosition(i, e => a(e.code === e.PERMISSION_DENIED, e), r)
    }),
    Nh = (e, t) => `${parseFloat(e).toFixed(2)}, ${parseFloat(t).toFixed(2)}`,
    Ph = (e, t, n, r, i) => {
        n && (n = n.toLowerCase(), M.set(`country`, n), M.setDefault(`hourFormat`, /us|uk|ph|ca|au|nz|in|eg|sa|co|pk|my/.test(n) ? `12h` : `24h`), M.get(`defaultUnits`) === `unset` && M.set(`defaultUnits`, /us|my|lr/.test(n) ? `imperial` : `metric`));
        let a = {
            ts: Date.now(),
            source: i,
            lat: parseFloat(e),
            lon: parseFloat(t),
            name: r || Nh(e, t)
        };
        M.set(`ipLocation`, a), N.emit(`newLocation`, a)
    };
F(`/services/umisteni`, {
    ongoingFetchRequest: W.preparedFetchRequests.umisteni
}).then(({
    data: e
}) => {
    !e || !(e.ll && e.ll.length) || Ph(e.ll[0], e.ll[1], e.country, e.city, `api`)
}).catch(e => {
    O(`geolocation`, `Unable to load/parse geoloc JSON`, e)
});
const Fh = async () => {
    let e = Date.now(),
        t = M.get(`startUp`),
        n = M.get(`homeLocation`),
        r = M.get(`startUpLastPosition`);
    if (t === `last` && r) return w(w({}, r), {}, {
        ts: e,
        source: `last`
    });
    if (t === `location` && n) return n;
    if (t === `ip`) {
        let t = M.get(`ipLocation`) || jh();
        return t.source === `fallback` || e - t.ts > 12 * 36e5 ? new Promise(e => {
            N.once(`newLocation`, e)
        }) : t
    } else {
        let t = M.get(`gpsLocation`);
        if (t && t.source === `gps` && e - t.ts < 900 * 1e3) return t;
        try {
            return await Mh({
                doNotShowFailureMessage: !0
            })
        } catch (e) {
            if (t) return t;
            throw e
        }
    }
};
async function Ih() {
    let e = Ah();
    return (e ? (await e.requestPermissions()).location : (await navigator.permissions.query({
        name: `geolocation`
    })).state) === `granted`
}
var Lh = b({
    registerCustomTileProtocol: () => Vh
});
let Rh;
const zh = new Map,
    Bh = new fr(64);

function Vh(e, t, n, r, i) {
    function a(a, o) {
        let s = t(a.url, e);
        if (s.modifiedUrl === ``) return new Promise(e => {
            r || e({
                data: null
            }), r ? e({
                data: r
            }) : Rh ? e({
                data: Rh
            }) : Gv(!0).then(t => {
                Rh = t, e({
                    data: t
                })
            }).catch(e => {
                console.error(`Failed to create placeholder tile image`, e)
            })
        });
        let c = `${e}_${s.modifiedUrl}`,
            l = Bh.get(c);
        if (l) return Promise.resolve({
            data: l
        });
        if (zh.has(c)) return zh.get(c);
        let u = new Promise((e, t) => {
            Hh(s, o, n, r, i).then(n => {
                zh.delete(c), n ? (Bh.put(c, n), e({
                    data: n
                })) : t(`Failed to load tile image for url: ${s.modifiedUrl}`)
            }).catch(e => {
                console.error(`Failed to load tile image "${c}"`, e)
            })
        });
        return zh.set(c, u), u
    }
    ee(e, a)
}
async function Hh(e, t, n, r, i) {
    let a = e => !!(e.redirected && i && r !== void 0 && e.url.includes(`empty.`));
    try {
        let i = await fetch(e.modifiedUrl, {
            signal: t.signal
        });
        if (i.status === 200) return n ? await n(await i.blob(), e) : a(i) ? r : await i.arrayBuffer();
        if (r) return r
    } catch (e) {
        if (r) return r
    }
}
var Uh = class extends v {
    constructor(e, t) {
        var n, r;
        let i = `protocol-${(n = t == null ? void 0 : t.layerId) == null ? performance.now() : n}`,
            a = `${i}://{z}/{x}/{y}`;
        super(a, t), C(this, `_preparedTileDefs`, {}), C(this, `_urlMapping`, void 0), this._urlMapping = Dn(a), Vh(i, this._modifyTileRequest.bind(this));
        let o = (r = this.options.minZoom) == null ? 0 : r;
        for (let t in e) {
            let n = e[t],
                r = parseInt(t);
            for (; o <= r; o++) this._preparedTileDefs[o] = {
                url: n.url,
                subdomains: n.subdomains,
                patch: n.patch ? Wh(n.patch, o) : void 0,
                patchUrl: n.patchUrl
            }
        }
    }
    _modifyTileRequest(e, t) {
        let n = e.split(`/`),
            r = {
                z: parseInt(n[this._urlMapping.z]),
                x: parseInt(n[this._urlMapping.x]),
                y: parseInt(n[this._urlMapping.y])
            },
            i = this._preparedTileDefs[r.z],
            a = i.url;
        return i.patch && i.patchUrl && r.x >= i.patch[0] && r.y >= i.patch[1] && r.x < i.patch[2] && r.y < i.patch[3] && (a = i.patchUrl), a = a.replaceAll(`{z}`, `${r.z}`).replace(`{x}`, `${r.x}`).replace(`{y}`, `${r.y}`), {
            modifiedUrl: a.replace(t, `https`),
            tileCoords: r
        }
    }
};

function Wh(e, t) {
    let n = t - e[4];
    if (n === 0) return e;
    let r = [];
    for (let t = 0; t < 4; t++) n > 0 ? r.push(e[t] << n) : r.push(e[t] >> -n);
    return r.push(t), r
}
var Gh = b({
    addOrUpdateBasemap: () => Xh,
    baseMapLayerId: () => Yh,
    grayMapZoomEnd: () => 11,
    mapTilesRecord: () => Jh,
    removeBasemap: () => Zh,
    reorderBasemapLayer: () => Qh
});
let Kh = null,
    qh;
const Jh = e => {
        let t = Re ? `-retina` : ``;
        return {
            graymap: `https://tiles.windy.com/tiles/v11.2/darkmap${t}/{z}/{x}/{y}.png`,
            simplemap: `https://tiles.windy.com/tiles/v11.2/simple${t}/{z}/{x}/{y}.png`,
            landmaskmap: `https://tiles.windy.com/tiles/v11.2/grayland/{z}/{x}/{y}.png`,
            graymapPatch5: `https://tiles.windy.com/tiles/v11.2/${e}/darkmap${t}/{z}/{x}/{y}.png`,
            graymapPatch11: `https://tiles.windy.com/tiles/v11.2/${e}/darkmap${t}/{z}/{x}/{y}.png`,
            simplemapPatch5: `https://tiles.windy.com/tiles/v11.2/${e}/simple${t}/{z}/{x}/{y}.png`,
            simplemapPatch9: `https://tiles.windy.com/tiles/v11.2/${e}/simple${t}/{z}/{x}/{y}.png`,
            sznmap: `https://tiles.windy.com/v1/maptiles/outdoor/${t ? `256%402x` : `256`}/{z}/{x}/{y}/?lang=en`,
            winter: `https://tiles.windy.com/v1/maptiles/winter/256/{z}/{x}/{y}/?lang=en`,
            satLocal: `https://tiles.windy.com/tiles/orto/v1.0/{z}/{z}-{x}-{y}.jpg`,
            sat: `https://node.windy.com/maptile/2.1/maptile/newest/satellite.day/{z}/{x}/{y}/256/jpg?token2=${M.get(`userToken`)}`
        }
    },
    Yh = `raster-basemap`;

function Xh() {
    var e;
    let t = M.get(`map`),
        n = M.get(`overlay`),
        r = Z.getMaxZoom() + 1,
        i = Z.getMinZoom(),
        a = null,
        o = null;
    (M.get(`usedLang`) === `hi` || M.get(`country`) === `in`) && (a = `in`, o = [44, 24, 50, 28, 6]);
    let s = Jh(a),
        c;
    c = t === `sat` ? {
        13: {
            url: s.satLocal
        },
        [r]: {
            url: s.sat,
            subdomains: `1234`
        }
    } : {
        [r]: {
            url: s[t] || s.sznmap
        }
    }, o ? (c[11] = {
        url: s.graymap,
        patchUrl: s.graymapPatch11,
        patch: o
    }, n === `satellite` ? (c[5] = {
        url: s.simplemapPatch5
    }, c[9] = {
        url: s.simplemap,
        patchUrl: s.simplemapPatch9,
        patch: o
    }) : c[5] = {
        url: s.graymapPatch5
    }) : (c[11] = {
        url: s.graymap
    }, (n === `satellite` || M.get(`showThickBorders`)) && (c[9] = {
        url: s.simplemap
    })), Zh();
    let l = (e = qh) == null ? $_.BASE_MAP : e;
    Kh = new Uh(c, {
        detectRetina: !1,
        minZoom: i,
        maxZoom: r,
        layerId: Yh,
        layerBucketId: l,
        tileSize: 256
    }), yv(() => {
        Kh == null || Kh.addTo(Z)
    }), document.body.dataset.map = t
}

function Zh() {
    Kh != null && Kh.map && (Kh.remove(), Kh = null)
}

function Qh(e) {
    if (e === qh) return;
    qh = e;
    let t = Kh == null ? void 0 : Kh.options.layerId;
    t && Z.maplibreMap && Z.maplibreMap.moveLayerToBucket(t, e)
}
var $h = b({
    createFillFun: () => dg,
    createFullRenderingParams: () => pg,
    emitter: () => eg,
    getDataZoom: () => ag,
    getTrans: () => rg,
    getWTable: () => ug,
    interpolateNearest: () => fg,
    testJPGtransparency: () => sg,
    testPNGtransparency: () => cg,
    tileW: () => ng,
    wTables: () => lg,
    whichTile: () => og,
    zoom2zoom: () => tg
});
const eg = new Ln({
        ident: `render`
    }),
    tg = {
        extreme: [0, 0, 1, 2, 3, 4, 4, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6],
        ultra: [0, 0, 0, 2, 3, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
        high: [0, 0, 0, 2, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
        normal: [0, 0, 0, 2, 2, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
        low: [0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]
    },
    ng = e => 2 ** e,
    rg = (e, t) => ng(e) / ng(t),
    ig = Object.keys(tg),
    ag = (e, t) => {
        if (!e) return t;
        if (e.dataTilesZoom) return e.dataTilesZoom;
        let n = e.dataQuality,
            r = tg[e.upgradeDataQuality ? ig[Math.max(ig.indexOf(n) - 1, 0)] : n][t];
        return e.maxTileZoom ? Math.min(U() ? e.maxTileZoom.premium : e.maxTileZoom.free, r) : r
    },
    og = (e, t) => {
        if (!t.fullPath) return null;
        let n = e.z,
            r = ag(t, n),
            i = rg(n, r),
            a = Math.floor(e.x / i),
            o = Math.floor(e.y / i),
            s = e.x % i,
            c = e.y % i,
            l = t.fullPath.replace(`<z>`, r.toString()).replace(`<y>`, o.toString()).replace(`<x>`, a.toString()),
            u = ng(r);
        return a < 0 || o < 0 || a >= u || o >= u ? null : {
            url: l,
            x: a,
            y: o,
            z: r,
            intX: s,
            intY: c,
            trans: i,
            transformR: t.transformR || null,
            transformG: t.transformG || null,
            transformB: t.transformB || null
        }
    },
    sg = (e, t) => !!(e[t + 2] & 192 || e[t + 6] & 192 || e[t + 1030] & 192 || e[t + 1034] & 192),
    cg = (e, t) => !e[t + 3] || !e[t + 7] || !e[t + 1028 + 3] || !e[t + 1028 + 7],
    lg = {},
    ug = e => {
        if (e in lg) return lg[e];
        let t = 4 * e * e,
            n = 0,
            r;
        if (e <= 32) r = new Uint16Array(t);
        else return null;
        let i, a;
        for (a = 0; a < e; a++)
            for (i = 0; i < e; i++) r[n++] = (e - a) * (e - i), r[n++] = (e - a) * i, r[n++] = a * (e - i), r[n++] = i * a;
        return lg[e] = r, r
    },
    dg = (e, t, n) => {
        let r = n.getColorTable();
        if (!r) throw Error(`Creating fill fun failed, cTable is not defined!`);
        let i = n.value2index.bind(n);
        switch (t) {
            case 1:
                return (t, n, a) => {
                    let o = (n << 8) + t << 2,
                        s = i(a);
                    e[o++] = r[s++], e[o++] = r[s++], e[o] = r[s]
                };
            case 2:
                return (t, n, a) => {
                    let o = (n << 8) + t << 2,
                        s = i(a),
                        c = r[s++],
                        l = r[s++],
                        u = r[s];
                    e[o] = e[o + 4] = c, e[o + 1] = e[o + 5] = l, e[o + 2] = e[o + 6] = u, o += 1024, e[o] = e[o + 4] = c, e[o + 1] = e[o + 5] = l, e[o + 2] = e[o + 6] = u
                }
        }
    },
    fg = (e, t, n, r, i, a, o, s, c, l) => {
        e !== null && (o = e[t], s = e[t + 1], c = e[t + 2], l = e[t + 3]);
        let u = Math.max(o, s, c, l);
        return u === o ? n : u === s ? r : u === c ? i : a
    },
    pg = async (e, t, n) => {
        let r = Kc[e],
            i = K[r.product || t.product],
            a = w(w({}, t), {}, {
                layer: r.ident,
                JPGtransparency: r.JPGtransparency || i.JPGtransparency,
                PNGtransparency: r.PNGtransparency || i.PNGtransparency,
                maxTileZoom: r.maxTileZoom || i.maxTileZoom,
                transformR: r.transformR,
                transformG: r.transformG,
                transformB: r.transformB,
                directory: i.directory,
                dataQuality: r.dataQuality || i.dataQuality,
                upgradeDataQuality: i.betterDataQuality && i.betterDataQuality.includes(r.ident),
                refTime: ``,
                fullPath: ``,
                path: ``
            }, r.renderParams);
        if ([`satellite`, `radar`].includes(i.ident)) return a;
        let o = await i.getRefTime(),
            s = await i.getCalendar();
        if (!s || !o) throw Error(`createFullRenderingParams: Calendar or refTime is not defined`);
        let c = s.ts2path(n),
            l;
        l = r.levels ? r.levels.includes(t.level) ? t.level : r.levels[0] : t.level;
        let u = r.fileSuffix || i.fileSuffix,
            d = r.filename || t.overlay || r.ident,
            f = `${be}/im/v3.0/${i.directory}/${o}/${c}/wm_grid_257/<z>/<x>/<y>/`,
            p = r.renderer === `accumulations` ? `${d}-surface.${u}?next=${t.acRange}h` : `${d}-${l}.${u}`,
            m = `${f}${r.query ? Bt(p, r.query) : p}`;
        return a.refTime = o, a.fullPath = m, a.path = c, a
    };
let mg = function(e) {
        return e[e.VERTEX = WebGLRenderingContext.ARRAY_BUFFER] = `VERTEX`, e[e.INDEX = WebGLRenderingContext.ELEMENT_ARRAY_BUFFER] = `INDEX`, e
    }({}),
    hg = function(e) {
        return e[e.STATIC = WebGLRenderingContext.STATIC_DRAW] = `STATIC`, e[e.DYNAMIC = WebGLRenderingContext.DYNAMIC_DRAW] = `DYNAMIC`, e
    }({});
var gg = class e {
    constructor(t, n) {
        C(this, `buffer`, void 0), C(this, `type`, void 0), C(this, `_dataLength`, void 0), C(this, `bufferId`, void 0);
        let r = t.createBuffer();
        if (!r) throw Error(`[GlBuffer] - failed to create WebGL buffer`);
        this.buffer = r, this.type = n, this.bufferId = e.idCounter++
    }
    static reset() {
        e.idCounter = 0
    }
    bind(e) {
        this._dataLength, this.buffer && e.bindBuffer(this.type, this.buffer)
    }
    unbind(e) {
        this.buffer && e.bindBuffer(this.type, null)
    }
    update(e, t, n = hg.STATIC) {
        this.buffer && (e.bindBuffer(this.type, this.buffer), e.bufferData(this.type, t, n), e.bindBuffer(this.type, null), this._dataLength = t.length)
    }
    get length() {
        return this._dataLength
    }
    destroy(e) {
        e.deleteBuffer(this.buffer)
    }
};
C(gg, `idCounter`, 0);
var _g = class e {
    constructor() {
        C(this, `vaoId`, e.vaosCount++), C(this, `vao`, void 0)
    }
    static reset() {
        e.vaosCount = 0
    }
    static create(t) {
        let n = new e;
        return n.init(t) ? n : null
    }
    bind(e) {
        if (!this.vao) throw Error(`[GlVertexArray] VAO object is undefined/null`);
        if (!(e instanceof WebGLRenderingContext)) e.bindVertexArray(this.vao);
        else {
            let t = Zg.getExtension(e, `OES_vertex_array_object`);
            if (t) t.bindVertexArrayOES(this.vao);
            else throw Error(`[GlVertexArray] Failed to retrieve "OES_vertex_array_object" extension`)
        }
    }
    unbind(e) {
        if (!(e instanceof WebGLRenderingContext)) e.bindVertexArray(null);
        else {
            let t = Zg.getExtension(e, `OES_vertex_array_object`);
            if (t) t.bindVertexArrayOES(null);
            else throw Error(`[GlVertexArray] Failed to retrieve "OES_vertex_array_object" extension`)
        }
    }
    destroy(e) {
        if (this.vao)
            if (!(e instanceof WebGLRenderingContext)) e.bindVertexArray(null), e.deleteVertexArray(this.vao);
            else {
                let t = Zg.getExtension(e, `OES_vertex_array_object`);
                t && (t.bindVertexArrayOES(null), t.deleteVertexArrayOES(this.vao))
            }
    }
    init(e) {
        let t;
        if (!(e instanceof WebGLRenderingContext)) t = e.createVertexArray();
        else {
            let n = Zg.getExtension(e, `OES_vertex_array_object`);
            n && (t = n.createVertexArrayOES())
        }
        return t ? (this.vao = t, !0) : !1
    }
};
C(_g, `vaosCount`, 0);
var vg = class e {
    constructor(t, n, r, i = !1) {
        C(this, `vbos`, []), C(this, `vertexCount`, void 0), C(this, `attributes`, []), C(this, `buffersStride`, []), C(this, `ebo`, void 0), C(this, `vaos`, new Map), C(this, `meshId`, void 0), C(this, `instanceBuffer`, void 0), C(this, `instanceAttributes`, void 0), C(this, `instanceBufferStride`, 0), C(this, `instancingInitialized`, !1), C(this, `drawElementsCall`, void 0), C(this, `drawArraysCall`, void 0), C(this, `vertexDivisorCall`, void 0), n.length, this.addVertexStream(t, n, i), r && (this.ebo = new gg(t, mg.INDEX), this.ebo.update(t, r, i ? t.DYNAMIC_DRAW : t.STATIC_DRAW)), this.meshId = e.numMeshes++
    }
    static reset() {
        e.numMeshes = 0
    }
    render(e, t, n = e.TRIANGLES, r = 1) {
        if (this.attributes.length === 0) throw Error(`[GlMesh] - Geometry layout not defined (at least one attribute must be specified - see GlMesh.registerShaderGeometryLayout method)`);
        if (this.instanceBuffer) this.renderInstanced(e, t, n, r);
        else {
            let r = t.programId,
                i = this.vaos.get(r);
            i ? i.bind(e) : this.bindGeometry(e), this.ebo ? e.drawElements(n, this.ebo.length, e.UNSIGNED_INT, 0) : e.drawArrays(n, 0, this.vertexCount), i == null || i.unbind(e)
        }
    }
    registerShaderGeometryLayout(e, t, n, r = 0) {
        if (r >= this.vbos.length) throw Error(`[GlMesh] Cannot set vertex layout for vertex stream ${r}, \n since this mesh contains only ${this.vbos.length} vertex streams`);
        this.buffersStride[r] = 0, Object.keys(n).forEach(i => {
            let a = [-1, -1];
            this.buffersStride[r] += n[i];
            let o = e.getAttribLocation(t.getProgram(), i);
            o < 0 || (a[0] = o, a[1] = n[i], this.attributes[r].set(i, a))
        }), r === 0 && (this.vertexCount = this.vbos[r].length / this.buffersStride[r]);
        let i = _g.create(e);
        i && (i.bind(e), this.bindGeometry(e), i.unbind(e), this.vaos.set(t.programId, i))
    }
    destroy(e) {
        var t, n;
        this.vbos.forEach(t => {
            t.destroy(e)
        }), (t = this.ebo) == null || t.destroy(e), this.vaos.forEach(t => {
            t.destroy(e)
        }), this.attributes.forEach(e => {
            e.clear()
        }), (n = this.instanceAttributes) == null || n.clear()
    }
    addVertexStream(e, t, n = !1) {
        let r = new gg(e, mg.VERTEX);
        r.update(e, t, n ? e.DYNAMIC_DRAW : e.STATIC_DRAW), this.vbos.push(r);
        let i = new Map;
        return this.attributes.push(i), this.vbos.length - 1
    }
    updateVertexStream(e, t, n) {
        if (t >= this.vbos.length) throw Error(`[GlMesh] Cannot update vertex stream with index ${t}, there are only ${this.vbos.length} streams`);
        return this.vbos[t].update(e, n), t === 0 && (this.vertexCount = this.vbos[t].length / this.buffersStride[t]), !0
    }
    initInstancing(e) {
        if (!(e instanceof WebGLRenderingContext)) this.drawElementsCall = (...t) => {
            e.drawElementsInstanced(...t)
        }, this.drawArraysCall = (...t) => {
            e.drawArraysInstanced(...t)
        }, this.vertexDivisorCall = (...t) => {
            e.vertexAttribDivisor(...t)
        };
        else {
            let t = Zg.getExtension(e, `ANGLE_instanced_arrays`);
            if (!t) return console.error(`[GlMesh] Failed to retrieve "ANGLE_instanced_arrays" extension instanced rendering`), !1;
            this.drawElementsCall = (...e) => {
                t.drawElementsInstancedANGLE(...e)
            }, this.drawArraysCall = (...e) => {
                t.drawArraysInstancedANGLE(...e)
            }, this.vertexDivisorCall = (...e) => {
                t.vertexAttribDivisorANGLE(...e)
            }
        }
        return this.instancingInitialized = !0, !0
    }
    setInstanceStream(e, t, n, r) {
        return this.instancingInitialized || this.initInstancing(e), e instanceof WebGLRenderingContext && !Zg.getExtension(e, `ANGLE_instanced_arrays`) ? !1 : (this.instanceAttributes || (this.instanceAttributes = new Map), this.instanceBuffer || (this.instanceBuffer = new gg(e, mg.VERTEX)), this.instanceBuffer.update(e, n, e.STATIC_DRAW), this.instanceBuffer.bind(e), Object.keys(r).forEach(n => {
            var i;
            let a = [-1, -1, -1];
            a[0] = e.getAttribLocation(t.getProgram(), n), a[1] = r[n][0], a[2] = r[n][1], (i = this.instanceAttributes) == null || i.set(n, a), this.instanceBufferStride += r[n][0]
        }), !0)
    }
    updateInstanceStream(e, t) {
        return this.instanceBuffer ? (this.instanceBuffer.update(e, t), !0) : !1
    }
    hasInstanceStream() {
        return !!this.instanceBuffer
    }
    bindGeometry(e) {
        this.vbos.forEach((t, n) => {
            t.bind(e);
            let r = 0;
            this.attributes[n].forEach(t => {
                e.enableVertexAttribArray(t[0]), e.vertexAttribPointer(t[0], t[1], e.FLOAT, !1, this.buffersStride[n] * 4, r * 4), r += t[1]
            })
        }), this.ebo && this.ebo.bind(e)
    }
    renderInstanced(e, t, n = e.TRIANGLES, r) {
        var i, a;
        if (!this.instanceBuffer) return;
        let o = t.programId,
            s = this.vaos.get(o);
        s ? s.bind(e) : this.bindGeometry(e), this.instanceBuffer.bind(e);
        let c = 0;
        (i = this.instanceAttributes) == null || i.forEach(t => {
            e.enableVertexAttribArray(t[0]), e.vertexAttribPointer(t[0], t[1], e.FLOAT, !1, this.instanceBufferStride * 4, c * 4), c += t[1], this.vertexDivisorCall(t[0], t[2])
        }), this.ebo ? this.drawElementsCall(n, this.ebo.length, e.UNSIGNED_INT, 0, r) : this.drawArraysCall(e.TRIANGLE_FAN, 0, this.vertexCount, r), (a = this.instanceAttributes) == null || a.forEach(e => {
            this.vertexDivisorCall(e[0], 0)
        }), this.instanceBuffer.unbind(e), s == null || s.unbind(e)
    }
};
C(vg, `numMeshes`, 0);
var yg = class {};
C(yg, `quadMeshUniqueVtxUv`, [0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 1, 0, 0, 0, 1]), C(yg, `quadMeshUniqueVtx`, [0, 1, 1, 1, 1, 0, 0, 0]), C(yg, `quadMeshTrianglesVtx`, [0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 0]);
var bg = class e {
    constructor(t = ``) {
        C(this, `_program`, void 0), C(this, `_programId`, e.numPrograms++), C(this, `_programName`, ``), this._programName = t
    }
    static reset() {
        e.numPrograms = 0
    }
    get programId() {
        return this._programId
    }
    static constructWithSources(t, n, r, i) {
        let a = new e(i),
            o, s;
        try {
            o = $g(t, n, t.VERTEX_SHADER), s = $g(t, r, t.FRAGMENT_SHADER)
        } catch (e) {
            throw e instanceof Jg ? (console.log(`%c Shader: %c ${e.additionalInfo.filename}\n%c Error log: %c ${e.additionalInfo.shaderLog}`, `color:orange`, `color:unset`, `color:orange`, `color:unset`), new Jg(e.message, {
                cause: e,
                additionalInfo: w(w({}, e.additionalInfo), {}, {
                    programName: a._programName
                })
            }, e.emitToElastic)) : e
        }
        let c;
        try {
            c = Qg(t, o, s)
        } catch (e) {
            throw e instanceof Jg ? new Jg(e.message, {
                cause: e,
                additionalInfo: w(w({}, e.additionalInfo), {}, {
                    programName: a._programName
                })
            }, e.emitToElastic) : e
        }
        return a._program = c, a
    }
    use(e) {
        if (!this._program) throw Error(`Shader program does not exist`);
        e.useProgram(this._program)
    }
    getProgram() {
        return this._program
    }
    destroy(e) {
        let t = e.getAttachedShaders(this._program);
        t == null || t.forEach(t => {
            e.detachShader(this._program, t), e.deleteShader(t)
        }), e.deleteProgram(this._program)
    }
};
C(bg, `numPrograms`, 0);
const xg = {
    el: void 0,
    el2: void 0,
    numTextures: 0,
    memoryUsage: 0,
    setup: !1
};
var Sg = class e {
    static reset() {
        e.numTextures = 0
    }
    static createFromUrl(t, n) {
        return new Promise((r, i) => {
            let a = new Image,
                o = new e(t);
            o.resize(t, {
                x: 1,
                y: 1
            }), a.onload = () => {
                o.updateContent(t, a), r(o)
            }, a.onerror = e => {
                i(e)
            }, a.crossOrigin = ``, a.src = n
        })
    }
    constructor(t, n = t.RGBA, r = t.TEXTURE_2D, i) {
        if (C(this, `_target`, void 0), C(this, `_texture`, void 0), C(this, `_textureId`, void 0), C(this, `_internalFormat`, void 0), C(this, `_dimensions`, void 0), C(this, `_uvDownScale`, {
                x: 1,
                y: 1
            }), C(this, `wrap`, void 0), C(this, `filter`, void 0), C(this, `_usedMemory`, 0), i) this._texture = i;
        else {
            let n = t.createTexture();
            if (!n) throw Error(`[GlTexture] Failed to create WebGL texture`);
            this._texture = n, this._textureId = e.numTextures++
        }
        this._internalFormat = n, this._target = r, this.wrap = t.CLAMP_TO_EDGE, this.filter = t.LINEAR, t.bindTexture(this._target, this._texture), t.texParameteri(this._target, t.TEXTURE_WRAP_S, this.wrap), t.texParameteri(this._target, t.TEXTURE_WRAP_T, this.wrap), t.texParameteri(this._target, t.TEXTURE_MIN_FILTER, this.filter), t.texParameteri(this._target, t.TEXTURE_MAG_FILTER, this.filter), t.bindTexture(this._target, null)
    }
    get texture() {
        return this._texture
    }
    get textureId() {
        return this._textureId
    }
    get target() {
        return this._target
    }
    get dimensions() {
        return this._dimensions
    }
    set format(e) {
        this._internalFormat = e
    }
    get format() {
        return this._internalFormat
    }
    get uvDownScale() {
        return this._uvDownScale
    }
    get usedMemory() {
        return this._usedMemory
    }
    updateContent(e, t, n, r, i = !1) {
        this.bind(e, n, r), e.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL, i), t instanceof HTMLImageElement || t instanceof HTMLCanvasElement || t instanceof ImageBitmap ? (this._dimensions = {
            x: t.width,
            y: t.height
        }, e.texImage2D(this._target, 0, this._internalFormat, this._internalFormat, e.UNSIGNED_BYTE, t)) : (this._dimensions = {
            x: t[1].x,
            y: t[1].y
        }, e.texImage2D(this._target, 0, this._internalFormat, t[1].x, t[1].y, 0, this._internalFormat, e.UNSIGNED_BYTE, t[0])), this.unbind(e)
    }
    create(e, t, n) {
        e.bindTexture(e.TEXTURE_2D, this._texture), e.texImage2D(e.TEXTURE_2D, 0, this._internalFormat, t, n, 0, this._internalFormat, e.UNSIGNED_BYTE, null), e.bindTexture(e.TEXTURE_2D, null), this._dimensions = {
            x: t,
            y: n
        }
    }
    bind(e, t, n) {
        e.bindTexture(this._target, this._texture), t && t !== this.wrap && (e.texParameteri(this._target, e.TEXTURE_WRAP_S, t), e.texParameteri(this._target, e.TEXTURE_WRAP_T, t), this.wrap = t), n && n !== this.filter && (e.texParameteri(this._target, e.TEXTURE_MIN_FILTER, n), e.texParameteri(this._target, e.TEXTURE_MAG_FILTER, n), this.filter = n)
    }
    unbind(e) {
        e.bindTexture(this._target, null)
    }
    destroy(e) {
        e.deleteTexture(this._texture)
    }
    resize(e, t, n = !1, r = e.RGBA) {
        if (!e_(t)) return console.error(`[GlTexture] Trying to resize texture with invalid dimensions: `, t), {
            x: 0,
            y: 0
        };
        let i = this._internalFormat !== r,
            a = !!this._dimensions,
            o = a && (this._dimensions.x !== t.x || this._dimensions.y !== t.y),
            s = n && this._dimensions && t.x <= this._dimensions.x && t.y <= this._dimensions.y;
        this._uvDownScale = {
            x: 1,
            y: 1
        };
        let c = !0;
        return a && (!o || o && s) ? (i || (c = !1), this._uvDownScale = {
            x: t.x / this._dimensions.x,
            y: t.y / this._dimensions.y
        }) : this._dimensions = t, this._internalFormat = r, c && this.reallocate(e), this._uvDownScale
    }
    reallocate(e) {
        let t = s_(this._internalFormat);
        this.bind(e), e.texImage2D(this._target, 0, this._internalFormat, this._dimensions.x, this._dimensions.y, 0, t, e.UNSIGNED_BYTE, null), this.unbind(e)
    }
    setupProfiling() {
        let e = document.querySelector(`.texture-count.textures`);
        e && (xg.el = e);
        let t = document.querySelector(`.texture-count.texture-memory`);
        t && (xg.el2 = t), e && t && (xg.setup = !0)
    }
    updateProfilingStats(e) {
        if (!(!xg.el || !xg.el2)) {
            if (e) console.log(`%c   [GlTexture] Texture '${this._textureId}' deleted`, `color:yellow`), xg.el.innerHTML = `${xg.numTextures--}`, xg.memoryUsage -= this._usedMemory;
            else {
                this._usedMemory > 0 && (xg.memoryUsage -= this._usedMemory);
                let e = o_(this._internalFormat);
                this._usedMemory = e * this.dimensions.x * this.dimensions.y, xg.memoryUsage += this._usedMemory
            }
            xg.el2.innerHTML = `${(xg.memoryUsage / (1 << 20)).toFixed(1)}MB`
        }
    }
};
C(Sg, `numTextures`, 0);
var Cg = class e {
    constructor(t) {
        C(this, `ident`, `gl-renderer`), C(this, `meshes`, []), C(this, `uniforms`, new Map), C(this, `dirtyUniforms`, new Set), C(this, `uniformTextures`, new Map), C(this, `program`, void 0), C(this, `renderReady`, !1), C(this, `clearColor`, void 0), C(this, `rendererId`, e.numRenderers++), this.ident = t
    }
    static reset() {
        e.numRenderers = 0
    }
    initFromSources(e, t, n) {
        try {
            let r = bg.constructWithSources(e, t, n, `${this.ident}-${this.rendererId}-program`);
            this.program = r, this.renderReady = !0
        } catch (e) {
            if (e instanceof Jg) l_(this.ident, e);
            else throw console.error(e), e
        }
    }
    render(e, t = e.TRIANGLES, n = 0) {
        !this.renderReady || this.meshes.length === 0 || (this.program.use(e), this.bindUniforms(e), this.meshes.forEach(r => {
            r.render(e, this.program, t, n)
        }), e.useProgram(null))
    }
    updateUniformValue(e, t) {
        let n = this.uniformTextures.has(e),
            r = n ? this.uniformTextures.get(e) : this.uniforms.get(e);
        if (r) {
            if (r.value = t, n) {
                this.uniformTextures.set(e, r), this.dirtyUniforms.add(e);
                return
            }
            this.uniforms.set(e, r), this.dirtyUniforms.add(e)
        }
    }
    registerUniformRecord(e, t, n, r = null) {
        if (!this.program) throw Error(`Shader program is not initialized yet`);
        let i = e.getUniformLocation(this.program.getProgram(), t);
        if (i === null) return !1;
        let a = {
            uniformId: t,
            uniformLocation: i,
            glDataType: n,
            value: r
        };
        return n === 1 ? (this.uniformTextures.set(t, a), this.dirtyUniforms.add(t)) : (this.uniforms.set(t, a), this.dirtyUniforms.add(t)), !0
    }
    isUniformRecordRegistered(e) {
        return this.uniforms.has(e)
    }
    addMesh(e) {
        this.meshes.push(e)
    }
    getAttachedShader() {
        return this.program
    }
    destroy(e) {
        this.meshes.forEach(t => {
            t.destroy(e)
        }), this.program.destroy(e), this.uniforms.clear()
    }
    setClearColor(e) {
        this.clearColor = e
    }
    clear(e) {
        var t;
        let n = (t = this.clearColor) == null ? {
            x: 0,
            y: 0,
            z: 0,
            w: 0
        } : t;
        e.clearColor(n.x, n.y, n.z, n.w), e.clear(e.COLOR_BUFFER_BIT)
    }
    bindUniforms(e) {
        this.dirtyUniforms.forEach(t => {
            let n = this.uniformTextures.has(t) ? this.uniformTextures.get(t) : this.uniforms.get(t);
            if (!n || n.value == null || n.value == null) return;
            let r = n.value instanceof Function ? n.value() : n.value;
            if (n.value === null || n.value === void 0) throw Error(`[GlRenderer] Uniform value is empty`);
            switch ((r == null ? void 0 : r.y) !== void 0 && (r = new Float32Array(Object.values(r))), n.glDataType) {
                case 5:
                    e.uniform1f(n.uniformLocation, r);
                    break;
                case 0:
                    e.uniform1i(n.uniformLocation, r);
                    break;
                case 2:
                    e.uniform4fv(n.uniformLocation, r);
                    break;
                case 6:
                    e.uniform3fv(n.uniformLocation, r);
                    break;
                case 4:
                    e.uniform2fv(n.uniformLocation, r);
                    break;
                case 7:
                    e.uniform1fv(n.uniformLocation, r);
                    break;
                case 8:
                    e.uniform4fv(n.uniformLocation, r);
                    break;
                case 3:
                    e.uniformMatrix4fv(n.uniformLocation, !1, r);
                    break;
                case 1: {
                    let r = parseInt(t.split(`l`)[1]);
                    if (isNaN(r)) return;
                    e.uniform1i(n.uniformLocation, r);
                    break
                }
            }
        }), this.dirtyUniforms.clear(), this.bindTextures(e)
    }
    bindTextures(e) {
        let t = new Set,
            n = {};
        this.uniformTextures.forEach((r, i) => {
            if (!r || r.value == null || r.value == null) return;
            let a = r.value instanceof Function ? r.value() : r.value;
            if (r.value === null || r.value === void 0) throw Error(`[GlRenderer] Uniform value is empty`);
            let o = parseInt(i.split(`l`)[1]);
            isNaN(o) ? n[i] = [r.uniformLocation, a] : (e.activeTexture(e.TEXTURE0 + o), a instanceof Sg ? a.bind(e) : e.bindTexture(e.TEXTURE_2D, a), t.add(o))
        });
        let r = 0;
        Object.entries(n).forEach(([n, [i, a]]) => {
            for (; t.has(r);) r++;
            e.activeTexture(e.TEXTURE0 + r), a instanceof Sg ? a.bind(e) : e.bindTexture(e.TEXTURE_2D, a), e.uniform1i(i, r++)
        })
    }
};
C(Cg, `numRenderers`, 0);
const wg = `What can you do? ${_e === `android` ? ` Update your Android System WebView component to the latest version.` : ``} Update your browser or Windy application to the latest version. And try again please.`;
`${M.get(`overlay`)}${wg}`;
let Tg = null;

function Eg() {
    if (Tg !== null) return Tg;
    try {
        let e = document.createElement(`canvas`);
        if (e.getContext(`webgl2`) || e.getContext(`webgl`) || e.getContext(`experimental-webgl`)) return Tg = !0, Tg;
        Dg(`Your device/browser does not support WebGL or has it disabled.`), Tg = !1
    } catch (e) {
        Dg(`An error occurred during WebGL initialization.`), Tg = !1
    }
    return Tg
}

function Dg(e) {
    Og(`It seems that ${M.get(`overlay`)} overlay failed. ${e}\n\n${wg}`)
}

function Og(e) {
    new kr({
        ident: `message-webgl-error`,
        className: `top-message bg-error`,
        html: e
    }).open()
}
let kg = null,
    Ag = null,
    jg = !1,
    Mg = `glContextUtils`;

function Ng(e, t) {
    Mg = t, kg && Vg(kg), kg = e.canvas, Ag = e, jg = !1, Bg(kg)
}

function Pg(e) {
    return !!e && typeof e.isContextLost == `function`
}

function Fg() {
    if (Ag && Pg(Ag)) try {
        return Ag.isContextLost()
    } catch (e) {}
    return !1
}

function Ig(e) {
    e.preventDefault(), !jg && queueMicrotask(() => {
        jg || Fg() && (jg = !0, Rg())
    })
}

function Lg() {
    jg = !1, requestAnimationFrame(() => {
        Fg() || zg()
    })
}

function Rg() {
    eg.emit(`contextLost`), N.emit(`glContextLost`), O(Mg, `Canvas context is lost`, void 0)
}

function zg() {
    eg.emit(`contextRestored`), N.emit(`glContextRestored`), O(Mg, `Canvas context is restored`, void 0)
}

function Bg(e) {
    e.addEventListener(`webglcontextlost`, Ig, !1), e.addEventListener(`webglcontextrestored`, Lg, !1)
}

function Vg(e) {
    e.removeEventListener(`webglcontextlost`, Ig, !1), e.removeEventListener(`webglcontextrestored`, Lg, !1)
}
N.on(`glLoseContext`, () => {}), N.on(`glRestoreContext`, () => {});
const X = window.WebGLRenderingContext,
    Hg = new Map([
        [X.NO_ERROR, `NO_ERROR`],
        [X.INVALID_ENUM, `INVALID_ENUM`],
        [X.INVALID_VALUE, `INVALID_VALUE`],
        [X.INVALID_OPERATION, `INVALID_OPERATION`],
        [X.INVALID_FRAMEBUFFER_OPERATION, `INVALID_FRAMEBUFFER_OPERATION`],
        [X.OUT_OF_MEMORY, `OUT_OF_MEMORY`],
        [X.CONTEXT_LOST_WEBGL, `CONTEXT_LOST_WEBGL`]
    ]),
    Ug = (function() {
        let e = new ArrayBuffer(2);
        return new DataView(e).setInt16(0, 256, !0), new Int16Array(e)[0] === 256
    })(),
    Wg = e => e.charAt(0) === `a`,
    Gg = e => e.charAt(0) === `u` || e.charAt(0) === `s`;
var Kg = class e {
    constructor(t = !1, n = !1) {
        C(this, `id`, void 0), C(this, `glId`, 0), C(this, `maxTextureSize`, 0), C(this, `_name`, void 0), C(this, `keepRefs`, void 0), C(this, `keepRefsShaders`, void 0), C(this, `framebuffers`, void 0), C(this, `buffers`, void 0), C(this, `shaders`, void 0), C(this, `programs`, void 0), C(this, `textures`, void 0), C(this, `_gl`, void 0), C(this, `canvas`, void 0), C(this, `isGlError`, !1), C(this, `lastGlErrorMsg`, ``), this.id = e.newId++, this.keepRefs = t, this.keepRefsShaders = n, this.reset()
    }
    reset() {
        this.framebuffers = [], this.buffers = [], this.shaders = [], this.programs = [], this.textures = [], this._gl = null, this.glId = 0, this.canvas = null
    }
    create(t, n, r) {
        if (this._name = r, !Eg()) return null;
        if (!(this._gl || this.canvas)) return this.canvas = t, this._gl = t.getContext(`webgl`, n) || t.getContext(`experimental-webgl`, n), this._gl && (this.glId = e.newGlId++, this.maxTextureSize = this._gl.getParameter(X.MAX_TEXTURE_SIZE)), Ng(this._gl, `GlObj_${this._name}`), this._gl
    }
    gl() {
        return this._gl
    }
    get() {
        return this.gl()
    }
    getCanvas() {
        return this.canvas
    }
    createShader(e, t, n) {
        let r = this.gl();
        if (!r) return null;
        let i = r.createShader(t ? r.VERTEX_SHADER : r.FRAGMENT_SHADER);
        if (i && (this.keepRefsShaders && this.shaders.push(i), r.shaderSource(i, e), r.compileShader(i), !r.getShaderParameter(i, r.COMPILE_STATUS))) {
            let e = r.getShaderInfoLog(i) || `getShaderInfoLog is null`,
                a = Error(e);
            throw a.contextLost = r.isContextLost(), a.isVertexShader = t, a.name = n || `shader`, a.full = `ERROR compileShader! name: ${a.name}; (${a.isVertexShader ? `VS` : `FS`}); (${this.getGlStatus()}); msg: ${a.message}`, a
        }
        return i
    }
    createProgramObj(e, t, n, r) {
        let i = this.gl();
        if (!i) return null;
        let a = i.createProgram(),
            o = {
                program: a
            },
            s = ``,
            c, l;
        if (a) {
            if (this.keepRefs && this.programs.push(a), n && n.length > 0)
                for (c = 0; c < n.length; c++) s += `#define ` + n[c] + `
`;
            let u = this.createShader(s + e, !0, r),
                d = this.createShader(s + t, !1, r);
            if (!u || !d) throw l = Error(`vertexShader or fragmentShader is null; name: ` + r), l;
            {
                if (i.attachShader(a, u), i.attachShader(a, d), i.linkProgram(a), !i.getProgramParameter(a, i.LINK_STATUS)) {
                    let e = i.getProgramInfoLog(a) || `getProgramInfoLog is null`;
                    throw l = Error(e), l.contextLost = i.isContextLost(), l.name = r || `shader`, l.full = `ERROR linkProgram! name: ${l.name}; ${this.getGlStatus()}`, l
                }
                let e = i.getProgramParameter(a, i.ACTIVE_ATTRIBUTES);
                for (c = 0; c < e; c++) {
                    let e = i.getActiveAttrib(a, c);
                    if (e) {
                        let t = e.name;
                        if (Wg(t)) o[t] = i.getAttribLocation(a, e.name);
                        else throw `Invalid attribute name "${t}"`
                    }
                }
                let t = i.getProgramParameter(a, i.ACTIVE_UNIFORMS);
                for (c = 0; c < t; c++) {
                    let e = i.getActiveUniform(a, c);
                    if (e) {
                        let t = i.getUniformLocation(a, e.name),
                            n = e.name,
                            r = n.indexOf(`[`);
                        if (r > 0 && (n = n.substring(0, r)), Gg(n)) o[n] = t;
                        else throw `Invalid uniform name "${n}"`
                    }
                }
            }
        } else throw l = Error(), l.full = `gl.createProgram() is null; name: ${r}; ${this.getGlStatus()}`, l;
        return o
    }
    bindAttribute(e, t, n, r, i, a, o) {
        let s = this.gl();
        s && (s.bindBuffer(X.ARRAY_BUFFER, e), s.enableVertexAttribArray(t), s.vertexAttribPointer(t, n, r, i, a, o))
    }
    textureFromUrlPromise(e, t, n, r, i, a) {
        return new Promise(o => {
            let s = new Image,
                c = this.createTexture2D(n, r, i, null, 1, 1, X.RGBA);
            s.onload = () => {
                this.resizeTexture2D(c, s, s.width, s.height, X.RGBA, a), o([e, c])
            }, s.crossOrigin = ``, s.src = t
        })
    }
    createTextureFromBase64(e, t, n, r, i) {
        let a = new Image,
            o = this.createTexture2D(e, t, n, null, 1, 1, X.RGBA);
        return a.onload = () => {
            this.resizeTexture2D(o, a, a.width, a.height, X.RGBA, i)
        }, a.src = r, o
    }
    createTexture2D(e, t, n, r, i, a, o, s) {
        let c = this.gl();
        if (c) {
            let l = c.createTexture();
            return l && (this.keepRefs && this.textures.push(l), l._width = i, l._height = a, c.bindTexture(c.TEXTURE_2D, l), this.setBindedTexture2DParams(e, t, n)), this.resizeTexture2D(l, r, i, a, o, s)
        }
        return null
    }
    resizeTexture2D(e, t, n, r, i, a) {
        if (!e) return e;
        let o = this.gl();
        if (i = i || X.RGBA, e._width = n, e._height = r, e._format = i, o) {
            if (o.bindTexture(X.TEXTURE_2D, e), Array.isArray(t)) {
                let e = n,
                    s = r;
                o.pixelStorei(X.UNPACK_ALIGNMENT, e > 4 ? 4 : 1);
                for (let n = 0; n < t.length; n++) {
                    e === 4 && o.pixelStorei(X.UNPACK_ALIGNMENT, 1);
                    let r = t[n];
                    r === null || ArrayBuffer.isView(r) ? o.texImage2D(X.TEXTURE_2D, n, i, e, s, 0, i, X.UNSIGNED_BYTE, r) : o.texImage2D(X.TEXTURE_2D, n, i, i, X.UNSIGNED_BYTE, r), e = Math.max(e >> 1, 1), s = Math.max(s >> 1, 1)
                }
                a = !1
            } else t === null || ArrayBuffer.isView(t) ? o.texImage2D(X.TEXTURE_2D, 0, i, n, r, 0, i, X.UNSIGNED_BYTE, t) : o.texImage2D(X.TEXTURE_2D, 0, i, i, X.UNSIGNED_BYTE, t);
            a && o.generateMipmap(X.TEXTURE_2D), o.bindTexture(X.TEXTURE_2D, null)
        }
        return e
    }
    deleteTexture2D(t) {
        var n;
        e.removeFromArray(t, this.textures), (n = this.gl()) == null || n.deleteTexture(t)
    }
    bindTexture2D(e, t, n) {
        let r = this.gl();
        r && (r.activeTexture(X.TEXTURE0 + (t || 0)), r.bindTexture(X.TEXTURE_2D, e), n && r.uniform1i(n, t))
    }
    setBindedTexture2DParams(e, t, n, r) {
        let i = this.gl();
        i && (i.texParameteri(X.TEXTURE_2D, X.TEXTURE_MIN_FILTER, e), i.texParameteri(X.TEXTURE_2D, X.TEXTURE_MAG_FILTER, t), i.texParameteri(X.TEXTURE_2D, X.TEXTURE_WRAP_S, n), i.texParameteri(X.TEXTURE_2D, X.TEXTURE_WRAP_T, r || n))
    }
    createBuffer(e) {
        let t = this.gl(),
            n = null;
        return t && (n = t.createBuffer(), n && (this.keepRefs && this.buffers.push(n), this.setBufferData(n, e))), n
    }
    setBufferData(e, t) {
        let n = this.gl();
        n && (n.bindBuffer(X.ARRAY_BUFFER, e), n.bufferData(X.ARRAY_BUFFER, t, X.STATIC_DRAW))
    }
    createIndexBuffer(e) {
        let t = this.gl(),
            n = null;
        return t && (n = t.createBuffer(), this.keepRefs && n && this.buffers.push(n), t.bindBuffer(X.ELEMENT_ARRAY_BUFFER, n), t.bufferData(X.ELEMENT_ARRAY_BUFFER, e, X.STATIC_DRAW)), n
    }
    bindFramebuffer(e, t) {
        let n = this.gl();
        n && (n.bindFramebuffer(n.FRAMEBUFFER, e), t && n.framebufferTexture2D(X.FRAMEBUFFER, X.COLOR_ATTACHMENT0, X.TEXTURE_2D, t, 0))
    }
    release() {
        let e = this._gl;
        if (e) {
            e.flush(), e.finish();
            let t = this.textures.length,
                n, r;
            for (n = 0; n < t; n++) r = this.textures[n], e.isTexture(r) && e.deleteTexture(r);
            for (t = this.programs.length, n = 0; n < t; n++) r = this.programs[n], e.isProgram(r) && e.deleteProgram(r);
            for (t = this.shaders.length, n = 0; n < t; n++) r = this.shaders[n], e.isShader(r) && e.deleteShader(r);
            for (t = this.buffers.length, n = 0; n < t; n++) r = this.buffers[n], e.isBuffer(r) && e.deleteBuffer(r);
            for (t = this.framebuffers.length, n = 0; n < t; n++) r = this.framebuffers[n], e.isFramebuffer(r) && e.deleteFramebuffer(r);
            this.reset()
        }
    }
    checkGlError() {
        let e = !0,
            t = `GL CONTEXT STATUS: `;
        if (this._gl) {
            let n = this._gl.isContextLost(),
                r = this._gl.getError();
            if (n) t += `GL CONTEXT LOST!`;
            else if (r === X.NO_ERROR) t += `no error.`, e = !1;
            else {
                let e = Hg.get(r);
                t += `${e} (code: ${r})!; contextLost: ${n}`
            }
        } else t += `gl is null!`;
        return this.isGlError = e, this.lastGlErrorMsg = t, e
    }
    getGlStatus() {
        return this.checkGlError(), this.lastGlErrorMsg
    }
    static getNextPowerOf2Size(e) {
        return 2 << Math.floor(Math.log2(e - 1))
    }
    static removeFromArray(e, t) {
        let n = -1;
        for (let r = 0; r < t.length; r++) t[r] === e && (n = r);
        return n > -1 && t.splice(n, 1), n
    }
};
C(Kg, `littleEndian`, Ug), C(Kg, `newId`, 0), C(Kg, `newGlId`, 1);
var qg = b({
        GlBuffer: () => gg,
        GlBufferType: () => mg,
        GlBufferUsage: () => hg,
        GlError: () => Jg,
        GlExtension: () => Zg,
        GlMesh: () => vg,
        GlObj: () => Kg,
        GlProgram: () => bg,
        GlRenderer: () => Cg,
        GlTexture: () => Sg,
        GlVertexArray: () => _g,
        GlslDataType: () => Yg,
        MeshFactory: () => yg,
        checkGlError: () => c_,
        checkTextureDimensions: () => e_,
        createPlaceHolderTexture: () => n_,
        createPlaceholderFbo: () => t_,
        createPlaceholderImageData: () => r_,
        createShaderFromSource: () => $g,
        createShaderProgram: () => Qg,
        getTextureFormatByInternalFormat: () => s_,
        glUtils: () => Xg,
        logErrorWebGL: () => l_,
        sizeOf: () => o_
    }),
    Jg = class extends Error {
        constructor(e, t, n = !1) {
            super(e, t), C(this, `additionalInfo`, {}), C(this, `emitToElastic`, !1), this.additionalInfo = (t == null ? void 0 : t.additionalInfo) || {}, this.emitToElastic = n
        }
        toObject() {
            return {
                message: this.message,
                additionalInfo: this.additionalInfo,
                cause: this.cause,
                emitToElastic: this.emitToElastic
            }
        }
    };
let Yg = function(e) {
    return e[e.Int = 0] = `Int`, e[e.Texture = 1] = `Texture`, e[e.FVec4 = 2] = `FVec4`, e[e.Mat4 = 3] = `Mat4`, e[e.FVec2 = 4] = `FVec2`, e[e.Float = 5] = `Float`, e[e.FVec3 = 6] = `FVec3`, e[e.FloatArray = 7] = `FloatArray`, e[e.FVec4Array = 8] = `FVec4Array`, e
}({});
const Xg = {
    placeholderImageDataEmpty: void 0,
    placeholderTextureEmpty: void 0,
    placeholderImageDataGrey128: void 0,
    placeholderTextureGrey128: void 0,
    placeholderTexture: void 0,
    placeholderFbo: void 0
};
var Zg = class e {
    static getExtension(t, n) {
        if (e.glExtensions.has(n) || e.setExtension(t, n)) return e.glExtensions.get(n)
    }
    static setExtension(t, n) {
        var r;
        if ((r = t.getSupportedExtensions()) != null && r.includes(n)) {
            let r = t.getExtension(n);
            if (r) return e.glExtensions.set(n, r), !0;
            console.error(`[GlExtension] could not retrieve ${n} extension context`)
        }
        return console.error(`[GlExtension] Extension ${n} does not exist or is not supported by the device`), !1
    }
    static unloadExtensions() {
        e.glExtensions.clear()
    }
};
C(Zg, `glExtensions`, new Map);

function Qg(e, t, n) {
    let r = e.createProgram();
    if (!r) throw new Jg(`Failed to create program`);
    if (e.attachShader(r, t), e.attachShader(r, n), e.linkProgram(r), !e.getProgramParameter(r, e.LINK_STATUS)) {
        let t = e.getProgramInfoLog(r);
        throw new Jg(`Failed to link shader program`, {
            additionalInfo: {
                programLog: t == null ? `` : t
            }
        }, !0)
    }
    return r
}

function $g(e, t, n) {
    let r = e.createShader(n);
    if (!r) throw new Jg(`Failed to create shader object`);
    e.shaderSource(r, t), e.compileShader(r);
    let i = e.getShaderParameter(r, e.COMPILE_STATUS);
    if (!i) {
        let a = e.getShaderInfoLog(r),
            o = n === e.VERTEX_SHADER ? `VERTEX` : `FRAGMENT`,
            s = u_(t),
            c = ``;
        s || (c = t.length > 255 ? t.substring(0, 255) + `...` : t);
        let l = `${o} shader compilation failed`,
            u = {},
            d = e.isContextLost();
        throw d || (u = {
            lastGlError: String(e.getError()),
            glVersion: e.getParameter(e.VERSION),
            glslVersion: e.getParameter(e.SHADING_LANGUAGE_VERSION),
            renderer: e.getParameter(e.RENDERER)
        }), new Jg(l, {
            additionalInfo: w({
                filename: s == null ? `unknown` : s,
                shaderLog: a || `No error log provided by driver`,
                compileStatus: String(i),
                contextLost: String(d),
                shaderSource: c
            }, u)
        }, !0)
    }
    return r
}

function e_(e) {
    let t = {
            x: 8196,
            y: 8196
        },
        n = e.x > 0 && e.y > 0,
        r = e.x < t.x && e.y < t.y;
    return n && r
}

function t_(e) {
    if (!Xg.placeholderTexture) return;
    let t = e.createFramebuffer();
    t && (e.bindFramebuffer(e.FRAMEBUFFER, t), e.framebufferTexture2D(e.FRAMEBUFFER, e.COLOR_ATTACHMENT0, e.TEXTURE_2D, Xg.placeholderTexture, 0), Xg.placeholderFbo = t, e.bindFramebuffer(e.FRAMEBUFFER, null))
}

function n_(e, t) {
    let n = e.createTexture();
    if (n) return e.bindTexture(e.TEXTURE_2D, n), t instanceof HTMLCanvasElement || t instanceof HTMLImageElement ? e.texImage2D(e.TEXTURE_2D, 0, e.RGBA, e.RGBA, e.UNSIGNED_BYTE, t) : e.texImage2D(e.TEXTURE_2D, 0, e.RGBA, 1, 1, 0, e.RGBA, e.UNSIGNED_BYTE, new Uint8Array([255, 0, 0, 255])), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MAG_FILTER, e.NEAREST), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MIN_FILTER, e.NEAREST), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_S, e.REPEAT), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_T, e.REPEAT), e.bindTexture(e.TEXTURE_2D, null), n
}
async function r_(e) {
    let t = i_();
    if (t) Xg.placeholderImageDataEmpty = await a_(t), Xg.placeholderTextureEmpty = n_(e, t);
    else throw Error(`Failed to create empty placeholder canvas`);
    let n = i_(`rgb(128, 128, 128)`);
    if (n) Xg.placeholderImageDataGrey128 = await a_(n), Xg.placeholderTextureGrey128 = n_(e, n);
    else throw Error(`Failed to create 128 grey placeholder canvas`)
}

function i_(e) {
    let t = document.createElement(`canvas`);
    t.width = 1, t.height = 1;
    let n = t.getContext(`2d`);
    return n ? (n.fillStyle = e == null ? `rgba(0, 0, 0, 0.0)` : e, n.rect(0, 0, 1, 1), n.fill(), t) : null
}

function a_(e) {
    return new Promise(t => {
        e.toBlob(e => {
            let n = new FileReader;
            n.onloadend = () => {
                let e = n.result;
                e && t(e)
            }, e && n.readAsArrayBuffer(e)
        }, `image/png`)
    })
}

function o_(e) {
    let t = 4;
    switch (e) {
        case WebGLRenderingContext.RGBA:
            t = 4;
            break;
        case WebGLRenderingContext.RGB:
            t = 3;
            break;
        case WebGLRenderingContext.LUMINANCE_ALPHA:
            t = 2;
            break;
        case WebGLRenderingContext.LUMINANCE:
        case WebGLRenderingContext.ALPHA:
            t = 1;
            break
    }
    if (kv.isWebGl2) switch (e) {
        case WebGL2RenderingContext.RG8:
            t = 2;
            break;
        case WebGL2RenderingContext.R8:
            t = 1;
            break
    }
    return t
}

function s_(e) {
    let t = e;
    if (!kv.isWebGl2) return t;
    switch (e) {
        case WebGL2RenderingContext.RG8:
            t = WebGL2RenderingContext.RG;
            break;
        case WebGL2RenderingContext.R8:
            t = WebGL2RenderingContext.RED;
            break
    }
    return t
}

function c_(e, t) {
    let n = e.getError();
    return n > 0 ? (console.error(`%c [GlError] WebGL error occurred - errno: %c${n} %c(${t})`, `color:white`, `color:red`, `color:white`), !1) : !0
}

function l_(e, t) {
    if (t.emitToElastic) {
        let n = {
            webglVersion: kv.context
        };
        O(e, t.message, t, {
            extra: w(w({}, n), t.additionalInfo)
        })
    }
}

function u_(e) {
    for (let t of [/\/\/\s*file:\s*(.+)/i, /\/\*\s*file:\s*(.+?)\s*\*\//i, /#define\s+FILE\s+"(.+?)"/i]) {
        let n = e.match(t);
        if (n && n[1]) return n[1].trim()
    }
    return null
}
var d_ = b({
    createGradientObject: () => g_,
    dataQualityToZoomOffset: () => v_,
    decodeHeader: () => p_,
    decodeImage: () => b_,
    decodeImageBytesCompact: () => y_,
    decodedTileDataSize: () => 257,
    imageBitmapToUint8Array: () => h_,
    prepareRainPattern: () => __,
    processHeader: () => m_,
    tileLayerZoomBounds: () => f_
});
const f_ = {
    x: 2,
    y: 11
};

function p_(e, t) {
    let n, r, i, a, o = new ArrayBuffer(28),
        s = new Uint8Array(o),
        c = new Float32Array(o),
        l = t * 4 * 4 + 8;
    for (a = 0; a < 28; a++) n = e[l], r = e[l + 1], i = e[l + 2], n = Math.round(n / 64), r = Math.round(r / 16), i = Math.round(i / 64), s[a] = (n << 6) + (r << 2) + i, l += 16;
    return c
}

function m_(e) {
    return {
        decoderRmin: e[0],
        decoderRstep: (e[1] - e[0]) / 255,
        decoderGmin: e[2],
        decoderGstep: (e[3] - e[2]) / 255,
        decoderBmin: e[4],
        decoderBstep: (e[5] - e[4]) / 255
    }
}

function h_(e) {
    let t = document.createElement(`canvas`);
    t.width = e.width, t.height = e.height;
    let n = t.getContext(`2d`, {
        desynchronized: !0,
        willReadFrequently: !0
    });
    if (!n) throw Error(`Could not get 2D context`);
    n.drawImage(e, 0, 0);
    let r = n.getImageData(0, 0, t.width, t.height);
    return new Uint8Array(r.data.buffer)
}

function g_(e, t) {
    let n = 2048;
    try {
        let r = t.steps,
            i = r,
            a = 1;
        i > n && (i = n, a = r / i);
        let o = 1 << Math.round(Math.log2(i));
        o < i && (o += o);
        let s = t.max - t.min,
            c = i / (s * o),
            l = -c * t.min,
            u = o << 2,
            d = t.createGradientArray(!1, !1, a);
        if (d.byteLength < u) {
            let e = new Uint8Array(u);
            if (e.set(d), d.byteLength > 7) {
                let t = new Uint8Array(4);
                for (let e = 0; e < 4; e++) t[e] = d[d.byteLength - 8 + e];
                for (let n = d.byteLength - 4; n < u; n += 4) e.set(t, n)
            }
            d = e
        } else d.byteLength > u && (d = new Uint8Array(d.buffer, 0, u));
        let f = new Sg(e);
        return f.resize(e, {
            x: o,
            y: 1
        }), f.bind(e, e.CLAMP_TO_EDGE, e.LINEAR), f.updateContent(e, [d, {
            x: o,
            y: 1
        }]), {
            texture: f,
            mul: c,
            add: l
        }
    } catch (e) {}
    return null
}

function __(e) {
    let t = new Uint8Array(16),
        n = [128, 192, 58, 0],
        r = 0;
    for (let e = 0; e < 2; e++)
        for (let i = 0; i < 2; i++) {
            let a = n[(i & 1) + ((e & 1) << 1)];
            for (let e = 0; e < 4; e++) t[r++] = a
        }
    let i = new Sg(e);
    return i.updateContent(e, [t, {
        x: 2,
        y: 2
    }], e.REPEAT, e.NEAREST), i
}

function v_(e) {
    var t;
    return (t = {
        low: 3,
        normal: 1,
        high: 1,
        ultra: 1,
        extreme: 0
    } [e]) == null ? 0 : t
}

function y_(e) {
    let t = 257 * 4,
        n = new Uint8Array(257 * t);
    return n.set(e.subarray(8 * t, 265 * t)), n
}
async function b_(e) {
    return x_(y_(e), 257, 257)
}

function x_(e, t, n) {
    let r = document.createElement(`canvas`);
    r.width = t, r.height = n;
    let i = r.getContext(`2d`);
    if (!i) throw Error(`Could not get 2D context`);
    let a = new Uint8ClampedArray(e.buffer, e.byteOffset, e.byteLength),
        o = new ImageData(a, t, n);
    return i.putImageData(o, 0, 0), createImageBitmap(r)
}
var S_ = b({
    extractTileHeader: () => T_,
    fetchImageBlob: () => w_,
    tileLayerSource: () => C_
});
const C_ = new class extends Ln {
    constructor() {
        var e;
        super({
            ident: `TileLayerSource`
        }), e = this, C(this, `_gl`, null), C(this, `_cache`, void 0), C(this, `_canvas`, null), C(this, `_ctx`, null), C(this, `_disposed`, !1), this._cache = new g(e => e, async (t, n) => {
            let r = await w_(t, n);
            if (!r.valid) return {
                valid: !1,
                url: t,
                _debugMessage: r.message
            };
            let i = await createImageBitmap(r.blob);
            if (n != null && n.aborted) return {
                valid: !1,
                url: t,
                _debugMessage: `Aborted`
            };
            let a = e._imageBitmapToUint8Array(i),
                o = p_(a, i.width),
                s = y_(a),
                c = m_(o),
                l = e._gl;
            if (!l || l.isContextLost()) return {
                valid: !1,
                url: t,
                _debugMessage: `Missing WebGL context`
            };
            l.pixelStorei(l.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 0);
            let u = l.createTexture();
            if (!u) throw Error(`Failed to create WebGL texture.`);
            return l.bindTexture(l.TEXTURE_2D, u), l.texParameteri(l.TEXTURE_2D, l.TEXTURE_MIN_FILTER, l.LINEAR), l.texParameteri(l.TEXTURE_2D, l.TEXTURE_MAG_FILTER, l.LINEAR), l.texParameteri(l.TEXTURE_2D, l.TEXTURE_WRAP_S, l.CLAMP_TO_EDGE), l.texParameteri(l.TEXTURE_2D, l.TEXTURE_WRAP_T, l.CLAMP_TO_EDGE), l.texImage2D(l.TEXTURE_2D, 0, l.RGBA, 257, 257, 0, l.RGBA, l.UNSIGNED_BYTE, s), l.bindTexture(l.TEXTURE_2D, null), {
                valid: !0,
                header: c,
                tex: u,
                url: t
            }
        }, e => {
            this.emit(`keydeleted`, e.url), e.valid && this._gl && !this._gl.isContextLost() && this._gl.deleteTexture(e.tex)
        })
    }
    init(e) {
        if (this._disposed) throw E_();
        this._gl = e.maplibreMap.painter.context.gl
    }
    async get(e, t) {
        var n = this;
        if (n._disposed) throw E_();
        if (!n._gl) throw D_();
        return await n._cache.get(e, t)
    }
    async awaitTile(e, t) {
        var n = this;
        if (n._disposed) throw E_();
        if (!n._gl) throw D_();
        return await n._cache.awaitLoad(e, t)
    }
    free(e) {
        if (this._disposed) throw E_();
        this._cache.free(e)
    }
    dispose() {
        if (this._disposed) throw E_();
        this._cache.dispose(), this._gl = null, this._ctx = null, this._canvas = null, this._disposed = !0
    }
    _imageBitmapToUint8Array(e) {
        if (this._canvas || (this._canvas = document.createElement(`canvas`)), !this._ctx) {
            let e = this._canvas.getContext(`2d`, {
                desynchronized: !0,
                willReadFrequently: !0
            });
            if (!e) throw Error(`Could not get 2D context`);
            this._ctx = e
        }
        return this._canvas.width = e.width, this._canvas.height = e.height, this._ctx.drawImage(e, 0, 0), this._ctx.getImageData(0, 0, this._canvas.width, this._canvas.height).data
    }
};
async function w_(e, t) {
    try {
        let n = await fetch(e, {
            signal: t
        });
        return n.status === 200 ? {
            valid: !0,
            blob: await n.blob()
        } : {
            valid: !1,
            message: `Got status ${n.status} ${n.statusText}`
        }
    } catch (e) {
        var n;
        return {
            valid: !1,
            message: `Got exception: ${e} Message: ${(n = e == null ? void 0 : e.message) == null ? `(undefined)` : n}`
        }
    }
}
async function T_(e) {
    let t = h_(e),
        n = p_(t, e.width);
    return {
        image: await b_(t),
        header: m_(n)
    }
}

function E_() {
    return Error(`Attempted to use a disposed TileLayerSource.`)
}

function D_() {
    return Error(`Attempted to use an uninitialized TileLayerSource.`)
}
var O_ = `#define GLSLIFY 1
vec4 sampleTileOrParent(vec2 uv,bool isParent){if(isParent){return texture2D(u_image1,uv);}return texture2D(u_image0,uv);}vec4 pixelTransform(vec4 surfTexColor,bool isParent){vec4 surfaceColor=surfTexColor;
#ifdef MASK
bool parent=false;vec2 tc=parent ? v_pos1.xy : v_pos0.xy;float threshold=1200.0/256.0;float pxSize=1.0/256.0;mediump float u2=tc.x-pxSize;mediump float u1=tc.x;mediump float u3=tc.x+pxSize;mediump float v1=tc.y;mediump float v2=tc.y-pxSize;mediump float v3=tc.y+pxSize;float aL=sampleTileOrParent(vec2(u2,v1),parent).a;float aM=sampleTileOrParent(vec2(u1,v1),parent).a;float aR=sampleTileOrParent(vec2(u3,v1),parent).a;float aB=sampleTileOrParent(vec2(u1,v2),parent).a;float aT=sampleTileOrParent(vec2(u1,v3),parent).a;float a=aL+aM+aR+aB+aT;float alpha=a>threshold ? 0.0 : 1.0;
#ifdef SEA
alpha=1.0-alpha;
#endif
surfaceColor=vec4(vec3(0.5),alpha);
#endif
#ifdef COLORED
vec3 sea=vec3(0.114,0.22,0.51);vec3 land=vec3(0.176,0.266,0.0);surfaceColor=vec4(mix(sea,land,surfTexColor.a),1.0);
#endif
return surfaceColor;}`,
    k_ = b({
        createLandLayer: () => A_
    });

function A_(e, t) {
    let n = [];
    switch (t) {
        case `sea-mask`:
            n.push(`MASK`, `SEA`);
            break;
        case `land-mask`:
            n.push(`MASK`);
            break;
        case `colored`:
            n.push(`COLORED`);
            break
    }
    return new v(e, {
        minZoom: 2,
        maxZoom: 11,
        keepBuffer: S ? 1 : 4,
        customShader: {
            pixelTransform: n.map(e => `#define ${e}`).join(`
`).concat(O_, `
`)
        },
        layerBucketId: t === `colored` ? $_.LANDSEA_MASK_COLORED : $_.LANDMASK_SEAMASK,
        layerId: `webgl-land_${t}`
    })
}

function j_(e) {
    return j_ = Object.setPrototypeOf ? Object.getPrototypeOf.bind() : function(e) {
        return e.__proto__ || Object.getPrototypeOf(e)
    }, j_(e)
}

function M_(e, t) {
    for (; !{}.hasOwnProperty.call(e, t) && (e = j_(e)) !== null;);
    return e
}

function N_() {
    return N_ = typeof Reflect < `u` && Reflect.get ? Reflect.get.bind() : function(e, t, n) {
        var r = M_(e, t);
        if (r) {
            var i = Object.getOwnPropertyDescriptor(r, t);
            return i.get ? i.get.call(arguments.length < 3 ? e : n) : i.value
        }
    }, N_.apply(null, arguments)
}

function P_(e, t, n, r) {
    var i = N_(j_(1 & r ? e.prototype : e), t, n);
    return 2 & r && typeof i == `function` ? function(e) {
        return i.apply(n, e)
    } : i
}
var F_;
const I_ = new Set([`capAlerts`, `radar`, `satellite`, `wetbulbtemp`, `topoMap`]),
    L_ = new Set([`efi`]),
    R_ = new Set([`wind`, `temp`]);
var z_ = class e extends r {
    constructor(t) {
        super(w(w({}, e.defaultOptions), t)), C(this, `product`, void 0), C(this, `cityDivs`, {}), C(this, `ts`, M.get(`timestamp`)), C(this, `hasHooks`, !1), C(this, `forecastLoaded`, !1), C(this, `tilesUrl`, void 0), C(this, `refTime`, void 0), C(this, `temperatureUnit`, void 0)
    }
    onAdd(e) {
        return this.hasHooks || (this.updateProduct(), this.createTilesUrl(), ud.on(`poi-label`, this.onClick, this), M.on(`timestamp`, this.onTsChange, this), M.on(`usedLang`, this.updateLabels, this), M.on(`englishLabels`, this.updateLabels, this), M.on(`product`, this.updateProduct.bind(this, !0)), M.on(`overlay`, this.updateProduct.bind(this, !0)), M.on(`pois`, this.updateProduct.bind(this, !0)), N.on(`metricChanged`, this.onMetricChanged, this), this.hasHooks = !0), super.onAdd(e)
    }
    onRemove(e) {
        return this.hasHooks && (ud.off(`poi-label`, this.onClick, this), M.off(`timestamp`, this.onTsChange, this), M.off(`usedLang`, this.updateLabels, this), M.off(`englishLabels`, this.updateLabels, this), M.off(`product`, this.updateProduct.bind(this, !0)), M.off(`overlay`, this.updateProduct.bind(this, !0)), M.off(`pois`, this.updateProduct.bind(this, !0)), N.off(`metricChanged`, this.onMetricChanged, this), this.hasHooks = !1), super.onRemove(e)
    }
    createTilesUrl() {
        let e = M.get(`englishLabels`) ? `en` : M.get(`usedLang`);
        this.tilesUrl = `https://tiles.windy.com/labels/v2.1/${e}`
    }
    updateLabels() {
        this.createTilesUrl(), this._reset()
    }
    async updateProduct(e) {
        var t = this;
        let n = M.get(`product`);
        K[n].labelsTemp || (n = `ecmwf`);
        let r = await K[n].getRefTime();
        if (!(t.forecastLoaded && t.product === n && t.refTime === r) && (t.product = n, t.refTime = r, e))
            for (let e in t.cityDivs) t.loadTileForecast(t.cityDivs[e])
    }
    onClick(e) {
        let {
            id: t,
            label: n
        } = e.dataset;
        if (!t) return;
        let [r, i] = t.split(`/`);
        N.emit(`rqstOpen`, `detail`, {
            lat: +r,
            lon: +i,
            name: n,
            id: t,
            source: `label`
        })
    }
    onTsChange(e) {
        this.ts = e, this.refreshWeather()
    }
    onMetricChanged(e, t) {
        e === `temp` && (this.temperatureUnit = t, this.refreshWeather())
    }
    refreshWeather() {
        for (let e in this.cityDivs) {
            let {
                labels: t,
                timestamps: n
            } = this.cityDivs[e], r = this.getIndexToCityTileData(n);
            for (let e = 0; e < t.length; e++) this.renderWeather(t[e], r)
        }
    }
    _reset() {
        this.reload()
    }
    toArray() {
        let e = [];
        for (let t in this.cityDivs) e = e.concat(this.cityDivs[t].labels);
        return e
    }
    getCityDivs() {
        let e = [];
        for (let t in this.cityDivs) e.push(this.cityDivs[t]);
        return e
    }
    loadTileForecast(e) {
        let t = M.get(`overlay`),
            n = M.get(`product`),
            r = M.get(`pois`);
        I_.has(t) || L_.has(n) || R_.has(r) || r === `cities` && t !== `temp` || e.labels.length && e.urlFrag && this.product && Bp(this.product, e.urlFrag).then(t => {
            t != null && t.data ? (this.onForecastLoaded(e, t.data), this.forecastLoaded = !0) : e.labels.forEach(e => {
                e.data = void 0, e.el.removeAttribute(`data-temp`)
            })
        }).catch(t => {
            console.error(`Failed to load city forecast "${e.urlFrag}"`, t)
        })
    }
    onForecastLoaded(e, t) {
        if (!t || typeof t != `object`) {
            e.labels.forEach(e => {
                e.data = void 0, e.el.removeAttribute(`data-temp`)
            });
            return
        }
        let {
            forecast: n,
            reftime: r,
            hours: i
        } = t;
        e.timestamps = i.map(e => r + e * T);
        let a = this.getIndexToCityTileData(e.timestamps);
        e.labels.forEach(e => {
            let {
                id: t
            } = e;
            t in n ? (e.data = n[t], this.renderWeather(e, a)) : (e.data = void 0, e.el.removeAttribute(`data-temp`))
        })
    }
    async _loadTileData(e, t) {
        var n = this;
        let r = `${e.z}/${e.x}/${e.y}`;
        try {
            return (await F(`${n.tilesUrl}/${r}.json`, {
                cache: !1,
                abortSignal: t
            })).data
        } catch (e) {
            return null
        }
    }
    _createTileContents(e, t, n) {
        e.classList.add(`leaflet-tile`), e.classList.add(`zoom${t.z}`), e.onselectstart = e.onmousemove = te;
        let r = re(t),
            i = `${r.z}/${r.x}/${r.y}`,
            a = this.renderTile(e, r, n);
        this.cityDivs[t.x + `:` + t.y] = a, a.urlFrag = i, this.loadTileForecast(a), this.fire(`labelsLayerTileLoaded`, {
            tile: a
        })
    }
    renderTile(e, t, r) {
        let i = this._physicalTileSize.x,
            a = [],
            o = this._contentScale;
        for (let c = 0; c < r.length; ++c) {
            var s;
            let [l, u, d, f, p, m] = r[c], h = d.substring(0, 2) !== `ci`, g = h ? l : `${p}/${f}`, _ = n.create(`div`, `leaflet-gridlayer-feature`), v = 1 << t.z, ee = {
                x: kt(f),
                y: jt(p)
            }, te = {
                x: t.x / v,
                y: t.y / v
            }, y = {
                x: (t.x + 1) / v,
                y: (t.y + 1) / v
            }, ne = {
                x: y.x - te.x,
                y: y.y - te.y
            }, re = {
                x: (ee.x - te.x) / ne.x * i,
                y: (ee.y - te.y) / ne.y * i
            };
            _.textContent = _.dataset.label = u, _.dataset.id = g, _.dataset.poi = `label`, _.classList.add(...(s = d.match(/\S+/g)) == null ? [] : s), _.style.transform = `translate(-50%, -50%) translate(${re.x}px, ${re.y}px) scale(${1 / o})`, _.style.width = `${m}px`, h || a.push({
                id: g,
                el: _
            }), e.appendChild(_), e.classList.add(`leaflet-tile-loaded`)
        }
        return {
            labels: a
        }
    }
    getIndexToCityTileData(e) {
        if (e != null && e.length) return qc(e, this.ts, !1)
    }
    renderWeather(e, t) {
        if (!e || !e.el) return;
        let {
            el: n,
            data: r
        } = e;
        if (!(r != null && r.length)) {
            n.removeAttribute(`data-temp`);
            return
        }
        t !== void 0 && t >= 0 && t < r.length && r[t] !== null ? n.dataset.temp = `${Is.temp.convertNumber(r[t])}°` : n.removeAttribute(`data-temp`)
    }
};
F_ = z_, C(z_, `defaultOptions`, w(w({}, P_(F_, `defaultOptions`, F_)), {}, {
    minZoom: 3,
    maxZoom: 11,
    pane: `markerPane`,
    className: `labels-layer`,
    keepBuffer: S ? 1 : 2,
    tileSize: r.getTileSizeForZoomOffset(.5)
}));
var B_ = b({
    cityLabels: () => W_,
    disable: () => H_,
    enable: () => U_
});
const V_ = `city-labels-disabled`,
    H_ = () => {
        document.body.classList.add(V_)
    },
    U_ = () => {
        document.body.classList.remove(V_)
    },
    W_ = new z_;
var G_ = b({
    centerMap: () => tv,
    ensurePointVisibleY: () => nv,
    getMapTiles: () => hv,
    hasMask: () => dv,
    isGlobeActive: () => gv,
    layerOrder: () => $_,
    map: () => Z,
    markers: () => ev,
    panToOffset: () => rv,
    setTileLayerLoader: () => Dv,
    toggleLandMask: () => fv,
    toggleLandSeaMaskColored: () => mv,
    toggleSeaMask: () => pv,
    whenMapInitialized: () => yv
});
i.defaultOptions.imagePath = `https://www.windy.com/img/leaflet/`, f.defaultOptions.icon = new i.Default, a.defaultImagePath = `https://www.windy.com/img/leaflet/`;
let K_ = 0;
const q_ = M.get(`startUp`);
let J_ = M.get(`startUpZoom`),
    Y_, X_ = [];
if (_h) Y_ = _h, J_ = null;
else switch (q_) {
    case `last`:
        Y_ = M.get(`startUpLastPosition`) || jh();
        break;
    case `location`:
        Y_ = M.get(`homeLocation`) || jh();
        break;
    case `ip`:
        Y_ = M.get(`ipLocation`) || jh();
        break;
    case `gps`:
        Y_ = M.get(`gpsLocation`) || jh();
        break;
    default:
        Y_ = jh()
}
const Z_ = e => e === `vn` || e === `in`,
    Q_ = Z_(M.get(`country`)) ? 11 : 16,
    $_ = {
        LANDSEA_MASK_COLORED: 100,
        MAIN: 200,
        SATELLITE: 210,
        RADAR: 225,
        PARTICLES: 250,
        LANDMASK_SEAMASK: 300,
        BASE_MAP: 400,
        PARTICLES_HIGH_ZOOM: 450,
        AIRSPACES: 500,
        WEBGL_POIS: 550,
        HURRICANES: 600,
        ISOLINES: 700
    },
    Z = new l(`leaflet-map`, {
        center: new o(+Y_.lat, +Y_.lon),
        zoom: J_ || (`zoom` in Y_ ? Y_.zoom : 5),
        minZoom: 3,
        maxZoom: Q_,
        attributionControl: !1,
        maxCanvasRatio: 2
    });
C_.init(Z);
const ev = {
    icon: new t({
        className: `icon-dot`,
        html: `<div class="icon-pulsating"></div>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5]
    }),
    pulsatingIcon: new t({
        className: `icon-dot`,
        html: `<div class="icon-pulsating repeat"></div>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5]
    }),
    webcamIcon: new t({
        className: `iconfont icon-webcam`,
        iconSize: [10, 10],
        iconAnchor: [5, 5]
    }),
    pulsatingWebcamIcon: new t({
        className: `iconfont icon-webcam`,
        html: `<div class="icon-pulsating repeat"></div>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5]
    }),
    myLocationIcon: new t({
        className: `icon-my-position`,
        html: `<img src="/img/maps/actual-pos-no-heading.png" />`,
        iconSize: [16, 16],
        iconAnchor: [8, 8]
    })
};

function tv(e, t = !1) {
    let n = e.zoom ? D(e.zoom, 3, 20) : Z.maplibreMap.getZoom() + 1;
    if (e.paddingTop || e.paddingLeft) {
        let r = e.paddingTop || 0,
            i = e.paddingLeft || 0,
            a = Z.project([e.lat, e.lon], n).subtract([i / 2, r / 2]),
            o = Z.unproject(a, n);
        Z.setView(o, n, {
            animate: t
        })
    } else Z.setView([e.lat, e.lon], n, {
        animate: t
    })
}

function nv(e, t, n) {
    let r = Z.latLngToContainerPoint([e, t]).y,
        i = Z.getSize();
    r > i.y - n && Z.panBy([0, r - (i.y - n)], {
        animate: !0,
        duration: 250
    })
}

function rv(e, t, n) {
    let r = Z.maplibreMap.getZoom() + 1,
        i = Z.getSize().y,
        a = Z.project([t, n], r).subtract([0, e - i / 2]),
        o = Z.unproject(a, r);
    Z.setView(o, r, {
        animate: !1
    })
}
`source` in Y_ && Y_.source === `fallback` && N.once(`newLocation`, e => {
    e.zoom = 5, tv(e, !0)
});
let iv = null;

function av(e) {
    e && !iv && (iv = new c({
        color: `#444`
    }).addTo(Z)), !e && iv && (Z.removeLayer(iv), iv = null)
}

function ov() {
    let e = Z.getCenter(),
        t = Math.round(Z.maplibreMap.getZoom()) + 1;
    M.set(`mapCoords`, {
        source: `maps`,
        lat: e.lat,
        lon: e.wrap().lng,
        zoom: t
    }), t !== K_ && (ce(/zoom\d+/, `zoom${t}`), K_ = t)
}
let sv, cv, lv;
const {
    landmaskmap: uv
} = Jh();
let dv = !1;

function fv(e) {
    e ? (lv && Z.hasLayer(lv) && Z.removeLayer(lv), cv && Z.hasLayer(cv) && Z.removeLayer(cv), sv || (sv = A_(uv, `land-mask`)), sv.addTo(Z), dv = !0) : !e && sv && (Z.hasLayer(sv) && Z.removeLayer(sv), dv = !1)
}

function pv(e) {
    e ? (lv && Z.hasLayer(lv) && Z.removeLayer(lv), sv && Z.hasLayer(sv) && Z.removeLayer(sv), cv || (cv = A_(uv, `sea-mask`)), cv.addTo(Z), dv = !0) : !e && cv && (Z.hasLayer(cv) && Z.removeLayer(cv), dv = !1)
}

function mv(e) {
    e ? (cv && Z.hasLayer(cv) && Z.removeLayer(cv), sv && Z.hasLayer(sv) && Z.removeLayer(sv), lv || (lv = A_(`https://tiles.windy.com/tiles/v11.2/grayland/{z}/{x}/{y}.png`, `colored`)), lv.addTo(Z), dv = !0) : lv && !e && (Z.hasLayer(lv) && Z.removeLayer(lv), dv = !1)
}
ov(), av(M.get(`graticule`)), Z.maplibreMap.on(`moveend`, ov), Z.leafletMap.on(`click`, md), N.on(`leafletGl-zoomIn`, () => {
    Z.zoomIn(1, {
        animate: !0
    })
}), N.on(`leafletGl-zoomOut`, () => {
    Z.zoomOut(1, {
        animate: !0
    })
}), M.on(`map`, () => Xh()), M.on(`graticule`, av), eg.on(`toggleSeaMask`, pv), eg.on(`toggleLandMask`, fv), eg.on(`toggleLandSeaMaskColored`, mv), Z.on(`contextmenu`, e => {
    let {
        containerPoint: t
    } = e, {
        lat: n,
        lng: r
    } = e.latlng instanceof o ? e.latlng.wrap() : e.latlng;
    S || N.emit(`rqstOpen`, `contextmenu`, {
        lat: n,
        lon: r,
        containerPoint: t
    })
}), M.on(`usedLang`, () => Xh()), M.once(`country`, e => {
    Z_(e) && (Z.setMaxZoom(11), Xh())
});
const hv = Jh,
    gv = () => M.get(`mapLibrary`) === `globe`;
let _v = !1;
Z.maplibreMap.once(`load`, Sv);
const vv = [];

function yv(e) {
    _v ? e() : vv.push(e)
}
Xh();

function bv() {
    vv.forEach(e => {
        e()
    })
}

function xv() {
    let e = Z.maplibreMap._container.style.height;
    Z.maplibreMap._container.style.height = `calc(${e} - 1px)`, Z.maplibreMap.once(`render`, () => {
        Z.maplibreMap._container.style.height = e
    })
}
async function Sv() {
    W_ == null || W_.addTo(Z), Kv(), Ng(Z.maplibreMap.painter.context.gl, `map`), _v = !0, Cv(), bv(), xv()
}

function Cv() {
    document.addEventListener(`touchstart`, wv), document.addEventListener(`touchend`, Tv), eg.on(`contextRestored`, () => {
        window.location.reload()
    })
}

function wv(e) {
    let t = e.touches;
    if (t.length > 1)
        for (let e = 0; e < t.length; e++) {
            let r = t.item(e);
            if (!r) continue;
            let i = r.target;
            if (i.hasAttribute(`data-poi`)) {
                var n;
                let e = (n = i.parentElement) == null ? void 0 : n.removeChild(i);
                if (!e) continue;
                e.style.visibility = `hidden`;
                let t = document.querySelector(`.maplibregl-canvas-container`);
                t && (t.appendChild(e), X_.push(e))
            }
        }
}

function Tv(e) {
    X_.forEach(e => {
        var t;
        (t = e.parentElement) == null || t.removeChild(e)
    }), X_ = []
}
const Ev = new Set;

function Dv(e, t) {
    t ? Ev.add(e) : Ev.delete(e);
    let n = Ev.size > 0;
    document.getElementsByTagName(`body`)[0] && (n ? document.body.classList.add(`loading-path`) : document.body.classList.remove(`loading-path`))
}
var Ov = b({
    MAPLIBRE_TILE_SIZE: () => 512,
    createPlaceholderImage: () => Gv,
    createPlaceholderImageCanvas: () => Wv,
    geoBoundsToMaplibreBounds: () => Rv,
    getSafeZoom: () => Av,
    getTileBounds: () => Pv,
    getWorldVisibleRectOffsets: () => jv,
    latLonBounds2TileBounds: () => Iv,
    lngLatBoundsToMercator: () => Mv,
    queryWebGlVersion: () => Kv,
    tileBoundsToLatLonBounds: () => Fv,
    tilePaddingSize: () => Nv,
    tileSizeToZoomOffset: () => Lv,
    utils: () => kv
});
const kv = {
    isWebGl2: !1,
    context: `WGL1`
};

function Av(e, t) {
    let n = Z.maplibreMap.getZoom() + (e == null ? 0 : e),
        r = Math.round(n);
    return Math.min(r, t || r)
}

function jv() {
    let e = [],
        t = Z.maplibreMap.getBounds(),
        n = {
            min: p.fromLngLat({
                lng: t._sw.lng,
                lat: t._sw.lat
            }),
            max: p.fromLngLat({
                lng: t._ne.lng,
                lat: t._ne.lat
            })
        },
        r = Math.floor(n.min.x),
        i = Math.floor(n.max.x);
    for (let t = r; t <= i; t++) e.push(t);
    return e
}

function Mv(e) {
    return {
        min: p.fromLngLat({
            lng: e._sw.lng,
            lat: e._sw.lat
        }),
        max: p.fromLngLat({
            lng: e._ne.lng,
            lat: e._ne.lat
        })
    }
}
const Nv = .25;

function Pv(e, t = !0) {
    let n = Z.maplibreMap.getBounds();
    {
        let t = 360 / 2 ** e * Nv;
        n._ne.lng += t, n._sw.lng -= t;
        let r = Bv(Hv(n._sw.lat, e, !1) + Nv, e),
            i = Bv(Hv(n._ne.lat, e, !1) - Nv, e);
        n._ne.lat = i, n._sw.lat = r
    }
    let r = Iv(n, e);
    t && r.min.x < 0 && (r.min.x += 2 ** e, r.max.x += 2 ** e);
    let i = r.min.y;
    return r.min.y = Math.max(r.max.y, 0), r.max.y = Math.min(i, 2 ** e - 1), r
}

function Fv(e, t) {
    return new d(new u(zv(e.min.x, t), Bv(e.max.y + 1, t)), new u(zv(e.max.x + 1, t), Bv(e.min.y, t)))
}

function Iv(e, t) {
    return e instanceof d ? {
        min: {
            x: Vv(e._sw.lng, t),
            y: Hv(e._sw.lat, t)
        },
        max: {
            x: Vv(e._ne.lng, t),
            y: Hv(e._ne.lat, t)
        }
    } : {
        min: {
            x: Vv(e.min.x, t),
            y: Hv(e.min.y, t)
        },
        max: {
            x: Vv(e.max.x, t),
            y: Hv(e.max.y, t)
        }
    }
}

function Lv(e) {
    return Math.log2(512 / e)
}

function Rv(e) {
    let t = e.getSouthWest(),
        n = e.getNorthEast();
    return [
        [t.lng, t.lat],
        [n.lng, n.lat]
    ]
}

function zv(e, t) {
    return (e / 2 ** t - .5) * 360
}

function Bv(e, t) {
    let n = .5 - e / 2 ** t;
    return (Math.PI / 2 - 2 * Math.atan(Math.exp(-n * 2 * Math.PI))) * (180 / Math.PI)
}

function Vv(e, t) {
    let n = 2 ** t * (e / 360 + .5);
    return Math.floor(n)
}

function Hv(e, t, n = !0) {
    let r = Math.PI / 180,
        i = Math.sin(e * r),
        a = 2 ** t * (.5 - .25 * Math.log((1 + i) / (1 - i)) / Math.PI);
    return n ? Math.floor(a) : a
}
const Uv = (e, t) => {
    e.width != 256 && (e.width = e.height = 256);
    let n = e.getContext(`2d`);
    n.fillStyle = `#888`, n.fillRect(0, 0, 256, 256), n.fillStyle = n.strokeStyle = `#BBB`, n.fillText(`No data!`, 14, 22), n.rect(3, 3, 250, 250), n.stroke()
};

function Wv(e, t) {
    let n = document.createElement(`canvas`);
    if (n.width = 1, n.height = 1, e) Uv(n, ``);
    else {
        let e = n.getContext(`2d`);
        if (!e) throw Error(`Failed to get 2D context`);
        e.fillStyle = t == null ? `red` : t, e.fillRect(0, 0, 1, 1)
    }
    return n
}

function Gv(e, t) {
    let n = Wv(e, t),
        r = new Image;
    return r.src = n.toDataURL(), new Promise(e => {
        r.onload = () => {
            e(r)
        }
    })
}

function Kv() {
    let e = !(Z.maplibreMap.painter.context.gl instanceof WebGLRenderingContext);
    kv.isWebGl2 = e, kv.context = e ? `WGL2` : `WGL1`
}
var qv = b({
        Throttler: () => Jv
    }),
    Jv = class {
        constructor(e) {
            C(this, `_workItemEnergyAvailable`, 1), C(this, `_workItems`, []), C(this, `_map`, void 0), C(this, `_interval`, void 0), C(this, `_lastFrameTime`, void 0), C(this, `_maxRefreshMs`, 100), C(this, `energyPerFrame`, 1), C(this, `maxAccumulatedEnergy`, 1), C(this, `_onNewFrame`, () => {
                this._lastFrameTime = performance.now();
                let e = [];
                for (let t of this._workItems) t.abort && t.abort.aborted ? t.action() : e.push(t);
                for (this._workItems = e; this._workItems.length > 0;) {
                    let e = null,
                        t = -1;
                    for (let n = 0; n < this._workItems.length; n++) {
                        let r = this._workItems[n];
                        (!e || e.priority < r.priority) && (e = r, t = n)
                    }
                    if (e && Math.min(this.maxAccumulatedEnergy, e.weight) <= this._workItemEnergyAvailable) e.action(), this._workItems.splice(t, 1), this._workItemEnergyAvailable -= e.weight;
                    else break
                }
                this._workItemEnergyAvailable < this.maxAccumulatedEnergy && (this._workItemEnergyAvailable += this.energyPerFrame)
            }), this._map = e, this._map.maplibreMap.on(`render`, this._onNewFrame), this._lastFrameTime = performance.now(), this._interval = setInterval(() => {
                performance.now() - this._lastFrameTime >= this._maxRefreshMs && this._onNewFrame()
            }, this._maxRefreshMs + 1)
        }
        async awaitThrottled(e, t = 0, n = 1) {
            var r = this;
            return new Promise(i => {
                r._workItems.push({
                    priority: t,
                    weight: n,
                    action: i,
                    abort: e
                })
            })
        }
        dispose() {
            this._map.maplibreMap.off(`render`, this._onNewFrame);
            for (let e of this._workItems) e.action();
            clearInterval(this._interval), this._workItems = [], this._workItemEnergyAvailable = 0
        }
    },
    Yv = b({
        EventManager: () => Xv
    }),
    Xv = class {
        constructor() {
            C(this, `DOMCallbacks`, {}), C(this, `MapLibreCallbacks`, {}), C(this, `storeCallbacks`, {}), C(this, `eventedCallbacks`, {}), C(this, `broadcastCallbacks`, {}), C(this, `mapCallbacks`, {}), C(this, `unsubscribers`, [])
        }
        addDOMListener(e, t, n) {
            let r = `${t}`,
                i = {
                    ref: n,
                    topic: t,
                    target: e
                };
            this.DOMCallbacks[r] || (this.DOMCallbacks[r] = []), this.DOMCallbacks[r].push(i), e.addEventListener(t, i.ref)
        }
        addMapLibreListener(e, t, n) {
            let r = `${t}`,
                i = {
                    ref: n,
                    topic: t,
                    target: e
                };
            this.MapLibreCallbacks[r] || (this.MapLibreCallbacks[r] = []), this.MapLibreCallbacks[r].push(i), e.on(`${t}`, n)
        }
        addStoreListener(e, t) {
            let n = `${e}`,
                r = {
                    ref: t,
                    topic: e
                };
            this.storeCallbacks[n] || (this.storeCallbacks[n] = []), this.storeCallbacks[n].push(r), M.on(e, t)
        }
        addEventedListener(e, t, n) {
            let r = `${String(t)}`,
                i = {
                    ref: n,
                    topic: t,
                    target: e
                };
            this.eventedCallbacks[r] || (this.eventedCallbacks[r] = []), this.eventedCallbacks[r].push(i), e.on(t, n)
        }
        addBroadcastListener(e, t) {
            let n = `${String(e)}`,
                r = {
                    ref: t,
                    topic: e
                };
            this.broadcastCallbacks[n] || (this.broadcastCallbacks[n] = []), this.broadcastCallbacks[n].push(r), N.on(e, t)
        }
        addMapListener(e, t) {
            let n = {
                callback: t,
                topic: e
            };
            this.mapCallbacks[e] || (this.mapCallbacks[e] = []), this.mapCallbacks[e].push(n), Z.maplibreMap.on(e, t)
        }
        addSvelteStoreListener(e, t, n = !1) {
            n ? this.unsubscribers.push(kn(e, t)) : this.unsubscribers.push(e.subscribe(t))
        }
        addMutationObserverListener(e, t, n) {
            let r = new MutationObserver(n);
            r.observe(e, t), this.unsubscribers.push(() => r.disconnect())
        }
        removeListeners() {
            for (let e of Object.values(this.DOMCallbacks))
                for (let {
                        ref: t,
                        topic: n,
                        target: r
                    }
                    of e) r.removeEventListener(n, t);
            for (let e of Object.values(this.MapLibreCallbacks))
                for (let {
                        ref: t,
                        topic: n,
                        target: r
                    }
                    of e) r.off(`${n}`, t);
            for (let e of Object.values(this.storeCallbacks))
                for (let {
                        ref: t,
                        topic: n
                    }
                    of e) M.off(`${n}`, t);
            for (let e of Object.values(this.eventedCallbacks))
                for (let {
                        ref: t,
                        topic: n,
                        target: r
                    }
                    of e) r.off(n, t);
            for (let e of Object.values(this.broadcastCallbacks))
                for (let {
                        ref: t,
                        topic: n
                    }
                    of e) N.off(`${n}`, t);
            for (let e of Object.values(this.mapCallbacks))
                for (let {
                        callback: t,
                        topic: n
                    }
                    of e) Z.maplibreMap.off(n, t);
            this.unsubscribers.forEach(e => e())
        }
    },
    Zv = b({
        getAvailableLevels: () => Qv
    });
const Qv = (e, t) => {
    var n, r;
    let i = K[t],
        a = Is[e],
        o = ((n = a.layers) == null ? [] : n).map(e => Kc[e]).filter(e => {
            var t;
            return (t = e.levels) == null ? void 0 : t.length
        }).map(e => e.levels).filter(e => !!e);
    if ((r = i.levels) != null && r.length && o.push(i.levels), i.levelsOverride) {
        var s;
        let e = i.levelsOverride;
        ((s = a.layers) == null ? [] : s).filter(t => t in e).map(t => e[t]).forEach(e => o.push(e))
    }
    let c = on(o);
    return e !== `wind` && (c = c.filter(e => e !== `100m`)), a.hasMoreLevels || (c = c.slice(0, 1)), c
};
var $v = b({
        Renderer: () => ey
    }),
    ey = class e {
        constructor(e) {
            C(this, `isOpen`, void 0), C(this, `ident`, void 0), C(this, `dependency`, void 0), C(this, `loadedDependency`, void 0), C(this, `userControl`, void 0), C(this, `interpolator`, void 0), C(this, `requiresFullRenderParams`, void 0), Object.assign(this, e)
        }
        static hasProp(e, t) {
            return !!e && typeof e == `object` && t in e
        }
        async open(t, n, r) {
            var i = this;
            let a = e => {
                    i.onopen(e), i.isOpen = !0
                },
                o = i.dependency ? (() => {
                    let e = Y[i.dependency];
                    return e ? e.open() : Promise.resolve(void 0)
                })() : Promise.resolve(void 0),
                s = i.requiresFullRenderParams ? pg(t, n, r) : Promise.resolve(void 0),
                [c] = await Promise.all([s, o]);
            if (!i.dependency) a(c);
            else {
                let t = Y[i.dependency];
                t ? i.loadedDependency = t instanceof q ? t.svelteApp : t.plugin : i.loadedDependency = void 0, e.hasProp(i.loadedDependency, `interpolator`) && (i.interpolator = i.loadedDependency.interpolator), a(c)
            }
        }
        close(e) {
            if (this.isOpen = !1, this.dependency) {
                this.onclose();
                let e = Y[this.dependency];
                e && e.close({
                    disableClosingAnimation: !0
                })
            }
        }
        onopen(t) {
            if (e.hasProp(this.loadedDependency, `onRenderStart`)) {
                let e = this.loadedDependency.onRenderStart;
                if (typeof e == `function`) {
                    let n = this.loadedDependency;
                    e.call(n, t)
                }
            }
        }
        onclose() {
            if (e.hasProp(this.loadedDependency, `onRenderEnd`)) {
                let e = this.loadedDependency.onRenderEnd;
                if (typeof e == `function`) {
                    let t = this.loadedDependency;
                    e.call(t)
                }
            }
        }
        async paramsChanged(t, n, r) {
            var i = this;
            if (e.hasProp(i.loadedDependency, `paramsChanged`)) {
                let e = i.loadedDependency.paramsChanged;
                if (typeof e == `function`)
                    if (i.requiresFullRenderParams) {
                        let a = await pg(t, n, r),
                            o = i.loadedDependency;
                        e.call(o, a)
                    } else {
                        let t = i.loadedDependency;
                        e.call(t)
                    }
            }
        }
        redraw() {
            if (e.hasProp(this.loadedDependency, `redraw`)) {
                let e = this.loadedDependency.redraw;
                if (typeof e == `function`) {
                    let t = this.loadedDependency;
                    e.call(t)
                }
            }
        }
    },
    ty = b({
        PreprocessedTileParams: () => ry,
        TilePreprocessor: () => iy,
        TilePreprocessorType: () => ny
    });
let ny = function(e) {
    return e[e.NONE = 0] = `NONE`, e[e.RADAR_FLOW = 1] = `RADAR_FLOW`, e[e.RADAR_DATA_WEBP = 2] = `RADAR_DATA_WEBP`, e[e.SATELLITE_DATA = 3] = `SATELLITE_DATA`, e[e.SATELLITE_FLOW = 4] = `SATELLITE_FLOW`, e[e.TILE_LAYER = 5] = `TILE_LAYER`, e[e.RADAR_PTYPE = 6] = `RADAR_PTYPE`, e
}({});
var ry = class {
        constructor() {
            C(this, `tileCoords`, void 0), C(this, `payload`, void 0)
        }
    },
    iy = class {},
    ay = `#version 300 es
#define GLSLIFY 1
in vec2 a_pos;out vec2 v_uv;void main(){v_uv=a_pos;gl_Position=vec4(a_pos*2.0f-1.0f,0.0f,1.0f);}`,
    oy = `#version 100
#define GLSLIFY 1
attribute vec2 a_pos;varying vec2 v_uv;void main(){v_uv=a_pos;gl_Position=vec4(a_pos*2.0-1.0,0.0,1.0);}`,
    sy = `#version 100
precision mediump float;
#define GLSLIFY 1
vec4 debugUVBorder(vec2 texCoords,float borderWidth){float edge=min(min(texCoords.s,texCoords.t),min(1.0-texCoords.s,1.0-texCoords.t));float border=step(edge,borderWidth);return vec4(border);}vec3 checker(vec2 fragCoords){const float size=32.0;vec2 f=floor(mod(fragCoords,vec2(size))/vec2(size)+0.5);vec3 c=(mod(f.x+f.y,2.0)==0.0)? vec3(1.0): vec3(0.3);return c;}uniform sampler2D u_channel0;uniform int u_flipY;varying vec2 v_uv;void main(){float t=(u_flipY>0)? v_uv.t : 1.0-v_uv.t;gl_FragColor=texture2D(u_channel0,vec2(v_uv.s,t));}`,
    cy = `#version 100
precision mediump float;
#define GLSLIFY 1
uniform sampler2D u_channel0;varying vec2 v_uv;void main(){gl_FragColor=texture2D(u_channel0,v_uv);}`,
    ly = `#version 100
#define GLSLIFY 1
attribute vec2 a_pos;varying vec2 v_uv;void main(){v_uv=a_pos;gl_Position=vec4(a_pos*2.0-1.0,0.0,1.0);}`,
    uy = `#version 100
precision mediump float;
#define GLSLIFY 1
uniform sampler2D u_channel0;varying vec2 v_uv;void main(){vec4 color=texture2D(u_channel0,vec2(v_uv.x,1.0-v_uv.y));gl_FragColor=color;}`,
    dy = `#version 100
precision highp float;
#define GLSLIFY 1
#pragma tileLayer_defines
#if !defined(BILINEAR_ALPHA) && defined(BICUBIC)
#define BILINEAR_ALPHA
#endif
#if defined(USE_BLUE_CHANNEL) && !defined(PNG)
#error The blue data texture channel is used both as opacity and as the main forecast value source. This is likely an error.
#endif
vec4 debugUVBorder_0(vec2 texCoords,float borderWidth){float edge=min(min(texCoords.s,texCoords.t),min(1.0-texCoords.s,1.0-texCoords.t));float border=step(edge,borderWidth);return vec4(border);}float cubicHermite(vec4 X,float t){mediump float a=-X.x*.5+(3.*X.y)*.5-(3.*X.z)*.5+X.w*.5;mediump float b=X.x-(5.*X.y)*.5+2.*X.z-X.w*.5;mediump float c=-X.x*.5+X.z*.5;mediump float d=X.y;mediump float tt=t*t;return clamp(a*tt*t+b*tt+c*t+d,0.,1.);}vec4 cubicHermiteVec4(vec4 A,vec4 B,vec4 C,vec4 D,float t){mediump vec4 a=-A*0.5+(3.0*B)*0.5-(3.0*C)*0.5+D*0.5;mediump vec4 b=A-(5.0*B)*0.5+2.0*C-D*0.5;mediump vec4 c=-A*0.5+C*0.5;mediump vec4 d=B;mediump float tt=t*t;return clamp(a*tt*t+b*tt+c*t+d,vec4(0.),vec4(1.));}varying vec2 v_uv;uniform sampler2D u_tex_main_data;uniform sampler2D u_tex_gradient_main;uniform highp vec4 u_data_tile_scale_offset;uniform float u_data_tile_size_rcp;uniform vec2 u_data_tile_size_usable;uniform vec4 u_header_data_rescale;uniform vec2 u_gradient_scale_offset;uniform float u_log_offset;uniform vec3 u_background_color;uniform vec4 u_pattern_scale_offset;uniform bool u_data_tile_missing;vec4 debugUVBorder(vec2 texCoords,float borderWidth){float edge=min(min(texCoords.s,texCoords.t),min(1.0-texCoords.s,1.0-texCoords.t));float border=step(edge,borderWidth);return vec4(border);}
#define saturate(x) clamp((x), 0.0, 1.0)
float remapSat(float value,float oldmin,float oldmax,float newmin,float newmax){return newmin+saturate((value-oldmin)/max(oldmax-oldmin,0.0001))*(newmax-newmin);}vec2 interpolateBilinear(lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 w4){vec2 result=vec2(0.0);
#ifdef USE_BLUE_CHANNEL
result.x=dot(vec4(s11.b,s12.b,s21.b,s22.b),w4);
#else
result.x=dot(vec4(s11.r,s12.r,s21.r,s22.r),w4);
#endif
#ifdef VECTOR_SIZE
result.y=dot(vec4(s11.g,s12.g,s21.g,s22.g),w4);
#endif
return result;}vec2 interpolateBicubic(lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 sampleCoordsX,highp vec4 sampleCoordsY,highp vec2 f0,highp vec2 f1){lowp vec4 s00=texture2D(u_tex_main_data,vec2(sampleCoordsX[0],sampleCoordsY[0]));lowp vec4 s01=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[0]));lowp vec4 s02=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[0]));lowp vec4 s03=texture2D(u_tex_main_data,vec2(sampleCoordsX[3],sampleCoordsY[0]));lowp vec4 s10=texture2D(u_tex_main_data,vec2(sampleCoordsX[0],sampleCoordsY[1]));lowp vec4 s13=texture2D(u_tex_main_data,vec2(sampleCoordsX[3],sampleCoordsY[1]));lowp vec4 s20=texture2D(u_tex_main_data,vec2(sampleCoordsX[0],sampleCoordsY[2]));lowp vec4 s23=texture2D(u_tex_main_data,vec2(sampleCoordsX[3],sampleCoordsY[2]));lowp vec4 s30=texture2D(u_tex_main_data,vec2(sampleCoordsX[0],sampleCoordsY[3]));lowp vec4 s31=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[3]));lowp vec4 s32=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[3]));lowp vec4 s33=texture2D(u_tex_main_data,vec2(sampleCoordsX[3],sampleCoordsY[3]));vec2 result=vec2(0.0);
#ifdef USE_BLUE_CHANNEL
lowp vec4 b0=vec4(s00.b,s01.b,s02.b,s03.b);lowp vec4 b1=vec4(s10.b,s11.b,s12.b,s13.b);lowp vec4 b2=vec4(s20.b,s21.b,s22.b,s23.b);lowp vec4 b3=vec4(s30.b,s31.b,s32.b,s33.b);lowp vec4 b4=cubicHermiteVec4(b0,b1,b2,b3,f1.y);result.x=cubicHermite(b4,f1.x);
#else
lowp vec4 r0=vec4(s00.r,s01.r,s02.r,s03.r);lowp vec4 r1=vec4(s10.r,s11.r,s12.r,s13.r);lowp vec4 r2=vec4(s20.r,s21.r,s22.r,s23.r);lowp vec4 r3=vec4(s30.r,s31.r,s32.r,s33.r);lowp vec4 r4=cubicHermiteVec4(r0,r1,r2,r3,f1.y);result.x=cubicHermite(r4,f1.x);lowp float rMax=max(max(s11.r,s12.r),max(s21.r,s22.r));lowp float rMin=min(min(s11.r,s12.r),min(s21.r,s22.r));result.x=clamp(result.x,rMin,rMax);
#endif
#ifdef VECTOR_SIZE
lowp vec4 g0=vec4(s00.g,s01.g,s02.g,s03.g);lowp vec4 g1=vec4(s10.g,s11.g,s12.g,s13.g);lowp vec4 g2=vec4(s20.g,s21.g,s22.g,s23.g);lowp vec4 g3=vec4(s30.g,s31.g,s32.g,s33.g);lowp vec4 gg=cubicHermiteVec4(g0,g1,g2,g3,f1.y);result.y=cubicHermite(gg,f1.x);
#endif
return result;}lowp float getOpacity(lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 w4){
#ifdef PNG
#ifdef BILINEAR_ALPHA
return max(sign(dot(vec4(s11.a,s12.a,s21.a,s22.a),w4)-0.66),0.0);
#else
return min(min(s11.a,s12.a),min(s21.a,s22.a));
#endif
#else
#ifdef BILINEAR_ALPHA
return 1.0-max(sign(dot(vec4(s11.b,s12.b,s21.b,s22.b),w4)-0.33),0.0);
#else
return 1.0-max(max(s11.b,s12.b),max(s21.b,s22.b));
#endif
#endif
}vec4 getPixelColor(vec2 tc){if(u_data_tile_missing){return texture2D(u_tex_main_data,tc);}vec2 dataTileTexcoord=tc*u_data_tile_scale_offset.xy+u_data_tile_scale_offset.zw;vec2 dataTileTexcoordPixels=tc*u_data_tile_size_usable;highp vec2 f1=fract(dataTileTexcoordPixels);highp vec2 f0=vec2(1.)-f1;highp vec4 w4=vec4(f0.y*f0.x,f0.y*f1.x,f1.y*f0.x,f1.y*f1.x);highp vec4 sampleCoordsX=vec4(dataTileTexcoord.x-u_data_tile_size_rcp,dataTileTexcoord.x,dataTileTexcoord.x+u_data_tile_size_rcp,dataTileTexcoord.x+u_data_tile_size_rcp*2.0);highp vec4 sampleCoordsY=vec4(dataTileTexcoord.y-u_data_tile_size_rcp,dataTileTexcoord.y,dataTileTexcoord.y+u_data_tile_size_rcp,dataTileTexcoord.y+u_data_tile_size_rcp*2.0);lowp vec4 s11=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[1]));lowp vec4 s12=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[1]));lowp vec4 s21=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[2]));lowp vec4 s22=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[2]));highp vec2 dataValues;
#ifdef BICUBIC
dataValues=interpolateBicubic(s11,s12,s21,s22,sampleCoordsX,sampleCoordsY,f0,f1);
#else
dataValues=interpolateBilinear(s11,s12,s21,s22,w4);
#endif
dataValues.x=dataValues.x*u_header_data_rescale.x+u_header_data_rescale.y;
#ifdef LOG
dataValues.x=max(0.0,pow(2.0,dataValues.x)+u_log_offset);
#endif
float mainValue=dataValues.x;
#ifdef VECTOR_SIZE
dataValues.y=dataValues.y*u_header_data_rescale.z+u_header_data_rescale.w;mainValue=length(dataValues);
#endif
vec3 resultColor=texture2D(u_tex_gradient_main,vec2(mainValue*u_gradient_scale_offset.x+u_gradient_scale_offset.y,0.5)).rgb;lowp float patternMask=1.0;
#ifdef RAIN
patternMask=remapSat(dataValues.x,0.07,0.13,0.0,1.0);
#endif
lowp float opacity=getOpacity(s11,s12,s21,s22,w4);return vec4(mix(u_background_color,resultColor,opacity),patternMask);}void main(){vec2 dataTileTexcoord=v_uv*u_data_tile_scale_offset.xy+u_data_tile_scale_offset.zw;
#ifdef DISPLAY_RAW
vec4 sample=texture2D(u_tex_main_data,dataTileTexcoord);gl_FragColor=vec4(sample.rgb,1.0);
#else
gl_FragColor=getPixelColor(v_uv);
#endif
#ifdef DEBUG_BORDER
vec4 border=debugUVBorder(v_uv,0.005)*vec4(0.0,0.0,1.0,1.0)+debugUVBorder(v_uv,0.005)*vec4(1.0,0.0,1.0,1.0);gl_FragColor.rgb=mix(border.rgb,gl_FragColor.rgb,1.0-max(border.g,border.b));
#endif
#ifdef DEBUG_SOURCE_BORDER
gl_FragColor+=debugUVBorder(dataTileTexcoord,0.005)*vec4(0.0,1.0,1.0,1.0);
#endif
#ifdef DEBUG_ICON
float relW=0.1;float xCond=1.0-step(relW,v_uv.x);float yCond=1.0-step(relW,v_uv.y);gl_FragColor.rgb+=xCond*yCond;
#endif
}`,
    fy = `#version 100
precision mediump float;
#define GLSLIFY 1
#pragma tileLayer_defines
vec4 debugUVBorder(vec2 texCoords,float borderWidth){float edge=min(min(texCoords.s,texCoords.t),min(1.0-texCoords.s,1.0-texCoords.t));float border=step(edge,borderWidth);return vec4(border);}uniform sampler2D u_tex_main_data;varying vec2 v_uv;uniform vec4 u_header_data_rescale;uniform vec4 uColors[11];uniform vec4 u_data_tile_scale_offset;uniform float u_data_tile_size_rcp;uniform vec2 u_data_tile_size_usable;
#define saturate(x) clamp((x), 0.0, 1.0)
#define isNear(x, y) saturate(sign((x) - (y)) - sign((x) - (y) - 1.0))
vec4 getPixelColor(vec2 tc){vec2 dataTileTexcoord=tc*u_data_tile_scale_offset.xy+u_data_tile_scale_offset.zw;vec2 dataTileTexcoordPixels=tc*u_data_tile_size_usable;float u1=dataTileTexcoord.x;float u2=dataTileTexcoord.x+u_data_tile_size_rcp;float v1=dataTileTexcoord.y;float v2=dataTileTexcoord.y+u_data_tile_size_rcp;vec4 s11=texture2D(u_tex_main_data,vec2(u1,v1));vec4 s12=texture2D(u_tex_main_data,vec2(u2,v1));vec4 s21=texture2D(u_tex_main_data,vec2(u1,v2));vec4 s22=texture2D(u_tex_main_data,vec2(u2,v2));vec2 f1=fract(dataTileTexcoordPixels);vec2 f0=vec2(1.)-f1;vec4 bilinearWeights=vec4(f0.y*f0.x,f0.y*f1.x,f1.y*f0.x,f1.y*f1.x);float dataValue=dot(vec4(s11.r,s12.r,s21.r,s22.r),bilinearWeights)*u_header_data_rescale.x+u_header_data_rescale.y;dataValue=max(0.0,pow(2.0,dataValue)-0.001);vec4 allSamplesG=vec4(s11.g,s12.g,s21.g,s22.g)*u_header_data_rescale.z+u_header_data_rescale.w;const float interpolationThreshold=0.45;vec3 resultColor=uColors[0].rgb;if(dataValue<=0.1){return vec4(resultColor,1.0);}for(int i=1;i<11;i++){if(dot(isNear(allSamplesG,float(i)),bilinearWeights)>interpolationThreshold){resultColor=uColors[i].rgb;}}return vec4(resultColor,1.0);}void main(){gl_FragColor=getPixelColor(v_uv);}`,
    py = b({
        ShaderStorage: () => my
    }),
    my = class {};
C(my, `WGL2`, {
    vTileTextureBlit: ly,
    vScreenQuad: ay,
    fTileTextureBlit: cy,
    fTextureDebug: sy,
    fTextureBlit: uy,
    fTileLayerPreprocess: dy,
    fTileLayerPtypePreprocess: fy
}), C(my, `WGL1`, {
    vTileTextureBlit: ly,
    vScreenQuad: oy,
    fTileTextureBlit: cy,
    fTextureDebug: sy,
    fTextureBlit: uy,
    fTileLayerPreprocess: dy,
    fTileLayerPtypePreprocess: fy
});
var hy = class {
    constructor(e, t) {
        var n, r, i, a, o;
        C(this, `_renderer`, void 0), C(this, `_primaryGradient`, void 0), C(this, `_renderProperties`, void 0), C(this, `_ptypeColors`, void 0), C(this, `_params`, void 0), C(this, `_gl`, void 0), C(this, `_destroyed`, !1), C(this, `_fbo`, void 0), this._params = t, this._gl = e;
        let s = (n = U() ? (r = t.maxTileZoom) == null ? void 0 : r.premium : (i = t.maxTileZoom) == null ? void 0 : i.free) == null ? 11 : n,
            c = tg[(a = t.dataQuality) == null ? `normal` : a][s] + 1,
            l = v_((o = t.dataQuality) == null ? `normal` : o);
        this._renderProperties = {
            useBlueChannel: !1,
            dataZoomOffset: l,
            maxDataZoom: c
        }, this._createUpdateGradients(t), this._initRenderer(t)
    }
    preRenderToTexture(e, t, n, r) {
        let i = this._gl;
        i.bindFramebuffer(i.FRAMEBUFFER, this._fbo), i.framebufferTexture2D(i.FRAMEBUFFER, i.COLOR_ATTACHMENT0, i.TEXTURE_2D, r.texture, 0), i.viewport(0, 0, r.dimensions.x, r.dimensions.y);
        let a = this._renderTile(i, t, n, {
            tileCoords: e
        });
        return i.framebufferTexture2D(i.FRAMEBUFFER, i.COLOR_ATTACHMENT0, i.TEXTURE_2D, null, 0), i.bindFramebuffer(i.FRAMEBUFFER, null), a
    }
    destroy() {
        this._gl.deleteFramebuffer(this._fbo), this._renderer.destroy(this._gl)
    }
    _renderTile(e, t, n, r) {
        if (this._destroyed) throw Error(`Tried to use a destroyed TileLayerPreprocessor.`);
        let i = this._bindUniforms(r.tileCoords, n),
            a = new Sg(this._gl, this._gl.RGBA, this._gl.TEXTURE_2D, t);
        return a.bind(e, void 0, e.NEAREST), this._renderer.updateUniformValue(`u_tex_main_data`, a), this._renderer.render(e, e.TRIANGLE_FAN), a.unbind(e), i
    }
    _bindUniforms(e, t) {
        var n, r, i, a, o;
        let s = Kc[this._params.layer],
            c = 0,
            l = 256 / 257,
            u = ag(this._params, e.z),
            d = 2 ** Math.max(0, e.z - u),
            f = e.x / d % 1 * l,
            p = e.y / d % 1 * l,
            m = Math.min(2 ** u / 2 ** e.z, 1),
            h = m * l,
            g = .998 * .0038910505836575876,
            _ = 256 * m,
            v = [h, h, f, p];
        this._renderer.updateUniformValue(`u_data_tile_scale_offset`, v), this._renderer.updateUniformValue(`u_data_tile_size_rcp`, g), this._renderer.updateUniformValue(`u_data_tile_size_usable`, [_, _]), this._renderer.updateUniformValue(`u_data_tile_missing`, 0);
        let ee = -.001,
            te = [128 / 255, 128 / 255, 128 / 255];
        switch (this._params.layer) {
            case `rain`:
                c = .5;
                break;
            case `ptype`: {
                var y;
                c = .5;
                let e = 1 / 255,
                    t = [
                        [e * 111, e * 111, e * 111],
                        [e * 0, e * 208, e * 239],
                        [e * 0, e * 0, e * 255],
                        [e * 197, e * 27, e * 195],
                        [e * 129, e * 63, e * 63],
                        [e * 227, e * 227, e * 227],
                        [e * 129, e * 195, e * 129],
                        [e * 202, e * 211, e * 57],
                        [e * 183, e * 119, e * 8],
                        [e * 227, e * 73, e * 19],
                        [e * 195, e * 63, e * 63]
                    ],
                    n = (y = this._ptypeColors) == null ? t : y,
                    r = [];
                for (let e = 0; e < 11; e++) r.push(...n[e], 1);
                this._renderer.updateUniformValue(`uColors`, r)
            }
            break;
            case `ccl`:
                c = .5;
                break;
            case `cloudtop`:
                te = [111 / 255, 111 / 255, 111 / 255];
                break
        }
        let ne = (n = this._primaryGradient) == null ? void 0 : n.texture;
        ne && this._renderer.updateUniformValue(`u_tex_gradient_main`, ne), s.wTransformR && s.wTransformR > 0 && (ee = s.wTransformR), this._renderProperties.useBlueChannel ? this._renderer.updateUniformValue(`u_header_data_rescale`, [255 * t.decoderBstep, t.decoderBmin, 0, 0]) : this._renderer.updateUniformValue(`u_header_data_rescale`, [255 * t.decoderRstep, t.decoderRmin, 255 * t.decoderGstep, t.decoderGmin + c]);
        let re = [(r = (i = this._primaryGradient) == null ? void 0 : i.mul) == null ? 1 : r, (a = (o = this._primaryGradient) == null ? void 0 : o.add) == null ? 0 : a];
        return this._renderer.updateUniformValue(`u_gradient_scale_offset`, re), this._renderer.updateUniformValue(`u_log_offset`, ee), this._renderer.updateUniformValue(`u_background_color`, te), {
            dataTileScaleOffset: v,
            sizeS: _,
            srcPixelSize: g
        }
    }
    _initRenderer(e) {
        let t = this._gl;
        this._renderer = new Cg(`tile-layer-preprocessor-standalone`), this._fbo = t.createFramebuffer();
        let n = gy(e);
        this._renderProperties.useBlueChannel = n.includes(`USE_BLUE_CHANNEL`);
        let r = e.layer === `ptype` ? my[kv.context].fTileLayerPtypePreprocess : my[kv.context].fTileLayerPreprocess;
        r = r.replace(`#pragma tileLayer_defines`, n), this._renderer.initFromSources(t, my.WGL1.vScreenQuad, r);
        let i = this._renderer.getAttachedShader(),
            a = new vg(t, new Float32Array(yg.quadMeshUniqueVtx), void 0, !1);
        a.registerShaderGeometryLayout(t, i, {
            a_pos: 2
        }), this._renderer.addMesh(a), this._renderer.registerUniformRecord(t, `u_tex_main_data`, 1), this._renderer.registerUniformRecord(t, `u_data_tile_missing`, 0), this._renderer.registerUniformRecord(t, `u_header_data_rescale`, 2), this._renderer.registerUniformRecord(t, `u_gradient_scale_offset`, 4), this._renderer.registerUniformRecord(t, `u_log_offset`, 5), this._renderer.registerUniformRecord(t, `u_background_color`, 6), this._renderer.registerUniformRecord(t, `u_tex_gradient_main`, 1), this._renderer.registerUniformRecord(t, `u_data_tile_scale_offset`, 2), this._renderer.registerUniformRecord(t, `u_data_tile_size_rcp`, 5), this._renderer.registerUniformRecord(t, `u_data_tile_size_usable`, 4), this._renderer.registerUniformRecord(t, `u_pattern_scale_offset`, 2), e.layer === `ptype` && this._renderer.registerUniformRecord(t, `uColors`, 8)
    }
    _createUpdateGradients(e) {
        let t = Kc[e.layer];
        this._primaryGradient && this._primaryGradient.texture && this._primaryGradient.texture.destroy(this._gl), this._primaryGradient = g_(this._gl, t.c.getColor());
        let n = B.ptype.getColor();
        if (n) {
            let e = 1 / 255;
            this._ptypeColors = [];
            for (let t = 0; t < 11; t++) {
                let r = n.RGBA(t);
                this._ptypeColors[t] = [e * r[0], e * r[1], e * r[2]]
            }
        }
    }
};

function gy(e) {
    let t;
    return t = e.shaderDefines && e.shaderDefines.length > 0 ? e.shaderDefines : [`BICUBIC`], t.map(e => `#define ${e}`).join(`
`)
}
const _y = {
    missing: `-`,
    waitingForDataTile: `W`,
    dataTileFailed: `F`,
    dataTileAborted: `A`,
    dataTileInvalid: `I`,
    contextLostDuringProcessing: `C`,
    success: `S`,
    deleted: `D`
};

function vy(e, t, n) {
    let r = ``,
        i = ``;
    for (let a = e.min.y; a <= e.max.y; a++) {
        for (let o = e.min.x; o <= e.max.x; o++) {
            let e = y({
                    x: o,
                    y: a,
                    z: t
                }),
                s = n.get(e);
            if (!s) {
                r += _y.missing;
                continue
            }
            r += _y[s.state], s.message && (i += `${e}: ${s.state}: ${s.message}\n`)
        }
        r += `
`
    }
    let a = `Legend:
`;
    for (let e in _y) a += `${_y[e]}: ${e}\n`;
    return a + `
` + r + `
` + i
}

function yy(e) {
    let t = Z.maplibreMap.painter.context.gl,
        n = new hy(t, e),
        r = e.fullPath,
        i = new Map,
        a = new _(async (a, o) => {
            let s = y(a),
                c = ag(e, a.z),
                l = 2 ** (c - a.z),
                u = by(r, {
                    x: Math.floor(a.x * l),
                    y: Math.floor(a.y * l),
                    z: c
                }),
                d;
            try {
                d = await C_.get(u, o)
            } catch (e) {
                if (e.message === `Aborted.`) return i.set(s, {
                    state: `dataTileAborted`,
                    message: `Abort caught in tile cache.`,
                    coords: a
                }), null;
                var f;
                throw i.set(s, {
                    state: `dataTileFailed`,
                    message: `Exception caught in tile cache: ${e} Message: ${(f = e == null ? void 0 : e.message) == null ? `(undefined)` : f}`,
                    coords: a
                }), e
            }
            if (!d.value.valid) return i.set(s, {
                state: `dataTileInvalid`,
                message: `DataTile: ${d.value._debugMessage}`,
                coords: a
            }), {
                valid: !1,
                _token: d
            };
            if (t.isContextLost()) return i.set(s, {
                state: `contextLostDuringProcessing`,
                message: `Lost WebGL context in tile cache.`,
                coords: a
            }), {
                valid: !1,
                _token: d
            };
            if (o.aborted) return C_.free(d), i.set(s, {
                state: `dataTileAborted`,
                message: `Abort caught in tile cache.`,
                coords: a
            }), null;
            let p = new Sg(t, t.RGBA, t.TEXTURE_2D);
            p.create(t, 256, 256);
            let m = n.preRenderToTexture(a, d.value.tex, d.value.header, p);
            return i.set(s, {
                state: `success`,
                coords: a
            }), {
                valid: !0,
                tex: p,
                dataHeader: d.value.header,
                dataTex: d.value.tex,
                coords: a,
                dataUniforms: m,
                _token: d
            }
        }, (e, n) => {
            n && (n.valid && !t.isContextLost() && n.tex.destroy(t), i.set(y(e), {
                state: `deleted`,
                coords: e
            }), C_.free(n._token))
        });
    return {
        cache: a,
        destroy: () => {
            a.off(), a.dispose(), t.isContextLost() || n.destroy()
        },
        debug: i
    }
}

function by(e, t) {
    return e.replace(/<z>/g, String(t.z)).replace(/<x>/g, String(t.x)).replace(/<y>/g, String(t.y))
}
var xy = b({
        TileLayerInterpolator: () => wy,
        tileLayerInterpolator: () => Ty
    }),
    Sy = class {
        constructor(e) {
            C(this, `_last`, null), C(this, `_gl`, void 0), C(this, `_fbo`, void 0), this._gl = e;
            let t = e.createFramebuffer();
            if (!t) throw Error(`Failed to create a framebuffer object.`);
            this._fbo = t
        }
        bind() {
            this._gl.bindFramebuffer(this._gl.FRAMEBUFFER, this._fbo)
        }
        dispose() {
            this._gl.deleteFramebuffer(this._fbo)
        }
        ensureTextureBound(e) {
            e !== this._last && (this._gl.framebufferTexture2D(this._gl.FRAMEBUFFER, this._gl.COLOR_ATTACHMENT0, this._gl.TEXTURE_2D, e, 0), this._last = e)
        }
        unbind() {
            this._gl.bindFramebuffer(this._gl.FRAMEBUFFER, null)
        }
    },
    Cy = class {
        constructor(e) {
            C(this, `_gl`, void 0), C(this, `_texFbo`, void 0), C(this, `_requests`, []), C(this, `_availablePbos`, []), C(this, `_pendingPboReads`, []), C(this, `_pboLoop`, void 0), C(this, `_disposed`, !1), this._gl = e, this._texFbo = new Sy(e), this._pboLoop = setInterval(() => {
                this._updatePboReads(), this._executeReads()
            }, 17)
        }
        dispose() {
            this._disposed = !0
        }
        async readPixels(e, t, n, r, i, a) {
            var o = this;
            if (o._disposed) throw Error(`Attempted to read pixels from a disposed PixelReader.`);
            return o._gl.isContextLost() ? null : new Promise(s => {
                o._requests.push({
                    sampleX: t,
                    sampleY: n,
                    width: r,
                    height: i,
                    texture: e,
                    resolve: s,
                    abort: a
                })
            })
        }
        _executeReads() {
            let e = [];
            for (let t of this._requests)(!t.abort || !t.abort.aborted) && e.push(t);
            this._requests = e, this._requests.length !== 0 && (ne(this._gl) ? this._executeReadsPBO(this._gl) : this._executeReadsSync())
        }
        _executeReadsSync() {
            let e = this._gl;
            this._texFbo.bind();
            for (let t = 0; t < 4 && t < this._requests.length; t++) {
                let n = this._requests[t];
                this._texFbo.ensureTextureBound(n.texture);
                let r = new Uint8Array(n.width * n.height * 4);
                e.readPixels(n.sampleX, n.sampleY, n.width, n.height, e.RGBA, e.UNSIGNED_BYTE, r), n.resolve(r)
            }
            this._texFbo.unbind(), this._requests.splice(0, Math.min(4, this._requests.length))
        }
        _executeReadsPBO(e) {
            let t = this._requests.splice(0, Math.min(this._requests.length, 64)),
                n = 0;
            for (let e of t) n += e.width * e.height * 4;
            let r = this._availablePbos.pop();
            if (!r) {
                let t = e.createBuffer();
                if (!t) throw Error(`Failed to create WebGL buffer.`);
                r = {
                    buffer: t,
                    size: 0
                }
            }
            e.bindBuffer(e.PIXEL_PACK_BUFFER, r.buffer), r.size < n && e.bufferData(e.PIXEL_PACK_BUFFER, n, e.STREAM_READ);
            let i = 0;
            this._texFbo.bind();
            for (let n of t) this._texFbo.ensureTextureBound(n.texture), e.readPixels(n.sampleX, n.sampleY, n.width, n.height, e.RGBA, e.UNSIGNED_BYTE, i), i += n.width * n.height * 4;
            this._texFbo.unbind(), e.bindBuffer(e.PIXEL_PACK_BUFFER, null);
            let a = e.fenceSync(e.SYNC_GPU_COMMANDS_COMPLETE, 0);
            if (!a) throw Error(`Failed to create WebGL fence sync.`);
            e.flush();
            let o = {
                pbo: r,
                requests: [...t],
                size: n,
                sync: a
            };
            this._pendingPboReads.push(o)
        }
        _updatePboReads() {
            let e = this._gl;
            if (!ne(e)) return;
            let t = [];
            for (let n of this._pendingPboReads) {
                let r = e.clientWaitSync(n.sync, 0, 0);
                if (r === e.CONDITION_SATISFIED || r === e.ALREADY_SIGNALED) {
                    let t = new Uint8Array(n.size);
                    e.bindBuffer(e.PIXEL_PACK_BUFFER, n.pbo.buffer), e.getBufferSubData(e.PIXEL_PACK_BUFFER, 0, t, 0, n.size), e.bindBuffer(e.PIXEL_PACK_BUFFER, null), e.deleteSync(n.sync), this._availablePbos.push(n.pbo);
                    let r = 0;
                    for (let e of n.requests) {
                        let n = e.width * e.height * 4,
                            i = t.subarray(r, r + n);
                        e.resolve(i), r += n
                    }
                } else t.push(n)
            }
            this._pendingPboReads = t, this._disposed && t.length === 0 && this._cleanUp()
        }
        _cleanUp() {
            clearInterval(this._pboLoop), this._pboLoop = -1;
            for (let e of this._requests) e.resolve(null);
            if (!this._gl.isContextLost()) {
                this._texFbo.dispose();
                for (let e of this._availablePbos) this._gl.deleteBuffer(e.buffer)
            }
            this._availablePbos = [], this._requests = []
        }
    },
    wy = class {
        constructor() {
            C(this, `_debugElement`, void 0), C(this, `_pixelReader`, void 0), C(this, `_lastDataZoom`, -1), C(this, `_pendingLoads`, new Map), C(this, `_latestParams`, void 0), C(this, `_requestGiveId`, 0), C(this, `_cache`, new Map), C(this, `_cachedRequestsByTileUrl`, new Map), C(this, `_onZoomEnd`, () => {
                if (!this._latestParams) return;
                let e = ag(this._latestParams, this._getIntZoom());
                if (e !== this._lastDataZoom) {
                    this._lastDataZoom = e;
                    let t = [...this._pendingLoads];
                    for (let [n, r] of t) r.dataZoom !== e && (r.abort.abort(), this._pendingLoads.delete(n))
                }
            }), C(this, `_keyDeleted`, e => {
                let t = this._cachedRequestsByTileUrl.get(e);
                if (t !== void 0) {
                    for (let e of t) this._cache.delete(e);
                    this._cachedRequestsByTileUrl.delete(e)
                }
            }), this._pixelReader = new Cy(Z.maplibreMap.painter.context.gl), Z.maplibreMap.on(`zoomend`, this._onZoomEnd), C_.on(`keydeleted`, this._keyDeleted), this._onZoomEnd()
        }
        paramsChanged(e) {
            this._latestParams = e, this._cachedRequestsByTileUrl.clear(), this._cache.clear();
            let t = [...this._pendingLoads];
            for (let [n, r] of t) r.fullPath !== e.fullPath && (r.abort.abort(), this._pendingLoads.delete(n));
            this._onZoomEnd()
        }
        createFun(e) {
            let t = this.sampleAtMercator.bind(this);
            e(Dy(t), Oy(t))
        }
        destroy() {
            Z.maplibreMap.off(`zoomend`, this._onZoomEnd), C_.off(`keydeleted`, this._keyDeleted), this._cache.clear(), this._cachedRequestsByTileUrl.clear(), this._clearAllWaitingTiles()
        }
        async sampleAtMercator(e, t, n, r) {
            var i = this;
            if (r || (r = i._latestParams), !r) return null;
            let a = i._requestGiveId++,
                o = i._getIntZoom(),
                s = 1 << o,
                c = {
                    x: s * e,
                    y: s * t
                },
                l = Math.floor(c.x),
                u = Math.floor(c.y);
            c.x -= l, c.y -= u;
            let d = ag(r, o),
                f = 1 << o - d,
                p = l / f,
                m = u / f,
                h = {
                    x: Math.floor(p),
                    y: Math.floor(m),
                    z: d
                },
                g = by(r.fullPath, h),
                _;
            try {
                n || (n = new AbortController), i._pendingLoads.set(a, {
                    abort: n,
                    dataZoom: d,
                    fullPath: r.fullPath
                }), _ = await C_.awaitTile(g, n.signal)
            } catch (e) {
                return null
            } finally {
                i._pendingLoads.has(a) && i._pendingLoads.delete(a)
            }
            if (!_) return null;
            try {
                let e = {
                    x: p % 1,
                    y: m % 1,
                    z: c.x / f,
                    w: c.y / f
                };
                return i._sampleDataFromTile(_.value, e, r, n.signal, h)
            } finally {
                C_.free(_)
            }
        }
        _getIntZoom() {
            let e = f_.x,
                t = f_.y - 1;
            return Math.round(D(Z.maplibreMap.getZoom(), e, t)) + 1
        }
        _clearAllWaitingTiles() {
            for (let e of this._pendingLoads.values()) e.abort.abort();
            this._pendingLoads.clear()
        }
        async _sampleDataFromTile(e, t, n, r, i) {
            var a = this;
            if (!e.valid) return null;
            let o = (t.x + t.z) * 256,
                s = (t.y + t.w) * 256,
                c = Math.floor(o),
                l = Math.floor(s),
                u = o - c,
                d = s - l,
                f = {
                    x: Math.floor(c),
                    y: Math.floor(l)
                },
                p = `${f.x}|${f.y}|${i.x}|${i.y}|${i.z}`,
                m = a._cache.get(p);
            if (m === void 0) {
                m = await a._pixelReader.readPixels(e.tex, f.x, f.y, 2, 2, r), a._cache.set(p, m);
                let t = a._cachedRequestsByTileUrl.get(e.url);
                t ? t.push(p) : a._cachedRequestsByTileUrl.set(e.url, [p])
            }
            if (!m || Ey(m, n)) return null;
            let h = ky([...Ay(m.subarray(0, 4), e.header, n), 0, ...Ay(m.subarray(4, 8), e.header, n), 0, ...Ay(m.subarray(8, 12), e.header, n), 0, ...Ay(m.subarray(12, 16), e.header, n), 0], u, d);
            if (a._debugElement) {
                let e = ky(m, u, d);
                a._debugElement.style.backgroundColor = `rgb(${e[0]},${e[1]},${e[2]})`
            }
            return h
        }
    };
const Ty = new wy;

function Ey(e, t) {
    for (let n = 0; n < 4; n++)
        if (t.JPGtransparency && e[n * 4 + 2] >= 192 || t.PNGtransparency && e[n * 4 + 3] < 1) return !0;
    return !1
}

function Dy(e) {
    return (t, n, r) => e(kt(t.lon), jt(t.lat), n, r)
}

function Oy(e) {
    return (t, n, r, i) => {
        let a = 256 * 2 ** (Z.maplibreMap.getZoom() + 1);
        return e(t / a, n / a, r, i)
    }
}

function ky(e, t, n) {
    let r = 1 - t,
        i = 1 - n,
        a = i * r,
        o = i * t,
        s = n * r,
        c = n * t,
        l = e[0],
        u = e[4],
        d = e[8],
        f = e[12],
        p = l * a + u * o + d * s + f * c,
        m = e[1],
        h = e[5],
        g = e[9],
        _ = e[13],
        v = m * a + h * o + g * s + _ * c,
        ee = e[2],
        te = e[6],
        y = e[10],
        ne = e[14];
    return [p, v, ee * a + te * o + y * s + ne * c]
}

function Ay(e, t, n) {
    let r = [0, 0, 0],
        i = [n.transformR, n.transformG, n.transformB],
        a = [t.decoderRstep, t.decoderGstep, t.decoderBstep],
        o = [t.decoderRmin, t.decoderGmin, t.decoderBmin];
    for (let t = 0; t < 3; t++) {
        let n = e[t] * a[t] + o[t],
            s = i[t];
        r[t] = s ? s(n) : n
    }
    return r
}
var jy = b({
        SwitchableTileCache: () => My
    }),
    My = class {
        get currentCache() {
            return this._currentCache
        }
        get keepBuffer() {
            return this._keepBuffer
        }
        get lastBounds() {
            return this._lastMapBounds
        }
        get lastZoom() {
            return this._lastMapZoom
        }
        constructor(t, n = 0, r = 0, i = 0) {
            C(this, `_nextCache`, null), C(this, `_currentCache`, void 0), C(this, `_keepBuffer`, void 0), C(this, `_maxLowerZoom`, void 0), C(this, `_maxHigherZoom`, void 0), C(this, `_lastMapBounds`, new e([0, 0], [0, 0])), C(this, `_lastMapZoom`, 0), C(this, `onSwitch`, void 0), this._currentCache = t, this._keepBuffer = n, this._maxLowerZoom = r, this._maxHigherZoom = i
        }
        setCache(e) {
            if (e === this._currentCache) throw Error(`SwitchableTileCache: bad usage: tried to switch to a cache that is already used as the current cache.`);
            if (e === this._nextCache) throw Error(`SwitchableTileCache: bad usage: tried to switch to a cache that is already being set up as the next cache.`);
            this._nextCache && (this._nextCache.destroy(), this._nextCache = null);
            let t = () => {
                if (this._nextCache !== e) throw Error(`SwitchableTileCache: 'alltilesloaded' event fired on a cache that should be ready to be switched, but this cache is no longer assigned as the next one. This state should never happen.`);
                if (this._currentCache === e) throw Error(`SwitchableTileCache: 'alltilesloaded' event fired on a cache that should be ready to be switched, but this cache is already the current cache. This state should never happen.`);
                let t = this._currentCache;
                this._currentCache = this._nextCache, this._nextCache = null, t.destroy(), this.onSwitch && this.onSwitch()
            };
            this._nextCache = e, this._nextCache.cache.once(`alltilesloaded`, t), this._updateInternal()
        }
        update(e) {
            let t = Math.round(e.getZoom()),
                n = e.getTileBounds(t);
            n.min.x -= this._keepBuffer, n.min.y = Math.max(n.min.y - this._keepBuffer, 0), n.max.x += this._keepBuffer, n.max.y = Math.min(n.max.y + this._keepBuffer, (1 << t) - 1), this._lastMapBounds = n, this._lastMapZoom = t, this._updateInternal()
        }
        getRenderableCoords() {
            return this._currentCache.cache.getOrderedTilePyramid(this._lastMapBounds, this._lastMapZoom, this._maxLowerZoom, this._maxHigherZoom)
        }
        getTile(e) {
            return this._currentCache.cache.getData(e)
        }
        hasTile(e) {
            return this._currentCache.cache.hasTile(e)
        }
        async awaitTile(e, t) {
            var n = this,
                r;
            return ((r = n._nextCache) == null ? n._currentCache : r).cache.awaitTile(e, t)
        }
        dispose() {
            this._nextCache && (this._nextCache.destroy(), this._nextCache = null), this._currentCache.destroy()
        }
        _updateInternal() {
            this._nextCache ? this._nextCache.cache.update(this._lastMapBounds, this._lastMapZoom) : this._currentCache.cache.update(this._lastMapBounds, this._lastMapZoom)
        }
    },
    Ny = class {
        constructor() {
            C(this, `_lastCenter`, void 0), C(this, `_lastZoom`, -1), C(this, `_lastTranslation`, new h(0, 0)), C(this, `_opacity`, 1), C(this, `_lastZooming`, !1), C(this, `_zooming`, !1), C(this, `_lastUpdateTime`, new Date), C(this, `_zoomStart`, () => {
                this._zooming = !0
            }), C(this, `_zoomEnd`, () => {
                this._zooming = !1
            })
        }
        get translation() {
            return this._lastTranslation
        }
        get opacity() {
            return this._opacity
        }
        init() {
            this._lastZoom = Z.getZoom(), this._lastCenter = Z.getCenter(), Z.on(`zoomstart`, this._zoomStart), Z.on(`zoomend`, this._zoomEnd)
        }
        update(e) {
            let t = Z.getCenter(),
                n = Z.getZoom(),
                r = new Date;
            if (n === this._lastZoom && this._lastCenter) {
                let r = Z.project(t, n),
                    i = Z.project(this._lastCenter, n),
                    a = r.sub(i);
                this._lastTranslation._add(a._divByPoint(new h(e.x, e.y))._mult(Z.webGLPixelRatio))
            }
            let i = this._opacity,
                a = (r.getTime() - this._lastUpdateTime.getTime()) / 1e3;
            this._lastZooming == this._zooming && (this._opacity = Math.min(Math.max(this._opacity + a / .1 * (this._zooming ? -1 : 1), 0), 1)), (i !== this._opacity || this._lastZooming !== this._zooming) && Z.maplibreMap.triggerRepaint(), this._lastCenter = t, this._lastZoom = n, this._lastUpdateTime = r, this._lastZooming = this._zooming
        }
        destroy() {
            Z.off(`zoomstart`, this._zoomStart), Z.off(`zoomend`, this._zoomEnd)
        }
    },
    Py = `#version 100
#define GLSLIFY 1
uniform mat4 u_matrix;uniform vec4 u_tile_transform;attribute vec2 a_pos;varying vec2 v_uv0;void main(){v_uv0=a_pos;gl_Position=u_matrix*vec4(a_pos*u_tile_transform.zw+u_tile_transform.xy,0.0,1.0);}`,
    Fy = `#version 100
precision mediump float;
#define GLSLIFY 1
#pragma variant
uniform bool u_tile_valid;uniform sampler2D u_tex_preprocessed_tile;
#define saturate(x) clamp((x), 0.0, 1.0)
#if defined(RAIN) || defined(CLOUDS) || defined(CCL)
#define PATTERN_ANY
#endif
#ifdef PATTERN_ANY
uniform highp vec4 u_data_tile_scale_offset;uniform float u_data_tile_size_usable;uniform float u_data_tile_size_rcp;uniform vec4 u_header_data_rescale;uniform vec4 u_pattern_scale_offset;uniform float u_pattern_opacity;uniform sampler2D u_tex_main_data;uniform sampler2D u_tex_pattern_primary;
#endif
#ifdef RAIN
uniform sampler2D u_tex_pattern_secondary;
#endif
#ifdef CLOUDS
uniform vec2 u_gradient_scale_offset;uniform sampler2D u_tex_gradient_secondary;
#endif
varying vec2 v_uv0;
#define isInRange(x, a, b) saturate(sign((x) - float(a)) - sign((x) - float(b)))
#ifdef RAIN
vec3 getRain(vec3 resultColor,lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 w4,lowp float patternMask){vec4 g4=vec4(s11.g,s12.g,s21.g,s22.g)*u_header_data_rescale.z+u_header_data_rescale.w;lowp vec4 mask1=vec4(dot(isInRange(g4,6,7),w4),dot(isInRange(g4,4,6),w4),dot(isInRange(g4,7,8),w4),dot(isInRange(g4,8,9),w4));mask1=saturate(mask1*10.0-4.5);lowp vec4 mask2=vec4(dot(isInRange(g4,9,10),w4),dot(isInRange(g4,10,11),w4),dot(isInRange(g4,11,12),w4),dot(isInRange(g4,3,4),w4));mask2=saturate(mask2*10.-4.5);mediump vec2 patternTexcoord=gl_FragCoord.xy*u_pattern_scale_offset.xy+u_pattern_scale_offset.zw;lowp vec4 patt=texture2D(u_tex_pattern_primary,patternTexcoord);lowp vec4 patt2=texture2D(u_tex_pattern_secondary,patternTexcoord);lowp vec4 masked1=patt*mask1;lowp vec4 masked2=patt2*mask2;const vec4 colorSnowflake=vec4(0.85,0.85,1.00,0.65);const vec4 colorSnowflakeDiamond=vec4(1.00,1.00,1.00,0.55);const vec4 colorSnowflakeRaindrop=vec4(0.80,0.90,1.00,0.50);const vec4 colorBallThing=vec4(0.80,0.70,1.00,0.60);const vec3 colorLightning=vec3(1.00,1.00,0.70);const vec3 opacitiesLightning=vec3(0.27,0.50,0.70);const vec4 colorExclamationMark=vec4(1.00,0.80,0.80,0.90);masked1*=patternMask*u_pattern_opacity;masked2*=patternMask*u_pattern_opacity;resultColor=mix(resultColor,colorSnowflake.rgb,masked1.r*colorSnowflake.a);resultColor=mix(resultColor,colorSnowflakeDiamond.rgb,masked1.g*colorSnowflakeDiamond.a);resultColor=mix(resultColor,colorSnowflakeRaindrop.rgb,masked1.b*colorSnowflakeRaindrop.a);resultColor=mix(resultColor,colorBallThing.rgb,masked1.a*colorBallThing.a);resultColor=mix(resultColor,colorLightning,masked2.r*opacitiesLightning.x);resultColor=mix(resultColor,colorLightning,masked2.g*opacitiesLightning.y);resultColor=mix(resultColor,colorLightning,masked2.b*opacitiesLightning.z);resultColor=mix(resultColor,colorExclamationMark.rgb,masked2.a*colorExclamationMark.a);return resultColor;}
#endif
#ifdef CLOUDS
vec3 getClouds(vec3 resultColor,lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 w4,lowp float patternMask){float g=dot(vec4(s11.g,s12.g,s21.g,s22.g),w4);g=g*u_header_data_rescale.z+u_header_data_rescale.w;if(g>10.0){g=g*10.0-90.0;}mediump vec2 patternTexcoord=gl_FragCoord.xy*u_pattern_scale_offset.xy+u_pattern_scale_offset.zw;lowp vec4 patt=texture2D(u_tex_pattern_primary,patternTexcoord);lowp vec4 grad2=texture2D(u_tex_gradient_secondary,vec2(g*u_gradient_scale_offset.x+u_gradient_scale_offset.y,0.5));lowp float patternOpacity=max(0.0,sign(patt.r+grad2.a-1.0))*patternMask*u_pattern_opacity;return mix(resultColor,grad2.rgb,patternOpacity);}
#endif
#ifdef CCL
vec3 getCcl(vec3 resultColor,lowp vec4 s11,lowp vec4 s12,lowp vec4 s21,lowp vec4 s22,highp vec4 w4,lowp float patternMask){mediump vec4 g4=vec4(s11.g,s12.g,s21.g,s22.g)*u_header_data_rescale.z+u_header_data_rescale.w;lowp vec4 mr4=sign(g4-1.0)-sign(g4-2.0)+sign(g4-3.0)-sign(g4-4.0);lowp vec4 mg4=sign(g4-2.0)-sign(g4-3.0)+sign(g4-4.0)-sign(g4-5.0);lowp vec4 mb4=sign(g4-6.0);lowp vec4 ma4=sign(g4-3.0)-sign(g4-6.0)+sign(g4-7.0);lowp float mr=dot(saturate(mr4),w4);lowp float mg=dot(saturate(mg4),w4);lowp float mb=dot(saturate(mb4),w4);lowp float ma=dot(saturate(ma4),w4);mediump vec2 patternTexcoord=gl_FragCoord.xy*u_pattern_scale_offset.xy+u_pattern_scale_offset.zw;lowp vec4 patt=texture2D(u_tex_pattern_primary,patternTexcoord);patt.xyz*=u_pattern_opacity;lowp vec4 mask=saturate(vec4(mr,mg,mb,ma)*10.0-4.5);lowp float add=min(dot(patt.rg,mask.rg),1.0)*0.4;lowp vec2 pattM=vec2(patt.a*0.35,patt.b-0.35);lowp float mul=1.0-clamp(dot(pattM,mask.ab),0.0,0.4);return mix(resultColor,mix(resultColor*mul,vec3(1.0),add),patternMask);}
#endif
vec4 renderBorder(vec2 texCoords,float borderWidth){float edge=min(min(texCoords.s,texCoords.t),min(1.0-texCoords.s,1.0-texCoords.t));float border=step(edge,borderWidth);return vec4(border);}
#ifdef PATTERN_ANY
vec3 applyPattern(vec3 resultColor,vec2 tc,float patternMask){if(patternMask<0.5/255.0){return resultColor;}vec2 dataTileTexcoord=tc*u_data_tile_scale_offset.xy+u_data_tile_scale_offset.zw;vec2 dataTileTexcoordPixels=tc*u_data_tile_size_usable;highp vec2 f1=fract(dataTileTexcoordPixels);highp vec2 f0=vec2(1.)-f1;highp vec4 w4=vec4(f0.y*f0.x,f0.y*f1.x,f1.y*f0.x,f1.y*f1.x);highp vec4 sampleCoordsX=vec4(dataTileTexcoord.x-u_data_tile_size_rcp,dataTileTexcoord.x,dataTileTexcoord.x+u_data_tile_size_rcp,dataTileTexcoord.x+u_data_tile_size_rcp*2.0);highp vec4 sampleCoordsY=vec4(dataTileTexcoord.y-u_data_tile_size_rcp,dataTileTexcoord.y,dataTileTexcoord.y+u_data_tile_size_rcp,dataTileTexcoord.y+u_data_tile_size_rcp*2.0);lowp vec4 s11=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[1]));lowp vec4 s12=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[1]));lowp vec4 s21=texture2D(u_tex_main_data,vec2(sampleCoordsX[1],sampleCoordsY[2]));lowp vec4 s22=texture2D(u_tex_main_data,vec2(sampleCoordsX[2],sampleCoordsY[2]));
#ifdef RAIN
resultColor=getRain(resultColor,s11,s12,s21,s22,w4,patternMask);
#endif
#ifdef CLOUDS
resultColor=getClouds(resultColor,s11,s12,s21,s22,w4,patternMask);
#endif
#ifdef CCL
resultColor=getCcl(resultColor,s11,s12,s21,s22,w4,patternMask);
#endif
return resultColor;}
#endif
void main(){vec4 color=texture2D(u_tex_preprocessed_tile,v_uv0);if(u_tile_valid){
#ifdef PATTERN_ANY
if(u_tile_valid){color.rgb=applyPattern(color.rgb,v_uv0,color.a);}
#endif
color.a=1.0;}
#ifdef DEBUG_TILE_BORDER
vec4 border=renderBorder(v_uv0,0.0025);vec4 borderColor=vec4(1.0,0.0,0.0,1.0);gl_FragColor=mix(color,borderColor,border.r);
#else
gl_FragColor=color;
#endif
}`,
    Iy = class extends Cg {
        constructor(e, t) {
            super(`tile-layer-renderer-${t}`), C(this, `_emptyPlaceholderTexture`, void 0), C(this, `_variant`, void 0), C(this, `_patternTranslator`, new Ny), C(this, `_bindings`, {
                uniformTileTexture: null,
                uniformTileTransform: null,
                uniformMatrix: null,
                uniformDataTileTexture: null,
                uniformPatternPrimaryTexture: null,
                uniformPatternSecondaryTexture: null,
                uniformGradientSecondaryTexture: null,
                uniformHeaderDataRescale: null,
                uniformTileValid: null,
                uniformDataTileOffsetScale: null,
                uniformDataTileSizeUsable: null,
                uniformPatternScale: null,
                uniformDataSizeRcp: null,
                uniformPatternOpacity: null,
                uniformGradientScaleOffset: null
            }), this._variant = t, this._initializeRenderer(e, t)
        }
        render(e) {
            throw Error(`Called TileLayerRenderer.render(), use renderTiles() instead.`)
        }
        renderTiles(e, t, n, r) {
            if (!r && this._variant !== `DEFAULT`) throw Error(`Non-default tile renderer may not be used without pattern textures.`);
            if (!this.renderReady || this.meshes.length === 0) return;
            this.program.use(e);
            let i = this.program.getProgram();
            this._bindings.uniformTileTexture || (this._bindings.uniformTileTexture = e.getUniformLocation(i, `u_tex_preprocessed_tile`), this._bindings.uniformTileTransform = e.getUniformLocation(i, `u_tile_transform`), this._bindings.uniformMatrix = e.getUniformLocation(i, `u_matrix`), this._bindings.uniformDataTileTexture = e.getUniformLocation(i, `u_tex_main_data`), this._bindings.uniformPatternPrimaryTexture = e.getUniformLocation(i, `u_tex_pattern_primary`), this._bindings.uniformPatternSecondaryTexture = e.getUniformLocation(i, `u_tex_pattern_secondary`), this._bindings.uniformGradientSecondaryTexture = e.getUniformLocation(i, `u_tex_gradient_secondary`), this._bindings.uniformHeaderDataRescale = e.getUniformLocation(i, `u_header_data_rescale`), this._bindings.uniformTileValid = e.getUniformLocation(i, `u_tile_valid`), this._bindings.uniformDataTileOffsetScale = e.getUniformLocation(i, `u_data_tile_scale_offset`), this._bindings.uniformDataTileSizeUsable = e.getUniformLocation(i, `u_data_tile_size_usable`), this._bindings.uniformPatternScale = e.getUniformLocation(i, `u_pattern_scale_offset`), this._bindings.uniformDataSizeRcp = e.getUniformLocation(i, `u_data_tile_size_rcp`), this._bindings.uniformPatternOpacity = e.getUniformLocation(i, `u_pattern_opacity`), this._bindings.uniformGradientScaleOffset = e.getUniformLocation(i, `u_gradient_scale_offset`)), this.bindUniforms(e);
            let a;
            if (this._variant === `RAIN`) {
                var o, s, c, l, u;
                e.activeTexture(e.TEXTURE2), e.bindTexture(e.TEXTURE_2D, (o = r == null || (s = r.texturePType1) == null ? void 0 : s.texture) == null ? null : o), e.uniform1i(this._bindings.uniformPatternPrimaryTexture, 2), e.activeTexture(e.TEXTURE3), e.bindTexture(e.TEXTURE_2D, (c = r == null || (l = r.texturePType2) == null ? void 0 : l.texture) == null ? null : c), e.uniform1i(this._bindings.uniformPatternSecondaryTexture, 3), a = r == null || (u = r.texturePType1) == null ? void 0 : u.dimensions
            }
            if (this._variant === `CLOUDS`) {
                var d, f, p, h, g, _, v, ee, te, y;
                e.activeTexture(e.TEXTURE2), e.bindTexture(e.TEXTURE_2D, (d = r == null || (f = r.textureCloudsRain) == null ? void 0 : f.texture) == null ? null : d), e.uniform1i(this._bindings.uniformPatternPrimaryTexture, 2), e.activeTexture(e.TEXTURE4), e.bindTexture(e.TEXTURE_2D, (p = n == null || (h = n.texture) == null ? void 0 : h.texture) == null ? null : p), e.uniform1i(this._bindings.uniformGradientSecondaryTexture, 4), e.uniform2f(this._bindings.uniformGradientScaleOffset, (g = n == null ? void 0 : n.mul) == null ? 1 : g, (_ = n == null ? void 0 : n.add) == null ? 0 : _), a = {
                    x: ((v = r == null || (ee = r.textureCloudsRain) == null || (ee = ee.dimensions) == null ? void 0 : ee.x) == null ? 1 : v) * 2,
                    y: ((te = r == null || (y = r.textureCloudsRain) == null || (y = y.dimensions) == null ? void 0 : y.y) == null ? 1 : te) * 2
                }
            }
            if (this._variant === `CCL`) {
                var ne, ie, b;
                e.activeTexture(e.TEXTURE2), e.bindTexture(e.TEXTURE_2D, (ne = r == null || (ie = r.textureCCL) == null ? void 0 : ie.texture) == null ? null : ne), e.uniform1i(this._bindings.uniformPatternPrimaryTexture, 2), a = r == null || (b = r.textureCCL) == null ? void 0 : b.dimensions
            }
            if (a) {
                let t = Math.max(window.devicePixelRatio, 1) * .5,
                    n = {
                        x: a.x * t,
                        y: a.y * t
                    };
                this._variant === `CLOUDS` && (n.x = Math.max(Math.round(n.x / 2) * 2, a.x), n.y = Math.max(Math.round(n.y / 2) * 2, a.y)), this._patternTranslator.update(n), e.uniform4f(this._bindings.uniformPatternScale, 1 / n.x, -1 / n.y, this._patternTranslator.translation.x, this._patternTranslator.translation.y), e.uniform1f(this._bindings.uniformPatternOpacity, this._patternTranslator.opacity)
            }
            let ae = t.getRenderableCoords();
            for (let n of ae) {
                let r = re(n),
                    i = t.getTile(r);
                if (!i) continue;
                let a = i.valid ? i.tex : this._emptyPlaceholderTexture;
                e.activeTexture(e.TEXTURE0), e.bindTexture(e.TEXTURE_2D, a.texture), e.uniform1i(this._bindings.uniformTileTexture, 0), e.uniform4fv(this._bindings.uniformTileTransform, new Float32Array([0, 0, 8192, 8192]));
                let o = 1 << n.z,
                    s = new m(r.z, Math.floor(n.x / o), r.z, r.x, r.y),
                    c = Z.maplibreMap.transform.getProjectionData(s, !1);
                e.uniformMatrix4fv(this._bindings.uniformMatrix, !1, c.mainMatrix), e.uniform1i(this._bindings.uniformTileValid, +!!i.valid), i.valid && this._variant !== `DEFAULT` && (e.activeTexture(e.TEXTURE1), e.bindTexture(e.TEXTURE_2D, i.dataTex), e.uniform1i(this._bindings.uniformDataTileTexture, 1), e.uniform4f(this._bindings.uniformHeaderDataRescale, 255 * i.dataHeader.decoderRstep, i.dataHeader.decoderRmin, 255 * i.dataHeader.decoderGstep, i.dataHeader.decoderGmin + (this._variant === `RAIN` || this._variant === `CCL` ? .5 : 0)), e.uniform4f(this._bindings.uniformDataTileOffsetScale, i.dataUniforms.dataTileScaleOffset[0], i.dataUniforms.dataTileScaleOffset[1], i.dataUniforms.dataTileScaleOffset[2], i.dataUniforms.dataTileScaleOffset[3]), e.uniform1f(this._bindings.uniformDataTileSizeUsable, i.dataUniforms.sizeS), e.uniform1f(this._bindings.uniformDataSizeRcp, i.dataUniforms.srcPixelSize)), this.meshes.forEach(t => {
                    t.render(e, this.program, e.TRIANGLE_FAN)
                })
            }
        }
        destroy(e) {
            this._emptyPlaceholderTexture.destroy(e), super.destroy(e, Z.maplibreMap), this._patternTranslator.destroy()
        }
        _initializeRenderer(e, t) {
            let n = Wv(!1, `rgba(0,0,0,0)`);
            this._emptyPlaceholderTexture = new Sg(e), this._emptyPlaceholderTexture.updateContent(e, [n.getContext(`2d`).getImageData(0, 0, n.width, n.height).data, {
                x: n.width,
                y: n.height
            }]), this._patternTranslator.init();
            let r = Fy.replace(`#pragma variant`, `#define ${t}`);
            this.initFromSources(e, Py, r);
            let i = this.getAttachedShader();
            if (!i) throw Error(`[TileLayer] Could not retrieve shader program from created renderer`);
            this.registerUniformRecord(e, `u_tex_preprocessed_tile`, 1), this.registerUniformRecord(e, `u_matrix`, 3), this.registerUniformRecord(e, `u_tile_transform`, 2);
            let a = new vg(e, new Float32Array(yg.quadMeshUniqueVtx), void 0, !1);
            a.registerShaderGeometryLayout(e, i, {
                a_pos: 2
            }), this.addMesh(a)
        }
    };
const Ly = `tileLayer`;
var Ry = class e {
    constructor(e, t) {
        C(this, `_rendererCache`, new Map), C(this, `_enabled`, !0), C(this, `_hasSea`, !1), C(this, `_landOnly`, !1), C(this, `_latestParams`, void 0), C(this, `_switchableCache`, null), C(this, `_cloudsPatternGradient`, void 0), C(this, `_cloudsPatternGradientDirty`, !0), C(this, `_currentOverlay`, void 0), C(this, `eventManager`, void 0), C(this, `type`, `custom`), C(this, `id`, void 0), C(this, `_debugPrintTiles`, () => {
            let e = `(no cache)`;
            this._switchableCache && this._switchableCache.currentCache && this._switchableCache.currentCache.debug && (e = vy(this._switchableCache.lastBounds, this._switchableCache.lastZoom, this._switchableCache.currentCache.debug)), console.log(`###

` + e)
        }), this.id = e, this._latestParams = ht(t), this.eventManager = new Xv, this._updateCache()
    }
    get switchableCache() {
        return this._switchableCache
    }
    render(t, n) {
        if (!this._switchableCache) return;
        let r = this._getCloudsPatternGradient(t),
            i = e._textures;
        this._selectRenderer(t, this._currentOverlay, !i).renderTiles(t, this._switchableCache, r, i)
    }
    onAdd(e, t) {
        this.eventManager.addMapLibreListener(e, `move`, e => {
            this._onUpdate()
        }), this._prepareTextures(t), N.on(`debugPrintTiles`, this._debugPrintTiles)
    }
    enableDisableLayer(e) {
        let t = Z.maplibreMap.getLayer(this.id);
        t && (t.visibility = e ? `visible` : `none`), Z.maplibreMap.triggerRepaint()
    }
    paramsChanged(e, t = !1) {
        var n, r;
        this._cloudsPatternGradientDirty = !0, !(((n = this._latestParams) == null ? void 0 : n.fullPath) === e.fullPath && ((r = this._latestParams) == null ? void 0 : r.layer) === e.layer && !t) && (this._latestParams = ht(e), this._updateCache())
    }
    onRemove(e, t) {
        var n;
        this._destroyRenderers(t), this.eventManager.removeListeners(), (n = this._switchableCache) == null || n.dispose(), this._switchableCache = null, Dv(Ly, !1), N.off(`debugPrintTiles`, this._debugPrintTiles), this._updateLandSeaMask(!0)
    }
    _selectRenderer(e, t, n = !1) {
        let r = `DEFAULT`;
        n || (t === `ccl` ? r = `CCL` : t === `clouds` ? r = `CLOUDS` : t === `rain` && (r = `RAIN`));
        let i = this._rendererCache.get(r);
        if (i) return i;
        let a = new Iy(e, r);
        return this._rendererCache.set(r, a), a
    }
    _destroyRenderers(e) {
        for (let t of this._rendererCache.values()) t.destroy(e);
        this._rendererCache.clear()
    }
    _onUpdate() {
        var e;
        this._enabled && ((e = this._switchableCache) == null || e.update(Z))
    }
    _updateLandSeaMask(e) {
        if (e) {
            eg.emit(`toggleSeaMask`, !1), eg.emit(`toggleLandMask`, !1);
            return
        }
        this._latestParams.sea !== this._hasSea && (this._hasSea = !!this._latestParams.sea, eg.emit(`toggleSeaMask`, this._hasSea)), this._latestParams.landOnly !== this._landOnly && (this._landOnly = this._latestParams.landOnly, eg.emit(`toggleLandMask`, this._landOnly))
    }
    _updateCache() {
        let e = yy(this._latestParams);
        if (Dv(Ly, !0), this._switchableCache) this._switchableCache.setCache(e);
        else {
            this._currentOverlay = this._latestParams.overlay;
            let t = new My(e, 1, 20, 20);
            this._switchableCache = t, e.cache.once(`alltilesloaded`, () => {
                Dv(Ly, !1), Z.maplibreMap.triggerRepaint(), N.emit(`redrawFinished`, this._latestParams)
            }), t.onSwitch = () => {
                Dv(Ly, !1), this._updateLandSeaMask(), this._currentOverlay = this._latestParams.overlay, Z.maplibreMap.triggerRepaint(), t.currentCache.cache.on(`tileloaded`, () => {
                    Z.maplibreMap.triggerRepaint()
                })
            }, t.update(Z), e.cache.on(`tileloaded`, () => {
                Z.maplibreMap.triggerRepaint()
            }), this._updateLandSeaMask()
        }
    }
    _getCloudsPatternGradient(e) {
        return (this._cloudsPatternGradientDirty || !this._cloudsPatternGradient) && (this._cloudsPatternGradientDirty = !1, this._cloudsPatternGradient && this._cloudsPatternGradient.texture && this._cloudsPatternGradient.texture.destroy(e), this._cloudsPatternGradient = g_(e, B.rainClouds.getColor())), this._cloudsPatternGradient
    }
    async _prepareTextures(t) {
        e._textures === null && (e._texturesLoadPromise === null && (e._texturesLoadPromise = e._prepareTextures(t)), await e._texturesLoadPromise)
    }
    static async _prepareTextures(t) {
        let n = __(t);
        n.bind(t, t.REPEAT, t.NEAREST), t.bindTexture(t.TEXTURE_2D, null);
        let r = {
                texturePType1: null,
                texturePType2: null,
                textureCCL: null,
                textureCloudsRain: n
            },
            i = e => {
                console.error(`Error loading TileLayerPreprocessor texture:`, e)
            },
            a = Sg.createFromUrl(t, `/img/textures/ptype1_v4.png`).then(e => {
                e.bind(t, t.REPEAT, t.LINEAR), t.bindTexture(t.TEXTURE_2D, null), r.texturePType1 = e
            }).catch(i),
            o = Sg.createFromUrl(t, `/img/textures/ptype2_v4.png`).then(e => {
                e.bind(t, t.REPEAT, t.LINEAR), t.bindTexture(t.TEXTURE_2D, null), r.texturePType2 = e
            }).catch(i),
            s = Sg.createFromUrl(t, `/img/textures/ccl32_v4.png`).then(e => {
                e.bind(t, t.REPEAT, t.LINEAR), t.bindTexture(t.TEXTURE_2D, null), r.textureCCL = e
            }).catch(i);
        return Promise.all([a, o, s]).finally(() => {
            e._textures = r, e._texturesLoadPromise = null
        })
    }
};
C(Ry, `_textures`, null), C(Ry, `_texturesLoadPromise`, null);
var zy = b({
    TileLayer: () => Vy
});
let By;
var Vy = class extends ey {
        constructor(e) {
            super(e), C(this, `_layerId`, void 0), C(this, `_lastUsedMapParams`, void 0), C(this, `_initializeCallbackSet`, !1), this._layerId = `${e.ident}`, this.interpolator = Ty
        }
        onopen(e) {
            this._ensureMapAndSetParams(e, !0)
        }
        close(e) {
            if (super.close(e), e.includes(`tileLayer`) || e.includes(`daySwitcher`) || e.includes(`accumulations`) || e.includes(`noUserControl`)) {
                By == null || By.enableDisableLayer(!1);
                return
            }
            By && (Z.maplibreMap.removeLayer(By.id), By = void 0)
        }
        redraw() {
            By && this._lastUsedMapParams && By.paramsChanged(this._lastUsedMapParams, !0)
        }
        async paramsChanged(e, t, n) {
            var r = this;
            let i = await pg(e, t, n);
            r._ensureMapAndSetParams(i)
        }
        _ensureMapAndSetParams(e, t = !1) {
            if (!e) throw Error(`[TileLayer] No render params supplied`);
            e.refTime !== `` && (Ty.paramsChanged(e), By ? (By.enableDisableLayer(!0), this._lastUsedMapParams = e, By.paramsChanged(e, t)) : this._initialize(e), N.emit(`tileLayerParamsChanged`, e))
        }
        _initialize(e) {
            if (this._initializeCallbackSet) {
                this._lastUsedMapParams = e;
                return
            }
            this._lastUsedMapParams = e, this._initializeCallbackSet = !0, yv(() => {
                By = new Ry(this._layerId, this._lastUsedMapParams), Z.maplibreMap.addLayerToBucket(By, $_.MAIN), Xh(), this._initializeCallbackSet = !1
            })
        }
    },
    Hy = class extends ey {
        constructor(...e) {
            super(...e), C(this, `baseLayer`, null)
        }
        open() {
            return this.isOpen = !0, this.interpolator = {
                createFun: e => {
                    e(ut, ut)
                }
            }, Zh(), this.addOrUpdateBaseLayer(), M.on(`map`, this.addOrUpdateBaseLayer, this), Promise.resolve()
        }
        close(e) {
            super.close(e), this.removeBaseLayer(), M.off(`map`, this.addOrUpdateBaseLayer, this), Xh()
        }
        addOrUpdateBaseLayer() {
            this.removeBaseLayer();
            let e = M.get(`map`),
                t = Jh();
            this.baseLayer = new v(t[e], {
                detectRetina: !1,
                keepBuffer: S ? 1 : 4,
                layerBucketId: $_.BASE_MAP
            }), document.body.dataset.map = e, this.baseLayer.addTo(Z)
        }
        removeBaseLayer() {
            this.baseLayer && (Z.removeLayer(this.baseLayer), this.baseLayer = null)
        }
    };
const Uy = {
    tileLayer: new Vy({
        ident: `tileLayer`,
        userControl: S ? `mobile-calendar` : `progress-bar`,
        requiresFullRenderParams: !0
    }),
    noUserControl: new Vy({
        ident: `noUserControl`,
        userControl: `none`,
        requiresFullRenderParams: !0
    }),
    radarPlus: new ey({
        ident: `radarPlus`,
        dependency: `radar-plus`,
        userControl: `radar-plus`,
        requiresFullRenderParams: !0
    }),
    capAlerts: new ey({
        ident: `capAlerts`,
        dependency: `cap-alerts`,
        userControl: `cap-alerts`
    }),
    avalancheDanger: new ey({
        ident: `avalancheDanger`,
        dependency: `avalanche-danger`,
        userControl: `avalanche-danger`
    }),
    isolines: new ey({
        ident: `isolines`,
        dependency: `isolines`,
        requiresFullRenderParams: !0
    }),
    particles: new ey({
        ident: `particles`,
        dependency: `gl-particles`,
        requiresFullRenderParams: !0
    }),
    daySwitcher: new Vy({
        ident: `daySwitcher`,
        userControl: `day-switcher`,
        requiresFullRenderParams: !0
    }),
    accumulations: new Vy({
        ident: `accumulations`,
        userControl: `accumulations`,
        requiresFullRenderParams: !0
    }),
    topoMap: new Hy({
        ident: `topoMap`,
        userControl: `map-selector`
    })
};
var Wy = b({});
let Gy;

function Ky() {
    for (let e of Object.values(Uy)) e.isOpen && e.redraw()
}
async function qy(e) {
    let t = Is[e.overlay].layers;
    if (!t) {
        N.emit(`redrawFinished`, e);
        return
    }
    let n = e.isolinesOn ? [`${e.isolinesType}Isolines`, ...t] : t,
        r = n.map(e => Kc[e].renderer);
    Object.values(Uy).forEach(e => {
        !r.includes(e.ident) && e.isOpen && e.close(r)
    });
    let i = M.get(`timestamp`),
        a = n.map(async t => {
            let {
                renderer: n
            } = Kc[t], r = Uy[n];
            return r.isOpen ? r.paramsChanged(t, e, i) : r.open(t, e, i)
        });
    await Promise.all(a);
    let o = r.filter(e => {
        var t;
        return ((t = Uy[e]) == null ? void 0 : t.userControl) !== void 0
    }).map(e => Uy[e].userControl)[0];
    if (o !== Gy) {
        if (Gy && Gy !== `none`) {
            var s;
            (s = Y[Gy]) == null || s.close({
                disableClosingAnimation: !0
            })
        }
        if (o && o !== `none`) {
            var c;
            (c = Y[o]) == null || c.open({
                disableOpeningAnimation: !0
            })
        }
        Gy = o
    }
    N.emit(`redrawFinished`, e)
}
N.on(`paramsChanged`, qy), N.on(`redrawLayers`, Ky);
var Jy = b({});
let Yy, Xy = null;

function Zy(e) {
    let t = M.get(`overlay`),
        n = M.get(`product`),
        r = M.get(`level`),
        i = M.get(`isolinesType`),
        a = M.get(`isolinesOn`),
        o = {
            acRange: Math.floor(M.get(`acRange`)),
            isolinesType: i,
            isolinesOn: a,
            level: r,
            overlay: t,
            product: n
        };
    N.emit(`paramsChanged`, o, e)
}
const Qy = yt(Zy, 100);
let $y;
const eb = (e, t) => {
    let n = M.get(`level`),
        r = Qv(e, t);
    M.set(`availLevels`, r), r.includes(n) || M.set(`level`, r[0] || `surface`)
};
M.defineProperty(`timestamp`, `syncSet`, e => typeof e == `string` ? parseInt(e) : e), M.defineProperty(`product`, `asyncSet`, async e => {
    let t = M.get(`product`),
        n = K[e];
    t !== e && K[t].close();
    let r = await n.getCalendar();
    if (r) {
        M.set(`calendar`, r);
        let {
            end: e,
            start: t
        } = r, i = M.get(`timestamp`), a = qc(r.timestamps, i, !0);
        if (a !== void 0 && (i = r.timestamps[a]), n.hasAccumulations)
            if (i + M.get(`acRange`) * 36e5 > e) {
                let t = Math.floor((e - M.get(`timestamp`)) / T);
                t >= 12 ? M.set(`acRange`, t) : (M.set(`timestamp`, e - 12 * T), M.set(`acRange`, 12))
            } else M.set(`timestamp`, i);
        else if (i < t || i > e) {
            let n = D(i, t, e);
            M.set(`timestamp`, n)
        }
    } else M.set(`calendar`, null);
    return M.set(`preferredProduct`, n.preferredProduct), n.open(), eb($y || M.get(`overlay`), e), e
}), M.defineProperty(`overlay`, `asyncSet`, async e => {
    $y = e;
    let t = Ju(e, M.get(`product`));
    return t !== M.get(`product`) && await M.set(`product`, t), ce(/overlay-\S+/, `overlay-${e}`), M.set(`availProducts`, Uu[e]), eb(e, t), e
}), [`acRange`, `level`, `isolinesType`, `isolinesOn`, `overlay`, `product`].forEach(e => {
    M.on(e, Qy.bind(null, e))
}), M.on(`timestamp`, e => {
    let t = hn(e);
    t !== Yy && (Yy = t, Qy(`path`))
});
const tb = bh || M.get(`startUpOverlay`) || `wind`,
    nb = xh || M.get(`startUpLastProduct`) || $u(tb) || `ecmwf`;
M.set(`product`, nb, {
    forceChange: !0
}), M.set(`overlay`, tb, {
    forceChange: !0
}), U() && M.get(`startUpLastStep`) === 1 && M.set(`detail1h`, !0), M.on(`detail1h`, e => {
    if (U()) {
        let t = M.get(`startUpLastStep`);
        M.set(`startUpLastStep`, t ? e ? 1 : 3 : null)
    }
});
const rb = yt(() => {
    let e = M.get(`product`);
    M.set(`product`, e, {
        forceChange: !0
    })
}, 500);
M.on(`calendar`, () => {
    clearTimeout(Xy), M.set(`timestamp`, M.get(`timestamp`), {
        forceChange: !0
    }), Xy = setTimeout(rb, .5 * T)
}), M.on(`subscription`, rb), M.on(`visibility`, rb), N.on(`onResume`, rb);
var ib = b({
    displayPoiOnMap: () => sb,
    poisCheckboxes: () => ob
});
const ab = [{
        bindStore: `displayAdStations`,
        checkboxText: S ? `Airport` : `Airp.`
    }, {
        bindStore: `displayWMOStations`,
        checkboxText: `WMO`
    }, {
        bindStore: `displayMadisPWStations`,
        checkboxText: `PWS`
    }, {
        bindStore: `displayShipStations`,
        checkboxText: `ShipBuoy`
    }],
    ob = {
        favs: [],
        cities: [],
        wind: ab,
        temp: ab,
        precip: [],
        metars: [{
            bindStore: `displayAirspaces`,
            checkboxTranslation: `MAP_AIRSPACES`
        }, {
            bindStore: `displayHeliports`,
            checkboxTranslation: `METAR_HELIPORTS`
        }],
        cams: [{
            bindStore: `camsPreviews`,
            checkboxTranslation: `CAMS_PREVIEWS`
        }],
        pgspots: [],
        kitespots: [],
        surfspots: [],
        tide: [],
        firespots: [],
        airq: [],
        radiosonde: [],
        empty: [],
        stations: []
    },
    sb = async () => {
        let e = M.get(`pois`),
            t = M.get(`poisTemporary`);
        return !!(e === `favs` && await Wf(e => e.type !== `route`)) || e !== `empty` || t !== `empty`
    }, cb = async () => {
        await sb() && (N.emit(`rqstOpen`, `poi-libs`), M.off(`pois`, cb), M.off(`poisTemporary`, cb))
    };
N.once(`redrawFinished`, async () => {
    !sp() && M.get(`pois`) === `favs` && M.set(`pois`, `empty`), await sb() ? cb() : (M.on(`pois`, cb), M.on(`poisTemporary`, cb))
});
var lb = b({
    AlertConditionType: () => db,
    AlertStatus: () => ub,
    CloudCoverage: () => mb,
    Direction: () => fb,
    Weekday: () => pb
});
let ub = function(e) {
        return e.Triggered = `triggered`, e.Normal = `normal`, e.Suspended = `suspended`, e
    }({}),
    db = function(e) {
        return e.Aqi = `aqi`, e.Cloudiness = `cloudiness`, e.FreshSnow = `freshSnow`, e.Pollen = `pollen`, e.Rainfall = `rainfall`, e.Swell = `swell`, e.Temperature = `temperature`, e.Time = `time`, e.Wind = `wind`, e
    }({}),
    fb = function(e) {
        return e.N = `N`, e.NE = `NE`, e.E = `E`, e.SE = `SE`, e.S = `S`, e.SW = `SW`, e.W = `W`, e.NW = `NW`, e
    }({}),
    pb = function(e) {
        return e.Monday = `mon`, e.Tuesday = `tue`, e.Wednesday = `wed`, e.Thursday = `thu`, e.Friday = `fri`, e.Saturday = `sat`, e.Sunday = `sun`, e
    }({}),
    mb = function(e) {
        return e.SkyClear = `SKC`, e.Few = `FEW`, e.Scattered = `SCT`, e.Broken = `BKN`, e.Overcast = `OVC`, e
    }({});
var hb = b({
    getPositionAndDisplayMarker: () => Hb,
    onPosition: () => Ib,
    start: () => Vb,
    stop: () => zb
});
let Q = 1,
    gb = 0,
    $ = null,
    _b = !1,
    vb = null,
    yb = null,
    bb = null,
    xb = !0,
    Sb = null,
    Cb = null;
const wb = Gt(/Huawei/i.test(navigator.userAgent) ? `HmsGeolocation` : `Geolocation`),
    Tb = Gt(`WindyCompassPlugin`),
    Eb = new t({
        className: `icon-my-position`,
        html: `<img src="/img/maps/actual-pos.png" />`,
        iconSize: [16, 36],
        iconAnchor: [8, 18]
    }),
    Db = new t({
        className: `icon-my-position`,
        html: `<img src="/img/maps/actual-pos-no-heading.png" />`,
        iconSize: [16, 16],
        iconAnchor: [8, 8]
    }),
    Ob = new t({
        className: `icon-in-motion`,
        html: `<div class="icon-in-motion__line">
                <div class="icon-in-motion__ruler1">10 min</div>
                <div class="icon-in-motion__ruler2">5 min</div>
          </div>
          <img src="/img/maps/actual-pos-flying3.png" />`,
        iconSize: [0, 0],
        iconAnchor: [0, 0]
    }),
    kb = (e, t, n) => {
        if (Cb = {
                heading: e,
                speed: t,
                lat: n
            }, $) {
            var r, i;
            (r = $.getElement()) == null || r.style.setProperty(`--heading`, `${Math.floor(e)}deg`);
            let a = t * 600,
                o = Z.getZoom(),
                s = a / (40075016.686 * Math.cos(n * Math.PI / 180) / (256 * 2 ** o));
            (i = $.getElement()) == null || i.style.setProperty(`--distance`, `${Math.round(s)}px`)
        }
    };
Z.on(`zoomend`, () => {
    if (Q === 3 && Cb) {
        let {
            heading: e,
            speed: t,
            lat: n
        } = Cb;
        kb(e, t, n)
    }
});
const Ab = bt(function(e, t) {
        if (!t && typeof(e == null ? void 0 : e.heading) == `number` && $) {
            var n;
            Q !== 2 && (Q = 2, $ == null || $.setIcon(Eb)), (n = $.getElement()) == null || n.style.setProperty(`--heading`, `${Math.floor(e.heading)}deg`)
        } else if (Q !== 1) {
            Q = 1, $ == null || $.setIcon(Db);
            return
        }
    }, 300),
    jb = () => {
        Sb !== null && (clearTimeout(Sb), Sb = null)
    },
    Mb = async () => {
        Tb && (bb = await Tb.watchHeading({
            enableHighAccuracy: !0
        }, Ab))
    }, Nb = () => {
        if (jb(), Q = 1, $) {
            var e;
            $.setIcon(Db), (e = $.getElement()) == null || e.classList.remove(`hide-text`)
        }
        xb = !0, Mb()
    }, Pb = () => {
        jb(), Q === 3 && (Sb = setTimeout(() => {
            Q === 3 && Nb()
        }, 3e4))
    }, Fb = async () => {
        Tb && bb && (await Tb.clearWatch({
            id: bb
        }), bb = null)
    }, Ib = async (e, t) => {
        if (t || !e) {
            console.error(`Error getting position:`, t);
            return
        }
        let {
            coords: {
                latitude: n,
                longitude: r,
                speed: i,
                heading: a
            }
        } = e;
        $ ? $.setLatLng([n, r]) : $ = new f([n, r], {
            icon: Db,
            zIndexOffset: 5e3,
            interactive: !1
        }).addTo(Z);
        let o = i !== null && i >= 1 && a !== null;
        if (o && Q !== 3) {
            if (await Fb(), Q = 3, $.setIcon(Ob), kb(a, i, n), Pb(), xb) {
                var s;
                xb = !1, await fn(1e4), xb = !1, (s = $.getElement()) == null || s.classList.add(`hide-text`)
            }
        } else !o && Q === 3 ? Nb() : !o && Q !== 2 ? await Mb() : o && Q === 3 && (kb(a, i, n), Pb());
        if (_b) {
            let e = Z.getZoom();
            Z.setView([n, r], Math.max(e, 8)), _b = !1
        }
        M.set(`gpsLocation`, {
            lat: n,
            lon: r,
            source: `gps`,
            ts: Date.now()
        })
    }, Lb = () => {
        yb !== null && (navigator.geolocation.clearWatch(yb), yb = null)
    }, Rb = () => {
        vb !== null && wb && (wb.clearWatch({
            id: vb
        }), vb = null)
    }, zb = () => {
        M.set(`showMyPosition`, !1), Q = -1, gb = 0, $ && (Z.removeLayer($), $ = null), Lb(), Rb(), Fb(), jb(), Cb = null
    }, Bb = {
        enableHighAccuracy: !0,
        timeout: 2e4,
        maximumAge: 0
    }, Vb = async (e = !1) => {
        let t = e ? 1 : 2;
        t !== gb && (gb === 2 && t === 1 || (Q = -1, gb = t, _b = e, M.set(`showMyPosition`, !0), wb ? (Rb(), vb = await wb.watchPosition(Bb, Ib)) : navigator.geolocation ? (Lb(), yb = navigator.geolocation.watchPosition(Ib, e => {
            console.error(`Error getting position:`, e)
        }, Bb)) : (console.error(`Geolocation is not supported by this browser.`), zb()), e && (await fn(et * 2), gb === 1 && zb())))
    }, Hb = async (e = {}) => (Vb(!0), Mh(e));
var Ub = b({
    closeAllPlugins: () => Xb,
    closePanes: () => Jb
});
const Wb = e => e in Y,
    Gb = e => Wb(e) && Y[e] || null;

function Kb(e) {
    let t = Gb(e);
    t && !t.neverClose && t.close()
}

function qb(e, t) {
    for (let n of Object.keys(Y)) {
        let r = Y[n];
        if (r && r.isOpen && r.pane === t && n !== e) return r
    }
}
const Jb = (e, t) => {
    t.forEach(t => {
        let n = qb(e, t);
        n == null || n.close({
            disableClosingAnimation: !0
        })
    })
};
async function Yb(e, t) {
    let n = e in Y ? Y[e] : null;
    if (!n) {
        O(`pluginCtrl`, `Attempt to open non existent plugin: ${e}`);
        return
    }
    let r = e => n.open({
        params: t,
        disableOpeningAnimation: e
    });
    if (!n.pane) {
        r();
        return
    }
    let i = n.pane;
    switch (i) {
        case `bottom`:
            Jb(e, [`bottom`, `rhpane`, `top`, `fullscreen-mobile`]), r();
            break;
        case `center`:
            Jb(e, [`rhpane`, `center`, `fullscreen-mobile`]), r();
            break;
        case `fullscreen-mobile`:
        case `rhpane`:
            if (Jb(e, [`bottom`, `center`]), Y.multimodel.close({
                    disableClosingAnimation: !0
                }), x) Jb(e, [`rhpane`, `nearest`, `fullscreen-mobile`]), r();
            else {
                let t = qb(e, i),
                    n = !!t;
                if (t && (t.ident === `radiosonde` && e === `sounding` || t.ident === `sounding` && e === `radiosonde`)) {
                    t == null || t.close({
                        disableClosingAnimation: n
                    }), r(n);
                    return
                }
                r(n).then(() => {
                    t == null || t.close({
                        disableClosingAnimation: n
                    })
                })
            }
            break;
        case `small-bottom-bottom`:
            S && Jb(e, [`rhpane`, `fullscreen-mobile`]), Jb(e, [i]), r();
            break;
        default:
            Jb(e, [i]), r()
    }
}

function Xb(e) {
    Object.entries(Y).forEach(([t, n]) => {
        n.pane && n.isOpen && e !== t && Kb(t)
    })
}
N.on(`rqstOpen`, Yb), N.on(`rqstClose`, Kb);
var Zb = b({});
N.once(`dependenciesResolved`, () => {
    S ? S && N.emit(`rqstOpen`, `mobile-ui`) : (N.emit(`rqstOpen`, `rhpane-top`), N.emit(`rqstOpen`, `rhbottom`)), N.emit(`rqstOpen`, `search-input`)
});
const Qb = yt(() => {
    var e, t;
    let n = Z.getZoom(),
        r = M.get(`mapLibrary`),
        i = M.get(`overlay`);
    n > 11.5 && r !== `globe` && !((e = Y[`map-selector`]) != null && e.isOpen) ? N.emit(`rqstOpen`, `map-selector`) : n <= 11.5 && (t = Y[`map-selector`]) != null && t.isOpen && i !== `topoMap` && N.emit(`rqstClose`, `map-selector`)
}, 200);
Z.on(`zoomend`, Qb), Qb();
let $b = !1;
if (M.on(`connection`, async e => {
        e && $b ? ($b = !1, await fn(500), await Nr({
            type: `success`,
            html: P.MSG_ONLINE_APP,
            timeout: 1e4,
            onclick: () => window.location.reload()
        })) : ($b = !0, await Nr({
            type: `error`,
            html: P.MSG_OFFLINE
        }))
    }), window.top !== window.self && !/^http\S+windy\.com/.test(document.referrer)) {
    let e = document.getElementById(`unlegal-embed`);
    throw (e || document.body).style.display = `block`, Error(`Unlegal embed`)
}
addEventListener(`popstate`, async ({
    state: e
}) => {
    let {
        url: t,
        search: n
    } = e, r = gn(n), i = fh(n);
    await uh(t, `back-button`, r) || Xb(), i && i.sharedCoords && tv(i.sharedCoords)
});
var ex = b({
    getCounter: () => tx,
    hitCounter: () => rx,
    neverSee: () => ix,
    shouldDisplayPromo: () => ax
});
const tx = async e => await Ga.get(e) || {
    id: e,
    displayed: 0,
    ts: 0
}, nx = async (e, t) => {
    await Ga.put(e, {
        id: e,
        displayed: t,
        ts: Date.now()
    })
}, rx = async (e, t = !0) => {
    let {
        displayed: n
    } = await tx(e);
    await nx(e, n + 1), t && yl(`promo`, e)
}, ix = e => {
    nx(e, 1e3)
}, ax = async ({
    id: e,
    end: t,
    counter: n,
    delay: r = 0
}) => {
    let i = Date.now();
    if (t && i > new Date(t).getTime()) return !1;
    let {
        ts: a,
        displayed: o
    } = await tx(e);
    return o === 0 || o < n && i - a > r
};
var ox = b({
    loadPatch: () => mx,
    openArticle: () => ux,
    openLiveAlert: () => fx,
    openObsoleteApp: () => cx,
    openPin2Hp: () => px,
    openPromo: () => dx,
    openWhatsNewArticle: () => lx
});
const sx = async () => !!await Wf(e => !!(e.pin2homepage && e.pin2homepage > 0)), cx = async () => {
    try {
        let e = await lm();
        if (e === null) return !1;
        let {
            data: {
                majorVersion: t,
                releasedAt: n
            }
        } = e;
        return kx() ? !1 : t > Number(`50.1.2`.split(`.`)[0]) && Date.now() - new Date(n).getTime() > 30 * 864e5 ? (N.emit(`rqstOpen`, `startup-promos`, {
            typeOfPromo: `obsoleteApp`
        }), !0) : !1
    } catch (e) {
        return console.error(`Error loading or parsing latest.json:`, e), !1
    }
}, lx = async e => {
    try {
        let {
            data: t
        } = await e;
        if (!t || kx() || t.importance !== `whatsNew`) return !1;
        let {
            id: n
        } = t, r = `autoOpenArticle-${n}`;
        return !await ax({
            id: r,
            counter: 1
        }) || M.get(`sessionCounter`) <= 2 ? !1 : (rx(r), Tx(), N.emit(`rqstOpen`, `articles`, {
            id: n,
            autoOpened: !0
        }), !0)
    } catch (e) {
        return console.error(`Error opening whatsNew article:`, e), !1
    }
}, ux = async e => {
    try {
        let {
            data: t
        } = await e;
        if (kx() || !t) return !1;
        let {
            id: n
        } = t, r = `article-${n}`;
        if (!await ax({
                id: r,
                counter: 3
            })) return !1;
        N.emit(`rqstOpen`, `startup-articles`, {
            data: t
        });
        let {
            ts: i
        } = await tx(r);
        return Date.now() - i > 36e5 && rx(r), !0
    } catch (e) {
        return console.error(`Error loading and opening article:`, e), !1
    }
}, dx = async e => {
    try {
        let {
            data: t,
            status: n
        } = await e;
        if (n !== 200 || t.content.trim() === `` || kx() || !t) return !1;
        let r = `featuredPromo-${t.id}`;
        return await ax({
            id: r,
            counter: 200,
            delay: 3 * 864e5
        }) ? (N.emit(`rqstOpen`, `startup-promos`, {
            data: t,
            typeOfPromo: `featured`
        }), rx(r), !0) : !1
    } catch (e) {
        return console.error(`Error loading and opening promo:`, e), !1
    }
}, fx = async (e, t) => {
    try {
        let {
            data: n
        } = await t;
        return kx() ? !1 : n.alerts.length > 0 ? (N.emit(`rqstOpen`, `startup-live-alerts`, {
            alerts: n.alerts,
            coords: e
        }), !0) : !1
    } catch (e) {
        return console.error(`Error loading live alerts:`, e), !1
    }
}, px = async () => {
    await hp() && await sx() && !kx() && N.emit(`rqstOpen`, `startup-pin2hp`)
}, mx = async () => {
    let e = `?refTime=${new Date().toISOString().replace(/^(.*):.*$/, `$1`)}`;
    try {
        await import(`https://www.windy.com/patch/v9/patch.js${e}`)
    } catch (e) {
        console.error(`Failed to load/run patch`, e)
    }
};
var hx = b({
    addDefaultListeners: () => bx,
    back2home: () => Ox,
    closeAllStartupPlugins: () => wx,
    hideStartupElements: () => Tx,
    shouldHideStartupElements: () => kx,
    showStartupElements: () => Sx,
    unsetShouldBeHidden: () => jx
});
let gx = !1,
    _x = !1;
const vx = Z.maplibreMap.getContainer(),
    yx = window.innerHeight > 750;

function bx() {
    _x || (document.body.addEventListener(`click`, Cx, !0), vx.addEventListener(`mousedown`, Tx, !0), vx.addEventListener(`touchstart`, Tx, !0), vx.addEventListener(`wheel`, Tx, !0), document.body.addEventListener(`keydown`, Tx), _x = !0)
}

function xx() {
    _x && (document.body.removeEventListener(`click`, Cx, !0), vx.removeEventListener(`mousedown`, Tx, !0), vx.removeEventListener(`touchstart`, Tx, !0), vx.removeEventListener(`wheel`, Tx, !0), document.body.removeEventListener(`keydown`, Tx), _x = !1)
}
async function Sx(e) {
    if (gx) return;
    let t = {
        capAlerts: Kp(e),
        wx: Lp(`ecmwf`, e, {
            setup: `summary`,
            includeNow: `true`,
            source: `hp`
        }, {
            cache: !1
        }),
        liveAlertsPromise: rm(e),
        articlePromise: om(e),
        promoPromise: sm(e)
    };
    N.emit(`rqstOpen`, `startup-weather`, {
        coords: e,
        promises: t
    }), px(), !await cx() && (await lx(t.articlePromise) || yx && (!gx && await fx(e, t.liveAlertsPromise) || !gx && await ux(t.articlePromise) || !gx && await dx(t.promoPromise)))
}

function Cx(e) {
    if (e && e.target) {
        let t = e.target;
        for (; t && t !== document.body;) {
            if (t && t.dataset && t.dataset.ignore === `hp`) return;
            t = t.parentElement
        }
    }
    Tx()
}
const wx = (e = !0) => {
    e && (N.emit(`rqstClose`, `startup-weather`), N.emit(`rqstClose`, `startup-pin2hp`), N.emit(`rqstClose`, `startup-debug`)), N.emit(`rqstClose`, `startup-articles`), N.emit(`rqstClose`, `startup-live-alerts`), N.emit(`rqstClose`, `startup-promos`)
};

function Tx() {
    gx || (gx = !0, wx(), xx())
}
async function Ex() {
    bx();
    try {
        await Sx(await Fh())
    } catch (e) {
        await Sx(jh()), O(`startup.ts`, `Unable to get home location, using fallback`, e)
    }
}
async function Dx() {
    await cx() || await lx(om(jh()))
}
async function Ox() {
    bx(), Xb(`startup-weather`), M.set(`timestamp`, Date.now()), gx = !1;
    let e = await Fh();
    Sx(e);
    let t = M.get(`startUpZoom`),
        n = t == null ? `zoom` in e ? e.zoom : 5 : t;
    tv({
        lat: e.lat,
        lon: e.lon,
        zoom: n
    })
}
N.on(`back2home`, Ox);
const kx = () => gx;

function Ax() {
    return !1
}
const jx = () => gx = !1;
N.once(`dependenciesResolved`, () => {
    if (Ax() ? N.emit(`rqstOpen`, `onboarding`) : M.get(`showWeather`) && !yh ? Ex() : Dx(), !S) {
        let e = Kt(`[data-ref="back2home"]`);
        e ? e.onclick = Ox : O(`startup.ts`, `Unable to hook up back2home icon`)
    }
    mx()
});
var Mx = b({});
const Nx = (e, t) => {
    let n = M.get(`timestamp`),
        r = qc(e.timestamps, n, !1);
    if (r != null && !(r === e.timestamps.length - 1 && t === `ArrowRight`) && !(r === 0 && t === `ArrowLeft`)) {
        let n = t === `ArrowLeft` ? r - 1 : r + 1,
            i = e.timestamps[n];
        M.set(`timestamp`, i, {
            UIident: `keyboard`
        })
    }
};

function Px(e) {
    let {
        key: t
    } = e, n = !1;
    if ((t === `ArrowLeft` || t === `ArrowRight`) && !e.shiftKey && typeof K[M.get(`product`)].calendar == `object`) {
        let e = M.get(`calendar`);
        e && (Nx(e, t), n = !0)
    } else t === `f` ? (N.emit(`rqstOpen`, `search`), n = !0) : t === `+` ? (N.emit(`zoomIn`), n = !0) : t === `-` && (N.emit(`zoomOut`), n = !0);
    n && e.preventDefault()
}
x || document.body.addEventListener(`keydown`, Px, !1);
var Fx = b({});
const Ix = document.body.classList;

function Lx() {
    setInterval(() => {
        Ix.add(`animate-logo`), setTimeout(() => Ix.remove(`animate-logo`), 2e3)
    }, 30 * 1e3)
}
N.once(`dependenciesResolved`, Lx);
const Rx = bt(async () => {
    let e = M.get(`timestamp`),
        t = K[M.get(`product`)],
        n = Is[M.get(`overlay`)],
        r = t == null ? void 0 : t.calendar,
        i = e + (n.isAccu ? M.get(`acRange`) * T : 0),
        a = !!(r != null && r.premiumStart && i > r.premiumStart),
        o = !!(r != null && r.premiumEnd && i < r.premiumEnd),
        s = !!(!U() && (a || o));
    se(document.body, s, `premium-calendar`)
}, 1e3);
U() || (M.on(`subscription`, Rx), N.on(`redrawFinished`, Rx));
var zx = b({
    emitter: () => Vx,
    get: () => Wx,
    hideLoader: () => Kx,
    reset: () => Ux,
    set: () => Hx,
    showLoader: () => Gx
});
let Bx = null;
const Vx = new Ln({
        ident: `query`
    }),
    Hx = (e, t) => {
        Bx = t, M.set(`searchInputValue`, e)
    },
    Ux = e => {
        Bx === e && (M.set(`searchInputValue`, ``), Bx = null)
    },
    Wx = () => M.get(`searchInputValue`),
    Gx = () => void M.set(`searchInputLoading`, !0),
    Kx = () => void M.set(`searchInputLoading`, !1);
var qx = b({});
let Jx = !1,
    Yx, Xx, Zx = 2,
    Qx = 0,
    $x;
const eS = {
        normal: 2,
        fast: 8,
        "very-fast": 16
    },
    tS = () => M.set(`animation`, !1),
    nS = e => {
        e !== `picker-mobile` && tS()
    },
    rS = e => {
        e || tS()
    },
    iS = e => /Accu$/.test(e) && tS(),
    aS = e => {
        let {
            timestamps: t
        } = e;
        return t[1] - t[0] < 2 * T
    };

function oS() {
    let e = M.get(`timestamp`) + Qx * Zx;
    e < $x ? (M.set(`timestamp`, e), Yx = setTimeout(oS, 50)) : tS()
}

function sS(e) {
    Zx = eS[e]
}

function cS() {
    let e = M.get(`calendar`);
    if (Xx = K[M.get(`product`)], !Xx.animation || !e) {
        tS();
        return
    }
    Jx = !0, Zx = eS[M.get(`animationSpeed`)], Qx = 50 * (aS(e) ? Xx.animationSpeed1h : Xx.animationSpeed), $x = U() || !e.premiumStart ? e.end : e.premiumStart, M.get(`timestamp`) + Qx * Zx >= $x && M.set(`timestamp`, Date.now()), M.on(`visibility`, rS), M.on(`product`, tS), M.on(`animationSpeed`, sS), M.on(`overlay`, iS), N.on(`pluginOpened`, nS), oS(), bl(`animation-started`)
}

function lS() {
    Jx = !1, clearTimeout(Yx), M.off(`visibility`, rS), M.off(`product`, tS), M.off(`overlay`, iS), M.off(`animationSpeed`, sS), N.off(`pluginOpened`, nS)
}
M.on(`animation`, e => {
    e !== Jx && (e ? cS() : lS())
});
var uS = b({});
`hidden` in document && document.addEventListener(`visibilitychange`, () => {
    M.set(`visibility`, !document.hidden)
});
var dS = b({
    share: () => fS
});
const fS = () => {
    let e = Cm();
    navigator.share ? navigator.share({
        text: `Great stuff on Windy.com`,
        url: e
    }).catch(e => {
        (e == null ? void 0 : e.name) !== `AbortError` && O(`nativeShareDialog`, e)
    }) : N.emit(`rqstOpen`, `share`)
};
var pS = b({
    getLatLonInterpolator: () => hS,
    getXYInterpolator: () => gS
});
const mS = () => {
        for (let e in Uy) {
            let t = Uy[e];
            if (t.isOpen && t.interpolator) return t.interpolator
        }
    },
    hS = () => new Promise(e => {
        let t = mS();
        t ? t.createFun(t => e(t)) : e(null)
    }),
    gS = () => new Promise(e => {
        let t = mS();
        t ? t.createFun((t, n) => e(n)) : e(null)
    });
var _S = b({});
const vS = (e, ...t) => {
    let n = M.get(`mapLibrary`);
    N.emit(`${n}-${e}`, ...t)
};
N.on(`zoomIn`, vS.bind(null, `zoomIn`)), N.on(`zoomOut`, vS.bind(null, `zoomOut`)), N.on(`paramsChanged`, vS.bind(null, `paramsChanged`));
var yS = b({
    PickerDot: () => wS,
    emitter: () => CS,
    pickerDot: () => TS
});
const bS = S ? Object.keys(Y).map(e => Y[e]).filter(e => e && e.disableMobilePicker) : [],
    xS = e => N.emit(`rqstOpen`, `picker`, e),
    SS = e => {
        for (let e = 0; e < bS.length; e++)
            if (bS[e].isOpen) return;
        N.emit(`rqstOpen`, `picker-mobile`, e)
    };
S ? (Z.on(`dragstart`, () => SS()), ud.on(`click`, () => SS())) : ud.on(`click`, xS);
const CS = new Ln({
    ident: `picker`
});
var wS = class {
    constructor() {
        C(this, `pickerDotEl`, void 0), C(this, `mapContainerEl`, void 0), C(this, `lat`, null), C(this, `lon`, null), S && (this.mapContainerEl = Kt(`#map-container`), this.pickerDotEl = Kt(`#picker-dot`), Z.on(`resize`, this.positionChanged.bind(this)))
    }
    lockPosition() {
        let e = this.getLatLon();
        return this.lat = e.lat, this.lon = e.lon, e
    }
    unlockPosition() {
        this.lat = null, this.lon = null
    }
    setPosition(e, t) {
        let {
            y: n
        } = this.getDotPosition();
        rv(n, e, t), this.lat = e, this.lon = t
    }
    offsetPosition(e) {
        this.mapContainerEl.style.transform = e > 0 ? `translateY(-${Math.floor(e / 2)}px)` : ``
    }
    resetOffset() {
        this.offsetPosition(0)
    }
    getLatLng() {
        let {
            x: e,
            y: t
        } = this.getDotPosition();
        return Z.containerPointToLatLng([e, t])
    }
    getLatLon(e, t) {
        let {
            lat: n,
            lng: r
        } = e !== void 0 && t !== void 0 ? Z.containerPointToLatLng([e, t]) : this.getLatLng();
        return {
            lat: n,
            lon: r
        }
    }
    getDotPosition() {
        return {
            x: this.pickerDotEl.offsetLeft + this.pickerDotEl.offsetWidth / 2,
            y: this.pickerDotEl.offsetTop + this.pickerDotEl.offsetHeight / 2
        }
    }
    positionChanged() {
        this.lat !== null && this.lon !== null && this.setPosition(this.lat, this.lon)
    }
};
const TS = new wS;
async function ES() {
    await hp() && await Ka.loadFromCloud() && N.emit(`redrawLayers`)
}
ES();
const DS = 10 * 1e3,
    OS = `error`,
    kS = {
        android: `Android`,
        ios: `iOS`,
        desktop: `browser`
    }.desktop;
typeof ResizeObserver > `u` && (Nr({
    type: OS,
    html: St(P.BROWSER_SUPPORT_ERROR, {
        platform: kS,
        technology: `ResizeObserver`
    }),
    timeout: DS
}), O(`compatibility-check`, `ResizeObserver not supported`)), typeof indexedDB > `u` && (Nr({
    type: OS,
    html: St(P.BROWSER_SUPPORT_ERROR, {
        platform: kS,
        technology: `IndexedDB`
    }),
    timeout: DS
}), O(`compatibility-check`, `IndexedDB not supported`)), N.emit(`dependenciesResolved`);
export {
    id as BottomSlide, Jc as Calendar, Qa as Color, ed as Drag, Yv as EventManager, In as Evented, Xm as ExternalSveltePlugin, Na as IDB, z_ as LabelsLayer, Ls as Layer, ji as Metric, Ni as MetricClasses, no as Overlay, ro as OverlayClasses, od as Plugin, jl as Product, $v as Renderer, py as ShaderStorage, bd as SveltePanePlugin, _d as SveltePlugin, nd as Swipe, jy as SwitchableTileCache, Cd as TagPlugin, zy as TileLayer, d_ as TileLayerUtils, ty as TilePreprocessor, Or as Window, hd as WindowPlugin, Kd as alerts, Zf as appsFlyer, Gh as baseMap, N as broadcast, B_ as cityLabels, Td as cloudSync, B as colors, Zb as components, Qn as connection, ae as css, Lh as customProtocol, A as dataSpecifications, ue as detectDevice, ar as device, Id as deviceLogging, Rm as errorLogger, Ke as errors, Qm as externalPlugins, Dp as fetch, oi as format, el as ga, kh as geolocation, qg as glUtils, Pr as http, Ra as idbInstances, pS as interpolator, Mx as keyboard, k_ as landLayer, Kc as layers, Zv as levelUtils, Vd as liveAlerts, um as location, fl as log, fr as lruCache, G_ as map, _S as mapGlobeCtrl, Ov as mapUtils, R as metrics, Vu as models, df as notifications, Is as overlays, Jy as params, Fx as permanentPromos, yS as picker, Y as plugins, Ub as pluginsCtrl, ib as pois, K as products, ex as promo, Tf as pushNotifications, zx as query, Wy as renderCtrl, $h as renderUtils, Uy as renderers, Nf as reverseName, Xc as rhMessage, me as rootScope, ih as router, dS as share, hb as showMyPosition, Sh as showableErrorsService, cd as singleclick, hx as startup, ox as startupUtils, j as storage, M as store, xl as subscription, qv as throttler, xy as tileInterpolator, S_ as tileLayerSource, qx as timeAnimation, Ar as topMessage, hr as trans, op as user, Xd as userAlerts, lb as userAlertsEnums, Df as userConsent, Ff as userFavs, Qe as utils, uS as visibility
};
W.BottomSlide = id, W.Calendar = Jc, W.Color = Qa, W.Drag = ed, W.EventManager = Yv, W.Evented = In, W.ExternalSveltePlugin = Xm, W.IDB = Na, W.LabelsLayer = z_, W.Layer = Ls, W.Metric = ji, W.MetricClasses = Ni, W.Overlay = no, W.OverlayClasses = ro, W.Plugin = od, W.Product = jl, W.Renderer = $v, W.ShaderStorage = py, W.SveltePanePlugin = bd, W.SveltePlugin = _d, W.Swipe = nd, W.SwitchableTileCache = jy, W.TagPlugin = Cd, W.TileLayer = zy, W.TileLayerUtils = d_, W.TilePreprocessor = ty, W.Window = Or, W.WindowPlugin = hd, W.alerts = Kd, W.appsFlyer = Zf, W.baseMap = Gh, W.broadcast = N, W.cityLabels = B_, W.cloudSync = Td, W.colors = B, W.components = Zb, W.connection = Qn, W.css = ae, W.customProtocol = Lh, W.dataSpecifications = A, W.detectDevice = ue, W.device = ar, W.deviceLogging = Id, W.errorLogger = Rm, W.errors = Ke, W.externalPlugins = Qm, W.fetch = Dp, W.format = oi, W.ga = el, W.geolocation = kh, W.glUtils = qg, W.http = Pr, W.idbInstances = Ra, W.interpolator = pS, W.keyboard = Mx, W.landLayer = k_, W.layers = Kc, W.levelUtils = Zv, W.liveAlerts = Vd, W.location = um, W.log = fl, W.lruCache = fr, W.map = G_, W.mapGlobeCtrl = _S, W.mapUtils = Ov, W.metrics = R, W.models = Vu, W.notifications = df, W.overlays = Is, W.params = Jy, W.permanentPromos = Fx, W.picker = yS, W.plugins = Y, W.pluginsCtrl = Ub, W.pois = ib, W.products = K, W.promo = ex, W.pushNotifications = Tf, W.query = zx, W.renderCtrl = Wy, W.renderUtils = $h, W.renderers = Uy, W.reverseName = Nf, W.rhMessage = Xc, W.rootScope = me, W.router = ih, W.share = dS, W.showMyPosition = hb, W.showableErrorsService = Sh, W.singleclick = cd, W.startup = hx, W.startupUtils = ox, W.storage = j, W.store = M, W.subscription = xl, W.throttler = qv, W.tileInterpolator = xy, W.tileLayerSource = S_, W.timeAnimation = qx, W.topMessage = Ar, W.trans = hr, W.user = op, W.userAlerts = Xd, W.userAlertsEnums = lb, W.userConsent = Df, W.userFavs = Ff, W.utils = Qe, W.visibility = uS;