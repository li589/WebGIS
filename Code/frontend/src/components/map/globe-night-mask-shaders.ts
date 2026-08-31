/**
 * Globe 夜半球 WebGL 着色器 — 球面网格 + 逐像素太阳高度角（硬边 v1）。
 * 不用 MapLibre image source（四角线性插值在全球 equirectangular 上会扭曲成多圈）。
 *
 * ⚠️ 夜半球网格必须覆盖到真正的 ±90° 极点。
 * 共享的 lngLatToGlobeSphere（风场/标量）会把纬度钳到 ±85.051°（Mercator 瓦片上限），
 * 若夜半球也用该钳制，8–23 月南极极夜区会露出「极冠亮洞」。
 */

/** 夜半球专用：允许 lat∈[-90,90]，极点坍缩到 (0,±1,0) */
export const GLOBE_NIGHT_SPHERE_GLSL = /* glsl */ `
  vec3 lngLatToGlobeSphereNight(float lon, float latDeg) {
    float lonRad = radians(lon);
    float latRad = radians(clamp(latDeg, -90.0, 90.0));
    float cosLat = cos(latRad);
    return vec3(cosLat * sin(lonRad), sin(latRad), cosLat * cos(lonRad));
  }
`

export const GLOBE_NIGHT_MASK_VERTEX_SHADER = /* glsl */ `
  attribute vec2 a_lnglat;
  uniform mat4 u_matrix;
  varying vec2 v_lnglat;
  varying vec3 v_sphere;
  varying float v_globeRim;
  ${GLOBE_NIGHT_SPHERE_GLSL}
  void main() {
    v_lnglat = a_lnglat;
    vec3 sphere = lngLatToGlobeSphereNight(a_lnglat.x, a_lnglat.y);
    v_sphere = sphere;
    vec4 clip = u_matrix * vec4(sphere, 1.0);
    gl_Position = clip;
    v_globeRim = length(clip.xy / clip.w) * (clip.w > 0.0 ? 1.0 : -1.0);
  }
`

export const GLOBE_NIGHT_MASK_FRAGMENT_SHADER = /* glsl */ `
  precision mediump float;
  varying vec2 v_lnglat;
  varying vec3 v_sphere;
  varying float v_globeRim;
  uniform float u_subsolarLon;
  uniform float u_declDeg;
  uniform vec3 u_camDir;
  uniform vec3 u_nightRgb;
  uniform float u_nightAlpha;

  void main() {
    // clip.w < 0：相机后方；dot <= 0：球体背对相机半球（会投影到可见圆盘内形成
    // 双重晨昏线）。仅绘制朝向相机的前半球。
    if (v_globeRim < 0.0) discard;
    // ⚠️ 逐像素归一化：顶点插值的 v_sphere 在球面轮廓附近不精确（三角形跨越
    // 轮廓线时顶点级 dot 判断出错，三角形片会"翻到球面外"→ 边缘往后弯/壳感）。
    // 每像素用精确球面法向做背面剔除 → 三角形被精确裁到球面轮廓。
    vec3 n = normalize(v_sphere);
    if (dot(n, u_camDir) <= 0.0) discard;

    float latRad = radians(v_lnglat.y);
    float declRad = radians(u_declDeg);
    float ha = radians(v_lnglat.x - u_subsolarLon);
    float sinH = sin(latRad) * sin(declRad) + cos(latRad) * cos(declRad) * cos(ha);

    // 大气折射修正：太阳在地平线下 ~0.83° 时仍照亮地面（真实晨昏线比几何位置
    // 偏 ~0.83°），sinH + sin(0.83°) 作为判据。
    float sinRefract = sinH + 0.0145;
    // 软边晨昏过渡：sinRefract ∈ [-sin(2°), 0] 内 alpha 从 1 线性降到 0，
    // 替代硬边"切一半"——看起来像真实晨昏过渡而非被刀切。
    float t = clamp(-sinRefract / 0.0349, 0.0, 1.0);
    if (t <= 0.0) discard;

    gl_FragColor = vec4(u_nightRgb, u_nightAlpha * t);
  }
`

/** Mercator 瓦片纬度上限（仅作分界参考；夜半球网格仍须到 ±90） */
export const GLOBE_MERCATOR_MAX_LAT = 85.051129

/**
 * 构建全球 lat/lon 三角网格，覆盖真正的 ±90° 极点。
 * 主体带用固定步长；极冠（|φ|>85.051）用扇形填到极点，消除南/北极亮洞。
 * 默认 2°×2°：相比 3° 网格三角形更贴合球面（减少"壳"感/平面偏差），
 * 顶点数 ~2.25 倍（约 65k 三角形），静态 buffer 一次性上传，性能无压力。
 */
export function buildGlobeNightMesh(lonStepDeg = 2, latStepDeg = 2): Float32Array {
  const lonMin = -180
  const lonMax = 180
  const latMin = -GLOBE_MERCATOR_MAX_LAT
  const latMax = GLOBE_MERCATOR_MAX_LAT
  const verts: number[] = []

  const pushQuad = (lon: number, lat: number, lon2: number, lat2: number) => {
    // CCW: (lon,lat) (lon2,lat) (lon,lat2)
    verts.push(lon, lat, lon2, lat, lon, lat2)
    // (lon2,lat) (lon2,lat2) (lon,lat2)
    verts.push(lon2, lat, lon2, lat2, lon, lat2)
  }

  // 主体：±85.051° 之间
  for (let lat = latMin; lat < latMax - 1e-6; lat += latStepDeg) {
    const lat2 = Math.min(latMax, lat + latStepDeg)
    for (let lon = lonMin; lon < lonMax - 1e-6; lon += lonStepDeg) {
      pushQuad(lon, lat, lon + lonStepDeg, lat2)
    }
  }

  // 北极冠：85.051 → 90（单极点扇形；勿在 90° 放两套不同 lon——球面坍缩后三角形面积为 0）
  for (let lon = lonMin; lon < lonMax - 1e-6; lon += lonStepDeg) {
    const lon2 = lon + lonStepDeg
    // CCW 外向：外圈 → 极点
    verts.push(lon, latMax, lon2, latMax, 0, 90)
  }

  // 南极冠：-85.051 → -90（单极点扇形；绕序与北极对称，保证背面剔除正确）
  for (let lon = lonMin; lon < lonMax - 1e-6; lon += lonStepDeg) {
    const lon2 = lon + lonStepDeg
    verts.push(lon, latMin, lon2, latMin, 0, -90)
  }

  return new Float32Array(verts)
}

/** 网格纬度范围（单测用） */
export function globeNightMeshLatRange(mesh = buildGlobeNightMesh()): {
  minLat: number
  maxLat: number
} {
  let minLat = Infinity
  let maxLat = -Infinity
  for (let i = 1; i < mesh.length; i += 2) {
    minLat = Math.min(minLat, mesh[i]!)
    maxLat = Math.max(maxLat, mesh[i]!)
  }
  return { minLat, maxLat }
}

export const GLOBE_NIGHT_MESH_VERTEX_COUNT = buildGlobeNightMesh().length / 2
