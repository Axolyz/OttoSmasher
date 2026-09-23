import { useEffect, useState } from "react";
const key = "otto.playback-bpm";
function read(): number | null {
  try {
    const n = JSON.parse(localStorage.getItem(key) || "null");
    return typeof n === "number" && n >= 20 && n <= 400 ? n : null;
  } catch {
    return null;
  }
}
export function usePlaybackTempo(): [
  number | null,
  (bpm: number | null) => void,
] {
  const [bpm, setBpm] = useState(read);
  useEffect(() => {
    const sync = () => setBpm(read());
    window.addEventListener("otto:tempo", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("otto:tempo", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [
    bpm,
    (value) => {
      localStorage.setItem(key, JSON.stringify(value));
      window.dispatchEvent(new Event("otto:tempo"));
    },
  ];
}
