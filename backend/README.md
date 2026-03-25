# Minutes Generator (Offline MVP)

这是一个“先跑通接口与网页”的离线 MVP（目前的转写/抽取用占位逻辑）。

## 启动
1. 创建虚拟环境：
   - `python3 -m venv venv`
2. 安装依赖：
   - `pip install -r requirements.txt`
3. 启动服务（在 `backend/` 目录下）：
   - `uvicorn app.main:app --reload --port 8000`
4. 打开浏览器：
   - `http://localhost:8000/`

## 离线 STT 模型（必须先准备）
离线转写使用 `faster-whisper` 的本地模型，代码默认会把模型下载到：
`backend/models/`

第一次运行如果本地没有模型，需要你在“有网络的环境”里先下载一次：
1. 先启动服务前临时允许下载（只用于第一次）：
   - `WHISPER_LOCAL_FILES_ONLY=false ./venv/bin/uvicorn app.main:app --port 8000`
2. 访问页面并上传任意音频，等待模型下载完成
3. 后续就改回离线模式（默认即为离线）即可：
   - `./venv/bin/uvicorn app.main:app --port 8000`

如果你想完全离线且不允许联网下载，建议把 `WHISPER_LOCAL_FILES_ONLY` 保持默认值（true）。

