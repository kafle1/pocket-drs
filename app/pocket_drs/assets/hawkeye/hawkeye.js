// Hawk-Eye visualization using Three.js
(function () {
  'use strict';

  let scene, camera, renderer, controls;
  let worldGroup, pitchGroup;
  let ballPathGroup, bounceMarker, impactMarker;
  let stumpsGroup;
  let ballMesh;
  let anim = null;
  let currentData = null;

  // Constants (meters)
  const PITCH_LENGTH = 20.12;
  const PITCH_WIDTH = 3.05;
  const STUMP_HEIGHT = 0.71;
  const STUMP_RADIUS = 0.02; 
  const STUMP_SPACING = 0.057; 

  function postBridge(type, payload) {
    try {
      if (typeof window.__hawkeyeBridgePost === 'function') {
        window.__hawkeyeBridgePost(type, payload);
      }
    } catch (_) {
      // no-op
    }
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
    scene.background = new THREE.Color(0x1a2332);
    scene.fog = new THREE.Fog(0x1a2332, 15, 50);

    worldGroup = new THREE.Group();
    scene.add(worldGroup);

    pitchGroup = new THREE.Group();
    worldGroup.add(pitchGroup);

    // Camera
    camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
    camera.position.set(PITCH_LENGTH + 4, 2.5, 0); 
    camera.lookAt(0, 0.5, 0);

    // Renderer
    const canvas = document.getElementById('canvas');
    renderer = new THREE.WebGLRenderer({ antialias: true, canvas: canvas });
    renderer.setSize(w, h);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    // OrbitControls for touch/drag interaction (needs renderer to be ready)
    if (typeof THREE.OrbitControls !== 'undefined') {
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.15;
      controls.minDistance = 3;
      controls.maxDistance = 40;
      controls.maxPolarAngle = Math.PI / 2.1;
      controls.target.set(PITCH_LENGTH / 2, 0.5, 0);
      controls.update();
    }

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(15, 25, 10);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 2048;
    dirLight.shadow.mapSize.height = 2048;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 60;
    dirLight.shadow.camera.left = -20;
    dirLight.shadow.camera.right = 20;
    dirLight.shadow.camera.top = 20;
    dirLight.shadow.camera.bottom = -20;
    dirLight.shadow.bias = -0.0001;
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0x7ec8f5, 0.3);
    fillLight.position.set(-10, 10, -10);
    scene.add(fillLight);

    // Ground
    const groundGeo = new THREE.PlaneGeometry(100, 100);
    const groundMat = new THREE.MeshStandardMaterial({ 
      color: 0x1a4010, 
      roughness: 0.85,
      metalness: 0.0
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    pitchGroup.add(ground);

    // Pitch
    const pitchGeo = new THREE.PlaneGeometry(PITCH_LENGTH, PITCH_WIDTH);
    const pitchMat = new THREE.MeshStandardMaterial({ 
      color: 0x3a6020, 
      roughness: 0.9,
      metalness: 0.0
    });
    const pitch = new THREE.Mesh(pitchGeo, pitchMat);
    pitch.rotation.x = -Math.PI / 2;
    pitch.position.set(PITCH_LENGTH / 2, 0.01, 0); 
    pitch.receiveShadow = true;
    pitch.castShadow = false;
    pitchGroup.add(pitch);

    // Crease lines
    const creaseMat = new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 });
    // Bowling crease (at x=PITCH_LENGTH)
    createLine(PITCH_LENGTH, -PITCH_WIDTH/2, PITCH_LENGTH, PITCH_WIDTH/2, creaseMat);
    // Popping crease (at x=PITCH_LENGTH - 1.22)
    createLine(PITCH_LENGTH - 1.22, -PITCH_WIDTH/2, PITCH_LENGTH - 1.22, PITCH_WIDTH/2, creaseMat);
    
    // Batting crease (at x=0)
    createLine(0, -PITCH_WIDTH/2, 0, PITCH_WIDTH/2, creaseMat);
    // Popping crease (at x=1.22)
    createLine(1.22, -PITCH_WIDTH/2, 1.22, PITCH_WIDTH/2, creaseMat);

    // Stumps
    stumpsGroup = new THREE.Group();
    pitchGroup.add(stumpsGroup);
    createStumps(0); // Batting end
    createStumps(PITCH_LENGTH); // Bowling end

      window.addEventListener('resize', onWindowResize, false);

      if (currentData && currentData.points && currentData.points.length >= 2) {
        updateTrajectory(currentData);
      }

      if (window.hawkeye) {
        window.hawkeye.isReady = true;
      }
      postBridge('ready', { ok: true });

      animate();
    } catch (e) {
      postBridge('error', { message: String(e) });
    }
  }

  function createLine(x1, z1, x2, z2, material) {
    const points = [];
    points.push(new THREE.Vector3(x1, 0.02, z1));
    points.push(new THREE.Vector3(x2, 0.02, z2));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, material);
    if (pitchGroup) pitchGroup.add(line);
  }

  function createStumps(xPos) {
    const stumpMat = new THREE.MeshStandardMaterial({ 
      color: 0xe0b080, 
      roughness: 0.5,
      metalness: 0.1
    });
    for(let i=-1; i<=1; i++) {
        const zPos = i * STUMP_SPACING;
        const geometry = new THREE.CylinderGeometry(STUMP_RADIUS, STUMP_RADIUS, STUMP_HEIGHT, 16);
        const stump = new THREE.Mesh(geometry, stumpMat);
        stump.position.set(xPos, STUMP_HEIGHT/2, zPos);
        stump.castShadow = true;
        stump.receiveShadow = true;
        stumpsGroup.add(stump);
    }
    // Bails
    const bailGeo = new THREE.CylinderGeometry(0.01, 0.01, STUMP_SPACING * 2, 8);
    const bail = new THREE.Mesh(bailGeo, stumpMat);
    bail.rotation.x = Math.PI / 2;
    bail.position.set(xPos, STUMP_HEIGHT + 0.01, 0);
    bail.castShadow = true;
    stumpsGroup.add(bail);
  }

  function onWindowResize() {
    const container = document.getElementById('container');
    if (!container || !camera || !renderer) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  }

  function animate() {
    requestAnimationFrame(animate);
    if (controls) controls.update();
    if (anim && anim.curve && ballMesh) {
      const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      const t = (now - anim.startMs) / anim.durationMs;
      if (t >= 1) {
        ballMesh.position.copy(anim.curve.getPoint(1));
        anim = null;
      } else if (t >= 0) {
        ballMesh.position.copy(anim.curve.getPoint(t));
      }
    }
    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  function updateTrajectory(data) {
    currentData = data;

    // If Flutter calls us before init() completes, keep the payload and bail.
    if (!scene || !camera || !renderer) return;
    
    applyPose(data && data.pose);

    // Clear previous trajectory
    if (ballPathGroup && worldGroup) {
      worldGroup.remove(ballPathGroup);
      ballPathGroup = null;
    }
    if (bounceMarker && worldGroup) {
      worldGroup.remove(bounceMarker);
      bounceMarker = null;
    }
    if (impactMarker && worldGroup) {
      worldGroup.remove(impactMarker);
      impactMarker = null;
    }

    if (!data || !data.points || data.points.length < 2) {
      updateDecision(null);
      if (ballMesh) ballMesh.visible = false;
      anim = null;
      if (ballPathGroup) {
        scene.remove(ballPathGroup);
        ballPathGroup = null;
      }
      if (bounceMarker) {
        scene.remove(bounceMarker);
        bounceMarker = null;
      }
      if (impactMarker) {
        scene.remove(impactMarker);
        impactMarker = null;
      }
      return;
    }

    // Convert points: x->x, y->z, z->y
    const pts = data.points.map(p => new THREE.Vector3(p.x, p.z, p.y));
    
    const bounceIndex = clampIndex(data.bounceIndex, 0, pts.length - 1);
    const impactIndex = clampIndex(data.impactIndex, pts.length - 1, pts.length - 1);

    ballPathGroup = new THREE.Group();

    // 1. Start to Bounce
    if (bounceIndex > 0) {
        const points1 = pts.slice(0, bounceIndex + 1);
        const line1 = createTube(points1, 0x3b82f6);
        ballPathGroup.add(line1);
    }

    // 2. Bounce to Impact
    if (impactIndex > bounceIndex) {
        const points2 = pts.slice(bounceIndex, impactIndex + 1);
        const line2 = createTube(points2, 0x22c55e);
        ballPathGroup.add(line2);
    }

    // 3. Impact to End (Predicted)
    if (impactIndex < pts.length - 1) {
        const points3 = pts.slice(impactIndex);
        // Make predicted path slightly transparent or dashed (dashed is hard with tubes, so just lighter color)
        const line3 = createTube(points3, 0xf59e0b, 0.6); 
        ballPathGroup.add(line3);
    }

    if (worldGroup) worldGroup.add(ballPathGroup);

    // Markers
    if (pts[bounceIndex]) {
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(0.07, 32, 32), 
          new THREE.MeshStandardMaterial({ 
            color: 0xef4444,
            roughness: 0.3,
            metalness: 0.1,
            emissive: 0xef4444,
            emissiveIntensity: 0.3
          })
        );
        sphere.position.copy(pts[bounceIndex]);
        sphere.castShadow = true;
        if (worldGroup) worldGroup.add(sphere);
        bounceMarker = sphere;
    }
    
    if (pts[impactIndex]) {
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(0.07, 32, 32), 
          new THREE.MeshStandardMaterial({ 
            color: 0x8b5cf6,
            roughness: 0.3,
            metalness: 0.1,
            emissive: 0x8b5cf6,
            emissiveIntensity: 0.3
          })
        );
        sphere.position.copy(pts[impactIndex]);
        sphere.castShadow = true;
        if (worldGroup) worldGroup.add(sphere);
        impactMarker = sphere;
    }

    updateDecision(data.decision);

    const wantsAnim = !!data.animate;
    if (wantsAnim) {
      if (!ballMesh) {
        ballMesh = new THREE.Mesh(
          new THREE.SphereGeometry(0.055, 32, 32),
          new THREE.MeshStandardMaterial({ 
            color: 0xffffff,
            roughness: 0.2,
            metalness: 0.1,
            emissive: 0xffffff,
            emissiveIntensity: 0.1
          })
        );
        ballMesh.castShadow = true;
        if (worldGroup) worldGroup.add(ballMesh);
      }
      const curve = new THREE.CatmullRomCurve3(pts);
      ballMesh.visible = true;
      ballMesh.position.copy(curve.getPoint(0));
      anim = { curve: curve, startMs: (typeof performance !== 'undefined' ? performance.now() : Date.now()), durationMs: 1500 };
    } else {
      if (ballMesh) ballMesh.visible = false;
      anim = null;
    }
  }

  function createTube(points, color, opacity = 1.0) {
      if (points.length < 2) return new THREE.Object3D();
      const curve = new THREE.CatmullRomCurve3(points);
      const geometry = new THREE.TubeGeometry(curve, points.length * 4, 0.04, 12, false);
      const material = new THREE.MeshStandardMaterial({ 
          color: color, 
          transparent: opacity < 1.0, 
          opacity: opacity,
          roughness: 0.4,
          metalness: 0.2,
          emissive: color,
          emissiveIntensity: 0.2
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      return mesh;
  }

  function toRad(value) {
    const n = Number(value);
    if (!isFinite(n)) return 0;
    return n * Math.PI / 180;
  }

  function applyPose(pose) {
    if (!worldGroup) return;
    const yaw = toRad(pose && pose.yawDeg);
    const tilt = toRad(pose && pose.tiltDeg);
    const roll = toRad(pose && pose.rollDeg);
    worldGroup.rotation.set(tilt, yaw, roll);
  }

  function updateDecision(decision) {
    const el = document.getElementById('decision');
    if (!el) return;
    el.className = '';
    el.style.display = 'none';

    if (decision === 'out') {
      el.textContent = 'OUT';
      el.className = 'out';
    } else if (decision === 'not_out') {
      el.textContent = 'NOT OUT';
      el.className = 'not-out';
    } else if (decision === 'umpires_call') {
      el.textContent = "UMPIRE'S CALL";
      el.className = 'umpires-call';
    }
  }

  window.hawkeye = { updateTrajectory: updateTrajectory, isReady: false };
  
  // Wait for Three.js to load if it hasn't yet (though script tag order should handle it)
  if (typeof THREE !== 'undefined') {
    init();
  } else {
    window.addEventListener('load', init);
  }

})();
