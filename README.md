# Minutes Generator (Offline Meeting Minutes)

This project provides a local web app to generate meeting minutes from Chinese audio recordings (audio file upload), producing minutes in a fixed `Markdown` template with bullet points.

## Overview
- Frontend: upload audio in the browser, show progress, display the final `Markdown`
- Backend: offline transcription (`faster-whisper`) + conservative extraction + render minutes
- Minutes structure (fixed template):
  - `今天聊了什么（议程/主题）` (Agenda / Topics)
  - `讨论要点` (Discussion highlights, per topic as bullets)
  - `最后怎么决定的（安排/共识）` (Only clearly decided items; uncertain ones go to “待确认”)
  - `还没定/需要再确认` (Pending/unresolved items)
  - `还缺什么信息（从录音里没明确到）` (Missing info that was not explicitly stated in the recording)
- Privacy: no cloud API by default; transcription and generation run locally

## Important Note (Model Files)

The code uses the Chinese `faster-whisper medium` model by default and expects model files to be available locally:
- Model directory: `./models/`
- Offline mode by default

## Getting Started (Local Run)

### 1) Prepare the runtime environment
Recommended: Python 3.9.

From the repository root:
```bash
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2) One-time setup: prepare the offline STT model
If the model is not available under `./models/`, do a one-time download in a network-enabled environment:

1) Temporarily allow model downloading:
```bash
WHISPER_LOCAL_FILES_ONLY=false ./venv/bin/uvicorn app.main:app --port 8000
```
2) Open `http://127.0.0.1:8000/`, upload any audio, and wait for the model to be downloaded/loaded
3) Stop the backend after the download completes

Then run in offline mode (default):
```bash
./venv/bin/uvicorn app.main:app --port 8000
```

> Tip: In offline mode, if you get “model not found / cache not ready” errors, check whether `./models/` contains the required files for `faster-whisper medium`.

### 3) Start and use the web page
Start the backend:
```bash
./venv/bin/uvicorn app.main:app --port 8000
```
Open the browser:
`http://127.0.0.1:8000/`

On the page:
- Upload an audio file (`mp3/m4a/wav`)
- (Optional) Fill meeting title / date / club name
- Click “Generate Minutes”
- Copy/save the resulting `Markdown`

## Extraction Rules (Conservative)
To minimize hallucinations:
- `安排/共识（已定）` (Decided / Assigned):
  - Only extract clearly decided/assigned statements into `【已定】`
- `还没定/需要再确认` (Not decided yet / Pending):
  - Put uncertain or pending statements into `【待确认】`
- Owner field:
  - Fill it only when the transcribed sentence explicitly contains a person name/title
  - Otherwise use `负责人未明确`
- Time field:
  - Fill it only when the transcribed sentence explicitly contains time/deadline info
  - Otherwise use `时间未明确`

## Known Limitations (Current Version)
- No advanced speaker diarization yet
- `安排/共识` and pending items use conservative heuristics (better to leave/mark “待确认”)

