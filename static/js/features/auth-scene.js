/* ═══════════════════════════════════════════════════════════════════
   3D SCENE — port of the "Sign In 3D" design's DCLogic component.
   A particle planet (or abstract data field) with a wireframe core,
   spiral inflow, rings and dust. Reacts to pointer (push), drag
   (spin), click (ripple) and hovering the core. Theme follows the
   `.light-mode` class on <html>; respects prefers-reduced-motion.
   Failure to load three.js leaves the CSS glow washes as the backdrop.
   Used by templates/auth/login.html and register.html; expects #scene,
   #vignette, #mode-btn, #theme-btn/#theme-label (and optional #point-label).
═══════════════════════════════════════════════════════════════════ */
/* ── Theme chip: drives the app-wide theme, same key as Settings ── */
(function () {
  const root = document.documentElement;
  const label = document.getElementById('theme-label');
  const sync = () => { label.textContent = root.classList.contains('light-mode') ? 'Dark' : 'Light'; };
  document.getElementById('theme-btn').addEventListener('click', () => {
    const mode = root.classList.contains('light-mode') ? 'dark' : 'light';
    if (window.ThemeEngine) window.ThemeEngine.setThemeMode(mode);
    try { localStorage.setItem('am_theme_mode', mode); } catch (e) {}
    sync();
  });
  sync();
})();

const PALETTES = {
  light: {
    stops: ['#06B6D4', '#2563EB', '#4F46E5', '#7C3AED'],
    additive: false, pointOpacity: 0.72, pointSize: 0.062,
    hazeColor: 0x93b4f5, hazeOpacity: 0.055, hazeSize: 0.5,
    shell: 0x4f46e5, shellOpacity: 0.1, node: 0x2563eb, nodeOpacity: 0.5,
    ring: [0x2563eb, 0x06b6d4, 0x7c3aed], ringOpacity: 0.16,
    dust: 0x9db8e8, dustOpacity: 0.3,
    ambient: 0.85, key: 0.55, rim: 0.6, fill: 0.4,
  },
  dark: {
    stops: ['#5ff0c8', '#4fb9ff', '#7fa8ff', '#b58bff'],
    additive: true, pointOpacity: 0.95, pointSize: 0.072,
    hazeColor: 0x4fd7c0, hazeOpacity: 0.05, hazeSize: 0.55,
    shell: 0x2ee6b0, shellOpacity: 0.15, node: 0x7ff5d6, nodeOpacity: 0.7,
    ring: [0x3fe0c0, 0x5aa8ff, 0x9d7dff], ringOpacity: 0.32,
    dust: 0x8fd8ff, dustOpacity: 0.45,
    ambient: 0.6, key: 0.7, rim: 0.8, fill: 0.5,
  },
};

const PLANET = {
  light: { deep: '#1D4ED8', ocean: '#2563EB', shallow: '#06B6D4', sand: '#D9B26A', land: '#16A34A', high: '#4D7C0F', ice: '#93C5FD',
           ring: [0xD9B26A, 0xA78BFA, 0x93C5FD], ringOpacity: 0.4 },
  dark:  { deep: '#2563EB', ocean: '#3B82F6', shallow: '#22D3EE', sand: '#FCD34D', land: '#4ADE80', high: '#A3E635', ice: '#F1F5F9',
           ring: [0xFCD34D, 0xC4B5FD, 0x93C5FD], ringOpacity: 0.45 },
};

const MODE_KEY = 'am_login_scene';
const canvas = document.getElementById('scene');
const vignette = document.getElementById('vignette');
// The hint line is optional: pages without it just skip the label.
const pointLabel = document.getElementById('point-label') || { textContent: '' };
const modeBtn = document.getElementById('mode-btn');

const currentTheme = () => document.documentElement.classList.contains('light-mode') ? 'light' : 'dark';
let mode = 'planet';
try { if (localStorage.getItem(MODE_KEY) === 'field') mode = 'field'; } catch (e) {}
const syncModeLabel = () => { modeBtn.textContent = mode === 'planet' ? 'Data field' : 'Planet'; };
syncModeLabel();

