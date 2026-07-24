/**
 * 风场粒子 WebGL 渲染 — GLSL 着色器源码（WebGL1 / GLSL ES 1.00）。
 *
 * 对照 Example/Windy.app WindMap.js 的着色器结构。所有着色器共享同一个
 * 球面 Mercator 投影助手，保证与 MapLibre 世界坐标系 [0,1]² 对齐。
 *
 * 注意：GLSL 字符串中的 ${} 是 TS 模板插值，在编译期拼接，不进入着色器源码。
 */

// ── 共享 Mercator 投影助手 ─────────────────────────────────────────

/**
 * 把球面经纬度 (lon, lat) 投影到 MapLibre 归一化 Mercator 世界坐标 [0,1]²。
 *
 * 坐标约定（与 MapLibre 内部一致）：
 *   x = (lon + 180) / 360  （西 0 → 东 1）
 *   y = 球面 Mercator       （北 0 → 南 1，纬度钳制 ±85.051129）
 * 再乘 u_matrix（modelViewProjectionMatrix）即得裁剪空间坐标。
 */
export const MERCATOR_PROJECTION_GLSL = /* glsl */ `
  vec2 lngLatToMercator(float lon, float latDeg) {
    float lat = clamp(latDeg, -85.051129, 85.051129);
    // 保留解包经度（可 >180）：与 MapLibre world copy 矩阵一致，勿折回 [-180,180]
    // 否则亚洲–太平洋视口右侧太平洋会投到左侧半屏
    float mercX = (lon + 180.0) / 360.0;
    float sinLat = sin(radians(lat));
    float mercY = 0.5 - log((1.0 + sinLat) / (1.0 - sinLat)) / (4.0 * 3.141592653589793);
    return vec2(mercX, mercY);
  }
`

/**
 * 与 MERCATOR_PROJECTION_GLSL 数学等价的 TS 实现。
 *
 * 用途：单测验证投影公式正确性（GLSL 无法直接在 node 环境执行）。
 * 修改任意一侧时必须同步另一侧。
 */
export function lngLatToMercatorNormalized(lon: number, latDeg: number): [number, number] {
  const lat = Math.max(-85.051129, Math.min(85.051129, latDeg))
  const mercX = (lon + 180) / 360
  const sinLat = Math.sin((lat * Math.PI) / 180)
  const mercY = 0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)
  return [mercX, mercY]
}

// ── B1 骨架验证：调试三角形 ─────────────────────────────────────────

/**
 * B1 阶段占位着色器：画一个固定的经纬度三角形，验证
 * 独立 WebGL context + MapLibre matrix 集成是否正确。
 * 接入真实风场（B2）后被风场/粒子着色器替换。
 */
export const TRIANGLE_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_lnglat;
  uniform mat4 u_matrix;
  ${MERCATOR_PROJECTION_GLSL}
  void main() {
    vec2 merc = lngLatToMercator(a_lnglat.x, a_lnglat.y);
    gl_Position = u_matrix * vec4(merc, 0.0, 1.0);
  }
`

export const TRIANGLE_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  void main() {
    gl_FragColor = vec4(1.0, 0.45, 0.1, 0.85);
  }
`

/**
 * Mercator 反投影：把归一化 Mercator 世界坐标 [0,1]² 还原为经纬度。
 *
 * 数学动机：Mercator 归一化坐标在屏幕上**线性插值是精确的**（merc→clip 是线性变换），
 * 因此顶点着色器输出 merc、片元里反投影，可在每个片元得到**逐像素精确**的经纬度，
 * 避免细分网格。逆公式：
 *   M = ln((1+sinφ)/(1-sinφ)) = 4π(0.5 - my)；φ = 2·atan(exp(M/2)) - π/2
 */
