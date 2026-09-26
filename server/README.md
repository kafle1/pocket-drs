---
title: Pocket DRS
emoji: 🏏
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: agpl-3.0
short_description: Analysis server for the Pocket DRS LBW app
---

The analysis server behind the Pocket DRS app. It takes a phone clip of one delivery and returns
the ball path, speed and the LBW call.

Get the app and the source at https://github.com/kafle1/pocket-drs

`make space` from the repo root deploys this folder to the Hugging Face Space. Run
`huggingface-cli login` once first.
