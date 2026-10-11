import * as THREE from 'three'

/**
 * The astrolabe: a night-sky portal framed by bronze rings, drawn with three.js.
 *
 * - 'portal' (Home): four gimbal rings, the Greek-letter ring and drifting star dust. Every few
 *   seconds a random ring or letter brightens and fades.
 * - 'oracle' (AI moments): the same portal in miniature. It speeds up and draws dust inward while
 *   the AI works ('thinking'), then settles ('done').
 *
 * Colours come from the CSS variables on `paletteEl`, so it follows the gold or indigo look.
 * It only renders while on screen, pauses in background tabs and asks for the low-power GPU,
 * leaving the discrete GPU to a local model.
 */

export type OracleMode = 'idle' | 'thinking' | 'done'

export interface AstrolabeOptions {
  mode: 'portal' | 'oracle'
  paletteEl: HTMLElement
  initialMode?: OracleMode
  onCoreHover?: (over: boolean) => void
  onPointer?: (x: number, y: number, width: number) => void
  onCoreClick?: () => void
}

export interface AstrolabeHandle {
  setMode: (mode: OracleMode) => void
  destroy: () => void
}

interface Palette {
  metal: string
  metalHi: string
  rete: string
  dust: string
  sky: string
  neb1: string
  neb2: string
  star: string
}

function readPalette(el: HTMLElement): Palette {
  const cs = getComputedStyle(el)
  const get = (name: string) => cs.getPropertyValue(name).trim()
  return {
    metal: get('--metal'), metalHi: get('--metal-hi'), rete: get('--rete'), dust: get('--dust'),
    sky: get('--sky'), neb1: get('--neb-1'), neb2: get('--neb-2'), star: get('--star'),
  }
}

/** Raw sRGB triplet for shader uniforms, which write their output without colour conversion. */
function rawRgb(hex: string) {
  const n = parseInt(hex.replace('#', ''), 16)
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255)
}

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const VS_UV = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

const FS_PORTAL = /* glsl */ `
uniform float uTime;
uniform float uIntensity;
uniform float uStarScale;
uniform vec2 uMouse;
uniform vec3 uSky;
uniform vec3 uNeb1;
uniform vec3 uNeb2;
uniform vec3 uStar;
varying vec2 vUv;
float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p);
  float a = hash(i); float b = hash(i + vec2(1.0, 0.0)); float c = hash(i + vec2(0.0, 1.0)); float d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0; float a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return v;
}
vec2 rot(vec2 p, float a) { float c = cos(a); float s = sin(a); return vec2(c * p.x - s * p.y, s * p.x + c * p.y); }
float stars(vec2 p, float scale, float thresh, float t) {
  vec2 g = p * scale * uStarScale; vec2 id = floor(g); vec2 f = fract(g) - 0.5;
  float h = hash(id);
  vec2 o = vec2(hash(id + 3.1), hash(id + 7.7)) - 0.5;
  float d = length(f - o * 0.6);
  float s = (1.0 - smoothstep(0.0, 0.08, d)) * step(thresh, h);
  return s * (0.55 + 0.45 * sin(t * 1.7 + h * 50.0));
}
void main() {
  vec2 p = vUv * 2.0 - 1.0;
  float r = length(p);
  float t = uTime;
  float swirl = t * (0.03 + 0.10 * uIntensity) + (1.0 - r) * (0.6 + 0.9 * uIntensity);
  vec2 q = rot(p, swirl) + uMouse * 0.12 * (1.0 - r);
  float n1 = fbm(q * 1.8 + vec2(t * 0.02, -t * 0.015));
  float n2 = fbm(rot(q, 1.3) * 2.6 - vec2(t * 0.03, 0.0));
  vec3 col = uSky;
  col = mix(col, uNeb1, smoothstep(0.45, 0.95, n1) * 0.85);
  col += uNeb2 * smoothstep(0.5, 1.0, n2) * 0.9;
  vec2 sp = rot(p, t * 0.01);
  float st = stars(sp + uMouse * 0.02, 9.0, 0.80, t);
  st += stars(rot(sp, 0.7) + uMouse * 0.05, 16.0, 0.84, t * 1.3) * 0.8;
  st += stars(rot(sp, 2.1) + uMouse * 0.09, 28.0, 0.88, t * 1.6) * 0.6;
  col += uStar * st;
  float core = exp(-r * r * 5.5);
  col += mix(uNeb1, uStar, 0.35) * core * (0.25 + 0.55 * uIntensity);
  col *= mix(1.0, 0.45, smoothstep(0.55, 1.0, r));
  col += uStar * smoothstep(0.86, 1.0, r) * (0.10 + 0.25 * uIntensity);
  float alpha = 1.0 - smoothstep(0.985, 1.0, r);
  gl_FragColor = vec4(col, alpha);
}`

