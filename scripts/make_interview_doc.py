# -*- coding: utf-8 -*-
"""生成面试用的项目介绍文档（DOCX）。

用法：<bundled python> scripts/make_interview_doc.py
"""

from __future__ import annotations

import pathlib

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUT = pathlib.Path("面试项目介绍-电商智能客服.docx")

CJK = "微软雅黑"
LATIN = "Segoe UI"


def _font(style, size: int, bold: bool = False, color: tuple[int, int, int] | None = None):
    style.font.name = LATIN
    style.font.size = Pt(size)
    style.font.bold = bold
    if color:
        style.font.color.rgb = RGBColor(*color)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), CJK)


def add(doc, text: str, size: int = 10.5, bold: bool = False, color=None,
        space_after: int = 4, align=None):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = LATIN
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
    if color:
        run.font.color.rgb = RGBColor(*color)
    paragraph.paragraph_format.space_after = Pt(space_after)
    if align:
        paragraph.alignment = align
    return paragraph


def bullet(doc, text: str, size: int = 10.5):
    paragraph = doc.add_paragraph(style="List Bullet")
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.name = LATIN
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
    paragraph.paragraph_format.space_after = Pt(2)
    return paragraph


def table(doc, rows: list[list[str]], widths: list[float] | None = None):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Light Grid Accent 1"
    for r, row in enumerate(rows):
        for c, cell_text in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            run = paragraph.add_run(cell_text)
            run.font.size = Pt(9.5)
            run.font.bold = (r == 0)
            run.font.name = LATIN
            run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
            paragraph.paragraph_format.space_after = Pt(0)
    doc.add_paragraph()
    return table


