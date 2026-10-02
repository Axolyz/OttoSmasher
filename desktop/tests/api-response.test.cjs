const {test} = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), ts = require('typescript');
const context = {exports: {}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('desktop/src/ApiResponse.ts', 'utf8'),
  {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText, context);
const read = context.exports.readApiResponse;
test('plain HTTP 500 is reported as service failure, not a JSON syntax error', async () => {
  await assert.rejects(read(new Response('Internal Server Error', {status: 500}), '/api/preparation/analysis'), /HTTP 500.*preparation\/analysis/);
});
test('JSON validation detail and successful payload are preserved', async () => {
  await assert.rejects(read(new Response('{"detail":"缺少模型"}', {status: 400}), '/api/test'), /缺少模型/);
  assert.equal((await read(new Response('{"total":2}'), '/api/test')).total, 2);
});
