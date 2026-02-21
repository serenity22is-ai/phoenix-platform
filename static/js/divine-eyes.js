/**
 * MYSTES — Divine Eyes
 * Displays the actual pencil sketch image with a smooth reveal animation
 * Eyes "open" via a CSS clip-path that expands from the center line
 */
(function () {
  'use strict';

  var container = document.getElementById('divine-eyes-canvas');
  if (!container) return;

  container.innerHTML = '';
  container.style.display = 'flex';
  container.style.alignItems = 'center';
  container.style.justifyContent = 'center';

  // Create the image element
  var img = document.createElement('img');
  img.src = '/static/images/divine-eyes.png?v=5';
  img.alt = 'MYSTES Eyes';
  img.draggable = false;

  // Style — centered, responsive, with clip-path for reveal
  var isMobile = window.innerWidth < 768;
  img.style.cssText = [
    'width:' + (isMobile ? '320px' : '480px'),
    'height:auto',
    'object-fit:contain',
    'filter:invert(1) brightness(1.1) contrast(1.2)',
    'opacity:0.85',
    'clip-path:inset(48% 0 48% 0)',
    'transition:clip-path 1.8s cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 1s ease',
    'pointer-events:none',
    'user-select:none'
  ].join(';');

  container.appendChild(img);

  // State
  var isOpen = false;
  var time = 0;
  var lastActivity = 0;

  function openEyes() {
    img.style.clipPath = 'inset(0% 0 0% 0)';
    img.style.opacity = '0.85';
    isOpen = true;
    lastActivity = time;
  }

  function closeEyes() {
    img.style.clipPath = 'inset(48% 0 48% 0)';
    img.style.opacity = '0.4';
    isOpen = false;
  }

  // Time tracking for auto-close
  var raf;
  function tick(ts) {
    time = ts / 1000;
    if (isOpen && time - lastActivity > 12) {
      closeEyes();
    }
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);

  // Auto-open after page load
  setTimeout(function () { openEyes(); }, 1500);

  // Interaction — open on search/chat focus
  function keepAwake() {
    lastActivity = time;
    if (!isOpen) openEyes();
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
        keepAwake();
      }
    }
  }, true);

  document.addEventListener('input', function () {
    if (isOpen) lastActivity = time;
  }, true);

  document.addEventListener('submit', function () { keepAwake(); }, true);

  document.addEventListener('click', function (e) {
    var el = e.target;
    if (!el) return;
    var cls = (el.className || '').toLowerCase();
    var text = (el.textContent || '').toLowerCase();
    if (cls.indexOf('search') > -1 || cls.indexOf('send') > -1 || text.indexOf('search') > -1) {
      keepAwake();
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && e.target === document.body)) {
      keepAwake();
    }
  });
})();