def build() -> None:
    doc = Document()
    _font(doc.styles["Normal"], 10.5)
    _font(doc.styles["Heading 1"], 15, bold=True, color=(0x1F, 0x2A, 0x44))
    _font(doc.styles["Heading 2"], 12.5, bold=True, color=(0x1F, 0x2A, 0x44))
    _font(doc.styles["List Bullet"], 10.5)

    title = doc.add_heading("面试项目介绍：电商智能客服（对话驱动的交易闭环）", level=0)
    _font(title.style, 19, bold=True, color=(0x1F, 0x2A, 0x44))
    add(doc, "线上面向客户：http://txjws.dpdns.org      代码：github.com/txjws05-debug/customer_service",
        size=10, color=(0x55, 0x55, 0x55), space_after=10)

    # ============================================================ 1
    doc.add_heading("一、30 秒速览（开场就用这段）", level=1)
    add(doc, "这是一个「对话驱动交易」的电商智能客服系统：用户在和客服对话的过程中，不只能问规则、"
             "查订单物流，还能直接加购、下单、支付、确认收货、申请售后；后台是一套业务闭环完整的电商中台，"
             "订单与售后都跑在真实的状态机上。全栈我自己实现，部署在阿里云上，CI/CD 从构建到自检全自动。")
    add(doc, "三个我最想讲、也最有数据的点：")
    bullet(doc, "检索质量有闭环：41 条标注评测集，Recall@1 从 91.7% 提到 100%，MRR 0.949 → 1.000，"
                "而且评测顺手暴露了「分数门槛根本挡不住超纲问题」这个结论。")
    bullet(doc, "并发正确性：10 个并发抢 3 件库存，结果恰好 3 单成功、7 单被拒、库存归零不超卖；"
                "这中间我还真踩到并修掉了一个丢失更新的 bug。")
    bullet(doc, "缓存边界设计：Redis 命中率 99.0%、吞吐提升 24%，但库存这种强一致字段永远不进缓存。")

    # ============================================================ 2
    doc.add_heading("二、2 分钟标准口述稿（按顺序念下来就是完整介绍）", level=1)
    for text in [
        "① 背景与目标：我想做一个「能真的办完事」的客服，而不只是问答机器人。所以它既要能答业务规则，"
        "又要能真的操作订单——查物流、退货、加购下单。",
        "② 我的做法：把系统拆成三块。前端 Next.js；客服 Agent 用 FastAPI + LangChain，"
        "核心是我写的两层决策（先判断这轮是办业务、答知识还是闲聊，再收集槽位、执行动作）；"
        "电商中台独立成服务，订单、售后、优惠券、积分、库存都在它这边，用状态机保证状态不会乱跳。",
        "③ 关键设计一：流程声明化。所有对话流程和槽位写在 user_flows.yml 里，"
        "新增一个业务能力 = 加一个 action + 一条流程，不用改对话引擎。",
        "④ 关键设计二：检索用向量 + 字面混合，而且我给它配了评测闭环，改动前后能对比。",
        "⑤ 关键设计三：交易侧的强一致。下单扣库存用行锁，缓存只加速读、绝不承接写，"
        "库存永远直连数据库。",
        "⑥ 交付：Docker Compose + Caddy 反代，GitHub Actions 构建推送到 GHCR，再由 SSH 部署到阿里云，"
        "部署脚本会自检（比如探一次真实接口、跑一遍检索评测），出问题自己先修一遍再报错。",
        "⑦ 结果与收获：客服端 115 个测试、中台 63 个测试（跑在真实 PostgreSQL 上）；"
        "检索、并发、缓存三块都有可复现的数字。最大的收获是：每一个「感觉变好了」都要变成一个数字。",
    ]:
        add(doc, text, space_after=5)

    # ============================================================ 3
    doc.add_heading("三、系统架构（用嘴说清楚就行，不用画图）", level=1)
    bullet(doc, "入口：Caddy 反向代理按路径分流——/api/* 给客服 Agent，/shop/* 给电商中台，"
                "页面走前端；生产用域名自动签发 HTTPS。")
    bullet(doc, "客服 Agent（Python/FastAPI）：TurnPlanner 两层决策 + YAML 流程引擎 + 槽位收集 + "
                "RAG 检索 + SSE 流式输出；对话状态持久化在 PostgreSQL，服务重启不丢上下文。")
    bullet(doc, "电商中台（Python/FastAPI + SQLAlchemy）：商品/SKU/库存、购物车、地址、订单状态机、"
                "Mock 支付、履约物流、优惠券、积分、售后工单、评价、运营管理端与经营看板。")
    bullet(doc, "数据：PostgreSQL 16 + pgvector（知识库向量检索、trigram 字面检索），两个库分开放。")
    bullet(doc, "规则集中：金额、运费、优惠券、积分、状态机全部收在 shop_rules.py，纯函数、可单测——"
                "这样「谁能改状态」只有一处定义。")

    # ============================================================ 4
    doc.add_heading("四、我最想被问的 5 个故事（有 bug、有数据、有取舍）", level=1)
    add(doc, "面试官问「讲讲你遇到最难的问题」时，按下面挑一个讲。每个故事都是：现象 → 定位 → 根因 → 修法 → 结果。",
        size=10, color=(0x55, 0x55, 0x55))

    doc.add_heading("故事 1：行锁看起来写了，但库存还是超卖（丢失更新）", level=2)
    bullet(doc, "现象：我写了压测脚本，10 个并发抢 3 件库存，结果 10 单全部成功，而库存只从 3 变成 2。")
    bullet(doc, "定位：查库存流水，10 条记录的「变更后库存」全是 2——说明每个事务都读到了旧值 3。")
    bullet(doc, "根因：下单前我先用 ORM 读了一次 SKU（进了 Session 的 identity map），之后再加 "
                "SELECT ... FOR UPDATE。SQLAlchemy 默认不会用查询结果覆盖已加载对象的属性，"
                "所以行锁住了，用的还是旧库存——锁形同虚设。")
    bullet(doc, "修法：给三处加锁查询加 execution_options(populate_existing=True)，强制用锁内读到的值覆盖；"
                "另外补了一个并发测试：3 件库存 + 10 个线程，必须恰好 3 单成功、库存归零。这个测试在修复前是红的。")
    bullet(doc, "结果：3 单成功 / 7 单返回 409 库存不足 / 最终库存 0。")
    bullet(doc, "追问「还有别的做法吗」：可以用原子条件更新 UPDATE ... SET stock = stock - ? "
                "WHERE id = ? AND stock >= ?，判断受影响行数是否为 1——把校验交给数据库一条语句完成。")

    doc.add_heading("故事 2：缓存怎么加才不出事（强一致字段不进缓存）", level=2)
    bullet(doc, "现象：商品详情页每次请求要打好几次数据库，我想加缓存，但最怕的是「页面显示有货、下单说库存不足」。")
    bullet(doc, "做法：缓存只放「静态骨架」（标题/描述/属性/品牌/规格价格），库存每次请求用一次轻量查询"
                "盖上去——库存永不进缓存。作废用版本号：catalog（运营改商品才变）和 dynamic（下单/评价/调库存会变）"
                "各一个版本号，写操作只 INCR 版本号，旧 key 自然过期，不需要枚举删除。")
    bullet(doc, "容错：Redis 连不上就当作没有缓存直接走库，连续失败熔断 30 秒，避免每个请求都卡在连接超时上；"
                "容器编排里依赖是 service_started，缓存不健康也不影响启动。")
    bullet(doc, "数据：同机 20 并发 400 次请求，吞吐 350.9 → 435.6 req/s，P50 54 → 41 ms，命中率 99.0%；"
                "而且开启缓存后「并发不超卖」的结论不变。")

    doc.add_heading("故事 3：给 RAG 做评测闭环，然后被自己的数据打脸", level=2)
    bullet(doc, "动机：改检索很容易「感觉好像准了」，说不清改前改后差多少。我建了 41 条标注集"
                "（直接问法 10 / 口语化改写 19 / 政策条款 7 / 超纲 5），指标 Recall@k、MRR、超纲拒答率，"
                "并自动产出 badcase 清单。")
    bullet(doc, "对比（真实 pgvector + pg_trgm）：纯向量 Recall@1 91.7% → 混合检索 94.4% → "
                "把语料里的口语化别名也纳入字面分 97.2% → 字面分口径换成 word_similarity 100%，MRR 1.000。")
    bullet(doc, "为什么换 word_similarity：短问题对长文档，similarity()（trigram 交集/并集）会被长文档稀释到接近 0，"
                "而 word_similarity() 看的是「问题里的词在文档里出现了多少」，更适合知识库这种短问长答。")
    bullet(doc, "被数据打脸的地方：我原以为 min_score=0.05 是个保守的兜底。评测显示正例 top1 分数 0.21~0.80、"
                "超纲问题 0.19~0.35，两段分布是重叠的——门槛抬到 0.31 能把超纲拒答率从 20% 提到 80%，"
                "但 Recall@5 会掉到 83%。所以结论是：超纲要靠意图识别 + 提示词兜底，光调分数门槛两头不讨好。")

    doc.add_heading("故事 4：接口前缀和页面路由撞车（一个真实线上事故）", level=2)
    bullet(doc, "现象：商城列表页正常，点商品卡片却显示 {\"detail\":\"Not Found\"}。")
    bullet(doc, "根因：反代规则把 /shop/* 全部转给中台接口，而商品详情页也是 /shop/[productId]，"
                "于是页面请求被当成接口发给了中台；列表页 /shop（没有斜杠，不匹配 /shop/*）却是好的，"
                "所以现象看起来像「偶发」。")
    bullet(doc, "修法：页面路由整体挪到 /mall/*，接口命名空间留在 /shop/*（中台 63 个测试、"
                "客服端调用和部署自检都依赖它）；并补了一个守卫测试，断言「任何反代前缀都不能与前端页面同名」"
                "「页面链接不能指向接口命名空间」——把旧目录恢复回去，这个测试立刻变红。")

    doc.add_heading("故事 5：部署要能自己发现失败（可观测性）", level=2)
    bullet(doc, "现象：Caddy 的 reload 返回 0，但新加的反代规则其实没生效，页面一访问就是 500/404。")
    bullet(doc, "修法：不再相信 reload 的退出码，改成重建 Caddy 容器（bind mount 的配置文件改动 compose "
                "不会自动重建），然后从宿主机真实探一次 /shop/categories；不通过就重启 Caddy 再探，"
                "仍然不通过才让流水线失败，并把响应体、容器里配置的规则数一起打出来，"
                "让「文件是旧的」和「配置是旧的」在日志里就能区分。")
    bullet(doc, "同类自检还有：部署后探测 embedding 后端是否可用、跑一遍检索评测——"
                "评测能跑完就说明「建表 → 向量 → SQL 检索」整条链路是通的。")

    # ============================================================ 5
    doc.add_heading("五、随口要能报出来的数字", level=1)
    table(doc, [
        ["项目", "数字"],
        ["代码规模", "客服 Agent + 电商中台 + 前端 + 部署脚本，4 个模块；中台 12 张业务表"],
        ["测试", "客服端 115 个用例；中台 63 个用例（集成测试跑在真实 PostgreSQL 上）"],
        ["检索评测", "41 条标注集；Recall@1 91.7% → 100%，MRR 0.949 → 1.000"],
        ["并发正确性", "10 并发抢 3 件 → 3 单成功、7 单 409、库存 0，无超卖"],
        ["缓存", "命中率 99.0%；吞吐 350.9 → 435.6 req/s；P50 54 → 41 ms"],
        ["用户规模（演示）", "3 个账号、6 款商品 / 10 个 SKU；单个用户 5 笔不同状态订单"],
        ["CI/CD", "7 个 job；只重建改动过的镜像（未改动组件复制 manifest 不传层数据）"],
        ["服务器", "阿里云 2C2G，5 个容器（PostgreSQL + Caddy + 三个应用），Docker Compose 编排"],
    ])

    # ============================================================ 6
    doc.add_heading("六、高频追问与答法", level=1)
    table(doc, [
        ["追问", "怎么答"],
        ["你在这个项目里最大的贡献是什么？",
         "对话驱动的交易闭环：让客服不只能答，还能真的把订单、售后办完。具体是三处：流程声明化"
         "（新增能力不改引擎）、检索评测闭环（改动有数据）、交易侧强一致（行锁 + 缓存边界）。"],
        ["为什么不用 Java / Spring？",
         "技术栈是团队和课设定的 Python；但项目里真正难的部分和语言无关——事务与锁、状态机、"
         "幂等、缓存一致性、CI/CD。这些我在这个项目里都实际做过并有数据。"],
        ["QPS 多少？能扛多少？",
         "本机压测 20 并发下商品读路径 350~435 req/s、P50 41~54ms。这是 2C2G 的演示环境、"
         "样本也小，我不拿它当容量结论；能讲的是分层结果：缓存命中率 99%，所以真正打到库的请求很少。"],
        ["怎么保证不超卖？",
         "下单时 SELECT ... FOR UPDATE 锁住涉及的 SKU 行，在锁内校验并扣减，同一事务提交；"
         "并且加锁查询必须带 populate_existing，否则会用到 identity map 里的旧值（我踩过，"
         "10 并发全部下单成功但库存只减 1）。"],
        ["缓存和数据库不一致怎么办？",
         "分两类：强一致的（库存、下单读的价格）根本不进缓存；可以短暂不一致的（商品列表的库存状态、"
         "销量、评分）用版本号作废 + 30 秒 TTL，接受秒级延迟。写操作只 INCR 版本号，不做删 key。"],
        ["RAG 怎么保证不胡说？",
         "三层：意图路由先判断该不该检索；检索有 min_score 门槛；提示词要求没有依据就说不知道。"
         "评测显示正例与超纲问题的分数分布重叠，所以我不假装门槛能全挡住，而是靠这三层一起兜。"],
        ["向量检索为什么还要加字面分？",
         "口语化改写里经常出现只在别名里有的词（比如「钱什么时候退回来」），字面分能补上向量漏掉的召回。"
         "实测把它加进来 Recall@1 从 91.7% 提到 97.2%，再换 word_similarity 到 100%。"],
        ["数据库迁移怎么做的？",
         "没用 Alembic（单库、单人维护、部署即启动，收益不抵成本），改用幂等的 "
         "ALTER TABLE ADD COLUMN IF NOT EXISTS + 幂等补种回填，中台 19 处、知识库 1 处。"],
        ["CI/CD 具体做什么？",
         "判断改动范围 → 4 个校验（两端测试、部署脚本与 workflow 断言、前端类型检查与构建）→ "
         "只重建改动过的镜像推 GHCR → SSH 部署 → 部署后自检（真实接口探测 + 检索评测）。"
         "未改动的组件用 docker buildx imagetools 复制 manifest，服务器拉取每层都命中缓存。"],
        ["如果重做，你会改什么？",
         "三件：① 服务间调用补上幂等键，现在的重复支付是靠状态机挡的；"
         "② 加可观测性（请求 ID 贯穿 + 分段耗时），现在的排障主要靠日志；"
         "③ 运营端加鉴权，现在是演示取舍、接口公开的。"],
    ])

    # ============================================================ 7
    doc.add_heading("七、我主动说的不足（显得可信）", level=1)
    bullet(doc, "运营管理端接口目前没有鉴权（/shop/admin/*），演示可以接受，生产必须加访问控制。")
    bullet(doc, "用户与商城账号的映射靠用户名兜底，真实系统应该做成账号绑定表。")
    bullet(doc, "超纲问题目前没有专门模型，靠意图路由 + 提示词缓解；评测已经量化了这个缺口。")
    bullet(doc, "所有性能数字来自本机小样本（41 条评测集、400 次压测请求），只代表趋势，不是容量结论。")
    bullet(doc, "还没做的两件：慢查询与索引优化（EXPLAIN 前后对比）、消息队列做订单超时关单"
                "（现在是读取时惰性判断）。")

    # ============================================================ 8
    doc.add_heading("八、面试前 10 分钟速览清单", level=1)
    bullet(doc, "打开线上站点看一眼：/mall（商城）、/chat（对话里下单）、/admin（运营看板）——确保能演示。")
    bullet(doc, "背下三个数字：Recall@1 91.7% → 100%；10 并发抢 3 件 → 3/7/0；缓存命中率 99.0%。")
    bullet(doc, "准备一个被追问的坑：丢失更新（identity map + FOR UPDATE + populate_existing）。")
    bullet(doc, "准备一个取舍：为什么库存不进缓存、为什么不用 Alembic、为什么 embedding 走 API。")
    bullet(doc, "准备好「如果重做会改什么」的三条（幂等键、可观测性、鉴权）。")
    bullet(doc, "如果被问到不会的，就说「这块我没做过，我的理解是……」，不要硬编。")

    doc.save(OUT)
    print(f"已生成：{OUT}（{len(doc.paragraphs)} 段，{len(doc.tables)} 个表格）")


if __name__ == "__main__":
    build()
