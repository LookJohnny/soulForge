/* home_props — 客厅/厨房/书桌/阳台的简易家具（程序化、低多边形、哑光）。
   镜像 engine/planner/space.py 的 HOME：角色站在 place 坐标上，家具摆在它身后/身侧，
   所以坐下（sit）时屁股正好落在沙发/凳子上。配色故意压暗，人物才是主角。 */

import * as THREE from 'three';

const M = (hex, rough = 0.95) => new THREE.MeshStandardMaterial({ color: hex, roughness: rough, metalness: 0 });
const PALETTE = {
  wood: M(0x4a3b4f), woodDark: M(0x35293a), fabric: M(0x5c4a6b), fabricDark: M(0x463a54),
  metal: M(0x2a2733, 0.6), stone: M(0x3b3644), leaf: M(0x3f6b4f), leafDark: M(0x2f4f3c), pot: M(0x7a5a4a),
  screen: new THREE.MeshStandardMaterial({ color: 0x1a1530, roughness: 0.4, emissive: 0x3a2f6a, emissiveIntensity: 0.6 }),
};

function box(w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y + h / 2, z); m.castShadow = true; m.receiveShadow = true; return m;
}
function cyl(r, h, mat, x = 0, y = 0, z = 0, seg = 18) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat);
  m.position.set(x, y + h / 2, z); m.castShadow = true; m.receiveShadow = true; return m;
}
function ball(r, mat, x, y, z) {
  const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 1), mat);
  m.position.set(x, y, z); m.castShadow = true; return m;
}

/** 沙发：角色站/坐在坐垫前沿，靠背在身后。 */
function sofa(g, x, z) {
  const seatH = 0.42;
  g.add(box(1.9, 0.22, 0.85, PALETTE.woodDark, x, 0, z - 0.45));           // 底座
  g.add(box(1.7, 0.2, 0.75, PALETTE.fabric, x, seatH - 0.2, z - 0.45));      // 坐垫
  g.add(box(1.9, 0.55, 0.22, PALETTE.fabricDark, x, seatH, z - 0.85));       // 靠背
  g.add(box(0.2, 0.32, 0.85, PALETTE.fabricDark, x - 0.95, seatH - 0.1, z - 0.45));
  g.add(box(0.2, 0.32, 0.85, PALETTE.fabricDark, x + 0.95, seatH - 0.1, z - 0.45));
  const rug = new THREE.Mesh(new THREE.CircleGeometry(1.4, 40), M(0x241d2e));
  rug.rotation.x = -Math.PI / 2; rug.position.set(x, 0.004, z + 0.1); rug.receiveShadow = true; g.add(rug);
}

/** 书桌 + 圆凳：桌子在角色身前偏后（她面向观众，桌在身侧靠后），凳子在脚下。 */
function desk(g, x, z) {
  g.add(box(1.3, 0.05, 0.65, PALETTE.wood, x, 0.72, z - 0.6));
  for (const [dx, dz] of [[-0.6, -0.9], [0.6, -0.9], [-0.6, -0.32], [0.6, -0.32]]) g.add(box(0.05, 0.72, 0.05, PALETTE.woodDark, x + dx, 0, z + dz));
  const tablet = box(0.5, 0.02, 0.34, PALETTE.screen, x - 0.1, 0.77, z - 0.6); tablet.rotation.x = -0.35; g.add(tablet);
  g.add(cyl(0.03, 0.25, PALETTE.metal, x + 0.45, 0.77, z - 0.7));
  const lampHead = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.12, 16, 1, true), PALETTE.metal); lampHead.position.set(x + 0.45, 1.05, z - 0.7); lampHead.rotation.x = Math.PI; g.add(lampHead);
  const light = new THREE.PointLight(0xffd9a8, 0.9, 2.2); light.position.set(x + 0.45, 1.0, z - 0.65); g.add(light);
  g.add(cyl(0.18, 0.04, PALETTE.fabric, x, 0.40, z - 0.05));                 // 凳面（角色 sit 落在这）
  g.add(cyl(0.03, 0.40, PALETTE.metal, x, 0, z - 0.05, 10));
  g.add(cyl(0.16, 0.02, PALETTE.metal, x, 0, z - 0.05));
}

