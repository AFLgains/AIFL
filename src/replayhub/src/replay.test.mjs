import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import * as THREE from 'three'

import { athleteAnimation } from './athleteAnimation.ts'
import { ballCameraTarget, followBallTarget, ON_BALL_OFFSET } from './camera.ts'
import { crowdMix } from './crowdAudio.ts'
import { stagePlayers } from './presentation.ts'
import { flightTrail, frameAt, matchEvents, parseReplay, poseAt } from './replay.ts'

const player = (id, x) => ({ id, role: 'midfielder', pos: [x, 0], vel: [2, 0], energy: 1 })
const state = (a, b, ball, score = { A: 0, B: 0 }) => ({
  score,
  ball,
  team_A: [player('A1', a)],
  team_B: [player('B1', b)],
})
const loose = (x) => ({ state: 'loose', position: [x, 0], velocity: [0, 0], owner: null })
const header = { kind: 'header', seconds: 5, team_A: 'A', team_B: 'B', final_score: { A: 6, B: 0 }, rules: {} }
const frame = (k, t, trigger, snapshot) => ({ kind: 'decision', k, t, trigger, state: snapshot })

test('decision times, not rounded state times, drive interpolation and seeking', () => {
  const replay = parseReplay([header, frame(0, 0, 'start', state(0, 10, loose(0))), frame(1, 2.5, 'scheduled', state(5, 8, loose(5)))].map(JSON.stringify).join('\n'))
  assert.equal(frameAt(replay.frames, 2.499), 0)
  assert.equal(frameAt(replay.frames, 2.5), 1)
  assert.deepEqual(poseAt(replay, 1.25).players[0].pos, [2.5, 0])
  assert.deepEqual(poseAt(replay, 2.5).players[0].pos, [5, 0])
})

test('flight continues smoothly across scheduled snapshots', () => {
  const flight = (x, remaining) => ({ state: 'flight', position: [x, 0], velocity: [10, 0], owner: null, flight: { kind: 'kick', from: 'A1', lands_at: [20, 0], lands_in_s: remaining } })
  const replay = { header, frames: [frame(0, 0, 'kick', state(0, 10, flight(0, 2))), frame(1, 1, 'scheduled', state(2, 8, flight(10, 1))), frame(2, 2, 'loose ball', state(4, 6, loose(20)))] }
  assert.deepEqual(poseAt(replay, 1).ball.position, [10, 0])
  assert.deepEqual(poseAt(replay, 1.5).ball.position, [15, 0])
  assert.ok(Math.abs(poseAt(replay, 0.999).ball.height - poseAt(replay, 1.001).ball.height) < 0.1)
})

test('flight trails follow the sampled ball arc across decisions and stop at release', () => {
  const flight = (x, remaining) => ({ state: 'flight', position: [x, 0], velocity: [10, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [20, 0], lands_in_s: remaining } })
  const replay = parseReplay([header, frame(0, 0, 'possession', state(0, 10, { state: 'held', position: [0, 0], velocity: [0, 0], owner: 'A1' })),
    frame(1, 1, 'kick', state(0, 10, flight(0, 2))), frame(2, 2, 'scheduled', state(2, 8, flight(10, 1)))].map(JSON.stringify).join('\n'))
  const samples = flightTrail(replay, poseAt(replay, 2.02))
  assert.ok(samples.length > 5)
  assert.ok(samples[0].time >= 1.5)
  assert.deepEqual(samples.at(-1).position, poseAt(replay, 2.02).ball.position)
  assert.ok(samples.some(({ height }) => height > samples[0].height))
  assert.deepEqual(flightTrail(replay, poseAt(replay, 0.9)), [])
  const justReleased = flightTrail(replay, poseAt(replay, 1.1))
  assert.ok(justReleased.every(({ time }) => time >= 1))
  for (const sample of samples) {
    const expected = poseAt(replay, sample.time).ball
    assert.ok(Math.hypot(sample.position[0] - expected.position[0], sample.position[1] - expected.position[1]) < 0.001)
    assert.ok(Math.abs(sample.height - expected.height) < 0.001)
  }
})

