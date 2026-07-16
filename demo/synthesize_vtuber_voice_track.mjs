import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';

const args = parseArgs(process.argv.slice(2));
const video = resolve(args.video ?? 'outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4');
const out = resolve(args.out ?? 'outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4');
const workDir = resolve(args.workDir ?? 'outputs/webgl/voice_demo');
const aiCoreUrl = String(args.aiCoreUrl ?? process.env.AI_CORE_URL ?? '').replace(/\/$/, '');
const mode = String(args.mode ?? 'auto'); // auto | fish | ai-core | edge | say
const dotenv = loadDotEnv(resolve('.env'));
const fishApiKey = process.env.FISH_AUDIO_API_KEY ?? dotenv.FISH_AUDIO_API_KEY ?? '';
const fishModel = process.env.FISH_AUDIO_MODEL ?? dotenv.FISH_AUDIO_MODEL ?? 's1';
const duration = Number(args.duration ?? 12);
const eventsJson = args.eventsJson ? resolve(args.eventsJson) : null;
const skipMux = args.skipMux === true || args.skipMux === 'true';
const skipFit = args.skipFit === true || args.skipFit === 'true';

if (!skipMux && !existsSync(video)) {
  throw new Error(`Video not found: ${video}`);
}
if (!['auto', 'fish', 'ai-core', 'edge', 'say'].includes(mode)) {
  throw new Error(`Unsupported --mode ${mode}; expected auto, fish, ai-core, edge, or say`);
}
if (mode === 'fish' && !fishApiKey) {
  throw new Error('--mode fish requires FISH_AUDIO_API_KEY (env or .env)');
}

rmSync(workDir, { recursive: true, force: true });
mkdirSync(workDir, { recursive: true });
mkdirSync(dirname(out), { recursive: true });

// voice map is built from configs/characters.json — the single source of truth
const agents = loadAgentsFromCharacterConfig(resolve('configs/characters.json'));

function loadAgentsFromCharacterConfig(configPath) {
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  const map = {};
  for (const character of config.characters) {
    const voice = character.voice ?? {};
    const fish = voice.fish ?? {};
    const edge = voice.edge ?? {};
    map[character.name] = {
      plannedProvider: fish.reference_id ? 'fish' : 'edge',
      fishVoice: fish.reference_id ?? null,
      fishLabel: fish.label ?? character.role_label ?? '',
      fishSpeed: fish.speed ?? 1.0,
      edgeVoice: edge.voice ?? 'zh-CN-XiaoxiaoNeural',
      sayVoice: voice.say ?? 'Tingting',
      rate: edge.rate ?? 160,
      pitch: edge.pitch ?? 1.0,
      post: voice.post ?? 'soft',
    };
  }
  return map;
}

const defaultEvents = [
  { t: 0.55, agent: 'Astra-F', text: '早间陪伴模式启动，我先校准表情和动作。', emotion: 'warm' },
  { t: 1.65, agent: 'Mason-M', text: '厨房执行器上线，热源保持安全距离。', emotion: 'calm' },
  { t: 2.75, agent: 'Hex-01', text: '非人形侦察单元在线，环境扫描开始。', emotion: 'robot' },
  { t: 3.95, agent: 'Mason-M', text: '我会把任务拆成可执行的关节动作。', emotion: 'calm' },
  { t: 4.95, agent: 'Astra-F', text: '先照顾情绪，再安排今天的动作模板。', emotion: 'curious' },
  { t: 6.15, agent: 'Hex-01', text: '植物叶片状态正常，湿度偏低。', emotion: 'robot' },
  { t: 7.25, agent: 'Astra-F', text: '这个动作可以写成模板，明天直接复用。', emotion: 'happy' },
  { t: 8.25, agent: 'Mason-M', text: '我把舵机曲线和安全阈值一起保存。', emotion: 'steady' },
  { t: 9.30, agent: 'Hex-01', text: '维修循环开始，扳手扭矩百分之七十。', emotion: 'robot' },
  { t: 10.35, agent: 'Astra-F', text: '情绪反馈良好，动作幅度可以再柔一点。', emotion: 'excited' },
  { t: 11.10, agent: 'Mason-M', text: '晚间复盘完成，明天计划已锁定。', emotion: 'calm' },
];

const events = eventsJson ? loadEventsFromJson(eventsJson, duration) : defaultEvents;

