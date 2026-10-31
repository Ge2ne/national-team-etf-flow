/**
 * ============================================================================
 *  国家队宽基 ETF 流向 · 每日自动解读邮件
 *  数据源：https://wj624.github.io/national-team-etf-flow/
 *  运行环境：Google Apps Script（script.google.com）
 *  项目名建议：五、 国家队ETF流向
 *
 *  ★ 本文件只做「读取 + 解读 + 发信」，不连接券商、不下单、不构成投资建议。
 * ============================================================================
 *
 *  【第一次使用，按顺序做这 4 步】
 *
 *  1. 打开 https://script.google.com/home → 左上「新项目」
 *     项目名改成「五、 国家队ETF流向」
 *  2. 把本文件全部内容粘进编辑器，覆盖掉原来的空 myFunction，Ctrl+S 保存
 *  3. 依次运行下面 3 个函数（第一次会弹授权，全部点「允许」）：
 *       ① testConnections()      —— 测数据源和 AI 通不通，看下方「执行记录」
 *       ② previewNow()           —— 立刻发一封到你的邮箱，先看效果
 *       ③ installDailyTrigger()  —— 装上「每天 08:30（北京）」的定时器
 *  4. 完成。之后工作日早上 08:30 自动收到邮件；想停就运行 removeTriggers()
 *
 *  【时间怎么安排的】
 *  报表每天 23:00（北京，周一至周五）由 GitHub Actions 自动刷新，
 *  所以第二天早上 08:30 发的，就是「昨天收盘后算出来的那份」。
 *  周六、周日不交易，脚本内部会自动跳过，不会打扰你。
 *
 *  【为什么 08:30，不是 09:00】
 *  A 股 09:15 开始集合竞价，08:30 发出你还来得及看完再决定今天怎么做，
 *  同时避开了 GitHub 定时任务偶尔 10~30 分钟的排队延迟（23:00 刷新到 08:30 有 9 个半小时缓冲）。
 *
 *  【为什么有时早上没收到邮件】
 *  两种情况会主动不发：
 *    ① 周末（自动跳过）
 *    ② 数据日没推进（比如交易所份额还没披露，数字和昨天一模一样）——
 *       同样的数字发第二遍没有意义。连续 3 次没推进时会改发一封「数据卡住了」的提醒。
 *  想要强制发一封，运行 previewNow() 即可，它不看这两个条件。
 *
 *  【出问题先看哪里】
 *  左侧「执行记录 / Executions」→ 点开最近一次 → 看「日志」，每一步都打了日志。
 *  常见：Gemini 配额用完 → 邮件照发，「AI 总结」栏自动降级为规则版并写明原因；
 *        数据未更新 → 邮件顶部有黄色横幅提示。
 */

// ============================================================
// 1. 配置区（只改这里就够了）
// ============================================================
var CONFIG = {
  // —— 数据源 ——
  URL_JSON: 'https://wj624.github.io/national-team-etf-flow/latest.json', // 精简结论数，9.5KB
  URL_TEXT: 'https://wj624.github.io/national-team-etf-flow/llms.txt',    // 人话版摘要，8.3KB
  URL_SITE: 'https://wj624.github.io/national-team-etf-flow/',

  // —— 密钥 ——
  GEMINI_API_KEY: 'AIzaSyByI8CxUl-oLHuEaKs-30xORMw3VQmvRnE',

  // —— 收件人（多个用英文逗号分隔）——
  RECEIVER_EMAIL: '332515070@qq.com',

  // —— Gemini 模型：按顺序尝试，第一个成功即用 ——
  GEMINI_MODELS: ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash'],

  // —— 时区与定时 ——
  TIMEZONE: 'Asia/Shanghai',
  TRIGGER_HOUR: 8,
  TRIGGER_MINUTE: 30,

  // —— 行为开关 ——
  WEEKDAYS_ONLY: true,      // true = 周六周日不发送
  SKIP_IF_UNCHANGED: true,  // true = 数据日与上次成功发送相同则跳过（避免重复）
  WITH_GEMINI: true,        // false = 不调 AI，直接用规则版总结
  DRY_RUN: false            // true = 只打印 HTML 不发信
};

// 脚本属性里存「上次成功发送的数据日」，用于去重
var PROP_ASOF = 'LAST_ASOF';
var PROP_SAME = 'SAME_COUNT';
var PROP_SENT = 'LAST_SENT_AT';

// previewNow() 会临时置为 true，跳过周末与去重检查
var FORCE_ = false;

// ============================================================
// 2. 名词白话解释（邮件「名词速查」用）
// ============================================================
var GLOSSARY = [
  ['净买卖（亿元）', '把 23 只 ETF 当天份额的增减，乘上当天净值折算成钱。正数 = 资金净申购进场（红色），负数 = 净赎回离场（绿色）。'],
  ['倍量份额', '当天净申购的份额，相当于该 ETF 自身规模的百分之几。用来横向比较大小盘 ETF 的「用力程度」。基准日固定为 2025-12-31，之后份额变化大的品种（如创业板 ETF）会被放大，看趋势可以，不宜跨品种硬比。'],
  ['历史分位', '今天的数字在过去 1262 个交易日里排第几。90% 表示只有 10% 的日子比今天更极端。'],
  ['越跌越买', '指数当天下跌，ETF 却被净申购。这是最典型的托底形态。反过来「上涨也在买」更接近追涨。'],
  ['持仓市值', '这 23 只 ETF 的份额 × 净值加总，可以近似看作「这批钱的体量」。它变小主要是净值下跌 + 赎回共同造成的，不全是钱跑了。'],
  ['数据日', '上交所与深交所的份额披露节奏不同、且都有 1~2 天滞后，本页取两地都有数据的最近共同交易日。']
];

// ============================================================
// 3. 主入口
// ============================================================
function dailyMain() {
  var t0 = new Date();
  log_('=== 开始 ' + fmt_(t0) + ' ===');

  // ---- 3.1 周末跳过 ----
  if (!FORCE_ && CONFIG.WEEKDAYS_ONLY && isWeekend_()) {
    log_('今天是周末（' + weekdayCn_(t0) + '），按设置不发送。');
    return;
  }

  // ---- 3.2 取数据 ----
  var d = fetchJson_();
  var txt = fetchText_();
  if (!d && !txt) {
    sendError_('数据取不到', '请先确认这两个地址能打开：\n' + CONFIG.URL_JSON + '\n' + CONFIG.URL_TEXT +
               '\n\n如果浏览器能打开而脚本打不开，通常是网络临时故障，稍后手动跑一次即可。');
    return;
  }
  if (!d) {
    sendError_('latest.json 解析失败', '取到了内容但不是合法 JSON，可能仓库正在构建中。');
    return;
  }

  var asof = String(d.asof || '');
  var today = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  log_('数据日 ' + asof + '（' + (d.asof_weekday || '') + '），今天 ' + today);

  // ---- 3.3 去重：数据日没推进就不重复发 ----
  var props = PropertiesService.getScriptProperties();
  var lastAsof = props.getProperty(PROP_ASOF) || '';
  if (!FORCE_ && CONFIG.SKIP_IF_UNCHANGED && lastAsof && lastAsof === asof) {
    var same = Number(props.getProperty(PROP_SAME) || '0') + 1;
    props.setProperty(PROP_SAME, String(same));
    log_('数据日没有推进（仍是 ' + asof + '，第 ' + same + ' 次），跳过本次发信。');

    if (same === 3) {
      // 连续第 3 次没推进，改发一封提醒，避免"悄无声息地坏掉"
      sendStale_(asof, today);
    }
    return;
  }

  // ---- 3.4 数据新鲜度 ----
  var bundle = { json: d, text: txt || '', warn: [], ai: null, rule: null, lights: null };
  var lagDays = daysBetween_(asof, today);
  if (lagDays >= 4) {
    bundle.warn.push('数据日是 ' + asof + '，距今 ' + lagDays + ' 天。可能是长假期、也可能是交易所份额迟迟未披露。' +
                     '本封邮件里的所有数字都是 ' + asof + ' 那一天的情况，不是今天的。');
  }

  // ---- 3.5 算信号灯 + 规则版总结 ----
  bundle.lights = buildLights_(d);
  bundle.rule = buildRuleSummary_(d);

  // ---- 3.6 调 AI ----
  if (CONFIG.WITH_GEMINI) {
    log_('调用 Gemini…');
    bundle.ai = askGemini_(d, txt, asof, today);
    log_('Gemini 结果：' + (bundle.ai.ok ? '成功（' + bundle.ai.model + '，' + bundle.ai.lines.length + ' 行）'
                                        : '失败 → ' + bundle.ai.error));
  } else {
    bundle.ai = { ok: false, lines: null, model: '', error: 'CONFIG.WITH_GEMINI = false，已主动关闭 AI' };
  }

  // ---- 3.7 生成邮件 ----
  var html = buildHtml_(d, bundle);
  var subject = buildSubject_(d);
  log_('主题：' + subject);
  log_('HTML 长度 ' + html.length);

  if (CONFIG.DRY_RUN) {
    log_('DRY_RUN = true，只打印不发信');
    log_(html);
    return;
  }

  // ---- 3.8 发送 ----
  var plain = buildPlain_(d, bundle);
  MailApp.sendEmail({
    to: CONFIG.RECEIVER_EMAIL,
    subject: subject,
    htmlBody: html,
    body: plain,
    name: '国家队ETF流向'
  });

  // ---- 3.9 记录状态 ----
  props.setProperty(PROP_ASOF, asof);
  props.setProperty(PROP_SAME, '0');
  props.setProperty(PROP_SENT, fmt_(new Date()));
  log_('✅ 已发送至 ' + CONFIG.RECEIVER_EMAIL + '，用时 ' +
       Math.round((new Date() - t0) / 1000) + 's，今日剩余配额 ' + MailApp.getRemainingDailyQuota() + ' 封');
}

