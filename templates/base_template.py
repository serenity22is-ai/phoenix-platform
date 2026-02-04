"""
PHOENIX World-Class UI Template
Planet Earth Documentary Inspired - Adventure & Higher Calling

Features:
- Aurora/cosmic background imagery
- Phoenix silhouette logo
- Cinematic, documentary feel
- Highly readable typography
- Inspiring adventure aesthetic
"""

# Sacred Geometry SVG - Metatron's Cube with animated paths
PHOENIX_LOGO_SVG = '''
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" class="sacred-geo">
  <defs>
    <linearGradient id="geoGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="rgba(139,45,91,0.9)"/>
      <stop offset="50%" stop-color="rgba(100,60,180,0.8)"/>
      <stop offset="100%" stop-color="rgba(13,79,79,0.9)"/>
    </linearGradient>
  </defs>
  <g fill="none" stroke="currentColor" stroke-width="0.6" opacity="0.9">
    <!-- Outer circle -->
    <circle cx="50" cy="50" r="44" class="geo-ring geo-r1"/>
    <!-- 6 Flower of Life seed circles -->
    <circle cx="50" cy="6" r="22" class="geo-ring geo-r2"/>
    <circle cx="88" cy="28" r="22" class="geo-ring geo-r2"/>
    <circle cx="88" cy="72" r="22" class="geo-ring geo-r2"/>
    <circle cx="50" cy="94" r="22" class="geo-ring geo-r2"/>
    <circle cx="12" cy="72" r="22" class="geo-ring geo-r2"/>
    <circle cx="12" cy="28" r="22" class="geo-ring geo-r2"/>
    <!-- Inner hexagon vertices to center — Metatron lines -->
    <line x1="50" y1="6" x2="88" y2="28" class="geo-line"/>
    <line x1="88" y1="28" x2="88" y2="72" class="geo-line"/>
    <line x1="88" y1="72" x2="50" y2="94" class="geo-line"/>
    <line x1="50" y1="94" x2="12" y2="72" class="geo-line"/>
    <line x1="12" y1="72" x2="12" y2="28" class="geo-line"/>
    <line x1="12" y1="28" x2="50" y2="6" class="geo-line"/>
    <!-- Cross lines through center -->
    <line x1="50" y1="6" x2="50" y2="94" class="geo-line"/>
    <line x1="12" y1="28" x2="88" y2="72" class="geo-line"/>
    <line x1="88" y1="28" x2="12" y2="72" class="geo-line"/>
    <!-- Star of David inner lines -->
    <line x1="50" y1="6" x2="88" y2="72" class="geo-line geo-l2"/>
    <line x1="50" y1="6" x2="12" y2="72" class="geo-line geo-l2"/>
    <line x1="88" y1="28" x2="50" y2="94" class="geo-line geo-l2"/>
    <line x1="88" y1="28" x2="12" y2="72" class="geo-line geo-l2"/>
    <line x1="88" y1="72" x2="12" y2="28" class="geo-line geo-l2"/>
    <line x1="88" y1="72" x2="50" y2="6" class="geo-line geo-l2"/>
    <line x1="50" y1="94" x2="12" y2="28" class="geo-line geo-l2"/>
    <line x1="50" y1="94" x2="88" y2="28" class="geo-line geo-l2"/>
    <line x1="12" y1="72" x2="50" y2="6" class="geo-line geo-l2"/>
    <line x1="12" y1="28" x2="88" y2="72" class="geo-line geo-l2"/>
    <line x1="12" y1="28" x2="50" y2="94" class="geo-line geo-l2"/>
    <line x1="12" y1="72" x2="88" y2="28" class="geo-line geo-l2"/>
    <!-- Inner circle -->
    <circle cx="50" cy="50" r="22" class="geo-ring geo-r3"/>
    <!-- Center seed -->
    <circle cx="50" cy="50" r="3" class="geo-center"/>
  </g>
</svg>
'''

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} | PHOENIX</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="PHOENIX - AI-powered search engine for geographic price arbitrage. Compare flights, hotels, products, rentals and more across 195 markets. Pay with crypto. Powered by XRPL.">
    <!-- PWA Meta -->
    <meta name="theme-color" content="#ff6b35">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Phoenix">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="msapplication-TileColor" content="#0a0612">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <link rel="manifest" href="/static/manifest.json">
    <link rel="apple-touch-icon" href="/static/icons/icon-192x192.png">
    <link rel="icon" type="image/x-icon" href="/favicon.ico">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Rajdhani:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <!-- Google OAuth handled via server-side redirect, no JS library needed -->
    <style>
        /* ============================================
           PHOENIX DESIGN SYSTEM
           Planet Earth Documentary Inspired
           ============================================ */

        :root {
            /* Earth/Documentary palette */
            --deep-space: #0a0612;
            --aurora-purple: #1a0a2e;
            --aurora-magenta: #4a1942;
            --aurora-pink: #8b2d5b;
            --earth-teal: #0d4f4f;
            --earth-green: #1a5f4a;

            /* Readable text colors - HIGH CONTRAST */
            --text-bright: #ffffff;
            --text-primary: #f5f5f5;
            --text-secondary: #d8d8e0;
            --text-muted: #b8b8c8;
            --text-on-light: #1a1a2e;
            --text-on-card: #2d2d3a;

            /* Accent colors - Phoenix fire theme */
            --phoenix-glow: #ff6b35;
            --phoenix-silver: #ffc107;
            --phoenix-cyan: #ff8c00;
            --phoenix-aurora: #ff4d00;
            --success-green: #4ade80;
            --ocean-blue: #ff8c00;

            /* Card backgrounds */
            --card-dark: rgba(15, 10, 25, 0.85);
            --card-glass: rgba(255, 255, 255, 0.95);
            --card-overlay: rgba(0, 0, 0, 0.6);

            /* Spacing */
            --space-xs: 4px;
            --space-sm: 8px;
            --space-md: 16px;
            --space-lg: 24px;
            --space-xl: 32px;
            --space-2xl: 48px;
            --space-3xl: 64px;
            --space-4xl: 96px;

            /* Typography - Cinematic */
            --font-display: 'Cinzel', 'Palatino', Georgia, serif;
            --font-sans: 'Rajdhani', 'Segoe UI', sans-serif;
            --font-mono: 'SF Mono', 'Fira Code', monospace;

            /* Transitions */
            --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* Reset */
        *, *::before, *::after {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        html {
            scroll-behavior: smooth;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        body {
            font-family: var(--font-sans);
            background: var(--deep-space);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
            line-height: 1.6;
        }

        /* Selection */
        ::selection {
            background: var(--phoenix-cyan);
            color: var(--deep-space);
        }

        /* ============================================
           AURORA BACKGROUND - Cosmic Documentary Feel
           ============================================ */

        /* ============================================
           ANIMATED AURORA BACKGROUND
           Multi-layer slow-drifting aurora curtains
           ============================================ */

        .aurora-bg {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 0;
            pointer-events: none;
            background: linear-gradient(180deg,
                #050210 0%,
                #0a0612 15%,
                #0e0818 35%,
                #120a20 55%,
                #0a0612 80%,
                #050210 100%
            );
            overflow: hidden;
        }

        /* Aurora curtain layer 1 — slow drift right, magenta/purple */
        .aurora-layer-1 {
            position: fixed;
            top: -20%; left: -20%;
            width: 140%; height: 140%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.5;
            background:
                radial-gradient(ellipse 60% 50% at 25% 30%, rgba(139, 45, 91, 0.6) 0%, transparent 60%),
                radial-gradient(ellipse 50% 40% at 65% 25%, rgba(74, 25, 66, 0.5) 0%, transparent 55%),
                radial-gradient(ellipse 70% 35% at 45% 60%, rgba(196, 69, 105, 0.25) 0%, transparent 50%);
            animation: auroraDrift1 25s ease-in-out infinite;
            will-change: transform, opacity;
        }

        /* Aurora curtain layer 2 — slow drift left, teal/green */
        .aurora-layer-2 {
            position: fixed;
            top: -15%; left: -15%;
            width: 130%; height: 130%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.35;
            background:
                radial-gradient(ellipse 55% 45% at 70% 35%, rgba(13, 79, 79, 0.7) 0%, transparent 55%),
                radial-gradient(ellipse 45% 55% at 30% 50%, rgba(26, 95, 74, 0.5) 0%, transparent 50%),
                radial-gradient(ellipse 65% 30% at 55% 70%, rgba(74, 222, 128, 0.15) 0%, transparent 45%);
            animation: auroraDrift2 30s ease-in-out infinite;
            will-change: transform, opacity;
        }

        /* Aurora curtain layer 3 — vertical shimmer, cool violet/cyan */
        .aurora-layer-3 {
            position: fixed;
            top: -10%; left: -10%;
            width: 120%; height: 120%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.3;
            background:
                radial-gradient(ellipse 40% 60% at 50% 20%, rgba(100, 60, 180, 0.4) 0%, transparent 50%),
                radial-gradient(ellipse 50% 40% at 35% 45%, rgba(60, 140, 160, 0.3) 0%, transparent 45%),
                radial-gradient(ellipse 35% 50% at 70% 55%, rgba(120, 40, 140, 0.25) 0%, transparent 40%);
            animation: auroraDrift3 20s ease-in-out infinite;
            will-change: transform, opacity;
        }

        /* Aurora curtain layer 4 — deep bloom, slow pulse */
        .aurora-layer-4 {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.2;
            background:
                radial-gradient(ellipse 80% 50% at 40% 40%, rgba(139, 45, 91, 0.5) 0%, transparent 50%),
                radial-gradient(ellipse 60% 70% at 60% 60%, rgba(13, 79, 79, 0.4) 0%, transparent 45%);
            animation: auroraPulse 35s ease-in-out infinite;
            will-change: opacity;
        }

        @keyframes auroraDrift1 {
            0%   { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 0.5; }
            25%  { transform: translate(4%, -3%) scale(1.05) rotate(1deg); opacity: 0.6; }
            50%  { transform: translate(7%, 2%) scale(1.02) rotate(-0.5deg); opacity: 0.45; }
            75%  { transform: translate(2%, -1%) scale(1.07) rotate(0.5deg); opacity: 0.55; }
            100% { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 0.5; }
        }

        @keyframes auroraDrift2 {
            0%   { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 0.35; }
            25%  { transform: translate(-5%, 2%) scale(1.04) rotate(-1deg); opacity: 0.4; }
            50%  { transform: translate(-3%, -3%) scale(1.08) rotate(0.5deg); opacity: 0.3; }
            75%  { transform: translate(-6%, 1%) scale(1.02) rotate(-0.5deg); opacity: 0.45; }
            100% { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 0.35; }
        }

        @keyframes auroraDrift3 {
            0%   { transform: translate(0, 0) scale(1); opacity: 0.3; }
            33%  { transform: translate(3%, -4%) scale(1.06); opacity: 0.4; }
            66%  { transform: translate(-2%, 3%) scale(1.03); opacity: 0.25; }
            100% { transform: translate(0, 0) scale(1); opacity: 0.3; }
        }

        @keyframes auroraPulse {
            0%, 100% { opacity: 0.2; }
            30%      { opacity: 0.35; }
            60%      { opacity: 0.15; }
            80%      { opacity: 0.3; }
        }

        /* Stars — dual layer with stagger */
        .stars {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 1;
            pointer-events: none;
            background-image:
                radial-gradient(1.5px 1.5px at 20px 30px, rgba(255,255,255,0.9), transparent),
                radial-gradient(1px 1px at 40px 70px, rgba(255,255,255,0.7), transparent),
                radial-gradient(1.5px 1.5px at 90px 40px, white, transparent),
                radial-gradient(1px 1px at 160px 120px, rgba(255,255,255,0.8), transparent),
                radial-gradient(1.5px 1.5px at 230px 80px, white, transparent),
                radial-gradient(1px 1px at 300px 150px, rgba(255,255,255,0.6), transparent),
                radial-gradient(1.5px 1.5px at 350px 50px, white, transparent),
                radial-gradient(1px 1px at 420px 180px, rgba(255,255,255,0.7), transparent),
                radial-gradient(1.5px 1.5px at 500px 90px, white, transparent),
                radial-gradient(1px 1px at 580px 130px, rgba(255,255,255,0.8), transparent),
                radial-gradient(1.5px 1.5px at 650px 60px, white, transparent),
                radial-gradient(1px 1px at 720px 200px, rgba(255,255,255,0.7), transparent),
                radial-gradient(1px 1px at 780px 25px, white, transparent),
                radial-gradient(1.5px 1.5px at 110px 170px, rgba(255,255,255,0.6), transparent),
                radial-gradient(1px 1px at 440px 45px, white, transparent),
                radial-gradient(1.5px 1.5px at 680px 160px, rgba(255,255,255,0.8), transparent);
            background-size: 800px 250px;
            animation: twinkle 6s ease-in-out infinite;
        }

        .stars-2 {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 1;
            pointer-events: none;
            background-image:
                radial-gradient(1px 1px at 55px 95px, rgba(255,255,255,0.6), transparent),
                radial-gradient(1.5px 1.5px at 135px 15px, white, transparent),
                radial-gradient(1px 1px at 215px 145px, rgba(255,255,255,0.7), transparent),
                radial-gradient(1.5px 1.5px at 330px 85px, rgba(255,255,255,0.5), transparent),
                radial-gradient(1px 1px at 475px 125px, white, transparent),
                radial-gradient(1.5px 1.5px at 565px 35px, rgba(255,255,255,0.8), transparent),
                radial-gradient(1px 1px at 625px 175px, rgba(255,255,255,0.6), transparent),
                radial-gradient(1.5px 1.5px at 755px 105px, white, transparent);
            background-size: 800px 220px;
            animation: twinkle2 9s ease-in-out infinite;
        }

        @keyframes twinkle {
            0%, 100% { opacity: 0.7; }
            50%      { opacity: 1; }
        }

        @keyframes twinkle2 {
            0%, 100% { opacity: 1; }
            50%      { opacity: 0.6; }
        }

        /* Reduce animation on low-power devices */
        @media (prefers-reduced-motion: reduce) {
            .aurora-layer-1, .aurora-layer-2, .aurora-layer-3, .aurora-layer-4 { animation: none; }
            .stars, .stars-2 { animation: none; opacity: 0.8; }
        }

        /* ============================================
           NAVIGATION - Documentary Style
           ============================================ */

        .nav {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1000;
            padding: var(--space-md) var(--space-2xl);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: transparent;
            transition: all 0.4s var(--ease-out);
        }

        .nav.scrolled {
            background: rgba(10, 6, 18, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
        }

        .nav-brand {
            display: flex;
            align-items: center;
            gap: var(--space-md);
            text-decoration: none;
            color: var(--text-bright);
        }

        /* Sacred Geometry Nav Logo */
        .nav-logo {
            width: 48px;
            height: 48px;
            color: rgba(160, 120, 200, 0.85);
            filter: drop-shadow(0 0 8px rgba(139, 45, 91, 0.5))
                    drop-shadow(0 0 16px rgba(100, 60, 180, 0.3));
            transition: all 0.4s var(--ease-out);
            animation: navGeoSpin 60s linear infinite;
        }

        .nav-logo:hover {
            color: rgba(180, 150, 220, 1);
            filter: drop-shadow(0 0 12px rgba(139, 45, 91, 0.8))
                    drop-shadow(0 0 24px rgba(100, 60, 180, 0.5))
                    drop-shadow(0 0 36px rgba(13, 79, 79, 0.3));
            transform: scale(1.1);
        }

        @keyframes navGeoSpin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        .nav-wordmark {
            font-family: var(--font-display);
            font-size: 24px;
            font-weight: 600;
            letter-spacing: 6px;
            color: var(--text-bright);
            text-transform: uppercase;
        }

        .nav-links {
            display: flex;
            align-items: center;
            gap: var(--space-lg);
        }

        .nav-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 1px;
            text-transform: uppercase;
            padding: var(--space-sm) var(--space-md);
            border-radius: 6px;
            transition: all 0.3s var(--ease-out);
        }

        .nav-link:hover {
            color: var(--text-bright);
            background: rgba(255, 255, 255, 0.1);
        }

        /* Nav "More" dropdown */
        .nav-more-wrapper {
            position: relative;
        }
        .nav-more-btn {
            background: none;
            border: none;
            cursor: pointer;
            font-family: inherit;
        }
        .nav-more-menu {
            display: none;
            position: absolute;
            top: 100%;
            right: 0;
            min-width: 180px;
            background: rgba(10, 6, 18, 0.97);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: var(--space-sm) 0;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
            z-index: 1100;
        }
        .nav-more-menu.open {
            display: block;
        }
        .nav-more-link {
            display: block;
            padding: var(--space-sm) var(--space-lg);
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0.5px;
            transition: all 0.2s ease;
        }
        .nav-more-link:hover {
            color: var(--text-bright);
            background: rgba(255, 255, 255, 0.08);
        }

        .nav-cta {
            background: linear-gradient(135deg, #ff6b35, #ff8c00);
            color: #ffffff !important;
            padding: var(--space-sm) var(--space-lg) !important;
            border-radius: 6px;
            font-weight: 600;
            box-shadow: 0 4px 20px rgba(255, 107, 53, 0.4);
        }

        .nav-cta:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(255, 107, 53, 0.5);
            background: linear-gradient(135deg, #ff8c00, #ffc107) !important;
        }

        /* XRPL Trust Badge */
        .xrpl-badge {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            padding: var(--space-xs) var(--space-md);
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 100px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
            letter-spacing: 0.5px;
        }

        .xrpl-badge::before {
            content: '';
            width: 8px;
            height: 8px;
            background: var(--success-green);
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.4); }
            50% { opacity: 0.8; box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
        }

        /* ============================================
           MAIN CONTENT
           ============================================ */

        .main {
            position: relative;
            z-index: 10;
            min-height: 100vh;
            padding-top: 80px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 var(--space-2xl);
        }

        /* ============================================
           TYPOGRAPHY - Highly Readable
           ============================================ */

        .heading-display {
            font-family: var(--font-display);
            font-size: clamp(48px, 10vw, 100px);
            font-weight: 600;
            letter-spacing: 8px;
            line-height: 0.95;
            color: var(--text-bright);
            text-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
            text-transform: uppercase;
        }

        .heading-1 {
            font-family: var(--font-display);
            font-size: clamp(32px, 5vw, 56px);
            font-weight: 600;
            letter-spacing: 4px;
            line-height: 1.1;
            color: var(--text-bright);
            text-transform: uppercase;
        }

        .heading-2 {
            font-family: var(--font-display);
            font-size: clamp(24px, 4vw, 40px);
            font-weight: 500;
            letter-spacing: 3px;
            line-height: 1.2;
            color: var(--text-bright);
            text-transform: uppercase;
        }

        .heading-3 {
            font-family: var(--font-display);
            font-size: clamp(18px, 3vw, 24px);
            font-weight: 500;
            letter-spacing: 2px;
            line-height: 1.3;
            color: var(--text-bright);
            text-transform: uppercase;
        }

        .text-large {
            font-size: 20px;
            line-height: 1.7;
            color: var(--text-secondary);
        }

        .text-body {
            font-size: 16px;
            line-height: 1.7;
            color: var(--text-secondary);
        }

        .text-accent {
            color: var(--text-bright);
        }

        /* Removed gradient text for better readability */
        .text-gradient {
            color: var(--text-bright);
        }

        /* ============================================
           BUTTONS - Warm, Inviting
           ============================================ */

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: var(--space-sm);
            padding: var(--space-md) var(--space-xl);
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-decoration: none;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s var(--ease-out);
        }

        .btn-primary {
            background: linear-gradient(135deg, #ff6b35, #ff8c00);
            color: #ffffff;
            box-shadow: 0 4px 20px rgba(255, 107, 53, 0.4);
            font-weight: 700;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(255, 107, 53, 0.5);
            background: linear-gradient(135deg, #ff8c00, #ffc107);
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.1);
            color: var(--text-bright);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.15);
            border-color: rgba(255, 255, 255, 0.3);
        }

        .btn-success {
            background: linear-gradient(135deg, #22c55e, #16a34a);
            color: var(--text-bright);
            box-shadow: 0 4px 20px rgba(34, 197, 94, 0.3);
        }

        .btn-large {
            padding: var(--space-lg) var(--space-2xl);
            font-size: 16px;
        }

        /* ============================================
           CARDS - Glass with Dark Theme
           ============================================ */

        .card {
            background: var(--card-dark);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: var(--space-xl);
            margin: var(--space-lg) 0;
            transition: all 0.3s var(--ease-out);
        }

        .card:hover {
            border-color: rgba(0, 212, 255, 0.3);
            transform: translateY(-4px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
        }

        /* Light card variant - FIXED READABILITY */
        .card-light {
            background: var(--card-glass);
            border: 1px solid rgba(0, 0, 0, 0.1);
        }

        .card-light,
        .card-light * {
            color: var(--text-on-card);
        }

        .card-light h1, .card-light h2, .card-light h3, .card-light h4, .card-light strong {
            color: #1a1a2e;
        }

        .card-light p, .card-light span, .card-light label {
            color: #3d3d4a;
        }

        .card-light .text-muted {
            color: #6b6b7a;
        }

        /* ============================================
           FORMS - Clear, Readable
           ============================================ */

        .form-group {
            margin-bottom: var(--space-lg);
        }

        .form-label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            color: var(--text-secondary);
            margin-bottom: var(--space-sm);
        }

        .card-light .form-label {
            color: #4a4a5a;
        }

        .form-input {
            width: 100%;
            padding: var(--space-md) var(--space-lg);
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            color: var(--text-bright);
            font-family: var(--font-sans);
            font-size: 16px;
            transition: all 0.3s var(--ease-out);
        }

        .form-input:focus {
            outline: none;
            background: rgba(255, 255, 255, 0.12);
            border-color: var(--phoenix-glow);
            box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.15);
        }

        .form-input::placeholder {
            color: var(--text-muted);
        }

        /* Light form inputs */
        .card-light .form-input {
            background: #f5f5f8;
            border: 1px solid #e0e0e8;
            color: #1a1a2e;
        }

        .card-light .form-input:focus {
            background: #ffffff;
            border-color: var(--phoenix-glow);
        }

        .card-light .form-input::placeholder {
            color: #9898a8;
        }

        /* ============================================
           ALERTS - Clear visibility
           ============================================ */

        .alert {
            padding: var(--space-md) var(--space-lg);
            border-radius: 12px;
            font-size: 14px;
            margin-bottom: var(--space-lg);
            display: flex;
            align-items: center;
            gap: var(--space-md);
            font-weight: 500;
        }

        .alert-success {
            background: rgba(34, 197, 94, 0.15);
            border: 1px solid rgba(34, 197, 94, 0.3);
            color: #4ade80;
        }

        .alert-error {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #f87171;
        }

        .alert-info {
            background: rgba(0, 212, 255, 0.15);
            border: 1px solid rgba(0, 212, 255, 0.3);
            color: var(--phoenix-glow);
        }

        /* ============================================
           DEAL CARDS - Flight results
           ============================================ */

        .deal {
            background: var(--card-dark);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: var(--space-xl);
            margin: var(--space-lg) 0;
            position: relative;
            overflow: hidden;
            transition: all 0.3s var(--ease-out);
        }

        .deal::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(180deg, var(--phoenix-glow), var(--phoenix-aurora));
        }

        .deal:hover {
            border-color: rgba(0, 212, 255, 0.3);
            transform: translateX(4px);
        }

        .deal-header {
            font-size: 22px;
            font-weight: 700;
            color: var(--text-bright);
            margin-bottom: var(--space-md);
            display: flex;
            align-items: center;
            gap: var(--space-md);
        }

        .price-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: var(--space-md) 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            color: var(--text-secondary);
        }

        .savings {
            color: var(--success-green);
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: var(--space-sm);
        }

        /* ============================================
           PAYMENT BOX - FIXED READABILITY
           ============================================ */

        .payment-box {
            background: var(--card-dark);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 16px;
            padding: var(--space-xl);
            margin-top: var(--space-xl);
        }

        .payment-box h3, .payment-box h4 {
            font-family: var(--font-display);
            letter-spacing: 2px;
            color: var(--text-bright);
        }

        .payment-box p, .payment-box span, .payment-box label {
            color: var(--text-secondary);
        }

        .xrp-address {
            font-family: var(--font-mono);
            font-size: 14px;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            padding: var(--space-md);
            word-break: break-all;
            color: var(--phoenix-glow);
        }

        /* ============================================
           STATUS BADGES
           ============================================ */

        .tag, .status-badge {
            display: inline-flex;
            align-items: center;
            gap: var(--space-xs);
            padding: var(--space-xs) var(--space-md);
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .tag {
            background: rgba(34, 197, 94, 0.15);
            color: var(--success-green);
            border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .tag-warning {
            background: rgba(167, 139, 250, 0.15);
            color: var(--phoenix-aurora);
            border: 1px solid rgba(167, 139, 250, 0.3);
        }

        .status-pending {
            background: rgba(167, 139, 250, 0.15);
            color: var(--phoenix-aurora);
        }

        .status-verified {
            background: rgba(34, 197, 94, 0.15);
            color: var(--success-green);
        }

        .status-expired {
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
        }

        /* ============================================
           STATS GRID
           ============================================ */

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: var(--space-lg);
            margin: var(--space-2xl) 0;
        }

        .stat-card {
            background: var(--card-dark);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: var(--space-xl);
            text-align: center;
            transition: all 0.3s var(--ease-out);
        }

        .stat-card:hover {
            border-color: rgba(0, 212, 255, 0.3);
            transform: translateY(-4px);
        }

        .stat-value {
            font-family: var(--font-display);
            font-size: 40px;
            font-weight: 600;
            letter-spacing: 2px;
            color: var(--text-bright);
        }

        .stat-label {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: var(--space-sm);
        }

        /* ============================================
           FOOTER - Documentary Credits Style
           ============================================ */

        .footer {
            position: relative;
            z-index: 10;
            background: rgba(10, 6, 18, 0.95);
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            padding: var(--space-3xl) 0;
            margin-top: var(--space-4xl);
        }

        .footer-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--space-lg);
        }

        .footer-brand {
            display: flex;
            align-items: center;
            gap: var(--space-md);
            color: var(--text-bright);
        }

        .footer-logo {
            width: 32px;
            height: 32px;
            color: var(--phoenix-glow);
        }

        .footer-links {
            display: flex;
            gap: var(--space-xl);
        }

        .footer-link {
            color: var(--text-muted);
            text-decoration: none;
            font-size: 14px;
            transition: color 0.3s var(--ease-out);
        }

        .footer-link:hover {
            color: var(--text-bright);
        }

        .footer-copy {
            width: 100%;
            text-align: center;
            padding-top: var(--space-xl);
            margin-top: var(--space-xl);
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            font-size: 13px;
            color: var(--text-muted);
        }

        .footer-tagline {
            color: var(--phoenix-glow);
            font-style: italic;
        }

        /* ============================================
           LOADING SCREEN - Cinematic
           ============================================ */

        .loading-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: var(--deep-space);
            z-index: 10000;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            transition: opacity 0.8s var(--ease-out), visibility 0.8s;
        }

        .loading-screen.hidden {
            opacity: 0;
            visibility: hidden;
        }

        /* Sacred geometry logo — loading screen */
        .loading-logo {
            width: 140px;
            height: 140px;
            color: rgba(160, 120, 200, 0.8);
            animation: geoSpin 40s linear infinite;
            filter: drop-shadow(0 0 15px rgba(139, 45, 91, 0.6))
                    drop-shadow(0 0 30px rgba(100, 60, 180, 0.4));
            position: relative;
        }

        /* Sacred geometry shared styles */
        .sacred-geo .geo-ring {
            stroke-dasharray: 300;
            stroke-dashoffset: 300;
            animation: geoDraw 3s ease-out forwards;
        }
        .sacred-geo .geo-r1 { animation-delay: 0s; }
        .sacred-geo .geo-r2 { animation-delay: 0.3s; stroke-width: 0.4; }
        .sacred-geo .geo-r3 { animation-delay: 0.8s; }
        .sacred-geo .geo-line {
            stroke-dasharray: 200;
            stroke-dashoffset: 200;
            animation: geoDraw 2s ease-out forwards;
            stroke-width: 0.35;
            opacity: 0.7;
        }
        .sacred-geo .geo-l2 { animation-delay: 1s; opacity: 0.4; stroke-width: 0.25; }
        .sacred-geo .geo-center {
            fill: currentColor;
            opacity: 0;
            animation: geoPulseCenter 2s ease-out 1.5s forwards;
        }

        @keyframes geoDraw {
            to { stroke-dashoffset: 0; }
        }
        @keyframes geoPulseCenter {
            0% { opacity: 0; r: 1; }
            100% { opacity: 0.8; r: 3; }
        }
        @keyframes geoSpin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        /* Ambient glow behind loading logo */
        .loading-screen::before {
            content: '';
            position: absolute;
            width: 250px;
            height: 250px;
            border-radius: 50%;
            background:
                radial-gradient(circle, rgba(139, 45, 91, 0.4) 0%, transparent 50%),
                radial-gradient(circle at 30% 40%, rgba(100, 60, 180, 0.3) 0%, transparent 40%),
                radial-gradient(circle at 70% 60%, rgba(13, 79, 79, 0.3) 0%, transparent 40%);
            animation: geoAmbient 6s ease-in-out infinite;
            pointer-events: none;
            z-index: -1;
        }

        @keyframes geoAmbient {
            0%, 100% { transform: scale(1); opacity: 0.6; }
            50% { transform: scale(1.15); opacity: 0.9; }
        }

        /* Remove ::after ember particles */
        .loading-screen::after { display: none; }

        @keyframes breathe {
            0%, 100% { transform: scale(1); filter: drop-shadow(0 0 40px rgba(139, 45, 91, 0.5)); }
            50% { transform: scale(1.05); filter: drop-shadow(0 0 60px rgba(100, 60, 180, 0.6)); }
        }

        /* Nav and footer sacred geometry logos */
        .nav-logo .geo-ring, .nav-logo .geo-line, .nav-logo .geo-l2 {
            stroke-dasharray: none;
            stroke-dashoffset: 0;
            animation: none;
        }
        .nav-logo .geo-center { opacity: 0.8; animation: none; }
        .footer-logo .geo-ring, .footer-logo .geo-line, .footer-logo .geo-l2 {
            stroke-dasharray: none;
            stroke-dashoffset: 0;
            animation: none;
        }
        .footer-logo .geo-center { opacity: 0.8; animation: none; }

        .loading-text {
            font-family: var(--font-display);
            margin-top: var(--space-xl);
            font-size: 14px;
            font-weight: 500;
            letter-spacing: 6px;
            text-transform: uppercase;
            color: var(--text-muted);
        }

        /* ============================================
           MOBILE HAMBURGER MENU
           ============================================ */

        .nav-toggle {
            display: none;
            flex-direction: column;
            gap: 5px;
            background: none;
            border: none;
            cursor: pointer;
            padding: var(--space-sm);
            z-index: 1001;
        }

        .nav-toggle span {
            display: block;
            width: 24px;
            height: 2px;
            background: var(--text-bright);
            transition: all 0.3s var(--ease-out);
            border-radius: 2px;
        }

        .nav-toggle.active span:nth-child(1) {
            transform: rotate(45deg) translate(5px, 5px);
        }

        .nav-toggle.active span:nth-child(2) {
            opacity: 0;
        }

        .nav-toggle.active span:nth-child(3) {
            transform: rotate(-45deg) translate(5px, -5px);
        }

        /* ============================================
           RESPONSIVE
           ============================================ */

        /* Tablet */
        @media (max-width: 1024px) {
            .nav {
                padding: var(--space-md) var(--space-lg);
            }

            .nav-links {
                gap: var(--space-sm);
            }

            .nav-link {
                font-size: 12px;
                padding: var(--space-xs) var(--space-sm);
            }

            .container {
                padding: 0 var(--space-lg);
            }

            .stats {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        /* Mobile */
        @media (max-width: 768px) {
            .nav {
                padding: var(--space-md);
            }

            .nav-toggle {
                display: flex;
            }

            .nav-links {
                position: fixed;
                top: 0;
                right: -100%;
                width: 280px;
                height: 100vh;
                flex-direction: column;
                background: rgba(10, 6, 18, 0.98);
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                padding: 80px var(--space-xl) var(--space-xl);
                gap: var(--space-xs);
                transition: right 0.4s var(--ease-out);
                z-index: 1000;
                overflow-y: auto;
            }

            .nav-links.open {
                right: 0;
                box-shadow: -10px 0 30px rgba(0, 0, 0, 0.5);
            }

            .nav-link {
                font-size: 14px;
                padding: var(--space-md);
                width: 100%;
                border-radius: 8px;
            }

            .nav-link:hover {
                background: rgba(255, 255, 255, 0.08);
            }

            .nav-wordmark {
                font-size: 18px;
                letter-spacing: 4px;
            }

            .nav-logo {
                width: 36px;
                height: 36px;
            }

            .container {
                padding: 0 var(--space-md);
            }

            .xrpl-badge {
                display: none;
            }

            /* Cards */
            .card {
                padding: var(--space-lg);
                border-radius: 12px;
            }

            /* Stats */
            .stats {
                grid-template-columns: repeat(2, 1fr);
                gap: var(--space-md);
            }

            .stat-value {
                font-size: 28px;
            }

            .stat-card {
                padding: var(--space-lg);
            }

            /* Deal cards */
            .deal {
                padding: var(--space-lg);
            }

            .deal-header {
                font-size: 18px;
                flex-wrap: wrap;
            }

            .price-row {
                flex-direction: column;
                align-items: flex-start;
                gap: var(--space-sm);
            }

            /* Tables — horizontal scroll */
            table {
                display: block;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                white-space: nowrap;
            }

            th, td {
                padding: var(--space-sm) var(--space-md);
                font-size: 13px;
            }

            /* Buttons */
            .btn-large {
                padding: var(--space-md) var(--space-xl);
                font-size: 14px;
                width: 100%;
                text-align: center;
            }

            /* Forms */
            .form-input {
                font-size: 16px; /* Prevents iOS zoom on focus */
            }

            /* Footer */
            .footer {
                padding: var(--space-2xl) 0;
            }

            .footer-content {
                flex-direction: column;
                text-align: center;
            }

            .footer-links {
                gap: var(--space-lg);
            }

            /* How it works grid */
            .how-it-works {
                grid-template-columns: 1fr;
            }

            /* Payment methods grid */
            .payment-methods {
                grid-template-columns: repeat(2, 1fr);
            }

            /* Headings */
            .heading-display {
                letter-spacing: 4px;
            }

            .heading-1 {
                letter-spacing: 2px;
            }
        }

        /* Small phones */
        @media (max-width: 480px) {
            .stats {
                grid-template-columns: 1fr;
            }

            .payment-methods {
                grid-template-columns: 1fr;
            }

            .nav-cta {
                padding: var(--space-sm) var(--space-md) !important;
                font-size: 13px;
            }
        }

        /* ============================================
           PWA STANDALONE MODE
           ============================================ */

        /* Safe area insets for notched devices (iPhone X+) */
        @supports (padding-top: env(safe-area-inset-top)) {
            .pwa-standalone .nav {
                padding-top: calc(var(--space-md) + env(safe-area-inset-top));
            }
            .pwa-standalone .main {
                padding-top: calc(80px + env(safe-area-inset-top));
            }
            .pwa-standalone .footer {
                padding-bottom: calc(var(--space-2xl) + env(safe-area-inset-bottom));
            }
        }

        /* Touch optimizations for mobile */
        @media (hover: none) and (pointer: coarse) {
            .nav-link {
                min-height: 44px;
                display: flex;
                align-items: center;
            }
            .btn {
                min-height: 48px;
            }
            .card:hover {
                transform: none;
            }
        }

        /* Standalone display mode */
        @media (display-mode: standalone) {
            .nav {
                padding-top: calc(var(--space-md) + env(safe-area-inset-top, 0px));
            }
        }

        /* ============================================
           UTILITY CLASSES
           ============================================ */

        hr {
            border: none;
            height: 1px;
            background: rgba(255, 255, 255, 0.1);
            margin: var(--space-2xl) 0;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: var(--space-md);
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        th {
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--text-muted);
        }

        td {
            color: var(--text-secondary);
        }

        /* Animation */
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .animate-in {
            animation: fadeInUp 0.8s var(--ease-out) forwards;
        }

        /* How it works - dark theme */
        .how-it-works {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: var(--space-xl);
            margin: var(--space-xl) 0;
        }

        .step {
            text-align: center;
            padding: var(--space-lg);
        }

        .step-icon {
            width: 72px;
            height: 72px;
            background: linear-gradient(135deg, var(--phoenix-glow), var(--phoenix-cyan));
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto var(--space-md);
            font-size: 28px;
            box-shadow: 0 8px 30px rgba(0, 212, 255, 0.3);
        }

        .step h3 {
            color: var(--text-bright);
            font-size: 16px;
            margin-bottom: var(--space-sm);
        }

        .step p {
            color: var(--text-muted);
            font-size: 14px;
        }

        /* Payment methods - dark theme */
        .payment-methods {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: var(--space-md);
            margin-top: var(--space-lg);
        }

        .payment-method {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: var(--space-lg);
            border-radius: 12px;
            text-align: center;
            transition: all 0.3s var(--ease-out);
        }

        .payment-method:hover {
            background: rgba(255, 255, 255, 0.08);
            border-color: rgba(0, 212, 255, 0.3);
            transform: translateY(-4px);
        }

        .payment-method .icon {
            font-size: 32px;
            margin-bottom: var(--space-sm);
        }

        .payment-method strong {
            display: block;
            color: var(--text-bright);
            margin-bottom: var(--space-xs);
        }

        .payment-method span {
            font-size: 12px;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
    <!-- Aurora Background — Animated layers -->
    <div class="aurora-bg"></div>
    <div class="aurora-layer-1"></div>
    <div class="aurora-layer-2"></div>
    <div class="aurora-layer-3"></div>
    <div class="aurora-layer-4"></div>
    <div class="stars"></div>
    <div class="stars-2"></div>

    <!-- Loading Screen -->
    <div class="loading-screen" id="loadingScreen">
        <svg class="loading-logo sacred-geo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
            <g fill="none" stroke="currentColor" stroke-width="0.6" opacity="0.9">
                <circle cx="50" cy="50" r="44" class="geo-ring geo-r1"/>
                <circle cx="50" cy="6" r="22" class="geo-ring geo-r2"/>
                <circle cx="88" cy="28" r="22" class="geo-ring geo-r2"/>
                <circle cx="88" cy="72" r="22" class="geo-ring geo-r2"/>
                <circle cx="50" cy="94" r="22" class="geo-ring geo-r2"/>
                <circle cx="12" cy="72" r="22" class="geo-ring geo-r2"/>
                <circle cx="12" cy="28" r="22" class="geo-ring geo-r2"/>
                <line x1="50" y1="6" x2="88" y2="28" class="geo-line"/>
                <line x1="88" y1="28" x2="88" y2="72" class="geo-line"/>
                <line x1="88" y1="72" x2="50" y2="94" class="geo-line"/>
                <line x1="50" y1="94" x2="12" y2="72" class="geo-line"/>
                <line x1="12" y1="72" x2="12" y2="28" class="geo-line"/>
                <line x1="12" y1="28" x2="50" y2="6" class="geo-line"/>
                <line x1="50" y1="6" x2="50" y2="94" class="geo-line"/>
                <line x1="12" y1="28" x2="88" y2="72" class="geo-line"/>
                <line x1="88" y1="28" x2="12" y2="72" class="geo-line"/>
                <line x1="50" y1="6" x2="88" y2="72" class="geo-line geo-l2"/>
                <line x1="50" y1="6" x2="12" y2="72" class="geo-line geo-l2"/>
                <line x1="88" y1="28" x2="50" y2="94" class="geo-line geo-l2"/>
                <line x1="88" y1="28" x2="12" y2="72" class="geo-line geo-l2"/>
                <line x1="50" y1="94" x2="12" y2="28" class="geo-line geo-l2"/>
                <line x1="12" y1="72" x2="88" y2="28" class="geo-line geo-l2"/>
                <circle cx="50" cy="50" r="22" class="geo-ring geo-r3"/>
                <circle cx="50" cy="50" r="3" class="geo-center" fill="currentColor"/>
            </g>
        </svg>
        <div class="loading-text">PHOENIX</div>
    </div>

    <!-- Navigation -->
    <nav class="nav" id="nav">
        <a href="/" class="nav-brand">
            <svg class="nav-logo sacred-geo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                <g fill="none" stroke="currentColor" stroke-width="0.8" opacity="0.9">
                    <circle cx="50" cy="50" r="44" class="geo-ring geo-r1"/>
                    <circle cx="50" cy="6" r="22" class="geo-ring geo-r2"/>
                    <circle cx="88" cy="28" r="22" class="geo-ring geo-r2"/>
                    <circle cx="88" cy="72" r="22" class="geo-ring geo-r2"/>
                    <circle cx="50" cy="94" r="22" class="geo-ring geo-r2"/>
                    <circle cx="12" cy="72" r="22" class="geo-ring geo-r2"/>
                    <circle cx="12" cy="28" r="22" class="geo-ring geo-r2"/>
                    <line x1="50" y1="6" x2="88" y2="28" class="geo-line"/>
                    <line x1="88" y1="28" x2="88" y2="72" class="geo-line"/>
                    <line x1="88" y1="72" x2="50" y2="94" class="geo-line"/>
                    <line x1="50" y1="94" x2="12" y2="72" class="geo-line"/>
                    <line x1="12" y1="72" x2="12" y2="28" class="geo-line"/>
                    <line x1="12" y1="28" x2="50" y2="6" class="geo-line"/>
                    <line x1="50" y1="6" x2="50" y2="94" class="geo-line"/>
                    <line x1="12" y1="28" x2="88" y2="72" class="geo-line"/>
                    <line x1="88" y1="28" x2="12" y2="72" class="geo-line"/>
                    <circle cx="50" cy="50" r="22" class="geo-ring geo-r3"/>
                    <circle cx="50" cy="50" r="3" class="geo-center" fill="currentColor" opacity="0.8"/>
                </g>
            </svg>
            <span class="nav-wordmark">PHOENIX</span>
        </a>

        <button class="nav-toggle" id="navToggle" aria-label="Toggle navigation">
            <span></span><span></span><span></span>
        </button>

        <div class="nav-links" id="navLinks">
            {% if current_user.is_authenticated %}
                <a href="/ai" class="nav-link">Chat</a>
                <a href="/search" class="nav-link">Flights</a>
                <a href="/deals" class="nav-link">Deals</a>
                <a href="/wallet" class="nav-link">Wallet</a>
                <div class="nav-more-wrapper">
                    <button class="nav-link nav-more-btn" id="navMoreBtn">More &#9662;</button>
                    <div class="nav-more-menu" id="navMoreMenu">
                        <a href="/dashboard" class="nav-more-link">Dashboard</a>
                        {% if current_user.is_admin %}<a href="/nodes" class="nav-more-link" style="color: var(--phoenix-glow);">Nodes</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/portal" class="nav-more-link" style="color: var(--phoenix-glow);">Proxy Portal</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/helper" class="nav-more-link" style="color: var(--phoenix-glow);">Helper</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/earn" class="nav-more-link" style="color: var(--phoenix-glow);">Earn</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/setup" class="nav-more-link" style="color: var(--phoenix-glow);">Setup Guides</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/admin" class="nav-more-link" style="color: var(--phoenix-glow);">Admin</a>{% endif %}
                    </div>
                </div>
                <a href="/logout" class="nav-link nav-cta">Logout</a>
            {% else %}
                <a href="/search" class="nav-link">Flights</a>
                <a href="/deals" class="nav-link">Deals</a>
                <a href="/login" class="nav-link">Login</a>
                <a href="/register" class="nav-link nav-cta">Get Started</a>
            {% endif %}
            <span class="xrpl-badge">XRPL Secured</span>
        </div>
    </nav>

    <!-- Onboarding Banner -->
    {% if not current_user.is_authenticated %}
    <div class="onboard-banner" id="onboardBanner">
        <div class="onboard-banner-inner">
            <div class="onboard-banner-text">
                <strong>Join the Phoenix Network</strong>
                <span class="onboard-banner-sub">Sign in with Google. Your browser becomes a node. Earn while you search.</span>
            </div>
            <div class="onboard-banner-action">
                <a href="/auth/google/start" class="onboard-btn google-signin-btn" id="googleSignInBtn" style="text-decoration:none;">
                    <svg width="18" height="18" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:8px;"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A11.96 11.96 0 001 12c0 1.94.46 3.77 1.18 5.42l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                    Sign in with Google
                </a>
            </div>
            <button class="onboard-banner-close" onclick="document.getElementById('onboardBanner').style.display='none';sessionStorage.setItem('banner_dismissed','1')" aria-label="Dismiss">&times;</button>
        </div>
    </div>
    <script>
    if(sessionStorage.getItem('banner_dismissed')){document.getElementById('onboardBanner').style.display='none';}
    </script>
    {% elif current_user.is_authenticated and not current_user.is_helper_node %}
    <div class="onboard-banner onboard-banner-node" id="onboardBanner">
        <div class="onboard-banner-inner">
            <div class="onboard-banner-text">
                <strong>Activate Your Node</strong>
                <span class="onboard-banner-sub">One click to start earning. Your browser becomes part of the Phoenix search network.</span>
            </div>
            <div class="onboard-banner-action">
                <button class="onboard-btn" id="onboardNodeBtn" onclick="onboardNode()">Become a Node</button>
            </div>
            <button class="onboard-banner-close" onclick="document.getElementById('onboardBanner').style.display='none'" aria-label="Dismiss">&times;</button>
        </div>
    </div>
    <script>
    function onboardNode(){
        var btn=document.getElementById('onboardNodeBtn');
        btn.textContent='Activating...';btn.disabled=true;
        fetch('/api/node/onboard',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]')?.content||''},body:JSON.stringify({country_code:'US'})})
        .then(r=>r.json()).then(d=>{
            if(d.success){document.getElementById('onboardBanner').innerHTML='<div class=\"onboard-banner-inner\"><div class=\"onboard-banner-text\"><strong>Node Active!</strong> <span class=\"onboard-banner-sub\">You are now part of the Phoenix network. Node ID: '+d.node_id+'</span></div></div>';setTimeout(()=>{document.getElementById('onboardBanner').style.display='none';},4000);}
            else{btn.textContent='Become a Node';btn.disabled=false;alert(d.error||'Onboarding failed');}
        }).catch(()=>{btn.textContent='Become a Node';btn.disabled=false;});
    }
    </script>
    {% endif %}

    <style>
    .onboard-banner{position:fixed;top:60px;left:0;right:0;z-index:999;background:linear-gradient(135deg,rgba(255,107,53,0.15),rgba(138,43,226,0.12));backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,107,53,0.3);padding:0;animation:bannerSlide .4s ease-out;}
    @keyframes bannerSlide{from{transform:translateY(-100%);opacity:0}to{transform:translateY(0);opacity:1}}
    .onboard-banner-inner{max-width:1200px;margin:0 auto;padding:12px 24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap;}
    .onboard-banner-text{flex:1;min-width:200px;font-family:'Rajdhani',sans-serif;}
    .onboard-banner-text strong{color:var(--phoenix-glow,#ff6b35);font-size:1.05rem;display:block;line-height:1.2;}
    .onboard-banner-sub{color:var(--text-secondary,#999);font-size:0.88rem;}
    .onboard-banner-action{flex-shrink:0;}
    .onboard-banner-close{background:none;border:none;color:var(--text-secondary,#999);font-size:1.4rem;cursor:pointer;padding:0 0 0 12px;line-height:1;opacity:0.7;}
    .onboard-banner-close:hover{opacity:1;color:var(--text-bright,#fff);}
    .onboard-btn{background:linear-gradient(135deg,#ff6b35,#ff8f5e);color:#fff;border:none;padding:10px 28px;border-radius:25px;font-family:'Rajdhani',sans-serif;font-weight:600;font-size:0.95rem;cursor:pointer;transition:all .2s;}
    .onboard-btn:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(255,107,53,0.4);}
    .onboard-btn:disabled{opacity:0.6;cursor:wait;transform:none;}
    .google-signin-btn{display:inline-flex;align-items:center;background:#fff;color:#3c4043;border:none;padding:10px 24px;border-radius:25px;font-family:'Rajdhani',sans-serif;font-weight:600;font-size:0.95rem;cursor:pointer;transition:all .2s;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,0.2);}
    .google-signin-btn:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(0,0,0,0.3);background:#f8f8f8;}
    @media(max-width:600px){.onboard-banner-inner{flex-direction:column;text-align:center;gap:10px;padding:10px 16px;}.onboard-banner-close{position:absolute;top:8px;right:12px;}}
    </style>

    <!-- Main Content -->
    <main class="main">
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }} animate-in">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            {{ content | safe }}
        </div>
    </main>

    <!-- Footer -->
    <footer class="footer">
        <div class="container">
            <div class="footer-content">
                <div class="footer-brand">
                    <svg class="footer-logo sacred-geo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                        <g fill="none" stroke="currentColor" stroke-width="0.8" opacity="0.7">
                            <circle cx="50" cy="50" r="44" class="geo-ring"/>
                            <circle cx="50" cy="6" r="22" class="geo-ring"/>
                            <circle cx="88" cy="28" r="22" class="geo-ring"/>
                            <circle cx="88" cy="72" r="22" class="geo-ring"/>
                            <circle cx="50" cy="94" r="22" class="geo-ring"/>
                            <circle cx="12" cy="72" r="22" class="geo-ring"/>
                            <circle cx="12" cy="28" r="22" class="geo-ring"/>
                            <circle cx="50" cy="50" r="22" class="geo-ring"/>
                            <circle cx="50" cy="50" r="3" fill="currentColor" opacity="0.8"/>
                        </g>
                    </svg>
                    <span style="font-family: 'Cinzel', serif; font-weight: 600; letter-spacing: 4px;">PHOENIX</span>
                </div>
                <div class="footer-links">
                    <a href="/terms" class="footer-link">Terms</a>
                    <a href="/privacy" class="footer-link">Privacy</a>
                    <a href="/about" class="footer-link">About</a>
                </div>
            </div>
            <div class="footer-copy">
                &copy; 2026 PHOENIX &mdash; <span class="footer-tagline">Breaking borders. Connecting humanity.</span>
                <br>Powered by XRP Ledger
            </div>
        </div>
    </footer>

    <script>
        // Navigation scroll effect
        window.addEventListener('scroll', function() {
            const nav = document.getElementById('nav');
            if (window.scrollY > 50) {
                nav.classList.add('scrolled');
            } else {
                nav.classList.remove('scrolled');
            }
        });

        // Mobile nav toggle
        (function() {
            var toggle = document.getElementById('navToggle');
            var links = document.getElementById('navLinks');
            if (toggle && links) {
                toggle.addEventListener('click', function() {
                    toggle.classList.toggle('active');
                    links.classList.toggle('open');
                });
                links.addEventListener('click', function(e) {
                    if (e.target.classList.contains('nav-link')) {
                        toggle.classList.remove('active');
                        links.classList.remove('open');
                    }
                });
            }
        })();

        // "More" dropdown menu
        (function() {
            var btn = document.getElementById('navMoreBtn');
            var menu = document.getElementById('navMoreMenu');
            if (btn && menu) {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    menu.classList.toggle('open');
                });
                document.addEventListener('click', function() {
                    menu.classList.remove('open');
                });
            }
        })();

        // Hide loading screen
        window.addEventListener('load', function() {
            setTimeout(function() {
                document.getElementById('loadingScreen').classList.add('hidden');
            }, 1000);
        });

        // Loading screen controls
        window.showLoadingScreen = function(message) {
            const loader = document.getElementById('loadingScreen');
            const text = loader.querySelector('.loading-text');
            if (message) text.textContent = message;
            loader.classList.remove('hidden');
        };

        window.hideLoadingScreen = function() {
            document.getElementById('loadingScreen').classList.add('hidden');
        };

        // PWA Service Worker registration
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', function() {
                navigator.serviceWorker.register('/service-worker.js')
                    .then(function(reg) {
                        console.log('Phoenix SW registered, scope:', reg.scope);
                    })
                    .catch(function(err) {
                        console.log('Phoenix SW registration failed:', err);
                    });
            });
        }

        // iOS standalone detection — adjust viewport for notch
        if (window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches) {
            document.documentElement.classList.add('pwa-standalone');
        }
    </script>

    <!-- Phoenix Node Client (Build #91) — auto-initializes node for all users -->
    <script src="/static/js/phoenix-node-client.js"></script>
    <script src="/static/js/phoenix-node-capture.js"></script>
    <script src="/static/js/phoenix-node-bridge.js"></script>
    {% if current_user.is_authenticated and current_user.is_helper_node %}
    <script>
        window.__PHOENIX_NODE_CONFIG__ = {
            serverUrl: window.location.origin,
            helperToken: "{{ helper_token_for_node|default('') }}",
            consent: {{ node_consent_json|default('{}')|safe }}
        };
        if (window.__PHOENIX_NODE_CONFIG__.helperToken) {
            autoInitPhoenixNode().catch(function(e) {
                console.warn('[PhoenixNode] Auto-init failed:', e.message);
            });
        }
    </script>
    {% endif %}
</body>
</html>
'''


# Updated HOME_HERO with documentary feel
HOME_HERO = '''
<style>
    .hero {
        min-height: calc(100vh - 80px);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        padding: 60px 20px 100px;
        position: relative;
    }

    .hero-overline {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 10px 20px;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 100px;
        font-family: var(--font-display);
        font-size: 12px;
        font-weight: 500;
        letter-spacing: 4px;
        text-transform: uppercase;
        color: var(--text-secondary);
        margin-bottom: 40px;
        animation: fadeInUp 0.8s var(--ease-out) forwards;
    }

    .hero-overline .dot {
        width: 8px;
        height: 8px;
        background: var(--success-green);
        border-radius: 50%;
        animation: pulse 2s ease-in-out infinite;
    }

    .hero h1 {
        font-family: var(--font-display);
        font-size: clamp(48px, 12vw, 120px);
        font-weight: 600;
        letter-spacing: 10px;
        line-height: 0.95;
        text-transform: uppercase;
        margin: 0 0 30px;
        color: var(--text-bright);
        text-shadow: 0 4px 40px rgba(0, 0, 0, 0.5);
        opacity: 0;
        animation: fadeInUp 0.8s var(--ease-out) 0.15s forwards;
    }

    .hero h1 .accent {
        display: block;
        color: var(--text-bright);
    }

    .hero-subtitle {
        font-size: clamp(18px, 2.5vw, 24px);
        font-weight: 400;
        color: var(--text-secondary);
        max-width: 700px;
        line-height: 1.7;
        margin: 0 0 50px;
        opacity: 0;
        animation: fadeInUp 0.8s var(--ease-out) 0.3s forwards;
    }

    .hero-ctas {
        display: flex;
        gap: 20px;
        flex-wrap: wrap;
        justify-content: center;
        opacity: 0;
        animation: fadeInUp 0.8s var(--ease-out) 0.45s forwards;
    }

    .hero-stats {
        display: flex;
        gap: 60px;
        margin-top: 80px;
        opacity: 0;
        animation: fadeInUp 0.8s var(--ease-out) 0.6s forwards;
    }

    .hero-stat {
        text-align: center;
    }

    .hero-stat-value {
        font-family: var(--font-display);
        font-size: 52px;
        font-weight: 600;
        letter-spacing: 2px;
        color: var(--text-bright);
    }

    .hero-stat-label {
        font-size: 12px;
        font-weight: 500;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-top: 8px;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(30px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Features */
    .features-section {
        padding: 100px 0;
    }

    .section-header {
        text-align: center;
        margin-bottom: 60px;
    }

    .section-header h2 {
        font-size: clamp(28px, 4vw, 42px);
        font-weight: 700;
        letter-spacing: -1px;
        color: var(--text-bright);
        margin-bottom: 16px;
    }

    .section-header p {
        font-size: 18px;
        color: var(--text-muted);
    }

    .features-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 24px;
    }

    .feature-card {
        background: var(--card-dark);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 20px;
        padding: 40px;
        transition: all 0.4s var(--ease-out);
    }

    .feature-card:hover {
        border-color: rgba(255, 107, 53, 0.3);
        transform: translateY(-8px);
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
    }

    .feature-icon {
        width: 64px;
        height: 64px;
        background: linear-gradient(135deg, rgba(255, 107, 53, 0.2), rgba(255, 200, 87, 0.1));
        border-radius: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 32px;
        margin-bottom: 24px;
    }

    .feature-card h3 {
        font-size: 22px;
        font-weight: 700;
        color: var(--text-bright);
        margin-bottom: 12px;
    }

    .feature-card p {
        font-size: 15px;
        color: var(--text-muted);
        line-height: 1.7;
    }

    /* Trust badges */
    .trust-section {
        padding: 60px 0;
    }

    .trust-badges {
        display: flex;
        justify-content: center;
        gap: 24px;
        flex-wrap: wrap;
    }

    .trust-badge {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 24px 32px;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        min-width: 140px;
        transition: all 0.3s var(--ease-out);
    }

    .trust-badge:hover {
        border-color: rgba(255, 107, 53, 0.3);
        background: rgba(255, 255, 255, 0.05);
    }

    .trust-badge .icon {
        font-size: 36px;
    }

    .trust-badge strong {
        font-size: 15px;
        font-weight: 600;
        color: var(--text-bright);
    }

    .trust-badge span {
        font-size: 12px;
        color: var(--text-muted);
    }

    @media (max-width: 768px) {
        .hero-stats {
            flex-direction: column;
            gap: 30px;
        }

        .features-grid {
            grid-template-columns: 1fr;
        }
    }
</style>

<section class="hero">
    <span class="hero-overline">
        <span class="dot"></span>
        Powered by XRP Ledger
    </span>

    <h1>EXPLORE<br><span class="accent">THE WORLD</span></h1>

    <p class="hero-subtitle">
        Break free from borders. Access flight prices from any country on Earth.
        Pay with crypto. No restrictions. No barriers. Your journey begins here.
    </p>

    <div class="hero-ctas">
        <a href="/search" class="btn btn-primary btn-large">Search Flights</a>
        <a href="/register" class="btn btn-secondary btn-large">Start Your Journey</a>
    </div>

    <div class="hero-stats">
        <div class="hero-stat">
            <div class="hero-stat-value">195</div>
            <div class="hero-stat-label">Countries</div>
        </div>
        <div class="hero-stat">
            <div class="hero-stat-value">70%</div>
            <div class="hero-stat-label">Max Savings</div>
        </div>
        <div class="hero-stat">
            <div class="hero-stat-value">{{ total_deals }}</div>
            <div class="hero-stat-label">Active Deals</div>
        </div>
    </div>
</section>

<section class="features-section">
    <div class="section-header">
        <h2>Why PHOENIX?</h2>
        <p>The future of travel is borderless</p>
    </div>

    <div class="features-grid">
        <div class="feature-card">
            <div class="feature-icon">&#127760;</div>
            <h3>Global Access</h3>
            <p>Search flights from any market on the planet. Our network spans every continent, giving you prices that were previously impossible to access.</p>
        </div>

        <div class="feature-card">
            <div class="feature-icon">&#128274;</div>
            <h3>Borderless Payments</h3>
            <p>Pay with XRP or cryptocurrency. No banking restrictions. No geographic blocks. Trustless escrow protects every single transaction.</p>
        </div>

        <div class="feature-card">
            <div class="feature-icon">&#127793;</div>
            <h3>Adventure Awaits</h3>
            <p>The same flight costs different prices around the world. We find the cheapest regional price and unlock it for you instantly.</p>
        </div>
    </div>
</section>

<section class="trust-section">
    <div class="trust-badges">
        <div class="trust-badge">
            <div class="icon">&#128179;</div>
            <strong>Cards</strong>
            <span>Visa, Mastercard</span>
        </div>
        <div class="trust-badge">
            <div class="icon">&#128142;</div>
            <strong>XRP</strong>
            <span>Instant Settlement</span>
        </div>
        <div class="trust-badge">
            <div class="icon">&#129689;</div>
            <strong>Crypto</strong>
            <span>BTC, ETH, USDC</span>
        </div>
        <div class="trust-badge">
            <div class="icon">&#128178;</div>
            <strong>RLUSD</strong>
            <span>XRPL Stablecoin</span>
        </div>
    </div>
</section>
'''
