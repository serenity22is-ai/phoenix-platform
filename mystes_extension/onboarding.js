/**
 * Mystes Node Extension — Onboarding Wizard (Build #83)
 *
 * Multi-provider OAuth one-click flow:
 *   Step 1: Welcome + "Continue with Google/Microsoft/Apple" / manual token (fallback)
 *   Step 2: Data category selection (all OFF by default)
 *   Success: Auto-authenticated, credentials saved
 *
 * Saves consent_state to chrome.storage.local + sync,
 * pushes consent to backend if connected, and notifies
 * background.js to register/unregister content scripts.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_SERVER_URL = "https://mystes.example.com";

// Microsoft Azure AD — replace with your registered Application (client) ID
const MICROSOFT_CLIENT_ID = "PLACEHOLDER_MICROSOFT_CLIENT_ID";

// Apple Sign-In — replace with your Services ID
const APPLE_CLIENT_ID = "PLACEHOLDER_APPLE_SERVICE_ID";

const steps = ["step1", "step2", "stepSuccess"];
let currentStep = 0;
let authCredentials = null;

// ---------------------------------------------------------------------------
// Step navigation
// ---------------------------------------------------------------------------

function showStep(index) {
  steps.forEach((id, i) => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("active", i === index);
  });
  for (let i = 1; i <= 2; i++) {
    const dot = document.getElementById("dot" + i);
    if (!dot) continue;
    dot.classList.remove("active", "completed");
    if (i - 1 === index) dot.classList.add("active");
    else if (i - 1 < index) dot.classList.add("completed");
  }
  currentStep = index;
}

// ---------------------------------------------------------------------------
// Google OAuth Sign-In
// ---------------------------------------------------------------------------

async function signInWithGoogle() {
  const loadingState = document.getElementById("loadingState");
  const authError = document.getElementById("authError");

  // Hide all buttons, show loading
  document.getElementById("googleSignInBtn").style.display = "none";
  document.getElementById("microsoftSignInBtn").style.display = "none";
  document.getElementById("appleSignInBtn").style.display = "none";
  loadingState.classList.add("visible");
  authError.classList.remove("visible");

  try {
    const token = await new Promise((resolve, reject) => {
      chrome.identity.getAuthToken({ interactive: true }, (token) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else {
          resolve(token);
        }
      });
    });

    if (!token) {
      throw new Error("Failed to get Google access token");
    }

    console.log("[Mystes] Got Google access token");

    const serverUrl = DEFAULT_SERVER_URL;
    const response = await fetch(`${serverUrl}/api/v1/auth/google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: token }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Server returned ${response.status}`);
    }

    const result = await response.json();
    console.log("[Mystes] Google OAuth success:", result.userName);

    await handleOAuthSuccess(result, serverUrl);
  } catch (error) {
    console.error("[Mystes] Google sign-in error:", error);
    showAuthButtons();
    loadingState.classList.remove("visible");
    authError.textContent = error.message;
    authError.classList.add("visible");
  }
}

// ---------------------------------------------------------------------------
// Microsoft OAuth Sign-In (Build #83)
// ---------------------------------------------------------------------------

async function signInWithMicrosoft() {
  const msBtn = document.getElementById("microsoftSignInBtn");
  const loadingState = document.getElementById("loadingState");
  const authError = document.getElementById("authError");

  msBtn.style.display = "none";
  document.getElementById("googleSignInBtn").style.display = "none";
  document.getElementById("appleSignInBtn").style.display = "none";
  loadingState.classList.add("visible");
  authError.classList.remove("visible");

  try {
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
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(response);
          }
        }
      );
    });

    // Extract access_token from fragment
    const fragment = new URL(responseUrl).hash.substring(1);
    const params = new URLSearchParams(fragment);
    const accessToken = params.get("access_token");

    if (!accessToken) {
      throw new Error("No access token received from Microsoft");
    }

    console.log("[Mystes] Got Microsoft access token");

    // Exchange with Mystes backend
    const serverUrl = DEFAULT_SERVER_URL;
    const response = await fetch(`${serverUrl}/api/v1/auth/microsoft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Server returned ${response.status}`);
    }

    const result = await response.json();
    console.log("[Mystes] Microsoft OAuth success:", result.userName);

    await handleOAuthSuccess(result, serverUrl);
  } catch (error) {
    console.error("[Mystes] Microsoft sign-in error:", error);
    showAuthButtons();
    loadingState.classList.remove("visible");
    authError.textContent = error.message;
    authError.classList.add("visible");
  }
}

// ---------------------------------------------------------------------------
// Apple Sign-In (Build #83)
// ---------------------------------------------------------------------------

async function signInWithApple() {
  const appleBtn = document.getElementById("appleSignInBtn");
  const loadingState = document.getElementById("loadingState");
  const authError = document.getElementById("authError");

  appleBtn.style.display = "none";
  document.getElementById("googleSignInBtn").style.display = "none";
  document.getElementById("microsoftSignInBtn").style.display = "none";
  loadingState.classList.add("visible");
  authError.classList.remove("visible");

  try {
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
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(response);
          }
        }
      );
    });

    // Extract id_token from fragment
    const fragment = new URL(responseUrl).hash.substring(1);
    const params = new URLSearchParams(fragment);
    const idToken = params.get("id_token");

    if (!idToken) {
      throw new Error("No ID token received from Apple");
    }

    console.log("[Mystes] Got Apple id_token");

    // Exchange with Mystes backend
    const serverUrl = DEFAULT_SERVER_URL;
    const response = await fetch(`${serverUrl}/api/v1/auth/apple`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: idToken }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Server returned ${response.status}`);
    }

    const result = await response.json();
    console.log("[Mystes] Apple OAuth success:", result.userName);

    await handleOAuthSuccess(result, serverUrl);
  } catch (error) {
    console.error("[Mystes] Apple sign-in error:", error);
    showAuthButtons();
    loadingState.classList.remove("visible");
    authError.textContent = error.message;
    authError.classList.add("visible");
  }
}

// ---------------------------------------------------------------------------
// Shared OAuth success handler (Build #83)
// ---------------------------------------------------------------------------

function showAuthButtons() {
  document.getElementById("googleSignInBtn").style.display = "flex";
  document.getElementById("microsoftSignInBtn").style.display = "flex";
  document.getElementById("appleSignInBtn").style.display = "flex";
}

async function handleOAuthSuccess(result, serverUrl) {
  authCredentials = {
    serverUrl: result.serverUrl || serverUrl,
    helperToken: result.helperToken,
    nodeId: result.nodeId,
    userName: result.userName,
    userEmail: result.userEmail,
  };

  await chrome.storage.sync.set({
    serverUrl: authCredentials.serverUrl,
    helperToken: authCredentials.helperToken,
    userName: authCredentials.userName,
    userEmail: authCredentials.userEmail,
  });

  // Pre-fill consent toggles if returning user
  if (result.consentProfile) {
    const p = result.consentProfile;
    const mapping = {
      toggle_search_queries: p.consent_search_queries,
      toggle_price_observations: p.consent_price_observations,
      toggle_ad_impressions: p.consent_ad_impressions,
      toggle_social_signals: p.consent_social_signals,
      toggle_browsing_data: p.consent_browsing_data,
      toggle_business_data: p.consent_business_data,
    };
    for (const [id, val] of Object.entries(mapping)) {
      const el = document.getElementById(id);
      if (el && val) el.checked = true;
    }
    updateEarningsPreview();
  }

  showStep(1);
}

// ---------------------------------------------------------------------------
// Manual Token Auth (Fallback)
// ---------------------------------------------------------------------------

async function signInWithManualToken() {
  const serverUrl = document.getElementById("serverUrl").value.trim();
  const helperToken = document.getElementById("helperToken").value.trim();
  const authError = document.getElementById("authError");

  if (!serverUrl || !helperToken) {
    authError.textContent = "Please enter both server URL and helper token.";
    authError.classList.add("visible");
    return;
  }

  authError.classList.remove("visible");

  try {
    const response = await fetch(`${serverUrl}/api/v1/node/auth`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ helper_token: helperToken }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || "Invalid token or server URL");
    }

    const result = await response.json();

    authCredentials = {
      serverUrl,
      helperToken,
      nodeId: result.node_id,
      userName: "Node Operator",
      userEmail: "",
    };

    await chrome.storage.sync.set({ serverUrl, helperToken });
    showStep(1);
  } catch (error) {
    console.error("[Mystes] Manual auth error:", error);
    authError.textContent = error.message;
    authError.classList.add("visible");
  }
}

// ---------------------------------------------------------------------------
// Consent toggles + earnings preview
// ---------------------------------------------------------------------------

const CATEGORIES = [
  { id: "toggle_search_queries", key: "search_queries", pts: 5 },
  { id: "toggle_price_observations", key: "price_observations", pts: 6 },
  { id: "toggle_ad_impressions", key: "ad_impressions", pts: 8 },
  { id: "toggle_social_signals", key: "social_signals", pts: 7 },
  { id: "toggle_browsing_data", key: "browsing_data", pts: 4 },
  { id: "toggle_business_data", key: "business_data", pts: 10 },
];

const BASE_RATE_PER_PT = 0.002;

function updateEarningsPreview() {
  let totalPts = 0;
  CATEGORIES.forEach((cat) => {
    const el = document.getElementById(cat.id);
    if (el && el.checked) totalPts += cat.pts;

    const card = el ? el.closest(".consent-card") : null;
    if (card) card.classList.toggle("enabled", el.checked);
  });

  const dailyEstimate = totalPts * BASE_RATE_PER_PT;
  const preview = document.getElementById("earningsPreview");
  if (preview) preview.textContent = "$" + dailyEstimate.toFixed(2);
}

CATEGORIES.forEach((cat) => {
  const el = document.getElementById(cat.id);
  if (el) el.addEventListener("change", updateEarningsPreview);
});

// ---------------------------------------------------------------------------
// Finish Setup
// ---------------------------------------------------------------------------

async function finishOnboarding() {
  const consentState = {
    onboarding_completed: true,
    onboarding_completed_at: new Date().toISOString(),
    location: true,
    updated_at: new Date().toISOString(),
  };

  CATEGORIES.forEach((cat) => {
    const el = document.getElementById(cat.id);
    consentState[cat.key] = el ? el.checked : false;
  });

  // Save to chrome.storage
  const storageData = { consent_state: consentState };
  if (authCredentials) {
    if (authCredentials.serverUrl) storageData.serverUrl = authCredentials.serverUrl;
    if (authCredentials.helperToken) storageData.helperToken = authCredentials.helperToken;
  }

  chrome.storage.sync.set(storageData);
  chrome.storage.local.set({ consent_state: consentState });

  // Notify background.js
  chrome.runtime.sendMessage({
    type: "consent_updated",
    consent_state: consentState,
  });

  // Push consent to backend if we have credentials
  if (authCredentials && authCredentials.helperToken) {
    try {
      const updates = {};
      CATEGORIES.forEach((cat) => {
        updates["consent_" + cat.key] = consentState[cat.key] || false;
      });

      await fetch(authCredentials.serverUrl + "/api/v1/node/consent", {
        method: "PUT",
        headers: {
          Authorization: "Bearer " + authCredentials.helperToken,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(updates),
      });
    } catch (e) {
      console.log("[Mystes] Backend consent push deferred:", e.message);
    }
  }

  // Show success with user name
  const successMsg = document.getElementById("successMessage");
  if (authCredentials && authCredentials.userName && authCredentials.userName !== "Node Operator") {
    successMsg.innerHTML =
      `Welcome, <strong>${authCredentials.userName}</strong>! Mystes Node is ready.<br>` +
      `You can adjust your data sharing preferences anytime from settings.`;
  }

  showStep(2);
}

// ---------------------------------------------------------------------------
// Event Listeners
// ---------------------------------------------------------------------------

document.getElementById("googleSignInBtn").addEventListener("click", signInWithGoogle);
document.getElementById("microsoftSignInBtn").addEventListener("click", signInWithMicrosoft);
document.getElementById("appleSignInBtn").addEventListener("click", signInWithApple);

document.getElementById("toggleManual").addEventListener("click", () => {
  document.getElementById("manualAuth").classList.toggle("visible");
});

document.getElementById("manualContinue").addEventListener("click", signInWithManualToken);
document.getElementById("backToStep1").addEventListener("click", () => showStep(0));
document.getElementById("finishSetup").addEventListener("click", finishOnboarding);
document.getElementById("closeSetup").addEventListener("click", () => window.close());

// ---------------------------------------------------------------------------
// Initialize — check for existing credentials
// ---------------------------------------------------------------------------

chrome.storage.sync.get(["serverUrl", "helperToken"], (data) => {
  if (data.serverUrl) document.getElementById("serverUrl").value = data.serverUrl;
  if (data.serverUrl && data.helperToken) {
    authCredentials = {
      serverUrl: data.serverUrl,
      helperToken: data.helperToken,
      nodeId: null,
      userName: null,
      userEmail: null,
    };
  }
});

console.log("[Mystes] Onboarding wizard loaded (Build #83)");
