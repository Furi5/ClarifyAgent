# CLAUDE.md

This file contains project-specific information for Claude Code to help with development tasks.

## Project Information
- **Project Name**: ClarifyAgent
- **Type**: Python web application for clarifying user queries
- **Main Framework**: Flask/FastAPI (web interface)

## Development Commands
```bash
# Run the web application
python run_web.py

# Install dependencies
pip install -r requirements.txt

# Run tests (if available)
pytest

# Lint code (if configured)
flake8 src/

# Type checking (if configured)
mypy src/
```

## Project Structure
- `src/clarifyagent/` - Main application code
  - `clarifier.py` - Core clarification logic
  - `web.py` - Web interface
  - `universal_clarifier.py` - Universal clarifier implementation
  - `static/` - Static web assets
- `run_web.py` - Application entry point
- `README.md` - Project documentation
- `log.md` - Project logs

## Notes
- The project appears to be focused on clarifying user queries or requests
- Web interface available through Flask/FastAPI
- Static files served from `src/clarifyagent/static/`