"""workflow 结构检查：把「只有改 workflow 时才踩得到」的坑变成断言。

线上真实踩过：deploy job 只在服务器上通过 SSH 操作，本地不需要仓库代码，
所以它原本没有 actions/checkout。后来给它加了一步
`bash deploy/check-secrets.sh`，结果直接
`bash: deploy/check-secrets.sh: No such file or directory`（exit 127），
整条部署挂掉 —— 而这种错在本地跑单测、跑脚本测试都发现不了。
"""

import pathlib
import re

import yaml

WORKFLOW_DIR = pathlib.Path(__file__).parents[1] / ".github" / "workflows"
REPO_ROOT = pathlib.Path(__file__).parents[1]

# 引用了仓库内脚本的路径特征（相对于仓库根）
_REPO_SCRIPT = re.compile(r"bash\s+([\w./-]+\.sh)")


def _workflows() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    }


def _steps():
    """产出 (workflow 名, job 名, job, step) 便于逐条检查。"""
    for name, doc in _workflows().items():
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                yield name, job_name, job, step


def test_workflow_yaml_is_parseable():
    workflows = _workflows()
    assert workflows, "没有找到任何 workflow 文件"
    for name, doc in workflows.items():
        assert doc.get("jobs"), f"{name} 里没有 jobs"


def test_referenced_scripts_exist():
    """workflow 里 `bash xxx.sh` 引用的文件必须真的在仓库里。"""
    missing = []
    for name, _job_name, _job, step in _steps():
        for match in _REPO_SCRIPT.finditer(step.get("run") or ""):
            path = match.group(1)
            if not (REPO_ROOT / path).is_file():
                missing.append(f"{name} 引用了 {path}，但仓库里没有这个文件")
    assert not missing, "\n".join(missing)


def test_jobs_using_repo_scripts_checkout_first():
    """引用仓库内脚本的 job 必须先 checkout，否则脚本根本不存在。

    这就是上面那次事故：deploy job 因为「不需要代码」而没 checkout，
    一旦有步骤要跑仓库里的脚本，就会 exit 127。
    """
    problems = []
    for name, doc in _workflows().items():
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            has_checkout = any(
                str(step.get("uses", "")).startswith("actions/checkout")
                for step in steps
            )
            if has_checkout:
                continue
            for step in steps:
                for match in _REPO_SCRIPT.finditer(step.get("run") or ""):
                    path = match.group(1)
                    if path.startswith(("deploy/", "tests/")):
                        problems.append(
                            f"{name} 的 job「{job_name}」引用了 {path}，"
                            f"但这个 job 没有 actions/checkout")
    assert not problems, "\n".join(problems)


def test_deploy_job_passes_embedding_config_to_ssh_step():
    """embedding 配置必须同时出现在 env 和 envs 里，少一个就传不到服务器。

    env 提供值，envs 决定哪些变量被转发到远端，两者缺一不可。
    """
    deploy = _workflows()["deploy.yml"]["jobs"]["deploy"]
    ssh_step = next(
        step for step in deploy["steps"]
        if str(step.get("uses", "")).startswith("appleboy/ssh-action")
    )

    env_keys = set((ssh_step.get("env") or {}).keys())
    envs = {item.strip() for item in (ssh_step["with"].get("envs") or "").split(",")}

    for key in ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY"):
        assert key in env_keys, f"{key} 不在 SSH 步骤的 env 里"
        assert key in envs, f"{key} 不在 SSH 步骤的 envs 里（不会被转发到服务器）"


def test_only_changed_images_are_built():
    """未改动的组件必须走「复用 manifest」而不是重新构建。

    否则一次只改前端的 push 也会重建后端和中台镜像：多花几分钟构建，
    服务器还要多拉几百 MB。判定逻辑在 deploy/detect-changes.sh 里。
    """
    doc = _workflows()["deploy.yml"]

    changes = doc["jobs"].get("changes")
    assert changes, "缺少 changes 作业：无法判断该重建哪些镜像"
    assert "images_csv" in str(changes.get("outputs")), "changes 必须输出 images_csv"

    checkout = next(
        step for step in changes["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout")
    )
    # 浅克隆 diff 不到上一次推送的提交，判定会直接失效
    assert checkout["with"].get("fetch-depth") == 0, "changes 作业必须 fetch-depth: 0"

    build = doc["jobs"]["build-and-push"]
    assert "changes" in build["needs"], "build-and-push 必须依赖 changes 作业"

    steps = build["steps"]
    reuse = [s for s in steps if "imagetools" in str(s.get("run", ""))]
    assert reuse, "缺少「复用上次镜像」的步骤"
    assert "images_csv" in str(reuse[0].get("if", "")), "复用步骤必须按 images_csv 判断"

    build_step = next(
        step for step in steps
        if str(step.get("uses", "")).startswith("docker/build-push-action")
    )
    assert "images_csv" in str(build_step.get("if", "")), "构建步骤必须按 images_csv 判断"
    # 两个条件必须互补，否则会出现「既没构建也没复用」的空洞
    assert "!" in str(reuse[0]["if"]), "复用条件应为「不在 images_csv 里」"
    assert "!" not in str(build_step["if"]), "构建条件应为「在 images_csv 里」"


def test_deploy_is_skipped_for_docs_only_changes():
    """只改文档时不该部署（镜像走复用，构建作业仍会跑完）。"""
    deploy = _workflows()["deploy.yml"]["jobs"]["deploy"]
    assert "changes" in deploy["needs"], "deploy 必须依赖 changes 才能读到 deploy_needed"
    assert "deploy_needed" in str(deploy.get("if", "")), "deploy 必须按 deploy_needed 判断"
