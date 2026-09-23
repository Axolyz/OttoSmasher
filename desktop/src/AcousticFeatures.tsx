import React, {useEffect, useState} from "react";
import {UButton,UInput,UDetails} from "./Ui";
import {request} from "./Workspace";
const api = (path: string) => request("/api/library-tools" + path);
export function FeatureFilters({
  mode,
  conditions,
  onChange,
  onPrepare,
}: {
  mode: string;
  conditions: any[];
  onChange: (x: any[]) => void;
  onPrepare: () => void;
}) {
  const [defs, setDefs] = useState<any[]>([]),
    [extra, setExtra] = useState(false);
  useEffect(() => {
    api("").then((x) => setDefs(x.feature_definitions));
  }, []);
  const names =
    mode === "pitched"
      ? [
          "sound.duration",
          "pitch.midi",
          "pitch.spread",
          "pitch.voiced_duration",
          "harmonic.high",
          "harmonic.ratio",
          "spectrum.high",
        ]
      : [
          "sound.duration",
          "sound.attack",
          "sound.decay",
          "sound.crest",
          "spectrum.low",
          "spectrum.high",
          "spectrum.flatness",
        ];
  return (
    <section className="feature-filters">
      <small>
        条件作用于当前已登记采样整体。缺少所选特征时不命中；句内音块条件请使用语音检索。
      </small>
      <UButton onClick={onPrepare}>后台准备当前范围指标</UButton>
      <label>
        <UInput
          type="checkbox"
          checked={extra}
          onChange={(e) => setExtra(e.target.checked)}
        />
        更多指标
      </label>
      <div className="row">
        {defs
          .filter(
            (d) =>
              extra || (d.producer === "otto.dsp" && names.includes(d.name)),
          )
          .map((d) => {
            const matches = (x: any) =>
              x.name === d.name && (x.producer || "otto.dsp") === d.producer;
            const c = conditions.find(matches);
            return (
              <label key={d.producer + ":" + d.name} title={d.definition}>
                <span>
                  <UInput
                    type="checkbox"
                    checked={!!c}
                    onChange={(e) =>
                      onChange(
                        e.target.checked
                          ? [
                              ...conditions,
                              { name: d.name, producer: d.producer },
                            ]
                          : conditions.filter((x) => !matches(x)),
                      )
                    }
                  />
                  {d.title || d.name} ({d.unit})
                </span>
                {c && (
                  <span>
                    <UInput
                      placeholder="最小"
                      type="number"
                      step="any"
                      value={c.min ?? ""}
                      onChange={(e) =>
                        onChange(
                          conditions.map((x) =>
                            matches(x)
                              ? {
                                  ...x,
                                  min:
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                }
                              : x,
                          ),
                        )
                      }
                    />
                    <UInput
                      placeholder="最大"
                      type="number"
                      step="any"
                      value={c.max ?? ""}
                      onChange={(e) =>
                        onChange(
                          conditions.map((x) =>
                            matches(x)
                              ? {
                                  ...x,
                                  max:
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                }
                              : x,
                          ),
                        )
                      }
                    />
                  </span>
                )}
              </label>
            );
          })}
      </div>
    </section>
  );
}

export function FeatureDetails({ id }: { id: string }) {
  const [value, setValue] = useState<any>(null),
    [defs, setDefs] = useState<any[]>([]);
  useEffect(() => {
    api("/features/" + id)
      .then(setValue)
      .catch(() => setValue(null));
    api("").then((x) => setDefs(x.feature_definitions));
  }, [id]);
  return (
    <UDetails>
      <summary>单音声学属性{value ? "" : "（尚未准备或已过期）"}</summary>
      {value && (
        <>
          <p>
            音高有效覆盖：{Math.round(value.coverage * 100)}% · {value.reason}
          </p>
          <div className="feature-values">
            {defs
              .filter((d) => d.producer === "otto.dsp")
              .map((d) => (
                <span key={d.name} title={d.definition}>
                  {d.title}：
                  {value.values[d.name] == null
                    ? "未知"
                    : Number(value.values[d.name]).toFixed(3)}{" "}
                  {d.unit}
                </span>
              ))}
          </div>
          <UDetails>
            <summary>起音／主体／尾部频谱</summary>
            <pre>{JSON.stringify(value.phases, null, 2)}</pre>
          </UDetails>
        </>
      )}
    </UDetails>
  );
}
