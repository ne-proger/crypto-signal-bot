import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

# Хелпер: безопасно выполнять sync-функции CCXT/Pandas в тредпуле
_executor = ThreadPoolExecutor(max_workers=8)

async def run_sync(func: Callable, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))
