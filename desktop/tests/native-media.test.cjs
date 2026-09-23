const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");
const vm = require("node:vm");
const code = ts.transpileModule(
  fs.readFileSync("desktop/src/NativeMedia.ts", "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
const tick = () => new Promise((r) => setImmediate(r));
function fixture() {
  const calls = [],
    listeners = new Set();
  let generation = 0;
  const bridge = {
    create: async () => 1,
    load: async (id, url) => {
      calls.push(["load", url]);
      return { generation: ++generation, start: 100, duration: 10 };
    },
    control: async (id, action, value) => calls.push([action, value]),
    geometry: () => {},
    destroy: async () => calls.push(["destroy"]),
    subscribe: (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
  };
  const window = new EventTarget();
  window.ottoDesktop = { player: bridge };
  const context = {
    exports: {},
    window,
    Event,
    CustomEvent,
    performance,
    URL,
    location: { href: "http://127.0.0.1:18765/helper/" },
  };
  vm.runInNewContext(code, context);
  const element = new EventTarget();
  element.dataset = {};
  const controller = context.exports.attachNativeMedia(element);
  const state = (changes, gen = generation) =>
    listeners.forEach((cb) =>
      cb({ id: 1, generation: gen, start: 100, duration: 10, changes }),
    );
  return { element, controller, calls, state, listeners };
}
test("native clock remains range-local; pending seek/play and waveform URLs never become blobs", async () => {
  const f = fixture(),
    e = f.element;
  e.src = "/api/helper/native-player/abc";
  e.currentTime = 2;
  await e.play();
  await tick();
  assert.equal(f.calls.filter((x) => x[0] === "play").length, 0);
  f.state({ loaded: "yes", "time-pos": "102", duration: "1500", pause: "yes" });
  await tick();
  assert.equal(e.duration, 10);
  assert.equal(e.currentTime, 2);
  assert(f.calls.some((x) => x[0] === "seek" && x[1] === 2));
  assert(f.calls.some((x) => x[0] === "play"));
  assert.equal(e.canPlayType("audio/wav"), "");
  e.src = "/api/helper/native-player/abc";
  await tick();
  assert.equal(f.calls.filter((x) => x[0] === "load").length, 1);
  let ended = 0;
  e.addEventListener("ended", () => ended++);
  f.state({ "eof-reached": "yes" });
  assert.equal(ended, 1);
  await e.play();
  await tick();
  assert.equal(e.currentTime, 0);
  f.controller.destroy();
  await tick();
  assert.equal(f.listeners.size, 0);
  assert(f.calls.some((x) => x[0] === "destroy"));
});
test("new source ignores old generation; failures never fall back to HTML playback", async () => {
  const f = fixture(),
    e = f.element;
  e.src = "/api/one";
  await tick();
  f.state({ loaded: "yes" });
  e.src = "/api/two";
  await tick();
  f.state({ loaded: "yes", "time-pos": "109" }, 1);
  assert.equal(e.readyState, 0);
  assert.equal(e.currentTime, 0);
  let errors = 0;
  e.addEventListener("error", () => errors++);
  f.state({ error: "selected stem missing" }, 2);
  assert.equal(errors, 1);
  assert.match(e.error.message, /stem missing/);
  await assert.rejects(e.play(), /stem missing/);
  f.controller.destroy();
});
test('native selection ends at local endpoint and seek returns to unbounded media',async()=>{
 const f=fixture(),e=f.element;
 e.src='/api/range';await tick();f.state({loaded:'yes','time-pos':'100',pause:'yes'});
 await f.controller.playRange(.1,.23,false);
 const command=f.calls.findLast(x=>x[0]==='range');
 assert.equal(command[1].start,.1);assert.equal(command[1].end,.23);
 f.state({'time-pos':'100.23','eof-reached':'yes'});
 assert.equal(e.currentTime,.23);assert.equal(e.paused,true);
 e.currentTime=5;await tick();
 assert.equal(e.currentTime,5);assert.equal(f.calls.findLast(x=>x[0]==='seek')[1].value,5);
 f.controller.destroy();
});