let THREE, r, renderer;
const mouse = { x: 0, y: 0 }, eased = { x: 0, y: 0 };
const pointer = { active: false };
let interact = 0, client = null, drag = null, hoverCoreState = false, lastT, t0, tmpV;
const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function planetColor(P, x, y, z) {
  if (Math.abs(y) > 0.82) return new THREE.Color(P.ice);
  const n = Math.sin(x * 2.3 + Math.sin(z * 1.9)) * Math.cos(y * 2.9 + x * 0.6)
          + Math.sin(z * 3.1 + y * 1.4) * 0.45 + Math.sin((x + z) * 5.2) * 0.12;
  if (n > 0.62) return new THREE.Color(P.high);
  if (n > 0.32) return new THREE.Color(P.land);
  if (n > 0.22) return new THREE.Color(P.sand);
  if (n > 0.0)  return new THREE.Color(P.shallow);
  if (n > -0.5) return new THREE.Color(P.ocean);
  return new THREE.Color(P.deep);
}

function rampColor(stops, t) {
  const n = stops.length - 1;
  const f = Math.min(0.9999, Math.max(0, t)) * n;
  const i = Math.floor(f);
  return new THREE.Color(stops[i]).lerp(new THREE.Color(stops[i + 1]), f - i);
}

function makeSprite(softness) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  if (softness === 'haze') {
    grad.addColorStop(0, 'rgba(255,255,255,0.55)');
    grad.addColorStop(0.45, 'rgba(255,255,255,0.16)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
  } else {
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.3, 'rgba(255,255,255,0.82)');
    grad.addColorStop(0.68, 'rgba(255,255,255,0.14)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
  }
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const tex = new THREE.Texture(c);
  tex.needsUpdate = true;
  return tex;
}

