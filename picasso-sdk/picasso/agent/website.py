"""
APAi Marketing Website — Professional landing page for apai.co.

Pages:
    /          — Homepage (single-page scrolling marketing site)
    /pricing   — Pricing tiers (standalone)
    /docs      — API documentation overview + quickstart
    /demo      — Live demo page (links to mystes.app)

Design:
    - Space Grotesk (headings) + Outfit (body) typography
    - Dark cosmic palette (#0a0612 base)
    - CSS-only aurora background, glass morphism cards
    - IntersectionObserver scroll reveal, no external JS libraries
    - Mobile responsive (768px + 480px breakpoints)

MYSTES KYRIOS LLC — Confidential.
"""

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# HOMEPAGE HTML
# ============================================================================

HOMEPAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APAi — Intelligent Travel Engine</title>
<meta name="description" content="APAi — The intelligent travel booking engine powered by ANASTASiA. Launch your OTA in 5 minutes. Credential sharing, intelligent arbitrage, fully automated booking. Zero API experience needed.">
<meta property="og:title" content="APAi — Intelligent Travel Engine">
<meta property="og:description" content="Launch your OTA in 5 minutes. Credential sharing, intelligent arbitrage, fully automated booking.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://apai.co">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="APAi — Intelligent Travel Engine">
<meta name="twitter:description" content="Launch your OTA in 5 minutes. Zero API experience needed.">
<meta name="theme-color" content="#6366f1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
/* ============================================
   APAi DESIGN SYSTEM
   Celestial / Cosmic Aesthetic
   ============================================ */

*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}

:root {
    --bg: #0a0612;
    --bg-elevated: #110e1f;
    --bg-card: rgba(255,255,255,0.04);
    --border: rgba(255,255,255,0.08);
    --border-hover: rgba(255,255,255,0.15);
    --accent: #6366f1;
    --accent-light: #818cf8;
    --accent-secondary: #a855f7;
    --accent-gradient: linear-gradient(135deg, #6366f1, #a855f7);
    --text: #f0eef5;
    --text-dim: #9994b8;
    --text-muted: #6b6689;
    --success: #22c55e;
    --warning: #f59e0b;
    --font-heading: 'Space Grotesk', sans-serif;
    --font-body: 'Outfit', sans-serif;
    --radius: 16px;
    --radius-sm: 8px;
    --radius-lg: 24px;
}

html {
    scroll-behavior: smooth;
    -webkit-text-size-adjust: 100%;
}

body {
    font-family: var(--font-body);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
}

a { color: var(--accent-light); text-decoration: none; transition: color 0.2s; }
a:hover { color: #c4b5fd; }

/* ============================================
   NAVIGATION
   ============================================ */

.nav {
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 100;
    padding: 0 24px;
    transition: background 0.3s, backdrop-filter 0.3s;
}
.nav.scrolled {
    background: rgba(10,6,18,0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border);
}
.nav-inner {
    max-width: 1200px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 72px;
}
.nav-logo {
    font-family: var(--font-heading);
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 4px;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.nav-links {
    display: flex;
    align-items: center;
    gap: 32px;
    list-style: none;
}
.nav-links a {
    color: var(--text-dim);
    font-size: 14px;
    font-weight: 500;
    letter-spacing: 0.5px;
    transition: color 0.2s;
}
.nav-links a:hover { color: var(--text); }
.nav-cta {
    padding: 10px 24px;
    background: var(--accent-gradient);
    border-radius: var(--radius-sm);
    color: white !important;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.5px;
    transition: opacity 0.2s, transform 0.2s;
}
.nav-cta:hover { opacity: 0.9; transform: translateY(-1px); color: white !important; }

/* Mobile hamburger */
.nav-toggle {
    display: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 8px;
}
.nav-toggle span {
    display: block;
    width: 24px;
    height: 2px;
    background: var(--text);
    margin: 5px 0;
    transition: transform 0.3s, opacity 0.3s;
}
.nav-toggle.active span:nth-child(1) { transform: rotate(45deg) translate(5px,5px); }
.nav-toggle.active span:nth-child(2) { opacity: 0; }
.nav-toggle.active span:nth-child(3) { transform: rotate(-45deg) translate(5px,-5px); }

@media (max-width: 768px) {
    .nav-toggle { display: block; }
    .nav-links {
        position: fixed;
        top: 72px; left: 0; right: 0; bottom: 0;
        background: rgba(10,6,18,0.98);
        backdrop-filter: blur(20px);
        flex-direction: column;
        justify-content: center;
        gap: 24px;
        transform: translateX(100%);
        transition: transform 0.3s ease;
    }
    .nav-links.open { transform: translateX(0); }
    .nav-links a { font-size: 18px; }
}

/* ============================================
   HERO — Ex Astris Cum Amore
   ============================================ */

.hero {
    position: relative;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 120px 24px 80px;
    overflow: hidden;
}

/* Aurora background */
.hero::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
        radial-gradient(ellipse 80% 50% at 20% 40%, rgba(99,102,241,0.25) 0%, transparent 60%),
        radial-gradient(ellipse 60% 80% at 80% 20%, rgba(168,85,247,0.2) 0%, transparent 55%),
        radial-gradient(ellipse 70% 60% at 50% 80%, rgba(59,130,246,0.15) 0%, transparent 50%),
        radial-gradient(ellipse 90% 40% at 70% 60%, rgba(139,45,91,0.12) 0%, transparent 55%),
        linear-gradient(180deg, #0a0612 0%, #0d0a1a 50%, #0a0612 100%);
    background-size: 200% 200%;
    animation: auroraShift 20s ease infinite;
    z-index: 0;
}

/* Star field */
.hero::after {
    content: '';
    position: absolute;
    inset: 0;
    background-image:
        radial-gradient(1px 1px at 10% 15%, rgba(255,255,255,0.6), transparent),
        radial-gradient(1px 1px at 25% 35%, rgba(255,255,255,0.4), transparent),
        radial-gradient(1.5px 1.5px at 40% 10%, rgba(255,255,255,0.7), transparent),
        radial-gradient(1px 1px at 55% 45%, rgba(255,255,255,0.3), transparent),
        radial-gradient(1px 1px at 70% 20%, rgba(255,255,255,0.5), transparent),
        radial-gradient(1.5px 1.5px at 85% 55%, rgba(255,255,255,0.6), transparent),
        radial-gradient(1px 1px at 15% 70%, rgba(255,255,255,0.4), transparent),
        radial-gradient(1px 1px at 35% 85%, rgba(255,255,255,0.3), transparent),
        radial-gradient(1.5px 1.5px at 60% 75%, rgba(255,255,255,0.5), transparent),
        radial-gradient(1px 1px at 80% 90%, rgba(255,255,255,0.4), transparent),
        radial-gradient(1px 1px at 95% 30%, rgba(255,255,255,0.3), transparent),
        radial-gradient(1px 1px at 5% 50%, rgba(255,255,255,0.5), transparent),
        radial-gradient(2px 2px at 48% 52%, rgba(255,255,255,0.8), transparent),
        radial-gradient(1px 1px at 30% 60%, rgba(255,255,255,0.3), transparent),
        radial-gradient(1px 1px at 75% 70%, rgba(255,255,255,0.4), transparent),
        radial-gradient(1.5px 1.5px at 90% 10%, rgba(255,255,255,0.5), transparent),
        radial-gradient(1px 1px at 20% 90%, rgba(255,255,255,0.3), transparent),
        radial-gradient(1px 1px at 65% 5%, rgba(255,255,255,0.4), transparent);
    animation: starTwinkle 8s ease-in-out infinite alternate;
    z-index: 0;
}

@keyframes auroraShift {
    0%   { background-position: 0% 50%; }
    25%  { background-position: 50% 0%; }
    50%  { background-position: 100% 50%; }
    75%  { background-position: 50% 100%; }
    100% { background-position: 0% 50%; }
}

@keyframes starTwinkle {
    0%   { opacity: 0.6; }
    100% { opacity: 1; }
}

.hero-content {
    position: relative;
    z-index: 1;
    max-width: 800px;
}

.hero-badge {
    display: inline-block;
    padding: 6px 16px;
    background: rgba(99,102,241,0.15);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 100px;
    font-size: 12px;
    font-weight: 500;
    color: var(--accent-light);
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 32px;
}

.hero h1 {
    font-family: var(--font-heading);
    font-size: clamp(48px, 8vw, 96px);
    font-weight: 800;
    letter-spacing: 8px;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 16px;
    line-height: 1.1;
    text-shadow: 0 0 80px rgba(99,102,241,0.3);
}

.hero-subtitle {
    font-family: var(--font-heading);
    font-size: clamp(14px, 2vw, 18px);
    color: var(--text-dim);
    letter-spacing: 3px;
    margin-bottom: 24px;
    font-weight: 400;
}

.hero-latin {
    font-style: italic;
    font-size: clamp(13px, 1.5vw, 16px);
    color: var(--text-muted);
    letter-spacing: 2px;
    margin-bottom: 48px;
    opacity: 0.7;
}

.hero-ctas {
    display: flex;
    gap: 16px;
    justify-content: center;
    flex-wrap: wrap;
}

.btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 14px 32px;
    border-radius: var(--radius-sm);
    font-family: var(--font-body);
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.25s ease;
    border: none;
    text-decoration: none;
}
.btn-primary {
    background: var(--accent-gradient);
    color: white;
    box-shadow: 0 4px 24px rgba(99,102,241,0.3);
}
.btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(99,102,241,0.4);
    color: white;
}
.btn-ghost {
    background: rgba(255,255,255,0.06);
    color: var(--text);
    border: 1px solid var(--border);
}
.btn-ghost:hover {
    background: rgba(255,255,255,0.1);
    border-color: var(--border-hover);
    color: var(--text);
}

.scroll-indicator {
    position: absolute;
    bottom: 32px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1;
    animation: scrollBounce 2s ease infinite;
}
.scroll-indicator svg {
    width: 24px;
    height: 24px;
    stroke: var(--text-muted);
    fill: none;
    stroke-width: 2;
}
@keyframes scrollBounce {
    0%, 100% { transform: translateX(-50%) translateY(0); }
    50% { transform: translateX(-50%) translateY(8px); }
}

/* ============================================
   SECTIONS — Common
   ============================================ */

section {
    padding: 120px 24px;
    position: relative;
}
.section-inner {
    max-width: 1100px;
    margin: 0 auto;
}
.section-label {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent-light);
    margin-bottom: 16px;
}
.section-title {
    font-family: var(--font-heading);
    font-size: clamp(28px, 4vw, 42px);
    font-weight: 700;
    margin-bottom: 16px;
    line-height: 1.2;
}
.section-desc {
    font-size: 17px;
    color: var(--text-dim);
    max-width: 640px;
    line-height: 1.7;
    margin-bottom: 48px;
}
.section-center {
    text-align: center;
}
.section-center .section-desc {
    margin-left: auto;
    margin-right: auto;
}

/* ============================================
   GLASS CARDS
   ============================================ */

