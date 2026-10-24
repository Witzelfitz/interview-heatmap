from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks


def score(segments, features, analysis, duration, config):
    a, b = float(config["llm_weight"]), float(config["audio_weight"])
    if a < 0 or b < 0 or abs(a + b - 1) > 1e-6:
        raise ValueError("Heat-Gewichte müssen nichtnegativ sein und zusammen 1 ergeben.")
    by_audio = {r["segment_id"]: r for r in features}
    by_analysis = {r["segment_id"]: r for r in analysis["segments"]}
    enriched = []
    # Ein-Sekunden-Raster, echte Stille bleibt 0; mehrere Sprecher werden gemittelt.
    size = max(1, int(np.ceil(duration)))
    grid, counts = np.zeros(size), np.zeros(size)
    for s in segments:
        semantic = by_analysis[s["id"]]
        audio = by_audio[s["id"]]
        heat = a * semantic["heat"] / 10 + b * audio["audio_score"]
        enriched.append({**s, **semantic, "audio": audio, "heat_final": heat})
        left, right = int(s["start"]), min(size, int(np.ceil(s["end"])))
        grid[left:right] += heat
        counts[left:right] += 1
    raw = np.divide(grid, counts, out=np.zeros_like(grid), where=counts > 0)
    smooth = uniform_filter1d(raw, size=max(1, round(config["smoothing_seconds"])), mode="nearest")
    indexes, _ = find_peaks(
        smooth, distance=max(1, config["peak_distance_seconds"]), prominence=config["peak_prominence"]
    )
    peaks = []
    for index in indexes:
        nearest = min(enriched, key=lambda s: abs((s["start"] + s["end"]) / 2 - index))
        peaks.append(
            {
                "time": int(index),
                "score": float(smooth[index]),
                "segment_id": nearest["id"],
                "label": nearest["tags"][0] if nearest["tags"] else "Heat Moment",
            }
        )
    curve = [{"time": i, "raw": float(raw[i]), "heat": float(smooth[i])} for i in range(size)]
    return {"segments": enriched, "curve": curve, "peaks": peaks, "weights": {"llm": a, "audio": b}}