test('scoring reset is a cut rather than a cross-field glide', () => {
  const replay = { header, frames: [frame(0, 0, 'kick', state(120, 110, loose(140))), frame(1, 1, 'ball-up', state(70, 67, loose(70), { A: 6, B: 0 }))] }
  assert.deepEqual(poseAt(replay, 0.9).players[0].pos, [120, 0])
  assert.deepEqual(poseAt(replay, 1).players[0].pos, [70, 0])
  assert.deepEqual(matchEvents(replay), [{ time: 1, team: 'A', label: 'Goal', points: 6 }])
})

test('supplied match parses and every decision yields a finite scene', async () => {
  const text = await readFile(new URL('../public/example_game_states_round36a_v_round26a.jsonl', import.meta.url), 'utf8')
  const replay = parseReplay(text)
  assert.equal(replay.frames.length, 338)
  assert.deepEqual(replay.frames.at(-1).state.score, { A: 20, B: 19 })
  assert.ok([...replay.cues.values()].some((cues) => cues.some((cue) => cue.kind === 'handball')))
  const visibleActions = new Set([...replay.cues.values()].flat().map((cue) => cue.kind))
  for (const kind of ['gather', 'catch', 'contest', 'bump']) assert.ok(visibleActions.has(kind), `${kind} must occur in the supplied match`)
  for (const frame of replay.frames) {
    const pose = poseAt(replay, frame.t)
    assert.equal(pose.players.length, 16)
    assert.ok(pose.players.every((player) => player.pos.every(Number.isFinite)))
    const staged = stagePlayers(pose.players, pose.ball.owner)
    assert.ok(staged.every(({ player, position }) => position.every(Number.isFinite) &&
      Math.hypot(position[0] - player.pos[0], position[1] - player.pos[1]) < 4))
    for (const player of pose.players) {
      const animation = athleteAnimation(player, frame.t, pose.ball.owner === player.id)
      assert.ok(Number.isFinite(animation.heading))
      assert.ok(animation.limbs.every((limb) => [limb.foot, limb.knee, limb.hand, limb.elbow].every((point) => point.every(Number.isFinite))))
    }
    assert.ok(pose.ball.position.every(Number.isFinite))
    assert.ok(Number.isFinite(pose.ball.height))
  }
})

test('the second selectable match loads with its own teams, events and final score', async () => {
  const text = await readFile(new URL('../public/golden_shower_cup_final_29970.jsonl', import.meta.url), 'utf8')
  const replay = parseReplay(text)
  assert.equal(replay.frames.length, 353)
  assert.equal(replay.header.team_A, 'community/golden_curry')
  assert.equal(replay.header.team_B, 'analyst/eagles/power_tweaked')
  assert.deepEqual(poseAt(replay, replay.header.seconds).score, { A: 19, B: 7 })
  assert.ok(matchEvents(replay).length > 0)
  assert.equal(poseAt(replay, 0).players.length, 16)
})

test('every handball in both matches gets a release cue and a continuous flight', async () => {
  let delayedReleases = 0
  for (const file of ['example_game_states_round36a_v_round26a.jsonl', 'golden_shower_cup_final_29970.jsonl']) {
    const replay = parseReplay(await readFile(new URL(`../public/${file}`, import.meta.url), 'utf8'))
    const starts = replay.frames.flatMap((frame, index) => {
      const ball = frame.state.ball
      if (ball.state !== 'flight' || ball.flight?.kind !== 'handball') return []
      const before = replay.frames[index - 1]?.state.ball
      if (before?.state === 'flight' && before.flight?.kind === 'handball' &&
        before.flight?.from === ball.flight.from &&
        JSON.stringify(before.flight?.lands_at) === JSON.stringify(ball.flight.lands_at)) return []
      return [index]
    })
    const cues = [...replay.cues.values()].flat().filter((cue) => cue.kind === 'handball')
    assert.ok(starts.length > 0)
    assert.equal(cues.length, starts.length + replay.hiddenHandballs.size)
    for (const index of starts) {
      const frame = replay.frames[index]
      const segment = replay.flightSegments.get(index)
      assert.ok(segment)
      assert.ok(segment.releaseTime <= frame.t)
      assert.ok(segment.releaseTime >= (replay.frames[index - 1]?.t ?? 0) - 1e-8)
      assert.ok(cues.some((cue) => cue.time === segment.releaseTime && cue.kind === 'handball'))
      const thrower = poseAt(replay, segment.releaseTime).players.find((p) => p.id === frame.state.ball.flight.from)
      assert.equal(thrower?.action?.kind, 'handball', `${file} handball by ${frame.state.ball.flight.from} at ${segment.releaseTime}`)
      if (segment.releaseTime > 0 && segment.releaseTime < frame.t - 0.01) {
        delayedReleases++
        const before = poseAt(replay, frame.t - 0.001).ball
        const after = poseAt(replay, frame.t + 0.001).ball
        assert.equal(before.state, 'flight')
        assert.ok(Math.hypot(before.position[0] - after.position[0], before.position[1] - after.position[1]) < 0.3)
        assert.ok(Math.abs(before.height - after.height) < 0.1)
      }
    }
  }
  assert.ok(delayedReleases > 0)
})