.glass {
    background: var(--bg-card);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: border-color 0.3s, transform 0.3s;
}
.glass:hover {
    border-color: var(--border-hover);
}
.glass-interactive:hover {
    transform: translateY(-4px);
    border-color: rgba(99,102,241,0.3);
}

/* ============================================
   GRID
   ============================================ */

.grid-3 {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
}
.grid-2 {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 24px;
}
@media (max-width: 768px) {
    .grid-3, .grid-2 { grid-template-columns: 1fr; }
}

/* ============================================
   SECTION 2 — THE ENGINE
   ============================================ */

.feature-card {
    padding: 32px;
}
.feature-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    background: rgba(99,102,241,0.12);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 20px;
    font-size: 22px;
}
.feature-card h3 {
    font-family: var(--font-heading);
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 12px;
}
.feature-card p {
    font-size: 14px;
    color: var(--text-dim);
    line-height: 1.7;
}

/* ============================================
   SECTION 3 — CREDENTIAL NETWORK
   ============================================ */

.network-visual {
    position: relative;
    height: 280px;
    margin-bottom: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.network-node {
    position: absolute;
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: rgba(99,102,241,0.1);
    border: 1px solid rgba(99,102,241,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    animation: nodePulse 3s ease-in-out infinite;
}
.network-node:nth-child(2) { animation-delay: 0.5s; }
.network-node:nth-child(3) { animation-delay: 1s; }
.network-node:nth-child(4) { animation-delay: 1.5s; }
.network-center {
    width: 80px;
    height: 80px;
    background: var(--accent-gradient);
    border: none;
    font-size: 14px;
    font-weight: 700;
    color: white;
    font-family: var(--font-heading);
    letter-spacing: 1px;
    z-index: 2;
}

@keyframes nodePulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.2); }
    50% { box-shadow: 0 0 20px 4px rgba(99,102,241,0.15); }
}

.network-line {
    position: absolute;
    height: 1px;
    background: linear-gradient(90deg, rgba(99,102,241,0.4), rgba(168,85,247,0.2));
    transform-origin: left center;
}

.flow-cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-top: 32px;
}
.flow-card {
    padding: 24px 16px;
    text-align: center;
    position: relative;
}
.flow-card::after {
    content: '\2192';
    position: absolute;
    right: -12px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--accent);
    font-size: 20px;
}
.flow-card:last-child::after { display: none; }
.flow-card .flow-num {
    display: inline-flex;
    width: 28px;
    height: 28px;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--accent-gradient);
    color: white;
    font-size: 12px;
    font-weight: 700;
    margin-bottom: 12px;
}
.flow-card h4 {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
}
.flow-card p {
    font-size: 12px;
    color: var(--text-dim);
    line-height: 1.5;
}

@media (max-width: 768px) {
    .flow-cards { grid-template-columns: 1fr 1fr; }
    .flow-card:nth-child(2)::after { display: none; }
    .flow-card::after { display: none; }
}
@media (max-width: 480px) {
    .flow-cards { grid-template-columns: 1fr; }
}

/* ============================================
   SECTION 4 — TIMELINE
   ============================================ */

.timeline {
    position: relative;
    padding-left: 40px;
    max-width: 700px;
}
.timeline::before {
    content: '';
    position: absolute;
    left: 14px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: linear-gradient(180deg, var(--accent), var(--accent-secondary), transparent);
}
.timeline-item {
    position: relative;
    padding: 0 0 40px 32px;
}
.timeline-item:last-child { padding-bottom: 0; }
.timeline-dot {
    position: absolute;
    left: -33px;
    top: 4px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--bg);
    box-shadow: 0 0 0 3px rgba(99,102,241,0.3);
}
.timeline-item h3 {
    font-family: var(--font-heading);
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 8px;
}
.timeline-item p {
    font-size: 14px;
    color: var(--text-dim);
    line-height: 1.7;
}

/* ============================================
   SECTION 5 — TURNKEY COMPARISON
   ============================================ */

.compare-grid {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 32px;
    align-items: center;
}
.compare-card {
    padding: 32px;
}
.compare-card.old {
    opacity: 0.6;
}
.compare-card h3 {
    font-family: var(--font-heading);
    font-size: 20px;
    margin-bottom: 20px;
}
.compare-card ul {
    list-style: none;
    font-size: 14px;
    color: var(--text-dim);
}
.compare-card ul li {
    padding: 8px 0;
    display: flex;
    align-items: center;
    gap: 10px;
}
.compare-card.old ul li::before {
    content: '\2717';
    color: #ef4444;
    font-weight: 700;
}
.compare-card.new ul li::before {
    content: '\2713';
    color: var(--success);
    font-weight: 700;
}
.compare-vs {
    font-family: var(--font-heading);
    font-size: 24px;
    color: var(--text-muted);
    font-weight: 700;
}
@media (max-width: 768px) {
    .compare-grid { grid-template-columns: 1fr; }
    .compare-vs { text-align: center; padding: 8px 0; }
}

.live-demo-link {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    margin-top: 32px;
    padding: 14px 28px;
    background: rgba(34,197,94,0.1);
    border: 1px solid rgba(34,197,94,0.3);
    border-radius: var(--radius-sm);
    color: var(--success);
    font-weight: 600;
    font-size: 14px;
    transition: all 0.2s;
}
.live-demo-link:hover {
    background: rgba(34,197,94,0.15);
    color: var(--success);
    transform: translateY(-2px);
}

/* ============================================
   SECTION 6 — API & SDK
   ============================================ */

.delivery-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 32px;
    background: rgba(255,255,255,0.03);
    border-radius: var(--radius-sm);
    padding: 4px;
    border: 1px solid var(--border);
    width: fit-content;
}
.delivery-tab {
    padding: 10px 24px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    color: var(--text-dim);
    transition: all 0.2s;
    background: none;
    border: none;
    font-family: var(--font-body);
}
.delivery-tab.active {
    background: var(--accent);
    color: white;
}
.delivery-tab:hover:not(.active) {
    color: var(--text);
}
.delivery-panel {
    display: none;
}
.delivery-panel.active {
    display: block;
}
.code-block {
    background: #12101e;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 24px;
    overflow-x: auto;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.7;
    color: #d4d4d8;
    position: relative;
}
.code-block .comment { color: #6b7280; }
.code-block .string { color: #a78bfa; }
.code-block .keyword { color: #f472b6; }
.code-block .method { color: #60a5fa; }

.copy-btn {
    position: absolute;
    top: 12px;
    right: 12px;
    padding: 6px 12px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-dim);
    font-size: 11px;
    cursor: pointer;
    font-family: var(--font-body);
    transition: all 0.2s;
}
.copy-btn:hover {
    background: rgba(255,255,255,0.1);
    color: var(--text);
}

/* ============================================
   SECTION 7 — PRICING
   ============================================ */

.pricing-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    margin-bottom: 48px;
}
.pricing-card {
    padding: 36px 28px;
    position: relative;
    overflow: hidden;
}
.pricing-card.featured {
    border-color: rgba(99,102,241,0.4);
    background: rgba(99,102,241,0.06);
}
.pricing-card.featured::before {
    content: 'MOST POPULAR';
    position: absolute;
    top: 16px;
    right: -28px;
    transform: rotate(45deg);
    background: var(--accent-gradient);
    color: white;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 4px 36px;
}
.pricing-tier {
    font-family: var(--font-heading);
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 4px;
}
.pricing-price {
    font-size: 42px;
    font-weight: 700;
    margin-bottom: 4px;
}
.pricing-price span { font-size: 16px; color: var(--text-dim); font-weight: 400; }
.pricing-desc {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 24px;
    line-height: 1.5;
}
.pricing-features {
    list-style: none;
    margin-bottom: 28px;
}
.pricing-features li {
    padding: 7px 0;
    font-size: 13px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 10px;
}
.pricing-features li::before {
    content: '\2713';
    color: var(--success);
    font-weight: 700;
    font-size: 14px;
}
.pricing-btn {
    display: block;
    width: 100%;
    text-align: center;
    padding: 12px;
    border-radius: var(--radius-sm);
    font-weight: 600;
    font-size: 14px;
    transition: all 0.2s;
}
.pricing-btn-primary {
    background: var(--accent-gradient);
    color: white;
}
.pricing-btn-primary:hover { opacity: 0.9; color: white; }
.pricing-btn-ghost {
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    color: var(--text);
}
.pricing-btn-ghost:hover { background: rgba(255,255,255,0.1); color: var(--text); }

.pricing-note {
    text-align: center;
    font-size: 14px;
    color: var(--text-dim);
    font-style: italic;
    margin-top: 16px;
}

@media (max-width: 768px) {
    .pricing-grid { grid-template-columns: 1fr; max-width: 400px; margin-left: auto; margin-right: auto; }
}

/* ============================================
   SECTION 8 — SANDBOX
   ============================================ */

.sandbox-box {
    max-width: 560px;
    margin: 0 auto;
    padding: 40px;
}
.sandbox-input-row {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
}
.sandbox-input {
    flex: 1;
    padding: 12px 16px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
}
.sandbox-input:focus {
    border-color: var(--accent);
}
.sandbox-input::placeholder {
    color: var(--text-muted);
}
.key-display {
    display: none;
    background: rgba(34,197,94,0.08);
    border: 1px solid rgba(34,197,94,0.25);
    border-radius: var(--radius-sm);
    padding: 20px;
    margin-top: 20px;
    text-align: center;
}
.key-display code {
    display: block;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 15px;
    color: var(--success);
    word-break: break-all;
    margin: 12px 0;
    user-select: all;
}
.key-display .key-warning {
    font-size: 11px;
    color: var(--warning);
    margin-top: 8px;
}

/* ============================================
   SECTION 9 — LIVE DEMO
   ============================================ */

.demo-frame {
    max-width: 800px;
    margin: 0 auto;
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border);
    background: var(--bg-elevated);
}
.demo-browser-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: rgba(255,255,255,0.03);
    border-bottom: 1px solid var(--border);
}
.demo-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}
.demo-dot:nth-child(1) { background: #ef4444; }
.demo-dot:nth-child(2) { background: #f59e0b; }
.demo-dot:nth-child(3) { background: #22c55e; }
.demo-url {
    flex: 1;
    margin-left: 12px;
    padding: 6px 12px;
    background: rgba(255,255,255,0.04);
    border-radius: 6px;
    font-size: 12px;
    color: var(--text-dim);
    font-family: 'SF Mono', monospace;
}
.demo-content {
    padding: 48px;
    text-align: center;
    min-height: 300px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}
.demo-content h3 {
    font-family: var(--font-heading);
    font-size: 24px;
    margin-bottom: 12px;
}
.demo-content p {
    color: var(--text-dim);
    max-width: 440px;
    margin-bottom: 24px;
    font-size: 15px;
    line-height: 1.7;
}

/* ============================================
   FOOTER
   ============================================ */

.footer {
    border-top: 1px solid var(--border);
    padding: 60px 24px 40px;
}
.footer-inner {
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 40px;
}
.footer-brand h3 {
    font-family: var(--font-heading);
    font-size: 18px;
    letter-spacing: 3px;
    margin-bottom: 8px;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.footer-brand p {
    font-size: 13px;
    color: var(--text-muted);
    font-style: italic;
}
.footer-links {
    display: flex;
    gap: 48px;
}
.footer-col h4 {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-bottom: 16px;
}
.footer-col a {
    display: block;
    padding: 4px 0;
    font-size: 13px;
    color: var(--text-muted);
}
.footer-col a:hover { color: var(--text); }

.footer-bottom {
    max-width: 1100px;
    margin: 40px auto 0;
    padding-top: 24px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    color: var(--text-muted);
}

@media (max-width: 768px) {
    .footer-inner { flex-direction: column; }
    .footer-links { flex-direction: column; gap: 24px; }
    .footer-bottom { flex-direction: column; gap: 8px; }
}

/* ============================================
   SCROLL REVEAL
   ============================================ */

.reveal {
    opacity: 0;
    transform: translateY(30px);
    transition: opacity 0.7s ease, transform 0.7s ease;
}
.reveal.visible {
    opacity: 1;
    transform: translateY(0);
}
.reveal-delay-1 { transition-delay: 0.1s; }
.reveal-delay-2 { transition-delay: 0.2s; }
.reveal-delay-3 { transition-delay: 0.3s; }

/* ============================================
   SECTION DIVIDERS
   ============================================ */

.section-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--border), transparent);
    margin: 0 auto;
    max-width: 600px;
}

/* ============================================
   PROVIDER DIRECTORY PREVIEW
   ============================================ */

.directory-preview {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
    margin-top: 48px;
}
.provider-preview {
    padding: 24px;
    text-align: left;
}
.provider-preview-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
}
.provider-preview-name {
    font-family: var(--font-heading);
    font-size: 16px;
    font-weight: 600;
}
.provider-preview-badge {
    font-size: 10px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 100px;
    letter-spacing: 0.5px;
}
.badge-enterprise { background: rgba(99,102,241,0.15); color: var(--accent-light); }
.badge-scale { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge-pro { background: rgba(34,197,94,0.15); color: var(--success); }
.badge-platform { background: rgba(245,158,11,0.15); color: #fbbf24; }
.provider-preview-creds {
    list-style: none;
    margin-bottom: 16px;
}
.provider-preview-creds li {
    padding: 3px 0;
    font-size: 12px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
}
.provider-preview-creds li::before {
    content: '\25C9';
    color: var(--accent);
    font-size: 10px;
}
.provider-preview-terms {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    font-size: 11px;
    color: var(--text-muted);
    padding-top: 12px;
    border-top: 1px solid var(--border);
}
.provider-preview-terms span {
    display: flex;
    justify-content: space-between;
}
.provider-preview-terms strong {
    color: var(--text-dim);
    font-weight: 500;
}
.connect-btn {
    display: inline-block;
    margin-top: 12px;
    padding: 6px 16px;
    font-size: 11px;
    font-weight: 600;
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 6px;
    color: var(--accent-light);
    cursor: default;
    letter-spacing: 0.3px;
}

@media (max-width: 768px) {
    .directory-preview { grid-template-columns: 1fr; }
}

/* ============================================
   P2P AUTONOMY CALLOUT
   ============================================ */

.autonomy-callout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-top: 48px;
}
.autonomy-card {
    padding: 28px;
    text-align: left;
}
.autonomy-card h4 {
    font-family: var(--font-heading);
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 8px;
}
.autonomy-card p {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.7;
}
.autonomy-highlight {
    display: inline-block;
    font-size: 28px;
    font-weight: 700;
    font-family: var(--font-heading);
    margin-bottom: 8px;
}
.autonomy-highlight.zero { color: var(--success); }
.autonomy-highlight.full { background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

@media (max-width: 768px) {
    .autonomy-callout { grid-template-columns: 1fr; }
}

/* ============================================
   AI ARCHITECT SECTION
   ============================================ */

.terminal-demo {
    max-width: 720px;
    margin: 0 auto;
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border);
    background: #0c0a16;
}
.terminal-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: rgba(255,255,255,0.03);
    border-bottom: 1px solid var(--border);
}
.term-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}
.term-dot:nth-child(1) { background: #ef4444; }
.term-dot:nth-child(2) { background: #f59e0b; }
.term-dot:nth-child(3) { background: #22c55e; }
.terminal-title {
    margin-left: 12px;
    font-size: 12px;
    color: var(--text-muted);
    font-family: 'SF Mono', monospace;
}
.terminal-body {
    padding: 24px;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.8;
    min-height: 260px;
}
.term-line {
    margin-bottom: 4px;
}
.term-prompt {
    color: var(--accent-light);
}
.term-user {
    color: #c4b5fd;
}
.term-response {
    color: var(--text-dim);
    padding-left: 16px;
}
.term-success {
    color: var(--success);
    padding-left: 16px;
}
.term-cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    background: var(--accent);
    animation: cursorBlink 1.2s step-end infinite;
    vertical-align: text-bottom;
}
@keyframes cursorBlink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
}

.architect-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
    margin-top: 48px;
}
.arch-stat {
    padding: 24px 16px;
    text-align: center;
}
.arch-stat-num {
    font-family: var(--font-heading);
    font-size: 28px;
    font-weight: 700;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
}
.arch-stat-label {
    font-size: 12px;
    color: var(--text-dim);
    line-height: 1.4;
}

