#!/usr/bin/env python3
"""Start the ClarifyAgent web server."""
import uvicorn
import os

if __name__ == "__main__":
    # Change to project directory for static file serving
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    port = 8080
    print("🧬 Starting ClarifyAgent Web Server...")
    print(f"📍 Open http://localhost:{port} in your browser")
    print("-" * 50)
    
    uvicorn.run(
        "src.clarifyagent.web:app",
        host="0.0.0.0",
        port=port,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )
