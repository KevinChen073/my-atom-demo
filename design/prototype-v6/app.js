import { mockBackend } from './mock-backend.js';

const app = document.getElementById('app');
const iconBase = '../v3/icons/';
const navItems = [
  ['workbench', '工作台', 'workbench.svg'], ['overview', '项目概览', 'overview.svg'],
  ['docs', '项目文档', 'docs.svg'], ['tests', '测试', 'tests.svg'], ['publish', '发布', 'publish.svg']
];
const LAYOUT_KEY = 'myatom-design-prototype-v6-layout';
function readLayout() {
  try {
    const value = JSON.parse(localStorage.getItem(LAYOUT_KEY));
    if (Number.isFinite(value?.sidebar) && value.sidebar >= 180 && value.sidebar <= 280 && Number.isFinite(value?.chatRatio) && value.chatRatio >= 42 && value.chatRatio <= 64) return value;
  } catch { /* Fall back to the review default. */ }
  return { sidebar: 220, chatRatio: 56 };
}
const ui = { projectId: null, view: 'home', previewTab: {}, codeFile: {}, docTab: {}, logOpen: false, modal: '', homeSearch: '', sideSearch: '', switchSearch: '', homeEmpty: false, previewMode: 'balanced', layout: readLayout(), drag: null };
const phaseLabel = { clarify: '等待需求确认', plan: '等待计划确认', building: '模拟生成中', built: '代码已保存' };
const starterExamples = {
  expense: { title: '每周支出记录', description: '记录金额、分类与备注', request: '做一个每周支出记录工具，能添加金额、分类和备注，刷新后记录仍在。' },
  pomodoro: { title: '番茄钟待办', description: '管理任务与专注时间', request: '做一个番茄钟待办，任务完成状态与专注次数都要保存。' },
  weekend: { title: '周末行程', description: '按时间安排并调整活动', request: '做一个周末行程网页，按时间排列活动，并允许我手动调整顺序。' }
};

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}
function icon(name, alt = '') { return `<img src="${iconBase}${name}" alt="${alt}" aria-hidden="${alt ? 'false' : 'true'}">`; }
function projectPath(id, view = 'workbench') { return `#/projects/${encodeURIComponent(id)}${view === 'workbench' ? '' : `/${view}`}`; }
function navigate(path) { if (location.hash === path) route(); else location.hash = path; }
function projects() { return mockBackend.listProjects(); }
function currentProject() { return mockBackend.getProject(ui.projectId); }
function layoutStyle() { return `--sidebar-width:${ui.layout.sidebar}px;--chat-ratio:${ui.layout.chatRatio}%`;
}
function applyLayout(save = false) {
  document.querySelector('.app-shell')?.style.setProperty('--sidebar-width', `${ui.layout.sidebar}px`);
  document.querySelector('.project-workspace')?.style.setProperty('--chat-ratio', `${ui.layout.chatRatio}%`);
  document.querySelector('.splitter-sidebar')?.setAttribute('aria-valuenow', String(Math.round(ui.layout.sidebar)));
  document.querySelector('.splitter-chat')?.setAttribute('aria-valuenow', String(Math.round(ui.layout.chatRatio)));
  if (save) { try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(ui.layout)); } catch { /* Browsing still works without saved preference. */ } }
}
function resetLayout() { ui.layout = { sidebar: 220, chatRatio: 56 }; applyLayout(true); }
function updateSplitter(kind, pixels) {
  if (kind === 'sidebar') ui.layout.sidebar = Math.max(180, Math.min(280, Math.round(pixels)));
  else {
    const width = document.querySelector('.project-workspace')?.clientWidth || 1;
    const clamped = Math.max(440, Math.min(width - 400, pixels));
    ui.layout.chatRatio = Math.round(clamped / width * 1000) / 10;
  }
  applyLayout();
}

