import * as THREE from 'three'

import type { Vec2 } from './replay'

export const ON_BALL_OFFSET = new THREE.Vector3(7.5, 6.8, 9.5)

export function ballCameraTarget(position: Vec2, height: number): THREE.Vector3 {
  return new THREE.Vector3(position[0] - 70, height, position[1])
}

// Move both the orbit target and camera by the same delta. This follows the
// ball without changing the angle or zoom chosen by the viewer.
export function followBallTarget(camera: THREE.Camera, orbitTarget: THREE.Vector3, ball: THREE.Vector3): void {
  camera.position.add(ball.clone().sub(orbitTarget))
  orbitTarget.copy(ball)
}