.pipeline-steps {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-top: 48px;
}
.pipe-step {
    text-align: center;
    padding: 20px 8px;
    position: relative;
}
.pipe-step::after {
    content: '\2192';
    position: absolute;
    right: -10px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--accent);
    font-size: 16px;
}
.pipe-step:last-child::after { display: none; }
.pipe-step-icon {
    font-size: 24px;
    margin-bottom: 8px;
}
.pipe-step h4 {
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 4px;
}
.pipe-step p {
    font-size: 10px;
    color: var(--text-dim);
    line-height: 1.4;
}

@media (max-width: 768px) {
    .architect-stats { grid-template-columns: 1fr 1fr; }
    .pipeline-steps { grid-template-columns: 1fr; }
    .pipe-step::after { display: none; }
}

/* ============================================
   CREDENTIAL COST CALCULATOR
   ============================================ */

.calc-box {
    max-width: 560px;
    margin: 48px auto 0;
    padding: 32px;
}
.calc-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
}
.calc-label {
    font-size: 13px;
    color: var(--text-dim);
}
.calc-input {
    width: 120px;
    padding: 8px 12px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: var(--font-body);
    font-size: 14px;
    text-align: right;
    outline: none;
}
.calc-input:focus { border-color: var(--accent); }
.calc-select {
    padding: 8px 12px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: var(--font-body);
    font-size: 14px;
    outline: none;
    cursor: pointer;
}
.calc-select option { background: #14112a; }
.calc-result {
    margin-top: 20px;
    padding: 20px;
    background: rgba(34,197,94,0.06);
    border: 1px solid rgba(34,197,94,0.2);
    border-radius: var(--radius-sm);
    text-align: center;
}
.calc-result-num {
    font-family: var(--font-heading);
    font-size: 36px;
    font-weight: 700;
    color: var(--success);
}
.calc-result-label {
    font-size: 13px;
    color: var(--text-dim);
    margin-top: 4px;
}
.calc-result-sub {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 8px;
    font-style: italic;
}

/* ============================================
   REDUCED MOTION
   ============================================ */

@media (prefers-reduced-motion: reduce) {
    .hero::before, .hero::after, .network-node, .scroll-indicator, .term-cursor { animation: none; }
    .reveal { opacity: 1; transform: none; transition: none; }
    html { scroll-behavior: auto; }
}
</style>
</head>
<body>

<!-- ========================================
     NAVIGATION
     ======================================== -->
<nav class="nav" id="mainNav">
    <div class="nav-inner">
        <a href="/" class="nav-logo">APAi</a>
        <button class="nav-toggle" id="navToggle" aria-label="Menu">
            <span></span><span></span><span></span>
        </button>
        <ul class="nav-links" id="navLinks">
            <li><a href="#engine">Features</a></li>
            <li><a href="#network">Network</a></li>
            <li><a href="#architect">Terminal</a></li>
            <li><a href="#pricing">Pricing</a></li>
            <li><a href="/docs">Docs</a></li>
            <li><a href="/signup" class="nav-cta">Get Started</a></li>
        </ul>
    </div>
</nav>

<!-- ========================================
     HERO — Ex Astris Cum Amore
     ======================================== -->
<section class="hero" id="hero">
    <div class="hero-content">
        <div class="hero-badge">Intelligent Travel Engine</div>
        <h1>APAi</h1>
        <div class="hero-subtitle">ANASTAS<em>i</em>A &mdash; Intelligent Travel APAi</div>
        <div class="hero-latin">Ex astris cum amore</div>
        <div class="hero-ctas">
            <a href="/signup" class="btn btn-primary">Get Started</a>
            <a href="https://mystes.app" target="_blank" rel="noopener" class="btn btn-ghost">See It Live &rarr;</a>
        </div>
    </div>
    <div class="scroll-indicator">
        <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
    </div>
</section>

<!-- ========================================
     SECTION 2 — THE ENGINE
     ======================================== -->
<section id="engine">
    <div class="section-inner section-center">
        <span class="section-label reveal">The Engine</span>
        <h2 class="section-title reveal">Plug in. Launch. Sell flights.</h2>
        <p class="section-desc reveal">APAi is the intelligent travel booking engine. Bring your credentials, get a fully automated OTA. Zero API experience needed. ANASTAS<em>i</em>A handles everything&mdash;from search to issuance.</p>

        <div class="grid-3">
            <div class="glass glass-interactive feature-card reveal reveal-delay-1">
                <div class="feature-icon">&#9733;</div>
                <h3>Intelligent Arbitrage</h3>
                <p>Credential routing across permissioned POS markets finds the cheapest fare globally. Automated spread calculation maximizes savings for every passenger.</p>
            </div>
            <div class="glass glass-interactive feature-card reveal reveal-delay-2">
                <div class="feature-icon">&#9881;</div>
                <h3>Self-Learning SDK</h3>
                <p>ANASTAS<em>i</em>A autonomously learns new APIs, probes endpoints, and generates knowledge cards. Intelligence deploys in real time&mdash;no dev work required.</p>
            </div>
            <div class="glass glass-interactive feature-card reveal reveal-delay-3">
                <div class="feature-icon">&#9889;</div>
                <h3>Fully Automated</h3>
                <p>From consumer search to ticket issuance. Booking, payment, confirmation&mdash;zero manual intervention. Your OTA runs itself.</p>
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 3 — CREDENTIAL NETWORK
     ======================================== -->
<section id="network">
    <div class="section-inner section-center">
        <span class="section-label reveal">Credential Network</span>
        <h2 class="section-title reveal">The P2P credential marketplace</h2>
        <p class="section-desc reveal">Turn your API credentials from a cost center into a revenue stream. Browse the directory, set your terms, connect with other OTAs. ANASTAS<em>i</em>A routes intelligently across every permissioned source. Raw credentials never leave your encrypted vault.</p>

        <div class="network-visual reveal">
            <div class="network-node" style="left:10%;top:30%">&#9992;</div>
            <div class="network-node" style="left:20%;top:75%">&#127760;</div>
            <div class="network-node" style="right:20%;top:25%">&#128273;</div>
            <div class="network-node" style="right:10%;top:70%">&#128200;</div>
            <div class="network-node network-center">APAi</div>
        </div>

        <div class="flow-cards">
            <div class="glass flow-card reveal reveal-delay-1">
                <div class="flow-num">1</div>
                <h4>Add Credentials</h4>
                <p>GDS, NDC, Direct Booking Bridge&mdash;bring any credential type</p>
            </div>
            <div class="glass flow-card reveal reveal-delay-2">
                <div class="flow-num">2</div>
                <h4>Set Your Terms</h4>
                <p>Query fees, revenue splits, markets, limits&mdash;you control everything</p>
            </div>
            <div class="glass flow-card reveal reveal-delay-3">
                <div class="flow-num">3</div>
                <h4>Publish to Network</h4>
                <p>Other OTAs browse your profile and request connection</p>
            </div>
            <div class="glass flow-card reveal">
                <div class="flow-num">4</div>
                <h4>Earn Passively</h4>
                <p>Revenue flows automatically as others route through your credentials</p>
            </div>
        </div>

        <!-- P2P Autonomy Callout -->
        <div class="autonomy-callout reveal">
            <div class="glass autonomy-card">
                <div class="autonomy-highlight zero">$0</div>
                <h4>P2P Platform Fee</h4>
                <p>Subscribers have full autonomy between one another. Set your own query fees, revenue splits, and terms. APAi takes nothing from peer-to-peer transactions&mdash;you&rsquo;re already paying for the engine.</p>
            </div>
            <div class="glass autonomy-card">
                <div class="autonomy-highlight full">100%</div>
                <h4>Your Credentials, Your Margin</h4>
                <p>Bookings through your own credentials earn you 100% of the margin. No routing fee, no split, no platform cut. The network amplifies your reach without touching your direct revenue.</p>
            </div>
        </div>

        <!-- Directory Preview -->
        <h3 class="reveal" style="font-family:var(--font-heading);font-size:18px;margin-top:56px;margin-bottom:8px">Network Directory</h3>
        <p class="reveal" style="font-size:14px;color:var(--text-dim);margin-bottom:24px">Browse providers, review terms, connect in one click. Every card is machine-readable&mdash;ANASTAS<em>i</em>A executes routing decisions in real time.</p>

        <div class="directory-preview reveal">
            <div class="glass provider-preview">
                <div class="provider-preview-header">
                    <span class="provider-preview-name">Atlas Travel Co.</span>
                    <span class="provider-preview-badge badge-enterprise">Enterprise</span>
                </div>
                <ul class="provider-preview-creds">
                    <li>Amadeus GDS &mdash; 38 markets (EU/APAC)</li>
                    <li>Duffel NDC &mdash; 22 airlines</li>
                    <li>liteAPI &mdash; 2.5M hotels</li>
                </ul>
                <div class="provider-preview-terms">
                    <span>Query fee <strong>$0.02</strong></span>
                    <span>Min booking <strong>$50</strong></span>
                    <span>Split <strong>Configurable</strong></span>
                    <span>Markets <strong>Open</strong></span>
                </div>
                <div class="connect-btn">Request Connection</div>
            </div>
            <div class="glass provider-preview">
                <div class="provider-preview-header">
                    <span class="provider-preview-name">MYSTES</span>
                    <span class="provider-preview-badge badge-platform">Platform</span>
                </div>
                <ul class="provider-preview-creds">
                    <li>Direct Booking Bridge &mdash; Any airline</li>
                    <li>Duffel NDC &mdash; 22 airlines</li>
                    <li>Duffel Stays &mdash; Hotels</li>
                </ul>
                <div class="provider-preview-terms">
                    <span>Query fee <strong>At-cost</strong></span>
                    <span>Bridge fee <strong>On spread</strong></span>
                    <span>Note <strong>Airline is MoR</strong></span>
                    <span>Status <strong>Auto-connected</strong></span>
                </div>
                <div class="connect-btn" style="background:rgba(34,197,94,0.12);border-color:rgba(34,197,94,0.3);color:var(--success)">Auto-Connected</div>
            </div>
        </div>

        <!-- Sub-API Provider Pitch -->
        <div class="glass reveal" style="margin-top:48px;padding:32px;text-align:left;border-color:rgba(168,85,247,0.2)">
            <h3 style="font-family:var(--font-heading);font-size:18px;margin-bottom:12px">Turn your API into a revenue stream</h3>
            <p style="font-size:14px;color:var(--text-dim);line-height:1.7;margin-bottom:16px">
                Your Amadeus contract costs you money every query. On the APAi network, you become a sub-API provider&mdash;other OTAs route searches through your credentials and pay you per query. An asset that was a pure cost center becomes passive income. Set your own prices. ANASTAS<em>i</em>A handles billing, routing, and enforcement.
            </p>
            <div style="font-size:13px;color:var(--text-muted);font-style:italic">
                &ldquo;Every OTA that joins makes the network stronger for everyone.&rdquo;
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 4 — HOW ANASTASiA WORKS
     ======================================== -->
<section id="intelligence">
    <div class="section-inner">
        <span class="section-label reveal">How It Works</span>
        <h2 class="section-title reveal">Intelligence that grows</h2>
        <p class="section-desc reveal">ANASTAS<em>i</em>A is not a static API wrapper. It learns, adapts, and evolves. Every API interaction generates intelligence that benefits the entire network.</p>

        <div class="timeline">
            <div class="timeline-item reveal">
                <div class="timeline-dot"></div>
                <h3>Knowledge Cards</h3>
                <p>12+ compiled intelligence cards handle 95% of operations at zero AI cost. Cards encode API schemas, authentication flows, error handling, and optimization strategies&mdash;machine-readable intelligence that executes instantly.</p>
            </div>
            <div class="timeline-item reveal">
                <div class="timeline-dot"></div>
                <h3>Auto-Learning</h3>
                <p>When ANASTAS<em>i</em>A encounters a new API, it probes endpoints, maps schemas, and generates knowledge cards autonomously. New credential sources come online without manual integration work.</p>
            </div>
            <div class="timeline-item reveal">
                <div class="timeline-dot"></div>
                <h3>Credential Routing</h3>
                <p>Intelligent routing across POS markets, GDS systems, and NDC channels. Every search evaluates all permissioned credentials to find the optimal booking path for each itinerary.</p>
            </div>
            <div class="timeline-item reveal">
                <div class="timeline-dot"></div>
                <h3>Drift Detection</h3>
                <p>A watchdog monitors API schemas for breaking changes. When providers update their systems, ANASTAS<em>i</em>A detects the drift, triggers auto-updates, and regenerates knowledge cards&mdash;zero downtime.</p>
            </div>
            <div class="timeline-item reveal">
                <div class="timeline-dot"></div>
                <h3>Cross-Platform Intelligence</h3>
                <p>Lessons learned on one platform propagate across the entire network. A booking pattern discovered on one OTA immediately benefits every APAi subscriber.</p>
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 5 — TURNKEY MODEL
     ======================================== -->
<section id="turnkey">
    <div class="section-inner section-center">
        <span class="section-label reveal">Turnkey Model</span>
        <h2 class="section-title reveal">Your OTA in 5 minutes</h2>
        <p class="section-desc reveal">Stop building from scratch. APAi gives you a production-ready OTA with your branding, your pricing, and your credentials&mdash;launched in minutes, not months.</p>

        <div class="compare-grid reveal">
            <div class="glass compare-card old">
                <h3>Traditional Build</h3>
                <ul>
                    <li>6-12 months development</li>
                    <li>$100K+ engineering cost</li>
                    <li>GDS certification required</li>
                    <li>Payment processor integration</li>
                    <li>API maintenance burden</li>
                    <li>Hiring dev team</li>
                </ul>
            </div>
            <div class="compare-vs">vs</div>
            <div class="glass compare-card new">
                <h3>APAi Turnkey</h3>
                <ul>
                    <li>5 minutes to launch</li>
                    <li>From $299/month</li>
                    <li>Zero API experience needed</li>
                    <li>Payments built in</li>
                    <li>Auto-updating intelligence</li>
                    <li>ANASTAS<em>i</em>A builds for you</li>
                </ul>
            </div>
        </div>

        <a href="https://mystes.app" target="_blank" rel="noopener" class="live-demo-link reveal">
            &#9889; See a working model live &mdash; mystes.app
        </a>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 6 — API & SDK
     ======================================== -->
<section id="sdk">
    <div class="section-inner">
        <span class="section-label reveal">API & SDK</span>
        <h2 class="section-title reveal">Build your way</h2>
        <p class="section-desc reveal">Three delivery mechanisms. Choose the one that fits your business. From raw API access to a full turnkey OTA&mdash;ANASTAS<em>i</em>A powers them all.</p>

        <div class="delivery-tabs reveal" role="tablist">
            <button class="delivery-tab active" data-panel="api" role="tab">API Key</button>
            <button class="delivery-tab" data-panel="turnkey" role="tab">Turnkey Template</button>
            <button class="delivery-tab" data-panel="plugin" role="tab">Vertical Plugin</button>
        </div>

        <div class="delivery-panel active" id="panel-api">
            <div class="grid-2 reveal">
                <div>
                    <h3 style="font-family:var(--font-heading);font-size:18px;margin-bottom:12px">Direct API Access</h3>
                    <p style="font-size:14px;color:var(--text-dim);line-height:1.7;margin-bottom:20px">
                        111+ REST endpoints. Search flights, book, manage bookings, access fare rules, seat maps, and more. Bearer token authentication. JSON in, JSON out. Native pricing intelligence built in.
                    </p>
                    <ul style="list-style:none;font-size:13px;color:var(--text-dim)">
                        <li style="padding:4px 0">&#8227; Flight search across all credentialed sources</li>
                        <li style="padding:4px 0">&#8227; Real-time fare comparison and arbitrage</li>
                        <li style="padding:4px 0">&#8227; Booking creation and management</li>
                        <li style="padding:4px 0">&#8227; Fare rules, seat maps, ancillaries</li>
                        <li style="padding:4px 0">&#8227; Billing, analytics, and usage tracking</li>
                    </ul>
                </div>
                <div class="code-block">
                    <button class="copy-btn" onclick="copyCode(this)">Copy</button>
<span class="comment"># Search flights with APAi</span>
<span class="keyword">curl</span> -X POST https://apai.co/api/v1/search/flights \
  -H <span class="string">"Authorization: Bearer ana_your_key"</span> \
  -H <span class="string">"Content-Type: application/json"</span> \
  -d <span class="string">'{
    "origin": "JFK",
    "destination": "LHR",
    "departure_date": "2026-06-15",
    "adults": 1,
    "cabin_class": "economy"
  }'</span>

