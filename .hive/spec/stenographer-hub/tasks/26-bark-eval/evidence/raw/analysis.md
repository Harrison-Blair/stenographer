## Speed and memory

| run | load s | first decode s | RTF corpus | RTF excerpts | phrase 2-10 s p50 / p95 ms | phrase <2 s p50 ms | peak RSS MB | RSS after load MB | peak GPU MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| turbo-ct2-cuda | 4.4 | 0.65 | 0.0645 | 0.1015 | 343 / 680 | 311 | 1820 | 1048 | 1394 |
| turbo-ct2-cpu | 2.3 | 6.89 | 1.4242 | 2.2639 | 7324 / 15394 | 7094 | 2157 | 1813 | - |
| pro-hf-cuda | 3.5 | 0.98 | 0.0404 | 0.0515 | 193 / 353 | 81 | 2317 | 1122 | 1692 |
| pro-hf-cpu | 3.2 | 0.70 | 0.1279 | 0.1516 | 578 / 990 | 263 | 4935 | 4621 | - |
| pro-sherpa-int8-cpu | 1.9 | 0.48 | 0.0913 | 0.1176 | 450 / 743 | 216 | 1421 | 1240 | - |
| clean-hf-cuda | 27.1 | 0.42 | 0.0384 | 0.0394 | 156 / 310 | 69 | 6216 | 6108 | 3292 |
| clean-hf-cpu | 25.8 | 0.67 | 0.1413 | 0.1355 | 523 / 986 | 230 | 6082 | 6043 | - |
| clean-sherpa-int8-cpu | 2.3 | 0.52 | 0.1000 | 0.1022 | 401 / 753 | 174 | 1426 | 1246 | - |

Phrases: 230 (107 of 2-10 s), 793 s of speech; corpus clips: 120, 609 s.

## Corpus WER % (verbatim references, scripts/transcription_study/scoring.py)

| run | AMI headset | LS clean | LS other | all | AMI, fillers removed from ref and hyp | filler words in hyp (ref has N) | exact clips |
|---|--:|--:|--:|--:|--:|--:|--:|
| turbo-ct2-cuda | 17.12 | 2.31 | 4.63 | 9.17 | 13.18 | 2 (36) | 58/120 |
| turbo-ct2-cpu | 17.99 | 2.69 | 4.86 | 9.71 | 14.09 | 2 (36) | 55/120 |
| pro-hf-cuda | 8.35 | 1.92 | 5.32 | 5.53 | 8.48 | 29 (36) | 71/120 |
| pro-hf-cpu | 8.35 | 1.92 | 5.32 | 5.53 | 8.48 | 29 (36) | 71/120 |
| pro-sherpa-int8-cpu | 7.77 | 1.92 | 5.56 | 5.34 | 7.73 | 32 (36) | 70/120 |
| clean-hf-cuda | 14.24 | 2.31 | 6.02 | 8.32 | 9.70 | 1 (36) | 58/120 |
| clean-hf-cpu | 14.24 | 2.31 | 6.02 | 8.32 | 9.70 | 1 (36) | 58/120 |
| clean-sherpa-int8-cpu | 15.25 | 2.12 | 5.79 | 8.62 | 10.91 | 1 (36) | 52/120 |

## Agreement on the private excerpts: WER % of column against row as reference

| reference \ hypothesis | turbo-ct2-cuda | turbo-ct2-cpu | pro-hf-cuda | pro-hf-cpu | pro-sherpa-int8-cpu | clean-hf-cuda | clean-hf-cpu | clean-sherpa-int8-cpu |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| turbo-ct2-cuda | - | 7.3 | 34.9 | 35.1 | 35.1 | 39.8 | 39.9 | 38.1 |
| turbo-ct2-cpu | 7.3 | - | 34.5 | 34.6 | 34.7 | 38.7 | 38.7 | 37.5 |
| pro-hf-cuda | 34.0 | 33.4 | - | 1.1 | 12.2 | 29.6 | 29.7 | 29.3 |
| pro-hf-cpu | 34.4 | 33.8 | 1.2 | - | 12.0 | 29.4 | 29.4 | 29.0 |
| pro-sherpa-int8-cpu | 33.7 | 33.1 | 12.0 | 11.6 | - | 30.9 | 30.9 | 29.5 |
| clean-hf-cuda | 44.6 | 42.6 | 34.5 | 33.9 | 34.0 | - | 0.1 | 12.0 |
| clean-hf-cpu | 44.7 | 42.7 | 34.5 | 34.0 | 34.1 | 0.1 | - | 12.1 |
| clean-sherpa-int8-cpu | 43.1 | 42.2 | 34.5 | 33.9 | 32.7 | 12.4 | 12.4 | - |

