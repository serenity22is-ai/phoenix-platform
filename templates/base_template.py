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
MYSTES_LOGO_SVG = '<img src="/static/favicon-eyes.svg?v=3" alt="MYSTES" style="width:60px;height:60px;">'

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} | MYSTES</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="MYSTES - AI-powered travel intelligence. Compare flights, hotels, and more across 102 markets. Wholesale prices, real savings.">
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
    <link rel="icon" type="image/svg+xml" href="/static/favicon-eyes.svg?v=3">
    <link rel="icon" type="image/x-icon" href="/favicon.ico">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <!-- 3D Scene & Scroll Animations -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js" defer></script>
    <!-- Google Identity Services (One Tap + Sign-In button) -->
    {% if google_client_id %}
    <script src="https://accounts.google.com/gsi/client" async defer></script>
    {% endif %}
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

        /* Loading screen geometric logo */
        .loading-logo {
            width: 140px;
            height: 140px;
            color: rgba(160, 120, 200, 0.8);
            animation: geoSpin 40s linear infinite;
            filter: drop-shadow(0 0 15px rgba(139, 45, 91, 0.6))
                    drop-shadow(0 0 30px rgba(100, 60, 180, 0.4));
            position: relative;
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

        /* ============================================
           TOAST NOTIFICATION SYSTEM
           ============================================ */
        #toast-container {
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
        }

        .toast {
            pointer-events: auto;
            min-width: 300px;
            max-width: 420px;
            padding: 14px 20px;
            border-radius: 12px;
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 500;
            line-height: 1.4;
            display: flex;
            align-items: flex-start;
            gap: 12px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            transform: translateX(120%);
            opacity: 0;
            transition: all 0.4s var(--ease-out);
        }

        .toast.show {
            transform: translateX(0);
            opacity: 1;
        }

        .toast.hiding {
            transform: translateX(120%);
            opacity: 0;
        }

        .toast-icon {
            font-size: 18px;
            flex-shrink: 0;
            margin-top: 1px;
        }

        .toast-content {
            flex: 1;
            color: #fff;
        }

        .toast-close {
            background: none;
            border: none;
            color: rgba(255,255,255,0.6);
            font-size: 18px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
            flex-shrink: 0;
        }

        .toast-close:hover {
            color: #fff;
        }

        .toast-success {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.9), rgba(5, 150, 105, 0.85));
            border: 1px solid rgba(52, 211, 153, 0.3);
        }

        .toast-error {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.9), rgba(185, 28, 28, 0.85));
            border: 1px solid rgba(248, 113, 113, 0.3);
        }

        .toast-info {
            background: linear-gradient(135deg, rgba(124, 58, 237, 0.9), rgba(109, 40, 217, 0.85));
            border: 1px solid rgba(167, 139, 250, 0.3);
        }

        .toast-warning {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.9), rgba(217, 119, 6, 0.85));
            border: 1px solid rgba(251, 191, 36, 0.3);
        }

        @media (max-width: 600px) {
            #toast-container {
                top: 70px;
                right: 10px;
                left: 10px;
            }
            .toast {
                min-width: unset;
                max-width: unset;
            }
        }
    </style>