<span class="comment"># Response: ranked flight results with pricing</span>
<span class="comment"># from all credentialed sources</span>
                </div>
            </div>
        </div>

        <div class="delivery-panel" id="panel-turnkey">
            <div class="glass reveal" style="padding:32px">
                <h3 style="font-family:var(--font-heading);font-size:18px;margin-bottom:12px">Complete OTA Frontend</h3>
                <p style="font-size:14px;color:var(--text-dim);line-height:1.7;margin-bottom:20px">
                    A production-ready OTA application with your branding and credentials. Consumer search, booking flow, admin dashboard, AI-powered chat agent, payment processing&mdash;everything included. Drop in your API key and launch.
                </p>
                <div class="grid-3" style="margin-top:24px">
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#127912;</div>
                        <div style="font-size:13px;font-weight:600;margin-bottom:4px">White-Label Branding</div>
                        <div style="font-size:12px;color:var(--text-dim)">Your name, your colors, your domain</div>
                    </div>
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#128176;</div>
                        <div style="font-size:13px;font-weight:600;margin-bottom:4px">Custom Pricing</div>
                        <div style="font-size:12px;color:var(--text-dim)">Set your own markups and strategies</div>
                    </div>
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#129302;</div>
                        <div style="font-size:13px;font-weight:600;margin-bottom:4px">AI Chat Agent</div>
                        <div style="font-size:12px;color:var(--text-dim)">ANASTAS<em>i</em>A answers customer queries</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="delivery-panel" id="panel-plugin">
            <div class="glass reveal" style="padding:32px">
                <h3 style="font-family:var(--font-heading);font-size:18px;margin-bottom:12px">Modular Add-Ons</h3>
                <p style="font-size:14px;color:var(--text-dim);line-height:1.7;margin-bottom:20px">
                    Already have a website? Drop in a vertical plugin. Self-contained flight search, hotel booking, or car rental module that integrates into your existing site. ANASTAS<em>i</em>A handles the backend.
                </p>
                <div class="grid-3" style="margin-top:24px">
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#9992;</div>
                        <div style="font-size:13px;font-weight:600">Flights</div>
                    </div>
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#127976;</div>
                        <div style="font-size:13px;font-weight:600">Hotels</div>
                    </div>
                    <div style="padding:16px;text-align:center">
                        <div style="font-size:28px;margin-bottom:8px">&#128663;</div>
                        <div style="font-size:13px;font-weight:600">Cars</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 6b — BUILT-IN AI ARCHITECT
     ======================================== -->
