import React, { useEffect, useState } from "react";
import { SoundOutlined } from "@ant-design/icons";
export function SampleThumbnail({ material }: { material: any }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [material.id]);
  return (
    <span className="sample-thumbnail" title="原片对应范围的中间画面">
      {failed ? (
        <SoundOutlined aria-label="无可用画面" />
      ) : (
        <img
          src={`/api/samples/${material.id}/thumbnail?v=${material.start}-${material.end}`}
          loading="lazy"
          decoding="async"
          alt="原片画面"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