test('handball release precedes its late snapshot and visibly passes from hands to flight', () => {
  const held = { state: 'held', position: [10, 0], velocity: [0, 0], owner: 'A1' }
  const flight = { state: 'flight', position: [16, 0], velocity: [10, 0], owner: null,
    flight: { kind: 'handball', from: 'A1', lands_at: [25, 0], lands_in_s: 0.9 } }
  const snapshot = (x, ball) => ({ score: { A: 0, B: 0 }, ball,
    team_A: [{ ...player('A1', x), vel: [2, 0] }], team_B: [player('B1', 30)] })
  const replay = parseReplay([header, frame(0, 0, 'possession', snapshot(10, held)),
    frame(1, 1, 'scheduled', snapshot(12, flight))].map(JSON.stringify).join('\n'))
  const segment = replay.flightSegments.get(1)
  assert.equal(segment.releaseTime, 0.5)
  assert.deepEqual(segment.origin, [11, 0])
  assert.equal(poseAt(replay, 0.49).ball.state, 'held')
  assert.equal(poseAt(replay, 0.51).ball.state, 'flight')
  assert.equal(poseAt(replay, 0.51).ball.owner, null)
  assert.equal(poseAt(replay, 0.51).players[0].action.kind, 'handball')
  const releasePose = athleteAnimation(poseAt(replay, 0.5).players[0], 0.5, false)
  assert.ok(Math.abs(releasePose.limbs[1].hand[0] - 0.97) < 0.2)
  assert.ok(Math.abs(poseAt(replay, 0.999).ball.position[0] - poseAt(replay, 1).ball.position[0]) < 0.1)
})

test('handballs caught between snapshots fly between owners rather than teleport', async () => {
  const text = await readFile(new URL('../public/example_game_states_round36a_v_round26a.jsonl', import.meta.url), 'utf8')
  const replay = parseReplay(text)
  for (const [release, catchTime, from, receiver] of [[50.8, 51.3, 'A3', 'A1'], [53.35, 54.05, 'A1', 'A3']]) {
    const before = poseAt(replay, release - 0.001).ball
    const start = poseAt(replay, release).ball
    const middle = poseAt(replay, (release + catchTime) / 2).ball
    const end = poseAt(replay, catchTime - 0.001).ball
    const caught = poseAt(replay, catchTime).ball
    assert.equal(before.owner, from)
    assert.equal(start.state, 'flight')
    assert.equal(middle.state, 'flight')
    assert.equal(middle.owner, null)
    assert.equal(caught.owner, receiver)
    assert.ok(Math.hypot(start.position[0] - before.position[0], start.position[1] - before.position[1]) < 0.2)
    assert.ok(Math.hypot(end.position[0] - caught.position[0], end.position[1] - caught.position[1]) < 0.2)
    assert.ok(Math.abs(end.height - caught.height) < 0.1)
    assert.equal(poseAt(replay, release).players.find((p) => p.id === from).action.kind, 'handball')
    assert.equal(poseAt(replay, catchTime).players.find((p) => p.id === receiver).action.kind, 'catch')
    const trail = flightTrail(replay, poseAt(replay, (release + catchTime) / 2))
    assert.ok(trail.length > 1)
    assert.ok(trail.every(({ time, position, height }) => {
      const ball = poseAt(replay, time).ball
      return time >= release && Math.hypot(position[0] - ball.position[0], position[1] - ball.position[1]) < 0.001 &&
        Math.abs(height - ball.height) < 0.001
    }))
  }
})