<section id="architect">
    <div class="section-inner section-center">
        <span class="section-label reveal">Built-In AI Architect</span>
        <h2 class="section-title reveal">Your dev team&rsquo;s best hire costs $0.05/query</h2>
        <p class="section-desc reveal">Every turnkey deployment ships with an ANASTAS<em>i</em>A Terminal&mdash;a built-in AI architect that knows your booking pipeline inside and out. Troubleshoot, configure, build custom modules, and deploy&mdash;all through natural language.</p>

        <div class="terminal-demo reveal">
            <div class="terminal-bar">
                <div class="term-dot"></div>
                <div class="term-dot"></div>
                <div class="term-dot"></div>
                <span class="terminal-title">ANASTAS<em style="font-style:normal">i</em>A Terminal &mdash; acme-travel.apai.co</span>
            </div>
            <div class="terminal-body">
                <div class="term-line"><span class="term-prompt">anastasia &gt; </span><span class="term-user">add seasonal pricing: 15% markup on EU flights Dec 15 - Jan 5</span></div>
                <div class="term-line term-response">Analyzing routing terms for 3 active EU connections...</div>
                <div class="term-line term-response">Creating seasonal rule: EU markets, +15% markup, Dec 15 2026 &mdash; Jan 5 2027</div>
                <div class="term-line term-success">&#10003; Seasonal pricing deployed. Will auto-activate Dec 15.</div>
                <div class="term-line" style="margin-top:8px"><span class="term-prompt">anastasia &gt; </span><span class="term-user">which credential has the best LHR coverage?</span></div>
                <div class="term-line term-response">Querying network connections... 4 credentials cover LHR.</div>
                <div class="term-line term-response">Best: Atlas Travel (Amadeus GDS) &mdash; 99.7% uptime, 1.2s avg, $0.02/query</div>
                <div class="term-line term-response">Runner-up: Your Duffel NDC &mdash; 98.4% uptime, 1.8s avg, no query fee</div>
                <div class="term-line" style="margin-top:8px"><span class="term-prompt">anastasia &gt; </span><span class="term-cursor"></span></div>
            </div>
        </div>

        <div class="architect-stats reveal">
            <div class="glass arch-stat">
                <div class="arch-stat-num">$0.05</div>
                <div class="arch-stat-label">Per query at Scale tier</div>
            </div>
            <div class="glass arch-stat">
                <div class="arch-stat-num">0</div>
                <div class="arch-stat-label">API experience required</div>
            </div>
            <div class="glass arch-stat">
                <div class="arch-stat-num">111+</div>
                <div class="arch-stat-label">Endpoints she knows</div>
            </div>
            <div class="glass arch-stat">
                <div class="arch-stat-num">24/7</div>
                <div class="arch-stat-label">Always available</div>
            </div>
        </div>

        <!-- Custom SDK Pipeline -->
        <h3 class="reveal" style="font-family:var(--font-heading);font-size:18px;margin-top:56px;margin-bottom:8px">Custom SDK Development</h3>
        <p class="reveal" style="font-size:14px;color:var(--text-dim);margin-bottom:8px;max-width:640px;margin-left:auto;margin-right:auto">Build custom modules through natural language. ANASTAS<em>i</em>A audits, tests, and deploys them&mdash;optionally to the marketplace for other subscribers.</p>

        <div class="pipeline-steps reveal">
            <div class="glass pipe-step">
                <div class="pipe-step-icon">&#128172;</div>
                <h4>Build</h4>
                <p>Describe what you need in plain language</p>
            </div>
            <div class="glass pipe-step">
                <div class="pipe-step-icon">&#128269;</div>
                <h4>Audit</h4>
                <p>Security scan, API compatibility, performance check</p>
            </div>
            <div class="glass pipe-step">
                <div class="pipe-step-icon">&#9881;</div>
                <h4>Sandbox</h4>
                <p>Test with mock data, verify no breakage</p>
            </div>
            <div class="glass pipe-step">
                <div class="pipe-step-icon">&#128640;</div>
                <h4>Deploy</h4>
                <p>Live with 24h monitoring + auto-rollback</p>
            </div>
            <div class="glass pipe-step">
                <div class="pipe-step-icon">&#127760;</div>
                <h4>Publish</h4>
                <p>Optional: share on the APAi marketplace</p>
            </div>
        </div>

        <div class="glass reveal" style="margin-top:48px;padding:28px;text-align:left;border-color:rgba(99,102,241,0.2)">
            <h4 style="font-family:var(--font-heading);font-size:16px;margin-bottom:12px">Why external AI can&rsquo;t compete</h4>
            <p style="font-size:13px;color:var(--text-dim);line-height:1.7">
                ANASTAS<em>i</em>A compiled the knowledge cards that power the system. She designed the booking pipeline, wrote the credential router, and knows every internal API. External AI needs the entire codebase fed each session&mdash;she has persistent context. Your custom code, your configurations, your routing terms&mdash;all sandboxed per tenant, zero cross-leakage.
            </p>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 7 — PRICING
     ======================================== -->
<section id="pricing">
    <div class="section-inner section-center">
        <span class="section-label reveal">Pricing</span>
        <h2 class="section-title reveal">Transparent. Flat. No negotiation.</h2>
        <p class="section-desc reveal">Same price for everyone. No enterprise deals. No custom contracts. Flat pricing levels the playing field.</p>

        <div class="pricing-grid">
            <div class="glass pricing-card reveal reveal-delay-1">
                <div class="pricing-tier">Pro</div>
                <div class="pricing-price">$299<span>/mo</span></div>
                <div class="pricing-desc">I&rsquo;m getting started.</div>
                <ul class="pricing-features">
                    <li>500 ANASTAS<em>i</em>A queries/mo</li>
                    <li>$0.12 per overage query</li>
                    <li>5% credential routing fee</li>
                    <li>Credential vault &mdash; 3 credentials</li>
                    <li>1 team seat (owner)</li>
                    <li>Turnkey OTA + admin dashboard</li>
                    <li>ANASTAS<em>i</em>A Terminal</li>
                    <li>Basic analytics</li>
                    <li>Network access</li>
                </ul>
                <a href="/signup" class="pricing-btn pricing-btn-ghost">Get Started</a>
            </div>

            <div class="glass pricing-card featured reveal reveal-delay-2">
                <div class="pricing-tier">Enterprise</div>
                <div class="pricing-price">$599<span>/mo</span></div>
                <div class="pricing-desc">I&rsquo;m running a business.</div>
                <ul class="pricing-features">
                    <li>2,000 ANASTAS<em>i</em>A queries/mo</li>
                    <li>$0.08 per overage query</li>
                    <li>3% credential routing fee</li>
                    <li>Credential vault &mdash; 10 credentials</li>
                    <li>5 team seats with roles</li>
                    <li>White-label branding</li>
                    <li>Full revenue analytics</li>
                    <li>Webhook system</li>
                    <li>Transaction audit trail</li>
                </ul>
                <a href="/signup" class="pricing-btn pricing-btn-primary">Get Started</a>
            </div>

            <div class="glass pricing-card reveal reveal-delay-3">
                <div class="pricing-tier">Scale</div>
                <div class="pricing-price">$999<span>/mo</span></div>
                <div class="pricing-desc">I&rsquo;m building an empire.</div>
                <ul class="pricing-features">
                    <li>5,000 ANASTAS<em>i</em>A queries/mo</li>
                    <li>$0.05 per overage query</li>
                    <li>2% credential routing fee</li>
                    <li>Unlimited credentials</li>
                    <li>Unlimited team seats</li>
                    <li>Network intelligence feed</li>
                    <li>Booking failure recovery</li>
                    <li>Credential health monitoring</li>
                    <li>Priority support (4h response)</li>
                </ul>
                <a href="/signup" class="pricing-btn pricing-btn-ghost">Get Started</a>
            </div>
        </div>

        <p class="pricing-note reveal">All tiers include the full ANASTAS<em>i</em>A intelligence engine&mdash;no model downgrading. Same 111+ API endpoints. Same encrypted vault. Free sandbox available.</p>

        <!-- Credential Cost Calculator -->
        <div class="glass calc-box reveal" id="calculator">
            <h3 style="font-family:var(--font-heading);font-size:18px;margin-bottom:4px;text-align:center">Credential Revenue Calculator</h3>
            <p style="font-size:13px;color:var(--text-dim);margin-bottom:24px;text-align:center">See how much your idle credentials could earn on the network.</p>

            <div class="calc-row">
                <span class="calc-label">Monthly searches routed through you</span>
                <input type="number" class="calc-input" id="calcQueries" value="5000" min="100" step="500" oninput="updateCalc()">
            </div>
            <div class="calc-row">
                <span class="calc-label">Your per-query fee</span>
                <input type="number" class="calc-input" id="calcQueryFee" value="0.03" min="0" step="0.01" oninput="updateCalc()">
            </div>
            <div class="calc-row">
                <span class="calc-label">Monthly bookings (est. 2% conversion)</span>
                <input type="number" class="calc-input" id="calcBookings" value="100" min="0" step="10" oninput="updateCalc()">
            </div>
            <div class="calc-row">
                <span class="calc-label">Avg booking margin you keep</span>
                <input type="number" class="calc-input" id="calcMargin" value="12" min="0" step="1" oninput="updateCalc()">
            </div>

            <div class="calc-result" id="calcResult">
                <div class="calc-result-num" id="calcTotal">$1,350</div>
                <div class="calc-result-label">Estimated monthly passive income</div>
                <div class="calc-result-sub" id="calcBreakdown">$150 from query fees + $1,200 from booking margins</div>
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 8 — SANDBOX
     ======================================== -->