// ============================================================
// 4. 取数
// ============================================================
function fetchJson_() {
  try {
    var r = UrlFetchApp.fetch(CONFIG.URL_JSON + '?t=' + Date.now(), {
      muteHttpExceptions: true, followRedirects: true
    });
    if (r.getResponseCode() !== 200) {
      log_('latest.json HTTP ' + r.getResponseCode());
      return null;
    }
    var s = r.getContentText('UTF-8');
    log_('latest.json 取到 ' + s.length + ' 字符');
    return JSON.parse(s);
  } catch (e) {
    log_('latest.json 异常：' + e);
    return null;
  }
}

function fetchText_() {
  try {
    var r = UrlFetchApp.fetch(CONFIG.URL_TEXT + '?t=' + Date.now(), {
      muteHttpExceptions: true, followRedirects: true
    });
    if (r.getResponseCode() !== 200) {
      log_('llms.txt HTTP ' + r.getResponseCode());
      return '';
    }
    return r.getContentText('UTF-8');
  } catch (e) {
    log_('llms.txt 异常：' + e);
    return '';
  }
}

// ============================================================
// 5. 信号灯 + 规则版总结（不依赖任何外部服务）
// ============================================================

/** 四个维度的红绿灯：资金 / 结构 / 涨跌 / 风险 */
function buildLights_(d) {
  var T = d.today || {}, mv = d.mv || {}, win = d.windows || {};
  var L = {};

  // 资金：今天净买卖在历史里的分位
  var p = num_(T.pct, 50);
  L['资金'] = p >= 80 ? { dot: '🟢', text: '强力进场' }
            : p >= 50 ? { dot: '🟡', text: '中性偏强' }
            : p >= 20 ? { dot: '🟡', text: '中性偏弱' }
                      : { dot: '🔴', text: '明显离场' };

  // 结构：多少只 ETF 在买
  var tot = num_(T.buy_count, 0) + num_(T.sell_count, 0) + num_(T.flat_count, 0);
  var br = tot > 0 ? num_(T.buy_count, 0) / tot * 100 : 50;
  L['结构'] = br >= 70 ? { dot: '🟢', text: '普遍净申购' }
            : br >= 40 ? { dot: '🟡', text: '分化' }
                       : { dot: '🔴', text: '普遍净赎回' };

  // 涨跌：指数涨跌 × 资金方向
  var tag = String(T.tag || '');
  L['涨跌'] = tag === '越跌越买' ? { dot: '🟢', text: '逆势托底' }
            : tag === '下跌也在卖' ? { dot: '🔴', text: '没有托底' }
            : tag ? { dot: '🟡', text: '顺势而为' }
                  : { dot: '·',  text: '—' };

  // 风险：短期与长期方向是否打架 / 持仓市值是否在高位
  if (d.reversal) {
    L['风险'] = { dot: '🔴', text: '短期≠长期' };
  } else if (num_(mv.pct, 50) >= 85) {
    L['风险'] = { dot: '🔴', text: '持仓高位' };
  } else if (num_(win.d250, 0) < 0) {
    L['风险'] = { dot: '🟡', text: '一年仍在流出' };
  } else {
    L['风险'] = { dot: '🟢', text: '方向一致' };
  }

  return L;
}

/**
 * 规则版总结：完全用 latest.json 里已算好的数字拼 7 段话。
 * AI 不可用它兜底，保证邮件里永远有一份「人话总结」。
 */
function buildRuleSummary_(d) {
  var T = d.today || {}, W = d.windows || {}, mv = d.mv || {};
  var cats = d.cats || [], etfs = d.etfs || [];

  var net = num_(T.net, 0);
  var pct = num_(T.pct, 50);
  var tag = String(T.tag || '');
  var dirWord = net > 0 ? '净买入' : (net < 0 ? '净卖出' : '基本持平');

  // 结构：找出买得最多和卖得最多的类别
  var topBuy = null, topSell = null;
  for (var i = 0; i < cats.length; i++) {
    var cv = num_(cats[i].today, 0);
    if (cv > 0 && (!topBuy || cv > num_(topBuy.today, 0))) topBuy = cats[i];
    if (cv < 0 && (!topSell || cv < num_(topSell.today, 0))) topSell = cats[i];
  }
  var topEtf = etfs.length ? etfs[0] : null;

  var 总结 = '今天这 ' + num_(d.scope && d.scope.etfs, 0) + ' 只宽基 ETF 合计' + dirWord + ' ' +
    Math.abs(net).toFixed(1) + ' 亿元，在近 ' + num_(d.scope && d.scope.days, 0) + ' 个交易日里属于' +
    (pct >= 90 ? '非常靠前' : pct >= 70 ? '偏强' : pct >= 30 ? '中等' : '偏弱') +
    '的水平（历史分位 ' + pct.toFixed(1) + '%），' +
    (T.rank_text ? T.rank_text + '。' : '') +
    '当天中证全指' + (num_(T.idx_chg, 0) < 0 ? '下跌 ' : '上涨 ') + Math.abs(num_(T.idx_chg, 0)).toFixed(1) + '%，' +
    '资金却在' + (net > 0 ? '进' : '出') + '，属于「' + (tag || '信号不明') + '」。' +
    (topEtf ? '出钱最多的是 ' + topEtf.n + '（' + yi_(topEtf.today) + ' 亿元）。' : '') +
    '需要提醒的是：ETF 份额的申赎只是「资金动向」的公开代理口径，不等于国家队真实下单。';

  var 一句话;
  if (tag === '越跌越买' && net > 0) {
    一句话 = '指数在跌，但买盘在进 —— 典型的托底姿态，说明这批资金不打算在这个位置撤退。';
  } else if (tag === '顺势加仓' && net > 0) {
    一句话 = '指数在涨、资金也在进，偏向追涨，这种买法对后市的要求更高。';
  } else if (tag === '涨了就卖' && net < 0) {
    一句话 = '指数在涨、资金却在撤，更像趁反弹减仓，不是好信号。';
  } else if (tag === '下跌也在卖' && net < 0) {
    一句话 = '指数在跌、资金也在走，这个位置没看到托底意愿。';
  } else {
    一句话 = '今天资金' + dirWord + '，方向不算极端。单日数据噪音大，建议看近 5 日和 20 日累计。';
  }

  var 资金 = '今日 ' + yi_(net) + ' 亿元（历史分位 ' + pct.toFixed(1) + '%）；' +
    '近 5 日 ' + yi_(num_(W.d5, 0)) + '、近 20 日 ' + yi_(num_(W.d20, 0)) + '、近 250 日 ' +
    yi_(num_(W.d250, 0)) + ' 亿元。' +
    (num_(T.streak_days, 0) > 1
      ? '已连续 ' + num_(T.streak_days, 0) + ' 天' + (T.streak_dir === 'buy' ? '净买入' : '净卖出') +
        '，累计 ' + yi_(num_(T.streak_sum, 0)) + ' 亿元。'
      : '');

  var 结构 = num_(T.buy_count, 0) + ' 只净申购、' + num_(T.sell_count, 0) + ' 只净赎回、' +
    num_(T.flat_count, 0) + ' 只持平。' +
    (topBuy ? '买得最猛的是' + topBuy.name + '（' + yi_(topBuy.today) + ' 亿元，' + topBuy.n_etf + ' 只标的）' : '') +
    (topSell ? '；卖得最多的是' + topSell.name + '（' + yi_(topSell.today) + ' 亿元）' : '') + '。';

  var 涨跌 = '中证全指当日 ' + (num_(T.idx_chg, 0) >= 0 ? '+' : '') + num_(T.idx_chg, 0).toFixed(1) + '%，' +
    '同期 ETF ' + dirWord + ' ' + Math.abs(net).toFixed(1) + ' 亿元，判定为「' + (tag || '—') + '」。' +
    (d.diverge && num_(d.diverge.streak, 0) >= 2
      ? '已连续 ' + num_(d.diverge.streak, 0) + ' 个交易日出现「越跌越买」。'
      : '');

  var 风险;
  if (d.reversal) {
    风险 = d.reversal.text;
  } else if (num_(mv.pct, 50) >= 85) {
    风险 = '全表持仓市值 ' + plain_(num_(mv.now, 0), 1) + ' 亿元，处在历史 ' + num_(mv.pct, 0).toFixed(0) +
           '% 分位的高位。高位意味着后续即便继续买，边际推动力也会递减。';
  } else {
    风险 = '全表持仓市值 ' + plain_(num_(mv.now, 0), 1) + ' 亿元，历史分位 ' + num_(mv.pct, 0).toFixed(0) +
           '%，不算极端。主要风险在于单日数据噪音，以及 ETF 申赎并不等于国家队真实动作。';
  }

  var 建议 = '先看两组数：一是近 20 日与近 250 日的方向是否一致（' +
    (num_(W.d20, 0) > 0 && num_(W.d250, 0) < 0 ? '现在不一致，说明是回补而非新趋势' : '目前看方向关系正常') +
    '），二是' + (topBuy ? topBuy.name : '主力类别') + '的买入能否连续。' +
    '只有「连续多日同向 + 覆盖面扩大」才值得当作趋势信号，单日大额不追。';

  return {
    '总结': 总结,
    '一句话': 一句话,
    '资金': 资金,
    '结构': 结构,
    '涨跌': 涨跌,
    '风险': 风险,
    '建议': 建议
  };
}

