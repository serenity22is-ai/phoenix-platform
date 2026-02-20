/**
 * MYSTES — The Eyes of the Oracle
 * Realistic feminine eyes matching pencil-sketch reference
 * White silhouette on dark background, crystal green iris with hint of gold
 * Eyes rest closed. When the seeker searches, they open.
 */
(function () {
  'use strict';

  var canvas = document.getElementById('divine-eyes-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  // ─── State ──────────────────────────────────────────────────
  var W = 0, H = 0;
  var openAmount = 0;
  var targetOpen = 0;
  var time = 0;
  var glowIntensity = 0;
  var irisRotation = 0;
  var lastActivity = 0;
  var hasEverOpened = false;

  // ─── Colors ─────────────────────────────────────────────────
  // Iris — crystal green with the lightest hint of gold
  var IRIS_OUTER    = '#0a4d30';   // dark emerald limbal ring
  var IRIS_MID      = '#15a857';   // vivid crystal green
  var IRIS_INNER    = '#42d68a';   // bright crystal green
  var IRIS_EDGE     = '#062e1c';   // darkest edge
  var PUPIL_COLOR   = '#050505';
  // White silhouette linework
  var LASH_COLOR    = 'rgba(255, 255, 255, 0.7)';
  var OUTLINE_COLOR = 'rgba(255, 255, 255, 0.55)';
  var BROW_COLOR    = 'rgba(255, 255, 255, 0.6)';

  // ─── Pre-generate lash arrays (once, not per frame) ─────────
  var cachedLashes = {};
  function getCachedLashes(key, eyeW, eyeH, isUpper, side) {
    if (cachedLashes[key]) return cachedLashes[key];
    cachedLashes[key] = generateLashes(eyeW, eyeH, isUpper, side);
    return cachedLashes[key];
  }

  // ─── Resize ─────────────────────────────────────────────────
  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cachedLashes = {}; // invalidate on resize
  }
  resize();
  window.addEventListener('resize', resize, { passive: true });

  // ─── Eyelash Generator ──────────────────────────────────────
  function generateLashes(eyeW, eyeH, isUpper, side) {
    var lashes = [];
    var count = isUpper ? 40 : 20;
    var flip = side === 'right' ? -1 : 1;

    for (var i = 0; i < count; i++) {
      var t = (i + 0.5) / count;
      var outerBias = side === 'left' ? t : (1 - t);
      // Longer lashes toward outer corner, matching the reference
      var lengthMult = 0.5 + outerBias * 1.0 + (Math.random() * 0.1 - 0.05);
      // Slight natural variation
      var randLen = 0.92 + Math.random() * 0.16;

      if (isUpper) {
        lashes.push({
          t: t,
          length: eyeH * 0.45 * lengthMult * randLen,
          curl: (0.15 + outerBias * 0.5) * flip * -1,
          thickness: 1.0 + outerBias * 1.0,
          angle: -Math.PI / 2 + (t - 0.5) * 0.7 + (outerBias - 0.5) * 0.25
        });
      } else {
        lashes.push({
          t: t,
          length: eyeH * 0.18 * lengthMult * randLen,
          curl: (0.08 + outerBias * 0.15) * flip,
          thickness: 0.6 + outerBias * 0.4,
          angle: Math.PI / 2 + (t - 0.5) * 0.35
        });
      }
    }
    return lashes;
  }

  // ─── Eye Path ───────────────────────────────────────────────
  function getEyePaths(cx, cy, w, h, open) {
    var ix = cx - w * 0.5;
    var iy = cy + h * 0.02;

    // Outer corner with slight upturn
    var ox = cx + w * 0.5;
    var oy = cy - h * 0.06;

    // Upper lid — wider arc for more open look matching reference
    var upperArc = h * 0.55 * open;
    var ucp1x = cx - w * 0.22;
    var ucp1y = cy - upperArc;
    var ucp2x = cx + w * 0.26;
    var ucp2y = cy - upperArc * 0.92;

    // Lower lid
    var lowerDrop = h * 0.2 * open;
    var lcp1x = cx - w * 0.18;
    var lcp1y = cy + lowerDrop;
    var lcp2x = cx + w * 0.22;
    var lcp2y = cy + lowerDrop * 0.82;

    return {
      inner: { x: ix, y: iy },
      outer: { x: ox, y: oy },
      upper: { cp1: { x: ucp1x, y: ucp1y }, cp2: { x: ucp2x, y: ucp2y } },
      lower: { cp1: { x: lcp1x, y: lcp1y }, cp2: { x: lcp2x, y: lcp2y } }
    };
  }

  function traceEyeOpening(cx, cy, w, h, open) {
    var p = getEyePaths(cx, cy, w, h, open);
    ctx.beginPath();
    ctx.moveTo(p.inner.x, p.inner.y);
    ctx.bezierCurveTo(p.upper.cp1.x, p.upper.cp1.y, p.upper.cp2.x, p.upper.cp2.y, p.outer.x, p.outer.y);
    ctx.bezierCurveTo(p.lower.cp2.x, p.lower.cp2.y, p.lower.cp1.x, p.lower.cp1.y, p.inner.x, p.inner.y);
    ctx.closePath();
  }

  // ─── Bezier utilities ──────────────────────────────────────
  function bezierPoint(t, p0, cp1, cp2, p1) {
    var mt = 1 - t, mt2 = mt * mt, mt3 = mt2 * mt;
    var t2 = t * t, t3 = t2 * t;
    return {
      x: mt3 * p0.x + 3 * mt2 * t * cp1.x + 3 * mt * t2 * cp2.x + t3 * p1.x,
      y: mt3 * p0.y + 3 * mt2 * t * cp1.y + 3 * mt * t2 * cp2.y + t3 * p1.y
    };
  }

  function bezierTangent(t, p0, cp1, cp2, p1) {
    var mt = 1 - t, mt2 = mt * mt, t2 = t * t;
    return {
      x: 3 * mt2 * (cp1.x - p0.x) + 6 * mt * t * (cp2.x - cp1.x) + 3 * t2 * (p1.x - cp2.x),
      y: 3 * mt2 * (cp1.y - p0.y) + 6 * mt * t * (cp2.y - cp1.y) + 3 * t2 * (p1.y - cp2.y)
    };
  }

  // ─── Draw Iris — Crystal Green ──────────────────────────────
  function drawIris(cx, cy, radius, t) {
    ctx.save();

    // Base gradient — crystal green, bright and clear
    var baseGrad = ctx.createRadialGradient(cx, cy, radius * 0.06, cx, cy, radius);
    baseGrad.addColorStop(0, IRIS_INNER);       // bright crystal center
    baseGrad.addColorStop(0.3, IRIS_MID);        // vivid emerald
    baseGrad.addColorStop(0.7, IRIS_OUTER);      // dark emerald
    baseGrad.addColorStop(1, IRIS_EDGE);          // darkest rim
    ctx.fillStyle = baseGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();

    // Radial stroma fibers — crystal-like radial patterns
    var fiberCount = 90;
    for (var f = 0; f < fiberCount; f++) {
      var angle = (f / fiberCount) * Math.PI * 2 + irisRotation * 0.015;
      var innerR = radius * 0.2;
      var outerR = radius * (0.78 + Math.sin(f * 4.7 + t * 0.15) * 0.1);
      var fiberAlpha = 0.1 + Math.sin(f * 3.1 + t * 0.2) * 0.04;

      // Mostly green fibers with very occasional gold hint
      if (f % 8 === 0) {
        // Very subtle gold — "lightest hint"
        ctx.strokeStyle = 'rgba(190, 175, 90, ' + (fiberAlpha * 0.6) + ')';
      } else {
        ctx.strokeStyle = 'rgba(30, 200, 100, ' + (fiberAlpha * 0.7) + ')';
      }
      ctx.lineWidth = 0.6 + Math.sin(f * 1.7) * 0.25;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(angle) * innerR, cy + Math.sin(angle) * innerR);
      var midAngle = angle + Math.sin(f * 2.3 + t * 0.1) * 0.06;
      var midR = (innerR + outerR) * 0.5;
      ctx.quadraticCurveTo(
        cx + Math.cos(midAngle) * midR,
        cy + Math.sin(midAngle) * midR,
        cx + Math.cos(angle + Math.sin(f) * 0.025) * outerR,
        cy + Math.sin(angle + Math.sin(f) * 0.025) * outerR
      );
      ctx.stroke();
    }

    // Subtle gold warmth ring near pupil — the "lightest hint of gold"
    ctx.globalCompositeOperation = 'overlay';
    var goldGrad = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, radius * 0.4);
    goldGrad.addColorStop(0, 'rgba(210, 195, 100, 0.12)');
    goldGrad.addColorStop(0.5, 'rgba(200, 180, 80, 0.06)');
    goldGrad.addColorStop(1, 'rgba(200, 180, 80, 0)');
    ctx.fillStyle = goldGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.4, 0, Math.PI * 2);
    ctx.fill();

    // Light direction — subtle bright spot for depth
    var sunX = cx - radius * 0.25;
    var sunY = cy - radius * 0.2;
    var sunGrad = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, radius * 0.6);
    sunGrad.addColorStop(0, 'rgba(100, 220, 140, 0.18)');
    sunGrad.addColorStop(0.5, 'rgba(80, 200, 120, 0.06)');
    sunGrad.addColorStop(1, 'rgba(80, 200, 120, 0)');
    ctx.fillStyle = sunGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalCompositeOperation = 'source-over';

    // Pupil
    var pupilSize = radius * (0.28 + Math.sin(t * 0.4) * 0.015);
    var pupilGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, pupilSize);
    pupilGrad.addColorStop(0, PUPIL_COLOR);
    pupilGrad.addColorStop(0.85, PUPIL_COLOR);
    pupilGrad.addColorStop(1, 'rgba(5, 5, 5, 0.5)');
    ctx.fillStyle = pupilGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, pupilSize, 0, Math.PI * 2);
    ctx.fill();

    // Pupil edge — very faint green glow
    ctx.strokeStyle = 'rgba(30, 180, 90, 0.25)';
    ctx.lineWidth = radius * 0.015;
    ctx.beginPath();
    ctx.arc(cx, cy, pupilSize * 1.03, 0, Math.PI * 2);
    ctx.stroke();

    // Catch-light 1 — main reflection (upper-left, prominent like in reference)
    var hlx = cx - radius * 0.25;
    var hly = cy - radius * 0.2;
    var hlr = radius * 0.15;
    var hlGrad = ctx.createRadialGradient(hlx, hly, 0, hlx, hly, hlr);
    hlGrad.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
    hlGrad.addColorStop(0.25, 'rgba(255, 255, 255, 0.6)');
    hlGrad.addColorStop(0.6, 'rgba(255, 255, 255, 0.15)');
    hlGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = hlGrad;
    ctx.beginPath();
    ctx.arc(hlx, hly, hlr, 0, Math.PI * 2);
    ctx.fill();

    // Catch-light 2 — small secondary (lower-right, like in reference)
    var hl2x = cx + radius * 0.15;
    var hl2y = cy + radius * 0.12;
    var hl2r = radius * 0.06;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.beginPath();
    ctx.arc(hl2x, hl2y, hl2r, 0, Math.PI * 2);
    ctx.fill();

    // Limbal ring — dark prominent edge
    ctx.strokeStyle = 'rgba(6, 30, 18, 0.75)';
    ctx.lineWidth = radius * 0.055;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.97, 0, Math.PI * 2);
    ctx.stroke();

    ctx.restore();
  }

  // ─── Draw Eyebrow ──────────────────────────────────────────
  function drawEyebrow(cx, cy, eyeW, eyeH, open, side) {
    if (open < 0.01 && !hasEverOpened) return;
    var alpha = hasEverOpened ? Math.max(0.3, open * 0.7) : 0;
    if (alpha < 0.01) return;

    ctx.save();
    var flip = side === 'right' ? -1 : 1;

    // Brow position — above the eye, arch matching reference
    var browStartX = cx - eyeW * 0.42 * flip;
    var browStartY = cy - eyeH * (0.7 + open * 0.25);
    var browPeakX = cx - eyeW * 0.05 * flip;
    var browPeakY = cy - eyeH * (1.05 + open * 0.3);
    var browEndX = cx + eyeW * 0.45 * flip;
    var browEndY = cy - eyeH * (0.65 + open * 0.2);

    // Draw individual hair strokes along the brow arch
    var strokeCount = 35;
    for (var i = 0; i < strokeCount; i++) {
      var t = i / (strokeCount - 1);

      // Position along the brow arch (quadratic interpolation)
      var mt = 1 - t;
      var bx = mt * mt * browStartX + 2 * mt * t * browPeakX + t * t * browEndX;
      var by = mt * mt * browStartY + 2 * mt * t * browPeakY + t * t * browEndY;

      // Hair direction — follows the brow arch with upward angle
      var angle = Math.atan2(
        2 * mt * (browPeakY - browStartY) + 2 * t * (browEndY - browPeakY),
        2 * mt * (browPeakX - browStartX) + 2 * t * (browEndX - browPeakX)
      );

      // Hair strokes angle slightly upward in the arch, down at tails
      var hairAngle = angle - Math.PI * 0.5 + (t - 0.3) * 0.4 * flip;

      // Hair length — thicker in the middle, tapers at ends
      var thickness = Math.sin(t * Math.PI) * 0.8 + 0.2;
      if (t < 0.1) thickness *= t / 0.1;
      if (t > 0.85) thickness *= (1 - t) / 0.15;
      var hairLen = eyeH * 0.15 * thickness * (0.85 + Math.random() * 0.3);

      // Slight random offset for natural look
      var offX = (Math.random() - 0.5) * 1.5;
      var offY = (Math.random() - 0.5) * 1.5;

      ctx.strokeStyle = 'rgba(255, 255, 255, ' + (alpha * (0.35 + thickness * 0.35)) + ')';
      ctx.lineWidth = 0.8 + thickness * 0.8;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(bx + offX, by + offY);
      ctx.lineTo(
        bx + Math.cos(hairAngle) * hairLen + offX,
        by + Math.sin(hairAngle) * hairLen + offY
      );
      ctx.stroke();
    }

    // Brow shape outline — very subtle guide stroke
    ctx.strokeStyle = 'rgba(255, 255, 255, ' + (alpha * 0.12) + ')';
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(browStartX, browStartY);
    ctx.quadraticCurveTo(browPeakX, browPeakY, browEndX, browEndY);
    ctx.stroke();

    ctx.restore();
  }

  // ─── Draw Eyelashes ─────────────────────────────────────────
  function drawLashes(paths, lashDefs, isUpper, open) {
    if (open < 0.02 && !isUpper) return;

    var p0, cp1, cp2, p1;
    if (isUpper) {
      p0 = paths.inner; cp1 = paths.upper.cp1; cp2 = paths.upper.cp2; p1 = paths.outer;
    } else {
      p0 = paths.inner; cp1 = paths.lower.cp1; cp2 = paths.lower.cp2; p1 = paths.outer;
    }

    for (var i = 0; i < lashDefs.length; i++) {
      var lash = lashDefs[i];
      var pt = bezierPoint(lash.t, p0, cp1, cp2, p1);
      var tan = bezierTangent(lash.t, p0, cp1, cp2, p1);
      var len = Math.sqrt(tan.x * tan.x + tan.y * tan.y);
      var nx, ny;
      if (isUpper) { nx = -tan.y / len; ny = tan.x / len; }
      else { nx = tan.y / len; ny = -tan.x / len; }

      var lashLen = lash.length;
      var endX = pt.x + nx * lashLen;
      var endY = pt.y + ny * lashLen;
      var curlX = pt.x + nx * lashLen * 0.6 + tan.x / len * lash.curl * lashLen;
      var curlY = pt.y + ny * lashLen * 0.6 + tan.y / len * lash.curl * lashLen;

      ctx.strokeStyle = LASH_COLOR;
      ctx.lineWidth = lash.thickness;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(pt.x, pt.y);
      ctx.quadraticCurveTo(curlX, curlY, endX, endY);
      ctx.stroke();

      // Double-stroke for hand-drawn feel
      if (lash.thickness > 1.2 && i % 3 === 0) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        ctx.lineWidth = 0.4;
        ctx.beginPath();
        ctx.moveTo(pt.x + 0.6, pt.y + 0.6);
        ctx.quadraticCurveTo(curlX + 1, curlY + 1, endX + 0.6, endY + 0.6);
        ctx.stroke();
      }
    }
  }

  // ─── Draw Single Eye ────────────────────────────────────────
  function drawEye(cx, cy, eyeW, eyeH, open, t, side) {
    if (open < 0.005 && !hasEverOpened) {
      drawClosedEyeHint(cx, cy, eyeW, eyeH, t, side);
      return;
    }

    var drawOpen = Math.max(open, 0.005);
    var paths = getEyePaths(cx, cy, eyeW, eyeH, drawOpen);

    // Subtle inner glow when opening
    if (open > 0.05) {
      ctx.save();
      var glowR = eyeW * 0.3 * open;
      var innerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      var ga = open * 0.2 * glowIntensity;
      innerGlow.addColorStop(0, 'rgba(255, 255, 255, ' + (ga * 0.5) + ')');
      innerGlow.addColorStop(0.5, 'rgba(255, 255, 255, ' + (ga * 0.2) + ')');
      innerGlow.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = innerGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Iris (clipped to eye opening)
    if (open > 0.02) {
      ctx.save();
      traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
      ctx.clip();

      // Sclera — white with slight transparency (not pure black void)
      var scleraGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, eyeW * 0.4);
      scleraGrad.addColorStop(0, 'rgba(220, 220, 225, 0.12)');
      scleraGrad.addColorStop(0.5, 'rgba(200, 200, 210, 0.08)');
      scleraGrad.addColorStop(1, 'rgba(180, 180, 190, 0.04)');
      ctx.fillStyle = scleraGrad;
      ctx.fill();

      var irisR = eyeH * 0.4 * (0.5 + open * 0.5);
      drawIris(cx, cy - eyeH * 0.01, irisR, t);

      ctx.restore();
    }

    // Eye outline
    ctx.save();
    traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
    ctx.strokeStyle = OUTLINE_COLOR;
    ctx.lineWidth = 1.8;
    ctx.stroke();

    // Ghost line for hand-drawn feel
    ctx.save();
    ctx.translate(0.5, 0.3);
    traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.lineWidth = 0.6;
    ctx.stroke();
    ctx.restore();

    // Crease line above upper lid
    if (open > 0.1) {
      var creaseOpen = drawOpen * 1.25;
      var creasePaths = getEyePaths(cx, cy - eyeH * 0.14, eyeW * 0.82, eyeH, creaseOpen);
      ctx.beginPath();
      ctx.moveTo(creasePaths.inner.x + eyeW * 0.06, creasePaths.inner.y);
      ctx.bezierCurveTo(
        creasePaths.upper.cp1.x, creasePaths.upper.cp1.y,
        creasePaths.upper.cp2.x, creasePaths.upper.cp2.y,
        creasePaths.outer.x - eyeW * 0.04, creasePaths.outer.y
      );
      ctx.strokeStyle = 'rgba(255, 255, 255, ' + (0.18 * open) + ')';
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }
    ctx.restore();

    // Eyeliner — bold upper lid line
    if (open > 0.03) {
      var linerPaths = getEyePaths(cx, cy, eyeW, eyeH, drawOpen);
      ctx.beginPath();
      ctx.moveTo(linerPaths.inner.x, linerPaths.inner.y);
      ctx.bezierCurveTo(
        linerPaths.upper.cp1.x, linerPaths.upper.cp1.y - 1.5,
        linerPaths.upper.cp2.x, linerPaths.upper.cp2.y - 1.5,
        linerPaths.outer.x + eyeW * 0.025, linerPaths.outer.y - eyeH * 0.025
      );
      ctx.strokeStyle = 'rgba(255, 255, 255, ' + (0.6 * Math.min(open * 2, 1)) + ')';
      ctx.lineWidth = 2.8;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    // Eyelashes
    var key = side + '_' + Math.round(eyeW);
    var upperLashes = getCachedLashes(key + '_upper', eyeW, eyeH, true, side);
    var lowerLashes = getCachedLashes(key + '_lower', eyeW, eyeH, false, side);
    drawLashes(paths, upperLashes, true, drawOpen);
    if (open > 0.1) {
      drawLashes(paths, lowerLashes, false, drawOpen);
    }
  }

  // ─── Closed Eye Hint ───────────────────────────────────────
  function drawClosedEyeHint(cx, cy, eyeW, eyeH, t, side) {
    ctx.save();
    var breathe = Math.sin(t * 0.5) * 0.3;
    var alpha = 0.2 + breathe * 0.05;

    var ix = cx - eyeW * 0.45;
    var ox = cx + eyeW * 0.45;
    var oy = cy - eyeH * 0.04;

    // Closed eye line
    ctx.beginPath();
    ctx.moveTo(ix, cy);
    ctx.bezierCurveTo(
      cx - eyeW * 0.12, cy - eyeH * 0.04,
      cx + eyeW * 0.18, cy - eyeH * 0.05,
      ox, oy
    );
    ctx.strokeStyle = 'rgba(255, 255, 255, ' + alpha + ')';
    ctx.lineWidth = 1.6;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Ghost stroke
    ctx.beginPath();
    ctx.moveTo(ix + 0.8, cy + 0.4);
    ctx.bezierCurveTo(
      cx - eyeW * 0.12 + 0.5, cy - eyeH * 0.03,
      cx + eyeW * 0.18 + 0.5, cy - eyeH * 0.04,
      ox + 0.5, oy + 0.5
    );
    ctx.strokeStyle = 'rgba(255, 255, 255, ' + (alpha * 0.3) + ')';
    ctx.lineWidth = 0.5;
    ctx.stroke();

    // Closed-eye lashes pointing down
    var lashCount = 14;
    for (var i = 0; i < lashCount; i++) {
      var lt = (i + 0.5) / lashCount;
      var lx = ix + (ox - ix) * lt;
      var ly = cy + (oy - cy) * lt - eyeH * 0.01;
      var outerBias = side === 'left' ? lt : (1 - lt);
      var lashLen = eyeH * 0.14 * (0.4 + outerBias * 0.8);

      ctx.beginPath();
      ctx.moveTo(lx, ly);
      ctx.quadraticCurveTo(
        lx + (outerBias - 0.3) * eyeW * 0.015,
        ly + lashLen * 0.55,
        lx + (outerBias - 0.4) * eyeW * 0.035,
        ly + lashLen
      );
      ctx.strokeStyle = 'rgba(255, 255, 255, ' + (alpha * 0.5) + ')';
      ctx.lineWidth = 0.7 + outerBias * 0.5;
      ctx.stroke();
    }

    // Draw eyebrow even when closed
    drawEyebrow(cx, cy, eyeW, eyeH, 0.15, side);

    ctx.restore();
  }

  // ─── Main Render ────────────────────────────────────────────
  function render() {
    ctx.clearRect(0, 0, W, H);

    var isMobile = W < 768;
    var eyeW = isMobile ? W * 0.32 : Math.min(W * 0.22, 300);
    var eyeH = eyeW * 0.42;
    var gap = isMobile ? W * 0.06 : eyeW * 0.35;

    var centerX = W / 2;
    var centerY = H * 0.4;

    var leftEyeX = centerX - gap / 2 - eyeW * 0.28;
    var rightEyeX = centerX + gap / 2 + eyeW * 0.28;

    // Draw eyebrows
    drawEyebrow(leftEyeX, centerY, eyeW, eyeH, openAmount, 'left');
    drawEyebrow(rightEyeX, centerY, eyeW, eyeH, openAmount, 'right');

    // Draw both eyes
    drawEye(leftEyeX, centerY, eyeW, eyeH, openAmount, time, 'left');
    drawEye(rightEyeX, centerY, eyeW, eyeH, openAmount, time, 'right');
  }

  // ─── Animation Loop ─────────────────────────────────────────
  var lastTime = 0;
  function animate(timestamp) {
    requestAnimationFrame(animate);

    var dt = Math.min((timestamp - lastTime) / 1000, 0.05);
    lastTime = timestamp;
    time += dt;

    // Smooth eyelid interpolation — smoother, more natural
    var speed = targetOpen > openAmount ? 2.0 : 1.2;
    openAmount += (targetOpen - openAmount) * speed * dt;
    if (Math.abs(openAmount - targetOpen) < 0.001) openAmount = targetOpen;

    // Glow
    var targetGlow = openAmount > 0.1 ? 1 : 0;
    glowIntensity += (targetGlow - glowIntensity) * dt * 2.5;

    // Slow iris rotation
    irisRotation += dt * 0.3;

    // Auto-close after 6 seconds of inactivity
    if (targetOpen > 0 && time - lastActivity > 6) {
      targetOpen = 0;
    }

    render();
  }
  requestAnimationFrame(animate);

  // ─── Search Event Binding ───────────────────────────────────
  function openEyes() {
    targetOpen = 1;
    lastActivity = time;
    hasEverOpened = true;
  }

  function keepAwake() {
    lastActivity = time;
    if (targetOpen < 1) targetOpen = 1;
  }

  // Event delegation
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el) return;
    var tag = el.tagName;
    var id = (el.id || '').toLowerCase();
    var cls = (el.className || '').toLowerCase();
    var placeholder = (el.placeholder || '').toLowerCase();

    if (tag === 'INPUT' || tag === 'TEXTAREA') {
      if (id.indexOf('search') !== -1 || id.indexOf('chat') !== -1 ||
          cls.indexOf('search') !== -1 || cls.indexOf('ai-input') !== -1 ||
          placeholder.indexOf('search') !== -1 || placeholder.indexOf('message') !== -1 ||
          placeholder.indexOf('where') !== -1 || placeholder.indexOf('find') !== -1 ||
          placeholder.indexOf('flight') !== -1) {
        openEyes();
      }
    }
  }, true);

  document.addEventListener('input', function () {
    if (targetOpen > 0) keepAwake();
  }, true);

  document.addEventListener('submit', function () {
    keepAwake();
  }, true);

  document.addEventListener('click', function (e) {
    var el = e.target;
    if (!el) return;
    var cls = (el.className || '').toLowerCase();
    var text = (el.textContent || '').toLowerCase();
    if (cls.indexOf('search') !== -1 || cls.indexOf('send') !== -1 ||
        text.indexOf('search') !== -1) {
      openEyes();
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && e.target === document.body)) {
      openEyes();
    }
  });

})();