// The Greek ring: the texture is a white mask, and each of the 24 letters can glow on its own.
const FS_RETE = /* glsl */ `
uniform sampler2D uMap;
uniform float uLetter[24];
uniform vec3 uBase;
uniform vec3 uHot;
varying vec2 vUv;
const float TAU = 6.28318530718;
void main() {
  float m = texture2D(uMap, vUv).a;
  vec2 p = vUv * 2.0 - 1.0;
  float r = length(p);
  float a = atan(p.x, p.y);
  if (a < 0.0) a += TAU;
  float g = 0.0;
  for (int i = 0; i < 24; i++) {
    float d = abs(a - float(i) * TAU / 24.0);
    d = min(d, TAU - d);
    g += uLetter[i] * exp(-(d * d) / 0.0056);
  }
  g *= smoothstep(0.885, 0.905, r) * (1.0 - smoothstep(0.97, 0.984, r));
  g = clamp(g, 0.0, 1.0);
  float h = 0.0;
  for (int k = 0; k < 8; k++) {
    float an = float(k) * TAU / 8.0;
    vec2 o = vec2(cos(an), sin(an));
    h += texture2D(uMap, vUv + o * 0.005).a + 0.6 * texture2D(uMap, vUv + o * 0.011).a;
  }
  h = h / 12.8 * g;
  vec3 glyph = mix(uBase, uHot, g);
  float ha = h * 0.8 * (1.0 - m);
  float outA = m + ha;
  vec3 outC = (glyph * m + uHot * ha) / max(outA, 0.0001);
  gl_FragColor = vec4(outC, clamp(outA, 0.0, 1.0));
}`

const VS_DUST = /* glsl */ `
attribute float aSize;
attribute float aSeed;
uniform float uTime;
uniform float uPR;
uniform float uScale;
varying float vA;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uPR * uScale * (10.0 / -mv.z);
  vA = 0.35 + 0.65 * abs(sin(uTime * 0.7 + aSeed * 6.2831));
}`

