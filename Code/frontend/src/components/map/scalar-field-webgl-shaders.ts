/**
 * 标量场 WebGL 着色器：Mercator 场四边形 + 双纹理 LUT 混合。
 *  - mercator 模式：u_matrix * vec4(merc, 0, 1)
 *  - globe 模式（u_useGlobe=1）：u_matrix * vec4(sphere3D, 1) 配合 mainMatrix(true) 矩阵；
 *    fragment 按 v_globeRim 边缘羽化 + 背面剔除，消灭"矩形色底硬边"。
 */
import {
  GLOBE_SPHERE_GLSL,
  MERCATOR_INVERSE_GLSL,
  MERCATOR_PROJECTION_GLSL,
} from './wind-particle-webgl-shaders'

export { MERCATOR_PROJECTION_GLSL, lngLatToMercatorNormalized } from './wind-particle-webgl-shaders'

export const SCALAR_FIELD_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_lnglat;
  uniform mat4 u_matrix;
  uniform float u_useGlobe;
  varying vec2 v_merc;
  varying float v_globeRim;
  ${MERCATOR_PROJECTION_GLSL}
  ${GLOBE_SPHERE_GLSL}
  void main() {
    vec2 merc = lngLatToMercator(a_lnglat.x, a_lnglat.y);
    v_merc = merc;
    if (u_useGlobe > 0.5) {
      vec3 sphere = lngLatToGlobeSphere(a_lnglat.x, a_lnglat.y);
      vec4 clip = u_matrix * vec4(sphere, 1.0);
      gl_Position = clip;
      v_globeRim = length(clip.xy / clip.w) * (clip.w > 0.0 ? 1.0 : -1.0);
    } else {
      gl_Position = u_matrix * vec4(merc, 0.0, 1.0);
      v_globeRim = -1.0;
    }
  }
`

/**
 * 双标量纹理 + 256×1 LUT。
 * u_blend=0 → 仅 texA；u_blend=1 → 仅 texB；中间线性混合归一化值后再查 LUT。
 * globe 模式额外按 v_globeRim 边缘羽化（0.85→1.05）并丢弃背面像素。
 */
export const SCALAR_FIELD_FRAGMENT_SHADER = /* glsl */ `
  // 默认精度 mediump；u_useGlobe 显式 highp 与 vertex 对齐避免 GLSL link 失败。
  precision mediump float;
  precision mediump int;
  uniform highp float u_useGlobe;
  varying vec2 v_merc;
  varying float v_globeRim;
  uniform sampler2D u_fieldA;
  uniform sampler2D u_fieldB;
  uniform sampler2D u_palette;
  uniform vec4 u_bounds;   // west, south, east, north
  uniform float u_blend;   // 0..1
  uniform float u_opacity;
  uniform float u_placeholder;  // >0.5：灰底占位（数据未到的视口区域）

  ${MERCATOR_INVERSE_GLSL}

  vec2 fieldUv(float lon, float lat) {
    float lonU = lon;
    float west = u_bounds.x;
    float east = u_bounds.z;
    float span = east - west;
    // 与 unwrapLonIntoGridFrame 一致：以网格中心 ±180 解包连续经度，
    // 避免跨日界线视口中负经度片元计算出负 UV 导致被整片丢弃。
    if (span < 359.0 && (east > 180.0 || west < -180.0 || span > 180.0)) {
      float center = (west + east) * 0.5;
      if (lonU < center - 180.0) lonU += 360.0;
      if (lonU > center + 180.0) lonU -= 360.0;
    }
    return vec2(
      (lonU - west) / span,
      (u_bounds.w - lat) / (u_bounds.w - u_bounds.y)
    );
  }

  void main() {
    // 灰底占位：淡灰半透明，数据瓦片到达后由数据 quad 覆盖上色
    if (u_placeholder > 0.5) {
      gl_FragColor = vec4(0.55, 0.58, 0.62, 0.20 * u_opacity);
      return;
    }
    // globe 模式：背面剔除 + 地平线羽化
    if (u_useGlobe > 0.5) {
      if (v_globeRim < 0.0) discard;
      float edgeFade = 1.0 - smoothstep(0.88, 1.06, v_globeRim);
      if (edgeFade <= 0.0) discard;
    }
    vec2 lnglat = mercatorToLngLat(v_merc);
    vec2 uv = fieldUv(lnglat.x, lnglat.y);
    if (uv.x < -0.002 || uv.x > 1.002 || uv.y < -0.002 || uv.y > 1.002) {
      discard;
    }
    vec2 uvClamped = clamp(uv, 0.0, 1.0);
    vec4 a = texture2D(u_fieldA, uvClamped);
    vec4 b = texture2D(u_fieldB, uvClamped);
    float mask = mix(a.a, b.a, clamp(u_blend, 0.0, 1.0));
    if (mask < 0.008) {
      discard;
    }
    // 仅按数据 mask 柔化。不能再对 quad 外框羽化：全球数据的主世界和
    // 相邻世界副本在国际日期变更线恰好共用该外框，两侧同时透明会形成裂缝。
    float softMask = smoothstep(0.008, 0.06, mask);
    float t = mix(a.r, b.r, clamp(u_blend, 0.0, 1.0));
    // 轻微 gamma（0.96）：略压中间调提亮，观感更沉稳
    t = pow(clamp(t, 0.0, 1.0), 0.96);
    // 极弱抖动，打断量化色带（不引入可见噪声纹理）
    float dither = (fract(sin(dot(uvClamped, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.004;
    t = clamp(t + dither, 0.0, 1.0);
    vec4 color = texture2D(u_palette, vec2(t, 0.5));
    float alpha = color.a * softMask * u_opacity;
    if (u_useGlobe > 0.5) {
      float edgeFade = 1.0 - smoothstep(0.88, 1.06, v_globeRim);
      alpha *= edgeFade;
    }
    gl_FragColor = vec4(color.rgb, alpha);
  }
`

/** 测试辅助：clamp blend */
export function clampBlend(t: number): number {
  if (!Number.isFinite(t)) return 0
  return Math.max(0, Math.min(1, t))
}