test('distance-driven gait, two-handed carrying, kick release and recovery survive seeking', () => {
  const held = { state: 'held', position: [0, 0], velocity: [0, 0], owner: 'A1' }
  const flight = { state: 'flight', position: [4, 0], velocity: [10, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [23, 0], lands_in_s: 1.9 } }
  const replay = parseReplay([header, frame(0, 0, 'start', state(0, 10, held)),
    frame(1, 1, 'scheduled', state(3, 10, held)),
    frame(2, 1.3, 'kick', state(4, 10, flight))].map(JSON.stringify).join('\n'))
  const early = poseAt(replay, 0.15).players[0]
  const late = poseAt(replay, 0.75).players[0]
  assert.notDeepEqual(athleteAnimation(early, 0.15, true).limbs[0].foot, athleteAnimation(late, 0.75, true).limbs[0].foot)
  assert.deepEqual(athleteAnimation(late, 0.75, true).limbs.map((limb) => limb.hand[0]), [0.66, 0.66])
  const windup = poseAt(replay, 1.25).players[0]
  const shot = athleteAnimation(windup, 1.25, true)
  assert.equal(shot.expression, 'kicking')
  assert.ok(shot.ball[1] < 1)
  const release = poseAt(replay, 1.3).players[0]
  assert.equal(release.action.kind, 'kick')
  assert.ok(athleteAnimation(release, 1.3, false).limbs[1].foot[0] > 0)
  assert.deepEqual(athleteAnimation(windup, 1.25, true), athleteAnimation(windup, 1.25, true))
})

test('catching and tackling get their own poses and expressions', () => {
  const flight = { state: 'flight', position: [0, 0], velocity: [1, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [2, 0], lands_in_s: 0.5 } }
  const caught = { state: 'held', position: [1, 0], velocity: [0, 0], owner: 'B1' }
  const replay = parseReplay([header, frame(0, 0, 'kick', state(0, 1, flight)),
    frame(1, 0.5, 'possession', state(0, 1, caught)),
    frame(2, 1, 'tackle', state(0, 1, loose(1)))].map(JSON.stringify).join('\n'))
  assert.equal(athleteAnimation(poseAt(replay, 0.5).players[1], 0.5, true).expression, 'catching')
  assert.equal(athleteAnimation(poseAt(replay, 1).players[0], 1, false).expression, 'tackling')
})

test('handball release has a distinct punching pose and expression', () => {
  const held = { state: 'held', position: [0, 0], velocity: [0, 0], owner: 'A1' }
  const flight = { state: 'flight', position: [0, 0], velocity: [8, 0], owner: null,
    flight: { kind: 'handball', from: 'A1', lands_at: [6, 0], lands_in_s: 0.75 } }
  const replay = parseReplay([header, frame(0, 0, 'possession', state(0, 10, held)),
    frame(1, 0.6, 'spill', state(0, 10, flight))].map(JSON.stringify).join('\n'))
  const before = athleteAnimation(poseAt(replay, 0.5).players[0], 0.5, true)
  const after = athleteAnimation(poseAt(replay, 0.64).players[0], 0.64, false)
  assert.equal(after.expression, 'handballing')
  assert.ok(after.limbs[1].hand[0] > before.limbs[1].hand[0])
  const lead = athleteAnimation(poseAt(replay, 0.599).players[0], 0.599, true)
  const follow = athleteAnimation(poseAt(replay, 0.601).players[0], 0.601, false)
  assert.ok(Math.abs(lead.limbs[1].hand[0] - follow.limbs[1].hand[0]) < 0.08)
})

