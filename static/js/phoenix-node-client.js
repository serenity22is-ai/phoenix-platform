/**
 * PHOENIX Mobile Node Client (Build #91)
 *
 * JavaScript port of node_service.py core logic for Capacitor WebView.
 * Talks directly to the Phoenix backend REST API (not localhost:19750).
 * Manages authentication, heartbeat, event buffering, and batch upload.
 *
 * Usage:
 *   const client = new PhoenixNodeClient(serverUrl, helperToken);
 *   await client.start();
 *   client.captureEvent({ event_type: 'page_visit', url: '...' });
 *   // ... later
 *   await client.stop();
 */

(function (root) {
  "use strict";

  // -------------------------------------------------------------------------
  // Constants (mirrors node_service.py lines 40-49)
  // -------------------------------------------------------------------------

  const VERSION = "1.0.0";
  const HEARTBEAT_INTERVAL_MS = 60000;      // 60s
  const BATCH_UPLOAD_INTERVAL_MS = 30000;    // 30s
  const CONFIG_REFRESH_INTERVAL_MS = 300000; // 5 min
  const MAX_BUFFER_SIZE = 2000;
  const MAX_BATCH_SIZE = 500;
  const RECONNECT_BASE_DELAY_MS = 1000;
  const RECONNECT_MAX_DELAY_MS = 60000;

  // -------------------------------------------------------------------------
  // PhoenixNodeClient
  // -------------------------------------------------------------------------

  class PhoenixNodeClient {
    /**
     * @param {string} serverUrl  Phoenix backend base URL
     * @param {string} helperToken  User's helper_token for X-Helper-Token auth
     * @param {object} [options]
     * @param {string} [options.nodeType='web']  'android' | 'ios' | 'web' | 'desktop'
     */
    constructor(serverUrl, helperToken, options = {}) {
      this.serverUrl = serverUrl.replace(/\/+$/, "");
      this.helperToken = helperToken;
      this.nodeType = options.nodeType || "web";

      // State
      this.nodeId = null;
      this.sessionId = null;
      this._eventBuffer = [];
      this._running = false;
      this._authenticated = false;
      this._connected = false;
      this._startTime = null;

      // Counters
      this._eventsCaptured = 0;
      this._eventsSent = 0;
      this._earningsToday = 0.0;
      this._uploadErrors = 0;

      // Config (from server)
      this._config = null;

      // Location
      this._lastLocation = null;

      // Reconnect
      this._reconnectDelay = RECONNECT_BASE_DELAY_MS;
      this._reconnecting = false;

      // Interval IDs
      this._heartbeatTimer = null;
      this._batchUploadTimer = null;
      this._configRefreshTimer = null;

      // Callbacks
      this.onStatusChange = null;  // (status) => {}
      this.onEarnings = null;      // (value_usd) => {}
    }

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------

    async start() {
      if (this._running) return;
      this._running = true;
      this._startTime = Date.now();
      console.log("[PhoenixNode] Starting node client, server:", this.serverUrl);

      const authenticated = await this._authenticate();
      if (!authenticated) {
        console.warn("[PhoenixNode] Auth failed — will retry in background");
        this._scheduleReconnect();
      } else {
        await this._startSession();
        await this._fetchConfig();
      }

      this._startLoops();
      this._emitStatus();
    }

    async stop() {
      if (!this._running) return;
      console.log("[PhoenixNode] Stopping node client...");
      this._running = false;
      this._stopLoops();

      // Flush remaining events
      if (this._eventBuffer.length > 0) {
        await this._flushBuffer();
      }

      // End session
      if (this._connected && this.sessionId) {
        await this._endSession();
      }

      this._emitStatus();
      this._logSummary();
    }

    // -----------------------------------------------------------------------
    // Backend API calls
    // -----------------------------------------------------------------------

    async _apiCall(method, path, body = null) {
      const url = `${this.serverUrl}${path}`;
      const headers = {
        "X-Helper-Token": this.helperToken,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": `PhoenixNodeClient/${VERSION} (${this.nodeType})`,
      };

      const opts = { method, headers };
      if (body) {
        opts.body = JSON.stringify(body);
      }

      // 10s timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      opts.signal = controller.signal;

      try {
        const resp = await fetch(url, opts);
        clearTimeout(timeoutId);
        return resp;
      } catch (err) {
        clearTimeout(timeoutId);
        throw err;
      }
    }

    async _authenticate() {
      try {
        const resp = await this._apiCall("POST", "/api/v1/node/auth", {
          helper_token: this.helperToken,
        });
        if (resp.ok) {
          const data = await resp.json();
          this.nodeId = data.node_id;
          this._authenticated = true;
          this._reconnectDelay = RECONNECT_BASE_DELAY_MS;
          console.log("[PhoenixNode] Authenticated — node_id:", this.nodeId);
          return true;
        } else {
          console.warn("[PhoenixNode] Auth failed:", resp.status);
          return false;
        }
      } catch (err) {
        console.warn("[PhoenixNode] Auth error:", err.message);
        return false;
      }
    }

    async _startSession() {
      if (!this._authenticated || !this.nodeId) return;
      try {
        const resp = await this._apiCall("POST", "/api/v1/node/session/start", {
          node_id: this.nodeId,
        });
        if (resp.ok) {
          const data = await resp.json();
          this.sessionId = data.session_id;
          this._connected = true;
          console.log("[PhoenixNode] Session started:", this.sessionId);
        } else {
          console.warn("[PhoenixNode] Session start failed:", resp.status);
        }
      } catch (err) {
        console.warn("[PhoenixNode] Session start error:", err.message);
      }
    }

    async _endSession() {
      try {
        await this._apiCall("POST", "/api/v1/node/session/end", {
          node_id: this.nodeId,
          session_id: this.sessionId,
        });
        console.log("[PhoenixNode] Session ended");
      } catch (err) {
        console.warn("[PhoenixNode] Session end error:", err.message);
      } finally {
        this.sessionId = null;
        this._connected = false;
      }
    }

    async _sendHeartbeat() {
      if (!this._running || !this._authenticated) return;
      try {
        const uptimeS = Math.floor((Date.now() - this._startTime) / 1000);
        const payload = {
          node_id: this.nodeId,
          uptime_s: uptimeS,
          events_buffered: this._eventBuffer.length,
          version: VERSION,
          node_type: this.nodeType,
        };
        if (this._lastLocation) {
          payload.location = this._lastLocation;
        }

        const resp = await this._apiCall("POST", "/api/v1/node/heartbeat", payload);
        if (resp.ok) {
          this._reconnectDelay = RECONNECT_BASE_DELAY_MS;
        } else if (resp.status === 401 || resp.status === 403) {
          this._authenticated = false;
          this._connected = false;
          this._scheduleReconnect();
        }
      } catch (err) {
        console.warn("[PhoenixNode] Heartbeat error:", err.message);
        if (!this._connected) {
          this._scheduleReconnect();
        }
      }
    }

    async _flushBuffer() {
      if (this._eventBuffer.length === 0) return;
      if (!this._authenticated || !this._connected) return;

      // Drain up to MAX_BATCH_SIZE
      const batch = this._eventBuffer.splice(0, MAX_BATCH_SIZE);

      try {
        const resp = await this._apiCall("POST", "/api/v1/node/data/ingest", {
          node_id: this.nodeId,
          session_id: this.sessionId,
          events: batch,
        });

        if (resp.ok) {
          const data = await resp.json();
          const accepted = data.accepted || batch.length;
          const valueUsd = data.value_usd || 0.0;
          this._eventsSent += accepted;
          this._earningsToday += valueUsd;
          console.log(
            `[PhoenixNode] Uploaded ${batch.length} events (accepted=${accepted}, value=$${valueUsd.toFixed(6)})`
          );
          if (this.onEarnings && valueUsd > 0) {
            this.onEarnings(valueUsd);
          }
        } else {
          console.warn("[PhoenixNode] Upload failed:", resp.status);
          this._uploadErrors++;
          // Put events back at front
          this._eventBuffer.unshift(...batch);
          this._trimBuffer();
        }
      } catch (err) {
        console.warn("[PhoenixNode] Upload error:", err.message);
        this._uploadErrors++;
        this._eventBuffer.unshift(...batch);
        this._trimBuffer();
      }
    }

    async _fetchConfig() {
      try {
        const resp = await this._apiCall("GET", "/api/v1/node/config");
        if (resp.ok) {
          this._config = await resp.json();
        }
      } catch (err) {
        console.debug("[PhoenixNode] Config fetch error:", err.message);
      }
    }

    // -----------------------------------------------------------------------
    // Event capture
    // -----------------------------------------------------------------------

    captureEvent(eventData) {
      if (!this._running) return;
      if (!eventData || typeof eventData !== "object") return;

      // Stamp with capture time
      eventData.captured_at = eventData.captured_at || new Date().toISOString();

      this._eventBuffer.push(eventData);
      this._eventsCaptured++;

      // Auto-flush if buffer full
      if (this._eventBuffer.length >= MAX_BUFFER_SIZE) {
        this._flushBuffer();
      }
    }

    // -----------------------------------------------------------------------
    // Location update
    // -----------------------------------------------------------------------

    updateLocation(lat, lon, accuracyM, source) {
      this._lastLocation = {
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        accuracy_m: accuracyM || null,
        source: source || "gps",
      };
    }

    // -----------------------------------------------------------------------
    // Background loops
    // -----------------------------------------------------------------------

    _startLoops() {
      this._heartbeatTimer = setInterval(
        () => this._sendHeartbeat(),
        HEARTBEAT_INTERVAL_MS
      );
      this._batchUploadTimer = setInterval(
        () => this._flushBuffer(),
        BATCH_UPLOAD_INTERVAL_MS
      );
      this._configRefreshTimer = setInterval(
        () => this._fetchConfig(),
        CONFIG_REFRESH_INTERVAL_MS
      );
    }

    _stopLoops() {
      if (this._heartbeatTimer) clearInterval(this._heartbeatTimer);
      if (this._batchUploadTimer) clearInterval(this._batchUploadTimer);
      if (this._configRefreshTimer) clearInterval(this._configRefreshTimer);
      this._heartbeatTimer = null;
      this._batchUploadTimer = null;
      this._configRefreshTimer = null;
    }

    // -----------------------------------------------------------------------
    // Reconnection with exponential backoff
    // -----------------------------------------------------------------------

    _scheduleReconnect() {
      if (this._reconnecting || !this._running) return;
      this._reconnecting = true;

      const attempt = async () => {
        if (!this._running) { this._reconnecting = false; return; }

        console.log(`[PhoenixNode] Reconnecting in ${this._reconnectDelay / 1000}s...`);
        await this._sleep(this._reconnectDelay);
        if (!this._running) { this._reconnecting = false; return; }

        const ok = await this._authenticate();
        if (ok) {
          await this._startSession();
          await this._fetchConfig();
          this._reconnecting = false;
          this._emitStatus();
          console.log("[PhoenixNode] Reconnected successfully");
        } else {
          this._reconnectDelay = Math.min(
            this._reconnectDelay * 2,
            RECONNECT_MAX_DELAY_MS
          );
          attempt();
        }
      };

      attempt();
    }

    // -----------------------------------------------------------------------
    // Status
    // -----------------------------------------------------------------------

    getStatus() {
      const uptimeS = this._startTime
        ? Math.floor((Date.now() - this._startTime) / 1000)
        : 0;
      return {
        running: this._running,
        connected: this._connected,
        authenticated: this._authenticated,
        node_id: this.nodeId,
        session_id: this.sessionId,
        node_type: this.nodeType,
        events_buffered: this._eventBuffer.length,
        events_captured: this._eventsCaptured,
        events_sent: this._eventsSent,
        upload_errors: this._uploadErrors,
        uptime_s: uptimeS,
        earnings_today: Math.round(this._earningsToday * 1e6) / 1e6,
        version: VERSION,
      };
    }

    _emitStatus() {
      if (this.onStatusChange) {
        this.onStatusChange(this.getStatus());
      }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    _trimBuffer() {
      if (this._eventBuffer.length > MAX_BUFFER_SIZE) {
        const dropped = this._eventBuffer.length - MAX_BUFFER_SIZE;
        this._eventBuffer = this._eventBuffer.slice(-MAX_BUFFER_SIZE);
        console.warn(`[PhoenixNode] Buffer overflow, dropped ${dropped} oldest events`);
      }
    }

    _sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    _logSummary() {
      const status = this.getStatus();
      console.log("[PhoenixNode] === Session Summary ===");
      console.log(`  Uptime: ${Math.floor(status.uptime_s / 3600)}h ${Math.floor((status.uptime_s % 3600) / 60)}m`);
      console.log(`  Events captured: ${status.events_captured}`);
      console.log(`  Events sent: ${status.events_sent}`);
      console.log(`  Upload errors: ${status.upload_errors}`);
      console.log(`  Earnings today: $${status.earnings_today} RLUSD`);
      console.log("[PhoenixNode] ========================");
    }
  }

  // -------------------------------------------------------------------------
  // Export
  // -------------------------------------------------------------------------

  root.PhoenixNodeClient = PhoenixNodeClient;

})(typeof window !== "undefined" ? window : globalThis);