const resolved = [];
for (let i = 0; i < events.length; i += 1) {
  const event = events[i];
  const agent = agents[event.agent];
  const rawPath = join(workDir, `clip_${String(i).padStart(2, '0')}_raw.aiff`);
  const wavPath = join(workDir, `clip_${String(i).padStart(2, '0')}.wav`);
  let provider = mode;

  if (mode === 'fish') {
    await synthesizeWithFish(event, agent, rawPath);
    provider = 'fish';
  } else if (mode === 'ai-core') {
    if (!aiCoreUrl) {
      throw new Error('--mode ai-core requires --ai-core-url or AI_CORE_URL');
    }
    await synthesizeWithAiCore(event, agent, rawPath);
    provider = 'ai-core';
  } else if (mode === 'edge') {
    await synthesizeWithEdge(event, agent, rawPath);
    provider = 'edge-tts';
  } else if (mode === 'say') {
    await synthesizeWithSay(event, agent, rawPath);
    provider = 'say-fallback';
  } else {
    try {
      if (!fishApiKey) {
        throw new Error('Fish Audio key not configured');
      }
      await synthesizeWithFish(event, agent, rawPath);
      provider = 'fish';
    } catch {
      try {
        await synthesizeWithEdge(event, agent, rawPath);
        provider = 'edge-tts';
      } catch {
        await synthesizeWithSay(event, agent, rawPath);
        provider = 'say-fallback';
      }
    }
  }

  await postProcessClip(rawPath, wavPath, agent, provider);
  if (!skipFit) {
    const nextT = events[i + 1]?.t;
    const windowEnd = (nextT != null ? nextT : duration) - 0.12;
    await fitClipToWindow(wavPath, Math.max(1.0, windowEnd - event.t));
  }
  resolved.push({ ...event, clip: wavPath, provider });
}

const srtPath = join(workDir, 'vtuber_life_voiceover.srt');
writeFileSync(srtPath, buildSrt(resolved, duration), 'utf8');

const audioPath = join(workDir, 'voice_mix.m4a');
await mixClips(resolved, audioPath, duration);

const manifestPath = join(workDir, 'voice_manifest.json');
writeFileSync(
  manifestPath,
  JSON.stringify(
    {
      sourceVideo: video,
      outputVideo: out,
      duration,
      mode,
      aiCoreUrl: aiCoreUrl || null,
      eventsJson,
      agents,
      events: resolved.map((event) => ({
        t: event.t,
        agent: event.agent,
        text: event.text,
        emotion: event.emotion,
        actionTemplateId: event.actionTemplateId ?? null,
        cameraShot: event.cameraShot ?? null,
        sourceAgentId: event.sourceAgentId ?? null,
        provider: event.provider,
        plannedProvider: agents[event.agent].plannedProvider,
        fishVoice: agents[event.agent].fishVoice,
        fishLabel: agents[event.agent].fishLabel,
        edgeVoice: agents[event.agent].edgeVoice,
        fallbackVoice: agents[event.agent].sayVoice,
      })),
    },
    null,
    2,
  ),
  'utf8',
);

if (!skipMux) await mux(video, audioPath, srtPath, out);

console.log(`wrote ${out}`);
console.log(`audio ${audioPath}`);
console.log(`srt ${srtPath}`);
console.log(`manifest ${manifestPath}`);

async function synthesizeWithFish(event, agent, targetPath) {
  const response = await fetch('https://api.fish.audio/v1/tts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${fishApiKey}`,
      model: fishModel,
    },
    body: JSON.stringify({
      text: event.text,
      reference_id: agent.fishVoice,
      format: 'mp3',
      mp3_bitrate: 128,
      normalize: true,
      temperature: 0.7,
      top_p: 0.8,
      latency: 'normal',
      prosody: { speed: agent.fishSpeed ?? 1.0, volume: 0 },
    }),
  });
  if (!response.ok) {
    throw new Error(`Fish Audio TTS failed: ${response.status} ${(await response.text()).slice(0, 200)}`);
  }
  const audio = Buffer.from(await response.arrayBuffer());
  if (audio.length < 100) {
    throw new Error('Fish Audio returned empty audio');
  }
  const mp3Path = targetPath.replace(/\.aiff$/, '.fish.mp3');
  writeFileSync(mp3Path, audio);
  await run('ffmpeg', ['-y', '-i', mp3Path, targetPath]);
}

