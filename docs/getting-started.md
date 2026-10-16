# Getting Started

This guide will help you get OpenKitsune up and running quickly.

## Prerequisites

Before you begin, ensure you have:

- **Python 3.11+** installed
- An **Anthropic API key** ([get one here](https://console.anthropic.com/))
- **Git** for cloning the repository

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or .\venv\Scripts\activate  # Windows

# Install OpenKitsune (core)
pip install openkitsune

# Optional features
pip install "openkitsune[all]"      # install all optional features
# pip install "openkitsune[windows]"  # Windows desktop automation
# pip install "openkitsune[feishu]"   # Feishu (Lark)

# Run setup wizard
openkitsune init
```

### Option 2: One-click install script (PyPI)

Linux/macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.ps1 | iex
```

To install extras / use a mirror, download and run with parameters (recommended):

```bash
curl -fsSL -o quickstart.sh https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.sh
bash quickstart.sh --extras all --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

```powershell
irm https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.ps1 -OutFile quickstart.ps1
.\quickstart.ps1 -Extras all -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

### Option 3: Install from Source (Development)

```bash
git clone https://github.com/openkitsune/openkitsune.git
cd openkitsune
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -e ".[all,dev]"
openkitsune init
```

## Configuration

### 1. Create Environment File

```bash
cp examples/.env.example .env
```

### 2. Add Your API Key

Edit `.env` and set your Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-your-api-key-here
```

### 3. Optional Settings

```bash
# Custom API endpoint (useful for proxies)
ANTHROPIC_BASE_URL=https://api.anthropic.com

# Model selection
DEFAULT_MODEL=claude-sonnet-4-20250514

# Agent behavior
MAX_ITERATIONS=100
AUTO_CONFIRM=false
```

## Your First Run

### Start the CLI

```bash
openkitsune
```

You should see:

```
╭─────────────────────────────────────────╮
│           OpenKitsune v0.5.9                │
│   A Self-Evolving AI Agent              │
╰─────────────────────────────────────────╯

You> 
```

### Try a Simple Task

```
You> Hello, what can you do?
```

OpenKitsune will introduce itself and explain its capabilities.

### Try a Complex Task

```
You> Create a Python script that calculates prime numbers up to 100
```

Watch as OpenKitsune:
1. Analyzes the task
2. Writes the code
3. Tests it
4. Reports the results

## Common Commands

| Command | Description |
|---------|-------------|
| `openkitsune` | Start interactive mode |
| `openkitsune run "task"` | Execute a single task |
| `openkitsune status` | Show agent status |
| `openkitsune selfcheck` | Run self-diagnostics |
| `openkitsune --help` | Show all commands |

## Next Steps

- [Architecture Overview](architecture.md) - Understand how OpenKitsune works
- [Configuration Guide](configuration.md) - All configuration options
- [Skills System](skills.md) - Create custom skills
- [IM Channels](im-channels.md) - Set up Telegram, etc.

## Troubleshooting

### "API key not found"

Ensure your `.env` file exists and contains `ANTHROPIC_API_KEY`.

### "Connection timeout"

Check your network connection. If in China, consider using a proxy:

```bash
ANTHROPIC_BASE_URL=https://your-proxy-url
```

### "Python version error"

OpenKitsune requires Python 3.11+. Check your version:

```bash
python --version
```

### Need More Help?

- Check [GitHub Issues](https://github.com/openkitsune/openkitsune/issues)
- Join [GitHub Discussions](https://github.com/openkitsune/openkitsune/discussions)
