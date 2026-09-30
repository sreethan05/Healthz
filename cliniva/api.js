/* Cliniva API client — talks to the real FastAPI backend. No mock data. */
(function () {
  var params = new URLSearchParams(location.search);
  var override = params.get("api");
  var API = {
    base: override ? override.replace(/\/+$/, "") : "",
    get token() { return sessionStorage.getItem("cliniva_token") || ""; },
    get role() { return sessionStorage.getItem("cliniva_role") || ""; },
    get user() { return sessionStorage.getItem("cliniva_user") || ""; },
    get authed() { return !!sessionStorage.getItem("cliniva_token"); }
  };

  function persist(token, role, user) {
    if (token) sessionStorage.setItem("cliniva_token", token);
    if (role) sessionStorage.setItem("cliniva_role", role);
    if (user) sessionStorage.setItem("cliniva_user", user);
  }

  API.login = function (username, password) {
    return call("POST", "/auth/login", { username: username, password: password }).then(function (r) {
      persist(r.token, r.role, username);
      return r;
    });
  };

  API.logout = function () {
    sessionStorage.removeItem("cliniva_token");
    sessionStorage.removeItem("cliniva_role");
    sessionStorage.removeItem("cliniva_user");
  };

  function detailToMessage(data) {
    if (data && typeof data.detail === "string") return data.detail;
    if (data && data.detail && typeof data.detail === "object" && data.detail.message) return data.detail.message;
    if (data && data.error) return data.error;
    return null;
  }

  function call(method, path, body) {
    var headers = { "Content-Type": "application/json" };
    if (API.token) headers.Authorization = "Bearer " + API.token;
    return fetch(API.base + path, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      if (res.status === 401 && API.authed) {
        API.logout();
        location.hash = "#/login";
        throw { status: 401, error: "Your session has expired. Please sign in again." };
      }
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          throw {
            status: res.status,
            error: detailToMessage(data) || ("Request failed (" + res.status + ")"),
            detail: data && data.detail
          };
        }
        return data;
      });
    }, function () {
      throw { status: 0, error: "Cannot reach the Cliniva server. Check your connection and try again." };
    });
  }

  API.get = function (path) { return call("GET", path); };
  API.post = function (path, body) { return call("POST", path, body); };
  window.API = API;
})();
