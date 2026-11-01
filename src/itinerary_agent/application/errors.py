"""应用层错误。

控制器只负责把 AppError 映射成 HTTP；不在 handler 里散落权限/找不到逻辑。
"""


class AppError(Exception):
    status_code = 400
    code = "APP_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class BadRequest(AppError):
    status_code = 400
    code = "BAD_REQUEST"
