"""Deterministic, project-approved answers for core CGDA terminology.

These rules sit outside the LLM prompt so demo mode and model-backed profiles use
the same wording.  Keep this module deliberately small: it only owns facts that
the project has explicitly approved; everything else remains unanswered.
"""

from __future__ import annotations

import re


_SM_REPLY = (
    "SM 是 Soil Moisture，即土壤水分，通常表示土壤体积含水量，单位为 "
    "m³/m³。本项目通过微波亮温和辐射传输模型反演 SM，它属于反演结果，"
    "不是传感器直接测得的数值。SM 较低不等于一定发生干旱；判断干旱还需要"
    "历史同期基准等信息。"
)

_VOD_REPLY = (
    "VOD 是 Vegetation Optical Depth，即植被光学厚度，在模型中通常用 τ "
    "表示，是无量纲参数。它描述微波信号通过植被冠层时受到的总体衰减；VOD "
    "越大，通常表示植被对微波信号的衰减越强。VOD 是模型反演结果，在没有"
    "项目依据时，不能直接等同于植被含水量、生物量或植被长势。"
)

_OMEGA_REPLY = (
    "ω（欧米伽）是植被冠层辐射传输模型中的散射参数，用于描述冠层消光作用中"
    "由散射造成的比例，通常取值在 0 到 1 之间。它不是直接观测值，而是结合"
    "多时相微波亮温等数据反演得到的模型参数，也不能直接理解为真实的冠层结构"
    "数值。当前项目资料还没有明确 ω、ωeff、“等效散射参数”和“单次散射反照率”"
    "之间的准确关系，因此不能自行认定它们完全等价。"
)

_ALGORITHM_REPLY = (
    "本项目研究的是基于 τ-ω 微波辐射传输模型的土壤水分与植被参数反演方法。"
    "算法利用垂直极化和水平极化亮温等输入，通过正向模型和数值优化，反演土壤"
    "水分 SM、植被光学厚度 VOD，以及部分流程中的 ω 参数。项目包含静态参数"
    "预处理、多年同期平均 ω 日常反演，以及动态 ω 分块反演等不同工作流程。"
)

_AVERAGE_DYNAMIC_REPLY = (
    "Average 和 Dynamic 的主要区别是 ω 的处理方式，不是 SM、VOD 的时间"
    "分辨率不同。Average 使用多年同期平均的 ω，并在每日反演中将其固定，"
    "计算量相对较小；Dynamic 按时间块联合估计每日变化的 ω，同时反演 SM 和 "
    "VOD，计算过程更复杂。两种流程都可以生成每日 SM 和 VOD 产品。"
)

_UNVERIFIED_METRICS_REPLY = (
    "当前资料中没有登记可核实的验证指标，因此无法说明算法精度，也不能编造"
    "准确率或误差数值。"
)

_UNVERIFIED_PROJECT_REPLY = (
    "当前项目知识库中没有足够信息支持这个结论，因此我无法可靠回答。请补充"
    "项目说明或由相关负责人确认。"
)

_DEFINITION_HINT = re.compile(
    r"什么是|是什[么麼]|什么意思|含义|概念|介绍(?:一下)?|解释(?:一下)?|指什么",
    re.I,
)
#: 项目知识库不覆盖的「机器学习 / 算法超参」等无关技术术语。用户拿这类词来问
#: （如「Adam 学习率是多少」），若没有拦截，会一路透传到模型，模型再拿上一轮的
#: 图层统计上下文把问题串成「继续统计土壤水分」（2026-11-10 老师实测 P0：连新会话
#: 都会复现，根因正是这里缺兜底）。
_ML_HYPERPARAM_HINT = re.compile(
    r"学习率|learning\s*rate|batch\s*size|epoch|adam|adamw|sgd|dropout|"
    r"正则化|regularization|损失函数|loss\s*function|优化器|optimizer|"
    r"梯度|gradient|权重|weight\s*decay|动量|momentum|lr\b",
    re.I,
)
#: 疑问标记：问「多少 / 是什么 / 默认值」等，说明在求一个值或定义。
_QUESTION_VALUE_HINT = re.compile(
    r"是多少|是什么|多少|多大|几多|默认值|设为|取值|数值|默认|怎么设置|"
    r"how\s*much|what\s*is",
    re.I,
)
#: 规划/设计意图：用户要的是「设计分析流程/工作流、逐项给步骤与参数、先不运行」，
#: 不是求某个概念的定义、也不是取数。这类请求必须放行给模型走规划路径，绝不能
#: 被下面的 `_DEFINITION_HINT`（命中「解释」）当成「什么是土壤水分」拦截。
#: 2026-11-10 老师实测 P1：用例 11/16「设计一个广州土壤水分月均值分析工作流，
#: 逐项解释所有步骤与参数，先不要运行」被误答成「SM 是 Soil Moisture…」的定义，
#: 新会话复测则答成「没取到数值」——根因就是这句里的「解释」触发了定义分支。
_PLANNING_HINT = re.compile(
    r"设计.{0,12}(?:工作流|流程|方案|步骤|分析)|"
    r"(?:工作流|分析流程|分析方案|处理流程).{0,6}(?:设计|规划|怎么|如何)|"
    r"(?:规划|设计).{0,6}(?:分析|处理|计算).{0,6}(?:流程|步骤|方案)|"
    r"(?:只给|仅给|只要).{0,6}(?:步骤|流程|方案)|"
    r"先不要运行|先别运行|不要运行|不运行|只出步骤|别运行|先不执行",
    re.I,
)
#: 项目内图层/变量/区域线索：出现这些词说明对象可能仍是系统里的取数对象，不该兜底拒答。
_KNOWLEDGE_SCOPE_HINT = re.compile(
    r"土壤水|土壤湿|含水量|墒情|植被光学厚度|光学厚度|等效散射|散射|ω|omega|"
    r"(?<![a-z])sm(?![a-z])|(?<![a-z])vod(?![a-z])|亮温|微波|反演|"
    r"图层|产品|数据|降水|温度|湿度",
    re.I,
)
#: 兜底拒答文案：项目资料里没有这个术语的信息，明确承认无法确定，不编造、不串题。
_ML_HYPERPARAM_REPLY = (
    "当前项目资料里没有登记「{term}」这个参数，我无法确定它的取值或含义。"
    "这个问题超出了本系统能回答的范围，我没有拿别的数据来顶替。"
)