</head>
<body>
    <!-- Toast Notifications -->
    <div id="toast-container"></div>

    <!-- 3D Aurora Background — Three.js WebGL -->
    <canvas id="aurora-canvas" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;"></canvas>

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
        <div class="loading-text">MYSTES</div>
    </div>

    <!-- Navigation -->
    <nav class="nav" id="nav">
        <a href="/" class="nav-brand">
            <svg class="nav-logo sacred-geo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
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
                    <circle cx="50" cy="50" r="22" class="geo-ring geo-r3"/>
                    <circle cx="50" cy="50" r="3" class="geo-center" fill="currentColor"/>
                </g>
            </svg>
            <span class="nav-wordmark">MYSTES</span>
        </a>

        <button class="nav-toggle" id="navToggle" aria-label="Toggle navigation">
            <span></span><span></span><span></span>
        </button>

        <div class="nav-links" id="navLinks">
            {% if current_user.is_authenticated %}
                <a href="/flights" class="nav-link">Flights</a>
                <a href="/hotels" class="nav-link">Hotels</a>
                <a href="/dashboard" class="nav-link">Dashboard</a>
                <a href="/rewards" class="nav-link" style="color: var(--mystes-glow);">Rewards</a>
                <div class="nav-more-wrapper">
                    <button class="nav-link nav-more-btn" id="navMoreBtn">More &#9662;</button>
                    <div class="nav-more-menu" id="navMoreMenu">
                        {% if feature_rentals %}<a href="/cars" class="nav-more-link">Cars</a>{% endif %}
                        {% if feature_activities %}<a href="/activities" class="nav-more-link">Activities</a>{% endif %}
                        <a href="/deals" class="nav-more-link">Deals</a>
                        <a href="/ai" class="nav-more-link">AI Search</a>
                        {% if feature_trip_planner %}<a href="/trips" class="nav-more-link">My Trips</a>{% endif %}
                        {% if feature_wishlist %}<a href="/collections" class="nav-more-link">Collections</a>{% endif %}
                        {% if feature_friends %}<a href="/friends" class="nav-more-link">Friends</a>{% endif %}
                        <a href="/travelers" class="nav-more-link">Travelers</a>
                        <a href="/business" class="nav-more-link" style="color: var(--mystes-silver);">Business</a>
                        {% if current_user.is_admin %}<a href="/admin" class="nav-more-link" style="color: var(--mystes-glow);">Admin</a>{% endif %}
                    </div>
                </div>
                <a href="/logout" class="nav-link nav-cta">Logout</a>
            {% else %}
                <a href="/flights" class="nav-link">Flights</a>
                <a href="/hotels" class="nav-link">Hotels</a>
                <a href="/deals" class="nav-link">Deals</a>
                <a href="/login" class="nav-link">Login</a>
                <a href="/register" class="nav-link nav-cta">Get Started</a>
            {% endif %}
        </div>
    </nav>

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
                            <circle cx="50" cy="50" r="22" class="geo-ring geo-r3"/>
                            <circle cx="50" cy="50" r="3" class="geo-center" fill="currentColor"/>
                        </g>
                    </svg>
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

        // Hide loading screen — runs immediately (script is at bottom of body, DOM is ready)
        setTimeout(function() {
            document.getElementById('loadingScreen').classList.add('hidden');
        }, 1200);

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

        // Toast notification system — replaces all alert() calls globally
        window._originalAlert = window.alert;
        window.alert = function(msg) {
            if (typeof window.showToast === 'function') {
                // Detect toast type from message content
                var type = 'info';
                var lmsg = (msg || '').toLowerCase();
                if (lmsg.indexOf('error') !== -1 || lmsg.indexOf('failed') !== -1 || lmsg.indexOf('could not') !== -1) type = 'error';
                else if (lmsg.indexOf('success') !== -1 || lmsg.indexOf('verified') !== -1 || lmsg.indexOf('saved') !== -1 || lmsg.indexOf('completed') !== -1) type = 'success';
                else if (lmsg.indexOf('please') !== -1 || lmsg.indexOf('warning') !== -1) type = 'warning';
                window.showToast(msg, type);
            } else {
                window._originalAlert(msg);
            }
        };

        window.showToast = function(message, type, duration) {
            type = type || 'info';
            duration = duration || 4000;
            var icons = { success: '&#10003;', error: '&#10007;', warning: '&#9888;', info: '&#8505;' };
            var container = document.getElementById('toast-container');
            var toast = document.createElement('div');
            toast.className = 'toast toast-' + type;
            toast.innerHTML = '<span class="toast-icon">' + (icons[type] || icons.info) + '</span>' +
                '<span class="toast-content">' + message + '</span>' +
                '<button class="toast-close" onclick="this.parentElement.classList.add(&apos;hiding&apos;);setTimeout(function(){this.remove()}.bind(this.parentElement),400)">&times;</button>';
            container.appendChild(toast);
            requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                    toast.classList.add('show');
                });
            });
            setTimeout(function() {
                if (toast.parentElement) {
                    toast.classList.add('hiding');
                    toast.classList.remove('show');
                    setTimeout(function() { if (toast.parentElement) toast.remove(); }, 400);
                }
            }, duration);
        };

        // Auto-convert Flask flash messages to toasts
        (function() {
            var alerts = document.querySelectorAll('.alert');
            alerts.forEach(function(alert) {
                var type = 'info';
                if (alert.classList.contains('alert-success')) type = 'success';
                else if (alert.classList.contains('alert-error') || alert.classList.contains('alert-danger')) type = 'error';
                else if (alert.classList.contains('alert-warning')) type = 'warning';
                showToast(alert.textContent.trim(), type, 5000);
                alert.style.display = 'none';
            });
        })();

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

    <!-- Google One Tap — auto-prompt for logged-out users -->
    {% if google_client_id and not current_user.is_authenticated %}
    <script>
    window.addEventListener('load', function() {
        if (typeof google === 'undefined' || !google.accounts) return;
        google.accounts.id.initialize({
            client_id: '{{ google_client_id }}',
            callback: function(response) {
                // POST credential JWT to our callback endpoint
                fetch('/auth/google/callback', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'credential=' + encodeURIComponent(response.credential)
                }).then(function(r) { return r.json ? r.json() : r.text(); })
                  .then(function() { window.location.reload(); })
                  .catch(function() { window.location.href = '/auth/google/start'; });
            },
            auto_select: false,
            cancel_on_tap_outside: true,
            context: 'signin'
        });
        // Show One Tap prompt (non-intrusive)
        google.accounts.id.prompt();
    });
    </script>
    {% endif %}

    <!-- Three.js 3D Aurora Scene -->
    <script src="/static/js/aurora-scene.js?v=4" defer></script>

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


