"""Intelligent concurrency control for performance optimization."""
import asyncio
import time
from typing import List, Any, Optional
from ..config import MAX_CONCURRENT_REQUESTS, ADAPTIVE_CONCURRENCY

class ConcurrencyManager:
    """Dynamic concurrency control based on API performance."""
    
    def __init__(self, initial_max: int = None):
        self.max_concurrent = initial_max or MAX_CONCURRENT_REQUESTS
        self.adaptive_enabled = ADAPTIVE_CONCURRENCY
        
        # Performance tracking
        self.response_times: List[float] = []
        self.error_count: int = 0
        self.total_requests: int = 0
        self.last_adjustment: float = time.time()
        
        # Adaptive thresholds
        self.fast_threshold = 5.0      # 响应时间<5s认为快
        self.slow_threshold = 15.0     # 响应时间>15s认为慢
        self.error_threshold = 0.1     # 错误率>10%认为压力过大
        
        print(f"[DEBUG] ConcurrencyManager initialized - "
              f"Max: {self.max_concurrent}, Adaptive: {self.adaptive_enabled}")
    
    def record_request(self, response_time: float, success: bool = True):
        """记录请求性能数据"""
        self.response_times.append(response_time)
        self.total_requests += 1
        
        if not success:
            self.error_count += 1
        
        # 只保留最近50次请求的数据
        if len(self.response_times) > 50:
            self.response_times.pop(0)
        
        # 每10个请求调整一次并发度
        if self.adaptive_enabled and self.total_requests % 10 == 0:
            self._adjust_concurrency()
    
    def _adjust_concurrency(self):
        """基于性能数据动态调整并发数"""
        current_time = time.time()
        
        # 至少间隔30秒才调整一次
        if current_time - self.last_adjustment < 30:
            return
        
        if len(self.response_times) < 5:
            return
        
        # 计算最近的平均响应时间
        recent_avg = sum(self.response_times[-10:]) / min(10, len(self.response_times))
        
        # 计算错误率
        error_rate = self.error_count / self.total_requests if self.total_requests > 0 else 0
        
        old_max = self.max_concurrent
        
        # 调整逻辑
        if error_rate > self.error_threshold:
            # 错误率过高，降低并发
            self.max_concurrent = max(1, self.max_concurrent - 1)
            reason = f"high error rate ({error_rate:.2%})"
            
        elif recent_avg > self.slow_threshold:
            # 响应时间太慢，降低并发
            self.max_concurrent = max(1, self.max_concurrent - 1)
            reason = f"slow response ({recent_avg:.1f}s)"
            
        elif recent_avg < self.fast_threshold and error_rate < 0.05:
            # 响应快且错误率低，可以提高并发
            self.max_concurrent = min(8, self.max_concurrent + 1)  # 最大不超过8
            reason = f"fast response ({recent_avg:.1f}s)"
            
        else:
            # 保持当前并发度
            return
        
        if old_max != self.max_concurrent:
            print(f"[DEBUG] Concurrency adjusted: {old_max} → {self.max_concurrent} "
                  f"(reason: {reason})")
            self.last_adjustment = current_time
    
    async def run_with_concurrency(self, tasks: List[Any], max_override: Optional[int] = None) -> List[Any]:
        """以控制的并发度执行任务列表"""
        if not tasks:
            return []
        
        max_concurrent = max_override or self.max_concurrent
        print(f"[DEBUG] Running {len(tasks)} tasks with max concurrency: {max_concurrent}")
        
        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def run_with_semaphore(task):
            async with semaphore:
                start_time = time.time()
                try:
                    result = await task
                    response_time = time.time() - start_time
                    self.record_request(response_time, success=True)
                    return result
                except Exception as e:
                    response_time = time.time() - start_time
                    self.record_request(response_time, success=False)
                    raise e
        
        # 包装所有任务
        wrapped_tasks = [run_with_semaphore(task) for task in tasks]
        
        # 并发执行
        start_time = time.time()
        results = await asyncio.gather(*wrapped_tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # 统计结果
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count
        
        print(f"[DEBUG] Batch completed: {success_count}/{len(results)} successful, "
              f"total time: {total_time:.2f}s, "
              f"avg per task: {total_time/len(results):.2f}s")
        
        return results
    
    def get_current_max(self) -> int:
        """获取当前最大并发数"""
        return self.max_concurrent
    
    def get_stats(self) -> dict:
        """获取性能统计"""
        if not self.response_times:
            return {"no_data": True}
        
        return {
            "max_concurrent": self.max_concurrent,
            "total_requests": self.total_requests,
            "error_rate": self.error_count / self.total_requests if self.total_requests > 0 else 0,
            "avg_response_time": sum(self.response_times) / len(self.response_times),
            "recent_avg_response_time": sum(self.response_times[-10:]) / min(10, len(self.response_times))
        }


# Global instance
concurrency_manager = ConcurrencyManager()


async def run_concurrent_tasks(tasks: List[Any], max_concurrent: Optional[int] = None) -> List[Any]:
    """使用智能并发控制运行任务"""
    return await concurrency_manager.run_with_concurrency(tasks, max_concurrent)