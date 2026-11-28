/* PubCast Energy Sphere avatar renderer.
 *
 * The floating-head avatar of woven light from the owner's October 2025 design:
 *   base glow (brightest at the centre), woven threads wrapping the sphere like
 *   thread on a spool and always flowing, a face (eyes, mouth, eyebrows) in denser
 *   brighter thread that keeps the core colour, and a spinning, scribbly mood ring.
 *   It floats, casts light on the floor below, and turns as a true sphere.
 *
 * One WebGL2 full-screen pass per canvas; no libraries. Any page can mount it:
 *   const av = PubCastEnergySphere.create(canvas, {core, ring, mood, energy, mode});
 *   av.set({mood: 'excited', talking: true});   av.destroy();
 * Modes are the Foundry's hologram modes: 'energy' | 'ghost' | 'solid'.
 */
(function () {
  'use strict';

  const FRAGMENT = `#version 300 es
precision highp float;
out vec4 outColor;

uniform vec2  uRes;
uniform float uTime;       // seconds, scaled by energy for flow
uniform float uClock;      // real seconds
uniform vec3  uCore;       // core colour: woven texture + face (never changes with mood)
uniform vec3  uRing;       // mood ring colour
uniform float uEnergy;     // 0..2
uniform mat3  uHead;       // world -> head (object) rotation
uniform float uBob;        // float height offset
uniform vec4  uFace;       // smile curvature, mouth open, brow raise, brow tilt
uniform float uEyeOpen;    // 0 closed .. 1 open (blink, surprise > 1)
uniform vec3  uBg;        // page colour behind the avatar
uniform float uMode;      // 0 energy, 1 ghost, 2 solid (hologram mode)
uniform float uLift;      // moves the head up the frame
uniform float uZoom;      // camera distance
uniform float uFloor;     // 0..1 glow cast on the floor below
uniform vec4  uFace2;     // eye arc (closed happy eyes), eye chevron (mischief), tear, unused

// ---------- noise ----------
vec3 hash3(float n) { return fract(sin(vec3(n, n + 1.3, n + 2.7)) * vec3(43758.5453, 22578.1459, 19642.3490)); }
float hash1(float n) { return fract(sin(n) * 43758.5453); }
vec3 g3(vec3 p) {
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)), dot(p, vec3(269.5, 183.3, 246.1)), dot(p, vec3(113.5, 271.9, 124.6)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float noise(vec3 p) {               // gradient noise, -1..1
  vec3 i = floor(p), f = fract(p), u = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(dot(g3(i), f), dot(g3(i + vec3(1,0,0)), f - vec3(1,0,0)), u.x),
                 mix(dot(g3(i + vec3(0,1,0)), f - vec3(0,1,0)), dot(g3(i + vec3(1,1,0)), f - vec3(1,1,0)), u.x), u.y),
             mix(mix(dot(g3(i + vec3(0,0,1)), f - vec3(0,0,1)), dot(g3(i + vec3(1,0,1)), f - vec3(1,0,1)), u.x),
                 mix(dot(g3(i + vec3(0,1,1)), f - vec3(0,1,1)), dot(g3(i + vec3(1,1,1)), f - vec3(1,1,1)), u.x), u.y), u.z);
}

// Thin anti-aliased line where coordinate v crosses an integer. px widens/narrows the hair.
float hair(float v, float px) {
  float d = abs(fract(v + 0.5) - 0.5);
  float w = max(fwidth(v), 1e-4);
  return 1.0 - smoothstep(0.0, px * w, d);
}

// Woven light: many families of threads, each wrapping the sphere like thread on a spool
// around its own slowly-turning axis, warped by flowing noise and broken into lengths.
float weave(vec3 q, float density, float px, float t, float seed) {
  float sum = 0.0;
  for (int k = 0; k < 9; k++) {
    float fk = float(k) + seed;
    vec3 a = normalize(hash3(fk * 7.13) * 2.0 - 1.0);
    vec3 b = normalize(cross(a, vec3(0.31, 0.83, 0.47)));
    float ang = t * (0.05 + 0.06 * hash1(fk * 3.1)) * (hash1(fk) > 0.5 ? 1.0 : -1.0);
    vec3 axis = normalize(a * cos(ang) + b * sin(ang));
    float s = dot(q, axis);
    s += 0.075 * noise(q * 2.3 + vec3(fk * 4.7, t * 0.22, -t * 0.17));
    s += 0.02 * noise(q * 7.0 + vec3(t * 0.3, fk, 0.0));
    float v = s * density * (0.8 + 0.4 * hash1(fk * 9.7));
    float id = floor(v + 0.5);
    float bright = 0.35 + 0.65 * hash1(id * 1.37 + fk * 11.0);
    float brk = smoothstep(-0.15, 0.35, noise(q * 3.4 + vec3(id * 0.37, fk * 2.0, t * 0.35)));
    sum += hair(v, px) * bright * brk;
  }
  return sum;
}

// distance to a quadratic curve y = y0 + c*(x/w)^2 - c*0.5 between -w..w (approximate, normalised by slope)
float curveDist(vec2 p, float y0, float c, float w) {
  float x = clamp(p.x, -w, w);
  float y = y0 - 0.5 * c + c * (x / w) * (x / w);
  float slope = 2.0 * c * x / (w * w);
  float dy = abs(p.y - y) / sqrt(1.0 + slope * slope);
  float dx = max(abs(p.x) - w, 0.0);
  return length(vec2(dx, dy));
}

// One face stroke as a bundle of scribbled light threads running along it (not a solid line).
// d: distance to the stroke's centre line, hw: half width.
float threadStroke(float d, float hw, vec2 p, float t, float seed) {
  float aa = 0.006;
  float band = 1.0 - smoothstep(hw, hw + aa, d);
  float wob = 0.55 * noise(vec3(p * 9.0, t * 0.6 + seed)) + 0.25 * noise(vec3(p * 23.0, seed));
  float lines = hair(d / (hw * 0.42) + wob, 1.3);           // ~2-3 threads across, wandering along the stroke
  float edge = 1.0 - smoothstep(0.0, hw, d);                // denser toward the centre line
  return band * (0.28 + 0.55 * edge + 0.85 * lines);
}

// distance from p to the segment a-b
float segDist(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a, ba = b - a;
  return length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0));
}

// distance to an ellipse outline (approximate)
float ellipseDist(vec2 p, vec2 c, vec2 r) { return abs(length((p - c) / r) - 1.0) * min(r.x, r.y); }

// Face, drawn in the head's own coordinates so it wraps the sphere as the head turns.
// x: stroke light (threads), y: woven fill.
vec2 face(vec3 q, float t) {
  if (q.z < 0.05) return vec2(0.0);
  vec2 p = q.xy;
  float smile = uFace.x, open = uFace.y, raise = uFace.z, tilt = uFace.w;
  float aa = 0.006;
  float stroke = 0.0, fill = 0.0;

  for (int i = 0; i < 2; i++) {
    float sx = i == 0 ? -1.0 : 1.0;
    // eyes: tall ovals with a woven fill
    vec2 c = vec2(0.255 * sx, 0.2);
    float arcW = uFace2.x, chevW = uFace2.y;
    float ovalW = (1.0 - arcW) * (1.0 - chevW);
    vec2 r = vec2(0.1, 0.15 * max(uEyeOpen, 0.05));
    stroke = max(stroke, ovalW * threadStroke(ellipseDist(p, c, r), 0.017, p, t, 3.0 + sx));
    float inside = length((p - c) / r);
    fill = max(fill, ovalW * (1.0 - smoothstep(1.0 - aa / r.x, 1.0, inside)));
    // closed, smiling eyes: an arch (happy, laughing)
    float arcD = curveDist(p - vec2(c.x, 0.0), c.y - 0.01, -0.09 * max(uEyeOpen, 0.3), 0.09);
    stroke = max(stroke, arcW * threadStroke(arcD, 0.016, p, t, 5.0 + sx));
    // mischief: squinted chevrons pointing toward the nose, > <
    vec2 tip = c + vec2(-sx * 0.055, -0.01);
    float chevD = min(segDist(p, c + vec2(sx * 0.07, 0.06), tip), segDist(p, c + vec2(sx * 0.07, -0.07), tip));
    stroke = max(stroke, chevW * threadStroke(chevD, 0.016, p, t, 7.0 + sx));

    // eyebrows: arcs that rise, fall and tilt with emotion (inner end toward the middle)
    float bx = p.x - c.x, inner = -sx * bx, hw = 0.12;
    float by = c.y + 0.225 + raise + 0.03 * (1.0 - (bx / hw) * (bx / hw)) + tilt * (inner / hw);
    float slope = abs(tilt / hw) + 0.06;
    float db = length(vec2(max(abs(bx) - hw, 0.0), abs(p.y - by) / sqrt(1.0 + slope * slope)));
    float thick = 0.012 * (1.0 - 0.45 * smoothstep(0.0, hw, abs(bx)));
    stroke = max(stroke, threadStroke(db, thick, p, t, 9.0 + sx));
  }

  // a tear below the eye on the viewer's right (sad)
  if (uFace2.z > 0.01) {
    vec2 tc = vec2(0.30, -0.01);
    vec2 tp = (p - tc) / vec2(1.0, 1.5);
    float drop = length(tp) - 0.05 + max(tp.y, 0.0) * 0.75;     // round bottom, pointed top
    stroke = max(stroke, uFace2.z * threadStroke(abs(drop), 0.011, p, t, 50.0));
    fill = max(fill, uFace2.z * (1.0 - smoothstep(-aa, 0.0, drop)));
  }

  // mouth: upper curve; opening adds a lower curve and a woven fill between them
  float w = 0.42 - 0.12 * open * step(0.6, open);
  float y0 = -0.19;
  float ohh = smoothstep(0.55, 0.85, open) * (1.0 - smoothstep(0.08, 0.25, abs(smile)));
  float upper = mix(smile, -0.16, ohh);              // round O for surprise
  w = mix(w, 0.16, ohh);
  float taper = mix(0.026, 0.014, smoothstep(0.0, w, abs(p.x)));
  stroke = max(stroke, threadStroke(curveDist(p, y0, upper, w), taper, p, t, 20.0));
  if (open > 0.01) {
    float xn = clamp(p.x / w, -1.0, 1.0);
    float drop = open * mix(0.27, 0.34, ohh) * (1.0 - xn * xn);
    float dl = curveDist(p - vec2(0.0, -drop), y0, mix(smile * (1.0 + 0.4 * open), upper, ohh), w);
    stroke = max(stroke, threadStroke(dl, 0.014, p, t, 31.0));
    float yu = y0 - 0.5 * upper + upper * xn * xn, yl = yu - drop;
    fill = max(fill, step(abs(p.x), w) * smoothstep(yl - aa, yl + aa, p.y) * (1.0 - smoothstep(yu - aa, yu + aa, p.y)));
  }
  // curled corners (as in the prototype still), only while smiling
  for (int i = 0; i < 2; i++) {
    float sx = i == 0 ? -1.0 : 1.0;
    vec2 corner = vec2(sx * w, y0 + 0.5 * smile);
    vec2 cc = corner + vec2(-sx * 0.035, 0.012);
    float dr = abs(length(p - cc) - 0.042);
    float arc = smoothstep(cc.y - 0.02, cc.y + 0.01, p.y) * step(0.0, sx * (p.x - cc.x) + 0.01);
    stroke = max(stroke, arc * smoothstep(0.08, 0.2, smile) * threadStroke(dr, 0.013, p, t, 40.0 + sx));
  }
  return vec2(stroke, fill) * smoothstep(0.05, 0.3, q.z);
}

void main() {
  vec2 frag = gl_FragCoord.xy;
  float aspect = uRes.x / uRes.y;
  vec2 uv = (frag - 0.5 * uRes) / min(uRes.x, uRes.y);   // fits portrait screens too
  uv.y += uLift;

  vec3 ro = vec3(0.0, 0.0, uZoom);
  vec3 rd = normalize(vec3(uv * 0.9, -1.6));
  vec3 cen = vec3(0.0, uBob, 0.0);

  vec3 col = vec3(0.0);
  float t = uTime;

  // ---- floor glow: the avatar is a light source ----
  float floorY = -1.85;
  if (rd.y < 0.0) {
    float tf = (floorY - ro.y) / rd.y;
    vec3 hp = ro + rd * tf;
    float h = cen.y - floorY;
    float d2 = dot(hp.xz - cen.xz, hp.xz - cen.xz);
    float pool = exp(-d2 / (0.9 + 0.35 * h)) / (0.6 + h * h * 0.35);
    col += uFloor * mix(uCore, uRing, 0.45) * pool * 0.16 * (0.6 + 0.4 * uEnergy) * smoothstep(40.0, 4.0, tf);
  }

  // ---- sphere ----
  vec3 oc = ro - cen;
  float bq = dot(oc, rd);
  float cq = dot(oc, oc) - 1.0;
  float disc = bq * bq - cq;
  float closest = sqrt(max(dot(oc, oc) - bq * bq, 0.0));   // ray's nearest distance to the centre
  float glowE = 0.55 + 0.45 * uEnergy;

  if (disc > 0.0) {
    float sq = sqrt(disc);
    vec3 pF = ro + rd * (-bq - sq);
    vec3 pB = ro + rd * (-bq + sq);
    vec3 nF = normalize(pF - cen);
    vec3 qF = uHead * nF;                 // head space
    vec3 qB = uHead * normalize(pB - cen);
    float ndv = clamp(dot(nF, -rd), 0.0, 1.0);
    float chord = 2.0 * sq;               // light path through the sphere

    float edge = 1.0 - smoothstep(1.0 - 2.0 * max(fwidth(closest), 1e-4), 1.0, closest);  // smooth silhouette
    vec3 sph = vec3(0.0);
    // base layer: soft volumetric glow, brightest at the centre
    sph += uCore * (0.018 + 0.05 * chord * chord) * glowE;
    // contour layer: woven light, front and (dimmer) back
    float front = weave(qF, 24.0, 0.85, t, 0.0) + 0.5 * weave(qF, 44.0, 0.75, t * 1.3, 20.0);
    float back  = weave(qB, 24.0, 0.85, t, 0.0);
    sph += uCore * front * 0.2 * glowE;
    sph += uCore * back * 0.06 * glowE;
    // bright rim where the threads pile up at the edge
    float rim = pow(1.0 - ndv, 4.0);
    if (rim > 0.02) sph += uCore * rim * (0.5 + 0.6 * weave(qF, 60.0, 1.0, t * 1.5, 40.0)) * glowE;

    // feature layer: denser, brighter thread, always the core colour
    vec2 f = face(qF, t);
    sph += uCore * f.x * 1.35;
    // the face seen through the ball from behind: on the far wall, mirrored and warped by the
    // light in between; hidden in solid mode (opaque), stronger in ghost mode
    vec3 qW = normalize(qB + 0.045 * vec3(noise(qB * 3.0 + vec3(t * 0.4)), noise(qB * 3.0 + vec3(7.0 - t * 0.3)), 0.0));
    vec2 fb = face(qW, t);
    float seeThrough = (1.0 - step(1.5, uMode)) * (0.34 + 0.3 * step(0.5, uMode));
    sph += uCore * (fb.x * 0.9 + fb.y * 0.12) * seeThrough * glowE;
    if (f.y > 0.001) sph += uCore * f.y * (0.06 + 0.5 * weave(qF, 110.0, 1.0, t * 0.6, 70.0));

    // hologram modes
    float ghost = step(0.5, uMode) * (1.0 - step(1.5, uMode));
    float solid = step(1.5, uMode);
    // ghost: see-through, the far side shows more, faint and flickering
    sph += uCore * back * 0.22 * ghost;
    sph *= mix(1.0, 0.3 + 0.08 * sin(uClock * 8.0 + qF.y * 6.0) + 0.06 * noise(vec3(qF.xy * 4.0, uClock * 3.0)), ghost);
    // solid: an opaque, lit ball of light with the threads and face on its skin
    vec3 keyDir = normalize(vec3(-0.45, 0.7, 0.55));
    float lit = 0.12 + 0.5 * pow(ndv, 1.3) + 0.18 * max(dot(nF, keyDir), 0.0);
    float spec = pow(max(dot(reflect(rd, nF), keyDir), 0.0), 28.0);
    vec3 body = uCore * lit + vec3(1.0, 0.96, 0.9) * spec * 0.45;
    sph = mix(sph, body + sph * 0.5 + uCore * f.x * 0.7, 0.65 * solid);
    col += sph * edge;
  }

  // ---- border layer: the spinning mood ring of loose, scribbly strands ----
  {
    vec3 cp = ro + rd * max(-bq, 0.0) - cen;
    vec3 right = vec3(1.0, 0.0, 0.0), up = vec3(0.0, 1.0, 0.0);
    float phi = atan(dot(cp, up), dot(cp, right));
    float spin = uClock * (0.25 + 0.35 * uEnergy);
    float ring = 0.0;
    for (int i = 0; i < 26; i++) {
      float fi = float(i);
      float a = phi + spin * (0.7 + 0.6 * hash1(fi * 5.3));
      vec3 cpos = vec3(cos(a), sin(a), 0.0) * (1.4 + hash1(fi) * 1.6);
      float r = 1.02 + 0.1 * hash1(fi * 2.1) + 0.075 * noise(cpos + vec3(fi * 3.7, uClock * 0.25, 0.0));
      float d = abs(closest - r);
      float w = max(fwidth(closest), 1e-4);
      float strand = 1.0 - smoothstep(0.0, 1.1 * w, d);
      strand *= 0.4 + 0.6 * smoothstep(-0.4, 0.4, noise(vec3(cos(a) * 3.0, sin(a) * 3.0, fi + uClock * 0.2)));
      ring += strand;
    }
    float halo = exp(-pow((closest - 1.09) / 0.07, 2.0));
    float hide = disc > 0.0 ? 0.55 : 1.0;          // strands crossing the face sit a little behind the glow
    float ringMode = uMode > 0.5 && uMode < 1.5 ? 0.42 : 1.0;
    col += uRing * (ring * 0.42 * hide + halo * 0.33) * glowE * ringMode;
    col += uRing * exp(-max(closest - 1.0, 0.0) * 5.0) * 0.06 * glowE;  // soft atmosphere
  }

  // tone map + slight warm grade
  col = 1.0 - exp(-col * 1.35);
  col = pow(col, vec3(0.95));
  col = 1.0 - (1.0 - uBg) * (1.0 - col);       // light added over the page colour
  outColor = vec4(col, 1.0);
}`;
  const VERTEX = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }`;

  // Face shapes for each mood (names match the server's mood field), after the owner's
  // expression sheet. arc: closed smiling eyes; chev: squinted mischief eyes; tear: a tear.
  // The ring keeps the avatar's own glow colour: moods change the face, not the chosen colours.
  const BASE = {smile: 0, open: 0, raise: 0, tilt: 0, eye: 1, arc: 0, chev: 0, tear: 0};
  const MOODS = Object.freeze({
    calm:      {...BASE, smile: 0.30, raise: 0.015},                                  // the prototype still
    happy:     {...BASE, smile: 0.30, open: 0.34, raise: 0.03, arc: 1},
    laughing:  {...BASE, smile: 0.24, open: 0.82, raise: 0.06, arc: 1},
    excited:   {...BASE, smile: 0.36, open: 0.55, raise: 0.06, eye: 1.08},
    surprised: {...BASE, open: 0.85, raise: 0.09, eye: 1.18},
    neutral:   {...BASE, smile: 0.0, raise: -0.015, eye: 0.62},
    sad:       {...BASE, smile: -0.20, raise: -0.01, tilt: 0.055, eye: 0.85, tear: 1},
    angry:     {...BASE, smile: -0.14, open: 0.10, raise: -0.03, tilt: -0.07, eye: 0.80},
    mischief:  {...BASE, smile: 0.34, raise: -0.01, tilt: -0.05, chev: 1},
  });
  const MODES = Object.freeze({energy: 0, ghost: 1, solid: 2});
  const HEX = /^#[0-9a-fA-F]{6}$/;

  function channels(hex, fallback) {
    const h = HEX.test(hex || '') ? hex : fallback;
    const n = parseInt(h.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => v / 255);
  }
  const linear = (hex, fallback) => channels(hex, fallback).map(v => Math.pow(v, 2.2));

  function supported() {
    try { return !!document.createElement('canvas').getContext('webgl2'); } catch (e) { return false; }
  }

  function create(canvas, options) {
    const o = Object.assign({core: '#ffc42e', ring: '#9ccf2a', mood: 'calm', energy: 1, mode: 'energy',
      background: '#000000', lift: 0.02, zoom: 5.6, floor: 1, interactive: true, idleLook: true, maxScale: 1.75}, options);
    const gl = canvas.getContext('webgl2', {antialias: false, alpha: false, powerPreference: 'high-performance'});
    if (!gl) throw new Error('WebGL2 is not available');

    const compile = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { const log = gl.getShaderInfoLog(s); gl.deleteShader(s); throw new Error(log); }
      return s;
    };
    const prog = gl.createProgram();
    const vs = compile(gl.VERTEX_SHADER, VERTEX), fs = compile(gl.FRAGMENT_SHADER, FRAGMENT);
    gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    const U = {};
    for (const n of ['uRes', 'uTime', 'uClock', 'uCore', 'uRing', 'uEnergy', 'uHead', 'uBob', 'uFace', 'uFace2', 'uEyeOpen', 'uBg', 'uMode', 'uLift', 'uZoom', 'uFloor']) U[n] = gl.getUniformLocation(prog, n);

    // live state eases toward its target
    const face = Object.assign({}, MOODS[o.mood] || MOODS.calm), faceTarget = Object.assign({}, face);
    const core = linear(o.core, '#ffc42e'), ring = linear(o.ring, '#9ccf2a');
    let coreT = core.slice(), ringT = ring.slice();
    let energy = Number.isFinite(+o.energy) ? +o.energy : 1, energyT = energy;
    let mode = MODES[o.mode] ?? 0, modeT = mode, talking = false;
    let bg = channels(o.background, '#000000');

    function set(p) {
      if (!p) return;
      if (p.mood && MOODS[p.mood]) Object.assign(faceTarget, MOODS[p.mood]);
      if (p.core) coreT = linear(p.core, '#ffc42e');
      if (p.ring) ringT = linear(p.ring, '#9ccf2a');
      if (Number.isFinite(p.energy)) energyT = Math.max(0, Math.min(2, p.energy));
      if (p.mode && p.mode in MODES) modeT = MODES[p.mode];
      if (typeof p.talking === 'boolean') talking = p.talking;
      if (p.background) bg = channels(p.background, '#000000');
      kick();
    }

    // head turning: drag, with a gentle idle look-around
    let dragYaw = Number.isFinite(+o.yaw) ? +o.yaw : 0, dragPitch = 0, dragging = false, lx = 0, ly = 0, lastInput = -1e9;
    const onDown = e => { dragging = true; lx = e.clientX; ly = e.clientY; try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* not capturable */ } };
    const onMove = e => {
      if (!dragging) return;
      dragYaw += (e.clientX - lx) * 0.008;
      dragPitch = Math.max(-0.9, Math.min(0.9, dragPitch + (e.clientY - ly) * 0.006));
      lx = e.clientX; ly = e.clientY; lastInput = performance.now();
    };
    const onUp = () => { dragging = false; };
    if (o.interactive) {
      canvas.style.touchAction = 'none';
      canvas.addEventListener('pointerdown', onDown); canvas.addEventListener('pointermove', onMove);
      canvas.addEventListener('pointerup', onUp); canvas.addEventListener('pointercancel', onUp);
    }

    // draw only while it can be seen
    let onScreen = true, raf = 0, destroyed = false;
    const io = 'IntersectionObserver' in window ? new IntersectionObserver(entries => { onScreen = entries.some(e => e.isIntersecting); if (onScreen) kick(); }) : null;
    if (io) io.observe(canvas);
    const onVis = () => { if (!document.hidden) kick(); };
    document.addEventListener('visibilitychange', onVis);

    // adaptive resolution keeps phones smooth
    let scale = 1, slowAvg = 16.7;
    const reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    let nextBlink = performance.now() + 2500, blinkT = -1, flow = 0, last = performance.now();

    function frame(now) {
      raf = 0;
      if (destroyed || !onScreen || document.hidden) return;
      const dtMs = now - last, dt = Math.min(dtMs / 1000, 0.1); last = now;
      slowAvg += (dtMs - slowAvg) * 0.05;
      if (slowAvg > 26 && scale > 0.45) { scale = Math.max(0.45, scale * 0.85); slowAvg = 16.7; }
      else if (slowAvg < 15 && scale < 1) { scale = Math.min(1, scale * 1.08); slowAvg = 16.7; }
      const dpr = Math.min(window.devicePixelRatio || 1, o.maxScale) * scale;
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr)), h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);

      const k = 1 - Math.exp(-dt * 6);
      for (const key in faceTarget) face[key] += (faceTarget[key] - face[key]) * k;
      for (let i = 0; i < 3; i++) { core[i] += (coreT[i] - core[i]) * k; ring[i] += (ringT[i] - ring[i]) * k; }
      energy += (energyT - energy) * k;
      mode += (modeT - mode) * Math.min(1, k * 2);
      if (Math.abs(modeT - mode) < 0.02) mode = modeT;
      flow += dt * (0.35 + 0.65 * energy) * (reduce ? 0.3 : 1);
      const s = now / 1000;

      const idle = o.idleLook ? Math.min(Math.max((now - lastInput - 2500) / 2500, 0), 1) : 0;
      if (!dragging) { dragYaw *= Math.pow(0.35, dt * idle); dragPitch *= Math.pow(0.35, dt * idle); }
      const yaw = dragYaw + idle * (0.32 * Math.sin(s * 0.37) + 0.1 * Math.sin(s * 0.91));
      const pitch = dragPitch + idle * 0.08 * Math.sin(s * 0.53 + 1.0);

      let eye = face.eye;
      if (blinkT < 0 && now > nextBlink) blinkT = now;
      if (blinkT >= 0) {
        const p = (now - blinkT) / 150;
        if (p < 1) eye *= Math.abs(1 - 2 * p) * 0.96 + 0.04;
        else { blinkT = -1; nextBlink = now + 2600 + Math.random() * 3600; }
      }
      let open = face.open;
      if (talking) open = Math.min(1, open + 0.42 * Math.max(0, Math.sin(s * 11) * 0.6 + Math.sin(s * 7.3 + 1.3) * 0.5 + 0.15));

      // world -> head rotation: transpose of Ry(yaw)·Rx(pitch), column-major
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      gl.uniformMatrix3fv(U.uHead, false, [cy, 0, -sy, sy * sp, cp, cy * sp, sy * cp, -sp, cy * cp]);
      gl.uniform2f(U.uRes, w, h);
      gl.uniform1f(U.uTime, flow);
      gl.uniform1f(U.uClock, reduce ? s * 0.3 : s);
      gl.uniform3fv(U.uCore, core); gl.uniform3fv(U.uRing, ring); gl.uniform3fv(U.uBg, bg);
      gl.uniform1f(U.uEnergy, energy); gl.uniform1f(U.uMode, mode);
      gl.uniform1f(U.uBob, (reduce ? 0.02 : 0.07) * Math.sin(s * 1.05) + 0.02 * Math.sin(s * 2.3));
      gl.uniform4f(U.uFace, face.smile, open, face.raise, face.tilt);
      gl.uniform4f(U.uFace2, face.arc, face.chev, face.tear, 0);
      gl.uniform1f(U.uEyeOpen, eye);
      gl.uniform1f(U.uLift, o.lift); gl.uniform1f(U.uZoom, o.zoom); gl.uniform1f(U.uFloor, o.floor);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      kick();
    }
    function kick() { if (!raf && !destroyed) { last = performance.now(); raf = requestAnimationFrame(frame); } }
    kick();

    function destroy() {
      destroyed = true;
      if (raf) cancelAnimationFrame(raf);
      if (io) io.disconnect();
      document.removeEventListener('visibilitychange', onVis);
      canvas.removeEventListener('pointerdown', onDown); canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp); canvas.removeEventListener('pointercancel', onUp);
      gl.deleteProgram(prog); gl.deleteShader(vs); gl.deleteShader(fs); gl.deleteBuffer(buf);
      const lose = gl.getExtension('WEBGL_lose_context');   // hand the context back now, not at GC
      if (lose) lose.loseContext();
    }
    return Object.freeze({set, destroy});
  }

  window.PubCastEnergySphere = Object.freeze({create, supported, MOODS: Object.keys(MOODS), MODES: Object.keys(MODES)});
})();