# Flight search homepage — direct Picasso overlay
HOME_HERO = '''
<style>
    .home-page { min-height: calc(100vh - 80px); padding: 60px 20px 80px; }

    /* Brand header */
    .home-brand { text-align: center; margin-bottom: 48px; opacity: 0; animation: fadeInUp 0.6s var(--ease-out) 0.1s forwards; }
    .home-brand h1 {
        font-family: var(--font-display); font-size: clamp(48px, 10vw, 96px); font-weight: 600;
        letter-spacing: 12px; text-transform: uppercase; color: var(--text-bright); margin: 0 0 12px;
        text-shadow: 0 4px 60px rgba(124, 58, 237, 0.3);
    }
    .home-brand .tagline {
        font-family: var(--font-sans); font-size: 18px; color: var(--text-secondary);
        letter-spacing: 4px; text-transform: uppercase; font-weight: 300; margin: 0;
    }

    /* Vertical cards grid */
    .verticals-grid {
        max-width: 900px; margin: 0 auto 48px;
        display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px;
        opacity: 0; animation: fadeInUp 0.6s var(--ease-out) 0.25s forwards;
    }
    .vertical-card {
        position: relative; padding: 36px 28px; border-radius: 16px;
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
        backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
        text-decoration: none; color: inherit; display: flex; flex-direction: column;
        align-items: center; text-align: center; gap: 14px;
        transition: border-color 0.3s, background 0.3s, transform 0.3s;
    }
    .vertical-card:hover {
        border-color: rgba(124,58,237,0.5); background: rgba(124,58,237,0.08);
        transform: translateY(-4px);
    }
    .vertical-card.coming-soon { opacity: 0.5; pointer-events: none; }
    .vc-icon { font-size: 40px; line-height: 1; }
    .vc-name {
        font-family: var(--font-display); font-size: 20px; font-weight: 600;
        letter-spacing: 4px; text-transform: uppercase; color: var(--text-bright);
    }
    .vc-desc { font-size: 13px; color: var(--text-secondary); line-height: 1.4; }
    .vc-badge {
        position: absolute; top: 12px; right: 12px;
        padding: 3px 10px; border-radius: 20px; font-size: 10px; font-weight: 700;
        letter-spacing: 1px; text-transform: uppercase;
    }
    .vc-badge.live { background: rgba(52, 211, 153, 0.2); color: #34d399; }
    .vc-badge.soon { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.4); }

    /* Powered by badge */
    .home-powered {
        text-align: center; margin-top: 32px;
        opacity: 0; animation: fadeInUp 0.6s var(--ease-out) 0.4s forwards;
    }
    .home-powered span {
        font-size: 12px; color: rgba(255,255,255,0.25); letter-spacing: 2px;
        text-transform: uppercase; font-family: var(--font-sans);
    }

    @keyframes fadeInUp { from { opacity:0; transform: translateY(20px); } to { opacity:1; transform: translateY(0); } }

    @media (max-width: 600px) {
        .verticals-grid { grid-template-columns: 1fr; gap: 14px; }
        .home-brand h1 { letter-spacing: 6px; }
    }
</style>

<section class="home-page">
    <div class="home-brand">
        <h1>MYSTES</h1>
        <p class="tagline">Travel Intelligence</p>
    </div>

    <div class="verticals-grid">
        <a href="/flights" class="vertical-card">
            <span class="vc-badge live">Live</span>
            <div class="vc-icon">&#9992;</div>
            <div class="vc-name">Flights</div>
            <div class="vc-desc">Search 102 markets for the cheapest fares</div>
        </a>

        <a href="/hotels" class="vertical-card">
            <span class="vc-badge live">Live</span>
            <div class="vc-icon">&#127976;</div>
            <div class="vc-name">Hotels</div>
            <div class="vc-desc">Best rates from 2M+ properties worldwide</div>
        </a>

        <a href="/activities" class="vertical-card coming-soon">
            <span class="vc-badge soon">Coming Soon</span>
            <div class="vc-icon">&#127947;</div>
            <div class="vc-name">Activities</div>
            <div class="vc-desc">Tours, experiences, and things to do</div>
        </a>

        <a href="/cars" class="vertical-card coming-soon">
            <span class="vc-badge soon">Coming Soon</span>
            <div class="vc-icon">&#128663;</div>
            <div class="vc-name">Cars</div>
            <div class="vc-desc">Rental cars and airport transfers</div>
        </a>
    </div>

    <div class="home-powered">
        <span>Powered by ANASTASiA</span>
    </div>
</section>
'''