// ============================================================
// 6. Gemini 解读
//    要求模型只输出 7 行「标签|内容」，便于稳定解析
// ============================================================
function askGemini_(d, txt, asof, today) {
  var T = d.today || {}, W = d.windows || {}, mv = d.mv || {};

  var factLine =
    '（以下是脚本已经算好的确定事实，可直接引用，不要改动数字）\n' +
    '- 数据日：' + asof + '（' + (d.asof_weekday || '') + '）\n' +
    '- 当日全表：' + yi_(num_(T.net, 0)) + ' 亿元，历史分位 ' + num_(T.pct, 0).toFixed(1) + '%，' +
      (T.rank_text || '') + '\n' +
    '- 买卖家数：买 ' + num_(T.buy_count, 0) + ' / 卖 ' + num_(T.sell_count, 0) + ' / 平 ' + num_(T.flat_count, 0) + '\n' +
    '- 连续同向：' + (num_(T.streak_days, 0) > 1
        ? num_(T.streak_days, 0) + ' 个交易日' + (T.streak_dir === 'buy' ? '净买入' : '净卖出') +
          '，累计 ' + yi_(num_(T.streak_sum, 0)) + ' 亿元'
        : '未形成连续') + '\n' +
    '- 窗口累计：5 日 ' + yi_(num_(W.d5, 0)) + ' / 20 日 ' + yi_(num_(W.d20, 0)) +
      ' / 60 日 ' + yi_(num_(W.d60, 0)) + ' / 250 日 ' + yi_(num_(W.d250, 0)) + ' 亿元\n' +
    '- 中证全指当日涨跌：' + num_(T.idx_chg, 0).toFixed(1) + '%，判定「' + (T.tag || '—') + '」\n' +
    '- 持仓市值：' + plain_(num_(mv.now, 0), 1) + ' 亿元，历史分位 ' + num_(mv.pct, 0).toFixed(1) + '%，' +
      '近一年最高 ' + plain_(num_(mv.hi, 0), 1) + '（' + (mv.hi_date || '') + '），最低 ' +
      plain_(num_(mv.lo, 0), 1) + '（' + (mv.lo_date || '') + '）\n' +
    (d.reversal ? '- ⚠️ 短期与长期方向相反：' + d.reversal.text + '\n' : '- 短期与长期方向一致，无反转警示\n');

  var prompt =
    '你正在给一个刚开始关注 A 股资金面的普通投资者写每日解读。\n' +
    '下面是一个「国家队宽基 ETF 净申购/净赎回」看板今天的全部数据。请据此写出今天的解读。\n\n' +
    '严格遵守：\n' +
    '1. 只能使用数据里出现的事实。绝对不要编造任何数字、政策、新闻、机构动作或历史事件。\n' +
    '2. 用大白话。必须用术语时，紧跟括号用一句白话解释。\n' +
    '3. 「总结」不超过 200 个汉字；其余每行不超过 70 个汉字。\n' +
    '4. 只输出下面 7 行，格式严格为「标签|内容」。不要标题、不要 Markdown、不要代码块、不要多余解释、每行内不许换行。\n' +
    '5. 「建议」只能写观察动作（盯哪个数、满足什么条件才值得行动），禁止出现买入/卖出/加仓/清仓这类直接指令。\n' +
    '6. 必须点明一个关键口径：ETF 被净申购只是「资金动向」的公开代理指标，不等于国家队真的在下单；份额披露还有 1~2 天滞后。\n' +
    '7. 如果短期（近 20 日）与长期（近 250 日）方向相反，必须在「风险」里明确说出「这是回补，不是趋势反转」。\n' +
    '8. 「总结」要像跟朋友讲话：先说结论（今天这批钱是在进还是在退、姿态是托底还是追涨），再用两个数字支撑，最后说最大的风险。不要罗列指标名。\n\n' +
    '需要输出的 7 行（标签必须一模一样）：\n' +
    '总结|（200 字内的一段话，可带标点，不许换行）\n' +
    '一句话|（对完全不懂的人：今天这批钱什么姿态，说明什么）\n' +
    '资金|（进了还是出了多少钱，在历史上算大还是算小）\n' +
    '结构|（哪些指数在买、哪些在卖，是普遍还是个例）\n' +
    '涨跌|（指数涨跌和资金方向配起来看，是托底还是追涨）\n' +
    '风险|（最该防的是什么，最该盯哪个数）\n' +
    '建议|（如果只看一件事，看什么）\n\n' +
    factLine + '\n' +
    '数据生成时间：' + (d.generated || '') + '，今天：' + today + '\n\n' +
    '完整数据如下：\n' + (txt || '（本次未取到 llms.txt，仅凭上面的确定事实判断）');

  var errs = [];
  for (var i = 0; i < CONFIG.GEMINI_MODELS.length; i++) {
    var model = CONFIG.GEMINI_MODELS[i];
    try {
      var url = 'https://generativelanguage.googleapis.com/v1beta/models/' +
                model + ':generateContent?key=' + CONFIG.GEMINI_API_KEY;
      var payload = {
        contents: [{ parts: [{ text: prompt }] }],
        // maxOutputTokens 给大一些：2.5 系列模型的「思考」也计入输出额度，
        // 给小了会出现正文被截断、只剩思考片段的情况。
        generationConfig: { temperature: 0.35, maxOutputTokens: 4000, topP: 0.9 }
      };
      var r = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      });
      var code = r.getResponseCode();
      if (code !== 200) {
        var msg = r.getContentText('UTF-8');
        var hint = geminiHint_(code, msg);
        errs.push(model + ' → HTTP ' + code + (hint ? '，' + hint : ''));
        log_('Gemini ' + model + ' HTTP ' + code + '：' + msg.substring(0, 260));
        continue;
      }
      var body = JSON.parse(r.getContentText('UTF-8'));
      var text = extractGeminiText_(body);
      if (!text) {
        errs.push(model + ' → 返回空内容（finishReason=' +
                  (((body.candidates || [])[0] || {}).finishReason || '无') + '）');
        continue;
      }
      var parsed = parseGeminiLines_(text);
      if (!parsed) {
        errs.push(model + ' → 输出格式不符（未解析出标签行）');
        log_('Gemini ' + model + ' 输出不符合格式，原文：' + text.substring(0, 300));
        continue;
      }
      log_('Gemini ' + model + ' OK，解析到 ' + parsed.length + ' 行');
      return { ok: true, lines: parsed, model: model, error: '' };
    } catch (e) {
      errs.push(model + ' → ' + String(e).substring(0, 120));
      log_('Gemini ' + model + ' 异常：' + e);
    }
  }
  return { ok: false, lines: null, model: '', error: errs.join('；') };
}

/** 把常见的 HTTP 错误翻译成一句人话，直接写进邮件里方便排查 */
function geminiHint_(code, msg) {
  var m = String(msg || '');
  if (code === 400 && /API key not valid/i.test(m)) return '密钥无效，请去 AI Studio 重新复制';
  if (code === 400) return '请求参数被拒，多半是模型名不对';
  if (code === 403) return '该密钥无权访问此模型，或未在项目里启用 Generative Language API';
  if (code === 404) return '这个模型在你的账号下不存在，换 GEMINI_MODELS 里的其他名字';
  if (code === 429) return '超出免费配额（每分钟或每天），明天会恢复';
  if (code === 500 || code === 503) return 'Google 侧临时故障，稍后自动重试即可';
  return '';
}

function extractGeminiText_(body) {
  try {
    var c = body.candidates || [];
    for (var i = 0; i < c.length; i++) {
      var parts = (c[i].content && c[i].content.parts) || [];
      var s = '';
      for (var j = 0; j < parts.length; j++) {
        // 跳过「思考」片段：2.5 系列会把推理过程作为 part 返回，带 thought:true，
        // 拼进来会污染「标签|内容」的解析。
        if (parts[j].thought === true) continue;
        if (parts[j].text) s += parts[j].text;
      }
      if (s.trim()) return s.trim();
    }
    if (body.promptFeedback) log_('Gemini 无内容，promptFeedback=' + JSON.stringify(body.promptFeedback));
    var fr = (c[0] && c[0].finishReason) || '';
    if (fr) log_('Gemini finishReason=' + fr + (fr === 'MAX_TOKENS' ? '（输出被截断，可加大 maxOutputTokens）' : ''));
  } catch (e) {}
  return '';
}

