#!/bin/bash

uv python install 3.12

npm i -g opencode-ai

if [ -t 0 ]; then
  opencode auth login
fi

npm i -g @openchamber/web
