// Mystes Extension Popup (Build #81)
(async function() {
  const LOCAL_URL = "http://localhost:19750";

  const statusDot = document.getElementById("statusDot");
  const earnings = document.getElementById("earnings");
  const nodeId = document.getElementById("nodeId");
  const eventsCaptured = document.getElementById("eventsCaptured");
  const eventsSent = document.getElementById("eventsSent");
  const uptime = document.getElementById("uptime");
  const status = document.getElementById("status");
  const setupBanner = document.getElementById("setupBanner");
  const consentBadges = document.getElementById("consentBadges");

  function formatUptime(seconds) {
    if (!seconds) return "\u2014";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  // ---------------------------------------------------------------------------
  // Consent state display
  // ---------------------------------------------------------------------------

  const CATEGORY_LABELS = {
    search_queries: "Search",
    price_observations: "Prices",
    ad_impressions: "Ads",
    social_signals: "Social",
    browsing_data: "Browsing",
    business_data: "Business"
  };

  // Display user info if available
  chrome.storage.sync.get(["userName", "userEmail"], (data) => {
    if (data.userName || data.userEmail) {
      const userInfo = document.getElementById("userInfo");
      const userNameEl = document.getElementById("userNamePopup");
      const userEmailEl = document.getElementById("userEmailPopup");
      const userInitialEl = document.getElementById("userInitial");

      if (data.userName) {
        userNameEl.textContent = data.userName;
        userInitialEl.textContent = data.userName.charAt(0).toUpperCase();
      }
      if (data.userEmail) {
        userEmailEl.textContent = data.userEmail;
      }
      userInfo.style.display = "block";
    }
  });

  chrome.storage.local.get(["consent_state"], (data) => {
    const consent = data.consent_state;

    if (!consent || !consent.onboarding_completed) {
      // Show setup banner
      setupBanner.classList.add("visible");
      statusDot.className = "status-dot setup";
      status.textContent = "Setup Required";
      return;
    }

    // Show consent badges
    consentBadges.classList.add("visible");
    for (const [key, label] of Object.entries(CATEGORY_LABELS)) {
      const badge = document.createElement("span");
      badge.className = `consent-badge ${consent[key] ? "on" : "off"}`;
      badge.textContent = label;
      consentBadges.appendChild(badge);
    }
  });

  // ---------------------------------------------------------------------------
  // Service status + stats
  // ---------------------------------------------------------------------------

  try {
    // Get local service status
    const res = await fetch(`${LOCAL_URL}/status`);
    const data = await res.json();

    statusDot.className = `status-dot ${data.connected ? "connected" : "disconnected"}`;
    status.textContent = data.connected ? "Connected" : "Disconnected";
    nodeId.textContent = data.node_id || "\u2014";
    uptime.textContent = formatUptime(data.uptime_s);
    eventsSent.textContent = data.events_sent || 0;
    earnings.textContent = `$${(data.earnings_today || 0).toFixed(4)}`;

    // Get extension stats
    chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
      if (response) {
        eventsCaptured.textContent = response.stats?.captured || 0;
      }
    });
  } catch (e) {
    statusDot.className = "status-dot disconnected";
    status.textContent = "Service Not Running";
    nodeId.textContent = "\u2014";
  }
})();