function parseRoute() {
  const match = location.hash.match(/^#\/projects\/([^/]+)(?:\/(overview|docs|tests|publish))?$/);
  return match ? { id: decodeURIComponent(match[1]), view: match[2] || 'workbench' } : { id: null, view: 'home' };
}

function topBanner() {
  return `<div class="prototype-strip"><span><b>DESIGN PROTOTYPE / V6</b><i></i>所有数据与生成结果均为浏览器内模拟</span><div><button type="button" data-action="toggle-empty">${ui.homeEmpty ? '显示历史项目' : '查看首次使用'}</button><button type="button" data-action="reset-demo">恢复示例</button><a href="./README.md" target="_blank" rel="noopener">评审说明 ↗</a></div></div>`;
}
function historyRows() {
  const list = (ui.homeEmpty ? [] : projects()).filter((p) => p.title.toLowerCase().includes(ui.sideSearch.toLowerCase()));
  if (!list.length) return ui.homeEmpty ? `<div class="side-empty">暂无历史项目。写下第一个想法开始。</div>` : `<div class="side-empty">没有匹配项目。<button type="button" data-action="clear-side-search">清空搜索</button></div>`;
  return list.map((p) => `<a class="history-project ${p.id === ui.projectId ? 'active' : ''}" href="${projectPath(p.id)}" ${p.id === ui.projectId ? 'aria-current="page"' : ''}><span class="project-monogram">${escapeHtml(p.short)}</span><span class="history-project-copy"><b>${escapeHtml(p.title)}</b><small>${phaseLabel[p.phase]}${p.version ? ` · ${escapeHtml(p.version)}` : ''}</small></span></a>`).join('');
}
function sidebar(project) {
  if (!project) {
    return `<aside class="sidebar project-sidebar home-sidebar" aria-label="历史项目">
      <a class="brand" href="#/" aria-label="MYATOM 首页">${icon('brand-lockup.svg', 'MYATOM')}</a>
      <button class="side-link side-home" type="button" data-action="all-projects"><span class="nav-glyph">⌁</span>所有项目</button>
      <a class="side-link side-create active" href="#/" aria-current="page"><span class="nav-glyph">＋</span>新建项目</a>
      <div class="side-rule"></div><div class="history-heading"><p class="side-caption">历史项目</p><span>${ui.homeEmpty ? 0 : projects().length}</span></div>
      <label class="side-search"><span class="sr-only">搜索历史项目</span><input id="side-search" type="search" placeholder="搜索项目" value="${escapeHtml(ui.sideSearch)}"></label>
      <nav class="history-list" id="history-list" aria-label="历史项目列表">${historyRows()}</nav>
      <div class="sidebar-foot"><span>访客空间</span><small>界面原型 · 无真实后端</small></div></aside>`;
  }
  return `<aside class="sidebar project-sidebar" aria-label="历史项目">
      <a class="brand" href="#/" aria-label="MYATOM 首页">${icon('brand-lockup.svg', 'MYATOM')}</a>
      <button class="side-link side-home" type="button" data-action="all-projects"><span class="nav-glyph">⌁</span>所有项目</button>
      <button class="side-link side-create" type="button" data-action="new-project"><span class="nav-glyph">＋</span>新建项目</button>
      <div class="side-rule"></div><div class="history-heading"><p class="side-caption">历史项目</p><span>${projects().length}</span></div>
      <label class="side-search"><span class="sr-only">搜索历史项目</span><input id="side-search" type="search" placeholder="搜索项目" value="${escapeHtml(ui.sideSearch)}"></label>
      <nav class="history-list" id="history-list" aria-label="历史项目列表">${historyRows()}</nav>
      <div class="sidebar-foot"><span>访客空间</span><small>界面原型 · 无真实后端</small></div></aside>`;
}

function projectRows(list) {
  if (!list.length) return `<div class="no-results"><b>没有匹配的项目</b><p>换一个项目名称试试。</p><button class="text-action" data-action="clear-search" type="button">清空搜索</button></div>`;
  return list.map((p) => `<a class="project-row" href="${projectPath(p.id)}"><span class="project-monogram">${escapeHtml(p.short)}</span><span class="row-title"><b>${escapeHtml(p.title)}</b><small>${escapeHtml(p.request)}</small></span><span class="status ${p.phase}">${phaseLabel[p.phase]}</span><span class="row-version">${p.version ? escapeHtml(p.version) : '—'}</span><span class="row-updated">${escapeHtml(p.updated)}</span><span class="row-arrow" aria-hidden="true">↗</span></a>`).join('');
}
function home() {
  const cards = Object.entries(starterExamples).map(([key, item]) => `<button class="starter-card" type="button" data-action="example" data-example="${key}"><span class="starter-card-top"><b>${item.title}</b><span aria-hidden="true">↗</span></span><small>${item.description}</small></button>`).join('');
  return `${topBanner()}<div class="app-shell home-app-shell">${sidebar(null)}<div class="main-shell home-main home-focus">
    <header class="topbar home-topbar"><span>新建项目</span><button class="help-button" type="button" data-action="help">关于原型 ↗</button></header>
    <main class="home-stage" id="main-content"><div class="home-stage-inner">
      <div class="home-title"><span class="home-brand-mark">◇</span><h1>今天想做什么？</h1><p>描述你想做的网页应用。关键需求会在对话中逐步确认。</p></div>
      <form id="create-form" class="home-composer"><label class="sr-only" for="create-request">描述你想做的应用</label><textarea id="create-request" maxlength="5000" placeholder="例如：做一个能记录每周支出的网页，添加后刷新仍能看到记录…"></textarea><input id="create-title" type="hidden" value=""><div class="home-compose-footer"><span id="create-hint">先说清目标，细节可以稍后补充</span><div class="home-compose-actions"><span id="request-count">0 / 5000</span><button class="primary home-submit" type="submit">创建项目 <span aria-hidden="true">→</span></button></div></div><p id="create-error" class="form-error" role="alert" hidden></p></form>
      <div class="starter-heading"><span>试试这些基础样例</span><small>点击卡片填入输入框</small></div><div class="starter-grid">${cards}</div>
    </div></main>
  </div></div>`;
}
function historyQuestion(project) {
  return { timezone: '日期按哪个时区计算？', nextRound: '一轮计时结束后，下一轮怎样开始？', account: '这版需要账号登录吗？', scope: '这一版先做单人行程吗？', storage: '新内容是否需要在刷新后保留？' }[project.questionKind || 'storage'];
}
function dialogueTurn(role, content, caption = '') {
  const user = role === 'user';
  return `<div class="dialogue-turn ${user ? 'dialogue-user' : 'dialogue-agent'}">${user ? '' : '<span class="agent-avatar" aria-hidden="true">◇</span>'}<div class="turn-body"><span class="turn-speaker">${caption || (user ? '你' : 'MYATOM · Agent')}</span><p>${escapeHtml(content)}</p></div></div>`;
}
function dialogueHistory(project) {
  const turns = [dialogueTurn('user', project.request, '你 · 初始需求')];
  if (project.phase !== 'clarify') {
    turns.push(dialogueTurn('agent', `我已整理你明确提出的目标。先确认一个会影响操作方式的问题：${historyQuestion(project)}`));
    if (project.decision) turns.push(dialogueTurn('user', project.decision, '你 · 需求确认'));
  }
  if (project.phase === 'building' || project.phase === 'built') {
    turns.push(dialogueTurn('agent', `我会先完成“${project.title}”的主要页面和关键交互，再核对保存与空状态。计划已准备好，确认后进入模拟构建。`));
    if (project.planNote) turns.push(dialogueTurn('user', `计划修改意见：${project.planNote}`, '你 · 修改意见'));
    turns.push(dialogueTurn('user', '确认计划，开始生成。', '你 · 计划确认'));
  }
  return turns.join('');
}
function chat(project) {
  const isBuilt = project.phase === 'built';
  let card = '';
  if (project.phase === 'clarify') {
    const kind = project.questionKind || 'storage';
    const questions = {
      timezone: ['日期按哪个时区计算？', '浏览器本地时区', '符合访问者所在地的“今天” · 建议', '中国时区', '始终按北京时间显示'],
      nextRound: ['一轮计时结束后，下一轮怎样开始？', '等待手动开始', '避免意外进入下一轮 · 建议', '自动开始下一轮', '适合连续专注'],
      account: ['这版需要账号登录吗？', '先用访客身份', '减少第一版操作步骤 · 建议', '需要账号登录', '为多人使用做准备'],
      scope: ['这一版先做单人行程吗？', '先做单人行程', '先验证时间安排与调整流程 · 建议', '支持多人协作', '需要成员与权限设计'],
      storage: ['新内容是否需要在刷新后保留？', '需要保存', '刷新后仍可读回 · 建议', '仅本次使用', '刷新后可重置']
    };
    const q = questions[kind];
    card = `<section class="decision-card" aria-label="需求确认"><div class="card-kicker"><span>01 / 需求澄清</span><span class="decision-tag">需要你确认</span></div><h3>先确认这一件事</h3><p class="card-description">已在你的描述里确定的内容，会直接进入计划。</p><div class="known-box"><b>已明确</b><ul>${project.known.map((fact) => `<li>${escapeHtml(fact)}</li>`).join('')}</ul></div><fieldset class="choice-group"><legend>${q[0]}</legend><label><input type="radio" name="clarify-choice" value="${q[1]}"><span><b>${q[1]}</b><small>${q[2]}</small></span></label><label><input type="radio" name="clarify-choice" value="${q[3]}"><span><b>${q[3]}</b><small>${q[4]}</small></span></label></fieldset><div class="card-actions"><button class="primary" type="button" data-action="confirm-clarify" disabled>确认并查看计划 →</button></div></section>`;
  } else if (project.phase === 'plan') {
    card = `<section class="decision-card" aria-label="计划确认"><div class="card-kicker"><span>02 / 构建计划</span><span class="decision-tag">需要你确认</span></div><h3>准备做这一版</h3><p class="card-description">下面是界面原型中的模拟计划。确认后可查看模拟生成状态。</p><div class="plan-item"><span>01</span><div><b>完成主要页面</b><p>围绕“${escapeHtml(project.title)}”建立一个清楚的操作界面。</p></div></div><div class="plan-item"><span>02</span><div><b>处理关键交互</b><p>${escapeHtml(project.decision || '采用已确认的需求约束')}，显示操作后的反馈。</p></div></div><div class="plan-item"><span>03</span><div><b>核对验收点</b><p>检查主要状态、空状态与失败提示。</p></div></div><label class="plan-feedback" for="plan-note">需要调整计划？</label><textarea id="plan-note" placeholder="写下要调整的地方，原型会保留在计划摘要中…"></textarea><div class="card-actions"><button class="secondary" type="button" data-action="save-plan-note">保存修改意见</button><button class="primary" type="button" data-action="confirm-plan">确认计划 →</button></div></section>`;
  } else if (project.phase === 'building') {
    card = `<section class="decision-card build-card" aria-label="模拟构建"><div class="card-kicker"><span>03 / 模拟构建</span><span class="mock-tag">演示状态</span></div><h3>计划已确认</h3><p class="card-description">本原型不生成代码。点击下方按钮，可切换到“版本已保存”的界面状态。</p><div class="build-step"><span>✓</span><div><b>需求与计划已确认</b><small>本地模拟状态</small></div></div><div class="build-step"><span>2</span><div><b>等待模拟完成</b><small>无后台任务、无真实进度</small></div></div><div class="card-actions"><button class="primary" type="button" data-action="finish-build">模拟完成构建 →</button></div></section>`;
  } else {
    card = `<section class="result-card"><div class="card-kicker"><span>03 / 本次结果</span><span class="success-tag">已保存版本</span></div><h3>可以检查这一版了</h3><p>${project.id === 'weekly-spend' ? '示例项目已进入结果状态。右侧可试用模拟应用，或查看源码布局。' : '当前项目已切换到模拟完成状态。右侧展示预览容器与代码阅读布局。'}</p><div class="result-meta"><span>版本 <b>${escapeHtml(project.version)}</b></span><span>模拟构建结果</span></div><button class="text-action" type="button" data-action="open-tests">查看测试记录 →</button></section>`;
  }
  const activity = `<details class="activity-details"><summary>过程记录（模拟） <span>▾</span></summary><ol><li>需求已提交</li><li>${project.phase === 'clarify' ? '等待需求确认' : '需求已确认'}</li>${project.phase !== 'clarify' ? '<li>计划已准备</li>' : ''}${project.phase === 'building' || isBuilt ? '<li>计划已确认</li>' : ''}${isBuilt ? '<li>示例版本已保存</li>' : ''}</ol></details>`;
  return `<section class="chat-column" aria-label="项目对话"><div class="column-head"><div><span class="small-overline">MYATOM / AGENT SESSION</span><h2>对话</h2></div><button class="history-jump" type="button" data-action="jump-history">查看历史 ↑</button></div><div class="chat-scroll" id="chat-scroll"><div class="thread-label"><span>示例对话</span><span>今天</span></div>${dialogueHistory(project)}${activity}<div class="dialogue-turn dialogue-agent current-turn"><span class="agent-avatar" aria-hidden="true">◇</span><div class="turn-body"><span class="turn-speaker">MYATOM · Agent <small>当前</small></span>${card}</div></div></div><div class="composer"><label for="chat-draft">继续迭代</label><textarea id="chat-draft" placeholder="描述你希望修改的地方…">${escapeHtml(project.draft)}</textarea><div class="composer-foot"><span>此处为界面草稿，提交不会调用模型</span><button type="button" data-action="draft-submit" aria-label="模拟提交新需求">↑</button></div></div></section>`;
}
function rightHead(project, view, subtitle = '') {
  const names = { workbench: '预览与文件', overview: '项目概览', docs: '项目文档', tests: '测试', publish: '发布' };
  return `<div class="right-heading"><div><span class="small-overline">PROJECT / ${escapeHtml(project.title)}</span><h2 tabindex="-1" id="panel-title">${names[view]}</h2></div><div class="right-heading-actions"><span class="right-subtitle">${subtitle || (project.version ? `${project.version} · 模拟版本` : '尚无版本')}</span><button type="button" data-action="expand-preview">${ui.previewMode === 'expanded' ? '恢复比例' : '放大右侧'}</button></div></div>`;
}
function previewArea(project) {
  if (project.phase !== 'built') {
    const next = project.phase === 'clarify' ? '确认关键决定' : project.phase === 'plan' ? '确认构建计划' : '完成模拟构建';
    return `${rightHead(project, 'workbench')}<div class="prebuild"><div class="prebuild-label"><span class="status-pin"></span> 生成前 / 当前阶段</div><h3>${next}，再看结果。</h3><p>右侧先说明已确定的内容与下一步。这里不会把尚不存在的应用画成可操作预览。</p><div class="prebuild-grid"><div><small>已经知道</small><b>${escapeHtml(project.known[0] || project.request)}</b></div><div><small>当前待办</small><b>${next}</b></div></div><div class="preview-placeholder"><span>◇</span><b>应用预览将在版本完成后出现</b><small>原型只演示界面状态；没有真实代码生成。</small></div></div>`;
  }
  const tab = ui.previewTab[project.id] || 'preview';
  let body = '';
  if (tab === 'code') {
    const file = ui.codeFile[project.id] || 'src/App.tsx';
    const snippets = {
      'src/App.tsx': '// 设计原型：此处展示代码阅读区布局\nexport default function App() {\n  return (\n    <main>\n      <h1>示例应用</h1>\n      <Content />\n    </main>\n  );\n}',
      'src/App.css': '/* 设计原型：示意样式，不是生成结果 */\nmain {\n  min-height: 100vh;\n  padding: 32px;\n}',
      'package.json': '{\n  "name": "myatom-demo-layout",\n  "private": true\n}'
    };
    body = `<div class="code-layout"><nav class="file-list" aria-label="示例文件"><b>示例文件</b>${Object.keys(snippets).map((name) => `<button type="button" class="${file === name ? 'selected' : ''}" data-action="code-file" data-file="${name}">${name}</button>`).join('')}</nav><div class="code-sample"><div>${file} <span>示意内容</span></div><pre><code>${escapeHtml(snippets[file])}</code></pre></div></div>`;
  } else if (project.id === 'weekly-spend') {
    const total = project.expenses.reduce((sum, expense) => sum + expense.amount, 0);
    body = `<div class="viewer-frame"><div class="viewer-bar"><span><i></i><i></i><i></i></span><b>MYATOM 模拟应用</b><small>当前页面仅用于界面评审</small></div><div class="sample-app"><div class="sample-header"><div><small>PERSONAL LEDGER</small><h3>每周支出</h3><p>把日常的每一笔，记得明白。</p></div><div class="sample-total"><span>本周合计</span><b>¥ ${total.toFixed(2)}</b></div></div><div class="sample-content"><section><div class="sample-list-head"><b>最近记录</b><span>${project.expenses.length} 笔</span></div>${project.expenses.map((e) => `<div class="expense-row"><span class="expense-symbol">${escapeHtml(e.category.slice(0, 1))}</span><span><b>${escapeHtml(e.name)}</b><small>${escapeHtml(e.category)}</small></span><strong>− ¥${e.amount.toFixed(2)}</strong></div>`).join('')}</section><form id="expense-form" class="expense-form"><b>添加一笔</b><label for="expense-name">项目名称</label><input id="expense-name" placeholder="例如：晚餐" required maxlength="24"><label for="expense-amount">金额</label><input id="expense-amount" type="number" min="0.01" step="0.01" placeholder="0.00" required><label for="expense-category">分类</label><select id="expense-category"><option>餐饮</option><option>交通</option><option>其他</option></select><button type="submit">添加记录 →</button></form></div></div></div><p class="viewer-foot">演示数据仅保存在当前浏览器 · 刷新后可读回，清除浏览器数据后消失</p>`;
  } else {
    body = `<div class="sample-generic"><span>◇</span><h3>模拟版本已就绪</h3><p>此处演示预览容器和版本切换的界面。原型没有按你的需求生成真实应用。</p></div>`;
  }
  return `${rightHead(project, 'workbench')}<div class="viewer-tools"><div class="segmented" role="group" aria-label="成果视图"><button type="button" class="${tab === 'preview' ? 'active' : ''}" data-action="preview-tab" data-tab="preview" aria-pressed="${tab === 'preview'}">预览</button><button type="button" class="${tab === 'code' ? 'active' : ''}" data-action="preview-tab" data-tab="code" aria-pressed="${tab === 'code'}">代码</button></div><span class="version-pill">${escapeHtml(project.version)} · 示例版本</span></div>${body}`;
}

function overview(project) {
  const phase = project.phase;
  return `${rightHead(project, 'overview')}<section class="panel-intro"><span class="section-index">当前进展</span><h3>${phase === 'built' ? '版本已保存，等待浏览器验收。' : phase === 'clarify' ? '还有一个决定，先确认清楚。' : phase === 'plan' ? '计划已准备，等你确认。' : '模拟构建进行中。'}</h3><p>${phase === 'built' ? '预览可以试用，发布仍需真实环境与验收证据。' : '下一步在左侧对话完成；项目状态会随着决定更新。'}</p><button class="secondary" type="button" data-action="go-workbench">继续当前任务 →</button></section><div class="overview-grid"><section class="timeline-panel"><h4>项目阶段</h4>${[['需求已确认', phase !== 'clarify'], ['计划已确认', phase === 'building' || phase === 'built'], ['版本已保存', phase === 'built'], ['浏览器验证', false]].map(([label, done], index) => `<div class="timeline-row"><span class="timeline-mark ${done ? 'done' : ''}">${done ? '✓' : index + 1}</span><div><b>${label}</b><small>${done ? '已完成 · 演示数据' : index === 3 ? '尚无执行证据' : '待完成'}</small></div></div>`).join('')}</section><section class="summary-panel"><h4>项目目标</h4><p>${escapeHtml(project.request)}</p><h4>下一步</h4><p>${phase === 'built' ? '在工作台试用预览，再查看测试证据。' : '返回工作台，完成当前的确认。'}</p><h4>最近版本</h4><p>${project.version ? `${escapeHtml(project.version)} · 模拟已保存` : '尚无版本'}</p></section></div>`;
}
function docs(project) {
  const tab = ui.docTab[project.id] || 'requirements';
  const tabs = [['requirements', '需求'], ['plan', '计划'], ['decisions', '决定'], ['files', '文件']];
  let content = '';
  if (tab === 'requirements') content = `<article class="doc-sheet"><p class="doc-meta">01 / 需求说明</p><h3>已明确的目标</h3><p class="doc-lead">${escapeHtml(project.request)}</p><h4>核心要求</h4><ol>${project.known.map((fact) => `<li>${escapeHtml(fact)}</li>`).join('')}</ol><h4>当前边界</h4><p>界面原型展示信息组织与操作状态，实际业务能力以正式产品为准。</p></article>`;
  if (tab === 'plan') content = `<article class="doc-sheet"><p class="doc-meta">02 / 构建计划</p><h3>${project.phase === 'clarify' ? '等待需求确认' : '本版计划'}</h3>${project.phase === 'clarify' ? '<p>确认关键决定后，这里会出现计划。</p>' : `<ol><li>整理目标与主要页面</li><li>完成关键交互及反馈</li><li>核对验收点与版本状态</li></ol>${project.planNote ? `<p class="doc-note">修改意见：${escapeHtml(project.planNote)}</p>` : ''}`}</article>`;
  if (tab === 'decisions') content = `<article class="doc-sheet"><p class="doc-meta">03 / 决定记录</p><h3>为什么这样做</h3><div class="decision-line"><span>需求约束</span><b>${escapeHtml(project.decision || '仍在确认中')}</b></div><div class="decision-line"><span>生成方式</span><b>此处为浏览器内模拟</b></div><p class="doc-note">修改已确认内容时，回工作台提出新一轮需求。</p></article>`;
  if (tab === 'files') content = `<article class="doc-sheet"><p class="doc-meta">04 / 文件</p><h3>${project.version ? '示例版本文件' : '还没有文件'}</h3>${project.version ? '<p>这些文件名用于验证代码阅读区，不对应真实生成文件。</p><button class="file-row" type="button" data-action="open-code" data-file="src/App.tsx">src/App.tsx <span>查看示意 →</span></button><button class="file-row" type="button" data-action="open-code" data-file="src/App.css">src/App.css <span>查看示意 →</span></button>' : '<p>完成模拟构建后，文件入口才会出现。</p>'}</article>`;
  return `${rightHead(project, 'docs')}<p class="panel-description">需求、计划与决定按项目整理；信息来自当前模拟状态。</p><div class="doc-tabs" role="tablist" aria-label="文档分类">${tabs.map(([key, label]) => `<button type="button" role="tab" aria-selected="${tab === key}" class="${tab === key ? 'active' : ''}" data-action="doc-tab" data-tab="${key}">${label}</button>`).join('')}</div>${content}`;
}
function tests(project) {
  const built = project.phase === 'built';
  return `${rightHead(project, 'tests')}<p class="panel-description">检查项与证据对应模拟版本；这里没有执行真实构建或浏览器测试。</p><div class="test-summary"><b>${built ? '2 项演示通过' : '尚无执行记录'}</b><span>${built ? '1 项未执行' : '完成模拟构建后显示检查结果'}</span></div><div class="test-table"><div class="test-row test-head"><span>检查项</span><span>结果</span><span>证据</span></div>${built ? `<div class="test-row"><span><i class="test-icon pass">✓</i><b>依赖准备</b></span><span class="test-status pass">示意通过</span><button type="button" data-action="test-log">${ui.logOpen ? '收起' : '查看说明'}</button></div><div class="test-row"><span><i class="test-icon pass">✓</i><b>界面构建</b></span><span class="test-status pass">示意通过</span><button type="button" data-action="test-log">${ui.logOpen ? '收起' : '查看说明'}</button></div><div class="test-row"><span><i class="test-icon pending">!</i><b>浏览器验证</b></span><span class="test-status pending">未执行</span><span class="muted">暂无证据</span></div>${ui.logOpen ? '<div class="test-log">设计原型仅模拟检查结果，没有运行命令或生成日志。正式产品必须展示对应版本的真实证据。</div>' : ''}` : `<div class="test-empty">当前项目尚未保存版本，因此没有构建或测试结果。</div>`}</div><div class="explain-box"><b>结果解释</b><p>演示标签说明页面状态，不代表真实通过。浏览器验收需要独立的运行证据。</p></div>`;
}
function publish(project) {
  const built = project.phase === 'built';
  return `${rightHead(project, 'publish')}<p class="panel-description">公开发布只有在真实部署后才能给出地址。</p><section class="publish-hero"><span class="section-index">发布状态</span><h3>尚未发布</h3><p>这个设计原型没有发布服务，也不会生成假的公网链接。</p></section><div class="publish-grid"><section><h4>发布前检查</h4><div class="publish-check"><span class="${built ? 'pass' : 'pending'}">${built ? '✓' : '!'}</span><div><b>代码版本</b><small>${built ? `${escapeHtml(project.version)} · 示例版本` : '尚未保存版本'}</small></div><em>${built ? '示意具备' : '待完成'}</em></div><div class="publish-check"><span class="pending">!</span><div><b>浏览器验证</b><small>没有真实业务流程执行记录</small></div><em>待完成</em></div><div class="publish-check"><span class="pending">!</span><div><b>公开环境</b><small>原型未连接部署服务</small></div><em>不可用</em></div></section><aside class="public-link"><h4>公开链接</h4><span>↗</span><b>暂无公开地址</b><p>发布成功后才能显示真实 URL 和对应版本。</p></aside></div><button class="secondary" type="button" data-action="open-tests">查看测试状态 →</button>`;
}
function rightPanel(project) {
  const views = { workbench: previewArea, overview, docs, tests, publish };
  return `${projectNav(project)}<div class="right-content">${views[ui.view](project)}</div>`;
}
function projectNav(project) {
  return `<nav class="project-view-nav" aria-label="右侧项目内容视图"><div class="project-view-links">${navItems.map(([view, label, file]) => `<a class="project-view-link ${ui.view === view ? 'active' : ''}" href="${projectPath(project.id, view)}" ${ui.view === view ? 'aria-current="page"' : ''}>${icon(file)}<span>${label}</span></a>`).join('')}</div></nav>`;
}
function projectShell(project) {
  return `${topBanner()}<div class="app-shell" style="${layoutStyle()}">${sidebar(project)}<div class="splitter splitter-sidebar" role="separator" tabindex="0" aria-label="调整历史项目宽度" aria-orientation="vertical" aria-valuemin="180" aria-valuemax="280" aria-valuenow="${ui.layout.sidebar}"></div><div class="main-shell project-main"><header class="topbar project-topbar"><div class="project-identity"><span class="identity-kicker">当前项目</span><button class="top-project-switch" type="button" data-action="switch-project" aria-haspopup="dialog"><b>${escapeHtml(project.title)}</b><span>⌄</span></button><span class="top-status ${project.phase}">${phaseLabel[project.phase]}</span></div><div class="top-actions"><span class="top-save">本浏览器模拟数据 · ${escapeHtml(project.updated)}</span><button type="button" class="panel-size-action" data-action="toggle-preview" aria-expanded="${ui.previewMode !== 'hidden'}">${ui.previewMode === 'hidden' ? '打开右侧' : '收起右侧'}</button><button type="button" class="panel-size-action" data-action="reset-layout">恢复默认布局</button></div></header><main class="project-workspace mode-${ui.previewMode}" id="main-content" style="--chat-ratio:${ui.layout.chatRatio}%">${chat(project)}<div class="splitter splitter-chat" role="separator" tabindex="0" aria-label="调整对话与右侧宽度" aria-orientation="vertical" aria-valuemin="42" aria-valuemax="64" aria-valuenow="${Math.round(ui.layout.chatRatio)}" ${ui.previewMode === 'hidden' ? 'hidden' : ''}></div><div class="right-panel" id="right-panel" aria-label="项目内容" ${ui.previewMode === 'hidden' ? 'hidden' : ''}>${rightPanel(project)}</div></main></div></div>`;
}
function positionCurrent(scroll) {
  const card = scroll?.querySelector('.current-turn .decision-card, .current-turn .result-card');
  if (!scroll || !card) return;
  scroll.scrollTop = scroll.scrollHeight;
  if (card.offsetHeight >= scroll.clientHeight - 12) {
    scroll.scrollTop += card.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
  }
}

function render(force = false) {
  const routeInfo = parseRoute(); ui.projectId = routeInfo.id; ui.view = routeInfo.view;
  if (!routeInfo.id) { app.dataset.projectId = ''; app.innerHTML = home(); return; }
  const project = currentProject();
  if (!project) { app.dataset.projectId = ''; app.innerHTML = `${topBanner()}<main class="missing-project"><h1>项目未找到</h1><p>这个模拟项目不存在，或示例数据已重置。</p><a class="primary" href="#/">返回所有项目 →</a></main>`; return; }
  const sameProject = app.dataset.projectId === project.id;
  if (!sameProject || force) {
    app.innerHTML = projectShell(project); app.dataset.projectId = project.id;
    const chatScroll = document.getElementById('chat-scroll');
    positionCurrent(chatScroll);
    return;
  }
  app.querySelectorAll('.project-view-link').forEach((link) => {
    const active = link.getAttribute('href') === projectPath(project.id, ui.view);
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  app.querySelectorAll('.history-project').forEach((link) => {
    const active = link.getAttribute('href') === projectPath(project.id);
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  if (ui.previewMode === 'hidden') ui.previewMode = 'balanced';
  const workspace = document.querySelector('.project-workspace');
  workspace.className = `project-workspace mode-${ui.previewMode}`;
  const toggle = document.querySelector('[data-action="toggle-preview"]');
  toggle.textContent = '收起右侧'; toggle.setAttribute('aria-expanded', 'true');
  const panel = document.getElementById('right-panel'); panel.innerHTML = rightPanel(project);
  panel.hidden = false;
  document.querySelector('.splitter-chat').hidden = ui.previewMode === 'expanded';
  document.getElementById('panel-title')?.focus({ preventScroll: true });
}
function route() { if (ui.modal) closeModal(); render(false); }

function switcherRows() {
  const matched = projects().filter((p) => p.title.toLowerCase().includes(ui.switchSearch.toLowerCase()));
  const list = ui.modal === 'all' ? matched : matched.slice(0, 8);
  return list.length ? list.map((p) => `<button type="button" class="switch-row ${p.id === ui.projectId ? 'selected' : ''}" data-action="choose-project" data-project="${escapeHtml(p.id)}"><span class="project-monogram">${escapeHtml(p.short)}</span><span><b>${escapeHtml(p.title)}</b><small>${phaseLabel[p.phase]} ${p.version ? `· ${escapeHtml(p.version)}` : ''}</small></span>${p.id === ui.projectId ? '<em>当前项目</em>' : '<span class="switch-arrow">↗</span>'}</button>`).join('') : '<p class="switch-empty">没有找到项目。可以查看所有项目或新建项目。</p>';
}
function openModal(kind) {
  ui.modal = kind; ui.switchSearch = ''; ui.modalTrigger = document.activeElement;
  const isProjects = kind === 'switch' || kind === 'all';
  const title = kind === 'all' ? '所有项目' : kind === 'switch' ? '切换项目' : '关于这个原型';
  const root = document.createElement('div'); root.id = 'dialog-root';
  root.innerHTML = `<div class="modal-backdrop" data-action="close-modal"></div><div class="modal-card" role="dialog" aria-modal="true" aria-label="${title}"><div class="modal-head"><h2>${title}</h2><button type="button" data-action="close-modal" aria-label="关闭">×</button></div>${isProjects ? `<label class="switch-search"><span class="sr-only">搜索项目名称</span><input id="switch-search" placeholder="搜索项目名称" autocomplete="off"></label><p class="modal-label">${kind === 'all' ? '你的项目' : '最近项目'}</p><div id="switch-list">${switcherRows()}</div><div class="modal-foot"><span>项目在当前浏览器内模拟保存</span><button type="button" data-action="new-from-switch">＋ 新建项目</button></div>` : `<p>这是独立的设计评审原型。项目、状态、应用预览和检查结果均由当前浏览器模拟；不会调用真实后端或模型。</p><p>从首页写下需求，或点一张样例卡。进入项目后可体验对话、确认、预览与状态视图。</p><div class="modal-foot"><button class="primary" type="button" data-action="close-modal">我知道了</button></div>`}</div>`;
  document.body.append(root); (isProjects ? root.querySelector('input') : root.querySelector('button'))?.focus();
}
function closeModal() { document.getElementById('dialog-root')?.remove(); ui.modal = ''; ui.modalTrigger?.focus(); ui.modalTrigger = null; }
function toast(message) {
  document.querySelector('.toast')?.remove();
  const element = document.createElement('div'); element.className = 'toast'; element.setAttribute('role', 'status'); element.textContent = message;
  document.body.append(element); window.setTimeout(() => element.remove(), 3200);
}

app.addEventListener('submit', (event) => {
  if (event.target.id === 'create-form') {
    event.preventDefault();
    const request = document.getElementById('create-request').value.trim();
    const title = document.getElementById('create-title').value;
    const error = document.getElementById('create-error');
    if (request.length < 8) { error.textContent = '请用至少 8 个字描述希望做出的结果。'; error.hidden = false; document.getElementById('create-request').focus(); return; }
    error.hidden = true; ui.homeEmpty = false; const project = mockBackend.createProject({ title, request }); navigate(projectPath(project.id));
  }
  if (event.target.id === 'expense-form') {
    event.preventDefault();
    const name = document.getElementById('expense-name').value.trim();
    const amount = Number(document.getElementById('expense-amount').value);
    const category = document.getElementById('expense-category').value;
    if (!name || !Number.isFinite(amount) || amount <= 0) return;
    mockBackend.addExpense(ui.projectId, { name, amount, category });
    document.getElementById('right-panel').innerHTML = rightPanel(currentProject());
    document.getElementById('expense-name')?.focus();
  }
});

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const action = button.dataset.action;
  if (action === 'close-modal') { closeModal(); return; }
  if (action === 'switch-project') { openModal('switch'); return; }
  if (action === 'all-projects') { openModal('all'); return; }
  if (action === 'jump-history') {
    const scroll = document.getElementById('chat-scroll');
    if (!scroll) return;
    const showHistory = button.textContent.startsWith('查看历史');
    if (showHistory) scroll.scrollTop = 0; else positionCurrent(scroll);
    button.textContent = showHistory ? '回到当前 ↓' : '查看历史 ↑';
    return;
  }
  if (action === 'reset-layout') { resetLayout(); ui.previewMode = 'balanced'; document.querySelector('.project-workspace').className = 'project-workspace mode-balanced'; document.querySelector('.splitter-chat').hidden = false; document.getElementById('right-panel').hidden = false; document.querySelector('[data-action="toggle-preview"]').textContent = '收起右侧'; document.querySelector('[data-action="toggle-preview"]').setAttribute('aria-expanded', 'true'); document.querySelector('[data-action="expand-preview"]').textContent = '放大右侧'; return; }
  if (action === 'toggle-preview') {
    ui.previewMode = ui.previewMode === 'hidden' ? 'balanced' : 'hidden';
    const workspace = document.querySelector('.project-workspace');
    workspace.className = `project-workspace mode-${ui.previewMode}`;
    document.getElementById('right-panel').hidden = ui.previewMode === 'hidden';
    document.querySelector('.splitter-chat').hidden = ui.previewMode === 'hidden';
    button.textContent = ui.previewMode === 'hidden' ? '打开右侧' : '收起右侧';
    button.setAttribute('aria-expanded', String(ui.previewMode !== 'hidden'));
    return;
  }
  if (action === 'expand-preview') {
    ui.previewMode = ui.previewMode === 'expanded' ? 'balanced' : 'expanded';
    document.querySelector('.project-workspace').className = `project-workspace mode-${ui.previewMode}`;
    document.querySelector('.splitter-chat').hidden = ui.previewMode === 'expanded';
    button.textContent = ui.previewMode === 'expanded' ? '恢复比例' : '放大右侧';
    return;
  }
  if (action === 'help') { openModal('help'); return; }
  if (action === 'choose-project') { const id = button.dataset.project; closeModal(); navigate(projectPath(id)); return; }
  if (action === 'new-from-switch') { closeModal(); navigate('#/'); requestAnimationFrame(() => document.getElementById('create-request')?.focus()); return; }
  if (action === 'reset-demo') { mockBackend.resetDemo(); closeModal(); ui.homeSearch = ''; ui.homeEmpty = false; navigate('#/'); render(true); return; }
  if (action === 'toggle-empty') { ui.homeEmpty = !ui.homeEmpty; ui.homeSearch = ''; navigate('#/'); render(true); return; }
  if (action === 'focus-create') { document.getElementById('create-request')?.focus(); return; }
  if (action === 'new-project') { navigate('#/'); requestAnimationFrame(() => document.getElementById('create-request')?.focus()); return; }
  if (action === 'clear-side-search') { ui.sideSearch = ''; const input = document.getElementById('side-search'); input.value = ''; document.getElementById('history-list').innerHTML = historyRows(); input.focus(); return; }
  if (action === 'clear-search') { ui.homeSearch = ''; const input = document.getElementById('home-search'); input.value = ''; document.getElementById('project-list').innerHTML = projectRows(projects()); input.focus(); return; }
  if (action === 'example') {
    const example = starterExamples[button.dataset.example]; if (!example) return;
    document.getElementById('create-request').value = example.request;
    document.getElementById('create-title').value = example.title;
    document.getElementById('request-count').textContent = `${document.getElementById('create-request').value.length} / 5000`;
    document.getElementById('create-request').focus(); return;
  }
  if (action === 'confirm-clarify') { const choice = document.querySelector('input[name="clarify-choice"]:checked')?.value; if (!choice) return; mockBackend.updateProject(ui.projectId, { phase: 'plan', decision: choice }); render(true); return; }
  if (action === 'save-plan-note') { mockBackend.updateProject(ui.projectId, { planNote: document.getElementById('plan-note').value.trim() }); button.textContent = '已保留修改意见'; return; }
  if (action === 'confirm-plan') { mockBackend.updateProject(ui.projectId, { phase: 'building', planNote: document.getElementById('plan-note').value.trim() }); render(true); return; }
  if (action === 'finish-build') { mockBackend.updateProject(ui.projectId, { phase: 'built', version: 'v1' }); render(true); return; }
  if (action === 'preview-tab') { ui.previewTab[ui.projectId] = button.dataset.tab; document.getElementById('right-panel').innerHTML = rightPanel(currentProject()); return; }
  if (action === 'code-file') { ui.codeFile[ui.projectId] = button.dataset.file; document.getElementById('right-panel').innerHTML = rightPanel(currentProject()); return; }
  if (action === 'doc-tab') { ui.docTab[ui.projectId] = button.dataset.tab; document.getElementById('right-panel').innerHTML = rightPanel(currentProject()); return; }
  if (action === 'test-log') { ui.logOpen = !ui.logOpen; document.getElementById('right-panel').innerHTML = rightPanel(currentProject()); return; }
  if (action === 'go-workbench') { navigate(projectPath(ui.projectId)); return; }
  if (action === 'open-tests') { navigate(projectPath(ui.projectId, 'tests')); return; }
  if (action === 'open-code') { ui.previewTab[ui.projectId] = 'code'; ui.codeFile[ui.projectId] = button.dataset.file || 'src/App.tsx'; navigate(projectPath(ui.projectId)); return; }
  if (action === 'draft-submit') { const field = document.getElementById('chat-draft'); if (!field.value.trim()) { field.focus(); return; } toast('草稿已保留在当前浏览器；没有调用模型。'); return; }
});
document.addEventListener('input', (event) => {
  if (event.target.id === 'side-search') { ui.sideSearch = event.target.value; document.getElementById('history-list').innerHTML = historyRows(); }
  if (event.target.id === 'home-search') { ui.homeSearch = event.target.value; document.getElementById('project-list').innerHTML = projectRows(projects().filter((p) => p.title.toLowerCase().includes(ui.homeSearch.toLowerCase()))); }
  if (event.target.id === 'switch-search') { ui.switchSearch = event.target.value; document.getElementById('switch-list').innerHTML = switcherRows(); }
  if (event.target.id === 'create-request') { document.getElementById('request-count').textContent = `${event.target.value.length} / 5000`; }
  if (event.target.id === 'chat-draft') { mockBackend.updateProject(ui.projectId, { draft: event.target.value }); }
  if (event.target.name === 'clarify-choice') { document.querySelector('[data-action="confirm-clarify"]').disabled = false; }
});
document.addEventListener('change', (event) => {
  if (event.target.name === 'clarify-choice') document.querySelector('[data-action="confirm-clarify"]').disabled = false;
});
document.addEventListener('pointerdown', (event) => {
  const handle = event.target.closest('.splitter'); if (!handle) return;
  const kind = handle.classList.contains('splitter-sidebar') ? 'sidebar' : 'chat';
  const startPixels = kind === 'sidebar' ? ui.layout.sidebar : document.querySelector('.chat-column').getBoundingClientRect().width;
  ui.drag = { kind, x: event.clientX, startPixels, previous: { ...ui.layout } };
  handle.classList.add('dragging'); handle.setPointerCapture(event.pointerId); event.preventDefault();
});
document.addEventListener('pointermove', (event) => {
  if (!ui.drag) return;
  updateSplitter(ui.drag.kind, ui.drag.startPixels + event.clientX - ui.drag.x);
});
document.addEventListener('pointerup', () => {
  if (!ui.drag) return;
  document.querySelector('.splitter.dragging')?.classList.remove('dragging'); ui.drag = null; applyLayout(true);
});
document.addEventListener('pointercancel', () => {
  if (!ui.drag) return;
  ui.layout = ui.drag.previous; ui.drag = null; document.querySelector('.splitter.dragging')?.classList.remove('dragging'); applyLayout();
});
document.addEventListener('dblclick', (event) => { if (event.target.closest('.splitter')) resetLayout(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && ui.drag) { ui.layout = ui.drag.previous; ui.drag = null; document.querySelector('.splitter.dragging')?.classList.remove('dragging'); applyLayout(); return; }
  const handle = event.target.closest('.splitter'); if (!handle) return;
  const kind = handle.classList.contains('splitter-sidebar') ? 'sidebar' : 'chat';
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const width = document.querySelector('.project-workspace')?.clientWidth || 1;
  const current = kind === 'sidebar' ? ui.layout.sidebar : document.querySelector('.chat-column').getBoundingClientRect().width;
  const lower = kind === 'sidebar' ? 180 : 440;
  const upper = kind === 'sidebar' ? 280 : width - 400;
  const next = event.key === 'Home' ? lower : event.key === 'End' ? upper : current + (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 48 : 16);
  updateSplitter(kind, next); applyLayout(true);
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && ui.modal) { event.preventDefault(); closeModal(); } });
window.addEventListener('hashchange', route);
if (!location.hash) location.hash = '#/'; else route();



