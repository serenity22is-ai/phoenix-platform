/**
 * MYSTES Aurora Scene — Three.js WebGL Background
 * Realistic aurora borealis curtains — NO stars
 * Smooth flowing vertical bands with organic movement
 */
(function () {
  'use strict';

  if (typeof THREE === 'undefined') return;

  const canvas = document.getElementById('aurora-canvas');
  if (!canvas) return;

  const isMobile = window.innerWidth < 768;

  // ─── Renderer ───────────────────────────────────────────────
  const renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: !isMobile,
    powerPreference: 'high-performance'
  });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // ─── Scene & Camera ───────────────────────────────────────
  const auroraScene = new THREE.Scene();
  const auroraCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  // ─── State ──────────────────────────────────────────────────
  const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
  let scrollY = 0;
  let scrollTarget = 0;
  const clock = new THREE.Clock();

  // ─── Aurora Shader — Realistic Curtains ─────────────────────
  const auroraVertexShader = `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = vec4(position, 1.0);
    }
  `;

  const auroraFragmentShader = `
    precision highp float;
    varying vec2 vUv;
    uniform float uTime;
    uniform vec2 uMouse;
    uniform float uScroll;
    uniform vec2 uResolution;

    // Smooth value noise
    float hash(vec2 p) {
      vec3 p3 = fract(vec3(p.xyx) * 0.1031);
      p3 += dot(p3, p3.yzx + 33.33);
      return fract((p3.x + p3.y) * p3.z);
    }

    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      float a = hash(i);
      float b = hash(i + vec2(1.0, 0.0));
      float c = hash(i + vec2(0.0, 1.0));
      float d = hash(i + vec2(1.0, 1.0));
      return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
    }

    // Low-octave FBM for smooth, large-scale variation
    float fbm(vec2 p) {
      float v = 0.0;
      v += 0.500 * noise(p); p *= 2.01;
      v += 0.250 * noise(p); p *= 2.02;
      v += 0.125 * noise(p);
      return v / 0.875;
    }

    // Aurora curtain function — creates a single flowing band
    float curtain(float x, float y, float t, float freq, float speed, float phase) {
      // Horizontal waving — slow sinusoidal + noise warp
      float wave = sin(x * freq + t * speed + phase) * 0.5 + 0.5;

      // Organic warping from low-freq noise
      float warp = fbm(vec2(x * 0.4 + t * 0.06 + phase, t * 0.03)) * 0.4;
      wave = wave * 0.6 + warp;

      // Vertical shape — bell curve, concentrated in upper screen
      float center = 0.65 + wave * 0.15 + sin(x * 2.0 + t * 0.3 + phase) * 0.05;
      float spread = 0.12 + wave * 0.06;
      float band = exp(-pow((y - center) / spread, 2.0));

      // Vertical striations — the "curtain folds"
      float folds = 0.4 + 0.6 * pow(
        0.5 + 0.5 * sin(x * 15.0 + fbm(vec2(x * 1.5 + phase, t * 0.1)) * 3.0 + t * 0.2),
        1.5
      );

      return band * folds;
    }

    void main() {
      vec2 uv = vUv;
      float aspect = uResolution.x / uResolution.y;
      float t = uTime * 0.12;
      float x = uv.x * aspect + uMouse.x * 0.03;
      float y = uv.y + uScroll * 0.0002;

      // === Multiple aurora curtain layers ===

      // Layer 1: Main green aurora — dominant, brightest
      float c1 = curtain(x, y, t, 2.5, 0.4, 0.0);
      vec3 green = vec3(0.15, 0.85, 0.45);

      // Layer 2: Teal secondary band
      float c2 = curtain(x + 0.5, y, t, 3.0, -0.3, 2.1);
      vec3 teal = vec3(0.08, 0.65, 0.7);

      // Layer 3: Purple upper glow
      float c3 = curtain(x + 1.0, y + 0.08, t, 2.0, 0.2, 4.2);
      vec3 purple = vec3(0.55, 0.15, 0.85);

      // Layer 4: Soft pink/red at the very top
      float c4 = curtain(x + 1.5, y + 0.12, t, 1.8, -0.15, 6.3);
      vec3 pink = vec3(0.75, 0.12, 0.5);

      // Height-based color blending within each curtain
      float heightMix = smoothstep(0.5, 0.85, y);

      // Composite all layers
      vec3 aurora = vec3(0.0);
      aurora += mix(green, teal, heightMix * 0.3) * c1 * 0.7;
      aurora += teal * c2 * 0.35;
      aurora += purple * c3 * 0.45;
      aurora += pink * c4 * 0.25;

      // Soft bloom/glow
      float bloom = (c1 + c2 * 0.5 + c3 * 0.7 + c4 * 0.3) * 0.06;
      vec3 bloomColor = mix(vec3(0.1, 0.6, 0.4), vec3(0.4, 0.1, 0.6), heightMix);
      aurora += bloomColor * bloom;

      // Bottom fade (dark ground) and top softening
      float edgeFade = smoothstep(0.0, 0.3, uv.y) * smoothstep(1.0, 0.88, uv.y);
      aurora *= edgeFade;

      // Brightness boost
      aurora *= 1.4;

      // Very subtle vignette for depth
      float vig = 1.0 - 0.15 * length((uv - 0.5) * vec2(aspect, 1.0));
      aurora *= vig;

      gl_FragColor = vec4(aurora, 1.0);
    }
  `;

  const auroraGeometry = new THREE.PlaneGeometry(2, 2);
  const auroraMaterial = new THREE.ShaderMaterial({
    vertexShader: auroraVertexShader,
    fragmentShader: auroraFragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) },
      uScroll: { value: 0 },
      uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) }
    },
    transparent: true,
    depthWrite: false
  });
  const auroraMesh = new THREE.Mesh(auroraGeometry, auroraMaterial);
  auroraScene.add(auroraMesh);

  // ─── Mouse tracking ─────────────────────────────────────────
  if (!isMobile) {
    window.addEventListener('mousemove', function (e) {
      mouse.tx = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.ty = -(e.clientY / window.innerHeight - 0.5) * 2;
    }, { passive: true });
  }

  // ─── Scroll tracking ───────────────────────────────────────
  window.addEventListener('scroll', function () {
    scrollTarget = window.pageYOffset || document.documentElement.scrollTop;
  }, { passive: true });

  // ─── Resize ─────────────────────────────────────────────────
  window.addEventListener('resize', function () {
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setSize(w, h);
    auroraMaterial.uniforms.uResolution.value.set(w, h);
  }, { passive: true });

  // ─── Animation Loop ─────────────────────────────────────────
  function animate() {
    requestAnimationFrame(animate);

    const elapsed = clock.getElapsedTime();

    // Smooth mouse interpolation
    mouse.x += (mouse.tx - mouse.x) * 0.04;
    mouse.y += (mouse.ty - mouse.y) * 0.04;

    // Smooth scroll interpolation
    scrollY += (scrollTarget - scrollY) * 0.1;

    // Update aurora
    auroraMaterial.uniforms.uTime.value = elapsed;
    auroraMaterial.uniforms.uMouse.value.set(mouse.x, mouse.y);
    auroraMaterial.uniforms.uScroll.value = scrollY;

    // Render aurora only
    renderer.render(auroraScene, auroraCamera);
  }

  animate();
})();