function applyPalette(theme) {
  if (!r || !THREE) return;
  const p = PALETTES[theme] || PALETTES.light;
  const blend = p.additive ? THREE.AdditiveBlending : THREE.NormalBlending;
  const planet = mode === 'planet';
  const P = PLANET[theme] || PLANET.light;
  const dk = theme === 'dark';

  const ca = r.geo.attributes.color;
  for (let i = 0; i < r.COUNT; i++) {
    const i3 = i * 3;
    const c = planet
      ? planetColor(P, r.base[i3] / r.R, r.base[i3 + 1] / r.R, r.base[i3 + 2] / r.R)
      : rampColor(p.stops, r.tval[i]);
    ca.array[i3] = c.r; ca.array[i3 + 1] = c.g; ca.array[i3 + 2] = c.b;
  }
  ca.needsUpdate = true;
  r.spin = planet ? 0.16 : 0.045;

  r.atmo.material.uniforms.uColor.value.setHex(dk ? 0x67e8f9 : 0x3b82f6);
  r.atmo.material.uniforms.uOpacity.value = planet ? (dk ? 0.85 : 0.55) : 0.3;
  r.atmo.material.blending = dk ? THREE.AdditiveBlending : THREE.NormalBlending;
  r.atmo.material.needsUpdate = true;

  const add = dk ? THREE.AdditiveBlending : THREE.NormalBlending;
  r.coreHeart.material.color.setHex(dk ? 0xffffff : 0x4f46e5);
  r.coreHalo.material.color.setHex(dk ? 0x67e8f9 : 0x60a5fa);
  r.coreHeart.material.blending = add; r.coreHalo.material.blending = add;
  r.coreHeart.material.needsUpdate = true; r.coreHalo.material.needsUpdate = true;
  r.coreBaseHalo = dk ? 0.6 : 0.42;
  r.coreBaseHeart = dk ? 0.95 : 0.75;

  r.shell.material.color.setHex(planet ? (dk ? 0x7DD3FC : 0x4338CA) : p.shell);
  r.shell.material.opacity = planet ? (dk ? 0.32 : 0.26) : p.shellOpacity * 1.6;
  r.shellGlows.forEach((g) => {
    g.material.color.copy(r.shell.material.color);
    g.material.opacity = (dk ? 0.16 : 0.1) / ((g.userData.k || 0) + 1);
    g.material.blending = add; g.material.needsUpdate = true;
  });

  const stops = dk ? ['#FFFFFF', '#A5F3FC', '#60A5FA', '#A78BFA'] : ['#312E81', '#4F46E5', '#2563EB', '#7C3AED'];
  const sc = r.swGeo.attributes.color.array;
  for (let i = 0; i < r.SW; i++) {
    const c = rampColor(stops, (r.swR[i] - r.swMin) / (r.swMax - r.swMin));
    sc[i * 3] = c.r; sc[i * 3 + 1] = c.g; sc[i * 3 + 2] = c.b;
  }
  r.swGeo.attributes.color.needsUpdate = true;
  r.swirl.material.blending = add; r.swirl.material.needsUpdate = true;
  r.swStops = stops;

  r.clouds.visible = planet;
  r.clouds.material.opacity = dk ? 0.55 : 0.8;
  r.world.rotation.z = planet ? 0.41 : 0;

  Object.assign(r.cloud.material, { opacity: p.pointOpacity, size: p.pointSize, blending: blend });
  if (planet) { r.cloud.material.size = 0.085; r.cloud.material.opacity = 0.95; }
  r.cloud.material.needsUpdate = true;
  r.basePointOpacity = planet ? 0.95 : p.pointOpacity;

  r.haze.material.color.setHex(p.hazeColor);
  Object.assign(r.haze.material, { opacity: p.hazeOpacity, size: p.hazeSize, blending: blend });
  r.haze.material.needsUpdate = true;

  const narrowNow = (canvas.clientWidth || window.innerWidth) < 1024;
  r.nodes.forEach((n, i) => {
    n.material.color.setHex(planet ? 0xE2E8F0 : p.node);
    n.material.opacity = planet ? 0.9 : p.nodeOpacity;
    n.visible = !(planet && (i >= 2 || narrowNow));
    const s = planet ? 1.2 : 1;
    n.scale.set(s, s, s);
  });

  vignette.style.opacity = planet ? '0.35' : '1';
  r.rings.forEach(({ ring }, i) => {
    ring.material.color.setHex(planet ? P.ring[i % 3] : p.ring[i % p.ring.length]);
    ring.material.opacity = planet ? P.ringOpacity : p.ringOpacity;
    ring.material.blending = blend;
    ring.material.needsUpdate = true;
  });
  r.dust.material.color.setHex(p.dust);
  Object.assign(r.dust.material, { opacity: p.dustOpacity, blending: blend });
  r.dust.material.needsUpdate = true;
  r.lights.ambient.intensity = p.ambient;
  r.lights.key.intensity = p.key;
  r.lights.rim.intensity = p.rim;
  r.lights.fill.intensity = p.fill;
  r.pal = p;
}

