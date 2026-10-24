<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  getJson,
  patchJson,
  type Badcase,
  type OverviewData,
} from '../api'

const overview = ref<OverviewData | null>(null)
const badcases = ref<Badcase[]>([])
const loading = ref(false)
const errorText = ref('')

const openBadcases = computed(
  () => overview.value?.badcases.find((item) => item.status === 'open')?.count || 0,
)

function formatNumber(value: number | undefined) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
}

function formatMs(value: number | undefined) {
  return `${(value || 0).toFixed(1)} ms`
}

function formatPercent(value: number | undefined) {
  return `${((value || 0) * 100).toFixed(2)}%`
}

function formatCost(value: number | undefined) {
  return `$${(value || 0).toFixed(4)}`
}

function layerClass(layer: string) {
  return `layer-${layer}`
}

function statusClass(status: string) {
  const normalized = status.toLowerCase()
  if (['rejected', 'failed', 'cancelled', 'error'].includes(normalized)) return 'badge-bad'
  if (['waiting_approval', 'waiting_human', 'paused', 'open'].includes(normalized)) {
    return 'badge-warn'
  }
  return 'badge-good'
}

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    const [data, cases] = await Promise.all([
      getJson<OverviewData>('/traces/overview'),
      getJson<{ badcases: Badcase[] }>('/badcases', 'u002'),
    ])
    overview.value = data
    badcases.value = cases.badcases || []
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function markBadcase(id: string, status: string) {
  try {
    await patchJson(`/badcases/${id}`, { status }, 'u002')
    await load()
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(load)
</script>

<template>
  <section class="card">
    <div class="card-header">
      <div>
        <h2>线上概览</h2>
        <div class="muted small">来自本地 SQLite 聚合；生产可替换为 Prometheus / ClickHouse</div>
      </div>
      <button class="btn" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>
    <p v-if="errorText" class="error">{{ errorText }}</p>
  </section>

  <template v-if="overview">
    <div class="grid-4">
      <div class="metric">
        <div class="metric-label">Traces</div>
        <div class="metric-value">{{ formatNumber(overview.totals.traces) }}</div>
        <div class="metric-note">{{ formatNumber(overview.totals.spans) }} spans</div>
      </div>
      <div class="metric">
        <div class="metric-label">错误率</div>
        <div class="metric-value">{{ formatPercent(overview.totals.error_rate) }}</div>
        <div class="metric-note">{{ formatNumber(overview.totals.errors) }} errors</div>
      </div>
      <div class="metric">
        <div class="metric-label">P95 延迟</div>
        <div class="metric-value">{{ formatMs(overview.totals.p95_duration_ms) }}</div>
        <div class="metric-note">平均 {{ formatMs(overview.totals.avg_duration_ms) }}</div>
      </div>
      <div class="metric">
        <div class="metric-label">模型调用</div>
        <div class="metric-value">{{ formatNumber(overview.llm.calls) }}</div>
        <div class="metric-note">
          {{ formatNumber(overview.llm.prompt_tokens + overview.llm.completion_tokens) }} tokens
        </div>
      </div>
    </div>

    <div class="grid-4">
      <div class="metric">
        <div class="metric-label">模型成本</div>
        <div class="metric-value">{{ formatCost(overview.llm.cost_usd) }}</div>
        <div class="metric-note">demo 价格表未接入时为 0</div>
      </div>
      <div class="metric">
        <div class="metric-label">未关闭 Badcase</div>
        <div class="metric-value">{{ formatNumber(openBadcases) }}</div>
        <div class="metric-note">来自反馈回流</div>
      </div>
      <div class="metric">
        <div class="metric-label">审批单</div>
        <div class="metric-value">
          {{ formatNumber(overview.approvals.reduce((sum, item) => sum + item.count, 0)) }}
        </div>
        <div class="metric-note">
          {{ overview.approvals.map((item) => `${item.status}:${item.count}`).join(' · ') || '—' }}
        </div>
      </div>
      <div class="metric">
        <div class="metric-label">任务状态</div>
        <div class="metric-value">
          {{ formatNumber(overview.task_status.reduce((sum, item) => sum + item.count, 0)) }}
        </div>
        <div class="metric-note">
          {{ overview.task_status.map((item) => `${item.status}:${item.count}`).join(' · ') || '—' }}
        </div>
      </div>
    </div>

    <div class="grid-2">
      <section class="card">
        <h2>按层延迟</h2>
        <table class="table">
          <thead>
            <tr>
              <th>Layer</th>
              <th>Spans</th>
              <th>Errors</th>
              <th>平均延迟</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in overview.layers" :key="row.layer">
              <td><span class="badge" :class="layerClass(row.layer)">{{ row.layer }}</span></td>
              <td>{{ formatNumber(row.spans) }}</td>
              <td>{{ formatNumber(row.errors) }}</td>
              <td>{{ formatMs(row.avg_duration_ms) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!overview.layers.length" class="empty">还没有 span 数据</div>
      </section>

      <section class="card">
        <h2>最近 Trace</h2>
        <table class="table">
          <thead>
            <tr>
              <th>Trace</th>
              <th>状态</th>
              <th>Spans</th>
              <th>最大延迟</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="trace in overview.recent_traces" :key="trace.trace_id">
              <td>
                <RouterLink :to="`/trace/${trace.trace_id}`" class="mono small">
                  {{ trace.trace_id }}
                </RouterLink>
              </td>
              <td>
                <span class="badge" :class="statusClass(trace.task_status || '')">
                  {{ trace.task_status || '—' }}
                </span>
              </td>
              <td>{{ trace.span_count }}</td>
              <td>{{ formatMs(trace.max_duration_ms) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!overview.recent_traces.length" class="empty">还没有 trace</div>
      </section>
    </div>

    <section class="card">
      <div class="card-header">
        <h2>Badcase 回流</h2>
        <span class="badge">{{ badcases.length }} 条</span>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>Trace</th>
            <th>分类</th>
            <th>严重度</th>
            <th>状态</th>
            <th>期望 / 实际</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in badcases" :key="item.badcase_id">
            <td>
              <RouterLink :to="`/trace/${item.trace_id}`" class="mono small">
                {{ item.trace_id }}
              </RouterLink>
            </td>
            <td>{{ item.category }}</td>
            <td>{{ item.severity }}</td>
            <td><span class="badge" :class="statusClass(item.status)">{{ item.status }}</span></td>
            <td class="small">
              <div>{{ item.expected || '—' }}</div>
              <div class="muted">{{ item.actual || '—' }}</div>
            </td>
            <td>
              <button class="btn btn-ghost small" @click="markBadcase(item.badcase_id, 'reproduced')">
                标记复现
              </button>
              <button class="btn btn-ghost small" @click="markBadcase(item.badcase_id, 'fixed')">
                标记修复
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!badcases.length" class="empty">还没有 badcase；可在 Trace 回放页提交反馈</div>
    </section>
  </template>
</template>
