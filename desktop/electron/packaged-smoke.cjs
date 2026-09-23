const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
module.exports = async function smoke(runtime, origin) {
  const response = await fetch(origin + '/api/helper/info');
  assert(response.ok);
  const info = await response.json();
  assert.equal(info.root, runtime.root);
  assert.equal(info.total, 0);
  const rate = 48000, wav = Buffer.alloc(44 + rate * 2);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(rate * 2, 40);
  const file = path.join(runtime.root, '中文 空格 测试.wav');
  fs.writeFileSync(file, wav);
  const capture = path.join(runtime.root, '范围输出.wav');
  const addon = require(runtime.env.OTTO_PLAYER_ADDON);
  const id = addon.create(Buffer.alloc(8), false);
  try {
    addon.command(id, ['set', 'ao', 'pcm']);
    addon.command(id, ['set', 'ao-pcm-file', capture]);
    addon.command(id, ['loadfile', file, 'replace', '-1', 'start=0.1,end=0.25,pause=no']);
    const state = {}; const deadline = Date.now() + 10000;
    do {
      Object.assign(state, addon.poll(id));
      if (state.error) throw Error(state.error);
      if (state['eof-reached'] === 'yes') break;
      await new Promise(r => setTimeout(r, 20));
    } while (Date.now() < deadline);
    await new Promise(r => setTimeout(r, 100));
    Object.assign(state, addon.poll(id));
    assert.equal(state['eof-reached'], 'yes', JSON.stringify(state));
    // Position notifications are coalesced. Verify emitted PCM frames, not a stale UI event.
  } finally { addon.destroy(id); fs.unlinkSync(file); }
  await require('./distribution.cjs').run(runtime.python, ['-c',
    'import sys,soundfile as sf; x=sf.info(sys.argv[1]); assert abs(x.frames/x.samplerate-0.15)<=2/x.samplerate, str(x)', capture],
    {env: {...process.env, ...runtime.env}});
  fs.unlinkSync(capture);
  // Validate the relocated Python and media binaries, not the developer environment.
  await require('./distribution.cjs').run(runtime.python, ['-c',
    'from ottosmasher.workspace import command,executable; command([executable("ffmpeg"),"-version"]); command([executable("ffprobe"),"-version"])'],
    {env: {...process.env, ...runtime.env}});
  return {passed: true, platform: process.platform, arch: process.arch, build: runtime.buildId,
    checks: ['isolated empty workspace', 'relocated Python/API', 'ffmpeg/ffprobe', 'native libmpv', 'Unicode media path', 'engine range stop'],
    not_tested: ['GPU inference', 'video embedding/high DPI', 'perceptual audio quality']};
};
