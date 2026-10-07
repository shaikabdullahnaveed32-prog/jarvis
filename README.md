# JARVIS

JARVIS is a personal AI assistant I am building for macOS.

The goal of the project is to create an assistant that can understand natural language, have conversations, remember context, and interact with the computer instead of only responding with text.

## Current Features

* AI conversations using Groq
* Natural language command understanding
* Voice input and output
* Mac automation
* Browser control
* Local memory
* Custom JARVIS interface
* Local configuration for API keys and sensitive data

## How It Works

JARVIS is built around an AI brain that interprets what the user asks and connects that understanding to different parts of the system.

```text
User
  |
  v
JARVIS Interface
  |
  v
AI Brain
  |
  +---- Groq
  |
  +---- Memory
  |
  +---- Computer Automation
  |
  +---- Browser
  |
  v
Action / Response
```

The project is still under development, so some capabilities are being improved and tested.

## Technology

* Python
* Groq API
* SQLite
* HTML
* CSS
* JavaScript
* macOS automation
* Browser automation
* Text-to-Speech

## Project Structure

```text
jarvis/
├── core/
├── data/
├── models/
├── ui/
├── main.py
├── server.py
├── setup_voice.py
├── run.sh
├── JARVIS.command
└── README.md
```

## Setup

JARVIS is currently developed and tested on macOS.

Clone the repository:

```bash
git clone https://github.com/shaikabdullahnaveed32-prog/jarvis.git
cd jarvis
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

The Groq API key is stored locally and is not included in the repository.

Do not upload API keys or other private credentials to GitHub.

## Models

Some local model files are not included in the repository because of their size. They need to be downloaded separately when setting up the project.

## Future Plans

JARVIS is an ongoing project. Some of the things I want to add include:

* More reliable computer control
* Better contextual memory
* More application integrations
* Improved voice interaction
* Safer confirmation for important actions
* More autonomous workflows
* Support for additional AI models
* A "God's Eye" style view that gives JARVIS a broader real-time view of information and activity
* A more advanced system for connecting different tools and services

## Why I Built It

I wanted to build something beyond a chatbot.

The idea is to make JARVIS an assistant that can understand what I mean, use the tools available on my computer, and eventually become a more capable interface between me and my digital environment.

This project is still being built and improved.
