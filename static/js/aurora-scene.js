/**
 * MYSTES Aurora Scene — Three.js WebGL Background
 * 3D aurora curtains + star field + interactive sacred geometry
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
  renderer.autoClear = false;

  // ─── Scenes & Camera ───────────────────────────────────────
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 5;

  // Separate scene for aurora (rendered behind)
  const auroraScene = new THREE.Scene();
  const auroraCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  // ─── State ──────────────────────────────────────────────────
  const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
  let scrollY = 0;
  let scrollTarget = 0;
  const clock = new THREE.Clock();

  // ─── Aurora Shader (fullscreen quad) ────────────────────────
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

    // Simplex-style hash noise
    vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

    float snoise(vec2 v) {
      const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                         -0.577350269189626, 0.024390243902439);
      vec2 i  = floor(v + dot(v, C.yy));
      vec2 x0 = v - i + dot(i, C.xx);
      vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
      vec4 x12 = x0.xyxy + C.xxzz;
      x12.xy -= i1;
      i = mod289(i);
      vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
      vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
      m = m * m;
      m = m * m;
      vec3 x = 2.0 * fract(p * C.www) - 1.0;
      vec3 h = abs(x) - 0.5;
      vec3 ox = floor(x + 0.5);
      vec3 a0 = x - ox;
      m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
      vec3 g;
      g.x = a0.x * x0.x + h.x * x0.y;
      g.yz = a0.yz * x12.xz + h.yz * x12.yw;
      return 130.0 * dot(m, g);
    }

    // Fractal Brownian Motion
    float fbm(vec2 p) {
      float f = 0.0;
      float w = 0.5;
      for (int i = 0; i < 5; i++) {
        f += w * snoise(p);
        p *= 2.0;
        w *= 0.5;
      }
      return f;
    }

    void main() {
      vec2 uv = vUv;
      float aspect = uResolution.x / uResolution.y;
      vec2 p = vec2(uv.x * aspect, uv.y);

      // Mouse influence — subtle displacement
      vec2 mouseInfluence = uMouse * 0.08;
      p += mouseInfluence;

      // Scroll — shift aurora upward
      float scrollOffset = uScroll * 0.0003;
      p.y += scrollOffset;

      float t = uTime * 0.15;

      // === Aurora Layer 1: Purple curtains ===
      float n1 = fbm(vec2(p.x * 1.5 + t * 0.3, p.y * 3.0 + sin(t * 0.5) * 0.5));
      // Curtain shape: concentrated in upper portion, flowing vertically
      float curtain1 = smoothstep(0.3, 0.7, uv.y + n1 * 0.3) * smoothstep(1.0, 0.55, uv.y);
      curtain1 *= smoothstep(-0.2, 0.3, n1);
      vec3 color1 = vec3(0.486, 0.228, 0.929); // #7c3aed purple

      // === Aurora Layer 2: Teal/cyan curtains ===
      float n2 = fbm(vec2(p.x * 1.2 - t * 0.2, p.y * 2.5 + cos(t * 0.4) * 0.6));
      float curtain2 = smoothstep(0.35, 0.75, uv.y + n2 * 0.25) * smoothstep(1.0, 0.6, uv.y);
      curtain2 *= smoothstep(-0.15, 0.35, n2);
      vec3 color2 = vec3(0.078, 0.722, 0.651); // #14b8a6 teal

      // === Aurora Layer 3: Deep violet shimmer ===
      float n3 = fbm(vec2(p.x * 2.0 + t * 0.1, p.y * 4.0 + sin(t * 0.3) * 0.8));
      float curtain3 = smoothstep(0.4, 0.8, uv.y + n3 * 0.2) * smoothstep(1.0, 0.65, uv.y);
      curtain3 *= smoothstep(-0.1, 0.4, n3) * 0.5;
      vec3 color3 = vec3(0.357, 0.129, 0.714); // #5b21b6 deep violet

      // Combine layers with additive blending
      vec3 aurora = color1 * curtain1 * 0.6
                  + color2 * curtain2 * 0.45
                  + color3 * curtain3 * 0.35;

      // Add subtle glow bloom
      float bloom = (curtain1 + curtain2 + curtain3) * 0.08;
      aurora += bloom;

      // Vertical fade: dark at bottom, aurora at top
      float vertFade = smoothstep(0.0, 0.4, uv.y);
      aurora *= vertFade;

      // Overall intensity
      aurora *= 0.85;

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

  // ─── Star Field ─────────────────────────────────────────────
  const STAR_COUNT = isMobile ? 2000 : 5000;
  const starPositions = new Float32Array(STAR_COUNT * 3);
  const starSizes = new Float32Array(STAR_COUNT);
  const starPhases = new Float32Array(STAR_COUNT);

  for (let i = 0; i < STAR_COUNT; i++) {
    starPositions[i * 3] = (Math.random() - 0.5) * 40;      // x
    starPositions[i * 3 + 1] = (Math.random() - 0.5) * 25;  // y
    starPositions[i * 3 + 2] = (Math.random() - 0.5) * 30 - 5; // z (behind camera mostly)
    starSizes[i] = Math.random() * 2.5 + 0.5;
    starPhases[i] = Math.random() * Math.PI * 2;
  }

  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
  starGeometry.setAttribute('aSize', new THREE.BufferAttribute(starSizes, 1));
  starGeometry.setAttribute('aPhase', new THREE.BufferAttribute(starPhases, 1));

  const starVertexShader = `
    attribute float aSize;
    attribute float aPhase;
    varying float vAlpha;
    uniform float uTime;
    uniform float uScroll;
    uniform vec2 uMouse;

    void main() {
      vec3 pos = position;

      // Scroll parallax — deeper stars move slower
      float depth = (pos.z + 20.0) / 40.0; // 0..1 normalized depth
      pos.y += uScroll * 0.001 * (1.0 - depth * 0.7);

      // Mouse parallax
      pos.x += uMouse.x * 0.3 * depth;
      pos.y += uMouse.y * 0.2 * depth;

      // Twinkle
      vAlpha = 0.4 + 0.6 * (0.5 + 0.5 * sin(uTime * 1.5 + aPhase));

      vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
      gl_PointSize = aSize * (300.0 / -mvPosition.z);
      gl_Position = projectionMatrix * mvPosition;
    }
  `;

  const starFragmentShader = `
    varying float vAlpha;
    void main() {
      // Soft circular point
      float d = length(gl_PointCoord - 0.5) * 2.0;
      if (d > 1.0) discard;
      float alpha = vAlpha * (1.0 - d * d);
      gl_FragColor = vec4(0.9, 0.92, 1.0, alpha);
    }
  `;

  const starMaterial = new THREE.ShaderMaterial({
    vertexShader: starVertexShader,
    fragmentShader: starFragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uScroll: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) }
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });

  const stars = new THREE.Points(starGeometry, starMaterial);
  scene.add(stars);

  // ─── Sacred Geometry (Interactive Wireframe) ────────────────
  const geoGroup = new THREE.Group();

  // Icosahedron wireframe
  const icoGeo = new THREE.IcosahedronGeometry(1.5, 1);
  const icoMat = new THREE.MeshBasicMaterial({
    color: 0x7c3aed,
    wireframe: true,
    transparent: true,
    opacity: 0.25
  });
  const icosahedron = new THREE.Mesh(icoGeo, icoMat);
  geoGroup.add(icosahedron);

  // Inner dodecahedron for depth
  const dodGeo = new THREE.DodecahedronGeometry(0.8, 0);
  const dodMat = new THREE.MeshBasicMaterial({
    color: 0x14b8a6,
    wireframe: true,
    transparent: true,
    opacity: 0.15
  });
  const dodecahedron = new THREE.Mesh(dodGeo, dodMat);
  geoGroup.add(dodecahedron);

  // Center point
  const centerGeo = new THREE.SphereGeometry(0.06, 16, 16);
  const centerMat = new THREE.MeshBasicMaterial({
    color: 0x7c3aed,
    transparent: true,
    opacity: 0.8
  });
  const centerSphere = new THREE.Mesh(centerGeo, centerMat);
  geoGroup.add(centerSphere);

  geoGroup.position.set(0, 0.3, 0);
  scene.add(geoGroup);

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
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    auroraMaterial.uniforms.uResolution.value.set(w, h);
  }, { passive: true });

  // ─── Animation Loop ─────────────────────────────────────────
  function animate() {
    requestAnimationFrame(animate);

    const elapsed = clock.getElapsedTime();
    const delta = clock.getDelta();

    // Smooth mouse interpolation
    mouse.x += (mouse.tx - mouse.x) * 0.05;
    mouse.y += (mouse.ty - mouse.y) * 0.05;

    // Smooth scroll interpolation
    scrollY += (scrollTarget - scrollY) * 0.1;

    // --- Update Aurora Shader ---
    auroraMaterial.uniforms.uTime.value = elapsed;
    auroraMaterial.uniforms.uMouse.value.set(mouse.x, mouse.y);
    auroraMaterial.uniforms.uScroll.value = scrollY;

    // --- Update Stars ---
    starMaterial.uniforms.uTime.value = elapsed;
    starMaterial.uniforms.uScroll.value = scrollY;
    starMaterial.uniforms.uMouse.value.set(mouse.x, mouse.y);

    // --- Update Sacred Geometry ---
    // Base rotation
    geoGroup.rotation.y += 0.003;
    geoGroup.rotation.x += 0.001;

    // Mouse influence on rotation
    geoGroup.rotation.y += mouse.x * 0.005;
    geoGroup.rotation.x += mouse.y * 0.003;

    // Counter-rotate inner dodecahedron
    dodecahedron.rotation.y -= 0.006;
    dodecahedron.rotation.z += 0.004;

    // Scroll: scale down and fade geometry as user scrolls
    const scrollFade = Math.max(0, 1 - scrollY / (window.innerHeight * 0.8));
    geoGroup.scale.setScalar(0.8 + scrollFade * 0.2);
    icoMat.opacity = 0.25 * scrollFade;
    dodMat.opacity = 0.15 * scrollFade;
    centerMat.opacity = 0.8 * scrollFade;

    // Center sphere pulse
    const pulse = 1 + Math.sin(elapsed * 2) * 0.15;
    centerSphere.scale.setScalar(pulse);

    // --- Render ---
    renderer.clear();
    renderer.render(auroraScene, auroraCamera);  // Aurora background first
    renderer.render(scene, camera);               // Stars + geometry on top
  }

  animate();
})();
