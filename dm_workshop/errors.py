class WorkshopError(Exception):
    """可以安全转换为 Web/MCP 错误响应的业务异常基类。"""


class NotFoundError(WorkshopError):
    pass


class RuleError(WorkshopError):
    pass


class ConflictError(WorkshopError):
    pass
