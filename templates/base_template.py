"""
MYSTES World-Class UI Template
Planet Earth Documentary Inspired - Adventure & Higher Calling

Features:
- Aurora/cosmic background imagery
- Mystes silhouette logo
- Cinematic, documentary feel
- Highly readable typography
- Inspiring adventure aesthetic
"""

# MYSTES Logo — Eyes SVG (referenced from static/favicon-eyes.svg)
MYSTES_LOGO_SVG = '<img src="/static/favicon-eyes.svg" alt="MYSTES" style="width:60px;height:60px;">'

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} | MYSTES</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="MYSTES - AI-powered search engine for geographic price arbitrage. Compare flights, hotels, products, rentals and more across 195 markets. Pay with crypto. Powered by XRPL.">
    <!-- PWA Meta -->
    <meta name="theme-color" content="#7c3aed">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Mystes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="msapplication-TileColor" content="#0a0612">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <link rel="manifest" href="/static/manifest.json">
    <link rel="apple-touch-icon" href="/static/icons/icon-192x192.png">
    <link rel="icon" type="image/svg+xml" href="/static/favicon-eyes.svg">
    <link rel="icon" type="image/x-icon" href="/favicon.ico">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <!-- 3D Scene & Scroll Animations -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js" defer></script>
    <!-- Google OAuth handled via server-side redirect, no JS library needed -->
    <style>
        /* ============================================
           MYSTES DESIGN SYSTEM
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

            /* Text colors - ALL WHITE */
            --text-bright: #ffffff;
            --text-primary: #ffffff;
            --text-secondary: #ffffff;
            --text-muted: #cccccc;
            --text-on-light: #1a1a2e;
            --text-on-card: #ffffff;

            /* Accent colors - Mystes purple/teal theme */
            --mystes-glow: #7c3aed;
            --mystes-silver: #14b8a6;
            --mystes-cyan: #6d28d9;
            --mystes-aurora: #5b21b6;
            --success-green: #4ade80;
            --ocean-blue: #0891b2;

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

            /* Typography - Clean Modern */
            --font-display: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-sans: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: 'SF Mono', 'Fira Code', monospace;
            --font-brand: 'Cinzel', 'Trajan Pro', 'Palatino Linotype', 'Book Antiqua', serif;

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
            background: var(--deep-space);
        }

        body {
            font-family: var(--font-sans);
            background: transparent;
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
            line-height: 1.6;
        }

        /* Selection */
        ::selection {
            background: var(--mystes-cyan);
            color: var(--deep-space);
        }

        /* MYSTES brand typography — Pythagorean initiate aesthetic */
        .mystes-brand {
            font-family: var(--font-brand);
            text-transform: uppercase;
            letter-spacing: 5px;
            background: linear-gradient(135deg, #ffffff 0%, #e8d5b7 40%, #ffffff 60%, #c9a96e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        /* ============================================
           AURORA BACKGROUND - Cosmic Documentary Feel
           ============================================ */

        /* ============================================
           DEEP SPACE BACKGROUND (Three.js renders behind)
           body is transparent so fixed canvases show through
           html element holds the dark fallback background
           ============================================ */

        /* Reduce animation on low-power devices */
        @media (prefers-reduced-motion: reduce) {
            #aurora-canvas { opacity: 0.5; }
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
            background: rgba(10, 6, 18, 0.6);
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
            border-bottom: 1px solid rgba(124, 58, 237, 0.12);
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
            font-family: var(--font-brand);
            font-size: 22px;
            font-weight: 700;
            letter-spacing: 8px;
            color: var(--text-bright);
            text-transform: uppercase;
            background: linear-gradient(135deg, #ffffff 0%, #e8d5b7 40%, #ffffff 60%, #c9a96e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            filter: drop-shadow(0 0 12px rgba(201, 169, 110, 0.3));
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
            background: linear-gradient(135deg, #7c3aed, #6d28d9);
            color: #ffffff !important;
            padding: var(--space-sm) var(--space-lg) !important;
            border-radius: 6px;
            font-weight: 600;
            box-shadow: 0 4px 20px rgba(124, 58, 237, 0.4);
        }

        .nav-cta:hover {
            transform: translateY(-3px);
            box-shadow: 0 0 30px rgba(124, 58, 237, 0.5), 0 10px 30px rgba(124, 58, 237, 0.3);
            background: linear-gradient(135deg, #6d28d9, #14b8a6) !important;
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
            background: linear-gradient(135deg, #7c3aed, #6d28d9);
            color: #ffffff;
            box-shadow: 0 4px 20px rgba(124, 58, 237, 0.4);
            font-weight: 700;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(124, 58, 237, 0.5);
            background: linear-gradient(135deg, #6d28d9, #14b8a6);
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
            transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.4s ease, border-color 0.3s ease;
            transform-style: preserve-3d;
        }

        .card:hover {
            border-color: rgba(124, 58, 237, 0.3);
            transform: translateY(-8px) rotateX(2deg);
            box-shadow: 0 20px 60px rgba(124, 58, 237, 0.2), 0 0 40px rgba(124, 58, 237, 0.08);
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
            border-color: var(--mystes-glow);
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
            border-color: var(--mystes-glow);
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
            color: var(--mystes-glow);
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
            background: linear-gradient(180deg, var(--mystes-glow), var(--mystes-aurora));
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
            color: var(--mystes-glow);
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
            color: var(--mystes-aurora);
            border: 1px solid rgba(167, 139, 250, 0.3);
        }

        .status-pending {
            background: rgba(167, 139, 250, 0.15);
            color: var(--mystes-aurora);
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
            color: var(--mystes-glow);
        }

        .footer-wordmark {
            font-family: var(--font-brand);
            font-weight: 600;
            letter-spacing: 5px;
            text-transform: uppercase;
            background: linear-gradient(135deg, #ffffff 0%, #e8d5b7 50%, #c9a96e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
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
            color: var(--mystes-glow);
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

        /* Loading screen logo */
        .loading-logo {
            width: 120px;
            height: 120px;
            position: relative;
            filter: drop-shadow(0 0 20px rgba(66, 214, 138, 0.4));
        }

        @keyframes pulse-glow {
            0%, 100% { opacity: 0.7; filter: drop-shadow(0 0 15px rgba(66, 214, 138, 0.3)); }
            50% { opacity: 1; filter: drop-shadow(0 0 30px rgba(66, 214, 138, 0.6)); }
        }

        .loading-screen::before { display: none; }
        .loading-screen::after { display: none; }

        .loading-text {
            font-family: var(--font-brand);
            margin-top: var(--space-xl);
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 10px;
            background: linear-gradient(135deg, #ffffff 0%, #e8d5b7 40%, #ffffff 60%, #c9a96e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
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
            background: linear-gradient(135deg, var(--mystes-glow), var(--mystes-cyan));
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
    <!-- 3D Aurora Background — Three.js WebGL -->
    <canvas id="aurora-canvas" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;"></canvas>

    <!-- Divine Eyes — Canvas 2D -->
    <canvas id="divine-eyes-canvas" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:2;pointer-events:none;"></canvas>

    <!-- Loading Screen -->
    <div class="loading-screen" id="loadingScreen">
        <img class="loading-logo" src="/static/favicon-eyes.svg" alt="MYSTES" style="width:120px;height:120px;opacity:0.9;animation:pulse-glow 2s ease-in-out infinite;">
        <div class="loading-text">MYSTES</div>
    </div>

    <!-- Navigation -->
    <nav class="nav" id="nav">
        <a href="/" class="nav-brand">
            <img class="nav-logo" src="/static/favicon-eyes.svg" alt="MYSTES" style="width:36px;height:36px;border-radius:8px;">
            <span class="nav-wordmark">MYSTES</span>
        </a>

        <button class="nav-toggle" id="navToggle" aria-label="Toggle navigation">
            <span></span><span></span><span></span>
        </button>

        <div class="nav-links" id="navLinks">
            {% if current_user.is_authenticated %}
                <a href="/ai" class="nav-link">AI Search</a>
                <a href="/dashboard" class="nav-link">Dashboard</a>
                <a href="/deals" class="nav-link">Deals</a>
                <a href="/wallet" class="nav-link">Wallet</a>
                <div class="nav-more-wrapper">
                    <button class="nav-link nav-more-btn" id="navMoreBtn">More &#9662;</button>
                    <div class="nav-more-menu" id="navMoreMenu">
                        <a href="/travelers" class="nav-more-link">Travelers</a>
                        {% if current_user.is_admin %}<a href="/admin/nodes" class="nav-more-link" style="color: var(--mystes-glow);">Nodes</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/portal" class="nav-more-link" style="color: var(--mystes-glow);">Proxy Portal</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/helper" class="nav-more-link" style="color: var(--mystes-glow);">Helper</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/earn" class="nav-more-link" style="color: var(--mystes-glow);">Earn</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/setup" class="nav-more-link" style="color: var(--mystes-glow);">Setup Guides</a>{% endif %}
                        {% if current_user.is_admin %}<a href="/admin" class="nav-more-link" style="color: var(--mystes-glow);">Admin</a>{% endif %}
                    </div>
                </div>
                <a href="/logout" class="nav-link nav-cta">Logout</a>
            {% else %}
                <a href="/" class="nav-link">Search</a>
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
                <strong>Join the Mystes Network</strong>
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
                <span class="onboard-banner-sub">One click to start earning. Your browser becomes part of the Mystes search network.</span>
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
            if(d.success){document.getElementById('onboardBanner').innerHTML='<div class=\"onboard-banner-inner\"><div class=\"onboard-banner-text\"><strong>Node Active!</strong> <span class=\"onboard-banner-sub\">You are now part of the Mystes network. Node ID: '+d.node_id+'</span></div></div>';setTimeout(()=>{document.getElementById('onboardBanner').style.display='none';},4000);}
            else{btn.textContent='Become a Node';btn.disabled=false;alert(d.error||'Onboarding failed');}
        }).catch(()=>{btn.textContent='Become a Node';btn.disabled=false;});
    }
    </script>
    {% endif %}

    <style>
    .onboard-banner{position:fixed;top:60px;left:0;right:0;z-index:999;background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(138,43,226,0.12));backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(124,58,237,0.3);padding:0;animation:bannerSlide .4s ease-out;}
    @keyframes bannerSlide{from{transform:translateY(-100%);opacity:0}to{transform:translateY(0);opacity:1}}
    .onboard-banner-inner{max-width:1200px;margin:0 auto;padding:12px 24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap;}
    .onboard-banner-text{flex:1;min-width:200px;font-family:'Rajdhani',sans-serif;}
    .onboard-banner-text strong{color:var(--mystes-glow,#7c3aed);font-size:1.05rem;display:block;line-height:1.2;}
    .onboard-banner-sub{color:var(--text-secondary,#999);font-size:0.88rem;}
    .onboard-banner-action{flex-shrink:0;}
    .onboard-banner-close{background:none;border:none;color:var(--text-secondary,#999);font-size:1.4rem;cursor:pointer;padding:0 0 0 12px;line-height:1;opacity:0.7;}
    .onboard-banner-close:hover{opacity:1;color:var(--text-bright,#fff);}
    .onboard-btn{background:linear-gradient(135deg,#7c3aed,#8b5cf6);color:#fff;border:none;padding:10px 28px;border-radius:25px;font-family:'Rajdhani',sans-serif;font-weight:600;font-size:0.95rem;cursor:pointer;transition:all .2s;}
    .onboard-btn:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(124,58,237,0.4);}
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
                    <img class="footer-logo" src="/static/favicon-eyes.svg" alt="MYSTES" style="width:40px;height:40px;opacity:0.7;border-radius:8px;">
                    <span class="footer-wordmark">MYSTES</span>
                </div>
                <div class="footer-links">
                    <a href="/terms" class="footer-link">Terms</a>
                    <a href="/privacy" class="footer-link">Privacy</a>
                    <a href="/about" class="footer-link">About</a>
                </div>
            </div>
            <div class="footer-copy">
                &copy; 2026 MYSTES &mdash; <span class="footer-tagline">Breaking borders. Connecting humanity.</span>
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

        // PWA Service Worker registration — force update on every load
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', function() {
                navigator.serviceWorker.register('/service-worker.js')
                    .then(function(reg) {
                        console.log('Mystes SW registered, scope:', reg.scope);
                        reg.update();
                    })
                    .catch(function(err) {
                        console.log('Mystes SW registration failed:', err);
                    });
            });
        }

        // iOS standalone detection — adjust viewport for notch
        if (window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches) {
            document.documentElement.classList.add('pwa-standalone');
        }
    </script>

    <!-- Mystes Node Client (Build #91) — auto-initializes node for all users -->
    <script src="/static/js/mystes-node-client.js"></script>
    <script src="/static/js/mystes-node-capture.js"></script>
    <script src="/static/js/mystes-node-bridge.js"></script>
    {% if current_user.is_authenticated and current_user.is_helper_node %}
    <script>
        window.__MYSTES_NODE_CONFIG__ = {
            serverUrl: window.location.origin,
            helperToken: "{{ helper_token_for_node|default('') }}",
            consent: {{ node_consent_json|default('{}')|safe }}
        };
        if (window.__MYSTES_NODE_CONFIG__.helperToken) {
            autoInitMystesNode().catch(function(e) {
                console.warn('[MystesNode] Auto-init failed:', e.message);
            });
        }
    </script>
    {% endif %}

    <!-- Three.js 3D Aurora Scene -->
    <script src="/static/js/aurora-scene.js" defer></script>

    <!-- Divine Eyes -->
    <script src="/static/js/divine-eyes.js" defer></script>

    <!-- GSAP Scroll Animations -->
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') return;
        gsap.registerPlugin(ScrollTrigger);

        // Hero section — cinematic staggered entrance
        var hero = document.querySelector('.hero');
        if (hero) {
            gsap.from('.hero h1', { y: 60, opacity: 0, duration: 1.4, ease: 'power3.out', delay: 0.3 });
            gsap.from('.hero-subtitle', { y: 40, opacity: 0, duration: 1.2, ease: 'power3.out', delay: 0.6 });
            gsap.from('.hero-search', { y: 30, opacity: 0, duration: 1, ease: 'power3.out', delay: 0.85 });
        }

        // Cards — slide up + fade on scroll into view
        gsap.utils.toArray('.card').forEach(function(card) {
            gsap.from(card, {
                scrollTrigger: { trigger: card, start: 'top 88%', toggleActions: 'play none none none' },
                y: 50, opacity: 0, duration: 0.7, ease: 'power2.out'
            });
        });

        // Section headings — fade in on scroll
        gsap.utils.toArray('.container h2, .container h3').forEach(function(el) {
            gsap.from(el, {
                scrollTrigger: { trigger: el, start: 'top 92%' },
                y: 25, opacity: 0, duration: 0.6, ease: 'power2.out'
            });
        });

        // Buttons — subtle entrance
        gsap.utils.toArray('.btn, .nav-cta').forEach(function(btn) {
            btn.addEventListener('mouseenter', function() {
                gsap.to(btn, { scale: 1.05, duration: 0.2, ease: 'power2.out' });
            });
            btn.addEventListener('mouseleave', function() {
                gsap.to(btn, { scale: 1, duration: 0.3, ease: 'power2.out' });
            });
        });
    });
    </script>
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

    .hero-search {
        display: flex;
        max-width: 560px;
        width: 100%;
        margin: 0 auto 30px;
        border-radius: 60px;
        overflow: hidden;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        opacity: 0;
        animation: fadeInUp 0.8s var(--ease-out) 0.4s forwards;
        transition: border-color 0.3s, box-shadow 0.3s;
    }

    .hero-search:focus-within {
        border-color: rgba(124, 58, 237, 0.5);
        box-shadow: 0 0 30px rgba(124, 58, 237, 0.15);
    }

    .hero-search-input {
        flex: 1;
        background: transparent;
        border: none;
        outline: none;
        padding: 16px 28px;
        font-size: 16px;
        font-family: var(--font-sans);
        color: var(--text-bright);
        letter-spacing: 0.3px;
    }

    .hero-search-input::placeholder {
        color: rgba(255, 255, 255, 0.35);
    }

    .hero-search-btn {
        background: linear-gradient(135deg, var(--mystes-purple), var(--mystes-deep));
        border: none;
        padding: 16px 32px;
        color: white;
        font-family: var(--font-display);
        font-size: 14px;
        font-weight: 500;
        letter-spacing: 2px;
        text-transform: uppercase;
        cursor: pointer;
        transition: opacity 0.3s;
    }

    .hero-search-btn:hover {
        opacity: 0.85;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(30px); }
        to { opacity: 1; transform: translateY(0); }
    }

</style>

<section class="hero">
    <h1><span class="mystes-brand">MYSTES</span></h1>

    <p class="hero-subtitle">Where would you like to travel?</p>

    <form class="hero-search" action="/ai" method="GET" autocomplete="off">
        <input type="text" name="q" class="hero-search-input" placeholder="Where do you want to go?" />
        <button type="submit" class="hero-search-btn">Search</button>
    </form>
</section>
'''
