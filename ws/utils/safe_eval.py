import ast

# 条件表达式中允许的比较运算符
_ALLOWED_COMPARE_OPS = {
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
}
# 允许的布尔 / 一元运算符
_ALLOWED_BOOL_OPS = {ast.And, ast.Or}
_ALLOWED_UNARY_OPS = {ast.Not, ast.USub, ast.UAdd}

# 允许在条件里调用的 slots 方法（白名单）
_ALLOWED_SLOT_CALLS = {"get"}

# 允许作为字面量出现的类型
_ALLOWED_CONST_TYPES = (str, int, float, bool, type(None))


class ConditionSecurityError(ValueError):
    """条件表达式不在白名单内时抛出。"""


class _ConditionValidator(ast.NodeVisitor):
    """逐节点校验，只放行安全的子集：

    - 名字只能访问 `slots`；
    - 下标只能取 `slots[常量]`；
    - 调用只能是 `slots.get(常量[, 默认])`；
    - 比较 / 布尔 / 算术判断所需的最小运算符集合；
    - 禁止属性访问（白名单调用除外）、导入、lambda、推导式、dunder 等。
    """

    def visit_Expression(self, node):
        self.generic_visit(node)

    def visit_Expr(self, node):
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id != "slots":
            raise ConditionSecurityError(f"不允许引用名字：{node.id}")
        self.generic_visit(node)

    def visit_Load(self, node):
        pass

    def visit_Constant(self, node):
        if not isinstance(node.value, _ALLOWED_CONST_TYPES):
            raise ConditionSecurityError("不支持的字面量类型")
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        if type(node.op) not in _ALLOWED_BOOL_OPS:
            raise ConditionSecurityError("不支持的布尔运算符")
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if type(node.op) not in _ALLOWED_UNARY_OPS:
            raise ConditionSecurityError("不支持的一元运算符")
        self.generic_visit(node)

    def visit_BinOp(self, node):
        # 仅放行加减（拼接/算术可能用到），其余拒绝
        if not isinstance(node.op, (ast.Add, ast.Sub)):
            raise ConditionSecurityError("不支持的二元运算符")
        self.generic_visit(node)

    def visit_Compare(self, node):
        for op in node.ops:
            if type(op) not in _ALLOWED_COMPARE_OPS:
                raise ConditionSecurityError("不支持的比较运算符")
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.generic_visit(node)

    def visit_Subscript(self, node):
        # 只允许 slots[常量]
        if not (isinstance(node.value, ast.Name) and node.value.id == "slots"):
            raise ConditionSecurityError("只允许对 slots 按下标取值")
        if not isinstance(node.slice, ast.Constant):
            raise ConditionSecurityError("下标必须是常量")
        self.generic_visit(node)

    def visit_Call(self, node):
        # 只允许 slots.get(...)
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "slots"
                and func.attr in _ALLOWED_SLOT_CALLS):
            raise ConditionSecurityError("只允许调用 slots.get(...)")
        if node.keywords:
            raise ConditionSecurityError("不允许关键字参数")
        # func 已在此整体校验，只逐个访问参数（不再 generic_visit func）
        for arg in node.args:
            if not isinstance(arg, ast.Constant):
                raise ConditionSecurityError("调用参数必须是常量")
            self.visit(arg)

    def visit_List(self, node):
        self.generic_visit(node)

    def visit_Tuple(self, node):
        self.generic_visit(node)

    def generic_visit(self, node):
        # Attribute / Lambda / comprehension / import / dunder 等都会走到这里被拒
        if isinstance(node, (ast.Attribute, ast.Lambda, ast.Dict,
                             ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                             ast.Import, ast.ImportFrom, ast.Starred,
                             ast.FunctionDef, ast.ClassDef, ast.Await)):
            raise ConditionSecurityError(
                f"条件中不允许出现：{type(node).__name__}")
        super().generic_visit(node)


def evaluate_condition(condition: str, slots: dict) -> bool:
    """在白名单保护下求值一个布尔条件。

    等价于原先的 eval(condition, {"slots": slots})，
    但表达式结构必须通过 AST 白名单校验，且 builtins 被屏蔽。
    """
    if not condition or not condition.strip():
        raise ConditionSecurityError("条件为空")
    try:
        tree = ast.parse(condition, mode="eval")
    except SyntaxError as exc:
        raise ConditionSecurityError(f"条件语法非法：{exc}")

    _ConditionValidator().visit(tree)

    safe_globals = {"__builtins__": {}, "slots": slots}
    return bool(eval(compile(tree, "<condition>", "eval"), safe_globals, {}))  # noqa: S307