export const MERCATOR_INVERSE_GLSL = /* glsl */ `
  vec2 mercatorToLngLat(vec2 merc) {
    float lon = merc.x * 360.0 - 180.0;
    float halfM = (0.5 - merc.y) * 2.0 * 3.141592653589793;
    float lat = degrees(2.0 * atan(exp(halfM)) - 1.5707963267948966);
    return vec2(lon, lat);
  }
`

/**
 * 从风场纹理 (R=u, G=v, B=speed, A=mask) 采样并解码。
 * u/v 编码：byte/255 ∈ [0,1] → (x*2-1) * maxWind；speed 编码：byte/255 * maxWind。
 */
export const WIND_TEXTURE_SAMPLE_GLSL = /* glsl */ `
  uniform sampler2D u_windTexture;
  uniform vec4 u_windBounds;  // west, south, east, north
  uniform float u_maxWind;

  // 由经纬度计算纹理 UV（等距矩形布局：x 西→东，y 北→南）
  // 解包框（east>180）时把 [-180,180] 查询 lon 卷入连续框
  vec2 windTexUv(float lon, float lat) {
    float lonU = lon;
    float west = u_windBounds.x;
    float east = u_windBounds.z;
    if (east > 180.0 || (east - west) > 180.0) {
      if (lonU < west) lonU += 360.0;
      if (lonU >= west + 360.0) lonU -= 360.0;
    }
    return vec2(
      (lonU - west) / (east - west),
      (u_windBounds.w - lat) / (u_windBounds.w - u_windBounds.y)
    );
  }

  // 采样并解码 (u, v) 向量（m/s）；A=0 表示无数据
  vec2 sampleWindVec(vec2 texUv) {
    vec4 t = texture2D(u_windTexture, texUv);
    if (t.a < 0.01) return vec2(0.0);
    float u = (t.r * 2.0 - 1.0) * u_maxWind;
    float v = (t.g * 2.0 - 1.0) * u_maxWind;
    return vec2(u, v);
  }
`

/** B2 风场可视化顶点着色器：投影 + 传递 Mercator 坐标 */
export const WIND_FIELD_VERTEX_SHADER = /* glsl */ `
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
 * B2 风场可视化片元着色器：反投影 → 采样风场 → 速度→颜色。
 * 速度配色用简洁的 蓝→青→白 渐变；B5 阶段替换为 LUT 调色板。
 */
export const WIND_FIELD_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_merc;
  uniform float u_opacity;
  ${MERCATOR_INVERSE_GLSL}
  ${WIND_TEXTURE_SAMPLE_GLSL}
  void main() {
    vec2 lnglat = mercatorToLngLat(v_merc);
    vec2 texUv = windTexUv(lnglat.x, lnglat.y);
    vec4 t = texture2D(u_windTexture, texUv);
    if (t.a < 0.01) {
      discard;
    }
    float speed = t.b * u_maxWind;
    float k = clamp(speed / u_maxWind, 0.0, 1.0);
    vec3 color = mix(vec3(0.10, 0.30, 0.65), vec3(0.55, 0.90, 1.00), smoothstep(0.0, 0.55, k));
    color = mix(color, vec3(1.0), smoothstep(0.55, 1.0, k));
    gl_FragColor = vec4(color, k * u_opacity);
  }
`

// ── B3 粒子平流（ping-pong FBO + RK2）──────────────────────────────

/**
 * 位置纹理 16-bit 分割精度编解码。
 *
 * 粒子位置 (lon, lat) 归一化到风场 bbox 的 [0,1]²，单坐标用 2 个字节存储
 * （hi + lo/255），精度 ~1/65025。RGBA8 四通道正好存 (nx, ny)：
 *   R = nx hi, G = nx lo, B = ny hi, A = ny lo
 */
