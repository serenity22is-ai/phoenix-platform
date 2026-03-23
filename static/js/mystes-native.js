/**
 * MYSTES Native Bridge — Capacitor integration for iOS/Android.
 *
 * Detects Capacitor environment and initializes native features.
 * Completely inert on web browsers (all methods are guarded by isNative).
 *
 * Features:
 *   - Push notification registration
 *   - Deep link / universal link handling
 *   - Haptic feedback on booking confirmations
 *   - App lifecycle management (pause/resume)
 *   - Keyboard behavior (auto-hide on scroll)
 *
 * MYSTES KYRIOS LLC — Confidential.
 * Build #188
 */

(function () {
    'use strict';

    var MystesNative = {
        isNative: !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()),

        _pushToken: null,
        _initialized: false,

        // ============================================================
        // Push Notifications
        // ============================================================

        initPushNotifications: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.PushNotifications) return;

            var PushNotifications = Plugins.PushNotifications;
            var self = this;

            PushNotifications.requestPermissions().then(function (result) {
                if (result.receive === 'granted') {
                    PushNotifications.register();
                }
            });

            PushNotifications.addListener('registration', function (token) {
                self._pushToken = token.value;
                self._registerToken(token.value);
            });

            PushNotifications.addListener('registrationError', function (error) {
                console.warn('[MYSTES] Push registration error:', error);
            });

            PushNotifications.addListener('pushNotificationReceived', function (notification) {
                // App is in foreground — show in-app notification
                self._showInAppNotification(notification);
            });

            PushNotifications.addListener('pushNotificationActionPerformed', function (notification) {
                // User tapped notification — handle deep link
                var data = notification.notification.data || {};
                if (data.url) {
                    window.location.href = data.url;
                }
            });
        },

        _registerToken: function (token) {
            var platform = 'unknown';
            if (window.Capacitor.getPlatform) {
                platform = window.Capacitor.getPlatform();
            }

            fetch('/api/push/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ token: token, platform: platform }),
            }).catch(function (err) {
                console.warn('[MYSTES] Token registration failed:', err);
            });
        },

        _showInAppNotification: function (notification) {
            var banner = document.createElement('div');
            banner.style.cssText =
                'position:fixed;top:0;left:0;right:0;padding:16px 20px;' +
                'background:linear-gradient(135deg,#7c3aed,#b388ff);color:#fff;' +
                'font-family:Outfit,sans-serif;font-size:0.95rem;z-index:99999;' +
                'display:flex;justify-content:space-between;align-items:center;' +
                'box-shadow:0 4px 20px rgba(0,0,0,0.3);';

            var text = document.createElement('span');
            text.textContent = notification.title || notification.body || 'New notification';
            banner.appendChild(text);

            var dismiss = document.createElement('button');
            dismiss.textContent = '\u2715';
            dismiss.style.cssText =
                'background:none;border:none;color:#fff;font-size:1.2rem;cursor:pointer;padding:0 4px;';
            dismiss.onclick = function () { banner.remove(); };
            banner.appendChild(dismiss);

            document.body.appendChild(banner);
            setTimeout(function () { banner.remove(); }, 5000);
        },

        // ============================================================
        // Deep Links / Universal Links
        // ============================================================

        initDeepLinks: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.App) return;

            Plugins.App.addListener('appUrlOpen', function (event) {
                var url = event.url || '';

                // Handle mystes:// scheme
                if (url.indexOf('mystes://') === 0) {
                    var path = url.replace('mystes://', '/');
                    window.location.href = path;
                    return;
                }

                // Handle universal links (https://mystes.app/...)
                if (url.indexOf('mystes.app/') !== -1) {
                    var idx = url.indexOf('mystes.app/');
                    var path = url.substring(idx + 'mystes.app'.length);
                    window.location.href = path;
                    return;
                }
            });
        },

        // ============================================================
        // Haptic Feedback
        // ============================================================

        hapticConfirmation: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.Haptics) return;

            Plugins.Haptics.notification({ type: 'SUCCESS' });
        },

        hapticLight: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.Haptics) return;

            Plugins.Haptics.impact({ style: 'LIGHT' });
        },

        // ============================================================
        // App Lifecycle
        // ============================================================

        initLifecycle: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.App) return;

            Plugins.App.addListener('appStateChange', function (state) {
                if (!state.isActive) {
                    // App going to background — save any draft state
                    try {
                        var input = document.querySelector('textarea:focus, input:focus');
                        if (input && input.value) {
                            sessionStorage.setItem('mystes_draft', input.value);
                            sessionStorage.setItem('mystes_draft_id', input.id || '');
                        }
                    } catch (e) { /* ignore */ }
                } else {
                    // App resuming — restore draft if exists
                    try {
                        var draft = sessionStorage.getItem('mystes_draft');
                        var draftId = sessionStorage.getItem('mystes_draft_id');
                        if (draft && draftId) {
                            var el = document.getElementById(draftId);
                            if (el && !el.value) {
                                el.value = draft;
                            }
                            sessionStorage.removeItem('mystes_draft');
                            sessionStorage.removeItem('mystes_draft_id');
                        }
                    } catch (e) { /* ignore */ }
                }
            });
        },

        // ============================================================
        // Keyboard Management
        // ============================================================

        initKeyboard: function () {
            if (!this.isNative) return;

            var Plugins = window.Capacitor.Plugins;
            if (!Plugins || !Plugins.Keyboard) return;

            // Hide keyboard when scrolling
            var scrollTimeout = null;
            document.addEventListener('scroll', function () {
                if (scrollTimeout) clearTimeout(scrollTimeout);
                scrollTimeout = setTimeout(function () {
                    var active = document.activeElement;
                    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
                        // Don't hide if user is actively typing
                        return;
                    }
                    Plugins.Keyboard.hide();
                }, 300);
            }, { passive: true });
        },

        // ============================================================
        // Biometric Auth (stub — requires @capgo/capacitor-native-biometric)
        // ============================================================

        checkBiometricAuth: function () {
            return Promise.resolve({ available: false, reason: 'Plugin not installed' });
        },

        // ============================================================
        // Master Initializer
        // ============================================================

        init: function () {
            if (this._initialized) return;
            this._initialized = true;

            if (!this.isNative) {
                return;
            }

            console.log('[MYSTES] Native platform detected:', window.Capacitor.getPlatform());

            this.initPushNotifications();
            this.initDeepLinks();
            this.initLifecycle();
            this.initKeyboard();
        },
    };

    // Expose globally
    window.MystesNative = MystesNative;

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            MystesNative.init();
        });
    } else {
        MystesNative.init();
    }
})();
