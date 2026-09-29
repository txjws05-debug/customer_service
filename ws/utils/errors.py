class ChatServiceError(Exception):
    """可预期的业务错误。

    消息内容会原样展示给用户：
    - 普通 HTTP 接口由 app 中的 exception handler 转成 400；
    - SSE 流式接口由路由捕获后下发 {"error": "..."} 事件。
    仅用于“用户能理解并据此调整”的情况；意外 bug 不应使用它。
    """