<section id="sandbox">
    <div class="section-inner section-center">
        <span class="section-label reveal">Sandbox</span>
        <h2 class="section-title reveal">Try it now</h2>
        <p class="section-desc reveal">Generate a free sandbox API key and start testing immediately. No credit card required.</p>

        <div class="glass sandbox-box reveal">
            <div class="sandbox-input-row">
                <input type="email" class="sandbox-input" id="sandboxEmail" placeholder="your@email.com" autocomplete="email">
                <button class="btn btn-primary" id="sandboxBtn" onclick="generateSandboxKey()" style="white-space:nowrap">Generate Key</button>
            </div>
            <div style="font-size:12px;color:var(--text-muted);text-align:left">
                Free sandbox &mdash; 50 test queries included. No credit card required.
            </div>

            <div class="key-display" id="keyDisplay">
                <div style="font-size:13px;color:var(--text-dim);margin-bottom:4px">Your API Key</div>
                <code id="keyValue"></code>
                <button class="copy-btn" onclick="copyKey()" style="position:static;margin-top:8px">Copy Key</button>
                <div class="key-warning">Save this key securely &mdash; it won&rsquo;t be shown again.</div>
            </div>

            <div id="sandboxError" style="display:none;margin-top:12px;padding:12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;font-size:13px;color:#ef4444"></div>

            <div id="quickstart" style="display:none;margin-top:24px;text-align:left">
                <h4 style="font-family:var(--font-heading);font-size:14px;margin-bottom:12px">Quick Start</h4>
                <div class="code-block" style="font-size:12px">
<span class="comment"># Test your new key</span>
<span class="keyword">curl</span> https://apai.co/api/v1/health \
  -H <span class="string">"Authorization: Bearer <span id="qsKey">ana_your_key</span>"</span>
                </div>
            </div>
        </div>
    </div>
</section>

<div class="section-divider"></div>

<!-- ========================================
     SECTION 9 — LIVE DEMO
     ======================================== -->
<section id="demo">
    <div class="section-inner section-center">
        <span class="section-label reveal">Live Demo</span>
        <h2 class="section-title reveal">See it running</h2>
        <p class="section-desc reveal">MYSTES runs on APAi. Every search, every booking, every credential route&mdash;powered by ANASTAS<em>i</em>A.</p>

        <div class="demo-frame reveal">
            <div class="demo-browser-bar">
                <div class="demo-dot"></div>
                <div class="demo-dot"></div>
                <div class="demo-dot"></div>
                <div class="demo-url">mystes.app</div>
            </div>
            <div class="demo-content">
                <h3>MYSTES</h3>
                <p>A production OTA powered entirely by APAi. Search flights across 102 markets, book with real-time arbitrage pricing, manage trips&mdash;all running on ANASTAS<em>i</em>A intelligence.</p>
                <a href="https://mystes.app" target="_blank" rel="noopener" class="btn btn-primary">Visit mystes.app &rarr;</a>
            </div>
        </div>
    </div>
</section>

<!-- ========================================
     FOOTER
     ======================================== -->
<footer class="footer">
    <div class="footer-inner">
        <div class="footer-brand">
            <h3>APAi</h3>
            <p>Ex astris cum amore</p>
        </div>
        <div class="footer-links">
            <div class="footer-col">
                <h4>Product</h4>
                <a href="#engine">Features</a>
                <a href="#network">Network</a>
                <a href="#architect">AI Terminal</a>
                <a href="#pricing">Pricing</a>
                <a href="/docs">Documentation</a>
            </div>
            <div class="footer-col">
                <h4>Get Started</h4>
                <a href="/signup">Sign Up</a>
                <a href="#sandbox">Sandbox</a>
                <a href="/demo">Live Demo</a>
                <a href="https://mystes.app" target="_blank" rel="noopener">MYSTES</a>
            </div>
            <div class="footer-col">
                <h4>Company</h4>
                <a href="#">Privacy Policy</a>
                <a href="#">Terms of Service</a>
            </div>
        </div>
    </div>
    <div class="footer-bottom">
        <span>&copy; 2026 MYSTES KYRIOS LLC. All rights reserved.</span>
        <span style="font-style:italic">ANASTAS<em>i</em>A &mdash; Intelligent Travel APAi</span>
    </div>
</footer>

<!-- ========================================
     JAVASCRIPT
     ======================================== -->
<script>
/* --- Navigation scroll effect --- */
const nav = document.getElementById('mainNav');
window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 50);
}, { passive: true });

/* --- Mobile menu toggle --- */
const toggle = document.getElementById('navToggle');
const links = document.getElementById('navLinks');
toggle.addEventListener('click', () => {
    toggle.classList.toggle('active');
    links.classList.toggle('open');
});
links.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => {
        toggle.classList.remove('active');
        links.classList.remove('open');
    });
});

/* --- Scroll reveal --- */
const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
        if (e.isIntersecting) {
            e.target.classList.add('visible');
        }
    });
}, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

/* --- Delivery tabs --- */
document.querySelectorAll('.delivery-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.delivery-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.delivery-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('panel-' + tab.dataset.panel).classList.add('active');
    });
});

/* --- Copy code --- */
function copyCode(btn) {
    const block = btn.parentElement;
    const text = block.textContent.replace('Copy', '').trim();
    navigator.clipboard.writeText(text).then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 1500);
    });
}

/* --- Sandbox key generation --- */
async function generateSandboxKey() {
    const email = document.getElementById('sandboxEmail').value.trim();
    const btn = document.getElementById('sandboxBtn');
    const display = document.getElementById('keyDisplay');
    const errEl = document.getElementById('sandboxError');

    errEl.style.display = 'none';
    display.style.display = 'none';

    if (!email || !email.includes('@')) {
        errEl.textContent = 'Please enter a valid email address.';
        errEl.style.display = 'block';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Generating...';

    try {
        const resp = await fetch('/api/v1/onboard/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agency_name: 'Sandbox-' + email.split('@')[0],
                email: email,
                contact_name: email.split('@')[0],
                agency_id: '000000',
                branch: 'SAND_001',
                session_token: 'sandbox_token',
                plan_id: 'pro',
                pricing_strategy: 'flat_fee',
                markup_percent: 10,
                markup_flat: 15,
            }),
        });
        const data = await resp.json();

        if (data.success && data.api_key) {
            document.getElementById('keyValue').textContent = data.api_key;
            document.getElementById('qsKey').textContent = data.api_key;
            display.style.display = 'block';
            document.getElementById('quickstart').style.display = 'block';
        } else {
            errEl.textContent = data.error || 'Could not generate key. Please try again.';
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Connection error. Please try again.';
        errEl.style.display = 'block';
    }

    btn.disabled = false;
    btn.textContent = 'Generate Key';
}

/* --- Copy key --- */
function copyKey() {
    const key = document.getElementById('keyValue').textContent;
    navigator.clipboard.writeText(key).then(() => {
        const btn = document.querySelector('#keyDisplay .copy-btn');
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy Key', 1500);
    });
}

/* --- Credential cost calculator --- */
function updateCalc() {
    const queries = parseFloat(document.getElementById('calcQueries').value) || 0;
    const queryFee = parseFloat(document.getElementById('calcQueryFee').value) || 0;
    const bookings = parseFloat(document.getElementById('calcBookings').value) || 0;
    const margin = parseFloat(document.getElementById('calcMargin').value) || 0;

    const queryRevenue = queries * queryFee;
    const bookingRevenue = bookings * margin;
    const total = queryRevenue + bookingRevenue;

    document.getElementById('calcTotal').textContent = '$' + total.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    document.getElementById('calcBreakdown').textContent =
        '$' + queryRevenue.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0}) +
        ' from query fees + $' +
        bookingRevenue.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0}) +
        ' from booking margins';
}
</script>

