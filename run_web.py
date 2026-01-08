#!/usr/bin/env python3
"""Start the ClarifyAgent web server."""
import uvicorn
import os

if __name__ == "__main__":
    # Change to project directory for static file serving
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    port = int(os.getenv("PORT", 8080))
    # 注意：多 worker 模式下，session 存储在内存中，不同 worker 之间不共享
    # 这会导致多轮对话（如澄清问答）时 session 状态丢失
    # 默认使用单 worker 模式确保 session 正常工作
    # 如需多 worker，需要实现 Redis 等共享存储
    workers = int(os.getenv("WORKERS", 1))  # 单进程，确保 session 状态共享
    limit_concurrency = int(os.getenv("LIMIT_CONCURRENCY", 100))  # 并发限制
    reload = os.getenv("RELOAD", "false").lower() == "true"  # 开发模式才启用reload
    
    print("🧬 Starting ClarifyAgent Web Server...")
    print(f"📍 Open http://localhost:{port} in your browser")
    print(f"⚙️  Workers: {workers}")
    print(f"⚙️  Max Concurrency: {limit_concurrency}")
    if workers > 1:
        print("⚠️  Warning: 多 worker 模式下 session 不共享，多轮对话可能失效")
        print("   建议使用 WORKERS=1 或实现 Redis session 存储")
    print("-" * 50)
    
    config = {
        "app": "src.clarifyagent.web:app",
        "host": "0.0.0.0",
        "port": port,
        "workers": workers,
        "limit_concurrency": limit_concurrency,
        "log_level": "info"
    }
    
    # reload 和 workers 不能同时使用
    if reload and workers == 1:
        config["reload"] = True
        print("🔄 Auto-reload enabled (development mode)")
    elif reload and workers > 1:
        print("⚠️  Warning: reload disabled when workers > 1")
    
    uvicorn.run(**config)
