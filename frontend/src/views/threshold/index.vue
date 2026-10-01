<template>
  <section class="page" data-module="threshold">
    <header class="page-head">
      <div>
        <h2>逾期阈值模拟器</h2>
        <p class="page-desc">拖动巡查周期、天气等级与路段风险，预览哪些巡查记录会转为督办；确认后发布规则并回填未来排班。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="publishing" @click="publishRule">
          {{ publishing ? '发布处理中…' : '发布规则' }}
        </button>
        <button class="btn" type="button" @click="reloadAll">刷新结果</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="sim-layout">
      <div class="panel">
        <h3>模拟参数</h3>
        <div class="slider-item">
          <div class="slider-head">
            <span>巡查周期</span>
            <span class="slider-value">{{ cycleDays }} 天</span>
          </div>
          <input v-model.number="cycleDays" type="range" min="1" max="30" step="1" />
          <div class="slider-scale"><span>1 天</span><span>30 天</span></div>
        </div>
        <div class="slider-item">
          <div class="slider-head">
            <span>天气等级</span>
            <span class="slider-value">{{ weatherLevel }} 级 · {{ weatherLabels[weatherLevel] }}</span>
          </div>
          <input v-model.number="weatherLevel" type="range" min="1" max="5" step="1" />
          <div class="slider-scale"><span>晴好</span><span>冰雪</span></div>
        </div>
        <div class="slider-item">
          <div class="slider-head">
            <span>路段风险</span>
            <span class="slider-value">{{ riskLabels[riskLevel] }}</span>
          </div>
          <input v-model.number="riskLevel" type="range" min="1" max="3" step="1" />
          <div class="slider-scale"><span>低风险</span><span>高风险</span></div>
        </div>
        <p class="panel-note">
          普通路段有效周期折减为 <strong>{{ simParams['普通路段有效周期'] ?? cycleDays }} 天</strong>；
          项目专用阈值以批准方案为准，不受滑杆影响。
        </p>
        <p class="panel-note">当前月历（{{ currentMonth }}）不纳入集中处理，旧巡查按原计划留痕。</p>
      </div>

      <div class="panel">
        <h3>模拟预览：{{ summary['预计转督办'] ?? 0 }} 条巡查将转为督办</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>巡查编号</th>
              <th>巡查路段</th>
              <th>巡查日期</th>
              <th>阈值来源</th>
              <th>有效周期</th>
              <th>已间隔</th>
              <th>逾期天数</th>
              <th>模拟结论</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in simItems" :key="String(row['巡查编号'])">
              <td>{{ row['巡查编号'] }}</td>
              <td>{{ row['巡查路段'] }}</td>
              <td>{{ row['巡查日期'] }}</td>
              <td>{{ row['阈值来源'] }}</td>
              <td>{{ row['有效周期'] }} 天</td>
              <td>{{ row['已间隔'] }} 天</td>
              <td>{{ row['逾期天数'] }} 天</td>
              <td>
                <span class="tag" :class="row['转督办'] ? 'warn' : 'ok'">
                  {{ row['转督办'] ? '转督办' : '维持正常' }}
                </span>
              </td>
            </tr>
            <tr v-if="!simItems.length">
              <td colspan="8" class="empty-state">暂无参与判定的巡查记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h3>项目专用阈值（以批准方案为准）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>规则名称</th>
            <th>覆盖路段</th>
            <th>批准方案号</th>
            <th>巡查周期</th>
            <th>规则状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in projectRules" :key="String(rule['id'])">
            <td>{{ rule['规则名称'] }}</td>
            <td>{{ rule['覆盖路段'] }}</td>
            <td>{{ rule['批准方案号'] }}</td>
            <td>{{ rule['巡查周期'] }} 天</td>
            <td><span class="tag ok">{{ rule['status'] }}</span></td>
          </tr>
          <tr v-if="!projectRules.length">
            <td colspan="5" class="empty-state">暂无项目专用阈值</td>
          </tr>
        </tbody>
      </table>
      <p class="panel-note" v-if="defaultRule">
        普通路段沿用既有周期：{{ defaultRule['规则名称'] }} · {{ defaultRule['巡查周期'] }} 天 · 当前版本 V{{ defaultRule['版本'] }}。
      </p>
    </div>

    <div class="panel">
      <h3>发布批次</h3>
      <div v-if="activeBatch" class="batch-active">
        <div class="batch-line">
          <span>{{ activeBatch['批次号'] }}</span>
          <span class="tag" :class="activeBatch['status'] === '已完成' ? 'ok' : 'warn'">{{ activeBatch['status'] }}</span>
          <span>游标 {{ activeBatch['游标'] }} / {{ activeBatch['总量'] }}</span>
        </div>
        <div class="progress">
          <div class="progress-inner" :style="{ width: batchProgress + '%' }"></div>
        </div>
        <p v-if="activeBatch['status'] === '已完成'" class="panel-note">
          转督办 {{ batchResult['转督办'] ?? 0 }} 条 · 病害登记 {{ batchResult['病害登记'] ?? 0 }} 条 ·
          排班回填 {{ batchResult['排班回填'] ?? 0 }} 条 · 旧排班调整 {{ batchResult['旧排班调整'] ?? 0 }} 条 ·
          留痕旧巡查 {{ batchResult['留痕旧巡查'] ?? 0 }} 条 · 跳过当前月 {{ batchResult['跳过当前月'] ?? 0 }} 个排班位
        </p>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>批次号</th>
            <th>规则</th>
            <th>状态</th>
            <th>游标</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="String(batch['批次号'])">
            <td>{{ batch['批次号'] }}</td>
            <td>{{ batch['规则名称'] }}</td>
            <td>
              <span class="tag" :class="batch['status'] === '已完成' ? 'ok' : batch['status'] === '失败' ? 'warn' : ''">
                {{ batch['status'] }}
              </span>
            </td>
            <td>{{ batch['游标'] }} / {{ batch['总量'] }}</td>
            <td>{{ batch['创建时间'] }}</td>
            <td class="row-actions">
              <button v-if="batch['status'] === '处理中'" class="link" type="button" @click="driveBatch(Number(batch['id']))">
                从游标续做
              </button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="6" class="empty-state">暂无发布批次，拖动滑杆后点击「发布规则」</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="result-grid">
      <div class="panel">
        <h3>巡查待办（已转督办）</h3>
        <table class="data-table">
          <thead>
            <tr><th>巡查编号</th><th>路段</th><th>逾期</th><th>适用阈值</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in todoPatrols" :key="String(row['巡查编号'])">
              <td>{{ row['巡查编号'] }}</td>
              <td>{{ row['巡查路段'] }}</td>
              <td>{{ row['逾期天数'] }} 天</td>
              <td>{{ row['适用阈值'] }}</td>
            </tr>
            <tr v-if="!todoPatrols.length">
              <td colspan="4" class="empty-state">暂无督办记录</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h3>路面病害清单</h3>
        <table class="data-table">
          <thead>
            <tr><th>病害编号</th><th>路段</th><th>类型</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in defects" :key="String(row['病害编号'])">
              <td>{{ row['病害编号'] }}</td>
              <td>{{ row['所属路段'] }}</td>
              <td>{{ row['病害类型'] }}</td>
              <td>{{ row['status'] }}</td>
            </tr>
            <tr v-if="!defects.length">
              <td colspan="4" class="empty-state">暂无病害记录</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h3>车辆排班汇总</h3>
        <table class="data-table">
          <thead>
            <tr><th>车辆</th><th>排班</th><th>待巡查</th><th>已调整</th><th>覆盖月份</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in vehicleSummary" :key="String(row['巡查车辆'])">
              <td>{{ row['巡查车辆'] }}</td>
              <td>{{ row['排班次数'] }}</td>
              <td>{{ row['待巡查'] }}</td>
              <td>{{ row['已调整'] }}</td>
              <td>{{ row['覆盖月份'] }}</td>
            </tr>
            <tr v-if="!vehicleSummary.length">
              <td colspan="5" class="empty-state">暂无排班数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h3>当前月历（{{ currentMonthInfo['月份'] ?? currentMonth }}，不纳入集中处理）</h3>
      <p class="panel-note">{{ currentMonthInfo['说明'] }}</p>
      <table class="data-table">
        <thead>
          <tr><th>排班编号</th><th>路段</th><th>计划日期</th><th>车辆</th><th>计划版本</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in currentMonthSchedules" :key="String(row['排班编号'])">
            <td>{{ row['排班编号'] }}</td>
            <td>{{ row['巡查路段'] }}</td>
            <td>{{ row['计划日期'] }}</td>
            <td>{{ row['巡查车辆'] }}</td>
            <td>{{ row['计划版本'] }}</td>
          </tr>
          <tr v-if="!currentMonthSchedules.length">
            <td colspan="5" class="empty-state">当前月暂无排班</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span v-if="noteMessage">{{ noteMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | undefined>
type Batch = Row & { 结果?: Record<string, number> }

const ENDPOINT = '/api/threshold'
const weatherLabels: Record<number, string> = { 1: '晴好', 2: '多云', 3: '降雨', 4: '暴雨', 5: '冰雪' }
const riskLabels: Record<number, string> = { 1: '低风险', 2: '中风险', 3: '高风险' }

const cycleDays = ref(7)
const weatherLevel = ref(1)
const riskLevel = ref(1)
const simItems = ref<Row[]>([])
const summary = ref<Row>({})
const simParams = ref<Row>({})
const currentMonth = ref('')
const rules = ref<Row[]>([])
const batches = ref<Batch[]>([])
const activeBatch = ref<Batch | null>(null)
const todoPatrols = ref<Row[]>([])
const defects = ref<Row[]>([])
const vehicleSummary = ref<Row[]>([])
const currentMonthInfo = ref<Row>({})
const publishing = ref(false)
const errorMessage = ref('')
const noteMessage = ref('')

const defaultRule = computed(() => rules.value.find((rule) => rule['适用范围'] === '普通路段'))
const projectRules = computed(() => rules.value.filter((rule) => rule['适用范围'] === '项目专用'))
const currentMonthSchedules = computed(() => (currentMonthInfo.value['排班'] as Row[] | undefined) ?? [])
const batchResult = computed(() => activeBatch.value?.['结果'] ?? {})
const batchProgress = computed(() => {
  const total = Number(activeBatch.value?.['总量'] ?? 0)
  if (!total) return 0
  return Math.round((Number(activeBatch.value?.['游标'] ?? 0) / total) * 100)
})
const stats = computed(() => [
  { label: '参与判定巡查', value: Number(summary.value['参与判定'] ?? 0) },
  { label: '预计转督办', value: Number(summary.value['预计转督办'] ?? 0) },
  { label: '项目专用方案', value: projectRules.value.length },
  { label: '留痕旧巡查', value: Number(summary.value['留痕旧巡查'] ?? 0) },
])

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function runSimulate() {
  try {
    const response = await request(`${ENDPOINT}/simulate`, {
      method: 'POST',
      body: JSON.stringify({
        cycle_days: cycleDays.value,
        weather_level: weatherLevel.value,
        risk_level: riskLevel.value,
      }),
    })
    if (!response.ok) {
      throw new Error('模拟预览请求未生效')
    }
    const payload = await response.json()
    simItems.value = payload.items ?? []
    summary.value = payload.summary ?? {}
    simParams.value = payload.params ?? {}
    currentMonth.value = payload['当前月历'] ?? currentMonth.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模拟预览失败'
  }
}

async function loadRules() {
  const payload = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/rules`)
  rules.value = payload.items ?? []
}

async function loadBatches() {
  const payload = await fetchJson<{ items: Batch[] }>(`${ENDPOINT}/batches`)
  batches.value = payload.items ?? []
}

async function loadResults() {
  const payload = await fetchJson<Record<string, unknown>>(`${ENDPOINT}/results`)
  todoPatrols.value = (payload['巡查待办'] as Row[]) ?? []
  defects.value = (payload['路面病害'] as Row[]) ?? []
  vehicleSummary.value = (payload['车辆排班'] as Row[]) ?? []
  currentMonthInfo.value = (payload['当前月历'] as Row) ?? {}
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    await Promise.all([loadRules(), loadBatches(), loadResults()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结果读取失败'
  }
}

async function driveBatch(batchId: number) {
  let failures = 0
  while (true) {
    try {
      const response = await request(`${ENDPOINT}/batches/${batchId}/resume`, {
        method: 'POST',
        body: '{}',
      })
      const payload = await response.json()
      if (!payload.ok) {
        errorMessage.value = payload.message ?? '批次处理失败'
        break
      }
      activeBatch.value = payload.entry
      failures = 0
      noteMessage.value = payload.message ?? ''
      if (payload.entry?.status !== '处理中') {
        break
      }
      await sleep(200)
    } catch {
      // 连接断开：游标在服务端，重试即从断点续做
      failures += 1
      noteMessage.value = '连接断开，将从批次游标续做…'
      if (failures > 5) {
        errorMessage.value = '多次重连失败，可稍后在批次列表手动续做'
        break
      }
      await sleep(800)
    }
  }
  await reloadAll()
}

async function publishRule() {
  const rule = defaultRule.value
  if (!rule) {
    errorMessage.value = '未找到普通路段既有周期规则，无法发布'
    return
  }
  errorMessage.value = ''
  noteMessage.value = ''
  // 幂等键由规则版本与滑杆参数决定：同一次发布重复提交只生效一次
  const key = [`R${rule['id']}`, `V${rule['版本']}`, `C${cycleDays.value}`, `W${weatherLevel.value}`, `R${riskLevel.value}`].join('-')
  publishing.value = true
  try {
    const response = await request(`${ENDPOINT}/rules/${rule['id']}/publish`, {
      method: 'POST',
      body: JSON.stringify({
        expected_version: Number(rule['版本'] ?? 1),
        idempotency_key: key,
        cycle_days: cycleDays.value,
        weather_level: weatherLevel.value,
        risk_level: riskLevel.value,
      }),
    })
    const payload = await response.json()
    noteMessage.value = payload.message ?? ''
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '发布失败'
      return
    }
    activeBatch.value = payload.entry
    if (payload.entry?.id) {
      await driveBatch(Number(payload.entry.id))
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '规则发布失败'
  } finally {
    publishing.value = false
    await reloadAll()
  }
}

let debounceTimer: number | undefined
watch([cycleDays, weatherLevel, riskLevel], () => {
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => void runSimulate(), 300)
})

onMounted(async () => {
  await reloadAll()
  const rule = defaultRule.value
  if (rule) {
    cycleDays.value = Number(rule['巡查周期'] ?? 7)
    weatherLevel.value = Number(rule['天气等级'] ?? 1)
    riskLevel.value = Number(rule['路段风险'] ?? 1)
  }
  await runSimulate()
})
</script>