test('jog and sprint have distinct silhouettes and smooth threshold transitions', () => {
  const moving = (x, speed) => ({ ...player('A1', x), vel: [speed, 0] })
  const snapshot = (x, speed) => ({ score: { A: 0, B: 0 }, ball: loose(x), team_A: [moving(x, speed)], team_B: [player('B1', 10)] })
  const replay = parseReplay([header, frame(0, 0, 'start', snapshot(0, 0)),
    frame(1, 1, 'scheduled', snapshot(1, 3)), frame(2, 2, 'scheduled', snapshot(5, 7)),
    frame(3, 3, 'scheduled', snapshot(9, 3)), frame(4, 4, 'scheduled', snapshot(10, 0))].map(JSON.stringify).join('\n'))
  assert.deepEqual(replay.transitions.get('A1').map((cue) => cue.kind), ['start', 'sprint', 'jog', 'stop'])
  for (const [at, kind] of [[0.5, 'start'], [1.625, 'sprint'], [2.375, 'jog'], [3.5, 'stop']]) {
    assert.equal(poseAt(replay, at).players[0].transition.kind, kind)
    const before = athleteAnimation(poseAt(replay, at - 0.001).players[0], at - 0.001, false)
    const after = athleteAnimation(poseAt(replay, at + 0.001).players[0], at + 0.001, false)
    assert.ok(Math.abs(before.lean - after.lean) < 0.03)
    assert.ok(Math.abs(before.limbs[0].foot[0] - after.limbs[0].foot[0]) < 0.08)
  }
  const jog = athleteAnimation(poseAt(replay, 1).players[0], 1, false)
  const sprint = athleteAnimation(poseAt(replay, 2).players[0], 2, false)
  assert.equal(jog.pace, 'jog')
  assert.equal(sprint.pace, 'sprint')
  assert.equal(jog.expression, 'jogging')
  assert.equal(sprint.expression, 'sprinting')
  assert.ok(sprint.lean < jog.lean - 0.12)
  assert.ok(sprint.sprint > jog.sprint)
  assert.deepEqual(athleteAnimation(poseAt(replay, 1.8).players[0], 1.8, false), athleteAnimation(poseAt(replay, 1.8).players[0], 1.8, false))
})

test('kicker turns toward the target before release, even while moving sideways', () => {
  const sideways = (x) => ({ ...player('A1', x), vel: [0, 6] })
  const held = { state: 'held', position: [0, 0], velocity: [0, 0], owner: 'A1' }
  const flight = { state: 'flight', position: [0, 0], velocity: [15, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [30, 0], lands_in_s: 2 } }
  const snapshot = (ball) => ({ score: { A: 0, B: 0 }, ball, team_A: [sideways(0)], team_B: [player('B1', 10)] })
  const replay = parseReplay([header, frame(0, 0, 'possession', snapshot(held)),
    frame(1, 1, 'kick', snapshot(flight))].map(JSON.stringify).join('\n'))
  assert.ok(athleteAnimation(poseAt(replay, 0.48).players[0], 0.48, true).heading > 1)
  assert.ok(Math.abs(athleteAnimation(poseAt(replay, 1).players[0], 1, false).heading) < 0.01)
  const before = athleteAnimation(poseAt(replay, 0.999).players[0], 0.999, true).heading
  const after = athleteAnimation(poseAt(replay, 1.001).players[0], 1.001, false).heading
  assert.ok(Math.abs(before - after) < 0.02)
})

test('loose-ball pickup bends the player down and brings the ball up through the hands', () => {
  const held = { state: 'held', position: [0.4, 0], velocity: [0, 0], owner: 'A1' }
  const replay = parseReplay([header, frame(0, 0, 'start', state(0, 10, loose(0.4))),
    frame(1, 0.4, 'possession', state(0.4, 10, held))].map(JSON.stringify).join('\n'))
  const actor = poseAt(replay, 0.4).players[0]
  assert.equal(actor.action.kind, 'gather')
  const pickup = athleteAnimation(actor, 0.4, true)
  assert.equal(pickup.expression, 'gathering')
  assert.ok(pickup.lean < -0.5)
  assert.ok(pickup.crouch > 0.3)
  assert.ok(pickup.limbs.every((limb) => limb.hand[1] < 1.1))
  assert.ok(pickup.ball[1] < 1.2)
  assert.ok(athleteAnimation(poseAt(replay, 0.8).players[0], 0.8, true).lean > pickup.lean)
})

