"use client";

/**
 * 换盘提示音可视化编辑器。
 *
 * Bambu 的 `M1006` 是「用步进电机演奏」：三个电机 = 三个声部。
 *
 *   M1006 A<x_note> B<x_dur> L<x_vol>
 *         C<y_note> D<y_dur> M<y_vol>
 *         E<z_note> F<z_dur> N<z_vol>
 *
 * 编码规则（来自 a1-jukebox 对固件 MIDI→gcode 转换器的逆向）：
 * - 音符码 = MIDI − 23，0 表示静音，37 = 中央 C（C4）
 * - 时长单位是**百分之一秒**（B20 = 200ms）
 * - 三个电机里 Y 最响，适合主旋律；本编辑器统一把旋律放在 Y 声部
 *
 * 只做「单声部旋律」，够用且不容易翻车；需要多声部时切到「原始乐谱」模式。
 */

import { useRef, useState } from "react";

import { Button } from "../ui/button";
import { NativeSelect } from "../ui/native-select";

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const OCTAVES = [4, 5];
const DURATIONS = [100, 200, 300, 400, 600, 800];

/** 音名 + 八度 → MIDI 编号 */
function toMidi(name, octave) {
  const index = NOTE_NAMES.indexOf(name);
  return (octave + 1) * 12 + (index < 0 ? 0 : index);
}

/** MIDI → 频率（仅用于试听；固件实际是步进电机发声） */
function toFrequency(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

/** 一个音符 → 一行 M1006（旋律放 Y 声部，X/Z 静音） */
function noteToGcode(midi, durationMs) {
  const code = Math.max(1, Math.min(72, midi - 23));
  const dur = Math.max(1, Math.round(durationMs / 10));
  return `M1006 A0 B${dur} L100 C${code} D${dur} M99 E0 F${dur} N100`;
}

/** 解析已有 M1006 文本 → 音符列表（无法还原的行忽略） */
function parseLines(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("M1006") && !/^M1006\s+[SW]/.test(line))
    .map((line) => {
      const match = /C(\d+)\s+D(\d+)/.exec(line);
      if (!match) return null;
      const code = Number(match[1]);
      if (!code) return null;
      const midi = code + 23;
      const octave = Math.floor(midi / 12) - 1;
      return {
        name: NOTE_NAMES[midi % 12],
        octave: OCTAVES.includes(octave) ? octave : OCTAVES[0],
        duration: Math.max(100, Math.min(800, Number(match[2]) * 10)),
        gcode: line
      };
    })
    .filter(Boolean);
}

export function MergeSoundEditor({ value, onChange }) {
  const notes = parseLines(value);
  const [playing, setPlaying] = useState(false);
  const audioCtxRef = useRef(null);

  const rebuild = (list) => {
    onChange(
      list
        .map((n) => noteToGcode(toMidi(n.name, n.octave), n.duration))
        .join("\n")
    );
  };

  // 用函数式更新：连续快速点击时 props.value 还没刷新，基于闭包会丢音符
  const addNote = () => {
    onChange((prev) => {
      const list = parseLines(prev);
      list.push({ name: "C", octave: 5, duration: 200 });
      return list.map((n) => noteToGcode(toMidi(n.name, n.octave), n.duration)).join("\n");
    });
  };

  const patchNote = (index, patch) => {
    rebuild(notes.map((n, i) => (i === index ? { ...n, ...patch } : n)));
  };

  const removeNote = (index) => {
    rebuild(notes.filter((_, i) => i !== index));
  };

  /** 用 Web Audio 粗略试听（方波更接近步进电机的质感） */
  async function preview() {
    if (typeof window === "undefined" || notes.length === 0) return;
    if (!audioCtxRef.current) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtxRef.current = new Ctx();
    }
    const ctx = audioCtxRef.current;
    if (ctx.state === "suspended") await ctx.resume();

    setPlaying(true);
    let cursor = ctx.currentTime + 0.05;
    for (const note of notes) {
      const seconds = note.duration / 1000;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = toFrequency(toMidi(note.name, note.octave));
      gain.gain.setValueAtTime(0.0001, cursor);
      gain.gain.exponentialRampToValueAtTime(0.12, cursor + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, cursor + seconds * 0.92);
      osc.connect(gain).connect(ctx.destination);
      osc.start(cursor);
      osc.stop(cursor + seconds);
      cursor += seconds;
    }
    setTimeout(() => setPlaying(false), Math.max(0, (cursor - ctx.currentTime) * 1000));
  }

  return (
    <div className="space-y-3 rounded-lg border border-black/[0.08] bg-[#fafafc] p-3 dark:border-white/10 dark:bg-white/5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          旋律放在 Y 声部（三个电机里最响），X/Z 静音；时值 100ms 起。
        </span>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={preview}
            disabled={notes.length === 0 || playing}
          >
            {playing ? "播放中…" : "试听"}
          </Button>
          <Button type="button" size="sm" onClick={addNote}>
            + 添加音符
          </Button>
        </div>
      </div>

      {notes.length === 0 ? (
        <p className="py-3 text-center text-xs text-muted-foreground">
          还没有音符。点「+ 添加音符」开始，或切到「原始乐谱」直接粘贴 M1006。
        </p>
      ) : (
        <ul className="space-y-2">
          {notes.map((note, index) => (
            <li key={`${index}-${note.name}-${note.octave}`} className="flex flex-wrap items-center gap-2">
              <NativeSelect
                className="w-20"
                value={note.name}
                onChange={(e) => patchNote(index, { name: e.target.value })}
                aria-label={`第 ${index + 1} 个音符的音名`}
              >
                {NOTE_NAMES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </NativeSelect>

              <NativeSelect
                className="w-16"
                value={String(note.octave)}
                onChange={(e) => patchNote(index, { octave: Number(e.target.value) })}
                aria-label={`第 ${index + 1} 个音符的八度`}
              >
                {OCTAVES.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </NativeSelect>

              <NativeSelect
                className="w-28"
                value={String(note.duration)}
                onChange={(e) => patchNote(index, { duration: Number(e.target.value) })}
                aria-label={`第 ${index + 1} 个音符的时值`}
              >
                {DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d} ms
                  </option>
                ))}
              </NativeSelect>

              <span className="min-w-0 flex-1 text-[11px] text-muted-foreground">
                第 {index + 1} 音
              </span>

              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={() => removeNote(index)}
              >
                删除
              </Button>
            </li>
          ))}
        </ul>
      )}

      {notes.length > 0 ? (
        <>
          <details className="rounded-md bg-black/[0.03] px-2 py-1.5 dark:bg-white/5">
            <summary className="cursor-pointer text-[11px] text-muted-foreground">
              查看生成的 M1006（{notes.length} 行）
            </summary>
            <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-muted-foreground">
              {value}
            </pre>
          </details>
          <p className="text-[11px] text-muted-foreground">
            试听是合成器近似（固件用步进电机发声，音色不同）；音高与时长是准确的。
          </p>
        </>
      ) : null}
    </div>
  );
}
