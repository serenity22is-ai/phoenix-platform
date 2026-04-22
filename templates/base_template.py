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
    <meta name="description" content="{{ meta_description|default('MYSTES - AI-powered travel intelligence. Compare flights, hotels, and more across 102 markets. Wholesale prices, real savings.') }}">
    <!-- OpenGraph / Social Sharing -->
    <meta property="og:title" content="{{ title }} | MYSTES">
    <meta property="og:description" content="{{ meta_description|default('AI-powered travel intelligence. Wholesale flights, hotels, cars, and activities across 102 markets.') }}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{{ request.url }}">
    <meta property="og:image" content="{{ request.url_root }}static/icons/icon-512x512.png">
    <meta property="og:site_name" content="MYSTES">
    <meta property="og:locale" content="en_US">
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{{ title }} | MYSTES">
    <meta name="twitter:description" content="{{ meta_description|default('AI-powered travel intelligence. Wholesale flights, hotels, cars, and activities across 102 markets.') }}">
    <meta name="twitter:image" content="{{ request.url_root }}static/icons/icon-512x512.png">
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
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <!-- Animations handled by CSS + IntersectionObserver (no external JS libraries) -->
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
            --font-brand: 'Space Grotesk', 'Inter', 'Segoe UI', sans-serif;

            /* Transitions */
            --ease-out: cubic-bezier(0.16, 1, 0.3, 1);

            /* Glass morphism tokens */
            --glass-bg: rgba(10, 6, 18, 0.85);
            --glass-bg-light: rgba(255, 255, 255, 0.04);
            --glass-border: rgba(255, 255, 255, 0.08);
            --glass-border-hover: rgba(124, 58, 237, 0.3);
            --glass-blur: blur(16px);

            /* Accent aliases */
            --accent: #C9A96E;
            --accent-purple: #7c3aed;
            --accent-teal: #14b8a6;

            /* Font alias */
            --font-body: var(--font-sans);

            /* Semantic colors */
            --danger-red: #ef4444;
            --warning-amber: #f59e0b;

            /* Border radius scale */
            --radius-sm: 6px;
            --radius-md: 8px;
            --radius-lg: 12px;
            --radius-xl: 16px;
            --radius-full: 100px;
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
           AURORA BACKGROUND - CSS Only (replaces Three.js)
           ============================================ */

        .aurora-bg {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 1;
            pointer-events: none;
            background: var(--deep-space);
            overflow: hidden;
        }

        .aurora-bg::before,
        .aurora-bg::after {
            content: '';
            position: absolute;
            width: 150%;
            height: 60%;
            border-radius: 50%;
            filter: blur(80px);
            opacity: 0.35;
            will-change: transform;
        }

        .aurora-bg::before {
            top: -10%;
            left: -25%;
            background: radial-gradient(ellipse, rgba(124,58,237,0.4) 0%, rgba(91,33,182,0.2) 40%, transparent 70%);
            animation: auroraFlow 30s ease-in-out infinite alternate;
        }

        .aurora-bg::after {
            top: 30%;
            right: -25%;
            background: radial-gradient(ellipse, rgba(20,184,166,0.15) 0%, rgba(8,145,178,0.1) 40%, transparent 70%);
            animation: auroraFlow 25s ease-in-out infinite alternate-reverse;
        }

        .aurora-stars {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 2;
            pointer-events: none;
            background-image:
                radial-gradient(2px 2px at 10% 15%, rgba(255,255,255,0.8), transparent),
                radial-gradient(1.5px 1.5px at 25% 45%, rgba(255,255,255,0.6), transparent),
                radial-gradient(2px 2px at 50% 20%, rgba(255,255,255,0.9), transparent),
                radial-gradient(1.5px 1.5px at 70% 65%, rgba(255,255,255,0.5), transparent),
                radial-gradient(1px 1px at 85% 30%, rgba(255,255,255,0.7), transparent),
                radial-gradient(1.5px 1.5px at 15% 80%, rgba(255,255,255,0.6), transparent),
                radial-gradient(2px 2px at 40% 90%, rgba(255,255,255,0.5), transparent),
                radial-gradient(1.5px 1.5px at 60% 8%, rgba(255,255,255,0.8), transparent),
                radial-gradient(1px 1px at 92% 75%, rgba(255,255,255,0.55), transparent),
                radial-gradient(1px 1px at 5% 55%, rgba(255,255,255,0.65), transparent),
                radial-gradient(1px 1px at 33% 72%, rgba(255,255,255,0.5), transparent),
                radial-gradient(2px 2px at 78% 12%, rgba(255,255,255,0.7), transparent),
                radial-gradient(1.5px 1.5px at 55% 50%, rgba(255,255,255,0.45), transparent),
                radial-gradient(1px 1px at 88% 88%, rgba(255,255,255,0.6), transparent),
                radial-gradient(1.5px 1.5px at 3% 35%, rgba(255,255,255,0.55), transparent),
                radial-gradient(1px 1px at 45% 5%, rgba(255,255,255,0.5), transparent),
                radial-gradient(2px 2px at 68% 42%, rgba(255,255,255,0.65), transparent),
                radial-gradient(1px 1px at 22% 95%, rgba(255,255,255,0.4), transparent),
                radial-gradient(1.5px 1.5px at 95% 55%, rgba(255,255,255,0.5), transparent),
                radial-gradient(1px 1px at 38% 28%, rgba(255,255,255,0.6), transparent);
            animation: starTwinkle 6s ease-in-out infinite alternate;
        }

        @keyframes auroraFlow {
            0% { transform: translate(0, 0) scale(1); }
            33% { transform: translate(3%, -2%) scale(1.03); }
            66% { transform: translate(-2%, 1%) scale(0.98); }
            100% { transform: translate(1%, -1%) scale(1.01); }
        }

        @keyframes starTwinkle {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; }
        }

        /* Reduce animation on low-power devices */
        @media (prefers-reduced-motion: reduce) {
            .aurora-bg::before, .aurora-bg::after, .aurora-stars { animation: none; }
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
        }

        .nav-logo:hover {
            color: rgba(180, 150, 220, 1);
            filter: drop-shadow(0 0 12px rgba(139, 45, 91, 0.8))
                    drop-shadow(0 0 24px rgba(100, 60, 180, 0.5))
                    drop-shadow(0 0 36px rgba(13, 79, 79, 0.3));
            transform: scale(1.1);
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
            transform: translateY(-4px);
            box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(124, 58, 237, 0.15);
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

        /* ============================================
           MYSTES COMPONENT LIBRARY
           Shared components — route files should use
           these instead of defining their own.
           ============================================ */

        /* --- Page Layouts --- */
        .mystes-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }
        .mystes-page-wide { max-width: 1100px; margin: 0 auto; padding: 0 16px; }

        .mystes-page-header {
            text-align: center;
            padding: 40px 0 10px;
        }
        .mystes-page-header h1 {
            font-family: var(--font-brand);
            font-size: clamp(28px, 6vw, 36px);
            font-weight: 700;
            letter-spacing: 4px;
            color: var(--text-bright);
            margin: 0 0 8px;
            text-transform: uppercase;
        }
        .mystes-page-header p {
            color: var(--text-muted);
            font-size: 15px;
            margin: 0;
        }

        /* --- Glass Card --- */
        .mystes-card {
            background: var(--glass-bg);
            backdrop-filter: var(--glass-blur);
            -webkit-backdrop-filter: var(--glass-blur);
            border: 1px solid var(--glass-border);
            border-radius: var(--radius-xl);
            padding: 24px;
            transition: border-color 0.3s var(--ease-out), transform 0.3s var(--ease-out), box-shadow 0.3s var(--ease-out);
        }
        .mystes-card:hover {
            border-color: var(--glass-border-hover);
        }
        .mystes-card.interactive:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
        }
        .mystes-card.compact { padding: 16px; }
        .mystes-card.flush { padding: 0; }

        /* --- Card Grid --- */
        .mystes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }
        .mystes-grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
        .mystes-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        .mystes-grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }

        @media (max-width: 768px) {
            .mystes-grid-2, .mystes-grid-3, .mystes-grid-4 { grid-template-columns: 1fr; }
        }

        /* --- Form Elements --- */
        .mystes-label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-family: var(--font-sans);
        }

        .mystes-input,
        .mystes-select,
        .mystes-textarea {
            width: 100%;
            padding: 12px 14px;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: var(--radius-md);
            color: var(--text-bright);
            font-family: var(--font-sans);
            font-size: 15px;
            transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
            box-sizing: border-box;
            outline: none;
        }
        .mystes-input:focus,
        .mystes-select:focus,
        .mystes-textarea:focus {
            background: rgba(255, 255, 255, 0.10);
            border-color: var(--accent-purple);
            box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.15);
        }
        .mystes-input::placeholder,
        .mystes-textarea::placeholder { color: rgba(255, 255, 255, 0.3); }
        .mystes-select option { background: #1a1a2e; color: #fff; }
        .mystes-textarea { resize: vertical; min-height: 60px; }

        .mystes-form-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        .mystes-form-grid .full-width { grid-column: 1 / -1; }

        @media (max-width: 640px) {
            .mystes-form-grid { grid-template-columns: 1fr; }
        }

        /* --- Buttons --- */
        .mystes-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 12px 24px;
            border: none;
            border-radius: var(--radius-md);
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 600;
            letter-spacing: 0.5px;
            cursor: pointer;
            transition: all 0.2s var(--ease-out);
            text-decoration: none;
            white-space: nowrap;
            line-height: 1.4;
        }
        .mystes-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }

        .mystes-btn-primary {
            background: linear-gradient(135deg, #7c3aed, #6d28d9);
            color: #fff;
            box-shadow: 0 4px 20px rgba(124, 58, 237, 0.3);
        }
        .mystes-btn-primary:hover:not(:disabled) {
            box-shadow: 0 8px 30px rgba(124, 58, 237, 0.4);
            transform: translateY(-1px);
        }

        .mystes-btn-gold {
            background: var(--accent);
            color: #000;
        }
        .mystes-btn-gold:hover:not(:disabled) {
            filter: brightness(1.1);
            transform: translateY(-1px);
        }

        .mystes-btn-ghost {
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: var(--text-muted);
        }
        .mystes-btn-ghost:hover:not(:disabled) {
            border-color: rgba(255, 255, 255, 0.3);
            color: var(--text-bright);
            background: rgba(255, 255, 255, 0.05);
        }

        .mystes-btn-danger {
            background: transparent;
            color: var(--danger-red);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }
        .mystes-btn-danger:hover:not(:disabled) {
            background: rgba(239, 68, 68, 0.1);
        }

        .mystes-btn-success {
            background: linear-gradient(135deg, #22c55e, #16a34a);
            color: #fff;
        }
        .mystes-btn-success:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 8px 30px rgba(34, 197, 94, 0.3);
        }

        .mystes-btn-lg { padding: 14px 32px; font-size: 15px; }
        .mystes-btn-sm { padding: 8px 16px; font-size: 13px; }
        .mystes-btn-full { width: 100%; }

        /* --- Badges --- */
        .mystes-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 10px;
            border-radius: var(--radius-full);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .mystes-badge-green { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.2); }
        .mystes-badge-purple { background: rgba(124, 58, 237, 0.15); color: #a78bfa; border: 1px solid rgba(124, 58, 237, 0.2); }
        .mystes-badge-amber { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.2); }
        .mystes-badge-red { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.2); }
        .mystes-badge-teal { background: rgba(20, 184, 166, 0.15); color: #14b8a6; border: 1px solid rgba(20, 184, 166, 0.2); }
        .mystes-badge-neutral { background: rgba(255, 255, 255, 0.1); color: var(--text-muted); }
        .mystes-badge-gold { background: rgba(201, 169, 110, 0.15); color: #C9A96E; border: 1px solid rgba(201, 169, 110, 0.2); }

        /* --- Spinner (replaces 15 duplicate @keyframes spin) --- */
        .mystes-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(124, 58, 237, 0.2);
            border-top-color: #7c3aed;
            border-radius: 50%;
            animation: mystes-spin 0.8s linear infinite;
        }
        .mystes-spinner-sm { width: 16px; height: 16px; border-width: 2px; }
        .mystes-spinner-white { border-color: rgba(255,255,255,0.3); border-top-color: #fff; }

        @keyframes mystes-spin { to { transform: rotate(360deg); } }

        /* --- Skeleton Loading --- */
        .mystes-skeleton {
            background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%);
            background-size: 200% 100%;
            animation: mystes-shimmer 1.5s infinite;
            border-radius: var(--radius-md);
        }
        @keyframes mystes-shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }

        /* --- Empty State --- */
        .mystes-empty {
            text-align: center;
            padding: 48px 20px;
            color: var(--text-muted);
        }
        .mystes-empty-icon {
            font-size: 48px;
            margin-bottom: 12px;
            opacity: 0.3;
        }
        .mystes-empty p { font-size: 14px; margin: 4px 0; }
        .mystes-empty a { color: var(--accent-purple); text-decoration: none; }

        /* --- Divider --- */
        .mystes-divider {
            border: none;
            height: 1px;
            background: rgba(255, 255, 255, 0.08);
            margin: 24px 0;
        }

        /* --- Modal --- */
        .mystes-modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.6);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            z-index: 5000;
            display: none;
            align-items: center;
            justify-content: center;
        }
        .mystes-modal-overlay.open { display: flex; }
        .mystes-modal {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: var(--radius-xl);
            padding: 32px;
            max-width: 480px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }

        /* --- Table --- */
        .mystes-table-wrap {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        .mystes-table {
            width: 100%;
            border-collapse: collapse;
        }
        .mystes-table th {
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--text-muted);
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .mystes-table td {
            padding: 12px 16px;
            color: var(--text-secondary);
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 14px;
        }
        .mystes-table tr:hover td { background: rgba(255, 255, 255, 0.02); }

        /* --- Scroll Reveal (replaces GSAP ScrollTrigger) --- */
        .reveal {
            opacity: 0;
            transform: translateY(24px);
            transition: opacity 0.6s var(--ease-out), transform 0.6s var(--ease-out);
        }
        .reveal.visible {
            opacity: 1;
            transform: translateY(0);
        }
        .reveal-stagger > .reveal:nth-child(1) { transition-delay: 0s; }
        .reveal-stagger > .reveal:nth-child(2) { transition-delay: 0.08s; }
        .reveal-stagger > .reveal:nth-child(3) { transition-delay: 0.16s; }
        .reveal-stagger > .reveal:nth-child(4) { transition-delay: 0.24s; }
        .reveal-stagger > .reveal:nth-child(5) { transition-delay: 0.32s; }
        .reveal-stagger > .reveal:nth-child(6) { transition-delay: 0.40s; }

        /* Hero entrance animation */
        .hero-entrance {
            opacity: 0;
            animation: heroIn 0.8s var(--ease-out) forwards;
        }
        .hero-entrance:nth-child(2) { animation-delay: 0.15s; }
        .hero-entrance:nth-child(3) { animation-delay: 0.3s; }

        @keyframes heroIn {
            from { opacity: 0; transform: translateY(40px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* --- Concierge Chat Widget --- */
        .concierge-bubble {
            position: fixed; bottom: 24px; right: 24px; width: 56px; height: 56px;
            background: var(--gold, #C9A96E); border-radius: 50%; cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 4px 20px rgba(201,169,110,0.4); z-index: 9999;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .concierge-bubble:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 28px rgba(201,169,110,0.6);
        }
        .concierge-panel {
            display: none; position: fixed; bottom: 90px; right: 24px; width: 340px; max-height: 480px;
            background: #16213e; border: 1px solid rgba(201,169,110,0.3); border-radius: var(--radius-xl);
            box-shadow: 0 8px 32px rgba(0,0,0,0.5); z-index: 9999; overflow: hidden;
            font-family: var(--font-body);
        }
        .concierge-panel.open { display: block; }
        .concierge-header {
            background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 16px 20px;
            border-bottom: 1px solid rgba(201,169,110,0.2); display: flex;
            align-items: center; justify-content: space-between;
        }
        .concierge-title {
            font-family: var(--font-brand); font-size: 14px; color: var(--gold, #C9A96E); letter-spacing: 1px;
        }
        .concierge-close { cursor: pointer; color: #888; font-size: 18px; background: none; border: none; padding: 4px; }
        .concierge-body { padding: 20px; max-height: 340px; overflow-y: auto; }
        .concierge-msg { color: #e0e0e0; font-size: 14px; line-height: 1.6; margin: 0 0 16px 0; }
        .concierge-options { display: flex; flex-direction: column; gap: 8px; }
        .concierge-cross-sell {
            display: none; margin-top: 16px; padding: 12px;
            background: rgba(128,90,213,0.15); border: 1px solid rgba(128,90,213,0.3); border-radius: var(--radius-md);
        }
        .concierge-cross-sell-msg { color: #b8a0d8; font-size: 12px; margin: 0; cursor: pointer; }
        .concierge-input-bar { padding: 12px 16px; border-top: 1px solid rgba(201,169,110,0.15); }
        .concierge-input-row { display: flex; gap: 8px; }
        .concierge-text-input {
            flex: 1; background: #0f1729; border: 1px solid rgba(201,169,110,0.2); border-radius: var(--radius-md);
            padding: 8px 12px; color: #e0e0e0; font-size: 13px; outline: none; font-family: var(--font-body);
        }
        .concierge-send {
            background: var(--gold, #C9A96E); border: none; border-radius: var(--radius-md);
            padding: 8px 14px; cursor: pointer; color: #1a1a2e; font-weight: 600; font-size: 13px;
        }
        .concierge-option-btn {
            background: rgba(201,169,110,0.15); border: 1px solid rgba(201,169,110,0.3); border-radius: var(--radius-md);
            padding: 10px 16px; color: #C9A96E; cursor: pointer; font-size: 13px; text-align: left;
            transition: background 0.2s; font-family: var(--font-body);
        }
        .concierge-option-btn:hover { background: rgba(201,169,110,0.25); }

        /* --- Cookie Consent Banner --- */
        .cookie-banner {
            display: none; position: fixed; bottom: 0; left: 0; right: 0; z-index: 10000;
            background: rgba(26,24,20,0.95); backdrop-filter: blur(12px); padding: 16px 24px;
            font-family: var(--font-body); color: #f5f1eb; font-size: 0.85rem;
            border-top: 1px solid rgba(67,97,238,0.3);
            align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap;
        }
        .cookie-banner.open { display: flex; }
        .cookie-banner a { color: #4361ee; text-decoration: underline; }
        .cookie-accept {
            padding: 8px 20px; background: #4361ee; color: white; border: none;
            border-radius: 6px; cursor: pointer; font-family: var(--font-body);
            font-size: 0.85rem; font-weight: 500; white-space: nowrap;
        }

        /* --- Utility Classes --- */
        .text-center { text-align: center; }
        .text-right { text-align: right; }
        .text-left { text-align: left; }
        .mt-0 { margin-top: 0; }
        .mt-sm { margin-top: 8px; }
        .mt-md { margin-top: 16px; }
        .mt-lg { margin-top: 24px; }
        .mt-xl { margin-top: 32px; }
        .mb-0 { margin-bottom: 0; }
        .mb-sm { margin-bottom: 8px; }
        .mb-md { margin-bottom: 16px; }
        .mb-lg { margin-bottom: 24px; }
        .gap-sm { gap: 8px; }
        .gap-md { gap: 16px; }
        .gap-lg { gap: 24px; }
        .flex { display: flex; }
        .flex-col { flex-direction: column; }
        .flex-between { display: flex; justify-content: space-between; align-items: center; }
        .flex-center { display: flex; align-items: center; }
        .flex-wrap { flex-wrap: wrap; }
        .inline-flex { display: inline-flex; align-items: center; gap: 8px; }
    </style>
</head>
<body>
    <!-- Toast Notifications -->
    <div id="toast-container"></div>

    <!-- Aurora Background — Pure CSS (replaced Three.js WebGL) -->
    <div class="aurora-bg"></div>
    <div class="aurora-stars"></div>

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
                        <a href="/bookings" class="nav-more-link">My Bookings</a>
                        {% if feature_rentals %}<a href="/cars" class="nav-more-link">Cars</a>{% endif %}
                        {% if feature_activities %}<a href="/activities" class="nav-more-link">Activities</a>{% endif %}
                        <a href="/insurance" class="nav-more-link">Insurance</a>
                        <a href="/deals" class="nav-more-link">Deals</a>
                        <a href="/ai" class="nav-more-link">AI Search</a>
                        {% if feature_trip_planner %}<a href="/trips" class="nav-more-link">My Trips</a>{% endif %}
                        {% if feature_wishlist %}<a href="/collections" class="nav-more-link">Collections</a>{% endif %}
                        {% if feature_friends %}<a href="/friends" class="nav-more-link">Friends</a>{% endif %}
                        <a href="/travelers" class="nav-more-link">Travelers</a>
                        <a href="/social" class="nav-more-link">Social</a>
                        <a href="/referral" class="nav-more-link" style="color: #4ade80;">Referrals</a>
                        <a href="/corporate" class="nav-more-link">Corporate</a>
                        <a href="/carts" class="nav-more-link">Shared Carts</a>
                        <a href="/arbitrate" class="nav-more-link" style="color: #f59e0b;">Arbitrate</a>
                        <a href="/business" class="nav-more-link" style="color: var(--mystes-silver);">Business</a>
                        <a href="/apai" class="nav-more-link" style="color: #a78bfa;">APAi</a>
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
                    <a href="/pricing" class="footer-link">Pricing</a>
                    <a href="/faq" class="footer-link">FAQ</a>
                    <a href="/contact" class="footer-link">Contact</a>
                    <a href="/about" class="footer-link">About</a>
                    <a href="/terms" class="footer-link">Terms</a>
                    <a href="/privacy" class="footer-link">Privacy</a>
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

        // Hide loading screen — flash sacred geometry briefly then fade out
        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                document.getElementById('loadingScreen').classList.add('hidden');
            });
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

    <!-- Scroll Reveal — IntersectionObserver (replaces GSAP + Three.js) -->
    <script>
    (function() {
        if (!('IntersectionObserver' in window)) return;
        var observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
        document.querySelectorAll('.reveal, .card, .deal, .stat-card, .mystes-card').forEach(function(el) {
            if (!el.classList.contains('reveal')) el.classList.add('reveal');
            observer.observe(el);
        });
    })();
    </script>

    <!-- MYSTES Concierge Chat Bubble (Build #181) — Zero AI cost -->
    <div id="concierge-bubble" class="concierge-bubble" onclick="toggleConcierge()">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1a1a2e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
    </div>

    <div id="concierge-panel" class="concierge-panel">
        <div class="concierge-header">
            <span class="concierge-title">MYSTES CONCIERGE</span>
            <button class="concierge-close" onclick="toggleConcierge()">&times;</button>
        </div>
        <div id="concierge-body" class="concierge-body">
            <p id="concierge-msg" class="concierge-msg"></p>
            <div id="concierge-options" class="concierge-options"></div>
            <div id="concierge-cross-sell" class="concierge-cross-sell">
                <p id="cross-sell-msg" class="concierge-cross-sell-msg"></p>
            </div>
        </div>
        <div class="concierge-input-bar">
            <div class="concierge-input-row">
                <input id="concierge-input" class="concierge-text-input" type="text" placeholder="Type a question..."
                    onkeydown="if(event.key==='Enter')sendConciergeText()">
                <button class="concierge-send" onclick="sendConciergeText()">Send</button>
            </div>
        </div>
    </div>

    <script>
    // Page context detection (Build #183) — zero cost, pure URL parsing
    const _pageContext = (function() {
        const path = window.location.pathname;
        const params = new URLSearchParams(window.location.search);
        let vertical = '';
        let pageType = 'browse';
        if (path.startsWith('/flights')) vertical = 'flight';
        else if (path.startsWith('/hotels')) vertical = 'hotel';
        else if (path.startsWith('/cars')) vertical = 'car';
        else if (path.startsWith('/activities')) vertical = 'activity';
        else if (path.startsWith('/book/')) { vertical = 'booking'; pageType = 'checkout'; }
        else if (path.startsWith('/booking-confirmation/')) { pageType = 'confirmation'; }
        else if (path.startsWith('/trips')) { vertical = 'trip'; pageType = 'planning'; }
        return {
            vertical: vertical,
            page_type: pageType,
            destination: params.get('destination') || params.get('city') || '',
            date: params.get('departure_date') || params.get('check_in') || params.get('pickup_date') || '',
            return_date: params.get('return_date') || params.get('check_out') || params.get('dropoff_date') || '',
            path: path,
        };
    })();
    function trackCrossSell(eventType, recommendedVertical) {
        fetch('/api/analytics/cross-sell', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event_type: eventType, source_vertical: _pageContext.vertical, recommended_vertical: recommendedVertical, page_url: window.location.pathname})
        }).catch(() => {});
    }
    let _conciergeFlow = 'welcome';
    function toggleConcierge() {
        const p = document.getElementById('concierge-panel');
        if (!p.classList.contains('open')) {
            p.classList.add('open');
            const flowMap = {flight:'flight_search', hotel:'hotel_search', car:'car_search', activity:'activity_search'};
            const autoFlow = flowMap[_pageContext.vertical] || 'welcome';
            fetchConcierge(autoFlow);
        } else { p.classList.remove('open'); }
    }
    function fetchConcierge(flowId, option, freetext) {
        _conciergeFlow = flowId;
        fetch('/api/concierge/message', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({flow_id: flowId, selected_option: option, freetext: freetext, page_context: _pageContext})
        }).then(r => r.json()).then(renderConcierge).catch(() => {
            document.getElementById('concierge-msg').textContent = 'Something went wrong. Please try again.';
        });
    }
    function renderConcierge(data) {
        if (data.type === 'redirect' && data.redirect_url) {
            if (data.redirect_url === '/ai') {
                fetch('/api/concierge/escalate', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({concierge_context: {flow_id: _conciergeFlow, vertical: _pageContext.vertical, destination: _pageContext.destination, date: _pageContext.date}})
                }).then(r => r.json()).then(d => {
                    if (d.allowed) window.location.href = d.redirect;
                    else { document.getElementById('concierge-msg').textContent = d.message || 'Upgrade to Travel+ for AI chat'; }
                });
                return;
            }
            window.location.href = data.redirect_url; return;
        }
        document.getElementById('concierge-msg').textContent = data.message || '';
        const opts = document.getElementById('concierge-options');
        opts.innerHTML = '';
        (data.options || []).forEach(o => {
            const btn = document.createElement('button');
            btn.textContent = o.label;
            btn.className = 'concierge-option-btn';
            btn.onclick = () => {
                if (o.redirect_url) {
                    if (o.redirect_url === '/ai') {
                        fetch('/api/concierge/escalate', {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({concierge_context: {flow_id: _conciergeFlow, vertical: _pageContext.vertical, destination: _pageContext.destination, date: _pageContext.date}})
                        }).then(r => r.json()).then(d => {
                            if (d.allowed) window.location.href = d.redirect;
                            else { document.getElementById('concierge-msg').textContent = d.message || 'Upgrade to Travel+ for AI chat'; }
                        });
                        return;
                    }
                    window.location.href = o.redirect_url; return;
                }
                if (o.next_flow) { fetchConcierge(o.next_flow); return; }
                fetchConcierge(data.flow_id || _conciergeFlow, o.id);
            };
            opts.appendChild(btn);
        });
        const cs = document.getElementById('concierge-cross-sell');
        if (data.cross_sell) {
            cs.style.display = 'block';
            const csMsg = document.getElementById('cross-sell-msg');
            csMsg.textContent = data.cross_sell.message;
            trackCrossSell('impression', data.cross_sell.vertical || '');
            if (data.cross_sell.link) {
                csMsg.onclick = () => { trackCrossSell('click', data.cross_sell.vertical || ''); window.location.href = data.cross_sell.link; };
            } else {
                csMsg.onclick = () => fetchConcierge(data.cross_sell.flow_id || 'welcome');
            }
        } else { cs.style.display = 'none'; }
    }
    function sendConciergeText() {
        const inp = document.getElementById('concierge-input');
        const text = inp.value.trim();
        if (!text) return;
        inp.value = '';
        fetchConcierge(_conciergeFlow, null, text);
    }
    </script>
    <script src="/static/js/mystes-native.js"></script>

    <!-- Build #217: Cookie Consent Banner (GDPR/CCPA) -->
    <div id="cookie-consent" class="cookie-banner">
        <span>We use essential cookies for site functionality. No advertising or tracking cookies.
            <a href="/cookies">Cookie Policy</a>
        </span>
        <button class="cookie-accept" onclick="acceptCookies()">Accept</button>
    </div>
    <script>
    (function(){
        if(!localStorage.getItem('mystes_cookie_consent')){
            document.getElementById('cookie-consent').classList.add('open');
        }
    })();
    function acceptCookies(){
        localStorage.setItem('mystes_cookie_consent','accepted');
        document.getElementById('cookie-consent').classList.remove('open');
    }
    </script>
</body>
</html>
'''


# Flight search homepage — direct Picasso overlay
HOME_HERO = '''
<style>
    .home-page { min-height: calc(100vh - 80px); padding: 60px 20px 80px; }

    .home-brand { text-align: center; margin-bottom: 48px; }
    .home-brand h1 {
        font-family: var(--font-display); font-size: clamp(48px, 10vw, 96px); font-weight: 600;
        letter-spacing: 12px; text-transform: uppercase; color: var(--text-bright); margin: 0 0 12px;
        text-shadow: 0 4px 60px rgba(124, 58, 237, 0.3);
    }
    .home-brand .tagline {
        font-family: var(--font-sans); font-size: 18px; color: var(--text-muted);
        letter-spacing: 4px; text-transform: uppercase; font-weight: 300; margin: 0;
    }

    .verticals-grid {
        max-width: 900px; margin: 0 auto 48px;
        display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px;
    }
    .vertical-card {
        position: relative; padding: 36px 28px;
        background: var(--glass-bg-light); border: 1px solid var(--glass-border);
        border-radius: var(--radius-xl);
        backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
        text-decoration: none; color: inherit; display: flex; flex-direction: column;
        align-items: center; text-align: center; gap: 14px;
        transition: border-color 0.3s, background 0.3s, transform 0.3s;
    }
    .vertical-card:hover {
        border-color: var(--glass-border-hover); background: rgba(124,58,237,0.08);
        transform: translateY(-4px);
    }
    .vertical-card.coming-soon { opacity: 0.5; pointer-events: none; }
    .vc-icon { font-size: 40px; line-height: 1; }
    .vc-name {
        font-family: var(--font-display); font-size: 20px; font-weight: 600;
        letter-spacing: 4px; text-transform: uppercase; color: var(--text-bright);
    }
    .vc-desc { font-size: 13px; color: var(--text-muted); line-height: 1.4; }

    .home-powered {
        text-align: center; margin-top: 32px;
    }
    .home-powered span {
        font-size: 12px; color: rgba(255,255,255,0.25); letter-spacing: 2px;
        text-transform: uppercase; font-family: var(--font-sans);
    }

    @media (max-width: 600px) {
        .verticals-grid { grid-template-columns: 1fr; gap: 14px; }
        .home-brand h1 { letter-spacing: 6px; }
    }
</style>

<section class="home-page">
    <div class="home-brand hero-entrance">
        <h1>MYSTES</h1>
        <p class="tagline">Travel Intelligence</p>
    </div>

    <div class="verticals-grid reveal-stagger">
        <a href="/flights" class="vertical-card reveal">
            <span class="mystes-badge mystes-badge-green" style="position:absolute;top:12px;right:12px;">Live</span>
            <div class="vc-icon">&#9992;</div>
            <div class="vc-name">Flights</div>
            <div class="vc-desc">Search 102 markets for the cheapest fares</div>
        </a>

        <a href="/hotels" class="vertical-card reveal">
            <span class="mystes-badge mystes-badge-green" style="position:absolute;top:12px;right:12px;">Live</span>
            <div class="vc-icon">&#127976;</div>
            <div class="vc-name">Hotels</div>
            <div class="vc-desc">Best rates from 2M+ properties worldwide</div>
        </a>

        <a href="/activities" class="vertical-card coming-soon reveal">
            <span class="mystes-badge mystes-badge-neutral" style="position:absolute;top:12px;right:12px;">Coming Soon</span>
            <div class="vc-icon">&#127947;</div>
            <div class="vc-name">Activities</div>
            <div class="vc-desc">Tours, experiences, and things to do</div>
        </a>

        <a href="/cars" class="vertical-card coming-soon reveal">
            <span class="mystes-badge mystes-badge-neutral" style="position:absolute;top:12px;right:12px;">Coming Soon</span>
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
