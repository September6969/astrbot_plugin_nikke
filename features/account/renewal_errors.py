"""续期公开错误只携带固定状态与脱敏说明。"""


class RenewalFailure(Exception):
    def __init__(self, status: str, detail: str, *, unknown: bool = False):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.unknown = unknown
