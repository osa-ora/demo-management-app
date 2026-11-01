# Demo Management

**Version 1.0 Beta** · AI chat for DemoIgnite-powered technical demo operations.

Demo Management provides a three-panel workspace: conversation history, an AI chat session, and a live DemoIgnite catalog. It uses the same lightweight application stack as the companion local apps: Python, FastAPI, and plain HTML/CSS/JavaScript.

<img width="1709" height="836" alt="Screenshot 2026-11-01 at 2 55 38 PM" src="https://github.com/user-attachments/assets/826eeafd-7227-47eb-a9cb-92294ab0c11a" />


## Features

- Three-panel workspace with session history, conversational assistant, and demo catalog.
- Ollama is the default AI provider. On first launch the app checks the local Ollama API, attempts `ollama serve` if it is not running, and uses the first installed model only for initial setup. After that, the selected model is retained and can be changed explicitly in Settings.
- Selected model is displayed in the chat header.
- DemoIgnite MCP is preconfigured at `http://127.0.0.1:8085/mcp`; the user can add, edit, enable, disable, or remove other HTTP or stdio MCP servers.
- MCP tools are discovered from configured servers and made available to the Ollama model for tool calling.
- Skills management supports local skill folders containing `SKILL.md`, plus creation of skill files from Settings. Installed skill instructions are included in the assistant's system context.
- Background monitoring checks MCP connectivity and configuration, installed Ollama models, and the skills directory every 15 seconds. Changes are reflected automatically; the demo catalog is refreshed when MCP configuration or connectivity changes (and periodically while connected). A selected model that is removed is flagged and cannot be used until another installed model is selected.
- Midnight, Cloud, and Graphite themes.
- About panel, responsive layout, persistent chat history, and launcher commands.

## Requirements

- Python 3.11+
- Ollama installed locally, with at least one model pulled (for example `ollama pull llama3.1:8b`).
- DemoIgnite source code available locally. Configure its repository directory in **Settings → MCP servers**; Demo Management can then start, stop, and restart the MCP process.
- Internet access on first launch to install Python dependencies and load the Google Fonts/Lucide assets.

## Start

### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

The launcher creates `.venv`, installs requirements, starts the server in the background, and opens `http://127.0.0.1:8767` when ready.

```bash
./run.sh status
./run.sh stop
./run.sh start
./run.sh restart
```

### Windows

```bat
run.bat
run.bat status
run.bat stop
```

## First launch

1. Launch Demo Management.
2. Open **Settings → MCP servers** and set the DemoIgnite source-code directory. It must contain `app.py` and `requirements.txt`. Save the location.
3. If DemoIgnite MCP is offline and a source directory is saved, Demo Management automatically starts it on startup. On first launch without a saved location, the app opens the MCP settings tab.
4. The first start creates a `.venv` inside the DemoIgnite repository, installs its requirements, and runs `app.py`. No separate startup script is required.
5. Use **Start**, **Stop**, and **Restart** in Settings → MCP servers to manage the process. Demo Management only stops a process it launched; an independently running MCP server is left untouched. A process launched by Demo Management is also stopped when Demo Management shuts down.
6. The app checks Ollama. If the service is unavailable, it attempts to start `ollama serve` when the executable is installed.
7. If one or more models are installed, the first launch selects the first available model as the initial default. Open **Settings → AI model** to select a different model. Once selected, the app does not randomly switch models.

## Configuration and data

User data is stored under `~/.demo-management/` (or `%USERPROFILE%\\.demo-management` on Windows). Set `DEMO_MANAGEMENT_HOME` to override it.

- `config.json` — provider, selected model, theme, MCP server definitions, DemoIgnite source location, and skills directory.
- `demoignite-process.json` — PID and repository location for the DemoIgnite process started and managed by this app.
- `sessions.json` — local chat sessions and message history.
- `skills/` — local skill folders. Each skill folder should contain `SKILL.md`.
- `server.log` / `server.pid` — launcher log and process ID on macOS/Linux.

Default web port is `8767`; override with `DM_PORT`.

## MCP integration

DemoIgnite is configured by default as a Streamable HTTP MCP server at `http://127.0.0.1:8085/mcp`. The app discovers tools from enabled MCP servers and exposes them as model tools. DemoIgnite's catalog uses the `list_demos` MCP tool. If the configured endpoint is offline at startup, Demo Management uses the repository directory saved in Settings (`demoignite_path`) to launch DemoIgnite. The repository must contain `app.py` and `requirements.txt`. The app creates `.venv` if needed, installs the requirements, and executes `app.py`; no separate shell script is needed. Settings provides Start, Stop, and Restart controls. The app tracks the PID of processes it starts and never stops an externally managed MCP process. A managed process is stopped when Demo Management shuts down. Startup output is written to `~/.demo-management/logs/demoignite.log`.

Other MCP servers can be configured in Settings using Streamable HTTP or stdio transport. For stdio servers, provide the executable and one argument per line. Only configure trusted MCP servers: tools may execute commands or modify infrastructure according to the permissions of the server process.

## Skills

Manage skills in Settings → Skills. A skill is a folder under the configured skills directory containing `SKILL.md`. The app includes these instructions in the model's system context. Skill files are trusted prompt content; review them before use.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Run checks:

```bash
PYTHONPATH=. pytest -q
python -m py_compile app/main.py run.py
node --check app/static/js/app.js
```

## Project structure

```text
demo-management/
├── app/
│   ├── main.py
│   ├── templates/index.html
│   └── static/
│       ├── css/app.css
│       └── js/app.js
├── tests/test_smoke.py
├── README.md
├── requirements.txt
├── pyproject.toml
├── run.py
├── run.sh
└── run.bat
```

**Demo Management · Version 1.0 Beta**

Powered by Osama Oransa.
