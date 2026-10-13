// 音名与音分（MIDI 音高：69 = A4 = 440 Hz）。检索浮层、波形的音高刻度与读数共用。
export const NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];

export const noteName = (m: number) => `${NOTE_NAMES[((m % 12) + 12) % 12]}${Math.floor(m / 12) - 1}`;

export const midiOf = (hz: number) => 69 + 12 * Math.log2(hz / 440);

/** 一个音高读成“最近的音名 + 偏差音分”：{ name: "B4", cents: -8 } */
export function readPitch(midi: number): { name: string; cents: number } {
  const n = Math.round(midi);
  return { name: noteName(n), cents: Math.round((midi - n) * 100) };
}
