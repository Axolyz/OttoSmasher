// Plain subtitle text only: never interpret source captions as ASS instructions.
function subtitleCommand(text) {
  if (typeof text !== "string" || text.length > 16000)
    throw Error("Invalid subtitle text");
  if (!text) return ["osd-overlay", "1", "none", ""];
  const escaped = text
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "")
    .replace(/\\/g, "\\\uFEFF")
    .replace(/{/g, "\\{")
    .replace(/}/g, "\\}")
    .replace(/\r\n?|\n/g, "\\N");
  return [
    "osd-overlay",
    "1",
    "ass-events",
    "{\\an2\\fs44\\bord2\\shad1\\c&HFFFFFF&\\3c&H000000&}" + escaped,
    "0",
    "720",
  ];
}
module.exports = { subtitleCommand };
