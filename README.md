# Minutes Generator

This project is a local web app for generating meeting minutes from Chinese meeting audio. It is designed for student society workflows and currently supports two meeting types:

- `management_weekly`
- `recruitment_prep`

The app follows this pipeline:

`Upload audio -> Choose meeting type -> Local transcription -> Structured summary -> Offline fallback if needed -> Render Markdown`

## Overview

- Frontend: upload audio, choose meeting type, track progress, and view the final Markdown
- Backend: local `faster-whisper` transcription + provider-based structured summarization + Markdown rendering
- Summary providers:
  - `ollama` for local/open-source models such as Qwen
  - `openai` for compatible remote APIs
- Fallback: if structured summarization fails, the backend falls back to a local rule-based summary

## Supported Meeting Types

### `management_weekly`
Output focuses on:

- department updates
- coordination issues
- weekly decisions
- weekly todos
- pending items

### `recruitment_prep`
Output focuses on:

- weekly progress
- additional information
- next week focus
- key decisions
- weekly todos
- risks or pending items

## Requirements

- Python 3.9+ recommended
- Local Whisper model files for transcription
- Optional: Ollama for local Qwen-based summarization
- Optional: API credentials if you want to use an OpenAI-compatible provider

## Installation

From the repository root:

```bash
cd backend
python3 -m venv generator
./generator/bin/pip install -r requirements.txt
./generator/bin/pip install requests
```

## 1. Prepare the Local Transcription Model

The backend uses `faster-whisper` for local transcription. By default it expects the model to be available under:

```bash
./models/
```

If the model is not available yet, do a one-time download in a network-enabled environment:

```bash
cd backend
WHISPER_LOCAL_FILES_ONLY=false ./generator/bin/uvicorn app.main:app --port 8000
```

Then:

1. Open `http://127.0.0.1:8000/`
2. Upload any audio file
3. Wait until the model is downloaded and loaded
4. Stop the server

After that, you can run with local-only Whisper mode again:

```bash
cd backend
./generator/bin/uvicorn app.main:app --port 8000
```

## 2. Configure the Summary Provider

The project supports two structured summary providers.

### Option A: Local Qwen via Ollama

This is the recommended setup if you want lower long-term cost and local inference.

Install Ollama first, then open one terminal and start the Ollama service:

```bash
ollama serve
```

Keep that terminal running.

Open a second terminal and pull a Qwen model such as:

```bash
ollama pull qwen2.5:7b
```

You can verify that Ollama is available with:

```bash
curl http://localhost:11434/api/tags
```

Then, in the backend terminal, set these environment variables before starting the app:

```bash
cd backend
export SUMMARY_PROVIDER=ollama
export OLLAMA_API_URL=http://localhost:11434/api/chat
export OLLAMA_MODEL=qwen2.5:7b
export ONLINE_SUMMARY_TIMEOUT=180
```

Notes:

- `SUMMARY_PROVIDER=ollama` makes the backend use the local Ollama API
- `OLLAMA_MODEL` should match the model name you actually pulled
- `ollama serve` must keep running while you are using local model summarization
- If Ollama summarization fails, the app automatically falls back to the local rule-based summary

### Option B: OpenAI-Compatible API

If you want to use a remote provider instead, configure:

```bash
cd backend
export SUMMARY_PROVIDER=openai
export ONLINE_SUMMARY_API_KEY=your_api_key
export ONLINE_SUMMARY_API_URL=https://api.openai.com/v1/chat/completions
export ONLINE_SUMMARY_MODEL=gpt-4o-mini
export ONLINE_SUMMARY_TIMEOUT=180
```

Notes:

- `ONLINE_SUMMARY_API_URL` can point to any compatible chat-completions endpoint
- If the request fails, the app automatically falls back to the local rule-based summary

## 3. Start the Backend

### Recommended startup flow for local Qwen + Ollama

Terminal 1:

```bash
ollama serve
```

Terminal 2:

```bash
cd backend
export SUMMARY_PROVIDER=ollama
export OLLAMA_API_URL=http://localhost:11434/api/chat
export OLLAMA_MODEL=qwen2.5:7b
export ONLINE_SUMMARY_TIMEOUT=180
WHISPER_LOCAL_FILES_ONLY=false ./generator/bin/uvicorn app.main:app --port 8000
```

### Offline-only startup flow

If you want to test the app without Ollama, you can run the backend by itself:

```bash
cd backend
WHISPER_LOCAL_FILES_ONLY=false ./generator/bin/uvicorn app.main:app --port 8000
```

Then open:

```text
http://127.0.0.1:8000/
```

## 4. Use the Web App

On the page:

1. Upload an audio file (`mp3`, `m4a`, or `wav`)
2. Choose a meeting type
3. Optionally fill in the meeting date
4. Decide whether to enable structured online summary
   - Leave it enabled if Ollama or a remote provider is configured
   - Disable it if you want to force the local fallback summary
5. Click `Generate Minutes`
6. Review, copy, or download the generated Markdown

## Environment Variables

### Transcription

```bash
WHISPER_LOCAL_FILES_ONLY=false
```

### Summary Provider Selection

```bash
SUMMARY_PROVIDER=ollama
```

Supported values:

- `ollama`
- `openai`

### Ollama

```bash
OLLAMA_API_URL=http://localhost:11434/api/chat
OLLAMA_MODEL=qwen2.5:7b
```

### OpenAI-Compatible Provider

```bash
ONLINE_SUMMARY_API_KEY=your_api_key
ONLINE_SUMMARY_API_URL=https://api.openai.com/v1/chat/completions
ONLINE_SUMMARY_MODEL=gpt-4o-mini
ONLINE_SUMMARY_TIMEOUT=180
```

## Current Behavior

- Audio transcription is always local
- Structured summarization uses the configured provider
- If structured summarization is disabled or fails, the backend falls back to a local rule-based summary
- Markdown is always rendered by backend code, not directly by the model

## Known Limitations

- No speaker diarization yet
- The offline fallback summary is heuristic and less polished than model-based summarization
- Long meetings may require a stronger local model for better structured output
- Local Qwen quality and speed depend heavily on your machine and the model size