async function probeDuration(path) {
  return new Promise((resolveProbe, rejectProbe) => {
    const child = spawn('ffprobe', ['-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]);
    let out = '';
    child.stdout.on('data', (d) => { out += d.toString(); });
    child.on('exit', (code) => {
      if (code === 0) resolveProbe(Number(out.trim()));
      else rejectProbe(new Error(`ffprobe exited ${code}`));
    });
  });
}

async function fitClipToWindow(wavPath, maxDuration) {
  // real voices pace themselves; if a line overruns its visual beat window,
  // compress up to 12% with atempo (imperceptible) instead of colliding
  const clipDuration = await probeDuration(wavPath);
  if (!Number.isFinite(clipDuration) || clipDuration <= maxDuration) return;
  const tempo = Math.min(1.18, clipDuration / maxDuration);
  const tmpPath = wavPath.replace(/\.wav$/, '.fit.wav');
  await run('ffmpeg', ['-y', '-i', wavPath, '-af', `atempo=${tempo.toFixed(4)}`, tmpPath]);
  rmSync(wavPath, { force: true });
  renameSync(tmpPath, wavPath);
  console.log(`fit ${wavPath.split('/').pop()} ${clipDuration.toFixed(2)}s -> <=${maxDuration.toFixed(2)}s (atempo ${tempo.toFixed(3)})`);
}

async function synthesizeWithAiCore(event, agent, targetPath) {
  const response = await fetch(`${aiCoreUrl}/tts/synthesize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: event.text,
      voice: agent.fishVoice,
      speed: speedFromRate(agent.rate),
    }),
  });
  if (!response.ok) {
    throw new Error(`AI Core TTS failed: ${response.status} ${await response.text()}`);
  }
  const data = await response.json();
  if (!data.audio_data) {
    throw new Error('AI Core TTS response missing audio_data');
  }
  const mp3Path = targetPath.replace(/\.aiff$/, '.mp3');
  writeFileSync(mp3Path, Buffer.from(data.audio_data, 'base64'));
  await run('ffmpeg', ['-y', '-i', mp3Path, targetPath]);
}

async function synthesizeWithEdge(event, agent, targetPath) {
  const mp3Path = targetPath.replace(/\.aiff$/, '.edge.mp3');
  const rate = Math.round((speedFromRate(agent.rate) - 1) * 100);
  const pitchHz = Math.round(((agent.edgePitch ?? 1) - 1) * 180);
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    rmSync(mp3Path, { force: true });
    try {
      await run('uv', [
        'run',
        '--package',
        'ai-core',
        'edge-tts',
        '--voice',
        agent.edgeVoice,
        '--rate',
        `${rate >= 0 ? '+' : ''}${rate}%`,
        '--pitch',
        `${pitchHz >= 0 ? '+' : ''}${pitchHz}Hz`,
        '--write-media',
        mp3Path,
        '--text',
        event.text,
      ]);
      if (!existsSync(mp3Path) || statSync(mp3Path).size === 0) {
        throw new Error('edge-tts produced an empty audio file');
      }
      break;
    } catch (err) {
      lastError = err;
      if (attempt === 3) {
        throw lastError;
      }
      await sleep(350 * attempt);
    }
  }
  await run('ffmpeg', ['-y', '-i', mp3Path, targetPath]);
}

async function synthesizeWithSay(event, agent, targetPath) {
  const voices = [agent.sayVoice, 'Tingting', 'Meijia'];
  let lastError = null;
  for (const voice of voices) {
    try {
      await run('/usr/bin/say', ['-v', voice, '-r', String(agent.rate), '-o', targetPath, '--', event.text]);
      return;
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError ?? new Error('say synthesis failed');
}

async function postProcessClip(inputPath, outputPath, agent, provider = 'edge-tts') {
  const filters = [];
  // pitch compensation is for neural-TTS voices only; fish references are final
  const pitch = provider === 'fish' ? 1 : agent.pitch;
  if (pitch !== 1) {
    filters.push(`asetrate=44100*${pitch.toFixed(3)}`, 'aresample=44100', `atempo=${(1 / pitch).toFixed(3)}`);
  } else {
    filters.push('aresample=44100');
  }
  if (agent.post === 'robot' && provider === 'fish') {
    // the fish reference already sounds synthetic; only a whisper of sparkle
    filters.push('treble=g=1');
  } else if (agent.post === 'robot') {
    // subtle digital tinge: gentle flanger + mild bit reduction, no warbly chorus
    filters.push(
      'flanger=delay=1.5:depth=0.6:regen=12:speed=0.6',
      'acrusher=level_in=1:level_out=1:bits=14:mode=log:aa=1:mix=0.14',
      'highpass=f=120',
      'treble=g=1',
    );
  }
  if (agent.post === 'bright') {
    filters.push('treble=g=1', 'acompressor=threshold=-18dB:ratio=2.2:attack=12:release=80');
  }
  if (agent.post === 'soft') {
    filters.push('bass=g=1.8', 'treble=g=-1.2', 'acompressor=threshold=-20dB:ratio=2.0:attack=18:release=110');
  }
  if (agent.post === 'warm') {
    filters.push('bass=g=2', 'acompressor=threshold=-20dB:ratio=2.0:attack=18:release=120');
  }
  filters.push('loudnorm=I=-18:LRA=11:TP=-1.5');

  await run('ffmpeg', [
    '-y',
    '-i',
    inputPath,
    '-af',
    filters.join(','),
    '-ar',
    '44100',
    '-ac',
    '2',
    outputPath,
  ]);
}

async function mixClips(items, targetPath, totalDuration) {
  const ffmpegArgs = [
    '-y',
    '-f',
    'lavfi',
    '-t',
    String(totalDuration),
    '-i',
    'anullsrc=channel_layout=stereo:sample_rate=44100',
  ];
  items.forEach((item) => {
    ffmpegArgs.push('-i', item.clip);
  });

  const delayed = items.map((item, index) => {
    const delayMs = Math.max(0, Math.round(item.t * 1000));
    return `[${index + 1}:a]adelay=${delayMs}|${delayMs},volume=1.05[a${index}]`;
  });
  const mixInputs = ['[0:a]', ...items.map((_, index) => `[a${index}]`)].join('');
  const filter = `${delayed.join(';')};${mixInputs}amix=inputs=${items.length + 1}:duration=longest:normalize=0,loudnorm=I=-16:LRA=11:TP=-1.5[a]`;

  ffmpegArgs.push('-filter_complex', filter, '-map', '[a]', '-t', String(totalDuration), '-c:a', 'aac', '-b:a', '192k', targetPath);
  await run('ffmpeg', ffmpegArgs);
}

async function mux(videoPath, audioPath, srtPath, targetPath) {
  await run('ffmpeg', [
    '-y',
    '-i',
    videoPath,
    '-i',
    audioPath,
    '-i',
    srtPath,
    '-map',
    '0:v:0',
    '-map',
    '1:a:0',
    '-map',
    '2:s:0',
    '-c:v',
    'copy',
    '-c:a',
    'aac',
    '-b:a',
    '192k',
    '-c:s',
    'mov_text',
    '-metadata:s:s:0',
    'language=chi',
    targetPath,
  ]);
}

function buildSrt(items, totalDuration) {
  return items
    .map((item, index) => {
      const next = items[index + 1]?.t;
      const start = item.t;
      let end = next == null ? totalDuration : Math.min(totalDuration, next - 0.08);
      if (end <= start) {
        end = Math.min(totalDuration, start + 0.45);
      }
      return `${index + 1}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${item.agent}: ${item.text}\n`;
    })
    .join('\n');
}

function formatSrtTime(seconds) {
  const ms = Math.round((seconds % 1) * 1000);
  const total = Math.floor(seconds);
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function speedFromRate(rate) {
  return Math.max(0.5, Math.min(2.0, rate / 175));
}

function loadEventsFromJson(path, totalDuration) {
  const parsed = JSON.parse(readFileSync(path, 'utf8'));
  const sourceEvents = Array.isArray(parsed) ? parsed : parsed.events;
  if (!Array.isArray(sourceEvents)) {
    throw new Error(`Expected ${path} to contain an events array`);
  }

  return sourceEvents
    .map((event) => ({
      t: Number(event.time ?? event.t ?? 0),
      agent: String(event.agentName ?? event.agent ?? event.agentId ?? 'SoulForge'),
      text: String(event.dialogue ?? event.text ?? ''),
      emotion: String(event.emotion ?? 'neutral'),
      actionTemplateId: event.actionTemplateId ?? null,
      cameraShot: event.cameraShot ?? null,
      sourceAgentId: event.agentId ?? null,
    }))
    .filter((event) => event.text && Number.isFinite(event.t) && event.t < totalDuration)
    .sort((a, b) => a.t - b.t);
}

function loadDotEnv(path) {
  const parsed = {};
  try {
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*"?([^"#]*)"?\s*(?:#.*)?$/);
      if (match) parsed[match[1]] = match[2].trim();
    }
  } catch {
    // no .env is fine
  }
  return parsed;
}

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) continue;
    const name = key.slice(2).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      parsed[name] = true;
    } else {
      parsed[name] = next;
      i += 1;
    }
  }
  return parsed;
}

function run(command, commandArgs) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, commandArgs, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', (data) => {
      stderr += data.toString();
    });
    child.on('exit', (code) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`${basename(command)} exited ${code}: ${stderr.slice(-1000)}`));
    });
  });
}

function sleep(ms) {
  return new Promise((resolveSleep) => {
    setTimeout(resolveSleep, ms);
  });
}
