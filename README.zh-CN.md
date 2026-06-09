# DailyArticleAgent

DailyArticleAgent 是一个可配置的科研文献情报 agent。它会按照 YAML 专题配置抓取论文、排序筛选、生成每日/每周 Markdown 摘要，并通过本地网页查看结果。启用 OpenAI-compatible LLM 后，它还能对单篇论文生成中文摘要、内容分析、不足判断和后续跟进建议。

[English README](README.md)

## 功能

- 用 YAML 配置不同研究专题
- 支持 arXiv、RSS、Crossref 来源
- 生成每日和每周 Markdown digest
- 可选 LLM 逐篇分析、judge 和 follow-up
- SQLite 保存论文、分类、摘要、运行历史和用户反馈
- 内置 worker、运行历史、失败重试、可选 webhook 告警
- 网页端支持 Markdown 预览、论文详情、反馈、PDF 上传重分析、profile 编辑
- 支持 ZIP 导出/恢复，便于迁移部署

## 安装

需要 Python 3.11+、Node.js 和 npm。推荐使用 [uv](https://docs.astral.sh/uv/)，但项目本身是标准 `pyproject.toml` Python 包，也可以在 Conda 环境中运行。

### uv

Bash:

```bash
uv sync --extra dev
cd front-end
npm install
npm run build
cd ..
```

PowerShell:

```powershell
uv sync --extra dev
Set-Location front-end
npm install
npm run build
Set-Location ..
```

cmd.exe:

```bat
uv sync --extra dev
cd front-end
npm install
npm run build
cd ..
```

### Conda + pip

Conda 只负责 Python 环境；Python 依赖仍然从 `pyproject.toml` 安装，避免维护两套依赖表。

Bash:

```bash
conda create -n daa python=3.11 -y
conda activate daa
python -m pip install -e ".[dev]"
cd front-end
npm install
npm run build
cd ..
```

PowerShell:

```powershell
conda create -n daa python=3.11 -y
conda activate daa
python -m pip install -e ".[dev]"
Set-Location front-end
npm install
npm run build
Set-Location ..
```

cmd.exe:

```bat
conda create -n daa python=3.11 -y
conda activate daa
python -m pip install -e .[dev]
cd front-end
npm install
npm run build
cd ..
```

## 快速开始

查看专题并生成摘要：

```bash
uv run daa profiles
uv run daa daily ai_systems_example
uv run daa weekly ai_systems_example
uv run uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

如果使用已激活的 Conda 环境，去掉 `uv run`：

```bash
daa profiles
daa daily ai_systems_example
daa weekly ai_systems_example
python -m uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

下文仍以 `uv run ...` 为主；如果使用已激活的 Conda 环境，直接运行对应 CLI 命令，网页服务使用 `python -m uvicorn ...`。

打开 `http://<host>:<port>`。

## 配置专题

仓库里的 `config/watch_profiles.yaml` 是公开示例。自己的专题建议复制到本地私有文件，避免提交到 Git。

Bash:

```bash
cp config/watch_profiles.yaml config/watch_profiles.local.yaml
export DAA_CONFIG_PATH=config/watch_profiles.local.yaml
export DAA_DB_PATH=data/articles.sqlite
export DAA_CONTENT_DIR=content
export DAA_TIMEZONE=UTC
```

PowerShell:

```powershell
Copy-Item config/watch_profiles.yaml config/watch_profiles.local.yaml
$env:DAA_CONFIG_PATH = "config/watch_profiles.local.yaml"
$env:DAA_DB_PATH = "data/articles.sqlite"
$env:DAA_CONTENT_DIR = "content"
$env:DAA_TIMEZONE = "UTC"
```

cmd.exe:

```bat
copy config\watch_profiles.yaml config\watch_profiles.local.yaml
set DAA_CONFIG_PATH=config\watch_profiles.local.yaml
set DAA_DB_PATH=data\articles.sqlite
set DAA_CONTENT_DIR=content
set DAA_TIMEZONE=UTC
```

也可以复制 `.env.example` 为 `.env` 后编辑。

## LLM 设置

默认不调用外部模型，只生成规则 fallback 摘要。需要 LLM 分析时加 `--use-llm`。

环境变量示例：

```text
DAA_LLM_API_BASE=https://<openai-compatible-provider>/v1
DAA_LLM_API_KEY=replace-with-your-own-key
DAA_LLM_MODEL=replace-with-model-name
DAA_LLM_CHAT_COMPLETIONS_URL=
```

检查模型接口：

```bash
uv run daa llm-check
```

使用 LLM 生成摘要：

```bash
uv run daa daily all --use-llm
```

## 自动运行和网页

启动内置 worker：

```bash
uv run daa worker all --daily-time 23:30 --weekly-time 23:45 --use-llm
```

启动网页：

```bash
uv run uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

用 ngrok 做外部测试：

```bash
ngrok http 8000
```

网页端可以手动触发 daily/weekly、查看运行历史、重试失败任务、给论文反馈、编辑 profile、上传 PDF 后重新分析。长时间操作会在页面显示状态；请求失败会显示错误信息。

## Docker Compose

Docker Compose 是迁移到其他电脑或服务器时最省事的方式。镜像里包含 Python 后端和已构建的前端；数据库、生成的 Markdown、上传的 PDF、私有 profile 和 `.env` 都留在镜像外，通过挂载目录保存。

准备本地运行文件：

Bash:

```bash
cp .env.example .env
cp config/watch_profiles.yaml config/watch_profiles.local.yaml
mkdir -p data content/daily content/weekly content/readings
```

PowerShell:

```powershell
Copy-Item .env.example .env
Copy-Item config/watch_profiles.yaml config/watch_profiles.local.yaml
New-Item -ItemType Directory -Force data, content/daily, content/weekly, content/readings
```

cmd.exe:

```bat
copy .env.example .env
copy config\watch_profiles.yaml config\watch_profiles.local.yaml
mkdir data
mkdir content\daily
mkdir content\weekly
mkdir content\readings
```

编辑 `.env` 和 `config/watch_profiles.local.yaml`，然后启动网页：

```bash
docker compose up --build web
```

打开 `http://localhost:8000`。

同时启动 scheduler/worker：

```bash
docker compose --profile worker up --build
```

迁移到另一台电脑：

1. clone 仓库。
2. 从旧电脑复制 `.env`、`config/watch_profiles.local.yaml`、`data/articles.sqlite` 和整个 `content/` 目录。
3. 运行 `docker compose up --build web`。

也可以用 ZIP 方式迁移：旧电脑导出，新电脑恢复。

```bash
uv run daa export-data backups/daa.zip
docker compose run --rm web daa restore-data /app/backups/daa.zip --replace
```

## 正文获取和 PDF 上传

agent 会优先尝试合法可访问的证据来源：本地 PDF、arXiv PDF、DOI 页面、公开 PDF 链接、公开 HTML/text 页面。它不会绕过出版社付费墙。

如果某篇文章只能拿到摘要：

1. digest 会保留原文链接，并给出低置信度的摘要级分析。
2. 如果你感兴趣，可以通过自己的合法权限下载 PDF。
3. 在网页论文详情里上传 PDF。
4. agent 会把 PDF 保存到 `content/readings/`，并基于 PDF 重新生成该论文的分析。

## 数据和迁移

这些运行数据默认不会进入 Git：

- `data/articles.sqlite`
- `content/daily/`
- `content/weekly/`
- `content/readings/`
- `config/*.local.yaml`
- `.env`

导出和恢复：

```bash
uv run daa export-data backups/daa.zip
uv run daa restore-data backups/daa.zip --replace
```

## 开发

```bash
uv run ruff check .
uv run pytest
cd front-end && npm run build
```