export const POSITION_ENCODE_GLSL = /* glsl */ `
  float decodeFloat(vec2 enc) {
    return enc.x + enc.y / 255.0;
  }
  vec2 encodeFloat(float v) {
    float hi = floor(v * 255.0);
    float lo = floor((v * 255.0 - hi) * 255.0);
    return vec2(hi, lo) / 255.0;
  }
  vec2 decodePosition(vec4 tex) {
    return vec2(decodeFloat(tex.rg), decodeFloat(tex.ba));
  }
  vec4 encodePosition(float nx, float ny) {
    vec2 ex = encodeFloat(nx);
    vec2 ey = encodeFloat(ny);
    return vec4(ex.x, ex.y, ey.x, ey.y);
  }
`

/** 确定性 hash 随机数（用于粒子重定位与概率丢弃） */
export const RAND_GLSL = /* glsl */ `
  float rand(vec2 co) {
    return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
  }
`

/** B3 更新 pass 顶点着色器：全屏 quad，传递粒子纹素坐标 */
export const PARTICLE_UPDATE_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_pos;  // 裁剪空间 quad [-1,1]
  varying vec2 v_texcoord;
  void main() {
    v_texcoord = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
  }
`

/**
 * B3 更新 pass 片元着色器：对每个粒子做多子步 RK2 midpoint 平流积分。
 *
 * 行为要点：
 *   - 概率丢弃 / u_resetAll → 重定位到随机位置；静风粒子静止不每帧重撒
 *   - 2 子步 RK2 + 每子步位移钳制，抑制急流/辐合带单帧大跳
 *   - 高风速区仅轻微提高重生率（DROP_BUMP 很低），避免高密度区粒子狂跳
 *   - 仅全球网格（east-west≥359°）做反子午线包裹；区域网格出界重撒
 *   - u_remap：bbox 变化首帧仅做归一化坐标重映射，保持轨迹/拖尾稳定
 * 风场纹理直接存 u/v，无需 GPU 三角函数。
 */
export const PARTICLE_UPDATE_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_texcoord;
  uniform sampler2D u_particleTexture;
  uniform float u_scaledSpeed;  // speedScale * zoomFactor * advectDt
  uniform float u_dt;
  uniform float u_frameSeed;
  uniform float u_resetAll;    // >0.5 时全部重定位
  uniform vec4 u_prevWindBounds;  // remap 前的 windBounds（west, south, east, north）
  uniform float u_remap;       // >0.5：仅做 bbox 坐标系重映射，本帧不平流

  // 基础生命周期丢弃；高风速 bump 刻意压低——旧值 0.014 使急流区重生率约 4.5×，
  // 粒子在高密度区不断瞬移，视觉上就是「跳动」。
  const float DROP_RATE = 0.0045;
  const float DROP_BUMP = 0.002;
  const float DROP_REF = 25.0;
  // 单帧总位移上限（度）。急流中 (u/cosLat)*scaledSpeed 可能远超点尺寸导致断线/跳点。
  const float MAX_STEP_DEG = 0.32;
  const int SUBSTEPS = 2;

  ${WIND_TEXTURE_SAMPLE_GLSL}
  ${POSITION_ENCODE_GLSL}
  ${RAND_GLSL}

  void main() {
    vec4 posTex = texture2D(u_particleTexture, v_texcoord);
    vec2 np = decodePosition(posTex);

    float w = u_windBounds.x, s = u_windBounds.y, e = u_windBounds.z, n = u_windBounds.w;

    // bbox 变化后的首帧：把旧归一化坐标按旧 bounds 还原为经纬度，再归一化到新
    // bounds。地理位置不变的粒子轨迹与屏幕拖尾完全不受扰动；出界粒子（zoom-in
    // 后）在新 bbox 内重撒，自动补足密度。
    if (u_remap > 0.5) {
      float plon = mix(u_prevWindBounds.x, u_prevWindBounds.z, np.x);
      float plat = mix(u_prevWindBounds.w, u_prevWindBounds.y, np.y);
      if (plon >= w && plon <= e && plat >= s && plat <= n) {
        gl_FragColor = encodePosition((plon - w) / (e - w), (n - plat) / (n - s));
      } else {
        vec2 rrp = vec2(
          rand(v_texcoord + vec2(u_frameSeed * 2.1, 0.3)),
          rand(v_texcoord + vec2(0.7, u_frameSeed * 2.9))
        );
        gl_FragColor = encodePosition(rrp.x, rrp.y);
      }
      return;
    }

    float lon = mix(w, e, np.x);
    float lat = mix(n, s, np.y);

    vec2 uv0 = sampleWindVec(windTexUv(lon, lat));
    float speed0 = length(uv0);

    // 静风粒子不再每帧重撒（避免风眼/静风区闪烁跳变），仅按正常概率生命周期重生
    float rnd = rand(v_texcoord + vec2(u_frameSeed, u_frameSeed * 1.7));
    float dropChance = (DROP_RATE + DROP_BUMP * min(1.0, speed0 / DROP_REF)) * u_dt;
    bool reseed = u_resetAll > 0.5 || rnd < dropChance;
    if (reseed) {
      vec2 rp = vec2(
        rand(v_texcoord + vec2(u_frameSeed * 2.1, 0.3)),
        rand(v_texcoord + vec2(0.7, u_frameSeed * 2.9))
      );
      gl_FragColor = encodePosition(rp.x, rp.y);
      return;
    }

    // 多子步 RK2 midpoint：在曲率大的急流/台风环流中降低单步误差与过冲
    float h = u_scaledSpeed / float(SUBSTEPS);
    float maxSubStep = MAX_STEP_DEG / float(SUBSTEPS);
    float curLon = lon;
    float curLat = lat;
    for (int i = 0; i < SUBSTEPS; i++) {
      vec2 uvA = sampleWindVec(windTexUv(curLon, curLat));
      float cosA = max(cos(radians(curLat)), 0.1);
      float midLon = curLon + (uvA.x / cosA) * (h * 0.5);
      float midLat = curLat + uvA.y * (h * 0.5);
      vec2 uvB = sampleWindVec(windTexUv(midLon, midLat));
      float cosB = max(cos(radians(midLat)), 0.1);
      float dLon = (uvB.x / cosB) * h;
      float dLat = uvB.y * h;
      float stepLen = length(vec2(dLon, dLat));
      if (stepLen > maxSubStep && stepLen > 1e-8) {
        float scale = maxSubStep / stepLen;
        dLon *= scale;
        dLat *= scale;
      }
      curLon += dLon;
      curLat += dLat;
    }
    float newLon = curLon;
    float newLat = curLat;

    // 边界处理：仅全球网格（跨整圈经度）做反子午线包裹；区域网格出界即重撒，
    // 避免粒子从区域一侧瞬移到对侧造成的混乱。纬度出界始终重撒。
    bool isGlobalGrid = (e - w) >= 359.0;
    bool outOfDomain;
    if (isGlobalGrid) {
      if (newLon > e) newLon = w + (newLon - e);
      if (newLon < w) newLon = e - (w - newLon);
      outOfDomain = newLat > n || newLat < s;
    } else {
      outOfDomain = newLon > e || newLon < w || newLat > n || newLat < s;
    }
    if (outOfDomain) {
      vec2 op = vec2(
        rand(v_texcoord + vec2(u_frameSeed * 3.3, 0.5)),
        rand(v_texcoord + vec2(0.9, u_frameSeed * 1.3))
      );
      gl_FragColor = encodePosition(op.x, op.y);
      return;
    }

    float nnx = clamp((newLon - w) / (e - w), 0.0, 1.0);
    float nny = clamp((n - newLat) / (n - s), 0.0, 1.0);
    gl_FragColor = encodePosition(nnx, nny);
  }
`

