# Round 010 — exact original worker reports and supersession

Each `.txt` archive is the **verbatim original GitHub comment body** (no newline normalization or editing). SHA-256 is calculated over those exact UTF-8 bytes.

- **Agent 5 original (superseded by correction)**: [original issue comment 6905591124](https://github.com/k1moradi/swapz/issues/127#issuecomment-6905591124); [verbatim text](agent5-original-report.txt); SHA-256 `47b1180cae84d76f9f7b19425704684d45477ed5c906bc3352c8cb911a6f17d0`.
- **Agent 5 authoritative correction**: [original issue comment 6905615744](https://github.com/k1moradi/swapz/issues/127#issuecomment-6905615744); [verbatim text](agent5-correction-original.txt); SHA-256 `b02cd557cda9b1612ceedaf1687be39856fc76e43285d6e6a93252457a8857ed`.
- **Agent 8 source report**: [original issue comment 6905616311](https://github.com/k1moradi/swapz/issues/127#issuecomment-6905616311); [verbatim text](agent8-original-report.txt); SHA-256 `ca374bec263974b662eb0a147824fa650c9203b4436383ef93734ef8148c2098`.

Only corrected **Agent 5 source commit [`9b3fa386`](https://github.com/k1moradi/swapz/commit/9b3fa3867677149f1a43a0d97d1e5b396ec8aa08)** is authoritative, not the earlier `0f8026ad...` described by the superseded original report. Agent 8 authoritative source is [`f1cd9113`](https://github.com/k1moradi/swapz/commit/f1cd9113f843a373a0feb625cff90f83cb8c9473). Both have frozen parent `4f88c81dcba4ee09d32f067e7353664a821ba986`.
