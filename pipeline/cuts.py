from __future__ import annotations

import math
import re
import shlex
from bisect import bisect_left, bisect_right
from pathlib import Path

from .audio import run
from .common import timestamp


class WordBoundaries:
    def __init__(self, words):
        words = list(words)
        self.starts = sorted(w["start"] for w in words)
        self.ends = sorted(w["end"] for w in words)


def sentence_units(segments):
    """Sätze über Whisper-Segmentgrenzen hinweg sammeln; unvollständige Enden kennzeichnen."""
    units, group = [], []
    for segment in segments:
        for word in segment["words"]:
            item = {
                **word,
                "segment_id": segment["id"],
                "heat": segment["heat_final"],
                "tags": segment["tags"],
                "speaker": segment["speaker"],
            }
            if group and (item["speaker"] != group[-1]["speaker"] or item["start"] - group[-1]["end"] > 1.5):
                units.append(unit(group, False))
                group = []
            group.append(item)
            if re.search(r'[.!?…][»”"\)]?$', item["word"]):
                units.append(unit(group, True))
                group = []
    if group:
        units.append(unit(group, False))
    return units


def unit(words, complete):
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": " ".join(w["word"] for w in words),
        "segment_ids": list(dict.fromkeys(w["segment_id"] for w in words)),
        "score": sum(w["heat"] for w in words) / len(words),
        "complete": complete,
        "words": words,
    }


def padded_range(group, all_words, duration, padding):
    start, end = group[0]["start"], group[-1]["end"]
    if isinstance(all_words, WordBoundaries):
        left, right = bisect_right(all_words.ends, start), bisect_left(all_words.starts, end)
        before = all_words.ends[left - 1] if left else 0.0
        after = all_words.starts[right] if right < len(all_words.starts) else duration
    else:
        before = max((w["end"] for w in all_words if w["end"] <= start), default=0.0)
        after = min((w["start"] for w in all_words if w["start"] >= end), default=duration)
    # Nur die vorhandene Pause nutzen; Nachbarwörter bleiben unangetastet.
    return max(before, start - min(padding, (start - before) / 2)), min(
        after, end + min(padding, (after - end) / 2)
    )


def make_cut(group, all_words, duration, padding, kind, identifier, title, reason):
    start, end = padded_range(group, all_words, duration, padding)
    text = " ".join(u["text"] for u in group)
    return {
        "id": identifier,
        "type": kind,
        "title": title,
        "start": start,
        "end": end,
        "duration": end - start,
        "score": sum(u["score"] for u in group) / len(group),
        "segment_ids": list(dict.fromkeys(sid for u in group for sid in u["segment_ids"])),
        "subtitle_text": text,
        "reason": reason,
        "boundary": "sentence",
    }


def candidates(units, minimum, maximum, words, duration, padding):
    result = []
    for i, first in enumerate(units):
        if i > 0 and not units[i - 1]["complete"]:
            continue  # kein neuer Clip mitten in einem abgebrochenen Satz
        for j in range(i, len(units)):
            group = units[i : j + 1]
            a, b = padded_range(group, words, duration, padding)
            if b - a > maximum:
                break
            if b - a >= minimum and group[-1]["complete"]:
                result.append(group)
    return result


