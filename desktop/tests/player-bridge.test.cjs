const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function fixture() {
  const handlers = {},
    commands = [],
    events = [],
    poll = [],
    timers = [];
  const addon = {
    create: () => 1,
    command: (id, args) => commands.push(args),
    poll: () => poll.shift() || {},
    destroy: () => {},
    geometry: () => {},
  };
  const sender = {
    isDestroyed: () => false,
    send: (name, state) => events.push(state),
    getZoomFactor: () => 1,
  };
  const event = { sender };
  const context = {
    module: { exports: {} },
    URL,
    process: { env: {} },
    require: (name) =>
      name === "electron"
        ? {
            ipcMain: {
              handle: (k, fn) => (handlers[k] = fn),
              on: (k, fn) => (handlers[k] = fn),
            },
            BrowserWindow: {
              fromWebContents: () => ({
                getNativeWindowHandle: () => Buffer.alloc(8),
              }),
            },
          }
        : name.endsWith(".node")
          ? addon
          : require(name.startsWith("./") ? "../electron/" + name.slice(2) : name),
    setInterval: (fn) => {
      timers.push(fn);
      return { unref() {} };
    },
    fetch: async () => ({
      ok: true,
      json: async () => ({
        path: "/movie 日本語.mkv",
        start: 103,
        end: 123,
        audio_path: "/对白.wav",
        audio_delay: 100,
        aid: null,
      }),
    }),
  };
  vm.runInNewContext(
    fs.readFileSync("desktop/electron/player.cjs", "utf8"),
    context,
  );
  context.module.exports("/workspace", "http://127.0.0.1:18765", () => {});
  const call = (name, ...args) =>
    handlers["otto:player:" + name](event, ...args);
  call("create", true);
  return { call, commands, poll, timers, events, handlers };
}
test("external stem is selected with an explicit offset; original audio stays disabled during loading", async () => {
  const f = fixture();
  const info = await f.call(
    "load",
    1,
    "/api/helper/native-player/012345678901234567890123",
  );
  assert.equal(info.duration, 20);
  assert(
    f.commands.some(
      (c) =>
        c[0] === "loadfile" &&
        c[1] === "/movie 日本語.mkv" &&
        c[4].includes("aid=no"),
    ),
  );
  assert(f.commands.some((c) => c.join("|") === "set|audio-delay|100"));
  f.poll.push({ loaded: "yes" });
  f.timers[0]();
  assert(f.commands.some((c) => c.join("|") === "audio-add|/对白.wav|select"));
  f.call("control", 1, "seek", 5);
  assert(f.commands.some((c) => c.join("|") === "seek|108|absolute+exact"));
});
test("renderer cannot open arbitrary files/remote URLs or operate another window player", async () => {
  const f = fixture();
  await assert.rejects(
    f.call("load", 1, "https://example.com/movie.mkv"),
    /宿主/,
  );
  await assert.rejects(f.call("load", 1, "file:///etc/passwd"), /宿主/);
  assert.throws(
    () => f.handlers["otto:player:control"]({ sender: {} }, 1, "play"),
    /Unknown player/,
  );
  assert.throws(() => f.call("control", 1, "seek", NaN), /Invalid/);
});
test("range endpoint is passed to the engine in source seconds and stale requests cannot change it", async () => {
 const f=fixture(); const info=await f.call("load",1,"/api/helper/native-player/012345678901234567890123");
 f.poll.push({loaded:"yes"});f.timers[0]();
 f.call("control",1,"range",{generation:info.generation,requestId:2,start:.12,end:.37,loop:false});
 assert(f.commands.some(c=>c.join("|")==="set|end|103.37"));
 const count=f.commands.length;
 f.call("control",1,"range",{generation:info.generation,requestId:1,start:0,end:1});
 assert.equal(f.commands.length,count);
 f.poll.push({restarted:"yes","eof-reached":"yes","time-pos":"103.12"});f.timers[0]();
 assert.equal(f.events.at(-1).changes["time-pos"],"103.37");
 f.call("control",1,"seek",{generation:info.generation,requestId:3,value:4});
 assert(f.commands.some(c=>c.join("|")==="set|end|123"));
});
