import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls, PerspectiveCamera, Text } from '@react-three/drei'
import { memo, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

import Athlete, { FootyBall } from './Athlete'
import { athleteAnimation } from './athleteAnimation'
import { ballCameraTarget, followBallTarget, ON_BALL_OFFSET } from './camera'
import { stagePlayers } from './presentation'
import { flightTrail, poseAt, type Pose, type Replay, type Vec2 } from './replay'

type View = 'broadcast' | 'free' | 'aerial' | 'onball'

const spot = (point: Vec2, height = 0): [number, number, number] => [point[0] - 70, height, point[1]]

function OvalLine({ rx, rz, y = 0.06, color = '#eff4db', opacity = 0.8, width = 1.3 }: { rx: number; rz: number; y?: number; color?: string; opacity?: number; width?: number }) {
  const points = useMemo(() => Array.from({ length: 129 }, (_, i) => {
    const a = i * Math.PI * 2 / 128
    return [Math.cos(a) * rx, y, Math.sin(a) * rz] as [number, number, number]
  }), [rx, rz, y])
  return <Line points={points} color={color} transparent opacity={opacity} lineWidth={width} />
}

const Field = memo(function Field({ rules }: { rules: Replay['header']['rules'] }) {
  const grass = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 512
    canvas.height = 512
    const context = canvas.getContext('2d')!
    context.fillStyle = '#426f39'
    context.fillRect(0, 0, 512, 512)
    for (let i = 0; i < 512; i += 32) {
      context.fillStyle = i % 64 === 0 ? '#476f3e' : '#3e6838'
      context.fillRect(i, 0, 32, 512)
    }
    let seed = 271
    for (let i = 0; i < 16000; i++) {
      seed = (seed * 1664525 + 1013904223) >>> 0
      const x = seed % 512
      seed = (seed * 1664525 + 1013904223) >>> 0
      context.fillStyle = i % 2 ? '#77935d22' : '#142c1922'
      context.fillRect(x, seed % 512, 2, 2)
    }
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.anisotropy = 8
    return texture
  }, [])
  const square = rules.centre_square / 2
  return <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} scale={[rules.length / 2, rules.width / 2, 1]} receiveShadow>
      <circleGeometry args={[1, 128]} />
      <meshStandardMaterial map={grass} roughness={1} side={THREE.DoubleSide} />
    </mesh>
    <OvalLine rx={rules.length / 2 - 0.7} rz={rules.width / 2 - 0.7} width={2.2} />
    <Line points={[[0, 0.09, -square], [0, 0.09, square]]} color="#e5eacb" transparent opacity={0.8} />
    <Line points={[[ -square, 0.09, -square], [square, 0.09, -square], [square, 0.09, square], [-square, 0.09, square], [-square, 0.09, -square]]} color="#e5eacb" transparent opacity={0.75} />
    <OvalLine rx={rules.centre_circle_radius} rz={rules.centre_circle_radius} y={0.1} />
    {[-1, 1].map((side) => {
      const arc = Array.from({ length: 81 }, (_, i) => {
        const a = -Math.PI / 2 + i * Math.PI / 80
        return [side * (70 - rules.arc_radius * Math.cos(a)), 0.1, rules.arc_radius * Math.sin(a)] as [number, number, number]
      }).filter(([x, , z]) => (x / 69.3) ** 2 + (z / 49.3) ** 2 <= 1)
      return <group key={side}>
        <Line points={arc} color="#f2ebc8" transparent opacity={0.78} lineWidth={1.6} />
        <Line points={[[side * 61, 0.1, -rules.behind_half_width], [side * 61, 0.1, rules.behind_half_width]]} color="#eee8ce" />
        <Line points={[[side * 61, 0.1, -rules.behind_half_width], [side * 70, 0.1, -rules.behind_half_width]]} color="#eee8ce" />
        <Line points={[[side * 61, 0.1, rules.behind_half_width], [side * 70, 0.1, rules.behind_half_width]]} color="#eee8ce" />
        {[-rules.behind_half_width, -rules.goal_half_width, rules.goal_half_width, rules.behind_half_width].map((z, i) =>
          <mesh key={z} position={[side * 70, i === 0 || i === 3 ? 2.75 : 4.5, z]} castShadow>
            <cylinderGeometry args={[0.13, 0.17, i === 0 || i === 3 ? 5.5 : 9, 12]} />
            <meshStandardMaterial color="#f6f3e8" metalness={0.18} roughness={0.4} />
          </mesh>,
        )}
      </group>
    })}
    <Text position={[0, 0.12, -37]} rotation={[-Math.PI / 2, 0, 0]} fontSize={3.2} color="#ffffff" fillOpacity={0.45} anchorX="center">THE OVAL  /  MATCHDAY</Text>
  </group>
})

