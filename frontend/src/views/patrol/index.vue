<template>
  <section class="page" data-module="patrol">
    <header class="page-head">
      <div>
        <h2>日常巡查管理</h2>
        <p class="page-desc">维护巡查记录，围绕巡查编号、巡查路段、巡查日期、巡查人员做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡查记录</button>
        <button class="btn" type="button" @click="exportRows">导出日常巡查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">逾期督办待办</span>
        <strong class="stat-value danger">{{ todoCount }}</strong>
      </article>
    </div>

    <section v-if="todos.length" class="todo-panel">
      <header class="todo-head">
        <h3>巡查待办 · 逾期督办（阈值模拟处置下发）</h3>
        <RouterLink class="link" to="/simulator">去模拟器</RouterLink>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>待办编号</th><th>来源巡查</th><th>路段</th><th>逾期天数</th>
            <th>生效周期</th><th>阈值来源</th><th>下发日期</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="todo in todos" :key="String(todo.id)">
            <td>{{ todo['待办编号'] }}</td>
            <td>{{ todo['来源巡查'] }}</td>
            <td>{{ todo['路段名称'] }}</td>
            <td class="danger">{{ todo['逾期天数'] }} 天</td>
            <td>{{ todo['生效周期'] }} 天</td>
            <td>{{ todo['适用来源'] }}</td>
            <td>{{ todo['下发日期'] }}</td>
            <td><span class="todo-badge">{{ todo['状态'] }}</span></td>
          </tr>
        </tbody>
      </table>
    </section>

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
          <td :colspan="columns.length + 1" class="empty-state">暂无日常巡查数据，可先登记巡查记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条日常巡查记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/patrol'
const columns = ["巡查编号", "巡查路段", "巡查日期", "巡查人员", "巡查车辆", "发现问题", "处置措施", "巡查状态"]
const actions = ["开始巡查", "完成巡查", "复核确认"]
const statuses = ["待巡查", "巡查中", "已完成", "已复核"]
const stats = [{"label": "今日巡查", "value": 0}, {"label": "待巡查路段", "value": 0}, {"label": "发现问题", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const todos = ref<Row[]>([])
const todoCount = ref(0)

async function loadTodos() {
  try {
    const response = await request('/api/simulator/todos')
    if (!response.ok) return
    const payload = await response.json()
    todos.value = payload.items ?? []
    todoCount.value = todos.value.length
  } catch {
    // 模拟器未就绪时不影响巡查主列表
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡查记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('日常巡查动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '日常巡查操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('巡查记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '日常巡查列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadTodos()
})
</script>

<style scoped>
.todo-panel {
  background: #fff;
  border: 1px solid #f3c6c0;
  border-left: 4px solid #b42318;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
}
.todo-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.todo-head h3 { margin: 0; font-size: 14px; }
.todo-badge { background: #fef2f2; color: #b42318; border-radius: 999px; padding: 1px 8px; font-size: 12px; }
.danger { color: #b42318; }
</style>
