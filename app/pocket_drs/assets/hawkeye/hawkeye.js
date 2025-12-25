// Hawk-Eye 3D Visualization using Three.js
(function() {
  'use strict';

  // Scene setup
  let scene, camera, renderer;
  let pitch, stumps = [], trajectory = null;
  let animationFrame = null;

  // Default dimensions (meters)
  const PITCH_LENGTH = 20.12;
  const PITCH_WIDTH = 3.05;
  const STUMP_HEIGHT = 0.71;
  const STUMP_SPACING = 0.057;

  function init() {
    const container = document.getElementById('container');
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);

    // Camera - positioned behind stumps looking down the pitch
    camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(-3, 2.5, 0);
    camera.lookAt(10, 0.5, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Lighting
    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambient);

    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(10, 20, 5);
    scene.add(directional);

    // Create pitch
    createPitch();
    createStumps();
    createCreaseLines();

    // Handle resize
    window.addEventListener('resize', onResize);

    // Start render loop
    animate();
  }

  function createPitch() {
    const geometry = new THREE.PlaneGeometry(PITCH_LENGTH, PITCH_WIDTH);
    const material = new THREE.MeshLambertMaterial({ 
      color: 0x2d5016,
      side: THREE.DoubleSide
    });
    pitch = new THREE.Mesh(geometry, material);
    pitch.rotation.x = -Math.PI / 2;
    pitch.rotation.z = Math.PI / 2;
    pitch.position.set(PITCH_LENGTH / 2, 0, 0);
    scene.add(pitch);

    // Ground plane (darker)
    const groundGeometry = new THREE.PlaneGeometry(50, 20);
    const groundMaterial = new THREE.MeshLambertMaterial({ color: 0x1a3d0a });
    const ground = new THREE.Mesh(groundGeometry, groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(10, -0.01, 0);
    scene.add(ground);
  }

  function createStumps() {
    const stumpGeometry = new THREE.CylinderGeometry(0.015, 0.015, STUMP_HEIGHT, 8);
    const stumpMaterial = new THREE.MeshLambertMaterial({ color: 0xd4a574 });
    const bailGeometry = new THREE.CylinderGeometry(0.008, 0.008, STUMP_SPACING * 2, 6);
    const bailMaterial = new THREE.MeshLambertMaterial({ color: 0xd4a574 });

    // Create 3 stumps
    for (let i = -1; i <= 1; i++) {
      const stump = new THREE.Mesh(stumpGeometry, stumpMaterial);
      stump.position.set(0, STUMP_HEIGHT / 2, i * STUMP_SPACING);
      scene.add(stump);
      stumps.push(stump);
    }

    // Bails
    const bail = new THREE.Mesh(bailGeometry, bailMaterial);
    bail.rotation.x = Math.PI / 2;
    bail.position.set(0, STUMP_HEIGHT + 0.02, 0);
    scene.add(bail);
  }

  function createCreaseLines() {
    const lineMaterial = new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 });
    
    // Popping crease at stumps
    const creasePoints = [
      new THREE.Vector3(0, 0.01, -PITCH_WIDTH / 2),
      new THREE.Vector3(0, 0.01, PITCH_WIDTH / 2)
    ];
    const creaseGeometry = new THREE.BufferGeometry().setFromPoints(creasePoints);
    const crease = new THREE.Line(creaseGeometry, lineMaterial);
    scene.add(crease);

    // Far crease
    const farCreasePoints = [
      new THREE.Vector3(PITCH_LENGTH, 0.01, -PITCH_WIDTH / 2),
      new THREE.Vector3(PITCH_LENGTH, 0.01, PITCH_WIDTH / 2)
    ];
    const farCreaseGeometry = new THREE.BufferGeometry().setFromPoints(farCreasePoints);
    const farCrease = new THREE.Line(farCreaseGeometry, lineMaterial);
    scene.add(farCrease);
  }

  function updateTrajectory(data) {
    // Remove old trajectory
    if (trajectory) {
      scene.remove(trajectory);
      trajectory = null;
    }

    if (!data || !data.points || data.points.length < 2) return;

    const { points, bounceIndex, impactIndex, decision } = data;

    // Create trajectory line with color segments
    const group = new THREE.Group();

    // Pre-bounce (blue)
    if (bounceIndex > 0) {
      const preBounce = points.slice(0, bounceIndex + 1);
      const line = createSegment(preBounce, 0x3b82f6);
      group.add(line);
    }

    // Post-bounce to impact (green)
    if (impactIndex > bounceIndex) {
      const postBounce = points.slice(Math.max(0, bounceIndex), impactIndex + 1);
      const line = createSegment(postBounce, 0x22c55e);
      group.add(line);
    }

    // Prediction to stumps (orange)
    if (points.length > impactIndex + 1) {
      const prediction = points.slice(impactIndex);
      const line = createSegment(prediction, 0xf59e0b);
      group.add(line);
    }

    // Add markers
    if (bounceIndex >= 0 && bounceIndex < points.length) {
      group.add(createMarker(points[bounceIndex], 0xef4444));
    }
    if (impactIndex >= 0 && impactIndex < points.length) {
      group.add(createMarker(points[impactIndex], 0x8b5cf6));
    }
    if (points.length > 0) {
      const last = points[points.length - 1];
      if (last.x <= 0.5) {
        group.add(createMarker(last, 0xf59e0b));
      }
    }

    scene.add(group);
    trajectory = group;

    // Update decision display
    updateDecision(decision);
  }

  function createSegment(points, color) {
    const curve = [];
    for (const p of points) {
      curve.push(new THREE.Vector3(p.x, p.z, p.y));
    }
    
    const geometry = new THREE.BufferGeometry().setFromPoints(curve);
    const material = new THREE.LineBasicMaterial({ color: color, linewidth: 3 });
    return new THREE.Line(geometry, material);
  }

  function createMarker(point, color) {
    const geometry = new THREE.SphereGeometry(0.04, 16, 16);
    const material = new THREE.MeshBasicMaterial({ color: color });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.set(point.x, point.z, point.y);
    return sphere;
  }

  function updateDecision(decision) {
    const el = document.getElementById('decision');
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

  function onResize() {
    const container = document.getElementById('container');
    const width = container.clientWidth;
    const height = container.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  function animate() {
    animationFrame = requestAnimationFrame(animate);
    renderer.render(scene, camera);
  }

  // Expose API to Flutter
  window.hawkeye = {
    updateTrajectory: updateTrajectory
  };

  // Initialize on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