function initScene() {
  const theme = currentTheme();
  const pal = PALETTES[theme];
  const blend = pal.additive ? THREE.AdditiveBlending : THREE.NormalBlending;

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
  camera.position.set(0, 0, 12.4);

  const world = new THREE.Group();
  world.position.x = -2.6;
  scene.add(world);

  // soft studio lighting
  const ambient = new THREE.AmbientLight(0xffffff, pal.ambient);
  const key = new THREE.DirectionalLight(0xffffff, pal.key);
  key.position.set(4, 6, 8);
  const rim = new THREE.DirectionalLight(0x2563eb, pal.rim);
  rim.position.set(-6, 2, -4);
  const fill = new THREE.DirectionalLight(0x7c3aed, pal.fill);
  fill.position.set(2, -5, 3);
  scene.add(ambient, key, rim, fill);

  const narrow = window.innerWidth < 1024;
  const COUNT = narrow ? 2800 : 5400;
  const R = 3.4;
  const pos = new Float32Array(COUNT * 3);
  const col = new Float32Array(COUNT * 3);
  const base = new Float32Array(COUNT * 3);
  const seed = new Float32Array(COUNT);
  const tval = new Float32Array(COUNT);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < COUNT; i++) {
    const y = 1 - (i / (COUNT - 1)) * 2;
    const rr = Math.sqrt(Math.max(0, 1 - y * y));
    const th = golden * i;
    // layered shells so it reads as a structure, not a solid ball
    const layer = i % 3;
    const j = (layer === 0 ? 0.72 : layer === 1 ? 0.88 : 1) * (0.97 + Math.random() * 0.09);
    pos[i * 3] = base[i * 3] = Math.cos(th) * rr * R * j;
    pos[i * 3 + 1] = base[i * 3 + 1] = y * R * j;
    pos[i * 3 + 2] = base[i * 3 + 2] = Math.sin(th) * rr * R * j;
    seed[i] = Math.random() * Math.PI * 2;
    tval[i] = (y + 1) / 2 * 0.75 + (layer / 3) * 0.25;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const dot = makeSprite('point');
  const hazeTex = makeSprite('haze');

  const cloud = new THREE.Points(geo, new THREE.PointsMaterial({
    size: pal.pointSize, map: dot, vertexColors: true, transparent: true,
    depthWrite: false, blending: blend, opacity: pal.pointOpacity, sizeAttenuation: true,
  }));
  world.add(cloud);

  // restrained glow: large very-faint sprites sharing the same positions
  const haze = new THREE.Points(geo, new THREE.PointsMaterial({
    size: pal.hazeSize, map: hazeTex, color: pal.hazeColor, transparent: true,
    depthWrite: false, blending: blend, opacity: pal.hazeOpacity, sizeAttenuation: true,
  }));
  world.add(haze);

  // small wireframe core, split into two hemispheres
  const shellR = R * 0.3;
  const icoG = new THREE.IcosahedronGeometry(shellR, 2);
  const srcPos = icoG.attributes.position.array;
  const topA = [], botA = [];
  for (let f = 0; f < srcPos.length; f += 9) {
    const cy = srcPos[f + 1] + srcPos[f + 4] + srcPos[f + 7];
    const tri = Array.from(srcPos.subarray(f, f + 9));
    if (cy >= 0) topA.push(...tri); else botA.push(...tri);
  }
  const mkHalf = (arr) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
    return g;
  };
  const shellMat = new THREE.MeshBasicMaterial({ color: pal.shell, wireframe: true, transparent: true, opacity: pal.shellOpacity });
  const shellTop = new THREE.Mesh(mkHalf(topA), shellMat);
  const shellBot = new THREE.Mesh(mkHalf(botA), shellMat);
  const shell = new THREE.Group();
  shell.material = shellMat;
  shell.add(shellTop, shellBot);
  world.add(shell);

  // glowing core: layered wireframe glow + bright heart + halo
  const shellGlows = [];
  [shellTop, shellBot].forEach((half) => {
    [1.035, 1.075].forEach((s, k) => {
      const m = new THREE.Mesh(half.geometry, new THREE.MeshBasicMaterial({
        color: pal.shell, wireframe: true, transparent: true, opacity: 0.08 / (k + 1), depthWrite: false,
      }));
      m.scale.set(s, s, s);
      m.userData.k = k;
      half.add(m);
      shellGlows.push(m);
    });
  });
  const coreHeart = new THREE.Sprite(new THREE.SpriteMaterial({ map: dot, color: 0xffffff, transparent: true, opacity: 0.9, depthWrite: false }));
  coreHeart.scale.set(1.3, 1.3, 1);
  const coreHalo = new THREE.Sprite(new THREE.SpriteMaterial({ map: hazeTex, color: 0x60a5fa, transparent: true, opacity: 0.5, depthWrite: false }));
  coreHalo.scale.set(4.6, 4.6, 1);
  world.add(coreHalo, coreHeart);

  // galactic swirl: spiral arms orbiting + falling into the core
  const SW = narrow ? 700 : 1300;
  const swR = new Float32Array(SW), swA = new Float32Array(SW), swY = new Float32Array(SW);
  const swMin = R * 0.08, swMax = R * 0.62;
  for (let i = 0; i < SW; i++) {
    const rr0 = swMin + Math.pow(Math.random(), 0.7) * (swMax - swMin);
    const arm = (i % 3) * (Math.PI * 2 / 3);
    swR[i] = rr0;
    swA[i] = arm + rr0 * 1.9 + (Math.random() - 0.5) * 0.55;
    swY[i] = (Math.random() - 0.5) * 0.18 * (1 - rr0 / swMax + 0.3);
  }
  const swGeo = new THREE.BufferGeometry();
  swGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(SW * 3), 3));
  swGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(SW * 3), 3));
  const swirl = new THREE.Points(swGeo, new THREE.PointsMaterial({
    size: 0.06, map: dot, vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false,
  }));
  swirl.rotation.x = 0.35;
  world.add(swirl);

  // atmosphere: fresnel rim glow, soft and edge-only
  const atmo = new THREE.Mesh(
    new THREE.SphereGeometry(R * 1.13, 64, 48),
    new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(0x3b82f6) }, uOpacity: { value: 0.5 } },
      vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }',
      fragmentShader: 'uniform vec3 uColor; uniform float uOpacity; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(1.0 - abs(dot(vN, vV)), 2.6); gl_FragColor = vec4(uColor, f * uOpacity); }',
      transparent: true, depthWrite: false,
    })
  );
  world.add(atmo);

  // cloud layer drifting above the surface
  const CL = 1100;
  const cpos = new Float32Array(CL * 3);
  for (let i = 0; i < CL; i++) {
    const u = Math.random() * 2 - 1, a = Math.random() * Math.PI * 2;
    const band = Math.sin(u * 7 + Math.cos(a * 3) * 1.4);
    if (band < 0.15) { i--; continue; }
    const s = Math.sqrt(1 - u * u), rad = R * 1.07;
    cpos[i * 3] = Math.cos(a) * s * rad;
    cpos[i * 3 + 1] = u * rad;
    cpos[i * 3 + 2] = Math.sin(a) * s * rad;
  }
  const cgeo = new THREE.BufferGeometry();
  cgeo.setAttribute('position', new THREE.BufferAttribute(cpos, 3));
  const clouds = new THREE.Points(cgeo, new THREE.PointsMaterial({
    size: 0.11, map: hazeTex, color: 0xffffff, transparent: true, opacity: 0.75,
    depthWrite: false, blending: THREE.NormalBlending,
  }));
  world.add(clouds);

  // a few translucent lit nodes (moons in planet mode)
  const nodes = [];
  const nodeGeo = new THREE.SphereGeometry(0.11, 24, 16);
  for (let i = 0; i < 7; i++) {
    const a = (i / 7) * Math.PI * 2;
    const n = new THREE.Mesh(nodeGeo, new THREE.MeshStandardMaterial({
      color: pal.node, roughness: 0.25, metalness: 0.1, transparent: true, opacity: pal.nodeOpacity,
    }));
    n.position.set(Math.cos(a) * R * 0.94, Math.sin(a * 1.7) * R * 0.5, Math.sin(a) * R * 0.94);
    n.userData.a = a;
    world.add(n);
    nodes.push(n);
  }

  const rings = [];
  [[R * 1.3, 0.22], [R * 1.58, -0.6], [R * 1.86, 1.05]].forEach(([rad, tilt], i) => {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(rad, 0.005, 6, 200),
      new THREE.MeshBasicMaterial({ color: pal.ring[i], transparent: true, opacity: pal.ringOpacity, blending: blend, depthWrite: false })
    );
    ring.rotation.x = Math.PI / 2 + tilt;
    ring.rotation.z = i * 0.7;
    world.add(ring);
    rings.push({ ring, spin: 0.05 + i * 0.035, dir: i % 2 ? -1 : 1 });
  });

  const DUST = 700;
  const dpos = new Float32Array(DUST * 3);
  for (let i = 0; i < DUST; i++) {
    dpos[i * 3] = (Math.random() - 0.5) * 34;
    dpos[i * 3 + 1] = (Math.random() - 0.5) * 20;
    dpos[i * 3 + 2] = (Math.random() - 0.5) * 22 - 4;
  }
  const dgeo = new THREE.BufferGeometry();
  dgeo.setAttribute('position', new THREE.BufferAttribute(dpos, 3));
  const dust = new THREE.Points(dgeo, new THREE.PointsMaterial({
    size: 0.03, map: dot, color: pal.dust, transparent: true, opacity: pal.dustOpacity,
    depthWrite: false, blending: blend,
  }));
  scene.add(dust);

  r = {
    scene, camera, world, cloud, haze, geo, base, seed, tval, shell, nodes, rings, dust, atmo, clouds,
    spinVel: 0, ripples: [], split: 0,
    shellGlows, coreHeart, coreHalo, swirl, swGeo, swR, swA, swY, SW, swMin, swMax, shellR,
    COUNT, R, pal, lights: { ambient, key, rim, fill },
  };
  t0 = performance.now();
  applyPalette(theme);
  pointLabel.textContent = (COUNT + DUST).toLocaleString() + ' live points · hover the core · drag to spin · click to pulse';

  const resize = () => {
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const narrowW = w < 1024;
    world.position.x = narrowW ? 0 : -2.6;
    world.position.y = narrowW ? 3.6 : 0;
    const s = narrowW ? 0.62 : 1;
    world.scale.set(s, s, s);
    applyPalette(currentTheme());
  };
  resize();
  new ResizeObserver(resize).observe(canvas);

  window.addEventListener('pointermove', (e) => {
    const b = canvas.getBoundingClientRect();
    mouse.x = ((e.clientX - b.left) / b.width) * 2 - 1;
    mouse.y = ((e.clientY - b.top) / b.height) * 2 - 1;
    client = { x: e.clientX - b.left, y: e.clientY - b.top, w: b.width, h: b.height };
    pointer.active = true;
    if (drag) {
      const dx = e.clientX - drag.x;
      drag.x = e.clientX;
      r.spinVel += dx * 0.0009;
    }
  }, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { pointer.active = false; mouse.x = 0; mouse.y = 0; drag = null; });
  window.addEventListener('pointerdown', (e) => {
    if (e.target.closest && e.target.closest('input,button,a,label,textarea,[data-nodrag]')) return;
    const b = canvas.getBoundingClientRect();
    const nx = ((e.clientX - b.left) / b.width) * 2 - 1;
    const ny = ((e.clientY - b.top) / b.height) * 2 - 1;
    r.ripples.push({ t0: (performance.now() - t0) / 1000, x: (nx * 2 + 0.9) * r.R, y: -ny * r.R * 1.5 });
    if (r.ripples.length > 4) r.ripples.shift();
    drag = { x: e.clientX };
  });
  window.addEventListener('pointerup', () => { drag = null; });

  // repaint the scene when the theme chip (or anything else) flips .light-mode
  new MutationObserver(() => applyPalette(currentTheme()))
    .observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

  animate();
}

