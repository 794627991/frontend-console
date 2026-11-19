// lanzi/robot.js — Lanzi 专栏的「机器人」渲染与凭据保存（a673 模块化拆分）
//
// 职责边界：
//   · 状态灯/文案/徽标的渲染（语义与 harness 侧栏一致，两处必须同款）
//   · 凭据表单（App ID / Secret）的脏标记与保存动作
// 不自己发轮询请求——宿主 panel.js 每拍拉到 bot_status 后调 renderRobot。
import { mkMsgArea } from './util.js';

// 状态灯（与 shell.js 的 hgBotLed 同语义；改一处必须改另一处）
export function botLed(j) {
  if (!j.manual) return 'lz-dot off';
  if (j.running && j.connected) return 'lz-dot on';
  if (j.remote_running) return 'lz-dot on';
  if (j.auth_failed) return 'lz-dot err';
  if (!j.running) return 'lz-dot idle';
  return 'lz-dot wait';
}

// 状态文案（指示灯表达状态，文字只在不正常/需要解释时给一句）
export function botPhase(j) {
  if (!j.manual) return '未配置凭据';
  if (j.running && j.connected) return '在线';
  if (j.remote_running) return '在线（本机另一进程 PID ' + j.remote_pid + '）';
  if (j.auth_failed) return '凭据被拒，请检查 App ID/Secret';
  if (!j.running) return j.kick_note || '已保存，未运行';
  return '连接中…';
}

/**
 * 机器人模块。持有「上一次已知的机器人状态」——保存时判断
 * 「Secret 留空是否可沿用旧值」必须依赖它。
 */
export function createRobotUI(els, opts) {
  const { botDotEl, botStateEl, botBadgeEl, botIdEl, botSecEl, botSaveBtn } = els;
  const { msgKeep, onChanged } = opts;

  // 上一次已知的机器人状态。注意只应在**成功拿到** bot_status 时覆盖：
  // 失败帧会缺 manual/app_id，覆盖后「留空沿用旧密钥」会被误拦。
  let lastBot = {};

  function render(bot, status) {
    // bot_status 与 status 的机器人字段同名（status_snapshot 直传），
    // 合并后的对象同时含 running/connected/manual/app_id 等
    const j = Object.assign({}, status || {}, bot || {});
    lastBot = j;
    botDotEl.className = botLed(j);
    botStateEl.textContent = botPhase(j);
    botBadgeEl.textContent = '机器人 ' + (j.manual ? (botPhase(j) || '在线') : '未配置');
    botBadgeEl.className = 'px-badge ' + ((j.running && j.connected) || j.remote_running
      ? 'px-healthy' : (j.auth_failed ? 'px-failed' : 'px-stopped'));
    // 输入框回填：用户动过的（dirty）不覆盖——否则「两项皆空=清除」永远点不到
    if (j.app_id && !botIdEl.dataset.dirty && !botIdEl.value) botIdEl.value = j.app_id;
    if (botIdEl.dataset.dirty && j.app_id && botIdEl.value === j.app_id)
      botIdEl.dataset.dirty = '';
    if (j.app_secret && !botSecEl.dataset.dirty && !botSecEl.value) botSecEl.value = j.app_secret;
    if (botSecEl.dataset.dirty && j.app_secret && botSecEl.value === j.app_secret)
      botSecEl.dataset.dirty = '';
  }

  // 输入即置 dirty；只有用户没动过才回填
  botIdEl.addEventListener('input', () => { botIdEl.dataset.dirty = '1'; });
  botSecEl.addEventListener('input', () => { botSecEl.dataset.dirty = '1'; });

  async function save() {
    const id = (botIdEl.value || '').trim();
    const secret = (botSecEl.value || '').trim();
    // 密钥留空 = 沿用已存密钥（仅 App ID 未变时；换 ID 必须重填）
    const keepSecret = !secret && id && lastBot.manual && lastBot.app_id === id;
    if (id && !secret && !keepSecret) { msgKeep('请填写 App Secret', true); return; }
    if (!id && secret) { msgKeep('请填写 App ID', true); return; }
    // 两项皆空 = 清除凭据并导致机器人掉线。状态未知（status 没拉到）
    // 时按「有风险」处理——undefined 不能当 false 放行
    if (!id && !secret && lastBot.manual !== false
        && !confirm('将清除已保存的机器人凭据并断开当前机器人连接，确定吗？')) return;
    botSaveBtn.disabled = true;
    const old = botSaveBtn.textContent;
    botSaveBtn.textContent = '保存中…';
    try {
      const j = await fetch('/api/lanzi/bot_credentials', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: id, app_secret: secret })
      }).then(r => r.json());
      msgKeep(j.msg || (j.ok ? '已保存' : '保存失败'), !j.ok);
      setTimeout(onChanged, 1500);
    } catch (e) { msgKeep('保存请求失败: ' + e, true); }
    botSaveBtn.disabled = false;
    botSaveBtn.textContent = old;
  }

  botSaveBtn.onclick = save;

  return { render, lastBot: () => lastBot };
}

// 供宿主创建消息区时复用（保持 util 的单一出口）
export { mkMsgArea };
