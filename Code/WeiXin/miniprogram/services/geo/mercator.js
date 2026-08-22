/**
 * Web Mercator 投影与屏幕对齐矩阵。
 *
 * 关键原理（方案 §2.1）：
 * 腾讯底图瓦片本身就是按 GCJ-02 坐标做 Web Mercator 切片的，
 * 因此对 GCJ-02 坐标直接套 mercator 公式，得到的屏幕像素与底图严格对齐。
 * WGS-84 数据先 wgs84ToGcj02 再进本模块。
 */

var PI = Math.PI;
var TILE_SIZE = 256;

/** 缩放级 z 对应的世界像素宽 */
function worldSize(z) {
  return TILE_SIZE * Math.pow(2, z);
}

/** 经纬度 → 世界像素（z 级）。lng/lat 为 GCJ-02（与底图同坐标系）。 */
function project(lng, lat, world) {
  var x = ((lng + 180) / 360) * world;
  var sin = Math.sin((lat * PI) / 180);
  var y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * PI)) * world;
  return { x: x, y: y };
}

/** 世界像素 → 经纬度（z 级），返回 GCJ-02。 */
function unproject(x, y, world) {
  var lng = (x / world) * 360 - 180;
  var n = PI - (2 * PI * y) / world;
  var lat = (180 / PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return { lng: lng, lat: lat };
}

/**
 * 纬度 lat（度）、缩放 z 下的地面分辨率（米/像素）。
 * 用于比例尺：metersPerPixel = 156543.03392 * cos(lat) / 2^z
 */
function metersPerPixel(latDeg, z) {
  return (156543.03392 * Math.cos((latDeg * PI) / 180)) / Math.pow(2, z);
}

/**
 * 视口（中心点 + z + 画布尺寸）→ 覆盖的 XYZ 瓦片集合（M2 瓦片调度器用）。
 * centerGcj: {lng,lat}；返回瓦片列表 [{z,x,y,screenX,screenY}]，
 * screenX/screenY 为该瓦片左上角在当前画布上的像素位置。
 * margin: 屏幕外多取的圈数（默认 1 圈缓冲）。
 */
function visibleTiles(centerGcj, z, canvasW, canvasH, margin) {
  var zi = Math.round(z);
  var clampedZ = Math.max(0, Math.min(19, zi));
  var world = worldSize(z); // 浮点 z：屏幕定位用，保证平滑
  var c = project(centerGcj.lng, centerGcj.lat, world);
  var halfW = canvasW / 2 + (margin || 1) * TILE_SIZE;
  var halfH = canvasH / 2 + (margin || 1) * TILE_SIZE;
  var scaleRatio = world / worldSize(clampedZ); // 2^(z-zi)，瓦片在屏幕上的缩放

  // 视口世界像素范围 → 整数 z 级瓦片索引范围
  var n = Math.pow(2, clampedZ);
  var minX = Math.floor((((c.x - halfW) / world) * n));
  var maxX = Math.floor((((c.x + halfW) / world) * n));
  var minY = Math.floor((((c.y - halfH) / world) * n));
  var maxY = Math.floor((((c.y + halfH) / world) * n));
  var maxIndex = n - 1;

  var tiles = [];
  for (var x = Math.max(0, minX); x <= Math.min(maxIndex, maxX); x++) {
    for (var y = Math.max(0, minY); y <= Math.min(maxIndex, maxY); y++) {
      // 瓦片左上角的世界像素（整数 z 级）→ 浮点 z 级 → 屏幕像素
      var worldX = x * TILE_SIZE * scaleRatio;
      var worldY = y * TILE_SIZE * scaleRatio;
      tiles.push({
        z: clampedZ,
        x: x,
        y: y,
        screenX: worldX - c.x + canvasW / 2,
        screenY: worldY - c.y + canvasH / 2,
        screenSize: TILE_SIZE * scaleRatio
      });
    }
  }
  return tiles;
}

/**
 * 视口（GCJ-02 中心 + z + 画布尺寸）→ WGS-84 经纬度范围。
 * 用于向 WGS-84 瓦片服务（overlay-tiles）请求正确的瓦片集合。
 */
function viewportWgsBounds(centerGcj, z, canvasW, canvasH) {
  var world = worldSize(z);
  var c = project(centerGcj.lng, centerGcj.lat, world);
  var corners = [
    unproject(c.x - canvasW / 2, c.y - canvasH / 2, world),
    unproject(c.x + canvasW / 2, c.y - canvasH / 2, world),
    unproject(c.x - canvasW / 2, c.y + canvasH / 2, world),
    unproject(c.x + canvasW / 2, c.y + canvasH / 2, world)
  ];
  var west = Infinity;
  var east = -Infinity;
  var south = Infinity;
  var north = -Infinity;
  corners.forEach(function (p) {
    west = Math.min(west, p.lng);
    east = Math.max(east, p.lng);
    south = Math.min(south, p.lat);
    north = Math.max(north, p.lat);
  });
  return { west: west, south: south, east: east, north: north };
}

/**
 * WGS-84 经纬度范围 → 整数 z 级瓦片索引集合（不带屏幕定位，定位由调用方
 * 经 gcj02→P 链路计算，见 map-shell._tileRect）。
 */
function wgsTilesForBounds(bounds, z, margin) {
  var n = Math.pow(2, z);
  var m = margin || 1;
  var west = Math.max(-180, bounds.west - (m * 360) / n);
  var east = Math.min(180, bounds.east + (m * 360) / n);
  var south = Math.max(-85.05, bounds.south);
  var north = Math.min(85.05, bounds.north);
  if (west >= east || south >= north) {
    return [];
  }
  var minX = Math.floor(((west + 180) / 360) * n);
  var maxX = Math.floor(((east + 180) / 360) * n);
  var world = worldSize(z);
  var nw = project(west, north, world);
  var sw = project(west, south, world);
  var minY = Math.max(0, Math.floor(nw.y / TILE_SIZE) - m);
  var maxY = Math.min(n - 1, Math.floor(sw.y / TILE_SIZE) + m);
  var tiles = [];
  for (var x = Math.max(0, minX); x <= Math.min(n - 1, maxX); x++) {
    for (var y = minY; y <= maxY; y++) {
      tiles.push({ z: z, x: x, y: y });
    }
  }
  return tiles;
}

module.exports = {
  TILE_SIZE: TILE_SIZE,
  worldSize: worldSize,
  project: project,
  unproject: unproject,
  metersPerPixel: metersPerPixel,
  visibleTiles: visibleTiles,
  viewportWgsBounds: viewportWgsBounds,
  wgsTilesForBounds: wgsTilesForBounds
};
