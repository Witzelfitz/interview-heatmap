"""Erzeugt auf macOS ein fiktives Interview; keine echten Interviewdaten erforderlich."""

import json
import subprocess
import sys
import wave
from pathlib import Path

DIALOGUE = [
    "Willkommen zum Gespräch. Du hast mitten im Winter deinen sicheren Beruf aufgegeben. Was war der Auslöser?",
    "Ich sass im Zug nach Zürich und merkte plötzlich, dass ich seit drei Jahren keinen freien Sonntag mehr hatte. Das wollte ich ändern.",
    "Viele Menschen träumen von einem Neuanfang. Wie hast du den ersten Schritt gewagt, und wer hat dich dabei unterstützt?",
    "Zuerst habe ich meiner Schwester davon erzählt. Sie hat gelacht und gesagt, endlich sagst du es laut. Dann kam die Angst vor dem Geld.",
    "Wie gross war diese Angst? Gab es einen konkreten Moment, in dem das ganze Vorhaben beinahe gescheitert wäre?",
    "Ja, im März. Die Bank hat unseren Kredit abgelehnt. Wir hatten noch genau zweitausend Franken auf dem Konto und drei Wochen bis zur Eröffnung.",
    "Wie habt ihr das gelöst? So kurz vor dem Ziel aufzugeben, muss unglaublich schwer gewesen sein.",
    "Wir haben unsere Nachbarn eingeladen und ehrlich erzählt, was fehlt. Am nächsten Morgen standen zwölf Menschen vor der Tür, mit Werkzeug und Kaffee.",
    "Das klingt nach einer überraschenden Wendung. Welche Begegnung aus diesen Tagen ist dir besonders in Erinnerung geblieben?",
    "Ein älterer Mann brachte einen Tisch, den seine verstorbene Frau gebaut hatte. Er sagte, hier soll wieder jemand daran lachen. Da musste ich weinen.",
    "Und heute ist aus diesem Raum ein Treffpunkt für das ganze Quartier geworden. Wie viele Menschen kommen zu euch?",
    "Letzte Woche waren es über dreihundert Gäste. Aber die wichtigste Zahl ist eine andere. Sieben Nachbarn, die vorher niemanden kannten, essen jetzt jeden Freitag zusammen.",
    "Was würdest du rückblickend anders machen? Gibt es etwas, das du anderen Gründerinnen und Gründern unbedingt mitgeben möchtest?",
    "Ich würde früher um Hilfe bitten. Ich dachte immer, Stärke heisst, alles alleine zu schaffen. Heute weiss ich, dass Vertrauen viel mehr Mut braucht.",
    "Gab es auch lustige Pannen? Wir haben bisher viel über die schwierigen und berührenden Momente gesprochen.",
    "Bei der Eröffnung haben wir das Salz mit dem Zucker verwechselt. Der erste Gast nannte unseren Kuchen ein sehr mutiges Konzept. Wir lachen heute noch darüber.",
    "Zum Abschluss eine letzte Frage. Was wünschst du dir für die nächsten Jahre und für die Menschen in deinem Quartier?",
    "Dass die Tür offen bleibt. Nicht nur unsere, sondern auch die Türen zwischen den Menschen. Manchmal beginnt eine grosse Veränderung mit einer kleinen Tasse Kaffee.",
]


def main():
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else ".local-tests")
    directory.mkdir(parents=True, exist_ok=True)
    turns, cursor = [], 0.0
    with wave.open(str(directory / "interview.wav"), "wb") as result:
        result.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for i, text in enumerate(DIALOGUE):
            voice = "Anna" if i % 2 == 0 else "Eddy (Deutsch (Deutschland))"
            aiff, wav = directory / "turn.aiff", directory / "turn.wav"
            subprocess.run(["say", "-v", voice, "-r", "155", "-o", str(aiff), text], check=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(aiff),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav),
                ],
                check=True,
            )
            with wave.open(str(wav), "rb") as piece:
                frames = piece.readframes(piece.getnframes())
                duration = piece.getnframes() / 16000
            result.writeframes(frames)
            turns.append({"start": cursor, "end": cursor + duration, "speaker": f"Stimme {i % 2 + 1}"})
            result.writeframes(b"\0" * 16000)  # 0.5 s Pause
            cursor += duration + 0.5
    (directory / "turns.json").write_text(json.dumps(turns, indent=2), encoding="utf-8")
    for name in ("turn.aiff", "turn.wav"):
        (directory / name).unlink()
    print(f"Fiktives Testinterview: {cursor:.1f} s, {directory / 'interview.wav'}")


if __name__ == "__main__":
    main()
