# RiskPilot 真实数据与真实 LLM 演示操作手册

## 一、一次性准备

在 PowerShell 中进入项目后端并安装依赖：

```powershell
cd C:\Users\Administrator\Desktop\测试文件\RiskPilot\backend
python -m pip install -r requirements.txt
```

## 二、生成可追溯历史数据证据包

先确定一个已经结束的分析截止日。历史研究模式不要使用盘中实时数据。例如：

```powershell
python build_evidence_pack.py --code 601318 --name 中国平安 --industry 保险 --start 20250101 --end 20250831 --activate
```

生成目录为 `data/evidence/601318/2025-08-31/`，其中包括：

- `raw/price_daily.csv`：原始历史日线；
- `raw/fundamental_index.csv`：公司资料接口原始结果；
- `raw/announcement_index.csv`：巨潮资讯公告索引；
- `normalized/riskpilot_snapshot.json`：系统实际读取的数据；
- `source_manifest.json`：接口、参数、上游来源、版本和获取时间；
- `sha256_manifest.json`：文件哈希清单；
- `evidence_pack_id.txt`：本证据包标识；
- `official_documents.json`：官方原文登记模板。

`--activate` 会先备份原快照，再把新快照放到 `data/snapshots/601318.json`。

## 三、补齐官方原文

从巨潮资讯或交易所公告页下载至少一份与演示结论有关的官方 PDF，放入证据包的 `raw/` 文件夹。然后编辑 `official_documents.json`，逐份填写：

```json
{
  "documents": [
    {
      "title": "公告的完整标题",
      "published_date": "2025-08-27",
      "source": "巨潮资讯",
      "source_url": "原公告页面链接",
      "local_file": "raw/公告文件名.pdf"
    }
  ]
}
```

补文件后重新运行同一条证据包命令，或自行重新计算哈希。不要修改原始 CSV 内容；如需清洗，只修改标准化文件并保留处理说明。

## 四、开启真实 LLM

不要把密钥写入代码、截图或提交到仓库。在启动后端的同一个 PowerShell 窗口执行：

```powershell
$env:OPENAI_API_KEY="你的密钥"
$env:OPENAI_MODEL="你的 API 项目当前可用的模型 ID"
python main.py
```

如果使用 DeepSeek API，则改为：

```powershell
$env:DEEPSEEK_API_KEY="你的DeepSeek密钥"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
python main.py
```

项目默认连接 `https://api.deepseek.com`，并在运行证据中记录提供方、模型名、响应ID和Token用量。不要同时设置两家提供方的密钥；如同时存在，项目优先使用DeepSeek。

调用 `/api/analyze` 时使用：

```json
{
  "stock_code": "601318",
  "capital": 100000,
  "max_loss": 2000,
  "agent_mode": "real"
}
```

只有三个 Agent 都返回成功，接口才会返回正式报告；失败或部分成功都会明确报错，不会偷偷替换成预设文案。

## 五、如何核验一次真实 LLM 运行

成功后，接口响应中的 `demo_run_dir` 指向 `data/demo_runs/` 下的本次运行目录。建议按以下顺序展示：

1. `source_manifest.json`：数据来自哪里、何时获取、使用了哪些参数；
2. `sha256_manifest.json` 与 `evidence_pack_id.txt`：原始文件可校验；
3. `run_manifest.json`：真实模式、模型、三个响应 ID、Token 用量和报告哈希；
4. 三份 `agent_*_output.txt`：三个 Agent 的原始输出；
5. `risk_engine_output.json`：AI 无权覆盖的确定性风险计算；
6. `final_report.md`：最终面向用户的报告。

对外展示时应明确说明：这是固定截止日的历史研究演示，不是实时荐股；系统不接证券账户、不自动下单；账户最大损失是标准情景预算而非损失保证。