</body>
</html>"""


# ============================================================================
# PRICING HTML (standalone page)
# ============================================================================

PRICING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pricing — APAi</title>
<meta name="description" content="APAi pricing — transparent, flat, no negotiation. Pro $299, Enterprise $599, Scale $999. Same price for everyone.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root {
    --bg: #0a0612; --bg-card: rgba(255,255,255,0.04); --border: rgba(255,255,255,0.08);
    --border-hover: rgba(255,255,255,0.15); --accent: #6366f1; --accent-secondary: #a855f7;
    --accent-gradient: linear-gradient(135deg, #6366f1, #a855f7);
    --text: #f0eef5; --text-dim: #9994b8; --text-muted: #6b6689; --success: #22c55e;
    --font-heading: 'Space Grotesk', sans-serif; --font-body: 'Outfit', sans-serif;
    --radius: 16px; --radius-sm: 8px;
}
body { font-family: var(--font-body); background: var(--bg); color: var(--text); line-height: 1.6; -webkit-font-smoothing: antialiased; }
a { color: #818cf8; text-decoration: none; }
a:hover { color: #c4b5fd; }

.top-bar { padding: 20px 24px; max-width: 1100px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
.top-bar-logo { font-family: var(--font-heading); font-size: 22px; font-weight: 700; letter-spacing: 4px; background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.top-bar a.back { font-size: 13px; color: var(--text-dim); }

.page { max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; text-align: center; }
.page h1 { font-family: var(--font-heading); font-size: 36px; margin-bottom: 12px; }
.page .sub { font-size: 16px; color: var(--text-dim); margin-bottom: 48px; max-width: 540px; margin-left: auto; margin-right: auto; }

.glass { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: var(--radius); }

.pricing-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 24px; margin-bottom: 48px; }
.pricing-card { padding: 36px 28px; position: relative; overflow: hidden; }
.pricing-card.featured { border-color: rgba(99,102,241,0.4); background: rgba(99,102,241,0.06); }
.pricing-card.featured::before { content: 'MOST POPULAR'; position: absolute; top: 16px; right: -28px; transform: rotate(45deg); background: var(--accent-gradient); color: white; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 4px 36px; }
.pricing-tier { font-family: var(--font-heading); font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.pricing-price { font-size: 42px; font-weight: 700; margin-bottom: 4px; }
.pricing-price span { font-size: 16px; color: var(--text-dim); font-weight: 400; }
.pricing-desc { font-size: 13px; color: var(--text-muted); margin-bottom: 24px; }
.pricing-features { list-style: none; margin-bottom: 28px; text-align: left; }
.pricing-features li { padding: 7px 0; font-size: 13px; color: var(--text-dim); display: flex; align-items: center; gap: 10px; }
.pricing-features li::before { content: '\2713'; color: var(--success); font-weight: 700; }
.pricing-btn { display: block; width: 100%; text-align: center; padding: 12px; border-radius: var(--radius-sm); font-weight: 600; font-size: 14px; transition: all 0.2s; }
.pricing-btn-primary { background: var(--accent-gradient); color: white; }
.pricing-btn-primary:hover { opacity: 0.9; color: white; }
.pricing-btn-ghost { background: rgba(255,255,255,0.06); border: 1px solid var(--border); color: var(--text); }
.pricing-btn-ghost:hover { background: rgba(255,255,255,0.1); color: var(--text); }

.note { font-size: 14px; color: var(--text-dim); font-style: italic; }

/* Comparison table */
.compare-table { width: 100%; border-collapse: collapse; margin: 48px 0; text-align: left; }
.compare-table th { font-family: var(--font-heading); font-size: 13px; font-weight: 600; padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text-dim); }
.compare-table td { padding: 10px 16px; font-size: 13px; color: var(--text-dim); border-bottom: 1px solid rgba(255,255,255,0.04); }
.compare-table tr:hover td { background: rgba(255,255,255,0.02); }
.compare-table td:first-child { color: var(--text); font-weight: 500; }

@media (max-width: 768px) { .pricing-grid { grid-template-columns: 1fr; max-width: 400px; margin-left: auto; margin-right: auto; } .compare-table { font-size: 12px; } }
</style>
</head>
<body>

<div class="top-bar">
    <a href="/" class="top-bar-logo">APAi</a>
    <a href="/" class="back">&larr; Home</a>
</div>

<div class="page">
    <h1>Pricing</h1>
    <p class="sub">Same price for everyone. No enterprise deals. No custom contracts. Flat pricing levels the playing field.</p>

    <div class="pricing-grid">
        <div class="glass pricing-card">
            <div class="pricing-tier">Pro</div>
            <div class="pricing-price">$299<span>/mo</span></div>
            <div class="pricing-desc">I&rsquo;m getting started.</div>
            <ul class="pricing-features">
                <li>500 ANASTAS<em>i</em>A queries/mo</li>
                <li>$0.12 per overage query</li>
                <li>5% credential routing fee</li>
                <li>Credential vault &mdash; 3 credentials</li>
                <li>1 team seat (owner)</li>
                <li>Turnkey OTA + admin dashboard</li>
                <li>ANASTAS<em>i</em>A Terminal</li>
                <li>Basic analytics</li>
                <li>Network access</li>
            </ul>
            <a href="/signup" class="pricing-btn pricing-btn-ghost">Get Started</a>
        </div>

        <div class="glass pricing-card featured">
            <div class="pricing-tier">Enterprise</div>
            <div class="pricing-price">$599<span>/mo</span></div>
            <div class="pricing-desc">I&rsquo;m running a business.</div>
            <ul class="pricing-features">
                <li>2,000 ANASTAS<em>i</em>A queries/mo</li>
                <li>$0.08 per overage query</li>
                <li>3% credential routing fee</li>
                <li>Credential vault &mdash; 10 credentials</li>
                <li>5 team seats with roles</li>
                <li>White-label branding</li>
                <li>Full revenue analytics</li>
                <li>Webhook system</li>
                <li>Transaction audit trail</li>
            </ul>
            <a href="/signup" class="pricing-btn pricing-btn-primary">Get Started</a>
        </div>

        <div class="glass pricing-card">
            <div class="pricing-tier">Scale</div>
            <div class="pricing-price">$999<span>/mo</span></div>
            <div class="pricing-desc">I&rsquo;m building an empire.</div>
            <ul class="pricing-features">
                <li>5,000 ANASTAS<em>i</em>A queries/mo</li>
                <li>$0.05 per overage query</li>
                <li>2% credential routing fee</li>
                <li>Unlimited credentials</li>
                <li>Unlimited team seats</li>
                <li>Network intelligence feed</li>
                <li>Booking failure recovery</li>
                <li>Credential health monitoring</li>
                <li>Priority support (4h response)</li>
            </ul>
            <a href="/signup" class="pricing-btn pricing-btn-ghost">Get Started</a>
        </div>
    </div>

    <p class="note">All tiers include the full ANASTAS<em>i</em>A intelligence engine&mdash;no model downgrading. Same 111+ API endpoints. Same encrypted vault. Free sandbox available.</p>

    <table class="compare-table">
        <thead>
            <tr>
                <th>Feature</th>
                <th>Pro</th>
                <th>Enterprise</th>
                <th>Scale</th>
            </tr>
        </thead>
        <tbody>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">USAGE &amp; PRICING</td></tr>
            <tr><td>Monthly price</td><td>$299</td><td>$599</td><td>$999</td></tr>
            <tr><td>Included queries</td><td>500</td><td>2,000</td><td>5,000</td></tr>
            <tr><td>Overage rate</td><td>$0.12</td><td>$0.08</td><td>$0.05</td></tr>
            <tr><td>Credential routing fee</td><td>5%</td><td>3%</td><td>2%</td></tr>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">CORE PLATFORM</td></tr>
            <tr><td>Full API access (111+ endpoints)</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Turnkey OTA template</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Admin dashboard</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>ANASTAS<em>i</em>A Terminal</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Knowledge card intelligence</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Sandbox environment</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Network access (route &amp; be routed)</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">CREDENTIALS &amp; TEAM</td></tr>
            <tr><td>Credential vault</td><td>3 credentials</td><td>10 credentials</td><td>Unlimited</td></tr>
            <tr><td>Team seats</td><td>1 (owner)</td><td>5 (with roles)</td><td>Unlimited</td></tr>
            <tr><td>Team roles (admin, ops, finance, dev)</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">ANALYTICS &amp; MONITORING</td></tr>
            <tr><td>Basic analytics (bookings, revenue)</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Full revenue analytics (P&amp;L per route)</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Transaction audit trail</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Query budget controls</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Network intelligence feed</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr><td>Provider reputation dashboard</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr><td>Credential health monitoring</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr><td>Revenue forecasting</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">BRANDING &amp; INTEGRATION</td></tr>
            <tr><td>Basic branding (logo, colors)</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>White-label (remove APAi branding)</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Custom notification templates</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Webhook system</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Dynamic / seasonal terms</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Bulk operations</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr><td>Data export (no lock-in)</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr style="background:rgba(255,255,255,0.02)"><td colspan="4" style="font-weight:600;color:var(--accent-light);font-size:12px;letter-spacing:1px;padding-top:16px">RELIABILITY &amp; SUPPORT</td></tr>
            <tr><td>Booking failure recovery</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
            <tr><td>Community support + docs</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Email support (24h response)</td><td>&mdash;</td><td>&#10003;</td><td>&#10003;</td></tr>
            <tr><td>Priority support (4h response)</td><td>&mdash;</td><td>&mdash;</td><td>&#10003;</td></tr>
        </tbody>
    </table>

    <div style="margin-top:48px">
        <a href="/signup" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#6366f1,#a855f7);color:white;border-radius:8px;font-weight:600;font-size:15px;transition:all 0.2s">Get Started &rarr;</a>
    </div>
</div>

</body>
</html>"""


# ============================================================================
# DOCS HTML
# ============================================================================

