# 中央汇金（国家队）核心宽基 ETF 每日净买入/净卖出报表



追踪中央汇金重仓的 **23 只核心宽基 ETF**（归为 **11 个指数类别**）的每日资金净买卖，

输出一份**自包含 HTML 报表**，图形与数据全部内联，断网也能看。



- **在线报表（点开即用）**：https://wj624.github.io/national-team-etf-flow/

- **看板中心（聚合入口）**：https://wj-dashboards.pages.dev/

- **原版报表（上游 wwww1998）**：https://wwww1998.github.io/national-team-etf-flow/

- **源码仓库**：https://github.com/wj624/national-team-etf-flow

- **给 AI 的摘要**：https://wj624.github.io/national-team-etf-flow/llms.txt



**一句话原理**：用 ETF 每日**份额变化 × 单位净值**，反推出当天有多少钱流进或流出（推导过程见第一节）。



> 本仓库复制自 [wwww1998/national-team-etf-flow](https://github.com/wwww1998/national-team-etf-flow)。

> **23 只标的、11 个类别、全部计算口径与原文一致**，改动集中在「怎么让它稳定、省资源地跑下去」。

> 逐项对照见下一节。



---



## 和原版（wwww1998）有什么不同



两个版本**看的是同一批数据、算的是同一个公式**，差别全在「怎么跑」和「跑完给谁用」。



| 项目 | 原版（wwww1998） | 本版（wj624） |
|---|---|---|
| 在线地址 | <https://wwww1998.github.io/national-team-etf-flow/> | <https://wj624.github.io/national-team-etf-flow/> |
| 单次耗时 | 中位 **9 分 43 秒**（近 22 次：最短 4 分、最长 69 分） | **7 分 33 秒**（实测） |
| 页面体积 | 较小（外链版） | **较大（内联版，全内联）** |
| 沪市取数失败时 | 用东财实时快照凑数，可能写入陈旧值 | **读同源仓库整行镜像**，不齐就停在上一交易日 |
| 仓库文件数 | 较少 | 较多 |
| 每日邮件推送 | 无 | `gas-national-team-daily.gs`（可选） |



> **关于「仓库体积」这一行**：两版显示的都是 GitHub 含**全部历史提交**的值，原版明显更大。

> 原版 2026-08-25 建库、每天提交约 10 次，至今 1100+ 次运行；本版 2026-10-31 建库、每天 1 次。

> 所以这个差距里既有「跑得少」，也有「还年轻」——单看工作区文件，本版其实更大

> 因为多存了 `_etf_data.json`、三份 AI 摘要和 ECharts 本体。

> 真正能长期拉开差距的是**提交频次低一个数量级**。



### ① 每天 10 次 → 1 次



原版把定时任务铺得很密：07:45–09:30 每 15 分钟一趟，再加 16:00 和 23:00，目的是「接住交易所**次日才发布**的份额」。



本版只留工作日 23:00 一次。代价是最新数据日可能比当天晚一个交易日，**但历史不会丢**——

增量窗口每次都回溯最近 12 天，下一次运行会自动补齐。运行次数从每年约 3650 次降到约 250 次，

机时从每天约 100 分钟降到 8 分钟。



对「一天只看一次」的使用习惯，这个取舍是划算的。如果你希望早上开盘前就能看到昨天的数据，

把 cron 加回 07:45 和 09:30 两个时间点即可（见第七节）。



### ② 图表从「外链」改成「内联」



`refresh.py` 里 ECharts 的路径原本写死成原作者本机的一个绝对路径：



```python

_EC_PATH = r"C:\Users\wxk11\.trae-cn\memory\echarts.min.js"

```



除了他那台电脑，任何机器——**包括 GitHub 的云端 runner**——都找不到这个文件，于是自动退回外链

`registry.npmmirror.com`。后果是：**页面的图并不自包含**，那个 CDN 一旦不通，所有图表空白

（下方数字表格还在，图全没了）。



实际上原版线上页面至今仍是外链状态（体积明显小于内联版），带着一个指向
`registry.npmmirror.com` 的 `<script>`。



本版把 **ECharts 5.5.0 原版**放进仓库，改成三级查找：



1. 原作者本机路径（保留兼容，他本机行为不变）

2. **仓库根目录的 `echarts.min.js`（新增，云端 checkout 即得）**

3. 都找不到才退回 CDN（最后兜底）



云端因此命中第二级，产出**体积更大的全内联页面，零外链、断网可用**。

上线实测（2026-11-03）：云端日志出现
`ECharts 内联来源: /home/runner/work/national-team-etf-flow/national-team-etf-flow/echarts.min.js`，
提交的 `index.html` 为全内联版本，页面里 `<script src>` 外链数为 **0**、无 `npmmirror` 字样。

> 刷新后仍看到旧页面或图空白，多半是 GitHub Pages 的缓存：加个 `?v=时间戳` 再看，或 Ctrl+F5 强刷。



### ③ 补了给 AI 和给邮件用的下游产物



原版只有 `index.html` 和份额缓存两样东西。本版多了 `make_summary.py`，每次刷新额外产出：



- `latest.json`（体积很小）：算好的结论数，供程序 / 邮件脚本读

- `llms.txt`（体积很小）：人话版摘要，可直接整段贴给大模型

- `snapshot.md`（体积很小）：同上内容，GitHub 上可直接渲染阅读



并配套一个 Google Apps Script 邮件脚本，工作日早上把结论发到邮箱（可选，见第十二节）。

### ④ 数据兜底更保守：同源镜像，宁缺勿错

2026-11-02 那天，本版报表显示沪深300 净卖出 −88.70 亿份，而 etf-lsi 显示净买入 +25.34 亿份，两边正相反。
原因：云端连不上上交所 → 旧逻辑回退东财实时快照 → 取到 301.99 亿份的陈旧份额（真值 414.01）→ 算出假减持。

| | 原版 | 本版 |
|---|---|---|
| 取数失败时 | 东财实时快照（可能陈旧） | 同源仓库整行镜像 |
| 最坏结果 | 报表出现错误数字 | 报表晚一天更新 |
一句话：**宁可少一天，不写错一个数**。这是两版在「数据准确性」上的关键差别。
代价是兜底依赖对方仓库存在——就算哪天没了，结果也只是停更一天，不会算错。



---



## 一、这份报表回答什么问题



中央汇金（俗称"国家队"）在护盘或调仓时，主要通过申购/赎回宽基 ETF 来实现。ETF 的**总份额**每天由交易所公布，

份额变多说明有人净申购（资金流入），份额变少说明有人净赎回（资金流出）。



于是可以用份额变化反推资金流向：



> **当日净买卖 =（当日基金份额 − 上一交易日份额）× 当日单位净值**



这就是整个项目的核心。它不区分申购方是谁（所以严格说跟踪的是"全市场在该 ETF 上的申赎净额"，

汇金只是其中最大的参与者之一），但作为观察国家队动向的代理指标，是市面上最常用、也最可验证的口径之一。



## 二、页面有哪些内容



打开在线报表，从上到下依次是：



| 模块 | 说明 |
|---|---|
| **KPI 卡片** | 最新交易日 / 近一周 / 近一月的合计净买卖（亿元） |
| **累计持仓金额** | 最长约 3 年的折线，按当前份额 × 净值估算的持仓市值，悬停看当日值 |
| **同类指数归集汇总** | 把跟踪同一指数的多只 ETF 加总（如 4 只沪深300ETF 合成一行），含最新份额与持仓市值 |



> **倍量**是什么：当日净买入金额 ÷（该类 2025-12-31 市值 × 0.1%），单位是"倍"。

> 它把绝对金额归一化，方便横向比较不同体量的指数——比如 1 亿元买沪深300 和 1 亿元买 MSCI A50，含金量并不一样。



## 三、监控哪些 ETF



共 **23 只**，归为 **11 个指数类别**：



- 沪深300：510300、510310、510330、159919

- 上证50：510050、510100

- 中证500：510500、512500、159922

- 中证1000：512100、159845、560010、159629

- 创业板：159915、159952、159977

- 科创板50：588080、588050

- 上证180：510180；上证180金融：510230

- 深证100：159901

- 中证800：515800

- MSCI中国A50：560050



清单写在 `refresh.py` 的 `TARGETS`（成员与市场归属）和 `CAT_MAP`（指数归类）里，想加减标的直接改这两个列表即可。



## 四、数据来源

> 2026-11 起**不再依赖 AKShare**。份额 / 净值 / 交易日历改由自建的
> [wj624/a-stock-api](https://github.com/wj624/a-stock-api) Worker 统一代理
> （`https://a-stock-api.wj4020410.workers.dev`），深市份额则在仓库内直连交易所官方 xlsx。
> 原因：AKShare 内部 `http.get` **既无 timeout 也无重试**，且 GitHub runner 的共享出口 IP 会被上交所限流，
> 换个出口 IP（Cloudflare）才是解法。

| 数据 | 来源 | 取数方式 |
|---|---|---|
| 沪市 ETF 份额 | 上交所 | Worker `/api/etf-shares?exchange=SH&date=YYYY-MM-DD`（逐日） |
| 基金单位净值 | 天天基金 | Worker `/api/fund-nav?code=XXXXXX`（东财 pingzhongdata） |
| 中证全指 K 线 | 东方财富（主）/ 腾讯（备） | `push2his` / `web.ifzq.gtimg.cn` |

> 东方财富只用于**指数 K 线**，不再参与份额计算。份额兜底改用同源镜像，原因见第五节第 4 条。

**单位约定（错一个数量级会静默毁掉全部份额指标）**

- 上交所接口原始字段 `TOT_VOL` 单位是**万份**；Worker 返回 `shares_10k`（万份），本仓库需 **× 10000** 换成「份」。
- 深交所 xlsx 的 `基金规模(份)` 本身已是「份」，**不得再乘**。
- 深交所该接口 `SHOWTYPE=JSON` 会返回 HTTP 500，**只有 xlsx 可用**，因此仓库里用 `openpyxl` 解析。

**已知风险：Worker 返回空表 ≠ 当天没数据**

Worker 会把上交所的偶发失败包装成 `200 + data: []`（同时在响应里带 `upstream_error` 字段说明原因）。
本仓库目前遇到空表就按「这天没份额」处理，会退化成 westock 旧值 —— **不会产生假数据**，但会丢掉 T+0 精度。
若要更稳，可参照 `wj624/etf-lsi` 的做法：**空表必须用直连 `query.sse.com.cn` 复核一次**再接。

**上游变了怎么办**

本仓库只消费 Worker 的 HTTP 契约，不消费 AKShare。同步上游、验证、部署的完整流程见
`wj624/a-stock-api` 仓库 `README.md`（内含**给 AI 的同步提示词**与 Runbook）。
只要 `/api/etf-shares`、`/api/fund-nav`、`/api/trade-calendar` 的**字段名与单位不变**，本仓库无需改动。

## 五、脚本做了哪些防错校准



份额口径看着简单，实际有几个坑，脚本都做了处理：



1. **份额折算/拆分识别**：基金做份额合并或拆分时，份额会等比骤变、净值反向等比联动（两者乘积≈1）。

   脚本检测到"份额变化 >30% 且净值反向变化"时，判定为非真实申赎，把当日净买卖**强制置 0**，避免假信号。

2. **沪深发布不同步**：两市公布节奏不一致时，取**两市都有数据的最近共同交易日**作为展示日，

   不会拿单边数据算出错误的合计值。

3. **幽灵交易日过滤**：用交易日历剔除落在非交易日（周末/法定节假日）的份额快照，

   防止节假日被兜底数据填成空柱子污染 X 轴。

4. **沪市兜底：同源镜像 + 宁缺勿错**。云端访问上交所接口偶有失败（Worker 也会被限流，重试 3 次仍有残次），

   此时从**同源仓库的份额缓存**（`wwww1998/national-team-etf-flow` 的 `_etf_shares_cache.json`）

   读取**同一交易日**的整行数据补齐，三道门槛任一不满足就整段沪市一并丢弃：

   - 日期必须**精确匹配**（不接受「拿最近一天顶替」）；
   - 镜像整行须达**完整行量级**（≥100 个代码，防止镜像自己也是半行）；
   - 本表 **15 只沪市标的全有正值**。

   不满足时报表**停在上一完整交易日**——宁可少一天，绝不写半行或旧值；接口恢复后由增量窗口自动回补。

   > 为什么不再用东财快照：2026-11-02 该接口对 510300 返回 301.99 亿份的**陈旧值**（真值 414.01 亿份），
   > 报表因此算出 −88.70 亿份的假减持，与 etf-lsi 的 +25.34 亿份方向相反。该路径已彻底移除。

5. **数据新鲜度自检**：若展示日落后于最近已结束交易日，等待 150 秒后重试，最多重试 2 次。



## 六、增量缓存机制（重要）



`_etf_shares_cache.json`（体积随数据增长）保存着近 **5 年**（`CAL_DAYS = 1850` 个工作日）的份额历史，同时缓存交易日历。



- 每次运行**只增量拉取最近约 12 天**再合并写回，因此云端跑一次只要几分钟；

- 若缓存起点晚于 5 年窗口，会自动从 5 年起点补齐一次，之后就一直是完整历史；

- 每次运行结束后缓存会被写回，并由工作流一并提交到仓库——**历史数据云端自持**，不依赖 Actions 的 actions/cache。



> ⚠️ **不要删除 `_etf_shares_cache.json`**。删了就要重新全量补抓 5 年历史，耗时长且容易中途失败。



## 七、自动运行



由 GitHub Actions 工作流 `.github/workflows/daily-refresh.yml` 驱动，在 `ubuntu-latest` + Python 3.11 上：

装依赖 → 跑 `refresh.py` → 把产物复制成 `index.html` → 连同缓存一起提交回仓库 → Pages 自动重新部署。



**当前调度：北京时间每周一至周五 23:00 跑一次**（cron 写的是 UTC，北京 = UTC+8）。



```yaml

- cron: "0 15 * * 1-5"    # 15:00 UTC = 23:00 北京，周一至周五

```



几个实现细节：



- **不会刷空 commit**：数据未推进时脚本沿用旧的"更新时间"，输出字节完全一致，

  工作流用 `git diff --cached --quiet` 检测到无变化就跳过提交。

- **并发保护**：脚本抓取耗时较长，push 前会先 `git pull --rebase origin main`，避免被他人提交挡住。

- **超时保护**：`timeout-minutes: 25`。GitHub 不给这行时的默认上限是 **360 分钟（6 小时）**——

  某个数据接口卡住不返回，任务会一直挂着，白占一个并发位，日志也要等很久才看得到。

  正常一轮 7–10 分钟（脚本自带的数据滞后自检最多再等 150 秒 × 2 次 = 5 分钟），25 分钟留足余量；

  真超了说明是**卡死而不是算得慢**，直接中断、等下一次调度重跑即可（历史不会丢，增量窗口会补）。

- **手动触发**：仓库 → Actions → 每日自动刷新国家队ETF报表 → Run workflow。



### 想改调度时间？



编辑 `.github/workflows/daily-refresh.yml` 里的 `cron` 即可，一行一个时间点。换算规则：



```

北京时间 − 8 小时 = UTC 时间，且分钟数不变

```



| 想要的时间 | cron 写法 | 含义 |
|---|---|---|
| 每天 23:00 | `0 15 * * *` | 每天 |
| 工作日 08:00 + 23:00 | `0 0 * * 1-5` 和 `0 15 * * 1-5` | 两个时间点 |


> 注意：GitHub 的 cron 用 UTC，且受调度拥挤影响可能延后几分钟到几十分钟，属正常现象；

> 星期字段不要用 `7`（部分实现里 7 既可能是周日也可能是无效值）。



### 为什么原来要跑 10 次，现在只跑 1 次够吗？



> 这一节是对照表里「每天 10 次 → 1 次」那条的展开说明。



原作者设置了早盘 07:45–09:30 每 15 分钟一趟，是为了接住交易所**次日才发布**的份额数据。

改成"工作日 23:00 一次"的实际影响是：



- **最新数据日可能比当天晚 1 天**——晚上 23:00 若交易所还没发布当日份额，报表显示的就是前一交易日；

- **但历史不会丢**。增量窗口会回溯最近 12 天，下一次运行会自动把落下的日子补齐；

- A 股只在周一至周五交易，所以"工作日"调度不会漏掉任何交易日。



对"一天只看一次"的使用习惯，这个取舍是划算的：运行次数从每年约 3650 次降到约 250 次，

而代价只是最新数据可能滞后一个交易日。



## 八、本地运行



```bash

pip install pandas requests openpyxl

python refresh.py

```



> 跑之前确认仓库根目录有 `echarts.min.js`（本仓库自带，clone 下来就有）。

> 没有它也能跑，但产出的页面会退回外链 CDN、不再自包含。



会生成三个产物：



| 文件 | 说明 |
|---|---|
| `国家队ETF每日净买入卖出报表.html` | 主报表；由 `refresh.py` 运行时生成，随后被工作流 `cp` 成 `index.html`，本身不必进版本库 |
| `_etf_data.json` | 完整原始数据，便于二次分析 |
| `_etf_shares_cache.json` | 近 5 年份额历史 + 交易日历缓存（数据资产，勿删） |


Windows 下若想用计划任务托管，可参考 `update_and_push.ps1`（带锁文件、日志、无变化跳过推送），

使用前把脚本里的仓库路径和 PAT 文件路径改成你自己的。



## 九、数据接口（给程序 / 给 AI 读）



页面本身是体积较大的自包含 HTML（内含 ECharts 本体），数值全部埋在 JS 数组里（`IDX_K` / `IDX_Q` / `DATA_D` 等），

剥掉脚本后只剩很短一段口径说明——**AI 的网页抓取器读不到任何一个数字**。



所以每次刷新会额外产出三份纯文本，连同完整原始数据一起，供脚本和大模型直接使用：



| 文件 | 大小 | 用途 |
|---|---|---|
| `_etf_data.json` | 较大 | 完整原始数据（`refresh.py` 生成）。含 11 类指数 5 年 K 线、23 只 ETF 逐日序列 |
| `latest.json` | 很小 | 算好的结论数，供程序 / 邮件脚本读 |
| `llms.txt` | 很小 | 人话版摘要，可直接发给大模型 / 粘贴进对话框 |
| `snapshot.md` | 很小 | 与 `llms.txt` 同内容，GitHub 上可直接渲染阅读 |



直接访问：



```text

在线看板      https://wj624.github.io/national-team-etf-flow/

给 AI 的摘要   https://wj624.github.io/national-team-etf-flow/llms.txt

精简数据      https://wj624.github.io/national-team-etf-flow/latest.json

全量数据      https://wj624.github.io/national-team-etf-flow/_etf_data.json

```



> 想要人看的图表版就用第一个；想让 AI 总结、或自己写脚本取数，用第二个/第三个。

> `_etf_data.json` 体积较大，一般不必直接下载。



**实测状态（2026-11-01）**：



| 地址 | 状态 | Content-Type | 大小 |
|---|---|---|---|
| `index.html` | 200 | text/html | 较大（随数据增长） |
| `llms.txt` | 200 | text/plain | 很小 |
| `_etf_data.json` | 200 | application/json | 较大（随数据增长） |



> ⚠️ **`.nojekyll` 不能删。** GitHub Pages 默认跑 Jekyll，会**静默排除所有以 `_` 开头的文件**，

> 导致 `_etf_data.json` / `_etf_shares_cache.json` 返回 404。仓库根目录那个空的 `.nojekyll`

> 就是用来关闭 Jekyll 处理的。删了它，上面两个文件立刻变 404。



`latest.json` 里已经算好了这些结论，下游不用重算：



| 字段 | 含义 |
|---|---|
| `today.net` | 当日全表净买卖（亿元，正=净买入） |
| `today.rank_text` | 「史上第 N 大单日净买入」 |
| `today.idx_chg` / `today.tag` | 当日中证全指涨跌，以及「越跌越买 / 顺势加仓 / 涨了就卖 / 下跌也在卖」判定 |
| `mv` | 全表持仓市值、历史分位、近一年高低点 |
| `etfs[]` | 23 只 ETF 的今日 / 本周 / 本月 / 倍量 / 最新份额 |



## 十、发布为网页



1. 仓库 **Settings → Pages**，Source 选 `Deploy from a branch` → 分支 `main`、目录 `/`（根目录）。

2. 访问 `https://<用户名>.github.io/<仓库名>/`。



报表是**完全自包含**的：ECharts 本体已经放进仓库并内联进页面，不引用任何外部 CDN，

**断网、离线、或者 CDN 挂了都不影响图表**。这也是本版与原版最直观的一处差别（详见开头对照表）。



## 十一、文件说明



```

.github/workflows/daily-refresh.yml   GitHub Actions 定时刷新工作流

refresh.py                            抓取 + 计算 + 生成报表的全部逻辑

echarts.min.js                        ECharts 5.5.0 本体，构建时内联进页面，勿删

make_summary.py                       从 _etf_data.json 提炼 latest.json / llms.txt / snapshot.md

gas-national-team-daily.gs            Google Apps Script 邮件脚本（每天早上发一封解读）

复制邮件脚本.html                     打开即可一键复制上面这个脚本的页面（每次拉最新版）

index.html                            已发布的自包含报表（由工作流自动生成并提交，体积较大）

.nojekyll                             空文件，关闭 Jekyll，否则下划线开头的文件不会被发布

_etf_data.json                        完整原始数据（自动生成并提交，供下游读取）

latest.json                           精简结论数（自动生成，体积很小）

llms.txt / snapshot.md                人话版摘要（自动生成，体积很小）

_etf_shares_cache.json                近 5 年份额历史 + 交易日历缓存（勿删）

update_and_push.ps1                   Windows 计划任务用的本地刷新+推送脚本（可选）

README.md                             本文件

```



> `echarts.min.js` 是**源文件不是产物**，别当垃圾清理掉。`refresh.py` 按

> 「原作者本机路径 → 仓库里的这份 → CDN」三级查找，删了它云端就只能退回外链，图表又变回依赖网络。



> `latest.json` / `llms.txt` / `snapshot.md` 都是**构建产物**，不要手改——下次刷新会被覆盖。

> 要调整内容请改 `make_summary.py`，本地先跑 `python make_summary.py --check` 预览。

### 出问题时先看这几行日志

| 日志关键字 | 含义 | 要不要管 |
|---|---|---|
| `数据新鲜度: 最新同步日=… 期望=… 正常` | 展示日已是最新交易日 | 正常 |
| `同源镜像兜底: 补入 … 沪市 15 只(镜像整行齐全)` | 上交所取数失败，已用镜像补齐 | 正常，数据可信 |
| `镜像兜底: … 行仅 N 个代码, 疑似半行, 拒绝` | 镜像自己也没跑完，被安全校验拦下 | 正常，属预期保护 |
| `ECharts 未找到本地副本, 回退 CDN 外链` | `echarts.min.js` 丢失或被清理 | 需处理：恢复该文件 |


## 十二、每天早上收一封邮件（可选）



`gas-national-team-daily.gs` 是配套的邮件脚本，跑在 Google Apps Script 上，免费、不用服务器。

它读本站的 `latest.json`，把结论整理成一封图文邮件，**工作日 08:30（北京）**发到你的邮箱。



### 分工



计算全部在 `make_summary.py` 里做完，GAS **只负责取数和排版**。

这样两端的算法不会各写一套、慢慢漂移——改口径只改 Python 一处。



### 部署步骤



> 想省事就直接开 **<https://wj624.github.io/national-team-etf-flow/复制邮件脚本.html>** ——

> 那个页面每次都从仓库拉最新代码，点「复制全文」再去 Apps Script 里粘贴就行，不用下载文件。



1. 打开 <https://script.google.com/home> → 左上「新项目」

2. 项目名改成 **五、 国家队ETF流向**

3. 把 `gas-national-team-daily.gs` 全文粘进编辑器，**覆盖掉默认的空 `myFunction`**，`Ctrl+S` 保存

4. **设置 Gemini 密钥**（只需一次）。密钥不写在代码里，而是存进「脚本属性」：

   - 去 <https://aistudio.google.com/apikey> 点「Create API key」拿一把

   - 在编辑器里临时加一行（可以加在文件最末尾）：

     ```js

     function setupKey() { setGeminiKey('把刚复制的密钥粘贴到这里'); }

     ```

   - 下拉选 `setupKey` → 运行 → 日志出现「✅ 已保存密钥：AIzaSy…xxxx（39 位）」

   - **把刚才那行删掉**，`Ctrl+S`

5. 依次运行下面三个函数（都在编辑器顶部下拉里选），每个第一次都会弹授权，

   点「查看权限」→ 选账号 → 左下「高级」→「前往项目（不安全）」→「允许」：



   | 顺序 | 函数 | 作用 |
   |---|---|---|
   | ① | `testConnections()` | 体检：数据源通不通、密钥有没有、还剩多少发信额度 |
   | ② | `listGeminiModels()` | 可选。列出你的密钥能用哪些模型；只有 AI 报错时才需要跑 |
   | ③ | `previewNow()` | 立刻发一封到邮箱，看实际效果 |
   | ④ | `installDailyTrigger()` | 装定时器：每天 08:30 自动跑 |



6. 点左侧**闹钟图标「触发器」**确认有一条：`dailyMain` / 时间驱动 / 每天 / 上午 8 点~9 点 / 已创建



### ⚠️ 密钥为什么不能写在代码里



这个仓库是**公开**的，`gas-national-team-daily.gs` 也在其中。Google 有自动化扫描器

盯着 GitHub 上的公开仓库，一旦扫到 `AIza` 开头的 Gemini 密钥，会直接把它**判定为泄露并永久作废**，

之后所有请求都返回 `403 Your API key was reported as leaked`。



所以脚本里 `CONFIG.GEMINI_API_KEY` 是空的，真实的密钥存在 Apps Script 的

「项目设置 → 脚本属性」里（`GEMINI_API_KEY` 这个键），运行时才读取。



**这一条对所有密钥都适用**：不要把任何 API key 提交进公开仓库，也不要把带密钥的文件

截图、粘贴到公开的地方。



### 密钥出问题怎么排查



跑 `listGeminiModels()`，日志会直接告诉你是哪一类：



| 日志里出现 | 含义 | 处理 |
|---|---|---|
| `reported as leaked` | 密钥已被判定泄露、永久作废 | 只能新建一把，`setGeminiKey()` 重新设置 |
| `API_KEY_SERVICE_BLOCKED` | 密钥设了 API 限制 | 控制台去掉限制，或新建 |
| `共 N 个模型` | 通了 | 末尾会打印推荐的 `GEMINI_MODELS` 行 |


### 会主动不发的情况



- **周末**：A 股不交易，直接跳过

- **数据日没推进**：交易所份额还没披露，数字和昨天一模一样，发第二遍没意义。

  连续 3 次没推进会改发一封「数据卡住了」的提醒，避免无声坏掉



想强制发一封，随时跑 `previewNow()`，它不看这两个条件。



### 常用开关（都在脚本顶部的 `CONFIG` 里）



| 字段 | 默认 | 说明 |
|---|---|---|
| `RECEIVER_EMAIL` | 已填 | 收件人，多个用英文逗号分隔 |
| `WITH_GEMINI` | `true` | 改 `false` 就不调大模型，直接用规则版总结（省配额、更快） |
| `SKIP_IF_UNCHANGED` | `true` | 改 `false` 数据没变也照发 |



其他工具函数：`removeTriggers()` 停发、`showHtml()` 只在日志里看邮件源码、`resetDedup()` 清掉去重记录。



> **AI 挂了不影响发信。** 邮件照发，「AI 总结」那一栏会自动降级成程序按固定规则拼的版本，

> 并在邮件里写明是哪个模型、报了什么错、怎么排查。降级版的结论来自同一批数字，只是措辞不如 AI 自然。



## 十三、给 AI 的维护提示词

> 这一章是写给「下一次接手这个仓库的 AI」的操作手册。人类读者可以跳过；但只要你的任务涉及改代码、
> 加 ETF、改调度、修数据，**请先读完 13.1～13.4 再动手**，13.5 是可整段复制给 AI 的提示词。

### 13.1 仓库速览：哪个能改、哪个碰了就坏事

| 文件 | 性质 | 说明 |
|---|---|---|
| `refresh.py` | **源码** | 抓份额 / 净值 / K 线 → 算净买卖 → 渲染整页 HTML。所有逻辑都在这里 |
| `gas-national-team-daily.gs` | **源码** | Google Apps Script 邮件脚本，每天早上读 `latest.json` 发一封解读邮件 |
| `_etf_shares_cache.json` | **数据资产，勿删** | 近 5 年份额历史 + 交易日历缓存（体积随数据增长），每次运行增量写回并提交 |
| `latest.json` / `llms.txt` / `snapshot.md` | 产物 | 给邮件脚本和大模型读的精简版，**不要手改**，要改内容去改 `make_summary.py` |
| `.nojekyll` | 必需的空文件 | 关闭 Jekyll，否则 `_etf_data.json` 这类下划线开头的文件不会被发布 |

### 13.2 数据链路与单位（错一个数量级会静默毁掉全部指标）

```
沪市份额  ── a-stock-api Worker /api/etf-shares?exchange=SH&date=…  (逐日，shares_10k = 万份 → ×10000)
深市份额  ── 仓库内直连 www.szse.cn/api/report/ShowReport 的 xlsx  (基金规模(份) 已是份 → 不许再乘)
单位净值  ── Worker /api/fund-nav?code=XXXXXX  (东财 pingzhongdata)
交易日历  ── Worker /api/trade-calendar
指数 K 线 ── 东财 push2his（主）/ 腾讯 web.ifzq.gtimg.cn（备）
沪市兜底  ── githubusercontent 上 wwww1998/national-team-etf-flow 的 _etf_shares_cache.json（仅失败时）
```

- 本仓库**只消费 Worker 的 HTTP 契约**，不消费 AKShare。上游同步、验证、部署看
  [`wj624/a-stock-api` 的 README](https://github.com/wj624/a-stock-api/blob/main/README.md)（内含可复制给 AI 的同步提示词与 Runbook）。
  只要三个端点的**字段名与单位不变**，本仓库一行都不用改。
- 依赖只有 `pandas requests openpyxl`。深交所 `SHOWTYPE=JSON` 返回 HTTP 500，**只有 xlsx 可用**，所以 `openpyxl` 不能删。

### 13.3 七个坑（按踩坑代价排序）

1. **东方财富快照会返回陈旧值，已彻底移除**（2026-11-02 真实事故）
   东财对 `510300` 返回 301.99 亿份的陈旧值（真值 414.01 亿份），报表由此算出 −88.70 亿份的**假减持**，
   与 `etf-lsi` 算出的 +25.34 亿份方向相反。份额**只能**来自交易所（Worker 代理上交所 / 深交所 xlsx），
   **不要**为了「多一路兜底」把东财快照加回来。
2. **镜像兜底有三道门槛，一道都不能松**
   取不到沪市时的兜底是同源仓库镜像（`wwww1998/national-team-etf-flow` 的 `_etf_shares_cache.json`），
   必须同时满足：① 日期**精确匹配**（绝不拿最近一天顶替）；② 镜像整行 ≥100 个代码（防镜像自己是半行）；
   ③ 本表 **15 只沪市标的全有正值**。任一不满足就**整段沪市一并丢弃**，报表停在上一完整交易日。
   **宁可少一天，绝不写半行或旧值。**
3. **Worker 返回 200 + 空数组 ≠ 当天没数据**
   Worker 会把上交所偶发失败包装成 `200 + data:[]`（并附 `upstream_error` 说明原因）。
   本仓库目前按「这天没份额」处理，会退化成镜像/旧值 —— **不产生假数据，但丢掉 T+0 精度**。
   要更稳就照 `wj624/etf-lsi` 的做法：**空表必须用直连 `query.sse.com.cn` 复核一次**再接。
4. **加一只 ETF 要同步改三处**
   `TARGETS`（代码 / 名称 / 市场）、`CAT_MAP`（归到哪个同类指数）、必要时 `CAT_INDEX`（该指数的 K 线源）。
   漏了 `CAT_MAP` 这只 ETF 就不进同类合计；漏了 `CAT_INDEX` 对应图表会没有 K 线。
   另外「15 只沪市标的全有正值」这条兜底门槛是**按当前列表算出来的**，加沪市标的时记得同步。
5. **构建顺序不能反**
   `refresh.py` 写出 `_etf_data.json` → `make_summary.py` 读它产出三份摘要 → `cp` 成 `index.html`。
   工作流里这三步是写死的顺序；本地手工跑也要按这个顺序，否则摘要会是上一次的旧数。
6. **`cron: "0 15 * * 1-5"` = 北京时间 23:00，`timeout-minutes: 25`**
   23:00 是因为份额要等交易所晚间披露；**万一 23:00 还没发，报表最新日会滞后一天，但不会丢历史**
   （增量窗口回溯最近 12 天，下一次运行自动补齐）。星期字段用 `1-5`，**禁止写 7**。
   超时 25 分钟是实测值（正常 7~10 分钟，数据滞后自检最多再等 150s × 2）+ 余量；超了说明是卡死而不是算得慢。
   数据没推进时 `refresh.py` 会沿用旧时间戳让输出字节不变，工作流 `git diff --cached --quiet` 后跳过提交，不产生冗余提交。
7. **提交阶段有 `git pull --rebase`**
   抓取耗时较长，期间若有人往 main 推过提交，直接 push 会被拒。rebase 失败就 `exit 1` 交给下一次调度，
   **不要**改成 `--force` 强推（会覆盖别人的提交）。

### 13.4 四类常见任务的 SOP

**A. 加 / 减一只 ETF**
改 `refresh.py` 的 `TARGETS` → 同步 `CAT_MAP` →（必要时）`CAT_INDEX` → 本地 `python refresh.py` →
检查 `_etf_data.json` 里新代码是否有逐日序列、`index.html` 对应图是否有数据 → 提交。
**不要**手工编辑 `_etf_shares_cache.json`：它由脚本增量维护，手改会在下一次写回时被覆盖或造成结构不一致。

**B. 改调度时间**
只改 `.github/workflows/daily-refresh.yml` 的 `cron`（UTC！北京时间 = UTC+8）。
改完在 Actions 里 `Run workflow` 手动验证一次。注意 `push` 到 `.github/workflows/daily-refresh.yml` 类文件不会自动触发（本仓库只配了 `schedule` + `workflow_dispatch`）。

**C. 改邮件（收件人 / 时间 / 是否调 AI）**
全在 `gas-national-team-daily.gs` 顶部的 `CONFIG`：`RECEIVER_EMAIL`、`TRIGGER_HOUR`/`TRIGGER_MINUTE`（默认 8:30）、
`WITH_GEMINI`、`WEEKDAYS_ONLY`、`SKIP_IF_UNCHANGED`、`DRY_RUN`。
**改完必须重新执行一次 `installDailyTrigger()`**，否则旧触发器还按老时间跑。
密钥（Gemini key 等）写在 Apps Script 的「脚本属性」里，**绝不写进代码**；仓库里也不存任何明文密钥。

**D. Action 红了怎么读**
① 「安装依赖」红 → 网络问题，重跑即可；
② `refresh.py` 红 → 往上翻日志找是哪个接口，`JSONDecodeError` 基本等于源站回空响应/HTML，不是格式问题；
③ 提交阶段红 → 大概率 rebase 冲突，看是不是有人同时改了 `index.html`（产物冲突直接以最新一次运行为准，重跑一次即可）；
④ 全绿但报表没更新 → 看日志里有没有「报表无变化, 跳过提交」，那是数据当天没推进，属正常。

### 13.5 可复制给 AI 的提示词

```text
【任务】维护 https://github.com/wj624/national-team-etf-flow（中央汇金/国家队核心宽基 ETF 每日净买入卖出报表）。

【先读什么】
1. README 第四章「数据来源」→ 认链路：份额只能来自交易所（Worker 代理上交所 / 深交所 xlsx），
   净值与交易日历走自建 Worker，指数 K 线走东财(主)/腾讯(备)。
2. README 第五章「脚本做了哪些防错校准」→ 5 条口径规则，禁止回退。
3. README 第六章「增量缓存机制」→ _etf_shares_cache.json 是数据资产，勿删勿手改。
4. README 第十三章（本章）→ 13.1 文件职责、13.3 七个坑、13.4 SOP。
5. 要动取数层时，再去读 https://github.com/wj624/a-stock-api 的 README（上游映射表 + 同步提示词）。

【硬约束，违反即算错】
- 份额数据只能来自交易所。东财快照 2026-11-02 曾对 510300 返回陈旧值（301.99 亿 vs 真值 414.01 亿），
  算出 −88.70 亿份假减持，该路径已彻底移除，不要为了"多一路兜底"加回来。
- 镜像兜底三道门槛（日期精确匹配 / 整行 ≥100 代码 / 15 只沪市全有正值）一道都不能松；
  任一不满足就整段沪市丢弃、报表停在上一完整交易日。绝不用最近一天顶替、绝不写半行。
- 单位：沪市 shares_10k 是万份 → ×10000；深市 xlsx 已是份 → 不许再乘。
- 加 ETF 必须同步改 TARGETS / CAT_MAP（必要时 CAT_INDEX）三处。
- 构建顺序固定：refresh.py(_etf_data.json) → make_summary.py(三份摘要) → cp 成 index.html。
- latest.json / llms.txt / snapshot.md / index.html 都是产物，不要手改，改 make_summary.py 或 refresh.py。
- echarts.min.js 是源文件不是垃圾，不要清理。
- cron 是 UTC，写 "0 15 * * 1-5"（北京 23:00），星期禁止写 7。
- 密钥只在 Apps Script 脚本属性 / 环境里，仓库不存任何明文；改完 CONFIG 要重跑 installDailyTrigger()。

【改完必须自检】
1. python refresh.py → 报表 HTML 生成，日志无 traceback；展示日 = 两市都有数据的最近共同交易日。
2. python make_summary.py --check → 三份摘要内容与报表一致（尤其最新日净买卖、同类合计）。
3. 检查 _etf_shares_cache.json：最新交易日整行存在、日期正确、无半行。
4. 抽查逻辑自洽：同类 ETF 净买卖方向不应与 _etf_data.json 里的份额差反向（折算日会被强制置 0，属正常）。
5. git status 里除 index.html / 三份摘要 / _etf_data.json / _etf_shares_cache.json 外，不应有其它改动；`refresh.py` 运行时还会额外生成 `国家队ETF每日净买入卖出报表.html` 与 `report_latest.html` 两个副本，它们由 `.gitignore` 忽略，不应出现在改动列表里。

【提交规范】
commit message 用中文，说明「改了什么 + 为什么」；动了口径或数据源要同步更新 README 第四 / 第五章。
```

### 13.6 动手前的三行自检

- 我改的这处，会不会让某只 ETF 的份额变成「旧值 / 半行 / 最近一天顶替」？三者都不允许。
- 加 ETF 时 `TARGETS` / `CAT_MAP` /（`CAT_INDEX`）是不是都改了？
- 这个文件是源码还是产物？产物只能靠重跑生成，不能手改。

---

## 免责声明



本报表仅用于数据观察与学习，**不构成任何投资建议**。

净买卖是份额口径的估算（日终数据），不是盘中实时资金流量，也无法区分具体申购主体。

---

## 附录 · 2026-11-05 全量整改记录（给维护者 / 给 AI 读）

> **这一节是什么**：AI 维护助手在 2026-11-05 对账号下 6 个仓库做完一次「大范围彻底修复」后追加的说明。目的只有一个——**让下一次维护（不管人或 AI）能看懂每个改动为什么做、哪些绝对不能回退**。
>
> **怎么读**：改任何代码之前，先读本 README 前文的「维护须知 / 铁律 / 给 AI 的维护提示词」，再读本附录。**两者冲突时以前文铁律为准**；本附录只解释本次改动，不新增、不覆盖任何设计口径。
>
> **本次原则**：用户要求「稳定、基本无维护、占用空间少、不自动生成垃圾」，并明确「修改前先看 README 的设计思路与维护须知」。因此本次只修**确定性 bug、静默失败、危险工作流行为、文档与代码不一致、依赖版本失控、运行时垃圾文件**；**没有做架构改造，没有删任何数据资产，没有改任何口径/阈值/单位/cron/构建顺序**。
>
> **本次改动范围**：6 仓共 40 个文件、0 删除；逐仓白名单精确提交，全程无 `--force`、无 rebase 冲突。**上线后的串行补测又追加了一次 pandas 3.x 兼容性修复（3 仓 6 文件，见 F 节），所以最终线上状态以 F 节为准，A 表里凡是写 `pandas<4` 的地方都已收紧为 `pandas<3`**。

### A. 本次改了什么（逐文件）

| 文件 | 原始缺陷（为什么必须改） | 本次修法 | 依据 / 约束 |
|---|---|---|---|
| `refresh.py`（2 处） | 页面「口径说明」仍写 AKShare / 天天基金旧描述，与「份额只能来自交易所」矛盾；ECharts 查找列表里残留**原作者 Windows 本机绝对路径** | 口径说明改「交易所官方披露（经自建 a-stock-api Worker 代理）」；查找列表只留仓库内 `echarts.min.js` 与 CDN 兜底 | 「`echarts.min.js` 是源文件不是垃圾，不要清理」；份额来源铁律 |
| `.github/workflows/daily-refresh.yml`（2 处） | `pip install pandas requests openpyxl` 无版本上界；无数据有效性守卫 | 改主版本上界 `pandas<3` / `numpy<3` / `requests<3` / `openpyxl<4`（pandas 由初次 `<4` 收紧，见 F 节）；插入守卫（只验存在 / 非空 / JSON 合法） | 构建顺序铁律；线上执行的是 workflow 的 pip install |
| `.github/workflows/monthly-snapshot.yml` | 每月自动 force 重写历史，会抹掉 `_etf_shares_cache.json` 的累积历史 | **停用 `schedule`**，保留 `workflow_dispatch`；guard 增加 `*.json` 合法性校验；回滚 SHA `retention-days` 90 → 365 | 不删文件、不改主体 |
| `.gitignore`（新建） | 运行时生成的中文名报表 HTML 与 `report_latest.html` 会留下未跟踪副本 | 新建：`__pycache__/`、`*.pyc`、`*.log`、`国家队ETF每日净买入卖出报表.html`、`report_latest.html` | 用户「不自动生成垃圾」；中文名 HTML 是**运行时副本**，随后 `cp` 成 `index.html`，不必进版本库 |
| `README.md` | 13 个 Markdown 表格缺表头下的分隔行（渲染错乱）；两个产物表缺行；工作流文件名写成 `daily.yml`（实际 `daily-refresh.yml`）；中文名 HTML 说明误导；过时字节数/文件数 | 补齐分隔行与产物表；订正文件名与说明；数字改定性；自检第 5 条补「两个运行时副本由 `.gitignore` 忽略」 | 十三、给 AI 的维护提示词（13.1 仓库速览 / 13.2 数据链路与单位） |

### B. 本次坚决没改（硬约束，改了就是破坏设计）

- **`_etf_shares_cache.json` 是数据资产，勿删勿手改**。
- **份额只能来自交易所，禁止恢复东财快照兜底**。
- **镜像兜底三道门槛未松**：日期精确匹配、整行 ≥100 代码、15 只沪市标的全有正值。
- **单位换算未改**：沪市 `shares_10k` 是万份需 `×10000`；深市 xlsx 已是份，**不许再乘**。
- **构建顺序固定**：`refresh.py → make_summary.py → cp` 成 `index.html`。
- **cron 仍是 UTC `"0 15 * * 1-5"`（北京 23:00），星期禁止写 7**；提交阶段保留 `git pull --rebase`，**禁止 `--force`**。
- **`echarts.min.js` 保留**（源文件，非垃圾）；**pandas 必须 `<3`**（F 节），改依赖 requirements 与 workflow 两处同步。

### C. 明令作废的旧建议（别再走回头路）

第一轮「只读体检报告」里提出过若干架构建议，**读完各仓 README 的维护须知后已全部作废**，本次一个都没采纳：

- ❌ **「产物不入库 / 数据与页面不进 git」**：本仓产物是 Pages / EdgeOne Pages / GAS 的**数据源本身**，从仓库检出，必须入库。
- ❌ **「删 `cache/` / 改回 `actions/cache`」**：`cache/` 是断网降级与历史累积的命根子。
- ❌ **「删数据资产 / 删摘要文件 / 清理 `echarts.min.js` / 删 `akshare` / 删 `westock-data`」**：均被 README 明确点名保护。
- ❌ **「把 `except: pass` 全改抛错」**：局部容错（TTL 状态、日志编码、临时文件清理、上游回退链）是设计，不是缺陷；本次只把**主流程**的静默失败改成显式失败。
- ❌ 早期报告曾把 GAS 脚本里的 `RECEIVER_EMAIL` 硬编码列为 bug —— **不是 bug**，它是 `CONFIG` 里明确列出的默认配置项，本次未改。

> 若下次 AI 读到 `wj624-仓库体检与整改思路.md` 或 `wj624-整改落地手册.md` 里的 P1/P2 建议，请以本附录为准：**那两份是整改前的中间产物，已作废**。


### D. 给 AI 的维护边界（可复制这段）

```
你在维护 wj624/national-team-etf-flow。动手前：
1. 先读 README 十三、给 AI 的维护提示词（13.2 单位换算错一个数量级会静默毁掉全部指标），再读本附录。
2. 绝对不要：删/手改 _etf_shares_cache.json；恢复东财快照兜底；放松镜像兜底三道门槛；
   改单位换算或构建顺序；把 cron 星期写成 7；用 --force 提交；清理 echarts.min.js。
3. 本附录 A 表已修的口径说明、Windows 绝对路径、依赖上界、表格渲染，别回退。
4. pandas 锁 <3，不要放宽到 <4 或去掉上界；改依赖必须 requirements.txt 与 daily-refresh.yml 两处同步（F 节）。
5. 改了数据源/口径/调度，同步 README 第四部分（数据来源）、第七部分（自动运行）、十三（提示词）。
6. 改完必须：按 refresh.py -> make_summary.py -> cp 顺序本地跑一遍，检查报表口径说明与份额单位；
   提交前确认中文名 HTML 与 report_latest.html 已被 .gitignore 忽略。
7. 线上写操作：精确 git add、中文 commit、git pull --rebase、绝不 force。
```
### E. 验证与回滚

| 项目 | 说明 |
|---|---|
| 本地验证 | 补丁脚本在从原仓库 `git archive HEAD` 导出的**干净副本**上端到端重跑：59/59 替换、2 处追加、2 个新建 `.gitignore`、5 个 `monthly-snapshot.yml` 降级；`.py` 用 `ast.parse`、`worker.js` 用 `node --check`、`.yml` 用 `yaml.safe_load`，语法自检 26 项全 PASS |
| README 硬约束复核 | 61 项，实际 61/61 通过（初检 5 项 FAIL 均为检查规则误报） |
| 线上内容核验 | GitHub API 独立核验：commit 主题、变更文件集合与白名单逐仓一致、**0 删除**、关键修复内容、数据资产 12/12 在线 |
| 线上实测 | 2026-11-05 串行手动触发 4 个核心 workflow 并逐个核验：4/4 全部 success、每仓产物 commit 均 removed=0、关键数据资产完好。第一次补测在 rotation-monitor 暴露 pandas 3.x 移除 resample('M') 的问题，双保险修复后重跑通过。明细与最终线上 HEAD 见下方「F. 补测实测记录」 |
| 令牌 / 垃圾 | 交付文件 `ghp_` / `github_pat_` 0 命中；仓库内不生成 `__pycache__` |

**回滚**：优先 `git revert <整改 commit>` 生成反向 commit 再 push（保留历史、无需 force）。整改前基线 `3cf2fdc4`，整改 commit `016a401a`（`git revert 016a401a`）；pandas 3.x 二次修复 commit `b0ef1c6c`（见 F 节，一并保留）。本次整改 commit 触发的是 `pages build and deployment`（**仅 Pages 部署 success**）。**已于 2026-11-05 串行补测手动 dispatch 实测通过**（run 41990810766，产物 commit `5110f0f1`，0 删除、3 项资产完好），见 F 节。

**下次改代码前的三行自检**（沿用前文铁律）：
1. 这个文件是源码还是产物？产物只能靠重跑生成，不能手改。
2. 改动会不会破坏「数据资产 / 口径 / 阈值 / 单位 / cron / 构建顺序」？会就停手。
3. 改完要跑什么验证、要同步 README 哪几节？写进 commit body。

### F. 补测实测记录（2026-11-05，含 pandas 3.x 兼容性二次修复）

整改 commit 上线后，用户要求对 4 个「`push` 不触发、只在 `schedule` / `workflow_dispatch` 跑」的核心抓数流水线做**串行手动触发补测**：一个跑完、核验通过，再触发下一个，避免并发写 `main` 冲突。

**第一次补测在 `rotation-monitor` 失败**，日志关键行：

```
ValueError: 'M' is no longer supported for offsets. Please use 'ME' instead.
  File ".github/workflows/generate_page.py", line 130, in ...
    monthly = bd.set_index('date')['close_cyb'].resample('M').last()
```

根因：pandas 3.1.1 于 2026-11-04 发布，移除了 `resample('M')` 别名，并默认开启 Copy-on-Write、改变字符串 dtype。**整改前依赖本无上界**；本轮整改把上界写成 `<4` 过宽，且 `daily_update.yml` 的 `pip install` 行仍是完全无上界 —— 这是策略失误，已按下面「双保险」纠正。

**双保险修复（3 仓 6 文件）**：

1. **代码**：`rotation-monitor/.github/workflows/generate_page.py` 的 `resample('M')` → `resample('ME')`（pandas 2.3.3 与 3.0.0 下语义一致，均为月末重采样，本地实测两种版本输出一致）。
2. **依赖**：所有 pandas 约束收紧为 `<3`，且 **`requirements.txt` 与 workflow 的 `pip install` 行两处同步** —— 线上实际执行的是 workflow 里的 pip install，不是 requirements.txt，只改一处等于没改。
3. **二次 commit**：`rotation-monitor` `ee80a439`、`earl-etf-dashboard` `af8b5237`、`national-team-etf-flow` `b0ef1c6c`。

**修复后重跑，4/4 全部通过**：

| 仓库 / workflow | run id | 结论 | 产物 commit（前 → 后） | 删除 | 关键资产 |
|---|---|---|---|---|---|
| `rotation-monitor` / `daily_update.yml` | 41990306988 | success | `ee80a439` → `1c6dd808` | 0 | `public/index.html` 完好 |
| `us-world-economy-dashboard` / `update.yml` | 41990418511 | success | `e9ee6da9` → `0b18f069` | 0 | `cache/` · `index.html` · `llms.txt` · `snapshot.md` · `version.txt` 完好 |
| `earl-etf-dashboard` / `update.yml` | 41990472730 | success | `af8b5237` → `abdee20d` | 0 | `cache/` · `version.txt` · `llms.txt` · `latest.json` · `index.html` 完好 |
| `national-team-etf-flow` / `daily-refresh.yml` | 41990810766 | success | `b0ef1c6c` → `5110f0f1` | 0 | `_etf_shares_cache.json` · `echarts.min.js` · `index.html` 完好 |

> `a-stock-api`（Worker 部署 + 13 个冒烟端点）与 `etf-lsi`（daily report）由 `push` 触发，整改当时即 `success`，不在上表。

**写本附录时各仓 `main` 的线上实况**（均为短 SHA，位数不影响定位）：

| 仓库 | 整改 commit | pandas 二次修复 | 补测产物 / 当前 HEAD |
|---|---|---|---|
| `a-stock-api` | `daea02a` | — | `daea02a` |
| `us-world-economy-dashboard` | `e9ee6da` | — | `0b18f06` |
| `earl-etf-dashboard` | `75255bd` | `af8b523` | `abdee20` |
| `national-team-etf-flow` | `016a401` | `b0ef1c6` | `5110f0f` |
| `rotation-monitor` | `b5f01af` | `ee80a43` | `1c6dd80` |
| `etf-lsi` | `606958f` | — | `8e8f74f`（自动产物 commit 会继续前移，属正常） |

> **给 AI 的硬约束**：这 3 个仓的 pandas **必须锁 `<3`**，不要「简化」成 `<4` 或去掉上界；`resample('ME')` 不要改回 `'M'`。改依赖时**必须同时改 `requirements.txt` 和 workflow 的 `pip install` 行** —— 第一次补测就是这样崩的。另外这 6 仓**没有单元测试套件**，上述「实测」指真实 workflow 执行 + 产物核验，改完代码仍应手动 dispatch 一次确认。

### G. 后续策略调整 · 按体积自动清理（2026-11-05 同日）

> **本仓情况**：本仓有 `monthly-snapshot.yml`，已按本节改制；`KEY_FILE` 为 `refresh.py`，不要改错。
>
> **优先级说明**：A / B / D 节记录的是当天**第一版**整改状态，原文保留不改以便追溯决策过程；关于「每月清理」的部分自本节起**以本节为准**：
> - A 表里的「停用 `schedule`」= 停用**旧版「每月 1 号无条件 force 重写 main」**的 schedule；
> - D 节「绝对不要恢复 monthly-snapshot 自动 schedule」= 不要恢复**上面那个旧版**；
> - 本节新增的「按体积体检 schedule」是**有意保留的新机制，不要删、不要改回每月无条件执行**。

#### 为什么要调整

用户指出：当初设计每月清理，是为了防止「每日产物入库」让仓库长期运行后体积膨胀。第一版整改只从「安全 / 可回滚」角度停用了 schedule，**没有回应「空间封顶」这个原始诉求**，等于把自动能力关掉了。实测后确认这个担心成立：

| 实测项 | 数值 |
|---|---|
| 6 仓当时合计体积 | 约 67 MB |
| 最大单个文件 | 4.4 MB（GitHub 单文件硬限 100 MB） |
| 仓库年龄 | 2~6 天（全部建于 2026-10-31 ~ 11-04） |
| 稳定后估算增长 | 约 1~2 MB/天（前几天叠加了整改提交，偏高） |
| 放着不管碰线时间 | 大半年 ~ 2 年到 1 GB 建议线 |
| GitHub 官方口径 | 理想 < 1 GB、强烈建议 < 5 GB，**不是免费版封顶** |
| 6 仓可见性 | 全部 **public**，Actions 分钟数免费不限量 |

结论：不会立刻被封，但会变慢、可能收到 GitHub 提醒邮件，所以「自动封顶」确实需要保留——只是不能再用「每月无条件强推」这种不可回滚的方式。

#### 改成什么

`.github/workflows/monthly-snapshot.yml`：

- `on.schedule` 改为**每周一 UTC 03:00（北京 11:00）只做一次「体积体检」**：读一次仓库 `size`，**低于 500 MB 就直接结束，一个字节都不改、绝不碰 `main` 历史**。
- 仅当 `size >= 500 MB（512000 KB）` 时才执行剪断。按 67 MB 起步、1~2 MB/天估算，约 8 个月~1 年才第一次真正动刀；清完回到约 10 MB 再重新累积，永远远低于 1 GB。
- `workflow_dispatch` 保留，新增 `force` 布尔输入（**默认 false**）：手动触发默认「只体检、不改动」，勾选 `force` 才忽略阈值立即清理。
- 原有护栏**全部保留**：`README.md` / `KEY_FILE` 存在、`git ls-files >= 8`、JSON 合法性校验、root commit 用 Git Data API（`parents: []`）、不走 `git push --force`、不触发 push 工作流、旧 HEAD 记入 artifact `retention-days: 365`、回滚命令写进日志、`concurrency` 互斥。
- **针对「按体积触发」新增一道护栏**：所有被跟踪文件必须 < 50 MB。体积突然暴涨通常是误提交大文件，绝不能把这种异常树固化成「唯一的 root commit」。
- guard 的 JSON 校验从「只查根目录 `*.json`」扩展到「`git ls-files -z '*.json'` 的全部被跟踪 JSON」。
- 体积读取优先 `gh api repos/... --jq .size`，失败回落 `github.event.repository.size`；两者都取不到时**安全跳过、不清理**。

#### 给 AI 的维护边界（追加，不替代 D 节）

1. **不要**把 `on.schedule` 改回「每月 1 号无条件执行」，不要删掉体积判断或改掉 `THRESHOLD_KB`。
2. **不要**把 `force` 默认值改成 `true`，不要去掉手动入口「默认只体检」的语义。
3. **不要**删掉 50 MB 单文件护栏或全量 JSON 校验；它们是「按体积自动」特有的防误固化措施。
4. 想立刻清理：Actions 页手动 dispatch 并**勾选 force**；只想体检：直接 dispatch 不勾选。
5. 清理后 `main` 变成 root commit，**外部克隆 / fork 需要重新 clone**；回滚命令在 run 日志与 artifact 里，保留 365 天。
6. 阈值 500 MB 可调，但**不要调到 1 GB 以上**（失去提前封顶意义），也**不要调到 100 MB 以下**（频繁剪历史）。
7. 判断是否需要清理看的是仓库 `size`（`gh api repos/<owner>/<repo> --jq .size`，单位 KB），不是文件个数或提交数。
8. 线上写操作照旧：精确 `git add`、中文 commit、`git pull --rebase`、**绝不 force**。

#### 验证与回滚

- 验证：改完用 `yaml.safe_load` 校验；在 Actions 手动 dispatch（**不勾选 force**）应看到 `below threshold: nothing to do, main history untouched`，且 `main` HEAD 不变、工作区无改动。
- 回滚本策略：`git revert <本策略 commit>` 即可回到「仅手动入口」的第一版状态；数据资产与其它 workflow 均不受影响。
