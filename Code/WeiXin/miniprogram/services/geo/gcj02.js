/**
 * GCJ-02（火星坐标）↔ WGS-84 坐标换算。
 *
 * 背景：微信 map 组件（腾讯底图）使用 GCJ-02；CGDA 后端全部为 WGS-84。
 * 规则（见 .ai/plans/2026-08-22-weixin-miniprogram-design.md §2.1）：
 *  - 屏幕/API 往返必须经过本模块，禁止直接混用两套坐标。
 *  - map 组件属性（center/markers）与 regionchange 返回坐标 = GCJ-02。
 *  - 后端 API 参数（overlay-value/weather-point/瓦片 z/x/y）= WGS-84。
 *
 * 移植自 Web 前端 geo-math 语义（标准 GCJ-02 加偏算法，国内范围有效）。
 */

var PI = Math.PI;
var AXIS = 6378245.0; // 克拉索夫斯基椭球长半轴
var EE = 0.00669342162296594323; // 偏心率平方

function outOfChina(lng, lat) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function _transformLat(lng, lat) {
  var ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng));
  ret += ((20.0 * Math.sin(6.0 * lng * PI) + 20.0 * Math.sin(2.0 * lng * PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(lat * PI) + 40.0 * Math.sin((lat / 3.0) * PI)) * 2.0) / 3.0;
  ret += ((160.0 * Math.sin((lat / 12.0) * PI) + 320.0 * Math.sin((lat * PI) / 30.0)) * 2.0) / 3.0;
  return ret;
}

function _transformLng(lng, lat) {
  var ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng));
  ret += ((20.0 * Math.sin(6.0 * lng * PI) + 20.0 * Math.sin(2.0 * lng * PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(lng * PI) + 40.0 * Math.sin((lng / 3.0) * PI)) * 2.0) / 3.0;
  ret += ((150.0 * Math.sin((lng / 12.0) * PI) + 300.0 * Math.sin((lng / 30.0) * PI)) * 2.0) / 3.0;
  return ret;
}

/** WGS-84 → GCJ-02。返回 { lng, lat }。 */
function wgs84ToGcj02(lng, lat) {
  if (outOfChina(lng, lat)) {
    return { lng: lng, lat: lat };
  }
  var dLat = _transformLat(lng - 105.0, lat - 35.0);
  var dLng = _transformLng(lng - 105.0, lat - 35.0);
  var radLat = (lat / 180.0) * PI;
  var magic = Math.sin(radLat);
  magic = 1 - EE * magic * magic;
  var sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / (((AXIS * (1 - EE)) / (magic * sqrtMagic)) * PI);
  dLng = (dLng * 180.0) / ((AXIS / sqrtMagic) * Math.cos(radLat) * PI);
  return { lng: lng + dLng, lat: lat + dLat };
}

/** GCJ-02 → WGS-84（迭代逼近，精度 ~1e-7°）。返回 { lng, lat }。 */
function gcj02ToWgs84(lng, lat) {
  if (outOfChina(lng, lat)) {
    return { lng: lng, lat: lat };
  }
  // 先用单次反变换做初值，再迭代 4 次收敛
  var g = wgs84ToGcj02(lng, lat);
  var wLng = lng - (g.lng - lng);
  var wLat = lat - (g.lat - lat);
  for (var i = 0; i < 4; i++) {
    var gg = wgs84ToGcj02(wLng, wLat);
    wLng = lng - (gg.lng - wLng);
    wLat = lat - (gg.lat - wLat);
  }
  return { lng: wLng, lat: wLat };
}

module.exports = {
  outOfChina: outOfChina,
  wgs84ToGcj02: wgs84ToGcj02,
  gcj02ToWgs84: gcj02ToWgs84
};
