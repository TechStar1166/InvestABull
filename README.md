# Multi-Agent Equity Research Assistant

**Agentic AI - Spring 2026 Project Kickoff**

This repository contains the source code for the **Multi-Agent Equity Research Assistant**, an institutional-grade AI application designed to replace monolithic LLM reasoning with a transparent, collaborative multi-agent workflow. 

By inputting a stock ticker, the system delegates specialized financial analysis tasks to distinct AI agents (Price, Filings, News, Macro) and synthesizes their findings into a structured, evidence-based investment memo. The application features a visible "Agent Trace Log" UI to ensure all logical deductions are highly traceable and auditable.

---

## Architecture & Tech Stack

This project utilizes a **Hybrid Multi-Model Architecture** to optimize for both high-volume data retrieval and elite logical synthesis.

### The "Brain" (AI Models & Orchestration)
* **Framework:** [CrewAI](https://www.crewai.com/)
* **Specialist Agents (High Volume / Retrieval):** Google Gemini 2.5 Flash
* **Coordinator Agent (Complex Synthesis / Logic):** Anthropic Claude 3.5 Sonnet

### The Data Pipeline (APIs & Tools)
* **Price & Quantitative:** `yfinance`
* **SEC Filings & Risks:** SEC EDGAR Database + ChromaDB (Vector Search / RAG)
* **News & Sentiment:** Tavily Agentic Search API
* **Macroeconomics:** FRED API (Federal Reserve Economic Data)

### The Application Layer
* **Frontend:** Next.js (App Router), React, Tailwind CSS
* **Backend:** FastAPI, Python, Pydantic
* **Development Environment:** Cursor IDE

---

## Team Roles & Delegation

To ensure clean execution and avoid merge conflicts, development is strictly divided into three distinct engineering domains:

* **[Name 1] - Frontend & Visualization Engineer**
  * *Domain:* Next.js UI, Tailwind CSS, State Management.
  * *Responsibilities:* Building the dark-mode dashboard, managing asynchronous state for the live "Agent Trace Log," and formatting the final Markdown output.
* **AG - AI Orchestration Lead**
  * *Domain:* FastAPI Backend, CrewAI Routing, Coordinator Prompting.
  * *Responsibilities:* Managing the API endpoints, defining the CrewAI agent topology, and tuning the Claude 3.5 Sonnet Coordinator Agent for conflict resolution.
* **[Name 3] - Data Engineering & API Specialist**
  * *Domain:* Data Pipelines, RAG, Specialist Agent Prompting.
  * *Responsibilities:* Building external tools (yfinance, Tavily, FRED), setting up ChromaDB for SEC filings, and ensuring the Gemini agents return clean, structured data.

---

## Getting Started (Local Development)

### 1. Prerequisites
You will need API keys from the following providers. **NEVER COMMIT THESE KEYS TO GITHUB.**
* [Google AI Studio](https://aistudio.google.com/) (Gemini)
* [Anthropic Console](https://console.anthropic.com/) (Claude)
* [Tavily](https://tavily.com/) (Search)

### 2. Clone the Repository
```bash
git clone [https://github.com/YOUR_GITHUB_USERNAME/equity-research-assistant.git](https://github.com/YOUR_GITHUB_USERNAME/equity-research-assistant.git)
cd equity-research-assistant