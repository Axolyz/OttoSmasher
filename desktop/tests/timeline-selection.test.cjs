const {test}=require('node:test'), assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const ctx={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('desktop/src/TimelineSelection.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx);
test('shift selection uses raw gesture, reverses symmetrically, never cascades',()=>{
 const intervals=[{start:1,end:2},{start:1.9,end:4},{start:3,end:5}];
 const result=ctx.exports.snapIntervals(1.1,1.5,intervals);assert.equal(result.start,1);assert.equal(result.end,2);
 const reversed=ctx.exports.snapIntervals(2.5,1.5,intervals);assert.equal(reversed.start,1);assert.equal(reversed.end,4);
 const plain=ctx.exports.snapIntervals(6,7,intervals);assert.equal(plain.start,6);assert.equal(plain.end,7);
});