const FS_DUST = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
varying float vA;
void main() {
  float d = length(gl_PointCoord - 0.5);
  float a = 1.0 - smoothstep(0.0, 0.5, d);
  gl_FragColor = vec4(uColor, a * a * vA * uOpacity);
}`

/** A soft studio environment so the metal rings have something to reflect. */
function makeEnvironment(renderer: THREE.WebGLRenderer) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 256
  const x = c.getContext('2d')!
  const g = x.createLinearGradient(0, 0, 0, 256)
  g.addColorStop(0, '#4a4a52')
  g.addColorStop(0.45, '#1a1b20')
  g.addColorStop(1, '#050506')
  x.fillStyle = g
  x.fillRect(0, 0, 512, 256)
  const blob = (cx: number, cy: number, r: number, a: number) => {
    const rg = x.createRadialGradient(cx, cy, 0, cx, cy, r)
    rg.addColorStop(0, `rgba(255,255,255,${a})`)
    rg.addColorStop(1, 'rgba(255,255,255,0)')
    x.fillStyle = rg
    x.fillRect(cx - r, cy - r, r * 2, r * 2)
  }
  blob(120, 70, 60, 1)
  blob(300, 60, 80, 0.9)
  blob(430, 110, 50, 0.8)
  blob(220, 150, 40, 0.35)
  const tex = new THREE.CanvasTexture(c)
  tex.mapping = THREE.EquirectangularReflectionMapping
  tex.colorSpace = THREE.SRGBColorSpace
  const pmrem = new THREE.PMREMGenerator(renderer)
  const target = pmrem.fromEquirectangular(tex)
  tex.dispose()
  pmrem.dispose()
  return target
}

/** The inner ring's tick marks and the 24 Greek letters, as a white mask. */
async function reteTexture() {
  try {
    await Promise.race([document.fonts.load('400 40px "GFS Didot"', 'ΑΒΓΩ'), new Promise((r) => setTimeout(r, 1500))])
  } catch {
    // Falls back to a system serif.
  }
  const S = 1024
  const C = S / 2
  const c = document.createElement('canvas')
  c.width = c.height = S
  const x = c.getContext('2d')!
  const Ro = C * 0.99
  const Ri = C * (2.14 / 2.56)
  x.translate(C, C)
  x.strokeStyle = '#ffffff'
  x.fillStyle = '#ffffff'
  const ring = (r: number, w: number) => {
    x.lineWidth = w
    x.beginPath()
    x.arc(0, 0, r, 0, Math.PI * 2)
    x.stroke()
  }
  ring(Ro - 2, 3)
  ring(Ri + 2, 3)
  const trackR = Ri + (Ro - Ri) * 0.3
  ring(trackR, 1.6)
  for (let i = 0; i < 120; i++) {
    const a = (i / 120) * Math.PI * 2
    const L = (trackR - Ri) * (i % 10 === 0 ? 0.85 : i % 5 === 0 ? 0.6 : 0.35)
    x.lineWidth = i % 5 === 0 ? 2.2 : 1.3
    x.beginPath()
    x.moveTo(Math.cos(a) * (Ri + 2), Math.sin(a) * (Ri + 2))
    x.lineTo(Math.cos(a) * (Ri + 2 + L), Math.sin(a) * (Ri + 2 + L))
    x.stroke()
  }
  const letters = 'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'
  const rL = trackR + (Ro - trackR) * 0.5
  x.font = `400 ${Math.round((Ro - trackR) * 0.62)}px "GFS Didot", Didot, Georgia, serif`
  x.textAlign = 'center'
  x.textBaseline = 'middle'
  for (let i = 0; i < 24; i++) {
    const a = (i / 24) * Math.PI * 2
    x.save()
    x.rotate(a)
    x.fillText(letters[i], 0, -rL)
    x.restore()
    const b = a + Math.PI / 24
    x.beginPath()
    x.arc(Math.sin(b) * rL, -Math.cos(b) * rL, 2.4, 0, Math.PI * 2)
    x.fill()
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.NoColorSpace
  tex.anisotropy = 4
  return tex
}

interface Gimbal {
  pivot: THREE.Group
  spin: THREE.Group
  mat: THREE.MeshStandardMaterial
  beadMat: THREE.MeshStandardMaterial | null
  speed: number
  tilt: [number, number]
  phase: number
  flare: number
}

interface Flare {
  ring?: number
  letter?: number
  start: number
  dur: number
  peak: number
}

const ORACLE: Record<OracleMode, { i: number; spin: number; flow: number }> = {
  idle: { i: 0.3, spin: 0.4, flow: 0 },
  thinking: { i: 1, spin: 2.8, flow: 1 },
  done: { i: 0.5, spin: 0.5, flow: 0 },
}

export async function createAstrolabe(canvas: HTMLCanvasElement, o: AstrolabeOptions): Promise<AstrolabeHandle> {
  const portal = o.mode === 'portal'
  const P = readPalette(o.paletteEl)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.15
  renderer.setClearColor(0x000000, 0)

  const disposables: { dispose: () => void }[] = []
  const keep = <T extends { dispose: () => void }>(x: T): T => {
    disposables.push(x)
    return x
  }
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100)
  const envTarget = makeEnvironment(renderer)
  scene.environment = envTarget.texture
  const key = new THREE.DirectionalLight(0xffffff, 1.6)
  key.position.set(-3, 4, 6)
  scene.add(key, new THREE.AmbientLight(0xffffff, 0.15))

  const rig = new THREE.Group()
  scene.add(rig)
  const metal = keep(new THREE.MeshStandardMaterial({ color: P.metal, metalness: 1, roughness: 0.3 }))
  const metalHi = keep(new THREE.MeshStandardMaterial({ color: P.metalHi, metalness: 1, roughness: 0.2 }))

  const diskR = portal ? 1.94 : 1.0
  rig.add(new THREE.Mesh(keep(new THREE.TorusGeometry(diskR + 0.05, 0.075, 32, 220)), metal))
  rig.add(new THREE.Mesh(keep(new THREE.TorusGeometry(diskR - 0.015, 0.012, 8, 220)), metalHi))
  const diskU = {
    uTime: { value: 0 },
    uIntensity: { value: 0.45 },
    uStarScale: { value: portal ? 1 : 0.55 },
    uMouse: { value: new THREE.Vector2() },
    uSky: { value: rawRgb(P.sky) },
    uNeb1: { value: rawRgb(P.neb1) },
    uNeb2: { value: rawRgb(P.neb2) },
    uStar: { value: rawRgb(P.star) },
  }
  const disk = new THREE.Mesh(
    keep(new THREE.CircleGeometry(diskR, 96)),
    keep(new THREE.ShaderMaterial({ uniforms: diskU, vertexShader: VS_UV, fragmentShader: FS_PORTAL, transparent: true, depthWrite: false })),
  )
  rig.add(disk)

  let rete: THREE.Mesh | null = null
  const letterGlow = new Float32Array(24)
  if (portal) {
    const reteU = {
      uMap: { value: keep(await reteTexture()) },
      uLetter: { value: letterGlow },
      uBase: { value: rawRgb(P.rete).multiplyScalar(0.85) },
      uHot: { value: rawRgb(P.star).lerp(new THREE.Vector3(1, 1, 1), 0.35) },
    }
    rete = new THREE.Mesh(
      keep(new THREE.RingGeometry(2.14, 2.56, 160, 1)),
      keep(new THREE.ShaderMaterial({ uniforms: reteU, vertexShader: VS_UV, fragmentShader: FS_RETE, transparent: true, depthWrite: false, side: THREE.DoubleSide })),
    )
    rete.position.z = -0.02
    rig.add(rete)
  }

  const radii = portal ? [2.78, 3.0, 3.22, 3.44] : [1.3, 1.48]
  const tilts: [number, number][] = portal ? [[1.18, 0.28], [-0.92, 0.7], [0.4, 1.22], [1.42, -0.6]] : [[1.1, 0.3], [-0.8, 0.9]]
  const speeds = portal ? [0.16, -0.12, 0.1, -0.08] : [0.5, -0.4]
  const gimbals: Gimbal[] = radii.map((R, i) => {
    const pivot = new THREE.Group()
    pivot.rotation.set(tilts[i][0], tilts[i][1], 0)
    const spin = new THREE.Group()
    spin.rotation.z = i * 1.3
    pivot.add(spin)
    const mat = keep(new THREE.MeshStandardMaterial({ color: P.metal, metalness: 1, roughness: 0.38, emissive: new THREE.Color(P.metalHi), emissiveIntensity: 0 }))
    spin.add(new THREE.Mesh(keep(new THREE.TorusGeometry(R, portal ? 0.02 : 0.022, 10, 240)), mat))
    let beadMat: THREE.MeshStandardMaterial | null = null
    if (portal) {
      beadMat = keep(new THREE.MeshStandardMaterial({ color: P.metalHi, emissive: new THREE.Color(P.star), emissiveIntensity: 0.35, metalness: 0.3, roughness: 0.4 }))
      const bead = new THREE.Mesh(keep(new THREE.SphereGeometry(0.085, 20, 16)), beadMat)
      bead.position.set(R, 0, 0)
      spin.add(bead)
    }
    rig.add(pivot)
    return { pivot, spin, mat, beadMat, speed: speeds[i], tilt: tilts[i], phase: i * 1.7, flare: 0 }
  })

  // Dust around the portal; flowing motes around the oracle.
  const N = portal ? 170 : 110
  const rnd = mulberry32(portal ? 11 : 23)
  const pos = new Float32Array(N * 3)
  const base = new Float32Array(N * 3)
  const seed = new Float32Array(N)
  const size = new Float32Array(N)
  const baseA = new Float32Array(N)
  const baseR = new Float32Array(N)
  for (let i = 0; i < N; i++) {
    const a = rnd() * Math.PI * 2
    const r = portal ? 2.3 + rnd() * 1.9 : 1.15 + rnd() * 0.55
    baseA[i] = a
    baseR[i] = r
    base[i * 3] = Math.cos(a) * r
    base[i * 3 + 1] = Math.sin(a) * r * 0.9
    base[i * 3 + 2] = (rnd() - 0.5) * (portal ? 1.6 : 0.5)
    seed[i] = rnd()
    size[i] = portal ? 1 + rnd() * 2.2 : 0.9 + rnd() * 1.3
  }
  pos.set(base)
  const dustGeo = keep(new THREE.BufferGeometry())
  dustGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  dustGeo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
  dustGeo.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  const dustU = {
    uTime: { value: 0 },
    uPR: { value: renderer.getPixelRatio() },
    uScale: { value: 1 },
    uColor: { value: rawRgb(P.dust) },
    uOpacity: { value: 0.9 },
  }
  scene.add(new THREE.Points(dustGeo, keep(new THREE.ShaderMaterial({
    uniforms: dustU, vertexShader: VS_DUST, fragmentShader: FS_DUST, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }))))

  const S = {
    t: 0,
    mouse: new THREE.Vector2(),
    mouseT: new THREE.Vector2(),
    inside: false,
    attract: 0,
    core: false,
    intensity: portal ? 0.45 : 0.5,
    spinMul: 1,
    flow: 0,
    flowPhase: 0,
    orbit: 0,
    pulse: 0,
    mode: o.initialMode ?? ('idle' as OracleMode),
  }
  const mw = new THREE.Vector3()

  // Random but smooth flares: a ring or a Greek letter brightens and fades on its own schedule.
  const flares: Flare[] = []
  let nextRing = 0.6
  let nextLetter = 0.2
  const envelope = (f: Flare) => {
    const x = (S.t - f.start) / f.dur
    return x <= 0 || x >= 1 ? 0 : f.peak * Math.sin(Math.PI * x) ** 2
  }
  function tickFlares() {
    if (S.t >= nextRing) {
      flares.push({ ring: Math.floor(Math.random() * gimbals.length), start: S.t, dur: 2.6 + Math.random() * 2.4, peak: 0.6 + Math.random() * 0.4 })
      nextRing = S.t + 1.2 + Math.random() * 2.6
    }
    if (S.t >= nextLetter) {
      flares.push({ letter: Math.floor(Math.random() * 24), start: S.t, dur: 1.8 + Math.random() * 2.4, peak: 0.55 + Math.random() * 0.45 })
      nextLetter = S.t + 0.3 + Math.random() * 0.9
    }
    for (let i = flares.length - 1; i >= 0; i--) if (S.t > flares[i].start + flares[i].dur) flares.splice(i, 1)
    gimbals.forEach((g) => { g.flare = 0 })
    letterGlow.fill(0)
    for (const f of flares) {
      const e = envelope(f)
      if (f.ring !== undefined) gimbals[f.ring].flare = Math.max(gimbals[f.ring].flare, e)
      else if (f.letter !== undefined) letterGlow[f.letter] = Math.max(letterGlow[f.letter], e)
    }
  }

  function update(dt: number, settle: boolean) {
    if (!settle) S.t += dt
    const k = settle ? 1 : 1 - Math.pow(0.02, dt)
    S.mouse.lerp(S.mouseT, settle ? 1 : 1 - Math.pow(0.002, dt))
    // Cursor parallax (tilts the astrolabe toward the pointer), switched off for now:
    // rig.rotation.y = S.mouse.x * 0.22
    // rig.rotation.x = -S.mouse.y * 0.16
    const target = portal ? { i: 0.45 + (S.core ? 0.35 : 0), spin: 1, flow: 0 } : ORACLE[S.mode]
    S.intensity += (target.i - S.intensity) * k
    S.spinMul += (target.spin - S.spinMul) * k
    S.flow += (target.flow - S.flow) * k
    S.attract += ((S.inside ? 1 : 0) - S.attract) * k
    S.pulse *= settle ? 0 : Math.pow(0.08, dt)
    diskU.uTime.value = S.t
    diskU.uIntensity.value = S.intensity + S.pulse
    // Shifts the stars inside the portal with the pointer, switched off for now:
    // diskU.uMouse.value.copy(S.mouse)
    dustU.uTime.value = S.t
    if (rete) rete.rotation.z = -S.t * 0.02
    if (portal && !settle) tickFlares()
    gimbals.forEach((g, i) => {
      if (!settle) g.spin.rotation.z += g.speed * dt * S.spinMul
      g.pivot.rotation.x = g.tilt[0] + Math.sin(S.t * 0.15 + g.phase) * 0.08
      g.pivot.rotation.y = g.tilt[1] + S.t * 0.03 * (i % 2 ? -1 : 1)
      g.mat.emissiveIntensity = g.flare * 0.3
      if (g.beadMat) g.beadMat.emissiveIntensity = 0.35 + g.flare * 0.7
    })
    if (!settle) {
      S.flowPhase += dt * 0.35 * S.flow
      S.orbit += dt * (0.12 + 1.1 * S.flow)
    }
    for (let i = 0; i < N; i++) {
      let x: number
      let y: number
      if (portal) {
        const a = S.t * 0.02 * (0.5 + seed[i])
        const bx = base[i * 3]
        const by = base[i * 3 + 1]
        x = bx * Math.cos(a) - by * Math.sin(a)
        y = bx * Math.sin(a) + by * Math.cos(a)
        // Pulls nearby star dust toward the pointer, switched off for now:
        // if (S.attract > 0.01) {
        //   const dx = mw.x - x
        //   const dy = mw.y - y
        //   const f = S.attract * 0.55 * Math.exp(-(dx * dx + dy * dy) / 1.4)
        //   x += dx * f
        //   y += dy * f
        // }
      } else {
        const ph = (seed[i] + S.flowPhase) % 1
        const r = baseR[i] - ph * 0.85 * S.flow
        const a = baseA[i] + S.orbit * (0.6 + seed[i] * 0.8)
        x = Math.cos(a) * r
        y = Math.sin(a) * r
      }
      pos[i * 3] = x
      pos[i * 3 + 1] = y
    }
    dustGeo.attributes.position.needsUpdate = true
    if (!portal) dustU.uOpacity.value = 0.35 + S.flow * 0.65
  }

  let raf = 0
  let last = 0
  let visible = false
  const render = () => renderer.render(scene, camera)
  const renderOnce = () => {
    update(0, true)
    render()
  }
  const schedule = () => {
    if (!raf && visible && !document.hidden && !reduced) raf = requestAnimationFrame(frame)
  }
  function frame(now: number) {
    raf = 0
    const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016)
    last = now
    update(dt, false)
    render()
    schedule()
  }
  const poke = () => (reduced ? renderOnce() : schedule())

  function resize() {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    if (!w || !h) return
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    const rMax = portal ? 3.62 : 1.6
    const tanH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
    camera.position.set(0, 0, Math.max((rMax * 1.04) / tanH, (rMax * 1.04) / (tanH * camera.aspect)))
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
    dustU.uScale.value = h / 320
    dustU.uPR.value = renderer.getPixelRatio()
    if (!raf) renderOnce()
  }
  const ro = new ResizeObserver(resize)
  ro.observe(canvas)
  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting
    last = 0
    if (visible) schedule()
  }, { rootMargin: '120px' })
  io.observe(canvas)
  const onVisibility = () => {
    last = 0
    schedule()
  }
  document.addEventListener('visibilitychange', onVisibility)

  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0)
  function onMove(e: PointerEvent) {
    const r = canvas.getBoundingClientRect()
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1))
    S.mouseT.copy(ndc)
    S.inside = true
    ray.setFromCamera(ndc, camera)
    ray.ray.intersectPlane(plane, mw)
    if (portal) {
      scene.updateMatrixWorld()
      const core = ray.intersectObject(disk, false).length > 0
      if (core !== S.core) {
        S.core = core
        canvas.style.cursor = core ? 'pointer' : 'default'
        o.onCoreHover?.(core)
      }
      o.onPointer?.(e.clientX - r.left, e.clientY - r.top, r.width)
    }
    poke()
  }
  function onLeave() {
    S.inside = false
    S.mouseT.set(0, 0)
    S.core = false
    canvas.style.cursor = 'default'
    o.onCoreHover?.(false)
    poke()
  }
  function onClick() {
    if (S.core) o.onCoreClick?.()
  }
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerdown', onMove)
  canvas.addEventListener('pointerleave', onLeave)
  canvas.addEventListener('click', onClick)
  resize()

  return {
    setMode(mode) {
      if (mode === 'done' && S.mode === 'thinking') S.pulse = 0.9
      S.mode = mode
      poke()
    },
    destroy() {
      cancelAnimationFrame(raf)
      raf = 0
      ro.disconnect()
      io.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerdown', onMove)
      canvas.removeEventListener('pointerleave', onLeave)
      canvas.removeEventListener('click', onClick)
      disposables.forEach((d) => d.dispose())
      envTarget.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
    },
  }
}
