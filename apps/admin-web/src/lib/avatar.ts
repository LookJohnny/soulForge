/** Generate a deterministic avatar gradient + emoji for a character */

const SPECIES_EMOJI: Record<string, string> = {
  兔子: "🐰", 小兔: "🐰", 兔: "🐰",
  熊: "🐻", 大熊: "🐻", 熊猫: "🐼", 大熊猫: "🐼", 北极熊: "🐻‍❄️",
  猫: "🐱", 小猫: "🐱", 猫咪: "🐱", 奶猫: "🐱",
  狗: "🐶", 小狗: "🐶", 柯基: "🐶", 柴犬: "🐕",
  狐狸: "🦊", 狐: "🦊",
  企鹅: "🐧",
  龙: "🐉", 恐龙: "🦕",
  独角兽: "🦄",
  老虎: "🐯", 狮子: "🦁",
  狼: "🐺",
  猴: "🐵", 猴子: "🐵",
  鹦鹉: "🦜", 小鸟: "🐦",
  蛇: "🐍",
  蝴蝶: "🦋",
  鹰: "🦅",
  仙女: "🧚", 精灵: "🧝", 天使: "👼",
  机器人: "🤖",
  外星人: "👽",
};

const GRADIENTS = [
  "from-amber-600/25 to-orange-800/15",
  "from-rose-600/20 to-pink-800/15",
  "from-violet-600/20 to-purple-800/15",
  "from-blue-600/20 to-indigo-800/15",
  "from-emerald-600/20 to-teal-800/15",
  "from-cyan-600/20 to-sky-800/15",
  "from-amber-500/20 to-yellow-700/15",
  "from-red-600/20 to-rose-800/15",
];

function hashStr(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function getCharacterEmoji(species: string): string {
  if (SPECIES_EMOJI[species]) return SPECIES_EMOJI[species];
  for (const [key, emoji] of Object.entries(SPECIES_EMOJI)) {
    if (species.includes(key) || key.includes(species)) return emoji;
  }
  return "✨";
}

export function getCharacterGradient(id: string): string {
  return GRADIENTS[hashStr(id) % GRADIENTS.length];
}
