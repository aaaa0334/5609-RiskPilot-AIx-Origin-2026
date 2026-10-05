"""
RiskPilot 多智能体编排模块
==========================
负责调用三个 AI Agent（技术面、基本面、公告新闻）进行分析，
并汇总多空证据。支持两种模式：
1. real: 通过 OpenAI Responses API 调用真实 LLM
2. preset_demo: 使用明确标注的预设内容，仅作离线故障备份
"""

import os
import json
import time
from datetime import datetime, timezone

# 演示模式下的预设分析内容（按股票代码索引）
# 这些内容是精心编写的演示数据，用于无 API key 时的离线演示
MOCK_ANALYSES = {
    "600519": {
        "technical": """### 一、可核验事实
- 当前价格：1,685.00 元，日期：2026-08-29
- 近 20 日涨跌幅：+3.2%
- 近 60 日涨跌幅：+8.5%
- MA5: 1,680 / MA10: 1,672 / MA20: 1,655 / MA60: 1,620（多头排列）
- RSI(14): 58（中性偏强）
- MACD: DIF 12.5, DEA 8.3, 柱 +4.2（零上，红柱放大）
- ATR(14): 28.5 元，占股价 1.69%
- 近 20 日日均成交量：2.8 万手，较前 20 日放大 15%

### 二、AI 推断
- 趋势判断：中期上升趋势，短期在 1,650-1,700 区间震荡整理
- 关键支撑位：1,620 元（依据：MA60 + 前期平台低点）
- 关键压力位：1,750 元（依据：前期高点）
- 波动率评价：低（ATR 占比 1.69%，低于 A 股平均）
- 量价关系：温和放量上涨，量价配合良好
- 技术面风险点：① RSI 接近 60，短期有超买迹象；② 1,750 压力位可能引发回调

### 三、提供给风险引擎的参数
- 建议关键支撑位：1,620 元
- 建议 ATR 风险倍数：2.5（低波动股票可适当放大）

### 四、不确定性
- 数据无明显缺失或异常
- 技术指标无明显冲突""",

        "fundamental": """### 一、可核验事实
- 最新报告期：2026-Q2
- 营业收入：816 亿元，同比 +15.2%
- 归母净利润：395 亿元，同比 +16.8%
- 扣非净利润：390 亿元，同比 +17.1%
- 经营现金流净额：320 亿元
- 毛利率：91.5%，净利率：48.4%，ROE：16.2%
- 资产负债率：18.5%
- PE(TTM): 28.5 倍，PB: 9.2 倍，股息率：1.8%
- 行业分类：白酒，行业指数近 20 日涨跌幅：+2.1%

### 二、AI 推断
- 盈利质量：优秀，利润有充足现金流支撑，非经常性损益占比极低
- 成长性：稳健，收入和利润双位数增长，符合行业龙头特征
- 财务健康度：极优，低负债、高现金流、高 ROE
- 估值水平：处于历史中位偏下，相对行业有溢价但合理
- 行业景气度：平稳复苏，高端白酒需求韧性较强
- 政策/宏观影响：消费刺激政策可能利好，关注消费税改革预期
- 基本面风险点：① 宏观消费疲软可能影响高端需求；② 库存周期变化

### 三、基本面失效条件
- 单季度营收同比增速降至 5% 以下
- 毛利率跌破 88%
- 出现重大食品安全或品牌危机事件

### 四、不确定性
- 2026 年中报数据为预告口径，最终以正式财报为准""",

        "news": """### 一、可核验事实
1. [2026-08-28] 定期报告：2026 年半年度报告（来源：上交所公告）
2. [2026-08-20] 股东大会：2026 年第一次临时股东大会决议（来源：上交所公告）
3. [2026-08-15] 机构调研：接待 12 家机构调研，讨论渠道库存和价格体系（来源：公司公告）
4. [2026-08-10] 行业新闻：白酒行业半年报整体回暖，高端酒表现优于次高端（来源：证券时报）
5. [2026-07-28] 分红实施：2025 年度分红派息实施公告（来源：上交所公告）

### 二、AI 推断
- 重大事项影响：中报业绩符合预期，渠道调研显示库存健康
- 市场情绪倾向：偏正面，机构关注度高
- 短期叙事主题：消费复苏 + 高端白酒韧性
- 关注度变化：中报发布后关注度上升
- 公告/新闻风险点：无重大负面公告

### 三、事件驱动的失效条件
- 公司发布业绩下修预告
- 核心管理层发生重大变动

### 四、不确定性
- 机构调研内容仅为摘要，具体交流细节未披露""",
    },

    "601318": {
        "technical": """### 一、可核验事实
- 当前价格：45.20 元，日期：2026-08-29
- 近 20 日涨跌幅：-1.5%
- 近 60 日涨跌幅：+4.2%
- MA5: 45.0 / MA10: 45.3 / MA20: 45.8 / MA60: 44.5（均线纠缠）
- RSI(14): 45（中性偏弱）
- MACD: DIF -0.2, DEA 0.1, 柱 -0.3（零下，绿柱缩小）
- ATR(14): 1.15 元，占股价 2.54%
- 近 20 日日均成交量：45 万手，较前 20 日缩小 10%

### 二、AI 推断
- 趋势判断：震荡格局，方向不明
- 关键支撑位：43.0 元（依据：近 60 日最低点 + MA60 附近）
- 关键压力位：47.5 元（依据：前期反弹高点）
- 波动率评价：中等（ATR 占比 2.54%）
- 量价关系：缩量震荡，多空分歧不大
- 技术面风险点：① MA20 压制明显；② 若跌破 43 可能打开下行空间

### 三、提供给风险引擎的参数
- 建议关键支撑位：43.0 元
- 建议 ATR 风险倍数：1.5

### 四、不确定性
- 均线纠缠，趋势方向不明确""",

        "fundamental": """### 一、可核验事实
- 最新报告期：2026-Q2
- 营业收入：4,520 亿元，同比 +8.3%
- 归母净利润：820 亿元，同比 +12.5%
- 扣非净利润：805 亿元，同比 +11.8%
- 经营现金流净额：1,200 亿元
- 毛利率：N/A（金融行业不适用），净利率：18.1%，ROE：11.5%
- 资产负债率：89.2%（金融行业特征）
- PE(TTM): 8.2 倍，PB: 0.95 倍，股息率：5.2%
- 行业分类：保险，行业指数近 20 日涨跌幅：-0.8%

### 二、AI 推断
- 盈利质量：良好，新业务价值率提升
- 成长性：稳健复苏，寿险改革成效逐步显现
- 财务健康度：金融行业高负债为正常特征，偿付能力充足
- 估值水平：极低，PB 破净，PE 处于历史低位
- 行业景气度：缓慢复苏，利率下行对投资端有压力
- 政策/宏观影响：① 长端利率下行影响投资收益；② 政策支持保险业发展
- 基本面风险点：① 利率持续下行压缩利差；② 地产敞口风险

### 三、基本面失效条件
- 新业务价值同比转负
- 核心偿付能力充足率跌破 100%
- 重大投资损失公告

### 四、不确定性
- 保险公司利润受投资收益率影响大，波动性较高""",

        "news": """### 一、可核验事实
1. [2026-08-27] 定期报告：2026 年半年度报告（来源：上交所公告）
2. [2026-08-22] 经营数据：前 7 月保费收入公告（来源：上交所公告）
3. [2026-08-05] 行业新闻：保险业新会计准则实施首年，利润口径变化（来源：中国证券报）
4. [2026-07-30] 股东大会：2025 年度股东大会决议（来源：上交所公告）

### 二、AI 推断
- 重大事项影响：中报新业务价值增长超预期
- 市场情绪倾向：中性偏正面，低估值吸引价值投资者
- 短期叙事主题：保险复苏 + 高股息防御
- 关注度变化：中报后关注度一般
- 公告/新闻风险点：无重大负面

### 三、事件驱动的失效条件
- 保费收入连续两月同比负增长
- 监管出台限制险资投资的政策

### 四、不确定性
- 长端利率走势对保险股影响重大，难以预测""",
    },

    "600036": {
        "technical": """### 一、可核验事实
- 当前价格：38.50 元，日期：2026-08-29
- 近 20 日涨跌幅：+2.1%
- 近 60 日涨跌幅：+6.8%
- MA5: 38.2 / MA10: 37.8 / MA20: 37.5 / MA60: 36.8（多头排列）
- RSI(14): 55（中性）
- MACD: DIF 0.3, DEA 0.1, 柱 +0.2（零上，红柱）
- ATR(14): 0.65 元，占股价 1.69%
- 近 20 日日均成交量：30 万手，较前 20 日放大 8%

### 二、AI 推断
- 趋势判断：缓慢上升趋势
- 关键支撑位：36.5 元（依据：MA60 + 前期平台）
- 关键压力位：40.0 元（整数关口 + 前期高点）
- 波动率评价：低（银行股特征）
- 量价关系：温和放量，走势稳健
- 技术面风险点：① 40 元整数关口压力；② 银行板块整体联动性强

### 三、提供给风险引擎的参数
- 建议关键支撑位：36.5 元
- 建议 ATR 风险倍数：2.5

### 四、不确定性
- 银行股受宏观政策影响大，技术面信号可能被政策事件打破""",

        "fundamental": """### 一、可核验事实
- 最新报告期：2026-Q2
- 营业收入：1,750 亿元，同比 +2.1%
- 归母净利润：780 亿元，同比 +5.8%
- 扣非净利润：775 亿元，同比 +5.5%
- 经营现金流净额：-200 亿元（季节性波动）
- 毛利率：N/A，净利率：44.6%，ROE：15.8%
- 资产负债率：91.2%（银行业特征）
- PE(TTM): 6.5 倍，PB: 1.05 倍，股息率：5.8%
- 行业分类：银行，行业指数近 20 日涨跌幅：+1.5%

### 二、AI 推断
- 盈利质量：稳健，息差企稳，资产质量良好
- 成长性：低速增长，符合银行业成熟期特征
- 财务健康度：资本充足率高，不良率低
- 估值水平：低估值高股息，防御属性强
- 行业景气度：平稳，息差压力边际缓解
- 政策/宏观影响：① LPR 下调影响息差；② 降准释放流动性
- 基本面风险点：① 息差持续收窄；② 房地产相关资产质量

### 三、基本面失效条件
- 净息差跌破 1.8%
- 不良贷款率上升超过 0.3 个百分点
- 资本充足率显著下降

### 四、不确定性
- 宏观经济走势对银行资产质量影响大""",

        "news": """### 一、可核验事实
1. [2026-08-26] 定期报告：2026 年半年度报告（来源：上交所公告）
2. [2026-08-20] 行业新闻：商业银行净息差企稳迹象显现（来源：金融时报）
3. [2026-08-15] 分红实施：2025 年度分红派息（来源：上交所公告）

### 二、AI 推断
- 重大事项影响：中报业绩稳健，资产质量好于预期
- 市场情绪倾向：偏正面，高股息吸引资金
- 短期叙事主题：银行防御 + 高股息
- 关注度变化：中规中矩
- 公告/新闻风险点：无

### 三、事件驱动的失效条件
- 央行超预期降息
- 房地产风险集中暴露

### 四、不确定性
- 无""",
    },

    "300750": {
        "technical": """### 一、可核验事实
- 当前价格：195.00 元，日期：2026-08-29
- 近 20 日涨跌幅：-5.2%
- 近 60 日涨跌幅：-12.8%
- MA5: 198 / MA10: 202 / MA20: 208 / MA60: 220（空头排列）
- RSI(14): 32（接近超卖）
- MACD: DIF -5.2, DEA -3.8, 柱 -1.4（零下，绿柱）
- ATR(14): 8.5 元，占股价 4.36%
- 近 20 日日均成交量：120 万手，较前 20 日放大 25%

### 二、AI 推断
- 趋势判断：下降趋势，短期有超卖反弹可能
- 关键支撑位：180 元（依据：近 60 日最低点）
- 关键压力位：210 元（依据：MA20 附近）
- 波动率评价：高（ATR 占比 4.36%，创业板特征）
- 量价关系：放量下跌，空头力量较强
- 技术面风险点：① 下降趋势明确；② 创业板涨跌幅 20%，波动大

### 三、提供给风险引擎的参数
- 建议关键支撑位：180 元
- 建议 ATR 风险倍数：1.0（高波动股票缩小倍数）

### 四、不确定性
- RSI 接近超卖，可能有技术性反弹，但趋势未改""",

        "fundamental": """### 一、可核验事实
- 最新报告期：2026-Q2
- 营业收入：1,850 亿元，同比 +22%
- 归母净利润：210 亿元，同比 +18%
- 扣非净利润：200 亿元，同比 +15%
- 经营现金流净额：350 亿元
- 毛利率：22.5%，净利率：11.4%，ROE：12.8%
- 资产负债率：65%
- PE(TTM): 22 倍，PB: 4.5 倍，股息率：0.5%
- 行业分类：新能源电池，行业指数近 20 日涨跌幅：-6.5%

### 二、AI 推断
- 盈利质量：良好，但毛利率有下行压力
- 成长性：高增长，但增速较前几年放缓
- 财务健康度：较好，但资本开支大
- 估值水平：中性，成长性溢价
- 行业景气度：下行，产能过剩担忧，价格战持续
- 政策/宏观影响：① 新能源汽车补贴退坡；② 海外贸易壁垒
- 基本面风险点：① 行业产能过剩；② 原材料价格波动；③ 海外市场政策风险

### 三、基本面失效条件
- 毛利率跌破 20%
- 市占率被竞争对手显著超越
- 海外重大项目受阻

### 四、不确定性
- 行业竞争格局变化快，技术路线存在不确定性""",

        "news": """### 一、可核验事实
1. [2026-08-28] 定期报告：2026 年半年度报告（来源：深交所公告）
2. [2026-08-25] 行业新闻：动力电池价格战持续，碳酸锂价格新低（来源：财联社）
3. [2026-08-20] 公司公告：海外工厂建设进展更新（来源：深交所公告）
4. [2026-08-12] 机构调研：接待机构调研，讨论产能利用率（来源：公司公告）

### 二、AI 推断
- 重大事项影响：中报增长但低于市场预期，毛利率承压
- 市场情绪倾向：偏负面，行业产能过剩担忧
- 短期叙事主题：新能源产能出清 + 价格战
- 关注度变化：高，行业龙头受关注
- 公告/新闻风险点：行业负面新闻较多

### 三、事件驱动的失效条件
- 行业出现大规模产能退出或整合
- 公司海外业务遭遇重大政策限制

### 四、不确定性
- 碳酸锂价格走势难以预测""",
    },

    "002594": {
        "technical": """### 一、可核验事实
- 当前价格：265.00 元，日期：2026-08-29
- 近 20 日涨跌幅：+5.5%
- 近 60 日涨跌幅：+12.0%
- MA5: 262 / MA10: 258 / MA20: 252 / MA60: 240（多头排列）
- RSI(14): 62（偏强）
- MACD: DIF 4.5, DEA 2.8, 柱 +1.7（零上，红柱放大）
- ATR(14): 7.2 元，占股价 2.72%
- 近 20 日日均成交量：85 万手，较前 20 日放大 20%

### 二、AI 推断
- 趋势判断：上升趋势，近期加速
- 关键支撑位：245 元（依据：MA20 + 前期突破平台）
- 关键压力位：285 元（依据：前期高点）
- 波动率评价：中高
- 量价关系：放量上涨，趋势强劲
- 技术面风险点：① RSI 偏高，短期有回调需求；② 加速上涨后可能震荡

### 三、提供给风险引擎的参数
- 建议关键支撑位：245 元
- 建议 ATR 风险倍数：1.5

### 四、不确定性
- 短期涨幅较大，追高风险增加""",

        "fundamental": """### 一、可核验事实
- 最新报告期：2026-Q2
- 营业收入：3,200 亿元，同比 +28%
- 归母净利润：165 亿元，同比 +35%
- 扣非净利润：155 亿元，同比 +32%
- 经营现金流净额：420 亿元
- 毛利率：20.8%，净利率：5.2%，ROE：14.5%
- 资产负债率：72%
- PE(TTM): 25 倍，PB: 5.8 倍，股息率：0.3%
- 行业分类：新能源汽车，行业指数近 20 日涨跌幅：+4.2%

### 二、AI 推断
- 盈利质量：改善明显，规模效应显现
- 成长性：高增长，销量和出口双驱动
- 财务健康度：较好，但负债率偏高
- 估值水平：中性偏高，成长性支撑
- 行业景气度：上升，新能源汽车渗透率持续提升
- 政策/宏观影响：① 出口增长强劲；② 国内价格战仍在持续
- 基本面风险点：① 价格战压缩利润；② 海外贸易壁垒；③ 智能化竞争

### 三、基本面失效条件
- 月度销量同比转负
- 毛利率跌破 18%
- 海外市场遭遇重大关税或禁令

### 四、不确定性
- 新能源汽车行业竞争激烈，技术迭代快""",

        "news": """### 一、可核验事实
1. [2026-08-29] 销量数据：8 月新能源汽车销量公告（来源：深交所公告）
2. [2026-08-26] 定期报告：2026 年半年度报告（来源：深交所公告）
3. [2026-08-22] 公司新闻：新车型发布，智能化升级（来源：公司官网）
4. [2026-08-18] 行业新闻：新能源汽车出口再创新高（来源：经济观察报）

### 二、AI 推断
- 重大事项影响：销量超预期，新车型市场反馈好
- 市场情绪倾向：正面，成长逻辑清晰
- 短期叙事主题：新能源汽车出海 + 智能化
- 关注度变化：高，销量数据发布后关注度上升
- 公告/新闻风险点：无重大负面

### 三、事件驱动的失效条件
- 月度销量不及预期
- 主要出口市场政策变化

### 四、不确定性
- 新车型销量爬坡情况需后续验证""",
    },
}


