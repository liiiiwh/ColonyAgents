"""spawn() 必须持强引用，防 fire-and-forget 任务中途被 GC。"""
import asyncio

import pytest

from app.core import bg_tasks


@pytest.mark.asyncio
async def test_spawn_retains_then_releases():
    started = asyncio.Event()
    release = asyncio.Event()

    async def work():
        started.set()
        await release.wait()

    base = bg_tasks.pending_count()
    task = bg_tasks.spawn(work(), name="t")
    await started.wait()
    # 运行中：被强引用持有
    assert bg_tasks.pending_count() == base + 1
    release.set()
    await task
    await asyncio.sleep(0)  # 让 done-callback 跑
    # 完成后：自动移除
    assert bg_tasks.pending_count() == base