const Stadium = memo(function Stadium() {
  const crowd = useMemo(() => {
    const positions: number[] = []
    const colors: number[] = []
    const palette = ['#c9d1b8', '#7a9db0', '#b9a887', '#364c61', '#dfa971', '#d4d8d5']
    for (let i = 0; i < 5000; i++) {
      const angle = i * 2.399963229728653
      const row = 1 + (i % 16)
      const rx = 75 + row * 1.45
      const rz = 54 + row * 1.2
      positions.push(Math.cos(angle) * rx, 1.4 + row * 0.61, Math.sin(angle) * rz)
      const color = new THREE.Color(palette[(i * 17 + Math.floor(i / 7)) % palette.length])
      colors.push(color.r, color.g, color.b)
    }
    return { positions: new Float32Array(positions), colors: new Float32Array(colors) }
  }, [])
  const geometry = useMemo(() => new THREE.BufferGeometry()
    .setAttribute('position', new THREE.BufferAttribute(crowd.positions, 3))
    .setAttribute('color', new THREE.BufferAttribute(crowd.colors, 3)), [crowd])
  return <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.45, 0]} receiveShadow>
      <planeGeometry args={[330, 260]} />
      <meshStandardMaterial color="#121f24" roughness={1} />
    </mesh>
    {[0, 1, 2, 3, 4, 5, 6].map((step) =>
      <OvalLine key={step} rx={74 + step * 4.2} rz={53 + step * 3.55} y={0.1 + step * 1.7} color={step === 0 ? '#ddcba1' : step % 2 ? '#1d3940' : '#416068'} opacity={1} width={step === 0 ? 4 : 6} />,
    )}
    <points geometry={geometry}>
      <pointsMaterial size={0.75} vertexColors sizeAttenuation />
    </points>
    <OvalLine rx={101} rz={77} y={13.5} color="#d6b47d" opacity={0.65} width={2.5} />
    {[-1, 1].flatMap((x) => [-1, 1].map((z) =>
      <group key={`${x}-${z}`} position={[x * 94, 0, z * 66]}>
        <mesh position={[0, 15, 0]}><cylinderGeometry args={[0.28, 0.48, 30, 8]} /><meshStandardMaterial color="#596873" metalness={0.65} /></mesh>
        <mesh position={[0, 30, 0]} rotation={[0, Math.atan2(-x, -z), -0.17]}><boxGeometry args={[11, 2.2, 3]} /><meshStandardMaterial color="#d6dbcf" emissive="#a1b3c0" emissiveIntensity={0.45} /></mesh>
        <pointLight position={[0, 28, 0]} intensity={38} distance={115} color="#fff2cf" />
      </group>,
    ))}
  </group>
})

function CameraDirector({ view, focus, ball, onCameraBasis }: { view: View; focus: Vec2; ball: Pose['ball']; onCameraBasis?: (right: Vec2, forward: Vec2) => void }) {
  const { camera } = useThree()
  const controls = useRef<OrbitControlsImpl>(null)
  const previousView = useRef<View>('broadcast')
  const direction = useMemo(() => new THREE.Vector3(), [])
  const right = useMemo(() => new THREE.Vector3(), [])
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), [])
  useFrame((_, delta) => {
    if (view === 'onball') {
      const target = ballCameraTarget(ball.position, ball.height)
      if (controls.current) {
        if (previousView.current !== 'onball') {
          controls.current.target.copy(target)
          camera.position.copy(target).add(ON_BALL_OFFSET)
        } else {
          followBallTarget(camera, controls.current.target, target)
        }
        controls.current.update()
      }
      if (onCameraBasis) {
        camera.getWorldDirection(direction)
        right.crossVectors(direction, up).normalize()
        const ground = Math.hypot(direction.x, direction.z) || 1
        onCameraBasis([right.x, right.z], [direction.x / ground, direction.z / ground])
      }
      previousView.current = view
      return
    }
    previousView.current = view
    if (view === 'free') return
    const ease = 1 - Math.exp(-delta * 2.2)
    const x = focus[0] - 70
    const z = focus[1]
    const target = view === 'aerial' ? new THREE.Vector3(0, 0, 0) : new THREE.Vector3(x * 0.82, 0, z * 0.75)
    const desired = view === 'aerial'
      ? new THREE.Vector3(0, 132, 75)
      : new THREE.Vector3(THREE.MathUtils.clamp(x + 25, -67, 78), 53, THREE.MathUtils.clamp(z + 62, 30, 94))
    camera.position.lerp(desired, ease)
    controls.current?.target.lerp(target, ease)
    controls.current?.update()
    if (onCameraBasis) {
      camera.getWorldDirection(direction)
      right.crossVectors(direction, up).normalize()
      const ground = Math.hypot(direction.x, direction.z) || 1
      onCameraBasis([right.x, right.z], [direction.x / ground, direction.z / ground])
    }
  })
  return <>
    <PerspectiveCamera makeDefault position={[30, 62, 85]} fov={48} near={0.1} far={700} />
    <OrbitControls ref={controls} enabled={view === 'free' || view === 'onball'} enablePan={view === 'free'} enableDamping dampingFactor={0.08} minDistance={view === 'onball' ? 4 : 10} maxDistance={view === 'onball' ? 42 : 230} maxPolarAngle={Math.PI / 2.04} />
  </>
}

