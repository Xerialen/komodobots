import * as THREE from "three";

// Quake is Z-up right-handed; three.js is Y-up right-handed.
// (x, y, z)_quake -> (x, z, -y)_three keeps handedness and yaw direction.
export function quakeToThree(x: number, y: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(x, z, -y);
}

export function setFromQuake(
  target: THREE.Vector3,
  x: number,
  y: number,
  z: number,
): THREE.Vector3 {
  return target.set(x, z, -y);
}
