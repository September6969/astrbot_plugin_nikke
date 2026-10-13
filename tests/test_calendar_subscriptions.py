"""日程类型订阅、个人艾特路由及持久化去重回归。"""
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from astrbot_plugin_nikke.features.calendar.subscriptions import CalendarSubscriptions
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from astrbot_plugin_nikke.application.commands.contracts import CommandContext

NOW = datetime(2026,10,13,0,tzinfo=timezone.utc)
class Store:
    def __init__(self): self.data={}
    def get_setting(self,k,default=None): return copy.deepcopy(self.data.get(k,default))
    def set_setting(self,k,v): self.data[k]=copy.deepcopy(v)
class Calendar:
    last_sync_error=""
    def __init__(self):
        self.event=CanonicalEvent(id="gamekee:1",title="限时签到",event_type="login",start_at=NOW-timedelta(days=2),end_at=NOW+timedelta(hours=23),sources=["gamekee"],primary_source="gamekee")
        self.context=SimpleNamespace(events=(self.event,),freshness="FRESH")
    def has_snapshot(self): return True
    def freeze_query_context(self,now): return self.context

def context(actor="one",conversation="group:a",private=False):
    return CommandContext(actor_id=actor,conversation_id=conversation,is_private_chat=private)

@pytest.mark.asyncio
async def test_opt_in_type_filter_route_and_restart_dedup():
    store=Store(); calendar=Calendar(); service=CalendarSubscriptions(store,calendar); sent=[]
    async def send(*args): sent.append(args); return True
    await service.dispatch_due(send,now=NOW)
    assert not sent
    service.command(context(),"订阅","协同")
    await service.dispatch_due(send,now=NOW)
    assert not sent
    service.command(context(),"订阅","签到")
    await service.dispatch_due(send,now=NOW)
    assert len(sent)==1 and sent[0][:3]==("group:a","one",False)
    calendar.event.version+=1
    calendar.event.end_at+=timedelta(minutes=30)
    await CalendarSubscriptions(store,calendar).dispatch_due(send,now=NOW)
    assert len(sent)==1

@pytest.mark.asyncio
async def test_per_user_per_conversation_cancel_and_private_route():
    service=CalendarSubscriptions(Store(),Calendar()); sent=[]
    async def send(*args): sent.append(args); return True
    service.command(context(),"订阅","签到")
    service.command(context("two"),"订阅","签到")
    service.command(context("one","private:a",True),"订阅","签到")
    service.command(context(),"取消订阅")
    await service.dispatch_due(send,now=NOW)
    assert {s[:3] for s in sent}=={("group:a","two",False),("private:a","one",True)}

@pytest.mark.asyncio
async def test_failed_unknown_delivery_is_not_replayed():
    service=CalendarSubscriptions(Store(),Calendar()); calls=[]
    service.command(context(),"订阅","签到")
    async def send(*args): calls.append(args); raise TimeoutError()
    await service.dispatch_due(send,now=NOW)
    await service.dispatch_due(send,now=NOW)
    assert len(calls)==1

@pytest.mark.parametrize("change",["expired","unknown_end","cancelled","ended","not_due","sync_error"])
def test_unreliable_and_outside_window_never_notify(change):
    calendar=Calendar(); service=CalendarSubscriptions(Store(),calendar)
    service.command(context(),"订阅","签到")
    if change=="expired": calendar.context.freshness="EXPIRED"
    if change=="unknown_end": calendar.event.end_precision="UNKNOWN"
    if change=="cancelled": calendar.event.is_cancelled=True
    if change=="ended": calendar.event.end_at=NOW
    if change=="not_due": calendar.event.end_at=NOW+timedelta(hours=25)
    if change=="sync_error": calendar.last_sync_error="failure"
    assert not service.plan(now=NOW)


def test_help_invalid_input_and_change_preserve_preferences():
    service=CalendarSubscriptions(Store(),Calendar())
    assert "可选类型" in service.command(context(),"订阅")
    assert not service._state()["targets"]
    service.command(context(),"订阅","协同,签到")
    with pytest.raises(ValueError): service.command(context(),"订阅","不存在")
    assert "协同、签到" in service.command(context(),"订阅状态")


@pytest.mark.asyncio
async def test_runtime_sends_real_at_component_only_for_group():
    from unittest.mock import AsyncMock
    from astrbot_plugin_nikke.adapters.astrbot.runtime import AstrBotRuntimeAdapter
    from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
    from astrbot.api.message_components import At, Plain
    runtime=object.__new__(AstrBotRuntimeAdapter)
    runtime._coordinator=RuntimeCoordinator()
    runtime._context=SimpleNamespace(send_message=AsyncMock(return_value=True))
    async def dispatch(sender):
        await sender("group:a","12345",False,"即将结束")
        await sender("private:a","12345",True,"即将结束")
    runtime._services=SimpleNamespace(calendar_application=SimpleNamespace(subscriptions=SimpleNamespace(dispatch_due=dispatch)))
    await runtime._dispatch_calendar()
    calls=runtime._context.send_message.await_args_list
    assert calls[0].args[0]=="group:a"
    group=calls[0].args[1].chain
    private=calls[1].args[1].chain
    assert isinstance(group[0],At) and str(group[0].qq)=="12345"
    assert all(isinstance(part,Plain) for part in private)
    await runtime._coordinator.close()

@pytest.mark.asyncio
async def test_command_entry_sets_subscription_without_rendering():
    from unittest.mock import Mock,AsyncMock
    from astrbot_plugin_nikke.application.commands.calendar import CalendarCommandHandler
    subs=CalendarSubscriptions(Store(),Calendar())
    render=AsyncMock()
    handler=CalendarCommandHandler(application=SimpleNamespace(subscriptions=subs),payload_builder=Mock(),render=render,start_background_refresh=Mock())
    result=await handler.handle(CommandContext(actor_id="one",conversation_id="group:a",parameters={"horizon":"订阅","page":"签到,协同"}))
    assert "已开启" in result.messages[0].text
    assert "签到、协同" in subs.command(context(),"订阅状态")
    render.assert_not_called()


def test_monthly_pass_and_event_pass_can_be_selected_separately():
    calendar=Calendar(); calendar.event.event_type="pass"; calendar.event.title="10月 Pass"
    service=CalendarSubscriptions(Store(),calendar)
    service.command(context(),"订阅","活动Pass")
    assert not service.plan(now=NOW)
    service.command(context(),"订阅","月度Pass")
    assert len(service.plan(now=NOW))==1


@pytest.mark.asyncio
async def test_scheduler_calendar_subscription_is_independent_and_nonoverlapping():
    import asyncio
    from unittest.mock import AsyncMock
    from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
    from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
    coordinator=RuntimeCoordinator(); gate=asyncio.Event(); calls=[]
    async def dispatch():
        calls.append(1)
        await gate.wait()
    scheduler=RuntimeScheduler(coordinator=coordinator,store=Store(),
        config={"daily_hour":8,"daily_minute":0,"summary_hour":9,"summary_minute":0,"enable_announcement_push":False},
        run_daily=AsyncMock(),send_summary=AsyncMock(),sync_announcements=AsyncMock(),sync_calendar=AsyncMock(),
        dispatch_announcements=AsyncMock(),dispatch_calendar=dispatch,clock=lambda:NOW,unix_time=lambda:1)
    await scheduler.tick(); await asyncio.sleep(0)
    await scheduler.tick(); await asyncio.sleep(0)
    assert calls==[1]
    gate.set()
    await coordinator.close()