function parseGeminiLines_(text) {
  var want = ['总结', '一句话', '资金', '结构', '涨跌', '风险', '建议'];
  var map = {};
  var lines = text.split('\n');
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i].replace(/^[\s>*\-•\d.、]+/, '').replace(/\*\*/g, '').replace(/`/g, '').trim();
    var p = ln.indexOf('|');
    if (p < 0) p = ln.indexOf('｜');
    if (p < 0) continue;
    var k = ln.substring(0, p).replace(/[【】\[\]:：]/g, '').trim();
    var v = ln.substring(p + 1).trim();
    if (want.indexOf(k) >= 0 && v) map[k] = v;
  }
  var out = [];
  for (var i2 = 0; i2 < want.length; i2++) {
    if (map[want[i2]]) out.push({ label: want[i2], text: map[want[i2]] });
  }
  return out.length >= 4 ? out : null;   // 至少解析出 4 行才算成功
}

// ============================================================
// 7. 邮件主题
// ============================================================
function buildSubject_(d) {
  var T = d.today || {};
  var net = num_(T.net, 0);
  var parts = [];

  parts.push('【国家队ETF】' + yi_(net) + '亿');
  if (T.tag) parts.push(String(T.tag));
  if (num_(T.streak_days, 0) > 1) {
    parts.push('连' + (T.streak_dir === 'buy' ? '买' : '卖') + num_(T.streak_days, 0) + '天');
  }
  return parts.join(' · ') + ' (' + (d.asof || '') + ')';
}

// ============================================================
// 8. 生成 HTML 邮件
// ============================================================
function buildHtml_(d, bundle) {
  var T = d.today || {}, W = d.windows || {}, mv = d.mv || {};
  var scope = d.scope || {};
  var genAt = fmt_(new Date());
  var C = {
    bg: '#f5f6f8', card: '#ffffff', line: '#e5e7eb', line2: '#f3f4f6',
    tx: '#1f2328', tx2: '#5b6472', tx3: '#8b95a3',
    up: '#d13a34', down: '#0f9960', blue: '#2563eb', org: '#ea8b1f',
    pur: '#7c3aed', slate: '#1e293b'
  };

  var h = [];
  h.push('<div style="margin:0;padding:0;background:' + C.bg + ';">');
  h.push('<div style="max-width:680px;margin:0 auto;padding:0 12px 28px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Microsoft YaHei\',sans-serif;font-size:14px;line-height:1.65;color:' + C.tx + ';">');

  // ---------- 页头 ----------
  h.push('<div style="background:' + C.slate + ';color:#fff;padding:18px 20px;border-radius:0 0 10px 10px;">');
  h.push('<div style="font-size:18px;font-weight:700;letter-spacing:.3px;">国家队宽基 ETF · 每日流向</div>');
  h.push('<div style="font-size:12px;color:#c7d0da;margin-top:5px;">数据日 ' + esc_(d.asof || '—') +
         '（' + esc_(d.asof_weekday || '') + '）　·　' + num_(scope.etfs, 0) + ' 只 ETF / ' +
         num_(scope.cats, 0) + ' 个指数类别　·　本邮件 ' + esc_(genAt) + ' 生成</div>');
  h.push('</div>');

  // ---------- 警告条 ----------
  if (bundle.warn && bundle.warn.length) {
    h.push('<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;margin-top:12px;font-size:12.5px;color:#92400e;line-height:1.7;">');
    for (var w = 0; w < bundle.warn.length; w++) {
      h.push('<div>⚠️ ' + esc_(bundle.warn[w]) + '</div>');
    }
    h.push('</div>');
  }

  // ---------- ① AI 总结（固定第一栏）----------
  h.push(aiSummaryHtml_(d, bundle, C));

  // ---------- ② 今日总览 ----------
  h.push(sectionOpen_(C, '① 今日总览', '一个数字 + 四个注脚，先搞清楚今天发生了什么。'));

  var netColor = T.net > 0 ? C.up : (T.net < 0 ? C.down : C.tx2);
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>');

  // 左：大数字
  h.push('<td width="46%" valign="middle" style="padding:4px 10px 4px 0;text-align:center;border-right:1px solid ' + C.line + ';">');
  h.push('<div style="font-size:13px;color:' + C.tx3 + ';">全表净买卖</div>');
  h.push('<div style="font-size:38px;font-weight:800;line-height:1.15;color:' + netColor + ';letter-spacing:-.5px;">' +
         esc_(yi_(num_(T.net, 0))) + '</div>');
  h.push('<div style="font-size:12px;color:' + C.tx3 + ';margin-top:-2px;">亿元</div>');
  if (T.tag) {
    var tagStyle = tagStyle_(String(T.tag));
    h.push('<div style="display:inline-block;margin-top:8px;background:' + tagStyle.bg + ';color:' + tagStyle.fg +
           ';font-size:13px;font-weight:700;padding:3px 14px;border-radius:12px;">' + esc_(T.tag) + '</div>');
  }
  h.push('</td>');

  // 右：四个注脚
  h.push('<td width="54%" valign="middle" style="padding:4px 0 4px 12px;">');
  h.push(kv_('买入 / 卖出 / 持平',
    num_(T.buy_count, 0) + ' / ' + num_(T.sell_count, 0) + ' / ' + num_(T.flat_count, 0), C));
  h.push(kv_('历史分位（近 ' + num_(scope.days, 0) + ' 日）',
    num_(T.pct, 0).toFixed(1) + '%', C));
  h.push(kv_('连续同向',
    num_(T.streak_days, 0) > 1
      ? (T.streak_dir === 'buy' ? '连买 ' : '连卖 ') + num_(T.streak_days, 0) + ' 天（' + yi_(num_(T.streak_sum, 0)) + ' 亿）'
      : '未形成', C));
  h.push(kv_('中证全指当日',
    (num_(T.idx_chg, 0) >= 0 ? '+' : '') + num_(T.idx_chg, 0).toFixed(1) + '%', C,
    num_(T.idx_chg, 0) >= 0 ? C.up : C.down));
  h.push('</td></tr></table>');

  // 排名文字
  if (T.rank_text) {
    h.push('<div style="margin-top:12px;padding:9px 12px;background:#f8fafc;border-radius:7px;font-size:12.5px;color:' + C.tx2 + ';">' +
           '📌 ' + esc_(T.rank_text) + '</div>');
  }
  h.push('</div>');

  // ---------- ③ 时间窗口 ----------
  h.push(sectionOpen_(C, '② 不同时间长度看，方向可能不一样',
    '单日数据噪音大。四个窗口并排看，才知道这只是「一天的波动」还是「一段的趋势」。'));
  h.push(winRow_(W, C));
  h.push('<div style="margin-top:6px;">');
  h.push(sparkBars_(d.recent || [], C));
  h.push('</div>');
  h.push('<div style="font-size:11.5px;color:' + C.tx3 + ';margin-top:6px;text-align:center;">' +
         '最近 ' + (d.recent || []).length + ' 个交易日的每日净买卖（红 = 买入，绿 = 卖出，柱高与金额成比例）</div>');
  h.push('</div>');

  // ---------- ④ 反转警示 ----------
  if (d.reversal) {
    h.push('<div style="background:#fef2f2;border:1px solid #fecaca;border-left:4px solid ' + C.up +
           ';border-radius:10px;padding:15px 16px;margin-top:12px;">');
    h.push('<div style="font-size:15px;font-weight:700;color:#991b1b;">⚠️ 短期与一年维度方向相反</div>');
    h.push('<div style="font-size:13px;color:#7f1d1d;line-height:1.85;margin-top:7px;">' + esc_(d.reversal.text) + '</div>');
    h.push('<div style="font-size:11.5px;color:#b45309;margin-top:8px;line-height:1.7;">' +
           '碰到这种情况，「近 20 日在买」不能直接外推成「趋势要来了」。真正的趋势反转，需要看到长期窗口（250 日）由负转正。</div>');
    h.push('</div>');
  }

  // ---------- ⑤ 持仓市值 ----------
  h.push(sectionOpen_(C, '③ 这批钱的体量',
    '份额 × 净值加总。它变小，通常是净值下跌 + 赎回一起造成的，不全是「钱跑了」。'));
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>');
  h.push('<td width="50%" valign="middle" style="padding:2px 10px 2px 0;text-align:center;border-right:1px solid ' + C.line + ';">');
  h.push('<div style="font-size:30px;font-weight:800;color:' + C.tx + ';line-height:1.2;">' +
         esc_(plain_(num_(mv.now, 0), 1)) + '</div>');
  h.push('<div style="font-size:12px;color:' + C.tx3 + ';">亿元　当前持仓市值</div>');
  h.push('<div style="font-size:11.5px;color:' + C.tx3 + ';margin-top:4px;">较前一日 ' +
         esc_(yi_(num_(mv.chg_1d, 0), 2)) + '%</div>');
  h.push('</td>');
  h.push('<td width="50%" valign="middle" style="padding:2px 0 2px 12px;font-size:12.5px;color:' + C.tx2 + ';">');
  h.push('<div style="margin-bottom:5px;">历史分位　<span style="font-weight:700;color:' + C.tx + ';">' +
         num_(mv.pct, 0).toFixed(1) + '%</span></div>');
  h.push('<div style="margin-bottom:5px;">近一年最高　<span style="font-weight:700;color:' + C.up + ';">' +
         esc_(plain_(num_(mv.hi, 0), 1)) + '</span><br><span style="font-size:11px;color:' + C.tx3 + ';">' +
         esc_(mv.hi_date || '') + '</span></div>');
  h.push('<div>近一年最低　<span style="font-weight:700;color:' + C.down + ';">' +
         esc_(plain_(num_(mv.lo, 0), 1)) + '</span><br><span style="font-size:11px;color:' + C.tx3 + ';">' +
         esc_(mv.lo_date || '') + '</span></div>');
  h.push('</td></tr></table>');
  h.push('</div>');

  // ---------- ⑥ 指数涨跌 × 资金流向 ----------
  var rows = (d.diverge && d.diverge.rows) || [];
  h.push(sectionOpen_(C, '④ 指数涨跌 × 资金流向（最近 ' + rows.length + ' 个交易日）',
    '整封邮件最该看的地方：同样在净买入，「跌的时候买」是托底，「涨的时候买」是追涨，含义完全不同。'));

  if (rows.length) {
    h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-size:12.5px;">');
    h.push('<tr style="background:#f8fafc;">');
    h.push('<th width="22%" align="left"  style="padding:7px 6px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">日期</th>');
    h.push('<th width="22%" align="right" style="padding:7px 6px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">中证全指</th>');
    h.push('<th width="26%" align="right" style="padding:7px 6px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">净买卖(亿)</th>');
    h.push('<th width="30%" align="right" style="padding:7px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">判断</th>');
    h.push('</tr>');
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var isLast = (i === rows.length - 1);
      var bg = isLast ? '#f0f9ff' : '#ffffff';
      var ts = tagStyle_(String(r.tag || ''));
      h.push('<tr style="background:' + bg + ';">');
      h.push('<td style="padding:7px 6px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx2 + ';white-space:nowrap;">' +
             esc_(String(r.d || '').substring(5)) +
             (isLast ? ' <span style="color:' + C.blue + ';font-size:10.5px;">最新</span>' : '') + '</td>');
      h.push('<td align="right" style="padding:7px 6px;border-bottom:1px solid ' + C.line2 + ';color:' +
             (num_(r.idx, 0) >= 0 ? C.up : C.down) + ';font-weight:600;white-space:nowrap;">' +
             (num_(r.idx, 0) >= 0 ? '+' : '') + num_(r.idx, 0).toFixed(1) + '%</td>');
      h.push('<td align="right" style="padding:7px 6px;border-bottom:1px solid ' + C.line2 + ';color:' +
             (num_(r.net, 0) >= 0 ? C.up : C.down) + ';font-weight:700;white-space:nowrap;">' + esc_(yi_(num_(r.net, 0))) + '</td>');
      h.push('<td align="right" style="padding:7px 4px;border-bottom:1px solid ' + C.line2 + ';">' +
             '<span style="display:inline-block;background:' + ts.bg + ';color:' + ts.fg +
             ';font-size:11px;font-weight:700;padding:2px 7px;border-radius:9px;white-space:nowrap;">' +
             esc_(r.tag || '—') + '</span></td>');
      h.push('</tr>');
    }
    h.push('</table>');

    if (num_(d.diverge.streak, 0) >= 2) {
      h.push('<div style="margin-top:10px;padding:9px 12px;background:#eff6ff;border-radius:7px;font-size:12.5px;color:#1e40af;">' +
             '🔥 已连续 <b>' + num_(d.diverge.streak, 0) + ' 个交易日</b>出现「越跌越买」，托底意愿较强。</div>');
    }

    h.push('<div style="margin-top:12px;padding:11px 13px;background:#f8fafc;border-radius:8px;font-size:11.5px;color:' + C.tx2 + ';line-height:1.9;">');
    h.push('<div style="font-weight:700;color:' + C.tx + ';margin-bottom:4px;">四种判断怎么理解</div>');
    var legend = [
      ['越跌越买', '指数跌、资金却在进 —— 最典型的托底形态，国家队常见动作'],
      ['顺势加仓', '指数涨、资金也在进 —— 偏追涨，对后市要求更高'],
      ['涨了就卖', '指数涨、资金在出 —— 趁反弹减仓，不是好信号'],
      ['下跌也在卖', '指数跌、资金也在出 —— 这个位置没看到托底意愿']
    ];
    for (var lg2 = 0; lg2 < legend.length; lg2++) {
      var lc = tagStyle_(legend[lg2][0]);
      h.push('<div><b style="color:' + lc.fg + ';background:' + lc.bg + ';padding:1px 6px;border-radius:6px;">' +
             legend[lg2][0] + '</b>　' + legend[lg2][1] + '</div>');
    }
    h.push('</div>');
  } else {
    h.push('<div style="font-size:12.5px;color:' + C.tx3 + ';">本次没有取到对照数据。</div>');
  }
  h.push('</div>');

  // ---------- ⑦ 各指数类别 ----------
  var cats = d.cats || [];
  h.push(sectionOpen_(C, '⑤ 各指数类别流向',
    '看结构，不只看总量。沪深300 在买、创业板在卖，和反过来，透露的信息完全不同。「倍量」= 相对自身规模的强度，方便横向比大小盘。'));
  if (cats.length) {
    h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-size:12px;">');
    h.push('<tr style="background:#f8fafc;">');
    h.push('<th width="25%" align="left"  style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">类别</th>');
    h.push('<th width="15%" align="right" style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">今日</th>');
    h.push('<th width="15%" align="right" style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">近5日</th>');
    h.push('<th width="16%" align="right" style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">近20日</th>');
    h.push('<th width="19%" align="right" style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">倍量</th>');
    h.push('<th width="10%" align="right" style="padding:7px 5px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">只数</th>');
    h.push('</tr>');
    for (var j = 0; j < cats.length; j++) {
      var ct = cats[j];
      h.push('<tr>');
      h.push('<td style="padding:7px 6px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx + ';font-weight:600;">' + esc_(ct.name) + '</td>');
      h.push(numTd_(ct.today, 1, C, true));
      h.push(numTd_(ct.w5, 1, C, false));
      h.push(numTd_(ct.m20, 1, C, false));
      h.push(numTd_(ct.bei, 2, C, false, ' 倍'));
      h.push('<td align="right" style="padding:7px 6px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx3 + ';">' + num_(ct.n_etf, 0) + '</td>');
      h.push('</tr>');
    }
    h.push('</table>');
  }
  h.push('</div>');

  // ---------- ⑧ ETF 明细 ----------
  var etfs = d.etfs || [];
  h.push(sectionOpen_(C, '⑥ ' + etfs.length + ' 只 ETF 明细（按今日净买卖绝对值排序）',
    '想知道钱具体进了哪只产品，就看这张表。'));
  if (etfs.length) {
    h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-size:11.5px;">');
    h.push('<tr style="background:#f8fafc;">');
    h.push('<th width="11%" align="left"  style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">代码</th>');
    h.push('<th width="31%" align="left"  style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">名称</th>');
    h.push('<th width="11%" align="right" style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">今日</th>');
    h.push('<th width="12%" align="right" style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">近一周</th>');
    h.push('<th width="12%" align="right" style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">近一月</th>');
    h.push('<th width="13%" align="right" style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">倍量</th>');
    h.push('<th width="10%" align="right" style="padding:6px 4px;border-bottom:1px solid ' + C.line + ';color:' + C.tx3 + ';font-weight:600;">份额</th>');
    h.push('</tr>');
    for (var k = 0; k < etfs.length; k++) {
      var e2 = etfs[k];
      var nm = String(e2.n || '');
      // 名称列宽约 32%，14 个字以内放得下；再长就截断，避免把表格撑破
      var shown = nm.length > 14 ? nm.substring(0, 14) + '…' : nm;
      h.push('<tr>');
      h.push('<td style="padding:6px 5px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx3 + ';">' + esc_(e2.c) + '</td>');
      h.push('<td style="padding:6px 5px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx + ';">' + esc_(shown) + '</td>');
      h.push(numTd_(e2.today, 1, C, true, '', '6px 5px'));
      h.push(numTd_(e2.week, 1, C, false, '', '6px 5px'));
      h.push(numTd_(e2.month, 1, C, false, '', '6px 5px'));
      h.push(numTd_(e2.bei, 2, C, false, ' 倍', '6px 5px'));
      h.push('<td align="right" style="padding:6px 5px;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx2 + ';">' +
             num_(e2.share, 0).toFixed(1) + '</td>');
      h.push('</tr>');
    }
    h.push('</table>');
    h.push('<div style="font-size:11px;color:' + C.tx3 + ';margin-top:7px;line-height:1.7;">' +
           '「份额」是该 ETF 最新基金份额（亿份），不是金额。倍量的基准日固定在 2025-12-31，' +
           '之后份额变化大的品种（如创业板 ETF）倍量会被放大，看趋势可以，不宜跨品种硬比。</div>');
  }
  h.push('</div>');

  // ---------- ⑨ 名词速查 ----------
  h.push(sectionOpen_(C, '⑦ 名词速查', '第一次看这份数据的话，先扫一眼这里。'));
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-size:12px;">');
  for (var g = 0; g < GLOSSARY.length; g++) {
    h.push('<tr>');
    h.push('<td width="96" valign="top" style="padding:8px 8px 8px 0;border-bottom:1px solid ' + C.line2 +
           ';font-weight:700;color:' + C.tx2 + ';white-space:nowrap;">' + esc_(GLOSSARY[g][0]) + '</td>');
    h.push('<td valign="top" style="padding:8px 0;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx + ';line-height:1.75;">' +
           esc_(GLOSSARY[g][1]) + '</td>');
    h.push('</tr>');
  }
  h.push('</table>');
  h.push('</div>');

  // ---------- ⑩ 口径与来源 ----------
  h.push(sectionOpen_(C, '⑧ 数据怎么来的 / 别误读什么', ''));
  h.push('<div style="font-size:12px;color:' + C.tx2 + ';line-height:1.9;">');
  h.push('<div style="font-weight:700;color:' + C.tx + ';margin-bottom:5px;">算法</div>');
  h.push('<div style="background:#f8fafc;border-radius:6px;padding:9px 11px;font-size:11.5px;line-height:1.8;color:' + C.tx2 + ';margin-bottom:11px;">' +
         '净买卖金额 =（当日份额 − 前一日份额）× 当日单位净值<br>' +
         '倍量份额　 = 当日净申购份额 ÷ 该 ETF 2025-12-31 份额 × 0.1%</div>');
  h.push('<div style="font-weight:700;color:' + C.tx + ';margin-bottom:5px;">数据来源</div>');
  h.push('<div style="margin-bottom:11px;">上交所 / 深交所 ETF 份额（AKShare 逐日与区间接口）　·　天天基金单位净值　·　东方财富指数 K 线（失败时降级腾讯行情）　·　新浪交易日历</div>');
  h.push('<div style="font-weight:700;color:' + C.tx + ';margin-bottom:5px;">三个必须知道的局限</div>');
  h.push('<div>① <b>ETF 净申购 ≠ 国家队买入。</b>这只是「资金动向」的公开代理口径，真正的持仓归属无法从公开数据看到。</div>');
  h.push('<div>② <b>份额披露有 1~2 天滞后。</b>沪深两市节奏不同，本页取两地都有数据的最近共同交易日，所以「数据日」通常比今天早一天。</div>');
  h.push('<div>③ <b>单日数据噪音大。</b>尤其在指数大跌当天，净值下折本身会让市值缩水，和「赎回」是两回事。判断趋势至少要看近 20 日。</div>');
  h.push('</div>');
  h.push('<div style="margin-top:12px;padding:10px 13px;background:#f8fafc;border-radius:8px;font-size:11.5px;color:' + C.tx3 + ';line-height:1.7;">' +
         '在线看板：' + esc_(CONFIG.URL_SITE) + '<br>' +
         '本邮件由脚本从公开数据自动生成，仅为数据观察，<b>不构成任何投资建议</b>。' +
         '数字如与看板不一致，以看板为准。</div>');
  h.push('</div>');

  h.push('</div></div>');
  return h.join('');
}

/**
 * 「AI 总结」栏 —— 邮件正文第一屏。
 * 有 AI 用 AI；AI 不可用则用规则版，并在下方小字说明原因与修法。
 * 无论哪种情况这一栏一定存在，不会出现「什么都没有」。
 */
function aiSummaryHtml_(d, bundle, C) {
  var ai = bundle.ai || { ok: false, lines: null, model: '', error: '未调用' };
  var rule = bundle.rule || {};
  var lights = bundle.lights || {};
  var isAI = !!(ai.ok && ai.lines && ai.lines.length);
  var T = d.today || {};

  var map = {};
  if (isAI) {
    for (var i = 0; i < ai.lines.length; i++) map[ai.lines[i].label] = ai.lines[i].text;
  }
  function get(k) {
    var v = isAI ? map[k] : rule[k];
    return v || '';
  }

  var oneline = get('一句话') || ('今天全表' + (num_(T.net, 0) >= 0 ? '净买入 ' : '净卖出 ') +
                                  Math.abs(num_(T.net, 0)).toFixed(1) + ' 亿元。');
  var body = get('总结');
  var advice = get('建议');
  var dims = ['资金', '结构', '涨跌', '风险'];

  var title = isAI ? '🧠 AI 总结' : '🧠 今日总结';
  var badge = isAI
    ? '<span style="display:inline-block;background:#e0f2fe;color:#0369a1;font-size:11px;font-weight:700;padding:2px 9px;border-radius:10px;vertical-align:middle;">AI 生成 · ' + esc_(ai.model) + '</span>'
    : '<span style="display:inline-block;background:#fef3c7;color:#92400e;font-size:11px;font-weight:700;padding:2px 9px;border-radius:10px;vertical-align:middle;">规则生成 · AI 未启用</span>';

  var h = [];
  h.push('<div style="background:' + C.card + ';border:1px solid ' + C.line +
         ';border-left:4px solid ' + C.pur + ';border-radius:10px;padding:16px;margin-top:12px;">');

  h.push('<div style="font-size:16px;font-weight:700;color:' + C.tx + ';">' + title + '　' + badge + '</div>');

  // 一句话（最醒目）
  h.push('<div style="margin-top:10px;padding:11px 14px;background:#f5f3ff;border-radius:8px;font-size:14.5px;font-weight:600;color:#4c1d95;line-height:1.65;">' +
         esc_(oneline) + '</div>');

  // 总结正文
  if (body) {
    h.push('<div style="margin-top:10px;font-size:13.5px;line-height:1.9;color:' + C.tx + ';">' + esc_(body) + '</div>');
  }

  // 四个维度
  var anyDim = false;
  for (var dd = 0; dd < dims.length; dd++) if (get(dims[dd])) anyDim = true;
  if (anyDim) {
    h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:11px;font-size:12.5px;border-top:1px solid ' + C.line + ';">');
    for (var d2 = 0; d2 < dims.length; d2++) {
      var t2 = get(dims[d2]);
      if (!t2) continue;
      var lg = lights[dims[d2]];
      var dot = lg ? lg.dot : '·';
      var word = lg ? ('<span style="color:' + C.tx3 + ';font-size:11px;">（' + esc_(lg.text) + '）</span>') : '';
      h.push('<tr>');
      h.push('<td width="62" valign="top" style="padding:8px 0;border-bottom:1px solid ' + C.line2 +
             ';font-weight:700;color:' + C.tx2 + ';white-space:nowrap;">' + dot + ' ' + esc_(dims[d2]) + '</td>');
      h.push('<td valign="top" style="padding:8px 0;border-bottom:1px solid ' + C.line2 + ';color:' + C.tx + ';line-height:1.8;">' +
             esc_(t2) + ' ' + word + '</td>');
      h.push('</tr>');
    }
    h.push('</table>');
  }

  // 建议
  if (advice) {
    h.push('<div style="margin-top:11px;padding:10px 13px;background:#eff6ff;border-radius:8px;border-left:3px solid ' + C.blue + ';">');
    h.push('<div style="font-size:11.5px;font-weight:700;color:' + C.blue + ';letter-spacing:.5px;">如果只看一件事</div>');
    h.push('<div style="font-size:13px;color:' + C.tx + ';margin-top:2px;line-height:1.8;">' + esc_(advice) + '</div>');
    h.push('</div>');
  }

  // 降级说明 / 免责
  if (!isAI) {
    h.push('<div style="margin-top:11px;padding:9px 12px;background:#fef2f2;border:1px solid #fecaca;border-radius:7px;font-size:11.5px;color:#991b1b;line-height:1.75;">');
    h.push('<div style="font-weight:700;">本次 AI 没有生成内容，以上是程序按固定规则拼出的总结 —— 结论来自同一批数字，只是措辞不如 AI 自然，内容依然准确。</div>');
    h.push('<div style="margin-top:4px;word-break:break-all;">原因：' + esc_(ai.error || '未知') + '</div>');
    h.push('<div style="margin-top:4px;color:#b45309;">排查：① 打开 script.google.com 本项目「执行记录」看日志；' +
           '② 运行 testConnections() 单独测 Gemini；③ 确认密钥有效、模型已在 AI Studio 启用、未超免费配额。</div>');
    h.push('</div>');
  } else {
    h.push('<div style="margin-top:10px;font-size:11px;color:' + C.tx3 + ';line-height:1.7;">' +
           '以上由大模型基于本邮件全部数据生成，仅供理解，不构成投资建议；如与下方原始数值冲突，以原始数值为准。</div>');
  }

  h.push('</div>');
  return h.join('');
}

// ============================================================
// 9. HTML 小组件
// ============================================================
function sectionOpen_(C, title, sub) {
  return '<div style="background:' + C.card + ';border:1px solid ' + C.line +
         ';border-radius:10px;padding:16px;margin-top:12px;">' +
         '<div style="font-size:15px;font-weight:700;color:' + C.tx + ';">' + esc_(title) + '</div>' +
         (sub ? '<div style="font-size:12px;color:' + C.tx3 + ';margin:3px 0 12px;line-height:1.7;">' + esc_(sub) + '</div>'
              : '<div style="height:10px;"></div>');
}

/** 一行「标签 / 值」 */
function kv_(label, val, C, color) {
  return '<div style="margin-bottom:7px;font-size:12px;color:' + C.tx3 + ';">' + esc_(label) + '<br>' +
    '<span style="font-size:13.5px;font-weight:700;color:' + (color || C.tx) + ';">' + esc_(val) + '</span></div>';
}

/** 带颜色 + 符号的数字单元格 */
function numTd_(v, nd, C, bold, suffix, pad) {
  var n = num_(v, null);
  var color = (n === null || n === 0) ? C.tx3 : (n > 0 ? C.up : C.down);
  var txt = (n === null) ? '—' : (yi_(n, nd) + (suffix || ''));
  return '<td align="right" style="padding:' + (pad || '7px 6px') + ';border-bottom:1px solid ' + C.line2 +
         ';color:' + color + ';' + (bold ? 'font-weight:700;' : '') + 'white-space:nowrap;">' + esc_(txt) + '</td>';
}

/** 「越跌越买」等四种标签的配色 */
function tagStyle_(tag) {
  if (tag === '越跌越买')   return { bg: '#dcfce7', fg: '#15803d' };
  if (tag === '顺势加仓')   return { bg: '#fee2e2', fg: '#b91c1c' };
  if (tag === '涨了就卖')   return { bg: '#fef3c7', fg: '#b45309' };
  if (tag === '下跌也在卖') return { bg: '#e0f2fe', fg: '#0369a1' };
  return { bg: '#f1f5f9', fg: '#5b6472' };
}

/** 四个时间窗口并排 */
function winRow_(W, C) {
  var items = [
    ['近 5 日', W.d5],
    ['近 20 日', W.d20],
    ['近 60 日', W.d60],
    ['近 250 日', W.d250]
  ];
  var h = [];
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:separate;border-spacing:5px 0;">');
  h.push('<tr>');
  for (var i = 0; i < items.length; i++) {
    var v = num_(items[i][1], 0);
    var color = v > 0 ? C.up : (v < 0 ? C.down : C.tx3);
    var bg = v > 0 ? '#fef2f2' : (v < 0 ? '#f0fdf4' : '#f8fafc');
    h.push('<td width="25%" align="center" valign="middle" style="padding:11px 4px;background:' + bg + ';border-radius:8px;">');
    h.push('<div style="font-size:11.5px;color:' + C.tx3 + ';white-space:nowrap;">' + esc_(items[i][0]) + '</div>');
    h.push('<div style="font-size:17px;font-weight:800;color:' + color + ';line-height:1.35;letter-spacing:-.3px;">' +
           esc_(yi_(v, 1)) + '</div>');
    h.push('<div style="font-size:10.5px;color:' + C.tx3 + ';">亿元</div>');
    h.push('</td>');
  }
  h.push('</tr></table>');
  return h.join('');
}

/**
 * 迷你柱状图：最近 N 个交易日的每日净买卖。
 * 上排画正数（向上），下排画负数（向下），中间一条零轴。
 * 纯 table + div，邮件客户端能正常渲染。
 */
function sparkBars_(recent, C) {
  if (!recent || !recent.length) return '';
  var n = recent.length;
  var max = 1;
  for (var i = 0; i < n; i++) {
    var a = Math.abs(num_(recent[i].net, 0));
    if (a > max) max = a;
  }
  var H = 32;

  var h = [];
  h.push('<div style="margin-top:14px;">');
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;table-layout:fixed;">');

  // 正半轴
  h.push('<tr>');
  for (var j = 0; j < n; j++) {
    var v1 = num_(recent[j].net, 0);
    var hh1 = v1 > 0 ? Math.max(2, Math.round(v1 / max * H)) : 0;
    h.push('<td align="center" valign="bottom" style="padding:0 1px;height:' + H + 'px;">' +
           (hh1 ? '<div style="height:' + hh1 + 'px;background:' + C.up + ';border-radius:2px 2px 0 0;font-size:0;line-height:0;">&nbsp;</div>' : '') +
           '</td>');
  }
  h.push('</tr>');

  // 零轴
  h.push('<tr><td colspan="' + n + '" style="height:1px;background:#cbd5e1;font-size:0;line-height:0;padding:0;">&nbsp;</td></tr>');

  // 负半轴
  h.push('<tr>');
  for (var k = 0; k < n; k++) {
    var v2 = num_(recent[k].net, 0);
    var hh2 = v2 < 0 ? Math.max(2, Math.round(Math.abs(v2) / max * H)) : 0;
    h.push('<td align="center" valign="top" style="padding:0 1px;height:' + H + 'px;">' +
           (hh2 ? '<div style="height:' + hh2 + 'px;background:' + C.down + ';border-radius:0 0 2px 2px;font-size:0;line-height:0;">&nbsp;</div>' : '') +
           '</td>');
  }
  h.push('</tr>');

  // 日期轴
  h.push('<tr>');
  h.push('<td colspan="' + n + '" style="padding-top:5px;font-size:10.5px;color:' + C.tx3 + ';">');
  h.push('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>');
  h.push('<td align="left">' + esc_(String(recent[0].d || '').substring(5)) + '</td>');
  h.push('<td align="right">' + esc_(String(recent[n - 1].d || '').substring(5)) + '</td>');
  h.push('</tr></table>');
  h.push('</td>');
  h.push('</tr>');

  h.push('</table>');
  h.push('</div>');
  return h.join('');
}

// ============================================================
// 10. 纯文本兜底正文（不支持 HTML 的客户端用）
// ============================================================
function buildPlain_(d, bundle) {
  var T = d.today || {}, W = d.windows || {}, mv = d.mv || {};
  var ai = bundle.ai || { ok: false, lines: null, model: '', error: '' };
  var rule = bundle.rule || {};
  var isAI = !!(ai.ok && ai.lines && ai.lines.length);
  var map = {};
  if (isAI) for (var a = 0; a < ai.lines.length; a++) map[ai.lines[a].label] = ai.lines[a].text;
  function g(k) { return (isAI ? map[k] : rule[k]) || ''; }

  var L = [];
  L.push('国家队宽基 ETF · 每日流向');
  L.push('数据日 ' + (d.asof || '—') + '（' + (d.asof_weekday || '') + '）');
  L.push('');
  L.push('【' + (isAI ? 'AI 总结（' + ai.model + '）' : '今日总结（规则生成，AI 未启用）') + '】');
  if (g('一句话')) L.push('· ' + g('一句话'));
  if (g('总结')) L.push(g('总结'));
  ['资金', '结构', '涨跌', '风险'].forEach(function (k) {
    if (g(k)) L.push('· ' + k + '：' + g(k));
  });
  if (g('建议')) L.push('· 建议：' + g('建议'));
  if (!isAI && ai.error) L.push('（AI 失败原因：' + ai.error + '）');
  L.push('');
  L.push('【今日总览】');
  L.push('全表净买卖：' + yi_(num_(T.net, 0)) + ' 亿元');
  L.push('买入/卖出/持平：' + num_(T.buy_count, 0) + ' / ' + num_(T.sell_count, 0) + ' / ' + num_(T.flat_count, 0));
  L.push('历史分位：' + num_(T.pct, 0).toFixed(1) + '%');
  if (T.rank_text) L.push(T.rank_text);
  if (num_(T.streak_days, 0) > 1) {
    L.push('连续同向：' + num_(T.streak_days, 0) + ' 天' +
           (T.streak_dir === 'buy' ? '净买入' : '净卖出') + '，累计 ' + yi_(num_(T.streak_sum, 0)) + ' 亿元');
  }
  L.push('中证全指当日：' + num_(T.idx_chg, 0).toFixed(1) + '%，判定「' + (T.tag || '—') + '」');
  L.push('');
  L.push('【时间窗口】');
  L.push('近5日 ' + yi_(num_(W.d5, 0)) + ' / 近20日 ' + yi_(num_(W.d20, 0)) +
         ' / 近60日 ' + yi_(num_(W.d60, 0)) + ' / 近250日 ' + yi_(num_(W.d250, 0)) + ' 亿元');
  L.push('持仓市值 ' + plain_(num_(mv.now, 0), 1) + ' 亿元（历史分位 ' + num_(mv.pct, 0).toFixed(1) + '%）');
  if (d.reversal) {
    L.push('');
    L.push('【⚠️ 短期与一年维度方向相反】');
    L.push(d.reversal.text);
  }
  L.push('');
  L.push('【指数涨跌 × 资金流向】');
  var rows = (d.diverge && d.diverge.rows) || [];
  for (var i = 0; i < rows.length; i++) {
    L.push(rows[i].d + '　' + (num_(rows[i].idx, 0) >= 0 ? '+' : '') + num_(rows[i].idx, 0).toFixed(1) + '%　' +
           yi_(num_(rows[i].net, 0)) + ' 亿　' + (rows[i].tag || ''));
  }
  L.push('');
  L.push('【各指数类别】');
  var cats = d.cats || [];
  for (var j = 0; j < cats.length; j++) {
    L.push(cats[j].name + '　今日 ' + yi_(num_(cats[j].today, 0)) + '　近5日 ' + yi_(num_(cats[j].w5, 0)) +
           '　近20日 ' + yi_(num_(cats[j].m20, 0)) + '　倍量 ' + num_(cats[j].bei, 0).toFixed(2));
  }
  L.push('');
  L.push('详见 ' + CONFIG.URL_SITE);
  L.push('本邮件自动生成，仅为数据观察，不构成投资建议。');
  return L.join('\n');
}

// ============================================================
// 11. 工具函数
// ============================================================
function log_(m) { console.log(m); }

function fmt_(d) { return Utilities.formatDate(d, CONFIG.TIMEZONE, 'yyyy-MM-dd HH:mm'); }

function num_(v, dflt) {
  var n = parseFloat(v);
  return isFinite(n) ? n : dflt;
}

/** 149.9 → "+149.9"；-12669.6 → "-12,669.6"；0 → "0.0" */
function yi_(v, nd) {
  nd = (nd === undefined) ? 1 : nd;
  if (v === null || v === undefined || !isFinite(parseFloat(v))) return '—';
  var n = parseFloat(v);
  var a = Math.abs(n).toFixed(nd);
  var dot = a.indexOf('.');
  var intPart = dot >= 0 ? a.substring(0, dot) : a;
  var frac = dot >= 0 ? a.substring(dot) : '';
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  var out = intPart + frac;
  if (n > 0) return '+' + out;
  if (n < 0) return '-' + out;
  return out;
}

/**
 * 同上，但**不强制加正号** —— 用于「持仓市值」「一年最高/最低」这类
 * 本来就是水平的数值。给它加 + 号会让人误以为是涨跌。
 */
function plain_(v, nd) {
  nd = (nd === undefined) ? 1 : nd;
  if (v === null || v === undefined || !isFinite(parseFloat(v))) return '—';
  var n = parseFloat(v);
  var a = Math.abs(n).toFixed(nd);
  var dot = a.indexOf('.');
  var intPart = dot >= 0 ? a.substring(0, dot) : a;
  var frac = dot >= 0 ? a.substring(dot) : '';
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (n < 0 ? '-' : '') + intPart + frac;
}

function esc_(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 用 ISO 星期（1 = 周一 … 7 = 周日）判断周末 */
function isWeekend_() {
  try {
    var u = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'u');
    var n = parseInt(u, 10);
    if (isFinite(n) && n >= 1 && n <= 7) return n >= 6;
  } catch (e) {}
  var cn = weekdayCn_(new Date());
  return cn === '周六' || cn === '周日';
}

function weekdayCn_(dt) {
  try {
    var w = Utilities.formatDate(dt, CONFIG.TIMEZONE, 'u');
    var arr = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
    var i = parseInt(w, 10) - 1;
    if (i >= 0 && i < 7) return arr[i];
  } catch (e) {}
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date().getDay()];
}

/** 两个 yyyy-MM-dd 之间差多少天（b − a） */
function daysBetween_(a, b) {
  if (!a || !b) return -1;
  var t1 = new Date(a + 'T00:00:00').getTime();
  var t2 = new Date(b + 'T00:00:00').getTime();
  if (!isFinite(t1) || !isFinite(t2)) return -1;
  return Math.round((t2 - t1) / 86400000);
}

function sendError_(title, detail) {
  log_('ERROR: ' + title + ' | ' + detail);
  try {
    MailApp.sendEmail({
      to: CONFIG.RECEIVER_EMAIL,
      subject: '【国家队ETF流向·失败】' + title,
      body: title + '\n\n' + detail + '\n\n时间：' + fmt_(new Date()) +
            '\n\n排查看这里：脚本编辑器左侧「执行记录」，点开最近一次看日志。',
      name: '国家队ETF流向'
    });
  } catch (e) { log_('连告警邮件都发不出去：' + e); }
}

/** 数据连续多日没推进时的提醒 */
function sendStale_(asof, today) {
  var body =
    '连续 3 个工作日过去了，看板的数据日还停在 ' + asof + '，没有出现新的交易日数据。\n\n' +
    '可能的原因：\n' +
    '1. 长假期（春节 / 国庆），这属于正常，假期结束后会自动恢复；\n' +
    '2. GitHub Actions 的定时任务连续失败（比如 AKShare 接口改版），需要去仓库 Actions 页面看红色叉号；\n' +
    '3. 交易所份额披露延迟超过 3 天（少见）。\n\n' +
    '先打开看板确认一下：' + CONFIG.URL_SITE + '\n' +
    '如果看板上的数据日也是 ' + asof + '，就是第 2 种，去仓库的 Actions 页看最近一次运行日志。\n\n' +
    '在问题修好之前，本脚本会继续跳过发信，不会重复发同一份数字。';
  try {
    MailApp.sendEmail({
      to: CONFIG.RECEIVER_EMAIL,
      subject: '【国家队ETF流向】数据已 ' + daysBetween_(asof, today) + ' 天未更新，请检查',
      body: body,
      name: '国家队ETF流向'
    });
    log_('已发送「数据未更新」提醒');
  } catch (e) { log_('提醒邮件发送失败：' + e); }
}

// ============================================================
// 12. 手动测试 / 安装定时器（各运行一次即可）
// ============================================================

/** ① 体检：测数据源与 Gemini 是否可用 */
function testConnections() {
  log_('—— 0/4 环境 ——');
  log_('   脚本时区 ' + Session.getScriptTimeZone() + '（定时器另行指定 ' + CONFIG.TIMEZONE + '，不受此影响）');
  log_('   今天是 ' + Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd EEE') +
       (isWeekend_() ? '，周末 → 自动模式下不会发送' : '，工作日'));

  log_('—— 1/4 latest.json ——');
  var d = fetchJson_();
  if (!d) {
    log_('   ❌ 取不到。先用浏览器打开 ' + CONFIG.URL_JSON + ' 确认能访问');
  } else {
    log_('   ✅ 数据日 ' + d.asof + '（' + d.asof_weekday + '），生成于 ' + d.generated);
    log_('      今日 ' + yi_(num_(d.today && d.today.net, 0)) + ' 亿，' + (d.today && d.today.tag) +
         '，连续 ' + num_(d.today && d.today.streak_days, 0) + ' 天');
    log_('      cats ' + ((d.cats || []).length) + ' 类 / etfs ' + ((d.etfs || []).length) +
         ' 只 / diverge ' + (((d.diverge || {}).rows || []).length) + ' 天');
    var need = ['asof', 'today', 'windows', 'mv', 'cats', 'etfs', 'diverge', 'recent', 'scope'];
    var miss = [];
    for (var i = 0; i < need.length; i++) if (!(need[i] in d)) miss.push(need[i]);
    log_('      字段检查：' + (miss.length ? '缺少 ' + miss.join(', ') : '全部齐全 ✅'));
  }

  log_('—— 2/4 llms.txt ——');
  var txt = fetchText_();
  log_('   ' + (txt ? '✅ ' + txt.length + ' 字符' : '❌ 取不到（只影响 AI 的输入质量，不影响发信）'));

  log_('—— 3/4 Gemini ——');
  if (!CONFIG.WITH_GEMINI) {
    log_('   已关闭（WITH_GEMINI=false），邮件里会用规则生成的总结');
  } else if (!d) {
    log_('   跳过（没有数据，无法构造 prompt）');
  } else {
    var g = askGemini_(d, txt, d.asof, Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd'));
    if (g.ok) {
      log_('   ✅ 成功（' + g.model + '），返回 ' + g.lines.length + ' 行：');
      for (var k = 0; k < g.lines.length; k++) log_('      ' + g.lines[k].label + '：' + g.lines[k].text);
    } else {
      log_('   ❌ 全部模型都失败。逐条原因：');
      log_('      ' + g.error);
      log_('   对照：400 密钥无效 / 403 无权或未启用 API / 404 模型名不存在 / 429 超配额');
      log_('   提示：AI 失败不影响发信，邮件会改用规则版总结并写明原因。');
    }
  }

  log_('—— 4/4 状态与配额 ——');
  var p = PropertiesService.getScriptProperties();
  log_('   上次成功发送的数据日：' + (p.getProperty(PROP_ASOF) || '（还没发过）'));
  log_('   上次发送时间：' + (p.getProperty(PROP_SENT) || '—'));
  log_('   今天还能发 ' + MailApp.getRemainingDailyQuota() + ' 封');
  log_('   已装定时器：');
  var ts = ScriptApp.getProjectTriggers();
  if (!ts.length) log_('      （无）');
  for (var t = 0; t < ts.length; t++) log_('      ' + ts[t].getHandlerFunction());
}

/** ② 立刻发一封看效果（跳过周末与去重，也不影响去重记录） */
function previewNow() {
  log_('预览模式：立刻生成并发送一封（忽略周末与「数据未变」检查）');
  FORCE_ = true;
  try {
    dailyMain();
  } finally {
    FORCE_ = false;
  }
}

/** ③ 装定时器：每天 08:30（北京），脚本内部再跳过周末 */
function installDailyTrigger() {
  removeTriggers();
  ScriptApp.newTrigger('dailyMain')
    .timeBased()
    .everyDays(1)
    .atHour(CONFIG.TRIGGER_HOUR)
    .nearMinute(CONFIG.TRIGGER_MINUTE)
    .inTimezone(CONFIG.TIMEZONE)
    .create();
  log_('✅ 已安装：每天 ' + pad2_(CONFIG.TRIGGER_HOUR) + ':' + pad2_(CONFIG.TRIGGER_MINUTE) +
       '（' + CONFIG.TIMEZONE + '）自动运行 dailyMain');
  log_('   ' + (CONFIG.WEEKDAYS_ONLY ? '周六周日会在脚本内部自动跳过' : '注意：WEEKDAYS_ONLY=false，周末也会发'));
  var ts = ScriptApp.getProjectTriggers();
  for (var i = 0; i < ts.length; i++) log_('   现有定时器：' + ts[i].getHandlerFunction());
}

/** 停掉全部定时器 */
function removeTriggers() {
  var ts = ScriptApp.getProjectTriggers();
  for (var i = 0; i < ts.length; i++) ScriptApp.deleteTrigger(ts[i]);
  log_('已删除 ' + ts.length + ' 个定时器');
}

/** ④ 只看邮件长什么样，不发信（调样式时用，日志里会输出整段 HTML） */
function showHtml() {
  var d = fetchJson_();
  if (!d) { log_('取不到 latest.json'); return; }
  var txt = fetchText_();
  var bundle = {
    json: d, text: txt, warn: [], lights: buildLights_(d),
    rule: buildRuleSummary_(d),
    ai: { ok: false, lines: null, model: '', error: 'showHtml() 里不调用 AI，用规则总结演示' }
  };
  var html = buildHtml_(d, bundle);
  log_('主题：' + buildSubject_(d));
  log_('HTML 长度 ' + html.length);
  log_(html);
}

/** ⑤ 清掉去重记录，让今天能重新发一次（改完样式后常用） */
function resetDedup() {
  var p = PropertiesService.getScriptProperties();
  p.deleteProperty(PROP_ASOF);
  p.deleteProperty(PROP_SAME);
  p.deleteProperty(PROP_SENT);
  log_('已清空去重记录。下次运行（含定时器）会正常发送。');
}

function pad2_(n) { return (n < 10 ? '0' : '') + n; }
