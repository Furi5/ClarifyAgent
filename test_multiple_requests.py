#!/usr/bin/env python3
"""
测试脚本：并发发送多个请求到 ClarifyAgent Web API

使用方法：
1. 确保 web 服务器正在运行：python run_web.py
2. 运行此脚本：python test_multiple_requests.py
"""

import asyncio
import aiohttp
import json
import time
from typing import List, Dict

# 配置
BASE_URL = "http://localhost:8080"  # 根据实际端口调整
API_ENDPOINT = f"{BASE_URL}/api/chat/stream"

# 测试请求列表
TEST_REQUESTS = [
    "Keytruda 在美国的首次获批日期",
    "STAT6 小分子抑制剂的开发现状",
    "PD-1 抑制剂的适应症列表",
]


async def send_single_request(session: aiohttp.ClientSession, query: str, session_id: str = None) -> Dict:
    """发送单个请求并收集所有响应"""
    params = {
        "session_id": session_id or "new",
        "message": query
    }
    
    print(f"[请求] 发送: {query[:50]}... (session_id: {params['session_id']})")
    start_time = time.time()
    
    responses = []
    try:
        async with session.get(API_ENDPOINT, params=params) as response:
            if response.status != 200:
                return {
                    "query": query,
                    "success": False,
                    "error": f"HTTP {response.status}",
                    "responses": []
                }
            
            # 读取流式响应
            async for line in response.content:
                if line:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: '):
                        try:
                            data = json.loads(line_str[6:])  # 移除 'data: ' 前缀
                            responses.append(data)
                            # 打印进度更新
                            if data.get('type') == 'progress':
                                print(f"  [进度] {data.get('stage', 'unknown')}: {data.get('message', '')}")
                        except json.JSONDecodeError:
                            pass
            
            elapsed = time.time() - start_time
            
            # 查找最终结果
            final_result = None
            for resp in responses:
                if resp.get('type') == 'result':
                    final_result = resp
                    break
            
            return {
                "query": query,
                "success": True,
                "elapsed": elapsed,
                "session_id": params['session_id'],
                "num_responses": len(responses),
                "has_result": final_result is not None,
                "final_result_type": final_result.get('response_type') if final_result else None
            }
    
    except Exception as e:
        return {
            "query": query,
            "success": False,
            "error": str(e),
            "elapsed": time.time() - start_time
        }


async def send_parallel_requests(queries: List[str], max_concurrent: int = 3) -> List[Dict]:
    """并发发送多个请求"""
    print(f"\n{'='*60}")
    print(f"并发发送 {len(queries)} 个请求 (最大并发: {max_concurrent})")
    print(f"{'='*60}\n")
    
    async with aiohttp.ClientSession() as session:
        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def send_with_semaphore(query: str, idx: int):
            async with semaphore:
                print(f"[任务 {idx+1}/{len(queries)}] 开始: {query[:50]}...")
                result = await send_single_request(session, query, session_id=f"test_{idx}")
                print(f"[任务 {idx+1}/{len(queries)}] 完成: {query[:50]}... (耗时: {result.get('elapsed', 0):.2f}s)")
                return result
        
        # 创建所有任务
        tasks = [send_with_semaphore(query, idx) for idx, query in enumerate(queries)]
        
        # 并发执行
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        return results, total_time


async def send_sequential_requests(queries: List[str]) -> List[Dict]:
    """顺序发送多个请求（使用同一个 session）"""
    print(f"\n{'='*60}")
    print(f"顺序发送 {len(queries)} 个请求（使用同一个 session）")
    print(f"{'='*60}\n")
    
    session_id = "sequential_test"
    results = []
    
    async with aiohttp.ClientSession() as session:
        for idx, query in enumerate(queries):
            print(f"\n[请求 {idx+1}/{len(queries)}]")
            result = await send_single_request(session, query, session_id=session_id)
            results.append(result)
            await asyncio.sleep(1)  # 请求之间稍作延迟
    
    return results


def print_summary(results: List[Dict], total_time: float, mode: str):
    """打印结果摘要"""
    print(f"\n{'='*60}")
    print(f"测试摘要 ({mode})")
    print(f"{'='*60}")
    print(f"总请求数: {len(results)}")
    print(f"总耗时: {total_time:.2f}s")
    print(f"平均耗时: {total_time/len(results):.2f}s per request")
    
    success_count = sum(1 for r in results if r.get('success'))
    print(f"成功: {success_count}/{len(results)}")
    
    if success_count > 0:
        avg_elapsed = sum(r.get('elapsed', 0) for r in results if r.get('success')) / success_count
        print(f"平均响应时间: {avg_elapsed:.2f}s")
    
    print(f"\n详细结果:")
    for idx, result in enumerate(results, 1):
        status = "✓" if result.get('success') else "✗"
        elapsed = result.get('elapsed', 0)
        print(f"  {status} [{idx}] {result['query'][:40]}... ({elapsed:.2f}s)")
        if not result.get('success'):
            print(f"     错误: {result.get('error', 'Unknown')}")


async def main():
    """主函数"""
    print("🧪 ClarifyAgent 多请求测试工具")
    print(f"📍 目标服务器: {BASE_URL}")
    print(f"📍 API 端点: {API_ENDPOINT}")
    
    # 检查服务器是否运行
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/") as response:
                if response.status != 200:
                    print(f"❌ 服务器未运行或无法访问 (HTTP {response.status})")
                    print(f"   请先运行: python run_web.py")
                    return
    except Exception as e:
        print(f"❌ 无法连接到服务器: {e}")
        print(f"   请先运行: python run_web.py")
        return
    
    print("✓ 服务器连接正常\n")
    
    # 选择测试模式
    print("选择测试模式:")
    print("1. 并发请求（多个 session，同时发送）")
    print("2. 顺序请求（同一个 session，依次发送）")
    
    choice = input("\n请选择 (1/2，默认1): ").strip() or "1"
    
    if choice == "1":
        # 并发请求
        max_concurrent = int(input("最大并发数 (默认3): ").strip() or "3")
        results, total_time = await send_parallel_requests(TEST_REQUESTS, max_concurrent)
        print_summary(results, total_time, "并发模式")
    else:
        # 顺序请求
        results = await send_sequential_requests(TEST_REQUESTS)
        total_time = sum(r.get('elapsed', 0) for r in results)
        print_summary(results, total_time, "顺序模式")


if __name__ == "__main__":
    asyncio.run(main())
