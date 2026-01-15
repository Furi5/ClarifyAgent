#!/usr/bin/env python3
"""
简单版本：快速发送多个请求

使用方法：
python simple_multi_request.py
"""

import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://localhost:8080"
API_ENDPOINT = f"{BASE_URL}/api/chat/stream"

# 测试请求
QUERIES = [
    "Keytruda 在美国的首次获批日期",
    "STAT6 小分子抑制剂的开发现状",
    "PD-1 抑制剂的适应症列表",
]


def send_request(query: str, session_id: str = None):
    """发送单个请求（同步版本）"""
    params = {
        "session_id": session_id or "new",
        "message": query
    }
    
    print(f"[发送] {query[:50]}...")
    start = time.time()
    
    try:
        response = requests.get(API_ENDPOINT, params=params, stream=True, timeout=300)
        response.raise_for_status()
        
        # 读取流式响应
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    try:
                        data = json.loads(line_str[6:])
                        if data.get('type') == 'progress':
                            print(f"  [进度] {data.get('stage')}: {data.get('message')}")
                        elif data.get('type') == 'result':
                            print(f"  [完成] {query[:50]}...")
                            break
                    except:
                        pass
        
        elapsed = time.time() - start
        print(f"[完成] {query[:50]}... (耗时: {elapsed:.2f}s)")
        return True, elapsed
    
    except Exception as e:
        elapsed = time.time() - start
        print(f"[错误] {query[:50]}... (耗时: {elapsed:.2f}s): {e}")
        return False, elapsed


def send_parallel(max_workers=3):
    """并发发送多个请求"""
    print(f"\n并发发送 {len(QUERIES)} 个请求 (最大并发: {max_workers})\n")
    
    start = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(send_request, QUERIES))
    total = time.time() - start
    
    success = sum(1 for r in results if r[0])
    print(f"\n完成: {success}/{len(QUERIES)} 成功, 总耗时: {total:.2f}s")


def send_sequential():
    """顺序发送多个请求"""
    print(f"\n顺序发送 {len(QUERIES)} 个请求\n")
    
    session_id = "sequential_test"
    start = time.time()
    
    for query in QUERIES:
        send_request(query, session_id=session_id)
        time.sleep(1)  # 请求之间延迟
    
    total = time.time() - start
    print(f"\n总耗时: {total:.2f}s")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "parallel":
        max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        send_parallel(max_workers)
    else:
        send_sequential()
