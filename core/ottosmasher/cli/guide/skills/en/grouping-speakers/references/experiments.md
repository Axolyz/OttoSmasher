# Trial results

All from Bocchi the Rock! (2026-10-30): 12 episodes, Netflix Japanese closed captions, vocals separated with HyperACE v2. About 9000 ranges took two to three minutes on CPU. Treat these as a reference point for another show, not a target.

## Models

| Task | Result |
|---|---|
| Cross-episode identification | anime_speaker_embedding (char) 87%, ReDimNet2+ 80%, WeSpeaker ResNet293 72% |
| Real two-speaker cues with both halves split correctly | alignment 63%, pyannote and Nemotron 11–12% |

## With labels

Hiding one fifth of the labels and predicting them, 5 rounds:

| Measure | Result |
|---|---|
| Precision, recall | 95%, 73% |
| Recall under 1 s, 1–2 s, 2 s and longer | 49%, 77%, 85% |
| Recall at 97% precision | 66% |
| Recall with about 240 labelled lines, one round | 53% |
| Same, with a second round adding confident results | 61% |

Logistic regression and one average voiceprint per character did worse. A bonus for "this character is labelled nearby" did not help. With enough samples the second round adds almost nothing.

Without cleaning, the app recorded about 60% of this show's labels.

## Without labels

Thresholds picked on episodes 1–6 and scored on 7–12:

| Measure | Result |
|---|---|
| Precision, recall | 94%, 65% |
| Recall under 1 s | 36% |
| Recall with the 5 most similar samples instead of the average | 60%; 14% under 1 s |
| Ceiling using all labels as voice samples | about 63% for the voiceprint alone |

Twenty groups were enough; more did not raise recall. Using unnamed small groups as negatives halved recall. The limit is the voiceprint itself (short lines, similar voices), not the grouping.
Mistakes concentrated between Nijika and Ryo, and between Hitori and Nijika or Kita.

## A full cleaning run

On 2026-10-31 the 12 episodes were cleaned with skill `cleaning-subtitles`. Of 227 two-person cues, 210 were split and 17 left alone because one line was not found. Of 2882 unlabelled cues, 2129 got a speaker from voiceprints, calibrated to 97% precision.
