import { Text } from '@react-three/drei'
import { useMemo } from 'react'
import * as THREE from 'three'

import { athleteAnimation } from './athleteAnimation'
import type { Point3, Expression } from './athleteAnimation'
import type { Contact } from './presentation'
import type { AnimatedPlayer, Vec2 } from './replay'

const bone = new THREE.CylinderGeometry(1, 1, 1, 9)
const up = new THREE.Vector3(0, 1, 0)
const skinTones = ['#d8af8b', '#a36d53', '#c48d65', '#e0b998', '#845849', '#ba906f']
const hairTones = ['#252929', '#453026', '#211f24', '#604433', '#302b29']

function Segment({ a, b, radius, color }: { a: Point3; b: Point3; radius: number; color: string }) {
  const start = new THREE.Vector3(...a)
  const end = new THREE.Vector3(...b)
  const diff = end.clone().sub(start)
  const rotation = new THREE.Quaternion().setFromUnitVectors(up, diff.clone().normalize())
  return <mesh geometry={bone} dispose={null} position={start.add(end).multiplyScalar(0.5)} quaternion={rotation} scale={[radius, diff.length(), radius]} castShadow>
    <meshStandardMaterial color={color} roughness={0.88} />
  </mesh>
}

// All coordinates in the carrier's local space. The same mesh is used for
// hands, flight and loose-ball play so possession changes don't change shape.
export function FootyBall({ position = [0, 0, 0], rotation = [0, 0, 0] }: { position?: Point3; rotation?: Point3 }) {
  return <group position={position} rotation={rotation}>
    <mesh castShadow scale={[0.34, 0.19, 0.195]}><sphereGeometry args={[1, 20, 12]} /><meshStandardMaterial color="#b46a3f" roughness={0.79} /></mesh>
    {[-0.24, 0.24].map((x) => <mesh key={x} position={[x, 0, 0]} rotation={[0, 0, Math.PI / 2]} scale={[0.193, 0.013, 0.198]}><torusGeometry args={[1, 0.05, 4, 24]} /><meshStandardMaterial color="#f5e7ca" /></mesh>)}
    <mesh position={[0, 0.187, 0]}><boxGeometry args={[0.24, 0.008, 0.02]} /><meshBasicMaterial color="#f8e7d4" /></mesh>
    {[-0.07, 0, 0.07].map((x) => <mesh key={x} position={[x, 0.194, 0]}><boxGeometry args={[0.012, 0.009, 0.085]} /><meshBasicMaterial color="#f8e7d4" /></mesh>)}
  </group>
}

function Face({ expression, effort, variant, skin, hair, time }: { expression: Expression; effort: number; variant: number; skin: string; hair: string; time: number }) {
  const blink = Math.sin(time * 1.8 + variant * 7.7) > 0.992
  const straining = expression === 'kicking' || expression === 'tackling' || expression === 'handballing' || expression === 'contesting' || expression === 'bumping' || expression === 'jostling' || expression === 'protecting'
  const catching = expression === 'catching' || expression === 'contesting'
  const running = expression === 'jogging' || expression === 'sprinting'
  const eyeHeight = blink ? 0.012 : straining ? 0.027 : running ? 0.045 - effort * 0.02 : 0.048 - effort * 0.014
  const browTilt = expression === 'tackling' ? 0.42 : expression === 'kicking' ? 0.31 :
    expression === 'handballing' ? 0.21 : catching ? -0.22 : running ? 0.05 + effort * 0.21 : expression === 'carrying' ? 0.11 + effort * 0.13 : 0
  const mouthOpen = catching || expression === 'tackling' || expression === 'handballing' || expression === 'bumping' || expression === 'jostling' || running
  const mouthHeight = running ? 0.017 + effort * 0.053 : mouthOpen ? (expression === 'tackling' ? 0.075 : 0.048) : 0.012
  return <group position={[0.025, 2.18, 0]}>
    <mesh scale={[0.96 + variant % 3 * 0.045, 1, 0.94 + variant % 2 * 0.055]} castShadow><sphereGeometry args={[0.278, 16, 12]} /><meshStandardMaterial color={skin} roughness={0.91} /></mesh>
    <mesh position={[-0.035, 0.15, 0]} scale={[0.29, 0.17 + variant % 2 * 0.035, 0.285]} castShadow><sphereGeometry args={[1, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.55]} /><meshStandardMaterial color={hair} roughness={0.99} /></mesh>
    <mesh position={[0.242, 0.005, 0]} scale={[0.075, 0.07, 0.053]}><sphereGeometry args={[1, 10, 8]} /><meshStandardMaterial color={skin} /></mesh>
    {[-1, 1].map((side) => <group key={side}>
      <mesh position={[0.227, 0.035, side * 0.125]} scale={[0.017, eyeHeight, 0.031]}><sphereGeometry args={[1, 9, 8]} /><meshStandardMaterial color="#242b2c" /></mesh>
      <mesh position={[0.224, 0.132 + (catching ? 0.023 : 0), side * 0.127]} rotation={[side * browTilt, 0, 0]} scale={[0.021, 0.015, 0.087]}><boxGeometry args={[1, 1, 1]} /><meshStandardMaterial color={hair} /></mesh>
      <mesh position={[-0.003, -0.016, side * 0.275]} scale={[0.047, 0.072, 0.038]}><sphereGeometry args={[1, 8, 8]} /><meshStandardMaterial color={skin} /></mesh>
    </group>)}
    <mesh position={[0.260, -0.104, 0]} scale={[0.016, mouthHeight, straining && !mouthOpen ? 0.086 : 0.055]}><sphereGeometry args={[1, 10, 8]} /><meshStandardMaterial color={mouthOpen ? '#553832' : '#75504a'} /></mesh>
    {straining && !mouthOpen && <mesh position={[0.276, -0.106, 0]} scale={[0.008, 0.008, 0.068]}><boxGeometry args={[1, 1, 1]} /><meshBasicMaterial color="#f4e2cc" /></mesh>}
  </group>
}