export default function ReplayScene({ replay, pose, view, selected, onSelect, onCameraBasis }: { replay: Replay; pose: Pose; view: View; selected: string | null; onSelect: (id: string) => void; onCameraBasis?: (right: Vec2, forward: Vec2) => void }) {
  const staged = useMemo(() => stagePlayers(pose.players, pose.ball.owner), [pose.players, pose.ball.owner])
  const holder = staged.find(({ player }) => player.id === pose.ball.owner)
  let visibleBall = holder ? { ...pose.ball, position: holder.position } : pose.ball
  const next = replay.frames[pose.index + 1]
  const catchArrival = useMemo(() => {
    if (pose.ball.state !== 'flight' || pose.ball.flight?.kind !== 'kick' || next?.state.ball.state !== 'held' || next.trigger === 'kick-in') return null
    const winnerPose = poseAt(replay, next.t)
    const winner = stagePlayers(winnerPose.players, winnerPose.ball.owner).find(({ player }) => player.id === next.state.ball.owner)
    if (winner?.player.action?.kind === 'catch' && winner.player.action.airborne) {
      const state = athleteAnimation(winner.player, next.t, true, winner.contact)
      const waist = 1.05 - state.crouch
      const local = new THREE.Vector3(state.ball[0], state.ball[1] - waist, state.ball[2])
        .applyEuler(new THREE.Euler(state.roll, state.twist, state.lean))
        .add(new THREE.Vector3(0, waist + state.bob + state.jump, 0))
        .applyAxisAngle(new THREE.Vector3(0, 1, 0), -state.heading)
      return { position: [winner.position[0] + state.leap[0] + local.x, winner.position[1] + state.leap[1] + local.z] as Vec2, height: local.y }
    }
    return null
  }, [replay, pose.ball.state, pose.ball.flight?.kind, next])
  const approach = (ball: Pose['ball'], at: number) => {
    if (!catchArrival || !next || at < next.t - 0.25) return ball
    const weight = THREE.MathUtils.smoothstep(at, next.t - 0.25, next.t)
    return { ...ball,
      position: [THREE.MathUtils.lerp(ball.position[0], catchArrival.position[0], weight), THREE.MathUtils.lerp(ball.position[1], catchArrival.position[1], weight)] as Vec2,
      height: THREE.MathUtils.lerp(ball.height, catchArrival.height, weight) }
  }
  visibleBall = approach(visibleBall, pose.time)
  const trail = flightTrail(replay, pose).map(({ position, height, time }) => {
    const sample = approach({ ...pose.ball, position, height }, time)
    return spot(sample.position, sample.height)
  })
  const focus = selected ? staged.find(({ player }) => player.id === selected)?.position ?? visibleBall.position : visibleBall.position
  return <Canvas shadows dpr={[1, 1.7]} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }} onPointerMissed={() => onSelect('')}>
    <color attach="background" args={['#111f2c']} />
    <fog attach="fog" args={['#1c3542', 135, 350]} />
    <ambientLight intensity={1.6} color="#dbe8e9" />
    <hemisphereLight args={['#b9dcf4', '#47672f', 2.1]} />
    <directionalLight position={[-35, 75, 35]} intensity={3.1} color="#ffe6b5" castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-105} shadow-camera-right={105} shadow-camera-top={85} shadow-camera-bottom={-85} shadow-bias={-0.0003} />
    <Stadium />
    <Field rules={replay.header.rules} />
    {staged.map(({ player, position, contact }) => <Athlete key={player.id} player={player} renderPos={position} contact={contact} time={pose.time} selected={selected === player.id} hasBall={pose.ball.owner === player.id} onSelect={onSelect} />)}
    {pose.ball.state !== 'held' && <group position={spot(visibleBall.position, visibleBall.height)}>
      <FootyBall rotation={[pose.time * 2, pose.time * 3, 0]} />
      {pose.ball.state === 'flight' && <pointLight intensity={0.8} distance={4} color="#ffc788" />}
    </group>}
    {trail.slice(1).map((point, i) => <Line key={i} points={[trail[i], point]}
      color="#f3c98b" transparent opacity={0.05 + 0.62 * ((i + 1) / (trail.length - 1)) ** 1.5}
      lineWidth={1.2 + 2.2 * (i + 1) / (trail.length - 1)} />)}
    <CameraDirector view={view} focus={focus} ball={visibleBall} onCameraBasis={onCameraBasis} />
  </Canvas>
}
