# RiskPilot

RiskPilot 是一款面向个人投资者的 AI 风险教育与历史决策实验产品。它不以预测涨跌为核心，而是先让用户明确模拟本金与最大损失预算，再通过多智能体分析、确定性风险计算和历史回放，帮助用户理解仓位、压力情景与决策纪律。

> 本项目使用固定历史数据，不连接真实证券账户、不自动下单，不构成投资建议或收益承诺。历史数据与模拟结果不代表未来表现。

## 在线体验

- 产品主页：<https://five609-riskpilot-aix-origin-2026.onrender.com/>
- 历史决策实验：<https://five609-riskpilot-aix-origin-2026.onrender.com/replay>
- API 健康检查：<https://five609-riskpilot-aix-origin-2026.onrender.com/api/health>

免费云服务可能休眠，首次打开通常需要等待几十秒。

## 产品亮点

- **风险预算优先**：先定义最大可承受损失，再计算参考仓位和压力情景。
- **多智能体协作**：技术面、基本面和信息面 Agent 分工输出，确定性风险引擎负责约束与校验。
- **时间隔离回放**：月度 4 关或周度 17 关，只向用户揭示当前节点及以前的数据，避免未来信息泄漏。
- **决策纪律量化**：归一化记录预算突破、情绪化调整、仓位越界和最大回撤，兼容不同实验长度。
- **可追溯数据链路**：保存来源、抓取参数、原始响应、标准化结果和 SHA-256 校验信息。
- **可部署与可验证**：FastAPI 后端、静态前端、自动化测试和 Render 云部署构成完整产品闭环。

## 核心功能

- 100 只 A 股固定历史样本，覆盖 30 个项目自定义行业标签。
- 股票名称/代码搜索、行业筛选和快速体验案例。
- K 线、均线、成交量、账户轨迹、未来遮挡与压力测试。
- 多用户身份、排行榜、主题阵营和实验结果反馈。
- 最大损失预算触发后终止后续选择，并按规则模拟退出。
- 标准化 JSON API，可返回结构化历史风险教育结果。

## 技术架构

```text
Browser UI (HTML / CSS / JavaScript)
            │
            ▼
FastAPI application
  ├─ Multi-agent analysis
  ├─ Deterministic risk engine
  ├─ Historical replay engine
  ├─ Discipline scoring / leaderboard
  └─ Public structured API
            │
            ▼
Versioned historical snapshots and evidence manifests
```

详细架构可打开 [`RiskPilot_系统架构图.html`](./RiskPilot_系统架构图.html)。

## 本地运行

1. 安装 Python 3.11 或更高版本，并勾选 `Add Python to PATH`。
2. 下载或克隆本仓库。
3. 双击 `运行演示.cmd`，首次启动需要联网安装依赖。
4. 打开 `http://127.0.0.1:8012/`；历史实验地址为 `http://127.0.0.1:8012/replay`。
5. 运行期间不要关闭启动窗口。

也可以手动启动：

```powershell
python -m pip install -r backend/requirements.txt
python backend/main.py
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖风险预算、回放时间隔离、执行规则、数据完整性、排行榜服务端复算和结构化 API。公开整理版本完成时，全量 45 项测试通过。

## 项目结构

- `frontend/`：股票分析与历史实验页面。
- `backend/`：API、多智能体分析、风险计算、历史回放与排行榜逻辑。
- `data/`：固定股票池、历史行情及可追溯证据文件。
- `tests/`：风险引擎、历史回放、数据隔离和接口测试。
- `docs/`：数据准备、真实 LLM 模式与运行说明。

## 数据与 AI 边界

- 默认无需 API Key，使用可离线运行的预设分析；这不代表每次执行都发生了真实 LLM 推理。
- 真实 LLM 模式仅从环境变量读取密钥，仓库不保存任何密钥。
- 历史实验仅使用节点及以前的数据，不查看尚未揭晓的未来走势。
- 当前样本是产品验证数据集，不是随机或市值加权抽样，也不是股票推荐池。
- 上游公开可访问不等于获得商业再分发授权；商业化前需重新核验数据许可与合规要求。

## 安全与隐私

公开版本不包含内部提交材料、个人联系方式、团队成员信息或运行密钥。提交问题前请阅读 [`SECURITY.md`](./SECURITY.md)。

## 授权说明

本仓库用于个人作品展示与技术交流，暂未授予复制、修改、再发布或商业使用许可。第三方数据及文档的权利归各自权利人所有。