def get_agent_analyses(
    stock_code: str,
    stock_data: dict,
    mode: str = "auto"
) -> dict:
    """
    获取三个 Agent 的分析结果。

    mode:
    - "auto": 如果有 OPENAI_API_KEY 则用真实模式，否则用 preset_demo
    - "real": 强制使用真实 LLM
    - "mock" / "preset_demo": 强制使用明确标注的预设离线演示
    """
    if mode == "auto":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        mode = "real" if api_key else "preset_demo"

    if mode == "real":
        return _call_real_agents(stock_code, stock_data)
    else:
        if stock_data.get("is_synthetic", False):
            return _get_synthetic_demo_analyses(stock_data)
        return _get_mock_analyses(stock_code, stock_data)


def _get_synthetic_demo_analyses(stock_data: dict) -> dict:
    """仅基于合成快照中的可见数值生成固定演示文案，不映射真实公司。"""
    indicators = stock_data.get("technical_indicators", {})
    name = stock_data.get("stock_name", "合成演示样本")
    technical = (
        f"【预设离线演示，未执行真实 AI 推理】\n"
        f"可核验事实：{name} 的合成快照中，MA5={indicators.get('ma5', 0)}，"
        f"MA20={indicators.get('ma20', 0)}，RSI14={indicators.get('rsi14', 0)}。\n"
        "AI推断示例：均线关系和动量指标可用于提出研究假设，但不能单独证明未来走势。\n"
        "失效条件：价格结构或数据窗口发生显著变化。\n"
        "不确定性：全部行情均为合成数据，不对应真实上市公司。"
    )
    fundamental = (
        "【预设离线演示，未执行真实 AI 推理】\n"
        "可核验事实：当前使用的是合成财务字段，不代表任何真实公司的经营情况。\n"
        "AI推断示例：正式模式应核对收入、利润、现金流、负债及报告期，并保留原始来源。\n"
        "失效条件：缺少可追溯财报时，不应形成真实公司基本面结论。\n"
        "不确定性：本段只用于展示 Agent 输出结构。"
    )
    news = (
        "【预设离线演示，未执行真实 AI 推理】\n"
        "可核验事实：当前新闻条目为合成演示内容，不对应真实公告或媒体报道。\n"
        "AI推断示例：正式模式应逐条记录标题、来源、发布时间和原文链接。\n"
        "失效条件：来源无法核验或发布时间晚于分析时点。\n"
        "不确定性：本段不能作为投资研究证据。"
    )
    data = {"technical": technical, "fundamental": fundamental, "news": news}
    return {
        **data,
        "bull_bear_summary": _generate_bull_bear_summary(data),
        "mode": "preset_demo",
        "run_status": "PRESET_DEMO",
        "model": None,
        "calls": {},
        "mode_notice": "预设离线演示，未执行真实 AI 推理",
    }


