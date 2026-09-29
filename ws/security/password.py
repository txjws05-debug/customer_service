import bcrypt


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希，返回可存储的字符串。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与已存储的 bcrypt 哈希是否匹配。"""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
