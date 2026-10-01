<template>
  <section class="page" data-module="vehicle_summary">
    <header class="page-head">
      <div>
        <h2>车辆排班汇总</h2>
        <p class="page-desc">
          按车辆汇总原计划、本月保留、模拟处置派车与规则回填班次。规则发布只重排未来排班，
          本月月历保留；旧巡查按原计划留痕。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/simulator">返回阈值模拟器</RouterLink>
        <button class="btn ghost" type="button" @click="reload">刷新汇总</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">本月保留班次</span>
        <strong class="stat-value">{{ totals.retained }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">模拟处置派车</span>
        <strong class="stat-value danger">{{ totals.dispatch }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">规则回填班次</span>
        <strong class="stat-value">{{ totals.backfill }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">未来已重排原计划</span>
        <strong class="stat-value">{{ totals.rescheduled }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent>
      <label class="filter-item">
        <span>来源筛选</span>
        <select v-model="sourceFilter">
          <option value="">全部</option>
          <option value="原计划">原计划</option>
          <option value="模拟处置派车">模拟处置派车</option>
          <option value="规则回填">规则回填</option>
        </select>
      </label>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>车辆编号</th>
          <th>驾驶员</th>
          <th>原计划</th>
          <th>本月保留</th>
          <th>已重排</th>
          <th>模拟处置派车</th>
          <th>规则回填</th>
          <th>班次明细</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in vehicles" :key="v['车辆编号']">
          <td>{{ v['车辆编号'] }}</td>
          <td>{{ v['驾驶员'] }}</td>
          <td>{{ v['原计划'] }}</td>
          <td>{{ v['本月保留'] }}</td>
          <td>{{ v['已重排'] }}</td>
          <td class="danger">{{ v['督办派车'] }}</td>
          <td>{{ v['规则回填'] }}</td>
          <td>
            <ul class="detail-list">
              <li
                v-for="d in filteredDetails(v['班次明细'])"
                :key="d['排班编号']"
                :class="`src-${sourceClass(d['来源'])}`"
              >
                {{ d['排班日期'] }} · {{ d['路段'] }} · {{ sourceLabel(d['来源']) }}
                <span class="mini">（{{ d['状态'] }}）</span>
              </li>
            </ul>
          </td>
        </tr>
        <tr v-if="!vehicles.length">
          <td colspan="8" class="empty-state">暂无排班数据，先到模拟器里发布规则或执行模拟处置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>汇总基准日：{{ asOf }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Json = Record<string, any>

const vehicles = ref<Json[]>([])
const asOf = ref('')
const errorMessage = ref('')
const sourceFilter = ref('')

const totals = computed(() =>
  vehicles.value.reduce(
    (acc, v) => ({
      retained: acc.retained + Number(v['本月保留'] ?? 0),
      dispatch: acc.dispatch + Number(v['督办派车'] ?? 0),
      backfill: acc.backfill + Number(v['规则回填'] ?? 0),
      rescheduled: acc.rescheduled + Number(v['已重排'] ?? 0),
    }),
    { retained: 0, dispatch: 0, backfill: 0, rescheduled: 0 },
  ),
)

function filteredDetails(details: Json[]) {
  if (!sourceFilter.value) return details
  return details.filter((d) => d['来源'] === sourceFilter.value)
}

function sourceClass(source: string) {
  if (source === '模拟处置派车') return 'dispatch'
  if (source === '规则回填') return 'backfill'
  return 'origin'
}

function sourceLabel(source: string) {
  return source
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<Json>('/api/simulator/vehicle-summary')
    vehicles.value = (payload.vehicles ?? []) as Json[]
    asOf.value = String(payload.asOf ?? '')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '排班汇总读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.detail-list { margin: 0; padding-left: 16px; font-size: 12px; line-height: 1.7; }
.detail-list li.src-dispatch { color: #b42318; }
.detail-list li.src-backfill { color: #1f6feb; }
.mini { color: var(--muted); }
.danger { color: #b42318; font-weight: 600; }
.filter-item select { padding: 4px 6px; }
</style>
