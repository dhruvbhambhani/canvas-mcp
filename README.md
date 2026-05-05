# canvas-mcp

An open-source MCP server that gives Claude Code real-time Canvas LMS data, accurate grade calculation, and AI-powered study tools.

Canvas's built-in grade display ignores syllabus weights, drop-lowest rules, and bonus points. This fixes that.

## What it does

- **Real grades** — computed from your syllabus weights, not Canvas's simplified display
- **What do I need?** — tells you exactly what score you need on remaining work to hit a target grade
- **All due dates** — across every course in one query
- **Study tools** — generate flashcards from any Canvas page on demand
- **14 MCP tools** — all queryable in plain English through Claude Code

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get your Canvas API token

1. Log into Canvas
2. Go to Account → Settings
3. Scroll to Approved Integrations → click **New Access Token**
4. Name it `Claude Code` and copy the token

### 3. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
CANVAS_URL=https://yourschool.instructure.com
CANVAS_TOKEN=your_canvas_token_here
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Test the data layer

```bash
python canvas_client.py
```

Should print your courses and assignment categories.

### 5. Add to Claude Code

On Windows, edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "canvas": {
      "command": "python",
      "args": ["C:/Users/dhruv/Documents/mcp_canvas/server.py"],
      "env": {
        "CANVAS_URL": "https://yourschool.instructure.com",
        "CANVAS_TOKEN": "your_canvas_token_here",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Restart Claude Code. The 14 tools appear automatically.

## Tools

| Tool | Description |
|------|-------------|
| `get_real_grade` | Weighted grade using syllabus weights |
| `what_do_i_need` | Score needed on remaining work for a target grade |
| `list_courses_with_grades` | All courses + real grades in one call |
| `get_grade_breakdown` | Category-by-category view with contributions |
| `get_syllabus_weights` | Parsed grade distribution from syllabus |
| `list_assignments` | Assignments with due dates and submission status |
| `get_assignment_details` | Full details including description and rubric |
| `list_upcoming_due_dates` | Due dates across all courses in the next N days |
| `get_grades` | Raw scores for every assignment in a course |
| `get_syllabus` | Full syllabus text |
| `list_modules` | Course modules and items |
| `get_page_content` | Text content of a Canvas page |
| `list_announcements` | Recent announcements from a course |
| `generate_flashcards` | Q&A flashcards generated from any Canvas page |
| `refresh_cache` | Clear cached data to force fresh fetch |

## Example queries

```
What's my real grade in ESET 349?
What do I need on the final to get an A in MMET 275?
What assignments do I have due this week across all my courses?
Generate flashcards from the Chapter 4 page in ESET 349
Show me all unsubmitted assignments
Am I on track for a 3.8 GPA this semester?
```

## Architecture

```
Claude Code
    │ stdio (MCP protocol)
server.py (FastMCP)
    ├── canvas_client.py   Canvas REST API wrapper
    ├── syllabus_parser.py Claude-powered HTML → structured JSON
    ├── grade_calculator.py weighted grade math, drop-lowest, what-if
    └── cache.py           JSON file cache with TTL
```

Cache TTLs: syllabus weights 24h · course list 1h · page content 2h · assignment scores never cached.

## Canvas API

Reading your own data via a personal access token is fully allowed — Canvas published this API specifically for student and developer use. You are only accessing your own account.