function animate() {
  requestAnimationFrame(animate);
  if (document.hidden) return;
  const t = (performance.now() - t0) / 1000;
  const speed = reduced ? 0 : 1;
  const p = r.pal;

  eased.x += (mouse.x - eased.x) * 0.05;
  eased.y += (mouse.y - eased.y) * 0.05;
  interact += ((pointer.active ? 1 : 0) - interact) * 0.045;

  const arr = r.geo.attributes.position.array;
  const mx = (eased.x * 2 + 0.9) * r.R;
  const my = -eased.y * r.R * 1.5;
  const breathe = 1 + Math.sin(t * 0.42 * speed) * 0.022;
  r.ripples = r.ripples.filter(rp => t - rp.t0 < 3);
  const rips = r.ripples;
  const sv = r.split;
  const pe = sv * sv * (3 - 2 * sv);   // eased hover-the-core amount
  for (let i = 0; i < r.COUNT; i++) {
    const i3 = i * 3;
    const bx = r.base[i3], by = r.base[i3 + 1], bz = r.base[i3 + 2];
    // two crossing waves = organic, weightless deformation
    const wave = Math.sin(t * 0.8 * speed + r.seed[i] + by * 0.55) * 0.06
               + Math.sin(t * 0.33 * speed + bx * 0.4 + bz * 0.3) * 0.035;
    const dx = bx - mx, dy = by - my;
    const push = Math.exp(-(dx * dx + dy * dy) / 3.6) * 0.7 * (0.2 + interact * 0.8);
    let ring = 0;
    for (let q = 0; q < rips.length; q++) {
      const rp = rips[q], age = t - rp.t0;
      const ex = bx - rp.x, ey = by - rp.y;
      const dd = Math.sqrt(ex * ex + ey * ey) - age * 4.2;
      ring += Math.exp(-dd * dd * 1.6) * 0.28 * Math.exp(-age * 1.1);
    }
    const k = breathe + wave + push + ring;
    let px = bx * k, py = by * k, pz = bz * k + push * 0.6;
    // hover the core: particles curve inward and orbit the wireframe
    if (pe > 0.001) {
      const sf = r.seed[i] / 6.2832;
      const e0 = Math.min(1, Math.max(0, pe * 1.7 - sf * 0.7));   // staggered, so they flow in waves
      const ei = e0 * e0 * (3 - 2 * e0);
      if (ei > 0) {
        const len = Math.sqrt(px * px + py * py + pz * pz) || 1;
        const orbitR = r.shellR * (1.35 + sf * 1.5);
        const phi = ei * (2.4 + sf * 2.0) + t * (0.9 - sf * 0.4) * ei;
        const c = Math.cos(phi), s = Math.sin(phi);
        const nx = px / len * orbitR, ny = py / len * orbitR * 0.55, nz = pz / len * orbitR;
        const rx = nx * c - nz * s, rz = nx * s + nz * c;
        px += (rx - px) * ei;
        py += (ny - py) * ei;
        pz += (rz - pz) * ei;
      }
    }
    arr[i3] = px; arr[i3 + 1] = py; arr[i3 + 2] = pz;
  }
  r.geo.attributes.position.needsUpdate = true;

  // glow strengthens only while interacting — restrained at rest
  r.haze.material.opacity = p.hazeOpacity * (1 + interact * 1.6);
  r.cloud.material.opacity = Math.min(1, r.basePointOpacity * (0.92 + interact * 0.12));

  const dt = Math.min(0.05, t - (lastT ?? t));
  lastT = t;
  r.rotY = (r.rotY || 0) + dt * r.spin * speed + r.spinVel;
  r.spinVel *= 0.94;
  r.clouds.rotation.y += dt * 0.07 * speed + r.spinVel * 0.3;
  r.world.rotation.y = r.rotY + eased.x * 0.42;
  r.world.rotation.x = eased.y * 0.28;

  // hover-the-core detection: project the core to screen space
  let hoverCore = false;
  if (client && pointer.active) {
    const v = tmpV || (tmpV = new THREE.Vector3());
    v.set(0, 0, 0);
    r.world.localToWorld(v);
    v.project(r.camera);
    const sx = (v.x + 1) / 2 * client.w, sy = (1 - v.y) / 2 * client.h;
    hoverCore = Math.hypot(client.x - sx, client.y - sy) < Math.min(client.w, client.h) * 0.12;
  }
  if (hoverCore !== hoverCoreState) {
    hoverCoreState = hoverCore;
    document.body.style.cursor = hoverCore ? 'pointer' : '';
  }
  r.split += ((hoverCore ? 1 : 0) - r.split) * 0.055;

  r.shell.rotation.y = -t * 0.22 * speed;
  r.shell.rotation.x = t * 0.11 * speed;
  const sp = 1 + Math.sin(t * 0.9) * 0.03 + interact * 0.05;
  r.shell.scale.set(sp, sp, sp);

  // core heartbeat — brightens while interacting or after a click pulse
  const kick = rips.length ? Math.exp(-(t - rips[rips.length - 1].t0) * 2.2) : 0;
  const beat = 0.5 + 0.5 * Math.sin(t * 1.6);
  r.coreHalo.material.opacity = Math.min(1, r.coreBaseHalo * (0.8 + beat * 0.3 + interact * 0.5 + kick * 0.8));
  r.coreHeart.material.opacity = Math.min(1, r.coreBaseHeart * (0.85 + beat * 0.15 + kick * 0.3));
  const hs = 4.6 * (1 + beat * 0.08 + kick * 0.35);
  r.coreHalo.scale.set(hs, hs, 1);
  const cs = 1.3 * (1 + kick * 0.5);
  r.coreHeart.scale.set(cs, cs, 1);

  // spiral inflow: Keplerian-ish orbit, slow fall toward the heart, respawn at the rim
  const sp3 = r.swGeo.attributes.position.array;
  const sc3 = r.swGeo.attributes.color.array;
  const pull = (0.05 + interact * 0.08 + kick * 0.5) * speed;
  for (let i = 0; i < r.SW; i++) {
    let rr = r.swR[i];
    r.swA[i] += dt * speed * (0.55 / (rr * 0.45 + 0.25)) * (1 + kick * 1.5);
    rr -= dt * pull * (0.6 + rr * 0.3);
    if (rr < r.swMin) {
      rr = r.swMax * (0.85 + Math.random() * 0.15);
      r.swA[i] = (i % 3) * (Math.PI * 2 / 3) + rr * 1.9 + (Math.random() - 0.5) * 0.55;
      const c = rampColor(r.swStops, 1);
      sc3[i * 3] = c.r; sc3[i * 3 + 1] = c.g; sc3[i * 3 + 2] = c.b;
    } else if ((i + Math.floor(t * 4)) % 25 === 0) {
      const c = rampColor(r.swStops, (rr - r.swMin) / (r.swMax - r.swMin));
      sc3[i * 3] = c.r; sc3[i * 3 + 1] = c.g; sc3[i * 3 + 2] = c.b;
    }
    r.swR[i] = rr;
    const a = r.swA[i];
    sp3[i * 3] = Math.cos(a) * rr;
    sp3[i * 3 + 1] = r.swY[i];
    sp3[i * 3 + 2] = Math.sin(a) * rr;
  }
  r.swGeo.attributes.position.needsUpdate = true;
  r.swGeo.attributes.color.needsUpdate = true;
  r.swirl.rotation.y = -r.rotY * 0.5;

  r.nodes.forEach((n, i) => {
    const a = n.userData.a + t * 0.09 * speed * (i % 2 ? 1 : -1);
    const rad = r.R * (0.9 + Math.sin(t * 0.5 + i) * 0.05);
    n.position.set(Math.cos(a) * rad, Math.sin(a * 1.7) * r.R * 0.5, Math.sin(a) * rad);
  });
  r.rings.forEach(({ ring, spin, dir }) => { ring.rotation.z += 0.075 * spin * dir * (speed || 0.0001); });
  r.dust.rotation.y = t * 0.01 * speed;
  r.dust.position.x = -eased.x * 0.8;
  r.dust.position.y = eased.y * 0.6;

  r.camera.position.x = eased.x * 0.7;
  r.camera.position.y = -eased.y * 0.5;
  r.camera.lookAt(r.world.position.x * 0.35, r.world.position.y * 0.15, 0);

  renderer.render(r.scene, r.camera);
}

modeBtn.addEventListener('click', () => {
  mode = mode === 'planet' ? 'field' : 'planet';
  try { localStorage.setItem(MODE_KEY, mode); } catch (e) {}
  syncModeLabel();
  applyPalette(currentTheme());
});

try {
  THREE = await import('https://unpkg.com/three@0.184.0/build/three.module.js');
  if (!THREE || !THREE.WebGLRenderer) throw new Error('three module missing WebGLRenderer');
  initScene();
} catch (e) {
  console.warn('3D field unavailable, ambient fallback active:', e);
  pointLabel.textContent = 'ambient field · offline mode';
}
