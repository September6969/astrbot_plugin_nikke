"""下载与编码共享一次出卡预算；后台任务由管线统一回收。"""
import asyncio
import math


class VoicePipeline:
    def __init__(self, provider, encoder, *, max_pending=20):
        if not 1 <= max_pending <= 20:
            raise ValueError("语音任务数量超限")
        self.provider, self.encoder = provider, encoder
        self.max_pending = max_pending
        self._tasks = {}
        self._closed = False

    async def resolve(self, map_key, speech_id, locale, *, adapter="aiocqhttp", budget=4):
        if self._closed or adapter != "aiocqhttp":
            return None
        if not math.isfinite(budget) or not 0 < budget <= 5:
            raise ValueError("语音响应预算必须在 0 到 5 秒之间")
        key = (map_key, speech_id, locale, adapter)
        task = self._tasks.get(key)
        if task is None:
            if len(self._tasks) >= self.max_pending:
                return None
            task = asyncio.create_task(self._prepare(*key))
            self._tasks[key] = task
            def completed(done):
                self._tasks.pop(key, None)
                # 读取异常，避免请求已超时后产生未处理的后台异常。
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(completed)
        try:
            # 下载、排队与编码共用外层预算，超时后仅继续准备缓存。
            return await asyncio.wait_for(asyncio.shield(task), budget)
        except (asyncio.TimeoutError, OSError, ValueError):
            return None

    async def _prepare(self, map_key, speech_id, locale, adapter):
        async def work():
            source = await self.provider.resolve(map_key, speech_id, locale, budget=30)
            if source is None:
                return None
            return await self.encoder.encode(source, adapter=adapter)
        # 后台预备也有上限，不能因编码排队永久占用任务槽。
        return await asyncio.wait_for(work(), 35)

    async def close(self):
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.provider.close()
        self._tasks.clear()
