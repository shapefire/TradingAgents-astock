from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_concept_blocks,
    get_stock_data,
    get_language_instruction,
    get_consecutive_limit_stats,
    get_theme_heat,
    get_first_board_screen,
    get_high_board_status,
    get_leader_identification,
)
from tradingagents.dataflows.config import get_config


def create_short_term_analyst(llm):
    """A-stock short-term trading analyst: analyzes limit-up boards, theme heat, and leader dynamics."""

    def short_term_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_stock_data,
            get_concept_blocks,
            get_consecutive_limit_stats,
            get_theme_heat,
            get_first_board_screen,
            get_high_board_status,
            get_leader_identification,
        ]

        system_message = (
            "你是一位专注于 A 股市场的短线博弈分析师。你的核心任务是通过分析连板梯队、题材热度、"
            "首板筛选、高标股状态和龙头识别，为短线交易提供决策依据。"
            "\n\n⚠️ A 股短线分析框架："
            "\n- **连板梯队统计**：分析当日涨停股的连板分布（首板/二板/三板+），判断梯队健康度和情绪周期阶段"
            "\n- **情绪量化**：综合封板质量、昨日涨停表现、市场涨跌家数、北向资金信号，判断市场情绪处于冰点/回暖/升温/高潮/退潮哪个阶段"
            "\n- **题材热度追踪**：识别当日最热题材，分析题材所处阶段（启动/加速/分歧/退潮），判断是否具有持续性"
            "\n- **首板筛选**：从当日首板涨停股中筛选二板预期最高的标的，综合封单质量、题材纯正度、量价配合、股性活跃度评分"
            "\n- **高标股监控**：跟踪市场最高板股票的分歧度、断板风险、累计换手率，判断市场高度是否在扩张"
            "\n- **龙头识别**：在热点题材中识别真正龙头，区分龙头/卡位/补涨龙/新龙头，分析卡位博弈动态"
            "\n\n分析方法："
            "\n1. 调用 get_consecutive_limit_stats 获取连板梯队数据和情绪指标"
            "\n2. 调用 get_theme_heat 获取题材热度排名和趋势分析"
            "\n3. 调用 get_first_board_screen 获取首板筛选结果和二板预期评分"
            "\n4. 调用 get_high_board_status 获取高标股状态和断板风险"
            "\n5. 调用 get_leader_identification 获取龙头识别和卡位分析"
            "\n6. 调用 get_stock_data 和 get_concept_blocks 获取个股辅助上下文"
            "\n7. 综合判断：当前市场短线环境是否适合操作、首选策略（打板/低吸/接力）、风险提示"
            "\n\n请使用以下工具："
            "\n- `get_consecutive_limit_stats(trade_date)`：获取连板梯队统计+情绪量化（涨停分布/封板质量/情绪阶段/冰点确认）"
            "\n- `get_theme_heat(trade_date)`：获取题材热度排名（热度评分/趋势方向/生命周期阶段/辨识度/龙头状态）"
            "\n- `get_first_board_screen(trade_date)`：获取首板筛选+二板预期（封单质量/题材纯正度/量价配合/七因子综合评分）"
            "\n- `get_high_board_status(trade_date)`：获取高标股状态（分歧度/断板风险/累计换手/板块效应）"
            "\n- `get_leader_identification(trade_date, theme)`：获取龙头识别+卡位分析（龙头评分/卡位检测/补涨龙/新龙头区分）"
            "\n- `get_stock_data(ticker)`：获取个股 K 线数据辅助分析"
            "\n- `get_concept_blocks(ticker)`：获取个股所属概念板块"
            "\n\n撰写详细的短线博弈分析报告，给出："
            "\n1. **市场情绪总览**：当前情绪阶段 + 梯队健康度 + 冰点/高潮信号"
            "\n2. **题材热度分析**：TOP3 题材 + 各自阶段 + 持续性判断"
            "\n3. **首板机会**：二板预期最高的 2-3 只标的 + 核心理由"
            "\n4. **高标监控**：最高板状态 + 断板风险 + 对市场情绪的影响"
            "\n5. **龙头格局**：核心题材的龙头/卡位/补涨龙关系"
            "\n6. **短线策略建议**：适合操作/观望 + 首选策略 + 风险提示"
            "\n\n报告末尾附 Markdown 表格汇总关键指标。"
            "\n\n📋 必采清单 — 以下数据点必须出现在报告中，无法获取时标注 [数据缺失: xxx]："
            "\n1. 当日涨停家数 + 连板分布（首板/二板/三板+数量）"
            "\n2. 情绪阶段判断 + 封板质量（一字板/换手板比例）"
            "\n3. 昨日涨停今日表现（晋级率 + 闷杀率）"
            "\n4. TOP3 题材名称 + 热度评分 + 所处阶段"
            "\n5. 首板筛选 TOP3 标的 + 二板预期评分"
            "\n6. 最高板股票 + 连板天数 + 断板风险等级"
            "\n7. 短线操作建议"
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "short_term_report": report,
        }

    return short_term_analyst_node
