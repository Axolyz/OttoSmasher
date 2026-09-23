// The app bundle is immutable. Only the workspace and relocated runtimes are writable.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');

function run(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {...options, windowsHide: true});
    let tail = '';
    child.stdout?.on('data', b => { tail = (tail + b).slice(-6000); });
    child.stderr?.on('data', b => { tail = (tail + b).slice(-6000); });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(Error(`${path.basename(file)} failed (${code}): ${tail}`)));
  });
}

async function sha256(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function prepare(app) {
  const codeRoot = path.join(process.resourcesPath, 'software');
  const assets = path.join(process.resourcesPath, 'runtime');
  const manifest = JSON.parse(fs.readFileSync(path.join(assets, 'manifest.json'), 'utf8'));
  if (manifest.platform !== process.platform || manifest.arch !== process.arch)
    throw Error('此安装包的系统或 CPU 架构不匹配');
  const root = path.resolve(process.env.OTTO_ROOT || path.join(app.getPath('userData'), 'workspace'));
  const runtime = path.join(app.getPath('userData'), 'runtimes', manifest.id);
  const ready = path.join(runtime, 'ready.json');
  fs.mkdirSync(root, {recursive: true});
  if (!fs.existsSync(ready)) {
    // An interrupted first launch can be safely retried; no user files live here.
    fs.rmSync(runtime, {recursive: true, force: true});
    fs.mkdirSync(runtime, {recursive: true});
    for (const item of manifest.files) {
      if (!/^[a-zA-Z0-9_.-]+$/.test(item.name) || !/^[a-z]+$/.test(item.target)) throw Error('Invalid runtime manifest');
      const archive = path.join(assets, item.name);
      if (await sha256(archive) !== item.sha256) throw Error(`运行库校验失败：${item.name}`);
      const destination = path.join(runtime, item.target);
      fs.mkdirSync(destination, {recursive: true});
      const tar = process.platform === 'win32' ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe') : '/usr/bin/tar';
      await run(tar, ['-xzf', archive, '-C', destination]);
    }
    const python = path.join(runtime, 'core', process.platform === 'win32' ? 'python.exe' : 'bin/python');
    for (const item of manifest.files) {
      const prefix = path.join(runtime, item.target);
      const unpack = path.join(prefix, process.platform === 'win32' ? 'Scripts/conda-unpack-script.py' : 'bin/conda-unpack');
      await run(python, [unpack], {env: {...process.env, PYTHONHOME: '', PYTHONPATH: ''}});
    }
    for (const item of manifest.native) {
      if (!/^[a-zA-Z0-9_.-]+$/.test(item.name)) throw Error('Invalid native manifest');
      const source = path.join(assets, item.name);
      if (await sha256(source) !== item.sha256) throw Error(`播放器校验失败：${item.name}`);
      fs.copyFileSync(source, path.join(runtime, item.name));
    }
    fs.writeFileSync(ready, JSON.stringify(manifest));
  }
  const core = path.join(runtime, 'core');
  const bins = process.platform === 'win32' ? [core, path.join(core, 'Library/bin'), path.join(core, 'Scripts')] : [path.join(core, 'bin')];
  return {root, codeRoot, buildId: manifest.id,
    python: path.join(core, process.platform === 'win32' ? 'python.exe' : 'bin/python'),
    env: {OTTO_ROOT: root, OTTO_CODE_ROOT: codeRoot, OTTO_CORE_ENV: core,
      OTTO_PLAYER_ADDON: path.join(runtime, 'player.node'), OTTO_BUILD_ID: manifest.id,
      PYTHONPATH: path.join(codeRoot, 'src'), PYTHONHOME: '', PYTHONUTF8: '1',
      PATH: [...bins, process.env.PATH || ''].join(path.delimiter)}};
}
module.exports = {prepare, run, sha256};