def _format_fundamental_readable(fundamental: dict, stock_name: str, stock_code: str, current_price: float = 0) -> str:
    """
    将嵌套的财务数据JSON格式化为中文可读的分析文本。
    所有数字来自原始数据，仅做单位换算和中文字段名翻译。
    """
    period = fundamental.get("latest_reporting_period", "未知")
    unit = fundamental.get("monetary_unit", "人民币百万元")
    industry = fundamental.get("industry", "")

    lines = [
        f"### 一、基本信息",
        f"- 股票：{stock_name}（{stock_code}）",
        f"- 行业：{industry}",
        f"- 报告期：{period}",
        f"- 货币单位：{unit}",
        "",
    ]

    # 最新报告期核心财务指标
    latest = fundamental.get("latest_period", {})
    if latest:
        lines.append("### 二、核心财务指标（来自官方财报）")
        lines.append("")

        # 收入
        revenue = latest.get("revenue")
        revenue_yoy = latest.get("revenue_yoy_pct")
        if revenue is not None:
            rev_yi = revenue / 100  # 百万元 → 亿元
            yoy_str = f"（同比{revenue_yoy:+.1f}%）" if revenue_yoy is not None else ""
            lines.append(f"- **营业收入**：{rev_yi:,.1f}亿元 {yoy_str}")

        # 归母净利润
        net_profit = latest.get("net_profit_attributable_to_parent")
        net_profit_yoy = latest.get("net_profit_yoy_pct")
        if net_profit is not None:
            np_yi = net_profit / 100
            yoy_str = f"（同比{net_profit_yoy:+.1f}%）" if net_profit_yoy is not None else ""
            lines.append(f"- **归母净利润**：{np_yi:,.1f}亿元 {yoy_str}")

        # 扣非净利润
        adj_profit = latest.get("adjusted_net_profit_attributable_to_parent")
        adj_yoy = latest.get("adjusted_net_profit_yoy_pct")
        if adj_profit is not None:
            adj_yi = adj_profit / 100
            yoy_str = f"（同比{adj_yoy:+.1f}%）" if adj_yoy is not None else ""
            lines.append(f"- **扣非净利润**：{adj_yi:,.1f}亿元 {yoy_str}")

        # 经营现金流
        ocf = latest.get("operating_cash_flow")
        ocf_yoy = latest.get("operating_cash_flow_yoy_pct")
        if ocf is not None:
            ocf_yi = ocf / 100
            yoy_str = f"（同比{ocf_yoy:+.1f}%）" if ocf_yoy is not None else ""
            lines.append(f"- **经营现金流净额**：{ocf_yi:,.1f}亿元 {yoy_str}")

        # EPS
        eps = latest.get("basic_eps_cny")
        if eps is not None:
            lines.append(f"- **基本每股收益**：{eps:.2f}元")

        # ROE
        roe = latest.get("weighted_average_roe_non_annualized_pct")
        if roe is not None:
            lines.append(f"- **加权平均ROE**：{roe:.1f}%（未年化）")

        # 分红
        dividend = latest.get("interim_dividend_per_share_cny")
        if dividend is not None:
            lines.append(f"- **中期每股股息**：{dividend:.2f}元")

        # 偿付能力（保险行业）
        solvency = latest.get("group_comprehensive_solvency_adequacy_pct")
        if solvency is not None:
            lines.append(f"- **集团综合偿付能力充足率**：{solvency:.1f}%")

        lines.append("")

    # 资产负债表
    bs = fundamental.get("balance_sheet", {})
    if bs:
        lines.append("### 三、资产负债状况")
        lines.append("")
        total_assets = bs.get("total_assets")
        if total_assets is not None:
            lines.append(f"- **总资产**：{total_assets/100:,.1f}亿元")
        total_liab = bs.get("total_liabilities")
        if total_liab is not None:
            lines.append(f"- **总负债**：{total_liab/100:,.1f}亿元")
        equity = bs.get("equity_attributable_to_parent")
        if equity is not None:
            lines.append(f"- **归母股东权益**：{equity/100:,.1f}亿元")
        al_ratio = bs.get("asset_liability_ratio_pct")
        if al_ratio is not None:
            lines.append(f"- **资产负债率**：{al_ratio:.1f}%")
        sector_note = bs.get("sector_context")
        if sector_note:
            lines.append(f"- 行业说明：{sector_note}")
        lines.append("")

    # 保险业务（如适用）
    ins = fundamental.get("insurance_business", {})
    if ins:
        lines.append("### 四、保险业务经营情况")
        lines.append("")
        nbv = ins.get("life_and_health_new_business_value")
        nbv_yoy = ins.get("life_and_health_new_business_value_yoy_pct")
        if nbv is not None:
            yoy_str = f"（同比{nbv_yoy:+.1f}%）" if nbv_yoy is not None else ""
            lines.append(f"- **寿险及健康险新业务价值**：{nbv/100:,.1f}亿元 {yoy_str}")
        life_solvency = ins.get("life_comprehensive_solvency_adequacy_pct")
        if life_solvency is not None:
            lines.append(f"- **寿险综合偿付能力充足率**：{life_solvency:.1f}%")
        prop_premium = ins.get("property_premium_income")
        prop_yoy = ins.get("property_premium_income_yoy_pct")
        if prop_premium is not None:
            yoy_str = f"（同比{prop_yoy:+.1f}%）" if prop_yoy is not None else ""
            lines.append(f"- **财险保费收入**：{prop_premium/100:,.1f}亿元 {yoy_str}")
        combined_ratio = ins.get("property_combined_ratio_pct")
        cr_change = ins.get("property_combined_ratio_change_pp")
        if combined_ratio is not None:
            change_str = f"（同比{cr_change:+.1f}个百分点）" if cr_change is not None else ""
            lines.append(f"- **财险综合成本率**：{combined_ratio:.1f}% {change_str}")
        lines.append("")

    # 投资组合（如适用）
    inv = fundamental.get("investment_portfolio", {})
    if inv:
        lines.append("### 五、投资组合情况")
        lines.append("")
        scale = inv.get("portfolio_scale_description")
        if scale:
            lines.append(f"- **投资组合规模**：{scale}")
        comp_yield = inv.get("comprehensive_investment_yield_non_annualized_pct")
        if comp_yield is not None:
            lines.append(f"- **综合投资收益率**：{comp_yield:.1f}%（未年化）")
        net_yield = inv.get("net_investment_yield_non_annualized_pct")
        if net_yield is not None:
            lines.append(f"- **净投资收益率**：{net_yield:.1f}%（未年化）")
        lines.append("")

    # 估值分析（理论依据：格雷厄姆《证券分析》，PE/PB/股息率是估值三大支柱）
    lines.append("### 六、估值水平")
    lines.append("")
    # 尝试从数据中提取估值指标
    pe = fundamental.get("pe_ttm") or fundamental.get("pe") or fundamental.get("price_to_earnings")
    pb = fundamental.get("pb") or fundamental.get("price_to_book")
    div_yield = fundamental.get("dividend_yield") or fundamental.get("dividend_yield_pct")
    # 如果有EPS和当前价，可以粗略估算PE（非精确，需标注）
    eps = latest.get("basic_eps_cny") if latest else None
    if pe is None and eps and eps > 0 and current_price > 0:
        # 注意：单期EPS不等于TTM EPS，这里只做粗略参考
        rough_pe = current_price / eps
        lines.append(f"- **PE（粗略估算，非TTM）**：约{rough_pe:.1f}倍（基于单期EPS，仅供参考，非精确估值）")
    if pe is not None:
        lines.append(f"- **市盈率PE(TTM)**：{pe}倍")
    if pb is not None:
        lines.append(f"- **市净率PB**：{pb}倍")
    if div_yield is not None:
        lines.append(f"- **股息率**：{div_yield}%")
    if pe is None and pb is None and div_yield is None:
        lines.append("- 当前快照未包含PE/PB/股息率等估值指标")
        lines.append("- 建议补充行情数据后进行估值分析（PE历史分位、PB历史分位、行业对比）")
        lines.append("- 估值分析理论依据：格雷厄姆《证券分析》(1934)，估值是基本面投资的核心维度")
    lines.append("")

    # AI推断（基于数据的定性判断）
    lines.append("### 七、基本面判断")
    lines.append("")
    judgments = []
    if latest:
        np_yoy = latest.get("net_profit_yoy_pct", 0)
        if np_yoy and np_yoy > 0:
            judgments.append(f"净利润同比增长{np_yoy:.1f}%，盈利能力保持正增长")
        elif np_yoy and np_yoy < 0:
            judgments.append(f"净利润同比下降{abs(np_yoy):.1f}%，需关注盈利承压原因")
        rev_yoy = latest.get("revenue_yoy_pct", 0)
        if rev_yoy and rev_yoy > 5:
            judgments.append("收入增速较快，业务扩张良好")
        ocf_yoy = latest.get("operating_cash_flow_yoy_pct", 0)
        if ocf_yoy and ocf_yoy > 10:
            judgments.append("经营现金流大幅改善，盈利质量较好")
    if ins:
        nbv_yoy = ins.get("life_and_health_new_business_value_yoy_pct", 0)
        if nbv_yoy and nbv_yoy > 20:
            judgments.append("新业务价值高速增长，寿险改革成效显著")
    if not judgments:
        judgments.append("财务数据整体平稳，需结合行业趋势进一步分析")
    for j in judgments:
        lines.append(f"- {j}")
    lines.append("")

    # 失效条件和不确定性
    lines.extend([
        "### 八、基本面失效条件",
        "",
        "- 核心财务指标（收入、净利润）出现显著恶化",
        "- 出现重大负面公告或监管处罚",
        "- 行业政策发生重大不利变化",
        "",
        "### 九、不确定性",
        "",
        "- 以上数据来自官方财报结构化字段，具体口径以原始公告为准",
        "- 单期数据不足以判断长期趋势，需结合多期财报对比",
        "- 金融行业（保险/银行）财务指标口径与一般工商企业不同",
    ])

    return "\n".join(lines)


