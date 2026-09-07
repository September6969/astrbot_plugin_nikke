# AssetManager 预取队列生命周期验收

## 范围

- `resolve_character_assets` 的共享线程池预取任务最多保留 16 项。
- 该数额覆盖一张角色卡当前 11 项资源预取，避免正常单卡无谓降级。
- 队列已满时不等待、不提交任务，直接使用既有 fallback。
- 硬预算到期时，尚未启动的 future 立即取消；已经运行的 Python 线程无法被安全强杀，仍受其底层 I/O 超时约束并返回 fallback。

## 离线验收

- 人为占满全部槽位后，整张卡不调用 executor 的 `submit`，且生成完整 fallback 资源集合。
- 单 worker 阻塞 portrait 后触发 0.05 秒预算，随后释放 worker；已排队的 equipment 任务没有开始执行。
- 全部验证使用合成图片、临时目录和 mock，不访问远端资源、账号或消息通道。

## 未覆盖的边界

- 不杀死已经运行的线程，不保证任意第三方 Python 调用可中断。
- 不替代独立的同键 single-flight、跨实例远端下载限额、Pillow/Spine 资源治理或真实多群负载验收。
