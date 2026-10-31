// 仅供界面评审的浏览器内模拟数据层；不调用产品 API、模型或发布服务。
const STORAGE_KEY = 'myatom-design-prototype-v7';

const seed = {
  projects: [
    {
      id: 'weekly-spend', title: '每周支出记录', short: '周', phase: 'built',
      request: '做一个每周支出记录工具，能添加金额、分类和备注，刷新后记录仍在。',
      known: ['记录每笔支出的金额与分类', '刷新后仍可查看记录', '面向日常个人记账'],
      decision: '先用访客身份', version: 'v3', updated: '今天 10:46', questionKind: 'account',
      expenses: [
        { id: 'e1', name: '午餐', category: '餐饮', amount: 28 },
        { id: 'e2', name: '地铁', category: '交通', amount: 4 },
        { id: 'e3', name: '咖啡', category: '餐饮', amount: 22 }
      ],
      draft: ''
    },
    {
      id: 'pomodoro', title: '番茄钟待办', short: '番', phase: 'clarify',
      request: '做一个番茄钟待办，任务完成状态与专注次数都要保存。',
      known: ['任务与专注计时', '完成状态和次数需要保存'],
      decision: '', version: '', updated: '今天 09:18', expenses: [], draft: '', questionKind: 'nextRound'
    },
    {
      id: 'weekend-plan', title: '城市周末计划', short: '行', phase: 'plan',
      request: '帮我做一个周末行程网页，能按时间排列活动并手动调整顺序。',
      known: ['按时间呈现活动', '允许手动调整顺序'],
      decision: '先只做单人行程', version: '', updated: '昨天 17:32', expenses: [], draft: '', questionKind: 'scope'
    }
  ]
};

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && Array.isArray(saved.projects)) return saved;
  } catch (_) { /* 使用演示初始数据 */ }
  return clone(seed);
}

let state = load();
function persist() { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
function lookup(id) { return state.projects.find((project) => project.id === id); }

export const mockBackend = {
  listProjects() { return clone(state.projects); },
  getProject(id) { const project = lookup(id); return project ? clone(project) : null; },
  createProject({ title, request }) {
    const cleanTitle = title.trim() || request.trim().replace(/^(帮我)?做一个|^我想(做|要)一个/, '').slice(0, 12) || '未命名项目';
    const isDate = /日期|今天|年月日/.test(request);
    const isTimer = /番茄|计时|倒计时/.test(request);
    const specifiesStorage = /保存|刷新后|持久/.test(request);
    const project = {
      id: `demo-${Date.now().toString(36)}`, title: cleanTitle, short: cleanTitle.slice(0, 1),
      phase: 'clarify', request: request.trim(),
      known: isDate ? ['显示今天的年月日', '中文单页网页'] : [request.trim()],
      decision: '', version: '', updated: '刚刚', expenses: [], draft: '',
      questionKind: isDate ? 'timezone' : isTimer ? 'nextRound' : specifiesStorage ? 'account' : 'storage'
    };
    state.projects.unshift(project); persist(); return clone(project);
  },
  updateProject(id, patch) {
    const project = lookup(id); if (!project) return null;
    Object.assign(project, patch, { updated: '刚刚' }); persist(); return clone(project);
  },
  addExpense(id, expense) {
    const project = lookup(id); if (!project) return null;
    project.expenses.unshift({ ...expense, id: `e-${Date.now().toString(36)}` });
    persist(); return clone(project);
  },
  resetDemo() { state = clone(seed); persist(); }
};