/** B3 绘制 pass 顶点着色器：从位置纹理读粒子位置，投影为点 */
export const PARTICLE_DRAW_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_texcoord;  // 粒子在位置纹理中的纹素中心
  uniform mat4 u_matrix;
  uniform sampler2D u_particleTexture;
  uniform float u_pointSize;
  varying float v_speedK;

  ${MERCATOR_PROJECTION_GLSL}
  ${WIND_TEXTURE_SAMPLE_GLSL}
  ${POSITION_ENCODE_GLSL}

  void main() {
    vec4 posTex = texture2D(u_particleTexture, a_texcoord);
    vec2 np = decodePosition(posTex);
    float lon = mix(u_windBounds.x, u_windBounds.z, np.x);
    float lat = mix(u_windBounds.w, u_windBounds.y, np.y);
    float speed = texture2D(u_windTexture, windTexUv(lon, lat)).b * u_maxWind;
    v_speedK = clamp(speed / u_maxWind, 0.0, 1.0);
    vec2 merc = lngLatToMercator(lon, lat);
    gl_Position = u_matrix * vec4(merc, 0.0, 1.0);
    gl_PointSize = u_pointSize;
  }
`

/**
 * 无 VTF 绘制：顶点已是裁剪空间 xy。
 * 颜色走 uniform（Windy 风格近白），片元用 gl_PointCoord 做软圆点。
 */
export const PARTICLE_DRAW_CLIP_VERTEX_SHADER = /* glsl */ `
  attribute vec3 a_clipSpeed; // x,y = NDC；z 保留（兼容缓冲布局）
  uniform float u_pointSize;
  void main() {
    gl_Position = vec4(a_clipSpeed.xy, 0.0, 1.0);
    gl_PointSize = max(u_pointSize, 1.0);
  }
