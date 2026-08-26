/* Bone/expression table sanity for humanoid_adapter (no browser needed). */
import assert from 'node:assert/strict';
import { RIG_TABLES, REQUIRED_BONES, expandTable, normName, EXPR_MAP } from '../web/lib/humanoid_adapter.js';

for (const [rig, table] of Object.entries(RIG_TABLES)) {
  const ex = expandTable(table);
  for (const b of REQUIRED_BONES) assert.ok(ex[b]?.length, `${rig}: required bone ${b} has no candidates`);
  for (const k of Object.keys(ex)) {
    if (k.startsWith('left')) assert.ok(ex['right' + k.slice(4)], `${rig}: ${k} lacks right-side twin`);
  }
}
assert.equal(normName('mixamorig:LeftForeArm'), 'leftforearm');
assert.equal(normName('mixamorig1:Hips'), 'hips');
assert.equal(normName('Skeleton_arm_joint_L__2_'), 'armjointl2');
assert.equal(normName('左ひじ'), '左ひじ');
for (const [name, cands] of Object.entries(EXPR_MAP)) assert.ok(cands.length >= 3, `${name}: too few morph candidates`);
console.log('humanoid tables ok:', Object.keys(RIG_TABLES).join(','), '| expressions:', Object.keys(EXPR_MAP).length);
