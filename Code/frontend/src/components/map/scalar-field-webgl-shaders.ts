/**
 * 标量场 WebGL 着色器：Mercator 场四边形 + 双纹理 LUT 混合。
 */
import {
  MERCATOR_INVERSE_GLSL,
  MERCATOR_PROJECTION_GLSL,
} from './wind-particle-webgl-shaders'

export { MERCATOR_PROJECTION_GLSL, lngLatToMercatorNormalized } from './wind-particle-webgl-shaders'

export const SCALAR_FIELD_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_lnglat;
  uniform mat4 u_matrix;
  varying vec2 v_merc;
  ${MERCATOR_PROJECTION_GLSL}
  void main() {
    vec2 merc = lngLatToMercator(a_lnglat.x, a_lnglat.y);
    v_merc = merc;
    gl_Position = u_matrix * vec4(merc, 0.0, 1.0);
  }
`

/**
 * 双标量纹理 + 256×1 LUT。
 * u_blend=0 → 仅 texA；u_blend=1 → 仅 texB；中间线性混合归一化值后再查 LUT。
 */
export const SCALAR_FIELD_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_merc;
  uniform sampler2D u_fieldA;
  uniform sampler2D u_fieldB;
  uniform sampler2D u_palette;
  uniform vec4 u_bounds;   // west, south, east, north
  uniform float u_blend;   // 0..1
  uniform float u_opacity;

  ${MERCATOR_INVERSE_GLSL}

  vec2 fieldUv(float lon, float lat) {
    return vec2(
      (lon - u_bounds.x) / (u_bounds.z - u_bounds.x),
      (u_bounds.w - lat) / (u_bounds.w - u_bounds.y)
    );
  }

  void main() {
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
    // 边缘羽化：场边界 + alpha softstep，减轻硬边色带
    float edge = min(min(uvClamped.x, 1.0 - uvClamped.x), min(uvClamped.y, 1.0 - uvClamped.y));
    float feather = smoothstep(0.0, 0.045, edge);
    float softMask = smoothstep(0.015, 0.22, mask) * feather;
    float t = mix(a.r, b.r, clamp(u_blend, 0.0, 1.0));
    // 轻微 gamma，压缩中间带状感
    t = pow(clamp(t, 0.0, 1.0), 0.92);
    // 极弱抖动，打断量化色带（不引入可见噪声纹理）
    float dither = (fract(sin(dot(uvClamped, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.004;
    t = clamp(t + dither, 0.0, 1.0);
    vec4 color = texture2D(u_palette, vec2(t, 0.5));
    gl_FragColor = vec4(color.rgb, color.a * softMask * u_opacity);
  }
`

/** 测试辅助：clamp blend */
export function clampBlend(t: number): number {
  if (!Number.isFinite(t)) return 0
  return Math.max(0, Math.min(1, t))
}