DOCS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Documentation — APAi</title>
<meta name="description" content="APAi API documentation. Get started with the intelligent travel booking engine in minutes.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root {
    --bg: #0a0612; --bg-card: rgba(255,255,255,0.04); --border: rgba(255,255,255,0.08);
    --accent: #6366f1; --accent-gradient: linear-gradient(135deg, #6366f1, #a855f7);
    --text: #f0eef5; --text-dim: #9994b8; --text-muted: #6b6689; --success: #22c55e;
    --font-heading: 'Space Grotesk', sans-serif; --font-body: 'Outfit', sans-serif;
    --radius: 16px; --radius-sm: 8px;
}
body { font-family: var(--font-body); background: var(--bg); color: var(--text); line-height: 1.6; -webkit-font-smoothing: antialiased; }
a { color: #818cf8; text-decoration: none; }
a:hover { color: #c4b5fd; }

.top-bar { padding: 20px 24px; max-width: 900px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
.top-bar-logo { font-family: var(--font-heading); font-size: 22px; font-weight: 700; letter-spacing: 4px; background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

.docs { max-width: 900px; margin: 0 auto; padding: 40px 24px 80px; }
.docs h1 { font-family: var(--font-heading); font-size: 32px; margin-bottom: 8px; }
.docs .lead { font-size: 16px; color: var(--text-dim); margin-bottom: 48px; }
.docs h2 { font-family: var(--font-heading); font-size: 22px; margin: 48px 0 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.docs h3 { font-size: 16px; font-weight: 600; margin: 24px 0 8px; }
.docs p { font-size: 14px; color: var(--text-dim); line-height: 1.7; margin-bottom: 16px; }
.docs ul { list-style: none; margin-bottom: 16px; }
.docs ul li { padding: 4px 0; font-size: 14px; color: var(--text-dim); }
.docs ul li::before { content: '\2022'; color: var(--accent); font-weight: 700; margin-right: 8px; }

.code-block {
    background: #12101e; border: 1px solid var(--border); border-radius: var(--radius-sm);
    padding: 20px; overflow-x: auto; font-family: 'SF Mono','Fira Code','Consolas',monospace;
    font-size: 13px; line-height: 1.7; color: #d4d4d8; margin: 16px 0; position: relative;
}
.comment { color: #6b7280; } .string { color: #a78bfa; } .keyword { color: #f472b6; }
.copy-btn { position: absolute; top: 8px; right: 8px; padding: 4px 10px; background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: 6px; color: var(--text-muted); font-size: 11px; cursor: pointer; font-family: var(--font-body); }

.endpoint-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm); margin: 12px 0; overflow: hidden; }
.endpoint-header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }
.endpoint-method { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; font-family: monospace; }
.method-get { background: rgba(34,197,94,0.15); color: #22c55e; }
.method-post { background: rgba(59,130,246,0.15); color: #60a5fa; }
.method-put { background: rgba(245,158,11,0.15); color: #f59e0b; }
.method-delete { background: rgba(239,68,68,0.15); color: #ef4444; }
.endpoint-path { font-family: monospace; font-size: 13px; }
.endpoint-desc { font-size: 12px; color: var(--text-muted); margin-left: auto; }

@media (max-width: 768px) { .endpoint-desc { display: none; } }
</style>
</head>
<body>

<div class="top-bar">
    <a href="/" class="top-bar-logo">APAi</a>
    <a href="/" style="font-size:13px;color:var(--text-dim)">&larr; Home</a>
</div>

<div class="docs">
    <h1>Documentation</h1>
    <p class="lead">Get started with the APAi intelligent travel booking engine.</p>

    <h2>Authentication</h2>
    <p>All API requests require a Bearer token. Include your API key in the <code style="background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;font-size:13px">Authorization</code> header:</p>
    <div class="code-block">
Authorization: Bearer ana_your_api_key_here
    </div>
    <p>Get your API key by <a href="/signup">signing up</a> or generating a <a href="/#sandbox">sandbox key</a>.</p>

    <h2>Base URL</h2>
    <div class="code-block">
https://apai.co/api/v1
    </div>

    <h2>Quick Start</h2>
    <h3>1. Health Check</h3>
    <div class="code-block">
<span class="keyword">curl</span> https://apai.co/api/v1/health \
  -H <span class="string">"Authorization: Bearer ana_your_key"</span>
    </div>

    <h3>2. Search Flights</h3>
    <div class="code-block">
<span class="keyword">curl</span> -X POST https://apai.co/api/v1/search/flights \
  -H <span class="string">"Authorization: Bearer ana_your_key"</span> \
  -H <span class="string">"Content-Type: application/json"</span> \
  -d <span class="string">'{
    "origin": "JFK",
    "destination": "LHR",
    "departure_date": "2026-06-15",
    "adults": 1,
    "cabin_class": "economy"
  }'</span>
    </div>

    <h3>3. Create Booking</h3>
    <div class="code-block">
<span class="keyword">curl</span> -X POST https://apai.co/api/v1/booking/create \
  -H <span class="string">"Authorization: Bearer ana_your_key"</span> \
  -H <span class="string">"Content-Type: application/json"</span> \
  -d <span class="string">'{
    "offer_id": "off_abc123",
    "passengers": [{
      "given_name": "John",
      "family_name": "Doe",
      "born_on": "1990-01-15",
      "gender": "m",
      "email": "john@example.com",
      "phone": "+1234567890"
    }]
  }'</span>
    </div>

    <h2>Core Endpoints</h2>

    <h3>Search</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/health</span><span class="endpoint-desc">Health check (no auth)</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/search/airports</span><span class="endpoint-desc">Airport search</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/search/flights</span><span class="endpoint-desc">Search flights</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/search/results</span><span class="endpoint-desc">Poll search results</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/search/fare-rules</span><span class="endpoint-desc">Fare rules</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/search/seatmap</span><span class="endpoint-desc">Seat map</span></div></div>

    <h3>Booking</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/booking/create</span><span class="endpoint-desc">Create booking</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/booking/search</span><span class="endpoint-desc">Search bookings</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/booking/document</span><span class="endpoint-desc">Get ticket document</span></div></div>

    <h3>Chat &amp; Assist</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/chat</span><span class="endpoint-desc">AI chat session</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/assist</span><span class="endpoint-desc">Admin assistant</span></div></div>

    <h3>Admin</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/admin/config</span><span class="endpoint-desc">Get agency config</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-put">PUT</span><span class="endpoint-path">/api/v1/admin/config/pricing</span><span class="endpoint-desc">Update pricing</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-put">PUT</span><span class="endpoint-path">/api/v1/admin/config/branding</span><span class="endpoint-desc">Update branding</span></div></div>

    <h3>Billing</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/billing/plans</span><span class="endpoint-desc">Available plans</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/billing/subscription</span><span class="endpoint-desc">Current subscription</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/billing/cost</span><span class="endpoint-desc">Current usage cost</span></div></div>

    <h3>Knowledge &amp; Intelligence</h3>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-post">POST</span><span class="endpoint-path">/api/v1/knowledge/learn</span><span class="endpoint-desc">Teach new knowledge</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/knowledge/catalog</span><span class="endpoint-desc">Knowledge catalog</span></div></div>
    <div class="endpoint-card"><div class="endpoint-header"><span class="endpoint-method method-get">GET</span><span class="endpoint-path">/api/v1/updates/status</span><span class="endpoint-desc">Update pipeline status</span></div></div>

    <h2>Response Format</h2>
    <p>All responses are JSON. Successful responses include the requested data. Errors include an <code style="background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;font-size:13px">error</code> field:</p>
    <div class="code-block">
<span class="comment">// Success</span>
{ <span class="string">"status"</span>: <span class="string">"healthy"</span>, <span class="string">"active_sessions"</span>: 3 }

<span class="comment">// Error</span>
{ <span class="string">"error"</span>: <span class="string">"Invalid API key"</span> }
    </div>

    <h2>Rate Limits</h2>
    <p>Rate limits are based on your subscription tier. The <code style="background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;font-size:13px">X-RateLimit-Remaining</code> header indicates remaining requests.</p>

    <div style="margin-top:48px;text-align:center">
        <p style="color:var(--text-muted);font-size:14px">Need help? Contact us at <a href="mailto:support@apai.co">support@apai.co</a></p>
    </div>
</div>

<script>
function copyCode(btn) {
    const block = btn.parentElement;
    navigator.clipboard.writeText(block.textContent.replace('Copy','').trim()).then(() => {
        btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 1500);
    });
}
</script>
</body>
</html>"""


# ============================================================================
# DEMO HTML
# ============================================================================

DEMO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Live Demo — APAi</title>
<meta name="description" content="See APAi in action. MYSTES is a production OTA powered entirely by APAi and ANASTASiA.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root {
    --bg: #0a0612; --bg-card: rgba(255,255,255,0.04); --border: rgba(255,255,255,0.08);
    --accent: #6366f1; --accent-gradient: linear-gradient(135deg, #6366f1, #a855f7);
    --text: #f0eef5; --text-dim: #9994b8; --text-muted: #6b6689; --success: #22c55e;
    --font-heading: 'Space Grotesk', sans-serif; --font-body: 'Outfit', sans-serif;
    --radius: 16px; --radius-sm: 8px;
}
body { font-family: var(--font-body); background: var(--bg); color: var(--text); line-height: 1.6; -webkit-font-smoothing: antialiased; min-height: 100vh; }
a { color: #818cf8; text-decoration: none; }

.top-bar { padding: 20px 24px; max-width: 900px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
.top-bar-logo { font-family: var(--font-heading); font-size: 22px; font-weight: 700; letter-spacing: 4px; background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

.demo-page { max-width: 900px; margin: 0 auto; padding: 40px 24px 80px; text-align: center; }
.demo-page h1 { font-family: var(--font-heading); font-size: 32px; margin-bottom: 12px; }
.demo-page .lead { font-size: 16px; color: var(--text-dim); margin-bottom: 48px; max-width: 560px; margin-left: auto; margin-right: auto; line-height: 1.7; }

.demo-frame { border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border); background: rgba(255,255,255,0.02); margin-bottom: 48px; }
.demo-bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border); }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot:nth-child(1) { background: #ef4444; } .dot:nth-child(2) { background: #f59e0b; } .dot:nth-child(3) { background: #22c55e; }
.demo-url { flex: 1; margin-left: 12px; padding: 6px 12px; background: rgba(255,255,255,0.04); border-radius: 6px; font-size: 12px; color: var(--text-dim); font-family: monospace; }
.demo-body { padding: 64px 24px; }
.demo-body h2 { font-family: var(--font-heading); font-size: 28px; margin-bottom: 12px; }
.demo-body p { font-size: 15px; color: var(--text-dim); max-width: 480px; margin: 0 auto 32px; line-height: 1.7; }

.demo-btn { display: inline-block; padding: 14px 32px; background: var(--accent-gradient); color: white; border-radius: var(--radius-sm); font-weight: 600; font-size: 15px; transition: all 0.2s; }
.demo-btn:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(99,102,241,0.3); color: white; }

.features { display: grid; grid-template-columns: repeat(3,1fr); gap: 24px; text-align: left; margin-top: 48px; }
.feature { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 24px; }
.feature h3 { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.feature p { font-size: 13px; color: var(--text-dim); line-height: 1.6; }
@media (max-width: 768px) { .features { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<div class="top-bar">
    <a href="/" class="top-bar-logo">APAi</a>
    <a href="/" style="font-size:13px;color:var(--text-dim)">&larr; Home</a>
</div>

<div class="demo-page">
    <h1>Live Demo</h1>
    <p class="lead">MYSTES is a production OTA powered entirely by APAi. Every search, every booking, every credential route&mdash;driven by ANASTAS<em>i</em>A intelligence.</p>

    <div class="demo-frame">
        <div class="demo-bar">
            <div class="dot"></div><div class="dot"></div><div class="dot"></div>
            <div class="demo-url">mystes.app</div>
        </div>
        <div class="demo-body">
            <h2>MYSTES</h2>
            <p>Search flights across 102 markets. Real-time arbitrage pricing. Intelligent credential routing. Trip planning. Hotels, cars, and activities&mdash;all on one platform.</p>
            <a href="https://mystes.app" target="_blank" rel="noopener" class="demo-btn">Visit mystes.app &rarr;</a>
        </div>
    </div>

    <div class="features">
        <div class="feature">
            <h3>Global Arbitrage</h3>
            <p>Point-of-sale arbitrage across 102 markets. Find fares that domestic searches miss.</p>
        </div>
        <div class="feature">
            <h3>Real-Time Intelligence</h3>
            <p>Knowledge cards process every search at zero AI cost. Intelligence that never sleeps.</p>
        </div>
        <div class="feature">
            <h3>Full Automation</h3>
            <p>Search, compare, book, issue. The entire workflow automated from consumer to confirmation.</p>
        </div>
    </div>

    <div style="margin-top:64px">
        <p style="color:var(--text-muted);font-size:14px;margin-bottom:16px">Ready to build your own?</p>
        <a href="/signup" class="demo-btn">Get Started with APAi &rarr;</a>
    </div>
</div>

</body>
</html>"""


# ============================================================================
# ROUTE REGISTRATION
# ============================================================================

def register_website_routes(app, onboarding=None, billing_manager=None):
    """Register marketing website routes — homepage, pricing, docs, demo."""
    from flask import Response

    @app.route("/")
    def homepage():
        """APAi homepage — marketing landing page."""
        return Response(HOMEPAGE_HTML, mimetype="text/html")

    @app.route("/pricing")
    def pricing_page():
        """APAi pricing page."""
        return Response(PRICING_HTML, mimetype="text/html")

    @app.route("/docs")
    def docs_page():
        """APAi API documentation."""
        return Response(DOCS_HTML, mimetype="text/html")

    @app.route("/demo")
    def demo_page():
        """APAi live demo page."""
        return Response(DEMO_HTML, mimetype="text/html")

    @app.errorhandler(404)
    def not_found(e):
        """Branded 404 page."""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 — APAi</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600&family=Outfit:wght@400&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Outfit',sans-serif;background:#0a0612;color:#f0eef5;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center}
h1{font-family:'Space Grotesk',sans-serif;font-size:72px;background:linear-gradient(135deg,#6366f1,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:12px}
p{color:#9994b8;font-size:16px;margin-bottom:24px}
a{color:#818cf8;text-decoration:none;font-size:14px}
a:hover{color:#c4b5fd}
</style>
</head>
<body>
<div>
<h1>404</h1>
<p>This page doesn't exist.</p>
<a href="/">&larr; Back to APAi</a>
</div>
</body>
</html>"""
        return Response(html, status=404, mimetype="text/html")

    logger.info("APAi website routes registered: /, /pricing, /docs, /demo")
