/**
 * MYSTES Aurora Scene — Three.js WebGL Background
 * Dark purple/black/blue aurora with star field
 * Deep space with flowing violet and indigo curtains
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
    alpha: false,
    antialias: !isMobile,
    powerPreference: 'high-performance'
  });
  renderer.setClearColor(0x0a0612, 1);
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

  // ─── Aurora Shader — Dark Mystes Palette + Stars ─────────────
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

    // Star field — deterministic pseudo-random star positions
    float stars(vec2 uv, float scale, float brightness) {
      vec2 grid = floor(uv * scale);
      vec2 f = fract(uv * scale);

      // Random position within each grid cell
      float rnd = hash(grid);
      float rnd2 = hash(grid + vec2(127.1, 311.7));
      vec2 starPos = vec2(rnd, rnd2) * 0.8 + 0.1;

      // Distance from star center
      float d = length(f - starPos);

      // Star brightness with slight twinkle
      float twinkle = 0.7 + 0.3 * sin(uTime * (1.0 + rnd * 2.0) + rnd * 6.28);

      // Only show ~30% of cells as stars (density control)
      float show = step(0.7, hash(grid + vec2(42.0, 17.0)));

      // Sharp point of light
      float star = show * brightness * twinkle * smoothstep(0.03, 0.005, d);

      // Vary star size — some bigger, some smaller
      float bigStar = show * brightness * twinkle * 0.3 * step(0.92, rnd) * smoothstep(0.05, 0.015, d);

      return star + bigStar;
    }

    // Aurora curtain function — creates a single flowing band
    float curtain(float x, float y, float t, float freq, float speed, float phase) {
      float wave = sin(x * freq + t * speed + phase) * 0.5 + 0.5;
      float warp = fbm(vec2(x * 0.4 + t * 0.06 + phase, t * 0.03)) * 0.4;
      wave = wave * 0.6 + warp;

      float center = 0.62 + wave * 0.18 + sin(x * 2.0 + t * 0.3 + phase) * 0.06;
      float spread = 0.10 + wave * 0.06;
      float band = exp(-pow((y - center) / spread, 2.0));

      // Curtain folds
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

      // === MYSTES Dark Aurora — Purple / Indigo / Blue ===

      // Deep space base — very dark purple-black (#0a0612)
      vec3 base = vec3(0.039, 0.024, 0.071);

      // === Star field — multiple layers for depth ===
      vec2 starUv = vec2(uv.x * aspect, uv.y);
      float starLight = 0.0;
      starLight += stars(starUv, 80.0, 0.9);   // Dense small stars
      starLight += stars(starUv + 100.0, 40.0, 1.0);  // Medium stars
      starLight += stars(starUv + 200.0, 20.0, 1.2);  // Fewer bright stars

      // Slight warm/cool color variation on stars
      float starColorMix = hash(floor(starUv * 80.0));
      vec3 starColor = mix(
        vec3(0.85, 0.85, 1.0),   // Cool white-blue
        vec3(1.0, 0.92, 0.8),    // Warm white-gold
        starColorMix * 0.3
      );

      // Layer 1: Deep violet aurora — primary, dominant
      float c1 = curtain(x, y, t, 2.5, 0.4, 0.0);
      vec3 violet = vec3(0.486, 0.227, 0.929);  // #7c3aed — mystes glow

      // Layer 2: Indigo band — secondary
      float c2 = curtain(x + 0.5, y, t, 3.0, -0.3, 2.1);
      vec3 indigo = vec3(0.357, 0.133, 0.714);  // #5b22b6 — deep purple

      // Layer 3: Dark blue shimmer — accent
      float c3 = curtain(x + 1.0, y + 0.06, t, 2.0, 0.2, 4.2);
      vec3 oceanBlue = vec3(0.031, 0.569, 0.698);    // #0891b2 — ocean blue

      // Layer 4: Subtle cyan highlight at peaks
      float c4 = curtain(x + 1.5, y + 0.10, t, 1.8, -0.15, 6.3);
      vec3 tealCyan = vec3(0.078, 0.722, 0.651);    // #14b8a6 — mystes silver/teal

      // Height-based color blending
      float heightMix = smoothstep(0.45, 0.85, y);

      // Composite — kept dim and moody
      vec3 aurora = base;

      // Add stars behind aurora (dimmed where aurora is bright)
      float auroraIntensity = c1 * 0.35 + c2 * 0.20 + c3 * 0.18 + c4 * 0.08;
      float starDim = 1.0 - smoothstep(0.0, 0.3, auroraIntensity);
      aurora += starColor * starLight * starDim;

      // Aurora layers
      aurora += mix(violet, indigo, heightMix * 0.4) * c1 * 0.35;
      aurora += indigo * c2 * 0.20;
      aurora += oceanBlue * c3 * 0.18;
      aurora += tealCyan * c4 * 0.08;

      // Subtle bloom/glow — purple-dominated
      float bloom = (c1 + c2 * 0.5 + c3 * 0.4 + c4 * 0.2) * 0.04;
      vec3 bloomColor = mix(vec3(0.30, 0.10, 0.55), vec3(0.05, 0.35, 0.55), heightMix);
      aurora += bloomColor * bloom;

      // Edge fades — dark ground, soft top
      float edgeFade = smoothstep(0.0, 0.25, uv.y) * smoothstep(1.0, 0.85, uv.y);
      aurora = mix(base, aurora, edgeFade);

      // Stars also fade at very bottom
      float starFade = smoothstep(0.0, 0.15, uv.y);
      aurora += starColor * starLight * starDim * (1.0 - edgeFade) * starFade * 0.5;

      // Subtle vignette for depth
      float vig = 1.0 - 0.2 * length((uv - 0.5) * vec2(aspect, 1.0));
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
