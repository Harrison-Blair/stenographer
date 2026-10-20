# Files preview visual check

I compared the before and after 150 by 45 pilot renders with the approved Files board at `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`. The board source is `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Files.dc.html`. Both screen captures use fake services and synthetic preview lines only. No audio or model was used.

Every preview line shows its speaker label text, such as `Speaker 1` or `Speaker 2`. This text distinguishes speakers without colour. Colour only adds a visual cue. The labels stay visible in the plain text render.

| Board element | Result | Comparison |
| --- | --- | --- |
| Preview timestamps | Matches | Each line starts with its timestamp. |
| Speaker labels | Differs by rule | The board uses colored chips. Files shows bold orange and purple labels with no fill, as required by the shared speaker palette and no-background rule. The speaker names remain visible on every line. |
| Transcript text | Matches | Each speaker label is followed by its synthetic sample text. |
| Speaker 1 and Speaker 2 distinction | Matches | The labels use the shared stable colors: orange for Speaker 1 and purple for Speaker 2. Their names also distinguish them without colour. |

Before and after files are `before-files.{svg,txt,png}` and `after-files.{svg,txt,png}` in this directory. The board image remains in the hive home and is not included here.