const spot = (point: Vec2): Point3 => [point[0] - 70, 0, point[1]]
const relativeTo = (point: Point3, y: number): Point3 => [point[0], point[1] - y, point[2]]

export default function Athlete({ player, renderPos, contact, time, hasBall, selected, onSelect }: { player: AnimatedPlayer; renderPos: Vec2; contact: Contact | null; time: number; hasBall: boolean; selected: boolean; onSelect: (id: string) => void }) {
  const state = athleteAnimation(player, time, hasBall, contact)
  const variant = Number(player.id.slice(1)) + (player.id[0] === 'A' ? 0 : 8)
  const skin = skinTones[(variant * 7) % skinTones.length]
  const hair = hairTones[(variant * 3) % hairTones.length]
  const isA = player.id[0] === 'A'
  const jersey = isA ? '#ed9e59' : '#c7dce3'
  const shorts = isA ? '#253c53' : '#233e50'
  const socks = isA ? '#e8ad70' : '#e8ede8'
  const bodyStripe = isA ? '#254159' : '#468098'
  const face = useMemo(() => ({ skin, hair }), [skin, hair])
  const waist = 1.05 - state.crouch

  return <group position={spot([renderPos[0] + state.leap[0], renderPos[1] + state.leap[1]])} rotation={[0, -state.heading, 0]} onClick={(event) => { event.stopPropagation(); onSelect(player.id) }}>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.035, 0]}><circleGeometry args={[selected ? 1.45 : 0.92, 24]} /><meshBasicMaterial color={selected ? '#ffe4a3' : '#000000'} transparent opacity={selected ? 0.35 : 0.16} depthWrite={false} /></mesh>
    {selected && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.055, 0]}><ringGeometry args={[1.25, 1.32, 40]} /><meshBasicMaterial color="#fff2bf" /></mesh>}
    <group position={[0, state.bob + state.jump, 0]}>
      {state.limbs.map((limb, index) => <group key={index}>
        <Segment a={limb.hip} b={limb.knee} radius={0.18} color={skin} />
        <Segment a={limb.knee} b={limb.foot} radius={0.13} color={socks} />
        <mesh position={limb.knee} castShadow><sphereGeometry args={[0.14, 10, 8]} /><meshStandardMaterial color={skin} /></mesh>
        <mesh position={[limb.foot[0] + 0.13, limb.foot[1] - 0.08, limb.foot[2]]} castShadow scale={[0.42, 0.16, 0.25]}><sphereGeometry args={[1, 12, 8]} /><meshStandardMaterial color={isA ? '#f2bd7c' : '#f4eee3'} roughness={0.75} /></mesh>
      </group>)}
      <group position={[0, waist, 0]} rotation={[state.roll, state.twist, state.lean]}>
        {state.limbs.map((limb, index) => <group key={index}>
          <Segment a={relativeTo(limb.shoulder, waist)} b={relativeTo(limb.elbow, waist)} radius={0.153} color={jersey} />
          <Segment a={relativeTo(limb.elbow, waist)} b={relativeTo(limb.hand, waist)} radius={0.113} color={skin} />
          <mesh position={relativeTo(limb.elbow, waist)}><sphereGeometry args={[0.11, 10, 8]} /><meshStandardMaterial color={skin} /></mesh>
          <mesh position={relativeTo(limb.hand, waist)} scale={[0.14, 0.095, 0.13]}><sphereGeometry args={[1, 10, 8]} /><meshStandardMaterial color={skin} /></mesh>
        </group>)}
        <mesh position={[0, 0.03, 0]} castShadow scale={[0.34, 0.19, 0.36]}><sphereGeometry args={[1, 12, 10]} /><meshStandardMaterial color={shorts} /></mesh>
        <mesh position={[0, 0.38, 0]} castShadow scale={[0.36, 0.48, 0.37]}><sphereGeometry args={[1, 16, 12]} /><meshStandardMaterial color={jersey} roughness={0.84} /></mesh>
        {[-1, 1].map((side) => <mesh key={side} position={[0, 0.37, side * 0.346]} scale={[0.28, 0.35, 0.034]}><sphereGeometry args={[1, 10, 10]} /><meshStandardMaterial color={bodyStripe} roughness={0.8} /></mesh>)}
        <mesh position={[0, 0.78, 0]}><cylinderGeometry args={[0.13, 0.15, 0.22, 10]} /><meshStandardMaterial color={skin} /></mesh>
        <group position={[0, -state.crouch - waist, 0]}><Face expression={state.expression} effort={state.sprint} variant={variant} skin={face.skin} hair={face.hair} time={time} /></group>
        <Text position={[-0.356, 0.38, 0]} rotation={[0, -Math.PI / 2, 0]} fontSize={0.30} color={isA ? '#20364c' : '#1e4151'} fontWeight={700}>{player.id.slice(1)}</Text>
        {hasBall && <FootyBall position={relativeTo(state.ball, waist)} rotation={[0, 0, -0.12]} />}
      </group>
    </group>
    {(selected || hasBall) && <Text position={[0, 3.0, 0]} fontSize={0.72} color="#fff6d9" outlineWidth={0.045} outlineColor="#14242b" anchorX="center">{player.id}{selected ? `  ·  ${state.pace.toUpperCase()}` : '  ●'}</Text>}
  </group>
}
