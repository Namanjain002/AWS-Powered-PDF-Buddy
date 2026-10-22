const CONFIG = {
  domain: "https://us-east-1rbhzgb7oy.auth.us-east-1.amazoncognito.com",
  clientId: "18v471ko83cr9gm0v3hjeuk7o1",
  redirectUri: "http://localhost:5500/",
  apiUrl: "https://mb07aecp34.execute-api.us-east-1.amazonaws.com",
};

const b64url = (buf) =>
  btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function randomString() {
  const a = new Uint8Array(32);
  crypto.getRandomValues(a);
  return b64url(a);
}

async function login() {
  const verifier = randomString();
  sessionStorage.setItem("pkce_verifier", verifier);
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: CONFIG.clientId,
    redirect_uri: CONFIG.redirectUri,
    scope: "openid email",
    code_challenge: b64url(hash),
    code_challenge_method: "S256",
  });
  location.href = `${CONFIG.domain}/oauth2/authorize?${params}`;
}

async function handleCallback() {
  const code = new URLSearchParams(location.search).get("code");
  if (!code) return;
  const res = await fetch(`${CONFIG.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CONFIG.clientId,
      code,
      redirect_uri: CONFIG.redirectUri,
      code_verifier: sessionStorage.getItem("pkce_verifier"),
    }),
  });
  const t = await res.json();
  sessionStorage.setItem("id_token", t.id_token);
  history.replaceState({}, "", "/");
}

async function api(body) {
  const res = await fetch(`${CONFIG.apiUrl}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + sessionStorage.getItem("id_token"),
    },
    body: JSON.stringify(body),
  });
  return res.json();
}
async function uploadPdf(file, folder = "default") {
  const token = sessionStorage.getItem("id_token");
  const r = await fetch(CONFIG.apiUrl + "/upload", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ filename: file.name, folder }),
  });
  if (!r.ok) throw new Error("presign failed: " + r.status);
  const { url, fields, key } = await r.json();

  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  form.append("file", file); // must be the LAST field
  const up = await fetch(url, { method: "POST", body: form });
  if (!up.ok) throw new Error("upload failed: " + up.status);
  return key;;
}