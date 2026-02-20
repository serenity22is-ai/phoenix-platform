/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║  MYSTES — The Eyes of the Oracle                            ║
 * ║  Divine feminine eyes that open upon seeking knowledge       ║
 * ║  "Mystes" — the initiated one who sees beyond the veil      ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * Canvas 2D — hand-drawn Da Vinci aesthetic
 * Eyes remain closed in meditative rest.
 * When the seeker searches, the eyes of gnosis open,
 * revealing irises of green-gold hazel —
 * forest and sunlight, the color of seeing.
 */
(function () {
  'use strict';

  var canvas = document.getElementById('divine-eyes-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  // ─── State ──────────────────────────────────────────────────
  var W = 0, H = 0;
  var openAmount = 0;       // 0 = closed, 1 = fully open
  var targetOpen = 0;
  var time = 0;
  var glowIntensity = 0;
  var irisRotation = 0;
  var particles = [];
  var lastActivity = 0;
  var hasEverOpened = false;

  // ─── Colors — Green-Gold Hazel (from reference) ─────────────
  var IRIS_OUTER    = '#3d6b35';   // deep forest green (limbal ring)
  var IRIS_MID      = '#6b9a4e';   // bright moss green
  var IRIS_INNER    = '#8fb86c';   // golden-green
  var IRIS_AMBER    = '#c4a44d';   // warm amber near pupil
  var IRIS_HIGHLIGHT = '#d4c87a';  // golden catch-light
  var IRIS_GLOW     = 'rgba(120, 170, 80, '; // + alpha + ')' — warm green glow
  var PUPIL_COLOR   = '#1a1208';   // warm near-black
  var SCLERA_COLOR  = 'rgba(245, 235, 225, 0.15)'; // warm off-white, very subtle
  var LASH_COLOR    = 'rgba(80, 60, 45, 0.8)';  // warm brown, natural
  var OUTLINE_COLOR = 'rgba(90, 70, 55, 0.55)';  // warm brown outline
  var GLOW_COLOR    = 'rgba(140, 180, 80, ';  // + alpha + ')' — golden-green glow

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
  }
  resize();
  window.addEventListener('resize', resize, { passive: true });

  // ─── Eyelash Generator ──────────────────────────────────────
  // Returns array of lash definitions for one eye
  function generateLashes(eyeW, eyeH, isUpper, side) {
    var lashes = [];
    var count = isUpper ? 32 : 18;
    var flip = side === 'right' ? -1 : 1;

    for (var i = 0; i < count; i++) {
      var t = (i + 0.5) / count;  // 0..1 along the lid
      // Longer lashes toward outer corner (t > 0.5 for left eye)
      var outerBias = side === 'left' ? t : (1 - t);
      var lengthMult = 0.6 + outerBias * 0.8 + Math.random() * 0.15;

      if (isUpper) {
        lashes.push({
          t: t,
          length: eyeH * 0.35 * lengthMult,
          curl: (0.2 + outerBias * 0.4) * flip * -1,
          thickness: 1.2 + outerBias * 0.8,
          angle: -Math.PI / 2 + (t - 0.5) * 0.6 + (outerBias - 0.5) * 0.3
        });
      } else {
        lashes.push({
          t: t,
          length: eyeH * 0.15 * lengthMult,
          curl: (0.1 + outerBias * 0.2) * flip,
          thickness: 0.8 + outerBias * 0.3,
          angle: Math.PI / 2 + (t - 0.5) * 0.4
        });
      }
    }
    return lashes;
  }

  // ─── Eye Path (almond shape) ────────────────────────────────
  // Returns the upper and lower lid paths for a given openAmount
  function getEyePaths(cx, cy, w, h, open) {
    // Inner corner (tear duct) — slightly rounded
    var ix = cx - w * 0.5;
    var iy = cy;

    // Outer corner — cat-eye upturn
    var ox = cx + w * 0.5;
    var oy = cy - h * 0.08;

    // Upper lid — interpolate between closed (flat) and open (arched)
    var upperArc = h * 0.52 * open;
    var ucp1x = cx - w * 0.2;
    var ucp1y = cy - upperArc;
    var ucp2x = cx + w * 0.25;
    var ucp2y = cy - upperArc * 0.95;

    // Lower lid — very slight drop when open
    var lowerDrop = h * 0.18 * open;
    var lcp1x = cx - w * 0.15;
    var lcp1y = cy + lowerDrop;
    var lcp2x = cx + w * 0.2;
    var lcp2y = cy + lowerDrop * 0.85;

    return {
      inner: { x: ix, y: iy },
      outer: { x: ox, y: oy },
      upper: { cp1: { x: ucp1x, y: ucp1y }, cp2: { x: ucp2x, y: ucp2y } },
      lower: { cp1: { x: lcp1x, y: lcp1y }, cp2: { x: lcp2x, y: lcp2y } }
    };
  }

  // Trace the full eye opening as a path
  function traceEyeOpening(cx, cy, w, h, open) {
    var p = getEyePaths(cx, cy, w, h, open);
    ctx.beginPath();
    ctx.moveTo(p.inner.x, p.inner.y);
    // Upper lid
    ctx.bezierCurveTo(p.upper.cp1.x, p.upper.cp1.y, p.upper.cp2.x, p.upper.cp2.y, p.outer.x, p.outer.y);
    // Lower lid (reverse direction)
    ctx.bezierCurveTo(p.lower.cp2.x, p.lower.cp2.y, p.lower.cp1.x, p.lower.cp1.y, p.inner.x, p.inner.y);
    ctx.closePath();
  }

  // ─── Point on bezier curve ──────────────────────────────────
  function bezierPoint(t, p0, cp1, cp2, p1) {
    var mt = 1 - t;
    var mt2 = mt * mt;
    var mt3 = mt2 * mt;
    var t2 = t * t;
    var t3 = t2 * t;
    return {
      x: mt3 * p0.x + 3 * mt2 * t * cp1.x + 3 * mt * t2 * cp2.x + t3 * p1.x,
      y: mt3 * p0.y + 3 * mt2 * t * cp1.y + 3 * mt * t2 * cp2.y + t3 * p1.y
    };
  }

  // Tangent on bezier
  function bezierTangent(t, p0, cp1, cp2, p1) {
    var mt = 1 - t;
    var mt2 = mt * mt;
    var t2 = t * t;
    return {
      x: 3 * mt2 * (cp1.x - p0.x) + 6 * mt * t * (cp2.x - cp1.x) + 3 * t2 * (p1.x - cp2.x),
      y: 3 * mt2 * (cp1.y - p0.y) + 6 * mt * t * (cp2.y - cp1.y) + 3 * t2 * (p1.y - cp2.y)
    };
  }

  // ─── Draw Iris (Green-Gold Hazel — from reference) ──────────
  function drawIris(cx, cy, radius, t) {
    ctx.save();

    // Base gradient — amber center to forest green edge
    var baseGrad = ctx.createRadialGradient(cx, cy, radius * 0.08, cx, cy, radius);
    baseGrad.addColorStop(0, IRIS_AMBER);       // warm gold near pupil
    baseGrad.addColorStop(0.25, IRIS_INNER);     // golden-green
    baseGrad.addColorStop(0.55, IRIS_MID);       // bright moss
    baseGrad.addColorStop(0.8, IRIS_OUTER);      // deep forest
    baseGrad.addColorStop(1, '#2a4a22');          // darkest edge
    ctx.fillStyle = baseGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();

    // Collarette ring — the golden-amber boundary visible in the reference
    ctx.strokeStyle = 'rgba(196, 164, 77, 0.35)';
    ctx.lineWidth = radius * 0.04;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.38, 0, Math.PI * 2);
    ctx.stroke();

    // Radial fibers — the stroma strands visible in hazel eyes
    // These radiate outward from the pupil, creating the natural iris texture
    var fiberCount = 80;
    for (var f = 0; f < fiberCount; f++) {
      var angle = (f / fiberCount) * Math.PI * 2 + irisRotation * 0.02;
      var innerR = radius * 0.22;
      var outerR = radius * (0.75 + Math.sin(f * 5.3 + t * 0.2) * 0.12);

      // Alternate between green and gold fibers like in the reference
      var isGoldFiber = (f % 3 === 0);
      var fiberAlpha = 0.12 + Math.sin(f * 2.7 + t * 0.3) * 0.05;

      if (isGoldFiber) {
        ctx.strokeStyle = 'rgba(196, 168, 77, ' + fiberAlpha + ')';
      } else {
        ctx.strokeStyle = 'rgba(107, 154, 78, ' + (fiberAlpha * 0.8) + ')';
      }
      ctx.lineWidth = 0.8 + Math.sin(f * 1.3) * 0.3;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(angle) * innerR, cy + Math.sin(angle) * innerR);

      // Gentle curve — natural fiber waviness
      var midAngle = angle + Math.sin(f * 2.1 + t * 0.15) * 0.08;
      var midR = (innerR + outerR) * 0.5;
      ctx.quadraticCurveTo(
        cx + Math.cos(midAngle) * midR,
        cy + Math.sin(midAngle) * midR,
        cx + Math.cos(angle + Math.sin(f) * 0.03) * outerR,
        cy + Math.sin(angle + Math.sin(f) * 0.03) * outerR
      );
      ctx.stroke();
    }

    // Crypts — the darker spots/gaps in the iris stroma
    // These create the depth that makes hazel eyes so captivating
    for (var cr = 0; cr < 12; cr++) {
      var cryptAngle = cr * 0.524 + Math.sin(cr * 3.1) * 0.3;
      var cryptDist = radius * (0.4 + Math.sin(cr * 2.7) * 0.15);
      var cryptSize = radius * (0.04 + Math.sin(cr * 4.1) * 0.015);
      var cryptX = cx + Math.cos(cryptAngle) * cryptDist;
      var cryptY = cy + Math.sin(cryptAngle) * cryptDist;
      var cryptGrad = ctx.createRadialGradient(cryptX, cryptY, 0, cryptX, cryptY, cryptSize);
      cryptGrad.addColorStop(0, 'rgba(40, 55, 30, 0.3)');
      cryptGrad.addColorStop(1, 'rgba(40, 55, 30, 0)');
      ctx.fillStyle = cryptGrad;
      ctx.beginPath();
      ctx.arc(cryptX, cryptY, cryptSize, 0, Math.PI * 2);
      ctx.fill();
    }

    // Sunlight warmth — the golden light visible in the reference photo
    // A warm light source from upper-left creates the living quality
    ctx.globalCompositeOperation = 'overlay';
    var sunX = cx - radius * 0.3;
    var sunY = cy - radius * 0.25;
    var sunGrad = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, radius * 0.7);
    sunGrad.addColorStop(0, 'rgba(212, 200, 122, 0.25)');
    sunGrad.addColorStop(0.4, 'rgba(180, 160, 80, 0.1)');
    sunGrad.addColorStop(1, 'rgba(180, 160, 80, 0)');
    ctx.fillStyle = sunGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();

    // Subtle living shimmer — very gentle color shift
    ctx.globalCompositeOperation = 'soft-light';
    for (var sh = 0; sh < 5; sh++) {
      var shAngle = t * 0.1 + sh * 1.257;
      var shDist = radius * (0.3 + Math.sin(t * 0.3 + sh * 2) * 0.15);
      var shSize = radius * 0.2;
      var shX = cx + Math.cos(shAngle) * shDist;
      var shY = cy + Math.sin(shAngle) * shDist;
      var shGrad = ctx.createRadialGradient(shX, shY, 0, shX, shY, shSize);
      shGrad.addColorStop(0, 'rgba(143, 184, 108, 0.15)');
      shGrad.addColorStop(1, 'rgba(143, 184, 108, 0)');
      ctx.fillStyle = shGrad;
      ctx.beginPath();
      ctx.arc(shX, shY, shSize, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalCompositeOperation = 'source-over';

    // Pupil — warm dark, not cold black
    var pupilSize = radius * (0.26 + Math.sin(t * 0.5) * 0.02);
    var pupilGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, pupilSize);
    pupilGrad.addColorStop(0, PUPIL_COLOR);
    pupilGrad.addColorStop(0.8, PUPIL_COLOR);
    pupilGrad.addColorStop(1, 'rgba(26, 18, 8, 0.6)');
    ctx.fillStyle = pupilGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, pupilSize, 0, Math.PI * 2);
    ctx.fill();

    // Pupil edge — amber glow ring where pupil meets iris (visible in reference)
    ctx.strokeStyle = 'rgba(196, 164, 77, 0.4)';
    ctx.lineWidth = radius * 0.02;
    ctx.beginPath();
    ctx.arc(cx, cy, pupilSize * 1.05, 0, Math.PI * 2);
    ctx.stroke();

    // Reflections — the living light that makes eyes feel real
    // Main catch-light (upper-left, like the reference photo)
    var hlx = cx - radius * 0.22;
    var hly = cy - radius * 0.18;
    var hlr = radius * 0.13;
    var hlGrad = ctx.createRadialGradient(hlx, hly, 0, hlx, hly, hlr);
    hlGrad.addColorStop(0, 'rgba(255, 252, 240, 0.9)');
    hlGrad.addColorStop(0.3, 'rgba(255, 250, 235, 0.4)');
    hlGrad.addColorStop(0.7, 'rgba(255, 248, 220, 0.1)');
    hlGrad.addColorStop(1, 'rgba(255, 248, 220, 0)');
    ctx.fillStyle = hlGrad;
    ctx.beginPath();
    ctx.arc(hlx, hly, hlr, 0, Math.PI * 2);
    ctx.fill();

    // Secondary catch-light (smaller, lower-right)
    var hl2x = cx + radius * 0.12;
    var hl2y = cy + radius * 0.14;
    var hl2r = radius * 0.05;
    ctx.fillStyle = 'rgba(255, 250, 235, 0.45)';
    ctx.beginPath();
    ctx.arc(hl2x, hl2y, hl2r, 0, Math.PI * 2);
    ctx.fill();

    // Limbal ring — dark green-brown edge (prominent in the reference)
    ctx.strokeStyle = 'rgba(35, 50, 25, 0.7)';
    ctx.lineWidth = radius * 0.06;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.97, 0, Math.PI * 2);
    ctx.stroke();

    ctx.restore();
  }

  // ─── Draw Eyelashes ─────────────────────────────────────────
  function drawLashes(paths, lashDefs, isUpper, open) {
    if (open < 0.02 && !isUpper) return;

    var p0, cp1, cp2, p1;
    if (isUpper) {
      p0 = paths.inner;
      cp1 = paths.upper.cp1;
      cp2 = paths.upper.cp2;
      p1 = paths.outer;
    } else {
      p0 = paths.inner;
      cp1 = paths.lower.cp1;
      cp2 = paths.lower.cp2;
      p1 = paths.outer;
    }

    for (var i = 0; i < lashDefs.length; i++) {
      var lash = lashDefs[i];
      var pt = bezierPoint(lash.t, p0, cp1, cp2, p1);
      var tan = bezierTangent(lash.t, p0, cp1, cp2, p1);

      // Normal to the curve (perpendicular, pointing outward)
      var len = Math.sqrt(tan.x * tan.x + tan.y * tan.y);
      var nx, ny;
      if (isUpper) {
        nx = -tan.y / len;
        ny = tan.x / len;
      } else {
        nx = tan.y / len;
        ny = -tan.x / len;
      }

      // Lash end point with curl
      var lashLen = lash.length;
      var endX = pt.x + nx * lashLen;
      var endY = pt.y + ny * lashLen;

      // Control point for curl
      var curlX = pt.x + nx * lashLen * 0.6 + tan.x / len * lash.curl * lashLen;
      var curlY = pt.y + ny * lashLen * 0.6 + tan.y / len * lash.curl * lashLen;

      ctx.strokeStyle = LASH_COLOR;
      ctx.lineWidth = lash.thickness;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(pt.x, pt.y);
      ctx.quadraticCurveTo(curlX, curlY, endX, endY);
      ctx.stroke();

      // Da Vinci double-stroke: a thinner parallel line for hand-drawn feel
      if (lash.thickness > 1 && i % 2 === 0) {
        ctx.strokeStyle = 'rgba(120, 95, 70, 0.25)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(pt.x + 0.5, pt.y + 0.5);
        ctx.quadraticCurveTo(curlX + 0.8, curlY + 0.8, endX + 0.5, endY + 0.5);
        ctx.stroke();
      }
    }
  }

  // ─── Draw Single Eye ────────────────────────────────────────
  function drawEye(cx, cy, eyeW, eyeH, open, t, side) {
    if (open < 0.005 && !hasEverOpened) {
      // Draw just a subtle closed line hint
      drawClosedEyeHint(cx, cy, eyeW, eyeH, t, side);
      return;
    }

    var drawOpen = Math.max(open, 0.005);
    var paths = getEyePaths(cx, cy, eyeW, eyeH, drawOpen);

    // ── Inner glow — light spilling through the opening ──
    if (open > 0.01) {
      ctx.save();
      var glowR = eyeW * 0.4 * open;
      var innerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      var ga = open * 0.35 * glowIntensity;
      innerGlow.addColorStop(0, GLOW_COLOR + (ga * 0.8) + ')');
      innerGlow.addColorStop(0.4, GLOW_COLOR + (ga * 0.4) + ')');
      innerGlow.addColorStop(1, GLOW_COLOR + '0)');
      ctx.fillStyle = innerGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // ── Iris (clipped to eye opening) ──
    if (open > 0.02) {
      ctx.save();
      traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
      ctx.clip();

      // Sclera — barely visible darkness
      var scleraGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, eyeW * 0.35);
      scleraGrad.addColorStop(0, 'rgba(20, 16, 10, 0.8)');
      scleraGrad.addColorStop(1, 'rgba(12, 10, 6, 0.9)');
      ctx.fillStyle = scleraGrad;
      ctx.fill();

      // Iris
      var irisR = eyeH * 0.38 * (0.5 + open * 0.5);
      drawIris(cx, cy - eyeH * 0.02, irisR, t);

      ctx.restore();
    }

    // ── Eye outline — Da Vinci style multi-stroke ──
    ctx.save();
    // Primary line
    traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
    ctx.strokeStyle = OUTLINE_COLOR;
    ctx.lineWidth = 1.8;
    ctx.stroke();

    // Secondary sketch line (offset) — hand-drawn feel
    ctx.save();
    ctx.translate(0.4, 0.3);
    traceEyeOpening(cx, cy, eyeW, eyeH, drawOpen);
    ctx.strokeStyle = 'rgba(120, 100, 75, 0.2)';
    ctx.lineWidth = 0.7;
    ctx.stroke();
    ctx.restore();

    // Crease line above upper lid
    if (open > 0.1) {
      var creaseOpen = drawOpen * 1.3;
      var creasePaths = getEyePaths(cx, cy - eyeH * 0.12, eyeW * 0.85, eyeH, creaseOpen);
      ctx.beginPath();
      ctx.moveTo(creasePaths.inner.x + eyeW * 0.05, creasePaths.inner.y);
      ctx.bezierCurveTo(
        creasePaths.upper.cp1.x, creasePaths.upper.cp1.y,
        creasePaths.upper.cp2.x, creasePaths.upper.cp2.y,
        creasePaths.outer.x - eyeW * 0.03, creasePaths.outer.y
      );
      ctx.strokeStyle = 'rgba(120, 100, 75, ' + (0.18 * open) + ')';
      ctx.lineWidth = 0.8;
      ctx.stroke();
    }
    ctx.restore();

    // ── Eyeliner — bold line along upper lid ──
    if (open > 0.03) {
      var linerPaths = getEyePaths(cx, cy, eyeW, eyeH, drawOpen);
      ctx.beginPath();
      ctx.moveTo(linerPaths.inner.x, linerPaths.inner.y);
      ctx.bezierCurveTo(
        linerPaths.upper.cp1.x, linerPaths.upper.cp1.y - 1,
        linerPaths.upper.cp2.x, linerPaths.upper.cp2.y - 1,
        linerPaths.outer.x + eyeW * 0.03, linerPaths.outer.y - eyeH * 0.03
      );
      ctx.strokeStyle = 'rgba(140, 115, 85, ' + (0.45 * Math.min(open * 2, 1)) + ')';
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    // ── Eyelashes ──
    var upperLashes = generateLashes(eyeW, eyeH, true, side);
    var lowerLashes = generateLashes(eyeW, eyeH, false, side);
    drawLashes(paths, upperLashes, true, drawOpen);
    if (open > 0.1) {
      drawLashes(paths, lowerLashes, false, drawOpen);
    }
  }

  // ─── Closed Eye Hint (Da Vinci sketch style) ───────────────
  function drawClosedEyeHint(cx, cy, eyeW, eyeH, t, side) {
    ctx.save();
    // Subtle breathing animation
    var breathe = Math.sin(t * 0.5) * 0.3;
    var alpha = 0.15 + breathe * 0.05;

    // Closed eye line — single elegant curve
    var ix = cx - eyeW * 0.45;
    var ox = cx + eyeW * 0.45;
    var oy = cy - eyeH * 0.05;

    ctx.beginPath();
    ctx.moveTo(ix, cy);
    ctx.bezierCurveTo(
      cx - eyeW * 0.15, cy - eyeH * 0.04,
      cx + eyeW * 0.2, cy - eyeH * 0.05,
      ox, oy
    );
    ctx.strokeStyle = 'rgba(140, 120, 90, ' + alpha + ')';
    ctx.lineWidth = 1.5;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Ghost sketch line
    ctx.beginPath();
    ctx.moveTo(ix + 1, cy + 0.5);
    ctx.bezierCurveTo(
      cx - eyeW * 0.15 + 0.5, cy - eyeH * 0.03,
      cx + eyeW * 0.2 + 0.5, cy - eyeH * 0.04,
      ox + 0.5, oy + 0.5
    );
    ctx.strokeStyle = 'rgba(140, 120, 90, ' + (alpha * 0.4) + ')';
    ctx.lineWidth = 0.6;
    ctx.stroke();

    // Few closed-eye lashes — pointing downward
    var lashCount = 12;
    for (var i = 0; i < lashCount; i++) {
      var lt = (i + 0.5) / lashCount;
      var lx = ix + (ox - ix) * lt;
      var ly = cy + (oy - cy) * lt - eyeH * 0.02;
      var outerBias = side === 'left' ? lt : (1 - lt);
      var lashLen = eyeH * 0.12 * (0.5 + outerBias * 0.7);

      ctx.beginPath();
      ctx.moveTo(lx, ly);
      ctx.quadraticCurveTo(
        lx + (outerBias - 0.3) * eyeW * 0.02,
        ly + lashLen * 0.6,
        lx + (outerBias - 0.4) * eyeW * 0.04,
        ly + lashLen
      );
      ctx.strokeStyle = 'rgba(140, 120, 90, ' + (alpha * 0.7) + ')';
      ctx.lineWidth = 0.8 + outerBias * 0.4;
      ctx.stroke();
    }

    ctx.restore();
  }

  // ─── Particle System — divine light motes ───────────────────
  function spawnParticles(cx, cy, eyeW) {
    if (particles.length > 60) return;
    for (var i = 0; i < 3; i++) {
      particles.push({
        x: cx + (Math.random() - 0.5) * eyeW * 0.6,
        y: cy + (Math.random() - 0.5) * eyeW * 0.2,
        vx: (Math.random() - 0.5) * 0.3,
        vy: -0.3 - Math.random() * 0.5,
        life: 1,
        decay: 0.005 + Math.random() * 0.008,
        size: 1 + Math.random() * 2.5
      });
    }
  }

  function updateAndDrawParticles() {
    for (var i = particles.length - 1; i >= 0; i--) {
      var p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.vy -= 0.003; // float upward faster
      p.life -= p.decay;

      if (p.life <= 0) {
        particles.splice(i, 1);
        continue;
      }

      var alpha = p.life * 0.6 * openAmount;
      ctx.fillStyle = 'rgba(180, 200, 120, ' + alpha + ')';
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
      ctx.fill();

      // Tiny glow
      if (p.size > 1.5) {
        var pg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 3);
        pg.addColorStop(0, 'rgba(140, 180, 80, ' + (alpha * 0.3) + ')');
        pg.addColorStop(1, 'rgba(140, 180, 80, 0)');
        ctx.fillStyle = pg;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  // ─── Sacred Geometry Frame (appears when eyes are open) ─────
  function drawSacredFrame(cx, cy, radius, open, t) {
    if (open < 0.3) return;
    var frameAlpha = (open - 0.3) / 0.7 * 0.15;

    ctx.save();
    ctx.strokeStyle = 'rgba(140, 170, 80, ' + frameAlpha + ')';
    ctx.lineWidth = 0.5;

    // Outer circle
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();

    // Inner circle
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.7, 0, Math.PI * 2);
    ctx.stroke();

    // Radiating lines
    var lineCount = 12;
    for (var i = 0; i < lineCount; i++) {
      var a = (i / lineCount) * Math.PI * 2 + t * 0.05;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * radius * 0.75, cy + Math.sin(a) * radius * 0.75);
      ctx.lineTo(cx + Math.cos(a) * radius * 1.05, cy + Math.sin(a) * radius * 1.05);
      ctx.stroke();
    }

    // Vesica piscis (the sacred eye shape)
    var vr = radius * 0.6;
    ctx.beginPath();
    ctx.arc(cx - vr * 0.35, cy, vr, -Math.PI / 3, Math.PI / 3);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx + vr * 0.35, cy, vr, Math.PI - Math.PI / 3, Math.PI + Math.PI / 3);
    ctx.stroke();

    ctx.restore();
  }

  // ─── Main Render ────────────────────────────────────────────
  function render() {
    ctx.clearRect(0, 0, W, H);

    // Eye sizing — responsive
    var isMobile = W < 768;
    var eyeW = isMobile ? W * 0.32 : Math.min(W * 0.2, 280);
    var eyeH = eyeW * 0.45;
    var gap = isMobile ? W * 0.08 : eyeW * 0.4;

    // Position — centered, slightly above middle
    var centerX = W / 2;
    var centerY = H * 0.38;

    var leftEyeX = centerX - gap / 2 - eyeW * 0.3;
    var rightEyeX = centerX + gap / 2 + eyeW * 0.3;

    // Sacred geometry frame (subtle, behind eyes)
    var frameRadius = eyeW * 1.8;
    drawSacredFrame(centerX, centerY, frameRadius, openAmount, time);

    // Draw both eyes
    drawEye(leftEyeX, centerY, eyeW, eyeH, openAmount, time, 'left');
    drawEye(rightEyeX, centerY, eyeW, eyeH, openAmount, time, 'right');

    // Particles
    if (openAmount > 0.3) {
      spawnParticles(leftEyeX, centerY, eyeW);
      spawnParticles(rightEyeX, centerY, eyeW);
    }
    updateAndDrawParticles();

    // Central third eye point (between the eyes, very subtle)
    if (openAmount > 0.5) {
      var thirdAlpha = (openAmount - 0.5) * 0.4;
      var thirdPulse = 3 + Math.sin(time * 2) * 1.5;
      var thirdGrad = ctx.createRadialGradient(centerX, centerY - eyeH * 0.3, 0, centerX, centerY - eyeH * 0.3, thirdPulse * 3);
      thirdGrad.addColorStop(0, 'rgba(160, 185, 90, ' + thirdAlpha + ')');
      thirdGrad.addColorStop(1, 'rgba(160, 185, 90, 0)');
      ctx.fillStyle = thirdGrad;
      ctx.beginPath();
      ctx.arc(centerX, centerY - eyeH * 0.3, thirdPulse * 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ─── Animation Loop ─────────────────────────────────────────
  var lastTime = 0;
  function animate(timestamp) {
    requestAnimationFrame(animate);

    var dt = Math.min((timestamp - lastTime) / 1000, 0.05);
    lastTime = timestamp;
    time += dt;

    // Smooth eyelid interpolation
    var speed = targetOpen > openAmount ? 0.8 : 0.5; // Open faster than close
    openAmount += (targetOpen - openAmount) * speed * dt * 2;
    if (Math.abs(openAmount - targetOpen) < 0.001) openAmount = targetOpen;

    // Glow intensity follows openAmount with slight overshoot
    var targetGlow = openAmount > 0.1 ? 1 : 0;
    glowIntensity += (targetGlow - glowIntensity) * dt * 3;

    // Iris rotation
    irisRotation += dt * 0.5;

    // Auto-close after inactivity (5 seconds)
    if (targetOpen > 0 && time - lastActivity > 5) {
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

  function closeEyes() {
    // Don't close immediately — let the inactivity timer handle it
    // This allows the eyes to stay open while user reads results
  }

  // Event delegation — catches all search inputs
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

  document.addEventListener('input', function (e) {
    if (targetOpen > 0) keepAwake();
  }, true);

  document.addEventListener('submit', function () {
    keepAwake();
  }, true);

  // Also open on any search button click
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

  // Keyboard shortcut: Ctrl+K or / to open (common search shortcuts)
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && e.target === document.body)) {
      openEyes();
    }
  });

})();