def proposals(scored, analysis, duration, config):
    segments, curve = scored["segments"], scored["curve"]
    units = sentence_units(segments)
    words = WordBoundaries(w for s in segments for w in s["words"])
    pad = config["pause_padding_seconds"]
    warnings = []
    by_id = {s["id"]: s for s in segments}
    quoted = {s["id"] for s in segments if s["quotable"] and s["quote"]}

    def editorial_groups(kind, minimum, maximum):
        result = []
        for recommendation in analysis.get("edit_recommendations", {}).get(kind, []):
            first, last = by_id[recommendation["start_segment_id"]], by_id[recommendation["end_segment_id"]]
            indexes = [
                i for i, u in enumerate(units) if u["start"] < last["end"] and u["end"] > first["start"]
            ]
            if not indexes:
                continue
            a, b = indexes[0], indexes[-1]
            group = units[a : b + 1]
            start, end = padded_range(group, words, duration, pad)
            if (
                minimum <= end - start <= maximum
                and group[-1]["complete"]
                and (a == 0 or units[a - 1]["complete"])
            ):
                result.append((group, recommendation))
        return result

    recommended_hooks = editorial_groups("hooks", config["hook_min_seconds"], config["hook_max_seconds"])
    hooks = candidates(units, config["hook_min_seconds"], config["hook_max_seconds"], words, duration, pad)
    # Fragen bevorzugen: klarer offener Loop; redaktionell prüfen, kein Retention-Versprechen.
    hook_group = max(
        hooks,
        key=lambda g: sum(u["score"] for u in g) / len(g) + (0.3 if g[-1]["text"].endswith("?") else 0),
        default=None,
    )
    hook = (
        make_cut(
            hook_group,
            words,
            duration,
            pad,
            "hook",
            "hook-1",
            "Cold Open",
            "Kurze, stark bewertete Passage; als Cold Open testen. Offenen Loop redaktionell prüfen.",
        )
        if hook_group
        else None
    )
    if recommended_hooks:
        group, recommendation = recommended_hooks[0]
        hook = make_cut(
            group, words, duration, pad, "hook", "hook-1", recommendation["title"], recommendation["reason"]
        )
    if not hook:
        warnings.append("Kein vollständiger Satz innerhalb der Hook-Länge; kein künstlicher Schnitt erzeugt.")
    groups = candidates(units, config["clip_min_seconds"], config["clip_max_seconds"], words, duration, pad)
    groups.sort(
        key=lambda g: (
            sum(u["score"] for u in g) / len(g)
            + 0.2 * g[-1]["score"]
            + 0.1 * any(sid in quoted for u in g for sid in u["segment_ids"])
        ),
        reverse=True,
    )
    recommended_clips = editorial_groups("clips", config["clip_min_seconds"], config["clip_max_seconds"])
    clips = []
    for group, recommendation in recommended_clips + [(group, None) for group in groups]:
        cut = make_cut(
            group,
            words,
            duration,
            pad,
            "clip",
            f"clip-{len(clips) + 1}",
            recommendation["title"] if recommendation else group[0]["text"][:72],
            recommendation["reason"]
            if recommendation
            else "Hoher Heat und starker Schluss; Kontext/Pointe und Hochformat-Bild prüfen.",
        )
        if all(cut["end"] <= c["start"] or cut["start"] >= c["end"] for c in clips):
            clips.append(cut)
        if len(clips) >= config["clip_count"]:
            break
    if len(clips) < 3:
        warnings.append(
            "Weniger als drei vollständige, nicht überlappende Social Clips in der Ziellänge gefunden."
        )
    shorts = {}
    for minutes in config["short_minutes"]:
        budget, selected = minutes * 60, set()
        # Einstieg, Abschluss und je ein starker Moment pro dramaturgischer Phase.
        complete = [i for i, u in enumerate(units) if u["complete"] and (i == 0 or units[i - 1]["complete"])]
        anchors = [complete[0], complete[-1]] if complete else []
        for phase in analysis["phases"]:
            indexes = [i for i in complete if phase["start"] <= units[i]["start"] < phase["end"]]
            if indexes:
                anchors.append(max(indexes, key=lambda i: units[i]["score"]))
        ranked = sorted(complete, key=lambda i: units[i]["score"], reverse=True)

        def selected_runs(indexes):
            runs = []
            for index in sorted(indexes):
                if runs and index == runs[-1][-1] + 1:
                    runs[-1].append(index)
                else:
                    runs.append([index])
            return runs

        for i in list(dict.fromkeys(anchors + ranked)):
            proposed = selected | {i}
            total = 0.0
            for indexes in selected_runs(proposed):
                a, b = padded_range([units[j] for j in indexes], words, duration, pad)
                total += b - a
            if total <= budget:
                selected.add(i)
        runs = selected_runs(selected)
        selections = [
            make_cut(
                [units[i] for i in run],
                words,
                duration,
                pad,
                "short",
                f"short-{minutes}-{j + 1}",
                f"{minutes}-Min-Version · Teil {j + 1}",
                "Chronologisch, mit Einstieg, Phasen-Höhepunkten und Abschluss, soweit im Zeitbudget.",
            )
            for j, run in enumerate(runs)
        ]
        shorts[str(minutes)] = {
            "target_seconds": budget,
            "duration": sum(c["duration"] for c in selections),
            "cuts": selections,
            "under_target": sum(c["duration"] for c in selections) < budget - 15,
        }
    reductions, seen = [], set()
    for u in units:
        clean = re.sub(r"\W+", " ", u["text"].lower()).strip()
        repeated = clean in seen
        seen.add(clean)
        filler = len(re.findall(r"\b(äh|ähm|hm|sozusagen|quasi|irgendwie)\b", clean))
        if u["complete"] and (u["score"] < config["retention_threshold"] or repeated or filler >= 3):
            reductions.append(
                make_cut(
                    [u],
                    words,
                    duration,
                    pad,
                    "reduction",
                    f"reduce-{len(reductions) + 1}",
                    "Kürzung prüfen",
                    "Wörtliche Wiederholung"
                    if repeated
                    else "Viele Füllwörter"
                    if filler >= 3
                    else "Niedriger Heat",
                )
            )
    risks, first = [], None
    for point in curve + [{"time": duration, "heat": 1.0}]:
        if point["heat"] < config["retention_threshold"]:
            if first is None:
                first = point["time"]
        elif first is not None:
            if point["time"] - first > config["retention_seconds"]:
                risks.append(
                    {
                        "start": first,
                        "end": min(duration, point["time"]),
                        "reason": f"Mehr als {config['retention_seconds']} s unter der konfigurierten Heat-Schwelle (Hypothese).",
                        "suggestion": "Kürzen, B-Roll einsetzen oder mit einem Zwischentitel orientieren.",
                    }
                )
            first = None
    return {
        "hook": hook,
        "clips": clips,
        "short_versions": shorts,
        "reductions": reductions,
        "retention_risks": risks,
        "warnings": warnings,
        "fps": config["edl_fps"],
    }