test('a marked kick prompts a jump; a spoil prompts opposing aerial contests', () => {
  const flight = { state: 'flight', position: [0, 0], velocity: [2, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [1, 0], lands_in_s: 0.5, markable: true } }
  const held = { state: 'held', position: [1, 0], velocity: [0, 0], owner: 'B1' }
  const mark = parseReplay([header, frame(0, 0, 'kick', state(0, 1, flight)),
    frame(1, 0.5, 'possession', state(0, 1, held))].map(JSON.stringify).join('\n'))
  const jump = athleteAnimation(poseAt(mark, 0.5).players[1], 0.5, true)
  assert.equal(jump.expression, 'catching')
  assert.ok(jump.jump > 0.65)
  assert.ok(jump.limbs.every((limb) => limb.hand[1] > 2.2))
  assert.ok(Math.hypot(...jump.leap) > 0, 'the winner leaps toward the incoming ball')

  const spoil = parseReplay([header, frame(0, 0, 'kick', state(0, 2, flight)),
    frame(1, 0.4, 'spoil', state(0, 1, loose(0.6)))].map(JSON.stringify).join('\n'))
  assert.equal(poseAt(spoil, 0.4).players[0].action.kind, 'contest')
  assert.equal(poseAt(spoil, 0.4).players[1].action.kind, 'contest')
  assert.ok(athleteAnimation(poseAt(spoil, 0.4).players[1], 0.4, false).jump > 0.7)
})

test('a kick-in after a score is not mistaken for an aerial catch', () => {
  const flight = { state: 'flight', position: [0, 0], velocity: [1, 0], owner: null,
    flight: { kind: 'kick', from: 'A1', lands_at: [8, 0], lands_in_s: 1, markable: true } }
  const held = { state: 'held', position: [8, 0], velocity: [0, 0], owner: 'B1' }
  const replay = parseReplay([header, frame(0, 0, 'kick', state(0, 8, flight)),
    frame(1, 1, 'kick-in', state(0, 8, held, { A: 0, B: 1 }))].map(JSON.stringify).join('\n'))
  assert.equal(poseAt(replay, 1).players[1].action, null)
})

test('opposing paths meeting produce a paired bump and recoil, not a repeated contact loop', () => {
  const snapshot = (a, b) => ({ score: { A: 0, B: 0 }, ball: loose(5),
    team_A: [player('A1', a)], team_B: [player('B1', b)] })
  const replay = parseReplay([header, frame(0, 0, 'start', snapshot(0, 3)),
    frame(1, 1, 'scheduled', snapshot(2, 1)),
    frame(2, 2, 'scheduled', snapshot(3, 0))].map(JSON.stringify).join('\n'))
  assert.equal(replay.cues.get('A1').filter((cue) => cue.kind === 'bump').length, 1)
  assert.equal(replay.cues.get('B1').filter((cue) => cue.kind === 'bump').length, 1)
  const a = athleteAnimation(poseAt(replay, 0.75).players[0], 0.75, false)
  const b = athleteAnimation(poseAt(replay, 0.75).players[1], 0.75, false)
  assert.equal(a.expression, 'bumping')
  assert.equal(b.expression, 'bumping')
  assert.ok(a.lean > 0.05)
  assert.ok(a.twist * b.twist < 0)
})

test('on-ball camera tracks 3D ball movement without losing the viewer orbit angle', () => {
  const camera = new THREE.PerspectiveCamera()
  const orbitTarget = ballCameraTarget([70, 0], 1.45)
  camera.position.copy(orbitTarget).add(ON_BALL_OFFSET)
  const flight = ballCameraTarget([87, -8], 9)
  followBallTarget(camera, orbitTarget, flight)
  assert.deepEqual(orbitTarget.toArray(), [17, 9, -8])
  assert.ok(camera.position.clone().sub(orbitTarget).distanceTo(ON_BALL_OFFSET) < 1e-10)
  // A manual pivot changes the offset; subsequent follow motion must keep it.
  camera.position.copy(orbitTarget).add(new THREE.Vector3(-5, 4, 9))
  followBallTarget(camera, orbitTarget, ballCameraTarget([90, -5], 2))
  assert.ok(camera.position.clone().sub(orbitTarget).distanceTo(new THREE.Vector3(-5, 4, 9)) < 1e-10)
})