- turbo-ct2-cuda: 2197 words, 4 filler words, 13 empty phrases of 230
- turbo-ct2-cpu: 2179 words, 4 filler words, 13 empty phrases of 230
- pro-hf-cuda: 2260 words, 32 filler words, 8 empty phrases of 230
- pro-hf-cpu: 2249 words, 31 filler words, 7 empty phrases of 230
- pro-sherpa-int8-cpu: 2275 words, 33 filler words, 10 empty phrases of 230
- clean-hf-cuda: 1773 words, 0 filler words, 18 empty phrases of 230
- clean-hf-cpu: 1773 words, 0 filler words, 18 empty phrases of 230
- clean-sherpa-int8-cpu: 1784 words, 0 filler words, 13 empty phrases of 230

## Word timestamps on the excerpt phrases

| run | phrases with text | with word times | invalid (outside phrase ±1 s or end<start) | non-monotonic starts | median word length ms |
|---|--:|--:|--:|--:|--:|
| turbo-ct2-cuda | 217 | 217 | 0 | 0 | 240 |
| turbo-ct2-cpu | 217 | 217 | 0 | 0 | 240 |
| pro-hf-cuda | 222 | 222 | 0 | 0 | 160 |
| pro-hf-cpu | 223 | 223 | 0 | 0 | 160 |
| pro-sherpa-int8-cpu | 220 | 220 | 0 | 0 | 160 |
| clean-hf-cuda | 212 | 212 | 0 | 0 | 160 |
| clean-hf-cpu | 212 | 212 | 0 | 0 | 160 |
| clean-sherpa-int8-cpu | 217 | 217 | 0 | 0 | 160 |

### Start-time difference of matched words (|Δstart|, ms; same normalised word, aligned)

| run A | run B | matched words | median | p90 |
|---|---|--:|--:|--:|
| turbo-ct2-cuda | turbo-ct2-cpu | 2091 | 0 | 20 |
| turbo-ct2-cuda | pro-hf-cuda | 1705 | 90 | 270 |
| turbo-ct2-cuda | pro-hf-cpu | 1696 | 90 | 270 |
| turbo-ct2-cuda | pro-sherpa-int8-cpu | 1707 | 90 | 270 |
| turbo-ct2-cuda | clean-hf-cuda | 1434 | 90 | 320 |
| turbo-ct2-cuda | clean-hf-cpu | 1433 | 90 | 320 |
| turbo-ct2-cuda | clean-sherpa-int8-cpu | 1458 | 80 | 300 |
| turbo-ct2-cpu | pro-hf-cuda | 1709 | 90 | 290 |
| turbo-ct2-cpu | pro-hf-cpu | 1701 | 90 | 290 |
| turbo-ct2-cpu | pro-sherpa-int8-cpu | 1712 | 90 | 280 |
| turbo-ct2-cpu | clean-hf-cuda | 1445 | 90 | 320 |
| turbo-ct2-cpu | clean-hf-cpu | 1444 | 90 | 320 |
| turbo-ct2-cpu | clean-sherpa-int8-cpu | 1461 | 90 | 320 |
| pro-hf-cuda | pro-hf-cpu | 2234 | 0 | 0 |
| pro-hf-cuda | pro-sherpa-int8-cpu | 2074 | 0 | 80 |
| pro-hf-cuda | clean-hf-cuda | 1612 | 10 | 90 |
| pro-hf-cuda | clean-hf-cpu | 1611 | 10 | 90 |
| pro-hf-cuda | clean-sherpa-int8-cpu | 1624 | 10 | 90 |
| pro-hf-cpu | pro-sherpa-int8-cpu | 2073 | 0 | 80 |
| pro-hf-cpu | clean-hf-cuda | 1610 | 10 | 90 |
| pro-hf-cpu | clean-hf-cpu | 1609 | 10 | 90 |
| pro-hf-cpu | clean-sherpa-int8-cpu | 1624 | 10 | 90 |
| pro-sherpa-int8-cpu | clean-hf-cuda | 1602 | 10 | 90 |
| pro-sherpa-int8-cpu | clean-hf-cpu | 1601 | 10 | 90 |
| pro-sherpa-int8-cpu | clean-sherpa-int8-cpu | 1628 | 10 | 90 |
| clean-hf-cuda | clean-hf-cpu | 1771 | 0 | 0 |
| clean-hf-cuda | clean-sherpa-int8-cpu | 1629 | 0 | 80 |
| clean-hf-cpu | clean-sherpa-int8-cpu | 1628 | 0 | 80 |