def timecode(frames, fps):
    if fps not in (24, 25, 30):
        raise ValueError("CMX3600 unterstützt hier nur 24, 25 oder 30 fps non-drop-frame")
    hours, rest = divmod(frames, 3600 * fps)
    minutes, rest = divmod(rest, 60 * fps)
    seconds, frame = divmod(rest, fps)
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frame:02}"


def parse_timecode(value, fps):
    fields = [int(v) for v in value.split(":")]
    if len(fields) != 4 or fields[1] >= 60 or fields[2] >= 60 or fields[3] >= fps:
        raise ValueError("Ungültiger Source-Timecode; --source-timecode HH:MM:SS:FF verwenden")
    h, m, s, f = fields
    if min(fields) < 0:
        raise ValueError("Negativer Source-Timecode")
    return ((h * 60 + m) * 60 + s) * fps + f


def safe_frame(seconds, fps, words, direction):
    frame = math.floor(seconds * fps + 1e-8) if direction < 0 else math.ceil(seconds * fps - 1e-8)
    # Falls kein ganzer Frame in die Pause passt, das angrenzende Wort vollständig mitnehmen.
    while True:
        crossing = next((w for w in words if w["start"] + 1e-8 < frame / fps < w["end"] - 1e-8), None)
        if not crossing:
            return max(0, frame)
        frame = math.floor(crossing["start"] * fps) if direction < 0 else math.ceil(crossing["end"] * fps)


def edl(
    cuts, filename, fps=25, words=(), source_timecode="00:00:00:00", title="INTERVIEW HEATMAP", video=True
):
    offset = parse_timecode(source_timecode, fps)
    # EDL ist ein zeilenorientiertes Format: Dateinamen dürfen keine neuen Datensätze einschleusen.
    filename = filename.replace("\r", " ").replace("\n", " ")
    lines, cursor = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""], 3600 * fps
    for index, cut in enumerate(cuts, 1):
        a, b = safe_frame(cut["start"], fps, words, -1), safe_frame(cut["end"], fps, words, 1)
        if b <= a:
            continue
        if b + offset >= 24 * 3600 * fps or cursor + b - a >= 24 * 3600 * fps:
            raise ValueError("CMX3600-Timecode überschreitet 24 Stunden")
        track = "AA/V" if video else "A"
        lines.append(
            f"{index:03}  AX       {track:<4} C        {timecode(a + offset, fps)} {timecode(b + offset, fps)} "
            f"{timecode(cursor, fps)} {timecode(cursor + b - a, fps)}"
        )
        lines.extend([f"* FROM CLIP NAME: {filename}", f"* COMMENT: {cut['id']}", ""])
        cursor += b - a
    return "\n".join(lines) + "\n"


def clip_srt(cut, segments):
    rows = []
    for s in segments:
        selected = [w for w in s["words"] if w["start"] >= cut["start"] and w["end"] <= cut["end"]]
        if selected:
            a, b = selected[0]["start"] - cut["start"], selected[-1]["end"] - cut["start"]
            text = " ".join(w["word"] for w in selected)
            rows.append(f"{len(rows) + 1}\n{timestamp(a, True)} --> {timestamp(b, True)}\n{text}\n")
    return "\n".join(rows)


def export_edls(cuts, metadata, segments, out: Path, source_timecode="00:00:00:00"):
    words = [w for s in segments for w in s["words"]]
    tracks = {
        "hook": [cuts["hook"]] if cuts["hook"] else [],
        "clips": cuts["clips"],
        **{f"short-{key}": value["cuts"] for key, value in cuts["short_versions"].items()},
    }
    exports = {}
    for name, selections in tracks.items():
        text = edl(
            selections,
            metadata["filename"],
            cuts["fps"],
            words,
            source_timecode,
            title=f"INTERVIEW {name.upper()}",
            video=metadata["media_type"] == "video",
        )
        (out / f"{name}.edl").write_text(text, encoding="utf-8")
        exports[f"{name}.edl"] = text
    default = exports.get("short-5.edl", exports["clips.edl"])
    (out / "cuts.edl").write_text(default, encoding="utf-8")
    exports["cuts.edl"] = default
    return exports


def render_script(cuts, segments, source, out, render=False, video=True):
    directory = out / "clips"
    directory.mkdir(exist_ok=True)
    commands = [
        "#!/bin/sh",
        "set -eu",
        "# Exakte Neucodierung; kein ungenauer Keyframe-/Stream-Copy-Schnitt.",
    ]
    selections = ([cuts["hook"]] if cuts["hook"] else []) + cuts["clips"]
    for cut in selections:
        target = directory / f"{cut['id']}{'.mp4' if video else '.m4a'}"
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source.resolve()),
            "-ss",
            f"{cut['start']:.6f}",
            "-t",
            f"{cut['duration']:.6f}",
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(target.resolve()),
        ]
        commands.append(shlex.join(command))
        (directory / f"{cut['id']}.srt").write_text(clip_srt(cut, segments), encoding="utf-8")
        if render:
            run(command)
    path = out / "render-clips.sh"
    path.write_text("\n".join(commands) + "\n", encoding="utf-8")
    path.chmod(0o700)