_METRIC_HINT = re.compile(
    r"精度|准确率|误差|不确定度|准不准|rmse|mae|r\s*[²2]|决定系数", re.I
)
_UNVERIFIED_PROJECT_HINT = re.compile(
    r"原创|创新点|论文|文献|期刊|专利|作者|发明人|获奖|领先|优于|最好|首创",
    re.I,
)
_PROJECT_CONTEXT = re.compile(
    r"本项目|这个项目|项目|我们|你们|研究|算法|反演|图层|产品|数据|"
    r"cgda|τ-ω|tau\s*-?\s*omega",
    re.I,
)


def project_knowledge_reply(message: str) -> str | None:
    """Return an approved answer for a narrow project-knowledge question.

    ``None`` means the request is not a knowledge question owned by this guard.
    Data queries such as “VOD 是多少” intentionally pass through to normal tools.
    """

    text = str(message or "").strip()
    if not text:
        return None
    folded = text.casefold()

    # 规划/设计意图最高优先：用户要「设计分析工作流、只给步骤不运行」时，
    # 这里必须返回 None 放行给模型走规划路径，绝不能落到下面的定义分支
    # 被当成「什么是土壤水分」。（2026-11-10 P1：用例 11/16 误答成 SM 定义 /
    # 没取到数值，根因就是「逐项解释步骤」里的「解释」触发了 _DEFINITION_HINT。）
    if _PLANNING_HINT.search(text):
        return None

    # 兜底拒答（最高优先）：用户问「项目知识库没登记的机器学习/算法超参」。
    # 「Adam 学习率是多少」这类问题若无此拦截，会透传到模型并被上一轮统计上下文串题。
    # 只在「是疑问句 + 命中无关术语 + 不含系统图层/变量/区域线索」时才拒答，
    # 避免误伤「SM 的均值」「土壤水分是多少」这类正常取数。
    _ml_term = _ML_HYPERPARAM_HINT.search(text)
    if (
        _ml_term is not None
        and _QUESTION_VALUE_HINT.search(text)
        and not _KNOWLEDGE_SCOPE_HINT.search(text)
    ):
        return _ML_HYPERPARAM_REPLY.format(term=_ml_term.group(0))

    if _METRIC_HINT.search(text) and _PROJECT_CONTEXT.search(text):
        return _UNVERIFIED_METRICS_REPLY
    if _UNVERIFIED_PROJECT_HINT.search(text) and _PROJECT_CONTEXT.search(text):
        return _UNVERIFIED_PROJECT_REPLY

    mentions_omega = "ω" in text or "欧米伽" in text or "omega" in folded
    mentions_omega_eff = "ωeff" in folded or "omegaeff" in folded
    if (
        mentions_omega
        and mentions_omega_eff
        and re.search(r"一样|相同|等价|区别|关系", text)
    ):
        return _UNVERIFIED_PROJECT_REPLY

    average_dynamic = (
        ("average" in folded and "dynamic" in folded)
        or ("平均" in text and "动态" in text)
    ) and re.search(r"区别|差别|不同|差异|怎么选|哪个好|关系", text)
    if average_dynamic:
        return _AVERAGE_DYNAMIC_REPLY

    algorithm_question = bool(
        re.search(
            r"(?:本项目|这个项目|我们|你们).{0,8}(?:研究|使用|采用|做).{0,8}算法"
            r"|(?:本项目|这个项目|我们|你们).{0,8}算法.{0,8}(?:什么|介绍|解释)"
            r"|(?:研究的|项目的|我们的|你们的)算法",
            text,
            re.I,
        )
    )
    if algorithm_question:
        return _ALGORITHM_REPLY

    if not _DEFINITION_HINT.search(text):
        return None
    if re.search(r"(?<![a-z])vod(?![a-z])", folded):
        return _VOD_REPLY
    if mentions_omega:
        return _OMEGA_REPLY
    if re.search(r"(?<![a-z])sm(?![a-z])", folded) or "土壤水分" in text:
        return _SM_REPLY
    return None
