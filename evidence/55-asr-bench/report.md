# ASR CPU benchmark report — 2026-10-20

This report copies the model-by-setting table from `docs/transcription-experiments.md`. It covers six cached models, int8, beam sizes 1 and 5, hotwords off/on, and context off/reference/decoded. It uses the same 60 public dev clips (741 reference words) and the same 6.49-second dictation clip for all settings. Reference context is an upper bound. The default baseline is medium.en / int8 / beam 1 / hotwords on / context off.

The RSS column records sampled worker-process RSS. Models ran sequentially, so later settings may include resident memory from prior models. See the docs for isolated three-clip model-footprint pilots and the recommendation. No production default changed.

| Model | Setting | WER | Median | p90 | Extra vs default | RTF | RSS peak |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium.en | beam 1; hotwords off; context off | 12.01% (89/741) | 1.953 s | 1.983 s | +0.083 s | 0.301x | 1.45 GiB |
| medium.en | beam 1; hotwords off; context reference (upper bound) | 12.55% (93/741) | 1.856 s | 2.776 s | -0.014 s | 0.286x | 1.45 GiB |
| medium.en | beam 1; hotwords off; context decoded | 12.15% (90/741) | 1.805 s | 1.838 s | -0.066 s | 0.278x | 1.45 GiB |
| medium.en | beam 1; hotwords on; context off | 11.34% (84/741) | 1.870 s | 1.995 s | +0.000 s | 0.288x | 1.45 GiB |
| medium.en | beam 1; hotwords on; context reference (upper bound) | 11.61% (86/741) | 1.864 s | 1.882 s | -0.006 s | 0.287x | 1.45 GiB |
| medium.en | beam 1; hotwords on; context decoded | 10.80% (80/741) | 1.535 s | 1.580 s | -0.335 s | 0.237x | 1.46 GiB |
| medium.en | beam 5; hotwords off; context off | 10.66% (79/741) | 1.933 s | 2.008 s | +0.063 s | 0.298x | 1.46 GiB |
| medium.en | beam 5; hotwords off; context reference (upper bound) | 14.30% (106/741) | 1.761 s | 1.806 s | -0.109 s | 0.271x | 1.46 GiB |
| medium.en | beam 5; hotwords off; context decoded | 12.01% (89/741) | 1.971 s | 1.978 s | +0.101 s | 0.304x | 1.46 GiB |
| medium.en | beam 5; hotwords on; context off | 16.19% (120/741) | 3.383 s | 3.403 s | +1.513 s | 0.521x | 1.57 GiB |
| medium.en | beam 5; hotwords on; context reference (upper bound) | 23.35% (173/741) | 3.549 s | 3.783 s | +1.679 s | 0.547x | 1.61 GiB |
| medium.en | beam 5; hotwords on; context decoded | 17.68% (131/741) | 2.510 s | 2.545 s | +0.640 s | 0.387x | 1.64 GiB |
| medium | beam 1; hotwords off; context off | 12.28% (91/741) | 1.847 s | 1.888 s | -0.023 s | 0.285x | 2.10 GiB |
| medium | beam 1; hotwords off; context reference (upper bound) | 10.66% (79/741) | 1.755 s | 1.782 s | -0.115 s | 0.270x | 2.10 GiB |
| medium | beam 1; hotwords off; context decoded | 12.15% (90/741) | 1.395 s | 1.425 s | -0.475 s | 0.215x | 2.10 GiB |
| medium | beam 1; hotwords on; context off | 15.52% (115/741) | 1.899 s | 1.914 s | +0.029 s | 0.293x | 2.10 GiB |
| medium | beam 1; hotwords on; context reference (upper bound) | 11.20% (83/741) | 1.848 s | 1.876 s | -0.022 s | 0.285x | 2.10 GiB |
| medium | beam 1; hotwords on; context decoded | 16.06% (119/741) | 1.858 s | 1.913 s | -0.012 s | 0.286x | 2.10 GiB |
| medium | beam 5; hotwords off; context off | 11.07% (82/741) | 1.879 s | 1.969 s | +0.008 s | 0.289x | 2.10 GiB |
| medium | beam 5; hotwords off; context reference (upper bound) | 10.12% (75/741) | 1.492 s | 1.509 s | -0.378 s | 0.230x | 2.10 GiB |
| medium | beam 5; hotwords off; context decoded | 11.47% (85/741) | 1.454 s | 1.651 s | -0.416 s | 0.224x | 2.10 GiB |
| medium | beam 5; hotwords on; context off | 15.38% (114/741) | 2.166 s | 2.294 s | +0.296 s | 0.334x | 2.10 GiB |
| medium | beam 5; hotwords on; context reference (upper bound) | 10.26% (76/741) | 2.327 s | 3.981 s | +0.457 s | 0.359x | 2.27 GiB |
| medium | beam 5; hotwords on; context decoded | 11.47% (85/741) | 2.012 s | 2.020 s | +0.142 s | 0.310x | 2.10 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords off; context off | 10.12% (75/741) | 1.664 s | 1.776 s | -0.206 s | 0.256x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords off; context reference (upper bound) | 8.10% (60/741) | 1.452 s | 1.553 s | -0.418 s | 0.224x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords off; context decoded | 9.31% (69/741) | 1.892 s | 1.942 s | +0.022 s | 0.292x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords on; context off | 10.26% (76/741) | 1.983 s | 1.991 s | +0.113 s | 0.306x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords on; context reference (upper bound) | 8.64% (64/741) | 1.929 s | 2.024 s | +0.059 s | 0.297x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 1; hotwords on; context decoded | 10.53% (78/741) | 2.039 s | 2.075 s | +0.169 s | 0.314x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords off; context off | 9.31% (69/741) | 1.683 s | 1.729 s | -0.188 s | 0.259x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords off; context reference (upper bound) | 8.50% (63/741) | 1.540 s | 1.638 s | -0.331 s | 0.237x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords off; context decoded | 10.66% (79/741) | 2.261 s | 2.813 s | +0.391 s | 0.348x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords on; context off | 11.88% (88/741) | 2.209 s | 2.411 s | +0.339 s | 0.340x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords on; context reference (upper bound) | 8.37% (62/741) | 1.605 s | 1.684 s | -0.265 s | 0.247x | 2.28 GiB |
| large-v3-turbo-ct2 | beam 5; hotwords on; context decoded | 10.39% (77/741) | 1.535 s | 1.602 s | -0.335 s | 0.237x | 2.28 GiB |
| distil-medium.en | beam 1; hotwords off; context off | 13.77% (102/741) | 0.819 s | 0.892 s | -1.051 s | 0.126x | 2.06 GiB |
| distil-medium.en | beam 1; hotwords off; context reference (upper bound) | 30.50% (226/741) | 0.875 s | 0.912 s | -0.995 s | 0.135x | 2.06 GiB |
| distil-medium.en | beam 1; hotwords off; context decoded | 23.21% (172/741) | 0.830 s | 0.855 s | -1.041 s | 0.128x | 2.06 GiB |
| distil-medium.en | beam 1; hotwords on; context off | 98.25% (728/741) | 0.784 s | 0.795 s | -1.087 s | 0.121x | 2.06 GiB |
| distil-medium.en | beam 1; hotwords on; context reference (upper bound) | 98.65% (731/741) | 0.822 s | 0.837 s | -1.048 s | 0.127x | 2.06 GiB |
| distil-medium.en | beam 1; hotwords on; context decoded | 98.38% (729/741) | 0.818 s | 0.835 s | -1.052 s | 0.126x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords off; context off | 14.04% (104/741) | 0.857 s | 0.929 s | -1.013 s | 0.132x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords off; context reference (upper bound) | 22.94% (170/741) | 1.535 s | 1.554 s | -0.335 s | 0.236x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords off; context decoded | 24.43% (181/741) | 0.794 s | 0.813 s | -1.076 s | 0.122x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords on; context off | 95.95% (711/741) | 7.955 s | 8.049 s | +6.085 s | 1.226x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords on; context reference (upper bound) | 95.55% (708/741) | 0.752 s | 0.819 s | -1.118 s | 0.116x | 2.06 GiB |
| distil-medium.en | beam 5; hotwords on; context decoded | 95.28% (706/741) | 8.675 s | 8.896 s | +6.805 s | 1.337x | 2.06 GiB |
| distil-small.en | beam 1; hotwords off; context off | 12.28% (91/741) | 0.330 s | 0.344 s | -1.540 s | 0.051x | 2.03 GiB |
| distil-small.en | beam 1; hotwords off; context reference (upper bound) | 14.84% (110/741) | 0.330 s | 0.343 s | -1.541 s | 0.051x | 2.03 GiB |
| distil-small.en | beam 1; hotwords off; context decoded | 13.09% (97/741) | 0.338 s | 0.357 s | -1.532 s | 0.052x | 2.03 GiB |
| distil-small.en | beam 1; hotwords on; context off | 99.73% (739/741) | 0.585 s | 0.588 s | -1.286 s | 0.090x | 2.03 GiB |
| distil-small.en | beam 1; hotwords on; context reference (upper bound) | 97.57% (723/741) | 1.439 s | 1.445 s | -0.432 s | 0.222x | 2.03 GiB |
| distil-small.en | beam 1; hotwords on; context decoded | 100.27% (743/741) | 0.567 s | 0.582 s | -1.303 s | 0.087x | 2.03 GiB |
| distil-small.en | beam 5; hotwords off; context off | 12.96% (96/741) | 0.343 s | 0.347 s | -1.527 s | 0.053x | 2.03 GiB |
| distil-small.en | beam 5; hotwords off; context reference (upper bound) | 13.36% (99/741) | 0.359 s | 0.360 s | -1.511 s | 0.055x | 2.03 GiB |
| distil-small.en | beam 5; hotwords off; context decoded | 12.96% (96/741) | 0.359 s | 0.373 s | -1.511 s | 0.055x | 2.03 GiB |
| distil-small.en | beam 5; hotwords on; context off | 109.99% (815/741) | 0.900 s | 0.924 s | -0.970 s | 0.139x | 2.03 GiB |
| distil-small.en | beam 5; hotwords on; context reference (upper bound) | 109.45% (811/741) | 0.921 s | 0.942 s | -0.949 s | 0.142x | 2.03 GiB |
| distil-small.en | beam 5; hotwords on; context decoded | 108.77% (806/741) | 0.928 s | 0.937 s | -0.942 s | 0.143x | 2.03 GiB |
| base.en | beam 1; hotwords off; context off | 15.79% (117/741) | 0.150 s | 0.160 s | -1.720 s | 0.023x | 2.00 GiB |
| base.en | beam 1; hotwords off; context reference (upper bound) | 15.11% (112/741) | 0.156 s | 0.157 s | -1.715 s | 0.024x | 2.00 GiB |
| base.en | beam 1; hotwords off; context decoded | 14.98% (111/741) | 0.158 s | 0.159 s | -1.712 s | 0.024x | 2.00 GiB |
| base.en | beam 1; hotwords on; context off | 22.67% (168/741) | 0.247 s | 0.259 s | -1.623 s | 0.038x | 2.00 GiB |
| base.en | beam 1; hotwords on; context reference (upper bound) | 19.84% (147/741) | 0.245 s | 0.247 s | -1.625 s | 0.038x | 2.00 GiB |
| base.en | beam 1; hotwords on; context decoded | 20.51% (152/741) | 0.243 s | 0.248 s | -1.627 s | 0.038x | 2.00 GiB |
| base.en | beam 5; hotwords off; context off | 15.79% (117/741) | 0.161 s | 0.173 s | -1.710 s | 0.025x | 2.00 GiB |
| base.en | beam 5; hotwords off; context reference (upper bound) | 15.65% (116/741) | 0.160 s | 0.165 s | -1.710 s | 0.025x | 2.00 GiB |
| base.en | beam 5; hotwords off; context decoded | 17.54% (130/741) | 0.156 s | 0.168 s | -1.714 s | 0.024x | 2.00 GiB |
| base.en | beam 5; hotwords on; context off | 26.99% (200/741) | 0.363 s | 0.364 s | -1.507 s | 0.056x | 2.00 GiB |
| base.en | beam 5; hotwords on; context reference (upper bound) | 27.40% (203/741) | 0.363 s | 0.375 s | -1.507 s | 0.056x | 2.00 GiB |
| base.en | beam 5; hotwords on; context decoded | 28.74% (213/741) | 0.366 s | 0.372 s | -1.504 s | 0.056x | 2.00 GiB |
