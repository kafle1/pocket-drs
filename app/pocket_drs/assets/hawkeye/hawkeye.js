// Hawk-Eye visualization using Three.js
(function () {
  'use strict';

  let scene, camera, renderer;
  let ballPathGroup, bounceMarker, impactMarker;
  let stumpsGroup;
  let currentData = null;

  // Constants (meters)
  const PITCH_LENGTH = 20.12;
  const PITCH_WIDTH = 3.05;
  const STUMP_HEIGHT = 0.71;
  const STUMP_RADIUS = 0.02; 
  const STUMP_SPACING = 0.057; 

  function init() {
    const container = document.getElementById('container');
    if (!container) return;
    const w = container.clientWidth;
    const h = container.clientHeight;

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);
    scene.fog = new THREE.Fog(0x0f172a, 10, 60);

    // Camera
    camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
    // Position: Behind the bowler (approx), looking at the batter's stumps (x=0)
    camera.position.set(PITCH_LENGTH + 4, 2.5, 0); 
    camera.lookAt(0, 0.5, 0);

    // Renderer
    const canvas = document.getElementById('canvas');
    renderer = new THREE.WebGLRenderer({ antialias: true, canvas: canvas });
    renderer.setSize(w, h);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
    dirLight.position.set(10, 20, 10);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 2048;
    dirLight.shadow.mapSize.height = 2048;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 50;
    dirLight.shadow.camera.left = -15;
    dirLight.shadow.camera.right = 15;
    dirLight.shadow.camera.top = 15;
    dirLight.shadow.camera.bottom = -15;
    scene.add(dirLight);

    // Ground
    const groundGeo = new THREE.PlaneGeometry(100, 100);
    const groundMat = new THREE.MeshStandardMaterial({ color: 0x12310b, roughness: 0.8 });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // Pitch
    const pitchGeo = new THREE.PlaneGeometry(PITCH_LENGTH, PITCH_WIDTH);
    const pitchMat = new THREE.MeshStandardMaterial({ color: 0x2d5016, roughness: 0.9 });
    const pitch = new THREE.Mesh(pitchGeo, pitchMat);
    pitch.rotation.x = -Math.PI / 2;
    pitch.position.set(PITCH_LENGTH / 2, 0.01, 0); 
    pitch.receiveShadow = true;
    scene.add(pitch);

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
    scene.add(stumpsGroup);
    createStumps(0); // Batting end
    createStumps(PITCH_LENGTH); // Bowling end

    window.addEventListener('resize', onWindowResize, false);
    
    animate();
  }

  function createLine(x1, z1, x2, z2, material) {
    const points = [];
    points.push(new THREE.Vector3(x1, 0.02, z1));
    points.push(new THREE.Vector3(x2, 0.02, z2));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, material);
    scene.add(line);
  }

  function createStumps(xPos) {
    const stumpMat = new THREE.MeshStandardMaterial({ color: 0xd4a574, roughness: 0.4 });
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
    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  function updateTrajectory(data) {
    currentData = data;
    
    // Clear previous trajectory
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

    if (!data || !data.points || data.points.length < 2) return;

    // Convert points: x->x, y->z, z->y
    const pts = data.points.map(p => new THREE.Vector3(p.x, p.z, p.y));
    
    const bounceIndex = Math.min(data.bounceIndex, pts.length - 1);
    const impactIndex = Math.min(data.impactIndex, pts.length - 1);

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

    scene.add(ballPathGroup);

    // Markers
    if (pts[bounceIndex]) {
        const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.06, 32, 32), new THREE.MeshStandardMaterial({ color: 0xef4444 }));
        sphere.position.copy(pts[bounceIndex]);
        sphere.castShadow = true;
        scene.add(sphere);
        bounceMarker = sphere;
    }
    
    if (pts[impactIndex]) {
        const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.06, 32, 32), new THREE.MeshStandardMaterial({ color: 0x8b5cf6 }));
        sphere.position.copy(pts[impactIndex]);
        sphere.castShadow = true;
        scene.add(sphere);
        impactMarker = sphere;
    }

    updateDecision(data.decision);
  }

  function createTube(points, color, opacity = 1.0) {
      if (points.length < 2) return new THREE.Object3D();
      const curve = new THREE.CatmullRomCurve3(points);
      const geometry = new THREE.TubeGeometry(curve, points.length * 4, 0.03, 8, false);
      const material = new THREE.MeshStandardMaterial({ 
          color: color, 
          transparent: opacity < 1.0, 
          opacity: opacity 
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      return mesh;
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

  window.hawkeye = { updateTrajectory: updateTrajectory };
  
  // Wait for Three.js to load if it hasn't yet (though script tag order should handle it)
  if (typeof THREE !== 'undefined') {
      init();
  } else {
      window.addEventListener('load', init);
  }

})();
