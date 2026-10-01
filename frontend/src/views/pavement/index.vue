<template>
  <section class="page" data-module="pavement">
    <header class="page-head">
      <div>
        <h2>路面病害管理</h2>
        <p class="page-desc">维护病害记录，围绕病害编号、所属路段、病害类型、严重程度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记病害记录</button>
        <button class="btn" type="button" @click="exportRows">导出路面病害清单</button>
      </div>
    </header>

    <div v-if="simDefectCount > 0" class="sim-banner">
      阈值模拟处置已向本清单追加 <strong>{{ simDefectCount }}</strong> 条「逾期巡查待排查病害」，
      同时下发了巡查待办与督办派车，可前往
      <RouterLink to="/simulator">逾期阈值模拟器</RouterLink> 查看口径。
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无路面病害数据，可先登记病害记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条路面病害记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pavement'
const columns = ["病害编号", "所属路段", "病害类型", "严重程度", "起止桩号", "面积", "发现日期", "病害状态"]
const actions = ["派发修复", "标记修复", "验收通过"]
const statuses = ["待修复", "修复中", "已修复", "已验收"]
const stats = [{"label": "待修复病害", "value": 0}, {"label": "修复中病害", "value": 0}, {"label": "已修复病害", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '病害记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('路面病害动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '路面病害操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('病害记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '路面病害列表读取失败'
  }
}

const simDefectCount = ref(0)

async function loadLandingStats() {
  try {
    const response = await request('/api/simulator/landing-stats')
    if (!response.ok) return
    const payload = await response.json()
    simDefectCount.value = Number(payload.defectCount ?? 0)
  } catch {
    // 模拟器不可用时不影响病害主列表
  }
}

onMounted(() => {
  void reload()
  void loadLandingStats()
})
</script>

<style scoped>
.sim-banner {
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-left: 4px solid #ea580c;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  color: #9a3412;
  margin-bottom: 12px;
}
.sim-banner a { color: #1f6feb; }
</style>
