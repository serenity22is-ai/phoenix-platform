/**
 * PHOENIX Capacitor Node Bridge (Build #91)
 *
 * Platform bridge that handles app foreground/background transitions
 * and keeps the node client alive across app lifecycle states.
 *
 * - Android: Starts foreground service with persistent notification
 * - iOS: Uses BackgroundTask for 30s flush + schedules periodic heartbeat
 * - Web: Falls through to standard setInterval behavior (no special handling)
 *
 * Requires:
 *   - phoenix-node-client.js (PhoenixNodeClient)
 *   - phoenix-node-capture.js (PhoenixNodeCapture)
 *   - @capacitor/app (App plugin)
 *   - @capawesome-team/capacitor-background-task (optional, for background)
 *   - @capawesome-team/capacitor-android-foreground-service (optional, Android)
 *
 * Usage:
 *   const bridge = new PhoenixNodeBridge({
 *     serverUrl: 'https://phoenix.example.com',
 *     helperToken: 'abc123',
 *     consent: { search_queries: true, price_observations: true, ... }
 *   });
 *   await bridge.initialize();
 */

(function (root) {
  "use strict";

  // -------------------------------------------------------------------------
  // Platform detection
  // -------------------------------------------------------------------------

  function detectPlatform() {
    // Capacitor provides Capacitor.getPlatform()
    if (typeof Capacitor !== "undefined" && Capacitor.getPlatform) {
      return Capacitor.getPlatform(); // 'android', 'ios', 'web'
    }
    // Fallback heuristic
    const ua = navigator.userAgent || "";
    if (/android/i.test(ua)) return "android";
    if (/iPad|iPhone|iPod/.test(ua)) return "ios";
    return "web";
  }

  // -------------------------------------------------------------------------
  // PhoenixNodeBridge
  // -------------------------------------------------------------------------

  class PhoenixNodeBridge {
    /**
     * @param {object} config
     * @param {string} config.serverUrl     Phoenix backend base URL
     * @param {string} config.helperToken   User's helper_token
     * @param {object} [config.consent]     Consent flags for data capture
     * @param {function} [config.onStatusChange]  Callback for status updates
     * @param {function} [config.onEarnings]      Callback for earnings events
     */
    constructor(config) {
      this.serverUrl = config.serverUrl;
      this.helperToken = config.helperToken;
      this.consent = config.consent || {};
      this.platform = detectPlatform();

      // Node type for heartbeat identification
      const nodeTypeMap = { android: "android", ios: "ios", web: "web" };
      const nodeType = nodeTypeMap[this.platform] || "web";

      // Create node client
      this.nodeClient = new root.PhoenixNodeClient(
        this.serverUrl,
        this.helperToken,
        { nodeType }
      );

      // Create capture module
      this.capture = new root.PhoenixNodeCapture(this.nodeClient, {
        consent: this.consent,
      });

      // Wire callbacks
      if (config.onStatusChange) {
        this.nodeClient.onStatusChange = config.onStatusChange;
      }
      if (config.onEarnings) {
        this.nodeClient.onEarnings = config.onEarnings;
      }

      this._foregroundServiceRunning = false;
      this._initialized = false;
    }

    /**
     * Initialize the bridge: start the node client, capture module,
     * and register lifecycle listeners.
     */
    async initialize() {
      if (this._initialized) return;
      this._initialized = true;

      console.log(`[PhoenixBridge] Initializing on platform: ${this.platform}`);

      // Start node client
      await this.nodeClient.start();

      // Start WebView capture
      this.capture.start();

      // Register app lifecycle listeners
      await this._registerLifecycleListeners();

      // Platform-specific setup
      if (this.platform === "android") {
        await this._setupAndroidForegroundService();
      }

      console.log("[PhoenixBridge] Initialized — node active");
    }

    /**
     * Shut down the bridge cleanly.
     */
    async shutdown() {
      console.log("[PhoenixBridge] Shutting down...");

      this.capture.stop();
      await this.nodeClient.stop();

      if (this.platform === "android" && this._foregroundServiceRunning) {
        await this._stopAndroidForegroundService();
      }

      this._initialized = false;
    }

    /**
     * Update consent flags (call when user changes settings).
     */
    updateConsent(consent) {
      this.consent = consent;
      this.capture.updateConsent(consent);
    }

    /**
     * Get current node status.
     */
    getStatus() {
      return this.nodeClient.getStatus();
    }

    // -----------------------------------------------------------------------
    // App lifecycle listeners
    // -----------------------------------------------------------------------

    async _registerLifecycleListeners() {
      // Try to import Capacitor App plugin
      let App = null;
      try {
        if (typeof Capacitor !== "undefined" && Capacitor.Plugins && Capacitor.Plugins.App) {
          App = Capacitor.Plugins.App;
        }
      } catch (e) {
        // Not available
      }

      if (!App) {
        console.log("[PhoenixBridge] Capacitor App plugin not available — running in web mode");
        // Web fallback: listen for visibilitychange
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "hidden") {
            this._onBackground();
          } else {
            this._onForeground();
          }
        });
        return;
      }

      // Capacitor app state change
      App.addListener("appStateChange", (state) => {
        if (state.isActive) {
          this._onForeground();
        } else {
          this._onBackground();
        }
      });
    }

    _onForeground() {
      console.log("[PhoenixBridge] App foregrounded");
      // Ensure loops are running (they continue via setInterval even if backgrounded,
      // but on some platforms they may be throttled)
      if (!this.nodeClient._running) {
        this.nodeClient.start();
        this.capture.start();
      }
    }

    _onBackground() {
      console.log("[PhoenixBridge] App backgrounded");

      if (this.platform === "ios") {
        this._handleIOSBackground();
      }
      // Android: foreground service keeps everything alive, nothing special needed
      // Web: setIntervals continue at reduced rate, acceptable
    }

    // -----------------------------------------------------------------------
    // Android foreground service
    // -----------------------------------------------------------------------

    async _setupAndroidForegroundService() {
      let ForegroundService = null;
      try {
        if (typeof Capacitor !== "undefined" && Capacitor.Plugins) {
          ForegroundService = Capacitor.Plugins.ForegroundService;
        }
      } catch (e) {
        // Plugin not installed
      }

      if (!ForegroundService) {
        console.log("[PhoenixBridge] Android ForegroundService plugin not available");
        return;
      }

      try {
        await ForegroundService.startForegroundService({
          id: 9001,
          title: "Phoenix Node Active",
          body: "Earning rewards — your node is contributing to the network",
          smallIcon: "ic_notification",
          buttons: [
            {
              title: "Stop",
              id: "stop_node",
            },
          ],
        });
        this._foregroundServiceRunning = true;
        console.log("[PhoenixBridge] Android foreground service started");

        // Listen for button clicks
        ForegroundService.addListener("buttonClicked", async (data) => {
          if (data.buttonId === "stop_node") {
            await this.shutdown();
          }
        });
      } catch (err) {
        console.warn("[PhoenixBridge] Failed to start foreground service:", err.message);
      }
    }

    async _stopAndroidForegroundService() {
      try {
        const ForegroundService = Capacitor.Plugins.ForegroundService;
        if (ForegroundService) {
          await ForegroundService.stopForegroundService();
          this._foregroundServiceRunning = false;
          console.log("[PhoenixBridge] Android foreground service stopped");
        }
      } catch (err) {
        console.warn("[PhoenixBridge] Failed to stop foreground service:", err.message);
      }
    }

    // -----------------------------------------------------------------------
    // iOS background handling
    // -----------------------------------------------------------------------

    _handleIOSBackground() {
      // Use Capacitor BackgroundTask plugin for the ~30s window iOS provides
      let BackgroundTask = null;
      try {
        if (typeof Capacitor !== "undefined" && Capacitor.Plugins) {
          BackgroundTask = Capacitor.Plugins.BackgroundTask;
        }
      } catch (e) {
        // Not available
      }

      if (!BackgroundTask) {
        console.log("[PhoenixBridge] iOS BackgroundTask plugin not available");
        return;
      }

      // Request background time
      const taskId = BackgroundTask.beforeExit(async () => {
        console.log("[PhoenixBridge] iOS background task started");

        try {
          // Use the ~30s window to:
          // 1. Send a heartbeat
          await this.nodeClient._sendHeartbeat();

          // 2. Flush any buffered events
          await this.nodeClient._flushBuffer();

          console.log("[PhoenixBridge] iOS background task completed");
        } catch (err) {
          console.warn("[PhoenixBridge] iOS background task error:", err.message);
        }

        // Signal task completion
        BackgroundTask.finish({ taskId });
      });
    }
  }

  // -------------------------------------------------------------------------
  // Auto-initialization helper
  // -------------------------------------------------------------------------

  /**
   * Auto-initialize the Phoenix node from page context.
   * Call this from the main app template after scripts are loaded.
   *
   * Looks for window.__PHOENIX_NODE_CONFIG__ set by the Flask template:
   * {
   *   serverUrl: 'https://phoenix.example.com',
   *   helperToken: 'abc123...',
   *   consent: { search_queries: true, price_observations: true, ... }
   * }
   */
  async function autoInitPhoenixNode() {
    const config = root.__PHOENIX_NODE_CONFIG__;
    if (!config || !config.helperToken) {
      console.log("[PhoenixBridge] No node config found — skipping auto-init");
      return null;
    }

    const bridge = new PhoenixNodeBridge(config);
    await bridge.initialize();

    // Store globally for debugging / status checks
    root.__PHOENIX_NODE_BRIDGE__ = bridge;

    return bridge;
  }

  // -------------------------------------------------------------------------
  // Export
  // -------------------------------------------------------------------------

  root.PhoenixNodeBridge = PhoenixNodeBridge;
  root.autoInitPhoenixNode = autoInitPhoenixNode;

})(typeof window !== "undefined" ? window : globalThis);