`

/**
 * Windy 风格粒子片元：实心点（不用 gl_PointCoord）。
 * 部分 GPU/ANGLE 上 PointCoord 异常会导致全部 discard → 完全看不见。
 * 连续丝状感靠 trailFade≈0.96 的拖尾叠加，与 WindMap.js 一致。
 */
export const PARTICLE_DRAW_SOFT_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  uniform vec4 u_color;
  void main() {
    gl_FragColor = u_color;
  }
`

/**
 * B5 绘制 pass 片元着色器：按风速从 256×1 LUT 调色板纹理取色。
 * （保留供旧路径/测试；主路径改用 PARTICLE_DRAW_SOFT_FRAGMENT_SHADER）
 */
export const PARTICLE_DRAW_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying float v_speedK;
  uniform sampler2D u_paletteTexture;
  uniform float u_opacity;
  void main() {
    vec4 c = texture2D(u_paletteTexture, vec2(v_speedK, 0.5));
    gl_FragColor = vec4(c.rgb, c.a * u_opacity);
  }
`

// ── B4 拖尾衰减（持久 ping-pong trail FBO）──────────────────────────

/**
 * B4 拖尾衰减片元着色器：把上一帧 trail 纹理整体乘 u_fade（RGB 与 A 同步衰减）。
 *
 * 帧率无关：u_fade = (1 - fadeAlpha)^dt，与 CPU 版指数模型
 * `1 - (1-fadeAlpha)^dt` 数学等价（每帧保留该比例的不透明度）。
 * 复用 PARTICLE_UPDATE_VERTEX_SHADER 的全屏 quad（a_pos → v_texcoord）。
 */
export const TRAIL_FADE_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_texcoord;
  uniform sampler2D u_texture;
  uniform float u_fade;
  void main() {
    vec4 c = texture2D(u_texture, v_texcoord);
    gl_FragColor = vec4(c.rgb * u_fade, c.a * u_fade);
  }
`

/**
 * B4 屏幕合成片元着色器：把 trail 纹理按 alpha 混合 blit 到屏幕。
 * 复用 PARTICLE_UPDATE_VERTEX_SHADER 的全屏 quad。
 */
export const TRAIL_SCREEN_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_texcoord;
  uniform sampler2D u_texture;
  uniform float u_opacity;
  void main() {
    vec4 c = texture2D(u_texture, v_texcoord);
    gl_FragColor = vec4(c.rgb, c.a * u_opacity);
  }
`
