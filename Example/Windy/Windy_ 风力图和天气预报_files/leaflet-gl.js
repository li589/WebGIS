/**
 * Leaflet & MapLibre GL
 * @license 3-Clause BSD. Full text of license: https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt & https://github.com/Leaflet/Leaflet/blob/main/LICENSE
 * @version 5.0.0-beta.7
 * @commit 9280387b2
 * @built 2026-06-11T07:50:20.818Z
 */
function t(t) {
    if (null != t && "number" == typeof t) return t - 1
}

function e(t, e) {
    if (0 == e) return t;
    const i = Math.pow(10, void 0 === e ? 6 : e);
    return Math.round(t * i) / i
}

function i(t, e, i) {
    const s = e[1],
        n = e[0],
        r = s - n;
    return t === s && i ? t : ((t - n) % r + r) % r + n
}

function s(t) {
    return t.trim().split(/\s+/)
}
let n;

function r(t) {
    if (!("_leaflet_id" in t)) {
        if (!n) {
            const t = function() {
                if ("undefined" != typeof globalThis) return globalThis;
                if ("undefined" != typeof self) return self;
                if ("undefined" != typeof window) return window;
                throw Error("Unable to locate global object.")
            }();
            t.leafletGLstampIdContainer || (t.leafletGLstampIdContainer = {
                lastId: 0
            }), n = t.leafletGLstampIdContainer
        }
        t._leaflet_id = ++n.lastId
    }
    return t._leaflet_id
}

function o() {
    return 0
}
class a extends Error {
    constructor() {
        super("This layer is not in a map.")
    }
}
class h {
    constructor(t, e, i) {
        this.x = i ? Math.round(t) : t, this.y = i ? Math.round(e) : e
    }
    clone() {
        return new h(this.x, this.y)
    }
    add(t) {
        return this.clone()._add(l(t))
    }
    _add(t) {
        return this.x += t.x, this.y += t.y, this
    }
    subtract(t) {
        return this.clone()._subtract(l(t))
    }
    _subtract(t) {
        return this.x -= t.x, this.y -= t.y, this
    }
    divideBy(t) {
        return this.clone()._divideBy(t)
    }
    _divideBy(t) {
        return this.x /= t, this.y /= t, this
    }
    multiplyBy(t) {
        return this.clone()._multiplyBy(t)
    }
    _multiplyBy(t) {
        return this.x *= t, this.y *= t, this
    }
    scaleBy(t) {
        return new h(this.x * t.x, this.y * t.y)
    }
    unscaleBy(t) {
        return new h(this.x / t.x, this.y / t.y)
    }
    round() {
        return this.clone()._round()
    }
    _round() {
        return this.x = Math.round(this.x), this.y = Math.round(this.y), this
    }
    floor() {
        return this.clone()._floor()
    }
    _floor() {
        return this.x = Math.floor(this.x), this.y = Math.floor(this.y), this
    }
    ceil() {
        return this.clone()._ceil()
    }
    _ceil() {
        return this.x = Math.ceil(this.x), this.y = Math.ceil(this.y), this
    }
    trunc() {
        return this.clone()._trunc()
    }
    _trunc() {
        return this.x = Math.trunc(this.x), this.y = Math.trunc(this.y), this
    }
    distanceTo(t) {
        const e = l(t),
            i = e.x - this.x,
            s = e.y - this.y;
        return Math.sqrt(i * i + s * s)
    }
    equals(t) {
        const e = l(t);
        return e.x === this.x && e.y === this.y
    }
    contains(t) {
        const e = l(t);
        return Math.abs(e.x) <= Math.abs(this.x) && Math.abs(e.y) <= Math.abs(this.y)
    }
    toString() {
        return `Point(${e(this.x)} ${e(this.y)})`
    }
    sub(t) {
        return this.clone()._subtract(l(t))
    }
    _sub(t) {
        return this.x -= t.x, this.y -= t.y, this
    }
    divByPoint(t) {
        return this.clone()._divByPoint(l(t))
    }
    _divByPoint(t) {
        return this.x /= t.x, this.y /= t.y, this
    }
    div(t) {
        return this.clone()._divideBy(t)
    }
    _div(t) {
        return this.x /= t, this.y /= t, this
    }
    mult(t) {
        return this.clone()._multiplyBy(t)
    }
    _mult(t) {
        return this.x *= t, this.y *= t, this
    }
    multByPoint(t) {
        return this.clone()._multByPoint(l(t))
    }
    _multByPoint(t) {
        return this.x *= t.x, this.y *= t.y, this
    }
    rotate(t) {
        return this.clone()._rotate(t)
    }
    rotateAround(t, e) {
        return this.clone()._rotateAround(t, e)
    }
    matMult(t) {
        return this.clone()._matMult(t)
    }
    unit() {
        return this.clone()._unit()
    }
    perp() {
        return this.clone()._perp()
    }
    mag() {
        return Math.sqrt(this.x * this.x + this.y * this.y)
    }
    dist(t) {
        return Math.sqrt(this.distSqr(t))
    }
    distSqr(t) {
        const e = t.x - this.x,
            i = t.y - this.y;
        return e * e + i * i
    }
    angle() {
        return Math.atan2(this.y, this.x)
    }
    angleTo(t) {
        return Math.atan2(this.y - t.y, this.x - t.x)
    }
    angleWith(t) {
        return this.angleWithSep(t.x, t.y)
    }
    angleWithSep(t, e) {
        return Math.atan2(this.x * e - this.y * t, this.x * t + this.y * e)
    }
    _matMult(t) {
        const e = t[2] * this.x + t[3] * this.y;
        return this.x = t[0] * this.x + t[1] * this.y, this.y = e, this
    }
    _unit() {
        return this._div(this.mag()), this
    }
    _perp() {
        const t = this.y;
        return this.y = this.x, this.x = -t, this
    }
    _rotate(t) {
        const e = Math.cos(t),
            i = Math.sin(t),
            s = i * this.x + e * this.y;
        return this.x = e * this.x - i * this.y, this.y = s, this
    }
    _rotateAround(t, e) {
        const i = Math.cos(t),
            s = Math.sin(t),
            n = e.y + s * (this.x - e.x) + i * (this.y - e.y);
        return this.x = e.x + i * (this.x - e.x) - s * (this.y - e.y), this.y = n, this
    }
    static convert(t) {
        return l(t)
    }
}

function l(t, e, i) {
    return t instanceof h ? t : Array.isArray(t) ? new h(t[0], t[1]) : void 0 !== t ? null === t ? null : "number" == typeof t ? "number" == typeof e ? new h(t, e, i) : new h(t, t) : "object" == typeof t && "x" in t && "y" in t ? new h(+t.x, +t.y) : void 0 : void 0
}
class c extends h {
    constructor(t, e, i, s) {
        super(t, e, s), this.z = s ? Math.round(i) : i
    }
}

function u(t) {
    return t && t.__esModule && Object.prototype.hasOwnProperty.call(t, "default") ? t.default : t
}
var d, p, _ = function() {
        if (p) return d;

        function t(t, e, i, s) {
            this.cx = 3 * t, this.bx = 3 * (i - t) - this.cx, this.ax = 1 - this.cx - this.bx, this.cy = 3 * e, this.by = 3 * (s - e) - this.cy, this.ay = 1 - this.cy - this.by, this.p1x = t, this.p1y = e, this.p2x = i, this.p2y = s
        }
        return p = 1, d = t, t.prototype = {
            sampleCurveX: function(t) {
                return ((this.ax * t + this.bx) * t + this.cx) * t
            },
            sampleCurveY: function(t) {
                return ((this.ay * t + this.by) * t + this.cy) * t
            },
            sampleCurveDerivativeX: function(t) {
                return (3 * this.ax * t + 2 * this.bx) * t + this.cx
            },
            solveCurveX: function(t, e) {
                if (void 0 === e && (e = 1e-6), t < 0) return 0;
                if (t > 1) return 1;
                for (var i = t, s = 0; s < 8; s++) {
                    var n = this.sampleCurveX(i) - t;
                    if (Math.abs(n) < e) return i;
                    var r = this.sampleCurveDerivativeX(i);
                    if (Math.abs(r) < 1e-6) break;
                    i -= n / r
                }
                var o = 0,
                    a = 1;
                for (i = t, s = 0; s < 20 && (n = this.sampleCurveX(i), !(Math.abs(n - t) < e)); s++) t > n ? o = i : a = i, i = .5 * (a - o) + o;
                return i
            },
            solve: function(t, e) {
                return this.sampleCurveY(this.solveCurveX(t, e))
            }
        }, d
    }(),
    m = u(_),
    f = "undefined" != typeof Float32Array ? Float32Array : Array;

function g(t) {
    return t[0] = 1, t[1] = 0, t[2] = 0, t[3] = 0, t[4] = 0, t[5] = 1, t[6] = 0, t[7] = 0, t[8] = 0, t[9] = 0, t[10] = 1, t[11] = 0, t[12] = 0, t[13] = 0, t[14] = 0, t[15] = 1, t
}

function y(t, e) {
    var i = e[0],
        s = e[1],
        n = e[2],
        r = e[3],
        o = e[4],
        a = e[5],
        h = e[6],
        l = e[7],
        c = e[8],
        u = e[9],
        d = e[10],
        p = e[11],
        _ = e[12],
        m = e[13],
        f = e[14],
        g = e[15],
        y = i * a - s * o,
        v = i * h - n * o,
        b = i * l - r * o,
        x = s * h - n * a,
        w = s * l - r * a,
        T = n * l - r * h,
        M = c * m - u * _,
        P = c * f - d * _,
        E = c * g - p * _,
        L = u * f - d * m,
        C = u * g - p * m,
        S = d * g - p * f,
        R = y * S - v * C + b * L + x * E - w * P + T * M;
    return R ? (t[0] = (a * S - h * C + l * L) * (R = 1 / R), t[1] = (n * C - s * S - r * L) * R, t[2] = (m * T - f * w + g * x) * R, t[3] = (d * w - u * T - p * x) * R, t[4] = (h * E - o * S - l * P) * R, t[5] = (i * S - n * E + r * P) * R, t[6] = (f * b - _ * T - g * v) * R, t[7] = (c * T - d * b + p * v) * R, t[8] = (o * C - a * E + l * M) * R, t[9] = (s * E - i * C - r * M) * R, t[10] = (_ * w - m * b + g * y) * R, t[11] = (u * b - c * w - p * y) * R, t[12] = (a * P - o * L - h * M) * R, t[13] = (i * L - s * P + n * M) * R, t[14] = (m * v - _ * x - f * y) * R, t[15] = (c * x - u * v + d * y) * R, t) : null
}

function v(t, e, i) {
    var s = e[0],
        n = e[1],
        r = e[2],
        o = e[3],
        a = e[4],
        h = e[5],
        l = e[6],
        c = e[7],
        u = e[8],
        d = e[9],
        p = e[10],
        _ = e[11],
        m = e[12],
        f = e[13],
        g = e[14],
        y = e[15],
        v = i[0],
        b = i[1],
        x = i[2],
        w = i[3];
    return t[0] = v * s + b * a + x * u + w * m, t[1] = v * n + b * h + x * d + w * f, t[2] = v * r + b * l + x * p + w * g, t[3] = v * o + b * c + x * _ + w * y, t[4] = (v = i[4]) * s + (b = i[5]) * a + (x = i[6]) * u + (w = i[7]) * m, t[5] = v * n + b * h + x * d + w * f, t[6] = v * r + b * l + x * p + w * g, t[7] = v * o + b * c + x * _ + w * y, t[8] = (v = i[8]) * s + (b = i[9]) * a + (x = i[10]) * u + (w = i[11]) * m, t[9] = v * n + b * h + x * d + w * f, t[10] = v * r + b * l + x * p + w * g, t[11] = v * o + b * c + x * _ + w * y, t[12] = (v = i[12]) * s + (b = i[13]) * a + (x = i[14]) * u + (w = i[15]) * m, t[13] = v * n + b * h + x * d + w * f, t[14] = v * r + b * l + x * p + w * g, t[15] = v * o + b * c + x * _ + w * y, t
}

function b(t, e, i) {
    var s, n, r, o, a, h, l, c, u, d, p, _, m = i[0],
        f = i[1],
        g = i[2];
    return e === t ? (t[12] = e[0] * m + e[4] * f + e[8] * g + e[12], t[13] = e[1] * m + e[5] * f + e[9] * g + e[13], t[14] = e[2] * m + e[6] * f + e[10] * g + e[14], t[15] = e[3] * m + e[7] * f + e[11] * g + e[15]) : (n = e[1], r = e[2], o = e[3], a = e[4], h = e[5], l = e[6], c = e[7], u = e[8], d = e[9], p = e[10], _ = e[11], t[0] = s = e[0], t[1] = n, t[2] = r, t[3] = o, t[4] = a, t[5] = h, t[6] = l, t[7] = c, t[8] = u, t[9] = d, t[10] = p, t[11] = _, t[12] = s * m + a * f + u * g + e[12], t[13] = n * m + h * f + d * g + e[13], t[14] = r * m + l * f + p * g + e[14], t[15] = o * m + c * f + _ * g + e[15]), t
}

function x(t, e, i) {
    var s = i[0],
        n = i[1],
        r = i[2];
    return t[0] = e[0] * s, t[1] = e[1] * s, t[2] = e[2] * s, t[3] = e[3] * s, t[4] = e[4] * n, t[5] = e[5] * n, t[6] = e[6] * n, t[7] = e[7] * n, t[8] = e[8] * r, t[9] = e[9] * r, t[10] = e[10] * r, t[11] = e[11] * r, t[12] = e[12], t[13] = e[13], t[14] = e[14], t[15] = e[15], t
}

function w(t, e, i) {
    var s = Math.sin(i),
        n = Math.cos(i),
        r = e[4],
        o = e[5],
        a = e[6],
        h = e[7],
        l = e[8],
        c = e[9],
        u = e[10],
        d = e[11];
    return e !== t && (t[0] = e[0], t[1] = e[1], t[2] = e[2], t[3] = e[3], t[12] = e[12], t[13] = e[13], t[14] = e[14], t[15] = e[15]), t[4] = r * n + l * s, t[5] = o * n + c * s, t[6] = a * n + u * s, t[7] = h * n + d * s, t[8] = l * n - r * s, t[9] = c * n - o * s, t[10] = u * n - a * s, t[11] = d * n - h * s, t
}

function T(t, e, i) {
    var s = Math.sin(i),
        n = Math.cos(i),
        r = e[0],
        o = e[1],
        a = e[2],
        h = e[3],
        l = e[4],
        c = e[5],
        u = e[6],
        d = e[7];
    return e !== t && (t[8] = e[8], t[9] = e[9], t[10] = e[10], t[11] = e[11], t[12] = e[12], t[13] = e[13], t[14] = e[14], t[15] = e[15]), t[0] = r * n + l * s, t[1] = o * n + c * s, t[2] = a * n + u * s, t[3] = h * n + d * s, t[4] = l * n - r * s, t[5] = c * n - o * s, t[6] = u * n - a * s, t[7] = d * n - h * s, t
}
var M = function(t, e, i, s, n) {
    var r = 1 / Math.tan(e / 2);
    if (t[0] = r / i, t[1] = 0, t[2] = 0, t[3] = 0, t[4] = 0, t[5] = r, t[6] = 0, t[7] = 0, t[8] = 0, t[9] = 0, t[11] = -1, t[12] = 0, t[13] = 0, t[15] = 0, null != n && n !== 1 / 0) {
        var o = 1 / (s - n);
        t[10] = (n + s) * o, t[14] = 2 * n * s * o
    } else t[10] = -1, t[14] = -2 * s;
    return t
};

function P() {
    var t = new f(3);
    return f != Float32Array && (t[0] = 0, t[1] = 0, t[2] = 0), t
}

function E(t) {
    var e = new f(3);
    return e[0] = t[0], e[1] = t[1], e[2] = t[2], e
}

function L(t, e, i) {
    var s = new f(3);
    return s[0] = t, s[1] = e, s[2] = i, s
}

function C(t, e, i) {
    return t[0] = e[0] + i[0], t[1] = e[1] + i[1], t[2] = e[2] + i[2], t
}

function S(t, e, i) {
    return t[0] = e[0] * i, t[1] = e[1] * i, t[2] = e[2] * i, t
}
var R, I = function(t, e, i) {
    return t[0] = e[0] - i[0], t[1] = e[1] - i[1], t[2] = e[2] - i[2], t
};

function A(t, e) {
    return t[0] * e[0] + t[1] * e[1] + t[2] * e[2] + t[3] * e[3]
}

function z(t, e, i) {
    var s = e[0],
        n = e[1],
        r = e[2],
        o = e[3];
    return t[0] = i[0] * s + i[4] * n + i[8] * r + i[12] * o, t[1] = i[1] * s + i[5] * n + i[9] * r + i[13] * o, t[2] = i[2] * s + i[6] * n + i[10] * r + i[14] * o, t[3] = i[3] * s + i[7] * n + i[11] * r + i[15] * o, t
}

function O() {
    var t = new f(4);
    return f != Float32Array && (t[0] = 0, t[1] = 0, t[2] = 0), t[3] = 1, t
}
P(),
    function() {
        var t;
        t = new f(4), f != Float32Array && (t[0] = 0, t[1] = 0, t[2] = 0, t[3] = 0)
    }(), P(), L(1, 0, 0), L(0, 1, 0), O(), O(), R = new f(9), f != Float32Array && (R[1] = 0, R[2] = 0, R[3] = 0, R[5] = 0, R[6] = 0, R[7] = 0), R[0] = 1, R[4] = 1, R[8] = 1;
var k = function(t) {
    var e = t[0],
        i = t[1];
    return e * e + i * i
};
! function() {
    var t = new f(2);
    f != Float32Array && (t[0] = 0, t[1] = 0)
}();
const D = 8192,
    B = JSON.parse("true");

function F() {
    return new Float64Array(16)
}

function Z() {
    const t = new Float32Array(16);
    return g(t), t
}

function N(t, e, i, s) {
    const n = new m(t, e, i, s);
    return t => n.solve(t)
}
const j = N(.25, .1, .25, 1);

function U(t, e, i) {
    return Math.min(i, Math.max(e, t))
}

function G(t, e, i) {
    const s = i - e,
        n = ((t - e) % s + s) % s + e;
    return n === e ? i : n
}

function q(t, ...e) {
    for (const i of e)
        for (const e in i) t[e] = i[e];
    return t
}

function $(t, e) {
    const i = {};
    for (let s = 0; s < e.length; s++) {
        const n = e[s];
        n in t && (i[n] = t[n])
    }
    return i
}
let W = 1;

function H() {
    return W++
}

function V(t, e, i) {
    const s = {};
    for (const i in t) s[i] = e.call(this, t[i], i, t);
    return s
}

function X(t, e, i) {
    const s = {};
    for (const i in t) e.call(this, t[i], i, t) && (s[i] = t[i]);
    return s
}

function K(t, e) {
    if (Array.isArray(t)) {
        if (!Array.isArray(e) || t.length !== e.length) return 0;
        for (let i = 0; i < t.length; i++)
            if (!K(t[i], e[i])) return 0;
        return 1
    }
    if ("object" == typeof t && null !== t && null !== e) {
        if ("object" != typeof e) return 0;
        if (Object.keys(t).length !== Object.keys(e).length) return 0;
        for (const i in t)
            if (!K(t[i], e[i])) return 0;
        return 1
    }
    return t === e
}

function Y(t) {
    return Array.isArray(t) ? t.map(Y) : "object" == typeof t && t ? V(t, Y) : t
}
const J = {};

function Q(t) {
    J[t] || (void 0 !== console && console.warn(t), J[t] = 1)
}

function tt(t) {
    return "undefined" != typeof ImageBitmap && t instanceof ImageBitmap
}
const et = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQYV2NgAAIAAAUAAarVyFEAAAAASUVORK5CYII=";

function it(t) {
    return t * Math.PI / 180
}

function st(t) {
    return t / Math.PI * 180
}

function nt(t, e, i) {
    const s = new Float64Array(4);
    return function(t, e, i, s) {
        var n = arguments.length > 4 && void 0 !== arguments[4] ? arguments[4] : "zyx",
            r = Math.PI / 360;
        s *= r, i *= r;
        var o = Math.sin(e *= r),
            a = Math.cos(e),
            h = Math.sin(i),
            l = Math.cos(i),
            c = Math.sin(s),
            u = Math.cos(s);
        switch (n) {
            case "xyz":
                t[0] = o * l * u + a * h * c, t[1] = a * h * u - o * l * c, t[2] = a * l * c + o * h * u, t[3] = a * l * u - o * h * c;
                break;
            case "xzy":
                t[0] = o * l * u - a * h * c, t[1] = a * h * u - o * l * c, t[2] = a * l * c + o * h * u, t[3] = a * l * u + o * h * c;
                break;
            case "yxz":
                t[0] = o * l * u + a * h * c, t[1] = a * h * u - o * l * c, t[2] = a * l * c - o * h * u, t[3] = a * l * u + o * h * c;
                break;
            case "yzx":
                t[0] = o * l * u + a * h * c, t[1] = a * h * u + o * l * c, t[2] = a * l * c - o * h * u, t[3] = a * l * u - o * h * c;
                break;
            case "zxy":
                t[0] = o * l * u - a * h * c, t[1] = a * h * u + o * l * c, t[2] = a * l * c + o * h * u, t[3] = a * l * u - o * h * c;
                break;
            case "zyx":
                t[0] = o * l * u - a * h * c, t[1] = a * h * u + o * l * c, t[2] = a * l * c - o * h * u, t[3] = a * l * u + o * h * c;
                break;
            default:
                throw Error("Unknown angle order " + n)
        }
    }(s, t, e - 90, i), s
}

function rt() {
    return Error("AbortError")
}
let ot, at;
const ht = {
    now: "undefined" != typeof performance && performance && performance.now ? performance.now.bind(performance) : Date.now.bind(Date),
    frameAsync: t => new Promise((e, i) => {
        const s = requestAnimationFrame(e);
        t.signal.addEventListener("abort", () => {
            cancelAnimationFrame(s), i(rt())
        })
    }),
    getImageData(t, e = 0) {
        return this.getImageCanvasContext(t).getImageData(-e, -e, t.width + 2 * e, t.height + 2 * e)
    },
    getImageCanvasContext(t) {
        const e = window.document.createElement("canvas"),
            i = e.getContext("2d", {
                willReadFrequently: B
            });
        if (!i) throw Error("failed to create canvas 2d context");
        return e.width = t.width, e.height = t.height, i.drawImage(t, 0, 0, t.width, t.height), i
    },
    resolveURL: t => (ot || (ot = document.createElement("a")), ot.href = t, ot.href),
    hardwareConcurrency: "undefined" != typeof navigator && navigator.hardwareConcurrency || 4,
    get prefersReducedMotion() {
        return matchMedia ? (null == at && (at = matchMedia("(prefers-reduced-motion: reduce)")), at.matches) : 0
    }
};
class lt {
    static testProp(t) {
        if (!lt.docStyle) return t[0];
        for (let e = 0; e < t.length; e++)
            if (t[e] in lt.docStyle) return t[e];
        return t[0]
    }
    static create(t, e, i) {
        const s = window.document.createElement(t);
        return void 0 !== e && (s.className = e), i && i.appendChild(s), s
    }
    static createNS(t, e) {
        return window.document.createElementNS(t, e)
    }
    static disableDrag() {
        lt.docStyle && lt.selectProp && (lt.userSelect = lt.docStyle[lt.selectProp], lt.docStyle[lt.selectProp] = "none")
    }
    static enableDrag() {
        lt.docStyle && lt.selectProp && (lt.docStyle[lt.selectProp] = lt.userSelect)
    }
    static setTransform(t, e) {
        t.style[lt.transformProp] = e
    }
    static addEventListener(t, e, i, s = {}) {
        t.addEventListener(e, i, "passive" in s ? s : s.capture)
    }
    static removeEventListener(t, e, i, s = {}) {
        t.removeEventListener(e, i, "passive" in s ? s : s.capture)
    }
    static suppressClickInternal(t) {
        t.preventDefault(), t.stopPropagation(), window.removeEventListener("click", lt.suppressClickInternal, 1)
    }
    static suppressClick() {
        window.addEventListener("click", lt.suppressClickInternal, 1), window.setTimeout(() => {
            window.removeEventListener("click", lt.suppressClickInternal, 1)
        }, 0)
    }
    static getScale(t) {
        const e = t.getBoundingClientRect();
        return {
            x: e.width / t.offsetWidth || 1,
            y: e.height / t.offsetHeight || 1,
            boundingClientRect: e
        }
    }
    static getPoint(t, e, i) {
        const s = e.boundingClientRect;
        return new h((i.clientX - s.left) / e.x - t.clientLeft, (i.clientY - s.top) / e.y - t.clientTop)
    }
    static mousePos(t, e) {
        const i = lt.getScale(t);
        return lt.getPoint(t, i, e)
    }
    static touchPos(t, e) {
        const i = [],
            s = lt.getScale(t);
        for (let n = 0; n < e.length; n++) i.push(lt.getPoint(t, s, e[n]));
        return i
    }
    static mouseButton(t) {
        return t.button
    }
    static remove(t) {
        t.parentNode && t.parentNode.removeChild(t)
    }
}
lt.docStyle = "undefined" != typeof window && window.document && window.document.documentElement.style, lt.selectProp = lt.testProp(["userSelect", "MozUserSelect", "WebkitUserSelect", "msUserSelect"]), lt.transformProp = lt.testProp(["transform", "WebkitTransform"]);
var ct = "5.0.0-beta.7";
const ut = {
    MAX_PARALLEL_IMAGE_REQUESTS: 16,
    MAX_PARALLEL_IMAGE_REQUESTS_PER_FRAME: 8,
    MAX_TILE_CACHE_ZOOM_LEVELS: 5,
    REGISTERED_PROTOCOLS: {},
    WORKER_URL: ""
};

function dt(t) {
    return ut.REGISTERED_PROTOCOLS[t.substring(0, t.indexOf("://"))]
}

function pt(t, e) {
    ut.REGISTERED_PROTOCOLS[t] = e
}

function _t(t) {
    delete ut.REGISTERED_PROTOCOLS[t]
}
class mt extends Error {
    constructor(t, e, i, s) {
        super(`AJAXError: ${e} (${t}): ${i}`), this.status = t, this.statusText = e, this.url = i, this.body = s
    }
}
const ft = () => ("blob:" === window.location.protocol ? window.parent : window).location.href,
    gt = function(t, e) {
        if (/:\/\//.test(t.url) && !/^https?:|^file:/.test(t.url)) {
            const i = dt(t.url);
            if (i) return i(t, e)
        }
        return !(/^file:/.test(i = t.url) || /^file:/.test(ft()) && !/^\w+:/.test(i)) && fetch && Request && AbortController && Object.prototype.hasOwnProperty.call(Request.prototype, "signal") ? async function(t, e) {
            const i = new Request(t.url, {
                method: t.method || "GET",
                body: t.body,
                credentials: t.credentials,
                headers: t.headers,
                cache: t.cache,
                referrer: ft(),
                signal: e.signal
            });
            "json" !== t.type || i.headers.has("Accept") || i.headers.set("Accept", "application/json");
            const s = await fetch(i);
            if (!s.ok) {
                const e = await s.blob();
                throw new mt(s.status, s.statusText, t.url, e)
            }
            let n;
            n = "arrayBuffer" === t.type || "image" === t.type ? s.arrayBuffer() : "json" === t.type ? s.json() : s.text();
            const r = await n;
            if (e.signal.aborted) throw rt();
            return {
                data: r,
                cacheControl: s.headers.get("Cache-Control"),
                expires: s.headers.get("Expires")
            }
        }(t, e): function(t, e) {
            return new Promise((i, s) => {
                var n;
                const r = new XMLHttpRequest;
                r.open(t.method || "GET", t.url, 1), "arrayBuffer" !== t.type && "image" !== t.type || (r.responseType = "arraybuffer");
                for (const e in t.headers) r.setRequestHeader(e, t.headers[e]);
                "json" === t.type && (r.responseType = "text", (null === (n = t.headers) || void 0 === n ? void 0 : n.Accept) || r.setRequestHeader("Accept", "application/json")), r.withCredentials = "include" === t.credentials, r.onerror = () => {
                    s(Error(r.statusText))
                }, r.onload = () => {
                    if (!e.signal.aborted)
                        if ((r.status >= 200 && r.status < 300 || 0 === r.status) && null !== r.response) {
                            let e = r.response;
                            if ("json" === t.type) try {
                                e = JSON.parse(r.response)
                            } catch (t) {
                                return void s(t)
                            }
                            i({
                                data: e,
                                cacheControl: r.getResponseHeader("Cache-Control"),
                                expires: r.getResponseHeader("Expires")
                            })
                        } else {
                            const e = new Blob([r.response], {
                                type: r.getResponseHeader("Content-Type")
                            });
                            s(new mt(r.status, r.statusText, t.url, e))
                        }
                }, e.signal.addEventListener("abort", () => {
                    r.abort(), s(rt())
                }), r.send(t.body)
            })
        }(t, e);
        var i
    },
    yt = (t, e) => gt(q(t, {
        type: "json"
    }), e),
    vt = {
        supported: 0,
        testSupport: function(t) {
            !wt && xt && (Tt ? Mt(t) : bt = t)
        }
    };
let bt, xt, wt = 0,
    Tt = 0;

function Mt(t) {
    const e = t.createTexture();
    t.bindTexture(t.TEXTURE_2D, e);
    try {
        if (t.texImage2D(t.TEXTURE_2D, 0, t.RGBA, t.RGBA, t.UNSIGNED_BYTE, xt), t.isContextLost()) return;
        vt.supported = 1
    } catch (t) {}
    t.deleteTexture(e), wt = 1
}
var Pt;
"undefined" != typeof document && (xt = document.createElement("img"), xt.onload = () => {
        bt && Mt(bt), bt = null, Tt = 1
    }, xt.onerror = () => {
        wt = 1, bt = null
    }, xt.src = "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAQAAAAfQ//73v/+BiOh/AAA="),
    function(t) {
        let e, i, s, n;
        t.resetRequestQueue = () => {
            e = [], i = 0, s = 0, n = {}
        }, t.addThrottleControl = t => {
            const e = s++;
            return n[e] = t, e
        }, t.removeThrottleControl = t => {
            delete n[t], o()
        }, t.getImage = (t, i, s = 1) => new Promise((n, r) => {
            vt.supported && (t.headers || (t.headers = {}), t.headers.accept = "image/webp,*/*"), q(t, {
                type: "image"
            }), e.push({
                abortController: i,
                requestParameters: t,
                supportImageRefresh: s,
                state: "queued",
                onError: t => {
                    r(t)
                },
                onSuccess: t => {
                    n(t)
                }
            }), o()
        });
        const r = async t => {
            t.state = "running";
            const {
                requestParameters: e,
                supportImageRefresh: s,
                onError: n,
                onSuccess: r,
                abortController: h
            } = t, l = 0 == s && ! function(t) {
                return "undefined" != typeof WorkerGlobalScope && void 0 !== t && t instanceof WorkerGlobalScope
            }(self) && !dt(e.url) && (!e.headers || Object.keys(e.headers).reduce((t, e) => t && "accept" === e, 1));
            i++;
            const c = l ? a(e, h) : gt(e, h);
            try {
                const e = await c;
                delete t.abortController, t.state = "completed", e.data instanceof HTMLImageElement || tt(e.data) ? r(e) : e.data && r({
                    data: await (u = e.data, "function" == typeof createImageBitmap ? (async t => {
                        if (0 === t.byteLength) return createImageBitmap(new ImageData(1, 1));
                        const e = new Blob([new Uint8Array(t)], {
                            type: "image/png"
                        });
                        try {
                            return createImageBitmap(e)
                        } catch (t) {
                            throw Error(`Could not load image because of ${t.message}. Please make sure to use a supported image type such as PNG or JPEG. Note that SVGs are not supported.`)
                        }
                    })(u) : (t => new Promise((e, i) => {
                        const s = new Image;
                        s.onload = () => {
                            e(s), URL.revokeObjectURL(s.src), s.onload = null, window.requestAnimationFrame(() => {
                                s.src = et
                            })
                        }, s.onerror = () => i(Error("Could not load image. Please make sure to use a supported image type such as PNG or JPEG. Note that SVGs are not supported."));
                        const n = new Blob([new Uint8Array(t)], {
                            type: "image/png"
                        });
                        s.src = t.byteLength ? URL.createObjectURL(n) : et
                    }))(u)),
                    cacheControl: e.cacheControl,
                    expires: e.expires
                })
            } catch (e) {
                delete t.abortController, n(e)
            } finally {
                i--, o()
            }
            var u
        }, o = () => {
            const t = (() => {
                for (const t of Object.keys(n))
                    if (n[t]()) return 1;
                return 0
            })() ? ut.MAX_PARALLEL_IMAGE_REQUESTS_PER_FRAME : ut.MAX_PARALLEL_IMAGE_REQUESTS;
            for (let s = i; s < t && e.length > 0; s++) {
                const t = e.shift();
                t.abortController.signal.aborted ? s-- : r(t)
            }
        }, a = (t, e) => new Promise((i, s) => {
            const n = new Image,
                r = t.url,
                o = t.credentials;
            o && "include" === o ? n.crossOrigin = "use-credentials" : (o && "same-origin" === o || ! function(t) {
                if (!t || t.indexOf("://") <= 0 || 0 === t.indexOf("data:image/") || 0 === t.indexOf("blob:")) return 1;
                const e = new URL(t),
                    i = window.location;
                return e.protocol === i.protocol && e.host === i.host
            }(r)) && (n.crossOrigin = "anonymous"), e.signal.addEventListener("abort", () => {
                n.src = "", s(rt())
            }), n.fetchPriority = "high", n.onload = () => {
                n.onerror = n.onload = null, i({
                    data: n
                })
            }, n.onerror = () => {
                n.onerror = n.onload = null, e.signal.aborted || s(Error("Could not load image. Please make sure to use a supported image type such as PNG or JPEG. Note that SVGs are not supported."))
            }, n.src = r
        })
    }(Pt || (Pt = {})), Pt.resetRequestQueue();
class Et {
    constructor(t) {
        this._transformRequestFn = t
    }
    transformRequest(t, e) {
        return this._transformRequestFn && this._transformRequestFn(t, e) || {
            url: t
        }
    }
    setTransformRequest(t) {
        this._transformRequestFn = t
    }
}

function Lt(t, e, i) {
    i[t] && -1 !== i[t].indexOf(e) || (i[t] = i[t] || [], i[t].push(e))
}

function Ct(t, e, i) {
    if (i && i[t]) {
        const s = i[t].indexOf(e); - 1 !== s && i[t].splice(s, 1)
    }
}
class St {
    constructor(t, e = {}) {
        q(this, e), this.type = t
    }
}
class Rt extends St {
    constructor(t, e = {}) {
        super("error", q({
            error: t
        }, e))
    }
}
class It {
    on(t, e) {
        return this._listeners = this._listeners || {}, Lt(t, e, this._listeners), this
    }
    off(t, e) {
        return Ct(t, e, this._listeners), Ct(t, e, this._oneTimeListeners), this
    }
    once(t, e) {
        return e ? (this._oneTimeListeners = this._oneTimeListeners || {}, Lt(t, e, this._oneTimeListeners), this) : new Promise(e => this.once(t, e))
    }
    fire(t, e) {
        "string" == typeof t && (t = new St(t, e || {}));
        const i = t.type;
        if (this.listens(i)) {
            t.target = this;
            const e = this._listeners && this._listeners[i] ? this._listeners[i].slice() : [];
            for (const i of e) i.call(this, t);
            const s = this._oneTimeListeners && this._oneTimeListeners[i] ? this._oneTimeListeners[i].slice() : [];
            for (const e of s) Ct(i, e, this._oneTimeListeners), e.call(this, t);
            const n = this._eventedParent;
            n && (q(t, "function" == typeof this._eventedParentData ? this._eventedParentData() : this._eventedParentData), n.fire(t))
        } else t instanceof Rt && console.error(t.error);
        return this
    }
    listens(t) {
        return this._listeners && this._listeners[t] && this._listeners[t].length > 0 || this._oneTimeListeners && this._oneTimeListeners[t] && this._oneTimeListeners[t].length > 0 || this._eventedParent && this._eventedParent.listens(t)
    }
    setEventedParent(t, e) {
        return this._eventedParent = t, this._eventedParentData = e, this
    }
}
class At extends It {
    constructor(t) {
        super(), this.id = t.id, this.type = t.type, "custom" !== t.type && "canvas" !== t.type && (this.metadata = t.metadata, this.minzoom = t.minzoom, this.maxzoom = t.maxzoom, "background" !== t.type && (this.source = t.source, this.sourceLayer = t["source-layer"]))
    }
    isHidden(t) {
        return this.minzoom && t < this.minzoom || this.maxzoom && t >= this.maxzoom ? 1 : "none" === this.visibility
    }
    recalculate(t) {
        t.getCrossfadeParameters && (this._crossfadeParameters = t.getCrossfadeParameters())
    }
    serialize() {
        const t = {
            id: this.id,
            type: this.type,
            source: this.source,
            "source-layer": this.sourceLayer,
            metadata: this.metadata,
            minzoom: this.minzoom,
            maxzoom: this.maxzoom
        };
        return this.visibility && (t.layout = t.layout || {}, t.layout.visibility = this.visibility), X(t, (t, e) => !(void 0 === t || "layout" === e && !Object.keys(t).length || "paint" === e && !Object.keys(t).length))
    }
    is3D() {
        return 0
    }
    isTileClipped() {
        return 0
    }
    hasOffscreenPass() {
        return 0
    }
    resize() {}
}
class zt extends At {}
class Ot extends At {
    constructor(t) {
        super(t), t.paint && (this.paint = t.paint)
    }
}
class kt extends At {
    constructor(t) {
        super(t), this.onAdd = t => {
            this.implementation.onAdd && this.implementation.onAdd(t, t.painter.context.gl)
        }, this.onRemove = t => {
            this.implementation.onRemove && this.implementation.onRemove(t, t.painter.context.gl)
        }, this.implementation = t
    }
    is3D() {
        return "3d" === this.implementation.renderingMode
    }
    hasOffscreenPass() {
        return void 0 !== this.implementation.prerender
    }
    recalculate() {}
    updateTransitions() {}
    hasTransition() {
        return 0
    }
    serialize() {
        throw Error("Custom layers cannot be serialized")
    }
}

function Dt(t) {
    if ("custom" === t.type) return new kt(t);
    switch (t.type) {
        case "background":
            return new zt(t);
        case "raster":
            return new Ot(t)
    }
}
class Bt {
    constructor(t, e) {
        if (isNaN(t) || isNaN(e)) throw Error(`Invalid LngLat object: (${t}, ${e})`);
        if (this.lng = +t, this.lat = +e, this.lat > 90 || this.lat < -90) throw Error("Invalid LngLat latitude value: must be between -90 and 90")
    }
    wrap() {
        return new Bt(G(this.lng, -180, 180), this.lat)
    }
    toArray() {
        return [this.lng, this.lat]
    }
    toString() {
        return `LngLat(${this.lng}, ${this.lat})`
    }
    distanceTo(t) {
        const e = Math.PI / 180,
            i = this.lat * e,
            s = t.lat * e;
        return 6371008.8 * Math.acos(Math.min(Math.sin(i) * Math.sin(s) + Math.cos(i) * Math.cos(s) * Math.cos((t.lng - this.lng) * e), 1))
    }
    static convert(t) {
        if (t instanceof Bt) return t;
        if (Array.isArray(t) && (2 === t.length || 3 === t.length)) return new Bt(Number(t[0]), Number(t[1]));
        if (!Array.isArray(t) && "object" == typeof t && null !== t) return new Bt(Number("lng" in t ? t.lng : t.lon), Number(t.lat));
        throw Error("`LngLatLike` argument must be specified as a LngLat instance, an object {lng: <lng>, lat: <lat>}, an object {lon: <lng>, lat: <lat>}, or an array of [<lng>, <lat>]")
    }
}
class Ft {
    constructor(t, e) {
        t && (e ? this.setSouthWest(t).setNorthEast(e) : Array.isArray(t) && (4 === t.length ? this.setSouthWest([t[0], t[1]]).setNorthEast([t[2], t[3]]) : this.setSouthWest(t[0]).setNorthEast(t[1])))
    }
    setNorthEast(t) {
        return this._ne = t instanceof Bt ? new Bt(t.lng, t.lat) : Bt.convert(t), this
    }
    setSouthWest(t) {
        return this._sw = t instanceof Bt ? new Bt(t.lng, t.lat) : Bt.convert(t), this
    }
    extend(t) {
        const e = this._sw,
            i = this._ne;
        let s, n;
        if (t instanceof Bt) s = t, n = t;
        else {
            if (!(t instanceof Ft)) return Array.isArray(t) ? 4 === t.length || t.every(Array.isArray) ? this.extend(Ft.convert(t)) : this.extend(Bt.convert(t)) : t && ("lng" in t || "lon" in t) && "lat" in t ? this.extend(Bt.convert(t)) : this;
            if (s = t._sw, n = t._ne, !s || !n) return this
        }
        return e || i ? (e.lng = Math.min(s.lng, e.lng), e.lat = Math.min(s.lat, e.lat), i.lng = Math.max(n.lng, i.lng), i.lat = Math.max(n.lat, i.lat)) : (this._sw = new Bt(s.lng, s.lat), this._ne = new Bt(n.lng, n.lat)), this
    }
    getCenter() {
        return new Bt((this._sw.lng + this._ne.lng) / 2, (this._sw.lat + this._ne.lat) / 2)
    }
    getSouthWest() {
        return this._sw
    }
    getNorthEast() {
        return this._ne
    }
    getNorthWest() {
        return new Bt(this.getWest(), this.getNorth())
    }
    getSouthEast() {
        return new Bt(this.getEast(), this.getSouth())
    }
    getWest() {
        return this._sw.lng
    }
    getSouth() {
        return this._sw.lat
    }
    getEast() {
        return this._ne.lng
    }
    getNorth() {
        return this._ne.lat
    }
    toArray() {
        return [this._sw.toArray(), this._ne.toArray()]
    }
    toString() {
        return `LngLatBounds(${"" + this._sw}, ${"" + this._ne})`
    }
    isEmpty() {
        return !(this._sw && this._ne)
    }
    contains(t) {
        const {
            lng: e,
            lat: i
        } = Bt.convert(t);
        let s = this._sw.lng <= e && e <= this._ne.lng;
        return this._sw.lng > this._ne.lng && (s = this._sw.lng >= e && e >= this._ne.lng), this._sw.lat <= i && i <= this._ne.lat && s
    }
    static convert(t) {
        return t instanceof Ft ? t : t ? new Ft(t) : t
    }
    static fromLngLat(t, e = 0) {
        const i = 360 * e / 40075017,
            s = i / Math.cos(Math.PI / 180 * t.lat);
        return new Ft(new Bt(t.lng - s, t.lat - i), new Bt(t.lng + s, t.lat + i))
    }
    adjustAntiMeridian() {
        const t = new Bt(this._sw.lng, this._sw.lat),
            e = new Bt(this._ne.lng, this._ne.lat);
        return new Ft(t, t.lng > e.lng ? new Bt(e.lng + 360, e.lat) : e)
    }
}
const Zt = 40030228.88407185;

function Nt(t) {
    return Zt * Math.cos(t * Math.PI / 180)
}

function jt(t) {
    return (180 + t) / 360
}

function Ut(t) {
    return (180 - 180 / Math.PI * Math.log(Math.tan(Math.PI / 4 + t * Math.PI / 360))) / 360
}

function Gt(t, e) {
    return t / Nt(e)
}

function qt(t) {
    return 360 / Math.PI * Math.atan(Math.exp((180 - 360 * t) * Math.PI / 180)) - 90
}
class $t {
    constructor(t, e, i = 0) {
        this.x = +t, this.y = +e, this.z = +i
    }
    static fromLngLat(t, e = 0) {
        const i = Bt.convert(t);
        return new $t(jt(i.lng), Ut(i.lat), Gt(e, i.lat))
    }
    toLngLat() {
        return new Bt(360 * this.x - 180, qt(this.y))
    }
    toAltitude() {
        return this.z * Nt(qt(this.y))
    }
    meterInMercatorCoordinateUnits() {
        return 1 / Zt * (t = qt(this.y), 1 / Math.cos(t * Math.PI / 180));
        var t
    }
}

function Wt(t) {
    return t - Math.floor(t)
}
class Ht {
    constructor(t, e, i) {
        this.bounds = Ft.convert(this.validateBounds(t)), this.minzoom = e || 0, this.maxzoom = i || 24
    }
    validateBounds(t) {
        return Array.isArray(t) && 4 === t.length ? [t[0], Math.max(-90, t[1]), t[2], Math.min(90, t[3])] : [-180, -90, 180, 90]
    }
    contains(t) {
        const e = Math.pow(2, t.z),
            i = Math.floor(Ut(this.bounds.getNorth()) * e),
            s = Math.ceil(Ut(this.bounds.getSouth()) * e);
        if (t.y < i || t.y >= s) return 0;
        let n = Wt(jt(this.bounds.getWest())),
            r = Wt(jt(this.bounds.getEast()));
        n >= r && (r += 1), n = Math.floor(n * e), r = Math.ceil(r * e);
        const o = (t.x % (a = e) + a) % a;
        var a;
        return o >= n && o < r || o + e >= n && o + e < r
    }
}
class Vt {
    constructor(t, e, i, s) {
        this.context = t, this.format = i, this.texture = t.gl.createTexture(), this.update(e, s ? q(s, {
            format: i
        }) : {
            format: i
        })
    }
    update(t, e, i) {
        var s;
        const {
            width: n,
            height: r
        } = t, o = !(this.size && this.size[0] === n && this.size[1] === r || i), {
            context: a
        } = this, {
            gl: h
        } = a;
        this.useMipmap = !(!e || !e.useMipmap);
        const l = null !== (s = null == e ? void 0 : e.format) && void 0 !== s ? s : h.RGBA,
            c = this.format !== l;
        this.format = l, h.bindTexture(h.TEXTURE_2D, this.texture), a.pixelStoreUnpackFlipY.set(0), a.pixelStoreUnpack.set(1), a.pixelStoreUnpackPremultiplyAlpha.set(this.format === h.RGBA && (!e || 0 != e.premultiply));
        try {
            const e = this.textureFormatFromInternalFormat(this.format);
            if (o || c) this.size = [n, r], t instanceof HTMLImageElement || t instanceof HTMLCanvasElement || t instanceof HTMLVideoElement || t instanceof ImageData || tt(t) ? h.texImage2D(h.TEXTURE_2D, 0, this.format, e, h.UNSIGNED_BYTE, t) : h.texImage2D(h.TEXTURE_2D, 0, this.format, n, r, 0, e, h.UNSIGNED_BYTE, t.data);
            else {
                const {
                    x: s,
                    y: o
                } = i || {
                    x: 0,
                    y: 0
                };
                t instanceof HTMLImageElement || t instanceof HTMLCanvasElement || t instanceof HTMLVideoElement || t instanceof ImageData || tt(t) ? h.texSubImage2D(h.TEXTURE_2D, 0, s, o, e, h.UNSIGNED_BYTE, t) : h.texSubImage2D(h.TEXTURE_2D, 0, s, o, n, r, e, h.UNSIGNED_BYTE, t.data)
            }
            this.useMipmap && this.isSizePowerOfTwo() && h.generateMipmap(h.TEXTURE_2D)
        } finally {
            a.pixelStoreUnpackFlipY.setDefault(), a.pixelStoreUnpack.setDefault(), a.pixelStoreUnpackPremultiplyAlpha.setDefault()
        }
    }
    bind(t, e, i) {
        const {
            context: s
        } = this, {
            gl: n
        } = s;
        n.bindTexture(n.TEXTURE_2D, this.texture), i !== n.LINEAR_MIPMAP_NEAREST || this.isSizePowerOfTwo() || (i = n.LINEAR), t !== this.filter && (n.texParameteri(n.TEXTURE_2D, n.TEXTURE_MAG_FILTER, t), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_MIN_FILTER, i || t), this.filter = t), e !== this.wrap && (n.texParameteri(n.TEXTURE_2D, n.TEXTURE_WRAP_S, e), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_WRAP_T, e), this.wrap = e)
    }
    restoreSettings() {
        const {
            context: t
        } = this, {
            gl: e
        } = t;
        let i = this.filter;
        i !== e.LINEAR_MIPMAP_NEAREST || this.isSizePowerOfTwo() || (i = e.LINEAR), e.bindTexture(e.TEXTURE_2D, this.texture), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MAG_FILTER, this.filter), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MIN_FILTER, i), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_S, this.wrap), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_T, this.wrap), e.bindTexture(e.TEXTURE_2D, null)
    }
    isSizePowerOfTwo() {
        return this.size[0] === this.size[1] && Math.log(this.size[0]) / Math.LN2 % 1 == 0
    }
    destroy() {
        const {
            gl: t
        } = this.context;
        t.deleteTexture(this.texture), this.texture = null
    }
    textureFormatFromInternalFormat(t) {
        let e = t;
        if (!this.context.isWebGL2) return e;
        switch (t) {
            case WebGL2RenderingContext.RG8:
                e = WebGL2RenderingContext.RG;
                break;
            case WebGL2RenderingContext.R8:
                e = WebGL2RenderingContext.RED
        }
        return e
    }
}
class Xt extends It {
    constructor(t, e, i) {
        super(), this.id = t, this.setEventedParent(i), this.type = "raster", this.minzoom = 0, this.maxzoom = 22, this.roundZoom = 1, this.scheme = "xyz", this.tileSize = 512, this._loaded = 0, this._textureFormat = WebGLRenderingContext.RGBA, this._options = q({
            type: "raster"
        }, e), q(this, $(e, ["url", "scheme", "tileSize"]))
    }
    set textureFormat(t) {
        this._textureFormat = t
    }
    get textureFormat() {
        return this._textureFormat
    }
    async load() {
        this._loaded = 0, this.fire(new St("dataloading", {
            dataType: "source"
        })), this._tileJSONRequest = new AbortController;
        try {
            const t = await async function(t, e, i) {
                let s = t;
                if (t.url && (s = (await yt(e.transformRequest(t.url, "Source"), i)).data), !s) return null;
                const n = $(q(s, t), ["tiles", "minzoom", "maxzoom", "attribution", "bounds", "scheme", "tileSize"]);
                return "vector_layers" in s && s.vector_layers && (n.vectorLayerIds = s.vector_layers.map(t => t.id)), n
            }(this._options, this.map._requestManager, this._tileJSONRequest);
            this._tileJSONRequest = null, this._loaded = 1, t && (q(this, t), t.bounds && (this.tileBounds = new Ht(t.bounds, this.minzoom, this.maxzoom)), this.fire(new St("data", {
                dataType: "source",
                sourceDataType: "metadata"
            })), this.fire(new St("data", {
                dataType: "source",
                sourceDataType: "content"
            })))
        } catch (t) {
            this._tileJSONRequest = null, this.fire(new Rt(t))
        }
    }
    loaded() {
        return this._loaded
    }
    onAdd(t) {
        this.map = t, this.load()
    }
    onRemove() {
        this._tileJSONRequest && (this._tileJSONRequest.abort(), this._tileJSONRequest = null)
    }
    setSourceProperty(t) {
        this._tileJSONRequest && (this._tileJSONRequest.abort(), this._tileJSONRequest = null), t(), this.load()
    }
    setTiles(t) {
        return this.setSourceProperty(() => {
            this._options.tiles = t
        }), this
    }
    setUrl(t) {
        return this.setSourceProperty(() => {
            this.url = t, this._options.url = t
        }), this
    }
    serialize() {
        return q({}, this._options)
    }
    hasTile(t) {
        return !this.tileBounds || this.tileBounds.contains(t.canonical)
    }
    async loadTile(t) {
        const e = t.tileID.canonical.url(this.tiles, this._options.forceDisableDevicePixelRatioScaling ? this.map.getPixelRatio() : 1, this.scheme);
        t.abortController = new AbortController;
        try {
            const i = await Pt.getImage(this.map._requestManager.transformRequest(e, "Tile"), t.abortController, this.map._refreshExpiredTiles);
            if (delete t.abortController, t.aborted) {
                const e = t.state;
                return t.state = "unloaded", void this.fire(new St("tilestate", {
                    oldState: e,
                    newState: t.state,
                    tile: t,
                    sourceId: this.id
                }))
            }
            if (i && i.data) {
                if (this.map._refreshExpiredTiles && i.cacheControl && i.expires) {
                    const e = t.state;
                    t.setExpiryData({
                        cacheControl: i.cacheControl,
                        expires: i.expires
                    }), e !== t.state && this.fire(new St("tilestate", {
                        oldState: e,
                        newState: t.state,
                        tile: t,
                        sourceId: this.id
                    }))
                }
                const e = this.map.painter.context,
                    s = e.gl,
                    n = i.data;
                t.texture = this.map.painter.getTileTexture(n.width), t.texture ? t.texture.update(n, {
                    useMipmap: 1,
                    format: this.textureFormat
                }) : (t.texture = new Vt(e, n, this.textureFormat, {
                    useMipmap: 1
                }), t.texture.bind(s.LINEAR, s.CLAMP_TO_EDGE, s.LINEAR_MIPMAP_NEAREST));
                const r = t.state;
                t.state = "loaded", this.fire(new St("tilestate", {
                    oldState: r,
                    newState: t.state,
                    tile: t,
                    sourceId: this.id
                }))
            }
        } catch (e) {
            delete t.abortController;
            const i = t.state;
            if (t.aborted) t.state = "unloaded", this.fire(new St("tilestate", {
                oldState: i,
                newState: t.state,
                tile: t,
                sourceId: this.id
            }));
            else if (e) throw t.state = "errored", this.fire(new St("tilestate", {
                oldState: i,
                newState: t.state,
                tile: t,
                sourceId: this.id
            })), e
        }
    }
    async abortTile(t) {
        t.abortController && (t.abortController.abort(), delete t.abortController)
    }
    async unloadTile(t) {
        t.texture && this.map.painter.saveTileTexture(t.texture)
    }
    hasTransition() {
        return 0
    }
}
const Kt = {},
    Yt = t => "raster" === t ? Xt : Kt[t],
    Jt = async (t, e) => {
        if (Yt(t)) throw Error(`A source type called "${t}" already exists.`);
        ((t, e) => {
            Kt[t] = e
        })(t, e)
    };
class Qt {
    constructor(t, e) {
        this.timeAdded = 0, this.fadeEndTime = 0, this.tileID = t, this.uid = H(), this.uses = 0, this.tileSize = e, this.expirationTime = null, this.queryPadding = 0, this.dependencies = {}, this.expiredRequestCount = 0, this.state = "loading"
    }
    registerFadeDuration(t) {
        const e = t + this.timeAdded;
        e < this.fadeEndTime || (this.fadeEndTime = e)
    }
    wasRequested() {
        return "errored" === this.state || "loaded" === this.state || "reloading" === this.state
    }
    hasData() {
        return "loaded" === this.state || "reloading" === this.state || "expired" === this.state
    }
    setExpiryData(t) {
        const e = this.expirationTime;
        if (t.cacheControl) {
            const e = function(t) {
                const e = {};
                if (t.replace(/(?:^|(?:\s*\,\s*))([^\x00-\x20\(\)<>@\,;\:\\"\/\[\]\?\=\{\}\x7F]+)(?:\=(?:([^\x00-\x20\(\)<>@\,;\:\\"\/\[\]\?\=\{\}\x7F]+)|(?:\"((?:[^"\\]|\\.)*)\")))?/g, (t, i, s, n) => {
                        const r = s || n;
                        return e[i] = r ? r.toLowerCase() : 1, ""
                    }), e["max-age"]) {
                    const t = parseInt(e["max-age"], 10);
                    isNaN(t) ? delete e["max-age"] : e["max-age"] = t
                }
                return e
            }(t.cacheControl);
            e["max-age"] && (this.expirationTime = Date.now() + 1e3 * e["max-age"])
        } else t.expires && (this.expirationTime = new Date(t.expires).getTime());
        if (this.expirationTime) {
            const t = Date.now();
            let i = 0;
            if (this.expirationTime > t) i = 0;
            else if (e)
                if (this.expirationTime < e) i = 1;
                else {
                    const s = this.expirationTime - e;
                    s ? this.expirationTime = t + Math.max(s, 3e4) : i = 1
                }
            else i = 1;
            i ? (this.expiredRequestCount++, this.state = "expired") : this.expiredRequestCount = 0
        }
    }
    getExpiryTimeout() {
        if (this.expirationTime) return this.expiredRequestCount ? 1e3 * (1 << Math.min(this.expiredRequestCount - 1, 31)) : Math.min(this.expirationTime - (new Date).getTime(), 2147483647)
    }
    setDependencies(t, e) {
        const i = {};
        for (const t of e) i[t] = 1;
        this.dependencies[t] = i
    }
    hasDependency(t, e) {
        for (const i of t) {
            const t = this.dependencies[i];
            if (t)
                for (const i of e)
                    if (t[i]) return 1
        }
        return 0
    }
}
class te {
    constructor(t, e) {
        this.max = t, this.onRemove = e, this.reset()
    }
    reset() {
        for (const t in this.data)
            for (const e of this.data[t]) e.timeout && clearTimeout(e.timeout), this.onRemove(e.value);
        return this.data = {}, this.order = [], this
    }
    add(t, e, i) {
        const s = t.wrapped().key;
        void 0 === this.data[s] && (this.data[s] = []);
        const n = {
            value: e,
            timeout: void 0
        };
        if (void 0 !== i && (n.timeout = setTimeout(() => {
                this.remove(t, n)
            }, i)), this.data[s].push(n), this.order.push(s), this.order.length > this.max) {
            const t = this._getAndRemoveByKey(this.order[0]);
            t && this.onRemove(t)
        }
        return this
    }
    has(t) {
        return t.wrapped().key in this.data
    }
    getAndRemove(t) {
        return this.has(t) ? this._getAndRemoveByKey(t.wrapped().key) : null
    }
    _getAndRemoveByKey(t) {
        const e = this.data[t].shift();
        return e.timeout && clearTimeout(e.timeout), 0 === this.data[t].length && delete this.data[t], this.order.splice(this.order.indexOf(t), 1), e.value
    }
    getByKey(t) {
        const e = this.data[t];
        return e ? e[0].value : null
    }
    get(t) {
        return this.has(t) ? this.data[t.wrapped().key][0].value : null
    }
    remove(t, e) {
        if (!this.has(t)) return this;
        const i = t.wrapped().key,
            s = void 0 === e ? 0 : this.data[i].indexOf(e),
            n = this.data[i][s];
        return this.data[i].splice(s, 1), n.timeout && clearTimeout(n.timeout), 0 === this.data[i].length && delete this.data[i], this.onRemove(n.value), this.order.splice(this.order.indexOf(i), 1), this
    }
    setMaxSize(t) {
        for (this.max = t; this.order.length > this.max;) {
            const t = this._getAndRemoveByKey(this.order[0]);
            t && this.onRemove(t)
        }
        return this
    }
    filter(t) {
        const e = [];
        for (const i in this.data)
            for (const s of this.data[i]) t(s.value) || e.push(s);
        for (const t of e) this.remove(t.value.tileID, t)
    }
}

function ee(t, e, i) {
    var s = 156543.03392804097 / Math.pow(2, i);
    return [t * s - 20037508.342789244, e * s - 20037508.342789244]
}
class ie {
    constructor(t, e, i) {
        if (! function(t, e, i) {
                return !(t < 0 || t > 25 || i < 0 || i >= Math.pow(2, t) || e < 0 || e >= Math.pow(2, t))
            }(t, e, i)) throw Error(`x=${e}, y=${i}, z=${t} outside of bounds. 0<=x<${Math.pow(2, t)}, 0<=y<${Math.pow(2, t)} 0<=z<=25 `);
        this.z = t, this.x = e, this.y = i, this.key = re(0, t, t, e, i)
    }
    equals(t) {
        return this.z === t.z && this.x === t.x && this.y === t.y
    }
    url(t, e, i) {
        const s = (r = this.y, a = ee(256 * (n = this.x), 256 * (r = Math.pow(2, o = this.z) - r - 1), o), h = ee(256 * (n + 1), 256 * (r + 1), o), a[0] + "," + a[1] + "," + h[0] + "," + h[1]);
        var n, r, o, a, h;
        const l = function(t, e, i) {
            let s, n = "";
            for (let r = t; r > 0; r--) s = 1 << r - 1, n += (e & s ? 1 : 0) + (i & s ? 2 : 0);
            return n
        }(this.z, this.x, this.y);
        return t[(this.x + this.y) % t.length].replace(/{prefix}/g, (this.x % 16).toString(16) + (this.y % 16).toString(16)).replace(/{z}/g, this.z + "").replace(/{x}/g, this.x + "").replace(/{y}/g, ("tms" === i ? Math.pow(2, this.z) - this.y - 1 : this.y) + "").replace(/{ratio}/g, e > 1 ? "@2x" : "").replace(/{quadkey}/g, l).replace(/{bbox-epsg-3857}/g, s)
    }
    isChildOf(t) {
        const e = this.z - t.z;
        return e > 0 && t.x === this.x >> e && t.y === this.y >> e
    }
    getTilePoint(t) {
        const e = Math.pow(2, this.z);
        return new h((t.x * e - this.x) * D, (t.y * e - this.y) * D)
    }
    toString() {
        return `${this.z}/${this.x}/${this.y}`
    }
}
class se {
    constructor(t, e) {
        this.wrap = t, this.canonical = e, this.key = re(t, e.z, e.z, e.x, e.y)
    }
}
class ne {
    constructor(t, e, i, s, n) {
        if (this.terrainRttPosMatrix32f = null, t < i) throw Error(`overscaledZ should be >= z; overscaledZ = ${t}; z = ${i}`);
        this.overscaledZ = t, this.wrap = e, this.canonical = new ie(i, +s, +n), this.key = re(e, t, i, s, n)
    }
    clone() {
        return new ne(this.overscaledZ, this.wrap, this.canonical.z, this.canonical.x, this.canonical.y)
    }
    equals(t) {
        return this.overscaledZ === t.overscaledZ && this.wrap === t.wrap && this.canonical.equals(t.canonical)
    }
    scaledTo(t) {
        if (t > this.overscaledZ) throw Error(`targetZ > this.overscaledZ; targetZ = ${t}; overscaledZ = ${this.overscaledZ}`);
        const e = this.canonical.z - t;
        return t > this.canonical.z ? new ne(t, this.wrap, this.canonical.z, this.canonical.x, this.canonical.y) : new ne(t, this.wrap, t, this.canonical.x >> e, this.canonical.y >> e)
    }
    calculateScaledKey(t, e) {
        if (t > this.overscaledZ) throw Error(`targetZ > this.overscaledZ; targetZ = ${t}; overscaledZ = ${this.overscaledZ}`);
        const i = this.canonical.z - t;
        return t > this.canonical.z ? re(this.wrap * +e, t, this.canonical.z, this.canonical.x, this.canonical.y) : re(this.wrap * +e, t, t, this.canonical.x >> i, this.canonical.y >> i)
    }
    isChildOf(t) {
        if (t.wrap !== this.wrap) return 0;
        const e = this.canonical.z - t.canonical.z;
        return 0 === t.overscaledZ || t.overscaledZ < this.overscaledZ && t.canonical.x === this.canonical.x >> e && t.canonical.y === this.canonical.y >> e
    }
    children(t) {
        if (this.overscaledZ >= t) return [new ne(this.overscaledZ + 1, this.wrap, this.canonical.z, this.canonical.x, this.canonical.y)];
        const e = this.canonical.z + 1,
            i = 2 * this.canonical.x,
            s = 2 * this.canonical.y;
        return [new ne(e, this.wrap, e, i, s), new ne(e, this.wrap, e, i + 1, s), new ne(e, this.wrap, e, i, s + 1), new ne(e, this.wrap, e, i + 1, s + 1)]
    }
    isLessThan(t) {
        return this.wrap < t.wrap ? 1 : this.wrap > t.wrap ? 0 : this.overscaledZ < t.overscaledZ ? 1 : this.overscaledZ > t.overscaledZ ? 0 : this.canonical.x < t.canonical.x ? 1 : this.canonical.x > t.canonical.x ? 0 : this.canonical.y < t.canonical.y ? 1 : 0
    }
    wrapped() {
        return new ne(this.overscaledZ, 0, this.canonical.z, this.canonical.x, this.canonical.y)
    }
    unwrapTo(t) {
        return new ne(this.overscaledZ, t, this.canonical.z, this.canonical.x, this.canonical.y)
    }
    overscaleFactor() {
        return Math.pow(2, this.overscaledZ - this.canonical.z)
    }
    toUnwrapped() {
        return new se(this.wrap, this.canonical)
    }
    toString() {
        return `${this.overscaledZ}/${this.canonical.x}/${this.canonical.y}`
    }
    getTilePoint(t) {
        return this.canonical.getTilePoint(new $t(t.x - this.wrap, t.y))
    }
}

function re(t, e, i, s, n) {
    (t *= 2) < 0 && (t = -1 * t - 1);
    const r = 1 << i;
    return (r * r * t + r * n + s).toString(36) + i.toString(36) + e.toString(36)
}
class oe extends It {
    constructor(t, e) {
        super(), this.alwaysLoadTiles = 0, this.tileAabbScale = void 0, this._trackedTiles = new Set, this._allNeededTilesLoaded = 0, this._supressTilesLoadedEvent = 0, this._updateMode = "auto", this.id = t, this.on("data", t => this._dataHandler(t)), this.on("dataloading", () => {
            this._sourceErrored = 0
        }), this.on("error", () => {
            this._sourceErrored = this._source.loaded()
        }), this._source = ((t, e, i) => {
            const s = new(Yt(e.type))(t, e, i);
            if (s.id !== t) throw Error(`Expected Source id to be ${t} instead of ${s.id}`);
            return s
        })(t, e, this), "on" in this._source && this._source.on("tilestate", t => this._tileStateUpdated(t)), this._tiles = {}, this._cache = new te(0, t => this._unloadTile(t)), this._timers = {}, this._cacheTimers = {}, this._maxTileCacheSize = null, this._maxTileCacheZoomLevels = null, this._loadedParentTiles = {}, this._coveredTiles = {}, this._didEmitContent = 0, this._updated = 0
    }
    get updateMode() {
        return this._updateMode
    }
    set updateMode(t) {
        this._updateMode = t
    }
    onAdd(t) {
        this.map = t, this._maxTileCacheSize = t ? t._maxTileCacheSize : null, this._maxTileCacheZoomLevels = t ? t._maxTileCacheZoomLevels : null, this._source && this._source.onAdd && this._source.onAdd(t)
    }
    onRemove(t) {
        this.clearTiles(), this._source && this._source.onRemove && this._source.onRemove(t)
    }
    loaded() {
        if (this._sourceErrored) return 1;
        if (!this._sourceLoaded) return 0;
        if (!this._source.loaded()) return 0;
        if (!(void 0 === this.used && void 0 === this.usedForTerrain || this.used || this.usedForTerrain || this.alwaysLoadTiles)) return 1;
        if (!this._updated) return 0;
        for (const t in this._tiles) {
            const e = this._tiles[t];
            if ("loaded" !== e.state && "errored" !== e.state) return 0
        }
        return 1
    }
    allNeededTilesLoaded() {
        return this._allNeededTilesLoaded
    }
    getSource() {
        return this._source
    }
    pause() {
        this._paused = 1
    }
    resume() {
        if (!this._paused) return;
        const t = this._shouldReloadOnResume;
        this._paused = 0, this._shouldReloadOnResume = 0, t && this.reload(), this.transform && this.update(this.transform)
    }
    async _loadTile(t, e, i) {
        try {
            await this._source.loadTile(t), this._tileLoaded(t, e, i)
        } catch (e) {
            const i = t.state;
            t.state = "errored", this._source.fire(new St("tilestate", {
                oldState: i,
                newState: t.state,
                tile: t,
                sourceId: this.id
            })), 404 !== e.status ? this._source.fire(new Rt(e, {
                tile: t
            })) : this.update(this.transform)
        }
    }
    _unloadTile(t) {
        this._source.unloadTile && this._source.unloadTile(t)
    }
    _abortTile(t) {
        this._source.abortTile && this._source.abortTile(t), this._source.fire(new St("dataabort", {
            tile: t,
            coord: t.tileID,
            dataType: "source"
        }))
    }
    serialize() {
        return this._source.serialize()
    }
    prepare() {
        this._source.prepare && this._source.prepare()
    }
    getIds() {
        return Object.values(this._tiles).map(t => t.tileID).sort(ae).map(t => t.key)
    }
    getRenderableIds() {
        const t = [];
        for (const e in this._tiles) this._isIdRenderable(e) && t.push(this._tiles[e]);
        return t.map(t => t.tileID).sort(ae).map(t => t.key)
    }
    hasRenderableParent(t) {
        const e = this.findLoadedParent(t, 0);
        return e ? this._isIdRenderable(e.tileID.key) : 0
    }
    _isIdRenderable(t) {
        return this._tiles[t] && this._tiles[t].hasData() && !this._coveredTiles[t]
    }
    reload() {
        if (this._paused) this._shouldReloadOnResume = 1;
        else {
            this._cache.reset();
            for (const t in this._tiles) "errored" !== this._tiles[t].state && this._reloadTile(t, "reloading")
        }
    }
    async _reloadTile(t, e) {
        const i = this._tiles[t];
        if (i) {
            if ("loading" !== i.state) {
                const t = i.state;
                i.state = e, this._source.fire(new St("tilestate", {
                    oldState: t,
                    newState: i.state,
                    tile: i,
                    sourceId: this.id
                }))
            } else try {
                this._abortTile(i)
            } catch (t) {}
            await this._loadTile(i, t, e)
        }
    }
    _tileLoaded(t, e, i) {
        t.timeAdded = ht.now(), "expired" === i && (t.refreshedUponExpiration = 1), this._setTileReloadTimer(e, t), t.aborted || this._source.fire(new St("data", {
            dataType: "source",
            tile: t,
            coord: t.tileID
        }))
    }
    _backfillDEM(t) {
        const e = this.getRenderableIds();
        for (let s = 0; s < e.length; s++) {
            const n = e[s];
            if (t.neighboringTiles && t.neighboringTiles[n]) {
                const e = this.getTileByID(n);
                i(t, e), i(e, t)
            }
        }

        function i(t, e) {
            t.needsHillshadePrepare = 1, t.needsTerrainPrepare = 1;
            let i = e.tileID.canonical.x - t.tileID.canonical.x;
            const s = e.tileID.canonical.y - t.tileID.canonical.y,
                n = Math.pow(2, t.tileID.canonical.z),
                r = e.tileID.key;
            0 === i && 0 === s || Math.abs(s) > 1 || (Math.abs(i) > 1 && (1 === Math.abs(i + n) ? i += n : 1 === Math.abs(i - n) && (i -= n)), e.dem && t.dem && (t.dem.backfillBorder(e.dem, i, s), t.neighboringTiles && t.neighboringTiles[r] && (t.neighboringTiles[r].backfilled = 1)))
        }
    }
    getTile(t) {
        return this.getTileByID(t.key)
    }
    getTileByID(t) {
        return this._tiles[t]
    }
    _retainLoadedChildren(t, e, i, s) {
        for (const n in this._tiles) {
            let r = this._tiles[n];
            if (s[n] || !r.hasData() || r.tileID.overscaledZ <= e || r.tileID.overscaledZ > i) continue;
            let o = r.tileID;
            for (; r && r.tileID.overscaledZ > e + 1;) {
                const t = r.tileID.scaledTo(r.tileID.overscaledZ - 1);
                r = this._tiles[t.key], r && r.hasData() && (o = t)
            }
            let a = o;
            for (; a.overscaledZ > e;)
                if (a = a.scaledTo(a.overscaledZ - 1), t[a.key]) {
                    s[o.key] = o;
                    break
                }
        }
    }
    findLoadedParent(t, e) {
        if (t.key in this._loadedParentTiles) {
            const i = this._loadedParentTiles[t.key];
            return i && i.tileID.overscaledZ >= e ? i : null
        }
        for (let i = t.overscaledZ - 1; i >= e; i--) {
            const e = t.scaledTo(i),
                s = this._getLoadedTile(e);
            if (s) return s
        }
    }
    findLoadedSibling(t) {
        return this._getLoadedTile(t)
    }
    _getLoadedTile(t) {
        const e = this._tiles[t.key];
        return e && e.hasData() ? e : this._cache.getByKey(t.wrapped().key)
    }
    updateCacheSize(t) {
        const e = Math.floor((Math.ceil(t.width / this._source.tileSize) + 1) * (Math.ceil(t.height / this._source.tileSize) + 1) * (null === this._maxTileCacheZoomLevels ? ut.MAX_TILE_CACHE_ZOOM_LEVELS : this._maxTileCacheZoomLevels));
        this._cache.setMaxSize("number" == typeof this._maxTileCacheSize ? Math.min(this._maxTileCacheSize, e) : e)
    }
    handleWrapJump(t) {
        const e = Math.round((t - (void 0 === this._prevLng ? t : this._prevLng)) / 360);
        if (this._prevLng = t, e) {
            const t = {};
            for (const i in this._tiles) {
                const s = this._tiles[i];
                s.tileID = s.tileID.unwrapTo(s.tileID.wrap + e), t[s.tileID.key] = s
            }
            this._tiles = t;
            for (const t in this._timers) clearTimeout(this._timers[t]), delete this._timers[t];
            for (const t in this._tiles) this._setTileReloadTimer(t, this._tiles[t])
        }
    }
    _updateCoveredAndRetainedTiles(t, e, i, s) {
        const n = {},
            r = {},
            o = Object.keys(t),
            a = ht.now();
        for (const i of o) {
            const s = t[i],
                o = this._tiles[i];
            if (!o || 0 !== o.fadeEndTime && o.fadeEndTime <= a) continue;
            const h = this.findLoadedParent(s, e),
                l = this.findLoadedSibling(s),
                c = h || l || null;
            c && (this._addTile(c.tileID), n[c.tileID.key] = c.tileID), r[i] = s
        }
        this._retainLoadedChildren(r, s, i, t);
        for (const e in n) t[e] || (this._coveredTiles[e] = 1, t[e] = n[e])
    }
    update(t) {
        var e;
        if (!this._sourceLoaded || this._paused) return;
        let i;
        this.transform = t, this.updateCacheSize(t), this.handleWrapJump(this.transform.center.lng), this._coveredTiles = {}, this.used || this.usedForTerrain || this.alwaysLoadTiles ? this._source.tileID ? i = t.getVisibleUnwrappedCoordinates(this._source.tileID).map(t => new ne(t.canonical.z, t.wrap, t.canonical.z, t.canonical.x, t.canonical.y)) : (i = t.coveringTiles({
            tileSize: this.usedForTerrain ? this.tileSize : this._source.tileSize,
            minzoom: this._source.minzoom,
            maxzoom: this._source.maxzoom,
            roundZoom: this.usedForTerrain ? 0 : this._source.roundZoom,
            reparseOverscaled: this._source.reparseOverscaled,
            tileBboxScale: null !== (e = this.tileAabbScale) && void 0 !== e ? e : 1
        }), this._source.hasTile && (i = i.filter(t => this._source.hasTile(t)))) : i = [];
        const s = t.coveringZoomLevel(this._source),
            n = Math.max(s - oe.maxOverzooming, this._source.minzoom),
            r = Math.max(s + oe.maxUnderzooming, this._source.minzoom);
        if (this.usedForTerrain) {
            const t = {};
            for (const e of i)
                if (e.canonical.z > this._source.minzoom) {
                    const i = e.scaledTo(e.canonical.z - 1);
                    t[i.key] = i;
                    const s = e.scaledTo(Math.max(this._source.minzoom, Math.min(e.canonical.z, 5)));
                    t[s.key] = s
                } i = i.concat(Object.values(t))
        }
        const o = 0 === i.length && !this._updated && this._didEmitContent;
        this._updated = 1, o && this.fire(new St("data", {
            sourceDataType: "idle",
            dataType: "source",
            sourceId: this.id
        }));
        const a = this._updateRetainedTiles(i, s);
        he(this._source.type) && this._updateCoveredAndRetainedTiles(a, n, r, s);
        const h = function(t, e) {
            const i = [];
            for (const s in t) s in e || i.push(s);
            return i
        }(this._tiles, a);
        for (const t of h) this._removeTile(t);
        this._updateLoadedParentTileCache(), this._updateLoadedSiblingTileCache()
    }
    _updateRetainedTiles(t, e) {
        var i;
        const s = {},
            n = {},
            r = Math.max(e - oe.maxOverzooming, this._source.minzoom),
            o = Math.max(e + oe.maxUnderzooming, this._source.minzoom),
            a = {};
        for (const i of t) {
            const t = this._addTile(i);
            s[i.key] = i, t.hasData() || e < this._source.maxzoom && (a[i.key] = i)
        }
        this._retainLoadedChildren(a, e, o, s);
        for (const o of t) {
            let t = this._tiles[o.key];
            if (t.hasData()) continue;
            if (e + 1 > this._source.maxzoom) {
                const t = o.children(this._source.maxzoom)[0],
                    e = this.getTile(t);
                if (e && e.hasData()) {
                    s[t.key] = t;
                    continue
                }
            } else {
                const t = o.children(this._source.maxzoom);
                if (s[t[0].key] && s[t[1].key] && s[t[2].key] && s[t[3].key]) continue
            }
            let a = t.wasRequested();
            for (let e = o.overscaledZ - 1; e >= r; --e) {
                const r = o.scaledTo(e);
                if (n[r.key]) break;
                if (n[r.key] = 1, t = this.getTile(r), !t && a && (t = this._addTile(r)), t) {
                    const e = t.hasData();
                    if ((e || !(null === (i = this.map) || void 0 === i ? void 0 : i.cancelPendingTileRequestsWhileZooming) || a) && (s[r.key] = r), a = t.wasRequested(), e) break
                }
            }
        }
        return s
    }
    _updateLoadedParentTileCache() {
        this._loadedParentTiles = {};
        for (const t in this._tiles) {
            const e = [];
            let i, s = this._tiles[t].tileID;
            for (; s.overscaledZ > 0;) {
                if (s.key in this._loadedParentTiles) {
                    i = this._loadedParentTiles[s.key];
                    break
                }
                e.push(s.key);
                const t = s.scaledTo(s.overscaledZ - 1);
                if (i = this._getLoadedTile(t), i) break;
                s = t
            }
            for (const t of e) this._loadedParentTiles[t] = i
        }
    }
    _updateLoadedSiblingTileCache() {
        this._loadedSiblingTiles = {};
        for (const t in this._tiles) {
            const e = this._tiles[t].tileID,
                i = this._getLoadedTile(e);
            this._loadedSiblingTiles[e.key] = i
        }
    }
    _addTile(t) {
        let e = this._tiles[t.key];
        if (e) return e;
        e = this._cache.getAndRemove(t), e && (this._setTileReloadTimer(t.key, e), e.tileID = t, this._cacheTimers[t.key] && (clearTimeout(this._cacheTimers[t.key]), delete this._cacheTimers[t.key], this._setTileReloadTimer(t.key, e)));
        const i = e;
        return e ? (e.uses++, this._tiles[t.key] = e, this._tileStateUpdated({
            oldState: "removed",
            newState: e.state,
            sourceId: this._source.id,
            tile: e
        })) : (e = new Qt(t, this._source.tileSize * t.overscaleFactor()), e.uses++, this._tiles[t.key] = e, this._tileStateUpdated({
            oldState: "removed",
            newState: e.state,
            sourceId: this._source.id,
            tile: e
        }), this._loadTile(e, t.key, e.state)), i || this._source.fire(new St("dataloading", {
            tile: e,
            coord: e.tileID,
            dataType: "source"
        })), e
    }
    _setTileReloadTimer(t, e) {
        t in this._timers && (clearTimeout(this._timers[t]), delete this._timers[t]);
        const i = e.getExpiryTimeout();
        i && (this._timers[t] = setTimeout(() => {
            this._reloadTile(t, "expired"), delete this._timers[t]
        }, i))
    }
    _removeTile(t) {
        const e = this._tiles[t];
        e && (e.uses--, delete this._tiles[t], this._tileStateUpdated({
            oldState: e.state,
            newState: "removed",
            sourceId: this._source.id,
            tile: e
        }), this._timers[t] && (clearTimeout(this._timers[t]), delete this._timers[t]), e.uses > 0 || (e.hasData() && "reloading" !== e.state ? this._cache.add(e.tileID, e, e.getExpiryTimeout()) : (e.aborted = 1, this._abortTile(e), this._unloadTile(e))))
    }
    _tileStateUpdated(t) {
        this._tileCountsByState || (this._tileCountsByState = {
            unloaded: 0,
            errored: 0,
            expired: 0,
            loaded: 0,
            loading: 0,
            reloading: 0
        });
        const e = this._trackedTiles.has(t.tile.uid);
        if ("removed" === t.oldState ? (this._trackedTiles.add(t.tile.uid), this._tileCountsByState[t.newState]++) : "removed" === t.newState ? e && (this._tileCountsByState[t.oldState]--, this._trackedTiles.delete(t.tile.uid)) : e && (this._tileCountsByState[t.oldState]--, this._tileCountsByState[t.newState]++), e || "removed" === t.oldState) {
            const e = this._tiles ? Object.keys(this._tiles).length : 0,
                i = this._tileCountsByState.loaded + this._tileCountsByState.errored === e,
                s = {
                    data: {
                        unloaded: this._tileCountsByState.unloaded,
                        errored: this._tileCountsByState.errored,
                        expired: this._tileCountsByState.expired,
                        loaded: this._tileCountsByState.loaded,
                        loading: this._tileCountsByState.loading,
                        reloading: this._tileCountsByState.reloading,
                        cachedCount: e,
                        sourceId: t.sourceId,
                        oldState: t.oldState,
                        newState: t.newState,
                        tile: t.tile,
                        allLoaded: i
                    }
                };
            this._allNeededTilesLoaded = i, this.fire("tileupdate", s), !this._supressTilesLoadedEvent && i && this.fire("tilesloaded", s)
        }
    }
    _dataHandler(t) {
        const e = t.sourceDataType;
        "source" === t.dataType && "metadata" === e && (this._sourceLoaded = 1), this._sourceLoaded && !this._paused && "source" === t.dataType && "content" === e && (this.reload(), this.transform && this.update(this.transform), this._didEmitContent = 1)
    }
    clearTiles() {
        this._shouldReloadOnResume = 0, this._paused = 0;
        try {
            this._supressTilesLoadedEvent = 1;
            for (const t in this._tiles) this._removeTile(t)
        } finally {
            this._supressTilesLoadedEvent = 0
        }
        this._cache.reset()
    }
    tilesIn(t, e, i) {
        const s = [],
            n = this.transform;
        if (!n) return s;
        const r = i ? n.getCameraQueryGeometry(t) : t,
            o = t.map(t => n.screenPointToMercatorCoordinate(t)),
            a = r.map(t => n.screenPointToMercatorCoordinate(t)),
            h = this.getIds();
        let l = 1 / 0,
            c = 1 / 0,
            u = -1 / 0,
            d = -1 / 0;
        for (const t of a) l = Math.min(l, t.x), c = Math.min(c, t.y), u = Math.max(u, t.x), d = Math.max(d, t.y);
        for (let t = 0; t < h.length; t++) {
            const i = this._tiles[h[t]],
                r = i.tileID,
                p = Math.pow(2, n.zoom - i.tileID.overscaledZ),
                _ = e * i.queryPadding * D / i.tileSize / p,
                m = [r.getTilePoint(new $t(l, c)), r.getTilePoint(new $t(u, d))];
            if (m[0].x - _ < D && m[0].y - _ < D && m[1].x + _ >= 0 && m[1].y + _ >= 0) {
                const t = o.map(t => r.getTilePoint(t)),
                    e = a.map(t => r.getTilePoint(t));
                s.push({
                    tile: i,
                    tileID: r,
                    queryGeometry: t,
                    cameraQueryGeometry: e,
                    scale: p
                })
            }
        }
        return s
    }
    getVisibleCoordinates() {
        const t = this.getRenderableIds().map(t => this._tiles[t].tileID);
        return this.transform && this.transform.precacheTiles(t), t
    }
    hasTransition() {
        if (this._source.hasTransition()) return 1;
        if (he(this._source.type)) {
            const t = ht.now();
            for (const e in this._tiles)
                if (this._tiles[e].fadeEndTime >= t) return 1
        }
        return 0
    }
    setDependencies(t, e, i) {
        const s = this._tiles[t];
        s && s.setDependencies(e, i)
    }
    reloadTilesForDependencies(t, e) {
        for (const i in this._tiles) this._tiles[i].hasDependency(t, e) && this._reloadTile(i, "reloading");
        this._cache.filter(i => !i.hasDependency(t, e))
    }
}

function ae(t, e) {
    const i = Math.abs(2 * t.wrap) - +(t.wrap < 0);
    return t.overscaledZ - e.overscaledZ || Math.abs(2 * e.wrap) - +(e.wrap < 0) - i || e.canonical.y - t.canonical.y || e.canonical.x - t.canonical.x
}

function he(t) {
    return "raster" === t || "image" === t || "video" === t
}
oe.maxOverzooming = 10, oe.maxUnderzooming = 3;
class le {
    constructor() {
        this.first = 1
    }
    update(t, e) {
        const i = Math.floor(t);
        return this.first ? (this.first = 0, this.lastIntegerZoom = i, this.lastIntegerZoomTime = 0, this.lastZoom = t, this.lastFloorZoom = i, 1) : (this.lastFloorZoom > i ? (this.lastIntegerZoom = i + 1, this.lastIntegerZoomTime = e) : this.lastFloorZoom < i && (this.lastIntegerZoom = i, this.lastIntegerZoomTime = e), t !== this.lastZoom ? (this.lastZoom = t, this.lastFloorZoom = i, 1) : 0)
    }
}
var ce = "void main() {gl_FragColor=vec4(1.0);}",
    ue = "uniform float u_fade_t;uniform float u_opacity;uniform sampler2D u_image0;uniform sampler2D u_image1;varying vec2 v_pos0;varying vec2 v_pos1;uniform float u_brightness_low;uniform float u_brightness_high;uniform float u_saturation_factor;uniform float u_contrast_factor;uniform vec3 u_spin_weights;void main() {vec4 color0=texture2D(u_image0,v_pos0);vec4 color1=texture2D(u_image1,v_pos1);\n#ifdef CUSTOM_RASTER\ncolor0=pixelTransform(color0,true);color1=pixelTransform(color1,false);\n#endif\nif (color0.a > 0.0) {color0.rgb=color0.rgb/color0.a;}if (color1.a > 0.0) {color1.rgb=color1.rgb/color1.a;}vec4 color=mix(color0,color1,u_fade_t);color.a*=u_opacity;vec3 rgb=color.rgb;rgb=vec3(dot(rgb,u_spin_weights.xyz),dot(rgb,u_spin_weights.zxy),dot(rgb,u_spin_weights.yzx));float average=(color.r+color.g+color.b)/3.0;rgb+=(average-rgb)*u_saturation_factor;rgb=(rgb-0.5)*u_contrast_factor+0.5;vec3 u_high_vec=vec3(u_brightness_low,u_brightness_low,u_brightness_low);vec3 u_low_vec=vec3(u_brightness_high,u_brightness_high,u_brightness_high);gl_FragColor=vec4(mix(u_high_vec,u_low_vec,rgb)*color.a,color.a);\n#ifdef OVERDRAW_INSPECTOR\ngl_FragColor=vec4(1.0);\n#endif\n}",
    de = "uniform vec2 u_tl_parent;uniform float u_scale_parent;uniform float u_buffer_scale;uniform vec4 u_coords_top;uniform vec4 u_coords_bottom;attribute vec2 a_pos;varying vec2 v_pos0;varying vec2 v_pos1;void main() {vec2 fractionalPos=a_pos/8192.0;vec2 position=mix(mix(u_coords_top.xy,u_coords_top.zw,fractionalPos.x),mix(u_coords_bottom.xy,u_coords_bottom.zw,fractionalPos.x),fractionalPos.y\n);gl_Position=projectTile(position);v_pos0=(fractionalPos-0.5)/u_buffer_scale+0.5;\n#ifdef GLOBE\nif (a_pos.y <-32767.5) {v_pos0.y=0.0;}if (a_pos.y > 32766.5) {v_pos0.y=1.0;}\n#endif\nv_pos1=v_pos0*u_scale_parent+u_tl_parent;}";
class pe {
    constructor(t, e, i, s = 1, n = 1) {
        this.r = t, this.g = e, this.b = i, this.a = s, n || (this.r *= s, this.g *= s, this.b *= s, s || this.overwriteGetter("rgb", [t, e, i, s]))
    }
    static parse(t) {
        if (t instanceof pe) return t;
        if ("string" != typeof t) return;
        const e = function(t) {
            if ("transparent" === (t = t.toLowerCase().trim())) return [0, 0, 0, 0];
            const e = _e(i = ye, s = t) ? i[s] : void 0;
            var i, s;
            if (e) {
                const [t, i, s] = e;
                return [t / 255, i / 255, s / 255, 1]
            }
            if (t.startsWith("#") && /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/.test(t)) {
                const e = t.length < 6 ? 1 : 2;
                let i = 1;
                return [me(t.slice(i, i += e)), me(t.slice(i, i += e)), me(t.slice(i, i += e)), me(t.slice(i, i + e) || "ff")]
            }
            if (t.startsWith("rgb")) {
                const e = t.match(/^rgba?\(\s*([\de.+-]+)(%)?(?:\s+|\s*(,)\s*)([\de.+-]+)(%)?(?:\s+|\s*(,)\s*)([\de.+-]+)(%)?(?:\s*([,\/])\s*([\de.+-]+)(%)?)?\s*\)$/);
                if (e) {
                    const [t, i, s, n, r, o, a, h, l, c, u, d] = e, p = "" + (n || " ") + (a || " ") + c;
                    if ("  " === p || "  /" === p || ",," === p || ",,," === p) {
                        const t = "" + s + o + l,
                            e = "%%%" === t ? 100 : "" === t ? 255 : 0;
                        if (e) {
                            const t = [ge(+i / e, 0, 1), ge(+r / e, 0, 1), ge(+h / e, 0, 1), u ? fe(+u, d) : 1];
                            if (!t.some(Number.isNaN)) return t
                        }
                    }
                }
            }
        }(t);
        return e ? new pe(...e, 0) : void 0
    }
    get rgb() {
        const {
            r: t,
            g: e,
            b: i,
            a: s
        } = this, n = s || 1 / 0;
        return this.overwriteGetter("rgb", [t / n, e / n, i / n, s])
    }
    overwriteGetter(t, e) {
        return Object.defineProperty(this, t, {
            value: e
        }), e
    }
    toString() {
        const [t, e, i, s] = this.rgb;
        return `rgba(${[t, e, i].map(t => Math.round(255 * t)).join(",")},${s})`
    }
}
pe.black = new pe(0, 0, 0, 1), pe.white = new pe(1, 1, 1, 1), pe.transparent = new pe(0, 0, 0, 0), pe.red = new pe(1, 0, 0, 1);
const _e = Object.hasOwn || function(t, e) {
    return Object.prototype.hasOwnProperty.call(t, e)
};

function me(t) {
    return parseInt(t.padEnd(2, t), 16) / 255
}

function fe(t, e) {
    return ge(e ? t / 100 : t, 0, 1)
}

function ge(t, e, i) {
    return Math.min(Math.max(e, t), i)
}
const ye = {
    aliceblue: [240, 248, 255],
    antiquewhite: [250, 235, 215],
    aqua: [0, 255, 255],
    aquamarine: [127, 255, 212],
    azure: [240, 255, 255],
    beige: [245, 245, 220],
    bisque: [255, 228, 196],
    black: [0, 0, 0],
    blanchedalmond: [255, 235, 205],
    blue: [0, 0, 255],
    blueviolet: [138, 43, 226],
    brown: [165, 42, 42],
    burlywood: [222, 184, 135],
    cadetblue: [95, 158, 160],
    chartreuse: [127, 255, 0],
    chocolate: [210, 105, 30],
    coral: [255, 127, 80],
    cornflowerblue: [100, 149, 237],
    cornsilk: [255, 248, 220],
    crimson: [220, 20, 60],
    cyan: [0, 255, 255],
    darkblue: [0, 0, 139],
    darkcyan: [0, 139, 139],
    darkgoldenrod: [184, 134, 11],
    darkgray: [169, 169, 169],
    darkgreen: [0, 100, 0],
    darkgrey: [169, 169, 169],
    darkkhaki: [189, 183, 107],
    darkmagenta: [139, 0, 139],
    darkolivegreen: [85, 107, 47],
    darkorange: [255, 140, 0],
    darkorchid: [153, 50, 204],
    darkred: [139, 0, 0],
    darksalmon: [233, 150, 122],
    darkseagreen: [143, 188, 143],
    darkslateblue: [72, 61, 139],
    darkslategray: [47, 79, 79],
    darkslategrey: [47, 79, 79],
    darkturquoise: [0, 206, 209],
    darkviolet: [148, 0, 211],
    deeppink: [255, 20, 147],
    deepskyblue: [0, 191, 255],
    dimgray: [105, 105, 105],
    dimgrey: [105, 105, 105],
    dodgerblue: [30, 144, 255],
    firebrick: [178, 34, 34],
    floralwhite: [255, 250, 240],
    forestgreen: [34, 139, 34],
    fuchsia: [255, 0, 255],
    gainsboro: [220, 220, 220],
    ghostwhite: [248, 248, 255],
    gold: [255, 215, 0],
    goldenrod: [218, 165, 32],
    gray: [128, 128, 128],
    green: [0, 128, 0],
    greenyellow: [173, 255, 47],
    grey: [128, 128, 128],
    honeydew: [240, 255, 240],
    hotpink: [255, 105, 180],
    indianred: [205, 92, 92],
    indigo: [75, 0, 130],
    ivory: [255, 255, 240],
    khaki: [240, 230, 140],
    lavender: [230, 230, 250],
    lavenderblush: [255, 240, 245],
    lawngreen: [124, 252, 0],
    lemonchiffon: [255, 250, 205],
    lightblue: [173, 216, 230],
    lightcoral: [240, 128, 128],
    lightcyan: [224, 255, 255],
    lightgoldenrodyellow: [250, 250, 210],
    lightgray: [211, 211, 211],
    lightgreen: [144, 238, 144],
    lightgrey: [211, 211, 211],
    lightpink: [255, 182, 193],
    lightsalmon: [255, 160, 122],
    lightseagreen: [32, 178, 170],
    lightskyblue: [135, 206, 250],
    lightslategray: [119, 136, 153],
    lightslategrey: [119, 136, 153],
    lightsteelblue: [176, 196, 222],
    lightyellow: [255, 255, 224],
    lime: [0, 255, 0],
    limegreen: [50, 205, 50],
    linen: [250, 240, 230],
    magenta: [255, 0, 255],
    maroon: [128, 0, 0],
    mediumaquamarine: [102, 205, 170],
    mediumblue: [0, 0, 205],
    mediumorchid: [186, 85, 211],
    mediumpurple: [147, 112, 219],
    mediumseagreen: [60, 179, 113],
    mediumslateblue: [123, 104, 238],
    mediumspringgreen: [0, 250, 154],
    mediumturquoise: [72, 209, 204],
    mediumvioletred: [199, 21, 133],
    midnightblue: [25, 25, 112],
    mintcream: [245, 255, 250],
    mistyrose: [255, 228, 225],
    moccasin: [255, 228, 181],
    navajowhite: [255, 222, 173],
    navy: [0, 0, 128],
    oldlace: [253, 245, 230],
    olive: [128, 128, 0],
    olivedrab: [107, 142, 35],
    orange: [255, 165, 0],
    orangered: [255, 69, 0],
    orchid: [218, 112, 214],
    palegoldenrod: [238, 232, 170],
    palegreen: [152, 251, 152],
    paleturquoise: [175, 238, 238],
    palevioletred: [219, 112, 147],
    papayawhip: [255, 239, 213],
    peachpuff: [255, 218, 185],
    peru: [205, 133, 63],
    pink: [255, 192, 203],
    plum: [221, 160, 221],
    powderblue: [176, 224, 230],
    purple: [128, 0, 128],
    rebeccapurple: [102, 51, 153],
    red: [255, 0, 0],
    rosybrown: [188, 143, 143],
    royalblue: [65, 105, 225],
    saddlebrown: [139, 69, 19],
    salmon: [250, 128, 114],
    sandybrown: [244, 164, 96],
    seagreen: [46, 139, 87],
    seashell: [255, 245, 238],
    sienna: [160, 82, 45],
    silver: [192, 192, 192],
    skyblue: [135, 206, 235],
    slateblue: [106, 90, 205],
    slategray: [112, 128, 144],
    slategrey: [112, 128, 144],
    snow: [255, 250, 250],
    springgreen: [0, 255, 127],
    steelblue: [70, 130, 180],
    tan: [210, 180, 140],
    teal: [0, 128, 128],
    thistle: [216, 191, 216],
    tomato: [255, 99, 71],
    turquoise: [64, 224, 208],
    violet: [238, 130, 238],
    wheat: [245, 222, 179],
    white: [255, 255, 255],
    whitesmoke: [245, 245, 245],
    yellow: [255, 255, 0],
    yellowgreen: [154, 205, 50]
};
class ve {
    constructor(t, e) {
        this.gl = t.gl, this.location = e
    }
}
class be extends ve {
    constructor(t, e) {
        super(t, e), this.current = 0
    }
    set(t) {
        this.current !== t && (this.current = t, this.gl.uniform1i(this.location, t))
    }
}
class xe extends ve {
    constructor(t, e) {
        super(t, e), this.current = 0
    }
    set(t) {
        this.current !== t && (this.current = t, this.gl.uniform1f(this.location, t))
    }
}
class we extends ve {
    constructor(t, e) {
        super(t, e), this.current = [0, 0]
    }
    set(t) {
        t[0] === this.current[0] && t[1] === this.current[1] || (this.current = t, this.gl.uniform2f(this.location, t[0], t[1]))
    }
}
class Te extends ve {
    constructor(t, e) {
        super(t, e), this.current = [0, 0, 0]
    }
    set(t) {
        t[0] === this.current[0] && t[1] === this.current[1] && t[2] === this.current[2] || (this.current = t, this.gl.uniform3f(this.location, t[0], t[1], t[2]))
    }
}
class Me extends ve {
    constructor(t, e) {
        super(t, e), this.current = [0, 0, 0, 0]
    }
    set(t) {
        t[0] === this.current[0] && t[1] === this.current[1] && t[2] === this.current[2] && t[3] === this.current[3] || (this.current = t, this.gl.uniform4f(this.location, t[0], t[1], t[2], t[3]))
    }
}
class Pe extends ve {
    constructor(t, e) {
        super(t, e), this.current = pe.transparent
    }
    set(t) {
        t.r === this.current.r && t.g === this.current.g && t.b === this.current.b && t.a === this.current.a || (this.current = t, this.gl.uniform4f(this.location, t.r, t.g, t.b, t.a))
    }
}
const Ee = new Float32Array(16);
class Le extends ve {
    constructor(t, e) {
        super(t, e), this.current = Ee
    }
    set(t) {
        if (t[12] !== this.current[12] || t[0] !== this.current[0]) return this.current = t, void this.gl.uniformMatrix4fv(this.location, 0, t);
        for (let e = 1; e < 16; e++)
            if (t[e] !== this.current[e]) {
                this.current = t, this.gl.uniformMatrix4fv(this.location, 0, t);
                break
            }
    }
}
const Ce = (t, e = 1) => ({
        u_color: t,
        u_overlay: 0,
        u_overlay_scale: e
    }),
    Se = (t, e, i, s, n) => ({
        u_tl_parent: t,
        u_scale_parent: e,
        u_buffer_scale: 1,
        u_fade_t: i.mix,
        u_opacity: i.opacity * (s.paint ? s.paint["raster-opacity"] : 1),
        u_image0: 0,
        u_image1: 1,
        u_brightness_low: 0,
        u_brightness_high: 1,
        u_saturation_factor: -0,
        u_contrast_factor: 1,
        u_spin_weights: Re(0),
        u_coords_top: [n[0].x, n[0].y, n[1].x, n[1].y],
        u_coords_bottom: [n[3].x, n[3].y, n[2].x, n[2].y]
    });

function Re(t) {
    const e = Math.sin(t *= Math.PI / 180),
        i = Math.cos(t);
    return [(2 * i + 1) / 3, (-Math.sqrt(3) * e - i + 1) / 3, (Math.sqrt(3) * e - i + 1) / 3]
}
const Ie = (t, e) => ({
        u_opacity: t,
        u_color: e
    }),
    Ae = new WeakMap;

function ze(t) {
    var e;
    if (Ae.has(t)) return Ae.get(t);
    {
        const i = null === (e = t.getParameter(t.VERSION)) || void 0 === e ? void 0 : e.startsWith("WebGL 2.0");
        return Ae.set(t, i), i
    }
}
const Oe = 6371e3;
class ke {
    constructor(t, e, i) {
        if (isNaN(t) || isNaN(e)) throw Error(`Invalid LatLng object: (${t}, ${e})`);
        this.lat = +t, this.lng = +e, void 0 !== i && (this.alt = +i)
    }
    equals(t, e) {
        return t ? (t = De(t), Math.max(Math.abs(this.lat - t.lat), Math.abs(this.lng - t.lng)) <= (void 0 === e ? 1e-9 : e)) : 0
    }
    toString(t) {
        return `LatLng(${e(this.lat, t)}, ${e(this.lng, t)})`
    }
    distanceTo(t) {
        const e = De(t),
            i = Math.PI / 180,
            s = this.lat * i,
            n = e.lat * i,
            r = Math.sin((e.lat - this.lat) * i / 2),
            o = Math.sin((e.lng - this.lng) * i / 2),
            a = r * r + Math.cos(s) * Math.cos(n) * o * o;
        return Oe * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)))
    }
    wrap() {
        return new ke(this.lat, i(this.lng, [-180, 180], 1), this.alt)
    }
    clone() {
        return new ke(this.lat, this.lng, this.alt)
    }
}

function De(t, e, i) {
    if (t instanceof ke) return t;
    if (null == t) throw Error("The first parameter of toLatLng cannot be null or undefined.");
    if (Array.isArray(t)) {
        if (3 === t.length) return new ke(t[0], t[1], t[2]);
        if (2 === t.length) return new ke(t[0], t[1]);
        throw Error("The first parameter of toLatLng cannot be an array of a length different than 2 or 3.")
    }
    if ("object" == typeof t && "lat" in t) return new ke(t.lat, "lng" in t ? t.lng : t.lon, t.alt);
    if (void 0 === e) throw Error("The second parameter of toLatLng cannot be null or undefined when the first parameter is not sufficient to describe coordinates.");
    return new ke(t, e, i)
}
class Be {
    constructor(t, e) {
        if (!t) return;
        if ("object" == typeof t && "_northEast" in t && "_southWest" in t) return this.extend(De(t._northEast)), void this.extend(De(t._southWest));
        const i = Ze(t) ? e ? [t, e] : [t] : t,
            s = i.length;
        for (let t = 0; t < s; t++) this.extend(i[t])
    }
    extend(t) {
        const e = this._southWest,
            i = this._northEast;
        let s, n;
        if (Ze(t)) {
            const e = De(t);
            s = e, n = e
        } else {
            const e = Fe(t);
            if (s = e._southWest, n = e._northEast, !s || !n) return this
        }
        return e || i ? (e.lat = Math.min(s.lat, e.lat), e.lng = Math.min(s.lng, e.lng), i.lat = Math.max(n.lat, i.lat), i.lng = Math.max(n.lng, i.lng)) : (this._southWest = new ke(s.lat, s.lng), this._northEast = new ke(n.lat, n.lng)), this
    }
    pad(t) {
        const e = this._southWest,
            i = this._northEast,
            s = Math.abs(e.lat - i.lat) * t,
            n = Math.abs(e.lng - i.lng) * t;
        return new Be(new ke(e.lat - s, e.lng - n), new ke(i.lat + s, i.lng + n))
    }
    getCenter() {
        return new ke((this._southWest.lat + this._northEast.lat) / 2, (this._southWest.lng + this._northEast.lng) / 2)
    }
    getSouthWest() {
        return this._southWest
    }
    getNorthEast() {
        return this._northEast
    }
    getNorthWest() {
        return new ke(this.getNorth(), this.getWest())
    }
    getSouthEast() {
        return new ke(this.getSouth(), this.getEast())
    }
    getWest() {
        return this._southWest.lng
    }
    getSouth() {
        return this._southWest.lat
    }
    getEast() {
        return this._northEast.lng
    }
    getNorth() {
        return this._northEast.lat
    }
    contains(t) {
        let e, i;
        Ze(t) ? e = i = t = De(t) : (e = (t = Fe(t)).getSouthWest(), i = t.getNorthEast());
        const s = this._southWest,
            n = this._northEast;
        return e.lat >= s.lat && i.lat <= n.lat && e.lng >= s.lng && i.lng <= n.lng
    }
    intersects(t) {
        t = Fe(t);
        const e = this._southWest,
            i = this._northEast,
            s = t.getSouthWest(),
            n = t.getNorthEast();
        return n.lat >= e.lat && s.lat <= i.lat && n.lng >= e.lng && s.lng <= i.lng
    }
    overlaps(t) {
        t = Fe(t);
        const e = this._southWest,
            i = this._northEast,
            s = t.getSouthWest(),
            n = t.getNorthEast();
        return n.lat > e.lat && s.lat < i.lat && n.lng > e.lng && s.lng < i.lng
    }
    toBBoxString() {
        return [this.getWest(), this.getSouth(), this.getEast(), this.getNorth()].join(",")
    }
    equals(t, e) {
        return t ? (t = Fe(t), this._southWest.equals(t.getSouthWest(), e) && this._northEast.equals(t.getNorthEast(), e)) : 0
    }
    isValid() {
        return !(!this._southWest || !this._northEast)
    }
}

function Fe(t, e) {
    return t instanceof Be ? t : new Be(t, e)
}

function Ze(t) {
    return !(t instanceof Be || Array.isArray(t) && "number" != typeof t[0])
}

function Ne(t, e) {
    return new Be(t, e)
}
const je = !We("chrome") && We("safari");
"undefined" != typeof orientation || We("mobile");
const Ue = "undefined" == typeof window ? 0 : !!window.PointerEvent,
    Ge = "undefined" == typeof window ? 0 : "ontouchstart" in window || !!window.TouchEvent,
    qe = Ge || Ue,
    $e = "undefined" == typeof window || void 0 === window.devicePixelRatio ? 0 : window.devicePixelRatio > 1;

function We(t) {
    return "undefined" == typeof navigator || void 0 === navigator.userAgent ? 0 : navigator.userAgent.toLowerCase().includes(t)
}
"undefined" != typeof navigator && void 0 !== navigator.platform && navigator.platform.startsWith("Mac"), "undefined" != typeof navigator && void 0 !== navigator.platform && navigator.platform.startsWith("Linux");
var He = {
    safari: je,
    pointer: Ue,
    touch: qe,
    touchNative: Ge,
    retina: $e
};
const Ve = {
        touchstart: "pointerdown",
        touchmove: "pointermove",
        touchend: "pointerup",
        touchcancel: "pointercancel"
    },
    Xe = {
        touchstart: function(t, e) {
            ei(t, e)
        },
        touchmove: ei,
        touchend: ei,
        touchcancel: ei
    },
    Ke = {};
let Ye = 0;

function Je(t) {
    Ke[t.pointerId] = t
}

function Qe(t) {
    Ke[t.pointerId] && (Ke[t.pointerId] = t)
}

function ti(t) {
    delete Ke[t.pointerId]
}

function ei(t, e) {
    if ("mouse" !== e.pointerType) {
        e.touches = [];
        for (const t in Ke) Object.prototype.hasOwnProperty.call(Ke, t) && e.touches.push(Ke[t]);
        e.changedTouches = [e], t(e)
    }
}

function ii(t, e, i, n) {
    if ("string" == typeof e) {
        const r = s(e);
        for (let e = 0, s = r.length; e < s; e++) ai(t, r[e], i, n)
    } else
        for (const [s, n] of Object.entries(e)) ai(t, s, n, i)
}
const si = "_leaflet_events";

function ni(t, e, i, n) {
    if (e)
        if ("string" == typeof e) {
            const r = s(e);
            if (void 0 === i) ri(t, t => r.includes(t));
            else
                for (let s = 0, o = e.length; s < o; s++) hi(t, r[s], i, n)
        } else
            for (const [s, n] of Object.entries(e)) hi(t, s, n, i);
    else ri(t), delete t[si]
}

function ri(t, e) {
    for (const i in t[si])
        if (Object.prototype.hasOwnProperty.call(t[si], i)) {
            const s = i.split(/\d/)[0];
            e && !e(s) || hi(t, s, null, void 0, i)
        }
}
const oi = {
    mouseenter: "mouseover",
    mouseleave: "mouseout",
    wheel: "undefined" == typeof window ? 0 : !("onwheel" in window)
};

function ai(t, e, i, s) {
    var n;
    const a = e + r(i) + (s ? "_" + r(s) : "");
    if (null === (n = t[si]) || void 0 === n ? void 0 : n[a]) return;
    let h = function(e) {
        return i.call(s || t, e || window.event)
    };
    const l = h;
    !He.touchNative && He.pointer && e.startsWith("touch") ? h = function(t, e, i) {
        return "touchstart" === e && (Ye || (document.addEventListener("pointerdown", Je, 1), document.addEventListener("pointermove", Qe, 1), document.addEventListener("pointerup", ti, 1), document.addEventListener("pointercancel", ti, 1), Ye = 1)), Xe[e] ? (i = Xe[e].bind(this, i), t.addEventListener(Ve[e], i, 0), i) : (console.warn("wrong event specified:", e), o)
    }(t, e, h) : He.touch && "dblclick" === e ? h = function(t, e) {
        t.addEventListener("dblclick", e);
        let i, s = 0;

        function n(t) {
            var e;
            if (1 !== t.detail) return void(i = t.detail);
            if ("mouse" === t.pointerType || t.sourceCapabilities && !t.sourceCapabilities.firesTouchEvents) return;
            const n = t.composedPath();
            if (n.some(t => t instanceof HTMLLabelElement && "for" in t.attributes) && !n.some(t => t instanceof HTMLInputElement || t instanceof HTMLSelectElement)) return;
            const r = Date.now();
            r - s <= 200 ? (i++, 2 === i && (null === (e = t.target) || void 0 === e || e.dispatchEvent(function(t) {
                const e = {
                    bubbles: t.bubbles,
                    cancelable: t.cancelable,
                    composed: t.composed,
                    detail: 2,
                    view: t.view,
                    screenX: t.screenX,
                    screenY: t.screenY,
                    clientX: t.clientX,
                    clientY: t.clientY,
                    ctrlKey: t.ctrlKey,
                    shiftKey: t.shiftKey,
                    altKey: t.altKey,
                    metaKey: t.metaKey,
                    button: t.button,
                    buttons: t.buttons,
                    relatedTarget: t.relatedTarget,
                    region: t.region,
                    pointerId: void 0,
                    width: void 0,
                    height: void 0,
                    pressure: void 0,
                    tangentialPressure: void 0,
                    tiltX: void 0,
                    tiltY: void 0,
                    twist: void 0,
                    pointerType: void 0,
                    isPrimary: void 0
                };
                let i;
                if (t instanceof PointerEvent) {
                    const s = Object.assign(Object.assign({}, e), {
                        pointerId: t.pointerId,
                        width: t.width,
                        height: t.height,
                        pressure: t.pressure,
                        tangentialPressure: t.tangentialPressure,
                        tiltX: t.tiltX,
                        tiltY: t.tiltY,
                        twist: t.twist,
                        pointerType: t.pointerType,
                        isPrimary: t.isPrimary
                    });
                    i = new PointerEvent("dblclick", s)
                } else i = new MouseEvent("dblclick", e);
                return i
            }(t)))) : i = 1, s = r
        }
        return t.addEventListener("click", n), {
            dblclick: e,
            simDblclick: n
        }
    }(t, h) : "addEventListener" in t ? "touchstart" === e || "touchmove" === e || "wheel" === e ? t.addEventListener(oi[e] || e, h, {
        passive: 0
    }) : "mouseenter" === e || "mouseleave" === e ? (h = function(e) {
        e = e || window.event, ui(t, e) && l(e)
    }, t.addEventListener(oi[e], h, 0)) : t.addEventListener(e, l, 0) : t.attachEvent("on" + e, h), t[si] = t[si] || {}, t[si][a] = h
}

function hi(t, e, i, s, n) {
    n = n || e + r(i) + (s ? "_" + r(s) : "");
    const o = t[si] && t[si][n];
    o && (!He.touchNative && He.pointer && e.startsWith("touch") ? function(t, e, i) {
        Ve[e] ? t.removeEventListener(Ve[e], i, 0) : console.warn("wrong event specified:", e)
    }(t, e, o) : He.touch && "dblclick" === e ? function(t, e) {
        t.removeEventListener("dblclick", e.dblclick), t.removeEventListener("click", e.simDblclick)
    }(t, o) : "removeEventListener" in t ? t.removeEventListener(oi[e] || e, o, 0) : t.detachEvent("on" + e, o), t[si][n] = null)
}

function li(t) {
    t.stopPropagation ? t.stopPropagation() : t.originalEvent ? t.originalEvent._stopped = 1 : t.cancelBubble = 1
}

function ci(t) {
    t.preventDefault ? t.preventDefault() : t.returnValue = 0
}

function ui(t, e) {
    let i = e.relatedTarget;
    if (!i) return 1;
    try {
        for (; i && i !== t;) i = i.parentNode
    } catch (t) {
        return 0
    }
    return i !== t
}
var di = {
    on: ii,
    addListener: ii,
    off: ni,
    removeListener: ni,
    stopPropagation: li,
    disableScrollPropagation: function(t) {
        ai(t, "wheel", li)
    },
    disableClickPropagation: function(t) {
        ii(t, "mousedown touchstart dblclick contextmenu", li), t._leaflet_disable_click = 1
    },
    preventDefault: ci,
    stop: function(t) {
        ci(t), li(t)
    },
    isExternalTarget: ui
};
const pi = /\{ *([\w_ -]+) *\}/g;

function _i(t, e) {
    return t.replace(pi, (t, i) => {
        let s = e[i];
        if (void 0 === s) throw Error("No value provided for variable " + t);
        return "function" == typeof s && (s = s(e)), s
    })
}

function mi(t, e, i) {
    const s = e || new h(0, 0);
    t.style.transform = `translate3d(${s.x}px,${s.y}px,0)${i ? ` scale(${i})` : ""}`
}

function fi(t) {
    const e = De(t);
    return new Bt(e.lng, e.lat)
}

function gi(t) {
    const e = 1 / Math.max(t || .5, .2);
    return t => 1 - Math.pow(1 - t, e)
}

function yi(t) {
    return t instanceof Be ? t : Fe(t)
}

function vi(t) {
    const e = yi(t);
    return Ft.convert([e.getWest(), e.getSouth(), e.getEast(), e.getNorth()])
}

function bi(t, e) {
    let i = e.relatedTarget;
    if (!i) return 1;
    try {
        for (; i && i !== t;) i = i.parentNode
    } catch (t) {
        return 0
    }
    return i !== t
}

function xi(t, e) {
    return window.requestAnimationFrame(t.bind(e))
}

function wi(t) {
    void 0 !== t && "undefined" != typeof window && window.cancelAnimationFrame(t)
}

function Ti(t, ...e) {
    for (let i = 0, s = e.length; i < s; i++) {
        const s = e[i];
        for (const e in s) t[e] = s[e]
    }
    return t
}

function Mi(t, e) {
    Object.prototype.hasOwnProperty.call(t, "options") || (t.options = t.options ? Object.create(t.options) : {});
    for (const i in e) Object.prototype.hasOwnProperty.call(e, i) && (t.options[i] = e[i]);
    return t.options
}

function Pi(t, e, i) {
    di.on(t, "focus", () => {
        i._tooltip && (i._tooltip._source = e, i.openTooltip())
    }, i), di.on(t, "blur", i.closeTooltip, i)
}

function Ei(t, e) {
    var i;
    const s = null === (i = e._tooltip) || void 0 === i ? void 0 : i.containerId;
    s && t.setAttribute("aria-describedby", s)
}

function Li(t) {
    return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;").replace(/\//g, "&#x2F;")
}
class Ci {
    constructor() {
        this._events = {}, this._firingCount = 0, this._eventParents = {}
    }
    on(t, e, i) {
        if ("object" == typeof t)
            for (const i in t) Object.prototype.hasOwnProperty.call(t, i) && void 0 !== t[i] && this._on(i, t[i], e);
        else if (t) {
            const n = s(t);
            for (let t = 0, s = n.length; t < s; t++) this._on(n[t], e, i)
        }
        return this
    }
    off(t, e, i) {
        if (arguments.length) {
            if ("object" == typeof t)
                for (const i in t) Object.prototype.hasOwnProperty.call(t, i) && void 0 !== t[i] && this._off(i, t[i], e);
            else if (t) {
                const n = s(t),
                    r = 1 === arguments.length;
                for (let t = 0, s = n.length; t < s; t++) r ? this._off(n[t]) : this._off(n[t], e, i)
            }
        } else this._events = {};
        return this
    }
    _on(t, e, i, s) {
        if ("function" != typeof e) return void console.warn("wrong listener type: " + typeof e);
        if (0 != this._listens(t, e, i)) return;
        i === this && (i = void 0);
        const n = {
            fn: e,
            ctx: i
        };
        s && (n.once = 1), this._events[t] = this._events[t] || [], this._events[t].push(n)
    }
    _off(t, e, i) {
        if (!this._events) return;
        let s = this._events[t];
        if (!s) return;
        if (1 === arguments.length) {
            if (this._firingCount > 0)
                for (let t = 0, e = s.length; t < e; t++) s[t].fn = o;
            return void delete this._events[t]
        }
        if ("function" != typeof e) return void console.warn("wrong listener type: " + typeof e);
        const n = this._listenerIndex(t, e, i);
        n >= 0 && (this._firingCount > 0 && (s[n].fn = o, this._events[t] = s = s.slice()), s.splice(n, 1))
    }
    fire(t, e, i) {
        if (!this.listens(t, i)) return this;
        const s = Ti({}, null != e ? e : {}, {
            type: t,
            target: this,
            sourceTarget: e && e.sourceTarget || this
        });
        if (this._events) {
            const e = this._events[t];
            if (e) {
                this._firingCount++;
                for (let i = 0, n = e.length; i < n; i++) {
                    const n = e[i],
                        r = n.fn;
                    n.once && this._off(t, r, n.ctx), r.call(n.ctx || this, s)
                }
                this._firingCount--
            }
        }
        return i && this._propagateEvent(s), this
    }
    listens(t, e, i, s) {
        let n;
        "function" != typeof e ? (s = !!e, n = void 0, i = void 0) : n = e;
        const r = this._events && this._events[t];
        if (r && r.length && 0 != this._listens(t, n, i)) return 1;
        if (s)
            for (const n in this._eventParents)
                if (this._eventParents[n].listens(t, e, i, s)) return 1;
        return 0
    }
    _listens(t, e, i) {
        const s = this._events[t] || [];
        if (!e) return !!s.length;
        i === this && (i = void 0);
        for (let t = 0, n = s.length; t < n; t++)
            if (s[t].fn === e && s[t].ctx === i) return 1;
        return 0
    }
    _listenerIndex(t, e, i) {
        const s = this._events[t] || [];
        i === this && (i = void 0);
        for (let t = 0, n = s.length; t < n; t++)
            if (s[t].fn === e && s[t].ctx === i) return t;
        return -1
    }
    once(t, e, i) {
        if ("object" == typeof t)
            for (const i in t) Object.prototype.hasOwnProperty.call(t, i) && void 0 !== t[i] && this._on(i, t[i], e, 1);
        else {
            const n = s(t);
            for (let t = 0, s = n.length; t < s; t++) this._on(n[t], e, i, 1)
        }
        return this
    }
    addEventParent(t) {
        return this._eventParents = this._eventParents || {}, this._eventParents[r(t)] = t, this
    }
    removeEventParent(t) {
        return this._eventParents && delete this._eventParents[r(t)], this
    }
    _propagateEvent(t) {
        for (const e in this._eventParents) Object.prototype.hasOwnProperty.call(this._eventParents, e) && this._eventParents[e].fire(t.type, Ti({
            layer: t.target,
            propagatedFrom: t.target
        }, t), 1)
    }
}
class Si extends Ci {
    get map() {
        return this._map
    }
    set map(t) {
        this._map = t
    }
    get leafletMap() {
        var t;
        return null === (t = this._map) || void 0 === t ? void 0 : t.leafletMap
    }
    constructor(t) {
        super(), this._popup = null, this._tooltip = null, this._tooltipHandlersAdded = 0, this._moveEndOpensTooltip = 0, this.options = Object.assign(Object.assign({}, Si.defaultOptions), t)
    }
    addTo(t) {
        return t.addLayer(this), this
    }
    remove() {
        if (!this._map) throw new a;
        return this.removeFrom(this._map)
    }
    removeFrom(t) {
        return t && t.removeLayer(this), this
    }
    getPane(t) {
        var e;
        return this._map && null !== (null === (e = this.options) || void 0 === e ? void 0 : e.pane) ? this._map.getPane(t ? this.options[t] || t : this.options.pane) : null
    }
    addInteractiveTarget(t) {
        if (!this._map) throw new a;
        return this._map instanceof Si ? this._map.addInteractiveTarget(t) : this._map.interactiveTargets[r(t)] = this, this
    }
    removeInteractiveTarget(t) {
        if (!this._map) throw new a;
        return this._map instanceof Si ? this._map.removeInteractiveTarget(t) : delete this._map.interactiveTargets[r(t)], this
    }
    getAttribution() {
        return this.options.attribution
    }
    _layerAdd(t) {
        const e = t.target;
        if (e.hasLayer(this)) {
            if (this._map = e, this._tooltip && this._initTooltipInteractions(), this.getEvents) {
                const t = this.getEvents();
                e.on(t, this), this.once("remove", function() {
                    e.off(t, this)
                }, this)
            }
            this.onAdd && this.onAdd(e), this.fire("add"), e.fire("layeradd", {
                layer: this
            })
        }
    }
    _initOverlay(t, e, i, s) {
        if (i instanceof t) return Mi(i, s), i._source = this, i;
        {
            const n = e && !s ? e : new t(s, this);
            return n.setContent(i), n
        }
    }
    unbindPopup() {
        return this._popup && (this.off({
            click: this._openPopup,
            keypress: this._onKeyPress,
            remove: this.closePopup,
            move: this._movePopup
        }), this._popupHandlersAdded = 0, this._popup = null), this
    }
    bindPopup(t, e) {
        return this._popup = this._initOverlay(Si.Popup, this._popup, t, e), this._popupHandlersAdded || (this.on({
            click: this._openPopup,
            keypress: this._onKeyPress,
            remove: this.closePopup,
            move: this._movePopup
        }), this._popupHandlersAdded = 1), this
    }
    openPopup(t) {
        return this._popup && (this._popup._source = this, this._popup._prepareOpen(t || this._latlng) && this._popup.openOn(this.leafletMap)), this
    }
    closePopup() {
        return this._popup && this._popup.close(), this
    }
    togglePopup() {
        return this._popup && this._popup.toggle(this), this
    }
    isPopupOpen() {
        return this._popup ? this._popup.isOpen() : 0
    }
    setPopupContent(t) {
        return this._popup && this._popup.setContent(t), this
    }
    getPopup() {
        return this._popup
    }
    _openPopup(t) {
        if (!this._popup || !this._map) return;
        di.stop(t);
        const e = t.layer || t.target;
        this._popup._source !== e || "type" in e && "Path" === e.type ? (this._popup._source = e, this.openPopup(t.latlng)) : this._map.hasLayer(this._popup) ? this.closePopup() : this.openPopup(t.latlng)
    }
    _movePopup(t) {
        this._popup && this._popup.setLatLng(t.latlng)
    }
    _onKeyPress(t) {
        "Enter" === t.originalEvent.code && this._openPopup(t)
    }
    bindTooltip(t, e) {
        return this._tooltip && this.isTooltipOpen() && this.unbindTooltip(), this._tooltip = this._initOverlay(Si.Tooltip, this._tooltip, t, e), this._initTooltipInteractions(), this._tooltip.options.permanent && this._map && this._map.hasLayer(this) && this.openTooltip(), this
    }
    unbindTooltip() {
        return this._tooltip && (this._initTooltipInteractions(1), this.closeTooltip(), this._tooltip = null), this
    }
    _initTooltipInteractions(t) {
        if (!this._tooltip) return;
        if (!t && this._tooltipHandlersAdded) return;
        if (!this._map) return;
        const e = {
            remove: this.closeTooltip,
            move: this._moveTooltip
        };
        this._tooltip.options.permanent ? e.add = this._openTooltip : (e.mouseover = this._openTooltip, e.mouseout = this.closeTooltip, e.click = this._openTooltip, this.leafletMap ? this._addTooltipFocusListeners(this) : e.add = () => {
            this._addTooltipFocusListeners(this)
        }), this._tooltip.options.sticky && (e.mousemove = this._moveTooltip), t ? this.off(e) : this.on(e), this._tooltipHandlersAdded = !t
    }
    openTooltip(t) {
        return this._tooltip && (this.addEventParent && this.removeEventParent || (this._tooltip._source = this), this._tooltip._prepareOpen(t) && (this._tooltip.openOn(this._map), this._setAriaDescribedByTooltipLayer(this))), this
    }
    closeTooltip() {
        return this._tooltip && this._tooltip.close(), this
    }
    toggleTooltip() {
        return this._tooltip && this._tooltip.toggle(this), this
    }
    isTooltipOpen() {
        return !!this._tooltip && this._tooltip.isOpen()
    }
    setTooltipContent(t) {
        return this._tooltip && this._tooltip.setContent(t), this
    }
    getTooltip() {
        return this._tooltip
    }
    _addTooltipFocusListeners(t) {
        throw Error("This layer type does not support tooltips.")
    }
    _setAriaDescribedByOnLayer(t) {
        t._setAriaDescribedByTooltipLayer(this)
    }
    _setAriaDescribedByTooltipLayer(t) {
        throw Error("This layer type does not support tooltips.")
    }
    _openTooltip(t) {
        if (!this._map || !this.leafletMap) throw new a;
        if (!this._tooltip) return;
        if (this.leafletMap.draggingMoving) return void("add" !== t.type || this._moveEndOpensTooltip || (this._moveEndOpensTooltip = 1, this.leafletMap.once("moveend", () => {
            this._moveEndOpensTooltip = 0, this._openTooltip(t)
        })));
        const e = t.layer || t.target;
        e instanceof Si && (this._tooltip._source = e), this.openTooltip(this._tooltip.options.sticky ? t.latlng : void 0)
    }
    _moveTooltip(t) {
        if (!this._map || !this.leafletMap) throw new a;
        if (!this._tooltip) return;
        let e, i, s = t.latlng;
        this._tooltip.options.sticky && t.originalEvent && (e = this.leafletMap.mouseEventToContainerPoint(t.originalEvent), i = this.leafletMap.containerPointToLayerPoint(e), s = this.leafletMap.layerPointToLatLng(i)), s && this._tooltip.setLatLng(s)
    }
    toGeoJSON(t) {
        return {
            type: "FeatureCollection",
            features: []
        }
    }
}
Si.defaultOptions = {
    pane: "overlayPane",
    attribution: null
};
class Ri {
    constructor(t, e) {
        if (!t) return;
        const i = Ai(t) && e && Ai(e) ? [t, e] : "min" in t ? [t.min, t.max] : t;
        for (let t = 0, e = i.length; t < e; t++) this.extend(i[t])
    }
    extend(t) {
        if (!t) return this;
        let e, i;
        if (Ai(t)) e = i = l(t);
        else {
            const s = Ii(t);
            if (e = s.min, i = s.max, !e || !i) return this
        }
        return this.min || this.max ? (this.min.x = Math.min(e.x, this.min.x), this.max.x = Math.max(i.x, this.max.x), this.min.y = Math.min(e.y, this.min.y), this.max.y = Math.max(i.y, this.max.y)) : (this.min = e.clone(), this.max = i.clone()), this
    }
    getCenter(t) {
        return new h((this.min.x + this.max.x) / 2, (this.min.y + this.max.y) / 2, t)
    }
    getBottomLeft() {
        return new h(this.min.x, this.max.y)
    }
    getTopRight() {
        return new h(this.max.x, this.min.y)
    }
    getTopLeft() {
        return this.min
    }
    getBottomRight() {
        return this.max
    }
    getSize() {
        return this.max.subtract(this.min)
    }
    contains(t) {
        let e, i;
        if (Ai(t)) e = i = l(t);
        else {
            const s = Ii(t);
            e = s.min, i = s.max
        }
        return e.x >= this.min.x && i.x <= this.max.x && e.y >= this.min.y && i.y <= this.max.y
    }
    intersects(t) {
        const e = Ii(t),
            i = this.min,
            s = this.max,
            n = e.min,
            r = e.max;
        return r.x >= i.x && n.x <= s.x && r.y >= i.y && n.y <= s.y
    }
    overlaps(t) {
        const e = Ii(t),
            i = this.min,
            s = this.max,
            n = e.min,
            r = e.max;
        return r.x > i.x && n.x < s.x && r.y > i.y && n.y < s.y
    }
    isValid() {
        return !(!this.min || !this.max)
    }
    pad(t) {
        const e = this.min,
            i = this.max,
            s = Math.abs(e.x - i.x) * t,
            n = Math.abs(e.y - i.y) * t;
        return Ii(l(e.x - s, e.y - n), l(i.x + s, i.y + n))
    }
    equals(t) {
        if (!t) return 0;
        const e = Ii(t);
        return this.min.equals(e.getTopLeft()) && this.max.equals(e.getBottomRight())
    }
}

function Ii(t, e) {
    return !t || t instanceof Ri ? t : new Ri(t, e)
}

function Ai(t) {
    return t instanceof h || "number" == typeof t[0] || "x" in t
}
var zi, Oi;
class ki extends At {
    constructor(t, e) {
        super({
            id: t,
            type: "canvas"
        }), this.type = "canvas", this.paint = {}, this.canvasLayer = e
    }
}
class Di extends(Oi = Si) {
    get lastRenderedArea() {
        return this._lastRenderedArea
    }
    get lastRenderedZoom() {
        return this._lastRenderedZoom
    }
    get texture() {
        return this._texture
    }
    get opacity() {
        var t;
        return null !== (t = this._layerObject.paint["raster-opacity"]) && void 0 !== t ? t : 1
    }
    set opacity(t) {
        this._layerObject.paint["raster-opacity"] = t
    }
    constructor(t) {
        const e = Object.assign(Object.assign({}, zi.defaultOptions), t);
        e.pane && (console.error("LeafletGL canvas layers do not support the 'pane' option, since they are drawn using WebGL."), e.pane = null), super(e), this._framePending = 0, this._textureRefreshAbort = null, this._onResize = () => {
            this._resize()
        }, this._onMapRender = async () => {
            var t, e;
            if (this._framePending) {
                this._framePending = 0, this._textureRefreshAbort && this._textureRefreshAbort.abort(), this._textureRefreshAbort = new AbortController;
                const i = await this._refreshCanvasTexture(this._textureRefreshAbort.signal);
                this._textureRefreshAbort = null, i && (null === (e = null === (t = this.map) || void 0 === t ? void 0 : t.maplibreMap) || void 0 === e || e.triggerRepaint())
            }
        }, this._onMoveEnd = () => {
            this._redraw()
        }, this._canvas = document.createElement("canvas"), this._init()
    }
    getPixelRatio() {
        if (!this.leafletMap) throw new a;
        return this.options.forceNativePixelRatio ? this.leafletMap.webGLPixelRatio : this.leafletMap.canvasPixelRatio
    }
    onAdd(t) {
        var e;
        this._setEvents(1), this._resize();
        const i = this._getLayerId();
        return this._layerObject = new ki(i, this), t.maplibreMap.addLayerToBucket(this._layerObject, null !== (e = this.options.bucketId) && void 0 !== e ? e : void 0), this
    }
    onRemove(t) {
        return this._setEvents(0), this.leafletMap.maplibreMap.removeLayer(this._getLayerId()), this
    }
    _init() {}
    _getLayerId() {
        return "_leaflet_canvas_layer_" + r(this)
    }
    _setEvents(t = 1) {
        const e = this.leafletMap.maplibreMap,
            i = t ? e.on.bind(e) : e.off.bind(e);
        i("resize", this._onResize), i("moveend", this._onMoveEnd), i("prerender", this._onMapRender)
    }
    _getGLContext() {
        if (!this.leafletMap) throw new a;
        return this.leafletMap.maplibreMap.painter.context.gl
    }
    _redraw() {
        var t;
        this._framePending = 1, (null === (t = this.map) || void 0 === t ? void 0 : t.maplibreMap) && this.map.maplibreMap.triggerRepaint()
    }
    async _refreshCanvasTexture(t) {
        var e;
        if (!this.leafletMap || !(null === (e = this.map) || void 0 === e ? void 0 : e.maplibreMap)) throw new a;
        const i = this.leafletMap.getZoom();
        if (void 0 !== this.options.minZoom && i < this.options.minZoom || void 0 !== this.options.maxZoom && i >= this.options.maxZoom + 1) return 0;
        const s = Math.round(i);
        if (await this._draw(s, t), t.aborted) return 0;
        const n = this.map.maplibreMap.transform;
        this.lastTopLeftPixelX = void 0, this.lastTopLeftOffset = void 0, this._lastRenderedZoom = i, this._lastRenderedArea = new Ri, this._lastRenderedArea.extend(n.screenPointToMercatorCoordinate(new h(0, 0))), this._lastRenderedArea.extend(n.screenPointToMercatorCoordinate(new h(this.map.maplibreMap.transform.width, this.map.maplibreMap.transform.height)));
        const r = this._getGLContext();
        if (r.bindTexture(r.TEXTURE_2D, this._texture), ze(r)) r.texSubImage2D(r.TEXTURE_2D, 0, 0, 0, this._canvas.width, this._canvas.height, r.RGBA, r.UNSIGNED_BYTE, this._canvas);
        else {
            const t = this._canvas.getContext("2d");
            if (!t) throw Error("Failed to create 2D canvas context for CanvasLayer.");
            const e = t.getImageData(0, 0, this._canvas.width, this._canvas.height);
            r.texSubImage2D(r.TEXTURE_2D, 0, 0, 0, this._canvas.width, this._canvas.height, r.RGBA, r.UNSIGNED_BYTE, e.data)
        }
        return r.bindTexture(r.TEXTURE_2D, null), 1
    }
    _resize() {
        var t, e;
        const i = null === (e = null === (t = this.leafletMap) || void 0 === t ? void 0 : t.maplibreMap) || void 0 === e ? void 0 : e.transform;
        if (!i) return;
        const s = this.getPixelRatio();
        this._canvas.width = i.width * s | 0, this._canvas.height = i.height * s | 0;
        const n = this._getGLContext();
        this._texture && n.deleteTexture(this._texture);
        const r = n.createTexture();
        if (!r) throw Error("Failed to create WebGL texture.");
        this._texture = r, n.bindTexture(n.TEXTURE_2D, this._texture), n.texImage2D(n.TEXTURE_2D, 0, n.RGBA, this._canvas.width, this._canvas.height, 0, n.RGBA, n.UNSIGNED_BYTE, null), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_MIN_FILTER, n.LINEAR), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_MAG_FILTER, n.LINEAR), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_WRAP_S, n.CLAMP_TO_EDGE), n.texParameteri(n.TEXTURE_2D, n.TEXTURE_WRAP_T, n.CLAMP_TO_EDGE), n.bindTexture(n.TEXTURE_2D, null), this._redraw()
    }
}
zi = Di, Di.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Oi, "defaultOptions", zi)), {
    pane: null,
    bucketId: null,
    forceNativePixelRatio: 1,
    minZoom: 0,
    maxZoom: 18
});
const Bi = (t, e) => {},
    Fi = {
        debug: (t, e) => ({
            u_color: new Pe(t, e.u_color),
            u_overlay: new be(t, e.u_overlay),
            u_overlay_scale: new xe(t, e.u_overlay_scale)
        }),
        depth: Bi,
        clippingMask: Bi,
        raster: (t, e) => ({
            u_tl_parent: new we(t, e.u_tl_parent),
            u_scale_parent: new xe(t, e.u_scale_parent),
            u_buffer_scale: new xe(t, e.u_buffer_scale),
            u_fade_t: new xe(t, e.u_fade_t),
            u_opacity: new xe(t, e.u_opacity),
            u_image0: new be(t, e.u_image0),
            u_image1: new be(t, e.u_image1),
            u_brightness_low: new xe(t, e.u_brightness_low),
            u_brightness_high: new xe(t, e.u_brightness_high),
            u_saturation_factor: new xe(t, e.u_saturation_factor),
            u_contrast_factor: new xe(t, e.u_contrast_factor),
            u_spin_weights: new Te(t, e.u_spin_weights),
            u_coords_top: new Me(t, e.u_coords_top),
            u_coords_bottom: new Me(t, e.u_coords_bottom)
        }),
        background: (t, e) => ({
            u_opacity: new xe(t, e.u_opacity),
            u_color: new Pe(t, e.u_color)
        }),
        canvas: (t, e) => ({
            u_tex: new be(t, e.u_image0),
            u_opacity: new xe(t, e.u_opacity)
        })
    },
    Zi = {
        prelude: Ni("#ifdef GL_ES\nprecision mediump float;\n#else\n#if !defined(lowp)\n#define lowp\n#endif\n#if !defined(mediump)\n#define mediump\n#endif\n#if !defined(highp)\n#define highp\n#endif\n#endif\n", "#ifdef GL_ES\nprecision highp float;\n#else\n#if !defined(lowp)\n#define lowp\n#endif\n#if !defined(mediump)\n#define mediump\n#endif\n#if !defined(highp)\n#define highp\n#endif\n#endif\nvec2 unpack_float(const float packedValue) {int packedIntValue=int(packedValue);int v0=packedIntValue/256;return vec2(v0,packedIntValue-v0*256);}vec2 unpack_opacity(const float packedOpacity) {int intOpacity=int(packedOpacity)/2;return vec2(float(intOpacity)/127.0,mod(packedOpacity,2.0));}vec4 decode_color(const vec2 encodedColor) {return vec4(unpack_float(encodedColor[0])/255.0,unpack_float(encodedColor[1])/255.0\n);}float unpack_mix_vec2(const vec2 packedValue,const float t) {return mix(packedValue[0],packedValue[1],t);}vec4 unpack_mix_color(const vec4 packedColors,const float t) {vec4 minColor=decode_color(vec2(packedColors[0],packedColors[1]));vec4 maxColor=decode_color(vec2(packedColors[2],packedColors[3]));return mix(minColor,maxColor,t);}vec2 get_pattern_pos(const vec2 pixel_coord_upper,const vec2 pixel_coord_lower,const vec2 pattern_size,const float tile_units_to_pixels,const vec2 pos) {vec2 offset=mod(mod(mod(pixel_coord_upper,pattern_size)*256.0,pattern_size)*256.0+pixel_coord_lower,pattern_size);return (tile_units_to_pixels*pos+offset)/pattern_size;}mat3 rotationMatrixFromAxisAngle(vec3 u,float angle) {float c=cos(angle);float s=sin(angle);float c2=1.0-c;return mat3(u.x*u.x*c2+      c,u.x*u.y*c2-u.z*s,u.x*u.z*c2+u.y*s,u.y*u.x*c2+u.z*s,u.y*u.y*c2+    c,u.y*u.z*c2-u.x*s,u.z*u.x*c2-u.y*s,u.z*u.y*c2+u.x*s,u.z*u.z*c2+    c\n);}\n#ifdef TERRAIN3D\nuniform sampler2D u_terrain;uniform float u_terrain_dim;uniform mat4 u_terrain_matrix;uniform vec4 u_terrain_unpack;uniform float u_terrain_exaggeration;uniform highp sampler2D u_depth;\n#endif\nconst highp vec4 bitSh=vec4(256.*256.*256.,256.*256.,256.,1.);const highp vec4 bitShifts=vec4(1.)/bitSh;highp float unpack(highp vec4 color) {return dot(color,bitShifts);}highp float depthOpacity(vec3 frag) {\n#ifdef TERRAIN3D\nhighp float d=unpack(texture2D(u_depth,frag.xy*0.5+0.5))+0.0001-frag.z;return 1.0-max(0.0,min(1.0,-d*500.0));\n#else\nreturn 1.0;\n#endif\n}float calculate_visibility(vec4 pos) {\n#ifdef TERRAIN3D\nvec3 frag=pos.xyz/pos.w;highp float d=depthOpacity(frag);if (d > 0.95) return 1.0;return (d+depthOpacity(frag+vec3(0.0,0.01,0.0)))/2.0;\n#else\nreturn 1.0;\n#endif\n}float ele(vec2 pos) {\n#ifdef TERRAIN3D\nvec4 rgb=(texture2D(u_terrain,pos)*255.0)*u_terrain_unpack;return rgb.r+rgb.g+rgb.b-u_terrain_unpack.a;\n#else\nreturn 0.0;\n#endif\n}float get_elevation(vec2 pos) {\n#ifdef TERRAIN3D\nvec2 coord=(u_terrain_matrix*vec4(pos,0.0,1.0)).xy*u_terrain_dim+1.0;vec2 f=fract(coord);vec2 c=(floor(coord)+0.5)/(u_terrain_dim+2.0);float d=1.0/(u_terrain_dim+2.0);float tl=ele(c);float tr=ele(c+vec2(d,0.0));float bl=ele(c+vec2(0.0,d));float br=ele(c+vec2(d,d));float elevation=mix(mix(tl,tr,f.x),mix(bl,br,f.x),f.y);return elevation*u_terrain_exaggeration;\n#else\nreturn 0.0;\n#endif\n}const float PI=3.141592653589793;uniform mat4 u_projection_matrix;"),
        projectionMercator: Ni("", "float projectLineThickness(float tileY) {return 1.0;}float projectCircleRadius(float tileY) {return 1.0;}vec4 projectTile(vec2 p) {vec4 result=u_projection_matrix*vec4(p,0.0,1.0);if (p.y <-32767.5 || p.y > 32766.5) {result.z=-10000000.0;}return result;}vec4 projectTileWithElevation(vec2 posInTile,float elevation) {return u_projection_matrix*vec4(posInTile,elevation,1.0);}vec4 projectTileFor3D(vec2 posInTile,float elevation) {return projectTileWithElevation(posInTile,elevation);}"),
        background: Ni("uniform vec4 u_color;uniform float u_opacity;void main() {gl_FragColor=u_color*u_opacity;\n#ifdef OVERDRAW_INSPECTOR\ngl_FragColor=vec4(1.0);\n#endif\n}", "attribute vec2 a_pos;void main() {gl_Position=projectTile(a_pos);}"),
        backgroundPattern: Ni("uniform vec2 u_pattern_tl_a;uniform vec2 u_pattern_br_a;uniform vec2 u_pattern_tl_b;uniform vec2 u_pattern_br_b;uniform vec2 u_texsize;uniform float u_mix;uniform float u_opacity;uniform sampler2D u_image;varying vec2 v_pos_a;varying vec2 v_pos_b;void main() {vec2 imagecoord=mod(v_pos_a,1.0);vec2 pos=mix(u_pattern_tl_a/u_texsize,u_pattern_br_a/u_texsize,imagecoord);vec4 color1=texture2D(u_image,pos);vec2 imagecoord_b=mod(v_pos_b,1.0);vec2 pos2=mix(u_pattern_tl_b/u_texsize,u_pattern_br_b/u_texsize,imagecoord_b);vec4 color2=texture2D(u_image,pos2);gl_FragColor=mix(color1,color2,u_mix)*u_opacity;\n#ifdef OVERDRAW_INSPECTOR\ngl_FragColor=vec4(1.0);\n#endif\n}", "uniform vec2 u_pattern_size_a;uniform vec2 u_pattern_size_b;uniform vec2 u_pixel_coord_upper;uniform vec2 u_pixel_coord_lower;uniform float u_scale_a;uniform float u_scale_b;uniform float u_tile_units_to_pixels;attribute vec2 a_pos;varying vec2 v_pos_a;varying vec2 v_pos_b;void main() {gl_Position=projectTile(a_pos);v_pos_a=get_pattern_pos(u_pixel_coord_upper,u_pixel_coord_lower,u_scale_a*u_pattern_size_a,u_tile_units_to_pixels,a_pos\n);v_pos_b=get_pattern_pos(u_pixel_coord_upper,u_pixel_coord_lower,u_scale_b*u_pattern_size_b,u_tile_units_to_pixels,a_pos\n);}"),
        canvas: Ni("uniform sampler2D u_tex;uniform float u_opacity;varying vec2 v_uv;void main() {if (v_uv.x < 0.0 || v_uv.y < 0.0 || v_uv.x > 1.0 || v_uv.y > 1.0) {discard;}vec4 color=texture2D(u_tex,v_uv);if (color.a < 0.5/255.0) {discard;}color.a*=u_opacity;gl_FragColor=vec4(color.rgb*color.a,color.a);}", "attribute vec2 a_pos;varying vec2 v_uv;void main() {v_uv=a_pos;gl_Position=u_projection_matrix*vec4(a_pos,0.0,1.0);}"),
        clippingMask: Ni(ce, "attribute vec2 a_pos;void main() {gl_Position=projectTile(a_pos);}"),
        debug: Ni("uniform highp vec4 u_color;uniform sampler2D u_overlay;varying vec2 v_uv;void main() {vec4 overlay_color=texture2D(u_overlay,v_uv);gl_FragColor=mix(u_color,overlay_color,overlay_color.a);}", "attribute vec2 a_pos;varying vec2 v_uv;uniform float u_overlay_scale;void main() {v_uv=a_pos/8192.0;gl_Position=projectTileWithElevation(a_pos*u_overlay_scale,get_elevation(a_pos));}"),
        depth: Ni(ce, "attribute vec2 a_pos;void main() {\n#ifdef GLOBE\ngl_Position=projectTileFor3D(a_pos,0.0);\n#else\ngl_Position=u_projection_matrix*vec4(a_pos,0.0,1.0);\n#endif\n}"),
        raster: Ni(ue, de)
    };

function Ni(t, e) {
    const i = /#pragma mapbox: ([\w]+) ([\w]+) ([\w]+) ([\w]+)/g,
        s = e.match(/attribute ([\w]+) ([\w]+)/g),
        n = t.match(/uniform ([\w]+) ([\w]+)([\s]*)([\w]*)/g),
        r = e.match(/uniform ([\w]+) ([\w]+)([\s]*)([\w]*)/g),
        o = r ? r.concat(n) : n,
        a = {};
    return {
        fragmentSource: t = t.replace(i, (t, e, i, s, n) => (a[n] = 1, "define" === e ? `\n#ifndef HAS_UNIFORM_u_${n}\nvarying ${i} ${s} ${n};\n#else\nuniform ${i} ${s} u_${n};\n#endif\n` : `\n#ifdef HAS_UNIFORM_u_${n}\n    ${i} ${s} ${n} = u_${n};\n#endif\n`)),
        vertexSource: e = e.replace(i, (t, e, i, s, n) => {
            const r = "float" === s ? "vec2" : "vec4",
                o = n.match(/color/) ? "color" : r;
            return a[n] ? "define" === e ? `\n#ifndef HAS_UNIFORM_u_${n}\nuniform lowp float u_${n}_t;\nattribute ${i} ${r} a_${n};\nvarying ${i} ${s} ${n};\n#else\nuniform ${i} ${s} u_${n};\n#endif\n` : "vec4" === o ? `\n#ifndef HAS_UNIFORM_u_${n}\n    ${n} = a_${n};\n#else\n    ${i} ${s} ${n} = u_${n};\n#endif\n` : `\n#ifndef HAS_UNIFORM_u_${n}\n    ${n} = unpack_mix_${o}(a_${n}, u_${n}_t);\n#else\n    ${i} ${s} ${n} = u_${n};\n#endif\n` : "define" === e ? `\n#ifndef HAS_UNIFORM_u_${n}\nuniform lowp float u_${n}_t;\nattribute ${i} ${r} a_${n};\n#else\nuniform ${i} ${s} u_${n};\n#endif\n` : "vec4" === o ? `\n#ifndef HAS_UNIFORM_u_${n}\n    ${i} ${s} ${n} = a_${n};\n#else\n    ${i} ${s} ${n} = u_${n};\n#endif\n` : `\n#ifndef HAS_UNIFORM_u_${n}\n    ${i} ${s} ${n} = unpack_mix_${o}(a_${n}, u_${n}_t);\n#else\n    ${i} ${s} ${n} = u_${n};\n#endif\n`
        }),
        staticAttributes: s,
        staticUniforms: o
    }
}

function ji(t, e, i) {
    return (1 - i) * t + i * e
}

function Ui(t) {
    return [...t]
}

function Gi(t, e) {
    if (Array.isArray(t)) {
        if (!Array.isArray(e) || t.length !== e.length) return 0;
        for (let i = 0; i < t.length; i++)
            if (!Gi(t[i], e[i])) return 0;
        return 1
    }
    if ("object" == typeof t && null !== t && null !== e) {
        if ("object" != typeof e) return 0;
        if (Object.keys(t).length !== Object.keys(e).length) return 0;
        for (const i in t)
            if (!Gi(t[i], e[i])) return 0;
        return 1
    }
    return t === e
}

function qi(t, e) {
    t.push(e)
}

function $i(t, e, i) {
    qi(i, {
        command: "addSource",
        args: [t, e[t]]
    })
}

function Wi(t, e, i) {
    qi(e, {
        command: "removeSource",
        args: [t]
    }), i[t] = 1
}

function Hi(t, e, i, s) {
    Wi(t, i, s), $i(t, e, i)
}

function Vi(t, e, i, s, n, r) {
    t = t || {}, e = e || {};
    for (const o in t) Object.prototype.hasOwnProperty.call(t, o) && (Gi(t[o], e[o]) || i.push({
        command: r,
        args: [s, o, e[o], n]
    }));
    for (const o in e) Object.prototype.hasOwnProperty.call(e, o) && !Object.prototype.hasOwnProperty.call(t, o) && (Gi(t[o], e[o]) || i.push({
        command: r,
        args: [s, o, e[o], n]
    }))
}

function Xi(t) {
    return t.id
}

function Ki(t, e) {
    return t[e.id] = e, t
}
class Yi {
    constructor(t, e, i) {
        this.vertexBuffer = t, this.indexBuffer = e, this.segments = i
    }
    destroy() {
        this.vertexBuffer.destroy(), this.indexBuffer.destroy(), this.segments.destroy(), this.vertexBuffer = null, this.indexBuffer = null, this.segments = null
    }
}
const Ji = {
    Int8: Int8Array,
    Uint8: Uint8Array,
    Int16: Int16Array,
    Uint16: Uint16Array,
    Int32: Int32Array,
    Uint32: Uint32Array,
    Float32: Float32Array
};
class Qi {
    constructor() {
        this.isTransferred = 0, this.capacity = -1, this.resize(0)
    }
    static serialize(t, e) {
        return t._trim(), e && (t.isTransferred = 1, e.push(t.arrayBuffer)), {
            length: t.length,
            arrayBuffer: t.arrayBuffer
        }
    }
    static deserialize(t) {
        const e = Object.create(this.prototype);
        return e.arrayBuffer = t.arrayBuffer, e.length = t.length, e.capacity = t.arrayBuffer.byteLength / e.bytesPerElement, e._refreshViews(), e
    }
    _trim() {
        this.length !== this.capacity && (this.capacity = this.length, this.arrayBuffer = this.arrayBuffer.slice(0, this.length * this.bytesPerElement), this._refreshViews())
    }
    clear() {
        this.length = 0
    }
    resize(t) {
        this.reserve(t), this.length = t
    }
    reserve(t) {
        if (t > this.capacity) {
            this.capacity = Math.max(t, Math.floor(5 * this.capacity), 128), this.arrayBuffer = new ArrayBuffer(this.capacity * this.bytesPerElement);
            const e = this.uint8;
            this._refreshViews(), e && this.uint8.set(e)
        }
    }
    _refreshViews() {
        throw Error("_refreshViews() must be implemented by each concrete StructArray layout")
    }
}

function ts(t, e) {
    return Math.ceil(t / e) * e
}
class es extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.int16 = new Int16Array(this.arrayBuffer)
    }
    emplaceBack(t, e) {
        const i = this.length;
        return this.resize(i + 1), this.emplace(i, t, e)
    }
    emplace(t, e, i) {
        const s = 2 * t;
        return this.int16[s + 0] = e, this.int16[s + 1] = i, t
    }
}
es.prototype.bytesPerElement = 4, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.int16 = new Int16Array(this.arrayBuffer)
    }
    emplaceBack(t, e, i) {
        const s = this.length;
        return this.resize(s + 1), this.emplace(s, t, e, i)
    }
    emplace(t, e, i, s) {
        const n = 3 * t;
        return this.int16[n + 0] = e, this.int16[n + 1] = i, this.int16[n + 2] = s, t
    }
}.prototype.bytesPerElement = 6, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.int16 = new Int16Array(this.arrayBuffer)
    }
    emplaceBack(t, e, i, s) {
        const n = this.length;
        return this.resize(n + 1), this.emplace(n, t, e, i, s)
    }
    emplace(t, e, i, s, n) {
        const r = 4 * t;
        return this.int16[r + 0] = e, this.int16[r + 1] = i, this.int16[r + 2] = s, this.int16[r + 3] = n, t
    }
}.prototype.bytesPerElement = 8, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.uint32 = new Uint32Array(this.arrayBuffer), this.uint16 = new Uint16Array(this.arrayBuffer)
    }
    emplaceBack(t, e, i) {
        const s = this.length;
        return this.resize(s + 1), this.emplace(s, t, e, i)
    }
    emplace(t, e, i, s) {
        const n = 4 * t;
        return this.uint32[2 * t + 0] = e, this.uint16[n + 2] = i, this.uint16[n + 3] = s, t
    }
}.prototype.bytesPerElement = 8;
class is extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.uint16 = new Uint16Array(this.arrayBuffer)
    }
    emplaceBack(t, e, i) {
        const s = this.length;
        return this.resize(s + 1), this.emplace(s, t, e, i)
    }
    emplace(t, e, i, s) {
        const n = 3 * t;
        return this.uint16[n + 0] = e, this.uint16[n + 1] = i, this.uint16[n + 2] = s, t
    }
}
is.prototype.bytesPerElement = 6, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.uint16 = new Uint16Array(this.arrayBuffer)
    }
    emplaceBack(t, e) {
        const i = this.length;
        return this.resize(i + 1), this.emplace(i, t, e)
    }
    emplace(t, e, i) {
        const s = 2 * t;
        return this.uint16[s + 0] = e, this.uint16[s + 1] = i, t
    }
}.prototype.bytesPerElement = 4;
class ss extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.uint16 = new Uint16Array(this.arrayBuffer)
    }
    emplaceBack(t) {
        const e = this.length;
        return this.resize(e + 1), this.emplace(e, t)
    }
    emplace(t, e) {
        return this.uint16[1 * t + 0] = e, t
    }
}
ss.prototype.bytesPerElement = 2, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.float32 = new Float32Array(this.arrayBuffer)
    }
    emplaceBack(t) {
        const e = this.length;
        return this.resize(e + 1), this.emplace(e, t)
    }
    emplace(t, e) {
        return this.float32[1 * t + 0] = e, t
    }
}.prototype.bytesPerElement = 4, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.float32 = new Float32Array(this.arrayBuffer)
    }
    emplaceBack(t, e) {
        const i = this.length;
        return this.resize(i + 1), this.emplace(i, t, e)
    }
    emplace(t, e, i) {
        const s = 2 * t;
        return this.float32[s + 0] = e, this.float32[s + 1] = i, t
    }
}.prototype.bytesPerElement = 8, class extends Qi {
    _refreshViews() {
        this.uint8 = new Uint8Array(this.arrayBuffer), this.float32 = new Float32Array(this.arrayBuffer)
    }
    emplaceBack(t, e, i, s) {
        const n = this.length;
        return this.resize(n + 1), this.emplace(n, t, e, i, s)
    }
    emplace(t, e, i, s, n) {
        const r = 4 * t;
        return this.float32[r + 0] = e, this.float32[r + 1] = i, this.float32[r + 2] = s, this.float32[r + 3] = n, t
    }
}.prototype.bytesPerElement = 16;
class ns extends es {}
class rs extends is {}
class os extends ss {}
class as {
    constructor(t = []) {
        this._forceNewSegmentOnNextPrepare = 0, this.segments = t
    }
    prepareSegment(t, e, i, s) {
        const n = this.segments[this.segments.length - 1];
        return t > as.MAX_VERTEX_ARRAY_LENGTH && Q(`Max vertices per segment is ${as.MAX_VERTEX_ARRAY_LENGTH}: bucket requested ${t}. Consider using the \`fillLargeMeshArrays\` function if you require meshes with more than ${as.MAX_VERTEX_ARRAY_LENGTH} vertices.`), this._forceNewSegmentOnNextPrepare || !n || n.vertexLength + t > as.MAX_VERTEX_ARRAY_LENGTH || n.sortKey !== s ? this.createNewSegment(e, i, s) : n
    }
    createNewSegment(t, e, i) {
        const s = {
            vertexOffset: t.length,
            primitiveOffset: e.length,
            vertexLength: 0,
            primitiveLength: 0,
            vaos: {}
        };
        return void 0 !== i && (s.sortKey = i), this._forceNewSegmentOnNextPrepare = 0, this.segments.push(s), s
    }
    getOrCreateLatestSegment(t, e, i) {
        return this.prepareSegment(0, t, e, i)
    }
    forceNewSegmentOnNextPrepare() {
        this._forceNewSegmentOnNextPrepare = 1
    }
    get() {
        return this.segments
    }
    destroy() {
        for (const t of this.segments)
            for (const e in t.vaos) t.vaos[e].destroy()
    }
    static simpleSegment(t, e, i, s) {
        return new as([{
            vertexOffset: t,
            primitiveOffset: e,
            vertexLength: i,
            primitiveLength: s,
            vaos: {},
            sortKey: 0
        }])
    }
}
as.MAX_VERTEX_ARRAY_LENGTH = 65535;
var hs = function(t, e = 1) {
    let i = 0,
        s = 0;
    return {
        members: [{
            name: "a_pos",
            type: "Int16",
            components: 2
        }].map(t => {
            const n = Ji[t.type].BYTES_PER_ELEMENT,
                r = i = ts(i, Math.max(e, n)),
                o = t.components || 1;
            return s = Math.max(s, n), i += n * o, {
                name: t.name,
                type: t.type,
                components: o,
                offset: r
            }
        }),
        size: ts(i, Math.max(s, e)),
        alignment: e
    }
}();
class ls {
    constructor(t, e) {
        if (e > t) throw Error("Min granularity must not be greater than base granularity.");
        this._baseZoomGranularity = t, this._minGranularity = e
    }
    getGranularityForZoomLevel(t) {
        return Math.max(Math.floor(this._baseZoomGranularity / (1 << t)), this._minGranularity, 1)
    }
}
class cs {
    constructor(t) {
        this.fill = t.fill, this.line = t.line, this.tile = t.tile, this.stencil = t.stencil, this.circle = t.circle
    }
}
cs.noSubdivision = new cs({
    fill: new ls(0, 0),
    line: new ls(0, 0),
    tile: new ls(0, 0),
    stencil: new ls(0, 0),
    circle: 1
});
const us = "#define PROJECTION_MERCATOR",
    ds = "mercator";
class ps {
    constructor() {
        this._cachedMesh = null
    }
    get name() {
        return "mercator"
    }
    get useSubdivision() {
        return 0
    }
    get shaderVariantName() {
        return ds
    }
    get shaderDefine() {
        return us
    }
    get shaderPreludeCode() {
        return Zi.projectionMercator
    }
    get vertexShaderPreludeCode() {
        return Zi.projectionMercator.vertexSource
    }
    get subdivisionGranularity() {
        return cs.noSubdivision
    }
    get useGlobeControls() {
        return 0
    }
    destroy() {}
    isRenderingDirty() {
        return 0
    }
    updateGPUdependent(t) {}
    getMeshFromTileID(t, e, i, s, n) {
        if (this._cachedMesh) return this._cachedMesh;
        const r = new ns;
        r.emplaceBack(0, 0), r.emplaceBack(D, 0), r.emplaceBack(0, D), r.emplaceBack(D, D);
        const o = t.createVertexBuffer(r, hs.members),
            a = as.simpleSegment(0, 0, 4, 2),
            h = new rs;
        h.emplaceBack(1, 0, 2), h.emplaceBack(1, 2, 3);
        const l = t.createIndexBuffer(h);
        return this._cachedMesh = new Yi(o, l, a), this._cachedMesh
    }
}
class _s {
    constructor(t = 0, e = 0, i = 0, s = 0) {
        if (isNaN(t) || t < 0 || isNaN(e) || e < 0 || isNaN(i) || i < 0 || isNaN(s) || s < 0) throw Error("Invalid value for edge-insets, top, bottom, left and right must all be numbers");
        this.top = t, this.bottom = e, this.left = i, this.right = s
    }
    interpolate(t, e, i) {
        return null != e.top && null != t.top && (this.top = ji(t.top, e.top, i)), null != e.bottom && null != t.bottom && (this.bottom = ji(t.bottom, e.bottom, i)), null != e.left && null != t.left && (this.left = ji(t.left, e.left, i)), null != e.right && null != t.right && (this.right = ji(t.right, e.right, i)), this
    }
    getCenter(t, e) {
        const i = U((this.left + t - this.right) / 2, 0, t),
            s = U((this.top + e - this.bottom) / 2, 0, e);
        return new h(i, s)
    }
    equals(t) {
        return this.top === t.top && this.bottom === t.bottom && this.left === t.left && this.right === t.right
    }
    clone() {
        return new _s(this.top, this.bottom, this.left, this.right)
    }
    toJSON() {
        return {
            top: this.top,
            bottom: this.bottom,
            left: this.left,
            right: this.right
        }
    }
}
const ms = 85.051129;

function fs(t, e) {
    if (!t.renderWorldCopies || t.lngRange) return;
    const i = e.lng - t.center.lng;
    e.lng += i > 180 ? -360 : i < -180 ? 360 : 0
}

function gs(t) {
    return Math.pow(2, t)
}

function ys(t) {
    return Math.log(t) / Math.LN2
}

function vs(t) {
    return Math.max(0, Math.floor(t))
}
class bs {
    constructor(t, e, i, s, n, r) {
        this._callbacks = t, this._tileSize = 512, this._renderWorldCopies = void 0 === r ? 1 : !!r, this._minZoom = e || 0, this._maxZoom = i || 22, this._minPitch = null == s ? 0 : s, this._maxPitch = null == n ? 60 : n, this.setMaxBounds(), this._width = 0, this._height = 0, this._center = new Bt(0, 0), this._elevation = 0, this._zoom = 0, this._tileZoom = vs(this._zoom), this._scale = gs(this._zoom), this._bearingInRadians = 0, this._fovInRadians = .6435011087932844, this._pitchInRadians = 0, this._rollInRadians = 0, this._unmodified = 1, this._edgeInsets = new _s, this._minElevationForCurrentTile = 0
    }
    apply(t, e) {
        this._latRange = t.latRange, this._lngRange = t.lngRange, this._width = t.width, this._height = t.height, this._center = t.center, this._elevation = t.elevation, this._minElevationForCurrentTile = t.minElevationForCurrentTile, this._zoom = t.zoom, this._tileZoom = vs(this._zoom), this._scale = gs(this._zoom), this._bearingInRadians = t.bearingInRadians, this._fovInRadians = t.fovInRadians, this._pitchInRadians = t.pitchInRadians, this._rollInRadians = t.rollInRadians, this._unmodified = t.unmodified, this._edgeInsets = new _s(t.padding.top, t.padding.bottom, t.padding.left, t.padding.right), this._minZoom = t.minZoom, this._maxZoom = t.maxZoom, this._minPitch = t.minPitch, this._maxPitch = t.maxPitch, this._renderWorldCopies = t.renderWorldCopies, e && this._constrain(), this._calcMatrices()
    }
    get pixelsToClipSpaceMatrix() {
        return this._pixelsToClipSpaceMatrix
    }
    get clipSpaceToPixelsMatrix() {
        return this._clipSpaceToPixelsMatrix
    }
    get minElevationForCurrentTile() {
        return this._minElevationForCurrentTile
    }
    setMinElevationForCurrentTile(t) {
        this._minElevationForCurrentTile = t
    }
    get tileSize() {
        return this._tileSize
    }
    get tileZoom() {
        return this._tileZoom
    }
    get scale() {
        return this._scale
    }
    get width() {
        return this._width
    }
    get height() {
        return this._height
    }
    get bearingInRadians() {
        return this._bearingInRadians
    }
    get lngRange() {
        return this._lngRange
    }
    get latRange() {
        return this._latRange
    }
    get pixelsToGLUnits() {
        return this._pixelsToGLUnits
    }
    get minZoom() {
        return this._minZoom
    }
    setMinZoom(t) {
        this._minZoom !== t && (this._minZoom = t, this.setZoom(this.getConstrained(this._center, this.zoom).zoom))
    }
    get maxZoom() {
        return this._maxZoom
    }
    setMaxZoom(t) {
        this._maxZoom !== t && (this._maxZoom = t, this.setZoom(this.getConstrained(this._center, this.zoom).zoom))
    }
    get minPitch() {
        return this._minPitch
    }
    setMinPitch(t) {
        this._minPitch !== t && (this._minPitch = t, this.setPitch(Math.max(this.pitch, t)))
    }
    get maxPitch() {
        return this._maxPitch
    }
    setMaxPitch(t) {
        this._maxPitch !== t && (this._maxPitch = t, this.setPitch(Math.min(this.pitch, t)))
    }
    get renderWorldCopies() {
        return this._renderWorldCopies
    }
    setRenderWorldCopies(t) {
        void 0 === t ? t = 1 : null === t && (t = 0), this._renderWorldCopies = t
    }
    get worldSize() {
        return this._tileSize * this._scale
    }
    get centerOffset() {
        return this.centerPoint._sub(this.size._div(2))
    }
    get size() {
        return new h(this._width, this._height)
    }
    get bearing() {
        return this._bearingInRadians / Math.PI * 180
    }
    setBearing(t) {
        const e = G(t, -180, 180) * Math.PI / 180;
        this._bearingInRadians !== e && (this._unmodified = 0, this._bearingInRadians = e, this._calcMatrices(), this._rotationMatrix = function() {
            var t = new f(4);
            return f != Float32Array && (t[1] = 0, t[2] = 0), t[0] = 1, t[3] = 1, t
        }(), function(t, e, i) {
            var s = e[0],
                n = e[1],
                r = e[2],
                o = e[3],
                a = Math.sin(i),
                h = Math.cos(i);
            t[0] = s * h + r * a, t[1] = n * h + o * a, t[2] = s * -a + r * h, t[3] = n * -a + o * h
        }(this._rotationMatrix, this._rotationMatrix, -this._bearingInRadians))
    }
    get rotationMatrix() {
        return this._rotationMatrix
    }
    get pitchInRadians() {
        return this._pitchInRadians
    }
    get pitch() {
        return this._pitchInRadians / Math.PI * 180
    }
    setPitch(t) {
        const e = U(t, this.minPitch, this.maxPitch) / 180 * Math.PI;
        this._pitchInRadians !== e && (this._unmodified = 0, this._pitchInRadians = e, this._calcMatrices())
    }
    get rollInRadians() {
        return this._rollInRadians
    }
    get roll() {
        return this._rollInRadians / Math.PI * 180
    }
    setRoll(t) {
        const e = t / 180 * Math.PI;
        this._rollInRadians !== e && (this._unmodified = 0, this._rollInRadians = e, this._calcMatrices())
    }
    get fovInRadians() {
        return this._fovInRadians
    }
    get fov() {
        return this._fovInRadians / Math.PI * 180
    }
    setFov(t) {
        this._fovInRadians !== (t = Math.max(.01, Math.min(60, t))) && (this._unmodified = 0, this._fovInRadians = t / 180 * Math.PI, this._calcMatrices())
    }
    get zoom() {
        return this._zoom
    }
    setZoom(t) {
        const e = this.getConstrained(this._center, t).zoom;
        this._zoom !== e && (this._unmodified = 0, this._zoom = e, this._tileZoom = Math.max(0, Math.floor(e)), this._scale = gs(e), this._constrain(), this._calcMatrices())
    }
    get center() {
        return this._center
    }
    setCenter(t) {
        t.lat === this._center.lat && t.lng === this._center.lng || (this._unmodified = 0, this._center = t, this._constrain(), this._calcMatrices())
    }
    get elevation() {
        return this._elevation
    }
    setElevation(t) {
        t !== this._elevation && (this._elevation = t, this._constrain(), this._calcMatrices())
    }
    get padding() {
        return this._edgeInsets.toJSON()
    }
    setPadding(t) {
        this._edgeInsets.equals(t) || (this._unmodified = 0, this._edgeInsets.interpolate(this._edgeInsets, t, 1), this._calcMatrices())
    }
    get centerPoint() {
        return this._edgeInsets.getCenter(this._width, this._height)
    }
    get pixelsPerMeter() {
        return this._pixelPerMeter
    }
    get unmodified() {
        return this._unmodified
    }
    isPaddingEqual(t) {
        return this._edgeInsets.equals(t)
    }
    interpolatePadding(t, e, i) {
        this._unmodified = 0, this._edgeInsets.interpolate(t, e, i), this._constrain(), this._calcMatrices()
    }
    coveringZoomLevel(t) {
        const e = (t.roundZoom ? Math.round : Math.floor)(this.zoom + ys(this._tileSize / t.tileSize));
        return Math.max(0, e)
    }
    resize(t, e) {
        this._width = t, this._height = e, this._constrain(), this._calcMatrices()
    }
    getMaxBounds() {
        return this._latRange && 2 === this._latRange.length && this._lngRange && 2 === this._lngRange.length ? new Ft([this._lngRange[0], this._latRange[0]], [this._lngRange[1], this._latRange[1]]) : null
    }
    setMaxBounds(t) {
        t ? (this._lngRange = [t.getWest(), t.getEast()], this._latRange = [Math.max(t.getSouth(), -85.051129), Math.min(t.getNorth(), ms)], this._constrain()) : (this._lngRange = null, this._latRange = [-85.051129, ms])
    }
    getConstrained(t, e) {
        return this._callbacks.getConstrained(t, e)
    }
    getCameraQueryGeometry(t, e) {
        if (1 === e.length) return [e[0], t];
        {
            let i = t.x,
                s = t.y,
                n = t.x,
                r = t.y;
            for (const t of e) i = Math.min(i, t.x), s = Math.min(s, t.y), n = Math.max(n, t.x), r = Math.max(r, t.y);
            return [new h(i, s), new h(n, s), new h(n, r), new h(i, r), new h(i, s)]
        }
    }
    _constrain() {
        if (!this.center || !this._width || !this._height || this._constraining) return;
        this._constraining = 1;
        const t = this._unmodified,
            {
                center: e,
                zoom: i
            } = this.getConstrained(this.center, this.zoom);
        this.setCenter(e), this.setZoom(i), this._unmodified = t, this._constraining = 0
    }
    _calcMatrices() {
        if (this._width && this._height) {
            this._pixelsToGLUnits = [2 / this._width, -2 / this._height];
            let t = g(new Float64Array(16));
            x(t, t, [this._width / 2, -this._height / 2, 1]), b(t, t, [1, -1, 0]), this._clipSpaceToPixelsMatrix = t, t = g(new Float64Array(16)), x(t, t, [1, -1, 1]), b(t, t, [-1, -1, 0]), x(t, t, [2 / this._width, 2 / this._height, 1]), this._pixelsToClipSpaceMatrix = t
        }
        this._callbacks.calcMatrices()
    }
}

function xs(t) {
    return $t.fromLngLat(t)
}

function ws(t) {
    return t && t.toLngLat()
}

function Ts(t, e) {
    const i = U(e.lat, -85.051129, ms);
    return new h(jt(e.lng) * t, Ut(i) * t)
}

function Ms(t, e) {
    return new $t(e.x / t, e.y / t).toLngLat()
}

function Ps(t) {
    return Math.tan(Math.PI / 2 - t.pitch * Math.PI / 180) * t.cameraToCenterDistance * .85
}

function Es(t, e) {
    const i = t.canonical,
        s = e / gs(i.z),
        n = i.x + Math.pow(2, i.z) * t.wrap,
        r = g(new Float64Array(16));
    return b(r, r, [n * s, i.y * s, 0]), x(r, r, [s / D, s / D, 1]), r
}
class Ls {
    constructor(t, e) {
        this.points = t, this.planes = e
    }
    static fromInvProjectionMatrix(t, e = 1, i = 0) {
        const s = Math.pow(2, i),
            n = [
                [-1, 1, -1, 1],
                [1, 1, -1, 1],
                [1, -1, -1, 1],
                [-1, -1, -1, 1],
                [-1, 1, 1, 1],
                [1, 1, 1, 1],
                [1, -1, 1, 1],
                [-1, -1, 1, 1]
            ].map(i => {
                const n = 1 / (i = z([], i, t))[3] / e * s;
                return function(t, e, i) {
                    return t[0] = e[0] * i[0], t[1] = e[1] * i[1], t[2] = e[2] * i[2], t[3] = e[3] * i[3], t
                }(i, i, [n, n, 1 / i[3], n])
            }),
            r = [
                [0, 1, 2],
                [6, 5, 4],
                [0, 3, 7],
                [2, 1, 5],
                [3, 2, 6],
                [0, 4, 5]
            ].map(t => {
                const e = function(t, e) {
                        var i = e[0],
                            s = e[1],
                            n = e[2],
                            r = i * i + s * s + n * n;
                        return r > 0 && (r = 1 / Math.sqrt(r)), t[0] = e[0] * r, t[1] = e[1] * r, t[2] = e[2] * r, t
                    }([], function(t, e, i) {
                        var s = e[0],
                            n = e[1],
                            r = e[2],
                            o = i[0],
                            a = i[1],
                            h = i[2];
                        return t[0] = n * h - r * a, t[1] = r * o - s * h, t[2] = s * a - n * o, t
                    }([], I([], n[t[0]], n[t[1]]), I([], n[t[2]], n[t[1]]))),
                    i = - function(t, e) {
                        return t[0] * e[0] + t[1] * e[1] + t[2] * e[2]
                    }(e, n[t[1]]);
                return e.concat(i)
            });
        return new Ls(n, r)
    }
}
class Cs {
    constructor(t, e) {
        this.min = t, this.max = e, this.center = S([], C([], this.min, this.max), .5)
    }
    scaled(t) {
        const e = I([], this.max, this.center);
        return S(e, e, t), new Cs(I([], this.center, e), C([], this.center, e))
    }
    quadrant(t) {
        const e = [t % 2 == 0, t < 2],
            i = E(this.min),
            s = E(this.max);
        for (let t = 0; t < e.length; t++) i[t] = e[t] ? this.min[t] : this.center[t], s[t] = e[t] ? this.center[t] : this.max[t];
        return s[2] = this.max[2], new Cs(i, s)
    }
    distanceX(t) {
        return Math.max(Math.min(this.max[0], t[0]), this.min[0]) - t[0]
    }
    distanceY(t) {
        return Math.max(Math.min(this.max[1], t[1]), this.min[1]) - t[1]
    }
    intersectsFrustum(t) {
        const e = [
            [this.min[0], this.min[1], this.min[2], 1],
            [this.max[0], this.min[1], this.min[2], 1],
            [this.max[0], this.max[1], this.min[2], 1],
            [this.min[0], this.max[1], this.min[2], 1],
            [this.min[0], this.min[1], this.max[2], 1],
            [this.max[0], this.min[1], this.max[2], 1],
            [this.max[0], this.max[1], this.max[2], 1],
            [this.min[0], this.max[1], this.max[2], 1]
        ];
        let i = 1;
        for (let s = 0; s < t.planes.length; s++) {
            const n = t.planes[s];
            let r = 0;
            for (let t = 0; t < e.length; t++) A(n, e[t]) >= 0 && r++;
            if (0 === r) return 0;
            r !== e.length && (i = 0)
        }
        if (i) return 2;
        for (let e = 0; e < 3; e++) {
            let i = Number.MAX_VALUE,
                s = -Number.MAX_VALUE;
            for (let n = 0; n < t.points.length; n++) {
                const r = t.points[n][e] - this.min[e];
                i = Math.min(i, r), s = Math.max(s, r)
            }
            if (s < 0 || i > this.max[e] - this.min[e]) return 0
        }
        return 1
    }
    intersectsPlane(t) {
        const e = [
            [this.min[0], this.min[1], this.min[2], 1],
            [this.max[0], this.min[1], this.min[2], 1],
            [this.max[0], this.max[1], this.min[2], 1],
            [this.min[0], this.max[1], this.min[2], 1],
            [this.min[0], this.min[1], this.max[2], 1],
            [this.max[0], this.min[1], this.max[2], 1],
            [this.max[0], this.max[1], this.max[2], 1],
            [this.min[0], this.max[1], this.max[2], 1]
        ];
        let i = 0;
        for (let s = 0; s < e.length; s++) A(t, e[s]) >= 0 && i++;
        return 0 === i ? 0 : i < e.length ? 1 : 2
    }
}
class Ss {
    get pixelsToClipSpaceMatrix() {
        return this._helper.pixelsToClipSpaceMatrix
    }
    get clipSpaceToPixelsMatrix() {
        return this._helper.clipSpaceToPixelsMatrix
    }
    get pixelsToGLUnits() {
        return this._helper.pixelsToGLUnits
    }
    get centerOffset() {
        return this._helper.centerOffset
    }
    get size() {
        return this._helper.size
    }
    get rotationMatrix() {
        return this._helper.rotationMatrix
    }
    get centerPoint() {
        return this._helper.centerPoint
    }
    get pixelsPerMeter() {
        return this._helper.pixelsPerMeter
    }
    setMinZoom(t) {
        this._helper.setMinZoom(t)
    }
    setMaxZoom(t) {
        this._helper.setMaxZoom(t)
    }
    setMinPitch(t) {
        this._helper.setMinPitch(t)
    }
    setMaxPitch(t) {
        this._helper.setMaxPitch(t)
    }
    setRenderWorldCopies(t) {
        this._helper.setRenderWorldCopies(t)
    }
    setBearing(t) {
        this._helper.setBearing(t)
    }
    setPitch(t) {
        this._helper.setPitch(t)
    }
    setRoll(t) {
        this._helper.setRoll(t)
    }
    setFov(t) {
        this._helper.setFov(t)
    }
    setZoom(t) {
        this._helper.setZoom(t)
    }
    setCenter(t) {
        this._helper.setCenter(t)
    }
    setElevation(t) {
        this._helper.setElevation(t)
    }
    setMinElevationForCurrentTile(t) {
        this._helper.setMinElevationForCurrentTile(t)
    }
    setPadding(t) {
        this._helper.setPadding(t)
    }
    interpolatePadding(t, e, i) {
        return this._helper.interpolatePadding(t, e, i)
    }
    isPaddingEqual(t) {
        return this._helper.isPaddingEqual(t)
    }
    coveringZoomLevel(t) {
        return this._helper.coveringZoomLevel(t)
    }
    resize(t, e) {
        this._helper.resize(t, e)
    }
    getMaxBounds() {
        return this._helper.getMaxBounds()
    }
    setMaxBounds(t) {
        this._helper.setMaxBounds(t)
    }
    getCameraQueryGeometry(t) {
        return this._helper.getCameraQueryGeometry(this.getCameraPoint(), t)
    }
    get tileSize() {
        return this._helper.tileSize
    }
    get tileZoom() {
        return this._helper.tileZoom
    }
    get scale() {
        return this._helper.scale
    }
    get worldSize() {
        return this._helper.worldSize
    }
    get width() {
        return this._helper.width
    }
    get height() {
        return this._helper.height
    }
    get lngRange() {
        return this._helper.lngRange
    }
    get latRange() {
        return this._helper.latRange
    }
    get minZoom() {
        return this._helper.minZoom
    }
    get maxZoom() {
        return this._helper.maxZoom
    }
    get zoom() {
        return this._helper.zoom
    }
    get center() {
        return this._helper.center
    }
    get minPitch() {
        return this._helper.minPitch
    }
    get maxPitch() {
        return this._helper.maxPitch
    }
    get pitch() {
        return this._helper.pitch
    }
    get pitchInRadians() {
        return this._helper.pitchInRadians
    }
    get roll() {
        return this._helper.roll
    }
    get rollInRadians() {
        return this._helper.rollInRadians
    }
    get bearing() {
        return this._helper.bearing
    }
    get bearingInRadians() {
        return this._helper.bearingInRadians
    }
    get fov() {
        return this._helper.fov
    }
    get fovInRadians() {
        return this._helper.fovInRadians
    }
    get elevation() {
        return this._helper.elevation
    }
    get minElevationForCurrentTile() {
        return this._helper.minElevationForCurrentTile
    }
    get padding() {
        return this._helper.padding
    }
    get unmodified() {
        return this._helper.unmodified
    }
    get renderWorldCopies() {
        return this._helper.renderWorldCopies
    }
    constructor(t, e, i, s, n) {
        this._posMatrixCache = new Map, this._alignedPosMatrixCache = new Map, this._fogMatrixCacheF32 = new Map, this._helper = new bs({
            calcMatrices: () => {
                this._calcMatrices()
            },
            getConstrained: (t, e) => this.getConstrained(t, e)
        }, t, e, i, s, n)
    }
    clone() {
        const t = new Ss;
        return t.apply(this), t
    }
    apply(t, e) {
        this._helper.apply(t, e)
    }
    get cameraToCenterDistance() {
        return this._cameraToCenterDistance
    }
    get cameraPosition() {
        return this._cameraPosition
    }
    get projectionMatrix() {
        return this._projectionMatrix
    }
    get modelViewProjectionMatrix() {
        return this._viewProjMatrix
    }
    get inverseProjectionMatrix() {
        return this._invProjMatrix
    }
    get nearZ() {
        return this._nearZ
    }
    get farZ() {
        return this._farZ
    }
    get mercatorMatrix() {
        return this._mercatorMatrix
    }
    getVisibleUnwrappedCoordinates(t) {
        const e = [new se(0, t)];
        if (this._helper._renderWorldCopies) {
            const i = this.screenPointToMercatorCoordinate(new h(0, 0)),
                s = this.screenPointToMercatorCoordinate(new h(this._helper._width, 0)),
                n = this.screenPointToMercatorCoordinate(new h(this._helper._width, this._helper._height)),
                r = this.screenPointToMercatorCoordinate(new h(0, this._helper._height)),
                o = Math.floor(Math.min(i.x, s.x, n.x, r.x)),
                a = Math.floor(Math.max(i.x, s.x, n.x, r.x)),
                l = 1;
            for (let i = o - l; i <= a + l; i++) 0 !== i && e.push(new se(i, t))
        }
        return e
    }
    coveringTiles(t) {
        return function(t, e, i) {
            let s = t.coveringZoomLevel(e);
            const n = s;
            if (void 0 !== e.minzoom && s < e.minzoom) return [];
            void 0 !== e.maxzoom && s > e.maxzoom && (s = e.maxzoom);
            const r = t.screenPointToMercatorCoordinate(t.getCameraPoint()),
                o = $t.fromLngLat(t.center),
                a = Math.pow(2, s),
                h = [a * r.x, a * r.y, 0],
                l = [a * o.x, a * o.y, 0],
                c = Ls.fromInvProjectionMatrix(i, t.worldSize, s);
            let u = e.minzoom || 0;
            t.pitch <= 60 && t.padding.top < .1 && (u = s);
            const d = t => ({
                    aabb: new Cs([t * a, 0, 0], [(t + 1) * a, a, 0]),
                    zoom: 0,
                    x: 0,
                    y: 0,
                    wrap: t,
                    fullyVisible: 0
                }),
                p = [],
                _ = [],
                m = s,
                f = e.reparseOverscaled ? n : s;
            if (t.renderWorldCopies)
                for (let t = 1; t <= 3; t++) p.push(d(-t)), p.push(d(t));
            for (p.push(d(0)); p.length > 0;) {
                const t = p.pop(),
                    i = t.x,
                    s = t.y;
                let n = t.fullyVisible;
                const r = void 0 !== e.tileBboxScale ? t.aabb.scaled(e.tileBboxScale) : t.aabb;
                if (!n) {
                    const t = r.intersectsFrustum(c);
                    if (0 === t) continue;
                    n = 2 === t
                }
                const o = l,
                    a = r.distanceX(o),
                    d = r.distanceY(o);
                if (t.zoom === m || Math.max(Math.abs(a), Math.abs(d)) > 3 + (1 << m - t.zoom) - 2 && t.zoom >= u) {
                    const e = m - t.zoom,
                        n = h[0] - .5 - (i << e),
                        r = h[1] - .5 - (s << e);
                    _.push({
                        tileID: new ne(t.zoom === m ? f : t.zoom, t.wrap, t.zoom, i, s),
                        distanceSq: k([l[0] - .5 - i, l[1] - .5 - s]),
                        tileDistanceToCamera: Math.sqrt(n * n + r * r)
                    });
                    continue
                }
                for (let e = 0; e < 4; e++) {
                    const r = (i << 1) + e % 2,
                        o = (s << 1) + (e >> 1),
                        a = t.zoom + 1,
                        h = t.aabb.quadrant(e);
                    p.push({
                        aabb: h,
                        zoom: a,
                        x: r,
                        y: o,
                        wrap: t.wrap,
                        fullyVisible: n
                    })
                }
            }
            return _.sort((t, e) => t.distanceSq - e.distanceSq).map(t => t.tileID)
        }(this, t, this._invViewProjMatrix)
    }
    setLocationAtPoint(t, e) {
        const i = this.screenPointToMercatorCoordinate(e),
            s = this.screenPointToMercatorCoordinate(this.centerPoint),
            n = xs(t),
            r = new $t(n.x - (i.x - s.x), n.y - (i.y - s.y));
        this.setCenter(ws(r)), this._helper._renderWorldCopies && this.setCenter(this.center.wrap())
    }
    locationToScreenPoint(t) {
        return this.coordinatePoint(xs(t))
    }
    screenPointToLocation(t) {
        return ws(this.screenPointToMercatorCoordinate(t))
    }
    screenPointToMercatorCoordinate(t) {
        const e = [t.x, t.y, 0, 1],
            i = [t.x, t.y, 1, 1];
        z(e, e, this._pixelMatrixInverse), z(i, i, this._pixelMatrixInverse);
        const s = e[3],
            n = i[3],
            r = e[1] / s,
            o = i[1] / n,
            a = e[2] / s,
            h = i[2] / n,
            l = a === h ? 0 : (0 - a) / (h - a);
        return new $t(ji(e[0] / s, i[0] / n, l) / this.worldSize, ji(r, o, l) / this.worldSize)
    }
    coordinatePoint(t, e = 0, i = this._pixelMatrix) {
        const s = [t.x * this.worldSize, t.y * this.worldSize, e, 1];
        return z(s, s, i), new h(s[0] / s[3], s[1] / s[3])
    }
    getBounds() {
        const t = Math.max(0, this._helper._height / 2 - Ps(this));
        return (new Ft).extend(this.screenPointToLocation(new h(0, t))).extend(this.screenPointToLocation(new h(this._helper._width, t))).extend(this.screenPointToLocation(new h(this._helper._width, this._helper._height))).extend(this.screenPointToLocation(new h(0, this._helper._height)))
    }
    isPointOnMapSurface(t) {
        return t.y > this.height / 2 - Ps(this)
    }
    calculatePosMatrix(t, e = 0, i) {
        var s;
        const n = null !== (s = t.key) && void 0 !== s ? s : re(t.wrap, t.canonical.z, t.canonical.z, t.canonical.x, t.canonical.y),
            r = e ? this._alignedPosMatrixCache : this._posMatrixCache;
        if (r.has(n)) {
            const t = r.get(n);
            return i ? t.f32 : t.f64
        }
        const o = Es(t, this.worldSize);
        v(o, e ? this._alignedProjMatrix : this._viewProjMatrix, o);
        const a = {
            f64: o,
            f32: new Float32Array(o)
        };
        return r.set(n, a), i ? a.f32 : a.f64
    }
    calculateFogMatrix(t) {
        const e = t.key,
            i = this._fogMatrixCacheF32;
        if (i.has(e)) return i.get(e);
        const s = Es(t, this.worldSize);
        return v(s, this._fogMatrix, s), i.set(e, new Float32Array(s)), i.get(e)
    }
    getConstrained(t, e) {
        e = U(+e, this.minZoom, this.maxZoom);
        const i = {
            center: new Bt(t.lng, t.lat),
            zoom: e
        };
        let s = this._helper._lngRange;
        if (!this._helper._renderWorldCopies && null === s) {
            const t = 180 - 1e-10;
            s = [-t, t]
        }
        const n = this.tileSize * gs(i.zoom);
        let r = 0,
            o = n,
            a = 0,
            l = n,
            c = 0,
            u = 0;
        const {
            x: d,
            y: p
        } = this.size;
        if (this._helper._latRange) {
            const t = this._helper._latRange;
            r = Ut(t[1]) * n, o = Ut(t[0]) * n, o - r < p && (c = p / (o - r))
        }
        const _ = !s || Math.abs(s[0] - s[1]) >= 1e6;
        s && !_ && (a = G(jt(s[0]) * n, 0, n), l = G(jt(s[1]) * n, 0, n), l < a && (l += n), l - a < d && (u = d / (l - a)));
        const {
            x: m,
            y: f
        } = Ts(n, t);
        let g, y;
        const v = Math.max(u || 0, c || 0);
        if (v) {
            const t = new h(u ? (l + a) / 2 : m, c ? (o + r) / 2 : f);
            return i.center = Ms(n, t).wrap(), i.zoom += ys(v), i
        }
        if (this._helper._latRange) {
            const t = p / 2;
            f - t < r && (y = r + t), f + t > o && (y = o - t)
        }
        if (s && !_) {
            const t = (a + l) / 2;
            let e = m;
            this._helper._renderWorldCopies && (e = G(m, t - n / 2, t + n / 2));
            const i = d / 2;
            e - i < a && (g = a + i), e + i > l && (g = l - i)
        }
        if (void 0 !== g || void 0 !== y) {
            const t = new h(null != g ? g : m, null != y ? y : f);
            i.center = Ms(n, t).wrap()
        }
        return i
    }
    _calcMatrices() {
        if (!this._helper._height) return;
        const t = this._helper._fovInRadians / 2,
            e = this.centerOffset,
            i = Ts(this.worldSize, this.center),
            s = i.x,
            n = i.y;
        this._cameraToCenterDistance = .5 / Math.tan(t) * this._helper._height, this._helper._pixelPerMeter = Gt(1, this.center.lat) * this.worldSize;
        const r = this._cameraToCenterDistance + this._helper._elevation * this._helper._pixelPerMeter / Math.cos(this.pitchInRadians),
            o = Math.min(this.elevation, this.minElevationForCurrentTile),
            a = o < 0 ? r - o * this._helper._pixelPerMeter / Math.cos(this.pitchInRadians) : r,
            h = Math.PI / 2 + this.pitchInRadians,
            l = it(this.fov) * (Math.abs(Math.cos(it(this.roll))) * this.height + Math.abs(Math.sin(it(this.roll))) * this.width) / this.height * (.5 + e.y / this.height),
            c = Math.sin(l) * a / Math.sin(U(Math.PI - h - l, .01, Math.PI - .01)),
            u = Ps(this),
            d = 2 * Math.atan(u / this._cameraToCenterDistance) * (.5 + e.y / (2 * u)),
            p = Math.sin(d) * a / Math.sin(U(Math.PI - h - d, .01, Math.PI - .01)),
            _ = Math.min(c, p);
        let m;
        this._farZ = 1.01 * (Math.cos(Math.PI / 2 - this.pitchInRadians) * _ + a), this._nearZ = this._helper._height / 50, m = new Float64Array(16), M(m, this.fovInRadians, this._helper._width / this._helper._height, this._nearZ, this._farZ), this._invProjMatrix = new Float64Array(16), y(this._invProjMatrix, m), m[8] = 2 * -e.x / this._helper._width, m[9] = 2 * e.y / this._helper._height, this._projectionMatrix = function(t) {
            var e = new f(16);
            return e[0] = t[0], e[1] = t[1], e[2] = t[2], e[3] = t[3], e[4] = t[4], e[5] = t[5], e[6] = t[6], e[7] = t[7], e[8] = t[8], e[9] = t[9], e[10] = t[10], e[11] = t[11], e[12] = t[12], e[13] = t[13], e[14] = t[14], e[15] = t[15], e
        }(m), x(m, m, [1, -1, 1]), b(m, m, [0, 0, -this._cameraToCenterDistance]), T(m, m, -this.rollInRadians), w(m, m, this.pitchInRadians), T(m, m, -this.bearingInRadians), b(m, m, [-s, -n, 0]), this._mercatorMatrix = x([], m, [this.worldSize, this.worldSize, this.worldSize]), x(m, m, [1, 1, this._helper._pixelPerMeter]), this._pixelMatrix = v(new Float64Array(16), this.clipSpaceToPixelsMatrix, m), b(m, m, [0, 0, -this.elevation]), this._viewProjMatrix = m, this._invViewProjMatrix = y([], m);
        const g = [0, 0, -1, 1];
        z(g, g, this._invViewProjMatrix), this._cameraPosition = [g[0] / g[3], g[1] / g[3], g[2] / g[3]], this._fogMatrix = new Float64Array(16), M(this._fogMatrix, this.fovInRadians, this.width / this.height, r, this._farZ), this._fogMatrix[8] = 2 * -e.x / this.width, this._fogMatrix[9] = 2 * e.y / this.height, x(this._fogMatrix, this._fogMatrix, [1, -1, 1]), b(this._fogMatrix, this._fogMatrix, [0, 0, -this.cameraToCenterDistance]), T(this._fogMatrix, this._fogMatrix, -this.rollInRadians), w(this._fogMatrix, this._fogMatrix, this.pitchInRadians), T(this._fogMatrix, this._fogMatrix, -this.bearingInRadians), b(this._fogMatrix, this._fogMatrix, [-s, -n, 0]), x(this._fogMatrix, this._fogMatrix, [1, 1, this._helper._pixelPerMeter]), b(this._fogMatrix, this._fogMatrix, [0, 0, -this.elevation]), this._pixelMatrix3D = v(new Float64Array(16), this.clipSpaceToPixelsMatrix, m);
        const P = this._helper._width % 2 / 2,
            E = this._helper._height % 2 / 2,
            L = Math.cos(this.bearingInRadians),
            C = Math.sin(-this.bearingInRadians),
            S = s - Math.round(s) + L * P + C * E,
            R = n - Math.round(n) + L * E + C * P,
            I = new Float64Array(m);
        if (b(I, I, [S > .5 ? S - 1 : S, R > .5 ? R - 1 : R, 0]), this._alignedProjMatrix = I, m = y(new Float64Array(16), this._pixelMatrix), !m) throw Error("failed to invert matrix");
        this._pixelMatrixInverse = m, this._clearMatrixCaches()
    }
    _clearMatrixCaches() {
        this._posMatrixCache.clear(), this._alignedPosMatrixCache.clear(), this._fogMatrixCacheF32.clear()
    }
    maxPitchScaleFactor() {
        if (!this._pixelMatrixInverse) return 1;
        const t = this.screenPointToMercatorCoordinate(new h(0, 0)),
            e = [t.x * this.worldSize, t.y * this.worldSize, 0, 1];
        return z(e, e, this._pixelMatrix)[3] / this._cameraToCenterDistance
    }
    getCameraPoint() {
        return this.centerPoint.add(new h(0, Math.tan(this.pitchInRadians) * (this._cameraToCenterDistance || 1)))
    }
    getCameraAltitude() {
        return Math.cos(this.pitchInRadians) * this._cameraToCenterDistance / this._helper._pixelPerMeter + this.elevation
    }
    lngLatToCameraDepth(t, e) {
        const i = xs(t),
            s = [i.x * this.worldSize, i.y * this.worldSize, e, 1];
        return z(s, s, this._viewProjMatrix), s[2] / s[3]
    }
    isRenderingDirty() {
        return 0
    }
    getProjectionData(t, e, i) {
        return function(t, e, i) {
            let s, n;
            if (t) {
                const e = t.canonical.z >= 0 ? 1 << t.canonical.z : Math.pow(2, t.canonical.z);
                s = [t.canonical.x / e, t.canonical.y / e, 1 / e / D, 1 / e / D]
            } else s = [0, 0, 1, 1];
            return n = t && t.terrainRttPosMatrix32f && !i ? t.terrainRttPosMatrix32f : e || Z(), {
                mainMatrix: n,
                tileMercatorCoords: s,
                clippingPlane: [0, 0, 0, 0],
                projectionTransition: 0,
                fallbackMatrix: n
            }
        }(t, t ? this.calculatePosMatrix(t, e, 1) : null, i)
    }
    isLocationOccluded(t) {
        return 0
    }
    getPixelScale() {
        return 1
    }
    getCircleRadiusCorrection() {
        return 1
    }
    getPitchedTextCorrection(t, e, i) {
        return 1
    }
    newFrameUpdate() {
        return {}
    }
    transformLightDirection(t) {
        return E(t)
    }
    getRayDirectionFromPixel(t) {
        throw Error("Not implemented.")
    }
    precacheTiles(t) {
        for (const e of t) this.calculatePosMatrix(e)
    }
    getMatrixForModel(t, e) {
        const i = $t.fromLngLat(t, e),
            s = i.meterInMercatorCoordinateUnits(),
            n = function() {
                const t = new Float64Array(16);
                return g(t), t
            }();
        return b(n, n, [i.x, i.y, i.z]), T(n, n, Math.PI), w(n, n, Math.PI / 2), x(n, n, [-s, s, s]), n
    }
    getProjectionDataForCustomLayer() {
        const t = new ne(0, 0, 0, 0, 0),
            e = this.getProjectionData(t, 0, 1),
            i = Es(t, this.worldSize);
        v(i, this._viewProjMatrix, i), e.tileMercatorCoords = [0, 0, 1, 1];
        const s = [D, D, this.worldSize / this._helper.pixelsPerMeter],
            n = [0, 0, this.elevation],
            r = F();
        b(r, i, n), x(r, r, s);
        const o = F();
        return b(o, i, n), x(o, o, s), e.fallbackMatrix = r, e.mainMatrix = o, e
    }
    getFastPathSimpleProjectionMatrix(t) {
        return this.calculatePosMatrix(t)
    }
}
class Rs {
    get useGlobeControls() {
        return 0
    }
    handlePanInertia(t, e) {
        return {
            easingOffset: t,
            easingCenter: e.center
        }
    }
    handleMapControlsRollPitchBearingZoom(t, e) {
        t.bearingDelta && e.setBearing(e.bearing + t.bearingDelta), t.pitchDelta && e.setPitch(e.pitch + t.pitchDelta), t.rollDelta && e.setRoll(e.roll + t.rollDelta), t.zoomDelta && e.setZoom(e.zoom + t.zoomDelta)
    }
    handleMapControlsPan(t, e, i) {
        e.setLocationAtPoint(i, t.around)
    }
    cameraForBoxAndBearing(t, e, i, s, n) {
        const r = n.padding,
            o = Ts(n.worldSize, i.getNorthWest()),
            a = Ts(n.worldSize, i.getNorthEast()),
            l = Ts(n.worldSize, i.getSouthEast()),
            c = Ts(n.worldSize, i.getSouthWest()),
            u = it(-s),
            d = o.rotate(u),
            p = a.rotate(u),
            _ = l.rotate(u),
            m = c.rotate(u),
            f = new h(Math.max(d.x, p.x, m.x, _.x), Math.max(d.y, p.y, m.y, _.y)),
            g = new h(Math.min(d.x, p.x, m.x, _.x), Math.min(d.y, p.y, m.y, _.y)),
            y = f.sub(g),
            v = (n.width - (r.left + r.right + e.left + e.right)) / y.x,
            b = (n.height - (r.top + r.bottom + e.top + e.bottom)) / y.y;
        if (b < 0 || v < 0) return void Q("Map cannot fit within canvas with the given bounds, padding, and/or offset.");
        const x = Math.min(ys(n.scale * Math.min(v, b)), t.maxZoom),
            w = h.convert(t.offset),
            T = new h((e.left - e.right) / 2, (e.top - e.bottom) / 2).rotate(it(s)),
            M = w.add(T).mult(n.scale / gs(x));
        return {
            center: Ms(n.worldSize, o.add(l).div(2).sub(M)),
            zoom: x,
            bearing: s
        }
    }
    handleJumpToCenterZoom(t, e) {
        t.zoom !== (void 0 !== e.zoom ? +e.zoom : t.zoom) && t.setZoom(+e.zoom), void 0 !== e.center && t.setCenter(Bt.convert(e.center))
    }
    handleEaseTo(t, e) {
        const i = t.zoom,
            s = t.padding,
            n = nt(t.roll, t.pitch, t.bearing),
            r = void 0 === e.roll ? t.roll : e.roll,
            o = void 0 === e.pitch ? t.pitch : e.pitch,
            a = void 0 === e.bearing ? t.bearing : e.bearing,
            h = nt(r, o, a),
            l = void 0 !== e.zoom,
            c = !t.isPaddingEqual(e.padding);
        let u = 0;
        const d = l ? +e.zoom : t.zoom;
        let p = t.centerPoint.add(e.offsetAsPoint);
        const _ = t.screenPointToLocation(p),
            {
                center: m,
                zoom: f
            } = t.getConstrained(Bt.convert(e.center || _), null != d ? d : i);
        fs(t, m);
        const g = Ts(t.worldSize, _),
            y = Ts(t.worldSize, m).sub(g),
            v = gs(f - i);
        return u = f !== i, {
            easeFunc: l => {
                if (u && t.setZoom(ji(i, f, l)), Math.abs(A(n, h)) >= .999999 || function(t, e, i, s, n) {
                        if (n < 1) {
                            const i = new Float64Array(4);
                            ! function(t, e, i, s) {
                                var n, r, o, a, h, l = e[0],
                                    c = e[1],
                                    u = e[2],
                                    d = e[3],
                                    p = i[0],
                                    _ = i[1],
                                    m = i[2],
                                    f = i[3];
                                (r = l * p + c * _ + u * m + d * f) < 0 && (r = -r, p = -p, _ = -_, m = -m, f = -f), 1 - r > 1e-6 ? (o = Math.sin(n = Math.acos(r)), a = Math.sin((1 - s) * n) / o, h = Math.sin(s * n) / o) : (a = 1 - s, h = s), t[0] = a * l + h * p, t[1] = a * c + h * _, t[2] = a * u + h * m, t[3] = a * d + h * f
                            }(i, t, e, n);
                            const r = function(t) {
                                const e = new Float64Array(9);
                                ! function(t, e) {
                                    var i = e[0],
                                        s = e[1],
                                        n = e[2],
                                        r = e[3],
                                        o = i + i,
                                        a = s + s,
                                        h = n + n,
                                        l = i * o,
                                        c = s * o,
                                        u = s * a,
                                        d = n * o,
                                        p = n * a,
                                        _ = n * h,
                                        m = r * o,
                                        f = r * a,
                                        g = r * h;
                                    t[0] = 1 - u - _, t[3] = c - g, t[6] = d + f, t[1] = c + g, t[4] = 1 - l - _, t[7] = p - m, t[2] = d - f, t[5] = p + m, t[8] = 1 - l - u
                                }(e, t);
                                const i = st(-Math.asin(U(e[2], -1, 1)));
                                let s, n;
                                return Math.hypot(e[5], e[8]) < .001 ? (s = 0, n = -st(Math.atan2(e[3], e[4]))) : (s = st(0 === e[5] && 0 === e[8] ? 0 : Math.atan2(e[5], e[8])), n = st(0 === e[1] && 0 === e[0] ? 0 : Math.atan2(e[1], e[0]))), {
                                    roll: s,
                                    pitch: i + 90,
                                    bearing: n
                                }
                            }(i);
                            s.setRoll(r.roll), s.setPitch(r.pitch), s.setBearing(r.bearing)
                        } else s.setRoll(i.roll), s.setPitch(i.pitch), s.setBearing(i.bearing)
                    }(n, h, {
                        roll: r,
                        pitch: o,
                        bearing: a
                    }, t, l), c && (t.interpolatePadding(s, e.padding, l), p = t.centerPoint.add(e.offsetAsPoint)), e.around) t.setLocationAtPoint(e.around, e.aroundPoint);
                else {
                    const e = gs(t.zoom - i),
                        s = Ms(t.worldSize, g.add(y.mult(l * Math.pow(f > i ? Math.min(2, v) : Math.max(.5, v), 1 - l))).mult(e));
                    t.setLocationAtPoint(t.renderWorldCopies ? s.wrap() : s, p)
                }
            },
            isZooming: u,
            elevationCenter: m
        }
    }
    handleFlyTo(t, e) {
        const i = void 0 !== e.zoom,
            s = t.zoom,
            n = t.getConstrained(Bt.convert(e.center || e.locationAtOffset), i ? +e.zoom : s),
            r = n.center,
            o = n.zoom;
        fs(t, r);
        const a = Ts(t.worldSize, e.locationAtOffset),
            h = Ts(t.worldSize, r).sub(a),
            l = h.mag(),
            c = gs(o - s);
        let u;
        return void 0 !== e.minZoom && (u = gs(t.getConstrained(r, Math.min(+e.minZoom, s, o)).zoom - s)), {
            easeFunc: (e, i, n, l) => {
                t.setZoom(1 === e ? o : s + ys(i));
                const c = 1 === e ? r : Ms(t.worldSize, a.add(h.mult(n)).mult(i));
                t.setLocationAtPoint(t.renderWorldCopies ? c.wrap() : c, l)
            },
            scaleOfZoom: c,
            targetCenter: r,
            scaleOfMinZoom: u,
            pixelPathLength: l
        }
    }
}
const Is = {
    version: 8,
    sources: {},
    layers: []
};
class As extends It {
    constructor(t) {
        super(), this.map = t, this._spritesImagesIds = {}, this._layers = {}, this._order = [], this.sourceCaches = {}, this.zoomHistory = new le, this._loaded = 0, this._resetUpdates(), this.on("data", t => {
            if ("source" !== t.dataType || "metadata" !== t.sourceDataType) return;
            const e = this.sourceCaches[t.sourceId];
            if (!e) return;
            const i = e.getSource();
            if (i && i.vectorLayerIds)
                for (const t in this._layers) {
                    const e = this._layers[t];
                    e.source === i.id && this._validateLayer(e)
                }
        })
    }
    loadURL(t, e = {}, i) {
        this.fire(new St("dataloading", {
            dataType: "style"
        })), e.validate = "boolean" == typeof e.validate ? e.validate : 1;
        const s = this.map._requestManager.transformRequest(t, "Style");
        this._loadStyleRequest = new AbortController;
        const n = this._loadStyleRequest;
        yt(s, this._loadStyleRequest).then(t => {
            this._loadStyleRequest = null, this._load(t.data, e, i)
        }).catch(t => {
            this._loadStyleRequest = null, t && !n.signal.aborted && this.fire(new Rt(t))
        })
    }
    loadJSON(t, e = {}, i) {
        this.fire(new St("dataloading", {
            dataType: "style"
        })), this._frameRequest = new AbortController, ht.frameAsync(this._frameRequest).then(() => {
            this._frameRequest = null, e.validate = 0 != e.validate, this._load(t, e, i)
        }).catch(() => {})
    }
    loadEmpty() {
        this.fire(new St("dataloading", {
            dataType: "style"
        })), this._load(Is, {
            validate: 0
        })
    }
    _load(t, e, i) {
        const s = e.transformStyle ? e.transformStyle(i, t) : t;
        this._loaded = 1, this.stylesheet = s;
        for (const t in s.sources) this.addSource(t, s.sources[t], {
            validate: 0
        });
        this._createLayers(), this._setProjectionInternal("mercator"), this.fire(new St("data", {
            dataType: "style"
        })), this.fire(new St("style.load"))
    }
    _createLayers() {
        const t = Ui(this.stylesheet.layers);
        this._order = [], this._layers = {}, this._serializedLayers = null;
        for (const e of t) {
            const t = Dt(e);
            void 0 !== t && (this._order.push(e.id), t.setEventedParent(this, {
                layer: {
                    id: e.id
                }
            }), this._layers[e.id] = t)
        }
    }
    _validateLayer(t) {
        const e = this.sourceCaches[t.source];
        if (!e) return;
        const i = t.sourceLayer;
        if (!i) return;
        const s = e.getSource();
        ("geojson" === s.type || s.vectorLayerIds && -1 === s.vectorLayerIds.indexOf(i)) && this.fire(new Rt(Error(`Source layer "${i}" does not exist on source "${s.id}" as specified by style layer "${t.id}".`)))
    }
    loaded() {
        if (!this._loaded) return 0;
        if (Object.keys(this._updatedSources).length) return 0;
        for (const t in this.sourceCaches)
            if (!this.sourceCaches[t].loaded()) return 0;
        return 1
    }
    _serializeByIds(t, e = 0) {
        const i = this._serializedAllLayers();
        if (!t || 0 === t.length) return Object.values(e ? Y(i) : i);
        const s = [];
        for (const n of t)
            if (i[n]) {
                const t = e ? Y(i[n]) : i[n];
                s.push(t)
            } return s
    }
    _serializedAllLayers() {
        let t = this._serializedLayers;
        if (t) return t;
        t = this._serializedLayers = {};
        const e = Object.keys(this._layers);
        for (const i of e) {
            const e = this._layers[i];
            "custom" !== e.type && (t[i] = e.serialize())
        }
        return t
    }
    hasTransitions() {
        for (const t in this.sourceCaches)
            if (this.sourceCaches[t].hasTransition()) return 1;
        return 0
    }
    _checkLoaded() {
        if (!this._loaded) throw Error("Style is not done loading.")
    }
    update(t) {
        if (!this._loaded) return;
        const e = this._changed;
        if (e) {
            for (const t in this._updatedSources) {
                const e = this._updatedSources[t];
                if ("reload" === e) this._reloadSource(t);
                else {
                    if ("clear" !== e) throw Error("Invalid action " + e);
                    this._clearSource(t)
                }
            }
            this._resetUpdates()
        }
        const i = {};
        for (const t in this.sourceCaches) {
            const e = this.sourceCaches[t];
            i[t] = e.used, "auto" === e.updateMode && (e.used = 0)
        }
        for (const e of this._order) {
            const i = this._layers[e];
            i.recalculate(t), !i.isHidden(t.zoom) && i.source && (this.sourceCaches[i.source].used = 1)
        }
        for (const t in i) {
            const e = this.sourceCaches[t];
            !!i[t] != !!e.used && e.fire(new St("data", {
                sourceDataType: "visibility",
                dataType: "source",
                sourceId: t
            }))
        }
        this.z = t.zoom, e && this.fire(new St("data", {
            dataType: "style"
        }))
    }
    _resetUpdates() {
        this._changed = 0, this._updatedLayers = {}, this._removedLayers = {}, this._updatedSources = {}, this._changedImages = {}, this._glyphsDidChange = 0
    }
    setState(t, e = {}) {
        this._checkLoaded();
        const i = this.serialize();
        (t = Y(t = e.transformStyle ? e.transformStyle(i, t) : t)).layers = Ui(t.layers);
        const s = function(t, e) {
                if (!t) return [{
                    command: "setStyle",
                    args: [e]
                }];
                let i = [];
                try {
                    if (!Gi(t.version, e.version)) return [{
                        command: "setStyle",
                        args: [e]
                    }];
                    Gi(t.center, e.center) || i.push({
                        command: "setCenter",
                        args: [e.center]
                    }), Gi(t.centerAltitude, e.centerAltitude) || i.push({
                        command: "setCenterAltitude",
                        args: [e.centerAltitude]
                    }), Gi(t.zoom, e.zoom) || i.push({
                        command: "setZoom",
                        args: [e.zoom]
                    }), Gi(t.bearing, e.bearing) || i.push({
                        command: "setBearing",
                        args: [e.bearing]
                    }), Gi(t.pitch, e.pitch) || i.push({
                        command: "setPitch",
                        args: [e.pitch]
                    }), Gi(t.roll, e.roll) || i.push({
                        command: "setRoll",
                        args: [e.roll]
                    }), Gi(t.sprite, e.sprite) || i.push({
                        command: "setSprite",
                        args: [e.sprite]
                    }), Gi(t.glyphs, e.glyphs) || i.push({
                        command: "setGlyphs",
                        args: [e.glyphs]
                    }), Gi(t.transition, e.transition) || i.push({
                        command: "setTransition",
                        args: [e.transition]
                    }), Gi(t.light, e.light) || i.push({
                        command: "setLight",
                        args: [e.light]
                    }), Gi(t.terrain, e.terrain) || i.push({
                        command: "setTerrain",
                        args: [e.terrain]
                    }), Gi(t.sky, e.sky) || i.push({
                        command: "setSky",
                        args: [e.sky]
                    }), Gi(t.projection, e.projection) || i.push({
                        command: "setProjection",
                        args: [e.projection]
                    });
                    const s = {},
                        n = [];
                    ! function(t, e, i, s) {
                        let n;
                        for (n in e = e || {}, t = t || {}) Object.prototype.hasOwnProperty.call(t, n) && (Object.prototype.hasOwnProperty.call(e, n) || Wi(n, i, s));
                        for (n in e) Object.prototype.hasOwnProperty.call(e, n) && (Object.prototype.hasOwnProperty.call(t, n) ? Gi(t[n], e[n]) || Hi(n, e, i, s) : $i(n, e, i))
                    }(t.sources, e.sources, n, s);
                    const r = [];
                    t.layers && t.layers.forEach(t => {
                            "source" in t && s[t.source] ? i.push({
                                command: "removeLayer",
                                args: [t.id]
                            }) : r.push(t)
                        }), i = i.concat(n),
                        function(t, e, i) {
                            e = e || [];
                            const s = (t = t || []).map(Xi),
                                n = e.map(Xi),
                                r = t.reduce(Ki, {}),
                                o = e.reduce(Ki, {}),
                                a = s.slice(),
                                h = Object.create(null);
                            let l, c, u, d, p;
                            for (let t = 0, e = 0; t < s.length; t++) l = s[t], Object.prototype.hasOwnProperty.call(o, l) ? e++ : (qi(i, {
                                command: "removeLayer",
                                args: [l]
                            }), a.splice(a.indexOf(l, e), 1));
                            for (let t = 0, e = 0; t < n.length; t++) l = n[n.length - 1 - t], a[a.length - 1 - t] !== l && (Object.prototype.hasOwnProperty.call(r, l) ? (qi(i, {
                                command: "removeLayer",
                                args: [l]
                            }), a.splice(a.lastIndexOf(l, a.length - e), 1)) : e++, d = a[a.length - t], qi(i, {
                                command: "addLayer",
                                args: [o[l], d]
                            }), a.splice(a.length - t, 0, l), h[l] = 1);
                            for (let t = 0; t < n.length; t++)
                                if (l = n[t], c = r[l], u = o[l], !h[l] && !Gi(c, u))
                                    if (Gi(c.source, u.source) && Gi(c["source-layer"], u["source-layer"]) && Gi(c.type, u.type)) {
                                        for (p in Vi(c.layout, u.layout, i, l, null, "setLayoutProperty"), Vi(c.paint, u.paint, i, l, null, "setPaintProperty"), Gi(c.filter, u.filter) || qi(i, {
                                                command: "setFilter",
                                                args: [l, u.filter]
                                            }), Gi(c.minzoom, u.minzoom) && Gi(c.maxzoom, u.maxzoom) || qi(i, {
                                                command: "setLayerZoomRange",
                                                args: [l, u.minzoom, u.maxzoom]
                                            }), c) Object.prototype.hasOwnProperty.call(c, p) && "layout" !== p && "paint" !== p && "filter" !== p && "metadata" !== p && "minzoom" !== p && "maxzoom" !== p && (0 === p.indexOf("paint.") ? Vi(c[p], u[p], i, l, p.slice(6), "setPaintProperty") : Gi(c[p], u[p]) || qi(i, {
                                            command: "setLayerProperty",
                                            args: [l, p, u[p]]
                                        }));
                                        for (p in u) Object.prototype.hasOwnProperty.call(u, p) && !Object.prototype.hasOwnProperty.call(c, p) && "layout" !== p && "paint" !== p && "filter" !== p && "metadata" !== p && "minzoom" !== p && "maxzoom" !== p && (0 === p.indexOf("paint.") ? Vi(c[p], u[p], i, l, p.slice(6), "setPaintProperty") : Gi(c[p], u[p]) || qi(i, {
                                            command: "setLayerProperty",
                                            args: [l, p, u[p]]
                                        }))
                                    } else qi(i, {
                                        command: "removeLayer",
                                        args: [l]
                                    }), d = a[a.lastIndexOf(l) + 1], qi(i, {
                                        command: "addLayer",
                                        args: [u, d]
                                    })
                        }(r, e.layers, i)
                } catch (t) {
                    console.warn("Unable to compute style diff:", t), i = [{
                        command: "setStyle",
                        args: [e]
                    }]
                }
                return i
            }(i, t),
            n = this._getOperationsToPerform(s);
        if (n.unimplemented.length > 0) throw Error(`Unimplemented: ${n.unimplemented.join(", ")}.`);
        if (0 === n.operations.length) return 0;
        for (const t of n.operations) t();
        return this.stylesheet = t, this._serializedLayers = null, 1
    }
    _getOperationsToPerform(t) {
        const e = [],
            i = [];
        for (const s of t) switch (s.command) {
            case "setCenter":
            case "setZoom":
            case "setBearing":
            case "setPitch":
                continue;
            case "addLayer":
                e.push(() => this.addLayer.apply(this, s.args));
                break;
            case "removeLayer":
                e.push(() => this.removeLayer.apply(this, s.args));
                break;
            case "addSource":
                e.push(() => this.addSource.apply(this, s.args));
                break;
            case "removeSource":
                e.push(() => this.removeSource.apply(this, s.args));
                break;
            case "setLayerZoomRange":
                e.push(() => this.setLayerZoomRange.apply(this, s.args));
                break;
            case "setTransition":
                e.push(() => {});
                break;
            default:
                i.push(s.command)
        }
        return {
            operations: e,
            unimplemented: i
        }
    }
    addSource(t, e, i = {}) {
        if (this._checkLoaded(), void 0 !== this.sourceCaches[t]) throw Error(`Source "${t}" already exists.`);
        if (!e.type) throw Error(`The type property must be defined, but only the following properties were given: ${Object.keys(e).join(", ")}.`);
        if (["vector", "geojson", "video", "canvas"].indexOf(e.type) >= 0) return void console.error(`Source type of ${e.type} is unsupported.`);
        this.map && this.map._collectResourceTiming && (e.collectResourceTiming = 1);
        const s = this.sourceCaches[t] = new oe(t, e);
        s.style = this, s.setEventedParent(this, () => ({
            isSourceLoaded: s.loaded(),
            source: s.serialize(),
            sourceId: t
        })), s.onAdd(this.map), this._changed = 1
    }
    removeSource(t) {
        if (this._checkLoaded(), void 0 === this.sourceCaches[t]) throw Error("There is no source with this ID");
        for (const e in this._layers)
            if (this._layers[e].source === t) return this.fire(new Rt(Error(`Source "${t}" cannot be removed while layer "${e}" is using it.`)));
        const e = this.sourceCaches[t];
        delete this.sourceCaches[t], delete this._updatedSources[t], e.fire(new St("data", {
            sourceDataType: "metadata",
            dataType: "source",
            sourceId: t
        })), e.setEventedParent(null), e.onRemove(this.map), this._changed = 1
    }
    getSource(t) {
        return this.sourceCaches[t] && this.sourceCaches[t].getSource()
    }
    addLayer(t, e, i = {}) {
        this._checkLoaded();
        const s = t.id;
        if (this.getLayer(s)) return void this.fire(new Rt(Error(`Layer "${s}" already exists on this map.`)));
        let n, r;
        if ("custom" === t.type) r = Dt(t);
        else if ("canvas" === t.type) r = t;
        else {
            if ("source" in t && "object" == typeof t.source && (this.addSource(s, t.source), t = q(t = Y(t), {
                    source: s
                })), "raster" === t.type && t.customShader && (n = "raster-" + s, function(t, e) {
                    if (!e.includes("vec4 pixelTransform")) throw Error("Custom raster tile pixel transform code does not contain 'pixelTransform' method");
                    const i = ue.slice(0, 298) + "\n#define CUSTOM_RASTER\n" + e + ue.slice(298) + "\n";
                    Zi[t] = Ni(i, de), Fi[t] = Fi.raster
                }(n, t.customShader.pixelTransform)), r = Dt(t), this._validateLayer(r), n) {
                const e = r,
                    i = t;
                e.customShaderId = n, e.tileFilter = i.tileFilter, e.postRenderTileCallback = i.postRenderTileCallback, e.preRenderTileCallback = i.preRenderTileCallback
            }
            r.setEventedParent(this, {
                layer: {
                    id: s
                }
            })
        }
        const o = e ? this._order.indexOf(e) : this._order.length;
        if (e && -1 === o) this.fire(new Rt(Error(`Cannot add layer "${s}" before non-existing layer "${e}".`)));
        else {
            if (this._order.splice(o, 0, s), this._layerOrderChanged = 1, this._layers[s] = r, this._removedLayers[s] && r.source && "custom" !== r.type) {
                const t = this._removedLayers[s];
                delete this._removedLayers[s], t.type !== r.type ? this._updatedSources[r.source] = "clear" : (this._updatedSources[r.source] = "reload", this.sourceCaches[r.source].pause())
            }
            this._updateLayer(r), r.onAdd && r.onAdd(this.map)
        }
    }
    moveLayer(t, e) {
        if (this._checkLoaded(), this._changed = 1, !this._layers[t]) return void this.fire(new Rt(Error(`The layer '${t}' does not exist in the map's style and cannot be moved.`)));
        if (t === e) return;
        const i = this._order.indexOf(t);
        this._order.splice(i, 1);
        const s = e ? this._order.indexOf(e) : this._order.length;
        e && -1 === s ? this.fire(new Rt(Error(`Cannot move layer "${t}" before non-existing layer "${e}".`))) : (this._order.splice(s, 0, t), this._layerOrderChanged = 1)
    }
    removeLayer(t) {
        this._checkLoaded();
        const e = this._layers[t];
        if (!e) return void this.fire(new Rt(Error(`Cannot remove non-existing layer "${t}".`)));
        e.setEventedParent(null);
        const i = e;
        i.customShaderId && Object.keys(this.map.painter.cache).forEach(t => {
            t.includes(i.customShaderId) && delete this.map.painter.cache[t]
        });
        const s = this._order.indexOf(t);
        this._order.splice(s, 1), this._layerOrderChanged = 1, this._changed = 1, this._removedLayers[t] = e, delete this._layers[t], this._serializedLayers && delete this._serializedLayers[t], delete this._updatedLayers[t], e.onRemove && e.onRemove(this.map)
    }
    getLayer(t) {
        return this._layers[t]
    }
    getLayersOrder() {
        return [...this._order]
    }
    hasLayer(t) {
        return t in this._layers
    }
    setLayerZoomRange(t, e, i) {
        this._checkLoaded();
        const s = this.getLayer(t);
        s ? s.minzoom === e && s.maxzoom === i || (null != e && (s.minzoom = e), null != i && (s.maxzoom = i), this._updateLayer(s)) : this.fire(new Rt(Error(`Cannot set the zoom range of non-existing layer "${t}".`)))
    }
    getTransition() {
        return q({
            duration: 300,
            delay: 0
        }, this.stylesheet && this.stylesheet.transition)
    }
    serialize() {
        if (!this._loaded) return;
        const t = V(this.sourceCaches, t => t.serialize()),
            e = this._serializeByIds(this._order, 1),
            i = this.stylesheet;
        return X({
            version: i.version,
            name: i.name,
            metadata: i.metadata,
            center: i.center,
            zoom: i.zoom,
            bearing: i.bearing,
            pitch: i.pitch,
            glyphs: i.glyphs,
            transition: i.transition,
            sources: t,
            layers: e
        }, t => void 0 !== t)
    }
    _updateLayer(t) {
        this._updatedLayers[t.id] = 1, t.source && !this._updatedSources[t.source] && "raster" !== this.sourceCaches[t.source].getSource().type && (this._updatedSources[t.source] = "reload", this.sourceCaches[t.source].pause()), this._serializedLayers = null, this._changed = 1
    }
    _setProjectionInternal(t) {
        this.projection = new ps, this.map.migrateProjection(new Ss, new Rs);
        for (const t in this.sourceCaches) this.sourceCaches[t].reload()
    }
    _remove() {
        this._frameRequest && (this._frameRequest.abort(), this._frameRequest = null), this._loadStyleRequest && (this._loadStyleRequest.abort(), this._loadStyleRequest = null), this._spriteRequest && (this._spriteRequest.abort(), this._spriteRequest = null);
        for (const t in this._layers) this._layers[t].setEventedParent(null);
        for (const t in this.sourceCaches) {
            const e = this.sourceCaches[t];
            e.setEventedParent(null), e.onRemove(this.map)
        }
        this.setEventedParent(null)
    }
    _clearSource(t) {
        this.sourceCaches[t].clearTiles()
    }
    _reloadSource(t) {
        this.sourceCaches[t].resume(), this.sourceCaches[t].reload()
    }
    _updateSources(t) {
        for (const e in this.sourceCaches) this.sourceCaches[e].update(t)
    }
}
class zs {
    constructor(t, e) {
        this.zoom = t, e ? (this.now = e.now, this.fadeDuration = e.fadeDuration, this.zoomHistory = e.zoomHistory, this.transition = e.transition) : (this.now = 0, this.fadeDuration = 0, this.zoomHistory = new le, this.transition = {})
    }
    crossFadingFactor() {
        return 0 === this.fadeDuration ? 1 : Math.min((this.now - this.zoomHistory.lastIntegerZoomTime) / this.fadeDuration, 1)
    }
    getCrossfadeParameters() {
        const t = this.zoom,
            e = t - Math.floor(t),
            i = this.crossFadingFactor();
        return t > this.zoomHistory.lastIntegerZoom ? {
            fromScale: 2,
            toScale: 1,
            t: e + (1 - e) * i
        } : {
            fromScale: .5,
            toScale: 1,
            t: 1 - (1 - i) * e
        }
    }
}
class Os {
    constructor() {
        this.boundProgram = null, this.boundLayoutVertexBuffer = null, this.boundIndexBuffer = null, this.boundVertexOffset = null, this.vao = null
    }
    bind(t, e, i, s, n) {
        this.context = t, this.vao && this.boundProgram === e && this.boundLayoutVertexBuffer === i && this.boundIndexBuffer === s && this.boundVertexOffset === n ? (t.bindVertexArray.set(this.vao), s && s.dynamicDraw && s.bind()) : this.freshBind(e, i, s, n)
    }
    freshBind(t, e, i, s) {
        const n = t.numAttributes,
            r = this.context,
            o = r.gl;
        this.vao && this.destroy(), this.vao = r.createVertexArray(), r.bindVertexArray.set(this.vao), this.boundProgram = t, this.boundLayoutVertexBuffer = e, this.boundIndexBuffer = i, this.boundVertexOffset = s, e.enableAttributes(o, t), e.bind(), e.setVertexAttribPointers(o, t, s), i && i.bind(), r.currentNumAttributes = n
    }
    destroy() {
        this.vao && (this.context.deleteVertexArray(this.vao), this.vao = null)
    }
}
const ks = {
    mainMatrix: "u_projection_matrix",
    tileMercatorCoords: "u_projection_tile_mercator_coords",
    clippingPlane: "u_projection_clipping_plane",
    projectionTransition: "u_projection_transition",
    fallbackMatrix: "u_projection_fallback_matrix"
};

function Ds(t) {
    const e = [];
    for (let i = 0; i < t.length; i++) {
        if (null === t[i]) continue;
        const s = t[i].split(" ");
        e.push(s.pop())
    }
    return e
}
class Bs {
    constructor(t, e, i, s, n) {
        const r = t.gl;
        this.program = r.createProgram();
        const o = Ds(e.staticAttributes),
            a = Zi.prelude.staticUniforms ? Ds(Zi.prelude.staticUniforms) : [],
            h = s.staticUniforms ? Ds(s.staticUniforms) : [],
            l = e.staticUniforms ? Ds(e.staticUniforms) : [],
            c = a.concat(h).concat(l),
            u = [];
        for (const t of c) u.indexOf(t) < 0 && u.push(t);
        const d = [];
        n && d.push(n);
        const p = d.concat(Zi.prelude.fragmentSource, s.fragmentSource, e.fragmentSource).join("\n"),
            _ = d.concat(Zi.prelude.vertexSource, s.vertexSource, e.vertexSource).join("\n"),
            m = r.createShader(r.FRAGMENT_SHADER);
        if (r.isContextLost()) return void(this.failedToCreate = 1);
        if (r.shaderSource(m, p), r.compileShader(m), !r.getShaderParameter(m, r.COMPILE_STATUS)) throw console.error("Failed to compile FS", r.getShaderInfoLog(m), p), Error("Could not compile fragment shader: " + r.getShaderInfoLog(m));
        r.attachShader(this.program, m);
        const f = r.createShader(r.VERTEX_SHADER);
        if (r.isContextLost()) return void(this.failedToCreate = 1);
        if (r.shaderSource(f, _), r.compileShader(f), !r.getShaderParameter(f, r.COMPILE_STATUS)) throw Error("Could not compile vertex shader: " + r.getShaderInfoLog(f));
        r.attachShader(this.program, f), this.attributes = {};
        const g = {};
        this.numAttributes = o.length;
        for (let t = 0; t < this.numAttributes; t++) o[t] && (r.bindAttribLocation(this.program, t, o[t]), this.attributes[o[t]] = t);
        if (r.linkProgram(this.program), !r.getProgramParameter(this.program, r.LINK_STATUS)) throw Error("Program failed to link: " + r.getProgramInfoLog(this.program));
        r.deleteShader(f), r.deleteShader(m);
        for (let t = 0; t < u.length; t++) {
            const e = u[t];
            if (e && !g[e]) {
                const t = r.getUniformLocation(this.program, e);
                t && (g[e] = t)
            }
        }
        this.fixedUniforms = i(t, g), this.projectionUniforms = ((t, e) => ({
            u_projection_matrix: new Le(t, e.u_projection_matrix),
            u_projection_tile_mercator_coords: new Me(t, e.u_projection_tile_mercator_coords),
            u_projection_clipping_plane: new Me(t, e.u_projection_clipping_plane),
            u_projection_transition: new xe(t, e.u_projection_transition),
            u_projection_fallback_matrix: new Le(t, e.u_projection_fallback_matrix)
        }))(t, g)
    }
    draw(t, e, i, s, n, r, o, a, h, l, c, u) {
        const d = t.gl;
        if (this.failedToCreate) return;
        if (t.program.set(this.program), t.setDepthMode(i), t.setStencilMode(s), t.setColorMode(n), t.setCullFace(r), a)
            for (const t in a) this.projectionUniforms[ks[t]].set(a[t]);
        if (o)
            for (const t in this.fixedUniforms) this.fixedUniforms[t].set(o[t]);
        let p = 0;
        switch (e) {
            case d.LINES:
                p = 2;
                break;
            case d.TRIANGLES:
                p = 3;
                break;
            case d.LINE_STRIP:
                p = 1
        }
        for (const i of u.get()) {
            const s = i.vaos || (i.vaos = {});
            (s[h] || (s[h] = new Os)).bind(t, this, l, c, i.vertexOffset), d.drawElements(e, i.primitiveLength * p, d.UNSIGNED_SHORT, i.primitiveOffset * p * 2)
        }
    }
}
class Fs {
    constructor(t, e, i) {
        this.context = t;
        const s = t.gl;
        this.buffer = s.createBuffer(), this.dynamicDraw = !!i, this.context.unbindVAO(), t.bindElementBuffer.set(this.buffer), s.bufferData(s.ELEMENT_ARRAY_BUFFER, e.arrayBuffer, this.dynamicDraw ? s.DYNAMIC_DRAW : s.STATIC_DRAW), this.dynamicDraw || delete e.arrayBuffer
    }
    bind() {
        this.context.bindElementBuffer.set(this.buffer)
    }
    updateData(t) {
        const e = this.context.gl;
        if (!this.dynamicDraw) throw Error("Attempted to update data while not in dynamic mode.");
        this.context.unbindVAO(), this.bind(), e.bufferSubData(e.ELEMENT_ARRAY_BUFFER, 0, t.arrayBuffer)
    }
    destroy() {
        this.buffer && (this.context.gl.deleteBuffer(this.buffer), delete this.buffer)
    }
}
const Zs = {
    Int8: "BYTE",
    Uint8: "UNSIGNED_BYTE",
    Int16: "SHORT",
    Uint16: "UNSIGNED_SHORT",
    Int32: "INT",
    Uint32: "UNSIGNED_INT",
    Float32: "FLOAT"
};
class Ns {
    constructor(t, e, i, s) {
        this.length = e.length, this.attributes = i, this.itemSize = e.bytesPerElement, this.dynamicDraw = s, this.context = t;
        const n = t.gl;
        this.buffer = n.createBuffer(), t.bindVertexBuffer.set(this.buffer), n.bufferData(n.ARRAY_BUFFER, e.arrayBuffer, this.dynamicDraw ? n.DYNAMIC_DRAW : n.STATIC_DRAW), this.dynamicDraw || delete e.arrayBuffer
    }
    bind() {
        this.context.bindVertexBuffer.set(this.buffer)
    }
    updateData(t) {
        if (t.length !== this.length) throw Error(`Length of new data is ${t.length}, which doesn't match current length of ${this.length}`);
        const e = this.context.gl;
        this.bind(), e.bufferSubData(e.ARRAY_BUFFER, 0, t.arrayBuffer)
    }
    enableAttributes(t, e) {
        for (let i = 0; i < this.attributes.length; i++) {
            const s = e.attributes[this.attributes[i].name];
            void 0 !== s && t.enableVertexAttribArray(s)
        }
    }
    setVertexAttribPointers(t, e, i) {
        for (let s = 0; s < this.attributes.length; s++) {
            const n = this.attributes[s],
                r = e.attributes[n.name];
            void 0 !== r && t.vertexAttribPointer(r, n.components, t[Zs[n.type]], 0, this.itemSize, n.offset + this.itemSize * (i || 0))
        }
    }
    destroy() {
        this.buffer && (this.context.gl.deleteBuffer(this.buffer), delete this.buffer)
    }
}
class js {
    constructor(t) {
        this.gl = t.gl, this.default = this.getDefault(), this.current = this.default, this.dirty = 0
    }
    get() {
        return this.current
    }
    set(t) {}
    getDefault() {
        return this.default
    }
    setDefault() {
        this.set(this.default)
    }
}
class Us extends js {
    getDefault() {
        return pe.transparent
    }
    set(t) {
        const e = this.current;
        (t.r !== e.r || t.g !== e.g || t.b !== e.b || t.a !== e.a || this.dirty) && (this.gl.clearColor(t.r, t.g, t.b, t.a), this.current = t, this.dirty = 0)
    }
}
class Gs extends js {
    getDefault() {
        return 1
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.clearDepth(t), this.current = t, this.dirty = 0)
    }
}
class qs extends js {
    getDefault() {
        return 0
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.clearStencil(t), this.current = t, this.dirty = 0)
    }
}
class $s extends js {
    getDefault() {
        return [1, 1, 1, 1]
    }
    set(t) {
        const e = this.current;
        (t[0] !== e[0] || t[1] !== e[1] || t[2] !== e[2] || t[3] !== e[3] || this.dirty) && (this.gl.colorMask(t[0], t[1], t[2], t[3]), this.current = t, this.dirty = 0)
    }
}
class Ws extends js {
    getDefault() {
        return 1
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.depthMask(t), this.current = t, this.dirty = 0)
    }
}
class Hs extends js {
    getDefault() {
        return 255
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.stencilMask(t), this.current = t, this.dirty = 0)
    }
}
class Vs extends js {
    getDefault() {
        return {
            func: this.gl.ALWAYS,
            ref: 0,
            mask: 255
        }
    }
    set(t) {
        const e = this.current;
        (t.func !== e.func || t.ref !== e.ref || t.mask !== e.mask || this.dirty) && (this.gl.stencilFunc(t.func, t.ref, t.mask), this.current = t, this.dirty = 0)
    }
}
class Xs extends js {
    getDefault() {
        const t = this.gl;
        return [t.KEEP, t.KEEP, t.KEEP]
    }
    set(t) {
        const e = this.current;
        (t[0] !== e[0] || t[1] !== e[1] || t[2] !== e[2] || this.dirty) && (this.gl.stencilOp(t[0], t[1], t[2]), this.current = t, this.dirty = 0)
    }
}
class Ks extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        t ? e.enable(e.STENCIL_TEST) : e.disable(e.STENCIL_TEST), this.current = t, this.dirty = 0
    }
}
class Ys extends js {
    getDefault() {
        return [0, 1]
    }
    set(t) {
        const e = this.current;
        (t[0] !== e[0] || t[1] !== e[1] || this.dirty) && (this.gl.depthRange(t[0], t[1]), this.current = t, this.dirty = 0)
    }
}
class Js extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        t ? e.enable(e.DEPTH_TEST) : e.disable(e.DEPTH_TEST), this.current = t, this.dirty = 0
    }
}
class Qs extends js {
    getDefault() {
        return this.gl.LESS
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.depthFunc(t), this.current = t, this.dirty = 0)
    }
}
class tn extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        t ? e.enable(e.BLEND) : e.disable(e.BLEND), this.current = t, this.dirty = 0
    }
}
class en extends js {
    getDefault() {
        const t = this.gl;
        return [t.ONE, t.ZERO]
    }
    set(t) {
        const e = this.current;
        (t[0] !== e[0] || t[1] !== e[1] || this.dirty) && (this.gl.blendFunc(t[0], t[1]), this.current = t, this.dirty = 0)
    }
}
class sn extends js {
    getDefault() {
        return pe.transparent
    }
    set(t) {
        const e = this.current;
        (t.r !== e.r || t.g !== e.g || t.b !== e.b || t.a !== e.a || this.dirty) && (this.gl.blendColor(t.r, t.g, t.b, t.a), this.current = t, this.dirty = 0)
    }
}
class nn extends js {
    getDefault() {
        return this.gl.FUNC_ADD
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.blendEquation(t), this.current = t, this.dirty = 0)
    }
}
class rn extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        t ? e.enable(e.CULL_FACE) : e.disable(e.CULL_FACE), this.current = t, this.dirty = 0
    }
}
class on extends js {
    getDefault() {
        return this.gl.BACK
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.cullFace(t), this.current = t, this.dirty = 0)
    }
}
class an extends js {
    getDefault() {
        return this.gl.CCW
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.frontFace(t), this.current = t, this.dirty = 0)
    }
}
class hn extends js {
    getDefault() {
        return null
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.useProgram(t), this.current = t, this.dirty = 0)
    }
}
class ln extends js {
    getDefault() {
        return this.gl.TEXTURE0
    }
    set(t) {
        (t !== this.current || this.dirty) && (this.gl.activeTexture(t), this.current = t, this.dirty = 0)
    }
}
class cn extends js {
    getDefault() {
        const t = this.gl;
        return [0, 0, t.drawingBufferWidth, t.drawingBufferHeight]
    }
    set(t) {
        const e = this.current;
        (t[0] !== e[0] || t[1] !== e[1] || t[2] !== e[2] || t[3] !== e[3] || this.dirty) && (this.gl.viewport(t[0], t[1], t[2], t[3]), this.current = t, this.dirty = 0)
    }
}
class un extends js {
    getDefault() {
        return null
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.bindFramebuffer(e.FRAMEBUFFER, t), this.current = t, this.dirty = 0
    }
}
class dn extends js {
    getDefault() {
        return null
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.bindRenderbuffer(e.RENDERBUFFER, t), this.current = t, this.dirty = 0
    }
}
class pn extends js {
    getDefault() {
        return null
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.bindTexture(e.TEXTURE_2D, t), this.current = t, this.dirty = 0
    }
}
class _n extends js {
    getDefault() {
        return null
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.bindBuffer(e.ARRAY_BUFFER, t), this.current = t, this.dirty = 0
    }
}
class mn extends js {
    getDefault() {
        return null
    }
    set(t) {
        const e = this.gl;
        e.bindBuffer(e.ELEMENT_ARRAY_BUFFER, t), this.current = t, this.dirty = 0
    }
}
class fn extends js {
    getDefault() {
        return null
    }
    set(t) {
        var e;
        if (t === this.current && !this.dirty) return;
        const i = this.gl;
        ze(i) ? i.bindVertexArray(t) : null === (e = i.getExtension("OES_vertex_array_object")) || void 0 === e || e.bindVertexArrayOES(t), this.current = t, this.dirty = 0
    }
}
class gn extends js {
    getDefault() {
        return 4
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.pixelStorei(e.UNPACK_ALIGNMENT, t), this.current = t, this.dirty = 0
    }
}
class yn extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL, t), this.current = t, this.dirty = 0
    }
}
class vn extends js {
    getDefault() {
        return 0
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        const e = this.gl;
        e.pixelStorei(e.UNPACK_FLIP_Y_WEBGL, t), this.current = t, this.dirty = 0
    }
}
class bn extends js {
    constructor(t, e) {
        super(t), this.context = t, this.parent = e
    }
    getDefault() {
        return null
    }
}
class xn extends bn {
    setDirty() {
        this.dirty = 1
    }
    set(t) {
        if (t === this.current && !this.dirty) return;
        this.context.bindFramebuffer.set(this.parent);
        const e = this.gl;
        e.framebufferTexture2D(e.FRAMEBUFFER, e.COLOR_ATTACHMENT0, e.TEXTURE_2D, t, 0), this.current = t, this.dirty = 0
    }
}
class wn extends bn {
    set(t) {
        if (t === this.current && !this.dirty) return;
        this.context.bindFramebuffer.set(this.parent);
        const e = this.gl;
        e.framebufferRenderbuffer(e.FRAMEBUFFER, e.DEPTH_ATTACHMENT, e.RENDERBUFFER, t), this.current = t, this.dirty = 0
    }
}
class Tn extends bn {
    set(t) {
        if (t === this.current && !this.dirty) return;
        this.context.bindFramebuffer.set(this.parent);
        const e = this.gl;
        e.framebufferRenderbuffer(e.FRAMEBUFFER, e.DEPTH_STENCIL_ATTACHMENT, e.RENDERBUFFER, t), this.current = t, this.dirty = 0
    }
}
class Mn {
    constructor(t, e, i, s, n) {
        this.context = t, this.width = e, this.height = i;
        const r = t.gl,
            o = this.framebuffer = r.createFramebuffer();
        if (this.colorAttachment = new xn(t, o), s) this.depthAttachment = n ? new Tn(t, o) : new wn(t, o);
        else if (n) throw Error("Stencil cannot be set without depth");
        if (r.checkFramebufferStatus(r.FRAMEBUFFER) !== r.FRAMEBUFFER_COMPLETE) throw Error("Framebuffer is not complete")
    }
    destroy() {
        const t = this.context.gl,
            e = this.colorAttachment.get();
        if (e && t.deleteTexture(e), this.depthAttachment) {
            const e = this.depthAttachment.get();
            e && t.deleteRenderbuffer(e)
        }
        t.deleteFramebuffer(this.framebuffer)
    }
}
class Pn {
    constructor(t, e, i) {
        this.blendFunction = t, this.blendColor = e, this.mask = i
    }
}
Pn.Replace = [1, 0], Pn.disabled = new Pn(Pn.Replace, pe.transparent, [0, 0, 0, 0]), Pn.unblended = new Pn(Pn.Replace, pe.transparent, [1, 1, 1, 1]), Pn.alphaBlended = new Pn([1, 771], pe.transparent, [1, 1, 1, 1]);
class En {
    get isWebGL2() {
        return this._isWebGL2
    }
    constructor(t) {
        var e, i;
        if (this.gl = t, this._isWebGL2 = ze(this.gl), this.clearColor = new Us(this), this.clearDepth = new Gs(this), this.clearStencil = new qs(this), this.colorMask = new $s(this), this.depthMask = new Ws(this), this.stencilMask = new Hs(this), this.stencilFunc = new Vs(this), this.stencilOp = new Xs(this), this.stencilTest = new Ks(this), this.depthRange = new Ys(this), this.depthTest = new Js(this), this.depthFunc = new Qs(this), this.blend = new tn(this), this.blendFunc = new en(this), this.blendColor = new sn(this), this.blendEquation = new nn(this), this.cullFace = new rn(this), this.cullFaceSide = new on(this), this.frontFace = new an(this), this.program = new hn(this), this.activeTexture = new ln(this), this.viewport = new cn(this), this.bindFramebuffer = new un(this), this.bindRenderbuffer = new dn(this), this.bindTexture = new pn(this), this.bindVertexBuffer = new _n(this), this.bindElementBuffer = new mn(this), this.bindVertexArray = new fn(this), this.pixelStoreUnpack = new gn(this), this.pixelStoreUnpackPremultiplyAlpha = new yn(this), this.pixelStoreUnpackFlipY = new vn(this), this.extTextureFilterAnisotropic = t.getExtension("EXT_texture_filter_anisotropic") || t.getExtension("MOZ_EXT_texture_filter_anisotropic") || t.getExtension("WEBKIT_EXT_texture_filter_anisotropic"), this.extTextureFilterAnisotropic && (this.extTextureFilterAnisotropicMax = t.getParameter(this.extTextureFilterAnisotropic.MAX_TEXTURE_MAX_ANISOTROPY_EXT)), this.maxTextureSize = t.getParameter(t.MAX_TEXTURE_SIZE), ze(t)) {
            this.HALF_FLOAT = t.HALF_FLOAT;
            const s = t.getExtension("EXT_color_buffer_half_float");
            this.RGBA16F = null !== (e = t.RGBA16F) && void 0 !== e ? e : null == s ? void 0 : s.RGBA16F_EXT, this.RGB16F = null !== (i = t.RGB16F) && void 0 !== i ? i : null == s ? void 0 : s.RGB16F_EXT, t.getExtension("EXT_color_buffer_float")
        } else {
            t.getExtension("EXT_color_buffer_half_float"), t.getExtension("OES_texture_half_float_linear");
            const e = t.getExtension("OES_texture_half_float");
            this.HALF_FLOAT = null == e ? void 0 : e.HALF_FLOAT_OES
        }
    }
    setDefault() {
        this.unbindVAO(), this.clearColor.setDefault(), this.clearDepth.setDefault(), this.clearStencil.setDefault(), this.colorMask.setDefault(), this.depthMask.setDefault(), this.stencilMask.setDefault(), this.stencilFunc.setDefault(), this.stencilOp.setDefault(), this.stencilTest.setDefault(), this.depthRange.setDefault(), this.depthTest.setDefault(), this.depthFunc.setDefault(), this.blend.setDefault(), this.blendFunc.setDefault(), this.blendColor.setDefault(), this.blendEquation.setDefault(), this.cullFace.setDefault(), this.cullFaceSide.setDefault(), this.frontFace.setDefault(), this.program.setDefault(), this.activeTexture.setDefault(), this.bindFramebuffer.setDefault(), this.pixelStoreUnpack.setDefault(), this.pixelStoreUnpackPremultiplyAlpha.setDefault(), this.pixelStoreUnpackFlipY.setDefault()
    }
    setDirty() {
        this.clearColor.dirty = 1, this.clearDepth.dirty = 1, this.clearStencil.dirty = 1, this.colorMask.dirty = 1, this.depthMask.dirty = 1, this.stencilMask.dirty = 1, this.stencilFunc.dirty = 1, this.stencilOp.dirty = 1, this.stencilTest.dirty = 1, this.depthRange.dirty = 1, this.depthTest.dirty = 1, this.depthFunc.dirty = 1, this.blend.dirty = 1, this.blendFunc.dirty = 1, this.blendColor.dirty = 1, this.blendEquation.dirty = 1, this.cullFace.dirty = 1, this.cullFaceSide.dirty = 1, this.frontFace.dirty = 1, this.program.dirty = 1, this.activeTexture.dirty = 1, this.viewport.dirty = 1, this.bindFramebuffer.dirty = 1, this.bindRenderbuffer.dirty = 1, this.bindTexture.dirty = 1, this.bindVertexBuffer.dirty = 1, this.bindElementBuffer.dirty = 1, this.bindVertexArray.dirty = 1, this.pixelStoreUnpack.dirty = 1, this.pixelStoreUnpackPremultiplyAlpha.dirty = 1, this.pixelStoreUnpackFlipY.dirty = 1
    }
    createIndexBuffer(t, e) {
        return new Fs(this, t, e)
    }
    createVertexBuffer(t, e, i) {
        return new Ns(this, t, e, i)
    }
    createRenderbuffer(t, e, i) {
        const s = this.gl,
            n = s.createRenderbuffer();
        return this.bindRenderbuffer.set(n), s.renderbufferStorage(s.RENDERBUFFER, t, e, i), this.bindRenderbuffer.set(null), n
    }
    createFramebuffer(t, e, i, s) {
        return new Mn(this, t, e, i, s)
    }
    clear({
        color: t,
        depth: e,
        stencil: i
    }) {
        const s = this.gl;
        let n = 0;
        t && (n |= s.COLOR_BUFFER_BIT, this.clearColor.set(t), this.colorMask.set([1, 1, 1, 1])), void 0 !== e && (n |= s.DEPTH_BUFFER_BIT, this.depthRange.set([0, 1]), this.clearDepth.set(e), this.depthMask.set(1)), void 0 !== i && (n |= s.STENCIL_BUFFER_BIT, this.clearStencil.set(i), this.stencilMask.set(255)), s.clear(n)
    }
    setCullFace(t) {
        0 == t.enable ? this.cullFace.set(0) : (this.cullFace.set(1), this.cullFaceSide.set(t.mode), this.frontFace.set(t.frontFace))
    }
    setDepthMode(t) {
        t.func !== this.gl.ALWAYS || t.mask ? (this.depthTest.set(1), this.depthFunc.set(t.func), this.depthMask.set(t.mask), this.depthRange.set(t.range)) : this.depthTest.set(0)
    }
    setStencilMode(t) {
        t.test.func !== this.gl.ALWAYS || t.mask ? (this.stencilTest.set(1), this.stencilMask.set(t.mask), this.stencilOp.set([t.fail, t.depthFail, t.pass]), this.stencilFunc.set({
            func: t.test.func,
            ref: t.ref,
            mask: t.test.mask
        })) : this.stencilTest.set(0)
    }
    setColorMode(t) {
        K(t.blendFunction, Pn.Replace) ? this.blend.set(0) : (this.blend.set(1), this.blendFunc.set(t.blendFunction), this.blendColor.set(t.blendColor)), this.colorMask.set(t.mask)
    }
    createVertexArray() {
        var t;
        return ze(this.gl) ? this.gl.createVertexArray() : null === (t = this.gl.getExtension("OES_vertex_array_object")) || void 0 === t ? void 0 : t.createVertexArrayOES()
    }
    deleteVertexArray(t) {
        var e;
        return ze(this.gl) ? this.gl.deleteVertexArray(t) : null === (e = this.gl.getExtension("OES_vertex_array_object")) || void 0 === e ? void 0 : e.deleteVertexArrayOES(t)
    }
    unbindVAO() {
        this.bindVertexArray.set(null)
    }
}
class Ln {
    constructor(t, e, i) {
        this.func = t, this.mask = e, this.range = i
    }
}
Ln.ReadOnly = 0, Ln.ReadWrite = 1, Ln.disabled = new Ln(519, Ln.ReadOnly, [0, 1]);
const Cn = 7680;
class Sn {
    constructor(t, e, i, s, n, r) {
        this.test = t, this.ref = e, this.mask = i, this.fail = s, this.depthFail = n, this.pass = r
    }
}
Sn.disabled = new Sn({
    func: 519,
    mask: 0
}, 0, 0, Cn, Cn, Cn);
const Rn = 2305;
class In {
    constructor(t, e, i) {
        this.enable = t, this.mode = e, this.frontFace = i
    }
}
In.disabled = new In(0, 1029, Rn), In.backCCW = new In(1, 1029, Rn), In.frontCCW = new In(1, 1028, Rn);
const An = [new h(0, 0), new h(D, 0), new h(D, D), new h(0, D)];

function zn(t, e, i, s, n, r, o, a, h = 0) {
    var l, u;
    const d = null !== (l = i.customShaderId) && void 0 !== l ? l : "raster",
        p = s[s.length - 1].overscaledZ,
        _ = t.context,
        m = _.gl,
        f = t.useProgram(d),
        g = t.transform,
        y = t.style.projection,
        v = t.colorModeForRenderPass(),
        b = !t.options.moving;
    for (const l of s) {
        const s = t.getDepthModeForSublayer(l.overscaledZ - p, Ln.ReadWrite, m.LESS),
            d = e.getTile(l);
        d.registerFadeDuration(300);
        const x = e.findLoadedParent(l, 0),
            w = e.findLoadedSibling(l),
            T = On(d, x || w || null, e, i, t.transform);
        let M, P;
        const E = null !== (u = i.tileFilter) && void 0 !== u ? u : m.LINEAR;
        _.activeTexture.set(m.TEXTURE0), d.texture.bind(E, m.CLAMP_TO_EDGE, m.LINEAR_MIPMAP_NEAREST), _.activeTexture.set(m.TEXTURE1), x ? (x.texture.bind(E, m.CLAMP_TO_EDGE, m.LINEAR_MIPMAP_NEAREST), M = Math.pow(2, x.tileID.overscaledZ - d.tileID.overscaledZ), P = [d.tileID.canonical.x * M % 1, d.tileID.canonical.y * M % 1]) : d.texture.bind(E, m.CLAMP_TO_EDGE, m.LINEAR_MIPMAP_NEAREST), d.texture.useMipmap && _.extTextureFilterAnisotropic && t.transform.pitch > 20 && m.texParameterf(m.TEXTURE_2D, _.extTextureFilterAnisotropic.TEXTURE_MAX_ANISOTROPY_EXT, _.extTextureFilterAnisotropicMax);
        const L = g.getProjectionData(l, b),
            C = Se(P || [0, 0], M || 1, T, i, a),
            S = y.getMeshFromTileID(_, l.canonical, r, o, "raster"),
            R = n ? n[l.overscaledZ] : Sn.disabled,
            I = new c(l.canonical.x, l.canonical.y, l.canonical.z);
        i.preRenderTileCallback && i.preRenderTileCallback(m, f.program, I, i.id), f.draw(_, m.TRIANGLES, s, R, v, h ? In.frontCCW : In.backCCW, C, L, i.id, S.vertexBuffer, S.indexBuffer, S.segments), i.postRenderTileCallback && i.postRenderTileCallback(m, I)
    }
}

function On(t, e, i, s, n) {
    var r;
    const o = null !== (r = s.paint["raster-fade-duration"]) && void 0 !== r ? r : 300;
    if (o > 0) {
        const s = ht.now(),
            r = (s - t.timeAdded) / o,
            a = e ? (s - e.timeAdded) / o : -1,
            h = i.getSource(),
            l = n.coveringZoomLevel({
                tileSize: h.tileSize,
                roundZoom: h.roundZoom
            }),
            c = !e || Math.abs(e.tileID.overscaledZ - l) > Math.abs(t.tileID.overscaledZ - l),
            u = c && t.refreshedUponExpiration ? 1 : U(c ? r : 1 - a, 0, 1);
        return t.refreshedUponExpiration && r >= 1 && (t.refreshedUponExpiration = 0), e ? {
            opacity: 1,
            mix: 1 - u
        } : {
            opacity: u,
            mix: 0
        }
    }
    return {
        opacity: 1,
        mix: 0
    }
}

function kn(t, e, i) {
    const s = t.context,
        n = s.gl,
        r = t.useProgram("debug"),
        o = Ln.disabled,
        a = Sn.disabled,
        h = t.colorModeForRenderPass(),
        l = "$debug";
    s.activeTexture.set(n.TEXTURE0);
    const c = e.getTileByID(i.key).latestRawTileData,
        u = Math.floor((c && c.byteLength || 0) / 1024),
        d = e.getTile(i).tileSize,
        p = 512 / Math.min(d, 512) * (i.overscaledZ / t.transform.zoom) * .5;
    let _ = "" + i.canonical;
    i.overscaledZ !== i.canonical.z && (_ += " => " + i.overscaledZ),
        function(t, e) {
            t.initDebugOverlayCanvas();
            const i = t.debugOverlayCanvas,
                s = t.context.gl,
                n = t.debugOverlayCanvas.getContext("2d");
            n.clearRect(0, 0, i.width, i.height), n.shadowColor = "white", n.shadowBlur = 2, n.lineWidth = 1.5, n.strokeStyle = "white", n.textBaseline = "top", n.font = "bold 36px Open Sans, sans-serif", n.fillText(e, 5, 5), n.strokeText(e, 5, 5), t.debugOverlayTexture.update(i), t.debugOverlayTexture.bind(s.LINEAR, s.CLAMP_TO_EDGE)
        }(t, `${_} ${u}kB`);
    const m = t.transform.getProjectionData(i, 1, 1);
    r.draw(s, n.TRIANGLES, o, a, Pn.alphaBlended, In.disabled, Ce(pe.transparent, p), m, l, t.debugBuffer, t.quadTriangleIndexBuffer, t.debugSegments), r.draw(s, n.LINE_STRIP, o, a, h, In.disabled, Ce(pe.red), m, l, t.debugBuffer, t.tileBorderIndexBuffer, t.debugSegments)
}
new pe(1, 0, 0, 1), new pe(0, 1, 0, 1), new pe(0, 0, 1, 1), new pe(1, 0, 1, 1), new pe(0, 1, 1, 1);
class Dn {
    constructor(t, e) {
        this.context = new En(t), this.transform = e, this._tileTextures = {}, this.setup(), this.numSublayers = oe.maxUnderzooming + oe.maxOverzooming + 1, this.depthEpsilon = 1 / 65536
    }
    resize(t, e, i) {
        if (this.width = Math.floor(t * i), this.height = Math.floor(e * i), this.pixelRatio = i, this.context.viewport.set([0, 0, this.width, this.height]), this.style)
            for (const t of this.style._order) this.style._layers[t].resize()
    }
    setup() {
        const t = this.context,
            e = new ns;
        e.emplaceBack(0, 0), e.emplaceBack(D, 0), e.emplaceBack(0, D), e.emplaceBack(D, D), this.debugBuffer = t.createVertexBuffer(e, hs.members), this.debugSegments = as.simpleSegment(0, 0, 4, 5);
        const i = new ns;
        i.emplaceBack(0, 0), i.emplaceBack(1, 0), i.emplaceBack(0, 1), i.emplaceBack(1, 1), this.viewportBuffer = t.createVertexBuffer(i, hs.members), this.viewportSegments = as.simpleSegment(0, 0, 4, 2);
        const s = new os;
        s.emplaceBack(0), s.emplaceBack(1), s.emplaceBack(3), s.emplaceBack(2), s.emplaceBack(0), this.tileBorderIndexBuffer = t.createIndexBuffer(s);
        const n = new rs;
        n.emplaceBack(1, 0, 2), n.emplaceBack(1, 2, 3), this.quadTriangleIndexBuffer = t.createIndexBuffer(n);
        const r = this.context.gl;
        this.stencilClearMode = new Sn({
            func: r.ALWAYS,
            mask: 0
        }, 0, 255, r.ZERO, r.ZERO, r.ZERO)
    }
    clearStencil() {
        const t = this.context,
            e = t.gl;
        this.nextStencilID = 1, this.currentStencilSource = void 0;
        const i = function() {
            var t = new f(16);
            return f != Float32Array && (t[1] = 0, t[2] = 0, t[3] = 0, t[4] = 0, t[6] = 0, t[7] = 0, t[8] = 0, t[9] = 0, t[11] = 0, t[12] = 0, t[13] = 0, t[14] = 0), t[0] = 1, t[5] = 1, t[10] = 1, t[15] = 1, t
        }();
        (function(t, e, i, s) {
            var n = 1 / (0 - i),
                r = 1 / (s - 0);
            t[0] = -2 * n, t[1] = 0, t[2] = 0, t[3] = 0, t[4] = 0, t[5] = -2 * r, t[6] = 0, t[7] = 0, t[8] = 0, t[9] = 0, t[10] = -2, t[11] = 0, t[12] = (0 + i) * n, t[13] = (0 + s) * r, t[14] = -1, t[15] = 1
        })(i, 0, this.width, this.height), x(i, i, [e.drawingBufferWidth, e.drawingBufferHeight, 0]);
        const s = {
            mainMatrix: i,
            tileMercatorCoords: [0, 0, 1, 1],
            clippingPlane: [0, 0, 0, 0],
            projectionTransition: 0,
            fallbackMatrix: i
        };
        this.useProgram("clippingMask", 1).draw(t, e.TRIANGLES, Ln.disabled, this.stencilClearMode, Pn.disabled, In.disabled, null, s, "$clipping", this.viewportBuffer, this.quadTriangleIndexBuffer, this.viewportSegments)
    }
    _renderTileClippingMasks(t, e, i) {
        if (this.currentStencilSource === t.source || !t.isTileClipped() || !e || !e.length) return;
        this.currentStencilSource = t.source, this.nextStencilID + e.length > 256 && this.clearStencil();
        const s = this.context;
        s.setColorMode(Pn.disabled), s.setDepthMode(Ln.disabled);
        const n = {};
        for (const t of e) n[t.key] = this.nextStencilID++;
        this._renderTileMasks(n, e, i, 1), this._renderTileMasks(n, e, i, 0), this._tileClippingMaskIDs = n
    }
    _renderTileMasks(t, e, i, s) {
        const n = this.context,
            r = n.gl,
            o = this.style.projection,
            a = this.transform,
            h = this.useProgram("clippingMask");
        for (const l of e) {
            const e = t[l.key],
                c = o.getMeshFromTileID(this.context, l.canonical, s, 1, "stencil"),
                u = a.getProjectionData(l);
            h.draw(n, r.TRIANGLES, Ln.disabled, new Sn({
                func: r.ALWAYS,
                mask: 0
            }, e, 255, r.KEEP, r.KEEP, r.REPLACE), Pn.disabled, i ? In.disabled : In.backCCW, null, u, "$clipping", c.vertexBuffer, c.indexBuffer, c.segments)
        }
    }
    _renderTilesDepthBuffer() {
        const t = this.context,
            e = t.gl,
            i = this.style.projection,
            s = this.transform,
            n = this.useProgram("depth"),
            r = this.getDepthModeFor3D(),
            o = s.coveringTiles({
                tileSize: s.tileSize
            });
        for (const a of o) {
            const o = i.getMeshFromTileID(this.context, a.canonical, 1, 1, "raster"),
                h = s.getProjectionData(a);
            n.draw(t, e.TRIANGLES, r, Sn.disabled, Pn.disabled, In.backCCW, null, h, "$clipping", o.vertexBuffer, o.indexBuffer, o.segments)
        }
    }
    stencilModeFor3D() {
        this.currentStencilSource = void 0, this.nextStencilID + 1 > 256 && this.clearStencil();
        const t = this.nextStencilID++,
            e = this.context.gl;
        return new Sn({
            func: e.NOTEQUAL,
            mask: 255
        }, t, 255, e.KEEP, e.KEEP, e.REPLACE)
    }
    stencilModeForClipping(t) {
        const e = this.context.gl;
        return new Sn({
            func: e.EQUAL,
            mask: 255
        }, this._tileClippingMaskIDs[t.key], 0, e.KEEP, e.KEEP, e.REPLACE)
    }
    stencilConfigForOverlap(t) {
        const e = this.context.gl,
            i = t.sort((t, e) => e.overscaledZ - t.overscaledZ),
            s = i[i.length - 1].overscaledZ,
            n = i[0].overscaledZ - s + 1;
        if (n > 1) {
            this.currentStencilSource = void 0, this.nextStencilID + n > 256 && this.clearStencil();
            const t = {};
            for (let i = 0; i < n; i++) t[i + s] = new Sn({
                func: e.GEQUAL,
                mask: 255
            }, i + this.nextStencilID, 255, e.KEEP, e.KEEP, e.REPLACE);
            return this.nextStencilID += n, [t, i]
        }
        return [{
            [s]: Sn.disabled
        }, i]
    }
    stencilConfigForOverlapTwoPass(t) {
        const e = this.context.gl,
            i = t.sort((t, e) => e.overscaledZ - t.overscaledZ),
            s = i[i.length - 1].overscaledZ,
            n = i[0].overscaledZ - s + 1;
        if (this.clearStencil(), n > 1) {
            const t = {},
                r = {};
            for (let i = 0; i < n; i++) t[i + s] = new Sn({
                func: e.GREATER,
                mask: 255
            }, n + 1 + i, 255, e.KEEP, e.KEEP, e.REPLACE), r[i + s] = new Sn({
                func: e.GREATER,
                mask: 255
            }, 1 + i, 255, e.KEEP, e.KEEP, e.REPLACE);
            return this.nextStencilID = 2 * n + 1, [t, r, i]
        }
        return this.nextStencilID = 3, [{
            [s]: new Sn({
                func: e.GREATER,
                mask: 255
            }, 2, 255, e.KEEP, e.KEEP, e.REPLACE)
        }, {
            [s]: new Sn({
                func: e.GREATER,
                mask: 255
            }, 1, 255, e.KEEP, e.KEEP, e.REPLACE)
        }, i]
    }
    colorModeForRenderPass() {
        return "opaque" === this.renderPass ? Pn.unblended : Pn.alphaBlended
    }
    getDepthModeForSublayer(t, e, i) {
        if (!this.opaquePassEnabledForLayer()) return Ln.disabled;
        const s = 1 - ((1 + this.currentLayer) * this.numSublayers + t) * this.depthEpsilon;
        return new Ln(i || this.context.gl.LEQUAL, e, [s, s])
    }
    getDepthModeFor3D() {
        return new Ln(this.context.gl.LEQUAL, Ln.ReadWrite, this.depthRangeFor3D)
    }
    opaquePassEnabledForLayer() {
        return this.currentLayer < this.opaquePassCutoff
    }
    render(t, e) {
        this.style = t, this.options = e;
        const i = this.style._order,
            s = this.style.sourceCaches,
            n = {},
            r = {};
        for (const t in s) n[t] = s[t].getVisibleCoordinates(), r[t] = n[t].slice().reverse();
        this.opaquePassCutoff = 1 / 0;
        for (let t = 0; t < i.length; t++)
            if (this.style._layers[i[t]].is3D()) {
                this.opaquePassCutoff = t;
                break
            } this.renderPass = "offscreen";
        for (const t of i) {
            const e = this.style._layers[t];
            if (!e.hasOffscreenPass() || e.isHidden(this.transform.zoom)) continue;
            const i = r[e.source];
            ("custom" === e.type || i.length) && this.renderLayer(this, s[e.source], e, i)
        }
        for (this.style.projection.updateGPUdependent({
                context: this.context,
                useProgram: t => this.useProgram(t)
            }), this.context.viewport.set([0, 0, this.width, this.height]), this.context.bindFramebuffer.set(null), this.context.clear({
                color: pe.transparent,
                depth: 1
            }), this.clearStencil(), this.depthRangeFor3D = [0, 1 - (t._order.length + 2) * this.numSublayers * this.depthEpsilon], this.renderPass = "opaque", this.currentLayer = i.length - 1; this.currentLayer >= 0; this.currentLayer--) {
            const t = this.style._layers[i[this.currentLayer]],
                e = s[t.source],
                r = n[t.source];
            this._renderTileClippingMasks(t, r, 0), this.renderLayer(this, e, t, r)
        }
        this.renderPass = "translucent";
        let o = 0;
        for (this.currentLayer = 0; this.currentLayer < i.length; this.currentLayer++) {
            const t = this.style._layers[i[this.currentLayer]],
                e = s[t.source];
            this.opaquePassEnabledForLayer() || o || (o = 1);
            const a = r[t.source];
            this._renderTileClippingMasks(t, n[t.source], 0), this.renderLayer(this, e, t, a)
        }
        if (this.options.showTileBoundaries) {
            const t = function(t, e) {
                let i = null;
                const s = Object.values(t._layers).flatMap(i => i.source && !i.isHidden(e) ? [t.sourceCaches[i.source]] : []),
                    n = s.filter(t => "vector" === t.getSource().type),
                    r = s.filter(t => "vector" !== t.getSource().type),
                    o = t => {
                        (!i || i.getSource().maxzoom < t.getSource().maxzoom) && (i = t)
                    };
                return n.forEach(t => o(t)), i || r.forEach(t => o(t)), i
            }(this.style, this.transform.zoom);
            t && function(t, e, i) {
                for (let s = 0; s < i.length; s++) kn(t, e, i[s])
            }(this, t, t.getVisibleCoordinates())
        }
        this.context.setDefault()
    }
    renderLayer(t, e, i, s) {
        if (!i.isHidden(this.transform.zoom) && ("background" === i.type || "custom" === i.type || "canvas" === i.type || (s || []).length)) switch (this.id = i.id, i.type) {
            case "raster":
                ! function(t, e, i, s) {
                    if ("translucent" !== t.renderPass) return;
                    if (!s.length) return;
                    if (t.style.projection.useSubdivision) {
                        const [n, r, o] = t.stencilConfigForOverlapTwoPass(s);
                        zn(t, e, i, o, n, 0, 1, An), zn(t, e, i, o, r, 1, 1, An)
                    } else {
                        const [n, r] = t.stencilConfigForOverlap(s);
                        zn(t, e, i, r, n, 0, 1, An)
                    }
                    const n = t.context.gl;
                    n.bindTexture(n.TEXTURE_2D, null)
                }(t, e, i, s);
                break;
            case "background":
                ! function(t, e, i, s) {
                    const n = new pe(1, 1, 1, 1),
                        r = t.context,
                        o = r.gl,
                        a = t.style.projection,
                        h = t.transform,
                        l = h.tileSize,
                        c = 1 === n.a && t.opaquePassEnabledForLayer() ? "opaque" : "translucent";
                    if (t.renderPass !== c) return;
                    const u = Sn.disabled,
                        d = t.getDepthModeForSublayer(0, "opaque" === c ? Ln.ReadWrite : Ln.ReadOnly),
                        p = t.colorModeForRenderPass(),
                        _ = t.useProgram("background"),
                        m = s || h.coveringTiles({
                            tileSize: l
                        });
                    for (const t of m) {
                        const e = h.getProjectionData(t),
                            s = Ie(1, n),
                            l = a.getMeshFromTileID(r, t.canonical, 0, 1, "raster");
                        _.draw(r, o.TRIANGLES, d, u, p, In.backCCW, s, e, i.id, l.vertexBuffer, l.indexBuffer, l.segments)
                    }
                }(t, 0, i, s);
                break;
            case "custom":
                ! function(t, e, i) {
                    const s = t.context,
                        n = i.implementation,
                        r = t.style.projection,
                        o = t.transform,
                        a = o.getProjectionDataForCustomLayer(),
                        h = {
                            farZ: o.farZ,
                            nearZ: o.nearZ,
                            fov: o.fov * Math.PI / 180,
                            modelViewProjectionMatrix: o.modelViewProjectionMatrix,
                            projectionMatrix: o.projectionMatrix,
                            shaderData: {
                                variantName: r.shaderVariantName,
                                vertexShaderPrelude: "const float PI = 3.141592653589793;\nuniform mat4 u_projection_matrix;\n" + r.shaderPreludeCode.vertexSource,
                                define: r.shaderDefine
                            },
                            defaultProjectionData: a
                        },
                        l = n.renderingMode ? n.renderingMode : "2d";
                    if ("offscreen" === t.renderPass) {
                        const e = n.prerender;
                        e && (t.setCustomLayerDefaults(), s.setColorMode(t.colorModeForRenderPass()), e.call(n, s.gl, h), s.setDirty(), t.setBaseState())
                    } else if ("translucent" === t.renderPass) {
                        t.setCustomLayerDefaults(), s.setColorMode(t.colorModeForRenderPass()), s.setStencilMode(Sn.disabled);
                        const e = "3d" === l ? t.getDepthModeFor3D() : t.getDepthModeForSublayer(0, Ln.ReadOnly);
                        s.setDepthMode(e), n.render(s.gl, h), s.setDirty(), t.setBaseState(), s.bindFramebuffer.set(null)
                    }
                }(t, 0, i);
                break;
            case "canvas":
                ! function(t, e) {
                    var i;
                    if ("translucent" !== t.renderPass) return;
                    const s = e.canvasLayer;
                    if (!e.canvasLayer.leafletMap) throw new a;
                    const n = e.canvasLayer.leafletMap.getZoom(),
                        r = s.options;
                    if (void 0 !== r.minZoom && n < r.minZoom || void 0 !== r.maxZoom && n >= r.maxZoom + 1) return;
                    const o = t.context,
                        h = o.gl,
                        l = t.useProgram("canvas"),
                        c = t.transform,
                        u = Pn.alphaBlended,
                        d = new Ln(h.ALWAYS, 0, [0, 0]),
                        p = Sn.disabled;
                    o.activeTexture.set(h.TEXTURE0), h.bindTexture(h.TEXTURE_2D, s.texture);
                    const _ = (t => {
                            var e;
                            const i = null !== (e = t.paint["raster-opacity"]) && void 0 !== e ? e : 1;
                            return {
                                u_tex: 0,
                                u_opacity: null != i ? i : 1
                            }
                        })(e),
                        m = c.getProjectionData(new ne(0, 0, 0, 0, 0)),
                        f = s.lastRenderedArea;
                    if (!f) return;
                    let g = null !== (i = s.lastTopLeftOffset) && void 0 !== i ? i : 0,
                        y = c.coordinatePoint(new $t(f.min.x + g, f.min.y));
                    if (void 0 !== s.lastTopLeftPixelX) {
                        const t = c.coordinatePoint(new $t(f.min.x + g + 1, f.min.y)),
                            e = g - Math.round((y.x - s.lastTopLeftPixelX) / (t.x - y.x));
                        e !== g && (g = e, y = c.coordinatePoint(new $t(f.min.x + g, f.min.y)))
                    }
                    s.lastTopLeftPixelX = y.x, s.lastTopLeftOffset = g;
                    const v = c.coordinatePoint(new $t(f.max.x + g, f.max.y)),
                        b = y.divByPoint({
                            x: c.width,
                            y: c.height
                        }).mult(2).sub({
                            x: 1,
                            y: 1
                        }),
                        x = v.divByPoint({
                            x: c.width,
                            y: c.height
                        }).mult(2).sub({
                            x: 1,
                            y: 1
                        }),
                        w = Z();
                    w[12] = b.x, w[13] = b.y, w[0] = x.x - b.x, w[5] = x.y - b.y;
                    const T = 2 / t.width,
                        M = 2 / t.height,
                        P = .5 * T,
                        E = .5 * M;
                    if (Math.abs(b.x + 1) < P && Math.abs(b.y + 1) < E && Math.abs(x.x - 1) < P && Math.abs(x.y - 1) < E) w[12] = -1, w[13] = -1, w[0] = 2, w[5] = 2;
                    else if (s.lastRenderedZoom === t.transform.zoom) {
                        const t = (b.x - 1) / T,
                            e = (b.y - 1) / M;
                        w[12] -= (t - Math.round(t)) * T, w[13] -= (e - Math.round(e)) * M
                    }
                    w[5] *= -1, w[13] *= -1, m.mainMatrix = w, m.fallbackMatrix = w, l.draw(o, h.TRIANGLES, d, p, u, In.backCCW, _, m, e.id, t.viewportBuffer, t.quadTriangleIndexBuffer, t.viewportSegments)
                }(t, i)
        }
    }
    saveTileTexture(t) {
        const e = this._tileTextures[t.size[0]];
        e ? e.push(t) : this._tileTextures[t.size[0]] = [t]
    }
    getTileTexture(t) {
        const e = this._tileTextures[t];
        return e && e.length > 0 ? e.pop() : null
    }
    useProgram(t, e = 0) {
        this.cache = this.cache || {};
        const i = this.style.projection,
            s = t + "/" + (e ? ds : i.shaderVariantName);
        return this.cache[s] || (this.cache[s] = new Bs(this.context, Zi[t], Fi[t], e ? Zi.projectionMercator : i.shaderPreludeCode, e ? us : i.shaderDefine)), this.cache[s]
    }
    setCustomLayerDefaults() {
        this.context.unbindVAO(), this.context.cullFace.setDefault(), this.context.activeTexture.setDefault(), this.context.pixelStoreUnpack.setDefault(), this.context.pixelStoreUnpackPremultiplyAlpha.setDefault(), this.context.pixelStoreUnpackFlipY.setDefault()
    }
    setBaseState() {
        const t = this.context.gl;
        this.context.cullFace.set(0), this.context.viewport.set([0, 0, this.width, this.height]), this.context.blendEquation.set(t.FUNC_ADD)
    }
    initDebugOverlayCanvas() {
        null == this.debugOverlayCanvas && (this.debugOverlayCanvas = document.createElement("canvas"), this.debugOverlayCanvas.width = 512, this.debugOverlayCanvas.height = 512, this.debugOverlayTexture = new Vt(this.context, this.debugOverlayCanvas, this.context.gl.RGBA))
    }
    destroy() {
        this.debugOverlayTexture && this.debugOverlayTexture.destroy();
        const t = this.context.gl.getExtension("WEBGL_lose_context");
        (null == t ? void 0 : t.loseContext) && t.loseContext(), this.context.gl.canvas.remove(), this.context.gl = null
    }
    overLimit() {
        const {
            drawingBufferWidth: t,
            drawingBufferHeight: e
        } = this.context.gl;
        return this.width !== t || this.height !== e
    }
}

function Bn(t, e) {
    let i, s = 0,
        n = null,
        r = null;
    const o = () => {
        n = null, s && (t.apply(r, i), n = setTimeout(o, e), s = 0)
    };
    return (...t) => (s = 1, r = this, i = t, n || o(), n)
}
class Fn {
    constructor(t) {
        this._getCurrentHash = () => {
            const t = window.location.hash.replace("#", "");
            if (this._hashName) {
                let e;
                return t.split("&").map(t => t.split("=")).forEach(t => {
                    t[0] === this._hashName && (e = t)
                }), (e && e[1] || "").split("/")
            }
            return t.split("/")
        }, this._onHashChange = () => {
            const t = this._getCurrentHash();
            if (t.length >= 3 && !t.some(t => isNaN(t))) {
                const e = this._map.dragRotate.isEnabled() && this._map.touchZoomRotate.isEnabled() ? +(t[3] || 0) : this._map.getBearing();
                return this._map.jumpTo({
                    center: [+t[2], +t[1]],
                    zoom: +t[0],
                    bearing: e,
                    pitch: +(t[4] || 0)
                }), 1
            }
            return 0
        }, this._updateHashUnthrottled = () => {
            const t = window.location.href.replace(/(#.*)?$/, this.getHashString());
            window.history.replaceState(window.history.state, null, t)
        }, this._removeHash = () => {
            const t = this._getCurrentHash();
            if (0 === t.length) return;
            const e = t.join("/");
            let i = e;
            i.split("&").length > 0 && (i = i.split("&")[0]), this._hashName && (i = `${this._hashName}=${e}`);
            let s = window.location.hash.replace(i, "");
            s.startsWith("#&") ? s = s.slice(0, 1) + s.slice(2) : "#" === s && (s = "");
            let n = window.location.href.replace(/(#.+)?$/, s);
            n = n.replace("&&", "&"), window.history.replaceState(window.history.state, null, n)
        }, this._updateHash = Bn(this._updateHashUnthrottled, 300), this._hashName = t && encodeURIComponent(t)
    }
    addTo(t) {
        return this._map = t, addEventListener("hashchange", this._onHashChange, 0), this._map.on("moveend", this._updateHash), this
    }
    remove() {
        return removeEventListener("hashchange", this._onHashChange, 0), this._map.off("moveend", this._updateHash), clearTimeout(this._updateHash()), this._removeHash(), delete this._map, this
    }
    getHashString(t) {
        const e = this._map.getCenter(),
            i = Math.round(100 * this._map.getZoom()) / 100,
            s = Math.pow(10, Math.ceil((i * Math.LN2 + 1.0453677741492975) / Math.LN10)),
            n = Math.round(e.lng * s) / s,
            r = Math.round(e.lat * s) / s,
            o = this._map.getBearing(),
            a = this._map.getPitch();
        let h = "";
        if (h += t ? `/${n}/${r}/${i}` : `${i}/${r}/${n}`, (o || a) && (h += "/" + Math.round(10 * o) / 10), a && (h += "/" + Math.round(a)), this._hashName) {
            const t = this._hashName;
            let e = 0;
            const i = window.location.hash.slice(1).split("&").map(i => {
                const s = i.split("=")[0];
                return s === t ? (e = 1, `${s}=${h}`) : i
            }).filter(t => t);
            return e || i.push(`${t}=${h}`), "#" + i.join("&")
        }
        return "#" + h
    }
}
const Zn = {
        linearity: .3,
        easing: N(0, 0, .3, 1)
    },
    Nn = q({
        deceleration: 2500,
        maxSpeed: 1400
    }, Zn),
    jn = q({
        deceleration: 20,
        maxSpeed: 1400
    }, Zn),
    Un = q({
        deceleration: 1e3,
        maxSpeed: 360
    }, Zn),
    Gn = q({
        deceleration: 1e3,
        maxSpeed: 90
    }, Zn),
    qn = q({
        deceleration: 1e3,
        maxSpeed: 360
    }, Zn);
class $n {
    constructor(t) {
        this._map = t, this.clear()
    }
    clear() {
        this._inertiaBuffer = []
    }
    record(t) {
        this._drainInertiaBuffer(), this._inertiaBuffer.push({
            time: ht.now(),
            settings: t
        })
    }
    _drainInertiaBuffer() {
        const t = this._inertiaBuffer,
            e = ht.now();
        for (; t.length > 0 && e - t[0].time > 160;) t.shift()
    }
    _onMoveEnd(t) {
        if (this._drainInertiaBuffer(), this._inertiaBuffer.length < 2) return;
        const e = {
            zoom: 0,
            bearing: 0,
            pitch: 0,
            roll: 0,
            pan: new h(0, 0),
            pinchAround: void 0,
            around: void 0
        };
        for (const {
                settings: t
            }
            of this._inertiaBuffer) e.zoom += t.zoomDelta || 0, e.bearing += t.bearingDelta || 0, e.pitch += t.pitchDelta || 0, e.roll += t.rollDelta || 0, t.panDelta && e.pan._add(t.panDelta), t.around && (e.around = t.around), t.pinchAround && (e.pinchAround = t.pinchAround);
        const i = this._inertiaBuffer[this._inertiaBuffer.length - 1].time - this._inertiaBuffer[0].time,
            s = {};
        if (e.pan.mag()) {
            const n = Hn(e.pan.mag(), i, q({}, Nn, t || {})),
                r = e.pan.mult(n.amount / e.pan.mag()),
                o = this._map.cameraHelper.handlePanInertia(r, this._map.transform);
            s.center = o.easingCenter, s.offset = o.easingOffset, Wn(s, n)
        }
        if (e.zoom) {
            const t = Hn(e.zoom, i, jn);
            s.zoom = this._map.transform.zoom + t.amount, Wn(s, t)
        }
        if (e.bearing) {
            const t = Hn(e.bearing, i, Un);
            s.bearing = this._map.transform.bearing + U(t.amount, -179, 179), Wn(s, t)
        }
        if (e.pitch) {
            const t = Hn(e.pitch, i, Gn);
            s.pitch = this._map.transform.pitch + t.amount, Wn(s, t)
        }
        if (e.roll) {
            const t = Hn(e.roll, i, qn);
            s.roll = this._map.transform.roll + U(t.amount, -179, 179), Wn(s, t)
        }
        if (s.zoom || s.bearing) {
            const t = void 0 === e.pinchAround ? e.around : e.pinchAround;
            s.around = t ? this._map.unproject(t) : this._map.getCenter()
        }
        return this.clear(), q(s, {
            noMoveStart: 1
        })
    }
}

function Wn(t, e) {
    (!t.duration || t.duration < e.duration) && (t.duration = e.duration, t.easing = e.easing)
}

function Hn(t, e, i) {
    const {
        maxSpeed: s,
        linearity: n,
        deceleration: r
    } = i, o = U(t * n / (e / 1e3), -s, s), a = Math.abs(o) / (r * n);
    return {
        easing: i.easing,
        duration: 1e3 * a,
        amount: o * (a / 2)
    }
}
class Vn extends St {
    preventDefault() {
        this._defaultPrevented = 1
    }
    get defaultPrevented() {
        return this._defaultPrevented
    }
    constructor(t, e, i, s = {}) {
        const n = lt.mousePos(e.getCanvas(), i);
        super(t, q({
            point: n,
            lngLat: e.unproject(n),
            originalEvent: i
        }, s)), this._defaultPrevented = 0, this.target = e
    }
}
class Xn extends St {
    preventDefault() {
        this._defaultPrevented = 1
    }
    get defaultPrevented() {
        return this._defaultPrevented
    }
    constructor(t, e, i) {
        const s = "touchend" === t ? i.changedTouches : i.touches,
            n = lt.touchPos(e.getCanvasContainer(), s),
            r = n.map(t => e.unproject(t)),
            o = n.reduce((t, e, i, s) => t.add(e.div(s.length)), new h(0, 0));
        super(t, {
            points: n,
            point: o,
            lngLats: r,
            lngLat: e.unproject(o),
            originalEvent: i
        }), this._defaultPrevented = 0
    }
}
class Kn extends St {
    preventDefault() {
        this._defaultPrevented = 1
    }
    get defaultPrevented() {
        return this._defaultPrevented
    }
    constructor(t, e, i) {
        super(t, {
            originalEvent: i
        }), this._defaultPrevented = 0
    }
}
class Yn {
    constructor(t, e) {
        this._map = t, this._clickTolerance = e.clickTolerance
    }
    reset() {
        delete this._mousedownPos
    }
    wheel(t) {
        return this._firePreventable(new Kn(t.type, this._map, t))
    }
    mousedown(t, e) {
        return this._mousedownPos = e, this._firePreventable(new Vn(t.type, this._map, t))
    }
    mouseup(t) {
        this._map.fire(new Vn(t.type, this._map, t))
    }
    click(t, e) {
        this._mousedownPos && this._mousedownPos.dist(e) >= this._clickTolerance || this._map.fire(new Vn(t.type, this._map, t))
    }
    dblclick(t) {
        return this._firePreventable(new Vn(t.type, this._map, t))
    }
    mouseover(t) {
        this._map.fire(new Vn(t.type, this._map, t))
    }
    mouseout(t) {
        this._map.fire(new Vn(t.type, this._map, t))
    }
    touchstart(t) {
        return this._firePreventable(new Xn(t.type, this._map, t))
    }
    touchmove(t) {
        this._map.fire(new Xn(t.type, this._map, t))
    }
    touchend(t) {
        this._map.fire(new Xn(t.type, this._map, t))
    }
    touchcancel(t) {
        this._map.fire(new Xn(t.type, this._map, t))
    }
    _firePreventable(t) {
        if (this._map.fire(t), t.defaultPrevented) return {}
    }
    isEnabled() {
        return 1
    }
    isActive() {
        return 0
    }
    enable() {}
    disable() {}
}
class Jn {
    constructor(t) {
        this._map = t
    }
    reset() {
        this._delayContextMenu = 0, this._ignoreContextMenu = 1, delete this._contextMenuEvent
    }
    mousemove(t) {
        this._map.fire(new Vn(t.type, this._map, t))
    }
    mousedown() {
        this._delayContextMenu = 1, this._ignoreContextMenu = 0
    }
    mouseup() {
        this._delayContextMenu = 0, this._contextMenuEvent && (this._map.fire(new Vn("contextmenu", this._map, this._contextMenuEvent)), delete this._contextMenuEvent)
    }
    contextmenu(t) {
        this._delayContextMenu ? this._contextMenuEvent = t : this._ignoreContextMenu || this._map.fire(new Vn(t.type, this._map, t)), this._map.listens("contextmenu") && t.preventDefault()
    }
    isEnabled() {
        return 1
    }
    isActive() {
        return 0
    }
    enable() {}
    disable() {}
}
class Qn {
    constructor(t) {
        this._map = t
    }
    get transform() {
        return this._map._requestedCameraState || this._map.transform
    }
    get center() {
        return {
            lng: this.transform.center.lng,
            lat: this.transform.center.lat
        }
    }
    get zoom() {
        return this.transform.zoom
    }
    get pitch() {
        return this.transform.pitch
    }
    get bearing() {
        return this.transform.bearing
    }
    unproject(t) {
        return this.transform.screenPointToLocation(h.convert(t))
    }
}
class tr {
    constructor(t, e) {
        this._map = t, this._tr = new Qn(t), this._el = t.getCanvasContainer(), this._container = t.getContainer(), this._clickTolerance = e.clickTolerance || 1
    }
    isEnabled() {
        return !!this._enabled
    }
    isActive() {
        return !!this._active
    }
    enable() {
        this.isEnabled() || (this._enabled = 1)
    }
    disable() {
        this.isEnabled() && (this._enabled = 0)
    }
    mousedown(t, e) {
        this.isEnabled() && t.shiftKey && 0 === t.button && (lt.disableDrag(), this._startPos = this._lastPos = e, this._active = 1)
    }
    mousemoveWindow(t, e) {
        if (!this._active) return;
        const i = e;
        if (this._lastPos.equals(i) || !this._box && i.dist(this._startPos) < this._clickTolerance) return;
        const s = this._startPos;
        this._lastPos = i, this._box || (this._box = lt.create("div", "maplibregl-boxzoom", this._container), this._container.classList.add("maplibregl-crosshair"), this._fireEvent("boxzoomstart", t));
        const n = Math.min(s.x, i.x),
            r = Math.max(s.x, i.x),
            o = Math.min(s.y, i.y),
            a = Math.max(s.y, i.y);
        lt.setTransform(this._box, `translate(${n}px,${o}px)`), this._box.style.width = r - n + "px", this._box.style.height = a - o + "px"
    }
    mouseupWindow(t, e) {
        if (!this._active) return;
        if (0 !== t.button) return;
        const i = this._startPos,
            s = e;
        if (this.reset(), lt.suppressClick(), i.x !== s.x || i.y !== s.y) return this._map.fire(new St("boxzoomend", {
            originalEvent: t
        })), {
            cameraAnimation: t => t.fitScreenCoordinates(i, s, this._tr.bearing, {
                linear: 1
            })
        };
        this._fireEvent("boxzoomcancel", t)
    }
    keydown(t) {
        this._active && 27 === t.keyCode && (this.reset(), this._fireEvent("boxzoomcancel", t))
    }
    reset() {
        this._active = 0, this._container.classList.remove("maplibregl-crosshair"), this._box && (lt.remove(this._box), this._box = null), lt.enableDrag(), delete this._startPos, delete this._lastPos
    }
    _fireEvent(t, e) {
        return this._map.fire(new St(t, {
            originalEvent: e
        }))
    }
}

function er(t, e) {
    if (t.length !== e.length) throw Error(`The number of touches and points are not equal - touches ${t.length}, points ${e.length}`);
    const i = {};
    for (let s = 0; s < t.length; s++) i[t[s].identifier] = e[s];
    return i
}
class ir {
    constructor(t) {
        this.reset(), this.numTouches = t.numTouches
    }
    reset() {
        delete this.centroid, delete this.startTime, delete this.touches, this.aborted = 0
    }
    touchstart(t, e, i) {
        (this.centroid || i.length > this.numTouches) && (this.aborted = 1), this.aborted || (void 0 === this.startTime && (this.startTime = t.timeStamp), i.length === this.numTouches && (this.centroid = function(t) {
            const e = new h(0, 0);
            for (const i of t) e._add(i);
            return e.div(t.length)
        }(e), this.touches = er(i, e)))
    }
    touchmove(t, e, i) {
        if (this.aborted || !this.centroid) return;
        const s = er(i, e);
        for (const t in this.touches) {
            const e = s[t];
            (!e || e.dist(this.touches[t]) > 30) && (this.aborted = 1)
        }
    }
    touchend(t, e, i) {
        if ((!this.centroid || t.timeStamp - this.startTime > 500) && (this.aborted = 1), 0 === i.length) {
            const t = !this.aborted && this.centroid;
            if (this.reset(), t) return t
        }
    }
}
class sr {
    constructor(t) {
        this.singleTap = new ir(t), this.numTaps = t.numTaps, this.reset()
    }
    reset() {
        this.lastTime = 1 / 0, delete this.lastTap, this.count = 0, this.singleTap.reset()
    }
    touchstart(t, e, i) {
        this.singleTap.touchstart(t, e, i)
    }
    touchmove(t, e, i) {
        this.singleTap.touchmove(t, e, i)
    }
    touchend(t, e, i) {
        const s = this.singleTap.touchend(t, e, i);
        if (s) {
            const e = t.timeStamp - this.lastTime < 500,
                i = !this.lastTap || this.lastTap.dist(s) < 30;
            if (e && i || this.reset(), this.count++, this.lastTime = t.timeStamp, this.lastTap = s, this.count === this.numTaps) return this.reset(), s
        }
    }
}
class nr {
    constructor(t) {
        this._tr = new Qn(t), this._zoomIn = new sr({
            numTouches: 1,
            numTaps: 2
        }), this._zoomOut = new sr({
            numTouches: 2,
            numTaps: 1
        }), this.reset()
    }
    reset() {
        this._active = 0, this._zoomIn.reset(), this._zoomOut.reset()
    }
    touchstart(t, e, i) {
        this._zoomIn.touchstart(t, e, i), this._zoomOut.touchstart(t, e, i)
    }
    touchmove(t, e, i) {
        this._zoomIn.touchmove(t, e, i), this._zoomOut.touchmove(t, e, i)
    }
    touchend(t, e, i) {
        const s = this._zoomIn.touchend(t, e, i),
            n = this._zoomOut.touchend(t, e, i),
            r = this._tr;
        return s ? (this._active = 1, t.preventDefault(), setTimeout(() => this.reset(), 0), {
            cameraAnimation: e => e.easeTo({
                duration: 300,
                zoom: r.zoom + 1,
                around: r.unproject(s)
            }, {
                originalEvent: t
            })
        }) : n ? (this._active = 1, t.preventDefault(), setTimeout(() => this.reset(), 0), {
            cameraAnimation: e => e.easeTo({
                duration: 300,
                zoom: r.zoom - 1,
                around: r.unproject(n)
            }, {
                originalEvent: t
            })
        }) : void 0
    }
    touchcancel() {
        this.reset()
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
}
class rr {
    constructor(t) {
        this._enabled = !!t.enable, this._moveStateManager = t.moveStateManager, this._clickTolerance = t.clickTolerance || 1, this._moveFunction = t.move, this._activateOnStart = !!t.activateOnStart, t.assignEvents(this), this.reset()
    }
    reset(t) {
        this._active = 0, this._moved = 0, delete this._lastPoint, this._moveStateManager.endMove(t)
    }
    _move(...t) {
        const e = this._moveFunction(...t);
        if (e.bearingDelta || e.pitchDelta || e.rollDelta || e.around || e.panDelta) return this._active = 1, e
    }
    dragStart(t, e) {
        this.isEnabled() && !this._lastPoint && this._moveStateManager.isValidStartEvent(t) && (this._moveStateManager.startMove(t), this._lastPoint = e.length ? e[0] : e, this._activateOnStart && this._lastPoint && (this._active = 1))
    }
    dragMove(t, e) {
        if (!this.isEnabled()) return;
        const i = this._lastPoint;
        if (!i) return;
        if (t.preventDefault(), !this._moveStateManager.isValidMoveEvent(t)) return void this.reset(t);
        const s = e.length ? e[0] : e;
        return !this._moved && s.dist(i) < this._clickTolerance ? void 0 : (this._moved = 1, this._lastPoint = s, this._move(i, s))
    }
    dragEnd(t) {
        this.isEnabled() && this._lastPoint && this._moveStateManager.isValidEndEvent(t) && (this._moved && lt.suppressClick(), this.reset(t))
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
    getClickTolerance() {
        return this._clickTolerance
    }
}
const or = 0,
    ar = 2,
    hr = {
        [or]: 1,
        [ar]: 2
    };
class lr {
    constructor(t) {
        this._correctEvent = t.checkCorrectEvent
    }
    startMove(t) {
        const e = lt.mouseButton(t);
        this._eventButton = e
    }
    endMove(t) {
        delete this._eventButton
    }
    isValidStartEvent(t) {
        return this._correctEvent(t)
    }
    isValidMoveEvent(t) {
        return ! function(t, e) {
            const i = hr[e];
            return void 0 === t.buttons || (t.buttons & i) !== i
        }(t, this._eventButton)
    }
    isValidEndEvent(t) {
        return lt.mouseButton(t) === this._eventButton
    }
}
const cr = t => {
    t.mousedown = t.dragStart, t.mousemoveWindow = t.dragMove, t.mouseup = t.dragEnd, t.contextmenu = t => {
        t.preventDefault()
    }
};
class ur {
    constructor(t, e) {
        this._clickTolerance = t.clickTolerance || 1, this._map = e, this.reset()
    }
    reset() {
        this._active = 0, this._touches = {}, this._sum = new h(0, 0)
    }
    _shouldBePrevented(t) {
        return t < (this._map.cooperativeGestures.isEnabled() ? 2 : 1)
    }
    touchstart(t, e, i) {
        return this._calculateTransform(t, e, i)
    }
    touchmove(t, e, i) {
        if (this._active) {
            if (!this._shouldBePrevented(i.length)) return t.preventDefault(), this._calculateTransform(t, e, i);
            this._map.cooperativeGestures.notifyGestureBlocked("touch_pan", t)
        }
    }
    touchend(t, e, i) {
        this._calculateTransform(t, e, i), this._active && this._shouldBePrevented(i.length) && this.reset()
    }
    touchcancel() {
        this.reset()
    }
    _calculateTransform(t, e, i) {
        i.length > 0 && (this._active = 1);
        const s = er(i, e),
            n = new h(0, 0),
            r = new h(0, 0);
        let o = 0;
        for (const t in s) {
            const e = s[t],
                i = this._touches[t];
            i && (n._add(e), r._add(e.sub(i)), o++, s[t] = e)
        }
        if (this._touches = s, this._shouldBePrevented(o) || !r.mag()) return;
        const a = r.div(o);
        return this._sum._add(a), this._sum.mag() < this._clickTolerance ? void 0 : {
            around: n.div(o),
            panDelta: a
        }
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
}
class dr {
    constructor() {
        this.reset()
    }
    reset() {
        this._active = 0, delete this._firstTwoTouches
    }
    touchstart(t, e, i) {
        this._firstTwoTouches || i.length < 2 || (this._firstTwoTouches = [i[0].identifier, i[1].identifier], this._start([e[0], e[1]]))
    }
    touchmove(t, e, i) {
        if (!this._firstTwoTouches) return;
        t.preventDefault();
        const [s, n] = this._firstTwoTouches, r = pr(i, e, s), o = pr(i, e, n);
        if (!r || !o) return;
        const a = this._aroundCenter ? null : r.add(o).div(2);
        return this._move([r, o], a, t)
    }
    touchend(t, e, i) {
        if (!this._firstTwoTouches) return;
        const [s, n] = this._firstTwoTouches, r = pr(i, e, s), o = pr(i, e, n);
        r && o || (this._active && lt.suppressClick(), this.reset())
    }
    touchcancel() {
        this.reset()
    }
    enable(t) {
        this._enabled = 1, this._aroundCenter = !!t && "center" === t.around
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return !!this._enabled
    }
    isActive() {
        return !!this._active
    }
}

function pr(t, e, i) {
    for (let s = 0; s < t.length; s++)
        if (t[s].identifier === i) return e[s]
}

function _r(t, e) {
    return Math.log(t / e) / Math.LN2
}
class mr extends dr {
    reset() {
        super.reset(), delete this._distance, delete this._startDistance
    }
    _start(t) {
        this._startDistance = this._distance = t[0].dist(t[1])
    }
    _move(t, e) {
        const i = this._distance;
        if (this._distance = t[0].dist(t[1]), this._active || !(Math.abs(_r(this._distance, this._startDistance)) < .1)) return this._active = 1, {
            zoomDelta: _r(this._distance, i),
            pinchAround: e
        }
    }
}

function fr(t, e) {
    return 180 * t.angleWith(e) / Math.PI
}
class gr extends dr {
    reset() {
        super.reset(), delete this._minDiameter, delete this._startVector, delete this._vector
    }
    _start(t) {
        this._startVector = this._vector = t[0].sub(t[1]), this._minDiameter = t[0].dist(t[1])
    }
    _move(t, e, i) {
        const s = this._vector;
        if (this._vector = t[0].sub(t[1]), this._active || !this._isBelowThreshold(this._vector)) return this._active = 1, {
            bearingDelta: fr(this._vector, s),
            pinchAround: e
        }
    }
    _isBelowThreshold(t) {
        this._minDiameter = Math.min(this._minDiameter, t.mag());
        const e = 25 / (Math.PI * this._minDiameter) * 360,
            i = fr(t, this._startVector);
        return Math.abs(i) < e
    }
}

function yr(t) {
    return Math.abs(t.y) > Math.abs(t.x)
}
class vr extends dr {
    constructor(t) {
        super(), this._currentTouchCount = 0, this._map = t
    }
    reset() {
        super.reset(), this._valid = void 0, delete this._firstMove, delete this._lastPoints
    }
    touchstart(t, e, i) {
        super.touchstart(t, e, i), this._currentTouchCount = i.length
    }
    _start(t) {
        this._lastPoints = t, yr(t[0].sub(t[1])) && (this._valid = 0)
    }
    _move(t, e, i) {
        if (this._map.cooperativeGestures.isEnabled() && this._currentTouchCount < 3) return;
        const s = t[0].sub(this._lastPoints[0]),
            n = t[1].sub(this._lastPoints[1]);
        return this._valid = this.gestureBeginsVertically(s, n, i.timeStamp), this._valid ? (this._lastPoints = t, this._active = 1, {
            pitchDelta: (s.y + n.y) / 2 * -.5
        }) : void 0
    }
    gestureBeginsVertically(t, e, i) {
        if (void 0 !== this._valid) return this._valid;
        const s = t.mag() >= 2,
            n = e.mag() >= 2;
        if (!s && !n) return;
        if (!s || !n) return void 0 === this._firstMove && (this._firstMove = i), i - this._firstMove < 100 ? void 0 : 0;
        const r = t.y > 0 == e.y > 0;
        return yr(t) && yr(e) && r
    }
}
const br = {
    panStep: 100,
    bearingStep: 15,
    pitchStep: 10
};
class xr {
    constructor(t) {
        this._tr = new Qn(t);
        const e = br;
        this._panStep = e.panStep, this._bearingStep = e.bearingStep, this._pitchStep = e.pitchStep, this._rotationDisabled = 0
    }
    reset() {
        this._active = 0
    }
    keydown(t) {
        if (t.altKey || t.ctrlKey || t.metaKey) return;
        let e = 0,
            i = 0,
            s = 0,
            n = 0,
            r = 0;
        switch (t.keyCode) {
            case 61:
            case 107:
            case 171:
            case 187:
                e = 1;
                break;
            case 189:
            case 109:
            case 173:
                e = -1;
                break;
            case 37:
                t.shiftKey ? i = -1 : (t.preventDefault(), n = -1);
                break;
            case 39:
                t.shiftKey ? i = 1 : (t.preventDefault(), n = 1);
                break;
            case 38:
                t.shiftKey ? s = 1 : (t.preventDefault(), r = -1);
                break;
            case 40:
                t.shiftKey ? s = -1 : (t.preventDefault(), r = 1);
                break;
            default:
                return
        }
        return this._rotationDisabled && (i = 0, s = 0), {
            cameraAnimation: o => {
                const a = this._tr;
                o.easeTo({
                    duration: 300,
                    easeId: "keyboardHandler",
                    easing: wr,
                    zoom: e ? Math.round(a.zoom) + e * (t.shiftKey ? 2 : 1) : a.zoom,
                    bearing: a.bearing + i * this._bearingStep,
                    pitch: a.pitch + s * this._pitchStep,
                    offset: [-n * this._panStep, -r * this._panStep],
                    center: a.center
                }, {
                    originalEvent: t
                })
            }
        }
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
    disableRotation() {
        this._rotationDisabled = 1
    }
    enableRotation() {
        this._rotationDisabled = 0
    }
}

function wr(t) {
    return t * (2 - t)
}
const Tr = 4.000244140625,
    Mr = 1 / 450;
class Pr {
    constructor(t, e) {
        this._onTimeout = t => {
            this._type = "wheel", this._delta -= this._lastValue, this._active || this._start(t)
        }, this._map = t, this._tr = new Qn(t), this._triggerRenderFrame = e, this._delta = 0, this._defaultZoomRate = .01, this._wheelZoomRate = Mr
    }
    setZoomRate(t) {
        this._defaultZoomRate = t
    }
    setWheelZoomRate(t) {
        this._wheelZoomRate = t
    }
    isEnabled() {
        return !!this._enabled
    }
    isActive() {
        return !!this._active || void 0 !== this._finishTimeout
    }
    isZooming() {
        return !!this._zooming
    }
    enable(t) {
        this.isEnabled() || (this._enabled = 1, this._aroundCenter = !!t && "center" === t.around)
    }
    disable() {
        this.isEnabled() && (this._enabled = 0)
    }
    _shouldBePrevented(t) {
        return this._map.cooperativeGestures.isEnabled() ? !(t.ctrlKey || this._map.cooperativeGestures.isBypassed(t)) : 0
    }
    wheel(t) {
        if (!this.isEnabled()) return;
        if (this._shouldBePrevented(t)) return void this._map.cooperativeGestures.notifyGestureBlocked("wheel_zoom", t);
        let e = t.deltaMode === WheelEvent.DOM_DELTA_LINE ? 40 * t.deltaY : t.deltaY;
        const i = ht.now(),
            s = i - (this._lastWheelEventTime || 0);
        this._lastWheelEventTime = i, 0 !== e && e % Tr === 0 ? this._type = "wheel" : 0 !== e && Math.abs(e) < 4 ? this._type = "trackpad" : s > 400 ? (this._type = null, this._lastValue = e, this._timeout = setTimeout(this._onTimeout, 40, t)) : this._type || (this._type = Math.abs(s * e) < 200 ? "trackpad" : "wheel", this._timeout && (clearTimeout(this._timeout), this._timeout = null, e += this._lastValue)), t.shiftKey && e && (e /= 4), this._type && (this._lastWheelEvent = t, this._delta -= e, this._active || this._start(t)), t.preventDefault()
    }
    _start(t) {
        if (!this._delta) return;
        this._frameId && (this._frameId = null), this._active = 1, this.isZooming() || (this._zooming = 1), this._finishTimeout && (clearTimeout(this._finishTimeout), delete this._finishTimeout);
        const e = lt.mousePos(this._map.getCanvas(), t),
            i = this._tr;
        this._aroundPoint = this._aroundCenter ? i.transform.locationToScreenPoint(Bt.convert(i.center)) : e, this._frameId || (this._frameId = 1, this._triggerRenderFrame())
    }
    renderFrame() {
        if (!this._frameId) return;
        if (this._frameId = null, !this.isActive()) return;
        const t = this._tr.transform;
        if ("number" == typeof this._lastExpectedZoom) {
            const e = t.zoom - this._lastExpectedZoom;
            "number" == typeof this._startZoom && (this._startZoom += e), "number" == typeof this._targetZoom && (this._targetZoom += e)
        }
        if (0 !== this._delta) {
            let e = 2 / (1 + Math.exp(-Math.abs(this._delta * ("wheel" === this._type && Math.abs(this._delta) > Tr ? this._wheelZoomRate : this._defaultZoomRate))));
            this._delta < 0 && 0 !== e && (e = 1 / e);
            const i = "number" != typeof this._targetZoom ? t.scale : gs(this._targetZoom);
            this._targetZoom = Math.min(t.maxZoom, Math.max(t.minZoom, ys(i * e))), "wheel" === this._type && (this._startZoom = t.zoom, this._easing = this._smoothOutEasing(200)), this._delta = 0
        }
        const e = "number" != typeof this._targetZoom ? t.zoom : this._targetZoom,
            i = this._startZoom,
            s = this._easing;
        let n, r = 0;
        const o = ht.now() - this._lastWheelEventTime;
        if ("wheel" === this._type && i && s && o) {
            const t = Math.min(o / 200, 1);
            n = ji(i, e, s(t)), t < 1 ? this._frameId || (this._frameId = 1) : r = 1
        } else n = e, r = 1;
        return this._active = 1, r && (this._active = 0, this._finishTimeout = setTimeout(() => {
            this._zooming = 0, this._triggerRenderFrame(), delete this._targetZoom, delete this._lastExpectedZoom, delete this._finishTimeout
        }, 200)), this._lastExpectedZoom = n, {
            noInertia: 1,
            needsRenderFrame: !r,
            zoomDelta: n - t.zoom,
            around: this._aroundPoint,
            originalEvent: this._lastWheelEvent
        }
    }
    _smoothOutEasing(t) {
        let e = j;
        if (this._prevEase) {
            const t = this._prevEase,
                i = (ht.now() - t.start) / t.duration,
                s = t.easing(i + .01) - t.easing(i),
                n = .27 / Math.sqrt(s * s + 1e-4) * .01;
            e = N(n, Math.sqrt(.0729 - n * n), .25, 1)
        }
        return this._prevEase = {
            start: ht.now(),
            duration: t,
            easing: e
        }, e
    }
    reset() {
        this._active = 0, this._zooming = 0, delete this._targetZoom, delete this._lastExpectedZoom, this._finishTimeout && (clearTimeout(this._finishTimeout), delete this._finishTimeout)
    }
}
class Er {
    constructor(t, e) {
        this._clickZoom = t, this._tapZoom = e
    }
    enable() {
        this._clickZoom.enable(), this._tapZoom.enable()
    }
    disable() {
        this._clickZoom.disable(), this._tapZoom.disable()
    }
    isEnabled() {
        return this._clickZoom.isEnabled() && this._tapZoom.isEnabled()
    }
    isActive() {
        return this._clickZoom.isActive() || this._tapZoom.isActive()
    }
}
class Lr {
    constructor(t) {
        this._tr = new Qn(t), this.reset()
    }
    reset() {
        this._active = 0
    }
    dblclick(t, e) {
        return t.preventDefault(), {
            cameraAnimation: i => {
                i.easeTo({
                    duration: 300,
                    zoom: this._tr.zoom + (t.shiftKey ? -1 : 1),
                    around: this._tr.unproject(e)
                }, {
                    originalEvent: t
                })
            }
        }
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
}
class Cr {
    constructor() {
        this._tap = new sr({
            numTouches: 1,
            numTaps: 1
        }), this.reset()
    }
    reset() {
        this._active = 0, delete this._swipePoint, delete this._swipeTouch, delete this._tapTime, delete this._tapPoint, this._tap.reset()
    }
    touchstart(t, e, i) {
        if (!this._swipePoint)
            if (this._tapTime) {
                const s = e[0],
                    n = t.timeStamp - this._tapTime < 500,
                    r = this._tapPoint.dist(s) < 30;
                n && r ? i.length > 0 && (this._swipePoint = s, this._swipeTouch = i[0].identifier) : this.reset()
            } else this._tap.touchstart(t, e, i)
    }
    touchmove(t, e, i) {
        if (this._tapTime) {
            if (this._swipePoint) {
                if (i[0].identifier !== this._swipeTouch) return;
                const s = e[0],
                    n = s.y - this._swipePoint.y;
                return this._swipePoint = s, t.preventDefault(), this._active = 1, {
                    zoomDelta: n / 128
                }
            }
        } else this._tap.touchmove(t, e, i)
    }
    touchend(t, e, i) {
        if (this._tapTime) this._swipePoint && 0 === i.length && this.reset();
        else {
            const s = this._tap.touchend(t, e, i);
            s && (this._tapTime = t.timeStamp, this._tapPoint = s)
        }
    }
    touchcancel() {
        this.reset()
    }
    enable() {
        this._enabled = 1
    }
    disable() {
        this._enabled = 0, this.reset()
    }
    isEnabled() {
        return this._enabled
    }
    isActive() {
        return this._active
    }
}
class Sr {
    constructor(t, e, i) {
        this._el = t, this._mousePan = e, this._touchPan = i
    }
    enable(t) {
        this._inertiaOptions = t || {}, this._mousePan.enable(), this._touchPan.enable(), this._el.classList.add("maplibregl-touch-drag-pan")
    }
    disable() {
        this._mousePan.disable(), this._touchPan.disable(), this._el.classList.remove("maplibregl-touch-drag-pan")
    }
    isEnabled() {
        return this._mousePan.isEnabled() && this._touchPan.isEnabled()
    }
    isActive() {
        return this._mousePan.isActive() || this._touchPan.isActive()
    }
}
class Rr {
    constructor(t, e, i, s) {
        this._pitchWithRotate = t.pitchWithRotate, this._rollEnabled = t.rollEnabled, this._mouseRotate = e, this._mousePitch = i, this._mouseRoll = s
    }
    enable() {
        this._mouseRotate.enable(), this._pitchWithRotate && this._mousePitch.enable(), this._rollEnabled && this._mouseRoll.enable()
    }
    disable() {
        this._mouseRotate.disable(), this._mousePitch.disable(), this._mouseRoll.disable()
    }
    isEnabled() {
        return this._mouseRotate.isEnabled() && (!this._pitchWithRotate || this._mousePitch.isEnabled()) && (!this._rollEnabled || this._mouseRoll.isEnabled())
    }
    isActive() {
        return this._mouseRotate.isActive() || this._mousePitch.isActive() || this._mouseRoll.isActive()
    }
}
class Ir {
    constructor(t, e, i, s) {
        this._el = t, this._touchZoom = e, this._touchRotate = i, this._tapDragZoom = s, this._rotationDisabled = 0, this._enabled = 1
    }
    enable(t) {
        this._touchZoom.enable(t), this._rotationDisabled || this._touchRotate.enable(t), this._tapDragZoom.enable(), this._el.classList.add("maplibregl-touch-zoom-rotate")
    }
    disable() {
        this._touchZoom.disable(), this._touchRotate.disable(), this._tapDragZoom.disable(), this._el.classList.remove("maplibregl-touch-zoom-rotate")
    }
    isEnabled() {
        return this._touchZoom.isEnabled() && (this._rotationDisabled || this._touchRotate.isEnabled()) && this._tapDragZoom.isEnabled()
    }
    isActive() {
        return this._touchZoom.isActive() || this._touchRotate.isActive() || this._tapDragZoom.isActive()
    }
    disableRotation() {
        this._rotationDisabled = 1, this._touchRotate.disable()
    }
    enableRotation() {
        this._rotationDisabled = 0, this._touchZoom.isEnabled() && this._touchRotate.enable()
    }
}
class Ar {
    constructor(t, e) {
        this._bypassKey = -1 !== navigator.userAgent.indexOf("Mac") ? "metaKey" : "ctrlKey", this._map = t, this._options = e, this._enabled = 0
    }
    isActive() {
        return 0
    }
    reset() {}
    _setupUI() {
        if (this._container) return;
        const t = this._map.getCanvasContainer();
        t.classList.add("maplibregl-cooperative-gestures"), this._container = lt.create("div", "maplibregl-cooperative-gesture-screen", t);
        let e = this._map._getUIString("CooperativeGesturesHandler.WindowsHelpText");
        "metaKey" === this._bypassKey && (e = this._map._getUIString("CooperativeGesturesHandler.MacHelpText"));
        const i = this._map._getUIString("CooperativeGesturesHandler.MobileHelpText"),
            s = document.createElement("div");
        s.className = "maplibregl-desktop-message", s.textContent = e, this._container.appendChild(s);
        const n = document.createElement("div");
        n.className = "maplibregl-mobile-message", n.textContent = i, this._container.appendChild(n), this._container.setAttribute("aria-hidden", "true")
    }
    _destroyUI() {
        this._container && (lt.remove(this._container), this._map.getCanvasContainer().classList.remove("maplibregl-cooperative-gestures")), delete this._container
    }
    enable() {
        this._setupUI(), this._enabled = 1
    }
    disable() {
        this._enabled = 0, this._destroyUI()
    }
    isEnabled() {
        return this._enabled
    }
    isBypassed(t) {
        return t[this._bypassKey]
    }
    notifyGestureBlocked(t, e) {
        this._enabled && (this._map.fire(new St("cooperativegestureprevented", {
            gestureType: t,
            originalEvent: e
        })), this._container.classList.add("maplibregl-show"), setTimeout(() => {
            this._container.classList.remove("maplibregl-show")
        }, 100))
    }
}
const zr = t => t.zoom || t.drag || t.roll || t.pitch || t.rotate;
class Or extends St {}

function kr(t) {
    return t.panDelta && t.panDelta.mag() || t.zoomDelta || t.bearingDelta || t.pitchDelta || t.rollDelta
}
class Dr {
    constructor(t, e) {
        this.handleWindowEvent = t => {
            this.handleEvent(t, t.type + "Window")
        }, this.handleEvent = (t, e) => {
            if ("blur" === t.type) return void this.stop(1);
            this._updatingCamera = 1;
            const i = "renderFrame" === t.type ? void 0 : t,
                s = {
                    needsRenderFrame: 0
                },
                n = {},
                r = {},
                o = t.touches,
                a = o ? this._getMapTouches(o) : void 0,
                h = a ? lt.touchPos(this._map.getCanvas(), a) : lt.mousePos(this._map.getCanvas(), t);
            for (const {
                    handlerName: o,
                    handler: l,
                    allowed: c
                }
                of this._handlers) {
                if (!l.isEnabled()) continue;
                let u;
                this._blockedByActive(r, c, o) ? l.reset() : l[e || t.type] && (u = l[e || t.type](t, h, a), this.mergeHandlerResult(s, n, u, o, i), u && u.needsRenderFrame && this._triggerRenderFrame()), (u || l.isActive()) && (r[o] = l)
            }
            const l = {};
            for (const t in this._previousActiveHandlers) r[t] || (l[t] = i);
            this._previousActiveHandlers = r, (Object.keys(l).length || kr(s)) && (this._changes.push([s, n, l]), this._triggerRenderFrame()), (Object.keys(r).length || kr(s)) && this._map._stop(1), this._updatingCamera = 0;
            const {
                cameraAnimation: c
            } = s;
            c && (this._inertia.clear(), this._fireEvents({}, {}, 1), this._changes = [], c(this._map))
        }, this._map = t, this._el = this._map.getCanvasContainer(), this._handlers = [], this._handlersById = {}, this._changes = [], this._inertia = new $n(t), this._bearingSnap = e.bearingSnap, this._previousActiveHandlers = {}, this._eventsInProgress = {}, this._addDefaultHandlers(e);
        const i = this._el;
        this._listeners = [
            [i, "touchstart", {
                passive: 1
            }],
            [i, "touchmove", {
                passive: 0
            }],
            [i, "touchend", void 0],
            [i, "touchcancel", void 0],
            [i, "mousedown", void 0],
            [i, "mousemove", void 0],
            [i, "mouseup", void 0],
            [document, "mousemove", {
                capture: 1
            }],
            [document, "mouseup", void 0],
            [i, "mouseover", void 0],
            [i, "mouseout", void 0],
            [i, "dblclick", void 0],
            [i, "click", void 0],
            [i, "keydown", {
                capture: 0
            }],
            [i, "keyup", void 0],
            [i, "wheel", {
                passive: 0
            }],
            [i, "contextmenu", void 0],
            [window, "blur", void 0]
        ];
        for (const [t, e, i] of this._listeners) lt.addEventListener(t, e, t === document ? this.handleWindowEvent : this.handleEvent, i)
    }
    destroy() {
        for (const [t, e, i] of this._listeners) lt.removeEventListener(t, e, t === document ? this.handleWindowEvent : this.handleEvent, i)
    }
    _addDefaultHandlers(t) {
        const e = this._map,
            i = e.getCanvasContainer();
        this._add("mapEvent", new Yn(e, t));
        const s = e.boxZoom = new tr(e, t);
        this._add("boxZoom", s), t.interactive && t.boxZoom && s.enable();
        const n = e.cooperativeGestures = new Ar(e, t.cooperativeGestures);
        this._add("cooperativeGestures", n), t.cooperativeGestures && n.enable();
        const r = new nr(e),
            o = new Lr(e);
        e.doubleClickZoom = new Er(o, r), this._add("tapZoom", r), this._add("clickZoom", o), t.interactive && t.doubleClickZoom && e.doubleClickZoom.enable();
        const a = new Cr;
        this._add("tapDragZoom", a);
        const h = e.touchPitch = new vr(e);
        this._add("touchPitch", h), t.interactive && t.touchPitch && e.touchPitch.enable(t.touchPitch);
        const l = (({
                enable: t,
                clickTolerance: e,
                bearingDegreesPerPixelMoved: i = .8
            }) => {
                const s = new lr({
                    checkCorrectEvent: t => 0 === lt.mouseButton(t) && t.ctrlKey || 2 === lt.mouseButton(t) && !t.ctrlKey
                });
                return new rr({
                    clickTolerance: e,
                    move: (t, e) => ({
                        bearingDelta: (e.x - t.x) * i
                    }),
                    moveStateManager: s,
                    enable: t,
                    assignEvents: cr
                })
            })(t),
            c = (({
                enable: t,
                clickTolerance: e,
                pitchDegreesPerPixelMoved: i = -.5
            }) => {
                const s = new lr({
                    checkCorrectEvent: t => 0 === lt.mouseButton(t) && t.ctrlKey || 2 === lt.mouseButton(t)
                });
                return new rr({
                    clickTolerance: e,
                    move: (t, e) => ({
                        pitchDelta: (e.y - t.y) * i
                    }),
                    moveStateManager: s,
                    enable: t,
                    assignEvents: cr
                })
            })(t),
            u = (({
                enable: t,
                clickTolerance: e,
                rollDegreesPerPixelMoved: i = .8
            }) => {
                const s = new lr({
                    checkCorrectEvent: t => 2 === lt.mouseButton(t) && t.ctrlKey
                });
                return new rr({
                    clickTolerance: e,
                    move: (t, e) => ({
                        rollDelta: (e.x - t.x) * i
                    }),
                    moveStateManager: s,
                    enable: t,
                    assignEvents: cr
                })
            })(t);
        e.dragRotate = new Rr(t, l, c, u), this._add("mouseRotate", l, ["mousePitch"]), this._add("mousePitch", c, ["mouseRotate", "mouseRoll"]), this._add("mouseRoll", u, ["mousePitch"]), t.interactive && t.dragRotate && e.dragRotate.enable();
        const d = (({
                enable: t,
                clickTolerance: e
            }) => {
                const i = new lr({
                    checkCorrectEvent: t => 0 === lt.mouseButton(t) && !t.ctrlKey
                });
                return new rr({
                    clickTolerance: e,
                    move: (t, e) => ({
                        around: e,
                        panDelta: e.sub(t)
                    }),
                    activateOnStart: 1,
                    moveStateManager: i,
                    enable: t,
                    assignEvents: cr
                })
            })(t),
            p = new ur(t, e);
        e.dragPan = new Sr(i, d, p), this._add("mousePan", d), this._add("touchPan", p, ["touchZoom", "touchRotate"]), t.interactive && t.dragPan && e.dragPan.enable(t.dragPan);
        const _ = new gr,
            m = new mr;
        e.touchZoomRotate = new Ir(i, m, _, a), this._add("touchRotate", _, ["touchPan", "touchZoom"]), this._add("touchZoom", m, ["touchPan", "touchRotate"]), t.interactive && t.touchZoomRotate && e.touchZoomRotate.enable(t.touchZoomRotate);
        const f = e.scrollZoom = new Pr(e, () => this._triggerRenderFrame());
        this._add("scrollZoom", f, ["mousePan"]), t.interactive && t.scrollZoom && e.scrollZoom.enable(t.scrollZoom);
        const g = e.keyboard = new xr(e);
        this._add("keyboard", g), t.interactive && t.keyboard && e.keyboard.enable(), this._add("blockableMapEvent", new Jn(e))
    }
    _add(t, e, i) {
        this._handlers.push({
            handlerName: t,
            handler: e,
            allowed: i
        }), this._handlersById[t] = e
    }
    stop(t) {
        if (!this._updatingCamera) {
            for (const {
                    handler: t
                }
                of this._handlers) t.reset();
            this._inertia.clear(), this._fireEvents({}, {}, t), this._changes = []
        }
    }
    isActive() {
        for (const {
                handler: t
            }
            of this._handlers)
            if (t.isActive()) return 1;
        return 0
    }
    isZooming() {
        return !!this._eventsInProgress.zoom || this._map.scrollZoom.isZooming()
    }
    isRotating() {
        return !!this._eventsInProgress.rotate
    }
    isMoving() {
        return !!zr(this._eventsInProgress) || this.isZooming()
    }
    _blockedByActive(t, e, i) {
        for (const s in t)
            if (s !== i && (!e || e.indexOf(s) < 0)) return 1;
        return 0
    }
    _getMapTouches(t) {
        const e = [];
        for (const i of t) this._el.contains(i.target) && e.push(i);
        return e
    }
    mergeHandlerResult(t, e, i, s, n) {
        if (!i) return;
        q(t, i);
        const r = {
            handlerName: s,
            originalEvent: i.originalEvent || n
        };
        void 0 !== i.zoomDelta && (e.zoom = r), void 0 !== i.panDelta && (e.drag = r), void 0 !== i.rollDelta && (e.roll = r), void 0 !== i.pitchDelta && (e.pitch = r), void 0 !== i.bearingDelta && (e.rotate = r)
    }
    _applyChanges() {
        const t = {},
            e = {},
            i = {};
        for (const [s, n, r] of this._changes) s.panDelta && (t.panDelta = (t.panDelta || new h(0, 0))._add(s.panDelta)), s.zoomDelta && (t.zoomDelta = (t.zoomDelta || 0) + s.zoomDelta), s.bearingDelta && (t.bearingDelta = (t.bearingDelta || 0) + s.bearingDelta), s.pitchDelta && (t.pitchDelta = (t.pitchDelta || 0) + s.pitchDelta), s.rollDelta && (t.rollDelta = (t.rollDelta || 0) + s.rollDelta), void 0 !== s.around && (t.around = s.around), void 0 !== s.pinchAround && (t.pinchAround = s.pinchAround), s.noInertia && (t.noInertia = s.noInertia), q(e, n), q(i, r);
        this._updateMapTransform(t, e, i), this._changes = []
    }
    _updateMapTransform(t, e, i) {
        const s = this._map,
            n = s._getTransformForUpdate();
        if (!kr(t)) return this._fireEvents(e, i, 1);
        s._stop(1);
        let {
            panDelta: r,
            zoomDelta: o,
            bearingDelta: a,
            pitchDelta: h,
            rollDelta: l,
            around: c,
            pinchAround: u
        } = t;
        void 0 !== u && (c = u), c = c || s.transform.centerPoint;
        const d = {
            panDelta: r,
            zoomDelta: o,
            rollDelta: l,
            pitchDelta: h,
            bearingDelta: a,
            around: c
        };
        this._map.cameraHelper.useGlobeControls && !n.isPointOnMapSurface(c) && (c = n.centerPoint);
        const p = n.screenPointToLocation(r ? c.sub(r) : c);
        this._map.cameraHelper.handleMapControlsRollPitchBearingZoom(d, n), this._map.cameraHelper.handleMapControlsPan(d, n, p), s._applyUpdatedTransform(n), this._map._update(), t.noInertia || this._inertia.record(t), this._fireEvents(e, i, 1)
    }
    _fireEvents(t, e, i) {
        const s = zr(this._eventsInProgress),
            n = zr(t),
            r = {};
        for (const e in t) {
            const {
                originalEvent: i
            } = t[e];
            this._eventsInProgress[e] || (r[e + "start"] = i), this._eventsInProgress[e] = t[e]
        }!s && n && this._fireEvent("movestart", n.originalEvent);
        for (const t in r) this._fireEvent(t, r[t]);
        n && this._fireEvent("move", n.originalEvent);
        for (const e in t) {
            const {
                originalEvent: i
            } = t[e];
            this._fireEvent(e, i)
        }
        const o = {};
        let a;
        for (const t in this._eventsInProgress) {
            const {
                handlerName: i,
                originalEvent: s
            } = this._eventsInProgress[t];
            this._handlersById[i].isActive() || (delete this._eventsInProgress[t], a = e[i] || s, o[t + "end"] = a)
        }
        for (const t in o) this._fireEvent(t, o[t]);
        const h = zr(this._eventsInProgress);
        if (i && (s || n) && !h) {
            this._updatingCamera = 1;
            const t = this._inertia._onMoveEnd(this._map.dragPan._inertiaOptions),
                e = t => 0 !== t && -this._bearingSnap < t && t < this._bearingSnap;
            !t || !t.essential && ht.prefersReducedMotion ? (this._map.fire(new St("moveend", {
                originalEvent: a
            })), e(this._map.getBearing()) && this._map.resetNorth()) : (e(t.bearing || this._map.getBearing()) && (t.bearing = 0), t.freezeElevation = 1, this._map.easeTo(t, {
                originalEvent: a
            })), this._updatingCamera = 0
        }
    }
    _fireEvent(t, e) {
        this._map.fire(new St(t, e ? {
            originalEvent: e
        } : {}))
    }
    _requestFrame() {
        return this._map.triggerRepaint(), this._map._renderTaskQueue.add(t => {
            delete this._frameId, this.handleEvent(new Or("renderFrame", {
                timeStamp: t
            })), this._applyChanges()
        })
    }
    _triggerRenderFrame() {
        void 0 === this._frameId && (this._frameId = this._requestFrame())
    }
}
class Br extends It {
    constructor(t, e, i) {
        super(), this._renderFrameCallback = () => {
            const t = Math.min((ht.now() - this._easeStart) / this._easeOptions.duration, 1);
            this._onEaseFrame(this._easeOptions.easing(t)), t < 1 && this._easeFrameId ? this._easeFrameId = this._requestRenderFrame(this._renderFrameCallback) : this.stop()
        }, this._moving = 0, this._zooming = 0, this.transform = t, this._bearingSnap = i.bearingSnap, this.cameraHelper = e, this.on("moveend", () => {
            delete this._requestedCameraState
        })
    }
    migrateProjection(t, e) {
        t.apply(this.transform), this.transform = t, this.cameraHelper = e
    }
    getCenter() {
        return new Bt(this.transform.center.lng, this.transform.center.lat)
    }
    setCenter(t, e) {
        return this.jumpTo({
            center: t
        }, e)
    }
    panBy(t, e, i) {
        return t = h.convert(t).mult(-1), this.panTo(this.transform.center, q({
            offset: t
        }, e), i)
    }
    panTo(t, e, i) {
        return this.easeTo(q({
            center: t
        }, e), i)
    }
    getZoom() {
        return this.transform.zoom
    }
    setZoom(t, e) {
        return this.jumpTo({
            zoom: t
        }, e), this
    }
    zoomTo(t, e, i) {
        return this.easeTo(q({
            zoom: t
        }, e), i)
    }
    zoomIn(t, e) {
        var i;
        return this.zoomTo(this.getZoom() + (null !== (i = null == t ? void 0 : t.zoomDelta) && void 0 !== i ? i : 1), t, e), this
    }
    zoomOut(t, e) {
        var i;
        return this.zoomTo(this.getZoom() - (null !== (i = null == t ? void 0 : t.zoomDelta) && void 0 !== i ? i : 1), t, e), this
    }
    getBearing() {
        return this.transform.bearing
    }
    setBearing(t, e) {
        return this.jumpTo({
            bearing: t
        }, e), this
    }
    getPadding() {
        return this.transform.padding
    }
    setPadding(t, e) {
        return this.jumpTo({
            padding: t
        }, e), this
    }
    rotateTo(t, e, i) {
        return this.easeTo(q({
            bearing: t
        }, e), i)
    }
    resetNorth(t, e) {
        return this.rotateTo(0, q({
            duration: 1e3
        }, t), e), this
    }
    resetNorthPitch(t, e) {
        return this.easeTo(q({
            bearing: 0,
            pitch: 0,
            roll: 0,
            duration: 1e3
        }, t), e), this
    }
    snapToNorth(t, e) {
        return Math.abs(this.getBearing()) < this._bearingSnap ? this.resetNorth(t, e) : this
    }
    getPitch() {
        return this.transform.pitch
    }
    setPitch(t, e) {
        return this.jumpTo({
            pitch: t
        }, e), this
    }
    getRoll() {
        return this.transform.roll
    }
    setRoll(t, e) {
        return this.jumpTo({
            roll: t
        }, e), this
    }
    cameraForBounds(t, e) {
        t = Ft.convert(t).adjustAntiMeridian();
        const i = e && e.bearing || 0;
        return this._cameraForBoxAndBearing(t.getNorthWest(), t.getSouthEast(), i, e)
    }
    _cameraForBoxAndBearing(t, e, i, s) {
        const n = {
            top: 0,
            bottom: 0,
            right: 0,
            left: 0
        };
        if ("number" == typeof(s = q({
                padding: n,
                offset: [0, 0],
                maxZoom: this.transform.maxZoom
            }, s)).padding) {
            const t = s.padding;
            s.padding = {
                top: t,
                bottom: t,
                right: t,
                left: t
            }
        }
        const r = q(n, s.padding);
        s.padding = r;
        const o = this.transform,
            a = new Ft(t, e);
        return this.cameraHelper.cameraForBoxAndBearing(s, r, a, i, o)
    }
    fitBounds(t, e, i) {
        return this._fitInternal(this.cameraForBounds(t, e), e, i)
    }
    fitScreenCoordinates(t, e, i, s, n) {
        return this._fitInternal(this._cameraForBoxAndBearing(this.transform.screenPointToLocation(h.convert(t)), this.transform.screenPointToLocation(h.convert(e)), i, s), s, n)
    }
    _fitInternal(t, e, i) {
        return t ? (delete(e = q(t, e)).padding, e.linear ? this.easeTo(e, i) : this.flyTo(e, i)) : this
    }
    jumpTo(t, e) {
        this.stop();
        const i = this._getTransformForUpdate();
        let s = 0,
            n = 0,
            r = 0;
        const o = i.zoom;
        this.cameraHelper.handleJumpToCenterZoom(i, t);
        const a = i.zoom !== o;
        return "bearing" in t && i.bearing !== +t.bearing && (s = 1, i.setBearing(+t.bearing)), "pitch" in t && i.pitch !== +t.pitch && (n = 1, i.setPitch(+t.pitch)), "roll" in t && i.roll !== +t.roll && (r = 1, i.setRoll(+t.roll)), null == t.padding || i.isPaddingEqual(t.padding) || i.setPadding(t.padding), this._applyUpdatedTransform(i), this.fire(new St("movestart", e)).fire(new St("move", e)), a && this.fire(new St("zoomstart", e)).fire(new St("zoom", e)).fire(new St("zoomend", e)), s && this.fire(new St("rotatestart", e)).fire(new St("rotate", e)).fire(new St("rotateend", e)), n && this.fire(new St("pitchstart", e)).fire(new St("pitch", e)).fire(new St("pitchend", e)), r && this.fire(new St("rollstart", e)).fire(new St("roll", e)).fire(new St("rollend", e)), this.fire(new St("moveend", e))
    }
    calculateCameraOptionsFromTo(t, e, i, s = 0) {
        const n = $t.fromLngLat(t, e),
            r = $t.fromLngLat(i, s),
            o = r.x - n.x,
            a = r.y - n.y,
            h = r.z - n.z,
            l = Math.hypot(o, a, h);
        if (0 === l) throw Error("Can't calculate camera options with same From and To");
        const c = Math.hypot(o, a),
            u = ys(this.transform.cameraToCenterDistance / l / this.transform.tileSize),
            d = 180 * Math.atan2(o, -a) / Math.PI;
        let p = 180 * Math.acos(c / l) / Math.PI;
        return p = h < 0 ? 90 - p : 90 + p, {
            center: r.toLngLat(),
            zoom: u,
            pitch: p,
            bearing: d
        }
    }
    easeTo(t, e) {
        this._stop(0, t.easeId), (0 == (t = q({
            offset: [0, 0],
            duration: 500,
            easing: j
        }, t)).animate || !t.essential && ht.prefersReducedMotion) && (t.duration = 0);
        const i = this._getTransformForUpdate(),
            s = this.getBearing(),
            n = i.pitch,
            r = i.roll,
            o = "bearing" in t ? this._normalizeBearing(t.bearing, s) : s,
            a = "pitch" in t ? +t.pitch : n,
            l = "roll" in t ? this._normalizeBearing(t.roll, r) : r,
            c = "padding" in t ? t.padding : i.padding,
            u = h.convert(t.offset);
        let d, p;
        t.around && (d = Bt.convert(t.around), p = i.locationToScreenPoint(d));
        const _ = {
                moving: this._moving,
                zooming: this._zooming,
                rotating: this._rotating,
                pitching: this._pitching,
                rolling: this._rolling
            },
            m = this.cameraHelper.handleEaseTo(i, {
                bearing: o,
                pitch: a,
                roll: l,
                padding: c,
                around: d,
                aroundPoint: p,
                offsetAsPoint: u,
                offset: t.offset,
                zoom: t.zoom,
                center: t.center
            });
        return this._rotating = this._rotating || s !== o, this._pitching = this._pitching || a !== n, this._rolling = this._rolling || l !== r, this._padding = !i.isPaddingEqual(c), this._zooming = this._zooming || m.isZooming, this._easeId = t.easeId, this._prepareEase(e, t.noMoveStart, _), this._ease(t => {
            m.easeFunc(t), this._applyUpdatedTransform(i), this._fireMoveEvents(e)
        }, t => {
            this._afterEase(e, t)
        }, t), this
    }
    _prepareEase(t, e, i = {}) {
        this._moving = 1, e || i.moving || this.fire(new St("movestart", t)), this._zooming && !i.zooming && this.fire(new St("zoomstart", t)), this._rotating && !i.rotating && this.fire(new St("rotatestart", t)), this._pitching && !i.pitching && this.fire(new St("pitchstart", t)), this._rolling && !i.rolling && this.fire(new St("rollstart", t))
    }
    _getTransformForUpdate() {
        return this.transformCameraUpdate ? (this._requestedCameraState || (this._requestedCameraState = this.transform.clone()), this._requestedCameraState) : this.transform
    }
    _applyUpdatedTransform(t) {
        const e = [];
        if (this.transformCameraUpdate && e.push(t => this.transformCameraUpdate(t)), !e.length) return;
        const i = t.clone();
        for (const t of e) {
            const e = i.clone(),
                {
                    center: s,
                    zoom: n,
                    roll: r,
                    pitch: o,
                    bearing: a,
                    elevation: h
                } = t(e);
            s && e.setCenter(s), void 0 !== n && e.setZoom(n), void 0 !== r && e.setRoll(r), void 0 !== o && e.setPitch(o), void 0 !== a && e.setBearing(a), void 0 !== h && e.setElevation(h), i.apply(e)
        }
        this.transform.apply(i)
    }
    _fireMoveEvents(t) {
        this.fire(new St("move", t)), this._zooming && this.fire(new St("zoom", t)), this._rotating && this.fire(new St("rotate", t)), this._pitching && this.fire(new St("pitch", t)), this._rolling && this.fire(new St("roll", t))
    }
    _afterEase(t, e) {
        if (this._easeId && e && this._easeId === e) return;
        delete this._easeId;
        const i = this._zooming,
            s = this._rotating,
            n = this._pitching,
            r = this._rolling;
        this._moving = 0, this._zooming = 0, this._rotating = 0, this._pitching = 0, this._rolling = 0, this._padding = 0, i && this.fire(new St("zoomend", t)), s && this.fire(new St("rotateend", t)), n && this.fire(new St("pitchend", t)), r && this.fire(new St("rollend", t)), this.fire(new St("moveend", t))
    }
    flyTo(t, e) {
        if (!t.essential && ht.prefersReducedMotion) {
            const i = $(t, ["center", "zoom", "bearing", "pitch", "roll"]);
            return this.jumpTo(i, e)
        }
        this.stop(), t = q({
            offset: [0, 0],
            speed: 1.2,
            curve: 1.42,
            easing: j
        }, t);
        const i = this._getTransformForUpdate(),
            s = i.bearing,
            n = i.pitch,
            r = i.roll,
            o = i.padding,
            a = "bearing" in t ? this._normalizeBearing(t.bearing, s) : s,
            l = "pitch" in t ? +t.pitch : n,
            c = "roll" in t ? this._normalizeBearing(t.roll, r) : r,
            u = "padding" in t ? t.padding : i.padding,
            d = h.convert(t.offset);
        let p = i.centerPoint.add(d);
        const _ = i.screenPointToLocation(p),
            m = this.cameraHelper.handleFlyTo(i, {
                bearing: a,
                pitch: l,
                roll: c,
                padding: u,
                locationAtOffset: _,
                offsetAsPoint: d,
                center: t.center,
                minZoom: t.minZoom,
                zoom: t.zoom
            });
        let f = t.curve;
        const g = Math.max(i.width, i.height),
            y = g / m.scaleOfZoom,
            v = m.pixelPathLength;
        "number" == typeof m.scaleOfMinZoom && (f = Math.sqrt(g / m.scaleOfMinZoom / v * 2));
        const b = f * f;

        function x(t) {
            const e = (y * y - g * g + (t ? -1 : 1) * b * b * v * v) / (2 * (t ? y : g) * b * v);
            return Math.log(Math.sqrt(e * e + 1) - e)
        }

        function w(t) {
            return (Math.exp(t) - Math.exp(-t)) / 2
        }

        function T(t) {
            return (Math.exp(t) + Math.exp(-t)) / 2
        }
        const M = x(0);
        let P = function(t) {
                return T(M) / T(M + f * t)
            },
            E = function(t) {
                return g * ((T(M) * (w(e = M + f * t) / T(e)) - w(M)) / b) / v;
                var e
            },
            L = (x(1) - M) / f;
        if (Math.abs(v) < 2e-6 || !isFinite(L)) {
            if (Math.abs(g - y) < 1e-6) return this.easeTo(t, e);
            const i = y < g ? -1 : 1;
            L = Math.abs(Math.log(y / g)) / f, E = () => 0, P = t => Math.exp(i * f * t)
        }
        return t.duration = "duration" in t ? +t.duration : 1e3 * L / ("screenSpeed" in t ? +t.screenSpeed / f : +t.speed), t.maxDuration && t.duration > t.maxDuration && (t.duration = 0), this._zooming = 1, this._rotating = s !== a, this._pitching = l !== n, this._rolling = c !== r, this._padding = !i.isPaddingEqual(u), this._prepareEase(e, 0), this._ease(t => {
            const h = t * L,
                _ = 1 / P(h),
                f = E(h);
            this._rotating && i.setBearing(ji(s, a, t)), this._pitching && i.setPitch(ji(n, l, t)), this._rolling && i.setRoll(ji(r, c, t)), this._padding && (i.interpolatePadding(o, u, t), p = i.centerPoint.add(d)), m.easeFunc(t, _, f, p), this._applyUpdatedTransform(i), this._fireMoveEvents(e)
        }, () => {
            this._afterEase(e)
        }, t), this
    }
    isEasing() {
        return !!this._easeFrameId
    }
    stop() {
        return this._stop()
    }
    _stop(t, e) {
        var i;
        if (this._easeFrameId && (this._cancelRenderFrame(this._easeFrameId), delete this._easeFrameId, delete this._onEaseFrame), this._onEaseEnd) {
            const t = this._onEaseEnd;
            delete this._onEaseEnd, t.call(this, e)
        }
        return t || null === (i = this.handlers) || void 0 === i || i.stop(0), this
    }
    _ease(t, e, i) {
        0 == i.animate || 0 === i.duration ? (t(1), e()) : (this._easeStart = ht.now(), this._easeOptions = i, this._onEaseFrame = t, this._onEaseEnd = e, this._easeFrameId = this._requestRenderFrame(this._renderFrameCallback))
    }
    _normalizeBearing(t, e) {
        t = G(t, -180, 180);
        const i = Math.abs(t - e);
        return Math.abs(t - 360 - e) < i && (t -= 360), Math.abs(t + 360 - e) < i && (t += 360), t
    }
}
const Fr = {
    compact: 1,
    customAttribution: '<a href="https://maplibre.org/" target="_blank">MapLibre</a>'
};
class Zr {
    constructor(t = Fr) {
        this._toggleAttribution = () => {
            this._container.classList.contains("maplibregl-compact") && (this._container.classList.contains("maplibregl-compact-show") ? (this._container.setAttribute("open", ""), this._container.classList.remove("maplibregl-compact-show")) : (this._container.classList.add("maplibregl-compact-show"), this._container.removeAttribute("open")))
        }, this._updateData = t => {
            !t || "metadata" !== t.sourceDataType && "visibility" !== t.sourceDataType && "style" !== t.dataType && "terrain" !== t.type || this._updateAttributions()
        }, this._updateCompact = () => {
            this._map.getCanvasContainer().offsetWidth <= 640 || this._compact ? 0 == this._compact ? this._container.setAttribute("open", "") : this._container.classList.contains("maplibregl-compact") || this._container.classList.contains("maplibregl-attrib-empty") || (this._container.setAttribute("open", ""), this._container.classList.add("maplibregl-compact", "maplibregl-compact-show")) : (this._container.setAttribute("open", ""), this._container.classList.contains("maplibregl-compact") && this._container.classList.remove("maplibregl-compact", "maplibregl-compact-show"))
        }, this._updateCompactMinimize = () => {
            this._container.classList.contains("maplibregl-compact") && this._container.classList.contains("maplibregl-compact-show") && this._container.classList.remove("maplibregl-compact-show")
        }, this.options = t
    }
    getDefaultPosition() {
        return "bottom-right"
    }
    onAdd(t) {
        return this._map = t, this._compact = this.options.compact, this._container = lt.create("details", "maplibregl-ctrl maplibregl-ctrl-attrib"), this._compactButton = lt.create("summary", "maplibregl-ctrl-attrib-button", this._container), this._compactButton.addEventListener("click", this._toggleAttribution), this._setElementTitle(this._compactButton, "ToggleAttribution"), this._innerContainer = lt.create("div", "maplibregl-ctrl-attrib-inner", this._container), this._updateAttributions(), this._updateCompact(), this._map.on("styledata", this._updateData), this._map.on("sourcedata", this._updateData), this._map.on("terrain", this._updateData), this._map.on("resize", this._updateCompact), this._map.on("drag", this._updateCompactMinimize), this._container
    }
    onRemove() {
        lt.remove(this._container), this._map.off("styledata", this._updateData), this._map.off("sourcedata", this._updateData), this._map.off("terrain", this._updateData), this._map.off("resize", this._updateCompact), this._map.off("drag", this._updateCompactMinimize), this._map = void 0, this._compact = void 0, this._attribHTML = void 0
    }
    _setElementTitle(t, e) {
        const i = this._map._getUIString("AttributionControl." + e);
        t.title = i, t.setAttribute("aria-label", i)
    }
    _updateAttributions() {
        if (!this._map.style) return;
        let t = [];
        if (this.options.customAttribution && (Array.isArray(this.options.customAttribution) ? t = t.concat(this.options.customAttribution.map(t => "string" != typeof t ? "" : t)) : "string" == typeof this.options.customAttribution && t.push(this.options.customAttribution)), this._map.style.stylesheet) {
            const t = this._map.style.stylesheet;
            this.styleOwner = t.owner, this.styleId = t.id
        }
        const e = this._map.style.sourceCaches;
        for (const i in e) {
            const s = e[i];
            if (s.used || s.usedForTerrain) {
                const e = s.getSource();
                e.attribution && t.indexOf(e.attribution) < 0 && t.push(e.attribution)
            }
        }
        t = t.filter(t => (t + "").trim()), t.sort((t, e) => t.length - e.length), t = t.filter((e, i) => {
            for (let s = i + 1; s < t.length; s++)
                if (t[s].indexOf(e) >= 0) return 0;
            return 1
        });
        const i = t.join(" | ");
        i !== this._attribHTML && (this._attribHTML = i, t.length ? (this._innerContainer.innerHTML = i, this._container.classList.remove("maplibregl-attrib-empty")) : this._container.classList.add("maplibregl-attrib-empty"), this._updateCompact(), this._editLink = null)
    }
}
class Nr {
    constructor() {
        this._queue = [], this._id = 0, this._cleared = 0, this._currentlyRunning = 0
    }
    add(t) {
        const e = ++this._id;
        return this._queue.push({
            callback: t,
            id: e,
            cancelled: 0
        }), e
    }
    remove(t) {
        const e = this._currentlyRunning,
            i = e ? this._queue.concat(e) : this._queue;
        for (const e of i)
            if (e.id === t) return void(e.cancelled = 1)
    }
    run(t = 0) {
        if (this._currentlyRunning) throw Error("Attempting to run(), but is already running. If you see this, it is likely that some rendering related code silently crashed, causing the task queue to never finish properly and crash the very next frame.");
        const e = this._currentlyRunning = this._queue;
        this._queue = [];
        for (const i of e)
            if (!i.cancelled && (i.callback(t), this._cleared)) break;
        this._cleared = 0, this._currentlyRunning = 0
    }
    clear() {
        this._currentlyRunning && (this._cleared = 1), this._queue = []
    }
}
var jr;
! function(t) {
    t.create = "create", t.load = "load", t.fullLoad = "fullLoad"
}(jr || (jr = {}));
let Ur = null,
    Gr = [];
const qr = 1e3 / 60,
    $r = "loadTime",
    Wr = "fullLoadTime",
    Hr = {
        mark(t) {
            performance.mark(t)
        },
        frame(t) {
            const e = t;
            null != Ur && Gr.push(e - Ur), Ur = e
        },
        clearMetrics() {
            Ur = null, Gr = [], performance.clearMeasures($r), performance.clearMeasures(Wr);
            for (const t in jr) performance.clearMarks(jr[t])
        },
        getPerformanceMetrics() {
            performance.measure($r, jr.create, jr.load), performance.measure(Wr, jr.create, jr.fullLoad);
            const t = performance.getEntriesByName($r)[0].duration,
                e = performance.getEntriesByName(Wr)[0].duration,
                i = Gr.length,
                s = 1 / (Gr.reduce((t, e) => t + e, 0) / i / 1e3),
                n = Gr.filter(t => t > qr).reduce((t, e) => t + (e - qr) / qr, 0);
            return {
                loadTime: t,
                fullLoadTime: e,
                fps: s,
                percentDroppedFrames: n / (i + n) * 100,
                totalFrames: i
            }
        }
    },
    Vr = {
        "AttributionControl.ToggleAttribution": "Toggle attribution",
        "AttributionControl.MapFeedback": "Map feedback",
        "FullscreenControl.Enter": "Enter fullscreen",
        "FullscreenControl.Exit": "Exit fullscreen",
        "GeolocateControl.FindMyLocation": "Find my location",
        "GeolocateControl.LocationNotAvailable": "Location not available",
        "LogoControl.Title": "MapLibre logo",
        "Map.Title": "Map",
        "Marker.Title": "Map marker",
        "NavigationControl.ResetBearing": "Reset bearing to north",
        "NavigationControl.ZoomIn": "Zoom in",
        "NavigationControl.ZoomOut": "Zoom out",
        "Popup.Close": "Close popup",
        "ScaleControl.Feet": "ft",
        "ScaleControl.Meters": "m",
        "ScaleControl.Kilometers": "km",
        "ScaleControl.Miles": "mi",
        "ScaleControl.NauticalMiles": "nm",
        "TerrainControl.Enable": "Enable terrain",
        "TerrainControl.Disable": "Disable terrain",
        "CooperativeGesturesHandler.WindowsHelpText": "Use Ctrl + scroll to zoom the map",
        "CooperativeGesturesHandler.MacHelpText": "Use ⌘ + scroll to zoom the map",
        "CooperativeGesturesHandler.MobileHelpText": "Use two fingers to move the map"
    };
class Xr {
    constructor() {
        this._buckets = []
    }
    addLayerAndGetBeforeId(t, e) {
        let i = -1;
        e = null != e ? e : 2e9;
        for (let t = 0; t <= this._buckets.length; t++) {
            if (t === this._buckets.length || this._buckets[t].bucketID > e) {
                i = t, this._buckets.splice(t, 0, {
                    bucketID: e,
                    layerIDs: []
                });
                break
            }
            if (this._buckets[t].bucketID === e) {
                i = t;
                break
            }
        }
        return this._buckets[i].layerIDs.push(t), i < this._buckets.length - 1 ? this._buckets[i + 1].layerIDs[0] : void 0
    }
    removeLayer(t) {
        for (let e = 0; e < this._buckets.length; e++) {
            const i = this._buckets[e];
            let s = 0;
            for (let n = 0; n < i.layerIDs.length; n++)
                if (i.layerIDs[n] === t) {
                    i.layerIDs.splice(n, 1), s = 1, 0 === i.layerIDs.length && this._buckets.splice(e, 1);
                    break
                } if (s) break
        }
    }
}
const Kr = ct,
    Yr = {
        hash: 0,
        interactive: 1,
        bearingSnap: 7,
        attributionControl: Fr,
        maplibreLogo: 0,
        failIfMajorPerformanceCaveat: 0,
        preserveDrawingBuffer: 0,
        refreshExpiredTiles: 1,
        scrollZoom: 1,
        minZoom: -2,
        maxZoom: 22,
        minPitch: 0,
        maxPitch: 60,
        boxZoom: 1,
        dragRotate: 1,
        dragPan: 1,
        keyboard: 1,
        doubleClickZoom: 1,
        touchZoomRotate: 1,
        touchPitch: 1,
        cooperativeGestures: 0,
        trackResize: 1,
        center: [0, 0],
        zoom: 0,
        bearing: 0,
        pitch: 0,
        roll: 0,
        renderWorldCopies: 1,
        maxTileCacheSize: null,
        maxTileCacheZoomLevels: ut.MAX_TILE_CACHE_ZOOM_LEVELS,
        transformRequest: null,
        transformCameraUpdate: null,
        fadeDuration: 300,
        crossSourceCollisions: 1,
        clickTolerance: 3,
        localIdeographFontFamily: "sans-serif",
        pitchWithRotate: 1,
        rollEnabled: 0,
        validateStyle: 1,
        maxCanvasSize: [4096, 4096],
        cancelPendingTileRequestsWhileZooming: 1
    };
class Jr extends Br {
    constructor(t) {
        Hr.mark(jr.create);
        const e = Object.assign(Object.assign({}, Yr), t);
        if (null != e.minZoom && null != e.maxZoom && e.minZoom > e.maxZoom) throw Error("maxZoom must be greater than or equal to minZoom");
        if (null != e.minPitch && null != e.maxPitch && e.minPitch > e.maxPitch) throw Error("maxPitch must be greater than or equal to minPitch");
        if (null != e.minPitch && e.minPitch < 0) throw Error("minPitch must be greater than or equal to 0");
        if (null != e.maxPitch && e.maxPitch > 85) throw Error("maxPitch must be less than or equal to 85");
        const i = new Ss,
            s = new Rs;
        if (void 0 !== e.minZoom && i.setMinZoom(e.minZoom), void 0 !== e.maxZoom && i.setMaxZoom(e.maxZoom), void 0 !== e.minPitch && i.setMinPitch(e.minPitch), void 0 !== e.maxPitch && i.setMaxPitch(e.maxPitch), void 0 !== e.renderWorldCopies && i.setRenderWorldCopies(e.renderWorldCopies), super(i, s, {
                bearingSnap: e.bearingSnap
            }), this._idleTriggered = 0, this._crossFadingFactor = 1, this._renderTaskQueue = new Nr, this._controls = [], this._mapId = H(), this.layerOrderingRepo = new Xr, this._contextLost = t => {
                t.preventDefault(), this._frameRequest && (this._frameRequest.abort(), this._frameRequest = null), this.fire(new St("webglcontextlost", {
                    originalEvent: t
                }))
            }, this._contextRestored = t => {
                this._setupPainter(), this.resize(), this._update(), this.fire(new St("webglcontextrestored", {
                    originalEvent: t
                }))
            }, this._onMapScroll = t => {
                if (t.target === this._container) return this._container.scrollTop = 0, this._container.scrollLeft = 0, 0
            }, this._onWindowOnline = () => {
                this._update()
            }, this._interactive = e.interactive, this._maxTileCacheSize = e.maxTileCacheSize, this._maxTileCacheZoomLevels = e.maxTileCacheZoomLevels, this._failIfMajorPerformanceCaveat = 1 == e.failIfMajorPerformanceCaveat, this._preserveDrawingBuffer = 1 == e.preserveDrawingBuffer, this._antialias = 1 == e.antialias, this._trackResize = 1 == e.trackResize, this._bearingSnap = e.bearingSnap, this._refreshExpiredTiles = 1 == e.refreshExpiredTiles, this._fadeDuration = e.fadeDuration, this._crossSourceCollisions = 1 == e.crossSourceCollisions, this._collectResourceTiming = 1 == e.collectResourceTiming, this._locale = Object.assign(Object.assign({}, Vr), e.locale), this._clickTolerance = e.clickTolerance, this._overridePixelRatio = e.pixelRatio, this._maxCanvasSize = e.maxCanvasSize, this.transformCameraUpdate = e.transformCameraUpdate, this.cancelPendingTileRequestsWhileZooming = 1 == e.cancelPendingTileRequestsWhileZooming, this._forceWebGL1 = 1 == e.forceWebGL1, this._imageQueueHandle = Pt.addThrottleControl(() => this.isMoving()), this._requestManager = new Et(e.transformRequest), "string" == typeof e.container) {
            if (this._container = document.getElementById(e.container), !this._container) throw Error(`Container '${e.container}' not found.`)
        } else {
            if (!(e.container instanceof HTMLElement)) throw Error("Invalid type: 'container' must be a String or HTMLElement.");
            this._container = e.container
        }
        if (e.maxBounds && this.setMaxBounds(e.maxBounds), this._setupContainer(), this._setupPainter(), this.on("move", () => this._update(0)).on("moveend", () => this._update(0)).on("zoom", () => this._update(1)).once("idle", () => {
                this._idleTriggered = 1
            }), "undefined" != typeof window) {
            addEventListener("online", this._onWindowOnline, 0);
            let t = 0;
            const e = Bn(t => {
                this._trackResize && !this._removed && (this.resize(t), this.redraw())
            }, 50);
            this._resizeObserver = new ResizeObserver(i => {
                t ? e(i) : t = 1
            }), this._resizeObserver.observe(this._container)
        }
        this.handlers = new Dr(this, e), this._hash = e.hash && new Fn("string" == typeof e.hash && e.hash || void 0).addTo(this), this._hash && this._hash._onHashChange() || (this.jumpTo({
            center: e.center,
            zoom: e.zoom,
            bearing: e.bearing,
            pitch: e.pitch,
            roll: e.roll
        }), e.bounds && (this.resize(), this.fitBounds(e.bounds, q({}, e.fitBoundsOptions, {
            duration: 0
        })))), this.resize(), this._localIdeographFontFamily = e.localIdeographFontFamily, this._validateStyle = e.validateStyle, this.on("style.load", () => {
            if (this.transform.unmodified) {
                const t = $(this.style.stylesheet, ["center", "zoom", "bearing", "pitch", "roll"]);
                this.jumpTo(t)
            }
        }), e.style ? this.setStyle(e.style, {
            localIdeographFontFamily: e.localIdeographFontFamily
        }) : this._lazyInitEmptyStyle(), e.attributionControl && this.addControl(new Zr("boolean" == typeof e.attributionControl ? void 0 : e.attributionControl)), this.on("data", t => {
            this._update("style" === t.dataType), this.fire(new St(t.dataType + "data", t))
        }), this.on("dataloading", t => {
            this.fire(new St(t.dataType + "dataloading", t))
        }), this.on("dataabort", t => {
            this.fire(new St("sourcedataabort", t))
        })
    }
    _getMapId() {
        return this._mapId
    }
    addControl(t, e) {
        if (void 0 === e && (e = t.getDefaultPosition ? t.getDefaultPosition() : "top-right"), !t || !t.onAdd) return this.fire(new Rt(Error("Invalid argument to map.addControl(). Argument must be a control with onAdd and onRemove methods.")));
        const i = t.onAdd(this);
        this._controls.push(t);
        const s = this._controlPositions[e];
        return -1 !== e.indexOf("bottom") ? s.insertBefore(i, s.firstChild) : s.appendChild(i), this
    }
    removeControl(t) {
        if (!t || !t.onRemove) return this.fire(new Rt(Error("Invalid argument to map.removeControl(). Argument must be a control with onAdd and onRemove methods.")));
        const e = this._controls.indexOf(t);
        return e > -1 && this._controls.splice(e, 1), t.onRemove(this), this
    }
    hasControl(t) {
        return this._controls.indexOf(t) > -1
    }
    calculateCameraOptionsFromTo(t, e, i, s) {
        return super.calculateCameraOptionsFromTo(t, e, i, s)
    }
    resize(t) {
        var e;
        const i = this._containerDimensions(),
            s = i[0],
            n = i[1],
            r = this._getClampedPixelRatio(s, n);
        if (this._resizeCanvas(s, n, r), this.painter.resize(s, n, r), this.painter.overLimit()) {
            const t = this.painter.context.gl;
            this._maxCanvasSize = [t.drawingBufferWidth, t.drawingBufferHeight];
            const e = this._getClampedPixelRatio(s, n);
            this._resizeCanvas(s, n, e), this.painter.resize(s, n, e)
        }
        this.transform.resize(s, n), null === (e = this._requestedCameraState) || void 0 === e || e.resize(s, n);
        const o = !this._moving;
        return o && (this.stop(), this.fire(new St("movestart", t)).fire(new St("move", t))), this.fire(new St("resize", t)), o && this.fire(new St("moveend", t)), this
    }
    _getClampedPixelRatio(t, e) {
        const {
            0: i,
            1: s
        } = this._maxCanvasSize, n = this.getPixelRatio(), r = t * n, o = e * n;
        return Math.min(r > i ? i / r : 1, o > s ? s / o : 1) * n
    }
    getPixelRatio() {
        var t;
        return null !== (t = this._overridePixelRatio) && void 0 !== t ? t : devicePixelRatio
    }
    setPixelRatio(t) {
        this._overridePixelRatio = t, this.resize()
    }
    getBounds() {
        return this.transform.getBounds()
    }
    getMaxBounds() {
        return this.transform.getMaxBounds()
    }
    setMaxBounds(t) {
        return this.transform.setMaxBounds(Ft.convert(t)), this._update()
    }
    setMinZoom(t) {
        if ((t = null == t ? -2 : t) >= -2 && t <= this.transform.maxZoom) return this.transform.setMinZoom(t), this._update(), this.getZoom() < t && this.setZoom(t), this;
        throw Error("minZoom must be between -2 and the current maxZoom, inclusive")
    }
    getMinZoom() {
        return this.transform.minZoom
    }
    setMaxZoom(t) {
        if ((t = null == t ? 22 : t) >= this.transform.minZoom) return this.transform.setMaxZoom(t), this._update(), this.getZoom() > t && this.setZoom(t), this;
        throw Error("maxZoom must be greater than the current minZoom")
    }
    getMaxZoom() {
        return this.transform.maxZoom
    }
    setMinPitch(t) {
        if ((t = null == t ? 0 : t) < 0) throw Error("minPitch must be greater than or equal to 0");
        if (t >= 0 && t <= this.transform.maxPitch) return this.transform.setMinPitch(t), this._update(), this.getPitch() < t && this.setPitch(t), this;
        throw Error("minPitch must be between 0 and the current maxPitch, inclusive")
    }
    getMinPitch() {
        return this.transform.minPitch
    }
    setMaxPitch(t) {
        if ((t = null == t ? 60 : t) > 85) throw Error("maxPitch must be less than or equal to 85");
        if (t >= this.transform.minPitch) return this.transform.setMaxPitch(t), this._update(), this.getPitch() > t && this.setPitch(t), this;
        throw Error("maxPitch must be greater than the current minPitch")
    }
    getMaxPitch() {
        return this.transform.maxPitch
    }
    getRenderWorldCopies() {
        return this.transform.renderWorldCopies
    }
    setRenderWorldCopies(t) {
        return this.transform.setRenderWorldCopies(t), this._update()
    }
    project(t) {
        return this.transform.locationToScreenPoint(Bt.convert(t))
    }
    unproject(t) {
        return this.transform.screenPointToLocation(h.convert(t))
    }
    isMoving() {
        var t;
        return this._moving || (null === (t = this.handlers) || void 0 === t ? void 0 : t.isMoving())
    }
    isZooming() {
        var t;
        return this._zooming || (null === (t = this.handlers) || void 0 === t ? void 0 : t.isZooming())
    }
    isRotating() {
        var t;
        return this._rotating || (null === (t = this.handlers) || void 0 === t ? void 0 : t.isRotating())
    }
    _saveDelegatedListener(t, e) {
        this._delegatedListeners = this._delegatedListeners || {}, this._delegatedListeners[t] = this._delegatedListeners[t] || [], this._delegatedListeners[t].push(e)
    }
    _removeDelegatedListener(t, e, i) {
        if (!this._delegatedListeners || !this._delegatedListeners[t]) return;
        const s = this._delegatedListeners[t];
        for (let t = 0; t < s.length; t++) {
            const n = s[t];
            if (n.listener === i && n.layers.length === e.length && n.layers.every(t => e.includes(t))) {
                for (const t in n.delegates) this.off(t, n.delegates[t]);
                return void s.splice(t, 1)
            }
        }
    }
    on(t, e) {
        return super.on(t, e)
    }
    once(t, e) {
        return super.once(t, e)
    }
    off(t, e, i) {
        return void 0 === i ? super.off(t, e) : (this._removeDelegatedListener(t, "string" == typeof e ? [e] : e, i), this)
    }
    setStyle(t, e) {
        return 0 != (e = q({}, {
            localIdeographFontFamily: this._localIdeographFontFamily,
            validate: this._validateStyle
        }, e)).diff && e.localIdeographFontFamily === this._localIdeographFontFamily && this.style && t ? (this._diffStyle(t, e), this) : (this._localIdeographFontFamily = e.localIdeographFontFamily, this._updateStyle(t, e))
    }
    setTransformRequest(t) {
        return this._requestManager.setTransformRequest(t), this
    }
    _getUIString(t) {
        const e = this._locale[t];
        if (null == e) throw Error(`Missing UI string '${t}'`);
        return e
    }
    _updateStyle(t, e) {
        var i, s;
        if (e.transformStyle && this.style && !this.style._loaded) return void this.style.once("style.load", () => this._updateStyle(t, e));
        const n = this.style && e.transformStyle ? this.style.serialize() : void 0;
        return this.style && (this.style.setEventedParent(null), this.style._remove()), t ? (this.style = new As(this), this.style.setEventedParent(this, {
            style: this.style
        }), "string" == typeof t ? this.style.loadURL(t, e, n) : this.style.loadJSON(t, e, n), this) : (null === (s = null === (i = this.style) || void 0 === i ? void 0 : i.projection) || void 0 === s || s.destroy(), delete this.style, this)
    }
    _lazyInitEmptyStyle() {
        this.style || (this.style = new As(this), this.style.setEventedParent(this, {
            style: this.style
        }), this.style.loadEmpty())
    }
    _diffStyle(t, e) {
        if ("string" == typeof t) {
            const i = this._requestManager.transformRequest(t, "Style");
            yt(i, new AbortController).then(t => {
                this._updateDiff(t.data, e)
            }).catch(t => {
                t && this.fire(new Rt(t))
            })
        } else "object" == typeof t && this._updateDiff(t, e)
    }
    _updateDiff(t, e) {
        try {
            this.style.setState(t, e) && this._update(1)
        } catch (i) {
            Q(`Unable to perform style diff: ${i.message || i.error || i}.  Rebuilding the style from scratch.`), this._updateStyle(t, e)
        }
    }
    getStyle() {
        if (this.style) return this.style.serialize()
    }
    isStyleLoaded() {
        return this.style ? this.style.loaded() : Q("There is no style added to the map.")
    }
    addSource(t, e) {
        return this._lazyInitEmptyStyle(), this.style.addSource(t, e), this._update(1)
    }
    isSourceLoaded(t) {
        const e = this.style && this.style.sourceCaches[t];
        if (void 0 !== e) return e.loaded();
        this.fire(new Rt(Error(`There is no source with ID '${t}'`)))
    }
    areTilesLoaded() {
        const t = this.style && this.style.sourceCaches;
        for (const e in t) {
            const i = t[e]._tiles;
            for (const t in i) {
                const e = i[t];
                if ("loaded" !== e.state && "errored" !== e.state) return 0
            }
        }
        return 1
    }
    removeSource(t) {
        return this.style.removeSource(t), this._update(1)
    }
    getSource(t) {
        return this.style.getSource(t)
    }
    addLayer(t, e) {
        return this._lazyInitEmptyStyle(), this.style.addLayer(t, e), this._update(1)
    }
    addLayerToBucket(t, e) {
        return this.addLayer(t, this.layerOrderingRepo.addLayerAndGetBeforeId(t.id, e))
    }
    moveLayerToBucket(t, e) {
        this.layerOrderingRepo.removeLayer(t);
        const i = this.layerOrderingRepo.addLayerAndGetBeforeId(t, e);
        return this.style.moveLayer(t, i), this._update(1)
    }
    removeLayer(t) {
        return this.style.removeLayer(t), this.layerOrderingRepo.removeLayer(t), this._update(1)
    }
    getLayer(t) {
        return this.style.getLayer(t)
    }
    getLayersOrder() {
        return this.style.getLayersOrder()
    }
    setLayerZoomRange(t, e, i) {
        return this.style.setLayerZoomRange(t, e, i), this._update(1)
    }
    getContainer() {
        return this._container
    }
    getCanvasContainer() {
        return this._canvasContainer
    }
    getCanvas() {
        return this._canvas
    }
    _containerDimensions() {
        let t = 0,
            e = 0;
        return this._container && (t = this._container.clientWidth || 400, e = this._container.clientHeight || 300), [t, e]
    }
    _setupContainer() {
        const t = this._container;
        t.classList.add("maplibregl-map");
        const e = this._canvasContainer = lt.create("div", "maplibregl-canvas-container", t);
        this._interactive && e.classList.add("maplibregl-interactive"), this._canvas = lt.create("canvas", "maplibregl-canvas", e), this._canvas.addEventListener("webglcontextlost", this._contextLost, 0), this._canvas.addEventListener("webglcontextrestored", this._contextRestored, 0), this._canvas.setAttribute("tabindex", this._interactive ? "0" : "-1"), this._canvas.setAttribute("aria-label", this._getUIString("Map.Title")), this._canvas.setAttribute("role", "region");
        const i = this._containerDimensions(),
            s = this._getClampedPixelRatio(i[0], i[1]);
        this._resizeCanvas(i[0], i[1], s);
        const n = this._controlContainer = lt.create("div", "maplibregl-control-container", t),
            r = this._controlPositions = {};
        ["top-left", "top-right", "bottom-left", "bottom-right"].forEach(t => {
            r[t] = lt.create("div", `maplibregl-ctrl-${t} `, n)
        }), this._container.addEventListener("scroll", this._onMapScroll, 0)
    }
    _resizeCanvas(t, e, i) {
        this._canvas.width = Math.floor(i * t), this._canvas.height = Math.floor(i * e), this._canvas.style.width = t + "px", this._canvas.style.height = e + "px"
    }
    _setupPainter() {
        const t = {
            alpha: 1,
            stencil: 1,
            depth: 1,
            failIfMajorPerformanceCaveat: this._failIfMajorPerformanceCaveat,
            preserveDrawingBuffer: this._preserveDrawingBuffer,
            antialias: this._antialias || 0
        };
        let e = null;
        this._canvas.addEventListener("webglcontextcreationerror", i => {
            e = {
                requestedAttributes: t
            }, i && (e.statusMessage = i.statusMessage, e.type = i.type)
        }, {
            once: 1
        });
        const i = !this._forceWebGL1 && this._canvas.getContext("webgl2", t) || this._canvas.getContext("webgl", t);
        if (!i) {
            const t = "Failed to initialize WebGL";
            throw e ? (e.message = t, Error(JSON.stringify(e))) : Error(t)
        }
        this.painter = new Dn(i, this.transform), vt.testSupport(i)
    }
    migrateProjection(t, e) {
        super.migrateProjection(t, e), this.painter.transform = t, this.fire(new St("projectiontransition", {
            newProjection: this.style.projection.name
        }))
    }
    loaded() {
        return !this._styleDirty && !this._sourcesDirty && !!this.style && this.style.loaded()
    }
    _update(t) {
        return this.style && this.style._loaded ? (this._styleDirty = this._styleDirty || t, this._sourcesDirty = 1, this.triggerRepaint(), this) : this
    }
    _requestRenderFrame(t) {
        return this._update(), this._renderTaskQueue.add(t)
    }
    _cancelRenderFrame(t) {
        this._renderTaskQueue.remove(t)
    }
    _render(t) {
        const e = this._idleTriggered ? this._fadeDuration : 0;
        if (this.painter.context.setDirty(), this.painter.setBaseState(), this._renderTaskQueue.run(t), this._removed) return;
        let i = 0;
        if (this.style && this._styleDirty) {
            this._styleDirty = 0;
            const t = this.transform.zoom,
                s = ht.now();
            this.style.zoomHistory.update(t, s);
            const n = new zs(t, {
                    now: s,
                    fadeDuration: e,
                    zoomHistory: this.style.zoomHistory,
                    transition: this.style.getTransition()
                }),
                r = n.crossFadingFactor();
            1 === r && r === this._crossFadingFactor || (i = 1, this._crossFadingFactor = r), this.style.update(n)
        }
        const s = this.transform.newFrameUpdate();
        this.style && (this._sourcesDirty || s.forceSourceUpdate) && (this._sourcesDirty = 0, this.style._updateSources(this.transform)), this.transform.setMinElevationForCurrentTile(0), this.transform.setElevation(0), s.fireProjectionEvent && this.fire(new St("projectiontransition", s.fireProjectionEvent)), this.fire(new St("prerender")), this.painter.render(this.style, {
            showTileBoundaries: this._showTileBoundaries,
            rotating: this.isRotating(),
            zooming: this.isZooming(),
            moving: this.isMoving(),
            fadeDuration: e,
            showPadding: this.showPadding
        }), this.fire(new St("render")), this.loaded() && !this._loaded && (this._loaded = 1, Hr.mark(jr.load), this.fire(new St("load"))), this.style && (this.style.hasTransitions() || i) && (this._styleDirty = 1);
        const n = this._sourcesDirty || this._styleDirty || this.style.projection.isRenderingDirty() || this.transform.isRenderingDirty();
        return n || this._repaint ? this.triggerRepaint() : !this.isMoving() && this.loaded() && this.fire(new St("idle")), !this._loaded || this._fullyLoaded || n || (this._fullyLoaded = 1, Hr.mark(jr.fullLoad)), this
    }
    redraw() {
        return this.style && (this._frameRequest && (this._frameRequest.abort(), this._frameRequest = null), this._render(0)), this
    }
    remove() {
        var t;
        this._hash && this._hash.remove();
        for (const t of this._controls) t.onRemove(this);
        this._controls = [], this._frameRequest && (this._frameRequest.abort(), this._frameRequest = null), this._renderTaskQueue.clear(), this.painter.destroy(), this.handlers.destroy(), delete this.handlers, this.setStyle(null), "undefined" != typeof window && removeEventListener("online", this._onWindowOnline, 0), Pt.removeThrottleControl(this._imageQueueHandle), null === (t = this._resizeObserver) || void 0 === t || t.disconnect(), this._canvas.removeEventListener("webglcontextrestored", this._contextRestored, 0), this._canvas.removeEventListener("webglcontextlost", this._contextLost, 0), lt.remove(this._canvasContainer), lt.remove(this._controlContainer), this._container.removeEventListener("scroll", this._onMapScroll, 0), this._container.classList.remove("maplibregl-map"), Hr.clearMetrics(), this._removed = 1, this.fire(new St("remove"))
    }
    triggerRepaint() {
        this.style && !this._frameRequest && (this._frameRequest = new AbortController, ht.frameAsync(this._frameRequest).then(t => {
            Hr.frame(t), this._frameRequest = null, this._render(t)
        }).catch(() => {}))
    }
    get showTileBoundaries() {
        return !!this._showTileBoundaries
    }
    set showTileBoundaries(t) {
        this._showTileBoundaries !== t && (this._showTileBoundaries = t, this._update())
    }
    get showPadding() {
        return !!this._showPadding
    }
    set showPadding(t) {
        this._showPadding !== t && (this._showPadding = t, this._update())
    }
    get showOverdrawInspector() {
        return !!this._showOverdrawInspector
    }
    set showOverdrawInspector(t) {
        this._showOverdrawInspector !== t && (this._showOverdrawInspector = t, this._update())
    }
    get repaint() {
        return !!this._repaint
    }
    set repaint(t) {
        this._repaint !== t && (this._repaint = t, this.triggerRepaint())
    }
    get vertices() {
        return !!this._vertices
    }
    set vertices(t) {
        this._vertices = t, this._update()
    }
    get version() {
        return Kr
    }
    getCameraTargetElevation() {
        return this.transform.elevation
    }
}
var Qr;

function to(t, e, i) {
    const s = document.createElement(t);
    return s.className = e || "", i && i.appendChild(s), s
}

function eo(t) {
    const e = t.parentNode;
    e && e.lastChild !== t && e.appendChild(t)
}

function io(t) {
    const e = t.parentNode;
    e && e.firstChild !== t && e.insertBefore(t, e.firstChild)
}

function so(t, e, i) {
    const s = e || new h(0, 0);
    t.style.transform = `translate3d(${s.x}px,${s.y}px,0)${i ? ` scale(${i})` : ""}`
}
const no = new WeakMap;

function ro(t, e) {
    no.set(t, e), so(t, e)
}

function oo(t) {
    var e;
    return null !== (e = no.get(t)) && void 0 !== e ? e : new h(0, 0)
}
const ao = "undefined" == typeof document ? {} : document.documentElement.style,
    ho = null !== (Qr = ["userSelect", "WebkitUserSelect"].find(t => t in ao)) && void 0 !== Qr ? Qr : "userSelect";
let lo, co, uo;

function po(t) {
    for (; - 1 === t.tabIndex;) t = t.parentNode;
    t.style && (_o(), co = t, uo = t.style.outlineStyle, t.style.outlineStyle = "none", di.on(window, "keydown", _o))
}

function _o() {
    co && (co.style.outlineStyle = null != uo ? uo : "", co = void 0, uo = void 0, di.off(window, "keydown", _o))
}

function mo(t) {
    return "correspondingElement" in t && t.correspondingElement && (t = t.correspondingElement), void 0 === t.className.baseVal ? t.className : t.className.baseVal
}

function fo(t, e) {
    if (void 0 !== t.classList) return t.classList.contains(e);
    const i = mo(t);
    return i.length > 0 && RegExp("(^|\\s)" + e + "(\\s|$)").test(i)
}

function go(t, e) {
    void 0 === t.className.baseVal ? t.className = e : t.className.baseVal = e
}
const yo = {
    create: to,
    setTransform: so,
    setPosition: ro,
    getPosition: oo,
    addClass: function(t, e) {
        const i = s(e);
        if (void 0 !== t.classList)
            for (const e of i) t.classList.add(e);
        else
            for (const e of i)
                if (!fo(t, e)) {
                    const i = mo(t);
                    go(t, (i ? i + " " : "") + e)
                }
    }
};
var vo, bo, xo, wo;
class To extends(bo = Si) {
    constructor(t) {
        super(Object.assign(Object.assign({}, vo.defaultOptions), t)), this._container = void 0, this._zoom = void 0, this._center = void 0, this._bounds = void 0
    }
    onAdd(t) {
        return this._container || (this._container = this._initContainer(), this._container.classList.add("leaflet-zoom-animated")), this.getPane().appendChild(this._container), this._resizeContainer(), this._onMoveEnd(), this
    }
    onRemove(t) {
        return this._destroyContainer(), this
    }
    getEvents() {
        return {
            viewreset: this._reset,
            zoom: this._onZoom,
            moveend: this._onMoveEnd,
            zoomend: this._onZoomEnd,
            resize: this._resizeContainer,
            move: this.options.continuous ? this._onMoveEnd : void 0
        }
    }
    _onZoom() {
        if (!this.leafletMap) throw new a;
        this._updateTransform(this.leafletMap.getCenter(), this.leafletMap.getZoom())
    }
    _updateTransform(t, e) {
        var i, s;
        if (!this.leafletMap || !this._container) throw new a;
        const n = this.leafletMap,
            r = n.getZoomScale(e, this._zoom),
            o = n.getSize().multiplyBy(.5 + (null !== (i = this.options.padding) && void 0 !== i ? i : 0)),
            h = n.project(null !== (s = this._center) && void 0 !== s ? s : n.getCenter(), e),
            l = o.multiplyBy(-r).add(h).subtract(this.leafletMap._getNewPixelOrigin(t, e));
        mi(this._container, l, r)
    }
    _onMoveEnd(t) {
        var e;
        if (!this.leafletMap) throw new a;
        const i = this.leafletMap,
            s = null !== (e = this.options.padding) && void 0 !== e ? e : 0,
            n = i.getSize(),
            r = i.containerPointToLayerPoint(n.multiplyBy(-s)).round();
        this._bounds = new Ri(r, r.add(n.multiplyBy(1 + 2 * s)).round()), this._center = i.getCenter(), this._zoom = i.getZoom(), this._updateTransform(this._center, this._zoom), this._onSettled(t)
    }
    _reset() {
        var t, e;
        if (!this.leafletMap) throw new a;
        this._onSettled(), this._updateTransform(null !== (t = this._center) && void 0 !== t ? t : this.leafletMap.getCenter(), null !== (e = this._zoom) && void 0 !== e ? e : this.leafletMap.getZoom()), this._onViewReset && this._onViewReset()
    }
    _initContainer() {
        return to("div")
    }
    _destroyContainer() {
        this._container && (di.off(this._container), this._container.remove(), this._container = void 0)
    }
    _resizeContainer() {
        var t;
        if (!this.leafletMap || !this._container) throw new a;
        const e = null !== (t = this.options.padding) && void 0 !== t ? t : 0,
            i = this.leafletMap.getSize().multiplyBy(1 + 2 * e).round();
        return this._container.style.width = i.x + "px", this._container.style.height = i.y + "px", i
    }
}
vo = To, To.defaultOptions = Object.assign(Object.assign({}, Reflect.get(bo, "defaultOptions", vo)), {
    padding: .1,
    continuous: 0
});
class Mo extends(wo = To) {
    constructor(t) {
        super(Object.assign(Object.assign({}, xo.defaultOptions), t)), this._layers = {}, r(this)
    }
    onAdd(t) {
        return super.onAdd(t), this.on("update", this._updatePaths, this), this
    }
    onRemove(t) {
        return super.onRemove(t), this.off("update", this._updatePaths, this), this
    }
    _onZoomEnd() {
        for (const t in this._layers) Object.prototype.hasOwnProperty.call(this._layers, t) && this._layers[t]._project()
    }
    _updatePaths() {
        for (const t in this._layers) Object.prototype.hasOwnProperty.call(this._layers, t) && this._layers[t]._update()
    }
    _onViewReset() {
        for (const t in this._layers) Object.prototype.hasOwnProperty.call(this._layers, t) && this._layers[t]._reset()
    }
    _onSettled() {
        this._update()
    }
}

function Po(t, e) {
    di.on(t, "click", t => {
        if (!e.leafletMap) throw new a;
        const i = e.leafletMap.maplibreMap,
            s = lt.mousePos(i._canvas, t),
            n = De(i.unproject(s)),
            r = {
                containerPoint: s,
                latlng: n,
                layerPoint: e.leafletMap.latLngToLayerPoint(n),
                target: e,
                type: "click",
                originalEvent: t
            };
        e.fire("click", r), t.stopPropagation()
    })
}

function Eo(t) {
    di.off(t, "click")
}

function Lo(t) {
    return document.createElementNS("http://www.w3.org/2000/svg", t)
}
xo = Mo, Mo.defaultOptions = Object.assign(Object.assign({}, Reflect.get(wo, "defaultOptions", xo)), {
    tolerance: 0
});
class Co extends Mo {
    _initContainer() {
        const t = Lo("svg");
        return t.setAttribute("pointer-events", "none"), this._rootGroup = Lo("g"), t.appendChild(this._rootGroup), t
    }
    _destroyContainer() {
        super._destroyContainer(), this._rootGroup = void 0, this._svgSize = void 0
    }
    _resizeContainer() {
        const t = super._resizeContainer();
        if (!this._container) throw Error("SVG container not initialized.");
        return this._svgSize && this._svgSize.equals(t) || (this._svgSize = t, this._container.setAttribute("width", "" + t.x), this._container.setAttribute("height", "" + t.y)), t
    }
    _update() {
        if (!this._container || !this._bounds) throw Error("SVG container not initialized.");
        const t = this._bounds,
            e = t.getSize();
        this._container.setAttribute("viewBox", [t.min.x, t.min.y, e.x, e.y].join(" ")), this.fire("update")
    }
    _initPath(t) {
        const e = t._path = Lo("path");
        t.options.className && e.classList.add(...s(t.options.className)), t.options.interactive && e.classList.add("leaflet-interactive"), this._updateStyle(t), this._layers[r(t)] = t
    }
    _addPath(t) {
        this._rootGroup || this._initContainer(), this._rootGroup.appendChild(t._path), t.addInteractiveTarget(t._path), Po(t._path, t)
    }
    _removePath(t) {
        t._path.remove(), t.removeInteractiveTarget(t._path), Eo(t._path), delete this._layers[r(t)]
    }
    _updatePath(t) {
        t._project(), t._update()
    }
    _updateStyle(t) {
        const e = t._path,
            i = t.options;
        e && (i.stroke ? (e.setAttribute("stroke", i.color), e.setAttribute("stroke-opacity", "" + i.opacity), e.setAttribute("stroke-width", "" + i.weight), e.setAttribute("stroke-linecap", i.lineCap), e.setAttribute("stroke-linejoin", i.lineJoin), i.dashArray ? e.setAttribute("stroke-dasharray", "string" == typeof i.dashArray ? i.dashArray : "" + i.dashArray) : e.removeAttribute("stroke-dasharray"), i.dashOffset ? e.setAttribute("stroke-dashoffset", i.dashOffset) : e.removeAttribute("stroke-dashoffset")) : e.setAttribute("stroke", "none"), i.fill ? (e.setAttribute("fill", i.fillColor || i.color), e.setAttribute("fill-opacity", "" + i.fillOpacity), e.setAttribute("fill-rule", i.fillRule || "evenodd")) : e.setAttribute("fill", "none"))
    }
    _updatePoly(t, e) {
        this._setPath(t, function(t, e) {
            let i = "";
            for (let s = 0, n = t.length; s < n; s++) {
                const n = t[s];
                for (let t = 0, e = n.length; t < e; t++) {
                    const e = n[t];
                    i += `${(t ? "L" : "M") + e.x} ${e.y}`
                }
                i += e ? "z" : ""
            }
            return i || "M0 0"
        }(t._parts, null != e ? e : 0))
    }
    _updateCircle(t) {
        const e = t._point,
            i = Math.max(Math.round(t._radius), 1),
            s = `a${i},${Math.max(Math.round(t._radiusPixels), 1) || i} 0 1,0 `,
            n = t._empty() ? "M0 0" : `M${e.x - i},${e.y}${s}${2 * i},0 ${s}${2 * -i},0 `;
        this._setPath(t, n)
    }
    _setPath(t, e) {
        t._path.setAttribute("d", e)
    }
    _bringToFront(t) {
        ! function(t) {
            const e = t.parentNode;
            e && e.lastChild !== t && e.appendChild(t)
        }(t._path)
    }
    _bringToBack(t) {
        ! function(t) {
            const e = t.parentNode;
            e && e.firstChild !== t && e.insertBefore(t, e.firstChild)
        }(t._path)
    }
}

function So(t) {
    return new Co(t)
}
class Ro extends Mo {
    constructor() {
        super(...arguments), this._postponeUpdatePaths = 0, this._layerInfos = {}
    }
    getEvents() {
        return q(super.getEvents(), {
            viewprereset: this._onViewPreReset
        })
    }
    _onViewPreReset() {
        this._postponeUpdatePaths = 1
    }
    onAdd(t) {
        return super.onAdd(t), this._draw(), this
    }
    _initContainer() {
        const t = document.createElement("canvas");
        di.on(t, "mousemove", this._onMouseMove, this), di.on(t, "click dblclick mousedown mouseup contextmenu", this._onClick, this), di.on(t, "mouseout", this._handleMouseOut, this), t._leaflet_disable_events = 1;
        const e = t.getContext("2d");
        if (!e) throw Error("Failed to create Canvas2D context.");
        return this._ctx = e, t
    }
    _destroyContainer() {
        wi(this._redrawRequest), delete this._ctx, super._destroyContainer()
    }
    _resizeContainer() {
        const t = super._resizeContainer(),
            e = this._ctxScale = window.devicePixelRatio;
        return this._container.width = e * t.x, this._container.height = e * t.y, t
    }
    _updatePaths() {
        if (this._postponeUpdatePaths) return;
        let t;
        this._redrawBounds = void 0;
        for (const e in this._layers) Object.prototype.hasOwnProperty.call(this._layers, e) && (t = this._layers[e], t._update());
        this._redraw()
    }
    _update() {
        var t, e, i, s;
        if (!this.leafletMap) throw new a;
        if (this.leafletMap._animatingZoom && this._bounds) return;
        if (!this._ctx) return;
        const n = this._bounds,
            r = this._ctxScale;
        this._ctx.setTransform(r, 0, 0, r, -(null !== (e = null === (t = null == n ? void 0 : n.min) || void 0 === t ? void 0 : t.x) && void 0 !== e ? e : 0) * r, -(null !== (s = null === (i = null == n ? void 0 : n.min) || void 0 === i ? void 0 : i.y) && void 0 !== s ? s : 0) * r), this.fire("update")
    }
    _reset() {
        super._reset(), this._postponeUpdatePaths && (this._postponeUpdatePaths = 0, this._updatePaths())
    }
    _initPath(t) {
        this._layers[r(t)] = t;
        const e = {
            layer: t,
            prev: this._drawLast,
            next: void 0
        };
        this._layerInfos[r(t)] = {
            drawOrder: e
        }, this._updateDashArray(t), this._drawLast && (this._drawLast.next = e), this._drawLast = e, this._drawFirst = this._drawFirst || this._drawLast
    }
    _addPath(t) {
        this._requestRedraw(t)
    }
    _removePath(t) {
        const e = r(t),
            i = this._layerInfos[e].drawOrder,
            {
                prev: s,
                next: n
            } = i;
        n ? n.prev = s : this._drawLast = s, s ? s.next = n : this._drawFirst = n, delete this._layerInfos[e], delete this._layers[e], this._requestRedraw(t)
    }
    _updatePath(t) {
        this._extendRedrawBounds(t), t._project(), t._update(), this._requestRedraw(t)
    }
    _updateStyle(t) {
        this._updateDashArray(t), this._requestRedraw(t)
    }
    _updateDashArray(t) {
        var e;
        if ("string" == typeof t.options.dashArray) {
            const e = t.options.dashArray.split(/[, ]+/),
                i = [];
            for (let t = 0; t < e.length; t++) {
                const s = Number(e[t]);
                if (isNaN(s)) return;
                i.push(s)
            }
            this._layerInfos[r(t)].dashArray = i
        } else this._layerInfos[r(t)].dashArray = null !== (e = t.options.dashArray) && void 0 !== e ? e : void 0
    }
    _requestRedraw(t) {
        this.map && (this._extendRedrawBounds(t), this._redrawRequest = this._redrawRequest || xi(this._redraw, this))
    }
    _extendRedrawBounds(t) {
        if (t._pxBounds) {
            const e = (t.options.weight || 0) + 1;
            this._redrawBounds = this._redrawBounds || new Ri, this._redrawBounds.extend(t._pxBounds.min.subtract([e, e])), this._redrawBounds.extend(t._pxBounds.max.add([e, e]))
        }
    }
    _redraw() {
        this._redrawRequest = void 0, this._redrawBounds && (this._redrawBounds.min.x = Math.floor(this._redrawBounds.min.x), this._redrawBounds.min.y = Math.floor(this._redrawBounds.min.y), this._redrawBounds.max.x = Math.ceil(this._redrawBounds.max.x), this._redrawBounds.max.y = Math.ceil(this._redrawBounds.max.y)), this._clear(), this._draw(), this._redrawBounds = void 0
    }
    _clear() {
        if (!this._ctx) return;
        const t = this._redrawBounds;
        if (t) {
            const e = t.getSize();
            this._ctx.clearRect(t.min.x, t.min.y, e.x, e.y)
        } else this._ctx.save(), this._ctx.setTransform(1, 0, 0, 1, 0, 0), this._ctx.clearRect(0, 0, this._container.width, this._container.height), this._ctx.restore()
    }
    _draw() {
        if (!this._ctx) return;
        let t;
        const e = this._redrawBounds;
        this._ctx.save();
        try {
            if (e) {
                const t = e.getSize();
                this._ctx.beginPath(), this._ctx.rect(e.min.x, e.min.y, t.x, t.y), this._ctx.clip()
            }
            this._drawing = 1;
            for (let i = this._drawFirst; i; i = i.next) t = i.layer, (!e || t._pxBounds && t._pxBounds.intersects(e)) && t._updatePath()
        } finally {
            this._drawing = 0, this._ctx.restore()
        }
    }
    _updatePoly(t, e) {
        if (!this._drawing || !this._ctx) return;
        const i = t._parts,
            s = i.length,
            n = this._ctx;
        if (s) {
            n.beginPath();
            for (let t = 0; t < s; t++) {
                for (let e = 0, s = i[t].length; e < s; e++) {
                    const s = i[t][e];
                    n[e ? "lineTo" : "moveTo"](s.x, s.y)
                }
                e && n.closePath()
            }
            this._fillStroke(n, t)
        }
    }
    _updateCircle(t) {
        if (!this._drawing || t._empty() || !this._ctx) return;
        const e = t._point,
            i = this._ctx,
            s = Math.max(Math.round(t._radius), 1),
            n = (Math.max(Math.round(t._radiusPixels), 1) || s) / s;
        1 !== n && (i.save(), i.scale(1, n)), i.beginPath(), i.arc(e.x, e.y / n, s, 0, 2 * Math.PI, 0), 1 !== n && i.restore(), this._fillStroke(i, t)
    }
    _fillStroke(t, e) {
        var i;
        const s = e.options;
        s.fill && (t.globalAlpha = null !== (i = s.fillOpacity) && void 0 !== i ? i : 1, t.fillStyle = s.fillColor || s.color, t.fill(s.fillRule || "evenodd")), s.stroke && 0 !== s.weight && (t.setLineDash && t.setLineDash(e.options && this._layerInfos[r(e)].dashArray || []), t.globalAlpha = s.opacity, t.lineWidth = s.weight, t.strokeStyle = s.color, t.lineCap = s.lineCap, t.lineJoin = s.lineJoin, t.stroke())
    }
    _onClick(t) {
        if (!this.leafletMap) throw new a;
        const e = this.leafletMap.mouseEventToLayerPoint(t);
        let i;
        for (let s = this._drawFirst; s; s = s.next) {
            const n = s.layer;
            n.options.interactive && n._containsPoint(e) && ("click" !== t.type && "preclick" !== t.type || !this.leafletMap._draggableMoved(n)) && (i = n)
        }
        this._fireEvent(i ? [i] : void 0, t)
    }
    _onMouseMove(t) {
        if (!this.leafletMap) throw new a;
        if (!this.map || this.leafletMap.draggingMoving || this.leafletMap._animatingZoom) return;
        const e = this.leafletMap.mouseEventToLayerPoint(t);
        this._handleMouseHover(t, e)
    }
    _handleMouseOut(t) {
        const e = this._hoveredLayer;
        e && (this._container.classList.remove("leaflet-interactive"), this._fireEvent([e], t, "mouseout"), this._hoveredLayer = void 0, this._mouseHoverThrottled = 0)
    }
    _handleMouseHover(t, e) {
        if (this._mouseHoverThrottled) return;
        let i;
        for (let t = this._drawFirst; t; t = t.next) {
            const s = t.layer;
            s.options.interactive && s._containsPoint(e) && (i = s)
        }
        i !== this._hoveredLayer && (this._handleMouseOut(t), i && (this._container.classList.add("leaflet-interactive"), this._fireEvent([i], t, "mouseover"), this._hoveredLayer = i)), this._fireEvent(this._hoveredLayer ? [this._hoveredLayer] : void 0, t), this._mouseHoverThrottled = 1, setTimeout(() => {
            this._mouseHoverThrottled = 0
        }, 32)
    }
    _fireEvent(t, e, i) {
        if (!this.leafletMap) throw new a;
        this.leafletMap._fireDOMEvent(e, i || e.type, t)
    }
    _bringToFront(t) {
        const e = this._layerInfos[r(t)].drawOrder;
        if (!e) return;
        const {
            prev: i,
            next: s
        } = e;
        s && (s.prev = i, i ? i.next = s : s && (this._drawFirst = s), e.prev = this._drawLast, this._drawLast.next = e, e.next = void 0, this._drawLast = e, this._requestRedraw(t))
    }
    _bringToBack(t) {
        const e = this._layerInfos[r(t)].drawOrder;
        if (!e) return;
        const {
            prev: i,
            next: s
        } = e;
        i && (i.next = s, s ? s.prev = i : i && (this._drawLast = i), e.prev = void 0, e.next = this._drawFirst, this._drawFirst.prev = e, this._drawFirst = e, this._requestRedraw(t))
    }
}

function Io(t) {
    return new Ro(t)
}
const Ao = {
    R: 6378137,
    MAX_LATITUDE: 85.0511287798,
    project(t) {
        const e = Math.PI / 180,
            i = this.MAX_LATITUDE,
            s = Math.sin(Math.max(Math.min(i, t.lat), -i) * e);
        return new h(this.R * t.lng * e, this.R * Math.log((1 + s) / (1 - s)) / 2)
    },
    unproject(t) {
        const e = 180 / Math.PI;
        return new ke((2 * Math.atan(Math.exp(t.y / this.R)) - Math.PI / 2) * e, t.x * e / this.R)
    },
    bounds: function() {
        const t = 20037508.342789244;
        return new Ri([-t, -t], [t, t])
    }()
};
class zo {
    constructor(t, e, i, s) {
        if (Array.isArray(t)) return this._a = t[0], this._b = t[1], this._c = t[2], void(this._d = t[3]);
        this._a = t, this._b = e, this._c = i, this._d = s
    }
    transform(t, e) {
        return this._transform(t.clone(), e)
    }
    _transform(t, e) {
        return t.x = (e = e || 1) * (this._a * t.x + this._b), t.y = e * (this._c * t.y + this._d), t
    }
    untransform(t, e) {
        return new h((t.x / (e = e || 1) - this._b) / this._a, (t.y / e - this._d) / this._c)
    }
}
class Oo {
    latLngToPoint(t, e) {
        const i = this.projection.project(t),
            s = this.scale(e);
        return this.transformation._transform(i, s)
    }
    pointToLatLng(t, e) {
        const i = this.scale(e),
            s = this.transformation.untransform(t, i);
        return this.projection.unproject(s)
    }
    project(t) {
        return this.projection.project(t)
    }
    unproject(t) {
        return this.projection.unproject(t)
    }
    scale(t) {
        return 256 * Math.pow(2, t)
    }
    zoom(t) {
        return Math.log(t / 256) / Math.LN2
    }
    getProjectedBounds(t) {
        const e = this.projection.bounds,
            i = this.scale(t),
            s = this.transformation.transform(e.min, i),
            n = this.transformation.transform(e.max, i);
        return new Ri(s, n)
    }
    get wrapLng() {}
    get wrapLat() {}
    wrapLatLng(t) {
        const e = this.wrapLng ? i(t.lng, this.wrapLng, 1) : t.lng,
            s = this.wrapLat ? i(t.lat, this.wrapLat, 1) : t.lat;
        return new ke(s, e, t.alt)
    }
    wrapLatLngBounds(t) {
        const e = t.getCenter(),
            i = this.wrapLatLng(e),
            s = e.lat - i.lat,
            n = e.lng - i.lng;
        if (0 === s && 0 === n) return t;
        const r = t.getSouthWest(),
            o = t.getNorthEast(),
            a = new ke(r.lat - s, r.lng - n),
            h = new ke(o.lat - s, o.lng - n);
        return new Be(a, h)
    }
}
class ko extends Oo {
    constructor() {
        super(...arguments), this.R = Oe
    }
    get wrapLng() {
        return [-180, 180]
    }
    distance(t, e) {
        return t.distanceTo(e)
    }
}
const Do = .5 / (Math.PI * Ao.R),
    Bo = (Zo = -Do, Array.isArray(Fo = Do) ? new zo(Fo) : new zo(Fo, .5, Zo, .5));
var Fo, Zo;
class No extends ko {
    constructor() {
        super(...arguments), this.projection = Ao, this.transformation = Bo
    }
    get code() {
        return "EPSG:3857"
    }
}
const jo = new No;
new class extends No {
    get code() {
        return "EPSG:900913"
    }
};
const Uo = jo,
    Go = new class extends ko {
        constructor() {
            super(...arguments), this.projection = {
                project(t) {
                    throw Error("Not implemented.")
                },
                unproject(t) {
                    throw Error("Not implemented.")
                },
                bounds: new Ri([0, 0], [0, 0])
            }, this.transformation = new zo(0, 0, 0, 0)
        }
        get code() {
            throw Error("Not implemented - do not use.")
        }
    };
class qo {
    constructor(t) {
        this._map = null, this.options = Object.assign(Object.assign({}, qo.defaultOptions), t)
    }
    getPosition() {
        return this.options.position
    }
    setPosition(t) {
        const e = this._map;
        return e && e.removeControl(this), this.options.position = t, e && e.addControl(this), this
    }
    getContainer() {
        return this._container
    }
    addTo(t) {
        this.remove(), this._map = t;
        const e = this._container = this.onAdd(t),
            i = this.getPosition(),
            s = t.getControlCorner(i);
        if (!s) throw Error("Trying to add a control to map, but control container is not initialized.");
        return e.classList.add("leaflet-control"), i.includes("bottom") ? s.insertBefore(e, s.firstChild) : s.appendChild(e), this._map.on("unload", this.remove, this), this
    }
    remove() {
        return this._map ? (this._container.remove(), this.onRemove && this.onRemove(this._map), this._map.off("unload", this.remove, this), this._map = null, this) : this
    }
    _refocusOnMap(t) {
        this._map && t && t.screenX > 0 && t.screenY > 0 && this._map.getContainer().focus()
    }
}
qo.defaultOptions = {
    position: "topright"
};
class $o extends qo {
    constructor(t) {
        super(Object.assign(Object.assign({}, $o.defaultOptions), t)), this._disabled = 0
    }
    onAdd(t) {
        const e = "leaflet-control-zoom",
            i = yo.create("div", e + " leaflet-bar"),
            s = this.options;
        return this._zoomInButton = this._createButton(s.zoomInText, s.zoomInTitle, e + "-in", i, this._zoomIn), this._zoomOutButton = this._createButton(s.zoomOutText, s.zoomOutTitle, e + "-out", i, this._zoomOut), this._updateDisabled(), t.on("zoomend", this._updateDisabled, this), i
    }
    onRemove(t) {
        t.off("zoomend", this._updateDisabled, this)
    }
    disable() {
        return this._disabled = 1, this._updateDisabled(), this
    }
    enable() {
        return this._disabled = 0, this._updateDisabled(), this
    }
    _zoomIn(t) {
        if (!this._map) throw new a;
        const e = this._map.maplibreMap;
        !this._disabled && e.getZoom() < e.getMaxZoom() && e.zoomIn({
            zoomDelta: this._map.options.zoomDelta * (t.shiftKey ? 3 : 1),
            duration: 200
        })
    }
    _zoomOut(t) {
        if (!this._map) throw new a;
        const e = this._map.maplibreMap;
        !this._disabled && e.getZoom() > e.getMinZoom() && e.zoomOut({
            zoomDelta: this._map.options.zoomDelta * (t.shiftKey ? 3 : 1),
            duration: 200
        })
    }
    _createButton(t, e, i, s, n) {
        const r = yo.create("a", i, s);
        return r.innerHTML = t, r.href = "#", r.title = e, r.setAttribute("role", "button"), r.setAttribute("aria-label", e), di.disableClickPropagation(r), di.on(r, "click", di.stop), di.on(r, "click", n, this), di.on(r, "click", this._refocusOnMap, this), r
    }
    _updateDisabled() {
        if (!this._map) throw new a;
        const t = this._map.maplibreMap,
            e = "leaflet-disabled";
        this._zoomInButton.classList.remove(e), this._zoomOutButton.classList.remove(e), this._zoomInButton.setAttribute("aria-disabled", "false"), this._zoomOutButton.setAttribute("aria-disabled", "false"), (this._disabled || t.getZoom() === t.getMinZoom()) && (this._zoomOutButton.classList.add(e), this._zoomOutButton.setAttribute("aria-disabled", "true")), (this._disabled || t.getZoom() === t.getMaxZoom()) && (this._zoomInButton.classList.add(e), this._zoomInButton.setAttribute("aria-disabled", "true"))
    }
}

function Wo(t) {
    return new $o(t)
}
$o.defaultOptions = {
    position: "topleft",
    zoomInText: '<span aria-hidden="true">+</span>',
    zoomInTitle: "Zoom in",
    zoomOutText: '<span aria-hidden="true">&#x2212;</span>',
    zoomOutTitle: "Zoom out"
};
const Ho = 250;
class Vo extends Ci {
    get maplibreMap() {
        return this._maplibreMap
    }
    get leafletMap() {
        return this
    }
    get fadeAnimated() {
        return 0
    }
    get _animatingZoom() {
        return this._zoomInProgress
    }
    get draggingMoving() {
        return this._moveInProgress
    }
    get interactiveTargets() {
        return this._interactiveTargets
    }
    get webGLPixelRatio() {
        return this._maplibreMap.painter.width / this._maplibreMap.transform.width
    }
    get canvasPixelRatio() {
        return null == this.options.maxCanvasRatio ? this.webGLPixelRatio : Math.min(this.webGLPixelRatio, this.options.maxCanvasRatio)
    }
    constructor(e, i) {
        super(), this._layers = {}, this._pixelOrigin = new h(0, 0), this._interactiveTargets = {}, this._paneRenderers = {}, this._renderer = void 0, this._zoomInProgress = 0, this._moveInProgress = 0, this._lastZoomPixelOrigin = new h(0, 0), this._mouseEvents = ["click", "dblclick", "mouseover", "mouseout", "contextmenu"], this.options = Object.assign(Object.assign({}, Vo.defaultOptions), i);
        const s = {
            container: e,
            minZoom: t((i = this.options).minZoom),
            maxZoom: t(i.maxZoom),
            zoom: t(i.zoom),
            keyboard: i.keyboard,
            attributionControl: i.attributionControl ? void 0 : 0,
            dragRotate: 0,
            pitchWithRotate: 0,
            touchPitch: 0,
            maxPitch: 0,
            minPitch: 0,
            forceWebGL1: i.forceWebGL1,
            doubleClickZoom: i.doubleClickZoom,
            scrollZoom: i.scrollWheelZoom,
            dragPan: i.dragging,
            touchZoomRotate: i.touchZoom
        };
        this._maplibreMap = new Jr(s), this._maplibreMap.touchZoomRotate.disableRotation(), this._lastZoomHandleUpdateZoom = this.getZoom(), i.maxBounds && this.setMaxBounds(i.maxBounds), void 0 !== i.zoom && this._maplibreMap.setZoom(i.zoom), i.center && void 0 !== i.zoom && this.setView(De(i.center), i.zoom, {
            animate: 0
        }), this._maplibreMap.keyboard.disable(), this._maplibreMap.on("zoomstart", () => {
            this._zoomInProgress = 1
        }), this._maplibreMap.on("zoom", () => {
            this._handleZoomOrigin(0)
        }), this._maplibreMap.on("zoomend", () => {
            this._handleZoomOrigin(!this.displayDuringZoom), this._zoomInProgress = 0
        }), this._maplibreMap.on("movestart", () => {
            this._moveInProgress = 1
        }), this._maplibreMap.on("moveend", () => {
            this._moveInProgress = 0
        }), this._maplibreMap.on("move", () => {
            this._updatePaneTranslation()
        }), this._initLayout(), this._initEvents(), this._addLayers(this.options.layers), this._updatePaneTranslation()
    }
    get displayDuringZoom() {
        return this.options.displayDuringZoom
    }
    set displayDuringZoom(t) {
        this.options.displayDuringZoom = t
    }
    _initLayout() {
        const t = this.maplibreMap._container;
        this._baseContainer = void 0;
        for (const e of t.children)
            if (e.classList.contains("maplibregl-canvas-container")) {
                this._baseContainer = e;
                break
            } if (!this._baseContainer) throw Error("Failed to find MapLibre map container.");
        const e = ["leaflet-container"];
        He.touch && e.push("leaflet-touch"), He.retina && e.push("leaflet-retina"), He.safari && e.push("leaflet-safari"), this.fadeAnimated && e.push("leaflet-fade-anim"), this._leafletContainer = to("div", "", this._baseContainer), this._leafletContainer.classList.add(...e), this._leafletContainer.setAttribute("style", "overflow: visible;");
        const {
            position: i
        } = getComputedStyle(this._leafletContainer);
        "absolute" !== i && "relative" !== i && "fixed" !== i && "sticky" !== i && (this._leafletContainer.style.position = "relative"), this._initPanes(), this._initControlPos(), this.options.zoomControl && (this._zoomControl = new $o, this.addControl(this._zoomControl))
    }
    _initEvents(t) {
        const e = t ? di.off : di.on;
        if (!this._baseContainer) throw Error("Failed to find MapLibre map container.");
        this._interactiveTargets = {}, this._interactiveTargets[r(this._baseContainer)] = this, t || (this._maplibreMap.on("load", t => {
            this.fire("load")
        }), this._maplibreMap.on("unload", t => {
            this.fire("unload")
        }), this._maplibreMap.on("zoomstart", t => {
            this.fire("zoomstart")
        }), this._maplibreMap.on("zoom", t => {
            this.fire("zoom")
        }), this._maplibreMap.on("zoomend", t => {
            this.fire("zoomend"), this.fire("viewreset")
        }), this._maplibreMap.on("movestart", t => {
            this.fire("movestart")
        }), this._maplibreMap.on("move", t => {
            this.fire("move")
        }), this._maplibreMap.on("moveend", t => {
            this.fire("moveend")
        }), this._maplibreMap.on("dragstart", t => {
            this.fire("dragstart")
        }), this._maplibreMap.on("drag", t => {
            this.fire("drag")
        }), this._maplibreMap.on("dragend", t => {
            this.fire("dragend")
        }), this._maplibreMap.on("resize", t => {
            this.fire("resize", {
                newSize: new h(this._maplibreMap.transform.width, this._maplibreMap.transform.height)
            })
        })), e(this._baseContainer, "click dblclick mousedown mouseup mouseover mouseout mousemove contextmenu keypress keydown keyup", this._handleDOMEvent, this)
    }
    _initPanes() {
        this._panes = {}, this._mapPane = this.createPane("mapPane", this._leafletContainer), ro(this._mapPane, new h(0, 0)), this.createPane("tilePane"), this.createPane("overlayPane"), this.createPane("shadowPane"), this.createPane("markerPane"), this.createPane("tooltipPane"), this.createPane("popupPane")
    }
    setView(t, e, i) {
        const s = i;
        return this._mapLibreEaseTo(fi(t), void 0 === e ? void 0 : e - 1, s), this
    }
    setZoom(t, e) {
        return this.setView(this.getCenter(), t, e)
    }
    zoomIn(t, e) {
        return t = t || this.options.zoomDelta, this.setZoom(this.getZoom() + t, e)
    }
    zoomOut(t, e) {
        return t = t || this.options.zoomDelta, this.setZoom(this.getZoom() - t, e)
    }
    setZoomAround(t, e, i) {
        const s = this.getZoomScale(e),
            n = this.getSize().divideBy(2),
            r = (t instanceof h ? t : this.latLngToContainerPoint(t)).subtract(n).multiplyBy(1 - 1 / s),
            o = this.containerPointToLatLng(n.add(r));
        return this.setView(o, e, i)
    }
    fitBounds(t, e) {
        var i, s, n;
        let r = null == e ? void 0 : e.padding;
        if (e && void 0 === e.padding && (e.paddingTopLeft || e.paddingBottomRight)) {
            r = {
                top: 0,
                bottom: 0,
                left: 0,
                right: 0
            };
            const t = l(null !== (i = e.paddingTopLeft) && void 0 !== i ? i : [0, 0]),
                n = l(null !== (s = e.paddingBottomRight) && void 0 !== s ? s : [0, 0]);
            e.paddingTopLeft && (r.left = t.x, r.top = t.y), e.paddingBottomRight && (r.right = n.x, r.bottom = n.y)
        }
        return this._maplibreMap.fitBounds(vi(t), {
            animate: null !== (n = null == e ? void 0 : e.animate) && void 0 !== n ? n : 0,
            padding: r,
            easing: gi()
        }), this
    }
    fitWorld(t) {
        return this.fitBounds([
            [-90, -180],
            [90, 180]
        ], t)
    }
    panTo(t, e) {
        return this.setView(t, void 0, e)
    }
    panBy(t, e) {
        var i, s;
        return this._maplibreMap.easeTo({
            center: this._maplibreMap.transform.center,
            animate: null !== (i = null == e ? void 0 : e.animate) && void 0 !== i ? i : 0,
            offset: l(t).mult(-1),
            duration: null !== (s = null == e ? void 0 : e.duration) && void 0 !== s ? s : Ho,
            easing: gi(null == e ? void 0 : e.easeLinearity)
        }), this
    }
    flyTo(t, e, i) {
        var s, n;
        return i = i || {}, this._maplibreMap.flyTo({
            center: fi(t),
            zoom: e,
            animate: null !== (s = null == i ? void 0 : i.animate) && void 0 !== s ? s : 0,
            duration: null !== (n = null == i ? void 0 : i.duration) && void 0 !== n ? n : Ho,
            easing: gi(null == i ? void 0 : i.easeLinearity)
        }), this
    }
    flyToBounds(t, e) {
        var i, s;
        const n = this._maplibreMap.cameraForBounds(vi(t));
        return n ? (this._maplibreMap.flyTo({
            center: n.center,
            zoom: n.zoom,
            animate: null !== (i = null == (e = e || {}) ? void 0 : e.animate) && void 0 !== i ? i : 0,
            duration: null !== (s = null == e ? void 0 : e.duration) && void 0 !== s ? s : Ho,
            easing: gi(null == e ? void 0 : e.easeLinearity)
        }), this) : this
    }
    setMaxBounds(t) {
        return this._maplibreMap.setMaxBounds(vi(t)), this
    }
    setMinZoom(t) {
        return this._maplibreMap.setMinZoom(t), this
    }
    setMaxZoom(t) {
        return this._maplibreMap.setMaxZoom(t), this
    }
    panInsideBounds(t, e) {
        const i = this._maplibreMap.transform.clone();
        return i.setMaxBounds(vi(t)), this._mapLibreEaseTo(i.center, i.zoom, e), this
    }
    stop() {
        return this._maplibreMap.stop(), this
    }
    remove() {
        this._initEvents(1);
        for (const t in this._layers) Object.prototype.hasOwnProperty.call(this._layers, t) && this._layers[t].remove();
        return this._layers = {}, this._clearControlPos(), this._maplibreMap.remove(), this
    }
    createPane(t, e) {
        const i = to("div", "leaflet-pane" + (t ? ` leaflet-${t.replace("Pane", "")}-pane` : ""), e || this._mapPane);
        return t && (this._panes[t] = i), i
    }
    getCenter() {
        const t = this._maplibreMap.getCenter();
        return new ke(t.lat, t.lng)
    }
    getZoom() {
        return this._maplibreMap.getZoom() + 1
    }
    getBounds() {
        const t = this._maplibreMap.getBounds();
        return new Be(t._sw, t._ne)
    }
    getMinZoom() {
        return this._maplibreMap.getMinZoom()
    }
    getMaxZoom() {
        return this._maplibreMap.getMaxZoom()
    }
    getBoundsZoom(t, e, i) {
        const s = yi(t);
        i = l(i || [0, 0]);
        let n = this.getZoom() || 0;
        const r = this.getMinZoom(),
            o = this.getMaxZoom(),
            a = s.getNorthWest(),
            h = s.getSouthEast(),
            c = this.getSize().subtract(i),
            u = Ii(this.project(h, n), this.project(a, n)).getSize(),
            d = this.options.zoomSnap,
            p = c.x / u.x,
            _ = c.y / u.y;
        return n = this.getScaleZoom(e ? Math.max(p, _) : Math.min(p, _), n), d && (n = Math.round(n / (d / 100)) * (d / 100), n = e ? Math.ceil(n / d) * d : Math.floor(n / d) * d), Math.max(r, Math.min(o, n))
    }
    getSize() {
        return new h(this._maplibreMap.transform.width, this._maplibreMap.transform.height)
    }
    getPixelBounds(t, e) {
        const i = this._getTopLeftPoint(void 0 !== t ? De(t) : void 0, e);
        return new Ri(i, i.add(this.getSize()))
    }
    getMercatorBounds() {
        const t = this.maplibreMap.transform.screenPointToMercatorCoordinate(new h(0, 0)),
            e = this.maplibreMap.transform.screenPointToMercatorCoordinate(new h(this.maplibreMap.transform.width, this.maplibreMap.transform.height));
        return new Ri(t, e)
    }
    getPixelOrigin() {
        return this._pixelOrigin
    }
    getPixelWorldBounds(t) {
        return Uo.getProjectedBounds(void 0 === t ? this.getZoom() : t)
    }
    getControlCorner(t) {
        return this._controlCorners ? this._controlCorners[t] : void 0
    }
    getPane(t) {
        return this._panes[t]
    }
    hasPane(t) {
        return void 0 !== this._panes[t]
    }
    getPanes() {
        return this._panes
    }
    getContainer() {
        return this._maplibreMap.getContainer()
    }
    getZoomScale(t, e) {
        return gs(t - (e = void 0 === e ? this.getZoom() : e))
    }
    getScaleZoom(t, e) {
        return e = void 0 === e ? this.getZoom() : e, t <= 0 ? 1 / 0 : ys(t) + e
    }
    project(t, e) {
        return e = void 0 === e ? this.getZoom() : e, Uo.latLngToPoint(De(t), e)
    }
    unproject(t, e) {
        return e = void 0 === e ? this.getZoom() : e, Uo.pointToLatLng(l(t), e)
    }
    layerPointToLatLng(t) {
        const e = l(t).add(this.getPixelOrigin());
        return this.unproject(e)
    }
    latLngToLayerPoint(t) {
        return this.project(De(t)).subtract(this.getPixelOrigin())
    }
    wrapLatLngBounds(t) {
        return Uo.wrapLatLngBounds(yi(t))
    }
    wrapLatLng(t) {
        return Uo.wrapLatLng(De(t))
    }
    distance(t, e) {
        return Uo.distance(De(t), De(e))
    }
    containerPointToLayerPoint(t) {
        return l(t).subtract(this._getMapPanePos())
    }
    layerPointToContainerPoint(t) {
        return l(t).add(this._getMapPanePos())
    }
    containerPointToLatLng(t) {
        return De(this.maplibreMap.unproject(l(t)))
    }
    latLngToContainerPoint(t) {
        return this._maplibreMap.project(fi(De(t)))
    }
    mouseEventToContainerPoint(t) {
        return lt.mousePos(this.maplibreMap.getCanvas(), t)
    }
    mouseEventToLayerPoint(t) {
        return this.containerPointToLayerPoint(this.mouseEventToContainerPoint(t))
    }
    mouseEventToLatLng(t) {
        return this.layerPointToLatLng(this.mouseEventToLayerPoint(t))
    }
    addLayer(e) {
        var i;
        if (!e._layerAdd) throw Error("The provided object is not a Layer.");
        const s = r(e);
        return this._layers[s] || (this._layers[s] = e, function(t) {
            return "TileLayer" === t._type
        }(e) && (void 0 === this.options.minZoom && this.maplibreMap.setMinZoom(Math.max(null !== (i = t(e.options.minZoom)) && void 0 !== i ? i : 0, 0)), void 0 === this.options.maxZoom && this.maplibreMap.setMaxZoom(t(e.options.maxZoom))), e.beforeAdd && e.beforeAdd(this), e._layerAdd({
            target: this
        })), this
    }
    removeLayer(t) {
        const e = r(t);
        return this._layers[e] ? (t.onRemove && t.onRemove(this), delete this._layers[e], this.fire("layerremove", {
            layer: t
        }), t.fire("remove"), t.map = void 0, this) : this
    }
    hasLayer(t) {
        return r(t) in this._layers
    }
    eachLayer(t, e) {
        for (const i in this._layers) Object.prototype.hasOwnProperty.call(this._layers, i) && t.call(e, this._layers[i]);
        return this
    }
    _updatePaneTranslation() {
        const t = this.getSize().divideBy(2),
            e = this.project(this.getCenter()).subtract(t),
            i = this._lastZoomPixelOrigin.subtract(e);
        ro(this._mapPane, new h(Math.round(i.x), Math.round(i.y)))
    }
    _updatePixelOrigin() {
        this._pixelOrigin = this._getNewPixelOrigin(this.getCenter())
    }
    _handleZoomOrigin(t) {
        if (!t) {
            const t = this.getZoom();
            if (Math.abs(t - this._lastZoomHandleUpdateZoom) < .1) return;
            this._lastZoomHandleUpdateZoom = t
        }
        ro(this._mapPane, new h(0, 0)), this._updatePixelOrigin(), this._lastZoomPixelOrigin = this._pixelOrigin
    }
    _addLayers(t) {
        for (let e = 0, i = (t = t ? Array.isArray(t) ? t : [t] : []).length; e < i; e++) this.addLayer(t[e])
    }
    _getTopLeftPoint(t, e) {
        return (t && void 0 !== e ? this._getNewPixelOrigin(t, e) : this.getPixelOrigin()).subtract(this._getMapPanePos())
    }
    _getNewPixelOrigin(t, e) {
        const i = this.getSize().divideBy(2);
        return this.project(t, e).subtract(i).add(this._getMapPanePos())
    }
    _latLngToNewLayerPoint(t, e, i) {
        const s = this._getNewPixelOrigin(i, e);
        return this.project(t, e).subtract(s)
    }
    _latLngBoundsToNewLayerBounds(t, e, i) {
        const s = this._getNewPixelOrigin(i, e);
        return Ii([this.project(t.getSouthWest(), e).subtract(s), this.project(t.getNorthWest(), e).subtract(s), this.project(t.getSouthEast(), e).subtract(s), this.project(t.getNorthEast(), e).subtract(s)])
    }
    _getCenterLayerPoint() {
        return this.containerPointToLayerPoint(this.getSize().divideBy(2))
    }
    _getCenterOffset(t) {
        return this.latLngToLayerPoint(t).subtract(this._getCenterLayerPoint())
    }
    whenReady(t, e) {
        return this._maplibreMap.style._loaded ? t.call(e || this, {
            target: this
        }) : this._maplibreMap.once("style.load", () => {
            t.call(e || this, {
                target: this
            })
        }), this
    }
    async waitReady() {
        return new Promise(t => {
            this.whenReady(t)
        })
    }
    openPopup(t, e, i) {
        return this._initOverlay(Vo.Popup, t, e, i).openOn(this), this
    }
    closePopup(t) {
        return (t = null != t ? t : this._popup) && t.close(), t === this._popup && (this._popup = void 0), this
    }
    openTooltip(t, e, i) {
        return this._initOverlay(Vo.Tooltip, t, e, i).openOn(this), this
    }
    closeTooltip(t) {
        return t.close(), this
    }
    _initOverlay(t, e, i, s) {
        let n;
        return n = e instanceof t ? e : new t(s).setContent(e), i && n.setLatLng(i), n
    }
    _draggableMoved(t) {
        return Ko(t) && t.dragging.enabled() ? t.dragging.moved() : Ko(this) ? this.dragging.moved() : 0
    }
    _findEventTargets(t, e) {
        let i = [],
            s = t.target || t.srcElement,
            n = 0;
        const o = "mouseout" === e || "mouseover" === e;
        for (; s;) {
            const a = this._interactiveTargets[r(s)];
            if (a && ("click" === e || "preclick" === e) && this._draggableMoved(a)) {
                n = 1;
                break
            }
            if (a && a.listens(e, 1)) {
                if (o && !bi(s, t)) break;
                if (i.push(a), o) break
            }
            if (s === this._baseContainer) break;
            if (!Xo(s)) break;
            s = s.parentNode
        }
        return i.length || n || o || !this.listens(e, 1) || (i = [this]), i
    }
    _isClickDisabled(t) {
        for (; t && t !== this._baseContainer;) {
            if (t._leaflet_disable_click || !t.parentNode) return 1;
            t = t.parentNode
        }
    }
    _handleDOMEvent(t) {
        const e = t.target || t.srcElement;
        if (e._leaflet_disable_events || "click" === t.type && this._isClickDisabled(e)) return;
        const i = t.type;
        "mousedown" === i && po(e), "click" === t.type && this.draggingMoving || this._fireDOMEvent(t, i)
    }
    _fireDOMEvent(t, e, i) {
        if ("click" === e) {
            const e = Ti({}, t, {
                type: "preclick"
            });
            this._fireDOMEvent(e, "preclick", i)
        }
        let s = this._findEventTargets(t, e);
        if (i) {
            const t = [];
            for (let s = 0; s < i.length; s++) i[s].listens(e, 1) && t.push(i[s]);
            s = t.concat(s)
        }
        if (!s.length) return;
        "contextmenu" === e && di.preventDefault(t);
        const n = s[0],
            r = {
                originalEvent: t,
                containerPoint: void 0,
                layerPoint: void 0,
                latlng: void 0
            };
        if (function(t) {
                return "keypress" !== t.type && "keydown" !== t.type && "keyup" !== t.type
            }(t)) {
            const e = function(t) {
                return t.getLatLng && (!t._radius || t._radius <= 10)
            }(n);
            r.containerPoint = e ? this.latLngToContainerPoint(n.getLatLng()) : this.mouseEventToContainerPoint(t), r.layerPoint = this.containerPointToLayerPoint(r.containerPoint), r.latlng = e ? n.getLatLng() : this.maplibreMap.unproject(r.containerPoint)
        }
        for (let t = 0; t < s.length; t++)
            if (s[t].fire(e, r, 1), r.originalEvent._stopped || 0 == s[t].options.bubblingMouseEvents && this._mouseEvents.includes(e)) return
    }
    _getMapPanePos() {
        return oo(this._mapPane) || new h(0, 0)
    }
    _mapLibreEaseTo(t, e, i) {
        var s, n;
        this._maplibreMap.easeTo({
            animate: null !== (s = null == i ? void 0 : i.animate) && void 0 !== s ? s : 0,
            center: t,
            zoom: e,
            duration: null !== (n = null == i ? void 0 : i.duration) && void 0 !== n ? n : Ho,
            easing: gi(null == i ? void 0 : i.easeLinearity)
        })
    }
    getRenderer(t) {
        let e = t.options.renderer || t.options.pane && this._getPaneRenderer(t.options.pane) || this.options.renderer || this._renderer;
        return e || (e = this._renderer = this._createRenderer()), this.hasLayer(e) || this.addLayer(e), e
    }
    _getPaneRenderer(t) {
        if ("overlayPane" === t || void 0 === t) return;
        let e = this._paneRenderers[t];
        return void 0 === e && (e = this._createRenderer({
            pane: t
        }), this._paneRenderers[t] = e), e
    }
    _createRenderer(t) {
        return this.options.preferCanvas && Io(t) || So(t)
    }
    getTileBounds(t) {
        t = null != t ? t : Math.ceil(this.getZoom());
        const e = this.maplibreMap,
            i = e.transform.screenPointToLocation(new h(0, 0)),
            s = e.transform.screenPointToLocation(new h(e.transform.width, e.transform.height)),
            n = new h(Yo(i.lng, t), Jo(i.lat, t)),
            r = new h(Yo(s.lng, t), Jo(s.lat, t)),
            o = new Ri(n, r);
        return o.min.y = Math.max(o.min.y, 0), o.max.y = Math.min(o.max.y, Math.pow(2, t) - 1), o
    }
    addControl(t) {
        return t.addTo(this), this
    }
    removeControl(t) {
        return t.remove(), this
    }
    _initControlPos() {
        const t = this._controlCorners = {},
            e = "leaflet-",
            i = this._controlContainer = to("div", e + "control-container", this.getContainer());

        function s(s, n) {
            t[s + n] = to("div", `${e + s} ${e}${n}`, i)
        }
        s("top", "left"), s("top", "right"), s("bottom", "left"), s("bottom", "right")
    }
    _clearControlPos() {
        var t;
        for (const t in this._controlCorners) Object.prototype.hasOwnProperty.call(this._controlCorners, t) && this._controlCorners[t].remove();
        null === (t = this._controlContainer) || void 0 === t || t.remove(), delete this._controlCorners, delete this._controlContainer
    }
}

function Xo(t) {
    return Object.prototype.hasOwnProperty.call(t, "parentNode")
}

function Ko(t) {
    return !!t.dragging
}

function Yo(t, e) {
    return Math.floor(Math.pow(2, e) * (t / 360 + .5))
}

function Jo(t, e, i = 1) {
    const s = Math.sin(t * (Math.PI / 180)),
        n = Math.pow(2, e) * (.5 - .25 * Math.log((1 + s) / (1 - s)) / Math.PI);
    return i ? Math.floor(n) : n
}
var Qo, ta;
Vo.defaultOptions = {
    layers: [],
    zoomSnap: 1,
    zoomDelta: 1,
    closePopupOnClick: 1,
    keyboard: 1,
    attributionControl: 1,
    zoomControl: 1,
    doubleClickZoom: 1,
    scrollWheelZoom: 1,
    dragging: 1,
    touchZoom: 1,
    center: [0, 0],
    forceWebGL1: 0,
    zoom: 0,
    minZoom: null,
    maxZoom: null,
    renderer: null,
    preferCanvas: 0,
    displayDuringZoom: 0,
    maxBounds: null,
    maxCanvasRatio: null
};
class ea extends(ta = Si) {
    constructor(t, e) {
        (null == e ? void 0 : e.pane) && console.warn("LeafletGL tile layers do not support the 'pane' option, since they are drawn using WebGL."), super(Object.assign(Object.assign({}, Qo.defaultOptions), e)), this._type = "TileLayer", this._visible = 1, this._url = t, this.options.minZoom = Math.min(this.options.maxZoom, this.options.minZoom)
    }
    set alwaysLoadTiles(t) {
        this._alwaysLoadTiles = t, this._trySetAlwaysLoaded()
    }
    get alwaysLoadTiles() {
        return this._alwaysLoadTiles
    }
    source() {
        var t, e;
        return null === (e = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap) || void 0 === e ? void 0 : e.getSource(this._getSourceId())
    }
    sourceCache() {
        var t, e, i;
        return null === (i = null === (e = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap) || void 0 === e ? void 0 : e.style) || void 0 === i ? void 0 : i.sourceCaches[this._getSourceId()]
    }
    layer() {
        var t, e;
        return null === (e = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap) || void 0 === e ? void 0 : e.getLayer(this._getLayerId())
    }
    _trySetAlwaysLoaded() {
        var t, e;
        const i = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap,
            s = this._getSourceId(),
            n = null === (e = null == i ? void 0 : i.style) || void 0 === e ? void 0 : e.sourceCaches[s];
        n && (n.alwaysLoadTiles = this._alwaysLoadTiles)
    }
    _trySetVisibility() {
        var t;
        const e = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap;
        if (!e) return;
        const i = e.getLayer(this._getLayerId());
        if (i && (i.visibility = this._visible ? "visible" : "none", this._visible)) {
            const t = this._getSourceId(),
                i = e.style.sourceCaches[t];
            if (!i) throw Error(`Tile cache ${t} does not exist`);
            i.used = 1, i.resume(), i.update(e.transform)
        }
    }
    set visible(t) {
        this._visible = t, this._trySetVisibility()
    }
    get visible() {
        return this._visible
    }
    get id() {
        var t;
        return null === (t = this.layer()) || void 0 === t ? void 0 : t.id
    }
    onAdd(t) {
        return this._containingMap = t, t.whenReady(() => {
            this._addMapLibreObjects()
        }), this
    }
    onRemove(t) {
        return this._removeMapLibreObjects(), this._containingMap = void 0, this
    }
    setOpacity(t) {
        this.options.opacity = t;
        const e = this.layer();
        return e && (e.paint["raster-opacity"] = t), this
    }
    isLoading() {
        return this._containingMap ? !this._containingMap.maplibreMap.loaded() : 0
    }
    redraw() {
        return this._containingMap && this._recreateMaplibreObjects(), this
    }
    getEvents() {
        return {}
    }
    getTileSize() {
        return new h(this.options.tileSize, this.options.tileSize)
    }
    setUrl(t) {
        if (this._url = t, this._containingMap) {
            const t = this._containingMap.maplibreMap,
                e = t.getSource(this._getSourceId()),
                i = this._getSourceId(),
                s = t.style.sourceCaches[i];
            if (!s) throw Error(`Tile cache ${i} does not exist`);
            s.clearTiles(), e.setTiles([this._url])
        }
        return this
    }
    _getLayerId() {
        return this.options.layerId ? this.options.layerId : "_leaflet_tile_layer_" + r(this)
    }
    _getSourceId() {
        return "_leaflet_source_" + r(this)
    }
    _addMapLibreObjects() {
        var e, i, s, n, r, o, h, l, c, u;
        const d = this._getSourceId(),
            p = this._getLayerId(),
            _ = null === (e = this._containingMap) || void 0 === e ? void 0 : e.maplibreMap;
        if (!_) throw new a;
        _.addSource(d, {
            type: "raster",
            tiles: ia(this._url, this.options.subdomains),
            minzoom: null !== (i = this.options.minNativeZoom) && void 0 !== i ? i : this.options.minZoom,
            maxzoom: null !== (s = this.options.maxNativeZoom) && void 0 !== s ? s : this.options.maxZoom,
            attribution: this.getAttribution && null !== (n = this.getAttribution()) && void 0 !== n ? n : "",
            tileSize: null !== (r = this.options.tileSize) && void 0 !== r ? r : 256,
            forceDisableDevicePixelRatioScaling: !this.options.detectRetina
        });
        const m = Object.assign({
            "raster-opacity": this.options.opacity
        }, this.options.paint);
        _.addLayerToBucket({
            id: p,
            source: d,
            type: "raster",
            minzoom: t(this.options.minZoom),
            maxzoom: t(this.options.maxZoom + .999),
            paint: m,
            customShader: null !== (o = this.options.customShader) && void 0 !== o ? o : void 0,
            tileFilter: null !== (h = this.options.tileFilter) && void 0 !== h ? h : void 0,
            preRenderTileCallback: null !== (l = this.options.preRenderTileCallback) && void 0 !== l ? l : void 0,
            postRenderTileCallback: null !== (c = this.options.postRenderTileCallback) && void 0 !== c ? c : void 0
        }, null !== (u = this.options.layerBucketId) && void 0 !== u ? u : void 0), this.options.keepBuffer > 0 && (_.style.sourceCaches[d].tileAabbScale = 1 + 2 * this.options.keepBuffer), this._trySetAlwaysLoaded(), this._trySetVisibility()
    }
    _removeMapLibreObjects() {
        var t;
        const e = null === (t = this._containingMap) || void 0 === t ? void 0 : t.maplibreMap;
        if (!e) throw new a;
        const i = this._getLayerId();
        e.removeLayer(i), e.removeSource(this._getSourceId())
    }
    _recreateMaplibreObjects() {
        const t = this._containingMap;
        if (!t) throw new a;
        this.onRemove(t), this.onAdd(t)
    }
}

function ia(t, e) {
    if (!e || !t.includes("{s}")) return [t];
    let i;
    if (Array.isArray(e)) i = e;
    else {
        i = [];
        for (let t = 0; t < e.length; t++) i.push(e[t])
    }
    const s = [];
    for (const e of i) s.push(t.replaceAll("{s}", e));
    return s
}

function sa(t, e) {
    return new ea(t, e)
}

function na(t) {
    const e = {
            x: t.x,
            y: t.y,
            z: t.z
        },
        i = 1 << e.z;
    return e.x = e.x % i, e.x < 0 && (e.x += i), e.x |= 0, e
}

function ra(t) {
    return `${t.x}_${t.y}_${t.z}`
}

function oa(t, e) {
    return `${t.x + (1 << t.z) * e}_${t.y}_${t.z}`
}

function aa(t) {
    const e = t.split("_");
    return {
        x: parseInt(e[0]),
        y: parseInt(e[1]),
        z: parseInt(e[2]),
        key: t
    }
}
Qo = ea, ea.defaultOptions = Object.assign(Object.assign({}, Reflect.get(ta, "defaultOptions", Qo)), {
    tileSize: 256,
    minZoom: 0,
    maxZoom: 18,
    opacity: 1,
    subdomains: "abc",
    detectRetina: 0,
    pane: null,
    minNativeZoom: null,
    maxNativeZoom: null,
    customShader: null,
    layerId: null,
    preRenderTileCallback: null,
    postRenderTileCallback: null,
    tileFilter: null,
    paint: null,
    keepBuffer: 0,
    layerBucketId: null
});
class ha {
    constructor() {
        this._root = {
            x: 0,
            y: 0,
            z: 0,
            children: [],
            payload: null,
            parent: null
        }
    }
    set(t, e, i, s) {
        const n = null === s;
        t |= 0, e |= 0;
        const r = 1 << (i |= 0);
        if (i < 0 || t < 0 || e < 0 || i > 30 || t >= r || e >= r) throw Error("Quad tree set coordinates are not in valid range.");
        let o = this._root;
        for (; o;) {
            if (o.z === i) {
                if (o.x !== t || o.y !== e) throw Error("Found the wrong quadtree entry!");
                break
            }
            const s = 1 << i - o.z - 1,
                r = t / s | 0,
                a = e / s | 0;
            let h = null;
            for (const t of o.children)
                if (t && t.x === r && t.y === a) {
                    h = t;
                    break
                } if (null === h) {
                if (n) return;
                h = {
                    x: r,
                    y: a,
                    z: o.z + 1,
                    children: [],
                    payload: null,
                    parent: o
                }, o.children.push(h)
            }
            o = h
        }
        const a = o;
        if (a.payload = s, !n) return;
        let h = a;
        for (; null === h.payload && null !== h.parent && 0 === h.children.length;) {
            h.payload = null;
            const t = h.parent;
            for (let e = 0; e < t.children.length; e++)
                if (t.children[e] === h) {
                    t.children.splice(e, 1);
                    break
                } h.parent = null, h = t
        }
    }
    delete(t, e, i) {
        this.set(t, e, i, null)
    }
    gatherOrderedRenderable(t, e, i, s) {
        const n = new Set;
        for (let r = t.min.y; r <= t.max.y; r++)
            for (let o = t.min.x; o <= t.max.x; o++) {
                const t = {
                        x: o,
                        y: r,
                        z: e
                    },
                    a = na(t),
                    h = t.x - a.x >> t.z;
                let l = this._root,
                    c = this._root;
                for (; c && c.z < a.z;) {
                    null !== c.payload && (l = c);
                    const t = 1 << a.z - c.z - 1,
                        e = a.x / t | 0,
                        i = a.y / t | 0;
                    let s = null;
                    for (const t of c.children)
                        if (t && t.x === e && t.y === i) {
                            s = t;
                            break
                        } c = s
                }
                let u = 0;
                c && (u = this._gatherUsableChildren(c, n, h, s)), u || null !== l.payload && a.z - l.z <= i && n.add(oa(l, h))
            }
        const r = [...n].map(t => aa(t));
        return r.sort((t, e) => t.z === e.z ? t.y === e.y ? t.x - e.x : t.y - e.y : t.z - e.z), r
    }
    _gatherUsableChildren(t, e, i, s) {
        if (null !== t.payload) return e.add(oa(t, i)), 1;
        if (0 === s) return 0;
        let n = 0;
        for (const r of t.children) this._gatherUsableChildren(r, e, i, s - 1) && n++;
        return 4 === n
    }
}
const la = "tile aborted";
class ca extends Ci {
    get pendingTilesCount() {
        return this._pendingTiles.size
    }
    get cachedTilesCount() {
        return this._cachedTiles.size
    }
    get requestedTilesCount() {
        return this._cachedTiles.size + this._pendingTiles.size
    }
    constructor(t, e) {
        super(), this._pendingTiles = new Map, this._cachedTiles = new Map, this._quadtree = new ha, this._tileRequests = new Map, this._deleteQueue = new Map, this._deleteLoop = null, this._lastBounds = null, this._lastZoom = null, this.deleteWaitTimeSeconds = 5, this._loadTile = t, this._beforeTileDeleted = e, this._deleteLoop = setInterval(() => {
            this._checkTilesForDeletion()
        }, 1e3)
    }
    getData(t) {
        var e;
        return null !== (e = this._cachedTiles.get(ra(na(t)))) && void 0 !== e ? e : null
    }
    hasTile(t) {
        return this._cachedTiles.has(ra(na(t)))
    }
    forEachTile(t) {
        for (const [e, i] of this._cachedTiles.entries()) t(aa(e), i)
    }
    getOrderedTilePyramid(t, e, i, s) {
        return this._quadtree.gatherOrderedRenderable(t, e, i, s)
    }
    update(t, e, i = 0) {
        if (e = Math.round(e), !i && this._lastBounds && this._lastZoom && this._lastZoom === e && this._lastBounds.equals(t)) return;
        this._lastZoom = e, this._lastBounds = new Ri(t);
        const s = function(t, e) {
                const i = [];
                for (let s = t.min.y; s <= t.max.y; s++)
                    for (let n = t.min.x; n <= t.max.x; n++) {
                        const t = na({
                            x: n,
                            y: s,
                            z: e
                        });
                        i.push(Object.assign(Object.assign({}, t), {
                            key: ra(t)
                        }))
                    }
                return i
            }(t, e),
            n = new Set;
        for (const t of s) {
            const e = ra(t);
            n.add(e)
        }
        const r = [];
        for (const [i] of this._cachedTiles) this._shouldDeleteTile(i, n, t, e) && r.push(aa(i));
        for (const [i] of this._pendingTiles) this._shouldDeleteTile(i, n, t, e) && r.push(aa(i));
        this.manualUpdate(s, r)
    }
    manualUpdate(t, e) {
        for (const e of t) {
            const t = e.key,
                i = this._cachedTiles.has(t),
                s = this._pendingTiles.has(t);
            i || s || this._triggerTileLoad(e), this._deleteQueue.delete(t)
        }
        const i = performance.now() / 1e3;
        for (const t of e) {
            const e = t.key,
                s = this._pendingTiles.get(e);
            s ? (s.abort(la + ": tile deleted"), this._pendingTiles.delete(e)) : this._deleteQueue.has(e) || this._deleteQueue.set(e, i)
        }
    }
    dispose() {
        for (const t of this._pendingTiles.keys()) {
            const e = aa(t);
            this._deleteTile(e)
        }
        for (const t of this._cachedTiles.keys()) {
            const e = aa(t);
            this._deleteTile(e)
        }
        for (const t of this._tileRequests.values())
            for (const e of t.resolves) e({
                status: "disposed"
            });
        this._tileRequests.clear(), null !== this._deleteLoop && (clearInterval(this._deleteLoop), this._deleteLoop = null)
    }
    async awaitTile(t, e) {
        const i = ra(na(t));
        if (this._cachedTiles.has(i)) {
            const t = this._cachedTiles.get(i);
            return t ? {
                status: "success",
                tile: t
            } : {
                status: "failed"
            }
        }
        return new Promise(s => {
            const n = this._tileRequests.get(i);
            n ? n.resolves.push(s) : this._tileRequests.set(i, {
                coords: t,
                resolves: [s]
            }), e && e.addEventListener("abort", () => {
                const t = this._tileRequests.get(i);
                if (!t) return;
                const e = t.resolves.indexOf(s);
                e < 0 || (t.resolves.splice(e, 1), s({
                    status: "aborted"
                }), 0 === t.resolves.length && this._tileRequests.delete(i))
            })
        })
    }
    forceDeleteTile(t) {
        this._deleteTile(Object.assign(Object.assign({}, t), {
            key: ra(t)
        }))
    }
    _checkTilesForDeletion() {
        const t = performance.now() / 1e3,
            e = this._deleteQueue.keys();
        for (const i of e) {
            const e = this._deleteQueue.get(i);
            void 0 !== e && t - e >= this.deleteWaitTimeSeconds && this._deleteTile(aa(i))
        }
    }
    _deleteTile(t) {
        const e = this._pendingTiles.get(t.key);
        if (e) e.abort(la + ": tile deleted"), this._pendingTiles.delete(t.key);
        else if (this._cachedTiles.has(t.key)) {
            const e = this._cachedTiles.get(t.key);
            void 0 !== e && (this.fire("beforetiledeleted", {
                coords: t,
                tile: e
            }), this._beforeTileDeleted && this._beforeTileDeleted(t, e), this._cachedTiles.delete(t.key), this._quadtree.set(t.x, t.y, t.z, null))
        }
        this._deleteQueue.delete(t.key)
    }
    _shouldDeleteTile(t, e, i, s) {
        if (e.has(t)) return 0;
        if (this._pendingTiles.has(t)) return 1;
        const n = aa(t);
        if (n.z < s) {
            const t = 1 << s - n.z,
                e = n.x * t,
                r = n.y * t;
            if (e <= i.max.x && e + t > i.min.x && r <= i.max.y && r + t > i.min.y) return 0
        }
        const r = {
            x: n.x,
            y: n.y,
            z: n.z
        };
        for (; r.z > s;) r.x = r.x / 2 | 0, r.y = r.y / 2 | 0, r.z -= 1;
        const o = ra(r);
        return !this._cachedTiles.has(o) && e.has(o) ? 0 : 1
    }
    async _triggerTileLoad(t) {
        var e;
        const i = new AbortController;
        this._pendingTiles.set(t.key, i);
        let s = null,
            n = 0;
        try {
            s = null !== (e = await this._loadTile(t, i.signal)) && void 0 !== e ? e : null
        } catch (t) {
            i.signal.aborted ? n = 1 : (s = null, console.error(t))
        } finally {
            i.signal.aborted && (n = 1);
            const e = s && !n;
            if (n) null !== s && this._beforeTileDeleted && this._beforeTileDeleted(t, s);
            else {
                this._cachedTiles.set(t.key, s), s && this._quadtree.set(t.x, t.y, t.z, s), this._pendingTiles.delete(t.key);
                const i = this._tileRequests.get(t.key);
                if (i) {
                    for (const t of i.resolves) t(e && s ? {
                        status: "success",
                        tile: s
                    } : {
                        status: "failed"
                    });
                    this._tileRequests.delete(t.key)
                }
            }
            e && this.fire("tileloaded", {
                coords: t,
                tile: s
            }), 0 === this._pendingTiles.size && this.fire("alltilesloaded")
        }
    }
}
var ua, da;
const pa = 256;
class _a extends(da = Si) {
    set showBorders(t) {
        this._showBorders = t
    }
    get showBorders() {
        return this._showBorders
    }
    constructor(t) {
        super(Object.assign(Object.assign({}, ua.defaultOptions), t)), this._showBorders = 0, this._zooming = 0, this._gridTiles = new Map, this._physicalTileSize = new h(pa, pa), this._contentScale = 1, this._onZoom = () => {
            if (!this.leafletMap) throw new a;
            this.leafletMap.displayDuringZoom && (this._updateLevels(), this._update())
        }, this._onZoomStart = () => {
            if (!this.leafletMap) throw new a;
            this._zooming = 1, this.leafletMap.displayDuringZoom || (this._hideShowLayer(1), this._removeAllTiles())
        }, this._onZoomEnd = () => {
            if (!this.leafletMap) throw new a;
            this._zooming = 0, this.leafletMap.displayDuringZoom || (this._removeAllTiles(), this._updateLevels(), this._hideShowLayer(0)), this._update(1)
        }, this._onMapMove = () => {
            this._zooming || (this._hideShowLayer(0), this._update())
        };
        const e = this.getTileSize().x,
            i = Math.pow(2, Math.floor(Math.log2(e)));
        this._physicalTileSize = new h(i, i), this._tileCache = new ca((t, e) => void 0 !== this.options.minZoom && t.z < this.options.minZoom || void 0 !== this.options.maxZoom && t.z > this.options.maxZoom ? Promise.resolve(null) : this._loadTileData(t, e)), this._tileCache.on("tileloaded", () => {
            this._update()
        })
    }
    static getTileSizeForZoomOffset(t) {
        return 256 * Math.pow(2, t)
    }
    get container() {
        return this._container
    }
    get levelTransform() {
        var t;
        return null === (t = this._level) || void 0 === t ? void 0 : t.transform
    }
    async _loadTileData(t, e) {
        return Promise.resolve(null)
    }
    _createTileContents(t, e, i) {
        const s = document.createElement("div");
        s.innerHTML = `${e.z}/${e.x}/${e.y}`, t.appendChild(s);
        const n = this.options.tileSize,
            r = [n instanceof h ? n.x : n, n instanceof h ? n.y : n],
            o = document.createElement("div");
        o.style.cssText = "position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%) rotate(45deg); display: flex; align-items: center; justify-content: center; flex-direction: column; color:white; font-size: 0.75em;", o.innerHTML = '<span>"_createTileContents"</span> <span>not implemented</span>', t.appendChild(o), t.style.border = "1px solid white", t.style.color = "red", t.style.fontSize = "2em", t.style.width = r[0] + "px", t.style.height = r[1] + "px"
    }
    _onTileLoaded(t, e) {
        this.fire("tileload", {
            tile: e,
            coords: t
        })
    }
    reload() {
        return this._removeAllTiles(), this._update(1), this
    }
    onAdd(t) {
        return this._initContainer(), this._updateLevels(), this._init(t), this
    }
    onRemove(t) {
        return this._removeAllTiles(), this._destroy(), this
    }
    getTileSize() {
        const t = this.options.tileSize;
        return t instanceof h ? t : new h(t, t)
    }
    getTilePos(t) {
        if (!this._level) throw new a;
        return (t instanceof h ? t : new h(t.x, t.y)).scaleBy(this._physicalTileSize).subtract(this._level.origin)
    }
    _createGridTile(t, e) {
        if (!this._level) throw new a;
        const i = document.createElement("div");
        this._createTileContents(i, t, e);
        const s = new h(t.x, t.y).scaleBy(this._physicalTileSize).subtract(this._level.origin);
        return this._level && this._level.element.appendChild(i), i.style.transform = `translate3d(${s.x}px, ${s.y}px, 0px)`, i.style.position = "absolute", i.classList.add("leaflet-tile"), i.classList.add("leaflet-tile-loaded"), i.classList.add("grid-layer-tile"), this.showBorders && this._renderDebugTileBorder(i, t), this._onTileLoaded(t, i), {
            element: i,
            coordinates: t
        }
    }
    _update(t = 0) {
        var e;
        if (!this.leafletMap) throw new a;
        const i = this.leafletMap.getZoom(),
            s = Math.log2(pa / this.getTileSize().x),
            n = Math.round(i + s),
            r = this.leafletMap.getTileBounds(n),
            o = null !== (e = this.options.keepBuffer) && void 0 !== e ? e : 0,
            h = new Ri({
                x: r.min.x - o,
                y: Math.max(r.min.y - o, 0)
            }, {
                x: r.max.x + o,
                y: Math.min(r.max.y + o, (1 << n) - 1)
            });
        this._tileCache.update(h, n, t);
        const l = this._tileCache.getOrderedTilePyramid(r, n, 999, 0),
            c = [],
            u = new Set;
        for (const t of l) {
            const e = ra(t);
            if (u.add(e), !this._gridTiles.has(e)) {
                const i = na(t),
                    s = this._tileCache.getData(i);
                s && this._gridTiles.set(e, this._createGridTile(t, s))
            }
        }
        for (const t of this._gridTiles.keys()) u.has(t) || c.push(t);
        for (const t of c) {
            const e = this._gridTiles.get(t);
            this._gridTiles.delete(t), null == e || e.element.remove()
        }
    }
    _removeAllTiles() {
        this._tileCache.dispose();
        for (const t of this._gridTiles.values()) t.element.remove();
        this._gridTiles.clear()
    }
    _init(t) {
        const e = t.maplibreMap;
        e.on("zoomstart", this._onZoomStart), e.on("zoomend", this._onZoomEnd), e.on("zoom", this._onZoom), e.on("move", this._onMapMove), this._update(1)
    }
    _destroy() {
        var t;
        if (!(null === (t = this.map) || void 0 === t ? void 0 : t.maplibreMap)) throw new a;
        const e = this.map.maplibreMap;
        this._level && (this._level.element.remove(), this._level = void 0), e.off("zoomstart", this._onZoomStart), e.off("zoomend", this._onZoomEnd), e.off("zoom", this._onZoom), e.off("move", this._onMapMove)
    }
    _hideShowLayer(t = 1) {
        var e, i;
        const s = null !== (i = null === (e = this._level) || void 0 === e ? void 0 : e.element) && void 0 !== i ? i : this._container;
        s && (s.style.visibility = t ? "hidden" : "visible")
    }
    _initContainer() {
        this._container || (this._container = to("div", "leaflet-layer leaflet-grid-layer " + (this.options.className || "")), this.getPane(this.options.pane).appendChild(this._container))
    }
    _updateLevels() {
        if (!this.leafletMap) throw new a;
        if (!this._level) {
            const t = to("div", "leaflet-tile-container leaflet-zoom-animated", this._container);
            this._level = {
                element: t,
                origin: l([0, 0]),
                zoom: 0,
                transform: {
                    translate: l([0, 0]),
                    scale: 1
                }
            }
        }
        const t = this.leafletMap,
            e = t.getZoom(),
            i = Math.log2(pa / this.getTileSize().x),
            s = Math.log2(pa / this._physicalTileSize.x),
            n = e + (Math.round(e + i) - Math.round(e + s));
        this._level.origin = t.project(t.unproject(t.getPixelOrigin()), n).round(), this._level.zoom = n;
        const r = t.getZoomScale(e, Math.round(n));
        this._contentScale = r;
        const o = t.getCenter(),
            h = this._level.origin.multiplyBy(r).subtract(t._getNewPixelOrigin(o, e)).round();
        this._level.transform = {
            translate: h,
            scale: r
        }, mi(this._level.element, h, r)
    }
    _renderDebugTileBorder(t, e) {
        const i = document.createElement("div");
        i.innerHTML = `${e.z}/${e.x}/${e.y}`, i.classList.add("debug-tile-coords"), t.appendChild(i), t.classList.add("debug-tile")
    }
}

function ma(t) {
    return new _a(t)
}

function fa(t) {
    let e = 0,
        i = 0,
        s = 0;
    for (let n = 0; n < t.length; n++) {
        const r = De(t[n]);
        e += r.lat, i += r.lng, s++
    }
    return De([e / s, i / s])
}

function ga(t) {
    return ya(t) ? t : ga(t[0])
}

function ya(t) {
    return !Array.isArray(t[0]) || "object" != typeof t[0][0] && void 0 !== t[0][0]
}

function va(t) {
    return 0 === t.length || ya(t[0])
}

function ba(t) {
    return new ke(t[1], t[0], t[2])
}

function xa(t, e) {
    const i = [],
        s = function(t) {
            return "number" == typeof t[0][0]
        }(t);
    for (let n, r = 0, o = t.length; r < o; r++) n = s ? (e || ba)(t[r]) : xa(t[r], e), i.push(n);
    return i
}

function wa(t, i) {
    return void 0 !== (t = De(t)).alt ? [e(t.lng, i), e(t.lat, i), e(t.alt, i)] : [e(t.lng, i), e(t.lat, i)]
}

function Ta(t, e, i) {
    if (ya(t)) {
        const s = [];
        for (let e = 0; e < t.length; e++) s.push(wa(t[e], i));
        return e && s.length > 0 && s.push(s[0].slice()), s
    } {
        const s = [];
        for (let n = 0; n < t.length; n++) s.push(Ta(t[n], e, i));
        return s
    }
}

function Ma(t, e) {
    return t.feature ? (Ti({}, t.feature, {
        geometry: e
    }), t.feature) : {
        type: "Feature",
        properties: {},
        geometry: e
    }
}

function Pa(t) {
    return "Feature" === t.type || "FeatureCollection" === t.type ? t : {
        type: "Feature",
        properties: {},
        geometry: t
    }
}

function Ea(t, e) {
    return Ma(t, {
        type: "Point",
        coordinates: wa(t.getLatLng(), e)
    })
}
var La;
ua = _a, _a.defaultOptions = Object.assign(Object.assign({}, Reflect.get(da, "defaultOptions", ua)), {
    tileSize: pa,
    minZoom: 0,
    maxZoom: 18,
    pane: "tilePane",
    className: "",
    keepBuffer: 2
});
class Ca {
    constructor(t) {
        this.options = t
    }
    _setIconStyles(t, e, i, s) {
        "number" == typeof i && (i = [i, i]);
        const n = l(i),
            r = l(s || n.divideBy(2));
        t.className = `leaflet-marker-${e} ${this.options.className || ""}`, r && (t.style.marginLeft = -r.x + "px", t.style.marginTop = -r.y + "px"), n && (t.style.width = n.x + "px", t.style.height = n.y + "px")
    }
}
class Sa extends Ca {
    constructor(t) {
        super(Object.assign(Object.assign({}, La.defaultOptions), t))
    }
    createIcon(t) {
        return this._createIcon("icon", t)
    }
    createShadow(t) {
        return this._createIcon("shadow", t)
    }
    _createIcon(t, e) {
        const i = this._getIconUrl(t);
        if (!i) {
            if ("icon" === t) throw Error("iconUrl not set in Icon options (see the docs).");
            return null
        }
        if ("shadow" === t && null == this.options.shadowSize) throw Error("If icon's shadow image is specified, its shadow size must also be specified.");
        const s = this._createImg(i, e && "IMG" === e.tagName ? e : void 0);
        return this._setIconStyles(s, t, "icon" === t ? this.options.iconSize : this.options.shadowSize, "icon" === t ? this.options.iconAnchor : this.options.shadowAnchor || this.options.iconAnchor), (this.options.crossOrigin || "" === this.options.crossOrigin) && (s.crossOrigin = 1 == this.options.crossOrigin ? "" : this.options.crossOrigin), s
    }
    _createImg(t, e) {
        return (e = e || document.createElement("img")).src = t, e
    }
    _getIconUrl(t) {
        return this._getIconUrlInternal(t)
    }
    _getIconUrlInternal(t) {
        return "icon" === t ? (He.retina ? this.options.iconRetinaUrl : this.options.iconUrl) || this.options.iconUrl : (He.retina ? this.options.shadowRetinaUrl : this.options.shadowUrl) || this.options.shadowUrl
    }
    _getDefaultIconUrl(t) {
        const e = La.Default;
        return "string" != typeof e.imagePath && (e.imagePath = this._detectIconPath()), (this.options.imagePath || e.imagePath) + this._getIconUrlInternal(t)
    }
    _stripUrl(t) {
        const e = function(t, e, i) {
                const s = e.exec(t);
                return s && s[i]
            },
            i = e(t, /^url\((['"])?(.+)\1\)$/, 2);
        return i && e(i, /^(.*)marker-icon\.png$/, 1)
    }
    _detectIconPath() {
        const t = to("div", "leaflet-default-icon-path", document.body),
            e = this._stripUrl(getComputedStyle(t).backgroundImage);
        if (document.body.removeChild(t), e) return e;
        const i = document.querySelector('link[href$="leaflet.css"]');
        return i ? i.href.substring(0, i.href.length - 11 - 1) : ""
    }
    static getIconDefaultDefaultOptions() {
        return {
            iconUrl: "marker-icon.png",
            iconRetinaUrl: "marker-icon-2x.png",
            shadowUrl: "marker-shadow.png",
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            tooltipAnchor: [16, -28],
            shadowSize: [41, 41]
        }
    }
}
La = Sa, Sa.defaultOptions = {
    popupAnchor: [0, 0],
    tooltipAnchor: [0, 0],
    crossOrigin: 0,
    className: "",
    iconRetinaUrl: null,
    iconAnchor: null,
    iconUrl: "marker-icon.png",
    shadowUrl: null,
    iconSize: [12, 12],
    shadowSize: null,
    shadowAnchor: null,
    shadowRetinaUrl: null,
    imagePath: null
}, Sa.Default = class extends La {
    constructor() {
        super(La.getIconDefaultDefaultOptions())
    }
    _getIconUrl(t) {
        return super._getDefaultIconUrl(t)
    }
};
const Ra = {
    iconSize: [12, 12],
    html: 0,
    bgPos: null,
    className: "leaflet-div-icon",
    popupAnchor: [0, 0],
    tooltipAnchor: [0, 0],
    iconAnchor: null
};
class Ia extends Ca {
    constructor(t) {
        super(Object.assign(Object.assign({}, Ra), t))
    }
    createIcon(t) {
        const e = t && "DIV" === t.tagName ? t : document.createElement("div"),
            i = this.options;
        if (i.html instanceof Element ? (e.replaceChildren(), e.appendChild(i.html)) : e.innerHTML = 0 != i.html ? i.html : "", i.bgPos) {
            const t = l(i.bgPos);
            e.style.backgroundPosition = `${-t.x}px ${-t.y}px`
        }
        return this._setIconStyles(e, "icon", this.options.iconSize, this.options.iconAnchor), e
    }
    createShadow(t) {
        return null
    }
}

function Aa(t) {
    return new Sa(t)
}

function za(t) {
    return new Ia(t)
}
class Oa {
    constructor(t) {
        this._enabled = 0, this._map = t
    }
    enable() {
        return this._enabled || (this._enabled = 1, this.addHooks()), this
    }
    disable() {
        return this._enabled ? (this._enabled = 0, this.removeHooks(), this) : this
    }
    enabled() {
        return this._enabled
    }
}
const ka = He.touch ? "touchstart mousedown" : "mousedown";
class Da extends Ci {
    constructor(t, e, i, s) {
        super(), this._enabled = 0, this._moved = 0, this._moving = 0, this._lastTarget = null, this.options = Object.assign(Object.assign({}, Da.defaultOptions), s), this._element = t, this._dragStartTarget = e || t, this._preventOutline = !!i
    }
    enable() {
        return this._enabled || (di.on(this._dragStartTarget, ka, this._onDown, this), this._enabled = 1), this
    }
    disable() {
        return this._enabled ? (Da._dragging === this && this.finishDrag(1), di.off(this._dragStartTarget, ka, this._onDown, this), this._enabled = 0, this._moved = 0, this) : this
    }
    _onDown(t) {
        if (!this._enabled) return;
        if (this._moved = 0, this._element.classList.contains("leaflet-zoom-anim")) return;
        if (this.isTouchEvent(t) && t.touches && 1 !== t.touches.length) return void(Da._dragging === this && this.finishDrag());
        if (Da._dragging || t.shiftKey || t instanceof MouseEvent && 0 !== t.button) return;
        const e = function(t) {
            do {
                if (!(t = t.parentNode)) return null
            } while (!(t.offsetWidth && t.offsetHeight || t === document.body));
            return t
        }(this._element);
        if (!e) return;
        if (Da._dragging = this, this._preventOutline && po(this._element), di.on(window, "dragstart", di.preventDefault), function() {
                const t = ao[ho];
                "none" !== t && (lo = t, ao[ho] = "none")
            }(), t.stopPropagation(), this._moving) return;
        this.fire("down");
        const i = this.isTouchEvent(t) ? t.touches[0] : t;
        this._startPoint = new h(i.clientX, i.clientY), this._startPos = oo(this._element), this._parentScale = function(t) {
            const e = t.getBoundingClientRect();
            return {
                x: e.width / t.offsetWidth || 1,
                y: e.height / t.offsetHeight || 1,
                boundingClientRect: e
            }
        }(e);
        const s = "mousedown" === t.type;
        di.on(document, s ? "mousemove" : "touchmove", this._onMove, this), di.on(document, s ? "mouseup" : "touchend touchcancel", this._onUp, this)
    }
    _onMove(t) {
        var e;
        if (!this._enabled) return;
        if (this.isTouchEvent(t) && t.touches.length > 1) return void(this._moved = 1);
        const i = this.isTouchEvent(t) ? t.touches[0] : t,
            s = new h(i.clientX, i.clientY)._subtract(this._startPoint);
        if ((s.x || s.y) && !(Math.abs(s.x) + Math.abs(s.y) < this.options.clickTolerance)) {
            if (s.x /= this._parentScale.x, s.y /= this._parentScale.y, di.preventDefault(t), !this._moved) {
                this.fire("dragstart"), this._moved = 1, document.body.classList.add("leaflet-dragging"), this._lastTarget = t.target || t.srcElement;
                const i = window.SVGElementInstance;
                i && this._lastTarget instanceof i && (this._lastTarget = this._lastTarget.correspondingUseElement), null === (e = this._lastTarget) || void 0 === e || e.classList.add("leaflet-drag-target")
            }
            this._newPos = this._startPos.add(s), this._moving = 1, this._lastEvent = t, this._updatePosition()
        }
    }
    _updatePosition() {
        const t = {
            originalEvent: this._lastEvent
        };
        this.fire("predrag", t), ro(this._element, this._newPos), this.fire("drag", t)
    }
    _onUp() {
        this._enabled && this.finishDrag()
    }
    isTouchEvent(t) {
        return He.touchNative && t instanceof TouchEvent
    }
    finishDrag(t) {
        document.body.classList.remove("leaflet-dragging"), this._lastTarget && (this._lastTarget.classList.remove("leaflet-drag-target"), this._lastTarget = null), di.off(document, "mousemove touchmove", this._onMove, this), di.off(document, "mouseup touchend touchcancel", this._onUp, this), di.off(window, "dragstart", di.preventDefault), void 0 !== lo && (ao[ho] = lo, lo = void 0);
        const e = this._moved && this._moving;
        this._moving = 0, Da._dragging = 0, e && this.fire("dragend", {
            noInertia: t,
            distance: this._newPos.distanceTo(this._startPos)
        })
    }
}
Da.defaultOptions = {
    clickTolerance: 3
}, Da._dragging = 0;
class Ba extends Oa {
    constructor(t) {
        if (!t.leafletMap) throw new a;
        super(t.leafletMap), this._marker = t
    }
    addHooks() {
        const t = this._marker._icon;
        return t ? (this._draggable || (this._draggable = new Da(t, t, 1)), this._draggable.on({
            dragstart: this._onDragStart,
            predrag: this._onPreDrag,
            drag: this._onDrag,
            dragend: this._onDragEnd
        }, this).enable(), t.classList.add("leaflet-marker-draggable"), this) : this
    }
    removeHooks() {
        return this._draggable.off({
            dragstart: this._onDragStart,
            predrag: this._onPreDrag,
            drag: this._onDrag,
            dragend: this._onDragEnd
        }, this).disable(), this._marker._icon && this._marker._icon.classList.remove("leaflet-marker-draggable"), this
    }
    moved() {
        return this._draggable && this._draggable._moved
    }
    _adjustPan(t) {
        if (!this._marker.leafletMap) throw new a;
        if (!this._marker._icon) return;
        const e = this._marker.leafletMap,
            i = this._marker.options.autoPanSpeed,
            s = this._marker.options.autoPanPadding,
            n = oo(this._marker._icon),
            r = e.getPixelBounds(),
            o = e.getPixelOrigin(),
            h = Ii(r.min._subtract(o).add(s), r.max._subtract(o).subtract(s));
        if (!h.contains(n)) {
            const s = l((Math.max(h.max.x, n.x) - h.max.x) / (r.max.x - h.max.x) - (Math.min(h.min.x, n.x) - h.min.x) / (r.min.x - h.min.x), (Math.max(h.max.y, n.y) - h.max.y) / (r.max.y - h.max.y) - (Math.min(h.min.y, n.y) - h.min.y) / (r.min.y - h.min.y)).multiplyBy(i);
            e.panBy(s, {
                animate: 0
            }), this._draggable._newPos._add(s), this._draggable._startPos._add(s), ro(this._marker._icon, this._draggable._newPos), this._onDrag(t), this._panRequest = xi(this._adjustPan.bind(this, t))
        }
    }
    _onDragStart() {
        this._oldLatLng = this._marker.getLatLng(), this._marker.closePopup(), this._marker.fire("movestart").fire("dragstart")
    }
    _onPreDrag(t) {
        this._marker.options.autoPan && (wi(this._panRequest), this._panRequest = xi(this._adjustPan.bind(this, t)))
    }
    _onDrag(t) {
        if (!this._marker || !this._marker.leafletMap) throw new a;
        if (!this._marker._icon) return;
        const e = this._marker._shadow,
            i = oo(this._marker._icon),
            s = this._marker.leafletMap.layerPointToLatLng(i);
        e && ro(e, i), this._marker._latlng = s, t.latlng = s, t.oldLatLng = this._oldLatLng, this._marker.fire("move", t).fire("drag", t)
    }
    _onDragEnd(t) {
        wi(this._panRequest), delete this._oldLatLng, this._marker.fire("moveend").fire("dragend", t)
    }
}
var Fa, Za;
class Na extends(Za = Si) {
    constructor(t, e) {
        super(Object.assign(Object.assign({}, Fa.defaultOptions), e)), this._icon = null, this._shadow = null, this._latlng = De(t)
    }
    onAdd(t) {
        return this._initIcon(), this._update(), this
    }
    onRemove(t) {
        return this._icon && this._removeIcon(), this._removeShadow(), this
    }
    getEvents() {
        return {
            zoom: this._update,
            viewreset: this._update,
            zoomend: this._update
        }
    }
    getLatLng() {
        return this._latlng
    }
    setLatLng(t) {
        const e = this._latlng;
        return this._latlng = De(t), this._update(), this.fire("move", {
            oldLatLng: e,
            latlng: this._latlng
        })
    }
    setZIndexOffset(t) {
        return this.options.zIndexOffset = t, this._update()
    }
    getIcon() {
        return this.options.icon
    }
    setIcon(t) {
        return this.options.icon = t, this.map && (this._initIcon(), this._update()), this._popup && this.bindPopup(this._popup, this._popup.options), this
    }
    setOpacity(t) {
        return this.options.opacity = t, this.map && this._updateOpacity(), this
    }
    getElement() {
        return this._icon
    }
    _update() {
        if (this._icon && this.leafletMap) {
            const t = this.leafletMap.latLngToLayerPoint(this._latlng).round();
            this._setPos(t)
        }
        return this
    }
    _addTooltipFocusListeners(t) {
        const e = this.getElement();
        e && Pi(e, this, t)
    }
    _setAriaDescribedByTooltipLayer(t) {
        const e = this.getElement();
        e && Ei(e, t)
    }
    _initIcon() {
        if (!this.map) throw new a;
        const t = this.options,
            e = t.icon.createIcon(this._icon);
        let i = 0;
        e !== this._icon && (this._icon && this._removeIcon(), i = 1, t.title && (e.title = t.title), "IMG" === e.tagName && (e.alt = t.alt || "")), t.keyboard && (e.tabIndex = 0, e.setAttribute("role", "button")), this._icon = e, t.riseOnHover && this.on({
            mouseover: this._bringToFront,
            mouseout: this._resetZIndex
        }), this.options.autoPanOnFocus && di.on(e, "focus", this._panOnFocus, this);
        const s = t.icon.createShadow(this._shadow);
        let n = 0;
        return s !== this._shadow && (this._removeShadow(), n = 1), s && s instanceof HTMLImageElement && (s.alt = ""), this._shadow = s, t.opacity < 1 && this._updateOpacity(), i && this.getPane().appendChild(this._icon), this._initInteraction(), s && n && this.getPane(t.shadowPane).appendChild(s), Po(this._icon, this), i
    }
    _removeIcon() {
        this.options.riseOnHover && this.off({
            mouseover: this._bringToFront,
            mouseout: this._resetZIndex
        }), this._icon && (this.options.autoPanOnFocus && di.off(this._icon, "focus", this._panOnFocus, this), Eo(this._icon), this._icon.remove(), this.removeInteractiveTarget(this._icon), this._icon = null)
    }
    _removeShadow() {
        this._shadow && this._shadow.remove(), this._shadow = null
    }
    _setPos(t) {
        this._icon && ro(this._icon, t), this._shadow && ro(this._shadow, t), this._zIndex = t.y + this.options.zIndexOffset, this._resetZIndex()
    }
    _updateZIndex(t) {
        this._icon && (this._icon.style.zIndex = "" + (this._zIndex + t))
    }
    _initInteraction() {
        if (!this.options.interactive) return;
        this._icon && (this._icon.classList.add("leaflet-interactive"), this.addInteractiveTarget(this._icon));
        let t = this.options.draggable;
        this.dragging && (t = this.dragging.enabled(), this.dragging.disable()), this.dragging = new Ba(this), t && this.dragging.enable()
    }
    _updateOpacity() {
        this._icon && (this._icon.style.opacity = "" + this.options.opacity)
    }
    _bringToFront() {
        this._updateZIndex(this.options.riseOffset)
    }
    _resetZIndex() {
        this._updateZIndex(0)
    }
    _panOnFocus() {
        var t;
        if (!(null === (t = this.map) || void 0 === t ? void 0 : t.maplibreMap)) throw new a;
        this.map.maplibreMap.panTo(this._latlng)
    }
    _getPopupAnchor() {
        return this.options.icon.options.popupAnchor
    }
    _getTooltipAnchor() {
        return this.options.icon.options.tooltipAnchor
    }
    toGeoJSON(t) {
        return Ea(this, t)
    }
}

function ja(t, e) {
    return new Na(t, e)
}
Fa = Na, Na.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Za, "defaultOptions", Fa)), {
    icon: new Sa.Default,
    interactive: 1,
    keyboard: 1,
    title: "",
    alt: "Marker",
    zIndexOffset: 0,
    opacity: 1,
    riseOnHover: 0,
    riseOffset: 250,
    pane: "markerPane",
    shadowPane: "shadowPane",
    bubblingMouseEvents: 0,
    autoPanOnFocus: 0,
    draggable: 0,
    autoPan: 0,
    autoPanPadding: [50, 50],
    autoPanSpeed: 10
});
class Ua extends Si {
    get maplibreMap() {
        var t;
        return null === (t = this.leafletMap) || void 0 === t ? void 0 : t.maplibreMap
    }
    constructor(t, e) {
        if (super(e), this._layers = {}, t)
            for (let e = 0, i = t.length; e < i; e++) this.addLayer(t[e])
    }
    addLayer(t) {
        const e = this.getLayerId(t);
        return this._layers[e] = t, this.map && this.map.addLayer(t), this
    }
    removeLayer(t) {
        const e = "number" == typeof t ? t : this.getLayerId(t);
        return this.map && this._layers[e] && this.map.removeLayer(this._layers[e]), delete this._layers[e], this
    }
    hasLayer(t) {
        return ("number" == typeof t ? t : this.getLayerId(t)) in this._layers
    }
    clearLayers() {
        return this.eachLayer(this.removeLayer, this)
    }
    invoke(t, ...e) {
        let i, s;
        for (i in this._layers) Object.prototype.hasOwnProperty.call(this._layers, i) && (s = this._layers[i], s[t] && s[t].apply(s, e));
        return this
    }
    eachLayer(t, e) {
        for (const i in this._layers) Object.prototype.hasOwnProperty.call(this._layers, i) && t.call(e, this._layers[i]);
        return this
    }
    getLayer(t) {
        return this._layers[t]
    }
    getLayers() {
        const t = [];
        return this.eachLayer(t.push, t), t
    }
    setZIndex(t) {
        return this.invoke("setZIndex", t)
    }
    getLayerId(t) {
        return r(t)
    }
    onAdd(t) {
        return this.eachLayer(t.addLayer, t)
    }
    onRemove(t) {
        return this.eachLayer(t.removeLayer, t)
    }
    _toMultiPoint(t) {
        const e = [];
        return this.eachLayer(i => {
            const s = i.toGeoJSON(t);
            "FeatureCollection" !== s.type && "GeometryCollection" !== s.geometry.type && e.push(s.geometry.coordinates)
        }), Ma(this, {
            type: "MultiPoint",
            coordinates: e
        })
    }
    toGeoJSON(t) {
        const e = this.feature && this.feature.geometry && this.feature.geometry.type;
        if ("MultiPoint" === e) return this._toMultiPoint(t);
        if ("GeometryCollection" === e) {
            const e = [];
            return this.eachLayer(i => {
                i.toGeoJSON && $a(i.toGeoJSON(t), e)
            }), Ma(this, {
                geometries: e,
                type: "GeometryCollection"
            })
        } {
            const e = [];
            return this.eachLayer(i => {
                i.toGeoJSON && qa(Pa(i.toGeoJSON(t)), e)
            }), {
                type: "FeatureCollection",
                features: e
            }
        }
    }
    _addTooltipFocusListeners(t) {
        this.eachLayer(e => {
            e._addTooltipFocusListeners(t)
        })
    }
    _setAriaDescribedByTooltipLayer(t) {
        this.eachLayer(e => {
            e._setAriaDescribedByTooltipLayer(t)
        })
    }
}
const Ga = function(t, e) {
    return new Ua(t, e)
};

function qa(t, e) {
    if ("Feature" === t.type) e.push(t);
    else
        for (const i of t.features) qa(i, e)
}

function $a(t, e) {
    if ("Feature" === t.type) e.push(t.geometry);
    else
        for (const i of t.features) $a(i, e)
}
class Wa extends Ua {
    addLayer(t) {
        return this.hasLayer(t) ? this : (t.addEventParent(this), super.addLayer(t), this.fire("layeradd", {
            layer: t
        }))
    }
    removeLayer(t) {
        if (!this.hasLayer(t)) return this;
        const e = this.getLayerId(t);
        return e in this._layers && (t = this._layers[e]), t.removeEventParent(this), super.removeLayer(t), this.fire("layerremove", {
            layer: t
        })
    }
    setStyle(t) {
        return this.invoke("setStyle", t)
    }
    bringToFront() {
        return this.invoke("bringToFront")
    }
    bringToBack() {
        return this.invoke("bringToBack")
    }
    getBounds() {
        const t = new Be(void 0, void 0);
        for (const e in this._layers)
            if (Object.prototype.hasOwnProperty.call(this._layers, e)) {
                const i = this._layers[e];
                i.getBounds ? t.extend(i.getBounds()) : i.getLatLng && t.extend(i.getLatLng())
            } return t
    }
    openPopup(t) {
        return this._popup && this._popup._prepareOpen(t || this._latlng) && this._popup.openOn(this.leafletMap), this
    }
}

function Ha(t, e) {
    return new Wa(t, e)
}
var Va, Xa, Ka, Ya, Ja, Qa;
class th extends(Xa = Si) {
    get containerId() {
        var t;
        return null === (t = this._container) || void 0 === t ? void 0 : t.id
    }
    constructor(t, e) {
        t && (t instanceof ke || Array.isArray(t)) ? (super(Object.assign(Object.assign({}, Va.defaultOptions), e)), this._latlng = De(t)) : (super(Object.assign(Object.assign({}, Va.defaultOptions), t)), this._source = e), this.options.content && (this._content = this.options.content)
    }
    openOn(t) {
        if (!(t = null != t ? t : this._source.leafletMap)) throw new a;
        return t.hasLayer(this) || t.addLayer(this), this
    }
    close() {
        return this.map && this.map.removeLayer(this), this
    }
    toggle(t) {
        return this.map ? this.close() : (t ? this._source = t : t = this._source, this._prepareOpen(), this.openOn(t.leafletMap)), this
    }
    onAdd(t) {
        return this._container || this._initLayout(), t.fadeAnimated && (this._container.style.opacity = "0"), clearTimeout(this._removeTimeout), this.getPane().appendChild(this._container), this._update(), t.fadeAnimated && (this._container.style.opacity = "1"), this.bringToFront(), this.options.interactive && (this._container.classList.add("leaflet-interactive"), this.addInteractiveTarget(this._container)), this
    }
    onRemove(t) {
        return t.fadeAnimated ? (this._container.style.opacity = "0", this._removeTimeout = setTimeout(() => this._container.remove(), 200)) : this._container.remove(), this.options.interactive && (this._container.classList.remove("leaflet-interactive"), this.removeInteractiveTarget(this._container)), this
    }
    getLatLng() {
        return this._latlng
    }
    setLatLng(t) {
        return this._latlng = De(t), this.map && (this._updatePosition(), this._adjustPan()), this
    }
    getContent() {
        return this._content
    }
    setContent(t) {
        return this._content = t, this._update(), this
    }
    getElement() {
        return this._container
    }
    _addTooltipFocusListeners(t) {
        const e = this.getElement();
        e && Pi(e, this, t)
    }
    _setAriaDescribedByTooltipLayer(t) {
        const e = this.getElement();
        e && Ei(e, t)
    }
    getEvents() {
        return {
            zoom: this._updatePosition,
            viewreset: this._updatePosition,
            zoomend: this._updatePosition
        }
    }
    isOpen() {
        return !!this.map && this.map.hasLayer(this)
    }
    bringToFront() {
        return this.map && eo(this._container), this
    }
    bringToBack() {
        return this.map && io(this._container), this
    }
    _prepareOpen(t) {
        let e = this._source;
        if (!e.leafletMap) return 0;
        if (e instanceof Wa) {
            const t = e._layers;
            let i = null;
            for (const e in t)
                if (t[e].leafletMap) {
                    i = t[e];
                    break
                } if (!i) return 0;
            e = i, this._source = i
        }
        if (!t)
            if (e.getCenter) t = e.getCenter();
            else if (e.getLatLng) t = e.getLatLng();
        else {
            if (!e.getBounds) throw Error("Unable to get source layer LatLng.");
            t = e.getBounds().getCenter()
        }
        return this.setLatLng(t), this.map && this._update(), 1
    }
    _update() {
        this.map && (this._container.style.visibility = "hidden", this._updateContent(), this._updateLayout(), this._updatePosition(), this._container.style.visibility = "", this._adjustPan())
    }
    _updateContent() {
        if (!this._content) return;
        const t = this._contentNode,
            e = "function" == typeof this._content ? this._content(this._source || this) : this._content;
        if ("string" == typeof e) t.innerHTML = e;
        else {
            for (; t.hasChildNodes();) t.removeChild(t.firstChild);
            t.appendChild(e)
        }
        this.fire("contentupdate")
    }
    _updatePosition() {
        if (!this.leafletMap) return;
        const t = this.leafletMap.latLngToLayerPoint(this._latlng),
            e = this._getAnchor();
        let i = l(this.options.offset);
        i = i.add(t).add(e);
        const s = this._containerBottom = -i.y,
            n = this._containerLeft = -Math.round(this._containerWidth / 2) + i.x;
        this._container.style.bottom = s + "px", this._container.style.left = n + "px"
    }
    _getAnchor() {
        return [0, 0]
    }
}
Va = th, th.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Xa, "defaultOptions", Va)), {
    interactive: 0,
    offset: [0, 0],
    className: "",
    content: ""
});
class eh extends(Ya = Si) {
    constructor(t) {
        super(Object.assign(Object.assign({}, Ka.defaultOptions), t)), this.type = "Path"
    }
    beforeAdd(t) {
        return this._renderer = t.getRenderer(this), this
    }
    onAdd(t) {
        return this._renderer._initPath(this), this._reset(), this._renderer._addPath(this), this
    }
    onRemove(t) {
        return this._renderer._removePath(this), this
    }
    redraw() {
        return this.map && this._renderer._updatePath(this), this
    }
    setStyle(t) {
        return this.options = Object.assign(Object.assign({}, this.options), t), this._renderer && (this._renderer._updateStyle(this), this.options.stroke && t && Object.prototype.hasOwnProperty.call(t, "weight") && this._updateBounds()), this
    }
    bringToFront() {
        return this._renderer && this._renderer._bringToFront(this), this
    }
    bringToBack() {
        return this._renderer && this._renderer._bringToBack(this), this
    }
    _reset() {
        this._project(), this._update()
    }
    _clickTolerance() {
        return (this.options.stroke ? this.options.weight / 2 : 0) + (this._renderer.options.tolerance || 0)
    }
}
Ka = eh, eh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Ya, "defaultOptions", Ka)), {
    stroke: 1,
    color: "#3388ff",
    weight: 3,
    opacity: 1,
    lineCap: "round",
    lineJoin: "round",
    dashArray: null,
    dashOffset: null,
    fill: 0,
    fillColor: null,
    fillOpacity: .2,
    fillRule: "evenodd",
    className: "",
    interactive: 0,
    bubblingMouseEvents: 1,
    renderer: null
});
class ih extends(Qa = th) {
    constructor(t, e) {
        t && (t instanceof ke || Array.isArray(t)) ? super(t, Object.assign(Object.assign({}, Ja.defaultOptions), e)) : super(Object.assign(Object.assign({}, Ja.defaultOptions), t), e), this._autopanning = 0
    }
    openOn(t) {
        if (!(t = t || this._source.leafletMap)) throw new a;
        const e = t._popup;
        return !t.hasLayer(this) && e && e.options.autoClose && t.closePopup(e), t._popup = this, super.openOn(t)
    }
    onAdd(t) {
        return super.onAdd(t), t.fire("popupopen", {
            popup: this
        }), this._source && (this._source.fire("popupopen", {
            popup: this
        }, 1), this._source instanceof eh || this._source.on("preclick", di.stopPropagation)), this
    }
    onRemove(t) {
        return super.onRemove(t), t.fire("popupclose", {
            popup: this
        }), this._source && (this._source.fire("popupclose", {
            popup: this
        }, 1), this._source instanceof eh || this._source.off("preclick", di.stopPropagation)), this
    }
    getEvents() {
        if (!this.leafletMap) throw new a;
        const t = super.getEvents();
        return (void 0 !== this.options.closeOnClick ? this.options.closeOnClick : this.leafletMap.options.closePopupOnClick) && (t.preclick = this.close), this.options.keepInView && (t.moveend = this._adjustPan), t
    }
    _initLayout() {
        const t = "leaflet-popup",
            e = this._container = to("div", `${t} ${this.options.className || ""}`),
            i = this._wrapper = to("div", t + "-content-wrapper", e);
        if (this._contentNode = to("div", t + "-content", i), di.disableClickPropagation(e), di.disableScrollPropagation(this._contentNode), di.on(e, "contextmenu", di.stopPropagation), this._tipContainer = to("div", t + "-tip-container", e), this._tip = to("div", t + "-tip", this._tipContainer), this.options.closeButton) {
            const i = this._closeButton = to("a", t + "-close-button", e);
            i.setAttribute("role", "button"), i.setAttribute("aria-label", this.options.closeButtonLabel), i.href = "#close", i.innerHTML = '<span aria-hidden="true">&#215;</span>', di.on(i, "click", function(t) {
                di.preventDefault(t), this.close()
            }, this)
        }
    }
    _updateLayout() {
        const t = this._contentNode,
            e = t.style;
        e.width = "", e.whiteSpace = "nowrap";
        let i = t.offsetWidth;
        i = Math.min(i, this.options.maxWidth), i = Math.max(i, this.options.minWidth), e.width = i + 1 + "px", e.whiteSpace = "", e.height = "";
        const s = this.options.maxHeight,
            n = "leaflet-popup-scrolled";
        s && t.offsetHeight > s ? (e.height = s + "px", t.classList.add(n)) : t.classList.remove(n), this._containerWidth = this._container.offsetWidth
    }
    _adjustPan() {
        if (!this.leafletMap) throw new a;
        if (!this.options.autoPan) return;
        if (this._autopanning) return void(this._autopanning = 0);
        const t = this.leafletMap,
            e = parseInt(getComputedStyle(this._container).marginBottom, 10) || 0,
            i = this._container.offsetHeight + e,
            s = this._containerWidth,
            n = new h(this._containerLeft, -i - this._containerBottom).add(oo(this._container)),
            r = t.layerPointToContainerPoint(n),
            o = l(this.options.autoPanPadding),
            c = l(this.options.autoPanPaddingTopLeft || o),
            u = l(this.options.autoPanPaddingBottomRight || o),
            d = t.getSize();
        let p = 0,
            _ = 0;
        r.x + s + u.x > d.x && (p = r.x + s - d.x + u.x), r.x - p - c.x < 0 && (p = r.x - c.x), r.y + i + u.y > d.y && (_ = r.y + i - d.y + u.y), r.y - _ - c.y < 0 && (_ = r.y - c.y), (p || _) && (this.options.keepInView && (this._autopanning = 1), t.fire("autopanstart").panBy([p, _]))
    }
    _getAnchor() {
        return this._source && this._source instanceof Na ? l(this._source._getPopupAnchor()) : new h(0, 0)
    }
    toGeoJSON(t) {
        return Ea(this, t)
    }
}

function sh(t, e) {
    return new ih(t, e)
}

function nh(t, e) {
    if (!e || !t.length) return t.slice();
    const i = e * e;
    return t = function(t, e) {
        const i = [t[0]];
        let s = 0;
        for (let n = 1; n < t.length; n++) ph(t[n], t[s]) > e && (i.push(t[n]), s = n);
        return s < t.length - 1 && i.push(t[t.length - 1]), i
    }(t, i), t = function(t, e) {
        const i = t.length,
            s = new("undefined" != typeof Uint8Array ? Uint8Array : Array)(i);
        s[0] = s[i - 1] = 1, hh(t, s, e, 0, i - 1);
        const n = [];
        for (let e = 0; e < i; e++) s[e] && n.push(t[e]);
        return n
    }(t, i), t
}

function rh(t, e, i) {
    return Math.sqrt(oh(t, e, i))
}

function oh(t, e, i) {
    const s = ah(t, e, i),
        n = t.x - s.x,
        r = t.y - s.y;
    return n * n + r * r
}

function ah(t, e, i) {
    let s = e.x,
        n = e.y;
    const r = i.x - s,
        o = i.y - n,
        a = r * r + o * o;
    if (a > 0) {
        const e = ((t.x - s) * r + (t.y - n) * o) / a;
        e > 1 ? (s = i.x, n = i.y) : e > 0 && (s += r * e, n += o * e)
    }
    return new h(s, n)
}

function hh(t, e, i, s, n) {
    let r, o = 0,
        a = n - 1;
    for (let e = s + 1; e <= n - 1; e++) r = _h(t[e], t[s], t[n]), r > o && (a = e, o = r);
    o > i && (e[a] = 1, hh(t, e, i, s, a), hh(t, e, i, a, n))
}
let lh;

function ch(t, e, i, s, n) {
    let r, o, a, h = s ? lh : dh(t, i),
        l = dh(e, i);
    for (lh = l;;) {
        if (!(h | l)) return [t, e];
        if (h & l) return 0;
        r = h || l, o = uh(t, e, r, i, n), a = dh(o, i), r === h ? (t = o, h = a) : (e = o, l = a)
    }
}

function uh(t, e, i, s, n) {
    const r = e.x - t.x,
        o = e.y - t.y,
        a = s.min,
        l = s.max;
    let c, u;
    return 8 & i ? (c = t.x + r * (l.y - t.y) / o, u = l.y) : 4 & i ? (c = t.x + r * (a.y - t.y) / o, u = a.y) : 2 & i ? (c = l.x, u = t.y + o * (l.x - t.x) / r) : 1 & i && (c = a.x, u = t.y + o * (a.x - t.x) / r), new h(c, u, n)
}

function dh(t, e) {
    let i = 0;
    return t.x < e.min.x ? i |= 1 : t.x > e.max.x && (i |= 2), t.y < e.min.y ? i |= 4 : t.y > e.max.y && (i |= 8), i
}

function ph(t, e) {
    const i = e.x - t.x,
        s = e.y - t.y;
    return i * i + s * s
}

function _h(t, e, i, s) {
    let n, r = e.x,
        o = e.y,
        a = i.x - r,
        h = i.y - o;
    const l = a * a + h * h;
    return l > 0 && (n = ((t.x - r) * a + (t.y - o) * h) / l, n > 1 ? (r = i.x, o = i.y) : n > 0 && (r += a * n, o += h * n)), a = t.x - r, h = t.y - o, a * a + h * h
}

function mh(t, e) {
    if (!t || 0 === t.length) throw Error("latlngs not passed");
    let i;
    ya(t) ? i = t : (console.warn("latlngs are not flat! Only the first ring will be used"), i = ga(t));
    let s = De([0, 0]);
    const n = Fe(i);
    n.getNorthWest().distanceTo(n.getSouthWest()) * n.getNorthEast().distanceTo(n.getNorthWest()) < 1700 && (s = fa(i));
    const r = i.length,
        o = [];
    for (let t = 0; t < r; t++) {
        const n = De(i[t]);
        o.push(e.project(De([n.lat - s.lat, n.lng - s.lng])))
    }
    let a, h = 0;
    for (let t = 0; t < r - 1; t++) h += o[t].distanceTo(o[t + 1]) / 2;
    if (0 === h) a = o[0];
    else {
        let t = 0;
        a = o[o.length - 1];
        for (let e = 0; e < r - 1; e++) {
            const i = o[e],
                s = o[e + 1],
                n = i.distanceTo(s);
            if (t += n, t > h) {
                const e = (t - h) / n;
                a = [s.x - e * (s.x - i.x), s.y - e * (s.y - i.y)];
                break
            }
        }
    }
    const c = e.unproject(l(a));
    return De([c.lat + s.lat, c.lng + s.lng])
}
Ja = ih, ih.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Qa, "defaultOptions", Ja)), {
    pane: "popupPane",
    offset: [0, 7],
    maxWidth: 300,
    minWidth: 50,
    maxHeight: null,
    autoPan: 1,
    autoPanPaddingTopLeft: null,
    autoPanPaddingBottomRight: null,
    autoPanPadding: [5, 5],
    keepInView: 0,
    closeButton: 1,
    closeButtonLabel: "Close popup",
    autoClose: 1,
    closeOnEscapeKey: 1,
    closeOnClick: 0
}), Si.Popup = ih, Vo.Popup = ih;
const fh = {
    simplify: nh,
    pointToSegmentDistance: rh,
    squaredDistanceOfClosestPointOnSegment: oh,
    closestPointOnSegment: ah,
    clipSegment: ch,
    polylineCenter: mh
};
var gh, yh, vh, bh, xh, wh, Th, Mh, Ph, Eh, Lh, Ch, Sh, Rh, Ih, Ah, zh, Oh;
class kh extends(yh = eh) {
    constructor(t, e) {
        super(Object.assign(Object.assign({}, gh.defaultOptions), e)), this._setLatLngs(t)
    }
    getLatLngs() {
        return this._latlngs
    }
    setLatLngs(t) {
        return this._setLatLngs(t), this.redraw()
    }
    isEmpty() {
        return !this._latlngs.length
    }
    closestLayerPoint(t) {
        let e, i = 1 / 0;
        for (let s = 0, n = this._parts.length; s < n; s++) {
            const n = this._parts[s];
            for (let s = 1, r = n.length; s < r; s++) {
                const r = n[s - 1],
                    o = n[s],
                    a = oh(t, r, o);
                a < i && (i = a, e = ah(t, r, o))
            }
        }
        if (e) {
            const t = e;
            return t.distance = Math.sqrt(i), t
        }
    }
    getCenter() {
        if (!this.map) throw new a;
        return mh(this._defaultShape(), Uo)
    }
    getBounds() {
        return this._bounds
    }
    addLatLng(t, e) {
        e = e || this._defaultShape();
        const i = De(t);
        return e.push(i), this._bounds.extend(t), this.redraw()
    }
    _setLatLngs(t) {
        this._bounds = new Be(void 0, void 0), this._latlngs = this._convertLatLngs(t)
    }
    _defaultShape() {
        return ya(this._latlngs) ? this._latlngs : ya(this._latlngs[0]) ? this._latlngs[0] : this._latlngs[0][0]
    }
    _convertLatLngs(t) {
        if (ya(t)) {
            const e = [];
            for (let i = 0, s = t.length; i < s; i++) e[i] = De(t[i]), this._bounds.extend(e[i]);
            return e
        } {
            const e = [];
            for (let i = 0, s = t.length; i < s; i++) e[i] = this._convertLatLngs(t[i]);
            return e
        }
    }
    _project() {
        const t = new Ri;
        this._rings = [], this._projectLatlngs(this._latlngs, this._rings, t), this._bounds.isValid() && t.isValid() && (this._rawPxBounds = t, this._updateBounds())
    }
    _updateBounds() {
        const t = this._clickTolerance(),
            e = new h(t, t);
        this._rawPxBounds && (this._pxBounds = new Ri([this._rawPxBounds.min.subtract(e), this._rawPxBounds.max.add(e)]))
    }
    _projectLatlngs(t, e, i) {
        if (!this.leafletMap) throw new a;
        const s = t.length;
        if (ya(t)) {
            const n = [];
            for (let e = 0; e < s; e++) n[e] = this.leafletMap.latLngToLayerPoint(t[e]), i.extend(n[e]);
            e.push(n)
        } else
            for (let n = 0; n < s; n++) this._projectLatlngs(t[n], e, i)
    }
    _clipPoints() {
        const t = this._renderer._bounds;
        if (this._parts = [], !this._pxBounds || !t || !this._pxBounds.intersects(t)) return;
        if (this.options.noClip) return void(this._parts = this._rings);
        const e = this._parts;
        let i, s, n, r, o, a, h;
        for (i = 0, n = 0, r = this._rings.length; i < r; i++)
            for (h = this._rings[i], s = 0, o = h.length; s < o - 1; s++) a = ch(h[s], h[s + 1], t, s, 1), a && (e[n] = e[n] || [], e[n].push(a[0]), a[1] === h[s + 1] && s !== o - 2 || (e[n].push(a[1]), n++))
    }
    _simplifyPoints() {
        const t = this._parts,
            e = this.options.smoothFactor;
        for (let i = 0, s = t.length; i < s; i++) t[i] = nh(t[i], e)
    }
    _update() {
        this.map && (this._clipPoints(), this._simplifyPoints(), this._updatePath())
    }
    _updatePath() {
        this._renderer._updatePoly(this)
    }
    _containsPoint(t, e) {
        let i, s, n, r, o, a;
        const h = this._clickTolerance();
        if (!this._pxBounds || !this._pxBounds.contains(t)) return 0;
        for (i = 0, r = this._parts.length; i < r; i++)
            for (a = this._parts[i], s = 0, o = a.length, n = o - 1; s < o; n = s++)
                if ((e || 0 !== s) && rh(t, a[n], a[s]) <= h) return 1;
        return 0
    }
    toGeoJSON(t) {
        const e = this._latlngs;
        return ya(e) ? Ma(this, {
            type: "LineString",
            coordinates: Ta(e, 0, t)
        }) : Ma(this, {
            type: "MultiLineString",
            coordinates: Ta(e, 0, t)
        })
    }
}

function Dh(t, e) {
    return new kh(t, e)
}

function Bh(t, e, i) {
    const s = [1, 4, 2, 8];
    let n = [];
    for (let i = 0, s = t.length; i < s; i++) {
        const s = t[i];
        s._code = dh(t[i], e), n.push(s)
    }
    for (let t = 0; t < 4; t++) {
        const r = s[t],
            o = [];
        let a;
        for (let t = 0, s = n.length, h = s - 1; t < s; h = t++) {
            const s = n[t],
                l = n[h];
            s._code & r ? l._code & r || (a = uh(l, s, r, e, i), a._code = dh(a, e), o.push(a)) : (l._code & r && (a = uh(l, s, r, e, i), a._code = dh(a, e), o.push(a)), o.push(s))
        }
        n = o
    }
    return n
}
gh = kh, kh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(yh, "defaultOptions", gh)), {
    smoothFactor: 1,
    noClip: 0
});
class Fh extends(bh = kh) {
    constructor(t, e) {
        super(t, Object.assign(Object.assign({}, vh.defaultOptions), e))
    }
    isEmpty() {
        return ya(this._latlngs) ? !this._latlngs.length : ya(this._latlngs[0]) ? !this._latlngs[0].length : !this._latlngs[0][0].length
    }
    getCenter() {
        if (!this.map) throw new a;
        return function(t, e) {
            let i, s, n, r, o, a, h, c, u, d;
            if (!t || 0 === t.length) throw Error("latlngs not passed");
            ya(t) ? d = t : (console.warn("latlngs are not flat! Only the first ring will be used"), d = ga(t));
            let p = De([0, 0]);
            const _ = Fe(d);
            _.getNorthWest().distanceTo(_.getSouthWest()) * _.getNorthEast().distanceTo(_.getNorthWest()) < 1700 && (p = fa(d));
            const m = d.length,
                f = [];
            for (i = 0; i < m; i++) {
                const t = De(d[i]);
                f.push(e.project(De([t.lat - p.lat, t.lng - p.lng])))
            }
            for (a = h = c = 0, i = 0, s = m - 1; i < m; s = i++) n = f[i], r = f[s], o = n.y * r.x - r.y * n.x, h += (n.x + r.x) * o, c += (n.y + r.y) * o, a += 3 * o;
            u = 0 === a ? f[0] : [h / a, c / a];
            const g = e.unproject(l(u));
            return De([g.lat + p.lat, g.lng + p.lng])
        }(this._defaultShape(), Uo)
    }
    _convertLatLngs(t) {
        const e = super._convertLatLngs(t),
            i = e.length;
        return ya(e) && i >= 2 && e[0].equals(e[i - 1]) && e.pop(), e
    }
    _setLatLngs(t) {
        this._bounds = new Be(void 0, void 0);
        const e = this._convertLatLngs(t);
        this._latlngs = ya(e) ? [e] : e
    }
    _defaultShape() {
        return ya(this._latlngs[0]) ? this._latlngs[0] : this._latlngs[0][0]
    }
    _clipPoints() {
        let t = this._renderer._bounds;
        if (!t) throw new a;
        const e = this.options.weight,
            i = new h(e, e);
        if (t = new Ri(t.min.subtract(i), t.max.add(i)), this._parts = [], this._pxBounds && this._pxBounds.intersects(t))
            if (this.options.noClip) this._parts = this._rings;
            else
                for (let e, i = 0, s = this._rings.length; i < s; i++) e = Bh(this._rings[i], t, 1), e.length && this._parts.push(e)
    }
    _updatePath() {
        this._renderer._updatePoly(this, 1)
    }
    _containsPoint(t) {
        if (!this._pxBounds || !this._pxBounds.contains(t)) return 0;
        let e = 0;
        for (let i = 0; i < this._parts.length; i++) {
            const s = this._parts[i];
            for (let i = 0, n = s.length - 1; i < s.length; n = i++) {
                const r = s[i],
                    o = s[n];
                r.y > t.y != o.y > t.y && t.x < (o.x - r.x) * (t.y - r.y) / (o.y - r.y) + r.x && (e = !e)
            }
        }
        return e || super._containsPoint(t, 1)
    }
    toGeoJSON(t) {
        const e = this._latlngs;
        return ya(e) ? Ma(this, {
            type: "Polygon",
            coordinates: [Ta(e, 1, t)]
        }) : va(e) ? Ma(this, {
            type: "Polygon",
            coordinates: Ta(e, 1, t)
        }) : Ma(this, {
            type: "MultiPolygon",
            coordinates: Ta(e, 1, t)
        })
    }
}

function Zh(t, e) {
    return new Fh(t, e)
}
vh = Fh, Fh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(bh, "defaultOptions", vh)), {
    fill: 1
});
class Nh extends Wa {
    constructor(t, e) {
        super([], e), t && this.addData(t)
    }
    addData(t) {
        if (Array.isArray(t) || "FeatureCollection" === t.type) {
            const e = Array.isArray(t) ? t : t.features;
            for (let t = 0, i = e.length; t < i; t++) this.addData(e[t]);
            return this
        }
        return this._addFeatureOrGeometry(t)
    }
    resetStyle(t) {
        return void 0 === t ? this.eachLayer(this.resetStyle, this) : (t.options = Object.assign({}, t.defaultOptions), this._setLayerStyle(t, this.options.style), this)
    }
    setStyle(t) {
        return this.eachLayer(function(e) {
            this._setLayerStyle(e, t)
        }, this)
    }
    _setLayerStyle(t, e) {
        if (t.setStyle)
            if ("function" == typeof e) {
                const i = e(t.feature);
                t.setStyle(i)
            } else t.setStyle(e);
        return this
    }
    _addFeatureOrGeometry(t) {
        const e = this.options;
        if (e.filter && !e.filter(t)) return this;
        const i = Uh(t, e);
        return i ? (i.feature = Pa(t), i.defaultOptions = i.options, this.resetStyle(i), e.onEachFeature && e.onEachFeature(t, i), this.addLayer(i)) : this
    }
}

function jh(t) {
    return t
}

function Uh(t, e) {
    const i = "Feature" === t.type ? t.geometry : t;
    if (!i) return null;
    const s = e && e.pointToLayer,
        n = e && e.coordsToLatLng || ba;
    let r, o, a, h;
    switch (i.type) {
        case "Point":
            return r = n(i.coordinates), qh(s, t, r, e);
        case "MultiPoint": {
            const o = [];
            for (a = 0, h = i.coordinates.length; a < h; a++) r = n(jh(i.coordinates[a])), o.push(qh(s, t, r, e));
            return new Wa(o)
        }
        case "LineString":
        case "MultiLineString":
            return o = xa(i.coordinates, n), new kh(o, e);
        case "Polygon":
        case "MultiPolygon":
            return o = xa(i.coordinates, n), new Fh(o, e);
        case "GeometryCollection": {
            const t = [];
            for (let s = 0, n = i.geometries.length; s < n; s++) {
                const n = Uh({
                    geometry: i.geometries[s],
                    type: "Feature",
                    properties: {}
                }, e);
                n && t.push(n)
            }
            return new Wa(t)
        }
        case "FeatureCollection": {
            const t = [];
            for (let s = 0, n = i.features.length; s < n; s++) {
                const n = Uh(i.features[s], e);
                n && t.push(n)
            }
            return new Wa(t)
        }
        default:
            throw Error("Invalid GeoJSON object.")
    }
}

function Gh(t, e) {
    return new Nh(t, e)
}

function qh(t, e, i, s) {
    return t ? t(e, i) : new Na(i, (null == s ? void 0 : s.markersInheritOptions) ? s : void 0)
}
class $h extends(wh = eh) {
    get _radiusPixels() {
        return this._radius
    }
    constructor(t, e) {
        super(Object.assign(Object.assign({}, xh.defaultOptions), e)), this._latlng = De(t), this._radius = this.options.radius
    }
    setLatLng(t) {
        const e = this._latlng;
        return this._latlng = De(t), this.redraw(), this.fire("move", {
            oldLatLng: e,
            latlng: this._latlng
        })
    }
    getLatLng() {
        return this._latlng
    }
    setRadius(t) {
        return this.options.radius = this._radius = t, this.redraw()
    }
    getRadius() {
        return this._radius
    }
    setStyle(t) {
        const e = t.radius || this._radius;
        return super.setStyle(t), this.setRadius(e), this
    }
    _project() {
        if (!this.leafletMap) throw new a;
        this._point = this.leafletMap.latLngToLayerPoint(this._latlng), this._updateBounds()
    }
    _updateBounds() {
        const t = this._radius,
            e = this._radiusPixels,
            i = this._clickTolerance(),
            s = new h(t + i, e + i);
        this._pxBounds = new Ri(this._point.subtract(s), this._point.add(s))
    }
    _update() {
        this.map && this._updatePath()
    }
    _updatePath() {
        this._renderer._updateCircle(this)
    }
    _empty() {
        return !(!this._radius || this._renderer._bounds && this._renderer._bounds.intersects(this._pxBounds))
    }
    _containsPoint(t) {
        return t.distanceTo(this._point) <= this._radius + this._clickTolerance()
    }
    toGeoJSON(t) {
        return Ea(this, t)
    }
}

function Wh(t, e) {
    return new $h(t, e)
}
xh = $h, $h.defaultOptions = Object.assign(Object.assign({}, Reflect.get(wh, "defaultOptions", xh)), {
    fill: 1,
    radius: 10
});
class Hh extends $h {
    get _radiusPixels() {
        return this._radiusY
    }
    constructor(t, e, i) {
        let s;
        if ("number" == typeof e ? (s = null != i ? i : {}, s.radius = e) : s = null != e ? e : {}, super(t, s), isNaN(this.options.radius)) throw Error("Circle radius cannot be NaN");
        this._mRadius = this.options.radius
    }
    setRadius(t) {
        return this._mRadius = t, this.redraw()
    }
    getRadius() {
        return this._mRadius
    }
    getBounds() {
        if (!this.leafletMap) throw new a;
        const t = new h(this._radius, this._radiusPixels);
        return new Be(this.leafletMap.layerPointToLatLng(this._point.subtract(t)), this.leafletMap.layerPointToLatLng(this._point.add(t)))
    }
    _project() {
        if (!this.leafletMap) throw new a;
        const t = this._latlng.lng,
            e = this._latlng.lat,
            i = this.leafletMap,
            s = Uo;
        if (s instanceof ko) {
            const s = Math.PI / 180,
                n = this._mRadius / Oe / s,
                r = i.project([e + n, t]),
                o = i.project([e - n, t]),
                a = r.add(o).divideBy(2),
                h = i.unproject(a).lat;
            let l = Math.acos((Math.cos(n * s) - Math.sin(e * s) * Math.sin(h * s)) / (Math.cos(e * s) * Math.cos(h * s))) / s;
            (isNaN(l) || 0 === l) && (l = n / Math.cos(Math.PI / 180 * e)), this._point = a.subtract(i.getPixelOrigin()), this._radius = isNaN(l) ? 0 : a.x - i.project([h, t - l]).x, this._radiusY = a.y - r.y
        } else {
            const t = s.unproject(s.project(this._latlng).subtract([this._mRadius, 0]));
            this._point = i.latLngToLayerPoint(this._latlng), this._radius = this._point.x - i.latLngToLayerPoint(t).x
        }
        this._updateBounds()
    }
}

function Vh(t, e, i) {
    return new Hh(t, e, i)
}
class Xh extends(Mh = th) {
    constructor(t, e) {
        t && (t instanceof ke || Array.isArray(t)) ? super(t, Object.assign(Object.assign({}, Th.defaultOptions), e)) : super(Object.assign(Object.assign({}, Th.defaultOptions), t), e)
    }
    onAdd(t) {
        return super.onAdd(t), this.setOpacity(this.options.opacity), t.fire("tooltipopen", {
            tooltip: this
        }), this._source && (this.addEventParent(this._source), this._source.fire("tooltipopen", {
            tooltip: this
        }, 1)), this
    }
    onRemove(t) {
        return super.onRemove(t), t.fire("tooltipclose", {
            tooltip: this
        }), this._source && (this.removeEventParent(this._source), this._source.fire("tooltipclose", {
            tooltip: this
        }, 1)), this
    }
    getEvents() {
        const t = super.getEvents();
        return this.options.permanent || (t.preclick = this.close), t
    }
    _initLayout() {
        this._contentNode = this._container = to("div", "leaflet-tooltip " + (this.options.className || "")), this._container.setAttribute("role", "tooltip"), this._container.setAttribute("id", "leaflet-tooltip-" + r(this))
    }
    _updateLayout() {
        this._containerWidth = this._container.offsetWidth
    }
    _adjustPan() {}
    _setPosition(t) {
        if (!this.leafletMap) throw new a;
        let e, i, s = this.options.direction;
        const n = this.leafletMap,
            r = this._container,
            o = n.latLngToContainerPoint(n.getCenter()),
            h = n.layerPointToContainerPoint(t),
            c = r.offsetWidth,
            u = r.offsetHeight,
            d = l(this.options.offset),
            p = this._getAnchor();
        "top" === s ? (e = c / 2, i = u) : "bottom" === s ? (e = c / 2, i = 0) : "center" === s ? (e = c / 2, i = u / 2) : "right" === s ? (e = 0, i = u / 2) : "left" === s ? (e = c, i = u / 2) : h.x < o.x ? (s = "right", e = 0, i = u / 2) : (s = "left", e = c + 2 * (d.x + p.x), i = u / 2), t = t.subtract(l(e, i, 1)).add(d).add(p), r.classList.remove("leaflet-tooltip-right", "leaflet-tooltip-left", "leaflet-tooltip-top", "leaflet-tooltip-bottom"), r.classList.add("leaflet-tooltip-" + s), ro(r, t)
    }
    _updatePosition() {
        if (!this.leafletMap) throw new a;
        const t = this.leafletMap.latLngToLayerPoint(this._latlng);
        this._setPosition(t)
    }
    setOpacity(t) {
        return this.options.opacity = t, this._container && (this._container.style.opacity = null == t ? void 0 : "" + t), this
    }
    _getAnchor() {
        return !this.options.sticky && (t = this._source) && "_getTooltipAnchor" in t ? l(this._source._getTooltipAnchor()) : new h(0, 0);
        var t
    }
}

function Kh(t, e) {
    return new Xh(t, e)
}
Th = Xh, Xh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Mh, "defaultOptions", Th)), {
    pane: "tooltipPane",
    offset: [0, 0],
    direction: "auto",
    permanent: 0,
    sticky: 0,
    opacity: .9
}), Si.Tooltip = Xh, Vo.Tooltip = Xh;
class Yh extends(Eh = Si) {
    constructor(t, e, i) {
        super(Object.assign(Object.assign({}, Ph.defaultOptions), i)), this._url = t, this._bounds = Fe(e)
    }
    onAdd(t) {
        return this._image || (this._initImage(this._url), this.options.opacity < 1 && this._updateOpacity()), this.options.interactive && (this._image.classList.add("leaflet-interactive"), this.addInteractiveTarget(this._image)), this.getPane().appendChild(this._image), this._reset(), this
    }
    onRemove(t) {
        return this._image.remove(), this.options.interactive && this.removeInteractiveTarget(this._image), this
    }
    setOpacity(t) {
        return this.options.opacity = t, this._image && this._updateOpacity(), this
    }
    setStyle(t) {
        return t.opacity && this.setOpacity(t.opacity), this
    }
    bringToFront() {
        return this.map && eo(this._image), this
    }
    bringToBack() {
        return this.map && io(this._image), this
    }
    setUrl(t) {
        return this._url = t, this._image && (this._image.src = t), this
    }
    setBounds(t) {
        return this._bounds = Fe(t), this.map && this._reset(), this
    }
    getEvents() {
        return {
            zoom: this._reset,
            zoomend: this._reset,
            viewreset: this._reset
        }
    }
    setZIndex(t) {
        return this.options.zIndex = t, this._updateZIndex(), this
    }
    getBounds() {
        return this._bounds
    }
    getElement() {
        return this._image
    }
    getCenter() {
        return this._bounds.getCenter()
    }
    _initImage(t) {
        const e = "string" == typeof(n = t) ? 0 : "IMG" === n.tagName,
            i = e ? t : to("img");
        var n;
        this._image = i, i.classList.add("leaflet-image-layer"), this.options.className && i.classList.add(...s(this.options.className)), i.onselectstart = o, i.onmousemove = o, i.onload = this.fire.bind(this, "load"), i.onerror = this._overlayOnError.bind(this), (this.options.crossOrigin || "" === this.options.crossOrigin) && (i.crossOrigin = this.options.crossOrigin), i.decoding = this.options.decoding, this.options.zIndex && this._updateZIndex(), e ? this._url = i.src : (i.src = this._url, i.alt = this.options.alt)
    }
    _reset() {
        if (!this.leafletMap) throw new a;
        const t = this._image,
            e = new Ri(this.leafletMap.latLngToLayerPoint(this._bounds.getNorthWest()), this.leafletMap.latLngToLayerPoint(this._bounds.getSouthEast())),
            i = e.getSize();
        ro(t, e.min), t.style.width = i.x + "px", t.style.height = i.y + "px"
    }
    _updateOpacity() {
        this._image.style.opacity = "" + this.options.opacity
    }
    _updateZIndex() {
        this._image && null != this.options.zIndex && (this._image.style.zIndex = "" + this.options.zIndex)
    }
    _overlayOnError() {
        this.fire("error");
        const t = this.options.errorOverlayUrl;
        t && this._url !== t && (this._url = t, this._image.src = t)
    }
}

function Jh(t, e, i) {
    return new Yh(t, e, i)
}
Ph = Yh, Yh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Eh, "defaultOptions", Ph)), {
    opacity: 1,
    alt: "",
    interactive: 0,
    crossOrigin: 0,
    errorOverlayUrl: "",
    zIndex: 1,
    className: "",
    decoding: "auto"
});
class Qh extends(Ch = Yh) {
    constructor(t, e, i) {
        super(t, e, Object.assign(Object.assign({}, Lh.defaultOptions), i))
    }
    _reset() {
        super._reset(), this._rotate()
    }
    _rotate() {
        this._image.style.transform += ` rotate(${this.options.angle}deg)`
    }
}
Lh = Qh, Qh.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Ch, "defaultOptions", Lh)), {
    angle: 0,
    opacity: 1,
    alt: "",
    interactive: 0,
    crossOrigin: 0,
    errorOverlayUrl: "",
    zIndex: 1,
    className: "",
    decoding: "auto",
    attribution: null,
    pane: null
});
class tl extends Wa {
    static set defaultImagePath(t) {
        el.defaultOptions.imagePath = t, il.defaultOptions.icon = new el.Default
    }
    constructor(t, e) {
        super(void 0, e), this._kml = t, this._layers = {}, t && this._addKML(t)
    }
    _addKML(t) {
        const e = this._parseKML(t);
        if (e && e.length) {
            for (let t = 0; t < e.length; t++) this.fire("addlayer", {
                layer: e[t]
            }), this.addLayer(e[t]);
            this.latLngs = this._getLatLngs(t), this.fire("loaded")
        }
    }
    _parseKML(t) {
        const e = this._parseStyles(t);
        this._parseStyleMap(t, e);
        const i = [];
        let s = t.getElementsByTagName("Folder");
        for (let t = 0; t < s.length; t++) {
            if (!this._checkFolder(s[t])) continue;
            const n = this._parseFolder(s[t], e);
            n && i.push(n)
        }
        s = t.getElementsByTagName("Placemark");
        for (let n = 0; n < s.length; n++) {
            if (!this._checkFolder(s[n])) continue;
            const r = this._parsePlacemark(s[n], t, e);
            r && i.push(r)
        }
        s = t.getElementsByTagName("GroundOverlay");
        for (let t = 0; t < s.length; t++) {
            const e = this._parseGroundOverlay(s[t]);
            e && i.push(e)
        }
        return i
    }
    _checkFolder(t, e) {
        let i = t.parentNode;
        for (; i && (!("tagName" in i) || "Folder" !== i.tagName);) i = i.parentNode;
        return !i || i === e
    }
    _parseStyles(t) {
        const e = {},
            i = t.getElementsByTagName("Style");
        for (let t = 0, s = i.length; t < s; t++) {
            const s = this._parseStyle(i[t]);
            s && (e["#" + s.id] = s)
        }
        return e
    }
    _parseStyle(t) {
        let e = {};
        const i = {
                color: 1,
                width: 1,
                Icon: 1,
                href: 1,
                hotSpot: 1
            },
            s = t.getElementsByTagName("LineStyle");
        s && s[0] && (e = sl(s[0], i));
        let n = {};
        const r = t.getElementsByTagName("PolyStyle");
        r && r[0] && (n = sl(r[0], i)), n.color && (e.fillColor = n.color), n.opacity && (e.fillOpacity = n.opacity);
        let o = {};
        const a = t.getElementsByTagName("IconStyle");
        a && a[0] && (o = sl(a[0], i)), o.href && (e.icon = new el({
            iconUrl: o.href,
            shadowUrl: null,
            anchorRef: {
                x: o.x,
                y: o.y
            },
            anchorType: {
                x: o.xunits,
                y: o.yunits
            }
        }));
        const h = t.getAttribute("id");
        return h && e && (e.id = h), e
    }
    _parseStyleMap(t, e) {
        const i = t.getElementsByTagName("StyleMap");
        for (let t = 0; t < i.length; t++) {
            const s = i[t];
            let n = "",
                r = "";
            const o = s.getElementsByTagName("key");
            o && o[0] && (n = o[0].textContent);
            const a = s.getElementsByTagName("styleUrl");
            a && a[0] && (r = a[0].textContent), "normal" === n && (e["#" + s.getAttribute("id")] = e[r])
        }
    }
    _parseFolder(t, e) {
        const i = [],
            s = t.getElementsByTagName("Folder");
        for (let n = 0; n < s.length; n++) {
            if (!this._checkFolder(s[n], t)) continue;
            const r = this._parseFolder(s[n], e);
            r && i.push(r)
        }
        const n = t.getElementsByTagName("Placemark");
        for (let s = 0; s < n.length; s++) {
            if (!this._checkFolder(n[s], t)) continue;
            const r = this._parsePlacemark(n[s], t, e);
            r && i.push(r)
        }
        const r = t.getElementsByTagName("GroundOverlay");
        for (let e = 0; e < r.length; e++) {
            if (!this._checkFolder(r[e], t)) continue;
            const s = this._parseGroundOverlay(r[e]);
            s && i.push(s)
        }
        if (i.length) return 1 === i.length ? i[0] : new Wa(i)
    }
    _parsePlacemark(t, e, i, s) {
        const n = s || {},
            r = t.getElementsByTagName("styleUrl");
        for (let t = 0; t < r.length; t++) {
            const e = r[t].childNodes[0].nodeValue;
            if (!e) continue;
            const s = i[e];
            for (const t in s) n[t] = s[t]
        }
        if (t.getElementsByTagName("Style")[0]) {
            const e = this._parseStyle(t);
            if (e)
                for (const t in e) n[t] = e[t]
        }
        const o = ["MultiGeometry", "MultiTrack", "gx:MultiTrack"];
        for (const s in o) {
            const r = t.getElementsByTagName(o[s]);
            for (let t = 0; t < r.length; t++) return this._parsePlacemark(r[t], e, i, n)
        }
        const a = [],
            h = {
                LineString: this._parseLineString,
                Polygon: this._parsePolygon,
                Point: this._parsePoint,
                Track: this._parseTrack,
                "gx:Track": this._parseTrack
            },
            l = ["LineString", "Polygon", "Point", "Track", "gx:Track"];
        for (const i of l) {
            const s = t.getElementsByTagName(i),
                r = h[i];
            for (let t = 0; t < s.length; t++) {
                const i = r.call(this, s[t], e, n);
                i && a.push(i)
            }
        }
        if (!a.length) return;
        let c;
        c = 1 === a.length ? a[0] : new Wa(a);
        let u = null;
        const d = t.getElementsByTagName("name");
        d.length && d[0].childNodes.length && (u = d[0].childNodes[0].nodeValue);
        let p = "";
        const _ = t.getElementsByTagName("description");
        for (let t = 0; t < _.length; t++)
            for (let e = 0; e < _[t].childNodes.length; e++) p += _[t].childNodes[e].nodeValue;
        return u && c.on("add", () => {
            c.bindPopup(`<h2>${Li(u)}</h2>${Li(p)}`, {
                className: "kml-popup"
            })
        }), c
    }
    _parseCoords(t) {
        const e = t.getElementsByTagName("coordinates");
        return this._readCoords(e[0])
    }
    _parseLineString(t, e, i) {
        const s = this._parseCoords(t);
        if (s.length) return new kh(s, i)
    }
    _parseTrack(t, e, i) {
        let s = e.getElementsByTagName("gx:coord");
        0 === s.length && (s = e.getElementsByTagName("coord"));
        let n = [];
        for (let t = 0; t < s.length; t++) n = n.concat(this._readGxCoords(s[t]));
        if (n.length) return new kh(n, i)
    }
    _parsePoint(t, e, i) {
        const s = t.getElementsByTagName("coordinates");
        if (!s.length) return;
        const n = s[0].childNodes[0].nodeValue.split(",");
        return new il(new ke(+n[1], +n[0]), i)
    }
    _parsePolygon(t, e, i) {
        let s;
        const n = [],
            r = t.getElementsByTagName("outerBoundaryIs");
        for (let t = 0; t < r.length; t++) s = this._parseCoords(r[t]), s && n.push(s);
        const o = [],
            a = t.getElementsByTagName("innerBoundaryIs");
        for (let t = 0; t < a.length; t++) s = this._parseCoords(a[t]), s && o.push(s);
        if (n.length) return i.fillColor && (i.fill = 1), new Fh(1 === n.length ? n.concat(o) : n, i)
    }
    _getLatLngs(t) {
        const e = t.getElementsByTagName("coordinates");
        let i = [];
        for (let t = 0; t < e.length; t++) i = i.concat(this._readCoords(e[t]));
        return i
    }
    _readCoords(t) {
        let e = "";
        for (let i = 0; i < t.childNodes.length; i++) e += t.childNodes[i].nodeValue;
        const i = [],
            s = e.split(/[\s\n]+/);
        for (let t = 0; t < s.length; t++) {
            const e = s[t].split(",");
            e.length < 2 || i.push(new ke(+e[1], +e[0]))
        }
        return i
    }
    _readGxCoords(t) {
        const e = t.firstChild.nodeValue.split(" ");
        return [new ke(+e[1], +e[0])]
    }
    _parseGroundOverlay(t) {
        const e = t.getElementsByTagName("LatLonBox")[0],
            i = e.getElementsByTagName("south")[0].childNodes[0].nodeValue,
            s = e.getElementsByTagName("west")[0].childNodes[0].nodeValue,
            n = e.getElementsByTagName("north")[0].childNodes[0].nodeValue,
            r = e.getElementsByTagName("east")[0].childNodes[0].nodeValue;
        if (!(i && s && n && r)) return null;
        const o = new Be([+i, +s], [+n, +r]),
            a = nl(t, {
                Icon: 1,
                href: 1,
                color: 1
            });
        if (void 0 !== e.getElementsByTagName("rotation")[0]) {
            const t = e.getElementsByTagName("rotation")[0].childNodes[0].nodeValue;
            a.rotation = parseFloat(t)
        }
        return a.href ? new Qh(a.href, o, {
            opacity: a.opacity,
            angle: a.rotation
        }) : null
    }
}
class el extends(Rh = Sa) {
    constructor(t) {
        super(Object.assign(Object.assign({}, Sh.defaultOptions), t))
    }
    _setIconStyles(t, e) {
        super._setIconStyles(t, e, this.options.iconSize), t.complete ? this.applyCustomStyles(t) : t.onload = this.applyCustomStyles.bind(this, t)
    }
    applyCustomStyles(t) {
        var e, i, s, n;
        const r = this.options;
        this.options.popupAnchor = [0, -.83 * t.height], t.style.marginLeft = "fraction" === r.anchorType.x ? -(null !== (e = r.anchorRef.x) && void 0 !== e ? e : 0) * t.width + "px" : -(null !== (i = r.anchorRef.x) && void 0 !== i ? i : 0) + "px", t.style.marginTop = "fraction" === r.anchorType.y ? -(1 - (null !== (s = r.anchorRef.y) && void 0 !== s ? s : 0)) * t.height + 1 + "px" : (null !== (n = r.anchorRef.y) && void 0 !== n ? n : 0) - t.height + 1 + "px"
    }
}
Sh = el, el.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Rh, "defaultOptions", Sh)), {
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    anchorRef: {},
    anchorType: {}
}), el.Default = class extends Sh {
    constructor() {
        super(Sa.getIconDefaultDefaultOptions())
    }
    _getIconUrl(t) {
        return super._getDefaultIconUrl(t)
    }
};
class il extends Na {
    constructor(t, e) {
        super(t, Object.assign({
            icon: new el.Default
        }, e))
    }
}

function sl(t, e) {
    const i = {};
    for (let s = 0; s < t.childNodes.length; s++) {
        const n = t.childNodes[s],
            r = n.tagName;
        if (e[r])
            if ("hotSpot" === r)
                for (let t = 0; t < n.attributes.length; t++) i[n.attributes[t].name] = n.attributes[t].nodeValue;
            else if (n.childNodes.length > 0) {
            const t = n.childNodes[0].nodeValue;
            if ("color" === r) i.opacity = parseInt(t.substring(0, 2), 16) / 255, i.color = `#${t.substring(6, 8)}${t.substring(4, 6)}${t.substring(2, 4)}`;
            else if ("width" === r) i.weight = +t;
            else if ("Icon" === r) {
                const t = sl(n, e);
                t.href && (i.href = t.href)
            } else "href" === r && (i.href = t)
        }
    }
    return i
}

function nl(t, e) {
    const i = {};
    let s = {};
    for (let n = 0; n < t.childNodes.length; n++) {
        const r = t.childNodes[n],
            o = r.tagName;
        if (!e[o]) continue;
        const a = r.childNodes[0].nodeValue;
        "Icon" === o ? (s = nl(r, e), s.href && (i.href = s.href)) : "href" === o ? i.href = a : "color" === o && (i.opacity = parseInt(a.substring(0, 2), 16) / 255, i.color = `#${a.substring(6, 8)}${a.substring(4, 6)}${a.substring(2, 4)}`)
    }
    return i
}

function rl(t, e) {
    return new tl(t, e)
}
class ol extends(Ah = Wa) {
    constructor(t, e) {
        super(void 0, Object.assign(Object.assign({}, Ih.defaultOptions), e)), "string" == typeof t ? t && this.addGPX(t, e) : this._gpx = t
    }
    addGPX(t, e, i) {
        if ("string" == typeof t) {
            const s = this,
                n = (t, e) => {
                    s._gpx = t, s.addGPX(t, e)
                };
            this.loadXML(t, n, e, i)
        } else {
            const i = this.parseGPX(t, e);
            if (!i) return this;
            this.addLayer(i), this.fire("loaded")
        }
        return this
    }
    parse() {
        return this._gpx && this.addGPX(this._gpx), this
    }
    _humanReadableLength(t) {
        return t < 2e3 ? t.toFixed(0) + " m" : (t / 1e3).toFixed(1) + " km"
    }
    loadXML(t, e, i, s) {
        return void 0 === i && (i = this.options), void 0 === s && (s = i.async), fetch(t).then(t => t.text()).then(t => (new window.DOMParser).parseFromString(t, "text/xml")).then(t => e(t, i)).catch(), this
    }
    _polylineLen(t) {
        return ll(t._latlngs)
    }
    parseGPX(t, e) {
        e = null != e ? e : {};
        const i = [];
        let s = 0;
        const n = [
            ["rte", "rtept"],
            ["trkseg", "trkpt"]
        ];
        for (let r = 0; r < n.length; r++) {
            const o = t.getElementsByTagName(n[r][0]);
            for (let t = 0; t < o.length; t++) {
                const a = this._parseTrkSeg(o[t], e, n[r][1]);
                for (let e = 0; e < a.length; e++) this._parseName(o[t], a[e]) && (s = 1), i.push(a[e])
            }
        }
        const r = t.getElementsByTagName("wpt");
        if (0 != e.display_wpt)
            for (let t = 0; t < r.length; t++) {
                const n = this._parseWpt(r[t], e);
                n && (this._parseName(r[t], n) && (s = 1), i.push(n))
            }
        if (!i.length) return null;
        let o = i[0];
        return i.length > 1 && (o = new Wa(i)), s || this._parseName(t, o), o
    }
    _parseName(t, e) {
        let i = "",
            s = "",
            n = 0,
            r = t.getElementsByTagName("name"),
            o = null,
            a = null;
        r.length && (a = r[0].childNodes[0].nodeValue), r = t.getElementsByTagName("desc");
        for (let t = 0; t < r.length; t++)
            for (let e = 0; e < r[t].childNodes.length; e++) s += r[t].childNodes[e].nodeValue;
        return r = t.getElementsByTagName("link"), r.length && (o = r[0].getAttribute("href")), e instanceof eh && (n = this._polylineLen(e)), a && (i += `<h2>${Li(a)}</h2>${Li(s)}`), n && (i += `<p>${this._humanReadableLength(n)}</p>`), o && (i += `<p><a target="_blank" href="${Li(o)}">[...]</a></p>`), e && void 0 === e._popup && e.bindPopup(i), i
    }
    _parseTrkSeg(t, e, i) {
        const s = t.getElementsByTagName(i);
        if (!s.length) return [];
        const n = [];
        for (let t = 0; t < s.length; t++) {
            const e = new ke(parseFloat(s[t].getAttribute("lat")), parseFloat(s[t].getAttribute("lon")));
            e.meta = {};
            for (const i in s[t].childNodes) {
                const n = s[t].childNodes[i];
                n.tagName && (e.meta[n.tagName] = n.textContent)
            }
            n.push(e)
        }
        const r = [new kh(n, e)];
        return this.fire("addline", {
            line: r
        }), r
    }
    _parseWpt(t, e) {
        const i = new Na(new ke(parseFloat(t.getAttribute("lat")), parseFloat(t.getAttribute("lon"))), e),
            s = {};
        for (let e = 0; e < t.childNodes.length; e++) {
            const i = t.childNodes[e];
            "#text" !== i.nodeName && (s[i.nodeName] = i.textContent)
        }
        return this.fire("addpoint", {
            point: i,
            attributes: s
        }), i
    }
    speedSplitEnable(t) {
        return Mi(this, t), this.on("addline", this._speedSplit, this)
    }
    speedSplitDisable() {
        return this.off("addline", this._speedSplit, this)
    }
    _speedSplit(t) {
        var e;
        const i = ga(t.line.pop().getLatLngs());
        let s = Math.floor(i.length / (null !== (e = this.options.chunks) && void 0 !== e ? e : 1));
        s < 3 && (s = 3);
        let n = null;
        for (let e = 0; e < i.length; e += s) {
            let r = 0,
                o = null;
            e + s > i.length && (s = i.length - e);
            for (let t = 0; t < s; t++) n && (r += n.distanceTo(i[e + t])), n = i[e + t], o || (o = hl(n.meta.time));
            n = i[e + s - 1], o = (hl(n.meta.time) - o) / 36e5;
            const a = .001 * r / o,
                h = al(a / this.options.maxSpeed),
                l = new kh(i.slice(e, e + s + 1), {
                    color: h,
                    weight: 2,
                    opacity: 1,
                    interactive: 1
                });
            l.bindPopup(`Dist: ${r.toFixed()}m; Speed: ${a.toFixed(2)} km/h`), t.line.push(l)
        }
    }
}

function al(t) {
    function e(t) {
        return function(t) {
            return Math.floor(t).toString(16).toUpperCase().padStart(2, "0")
        }(256 * t)
    }
    return t < 0 ? "#FF0000" : t < 1 / 3 ? `#FF${e(3 * t)}00` : t < 2 / 3 ? `#${e(2 - 3 * t)}FF00` : t < 1 ? "#00FF" + e(3 * t - 2) : "#00FFFF"
}

function hl(t) {
    try {
        return new Date(t).getTime()
    } catch (t) {
        return (new Date).getTime()
    }
}

function ll(t) {
    let e = 0;
    if (ya(t)) {
        let i = null;
        for (let s = 0; s < t.length; s++) s && i && (e += i.distanceTo(t[s])), i = t[s];
        return e
    }
    for (const i of t) e += ll(i);
    return e
}
Ih = ol, ol.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Ah, "defaultOptions", Ih)), {
    maxSpeed: 110,
    chunks: 200
});
class cl extends(Oh = Si) {
    constructor(t) {
        super(Object.assign(Object.assign({}, zh.defaultOptions), t)), this.options.font.split(" ").length < 2 && (this.options.font += " Verdana"), this.options.fontColor || (this.options.fontColor = this.options.color), this.options.zoomInterval && (Array.isArray(this.options.zoomInterval) ? (this.options.latInterval || (this.options.latInterval = this.options.zoomInterval), this.options.lngInterval || (this.options.lngInterval = this.options.zoomInterval)) : (this.options.zoomInterval.latitude && (this.options.latInterval = this.options.zoomInterval.latitude, this.options.zoomInterval.longitude || (this.options.lngInterval = this.options.zoomInterval.latitude)), this.options.zoomInterval.longitude && (this.options.lngInterval = this.options.zoomInterval.longitude, this.options.zoomInterval.latitude || (this.options.latInterval = this.options.zoomInterval.longitude))))
    }
    onAdd(t) {
        this._canvas || this._initCanvas();
        const e = t.getPane("overlayPane");
        if (!e) throw Error("Overlay pane not present, cannot add LatLng graticule.");
        return e.appendChild(this._canvas), t.on("viewreset", this._reset, this), t.on("move", this._reset, this), t.on("moveend", this._reset, this), t.on("zoom", this._reset, this), this._reset(), this
    }
    onRemove(t) {
        return this._canvas.remove(), t.off("viewreset", this._reset, this), t.off("move", this._reset, this), t.off("moveend", this._reset, this), t.off("zoom", this._reset, this), this
    }
    addTo(t) {
        return t.addLayer(this), this
    }
    setOpacity(t) {
        return this.options.opacity = t, this._updateOpacity(), this
    }
    _initCanvas() {
        this._canvas = to("canvas", ""), this._updateOpacity(), di.on(this._canvas, "onselectstart", o), di.on(this._canvas, "onmousemove", o), di.on(this._canvas, "onload", this._onCanvasLoad, this)
    }
    _reset() {
        if (!this.leafletMap) throw new a;
        const t = this._canvas,
            e = this.leafletMap.getSize();
        ro(t, this.leafletMap.containerPointToLayerPoint([0, 0])), t.width = e.x, t.height = e.y, t.style.width = e.x + "px", t.style.height = e.y + "px", this._calcInterval(), this._draw(1)
    }
    _onCanvasLoad() {
        this.fire("load")
    }
    _updateOpacity() {
        this._canvas.style.opacity = "" + this.options.opacity
    }
    _formatLat(t) {
        return this.options.latFormatTickLabel ? this.options.latFormatTickLabel(t) : t < 0 ? `${-1 * t}${this.options.sides[1]}` : t > 0 ? `${t}${this.options.sides[0]}` : "" + t
    }
    _formatLng(t) {
        return this.options.lngFormatTickLabel ? this.options.lngFormatTickLabel(t) : -180 === (t = i(t, [-180, 180], 1)) ? "" + -1 * t : 0 === t || 180 === t ? "" + t : t < 0 ? `${-1 * t}${this.options.sides[3]}` : t > 0 ? `${t}${this.options.sides[2]}` : "" + t
    }
    _calcInterval() {
        if (!this.leafletMap) throw new a;
        const t = Math.floor(this.leafletMap.getZoom());
        if (this._currZoom !== t && (this._currLngInterval = 0, this._currLatInterval = 0, this._currZoom = t), !this._currLngInterval) try {
            for (const e in this.options.lngInterval) {
                const i = this.options.lngInterval[e];
                if (i.start <= t && i.end && i.end >= t) {
                    this._currLngInterval = i.interval;
                    break
                }
            }
        } catch (t) {
            this._currLngInterval = 0
        }
        if (!this._currLatInterval) try {
            for (const e in this.options.latInterval) {
                const i = this.options.latInterval[e];
                if (i.start <= t && i.end && i.end >= t) {
                    this._currLatInterval = i.interval;
                    break
                }
            }
        } catch (t) {
            this._currLatInterval = 0
        }
    }
    _draw(t) {
        var e;
        const i = this._canvas,
            s = this.leafletMap;
        if (!s) return;
        this._currLngInterval && this._currLatInterval || this._calcInterval();
        const n = this._currLatInterval,
            r = this._currLngInterval,
            o = i.getContext("2d");
        if (!o) throw Error("Failed to create 2D canvas context for LatLngGraticule.");
        let a;
        o.clearRect(0, 0, i.width, i.height), o.lineWidth = this.options.weight, o.strokeStyle = this.options.color, o.fillStyle = null !== (e = this.options.fontColor) && void 0 !== e ? e : this.options.color, o.setLineDash(this.options.dashArray), this.options.font && (o.font = this.options.font);
        try {
            a = function(t) {
                t.length > 2 && "p" === t.charAt(t.length - 2) && (t = t.substr(0, t.length - 2));
                try {
                    return parseInt(t, 10)
                } catch (t) {
                    return 0
                }
            }(o.font.trim().split(" ")[0])
        } catch (t) {
            a = 12
        }
        const h = i.width,
            l = i.height,
            c = s.containerPointToLatLng([0, 0]),
            u = s.containerPointToLatLng([h, 0]);
        let d = s.containerPointToLatLng([h, l]).lat,
            p = c.lat,
            _ = c.lng,
            m = u.lng,
            f = (p - d) / (.2 * l);
        if (isNaN(f)) return;
        f < 1 && (f = 1), d = d < -90 ? -90 : d - f | 0, p = p > 90 ? 90 : p + f | 0;
        let g = (m - _) / (.2 * h);
        if (g < 1 && (g = 1), _ > 0 && m < 0 && (m += 360), m = m + g | 0, _ = _ - g | 0, n > 0) {
            for (let e = n; e <= p; e += n) e >= d && this._drawLatLine(e, t, o, a, _, m, h);
            for (let e = 0; e >= d; e -= n) e <= p && this._drawLatLine(e, t, o, a, _, m, h)
        }
        if (r > 0) {
            for (let e = r; e <= m; e += r) e >= _ && this._drawLonLine(e, t, o, a, p, d, l);
            for (let e = 0; e >= _; e -= r) e <= m && this._drawLonLine(e, t, o, a, p, d, l)
        }
    }
    _drawLatLine(t, e, i, s, n, r, o) {
        const a = this._latLngToCanvasPoint(new ke(t, n)),
            h = this._formatLat(t),
            l = i.measureText(h).width,
            c = this.options.showLabel && e ? l + 10 : 0,
            u = this._latLngToCanvasPoint(new ke(t, r));
        if (i.beginPath(), i.moveTo(1 + c, a.y), i.lineTo(u.x - 1 - c, u.y), i.stroke(), this.options.showLabel && e) {
            const t = a.y + s / 2 - 2;
            i.fillText(h, 0, t), i.fillText(h, o - l, t)
        }
    }
    _drawLonLine(t, e, i, s, n, r, o) {
        const a = this._formatLng(t),
            h = i.measureText(a).width,
            l = this._latLngToCanvasPoint(new ke(r, t)),
            c = this.options.showLabel && e ? s + 5 : 0,
            u = this._latLngToCanvasPoint(new ke(n, t));
        i.beginPath(), i.moveTo(u.x, 5 + c), i.lineTo(l.x, o - 1 - c), i.stroke(), this.options.showLabel && e && (i.fillText(a, u.x - h / 2, s + 5), i.fillText(a, l.x - h / 2, o - 3))
    }
    _latLngToCanvasPoint(t) {
        if (!this.leafletMap) throw new a;
        const e = this.leafletMap,
            i = e.project(t);
        return i._subtract(e.getPixelOrigin()), i.add(e._getMapPanePos())
    }
}
zh = cl, cl.defaultOptions = Object.assign(Object.assign({}, Reflect.get(Oh, "defaultOptions", zh)), {
    showLabel: 1,
    opacity: 1,
    weight: .8,
    color: "#aaa",
    font: "12px Verdana",
    dashArray: [0, 0],
    lngLineCurved: 0,
    latLineCurved: 0,
    zoomInterval: [{
        start: 2,
        end: 2,
        interval: 40
    }, {
        start: 3,
        end: 3,
        interval: 20
    }, {
        start: 4,
        end: 4,
        interval: 10
    }, {
        start: 5,
        end: 7,
        interval: 5
    }, {
        start: 8,
        end: 20,
        interval: 1
    }],
    sides: ["N", "S", "E", "W"],
    latInterval: null,
    lngInterval: null,
    fontColor: null,
    latFormatTickLabel: null,
    lngFormatTickLabel: null
});
class ul extends Di {
    constructor(t, e, i) {
        super(t), this._lastMovementTileUpdateTime = new Date, this._moving = 0, this._onMove = () => {
            if (!this.leafletMap) throw new a;
            const t = new Date;
            if (t.getTime() - this._lastMovementTileUpdateTime.getTime() < 200) return;
            this._lastMovementTileUpdateTime = t;
            const e = Math.round(this.leafletMap.getZoom()),
                i = this.leafletMap.getTileBounds(e);
            this._tileCache.update(i, e)
        }, this._moveStart = () => {
            this._moving = 1
        }, this._moveEnd = () => {
            this._moving = 0
        }, this._tileCache = new ca((t, i) => void 0 !== this.options.minZoom && t.z < this.options.minZoom || void 0 !== this.options.maxZoom && t.z > this.options.maxZoom ? Promise.resolve(null) : e(t, i)), this._tileCache.on("tileloaded", t => {
            i && i(t.coords, t.tile), this._moving || this._redraw()
        })
    }
    onAdd(t) {
        return t.leafletMap.on("move", this._onMove), t.leafletMap.on("movestart", this._moveStart), t.leafletMap.on("moveend", this._moveEnd), super.onAdd(t)
    }
    onRemove(t) {
        return t.leafletMap.off("move", this._onMove), t.leafletMap.off("movestart", this._moveStart), t.leafletMap.off("moveend", this._moveEnd), super.onRemove(t)
    }
    redraw() {
        return this._redraw(), this
    }
    async _draw(t, e) {
        if (!this.leafletMap) throw new a;
        const i = this.leafletMap.getTileBounds(t);
        this._tileCache.update(i, t), await this._drawTiles(i, t, e)
    }
    async _drawTiles(t, e, i) {
        if (!this.leafletMap) throw new a;
        const s = this._canvas,
            n = this._canvas.getContext("2d", {
                willReadFrequently: B
            }),
            r = this.leafletMap.maplibreMap.transform,
            o = this.getPixelRatio();
        n.save();
        try {
            n.globalCompositeOperation = "source-over", n.clearRect(0, 0, s.width, s.height);
            const a = this._tileCache.getOrderedTilePyramid(t, e, 999, 2);
            n.strokeStyle = "grey", n.lineWidth = e > 6 ? 1 : .5;
            for (const t of a) {
                if (i.aborted) break;
                const a = na(t),
                    h = this._tileCache.getData(a);
                if (!h) continue;
                const l = 1 << t.z,
                    c = r.coordinatePoint(new $t(t.x / l, t.y / l)).mult(o),
                    u = r.coordinatePoint(new $t((t.x + 1) / l, (t.y + 1) / l)).mult(o),
                    d = u.x - c.x,
                    p = u.y - c.y,
                    _ = Math.max(c.x, 0),
                    m = Math.max(c.y, 0),
                    f = Math.min(u.x, s.width) - _,
                    g = Math.min(u.y, s.height) - m;
                if (0 !== f && 0 !== g) {
                    n.save();
                    try {
                        n.rect(_, m, f, g), n.clip(), n.clearRect(_, m, f, g), await this._drawTile(n, h, e, t.z, c.x, c.y, d, p, i)
                    } catch (t) {
                        n.clearRect(_, m, f, g)
                    } finally {
                        n.restore()
                    }
                }
            }
        } finally {
            n.restore()
        }
    }
}

function dl(t, e) {
    const i = {
        value: t.value,
        _stringKey: e
    };
    return t.allocations.add(i), i
}
class pl {
    get deleteTimeoutSeconds() {
        return this._deleteTimeoutSeconds
    }
    set deleteTimeoutSeconds(t) {
        this._deleteTimeoutSeconds = t, this._checkTimeouts()
    }
    constructor(t, e, i) {
        this._cache = new Map, this._currentlyLoading = new Map, this._waiting = new Map, this._disposed = 0, this._timeoutInterval = null, this._deleteTimeoutSeconds = 10, this._getStringKey = t, this._load = e, this._delete = i, this._timeoutInterval = setInterval(() => {
            this._checkTimeouts()
        }, 1e3)
    }
    async get(t, e) {
        if (this._disposed) throw Error("Cache is disposed.");
        const i = this._getStringKey(t),
            s = this._cache.get(i);
        if (s) return dl(s, i);
        let n = this._currentlyLoading.get(i);
        const r = !n;
        n || (n = {
            mainAbort: new AbortController,
            promises: []
        }, this._currentlyLoading.set(i, n));
        const o = n,
            a = new Promise((t, s) => {
                const n = {
                    resolve: t,
                    reject: s,
                    finished: 0
                };
                o.promises.push(n), e && e.addEventListener("abort", () => {
                    if (n.finished) return;
                    n.finished = 1, s(Error("Aborted."));
                    const t = this._currentlyLoading.get(i);
                    t && (t.promises.splice(t.promises.indexOf(n), 1), 0 === t.promises.length && (this._currentlyLoading.delete(i), t.mainAbort.abort(la + ": request cancelled")))
                })
            });
        return r && this._load(t, o.mainAbort.signal).then(t => {
            if (o.mainAbort.signal.aborted) {
                this._delete && this._delete(t);
                for (let t = 0; t < o.promises.length; t++) {
                    const e = o.promises[t];
                    e.finished = 1, e.reject(Error("Aborted."))
                }
                return
            }
            if (this._currentlyLoading.get(i) !== o) throw Error("Duplicate or otherwise invalid loading of item detected.");
            if (this._cache.has(i)) throw Error("Loaded an item that is already in the cache.");
            const e = {
                allocations: new Set,
                value: t,
                key: i,
                zeroAllocsTime: performance.now()
            };
            this._cache.set(i, e), this._currentlyLoading.delete(i);
            const s = [];
            for (let t = 0; t < o.promises.length; t++) s.push(dl(e, i));
            for (let t = 0; t < o.promises.length; t++) {
                const e = o.promises[t];
                e.finished = 1, e.resolve(s[t])
            }
            const n = this._waiting.get(i);
            if (n) {
                for (const t of n) t.finished = 1, t.resolve(dl(e, i));
                this._waiting.delete(i)
            }
        }).catch(t => {
            this._currentlyLoading.get(i) === o && this._currentlyLoading.delete(i);
            for (let e = 0; e < o.promises.length; e++) {
                const i = o.promises[e];
                i.finished = 1, i.reject(t)
            }
            if (!o.mainAbort.signal.aborted) {
                const e = this._waiting.get(i);
                if (e) {
                    for (const i of e) i.finished = 1, i.reject(t);
                    this._waiting.delete(i)
                }
            }
        }), a
    }
    async awaitLoad(t, e) {
        if (this._disposed) throw Error("Cache is disposed.");
        const i = this._getStringKey(t),
            s = this._cache.get(i);
        if (s) return dl(s, i);
        let n = this._waiting.get(i);
        return n || (n = [], this._waiting.set(i, n)), new Promise((t, s) => {
            const r = {
                resolve: t,
                reject: s,
                finished: 0
            };
            n.push(r), null == e || e.addEventListener("abort", () => {
                if (r.finished) return;
                r.finished = 1, r.reject(Error("Aborted."));
                const t = this._waiting.get(i);
                if (!t || t !== n) return;
                const e = t.indexOf(r);
                e >= 0 && t.splice(e, 1), 0 === t.length && this._waiting.delete(i)
            })
        })
    }
    free(t) {
        if (this._disposed) throw Error("Cache is disposed.");
        const e = this._cache.get(t._stringKey);
        if (!e) throw Error("Tried to free an item that was already deleted.");
        if (!e.allocations.has(t)) throw Error("Tried to free an item with an alloc token that was already used or is invalid (maybe belongs to another cache or item?).");
        if (e.value !== t.value) throw Error("Alloc token and real cache value mismatch detected.");
        e.allocations.delete(t), 0 === e.allocations.size && (e.zeroAllocsTime = performance.now(), this._deleteTimeoutSeconds <= 0 && this._deleteItem(e))
    }
    dispose() {
        if (this._disposed) throw Error("Cache is disposed.");
        for (const t of this._currentlyLoading.values()) t.mainAbort.abort("Cache was disposed of.");
        null !== this._timeoutInterval && (clearInterval(this._timeoutInterval), this._timeoutInterval = null);
        for (const [t, e] of this._waiting)
            for (const t of e) t.reject("Cache was disposed of.");
        this._waiting.clear();
        for (const t of this._cache.values()) this._deleteItem(t);
        this._disposed = 1
    }
    _deleteItem(t) {
        this._delete && this._delete(t.value), this._cache.delete(t.key)
    }
    _checkTimeouts() {
        const t = performance.now();
        for (const e of this._cache.values()) t - e.zeroAllocsTime >= 1e3 * this._deleteTimeoutSeconds && 0 === e.allocations.size && this._deleteItem(e)
    }
}
var _l = Object.freeze({
    __proto__: null,
    Bounds: Ri,
    CanvasLayer: Di,
    CanvasRenderer: Ro,
    CanvasTileLayer: ul,
    Circle: Hh,
    CircleMarker: $h,
    DivIcon: Ia,
    DivOverlay: th,
    DomEvent: di,
    DomUtil: yo,
    Draggable: Da,
    Earth: Go,
    FeatureGroup: Wa,
    GPX: ol,
    GeoJSON: Nh,
    GridLayer: _a,
    Icon: Sa,
    ImageOverlay: Yh,
    KML: tl,
    LatLng: ke,
    LatLngBounds: Be,
    LatLngGraticule: cl,
    Layer: Si,
    LayerGroup: Ua,
    LeafletGlMap: Vo,
    LineUtil: fh,
    Marker: Na,
    Path: eh,
    Polygon: Fh,
    Polyline: kh,
    Popup: ih,
    ReferenceCountedCache: pl,
    RotatedImageOverlay: Qh,
    SVGRenderer: Co,
    TileCache: ca,
    TileLayer: ea,
    TileQuadTree: ha,
    Tooltip: Xh,
    canvas: Io,
    circle: Vh,
    circleMarker: Wh,
    divIcon: za,
    falseFn: o,
    featureGroup: Ha,
    geoJSON: Gh,
    getCoordsKey: ra,
    gridLayer: ma,
    icon: Aa,
    imageOverlay: Jh,
    isLatLngArrayFlat: ya,
    isLatLngArraySinglyNested: va,
    isWebGL2: ze,
    kml: rl,
    latLng: De,
    latLngBounds: Ne,
    layerGroup: Ga,
    marker: ja,
    polygon: Zh,
    polyline: Dh,
    popup: sh,
    stamp: r,
    svg: So,
    template: _i,
    tileLayer: sa,
    tooltip: Kh,
    wrappedCoords: na,
    zoom: Wo
});

function ml(t, e) {
    const i = void 0 !== t.granularity ? Math.max(t.granularity, 1) : 1,
        s = i + (t.generateBorders ? 2 : 0),
        n = i + (t.extendToNorthPole || t.generateBorders ? 1 : 0) + (t.extendToSouthPole || t.generateBorders ? 1 : 0),
        r = s + 1,
        o = n + 1,
        a = t.generateBorders ? -1 : 0,
        h = t.generateBorders || t.extendToNorthPole ? -1 : 0,
        l = i + (t.generateBorders ? 1 : 0),
        c = i + (t.generateBorders || t.extendToSouthPole ? 1 : 0),
        u = r * o,
        d = s * n * 6,
        p = r * o > 65536;
    if (p && "16bit" === e) throw Error("Granularity is too large and meshes would not fit inside 16 bit vertex indices.");
    const _ = p || "32bit" === e,
        m = new Int16Array(2 * u);
    let f;
    f = _ ? {
        vertices: m,
        indices: new Uint32Array(d),
        uses32bitIndices: 1
    } : {
        vertices: m,
        indices: new Uint16Array(d),
        uses32bitIndices: 0
    };
    const g = f.indices;
    let y = 0;
    for (let e = h; e <= c; e++)
        for (let s = a; s <= l; s++) {
            let n = s / i * D; - 1 === s && (n = -64), s === i + 1 && (n = 8256);
            let r = e / i * D; - 1 === e && (r = t.extendToNorthPole ? -32768 : -64), e === i + 1 && (r = t.extendToSouthPole ? 32767 : 8256), m[y++] = n, m[y++] = r
        }
    let v = 0;
    for (let t = 0; t < n; t++)
        for (let e = 0; e < s; e++) {
            const i = e + 1 + t * r,
                s = e + (t + 1) * r,
                n = e + 1 + (t + 1) * r;
            g[v++] = e + t * r, g[v++] = s, g[v++] = i, g[v++] = i, g[v++] = s, g[v++] = n
        }
    return f
}
const fl = ct;

function gl() {
    return fl
}

function yl() {
    return ut.MAX_PARALLEL_IMAGE_REQUESTS
}

function vl(t) {
    ut.MAX_PARALLEL_IMAGE_REQUESTS = t
}
var bl = Object.freeze({
    __proto__: null,
    AJAXError: mt,
    AttributionControl: Zr,
    BoxZoomHandler: tr,
    CooperativeGesturesHandler: Ar,
    DoubleClickZoomHandler: Er,
    DragPanHandler: Sr,
    DragRotateHandler: Rr,
    EdgeInsets: _s,
    Event: St,
    Evented: It,
    Hash: Fn,
    KeyboardHandler: xr,
    LngLat: Bt,
    LngLatBounds: Ft,
    MapLibreMap: Jr,
    MapMouseEvent: Vn,
    MapTouchEvent: Xn,
    MapWheelEvent: Kn,
    MercatorCoordinate: $t,
    OverscaledTileID: ne,
    Point: h,
    RasterTileSource: Xt,
    ScrollZoomHandler: Pr,
    SourceCache: oe,
    Style: As,
    Tile: Qt,
    TwoFingersTouchPitchHandler: vr,
    TwoFingersTouchRotateHandler: gr,
    TwoFingersTouchZoomHandler: mr,
    TwoFingersTouchZoomRotateHandler: Ir,
    addProtocol: pt,
    addSourceType: Jt,
    config: ut,
    createTileMesh: ml,
    getMaxParallelImageRequests: yl,
    getVersion: gl,
    removeProtocol: _t,
    setMaxParallelImageRequests: vl
});
window.L = Object.assign(Object.assign({}, _l), bl);
export {
    mt as AJAXError, Zr as AttributionControl, Ri as Bounds, tr as BoxZoomHandler, Di as CanvasLayer, Ro as CanvasRenderer, ul as CanvasTileLayer, Hh as Circle, $h as CircleMarker, Ar as CooperativeGesturesHandler, Ia as DivIcon, th as DivOverlay, di as DomEvent, yo as DomUtil, Er as DoubleClickZoomHandler, Sr as DragPanHandler, Rr as DragRotateHandler, Da as Draggable, Go as Earth, _s as EdgeInsets, St as Event, It as Evented, Wa as FeatureGroup, ol as GPX, Nh as GeoJSON, _a as GridLayer, Fn as Hash, Sa as Icon, Yh as ImageOverlay, tl as KML, xr as KeyboardHandler, ke as LatLng, Be as LatLngBounds, cl as LatLngGraticule, Si as Layer, Ua as LayerGroup, Vo as LeafletGlMap, fh as LineUtil, Bt as LngLat, Ft as LngLatBounds, Jr as MapLibreMap, Vn as MapMouseEvent, Xn as MapTouchEvent, Kn as MapWheelEvent, Na as Marker, $t as MercatorCoordinate, ne as OverscaledTileID, eh as Path, h as Point, Fh as Polygon, kh as Polyline, ih as Popup, Xt as RasterTileSource, pl as ReferenceCountedCache, Qh as RotatedImageOverlay, Co as SVGRenderer, Pr as ScrollZoomHandler, oe as SourceCache, As as Style, Qt as Tile, ca as TileCache, ea as TileLayer, ha as TileQuadTree, Xh as Tooltip, vr as TwoFingersTouchPitchHandler, gr as TwoFingersTouchRotateHandler, mr as TwoFingersTouchZoomHandler, Ir as TwoFingersTouchZoomRotateHandler, pt as addProtocol, Jt as addSourceType, Io as canvas, Vh as circle, Wh as circleMarker, ut as config, ml as createTileMesh, za as divIcon, o as falseFn, Ha as featureGroup, Gh as geoJSON, ra as getCoordsKey, yl as getMaxParallelImageRequests, gl as getVersion, ma as gridLayer, Aa as icon, Jh as imageOverlay, ya as isLatLngArrayFlat, va as isLatLngArraySinglyNested, ze as isWebGL2, rl as kml, De as latLng, Ne as latLngBounds, Ga as layerGroup, ja as marker, Zh as polygon, Dh as polyline, sh as popup, _t as removeProtocol, vl as setMaxParallelImageRequests, r as stamp, So as svg, _i as template, sa as tileLayer, Kh as tooltip, na as wrappedCoords, Wo as zoom
};//# sourceMappingURL=leaflet-gl.js.map