/** 厨房：台面在身后，灶台两圈 + 平底锅 + 水槽龙头。 */
function kitchen(g, x, z) {
  g.add(box(2.0, 0.88, 0.62, PALETTE.woodDark, x, 0, z - 0.75));
  g.add(box(2.06, 0.04, 0.66, PALETTE.stone, x, 0.88, z - 0.75));
  g.add(box(0.7, 0.012, 0.45, PALETTE.metal, x - 0.4, 0.92, z - 0.75));
  g.add(cyl(0.11, 0.012, M(0x151219), x - 0.55, 0.932, z - 0.68));
  g.add(cyl(0.11, 0.012, M(0x151219), x - 0.25, 0.932, z - 0.82));
  g.add(cyl(0.14, 0.05, PALETTE.metal, x - 0.55, 0.944, z - 0.68));          // 锅
  g.add(box(0.22, 0.02, 0.03, PALETTE.metal, x - 0.32, 0.96, z - 0.68));     // 锅柄
  g.add(box(0.5, 0.02, 0.36, M(0x1c1922), x + 0.5, 0.905, z - 0.75));        // 水槽
  const tap = cyl(0.015, 0.22, PALETTE.metal, x + 0.5, 0.92, z - 0.95, 8); g.add(tap);
  g.add(box(2.0, 0.6, 0.3, PALETTE.wood, x, 1.5, z - 0.9));                  // 吊柜
  for (let i = -2; i <= 2; i++) g.add(box(0.05, 0.35, 0.05, PALETTE.woodDark, x + i * 0.45, 0.02, z - 0.75));
  const shelfLight = new THREE.PointLight(0xfff0d8, 0.6, 2.4); shelfLight.position.set(x, 1.4, z - 0.5); g.add(shelfLight);
}

/** 阳台花架：三层架子 + 几盆植物 + 洒水壶。 */
function plants(g, x, z) {
  const base = [x, z - 0.55];
  for (const [dx, h] of [[-0.45, 0.35], [0.45, 0.35], [-0.45, 0.85], [0.45, 0.85]]) g.add(box(0.05, h, 0.05, PALETTE.woodDark, base[0] + dx, 0, base[1]));
  g.add(box(1.0, 0.04, 0.4, PALETTE.wood, base[0], 0.35, base[1]));
  g.add(box(1.0, 0.04, 0.4, PALETTE.wood, base[0], 0.85, base[1]));
  const pots = [[-0.3, 0.39, 0.16], [0.25, 0.39, 0.2], [-0.2, 0.89, 0.14], [0.3, 0.89, 0.12], [0.55, 0, 0.26]];
  for (const [dx, y, r] of pots) {
    g.add(cyl(r * 0.55, r * 0.7, PALETTE.pot, base[0] + dx, y, base[1]));
    g.add(ball(r, PALETTE.leaf, base[0] + dx, y + r * 0.7 + r * 0.6, base[1]));
    g.add(ball(r * 0.7, PALETTE.leafDark, base[0] + dx + r * 0.4, y + r * 0.7 + r * 0.9, base[1] - r * 0.3));
  }
  g.add(cyl(0.08, 0.16, PALETTE.metal, base[0] - 0.55, 0, base[1] + 0.25));   // 洒水壶
  g.add(box(0.16, 0.02, 0.02, PALETTE.metal, base[0] - 0.47, 0.12, base[1] + 0.25));
}

/**
 * 把家具放进场景。places: { sofa:{x,z}, kitchen:{x,z}, desk:{x,z}, plants:{x,z} } —— 与 live.js PLACES 相同。
 * @returns {THREE.Group} 可整体移除
 */
export function buildHome(scene, places) {
  const g = new THREE.Group(); g.name = 'home';
  if (places.sofa) sofa(g, places.sofa.x, places.sofa.z);
  if (places.desk) desk(g, places.desk.x, places.desk.z);
  if (places.kitchen) kitchen(g, places.kitchen.x, places.kitchen.z);
  if (places.plants) plants(g, places.plants.x, places.plants.z);
  // 地板：一整块，取代单人模式的圆盘
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(7, 5), M(0x17141f));
  floor.rotation.x = -Math.PI / 2; floor.position.set(0.2, -0.001, -0.5); floor.receiveShadow = true; g.add(floor);
  const wall = box(7, 2.6, 0.06, M(0x1d1826), 0.2, 0, -1.9); wall.receiveShadow = true; g.add(wall);
  scene.add(g);
  return g;
}
