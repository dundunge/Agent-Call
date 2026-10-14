(function () {
  'use strict';
  const { Simulator, DEFAULT_PROMPT, totalSteps } = window.AITeamSimulation;
  const sim = new Simulator();
  const state = { selected: 'root', view: 'chat', inspector: 'task', playing: false, timer: null, eventFilter: 'all', folded: new Set(), revision: 0 };
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const escape = (v) => String(v ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const icon = (family) => `<i class="provider-icon ${family}">${({ gpt: 'G', deepseek: 'D', grok: 'X' })[family]}</i>`;
  const labels = { planned: '待派发', running: '运行中', waiting: '等子线程', completed: '已完成', blocked: '待对账' };
  const times = (at) => new Date(at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const badge = (node) => `<span class="tag ${node.state}">${labels[node.state]}</span>`;

  function toast(message) {
    $('#toast').textContent = message; $('#toast').classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').classList.remove('show'), 2500);
  }
  function ancestors(node) {
    const chain = [node];
    while (chain[0].parent) chain.unshift(sim.node(chain[0].parent));
    return chain;
  }
  function renderTree() {
    $('#thread-counter').textContent = `${sim.nodes.filter((n) => n.spawned).length} / ${sim.nodes.length}`;
    $('#thread-tree').innerHTML = sim.nodes.filter((n) => !ancestors(n).slice(0, -1).some((a) => state.folded.has(a.id))).map((n) => {
      const hasChildren = sim.nodes.some((x) => x.parent === n.id);
      return `<div class="thread-wrap"><button class="thread-node ${n.state} ${state.selected === n.id ? 'selected' : ''}" data-thread="${n.id}" data-level="${n.level}" style="--level:${n.level}" role="treeitem" aria-level="${n.level + 1}" aria-selected="${state.selected === n.id}" ${hasChildren ? `aria-expanded="${!state.folded.has(n.id)}"` : ''}>${icon(n.family)}<span class="thread-text"><span class="thread-title">${escape(n.model)}</span><span class="thread-meta">${n.level === 0 ? '主控' : `${n.level} 级 · ${n.name}`} · ${labels[n.state]}</span></span><i class="dot ${n.state}"></i></button>${hasChildren ? `<button class="fold-control" data-fold="${n.id}" aria-label="${state.folded.has(n.id) ? '展开' : '收起'}${escape(n.model)}子线程">${state.folded.has(n.id) ? '›' : '⌄'}</button>` : ''}</div>`;
    }).join('');
  }
  function renderHeader() {
    const node = sim.node(state.selected);
    $('#breadcrumbs').innerHTML = ancestors(node).map((n, i) => `${i ? '<span class="crumb-sep">/</span>' : ''}<button class="crumb ${n.id === node.id ? 'current' : ''}" data-thread="${n.id}">${escape(n.name)}</button>`).join('') + `<span class="tag">${node.level === 0 ? '主控' : `L${node.level}`}</span>`;
    $$('.session-tab').forEach((b) => { b.classList.toggle('active', b.dataset.view === state.view); b.setAttribute('aria-selected', b.dataset.view === state.view); });
    $$('.panel-nav .nav-button').forEach((b) => b.classList.toggle('active', b.dataset.view === state.view));
    $('#event-counter').textContent = sim.events.length;
    $('#run-progress').textContent = `${sim.cursor} / ${totalSteps}`;
    const text = sim.phase === 'ready' ? '准备就绪' : sim.phase === 'blocked' ? '送达不明 · 已停止' : sim.phase === 'review' ? '执行完成 · 待验收' : sim.phase === 'accepted' ? '模拟已验收' : state.playing ? '正在模拟' : '已暂停';
    $('#run-status').textContent = text;
    $('#run-dot').className = `dot ${sim.phase === 'blocked' ? 'blocked' : ['review', 'accepted'].includes(sim.phase) ? 'completed' : state.playing ? 'running' : 'waiting'}`;
    $('#progress-fill').style.width = `${sim.cursor / totalSteps * 100}%`;
    $('#play-run').textContent = state.playing ? 'Ⅱ 暂停' : sim.phase === 'review' ? '核对并验收' : sim.phase === 'accepted' ? '↺ 重新演示' : sim.phase === 'blocked' ? '等待对账' : sim.cursor ? '▶ 继续' : '▶ 运行演示';
    $('#play-run').disabled = sim.phase === 'blocked';
    $('#step-run').disabled = ['blocked', 'review', 'accepted'].includes(sim.phase) || state.playing;
    $('#scenario-select').disabled = sim.cursor > 0;
    const notice = $('#run-notice');
    notice.hidden = !['blocked', 'review'].includes(sim.phase);
    notice.innerHTML = sim.phase === 'blocked' ? '送达超时，保留原请求。<button class="thread-link" data-action="reconcile">查询原 requestId 并恢复</button>' : sim.phase === 'review' ? '全部分支已回收。<button class="thread-link" data-action="accept">核对模拟证据并记录验收</button>' : '';
  }
  function toolCard(event, node) {
    const target = event.target ? sim.node(event.target) : null;
    const title = ({ dispatch: 'agent_call.send', collect: 'agent_call.collect', join: 'agent_call.join', tool: event.tool, delivery_unknown: 'delivery.unknown', reconciled: 'delivery.reconcile' })[event.kind];
    const payload = { protocol: 'agent-call/v1', kind: event.kind, requestId: event.requestId, ...(target ? { recipient: target.id, recipientRequestId: event.childRequestId } : {}), simulated: true };
    return `<details class="tool-card" data-key="event-${event.seq}" ${['dispatch', 'delivery_unknown', 'reconciled'].includes(event.kind) ? 'open' : ''}><summary><span class="mono">${escape(title)}</span><span class="tag ${event.kind === 'delivery_unknown' ? 'blocked' : ''}">${event.kind === 'delivery_unknown' ? 'unknown' : '模拟'}</span></summary><div class="tool-body">${target ? `<div class="tool-route">${icon(node.family)}<span>${escape(node.model)}</span><span>→</span><button class="thread-link" data-thread="${target.id}">${escape(target.model)} ↗</button></div>` : ''}<p>${escape(event.text)}</p>${event.output ? `<pre>${escape(event.output)}</pre>` : `<details data-key="packet-${event.seq}"><summary>协议字段</summary><pre>${escape(JSON.stringify(payload, null, 2))}</pre></details>`}</div></details>`;
  }
  function renderChat() {
    const node = sim.node(state.selected);
    if (!node.messages.length) return `<div class="planned-message">${icon(node.family)}<h2>${escape(node.model)}</h2><p>${escape(node.objective)}</p><p>这是待派发的 ${node.level} 级线程。开始演示后，父线程会把任务送入这里。</p><button class="button subtle" data-thread="${node.parent || 'root'}">查看父线程</button></div>`;
    let html = node.messages.map((m) => {
      if (m.kind === 'user') return `<div class="user-row"><div class="user-bubble">${m.from ? `<span class="message-caption">来自 ${escape(sim.node(m.from).model)}<br></span>` : ''}${escape(m.text)}</div></div>`;
      if (['dispatch', 'collect', 'join', 'tool', 'delivery_unknown', 'reconciled'].includes(m.kind)) return toolCard(m, node);
      return `<article class="assistant-row"><div class="message-header">${icon(node.family)}<strong>${escape(node.model)}</strong><time>${times(m.at)}</time></div><p class="message-text">${escape(m.text)}</p>${m.artifact ? `<button class="thread-link message-caption" data-action="artifact" data-name="${escape(m.artifact)}">▤ ${escape(m.artifact)} · 模拟产物</button>` : ''}${m.kind === 'acceptance' ? '<span class="message-caption">✓ 验收证据已记录</span>' : ''}</article>`;
    }).join('');
    if (sim.phase === 'ready' && node.id === 'root') {
      html += `<div class="phase-note"><strong>一个主控，三条分支，七个独立线程。</strong><br>DeepSeek V4 Pro → V4 Flash；Grok → 同组 Grok；GPT-6.1-Sol → GPT-6 Luna。点击线程树可以查看每个会话。<br><button class="button info" data-action="play">▶ 开始层级派发演示</button></div>`;
    }
    if (state.playing && ['running', 'waiting'].includes(node.state)) html += '<div class="live-row"><i class="dot running"></i>模拟线程正在推进…</div>';
    if (node.id === 'root' && sim.phase === 'review') html += '<div class="phase-note"><strong>执行已完成，验收尚未开始。</strong><br>先核对三级拓扑、分支结果和协议事件，再记录最终验收。<br><button class="button primary" data-action="accept">核对并验收</button></div>';
    return `<div class="chat-inner">${html}</div>`;
  }
  function topologyNode(n) {
    return `<button class="topology-node ${n.state} ${n.id === state.selected ? 'selected' : ''}" data-thread="${n.id}">${icon(n.family)}<span class="topology-copy"><strong>${escape(n.model)}</strong><small>${n.level === 0 ? '主控' : `L${n.level} · ${n.name}`} · ${labels[n.state]}</small></span><i class="dot ${n.state}"></i></button>`;
  }
  function renderTopology() {
    const root = sim.node('root');
    return `<div class="view-title"><h1>团队拓扑</h1><p>一级分支由 GPT 主控派发；二级线程由各自父线程继续派发。点击节点打开独立会话。</p></div><div class="topology-root">${topologyNode(root)}<div class="topology-connector"></div><div class="topology-branches">${sim.nodes.filter((n) => n.level === 1).map((n) => { const child = sim.nodes.find((x) => x.parent === n.id); return `<div class="topology-branch">${topologyNode(n)}<div class="topology-connector"></div>${topologyNode(child)}<span class="topology-caption">同组 ${escape(n.family)} · 二级派发</span></div>`; }).join('')}</div></div><div class="team-stats"><span><b>${sim.nodes.filter((n) => n.spawned).length}</b>已创建</span><span><b>${sim.nodes.filter((n) => n.outcome === 'completed').length}</b>执行完成</span><span><b>2</b>最大 depth</span></div><div class="phase-note">所有节点均来自预设模拟脚本。灰色节点表示计划中的线程；运行时会逐个创建、执行并回收。</div>`;
  }
  function renderEvents() {
    const events = state.eventFilter === 'all' ? sim.events : sim.events.filter((e) => e.node === state.selected || e.target === state.selected);
    return `<div class="view-title"><h1>事件日志</h1><p>每条事件关联线程、父子关系与原 requestId。</p></div><div class="events-toolbar"><label class="sr-only" for="event-filter">事件范围</label><select id="event-filter"><option value="all" ${state.eventFilter === 'all' ? 'selected' : ''}>全部线程</option><option value="selected" ${state.eventFilter !== 'all' ? 'selected' : ''}>当前线程</option></select><button class="button subtle" data-action="export"><svg><use href="#i-download"/></svg>导出 JSON</button></div>${events.length ? events.map((e) => `<article class="event-row"><div class="event-heading"><span class="mono">#${String(e.seq).padStart(2, '0')}</span><span class="tag">${escape(e.kind)}</span><button class="thread-link" data-thread="${e.node}">${escape(sim.node(e.node).model)}</button><time>${times(e.at)}</time></div><p>${escape(e.text)}</p><details><summary class="mono">${escape(e.requestId)}</summary><pre class="json-code">${escape(JSON.stringify(e, null, 2))}</pre></details></article>`).join('') : '<div class="planned-message">还没有事件。运行演示或单步推进以生成轨迹。</div>'}`;
  }
  function renderArtifacts() {
    return `<div class="view-title"><h1>模拟产物</h1><p>按线程回收的预设结果，可下载查看；不代表真实模型输出。</p></div>${sim.artifacts.length ? sim.artifacts.map((a) => `<article class="artifact-card"><header><strong>▤ ${escape(a.name)}</strong><button class="button subtle" data-action="artifact" data-name="${escape(a.name)}">下载</button></header><p>${escape(sim.node(a.node).result)}</p><button class="thread-link" data-thread="${a.node}">${escape(sim.node(a.node).model)} · ${escape(sim.node(a.node).name)} ↗</button><details><summary>查看原文</summary><pre class="json-code">${escape(a.content)}</pre></details></article>`).join('') : '<div class="planned-message">线程完成后，模拟产物会出现在这里。</div>'}`;
  }
  function renderView(autoScroll = false) {
    const port = $('#view-content');
    const oldScroll = port.scrollTop;
    const atBottom = oldScroll >= port.scrollHeight - port.clientHeight - 100;
    const cardStates = [...port.querySelectorAll('details[data-key]')].map((el) => [el.dataset.key, el.open]);
    port.innerHTML = ({ chat: renderChat, topology: renderTopology, events: renderEvents, artifacts: renderArtifacts })[state.view]();
    if (autoScroll) cardStates.forEach(([key, opened]) => { const card = port.querySelector(`details[data-key="${key}"]`); if (card) card.open = opened; });
    if (autoScroll && state.view === 'chat' && atBottom) port.scrollTop = port.scrollHeight;
    else if (autoScroll) port.scrollTop = oldScroll;
    else port.scrollTop = 0;
  }
  function renderInspector() {
    $$('.inspector-tabs button').forEach((b) => { b.classList.toggle('active', b.dataset.inspector === state.inspector); b.setAttribute('aria-selected', b.dataset.inspector === state.inspector); });
    const node = sim.node(state.selected);
    let html;
    if (state.inspector === 'architecture') {
      html = `<div class="inspect-model"><strong>V1 分工</strong><span class="tag">演示 + 控制面</span></div><p class="inspect-text">前端复用 DSH 主题与三栏会话布局。层级模拟运行在浏览器；真实 Agent 接入由本地适配器承载。</p><div class="arch-component"><strong>Agent Call</strong><p>优先复用的通信协议与原生会话桥：requestId、真实会话引用、送达与结果收集。</p><span class="tag">现有基座</span></div><div class="arch-component"><strong>LangGraph</strong><p>后续工作流权威：任务图、检查点、暂停恢复与人工验收。当前模拟器未调用 LangGraph。</p><span class="tag">下一阶段</span></div><div class="arch-component"><strong>Microsoft Agent Framework</strong><p>可选执行运行时与企业集成适配器，映射到统一协议；不与 LangGraph 争夺顶层任务状态。</p><span class="tag">可选适配</span></div><div class="arch-component"><strong>DSH</strong><p>复用 UI 设计；真实接入时承载 DeepSeek 的原生会话、工具与同组子线程。</p><span class="tag">UI 已复用 · 后端待接入</span></div><div class="attribution">主题 CSS 来自 <a href="https://github.com/deepseek-ai/deepseek-harness" target="_blank" rel="noopener">DeepSeek Harness</a> (MIT)，保留 <a href="vendor/DSH-LICENSE.txt" target="_blank">许可证</a>。<br>AI Team 的层级模拟器为本项目实现。</div>`;
    } else if (state.inspector === 'protocol') {
      const packet = { protocol: 'agent-call/v1', kind: 'request', taskId: `${sim.runId}:${node.id}`, attemptId: '1', requestId: node.requestId, parentThreadId: node.parent, provider: node.family, model: node.model, recipientTaskRef: node.spawned ? `mock://${sim.runId}/${node.id}` : null, workspace: 'demo://workspace', objective: node.objective, allowedActions: ['simulate'], simulated: true };
      html = `<div class="inspect-title">AGENT CALL / V1</div><p class="inspect-text">独立请求与会话引用。mock:// 引用只对应本页模拟线程。</p><pre class="json-code">${escape(JSON.stringify(packet, null, 2))}</pre><div class="state-grid"><div class="state-row"><span>送达</span><code>${escape(node.delivery)}</code></div><div class="state-row"><span>执行</span><code>${escape(node.outcome)}</code></div><div class="state-row"><span>调用方验收</span><code>${escape(node.acceptance)}</code></div></div><button class="button subtle" data-action="export">导出完整模拟记录</button>`;
    } else {
      const children = sim.nodes.filter((n) => n.parent === node.id);
      html = `<div class="inspect-model">${icon(node.family)}<div><strong>${escape(node.model)}</strong><small>${node.level === 0 ? '主控' : `${node.level} 级线程`} · ${escape(node.role)}</small></div>${badge(node)}</div><div class="inspect-title">任务目标</div><p class="inspect-text">${escape(node.objective)}</p><div class="inspect-title">运行状态</div><div class="state-grid"><div class="state-row"><span>送达</span><code>${escape(node.delivery)}</code></div><div class="state-row"><span>执行</span><code>${escape(node.outcome)}</code></div><div class="state-row"><span>调用方验收</span><code>${escape(node.acceptance)}</code></div><div class="state-row"><span>requestId</span><code>${escape(node.requestId)}</code></div></div><div class="inspect-title">父子关系</div><div class="lineage">${ancestors(node).map((n, i) => `${i ? '<span class="lineage-arrow">↓ 派发</span>' : ''}<button class="lineage-node ${n.id === node.id ? 'selected' : ''}" data-thread="${n.id}">${icon(n.family)}${escape(n.model)}</button>`).join('')}${children.map((n) => `<span class="lineage-arrow">↓ 子线程</span><button class="lineage-node" data-thread="${n.id}">${icon(n.family)}${escape(n.model)}<span class="dot ${n.state}"></span></button>`).join('')}</div>${node.result ? `<div class="inspect-title">已回收结果</div><p class="inspect-text">${escape(node.result)}</p>` : ''}<div class="inspect-title">验收边界</div><ul class="inspect-list"><li>派发记录与子线程 ID 对应。</li><li>子线程完成后才允许父线程回收。</li><li>送达 unknown 时先用原请求对账。</li></ul>${sim.phase === 'blocked' ? '<button class="button info" data-action="reconcile">查询原 requestId</button>' : sim.phase === 'review' ? '<button class="button primary" data-action="accept">主控最终验收</button>' : ''}`;
    }
    $('#inspector-content').innerHTML = html;
  }
  function render(autoScroll = false) { renderTree(); renderHeader(); renderView(autoScroll); renderInspector(); }
  function pause() { clearTimeout(state.timer); state.timer = null; state.playing = false; }
  function delay() { return 1200 / Number($('#speed-select').value); }
  function tick() {
    if (!state.playing) return;
    try { sim.step(); } catch (error) { pause(); toast(error.message); }
    if (['blocked', 'review', 'accepted'].includes(sim.phase)) pause();
    render(true);
    if (state.playing) state.timer = setTimeout(tick, delay());
  }
  function play() {
    if (sim.phase === 'review') return openAcceptance();
    if (sim.phase === 'accepted') reset();
    if (sim.phase === 'blocked') return toast('先核对原 requestId 的送达状态。');
    if (state.playing) { pause(); render(true); return; }
    state.playing = true; tick();
  }
  function reset() {
    pause(); sim.reset($('#prompt-input').value || DEFAULT_PROMPT, $('#scenario-select').value);
    state.selected = 'root'; state.view = 'chat'; state.eventFilter = 'all'; state.folded.clear();
    render();
  }
  function selectThread(id) {
    sim.node(id); state.selected = id; state.view = 'chat'; render();
    document.body.classList.remove('sidebar-open');
  }
  function download(name, value, type) {
    const blob = new Blob([value], { type }); const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = name;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }
  function openAcceptance() {
    if (sim.phase !== 'review') return toast('必须先收回全部分支结果。');
    const checks = ['三级父子关系与同组模型派发已核对', '六个子线程均完成，三个一级结果已回收', 'requestId、送达、执行与验收事件已核对'];
    $('#accept-checks').innerHTML = checks.map((text) => `<label class="accept-check"><input type="checkbox" name="accept-evidence" value="${escape(text)}"><span>${escape(text)}</span></label>`).join('');
    $('#confirm-accept').disabled = true;
    $('#accept-dialog').showModal();
  }
  function action(name, button) {
    if (name === 'play') play();
    if (name === 'accept') openAcceptance();
    if (name === 'reconcile') { const id = sim.reconcile(); toast(`原请求 ${id} 已对账；可继续。`); render(true); }
    if (name === 'export') download('aiteam-mock-run.json', JSON.stringify(sim.snapshot(), null, 2), 'application/json');
    if (name === 'artifact') { const item = sim.artifacts.find((a) => a.name === button.dataset.name); if (item) download(item.name, item.content, 'text/markdown;charset=utf-8'); }
  }
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-thread],[data-view],[data-inspector],[data-action],[data-fold]');
    if (!button) return;
    try {
      if (button.dataset.fold) {
        const id = button.dataset.fold;
        if (state.folded.has(id)) state.folded.delete(id); else state.folded.add(id);
        renderTree();
      } else if (button.dataset.thread) selectThread(button.dataset.thread);
      else if (button.dataset.view) { state.view = button.dataset.view; render(); document.body.classList.remove('sidebar-open'); }
      else if (button.dataset.inspector) { state.inspector = button.dataset.inspector; renderInspector(); }
      else if (button.dataset.action) action(button.dataset.action, button);
    } catch (error) { toast(error.message); }
  });
  $('#play-run').addEventListener('click', play);
  $('#step-run').addEventListener('click', () => { sim.step(); render(true); });
  $('#reset-run').addEventListener('click', () => { reset(); toast('当前模拟已重置。'); });
  $('#new-run').addEventListener('click', () => { reset(); $('#prompt-input').focus(); toast('已创建新的模拟尝试。'); });
  $('#send-prompt').addEventListener('click', () => { reset(); play(); });
  $('#prompt-input').addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); $('#send-prompt').click(); } });
  $('#scenario-select').addEventListener('change', reset);
  $('#speed-select').addEventListener('change', () => { if (state.playing) { clearTimeout(state.timer); state.timer = setTimeout(tick, delay()); } });
  $('#view-content').addEventListener('change', (event) => { if (event.target.id === 'event-filter') { state.eventFilter = event.target.value; renderView(); } });
  $('#accept-checks').addEventListener('change', () => { $('#confirm-accept').disabled = $$('input[name="accept-evidence"]:checked').length !== 3; });
  $('#confirm-accept').addEventListener('click', () => { sim.accept($$('input[name="accept-evidence"]:checked').map((c) => c.value)); $('#accept-dialog').close(); state.selected = 'root'; state.view = 'chat'; render(true); toast('模拟验收完成，证据已写入事件记录。'); });
  $('#about-button').addEventListener('click', () => { state.inspector = 'architecture'; document.body.classList.remove('rightbar-hidden'); document.body.classList.add('rightbar-open'); renderInspector(); });
  $('#details-toggle').addEventListener('click', () => { if (window.matchMedia('(max-width:1100px)').matches) document.body.classList.toggle('rightbar-open'); else document.body.classList.toggle('rightbar-hidden'); });
  $('#rightbar-close').addEventListener('click', () => { document.body.classList.remove('rightbar-open'); document.body.classList.add('rightbar-hidden'); });
  $('#sidebar-collapse').addEventListener('click', () => { document.body.classList.remove('sidebar-open'); document.body.classList.add('sidebar-hidden'); });
  $('#sidebar-expand').addEventListener('click', () => { if (window.matchMedia('(max-width:650px)').matches) document.body.classList.add('sidebar-open'); else document.body.classList.remove('sidebar-hidden'); });
  $('#sidebar-shade').addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  $('#select-project').addEventListener('click', () => selectThread('root'));
  $('.brand').addEventListener('click', (e) => { e.preventDefault(); selectThread('root'); });
  $('#theme-toggle').addEventListener('click', () => { const dark = !document.body.hasAttribute('data-ds-dark-theme'); document.body.toggleAttribute('data-ds-dark-theme', dark); try { localStorage.setItem('aiteam-theme', dark ? 'dark' : 'light'); } catch (_) {} });
  try { document.body.toggleAttribute('data-ds-dark-theme', localStorage.getItem('aiteam-theme') === 'dark'); } catch (_) {}
  render();
})();