test('overlapping players separate visually without changing the source positions or losing the ball', () => {
  const a = { ...player('A1', 70), distance: 0, action: null, vel: [0, 0] }
  const b = { ...player('B1', 70), distance: 0, action: null, vel: [0, 0] }
  const source = [a, b]
  const staged = stagePlayers(source, 'A1')
  const gap = Math.hypot(staged[0].position[0] - staged[1].position[0], staged[0].position[1] - staged[1].position[1])
  assert.ok(gap >= 1.07)
  assert.deepEqual(source.map((entry) => entry.pos), [[70, 0], [70, 0]])
  assert.ok(Math.hypot(staged[0].position[0] - 70, staged[0].position[1]) < 0.25)
  assert.ok(staged[0].contact.intensity > 0.5)
  assert.equal(athleteAnimation(a, 0.2, true, staged[0].contact).expression, 'protecting')
  assert.equal(athleteAnimation(b, 0.2, false, staged[1].contact).expression, 'jostling')
  assert.deepEqual(stagePlayers(source, 'A1'), staged)
})

test('crowded clusters spread apart, nearby opponents jostle and teammates do not', () => {
  const clustered = ['A1', 'A2', 'B1', 'B2'].map((id) =>
    ({ ...player(id, 70), distance: 0, action: null, vel: [0, 0] }))
  const staged = stagePlayers(clustered, null)
  for (let i = 0; i < staged.length; i++) for (let j = i + 1; j < staged.length; j++) {
    assert.ok(Math.hypot(staged[i].position[0] - staged[j].position[0], staged[i].position[1] - staged[j].position[1]) > 0.75)
  }
  const near = stagePlayers([{ ...clustered[0] }, { ...clustered[2], pos: [71.7, 0] }], null)
  assert.ok(near[0].contact.intensity > 0)
  assert.notDeepEqual(athleteAnimation(near[0].player, 0, false, near[0].contact).limbs.map((limb) => limb.hand),
    athleteAnimation(near[0].player, 0.3, false, near[0].contact).limbs.map((limb) => limb.hand))
  assert.equal(stagePlayers(clustered.slice(0, 2), null)[0].contact, null)
  assert.equal(stagePlayers([clustered[0], { ...clustered[2], pos: [75, 0] }], null)[0].contact, null)
})

test('a scripted kick takes precedence over continuous jostling', () => {
  const carrier = { ...player('A1', 70), distance: 0, action: { kind: 'kick', time: 0, direction: [1, 0] } }
  const opponent = { ...player('B1', 70), distance: 0, action: null }
  const contact = stagePlayers([carrier, opponent], 'A1')[0].contact
  assert.equal(athleteAnimation(carrier, 0, true, contact).expression, 'kicking')
})

test('crowd bed stays audible while goals, danger and late close play lift the cheer', () => {
  const replay = { header: { ...header, seconds: 240, rules: { length: 140, arc_radius: 50 } } }
  const neutral = { ball: loose(70), players: [player('A1', 70), player('B1', 90)], score: { A: 0, B: 0 } }
  const baseline = crowdMix(replay, neutral, [], 100)
  assert.ok(baseline.ambient > 0)
  assert.ok(baseline.cheer < 0.1)
  const danger = crowdMix(replay, { ...neutral, ball: loose(133) }, [], 100)
  assert.ok(danger.cheer > baseline.cheer)
  const pressured = crowdMix(replay, { ...neutral, ball: { ...loose(115), state: 'held', owner: 'A1' },
    players: [player('A1', 115), player('B1', 116)] }, [], 100)
  assert.ok(pressured.cheer > danger.cheer * 0.5)
  const behind = crowdMix(replay, neutral, [{ time: 100, points: 1 }], 100)
  const goal = crowdMix(replay, neutral, [{ time: 100, points: 6 }], 100)
  assert.ok(goal.cheer > behind.cheer)
  assert.equal(goal.whistleAt, 100)
  assert.equal(crowdMix(replay, neutral, [{ time: 100, points: 6 }], 100.4).whistleAt, undefined)
  const stoppage = { ...replay, frames: [frame(0, 100, 'ball-up', neutral)] }
  assert.equal(crowdMix(stoppage, { ...neutral, index: 0 }, [], 100.1).whistleAt, 100)
  assert.ok(crowdMix(replay, neutral, [{ time: 100, points: 6 }], 105).cheer < goal.cheer)
  const close = crowdMix(replay, { ...neutral, score: { A: 19, B: 20 } }, [], 220)
  assert.ok(close.cheer > baseline.cheer)
})
