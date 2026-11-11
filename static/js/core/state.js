/**
 * state.js — lightweight global state store
 */
const State = (() => {
  const _store = {
    user:        null,
    workspaces:  [],
    activeWs:    null,   // { id, name, folder_name, role }
    activeProject: null, // project name string
  };

  const _listeners = {};

  function get(key) { return _store[key]; }

  function set(key, value) {
    _store[key] = value;
    if (_listeners[key]) _listeners[key].forEach(fn => fn(value));
  }

  function on(key, fn) {
    if (!_listeners[key]) _listeners[key] = [];
    _listeners[key].push(fn);
  }

  return { get, set, on };
})();