def _get_mock_analyses(stock_code: str, stock_data: dict) -> dict:
    """
    获取预设的演示分析内容。
    关键数字（价格、均线、RSI、ATR、涨跌幅）从真实快照数据动态提取，
    定性判断（趋势、风险点）使用模板文案，确保数据一致性。
    """
    ind = stock_data.get("technical_indicators", {})
    current_price = stock_data.get("current_price", 0)
    atr_14 = stock_data.get("atr_14", 0)
    key_support = stock_data.get("key_support", 0)
    stock_name = stock_data.get("stock_name", "")
    snapshot_date = stock_data.get("snapshot_date", stock_data.get("analysis_cutoff", ""))
    daily = stock_data.get("daily_data", [])

    ma5 = ind.get("ma5", 0)
    ma10 = ind.get("ma10", 0)
    ma20 = ind.get("ma20", 0)
    ma60 = ind.get("ma60", 0)
    rsi14 = ind.get("rsi14", 0)
    change_20d = ind.get("change_20d", 0)
    change_60d = ind.get("change_60d", 0)
    atr_ratio = (atr_14 / current_price * 100) if current_price > 0 else 0

    # 均线排列判断
    if ma5 > ma10 > ma20 > ma60:
        ma_pattern = "多头排列"
        trend = "上升趋势"
    elif ma5 < ma10 < ma20 < ma60:
        ma_pattern = "空头排列"
        trend = "下降趋势"
    else:
        ma_pattern = "均线纠缠"
        trend = "震荡格局，方向不明"

    # RSI 区间判断
    if rsi14 >= 70:
        rsi_desc = "超买区间，短期有回调风险"
    elif rsi14 <= 30:
        rsi_desc = "超卖区间，可能有技术性反弹"
    else:
        rsi_desc = "中性区间"

    # 波动率判断
    if atr_ratio >= 4:
        vol_desc = "高"
    elif atr_ratio >= 2.5:
        vol_desc = "中高"
    elif atr_ratio >= 1.5:
        vol_desc = "中等"
    else:
        vol_desc = "低"

    # 近20日成交量（手）
    if daily:
        volumes = [d.get("volume", 0) for d in daily[-20:]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0
        avg_vol_wan = avg_vol / 10000  # 转为万手
    else:
        avg_vol_wan = 0

    # 压力位估算：近20日高点
    if daily:
        recent_high = max(d.get("high", 0) for d in daily[-20:])
    else:
        recent_high = current_price * 1.05

    technical = f"""### 一、可核验事实
- 当前价格：{current_price:.2f} 元，日期：{snapshot_date}
- 近 20 日涨跌幅：{change_20d:+.2f}%
- 近 60 日涨跌幅：{change_60d:+.2f}%
- MA5: {ma5:.2f} / MA10: {ma10:.2f} / MA20: {ma20:.2f} / MA60: {ma60:.2f}（{ma_pattern}）
- RSI(14): {rsi14:.1f}（{rsi_desc}）
- ATR(14): {atr_14:.2f} 元，占股价 {atr_ratio:.2f}%
- 近 20 日日均成交量：约 {avg_vol_wan:.1f} 万手

### 二、AI 推断
- 趋势判断：{trend}
- 关键支撑位：{key_support:.2f} 元（依据：近 20 日结构低点，跌破则趋势逻辑失效）
- 关键压力位：{recent_high:.2f} 元（依据：近 20 日高点）
- 波动率评价：{vol_desc}（ATR 占比 {atr_ratio:.2f}%）
- 技术面风险点：① 若跌破 {key_support:.2f} 元支撑，可能打开下行空间；② RSI 和均线信号需结合量能确认

### 三、提供给风险引擎的参数
- 建议关键支撑位：{key_support:.2f} 元
- 建议 ATR 风险倍数：由风险引擎根据波动率自动确定

### 四、不确定性
- 技术指标基于历史数据，不代表未来走势
- 重大公告或政策事件可能导致技术分析失效"""

    # 基本面分析：优先用快照中的真实财务数据，格式化后展示
    fundamental_data = stock_data.get("fundamental", {})
    if fundamental_data and isinstance(fundamental_data, dict) and len(fundamental_data) > 2:
        fundamental = _format_fundamental_readable(fundamental_data, stock_name, stock_code, current_price)
    else:
        # 无真实财务数据时用通用模板
        fundamental = f"""### 一、可核验事实
- 股票：{stock_name}（{stock_code}）
- 行业：{stock_data.get("industry", "待补充")}
- 详细财务数据：当前快照未包含结构化财务字段

### 二、AI 推断
- 正式模式下应核对收入、利润、现金流、负债及报告期，并保留原始来源
- 缺少可追溯财报时，不应形成真实公司基本面结论

### 三、基本面失效条件
- 公司发布业绩下修或重大负面公告
- 行业政策发生重大不利变化

### 四、不确定性
- 本段仅展示 Agent 输出结构，不构成基本面判断"""

    # 公告新闻分析：优先用快照中的真实公告
    news_data = stock_data.get("news", [])
    if news_data:
        news_lines = []
        for i, item in enumerate(news_data[:8]):
            date = item.get("date", "")
            title = item.get("title", "")
            source = item.get("source", "")
            news_lines.append(f"{i+1}. [{date}] {title}（来源：{source}）")
        news = f"""### 一、可核验事实（时间倒序，来自数据快照）
{chr(10).join(news_lines)}

### 二、AI 推断
- 以上公告标题来自官方披露渠道，具体内容需查阅原文
- 公告密集期通常对应业绩发布或重大事项窗口

### 三、事件驱动的失效条件
- 出现业绩下修、监管处罚或重大负面公告
- 核心管理层发生重大变动

### 四、不确定性
- 仅基于公告标题，未提取全文内容，可能遗漏关键细节"""
    else:
        news = """### 一、可核验事实
- 当前快照未包含公告数据

### 二、AI 推断
- 正式模式应逐条记录公告标题、来源、发布时间和原文链接

### 三、事件驱动的失效条件
- 出现未预期的重大公告

### 四、不确定性
- 无公告数据时无法进行事件驱动分析"""

    data = {"technical": technical, "fundamental": fundamental, "news": news}
    return {
        **data,
        "bull_bear_summary": _generate_bull_bear_summary(data),
        "mode": "preset_demo",
        "run_status": "PRESET_DEMO",
        "model": None,
        "calls": {},
        "mode_notice": "预设离线演示，未执行真实 AI 推理；关键数值来自数据快照",
    }


def _generate_bull_bear_summary(analyses: dict) -> str:
    """从三个 Agent 的分析中汇总预设多空证据。"""
    return """### 多头证据
1. 技术面：关键支撑位明确，止损空间可量化
2. 基本面：公司财务数据可核验，行业地位清晰
3. 信息面：公告和新闻来源可追溯

### 空头证据
1. 技术面：存在趋势性风险或压力位压制
2. 基本面：行业景气度或估值存在不确定性
3. 信息面：可能存在未充分反映的负面因素

### 信息冲突与不确定性
- AI 推断部分可能存在偏差，关键决策需人工复核
- 不同信息源可能存在时间差或口径差异
- 极端行情下技术分析和基本面分析可能同时失效"""


def _call_real_agents(stock_code: str, stock_data: dict) -> dict:
    """
    调用真实 LLM API 进行 Agent 分析。
    支持 DeepSeek 或 OpenAI 的 Responses API 环境变量。
    每个 Agent 都记录响应 ID、模型、耗时、Token 用量与原始输出。
    三个 Agent 只有全部成功时才返回 REAL_SUCCESS。
    """
    try:
        from openai import OpenAI
    except ImportError:
        return _real_failure("未安装 openai Python SDK")

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    provider = "deepseek" if deepseek_key else "openai"
    api_key = deepseek_key or openai_key
    base_url = os.environ.get(
        "DEEPSEEK_BASE_URL" if provider == "deepseek" else "OPENAI_BASE_URL",
        "https://api.deepseek.com" if provider == "deepseek" else "https://api.openai.com/v1",
    )
    model = os.environ.get(
        "DEEPSEEK_MODEL" if provider == "deepseek" else "OPENAI_MODEL", ""
    ).strip()

    if not api_key:
        return _real_failure("未设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
    if not model:
        return _real_failure(
            f"未设置 {'DEEPSEEK_MODEL' if provider == 'deepseek' else 'OPENAI_MODEL'}，"
            "请填写当前 API 项目可用的模型 ID"
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 加载 prompt 模板
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    run_started = datetime.now(timezone.utc).astimezone()
    results = {}
    calls = {}

    for agent_name, prompt_file, data_key in [
        ("technical", "technical_agent.txt", "technical_data"),
        ("fundamental", "fundamental_agent.txt", "fundamental_data"),
        ("news", "news_agent.txt", "news_data"),
    ]:
        prompt_path = os.path.join(prompt_dir, prompt_file)
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
        system_prompt += (
            "\n\n## 输出长度控制\n"
            "请直接输出最终分析，不展示思维过程。全文不超过1800个中文字符；"
            "优先保留可核验事实、核心风险、失效条件和不确定性，避免重复复述数据。"
        )

        # 构造用户消息（将股票数据序列化为文本）
        user_content = _format_stock_data_for_agent(stock_data, agent_name)

        call_started = datetime.now(timezone.utc).astimezone()
        clock_started = time.perf_counter()
        call_record = {
            "status": "FAILED",
            "started_at": call_started.isoformat(timespec="seconds"),
            "response_id": None,
            "model": model,
            "provider": provider,
            "duration_ms": None,
            "usage": None,
            "error": None,
        }
        try:
            request_args = dict(
                model=model,
                instructions=system_prompt,
                input=user_content,
                max_output_tokens=3000,
            )
            if provider == "deepseek":
                request_args["reasoning"] = {"effort": "none"}
            if provider == "openai":
                request_args["store"] = False
            response = client.responses.create(**request_args)
            output_text = (response.output_text or "").strip()
            if getattr(response, "status", None) != "completed" or not output_text:
                incomplete = getattr(response, "incomplete_details", None)
                raise RuntimeError(
                    "响应未完成或没有文本输出，"
                    f"status={getattr(response, 'status', None)}, "
                    f"incomplete_details={incomplete}"
                )
            usage = getattr(response, "usage", None)
            call_record.update(
                {
                    "status": "SUCCESS",
                    "response_id": getattr(response, "id", None),
                    "model": getattr(response, "model", model),
                    "usage": {
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                    }
                    if usage
                    else None,
                }
            )
            results[agent_name] = output_text
        except Exception as exc:
            call_record["error"] = str(exc)
            results[agent_name] = ""
        finally:
            call_record["duration_ms"] = round(
                (time.perf_counter() - clock_started) * 1000
            )
            call_record["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat(
                timespec="seconds"
            )
            calls[agent_name] = call_record

    success_count = sum(call["status"] == "SUCCESS" for call in calls.values())
    run_status = (
        "REAL_SUCCESS" if success_count == 3 else "REAL_PARTIAL" if success_count else "FAILED"
    )
    results["bull_bear_summary"] = (
        _generate_bull_bear_summary(
            {
                "technical": results.get("technical", ""),
                "fundamental": results.get("fundamental", ""),
                "news": results.get("news", ""),
            }
        )
        if run_status == "REAL_SUCCESS"
        else ""
    )
    results["mode"] = "real"
    results["run_status"] = run_status
    results["model"] = model
    results["provider"] = provider
    results["started_at"] = run_started.isoformat(timespec="seconds")
    results["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )
    results["calls"] = calls
    return results


def _real_failure(message: str) -> dict:
    """生成不会被误认为真实成功的失败结果。"""
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "technical": "",
        "fundamental": "",
        "news": "",
        "bull_bear_summary": "",
        "mode": "real",
        "run_status": "FAILED",
        "model": os.environ.get("DEEPSEEK_MODEL", os.environ.get("OPENAI_MODEL", "")),
        "provider": "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "openai",
        "started_at": now,
        "completed_at": now,
        "calls": {},
        "error": message,
    }


def _format_stock_data_for_agent(stock_data: dict, agent_type: str) -> str:
    """将股票数据格式化为 Agent 可读的文本"""
    lines = [f"股票代码：{stock_data.get('stock_code', '')}"]
    lines.append(f"股票名称：{stock_data.get('stock_name', '')}")
    lines.append(f"当前价格：{stock_data.get('current_price', '')}")
    lines.append("")

    if agent_type == "technical":
        ind = stock_data.get("technical_indicators", {})
        lines.append("## 技术指标")
        for k, v in ind.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("## 近 20 个交易日数据（日期, 开, 收, 高, 低, 成交量）")
        for d in stock_data.get("daily_data", [])[-20:]:
            lines.append(f"{d.get('date','')}, {d.get('open','')}, {d.get('close','')}, "
                         f"{d.get('high','')}, {d.get('low','')}, {d.get('volume','')}")

    elif agent_type == "fundamental":
        lines.append("## 官方财报结构化数据（JSON）")
        lines.append(json.dumps(stock_data.get("fundamental", {}), ensure_ascii=False, indent=2))

    elif agent_type == "news":
        lines.append("## 近期公告与新闻")
        for item in stock_data.get("news", [])[:15]:
            lines.append(f"- [{item.get('date', '')}] {item.get('title', '')}（{item.get('source', '')}）")
        lines.append("")
        lines.append("## 已保存并核验的官方原文")
        for item in stock_data.get("official_documents", []):
            lines.append(
                f"- [{item.get('published_date', '')}] {item.get('title', '')}"
                f"（来源：{item.get('source', '')}；本地文件：{item.get('local_file', '')}）"
            )

    return "\n".join(lines)
