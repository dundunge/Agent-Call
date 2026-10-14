/* AI Team deterministic simulator. No network, credentials, or model inference. */
(function (scope, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else scope.AITeamSimulation = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const TEAM = [
    { id: 'root', parent: null, level: 0, family: 'gpt', model: 'GPT-6.1-Sol', name: '主控', role: '拆解与汇总', objective: '拆解用户目标，协调各分支并记录最终验收。' },
    { id: 'deepseek-pro', parent: 'root', level: 1, family: 'deepseek', model: 'DeepSeek V4 Pro', name: '研究', role: '方案研究', objective: '分析 V1 路线，委派同组 Flash 抽取证据。' },
    { id: 'deepseek-flash', parent: 'deepseek-pro', level: 2, family: 'deepseek', model: 'DeepSeek V4 Flash', name: '证据抽取', role: '快速执行', objective: '读取模拟资料，整理方案能力与限制。' },
    { id: 'grok', parent: 'root', level: 1, family: 'grok', model: 'Grok', name: '风险', role: '反例审查', objective: '审查过度承诺、未知送达与多线程写入冲突。' },
    { id: 'grok-worker', parent: 'grok', level: 2, family: 'grok', model: 'Grok', name: '反例检查', role: '独立检查', objective: '以另一个 Grok 会话运行预设反例检查。' },
    { id: 'gpt-sol', parent: 'root', level: 1, family: 'gpt', model: 'GPT-6.1-Sol', name: '实现', role: '实现与验收', objective: '规划可交付功能，委派 Luna 复核验收条件。' },
    { id: 'gpt-luna', parent: 'gpt-sol', level: 2, family: 'gpt', model: 'GPT-6 Luna', name: '验收复核', role: '快速验证', objective: '检查层级、协议字段与完成门槛。' },
  ];
  const DEFAULT_PROMPT = '研究 AI Team 的 V1 方案，比较实现路线，给出可验证的项目成果。';
  const SCRIPT = [
    { kind: 'message', node: 'root', text: '我会拆成研究、风险和实现三个一级线程。每个一级线程可以继续委派一个同组模型；结果先回收给父线程，再由主控汇总。' },
    { kind: 'dispatch', node: 'root', target: 'deepseek-pro', text: '研究 Agent Call、LangGraph、Microsoft Agent Framework 与 DSH 的分工。请委派同组 Flash 整理证据。' },
    { kind: 'dispatch', node: 'root', target: 'grok', text: '审查可行性与过度承诺。请创建同组 Grok 子线程检查反例。' },
    { kind: 'dispatch', node: 'root', target: 'gpt-sol', text: '给出前端与控制面的实施路线。请委派 GPT-6 Luna 复核验收。' },
    { kind: 'message', node: 'deepseek-pro', text: '研究范围已收到。我负责路线比较，Flash 负责资料抽取；两者分别保留独立会话与 requestId。' },
    { kind: 'message', node: 'grok', text: '检查三个常见误判：送达被当成完成、完成被当成验收、超时后重复派发。' },
    { kind: 'dispatch', node: 'deepseek-pro', target: 'deepseek-flash', text: '从模拟资料中抽取四个组件的职责，标记尚未接入的能力。' },
    { kind: 'dispatch', node: 'grok', target: 'grok-worker', text: '用独立会话检查未知送达、重试和共享工作区三个反例。' },
    { kind: 'dispatch', node: 'gpt-sol', target: 'gpt-luna', text: '复核三级线程结构；确认二级派发保持模型家族，并检查最终验收条件。' },
    { kind: 'tool', node: 'deepseek-flash', tool: 'read_fixture', text: '读取 4 份模拟组件说明。', output: 'agent-call: transport\nLangGraph: durable workflow\nAgent Framework: optional runtime\nDSH: session UI + worker' },
    { kind: 'tool', node: 'grok-worker', tool: 'check_counterexamples', text: '运行 3 个预设反例。', output: 'accepted ≠ completed\ncompleted ≠ caller acceptance\nunknown → reconcile original request' },
    { kind: 'tool', node: 'gpt-luna', tool: 'validate_team', text: '核对父子关系与协议字段。', output: '7 threads / max depth 2\n3 same-family child routes\nrequestId + parentThreadId present' },
    { kind: 'result', node: 'deepseek-flash', text: '已整理四项职责与对应限制。当前网页是模拟器；真实模型质量和原生会话可见性仍需单独验证。', artifact: 'component-matrix.md' },
    { kind: 'collect', node: 'deepseek-pro', target: 'deepseek-flash', text: '收回 Flash 的结构化结果，核对职责表与限制字段。' },
    { kind: 'result', node: 'deepseek-pro', text: '建议 V1 先交付 DSH 式会话体验与 Agent Call 协议边界。后续由 LangGraph 管理长任务恢复，DSH 承载 DeepSeek 原生会话。', artifact: 'research.md' },
    { kind: 'result', node: 'grok-worker', text: '三条反例已确认：送达超时要停止盲重试，结果完成不自动验收，共享文件必须有唯一写入者。', artifact: 'counterexamples.md' },
    { kind: 'collect', node: 'grok', target: 'grok-worker', text: '收回同组 Grok 子线程结果，保留反例与限制。' },
    { kind: 'result', node: 'grok', text: '公开演示应使用预设数据；真实接入通过本地受控适配器，公开站点不持有模型凭据。', artifact: 'risk-review.md' },
    { kind: 'result', node: 'gpt-luna', text: '三级关系通过；二级派发保持同组；最终验收必须等三个一级线程完成，并记录证据。', artifact: 'acceptance-checks.md' },
    { kind: 'collect', node: 'gpt-sol', target: 'gpt-luna', text: '收回 Luna 的验收条件，核对父子层级与协议标识。' },
    { kind: 'result', node: 'gpt-sol', text: '实现路线：会话树与逐步模拟 → 协议事件层 → 本地 Agent Call 接入 → LangGraph 恢复与人工验收。', artifact: 'implementation.md' },
    { kind: 'join', node: 'root', text: '三个一级线程已完成。逐一核对分支回执与模拟产物，保留每个线程的独立结果。' },
    { kind: 'message', node: 'root', text: '研究、风险和实现结论已合并。V1 公开演示的验收范围是层级派发、过程可查看和结果回收。' },
    { kind: 'result', node: 'root', text: '模拟执行完成，等待最终验收。请检查团队拓扑、子线程结果与协议事件，再记录通过。', artifact: 'team-report.md' },
  ];
  const clone = (v) => JSON.parse(JSON.stringify(v));

  class Simulator {
    constructor(options = {}) {
      this.clock = options.clock || (() => new Date().toISOString());
      this.runNumber = 0;
      this.reset();
    }
    reset(prompt = DEFAULT_PROMPT, mode = 'success') {
      if (!['success', 'unknown'].includes(mode)) throw new Error('Unknown scenario');
      this.runNumber += 1;
      this.runId = `mock-${this.runNumber}`;
      this.prompt = String(prompt).trim().slice(0, 1200) || DEFAULT_PROMPT;
      this.mode = mode;
      this.cursor = 0;
      this.phase = 'ready';
      this.events = [];
      this.artifacts = [];
      this.blockedNode = null;
      this.nodes = TEAM.map((n) => ({ ...clone(n), state: 'planned', spawned: n.id === 'root', delivery: n.id === 'root' ? 'simulated' : 'not_sent', outcome: 'not_started', acceptance: 'not_run', requestId: `${this.runId}:${n.id}:1`, messages: [], result: null }));
      this.node('root').messages.push({ kind: 'user', text: this.prompt, at: this.clock() });
      return this;
    }
    node(id) {
      const found = this.nodes.find((n) => n.id === id);
      if (!found) throw new Error(`Thread not found: ${id}`);
      return found;
    }
    emit(kind, node, data) {
      const event = { seq: this.events.length + 1, kind, node: node.id, requestId: node.requestId, runId: this.runId, simulated: true, at: this.clock(), ...data };
      this.events.push(event);
      node.messages.push(event);
      return event;
    }
    step() {
      if (['blocked', 'review', 'accepted'].includes(this.phase)) return false;
      const action = SCRIPT[this.cursor];
      if (!action) return false;
      const node = this.node(action.node);
      this.phase = 'running';
      this.node('root').state = 'running';
      this.node('root').outcome = 'in_progress';
      if (action.kind === 'dispatch') {
        const child = this.node(action.target);
        if (child.parent !== node.id) throw new Error('Invalid parent route');
        if (child.level === 2 && child.family !== node.family) throw new Error('Secondary children must use the parent family');
        if (child.spawned) throw new Error('Duplicate dispatch');
        child.spawned = true;
        child.state = 'running';
        child.delivery = 'simulated';
        child.outcome = 'in_progress';
        node.state = 'waiting';
        child.messages.push({ kind: 'user', text: action.text, from: node.id, at: this.clock() });
        this.emit('dispatch', node, { text: action.text, target: child.id, childRequestId: child.requestId, delivery: 'simulated' });
        if (this.mode === 'unknown' && child.id === 'deepseek-flash') {
          child.state = 'blocked'; child.delivery = 'unknown'; child.outcome = 'unknown';
          this.blockedNode = child.id; this.phase = 'blocked';
          this.emit('delivery_unknown', child, { text: '模拟派发超时。原 requestId 已保留；停止后续推进，等待送达对账。', delivery: 'unknown' });
        }
      } else if (action.kind === 'collect') {
        const child = this.node(action.target);
        if (child.outcome !== 'completed') throw new Error('Cannot collect an unfinished child');
        child.acceptance = 'passed';
        this.emit('collect', node, { text: action.text, target: child.id, childRequestId: child.requestId, evidence: [child.result] });
      } else if (action.kind === 'join') {
        const children = this.nodes.filter((n) => n.parent === node.id);
        if (children.some((n) => n.outcome !== 'completed')) throw new Error('Join requires all branches to complete');
        children.forEach((n) => { n.acceptance = 'passed'; });
        node.state = 'running';
        this.emit('join', node, { text: action.text, targets: children.map((n) => n.id), evidence: children.map((n) => n.result) });
      } else if (action.kind === 'result') {
        const children = this.nodes.filter((n) => n.parent === node.id);
        if (children.some((n) => n.outcome !== 'completed')) throw new Error('A parent cannot complete before its children');
        node.state = 'completed'; node.outcome = 'completed'; node.result = action.text;
        this.artifacts.push({ name: action.artifact, node: node.id, simulated: true, content: `# ${node.model} · ${node.role}\n\n> 预设模拟产物，不是模型推理结果。\n\n${action.text}\n\nrequestId: ${node.requestId}\nparentThreadId: ${node.parent || 'none'}\n` });
        this.emit('result', node, { text: action.text, artifact: action.artifact, outcome: 'completed' });
        if (node.id === 'root') this.phase = 'review';
      } else {
        node.state = 'running';
        this.emit(action.kind, node, { text: action.text, ...(action.tool ? { tool: action.tool, output: action.output } : {}) });
      }
      this.cursor += 1;
      return true;
    }
    reconcile() {
      if (this.phase !== 'blocked' || !this.blockedNode) throw new Error('No uncertain delivery to reconcile');
      const node = this.node(this.blockedNode);
      const requestId = node.requestId;
      node.state = 'running'; node.delivery = 'simulated'; node.outcome = 'in_progress';
      this.emit('reconciled', node, { text: '用原 requestId 查询模拟回执：已送达。恢复原尝试，没有重新派发。', reconciledRequestId: requestId, delivery: 'simulated' });
      this.blockedNode = null; this.phase = 'running';
      return requestId;
    }
    accept(evidence) {
      if (this.phase !== 'review') throw new Error('Final acceptance requires an observed root result');
      if (!Array.isArray(evidence) || evidence.length < 3 || evidence.some((x) => typeof x !== 'string' || !x.trim())) throw new Error('Three evidence checks are required');
      if (this.nodes.some((n) => n.outcome !== 'completed')) throw new Error('All threads must be complete');
      const root = this.node('root');
      root.acceptance = 'passed';
      this.emit('acceptance', root, { text: '主控最终验收已记录：层级关系、分支回收和协议证据通过模拟检查。', evidence: [...evidence], acceptance: 'passed' });
      this.phase = 'accepted';
    }
    snapshot() {
      return clone({ protocol: 'agent-call/v1', mode: 'mock', simulated: true, runId: this.runId, prompt: this.prompt, scenario: this.mode, cursor: this.cursor, totalSteps: SCRIPT.length, phase: this.phase, nodes: this.nodes, events: this.events, artifacts: this.artifacts });
    }
  }
  return { Simulator, TEAM: clone(TEAM), totalSteps: SCRIPT.length, DEFAULT_PROMPT };
});
