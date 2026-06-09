# DailyArticleAgent

DailyArticleAgent is a configurable research literature agent for daily and weekly paper intelligence. It fetches papers from scientific sources, ranks them against YAML watch profiles, optionally asks an OpenAI-compatible model for paper-level analysis, writes Markdown digests, and serves the archive through a local web dashboard.

[中文说明](README.zh-CN.md)

## Features

- YAML watch profiles for different research topics
- arXiv, RSS, and Crossref source adapters
- Daily and weekly Markdown digests
- Optional LLM paper summaries, critique, and follow-up suggestions
- SQLite storage for papers, classifications, digests, runs, and feedback
- Built-in worker, run history, failed-run retry, and optional webhook alerts
- Web dashboard with Markdown preview, paper drawer, feedback, PDF upload, and profile editing
- ZIP export/restore for moving an installation

## Install

Requires Python 3.11+, Node.js, and npm. [uv](https://docs.astral.sh/uv/) is the recommended Python workflow, but the project is a standard `pyproject.toml` package and can also run in Conda.

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

Conda can manage the Python environment; Python dependencies still come from `pyproject.toml`.

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

## Quick Start

List profiles and generate a digest:

```bash
uv run daa profiles
uv run daa daily ai_systems_example
uv run daa weekly ai_systems_example
uv run uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

In an activated Conda environment, drop `uv run`:

```bash
daa profiles
daa daily ai_systems_example
daa weekly ai_systems_example
python -m uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

The rest of this README uses `uv run ...` examples. In an activated Conda environment, run the CLI command directly, or use `python -m uvicorn ...` for the web server.

Open `http://<host>:<port>`.

## Configuration

The tracked `config/watch_profiles.yaml` is a public example. For private topics, copy it to an ignored local file and point the app at it.

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

You can also copy `.env.example` to `.env` and edit it.

## LLM Provider

DailyArticleAgent uses deterministic fallback summaries unless `--use-llm` is set.

Environment variables:

```text
DAA_LLM_API_BASE=https://<openai-compatible-provider>/v1
DAA_LLM_API_KEY=replace-with-your-own-key
DAA_LLM_MODEL=replace-with-model-name
DAA_LLM_CHAT_COMPLETIONS_URL=
```

Check the provider:

```bash
uv run daa llm-check
```

Generate with LLM analysis:

```bash
uv run daa daily all --use-llm
```

## Worker And Web

Run the built-in worker:

```bash
uv run daa worker all --daily-time 23:30 --weekly-time 23:45 --use-llm
```

Serve the web UI:

```bash
uv run uvicorn dailyarticleagent.web:app --host <host> --port <port>
```

For public testing through ngrok:

```bash
ngrok http 8000
```

The web UI can trigger runs, retry failed runs, save feedback, edit profiles, and upload PDFs for reanalysis. Long operations show an in-page status message; if a request fails, the error is shown in the dashboard.

## Docker Compose

Docker Compose is the simplest way to move the app to another machine. The image contains the Python backend and built frontend; your database, generated Markdown, uploaded PDFs, private profile, and `.env` stay outside the image as mounted files.

Prepare local runtime files:

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

Edit `.env` and `config/watch_profiles.local.yaml`, then start the web app:

```bash
docker compose up --build web
```

Open `http://localhost:8000`.

Run the scheduler/worker as well:

```bash
docker compose --profile worker up --build
```

Migration to another machine:

1. Clone the repository.
2. Copy `.env`, `config/watch_profiles.local.yaml`, `data/articles.sqlite`, and the whole `content/` directory from the old machine.
3. Run `docker compose up --build web`.

For ZIP-based migration, you can also export on the old machine and restore on the new one:

```bash
uv run daa export-data backups/daa.zip
docker compose run --rm web daa restore-data /app/backups/daa.zip --replace
```

## Full Text And PDF Uploads

The agent tries public evidence first: local PDFs, arXiv PDFs, DOI pages, public PDF links, and public HTML/text pages. It does not bypass paywalls.

If a paper only has metadata or an abstract:

1. The digest keeps the source link and produces a low-confidence summary.
2. Download the PDF through your own legal access if the paper is important.
3. Upload the PDF from the paper drawer in the web UI.
4. The agent saves the PDF under `content/readings/` and regenerates the paper insight.

## Data And Backup

Generated files are ignored by Git:

- `data/articles.sqlite`
- `content/daily/`
- `content/weekly/`
- `content/readings/`
- `config/*.local.yaml`
- `.env`

Export and restore:

```bash
uv run daa export-data backups/daa.zip
uv run daa restore-data backups/daa.zip --replace
```

## Development

```bash
uv run ruff check .
uv run pytest
cd front-end && npm run build
```
