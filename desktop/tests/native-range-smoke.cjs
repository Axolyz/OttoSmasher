// Real Electron/libmpv engine, with a deliberately blocked JS event loop.
const {app}=require('electron');const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),addon=require(path.join(root,'.runtime/player.node'));
const {rangeCommands,clearRangeCommands}=require('../electron/playback-range.cjs');
app.setPath('userData',path.join(root,'.runtime/range-smoke-profile'));
app.whenReady().then(async()=>{
 const rate=48000,count=rate*3,wav=Buffer.alloc(44+count*2);
 wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(count*2,40);
 const file=path.join(root,'.runtime/range-smoke.wav');fs.writeFileSync(file,wav);
 const id=addon.create(Buffer.alloc(8),false),state={};
 const wait=async(fn)=>{const until=Date.now()+5000;while(Date.now()<until){Object.assign(state,addon.poll(id));if(state.error)throw Error(state.error);if(fn())return;await new Promise(r=>setTimeout(r,10))}throw Error(JSON.stringify(state))};
 try{
  addon.command(id,['set','mute','yes']);addon.command(id,['loadfile',file,'replace','-1','start=0.5,end=2.5,pause=yes']);await wait(()=>state.loaded==='yes');
  const spec={start:.5,end:2.5};
  for(const [a,b] of [[.071,.117],[.51,.673],[.8,1.057]]){
    delete state['eof-reached'];
    for(const c of rangeCommands(spec,{start:a,end:b}))addon.command(id,c);
    // There is no JS polling/cutoff while mpv consumes this whole selection.
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,700);
    await wait(()=>state['eof-reached']==='yes');
    assert(Math.abs(Number(state['time-pos'])-(spec.start+b))<=2/rate);
    console.log('PASS engine boundary, UI blocked',a,b,state['time-pos']);
  }
  delete state['eof-reached'];
  for(const c of rangeCommands(spec,{start:.3,end:.5,loop:true}))addon.command(id,c);
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,950);
  Object.assign(state,addon.poll(id));assert.notEqual(state['eof-reached'],'yes');
  await wait(()=>Number(state['time-pos'])>=.8 && Number(state['time-pos'])<=1.025);
  for(const c of clearRangeCommands(spec))addon.command(id,c);
  addon.command(id,['seek','1.6','absolute+exact']);
  await wait(()=>Number(state['time-pos'])>=1.59);console.log('PASS engine loop and ordinary seek exits range');
 }finally{addon.destroy(id);fs.unlinkSync(file)}app.quit();
}).catch(e=>{console.error(e);app.exit(1)});
