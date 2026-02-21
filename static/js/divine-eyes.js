/**
 * MYSTES — Divine Eyes (SVG-based)
 * Clean white line-art eyes on dark background
 * Crystal green iris — SVG for smooth, precise rendering
 * Eyes open from closed on page load
 */
(function () {
  'use strict';

  var container = document.getElementById('divine-eyes-canvas');
  if (!container) return;

  // Convert canvas element to a div container for SVG
  container.innerHTML = '';
  container.style.display = 'flex';
  container.style.alignItems = 'center';
  container.style.justifyContent = 'center';

  // ─── State ──────────────────────────────────────────────────
  var openAmount = 0;       // 0 = closed, 1 = fully open
  var targetOpen = 0;
  var time = 0;
  var lastActivity = 0;
  var hasOpened = false;

  // ─── Create SVG ─────────────────────────────────────────────
  var ns = 'http://www.w3.org/2000/svg';
  var isMobile = window.innerWidth < 768;
  var svgW = isMobile ? 340 : 520;
  var svgH = isMobile ? 160 : 240;

  var svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 520 240');
  svg.setAttribute('width', svgW);
  svg.setAttribute('height', svgH);
  svg.style.overflow = 'visible';
  container.appendChild(svg);

  // ─── Defs: iris gradient + clip paths ───────────────────────
  var defs = document.createElementNS(ns, 'defs');

  // Iris gradient — crystal green
  var irisGrad = document.createElementNS(ns, 'radialGradient');
  irisGrad.id = 'irisGrad';
  ['0%:#42d68a', '25%:#22c070', '55%:#0f8a45', '80%:#0a5c2e', '100%:#062e1c'].forEach(function (s) {
    var parts = s.split(':');
    var stop = document.createElementNS(ns, 'stop');
    stop.setAttribute('offset', parts[0]);
    stop.setAttribute('stop-color', parts[1]);
    irisGrad.appendChild(stop);
  });
  defs.appendChild(irisGrad);

  // Gold hint gradient
  var goldGrad = document.createElementNS(ns, 'radialGradient');
  goldGrad.id = 'goldHint';
  var gs1 = document.createElementNS(ns, 'stop');
  gs1.setAttribute('offset', '0%');
  gs1.setAttribute('stop-color', 'rgba(210,195,100,0.15)');
  goldGrad.appendChild(gs1);
  var gs2 = document.createElementNS(ns, 'stop');
  gs2.setAttribute('offset', '100%');
  gs2.setAttribute('stop-color', 'rgba(210,195,100,0)');
  goldGrad.appendChild(gs2);
  defs.appendChild(goldGrad);

  // Catch-light gradient
  var hlGrad = document.createElementNS(ns, 'radialGradient');
  hlGrad.id = 'catchLight';
  hlGrad.setAttribute('cx', '35%');
  hlGrad.setAttribute('cy', '35%');
  hlGrad.setAttribute('r', '50%');
  var hl1 = document.createElementNS(ns, 'stop');
  hl1.setAttribute('offset', '0%');
  hl1.setAttribute('stop-color', 'rgba(255,255,255,0.95)');
  hlGrad.appendChild(hl1);
  var hl2 = document.createElementNS(ns, 'stop');
  hl2.setAttribute('offset', '50%');
  hl2.setAttribute('stop-color', 'rgba(255,255,255,0.3)');
  hlGrad.appendChild(hl2);
  var hl3 = document.createElementNS(ns, 'stop');
  hl3.setAttribute('offset', '100%');
  hl3.setAttribute('stop-color', 'rgba(255,255,255,0)');
  hlGrad.appendChild(hl3);
  defs.appendChild(hlGrad);

  // Clip paths for each eye (will be animated)
  var leftClip = document.createElementNS(ns, 'clipPath');
  leftClip.id = 'leftEyeClip';
  var leftClipPath = document.createElementNS(ns, 'path');
  leftClip.appendChild(leftClipPath);
  defs.appendChild(leftClip);

  var rightClip = document.createElementNS(ns, 'clipPath');
  rightClip.id = 'rightEyeClip';
  var rightClipPath = document.createElementNS(ns, 'path');
  rightClip.appendChild(rightClipPath);
  defs.appendChild(rightClip);

  svg.appendChild(defs);

  // ─── Eye geometry constants ─────────────────────────────────
  var leftCx = 150, rightCx = 370, cy = 130;
  var eyeW = 120, eyeH = 55;

  // ─── Build eye path from open amount ────────────────────────
  function eyePath(cx, open) {
    // Inner and outer corners (fixed)
    var ix = cx - eyeW;
    var ox = cx + eyeW;
    var iy = cy + 2;
    var oy = cy - 3;

    // Upper lid control points
    var upperH = eyeH * open;
    var ucp1x = cx - eyeW * 0.4;
    var ucp1y = cy - upperH * 0.95;
    var ucp2x = cx + eyeW * 0.35;
    var ucp2y = cy - upperH * 0.9;

    // Lower lid control points
    var lowerH = eyeH * 0.35 * open;
    var lcp1x = cx - eyeW * 0.35;
    var lcp1y = cy + lowerH * 0.85;
    var lcp2x = cx + eyeW * 0.4;
    var lcp2y = cy + lowerH * 0.75;

    return 'M ' + ix + ',' + iy +
           ' C ' + ucp1x + ',' + ucp1y + ' ' + ucp2x + ',' + ucp2y + ' ' + ox + ',' + oy +
           ' C ' + lcp2x + ',' + (cy + lcp2y - cy) + ' ' + lcp1x + ',' + (cy + lcp1y - cy) + ' ' + ix + ',' + iy +
           ' Z';
  }

  function upperLidPath(cx, open) {
    var ix = cx - eyeW;
    var ox = cx + eyeW;
    var iy = cy + 2;
    var oy = cy - 3;
    var upperH = eyeH * open;
    var ucp1x = cx - eyeW * 0.4;
    var ucp1y = cy - upperH * 0.95;
    var ucp2x = cx + eyeW * 0.35;
    var ucp2y = cy - upperH * 0.9;
    return 'M ' + ix + ',' + iy + ' C ' + ucp1x + ',' + ucp1y + ' ' + ucp2x + ',' + ucp2y + ' ' + ox + ',' + oy;
  }

  function closedLinePath(cx) {
    var ix = cx - eyeW * 0.9;
    var ox = cx + eyeW * 0.9;
    return 'M ' + ix + ',' + cy + ' Q ' + cx + ',' + (cy - 4) + ' ' + ox + ',' + (cy - 2);
  }

  // ─── Create eye group ───────────────────────────────────────
  function createEye(cx, clipId, side) {
    var g = document.createElementNS(ns, 'g');

    // --- Eyebrow ---
    var brow = document.createElementNS(ns, 'path');
    var browFlip = side === 'left' ? 1 : -1;
    var bs = cx - eyeW * 0.85;
    var be = cx + eyeW * 0.9;
    var bp = cx + eyeW * 0.1 * browFlip;
    brow.setAttribute('d', 'M ' + bs + ',' + (cy - eyeH * 0.9) +
      ' Q ' + bp + ',' + (cy - eyeH * 1.65) + ' ' + be + ',' + (cy - eyeH * 0.75));
    brow.setAttribute('fill', 'none');
    brow.setAttribute('stroke', 'rgba(255,255,255,0.7)');
    brow.setAttribute('stroke-width', '2.5');
    brow.setAttribute('stroke-linecap', 'round');
    g.appendChild(brow);
    g._brow = brow;

    // --- Iris group (clipped) ---
    var irisG = document.createElementNS(ns, 'g');
    irisG.setAttribute('clip-path', 'url(#' + clipId + ')');

    // Sclera
    var sclera = document.createElementNS(ns, 'ellipse');
    sclera.setAttribute('cx', cx);
    sclera.setAttribute('cy', cy);
    sclera.setAttribute('rx', eyeW * 0.7);
    sclera.setAttribute('ry', eyeH * 0.8);
    sclera.setAttribute('fill', 'rgba(245,243,240,0.85)');
    irisG.appendChild(sclera);

    // Iris
    var irisR = 32;
    var iris = document.createElementNS(ns, 'circle');
    iris.setAttribute('cx', cx);
    iris.setAttribute('cy', cy);
    iris.setAttribute('r', irisR);
    iris.setAttribute('fill', 'url(#irisGrad)');
    irisG.appendChild(iris);

    // Limbal ring
    var limbal = document.createElementNS(ns, 'circle');
    limbal.setAttribute('cx', cx);
    limbal.setAttribute('cy', cy);
    limbal.setAttribute('r', irisR - 1);
    limbal.setAttribute('fill', 'none');
    limbal.setAttribute('stroke', 'rgba(6,30,18,0.7)');
    limbal.setAttribute('stroke-width', '2');
    irisG.appendChild(limbal);

    // Gold hint
    var gold = document.createElementNS(ns, 'circle');
    gold.setAttribute('cx', cx);
    gold.setAttribute('cy', cy);
    gold.setAttribute('r', irisR * 0.5);
    gold.setAttribute('fill', 'url(#goldHint)');
    irisG.appendChild(gold);

    // Stroma fibers (radial lines — subtle)
    for (var f = 0; f < 24; f++) {
      var angle = (f / 24) * Math.PI * 2;
      var line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', cx + Math.cos(angle) * 8);
      line.setAttribute('y1', cy + Math.sin(angle) * 8);
      line.setAttribute('x2', cx + Math.cos(angle) * (irisR - 3));
      line.setAttribute('y2', cy + Math.sin(angle) * (irisR - 3));
      var isGold = f % 8 === 0;
      line.setAttribute('stroke', isGold ? 'rgba(190,175,90,0.12)' : 'rgba(30,200,100,0.1)');
      line.setAttribute('stroke-width', '0.5');
      irisG.appendChild(line);
    }

    // Pupil
    var pupil = document.createElementNS(ns, 'circle');
    pupil.setAttribute('cx', cx);
    pupil.setAttribute('cy', cy);
    pupil.setAttribute('r', '10');
    pupil.setAttribute('fill', '#050505');
    irisG.appendChild(pupil);

    // Catch-light main
    var hl = document.createElementNS(ns, 'circle');
    hl.setAttribute('cx', cx - 8);
    hl.setAttribute('cy', cy - 7);
    hl.setAttribute('r', '5.5');
    hl.setAttribute('fill', 'url(#catchLight)');
    irisG.appendChild(hl);

    // Catch-light secondary
    var hl2 = document.createElementNS(ns, 'circle');
    hl2.setAttribute('cx', cx + 6);
    hl2.setAttribute('cy', cy + 5);
    hl2.setAttribute('r', '2');
    hl2.setAttribute('fill', 'rgba(255,255,255,0.4)');
    irisG.appendChild(hl2);

    g.appendChild(irisG);

    // --- Eye outline ---
    var outline = document.createElementNS(ns, 'path');
    outline.setAttribute('fill', 'none');
    outline.setAttribute('stroke', 'rgba(255,255,255,0.6)');
    outline.setAttribute('stroke-width', '1.8');
    outline.setAttribute('stroke-linecap', 'round');
    outline.setAttribute('stroke-linejoin', 'round');
    g.appendChild(outline);
    g._outline = outline;

    // --- Bold upper lid (eyeliner) ---
    var liner = document.createElementNS(ns, 'path');
    liner.setAttribute('fill', 'none');
    liner.setAttribute('stroke', 'rgba(255,255,255,0.8)');
    liner.setAttribute('stroke-width', '3.2');
    liner.setAttribute('stroke-linecap', 'round');
    g.appendChild(liner);
    g._liner = liner;

    // --- Crease line ---
    var crease = document.createElementNS(ns, 'path');
    crease.setAttribute('fill', 'none');
    crease.setAttribute('stroke', 'rgba(255,255,255,0.15)');
    crease.setAttribute('stroke-width', '0.8');
    crease.setAttribute('stroke-linecap', 'round');
    g.appendChild(crease);
    g._crease = crease;

    // --- Lashes (static SVG paths — pre-built, clean) ---
    var lashG = document.createElementNS(ns, 'g');
    lashG.setAttribute('stroke', 'rgba(255,255,255,0.7)');
    lashG.setAttribute('stroke-linecap', 'round');
    lashG.setAttribute('fill', 'none');
    g.appendChild(lashG);
    g._lashG = lashG;

    // --- Closed-eye line (visible when closed) ---
    var closedLine = document.createElementNS(ns, 'path');
    closedLine.setAttribute('fill', 'none');
    closedLine.setAttribute('stroke', 'rgba(255,255,255,0.35)');
    closedLine.setAttribute('stroke-width', '1.5');
    closedLine.setAttribute('stroke-linecap', 'round');
    closedLine.setAttribute('d', closedLinePath(cx));
    g.appendChild(closedLine);
    g._closedLine = closedLine;

    return g;
  }

  // Soft glow filter for subtle backdrop
  var blurFilter = document.createElementNS(ns, 'filter');
  blurFilter.id = 'softGlow';
  var feBlur = document.createElementNS(ns, 'feGaussianBlur');
  feBlur.setAttribute('stdDeviation', '30');
  blurFilter.appendChild(feBlur);
  defs.appendChild(blurFilter);

  var leftEyeG = createEye(leftCx, 'leftEyeClip', 'left');
  var rightEyeG = createEye(rightCx, 'rightEyeClip', 'right');
  svg.appendChild(leftEyeG);
  svg.appendChild(rightEyeG);

  // ─── Build lash paths for a given open amount ──────────────
  function buildLashes(g, cx, open, side) {
    // Clear existing
    while (g._lashG.firstChild) g._lashG.removeChild(g._lashG.firstChild);
    if (open < 0.05) return;

    var count = 15;
    for (var i = 0; i < count; i++) {
      var t = (i + 0.5) / count;

      // Position along upper lid
      var ix = cx - eyeW;
      var ox = cx + eyeW;
      var iy = cy + 2;
      var oy = cy - 3;
      var upperH = eyeH * open;

      // Cubic bezier point on upper lid
      var mt = 1 - t;
      var ucp1x = cx - eyeW * 0.4;
      var ucp1y = cy - upperH * 0.95;
      var ucp2x = cx + eyeW * 0.35;
      var ucp2y = cy - upperH * 0.9;

      var px = mt * mt * mt * ix + 3 * mt * mt * t * ucp1x + 3 * mt * t * t * ucp2x + t * t * t * ox;
      var py = mt * mt * mt * iy + 3 * mt * mt * t * ucp1y + 3 * mt * t * t * ucp2y + t * t * t * oy;

      // Tangent for normal direction
      var tx = 3 * mt * mt * (ucp1x - ix) + 6 * mt * t * (ucp2x - ucp1x) + 3 * t * t * (ox - ucp2x);
      var ty = 3 * mt * mt * (ucp1y - iy) + 6 * mt * t * (ucp2y - ucp1y) + 3 * t * t * (oy - ucp2y);
      var tLen = Math.sqrt(tx * tx + ty * ty);
      var nx = -ty / tLen;
      var ny = tx / tLen;

      // Lash length — longer toward outer corner
      var outer = side === 'left' ? t : (1 - t);
      var lashLen = (12 + outer * 22) * open;
      var curl = (0.1 + outer * 0.4) * (side === 'left' ? 1 : -1);

      var endX = px + nx * lashLen;
      var endY = py + ny * lashLen;
      var cpX = px + nx * lashLen * 0.6 + tx / tLen * curl * lashLen;
      var cpY = py + ny * lashLen * 0.6 + ty / tLen * curl * lashLen;

      var lash = document.createElementNS(ns, 'path');
      lash.setAttribute('d', 'M ' + px + ',' + py + ' Q ' + cpX + ',' + cpY + ' ' + endX + ',' + endY);
      lash.setAttribute('stroke-width', String(0.8 + outer * 1.2));
      g._lashG.appendChild(lash);
    }

    // Lower lashes (fewer, shorter)
    if (open > 0.2) {
      var lCount = 8;
      for (var j = 0; j < lCount; j++) {
        var lt = (j + 0.5) / lCount;
        var lx = cx - eyeW * 0.7 + lt * eyeW * 1.4;
        var lowerH = eyeH * 0.35 * open;
        var ly = cy + Math.sin(lt * Math.PI) * lowerH * 0.8;
        var louter = side === 'left' ? lt : (1 - lt);
        var lLen = (5 + louter * 10) * open;

        var ll = document.createElementNS(ns, 'path');
        ll.setAttribute('d', 'M ' + lx + ',' + ly + ' L ' + (lx + (louter - 0.4) * 3) + ',' + (ly + lLen));
        ll.setAttribute('stroke-width', String(0.5 + louter * 0.5));
        ll.setAttribute('stroke', 'rgba(255,255,255,0.45)');
        g._lashG.appendChild(ll);
      }
    }
  }

  // ─── Update eye state ──────────────────────────────────────
  function updateEyes(open) {
    // Clip paths
    leftClipPath.setAttribute('d', eyePath(leftCx, Math.max(open, 0.001)));
    rightClipPath.setAttribute('d', eyePath(rightCx, Math.max(open, 0.001)));

    // Outlines
    leftEyeG._outline.setAttribute('d', open > 0.01 ? eyePath(leftCx, open) : closedLinePath(leftCx));
    rightEyeG._outline.setAttribute('d', open > 0.01 ? eyePath(rightCx, open) : closedLinePath(rightCx));

    // Upper lid liner
    if (open > 0.02) {
      leftEyeG._liner.setAttribute('d', upperLidPath(leftCx, open));
      rightEyeG._liner.setAttribute('d', upperLidPath(rightCx, open));
      leftEyeG._liner.setAttribute('stroke', 'rgba(255,255,255,' + Math.min(open * 1.5, 0.8) + ')');
      rightEyeG._liner.setAttribute('stroke', 'rgba(255,255,255,' + Math.min(open * 1.5, 0.8) + ')');
    } else {
      leftEyeG._liner.setAttribute('d', '');
      rightEyeG._liner.setAttribute('d', '');
    }

    // Crease
    if (open > 0.15) {
      var creaseAlpha = Math.min((open - 0.15) * 0.3, 0.15);
      [leftCx, rightCx].forEach(function (ecx, idx) {
        var el = idx === 0 ? leftEyeG : rightEyeG;
        var cix = ecx - eyeW * 0.65;
        var cox = ecx + eyeW * 0.65;
        var cpx = ecx;
        var cpy = cy - eyeH * open * 1.25;
        el._crease.setAttribute('d', 'M ' + cix + ',' + (cy - eyeH * open * 0.5) + ' Q ' + cpx + ',' + cpy + ' ' + cox + ',' + (cy - eyeH * open * 0.4));
        el._crease.setAttribute('stroke', 'rgba(255,255,255,' + creaseAlpha + ')');
      });
    }

    // Closed line
    leftEyeG._closedLine.setAttribute('stroke', 'rgba(255,255,255,' + (0.35 * (1 - open)) + ')');
    rightEyeG._closedLine.setAttribute('stroke', 'rgba(255,255,255,' + (0.35 * (1 - open)) + ')');

    // Brow lift
    var browLift = open * 8;
    leftEyeG._brow.setAttribute('transform', 'translate(0,' + (-browLift) + ')');
    rightEyeG._brow.setAttribute('transform', 'translate(0,' + (-browLift) + ')');
    leftEyeG._brow.setAttribute('stroke', 'rgba(255,255,255,' + (0.4 + open * 0.3) + ')');
    rightEyeG._brow.setAttribute('stroke', 'rgba(255,255,255,' + (0.4 + open * 0.3) + ')');

    // Lashes
    buildLashes(leftEyeG, leftCx, open, 'left');
    buildLashes(rightEyeG, rightCx, open, 'right');
  }

  // Initial state — closed
  updateEyes(0);

  // ─── Animation Loop ─────────────────────────────────────────
  var lastTime = 0;
  function animate(timestamp) {
    requestAnimationFrame(animate);
    var dt = Math.min((timestamp - lastTime) / 1000, 0.05);
    lastTime = timestamp;
    time += dt;

    // Smooth interpolation
    var speed = targetOpen > openAmount ? 1.8 : 1.0;
    var diff = targetOpen - openAmount;
    openAmount += diff * speed * dt;
    if (Math.abs(diff) < 0.002) openAmount = targetOpen;

    // Auto-close after inactivity
    if (targetOpen > 0 && time - lastActivity > 10) {
      targetOpen = 0;
    }

    updateEyes(openAmount);
  }
  requestAnimationFrame(animate);

  // ─── Interaction ────────────────────────────────────────────
  function openEyes() {
    targetOpen = 1;
    lastActivity = time;
    hasOpened = true;
  }

  function keepAwake() {
    lastActivity = time;
    if (targetOpen < 1) targetOpen = 1;
  }

  // Search/input focus
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el) return;
    var tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') {
      var id = (el.id || '').toLowerCase();
      var cls = (el.className || '').toLowerCase();
      var ph = (el.placeholder || '').toLowerCase();
      if (id.indexOf('search') > -1 || id.indexOf('chat') > -1 ||
          cls.indexOf('search') > -1 || cls.indexOf('ai-input') > -1 ||
          ph.indexOf('search') > -1 || ph.indexOf('where') > -1 ||
          ph.indexOf('message') > -1 || ph.indexOf('find') > -1) {
        openEyes();
      }
    }
  }, true);

  document.addEventListener('input', function () {
    if (targetOpen > 0) keepAwake();
  }, true);

  document.addEventListener('submit', function () { keepAwake(); }, true);

  document.addEventListener('click', function (e) {
    var el = e.target;
    if (!el) return;
    var cls = (el.className || '').toLowerCase();
    var text = (el.textContent || '').toLowerCase();
    if (cls.indexOf('search') > -1 || cls.indexOf('send') > -1 || text.indexOf('search') > -1) {
      openEyes();
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && e.target === document.body)) {
      openEyes();
    }
  });

  // Auto-open on page load
  setTimeout(function () { openEyes(); }, 1500);

})();
