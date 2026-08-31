/**
 * 轻量发布订阅 store（M1 仅骨架，M2 起承接 layers/time/basemap 状态）。
 * 用法：
 *   var store = require('store/index');
 *   store.set('basemap', 'satellite');
 *   var off = store.on('basemap', function (v) { ... });
 */
var _state = {};
var _listeners = {};

function get(key) {
  return _state[key];
}

function set(key, value) {
  _state[key] = value;
  var list = _listeners[key] || [];
  for (var i = 0; i < list.length; i++) {
    try {
      list[i](value);
    } catch (e) {
      console.error('[store] listener error for key', key, e);
    }
  }
}

function on(key, fn) {
  if (!_listeners[key]) {
    _listeners[key] = [];
  }
  _listeners[key].push(fn);
  return function off() {
    var list = _listeners[key] || [];
    var idx = list.indexOf(fn);
    if (idx >= 0) {
      list.splice(idx, 1);
    }
  };
}

module.exports = { get: get, set: set, on: on };
