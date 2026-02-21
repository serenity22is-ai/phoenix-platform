/**
 * MYSTES — Divine Eyes
 * Realistic feminine eyes matching pencil sketch reference
 * Thick filled eyebrows, dramatic sweeping lashes, crystal green iris
 * White luminous strokes on dark aurora background
 * Eyes animate open from closed on page load
 */
(function () {
  'use strict';

  var container = document.getElementById('divine-eyes-canvas');
  if (!container) return;

  container.innerHTML = '';
  container.style.display = 'flex';
  container.style.alignItems = 'center';
  container.style.justifyContent = 'center';

  // ─── State ──────────────────────────────────────────────────
  var openAmount = 0;
  var targetOpen = 0;
  var time = 0;
  var lastActivity = 0;
  var prevOpen = -1; // track for lash rebuild optimization

  // ─── SVG Setup ──────────────────────────────────────────────
  var ns = 'http://www.w3.org/2000/svg';
  var isMobile = window.innerWidth < 768;
  var svgW = isMobile ? 380 : 580;
  var svgH = isMobile ? 200 : 300;

  var svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 580 300');
  svg.setAttribute('width', svgW);
  svg.setAttribute('height', svgH);
  svg.style.overflow = 'visible';
  container.appendChild(svg);

  // ─── Defs ───────────────────────────────────────────────────
  var defs = document.createElementNS(ns, 'defs');

  // Iris gradient — crystal green
  var irisGrad = document.createElementNS(ns, 'radialGradient');
  irisGrad.id = 'irisGrad';
  [['0%','#42d68a'],['22%','#2acc78'],['50%','#15a857'],['78%','#0a5c2e'],['100%','#062e1c']].forEach(function(s) {
    var stop = document.createElementNS(ns, 'stop');
    stop.setAttribute('offset', s[0]);
    stop.setAttribute('stop-color', s[1]);
    irisGrad.appendChild(stop);
  });
  defs.appendChild(irisGrad);

  // Gold hint
  var goldGrad = document.createElementNS(ns, 'radialGradient');
  goldGrad.id = 'goldHint';
  [['0%','rgba(210,195,100,0.18)'],['100%','rgba(210,195,100,0)']].forEach(function(s) {
    var stop = document.createElementNS(ns, 'stop');
    stop.setAttribute('offset', s[0]);
    stop.setAttribute('stop-color', s[1]);
    goldGrad.appendChild(stop);
  });
  defs.appendChild(goldGrad);

  // Catch-light
  var hlGrad = document.createElementNS(ns, 'radialGradient');
  hlGrad.id = 'catchLight';
  hlGrad.setAttribute('cx', '35%');
  hlGrad.setAttribute('cy', '35%');
  hlGrad.setAttribute('r', '50%');
  [['0%','rgba(255,255,255,0.95)'],['50%','rgba(255,255,255,0.3)'],['100%','rgba(255,255,255,0)']].forEach(function(s) {
    var stop = document.createElementNS(ns, 'stop');
    stop.setAttribute('offset', s[0]);
    stop.setAttribute('stop-color', s[1]);
    hlGrad.appendChild(stop);
  });
  defs.appendChild(hlGrad);

  // Clip paths (animated)
  var leftClip = document.createElementNS(ns, 'clipPath');
  leftClip.id = 'leftClip';
  var leftClipPath = document.createElementNS(ns, 'path');
  leftClip.appendChild(leftClipPath);
  defs.appendChild(leftClip);

  var rightClip = document.createElementNS(ns, 'clipPath');
  rightClip.id = 'rightClip';
  var rightClipPath = document.createElementNS(ns, 'path');
  rightClip.appendChild(rightClipPath);
  defs.appendChild(rightClip);

  svg.appendChild(defs);

  // ─── Eye geometry constants ─────────────────────────────────
  var LCX = 165;   // left eye center x
  var RCX = 415;   // right eye center x
  var CY = 155;    // vertical center
  var EW = 80;     // eye half-width (corner to center)
  var EH = 50;     // max eye half-height when fully open

  // ─── Path generators ────────────────────────────────────────
  function eyeOpenPath(cx, open) {
    var ix = cx - EW;       // inner corner x
    var ox = cx + EW;       // outer corner x
    var iy = CY + 3;        // inner corner y (slightly below center)
    var oy = CY - 5;        // outer corner y (cat-eye uptilt)

    if (open < 0.01) {
      return 'M ' + ix + ',' + CY + ' Q ' + cx + ',' + (CY - 3) + ' ' + ox + ',' + (CY - 2);
    }

    var uH = EH * open;
    var lH = EH * 0.32 * open;

    // Upper lid — pronounced arch, peak shifted slightly toward outer corner
    var u1x = cx - EW * 0.42;
    var u1y = CY - uH * 0.88;
    var u2x = cx + EW * 0.32;
    var u2y = CY - uH * 0.92;

    // Lower lid — gentle curve
    var l1x = cx + EW * 0.38;
    var l1y = CY + lH * 0.78;
    var l2x = cx - EW * 0.35;
    var l2y = CY + lH * 0.65;

    return 'M ' + ix + ',' + iy +
      ' C ' + u1x + ',' + u1y + ' ' + u2x + ',' + u2y + ' ' + ox + ',' + oy +
      ' C ' + l1x + ',' + l1y + ' ' + l2x + ',' + l2y + ' ' + ix + ',' + iy + ' Z';
  }

  function upperLidPath(cx, open) {
    var ix = cx - EW;
    var ox = cx + EW;
    var iy = CY + 3;
    var oy = CY - 5;
    var uH = EH * open;
    return 'M ' + ix + ',' + iy +
      ' C ' + (cx - EW * 0.42) + ',' + (CY - uH * 0.88) +
      ' ' + (cx + EW * 0.32) + ',' + (CY - uH * 0.92) +
      ' ' + ox + ',' + oy;
  }

  function closedLinePath(cx) {
    return 'M ' + (cx - EW * 0.95) + ',' + CY +
      ' Q ' + cx + ',' + (CY - 4) +
      ' ' + (cx + EW * 0.95) + ',' + (CY - 2);
  }

  // Get point and tangent on upper lid cubic bezier at parameter t
  function upperLidPoint(cx, open, t) {
    var ix = cx - EW, ox = cx + EW;
    var iy = CY + 3, oy = CY - 5;
    var uH = EH * open;
    var u1x = cx - EW * 0.42, u1y = CY - uH * 0.88;
    var u2x = cx + EW * 0.32, u2y = CY - uH * 0.92;

    var mt = 1 - t;
    var px = mt*mt*mt*ix + 3*mt*mt*t*u1x + 3*mt*t*t*u2x + t*t*t*ox;
    var py = mt*mt*mt*iy + 3*mt*mt*t*u1y + 3*mt*t*t*u2y + t*t*t*oy;

    var tdx = 3*mt*mt*(u1x - ix) + 6*mt*t*(u2x - u1x) + 3*t*t*(ox - u2x);
    var tdy = 3*mt*mt*(u1y - iy) + 6*mt*t*(u2y - u1y) + 3*t*t*(oy - u2y);
    var tLen = Math.sqrt(tdx*tdx + tdy*tdy) || 1;

    return {
      x: px, y: py,
      nx: -tdy / tLen,  // outward normal x
      ny: tdx / tLen,   // outward normal y
      tx: tdx / tLen,   // tangent x
      ty: tdy / tLen    // tangent y
    };
  }

  // ─── Create eyebrow ────────────────────────────────────────
  function createBrow(cx, side) {
    var g = document.createElementNS(ns, 'g');
    var isLeft = (side === 'left');

    // Brow shape coordinates — thick filled arch
    // Matches reference: thick in middle, tapers at both ends
    var innerX, peakX, outerX;
    var topInnerY, topPeakY, topOuterY;
    var thickness; // varies along brow

    if (isLeft) {
      innerX = cx - EW * 0.65;
      peakX = cx + EW * 0.2;
      outerX = cx + EW * 0.88;
    } else {
      innerX = cx + EW * 0.65;
      peakX = cx - EW * 0.2;
      outerX = cx - EW * 0.88;
    }

    topPeakY = CY - EH * 1.72;
    topInnerY = CY - EH * 1.15;
    topOuterY = CY - EH * 1.2;

    // Filled brow shape — upper and lower edges
    var browPath = document.createElementNS(ns, 'path');
    var thickInner = 5;  // thin at inner end
    var thickPeak = 12;  // thickest in middle
    var thickOuter = 3;  // thin at tail

    browPath.setAttribute('d',
      // Upper edge
      'M ' + innerX + ',' + topInnerY +
      ' Q ' + ((innerX + peakX) / 2) + ',' + (topPeakY - 3) +
      ' ' + peakX + ',' + topPeakY +
      ' Q ' + ((peakX + outerX) / 2) + ',' + ((topPeakY + topOuterY) / 2 - 4) +
      ' ' + outerX + ',' + topOuterY +
      // Lower edge (return path, offset downward by thickness)
      ' Q ' + ((peakX + outerX) / 2) + ',' + ((topPeakY + topOuterY) / 2 - 4 + thickOuter) +
      ' ' + peakX + ',' + (topPeakY + thickPeak) +
      ' Q ' + ((innerX + peakX) / 2) + ',' + (topPeakY - 3 + thickPeak) +
      ' ' + innerX + ',' + (topInnerY + thickInner) +
      ' Z'
    );
    browPath.setAttribute('fill', 'rgba(255,255,255,0.38)');
    browPath.setAttribute('stroke', 'none');
    g.appendChild(browPath);

    // Upper edge stroke for definition
    var browStroke = document.createElementNS(ns, 'path');
    browStroke.setAttribute('d',
      'M ' + innerX + ',' + topInnerY +
      ' Q ' + ((innerX + peakX) / 2) + ',' + (topPeakY - 3) +
      ' ' + peakX + ',' + topPeakY +
      ' Q ' + ((peakX + outerX) / 2) + ',' + ((topPeakY + topOuterY) / 2 - 4) +
      ' ' + outerX + ',' + topOuterY
    );
    browStroke.setAttribute('fill', 'none');
    browStroke.setAttribute('stroke', 'rgba(255,255,255,0.5)');
    browStroke.setAttribute('stroke-width', '1.2');
    browStroke.setAttribute('stroke-linecap', 'round');
    g.appendChild(browStroke);

    // Lower edge stroke
    var browLower = document.createElementNS(ns, 'path');
    browLower.setAttribute('d',
      'M ' + innerX + ',' + (topInnerY + thickInner) +
      ' Q ' + ((innerX + peakX) / 2) + ',' + (topPeakY - 3 + thickPeak) +
      ' ' + peakX + ',' + (topPeakY + thickPeak) +
      ' Q ' + ((peakX + outerX) / 2) + ',' + ((topPeakY + topOuterY) / 2 - 4 + thickOuter) +
      ' ' + outerX + ',' + (topOuterY + thickOuter)
    );
    browLower.setAttribute('fill', 'none');
    browLower.setAttribute('stroke', 'rgba(255,255,255,0.35)');
    browLower.setAttribute('stroke-width', '0.8');
    browLower.setAttribute('stroke-linecap', 'round');
    g.appendChild(browLower);

    // Hair-stroke texture — short lines mimicking individual hairs
    var hairCount = 28;
    for (var i = 0; i < hairCount; i++) {
      var ht = (i + 0.3) / hairCount;

      // Position along brow arch (quadratic interpolation)
      var mt1 = 1 - ht;
      var hx = mt1 * mt1 * innerX + 2 * mt1 * ht * peakX + ht * ht * outerX;
      var hy = mt1 * mt1 * topInnerY + 2 * mt1 * ht * topPeakY + ht * ht * topOuterY;
      // Center vertically in brow
      var localThick = mt1 * mt1 * thickInner + 2 * mt1 * ht * thickPeak + ht * ht * thickOuter;
      hy += localThick * 0.4;

      // Hair direction: near-vertical at inner end, more lateral toward outer
      var hairAngle;
      if (isLeft) {
        hairAngle = -1.3 + ht * 0.9; // -1.3 rad (upward-left) to -0.4 rad (more lateral)
      } else {
        hairAngle = -1.8 + ht * -0.9; // mirror
        hairAngle = Math.PI + 1.3 - ht * 0.9;
      }

      var hairLen = 4 + Math.sin(ht * Math.PI) * 6;
      var hair = document.createElementNS(ns, 'line');
      hair.setAttribute('x1', hx - Math.cos(hairAngle) * hairLen * 0.4);
      hair.setAttribute('y1', hy - Math.sin(hairAngle) * hairLen * 0.4);
      hair.setAttribute('x2', hx + Math.cos(hairAngle) * hairLen * 0.6);
      hair.setAttribute('y2', hy + Math.sin(hairAngle) * hairLen * 0.6);
      hair.setAttribute('stroke', 'rgba(255,255,255,' + (0.2 + Math.sin(ht * Math.PI) * 0.2) + ')');
      hair.setAttribute('stroke-width', String(0.6 + Math.sin(ht * Math.PI) * 0.6));
      hair.setAttribute('stroke-linecap', 'round');
      g.appendChild(hair);
    }

    return g;
  }

  // ─── Create one eye ─────────────────────────────────────────
  function createEye(cx, clipId, side) {
    var g = document.createElementNS(ns, 'g');

    // --- Iris group (clipped to eye opening) ---
    var irisG = document.createElementNS(ns, 'g');
    irisG.setAttribute('clip-path', 'url(#' + clipId + ')');

    // Sclera
    var sclera = document.createElementNS(ns, 'ellipse');
    sclera.setAttribute('cx', cx);
    sclera.setAttribute('cy', CY);
    sclera.setAttribute('rx', EW * 0.72);
    sclera.setAttribute('ry', EH * 0.82);
    sclera.setAttribute('fill', 'rgba(220,220,225,0.08)');
    irisG.appendChild(sclera);

    // Iris
    var irisR = 35;
    var iris = document.createElementNS(ns, 'circle');
    iris.setAttribute('cx', cx);
    iris.setAttribute('cy', CY);
    iris.setAttribute('r', irisR);
    iris.setAttribute('fill', 'url(#irisGrad)');
    irisG.appendChild(iris);

    // Limbal ring
    var limbal = document.createElementNS(ns, 'circle');
    limbal.setAttribute('cx', cx);
    limbal.setAttribute('cy', CY);
    limbal.setAttribute('r', irisR - 1);
    limbal.setAttribute('fill', 'none');
    limbal.setAttribute('stroke', 'rgba(6,30,18,0.8)');
    limbal.setAttribute('stroke-width', '2.5');
    irisG.appendChild(limbal);

    // Gold hint
    var gold = document.createElementNS(ns, 'circle');
    gold.setAttribute('cx', cx);
    gold.setAttribute('cy', CY);
    gold.setAttribute('r', irisR * 0.42);
    gold.setAttribute('fill', 'url(#goldHint)');
    irisG.appendChild(gold);

    // Stroma fibers
    for (var f = 0; f < 24; f++) {
      var fa = (f / 24) * Math.PI * 2;
      var fl = document.createElementNS(ns, 'line');
      fl.setAttribute('x1', cx + Math.cos(fa) * 9);
      fl.setAttribute('y1', CY + Math.sin(fa) * 9);
      fl.setAttribute('x2', cx + Math.cos(fa) * (irisR - 3));
      fl.setAttribute('y2', CY + Math.sin(fa) * (irisR - 3));
      fl.setAttribute('stroke', f % 6 === 0 ? 'rgba(190,175,90,0.12)' : 'rgba(30,200,100,0.1)');
      fl.setAttribute('stroke-width', '0.5');
      irisG.appendChild(fl);
    }

    // Pupil
    var pupil = document.createElementNS(ns, 'circle');
    pupil.setAttribute('cx', cx);
    pupil.setAttribute('cy', CY);
    pupil.setAttribute('r', '11');
    pupil.setAttribute('fill', '#080808');
    irisG.appendChild(pupil);

    // Catch-light
    var hl = document.createElementNS(ns, 'circle');
    hl.setAttribute('cx', cx - 9);
    hl.setAttribute('cy', CY - 8);
    hl.setAttribute('r', '6.5');
    hl.setAttribute('fill', 'url(#catchLight)');
    irisG.appendChild(hl);

    // Secondary catch-light
    var hl2 = document.createElementNS(ns, 'circle');
    hl2.setAttribute('cx', cx + 7);
    hl2.setAttribute('cy', CY + 6);
    hl2.setAttribute('r', '2.5');
    hl2.setAttribute('fill', 'rgba(255,255,255,0.4)');
    irisG.appendChild(hl2);

    g.appendChild(irisG);

    // --- Eye outline ---
    var outline = document.createElementNS(ns, 'path');
    outline.setAttribute('fill', 'none');
    outline.setAttribute('stroke', 'rgba(255,255,255,0.55)');
    outline.setAttribute('stroke-width', '2');
    outline.setAttribute('stroke-linecap', 'round');
    outline.setAttribute('stroke-linejoin', 'round');
    g.appendChild(outline);
    g._outline = outline;

    // --- Bold upper lid (eyeliner) ---
    var liner = document.createElementNS(ns, 'path');
    liner.setAttribute('fill', 'none');
    liner.setAttribute('stroke', 'rgba(255,255,255,0.7)');
    liner.setAttribute('stroke-width', '3.5');
    liner.setAttribute('stroke-linecap', 'round');
    g.appendChild(liner);
    g._liner = liner;

    // --- Crease line ---
    var crease = document.createElementNS(ns, 'path');
    crease.setAttribute('fill', 'none');
    crease.setAttribute('stroke', 'rgba(255,255,255,0.12)');
    crease.setAttribute('stroke-width', '1');
    crease.setAttribute('stroke-linecap', 'round');
    g.appendChild(crease);
    g._crease = crease;

    // --- Upper lash container ---
    var upperLashG = document.createElementNS(ns, 'g');
    upperLashG.setAttribute('fill', 'none');
    g.appendChild(upperLashG);
    g._upperLashG = upperLashG;

    // --- Lower lash container ---
    var lowerLashG = document.createElementNS(ns, 'g');
    lowerLashG.setAttribute('fill', 'none');
    g.appendChild(lowerLashG);
    g._lowerLashG = lowerLashG;

    // --- Closed line ---
    var closedLine = document.createElementNS(ns, 'path');
    closedLine.setAttribute('fill', 'none');
    closedLine.setAttribute('stroke', 'rgba(255,255,255,0.4)');
    closedLine.setAttribute('stroke-width', '1.5');
    closedLine.setAttribute('stroke-linecap', 'round');
    closedLine.setAttribute('d', closedLinePath(cx));
    g.appendChild(closedLine);
    g._closedLine = closedLine;

    return g;
  }

  // ─── Build upper lashes — DRAMATIC, matching reference ─────
  function buildUpperLashes(g, cx, open, side) {
    while (g._upperLashG.firstChild) g._upperLashG.removeChild(g._upperLashG.firstChild);
    if (open < 0.08) return;

    var isLeft = (side === 'left');

    // Define lash positions along the lid (t parameter, 0=inner, 1=outer)
    // Cluster more toward outer corner like the reference
    var lashPositions = [
      0.06, 0.11, 0.16, 0.21, 0.26,
      0.31, 0.36, 0.41, 0.46, 0.51,
      0.56, 0.60, 0.64, 0.68, 0.72,
      0.76, 0.80, 0.84, 0.88, 0.92, 0.96
    ];

    for (var i = 0; i < lashPositions.length; i++) {
      var t = lashPositions[i];
      var pt = upperLidPoint(cx, open, t);

      // "outer" = how far toward the outer corner (0=inner, 1=outer)
      var outer = isLeft ? t : (1 - t);

      // DRAMATIC lash length — reference shows very long outer lashes
      // Inner lashes: ~15px, middle: ~25px, outer: ~48px
      var lashLen = (12 + outer * outer * 42) * open;

      // Lash thickness — thicker toward outer
      var lashWidth = 0.8 + outer * 1.8;

      // Curl — outer lashes curl outward more dramatically
      var curlStrength = 0.15 + outer * 0.55;
      var curlDir = isLeft ? 1 : -1;

      // End point — lashes go outward (normal) with curl
      var endX = pt.x + pt.nx * lashLen;
      var endY = pt.y + pt.ny * lashLen;

      // Control point for the curl (quadratic bezier)
      var cpX = pt.x + pt.nx * lashLen * 0.55 + pt.tx * curlDir * curlStrength * lashLen;
      var cpY = pt.y + pt.ny * lashLen * 0.55 + pt.ty * curlDir * curlStrength * lashLen;

      var lash = document.createElementNS(ns, 'path');
      lash.setAttribute('d', 'M ' + pt.x + ',' + pt.y +
        ' Q ' + cpX + ',' + cpY + ' ' + endX + ',' + endY);
      lash.setAttribute('stroke', 'rgba(255,255,255,' + (0.55 + outer * 0.25) + ')');
      lash.setAttribute('stroke-width', String(lashWidth));
      lash.setAttribute('stroke-linecap', 'round');
      g._upperLashG.appendChild(lash);

      // Add "companion" lashes for thickness on the outer half (like reference)
      if (outer > 0.4 && open > 0.3) {
        var compLen = lashLen * (0.6 + Math.random() * 0.25);
        var compCurl = curlStrength * (0.8 + Math.random() * 0.3);
        var compEndX = pt.x + pt.nx * compLen + pt.tx * curlDir * 3;
        var compEndY = pt.y + pt.ny * compLen + pt.ty * curlDir * 3;
        var compCpX = pt.x + pt.nx * compLen * 0.5 + pt.tx * curlDir * compCurl * compLen;
        var compCpY = pt.y + pt.ny * compLen * 0.5 + pt.ty * curlDir * compCurl * compLen;

        var comp = document.createElementNS(ns, 'path');
        comp.setAttribute('d', 'M ' + (pt.x + pt.tx * curlDir * 2) + ',' + (pt.y + pt.ty * curlDir * 2) +
          ' Q ' + compCpX + ',' + compCpY + ' ' + compEndX + ',' + compEndY);
        comp.setAttribute('stroke', 'rgba(255,255,255,' + (0.35 + outer * 0.2) + ')');
        comp.setAttribute('stroke-width', String(lashWidth * 0.7));
        comp.setAttribute('stroke-linecap', 'round');
        g._upperLashG.appendChild(comp);
      }
    }
  }

  // ─── Build lower lashes ─────────────────────────────────────
  function buildLowerLashes(g, cx, open, side) {
    while (g._lowerLashG.firstChild) g._lowerLashG.removeChild(g._lowerLashG.firstChild);
    if (open < 0.25) return;

    var isLeft = (side === 'left');
    var lH = EH * 0.32 * open;

    // 10 lower lashes, sparser than upper
    for (var j = 0; j < 10; j++) {
      var lt = (j + 0.5) / 10;
      var lx = cx - EW * 0.68 + lt * EW * 1.36;
      var ly = CY + Math.sin(lt * Math.PI) * lH * 0.82;

      var outer = isLeft ? lt : (1 - lt);
      var lLen = (5 + outer * 14) * open;

      // Slight outward angle
      var dx = (outer - 0.45) * 4;

      var ll = document.createElementNS(ns, 'path');
      ll.setAttribute('d', 'M ' + lx + ',' + ly +
        ' Q ' + (lx + dx * 0.5) + ',' + (ly + lLen * 0.6) +
        ' ' + (lx + dx) + ',' + (ly + lLen));
      ll.setAttribute('stroke', 'rgba(255,255,255,' + (0.3 + outer * 0.2) + ')');
      ll.setAttribute('stroke-width', String(0.5 + outer * 0.7));
      ll.setAttribute('stroke-linecap', 'round');
      g._lowerLashG.appendChild(ll);
    }
  }

  // ─── Create eyebrows and eyes ───────────────────────────────
  var leftBrowG = createBrow(LCX, 'left');
  var rightBrowG = createBrow(RCX, 'right');
  var leftEyeG = createEye(LCX, 'leftClip', 'left');
  var rightEyeG = createEye(RCX, 'rightClip', 'right');

  // Nose bridge hint
  var nose = document.createElementNS(ns, 'path');
  nose.setAttribute('d', 'M 282,' + (CY - 12) + ' Q 290,' + (CY + 15) + ' 288,' + (CY + 35));
  nose.setAttribute('fill', 'none');
  nose.setAttribute('stroke', 'rgba(255,255,255,0.04)');
  nose.setAttribute('stroke-width', '1.5');
  svg.appendChild(nose);

  svg.appendChild(leftEyeG);
  svg.appendChild(rightEyeG);
  svg.appendChild(leftBrowG);
  svg.appendChild(rightBrowG);

  // Start brows hidden (will fade in with eyes)
  leftBrowG.setAttribute('opacity', '0');
  rightBrowG.setAttribute('opacity', '0');

  // ─── Update eyes for current open amount ────────────────────
  function updateEyes(open) {
    // Clip paths
    leftClipPath.setAttribute('d', eyeOpenPath(LCX, Math.max(open, 0.001)));
    rightClipPath.setAttribute('d', eyeOpenPath(RCX, Math.max(open, 0.001)));

    // Outlines
    leftEyeG._outline.setAttribute('d', open > 0.01 ? eyeOpenPath(LCX, open) : closedLinePath(LCX));
    rightEyeG._outline.setAttribute('d', open > 0.01 ? eyeOpenPath(RCX, open) : closedLinePath(RCX));

    // Upper lid liner
    if (open > 0.03) {
      leftEyeG._liner.setAttribute('d', upperLidPath(LCX, open));
      rightEyeG._liner.setAttribute('d', upperLidPath(RCX, open));
      var linerAlpha = Math.min(open * 1.2, 0.7);
      leftEyeG._liner.setAttribute('stroke', 'rgba(255,255,255,' + linerAlpha + ')');
      rightEyeG._liner.setAttribute('stroke', 'rgba(255,255,255,' + linerAlpha + ')');
    } else {
      leftEyeG._liner.setAttribute('d', '');
      rightEyeG._liner.setAttribute('d', '');
    }

    // Crease
    if (open > 0.2) {
      var ca = Math.min((open - 0.2) * 0.18, 0.12);
      [LCX, RCX].forEach(function(ecx, idx) {
        var el = idx === 0 ? leftEyeG : rightEyeG;
        var ci = ecx - EW * 0.68;
        var co = ecx + EW * 0.68;
        var cpy = CY - EH * open * 1.28;
        el._crease.setAttribute('d',
          'M ' + ci + ',' + (CY - EH * open * 0.48) +
          ' Q ' + ecx + ',' + cpy +
          ' ' + co + ',' + (CY - EH * open * 0.42));
        el._crease.setAttribute('stroke', 'rgba(255,255,255,' + ca + ')');
      });
    }

    // Closed line fades out as eyes open
    var closedAlpha = 0.4 * (1 - open);
    leftEyeG._closedLine.setAttribute('stroke', 'rgba(255,255,255,' + closedAlpha + ')');
    rightEyeG._closedLine.setAttribute('stroke', 'rgba(255,255,255,' + closedAlpha + ')');

    // Eyebrows — fade in and lift upward as eyes open
    var browAlpha = Math.min(open * 1.5, 1);
    var browLift = open * 8;
    leftBrowG.setAttribute('opacity', String(browAlpha));
    rightBrowG.setAttribute('opacity', String(browAlpha));
    leftBrowG.setAttribute('transform', 'translate(0,' + (-browLift) + ')');
    rightBrowG.setAttribute('transform', 'translate(0,' + (-browLift) + ')');

    // Lashes — only rebuild when open amount changes significantly
    if (Math.abs(open - prevOpen) > 0.008 || prevOpen < 0) {
      buildUpperLashes(leftEyeG, LCX, open, 'left');
      buildUpperLashes(rightEyeG, RCX, open, 'right');
      buildLowerLashes(leftEyeG, LCX, open, 'left');
      buildLowerLashes(rightEyeG, RCX, open, 'right');
      prevOpen = open;
    }
  }

  // Initial state — closed
  updateEyes(0);

  // ─── Animation Loop ───────────────────────────────────────
  var lastTime = 0;
  function animate(timestamp) {
    requestAnimationFrame(animate);
    var dt = Math.min((timestamp - lastTime) / 1000, 0.05);
    lastTime = timestamp;
    time += dt;

    // Smooth interpolation — opens faster than it closes
    var speed = targetOpen > openAmount ? 2.0 : 1.2;
    var diff = targetOpen - openAmount;
    openAmount += diff * speed * dt;
    if (Math.abs(diff) < 0.002) openAmount = targetOpen;

    // Auto-close after 12s inactivity
    if (targetOpen > 0 && time - lastActivity > 12) {
      targetOpen = 0;
    }

    updateEyes(openAmount);
  }
  requestAnimationFrame(animate);

  // ─── Interaction ──────────────────────────────────────────
  function openEyes() {
    targetOpen = 1;
    lastActivity = time;
  }

  function keepAwake() {
    lastActivity = time;
    if (targetOpen < 1) targetOpen = 1;
  }

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
