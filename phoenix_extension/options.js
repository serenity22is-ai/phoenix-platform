// Phoenix Extension Options
(function() {
  const serverUrl = document.getElementById("serverUrl");
  const helperToken = document.getElementById("helperToken");
  const servicePort = document.getElementById("servicePort");
  const saveBtn = document.getElementById("saveBtn");
  const testBtn = document.getElementById("testBtn");
  const statusMsg = document.getElementById("statusMsg");

  function showStatus(message, isError) {
    statusMsg.textContent = message;
    statusMsg.className = `status-msg ${isError ? "error" : "success"}`;
  }

  // Load saved settings
  chrome.storage.sync.get(["serverUrl", "helperToken", "servicePort"], (data) => {
    if (data.serverUrl) serverUrl.value = data.serverUrl;
    if (data.helperToken) helperToken.value = data.helperToken;
    if (data.servicePort) servicePort.value = data.servicePort;
  });

  // Save
  saveBtn.addEventListener("click", () => {
    chrome.storage.sync.set({
      serverUrl: serverUrl.value.trim(),
      helperToken: helperToken.value.trim(),
      servicePort: parseInt(servicePort.value) || 19750
    }, () => {
      showStatus("Settings saved successfully!", false);
    });
  });

  // Test connection
  testBtn.addEventListener("click", async () => {
    const port = parseInt(servicePort.value) || 19750;
    try {
      const res = await fetch(`http://localhost:${port}/status`);
      const data = await res.json();
      if (data.connected) {
        showStatus(`Connected! Node ID: ${data.node_id}`, false);
      } else {
        showStatus("Service running but not connected to backend", true);
      }
    } catch (e) {
      showStatus("Cannot reach local service. Make sure node_service.py is running.", true);
    }
  });

  // --- Node Consent Economy (Build #75) ---

  const consentStatusMsg = document.getElementById("consentStatusMsg");
  const saveConsentBtn = document.getElementById("saveConsentBtn");

  const CONSENT_FIELDS = [
    "consent_search_queries",
    "consent_price_observations",
    "consent_ad_impressions",
    "consent_social_signals",
    "consent_browsing_data",
    "consent_business_data",
  ];

  function showConsentStatus(message, isError) {
    consentStatusMsg.textContent = message;
    consentStatusMsg.className = `status-msg ${isError ? "error" : "success"}`;
  }

  async function loadConsentProfile() {
    const url = serverUrl.value.trim();
    const token = helperToken.value.trim();
    if (!url || !token) return;

    try {
      const res = await fetch(`${url}/api/v1/node/consent`, {
        headers: { "Authorization": `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      const profile = data.profile || {};

      // Set checkboxes
      CONSENT_FIELDS.forEach((field) => {
        const el = document.getElementById(field);
        if (el && profile[field] !== undefined) el.checked = profile[field];
      });

      // Tier info
      const tierInfo = document.getElementById("tierInfo");
      const tier = (profile.current_tier || "bronze").charAt(0).toUpperCase() + (profile.current_tier || "bronze").slice(1);
      const score = profile.tier_score || 0;
      const multiplier = profile.payout_multiplier || 1.0;
      const discount = ((profile.arbitrage_fee_discount || 0) * 100).toFixed(0);
      tierInfo.innerHTML = `
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
          <span style="font-weight:600;color:#333;">${tier}</span>
          <span style="color:#1a73e8;font-weight:600;">Score: ${score}/100</span>
        </div>
        <div style="height:6px;background:#e0e0e0;border-radius:3px;overflow:hidden;margin-bottom:8px;">
          <div style="height:100%;width:${score}%;background:linear-gradient(90deg,#1a73e8,#00e676);border-radius:3px;"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:12px;">
          <span>Payout: ${multiplier}x</span>
          <span>Arbitrage Discount: ${discount}%</span>
        </div>
      `;
    } catch (e) {
      // Silent — tier info stays as loading
    }
  }

  // Bridge consent to chrome.storage.local for content.js + background.js
  function syncConsentToLocal() {
    const consentState = {
      onboarding_completed: true,
      location: true,
      updated_at: new Date().toISOString(),
    };

    CONSENT_FIELDS.forEach((field) => {
      const el = document.getElementById(field);
      // Map "consent_search_queries" → "search_queries"
      const key = field.replace("consent_", "");
      consentState[key] = el ? el.checked : false;
    });

    chrome.storage.local.set({ consent_state: consentState });
    chrome.runtime.sendMessage({
      type: "consent_updated",
      consent_state: consentState,
    });
  }

  // Save consent
  saveConsentBtn.addEventListener("click", async () => {
    const url = serverUrl.value.trim();
    const token = helperToken.value.trim();
    if (!url || !token) {
      showConsentStatus("Set server URL and token first.", true);
      return;
    }

    const updates = {};
    CONSENT_FIELDS.forEach((field) => {
      const el = document.getElementById(field);
      if (el) updates[field] = el.checked;
    });

    try {
      const res = await fetch(`${url}/api/v1/node/consent`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        showConsentStatus("Consent updated!", false);
        syncConsentToLocal();
        loadConsentProfile();
      } else {
        const err = await res.json().catch(() => ({}));
        showConsentStatus(err.error || "Failed to update consent.", true);
      }
    } catch (e) {
      showConsentStatus("Network error saving consent.", true);
    }
  });

  // Load consent on page open + sync to local storage
  loadConsentProfile();
  syncConsentToLocal();

  // --- OAuth Re-authentication (Build #83) ---

  const reAuthMsg = document.getElementById("reAuthMsg");

  // Microsoft Azure AD — replace with your registered Application (client) ID
  const MICROSOFT_CLIENT_ID = "PLACEHOLDER_MICROSOFT_CLIENT_ID";
  // Apple Sign-In — replace with your Services ID
  const APPLE_CLIENT_ID = "PLACEHOLDER_APPLE_SERVICE_ID";

  async function handleReAuthResult(result) {
    const url = serverUrl.value.trim() || "https://phoenix.example.com";
    await chrome.storage.sync.set({
      serverUrl: result.serverUrl || url,
      helperToken: result.helperToken,
      userName: result.userName,
      userEmail: result.userEmail,
    });
    serverUrl.value = result.serverUrl || url;
    helperToken.value = result.helperToken;
    reAuthMsg.className = "status-msg success";
    reAuthMsg.textContent = `Re-authenticated as ${result.userEmail}`;
    loadConsentProfile();
  }

  // Google re-auth
  const reAuthGoogleBtn = document.getElementById("reAuthGoogleBtn");
  if (reAuthGoogleBtn) {
    reAuthGoogleBtn.addEventListener("click", async () => {
      try {
        reAuthGoogleBtn.disabled = true;
        reAuthGoogleBtn.textContent = "...";

        const token = await new Promise((resolve, reject) => {
          chrome.identity.getAuthToken({ interactive: true }, (token) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
            } else {
              resolve(token);
            }
          });
        });

        if (!token) throw new Error("Failed to get Google access token");

        const url = serverUrl.value.trim() || "https://phoenix.example.com";
        const res = await fetch(`${url}/api/v1/auth/google`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ access_token: token }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || "Re-authentication failed");
        }

        await handleReAuthResult(await res.json());
      } catch (e) {
        reAuthMsg.className = "status-msg error";
        reAuthMsg.textContent = e.message;
      } finally {
        reAuthGoogleBtn.disabled = false;
        reAuthGoogleBtn.textContent = "Re-auth Google";
      }
    });
  }

  // Microsoft re-auth
  const reAuthMicrosoftBtn = document.getElementById("reAuthMicrosoftBtn");
  if (reAuthMicrosoftBtn) {
    reAuthMicrosoftBtn.addEventListener("click", async () => {
      try {
        reAuthMicrosoftBtn.disabled = true;
        reAuthMicrosoftBtn.textContent = "...";

        const redirectUrl = chrome.identity.getRedirectURL();
        const authUrl = new URL("https://login.microsoftonline.com/common/oauth2/v2.0/authorize");
        authUrl.searchParams.set("client_id", MICROSOFT_CLIENT_ID);
        authUrl.searchParams.set("response_type", "token");
        authUrl.searchParams.set("redirect_uri", redirectUrl);
        authUrl.searchParams.set("scope", "openid email profile User.Read");
        authUrl.searchParams.set("response_mode", "fragment");

        const responseUrl = await new Promise((resolve, reject) => {
          chrome.identity.launchWebAuthFlow(
            { url: authUrl.toString(), interactive: true },
            (response) => {
              if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
              else resolve(response);
            }
          );
        });

        const fragment = new URL(responseUrl).hash.substring(1);
        const params = new URLSearchParams(fragment);
        const accessToken = params.get("access_token");
        if (!accessToken) throw new Error("No access token from Microsoft");

        const url = serverUrl.value.trim() || "https://phoenix.example.com";
        const res = await fetch(`${url}/api/v1/auth/microsoft`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ access_token: accessToken }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || "Re-authentication failed");
        }

        await handleReAuthResult(await res.json());
      } catch (e) {
        reAuthMsg.className = "status-msg error";
        reAuthMsg.textContent = e.message;
      } finally {
        reAuthMicrosoftBtn.disabled = false;
        reAuthMicrosoftBtn.textContent = "Re-auth Microsoft";
      }
    });
  }

  // Apple re-auth
  const reAuthAppleBtn = document.getElementById("reAuthAppleBtn");
  if (reAuthAppleBtn) {
    reAuthAppleBtn.addEventListener("click", async () => {
      try {
        reAuthAppleBtn.disabled = true;
        reAuthAppleBtn.textContent = "...";

        const redirectUrl = chrome.identity.getRedirectURL();
        const authUrl = new URL("https://appleid.apple.com/auth/authorize");
        authUrl.searchParams.set("client_id", APPLE_CLIENT_ID);
        authUrl.searchParams.set("response_type", "code id_token");
        authUrl.searchParams.set("redirect_uri", redirectUrl);
        authUrl.searchParams.set("scope", "name email");
        authUrl.searchParams.set("response_mode", "fragment");

        const responseUrl = await new Promise((resolve, reject) => {
          chrome.identity.launchWebAuthFlow(
            { url: authUrl.toString(), interactive: true },
            (response) => {
              if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
              else resolve(response);
            }
          );
        });

        const fragment = new URL(responseUrl).hash.substring(1);
        const params = new URLSearchParams(fragment);
        const idToken = params.get("id_token");
        if (!idToken) throw new Error("No ID token from Apple");

        const url = serverUrl.value.trim() || "https://phoenix.example.com";
        const res = await fetch(`${url}/api/v1/auth/apple`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id_token: idToken }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || "Re-authentication failed");
        }

        await handleReAuthResult(await res.json());
      } catch (e) {
        reAuthMsg.className = "status-msg error";
        reAuthMsg.textContent = e.message;
      } finally {
        reAuthAppleBtn.disabled = false;
        reAuthAppleBtn.textContent = "Re-auth Apple";
      }
    });
  }
})();
