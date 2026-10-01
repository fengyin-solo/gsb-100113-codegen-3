<template>
  <section class="page sim-page" data-module="simulator">
    <header class="page-head">
      <div>
        <h2>逾期阈值模拟器</h2>
        <p class="page-desc">
          拖动巡查周期、天气等级与路段风险，实时预览哪些在办巡查将转为督办。
          专项段阈值以批准方案为准，普通路段继续沿用既有周期（滑块只加密、不放松）。
        </p>
      </div>
      <div class="sim-meta">
        <span class="chip">模拟基准日：{{ config.referenceDate ?? '—' }}</span>
        <span class="chip" v-if="currentRule">当前生效规则：v{{ currentRule['版本号'] }}</span>
        <span class="chip muted" v-else>尚未发布规则</span>
      </div>
    </header>

    <div class="sim-layout">
      <!-- 左侧：滑块与操作 -->
      <div class="sim-panel controls">
        <h3>阈值滑块</h3>

        <div class="slider-block">
          <div class="slider-head">
            <label for="cycle">巡查周期（天）</label>
            <strong>{{ cycle }}</strong>
          </div>
          <input id="cycle" v-model.number="cycle" type="range" min="1" max="14" step="1" />
          <div class="slider-scale"><span>1（加密）</span><span>14（常态）</span></div>
          <p class="hint">普通路段取「滑块周期」与「既有周期」的较小值，只允许更严。</p>
        </div>

        <div class="slider-block">
          <div class="slider-head">
            <label for="weather">天气等级</label>
            <strong>{{ weatherLabel }}</strong>
          </div>
          <input id="weather" v-model.number="weather" type="range" min="0" max="4" step="1" />
          <div class="slider-scale">
            <span v-for="(lv, i) in config.weather?.levels ?? []" :key="lv" :class="{ on: weather === i }">{{ i }}</span>
          </div>
        </div>

        <div class="slider-block">
          <div class="slider-head">
            <label for="risk">路段风险（叠加值）</label>
            <strong>{{ riskLabel }}</strong>
          </div>
          <input id="risk" v-model.number="risk" type="range" min="0" max="2" step="1" />
          <div class="slider-scale">
            <span v-for="(lv, i) in config.risk?.levels ?? []" :key="lv" :class="{ on: risk === i }">{{ i }}</span>
          </div>
          <p class="hint">天气 {{ weatherPenalty }} 天 / 风险 {{ riskPenalty }} 天，从基础周期扣减（最低 1 天）。</p>
        </div>

        <div class="sim-actions">
          <button class="btn primary" type="button" :disabled="applying" @click="applySimulation">
            {{ applying ? '处置中…' : '模拟处置（落待办/病害/派车）' }}
          </button>
          <button class="btn" type="button" :disabled="publishing" @click="publish">
            {{ publishing ? '发布中…' : '发布规则并回填未来排班' }}
          </button>
          <p class="hint warn">发布只回填未来排班；本月月历保留不集中处理，旧巡查按原计划留痕。</p>
        </div>

        <p v-if="message" class="sim-message" :class="{ error: !lastOk }">{{ message }}</p>
      </div>

      <!-- 右侧：预览结果 -->
      <div class="sim-panel preview">
        <div class="preview-head">
          <h3>督办预览</h3>
          <span class="chip" v-if="loading">计算中…</span>
        </div>

        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">将转督办</span>
            <strong class="stat-value danger">{{ preview?.summary['将转督办'] ?? 0 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">留痕/暂不督办</span>
            <strong class="stat-value">{{ preview?.summary['留痕或暂不督办'] ?? 0 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">未来在办（不预览）</span>
            <strong class="stat-value">{{ preview?.summary['未来在办'] ?? 0 }}</strong>
          </article>
        </div>

        <h4>各路段生效阈值</h4>
        <table class="data-table compact">
          <thead>
            <tr>
              <th>路段</th><th>适用来源</th><th>既有</th><th>基础</th>
              <th>天/风扣减</th><th>生效周期</th><th>滑块</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in preview?.thresholds ?? []" :key="t['路段编号']" :class="{ plan: t['适用来源'] === '批准方案' }">
              <td>{{ t['路段编号'] }} {{ t['路段名称'] }}</td>
              <td>{{ t['适用来源'] }}<span v-if="t['方案编号']" class="mini">（{{ t['方案编号'] }}）</span></td>
              <td>{{ t['既有周期'] }} 天</td>
              <td>{{ t['基础周期'] }} 天</td>
              <td>-{{ t['天气扣减'] }} / -{{ t['风险扣减'] }}</td>
              <td><strong>{{ t['生效周期'] }} 天</strong></td>
              <td>{{ t['滑块是否生效'] ? '生效' : '锁定' }}</td>
            </tr>
          </tbody>
        </table>

        <h4>将转督办的巡查记录（{{ preview?.overdue.length ?? 0 }}）</h4>
        <table class="data-table compact">
          <thead>
            <tr>
              <th>巡查编号</th><th>路段</th><th>计划日期</th><th>应完成</th>
              <th>逾期</th><th>来源</th><th>当前督办</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in preview?.overdue ?? []" :key="o['巡查id']">
              <td>{{ o['巡查编号'] }}</td>
              <td>{{ o['路段名称'] }}</td>
              <td>{{ o['计划日期'] }}</td>
              <td>{{ o['应完成日期'] }}</td>
              <td class="danger">{{ o['逾期天数'] }} 天</td>
              <td>{{ o['适用来源'] }}</td>
              <td>{{ o['督办状态'] }}</td>
            </tr>
            <tr v-if="!(preview?.overdue.length)"><td colspan="7" class="empty-state">当前参数下没有将转督办的记录</td></tr>
          </tbody>
        </table>

        <details>
          <summary>留痕 / 暂不督办清单（{{ preview?.retained.length ?? 0 }}）</summary>
          <table class="data-table compact">
            <thead>
              <tr><th>巡查编号</th><th>路段</th><th>状态</th><th>性质</th><th>原因</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in preview?.retained ?? []" :key="r['巡查id']">
                <td>{{ r['巡查编号'] }}</td>
                <td>{{ r['路段名称'] }}</td>
                <td>{{ r['巡查状态'] }}</td>
                <td>{{ r['记录性质'] }}</td>
                <td>{{ r['留痕原因'] }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </div>
    </div>

    <!-- 专项方案 -->
    <div class="sim-panel">
      <div class="preview-head">
        <h3>项目专用阈值方案（以批准方案为准）</h3>
      </div>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>方案编号</th><th>名称</th><th>路段</th><th>周期</th>
            <th>天气</th><th>风险</th><th>状态</th><th>批准日期</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in plans" :key="p.id">
            <td>{{ p['方案编号'] }}</td>
            <td>{{ p['方案名称'] }}</td>
            <td>{{ p['路段编号'] }}</td>
            <td>{{ p['巡查周期'] }} 天</td>
            <td>{{ p['天气等级'] }}</td>
            <td>{{ p['风险等级'] }}</td>
            <td>
              <span class="badge" :class="p['方案状态'] === '已批准' ? 'ok' : 'pending'">{{ p['方案状态'] }}</span>
            </td>
            <td>{{ p['批准日期'] ?? '—' }}</td>
            <td>
              <button v-if="p['方案状态'] !== '已批准'" class="link" type="button" @click="approve(p.id)">
                批复并生效
              </button>
              <span v-else class="mini">阈值已锁定</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 集中重排批次 -->
    <div class="sim-panel">
      <div class="preview-head">
        <h3>集中重排批次（版本锁 · 事务 · 游标续算）</h3>
        <button class="btn ghost" type="button" @click="loadBatches">刷新批次</button>
      </div>
      <table class="data-table compact" v-if="batches.length">
        <thead>
          <tr>
            <th>批次号</th><th>规则版本</th><th>进度</th><th>游标</th>
            <th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td>{{ b['批次号'] }}</td>
            <td>v{{ b['规则版本'] }}</td>
            <td>
              <progress :value="b['已处理']" :max="b['总数']"></progress>
              {{ b['已处理'] }} / {{ b['总数'] }}
            </td>
            <td>{{ b['游标'] }}</td>
            <td>
              <span class="badge" :class="b['状态'] === '已完成' ? 'ok' : 'pending'">{{ b['状态'] }}</span>
            </td>
            <td>
              <button v-if="b['状态'] !== '已完成'" class="link" type="button" @click="resume(b.id)">
                从游标续算一块
              </button>
              <span v-else class="mini">回填完成</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="mini">还没有发布过规则；发布后这里显示批次游标，连接断开可从游标续做。</p>
    </div>

    <footer class="page-foot">
      <span>模拟处置结果落到：巡查待办、路面病害清单、<RouterLink to="/vehicle_summary">车辆排班汇总</RouterLink></span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Json = Record<string, any>

const config = ref<Json>({})
const plans = ref<Json[]>([])
const batches = ref<Json[]>([])
const preview = ref<Json | null>(null)

const cycle = ref(7)
const weather = ref(0)
const risk = ref(0)

const loading = ref(false)
const applying = ref(false)
const publishing = ref(false)
const message = ref('')
const lastOk = ref(true)

const currentRule = computed<Json | null>(() => config.value.currentRule ?? null)
const weatherLabel = computed(() => config.value.weather?.levels?.[weather.value] ?? weather.value)
const riskLabel = computed(() => config.value.risk?.levels?.[risk.value] ?? risk.value)
const weatherPenalty = computed(() => [0, 0, 1, 2, 3][weather.value])
const riskPenalty = computed(() => [0, 1, 2][risk.value])

let timer: ReturnType<typeof setTimeout> | undefined
watch([cycle, weather, risk], () => {
  // 拖动过程中不打满接口：停顿 300ms 后再请求预览。
  clearTimeout(timer)
  timer = setTimeout(() => void loadPreview(), 300)
})

async function getJson(path: string): Promise<any> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return response.json()
}

async function postJson(path: string, body: object): Promise<any> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw Object.assign(new Error(detail.detail?.message ?? `接口返回 ${response.status}`), {
      status: response.status,
      detail,
    })
  }
  return response.json()
}

function flash(text: string, ok = true) {
  message.value = text
  lastOk.value = ok
}

async function loadConfig() {
  config.value = await getJson('/api/simulator/config')
}

async function loadPreview() {
  loading.value = true
  try {
    const query = new URLSearchParams({
      cycle: String(cycle.value),
      weather: String(weather.value),
      risk: String(risk.value),
    })
    preview.value = await getJson(`/api/simulator/preview?${query.toString()}`)
  } catch (error) {
    flash(error instanceof Error ? error.message : '预览读取失败', false)
  } finally {
    loading.value = false
  }
}

async function loadPlans() {
  const payload = await getJson('/api/simulator/plans')
  plans.value = payload.items ?? []
}

async function loadBatches() {
  const payload = await getJson('/api/simulator/batches')
  batches.value = payload.items ?? []
}

function sliderBody() {
  return { cycle: cycle.value, weather: weather.value, risk: risk.value }
}

async function applySimulation() {
  applying.value = true
  try {
    const result = await postJson('/api/simulator/apply', sliderBody())
    flash(`${result.message}；路面病害 +${result.defectsCreated}，督办派车 +${result.dispatchesCreated}`)
    await Promise.all([loadPreview(), loadBatches()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '模拟处置失败', false)
  } finally {
    applying.value = false
  }
}

async function publish() {
  publishing.value = true
  try {
    const baseVersion = currentRule.value ? Number(currentRule.value['版本号']) : null
    const result = await postJson('/api/simulator/publish', { ...sliderBody(), baseVersion })
    if (result.idempotent) {
      flash(result.message)
    } else {
      const b = result.batch.batch
      flash(`规则 v${result.rule['版本号']} 已发布，重排批次推进到 ${b['游标']}/${b['总数']}（${b['状态']}）`)
    }
    await Promise.all([loadConfig(), loadBatches(), loadPreview()])
  } catch (error) {
    const anyError = error as Error & { status?: number; detail?: any }
    if (anyError.status === 409) {
      const d = anyError.detail?.detail ?? {}
      flash(`版本锁拦截：${d.message ?? '规则版本冲突或已有批次在跑'}`, false)
      await Promise.all([loadConfig(), loadBatches()])
    } else {
      flash(anyError.message, false)
    }
  } finally {
    publishing.value = false
  }
}

async function resume(batchId: number) {
  try {
    const result = await postJson(`/api/simulator/batches/${batchId}/resume`, {})
    const b = result.batch
    flash(`批次续算：游标 ${b['游标']}/${b['总数']}，状态 ${b['状态']}`)
    await Promise.all([loadBatches(), loadPreview()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '续算失败', false)
  }
}

async function approve(planId: number) {
  try {
    const result = await postJson(`/api/simulator/plans/${planId}/approve`, {})
    flash(result.message)
    await Promise.all([loadPlans(), loadConfig(), loadPreview()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '方案批复失败', false)
  }
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadPlans(), loadBatches()])
  await loadPreview()
})
</script>

<style scoped>
.sim-meta { display: flex; gap: 8px; }
.chip {
  background: #eef4ff; border: 1px solid #c6d8f7; color: #1f4fb0;
  border-radius: 999px; padding: 3px 10px; font-size: 12px;
}
.chip.muted { background: #f1f5f9; border-color: #e2e8f0; color: #64748b; }
.sim-layout { display: grid; grid-template-columns: 320px 1fr; gap: 12px; }
.sim-panel {
  background: #fff; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; margin-bottom: 12px;
}
.sim-panel h3 { margin: 0 0 10px; font-size: 15px; }
.sim-panel h4 { margin: 14px 0 6px; font-size: 13px; color: #334155; }
.slider-block { margin-bottom: 14px; }
.slider-head { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
.slider-head label { color: #334155; }
.slider-block input[type='range'] { width: 100%; }
.slider-scale { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }
.slider-scale span.on { color: var(--brand); font-weight: 600; }
.hint { font-size: 11px; color: var(--muted); margin: 4px 0 0; }
.hint.warn { color: #92400e; }
.sim-actions { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.sim-actions .btn { width: 100%; }
.sim-message { font-size: 12px; color: #15803d; margin-top: 8px; }
.sim-message.error { color: #b42318; }
.preview-head { display: flex; justify-content: space-between; align-items: center; }
.data-table.compact th, .data-table.compact td { padding: 5px 8px; font-size: 12px; }
.danger { color: #b42318; font-weight: 600; }
tr.plan { background: #f8fafc; }
.mini { font-size: 11px; color: var(--muted); }
.badge { border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.pending { background: #fef9c3; color: #854d0e; }
details summary { cursor: pointer; font-size: 12px; color: var(--brand); margin: 10px 0 6px; }
progress { width: 120px; vertical-align: middle; margin-right: 6px; }
@media (max-width: 1080px) { .sim-layout { grid-template-columns: 1fr; } }
</style>
