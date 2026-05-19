// Pocket DRS — Hawk-Eye 3D visualisation.
// Broadcast-grade pitch + ball trajectory rendered with Three.js. The scene
// reflects the app's signal-red / pitch-green palette and is tuned for
// readability on phones (high contrast, low-haze fog, restrained colour).
(function () {
  'use strict';

  let scene, camera, renderer, controls;
  let worldGroup, pitchGroup;
  let ballPathGroup, bounceMarker, impactMarker, bounceRing, impactRing;
  let stumpsGroup;
  let ballMesh, ballTrail;
  let anim = null;
  let currentData = null;
  let lastFrameMs = 0;

  // --- Geometry constants (metres) -------------------------------------
  const PITCH_LENGTH = 20.12;
  const PITCH_WIDTH  = 3.05;
  const STUMP_HEIGHT = 0.71;
  const STUMP_RADIUS = 0.02;
  const STUMP_SPACING = 0.057;

  // --- Brand colours ---------------------------------------------------
  const COL = {
    bg: 0x0a0a0b,
    fog: 0x0a0a0b,
    outfield: 0x0d2912,
    pitch: 0x6b5435,
    pitchEdge: 0x4a3a24,
    crease: 0xf4f4f0,
    stump: 0xd9bf8a,
    bail: 0xefd9aa,
    signalRed: 0xff2d2d,
    pitchGreen: 0x00d957,
    caution: 0xffb400,
    ash: 0x8b8b92,
    ball: 0xf4f4f0,
    grid: 0x1a1a1f,
  };

  function postBridge(type, payload) {
    try {
      if (typeof window.__hawkeyeBridgePost === 'function') {
        window.__hawkeyeBridgePost(type, payload);
      }
    } catch (_) { /* no-op */ }
  }

  function clampIndex(value, fallback, maxInclusive) {
    const n = Number.isFinite(value) ? value : fallback;
    if (n < 0) return 0;
    if (n > maxInclusive) return maxInclusive;
    return Math.floor(n);
  }

  function init() {
    try {
      const container = document.getElementById('container');
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;

      // Scene
      scene = new THREE.Scene();
      scene.background = new THREE.Color(COL.bg);
      scene.fog = new THREE.Fog(COL.fog, 18, 55);

      worldGroup = new THREE.Group();
      scene.add(worldGroup);

      pitchGroup = new THREE.Group();
      worldGroup.add(pitchGroup);

      // Camera — broadcast side-on with a slight elevation. Default pose
      // looks straight down the pitch; applyPose() overrides per-pitch.
      camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 200);
      camera.position.set(PITCH_LENGTH + 6, 3.2, 0.05);
      camera.lookAt(PITCH_LENGTH / 2, 0.4, 0);

      // Renderer
      const canvas = document.getElementById('canvas');
      renderer = new THREE.WebGLRenderer({ antialias: true, canvas: canvas, alpha: false });
      renderer.setSize(w, h);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      if (renderer.outputColorSpace !== undefined) {
        renderer.outputColorSpace = THREE.SRGBColorSpace;
      }

      // Controls
      if (typeof THREE.OrbitControls !== 'undefined') {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.12;
        controls.minDistance = 4;
        controls.maxDistance = 38;
        controls.maxPolarAngle = Math.PI / 2.05;
        controls.target.set(PITCH_LENGTH / 2, 0.4, 0);
        controls.update();
      }

      // --- Lighting -----------------------------------------------------
      // Cool ambient base + warm key from above-batting end + cyan rim
      // from bowler side. Mirrors the broadcast-style two-light setup.
      const ambient = new THREE.AmbientLight(0xc8d4e8, 0.45);
      scene.add(ambient);

      const key = new THREE.DirectionalLight(0xfff2d4, 1.05);
      key.position.set(8, 22, 12);
      key.castShadow = true;
      key.shadow.mapSize.width = 2048;
      key.shadow.mapSize.height = 2048;
      key.shadow.camera.near = 0.5;
      key.shadow.camera.far = 60;
      key.shadow.camera.left = -22;
      key.shadow.camera.right = 22;
      key.shadow.camera.top = 22;
      key.shadow.camera.bottom = -22;
      key.shadow.bias = -0.0002;
      scene.add(key);

      const rim = new THREE.DirectionalLight(0x6aa3ff, 0.35);
      rim.position.set(-14, 8, -8);
      scene.add(rim);

      // --- Outfield (large dark surface) --------------------------------
      const outfieldGeo = new THREE.PlaneGeometry(120, 120);
      const outfieldMat = new THREE.MeshStandardMaterial({
        color: COL.outfield,
        roughness: 0.95,
        metalness: 0.0,
      });
      const outfield = new THREE.Mesh(outfieldGeo, outfieldMat);
      outfield.rotation.x = -Math.PI / 2;
      outfield.position.set(PITCH_LENGTH / 2, 0.0, 0);
      outfield.receiveShadow = true;
      pitchGroup.add(outfield);

      // Subtle ground grid for depth perception (broadcast HUD feel).
      const gridHelper = new THREE.GridHelper(80, 80, COL.grid, COL.grid);
      gridHelper.material.opacity = 0.18;
      gridHelper.material.transparent = true;
      gridHelper.position.set(PITCH_LENGTH / 2, 0.005, 0);
      pitchGroup.add(gridHelper);

      // --- Pitch strip --------------------------------------------------
      const pitchGeo = new THREE.PlaneGeometry(PITCH_LENGTH, PITCH_WIDTH);
      const pitchMat = new THREE.MeshStandardMaterial({
        color: COL.pitch,
        roughness: 0.92,
        metalness: 0.0,
      });
      const pitchMesh = new THREE.Mesh(pitchGeo, pitchMat);
      pitchMesh.rotation.x = -Math.PI / 2;
      pitchMesh.position.set(PITCH_LENGTH / 2, 0.011, 0);
      pitchMesh.receiveShadow = true;
      pitchGroup.add(pitchMesh);

      // Edge strip (slightly darker) to outline the pitch.
      const edgeGeo = new THREE.PlaneGeometry(PITCH_LENGTH + 0.06, PITCH_WIDTH + 0.06);
      const edgeMat = new THREE.MeshStandardMaterial({
        color: COL.pitchEdge, roughness: 0.95, metalness: 0.0,
      });
      const edge = new THREE.Mesh(edgeGeo, edgeMat);
      edge.rotation.x = -Math.PI / 2;
      edge.position.set(PITCH_LENGTH / 2, 0.009, 0);
      edge.receiveShadow = true;
      pitchGroup.add(edge);

      // --- Crease markings ---------------------------------------------
      const RETURN_HALF = 0.66;
      // Bowler end
      createCrease(PITCH_LENGTH, -PITCH_WIDTH / 2, PITCH_LENGTH, PITCH_WIDTH / 2);
      createCrease(PITCH_LENGTH - 1.22, -PITCH_WIDTH / 2, PITCH_LENGTH - 1.22, PITCH_WIDTH / 2);
      createCrease(PITCH_LENGTH - 1.22, -RETURN_HALF, PITCH_LENGTH + 0.4, -RETURN_HALF);
      createCrease(PITCH_LENGTH - 1.22, RETURN_HALF, PITCH_LENGTH + 0.4, RETURN_HALF);
      // Batter end
      createCrease(0, -PITCH_WIDTH / 2, 0, PITCH_WIDTH / 2);
      createCrease(1.22, -PITCH_WIDTH / 2, 1.22, PITCH_WIDTH / 2);
      createCrease(1.22, -RETURN_HALF, -0.4, -RETURN_HALF);
      createCrease(1.22, RETURN_HALF, -0.4, RETURN_HALF);

      // --- Stumps -------------------------------------------------------
      stumpsGroup = new THREE.Group();
      pitchGroup.add(stumpsGroup);
      createStumps(0);
      createStumps(PITCH_LENGTH);

      // Resize observer + window listener for safety.
      window.addEventListener('resize', onWindowResize, false);
      if (typeof ResizeObserver !== 'undefined') {
        try { new ResizeObserver(onWindowResize).observe(container); } catch (_) { /* no-op */ }
      }

      if (currentData && currentData.points && currentData.points.length >= 2) {
        updateTrajectory(currentData);
      } else {
        applyPose(null);
      }

      if (window.hawkeye) window.hawkeye.isReady = true;
      postBridge('ready', { ok: true });

      lastFrameMs = performance.now();
      animate();
    } catch (e) {
      postBridge('error', { message: String(e) });
    }
  }

  function createCrease(x1, z1, x2, z2) {
    const dx = Math.abs(x2 - x1);
    const dz = Math.abs(z2 - z1);
    const STRIP_W = 0.045;
    const lengthwise = dx >= dz;
    const w = lengthwise ? Math.max(dx, STRIP_W) : STRIP_W;
    const d = lengthwise ? STRIP_W : Math.max(dz, STRIP_W);
    const geometry = new THREE.BoxGeometry(w, 0.012, d);
    const material = new THREE.MeshStandardMaterial({
      color: COL.crease,
      roughness: 0.55,
      metalness: 0.0,
      emissive: COL.crease,
      emissiveIntensity: 0.12,
    });
    const strip = new THREE.Mesh(geometry, material);
    strip.position.set((x1 + x2) / 2, 0.022, (z1 + z2) / 2);
    strip.receiveShadow = true;
    if (pitchGroup) pitchGroup.add(strip);
  }

  function createStumps(xPos) {
    const stumpMat = new THREE.MeshStandardMaterial({
      color: COL.stump, roughness: 0.45, metalness: 0.12,
    });
    const bailMat = new THREE.MeshStandardMaterial({
      color: COL.bail, roughness: 0.4, metalness: 0.15,
    });
    for (let i = -1; i <= 1; i++) {
      const zPos = i * STUMP_SPACING;
      const geometry = new THREE.CylinderGeometry(STUMP_RADIUS, STUMP_RADIUS, STUMP_HEIGHT, 18);
      const stump = new THREE.Mesh(geometry, stumpMat);
      stump.position.set(xPos, STUMP_HEIGHT / 2, zPos);
      stump.castShadow = true;
      stump.receiveShadow = true;
      stumpsGroup.add(stump);
    }
    const bailGeo = new THREE.CylinderGeometry(0.011, 0.011, STUMP_SPACING * 2, 10);
    const bail = new THREE.Mesh(bailGeo, bailMat);
    bail.rotation.x = Math.PI / 2;
    bail.position.set(xPos, STUMP_HEIGHT + 0.01, 0);
    bail.castShadow = true;
    stumpsGroup.add(bail);
  }

  function onWindowResize() {
    const container = document.getElementById('container');
    if (!container || !camera || !renderer) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }

  function animate() {
    requestAnimationFrame(animate);
    const now = performance.now();
    const dt = (now - lastFrameMs) / 1000;
    lastFrameMs = now;

    if (controls) controls.update();

    if (anim && anim.curve && ballMesh) {
      const t = (now - anim.startMs) / anim.durationMs;
      if (t >= 1) {
        ballMesh.position.copy(anim.curve.getPoint(1));
        anim = null;
      } else if (t >= 0) {
        ballMesh.position.copy(anim.curve.getPoint(t));
      }
    }

    // Bounce/impact markers pulse to draw the eye.
    if (bounceMarker) {
      const k = 0.07 + Math.sin(now * 0.005) * 0.012;
      bounceMarker.scale.setScalar(k / 0.07);
    }
    if (impactMarker) {
      const k = 0.07 + Math.sin(now * 0.005 + Math.PI / 2) * 0.012;
      impactMarker.scale.setScalar(k / 0.07);
    }
    if (bounceRing) bounceRing.rotation.z += dt * 0.5;
    if (impactRing) impactRing.rotation.z -= dt * 0.5;

    if (renderer && scene && camera) renderer.render(scene, camera);
  }

  function updateTrajectory(data) {
    currentData = data;
    if (!scene || !camera || !renderer) return;

    applyPose(data && data.pose);

    // Clean previous trajectory artefacts.
    [ballPathGroup, bounceMarker, impactMarker, bounceRing, impactRing].forEach((m) => {
      if (m && worldGroup) worldGroup.remove(m);
    });
    ballPathGroup = null;
    bounceMarker = null;
    impactMarker = null;
    bounceRing = null;
    impactRing = null;

    if (!data || !data.points || data.points.length < 2) {
      updateDecision(null);
      if (ballMesh) ballMesh.visible = false;
      anim = null;
      return;
    }

    // Coordinate space: server (x,y,z) → three (x, z, y). x is along the
    // pitch length, y is height (up), z is lateral.
    const pts = data.points.map((p) => new THREE.Vector3(p.x, p.z, p.y));

    const bounceIndex = clampIndex(data.bounceIndex, 0, pts.length - 1);
    const impactIndex = clampIndex(data.impactIndex, pts.length - 1, pts.length - 1);

    ballPathGroup = new THREE.Group();

    // Three-segment trail: flight (red) — post-bounce (green) — predicted
    // continuation (amber, semi-transparent). Each segment is a tube so the
    // line has volume and reads through fog.
    if (bounceIndex > 0) {
      ballPathGroup.add(createTube(pts.slice(0, bounceIndex + 1), COL.signalRed, 1.0, 0.045));
    }
    if (impactIndex > bounceIndex) {
      ballPathGroup.add(createTube(pts.slice(bounceIndex, impactIndex + 1), COL.pitchGreen, 1.0, 0.04));
    }
    if (impactIndex < pts.length - 1) {
      ballPathGroup.add(createTube(pts.slice(impactIndex), COL.caution, 0.65, 0.04));
    }

    worldGroup.add(ballPathGroup);

    // Bounce / impact markers + spinning ground rings for emphasis.
    if (pts[bounceIndex]) {
      const node = createMarker(pts[bounceIndex], COL.signalRed);
      const ring = createGroundRing(pts[bounceIndex], COL.signalRed, 0.18);
      worldGroup.add(node);
      worldGroup.add(ring);
      bounceMarker = node;
      bounceRing = ring;
    }
    if (pts[impactIndex]) {
      const node = createMarker(pts[impactIndex], COL.caution);
      const ring = createGroundRing(pts[impactIndex], COL.caution, 0.16);
      worldGroup.add(node);
      worldGroup.add(ring);
      impactMarker = node;
      impactRing = ring;
    }

    updateDecision(data.decision);

    if (data.animate) {
      if (!ballMesh) {
        ballMesh = new THREE.Mesh(
          new THREE.SphereGeometry(0.052, 32, 32),
          new THREE.MeshStandardMaterial({
            color: COL.ball,
            roughness: 0.22,
            metalness: 0.08,
            emissive: 0xffffff,
            emissiveIntensity: 0.18,
          })
        );
        ballMesh.castShadow = true;
        worldGroup.add(ballMesh);
      }
      const curve = new THREE.CatmullRomCurve3(pts);
      ballMesh.visible = true;
      ballMesh.position.copy(curve.getPoint(0));
      anim = { curve: curve, startMs: performance.now(), durationMs: 1700 };
    } else {
      if (ballMesh) ballMesh.visible = false;
      anim = null;
    }
  }

  function createTube(points, color, opacity, radius) {
    if (!points || points.length < 2) return new THREE.Object3D();
    const curve = new THREE.CatmullRomCurve3(points);
    const segments = Math.min(120, Math.max(24, points.length * 4));
    const geometry = new THREE.TubeGeometry(curve, segments, radius || 0.04, 14, false);
    const material = new THREE.MeshStandardMaterial({
      color: color,
      transparent: (opacity != null && opacity < 1.0),
      opacity: opacity == null ? 1.0 : opacity,
      roughness: 0.35,
      metalness: 0.05,
      emissive: color,
      emissiveIntensity: 0.32,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function createMarker(position, color) {
    const node = new THREE.Mesh(
      new THREE.SphereGeometry(0.07, 24, 24),
      new THREE.MeshStandardMaterial({
        color: color,
        roughness: 0.3,
        metalness: 0.1,
        emissive: color,
        emissiveIntensity: 0.5,
      })
    );
    node.position.copy(position);
    node.castShadow = true;
    return node;
  }

  function createGroundRing(position, color, radius) {
    const ringGeo = new THREE.RingGeometry(radius * 0.6, radius, 48);
    const ringMat = new THREE.MeshBasicMaterial({
      color: color,
      transparent: true,
      opacity: 0.55,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(position.x, 0.025, position.z);
    return ring;
  }

  function toRad(value) {
    const n = Number(value);
    if (!isFinite(n)) return 0;
    return n * Math.PI / 180;
  }

  function applyPose(pose) {
    if (!worldGroup || !camera) return;
    const yaw = toRad(pose && pose.yawDeg);
    const tilt = toRad(pose && pose.tiltDeg);
    const roll = toRad(pose && pose.rollDeg);
    const distance = Math.max(7, Number(pose && pose.cameraDistanceM) || 19);
    const height = Math.max(1.6, Number(pose && pose.cameraHeightM) || 2.8);
    const lateral = Number(pose && pose.cameraLateralOffsetM) || 0;
    const targetX = Number(pose && pose.targetXM);
    const safeTargetX = isFinite(targetX) ? targetX : (PITCH_LENGTH / 2);

    worldGroup.rotation.set(0, 0, 0);

    const viewDirection = new THREE.Vector3(-1, 0, 0);
    viewDirection.applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
    viewDirection.applyAxisAngle(new THREE.Vector3(0, 0, 1), tilt);

    const target = new THREE.Vector3(safeTargetX, 0.35, 0);
    const eye = target.clone().sub(viewDirection.multiplyScalar(distance));
    eye.y = height;
    eye.z += lateral;

    camera.position.copy(eye);
    camera.up.set(0, 1, 0);
    camera.rotation.set(0, 0, 0);
    camera.lookAt(target);
    camera.rotateZ(roll);

    if (controls) {
      controls.target.copy(target);
      controls.update();
    }
  }

  function updateDecision(decision) {
    const el = document.getElementById('decision');
    if (!el) return;
    el.classList.remove('out', 'not-out', 'umpires-call', 'visible');
    el.style.display = '';

    if (!decision) {
      el.textContent = '';
      el.style.display = 'none';
      return;
    }

    if (decision === 'out') { el.textContent = 'OUT'; el.classList.add('out'); }
    else if (decision === 'not_out') { el.textContent = 'NOT OUT'; el.classList.add('not-out'); }
    else if (decision === 'umpires_call') { el.textContent = "UMPIRE'S CALL"; el.classList.add('umpires-call'); }
    else { el.style.display = 'none'; return; }

    // trigger CSS transition next tick.
    requestAnimationFrame(() => el.classList.add('visible'));
  }

  window.hawkeye = { updateTrajectory: updateTrajectory, isReady: false };

  if (typeof THREE !== 'undefined') init();
  else window.addEventListener('load', init);
})();
