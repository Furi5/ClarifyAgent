"""HTTP connection pool for performance optimization."""
import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any
from ..config import API_TIMEOUT, MAX_CONCURRENT_REQUESTS

class HTTPConnectionPool:
    """Optimized HTTP connection pool with keep-alive."""
    
    _instance: Optional['HTTPConnectionPool'] = None
    _session: Optional[aiohttp.ClientSession] = None
    _stats: Dict[str, Any] = {}
    
    def __new__(cls) -> 'HTTPConnectionPool':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._stats = {
                'total_requests': 0,
                'connection_reuses': 0,
                'avg_response_time': 0,
                'last_reset': time.time()
            }
        return cls._instance
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create optimized HTTP session."""
        if self._session is None or self._session.closed:
            # Optimized connector configuration
            connector = aiohttp.TCPConnector(
                limit=MAX_CONCURRENT_REQUESTS * 2,  # 总连接池大小
                limit_per_host=MAX_CONCURRENT_REQUESTS,  # 每个主机的连接数
                ttl_dns_cache=300,  # DNS缓存5分钟
                use_dns_cache=True,
                keepalive_timeout=60,  # Keep-alive 60秒
                enable_cleanup_closed=True
            )
            
            # Session timeout configuration
            timeout = aiohttp.ClientTimeout(
                total=API_TIMEOUT,
                connect=10,
                sock_read=API_TIMEOUT
            )
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'ClarifyAgent/1.0 (Optimized)',
                    'Connection': 'keep-alive'
                }
            )
            
            print(f"[DEBUG] HTTP Connection Pool created - Max connections: {MAX_CONCURRENT_REQUESTS}")
        
        return self._session
    
    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make HTTP request with connection pooling."""
        start_time = time.time()
        session = await self.get_session()
        
        try:
            # Track connection reuse
            connection_info = session.connector._conns if hasattr(session.connector, '_conns') else {}
            initial_connections = len(connection_info)
            
            response = await session.request(method, url, **kwargs)
            
            # Update stats
            end_time = time.time()
            response_time = end_time - start_time
            
            self._stats['total_requests'] += 1
            
            # Check if connection was reused
            final_connections = len(connection_info) if hasattr(session.connector, '_conns') else 0
            if final_connections <= initial_connections:
                self._stats['connection_reuses'] += 1
            
            # Update average response time
            total_requests = self._stats['total_requests']
            current_avg = self._stats['avg_response_time']
            self._stats['avg_response_time'] = (current_avg * (total_requests - 1) + response_time) / total_requests
            
            if total_requests % 10 == 0:  # 每10个请求打印一次统计
                reuse_rate = (self._stats['connection_reuses'] / total_requests) * 100
                print(f"[DEBUG] HTTP Pool Stats - Requests: {total_requests}, "
                      f"Reuse Rate: {reuse_rate:.1f}%, "
                      f"Avg Time: {self._stats['avg_response_time']:.2f}s")
            
            return response
            
        except Exception as e:
            print(f"[ERROR] HTTP request failed: {e}")
            raise
    
    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make GET request."""
        return await self.request('GET', url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make POST request."""
        return await self.request('POST', url, **kwargs)
    
    async def close(self):
        """Close the session and cleanup."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            print("[DEBUG] HTTP Connection Pool closed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics."""
        return self._stats.copy()


# Global instance
http_pool = HTTPConnectionPool()


async def optimized_http_get(url: str, **kwargs) -> aiohttp.ClientResponse:
    """Optimized HTTP GET using connection pool."""
    return await http_pool.get(url, **kwargs)


async def optimized_http_post(url: str, **kwargs) -> aiohttp.ClientResponse:
    """Optimized HTTP POST using connection pool."""
    return await http_pool.post(url, **kwargs)