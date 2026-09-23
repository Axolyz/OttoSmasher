// Optional macOS engine integration test. No window or application UI automation.
const { app } = require("electron");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const addon = require(path.join(root, ".runtime/player.node"));
app.setPath("userData", path.join(root, ".runtime/player-smoke-profile"));
app
  .whenReady()
  .then(async () => {
    const rate = 24000,
      count = rate * 2,
      wav = Buffer.alloc(44 + count * 2);
    wav.write("RIFF");
    wav.writeUInt32LE(wav.length - 8, 4);
    wav.write("WAVEfmt ", 8);
    wav.writeUInt32LE(16, 16);
    wav.writeUInt16LE(1, 20);
    wav.writeUInt16LE(1, 22);
    wav.writeUInt32LE(rate, 24);
    wav.writeUInt32LE(rate * 2, 28);
    wav.writeUInt16LE(2, 32);
    wav.writeUInt16LE(16, 34);
    wav.write("data", 36);
    wav.writeUInt32LE(count * 2, 40);
    const file = path.join(root, ".runtime/player-smoke.wav");
    fs.writeFileSync(file, wav);
    const id = addon.create(Buffer.alloc(8), false),
      state = {};
    const until = async (fn) => {
      const stop = Date.now() + 12000;
      while (Date.now() < stop) {
        Object.assign(state, addon.poll(id));
        if (state.error) throw Error(state.error);
        if (fn()) return;
        await new Promise((r) => setTimeout(r, 25));
      }
      throw Error("Timeout: " + JSON.stringify(state));
    };
    try {
      addon.command(id, ["set", "mute", "yes"]);
      addon.command(id, [
        "loadfile",
        file,
        "replace",
        "-1",
        "start=0.25,end=1.25,pause=yes",
      ]);
      await until(() => state.loaded === "yes" && Number(state.duration) > 0);
      assert.equal(Number(state.duration), 2);
      addon.command(id, ["seek", "0.75", "absolute+exact"]);
      await until(() => Math.abs(Number(state["time-pos"]) - 0.75) < 0.03);
      addon.command(id, ["set", "pause", "no"]);
      await until(() => state["eof-reached"] === "yes");
      assert(Number(state["time-pos"]) <= 1.3);
      console.log(
        "PASS native WAV decode, exact seek, end boundary:",
        JSON.stringify(state),
      );
    } finally {
      addon.destroy(id);
      fs.unlinkSync(file);
    }
    app.quit();
  })
  .catch((error) => {
    console.error(error);
    app.exit(1);
  });
