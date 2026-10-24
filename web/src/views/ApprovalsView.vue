<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { getJson, postJson, type ApprovalItem } from '../api'

const approvals = ref<ApprovalItem[]>([])
const status = ref('pending')
const loading = ref(false)
const errorText = ref('')
const comments = ref<Record<string, string>>({})
let timer: number | undefined

function statusClass(value: string) {
  if (['rejected', 'failed', 'cancelled'].includes(value.toLowerCase())) return 'badge-bad'
  if (['approved', 'completed'].includes(value.toLowerCase())) return 'badge-good'
  return 'badge-warn'
}

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    const data = await getJson<{ approvals: ApprovalItem[] }>(
      `/approvals?status=${status.value}`, 'u002',
    )
    approvals.value = data.approvals || []
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function decide(item: ApprovalItem, action: 'approve' | 'reject') {
  try {
    await postJson(
      `/admin/approvals/${item.approval_id}/${action}`,
      { comment: comments.value[item.approval_id] || '' },
      'u002',
    )
    await load()
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 3000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <section class="card">
    <div class="card-header">
      <div>
        <h2>审批工作台</h2>
        <div class="muted small">审批与对话分离；通过/驳回后任务会自动恢复。</div>
      </div>
      <div class="row">
        <select v-model="status" style="width: auto" @change="load">
          <option value="pending">待审批</option>
          <option value="approved">已通过</option>
          <option value="rejected">已驳回</option>
        </select>
        <button class="btn" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>
    <p v-if="errorText" class="error">{{ errorText }}</p>
  </section>

  <div v-if="!approvals.length" class="card empty">
    当前没有{{ status === 'pending' ? '待处理' : '' }}审批单
  </div>

  <section
    v-for="item in approvals"
    :key="item.approval_id"
    class="card approval-card"
  >
    <div class="card-header">
      <div>
        <div class="row">
          <span class="badge" :class="statusClass(item.status)">{{ item.status }}</span>
          <span class="mono small">{{ item.approval_id }}</span>
        </div>
        <div class="small muted" style="margin-top: 6px">
          tenant {{ item.tenant_id || '—' }} · user {{ item.user_id || '—' }} ·
          revision {{ item.revision }}
        </div>
      </div>
      <div class="row">
        <RouterLink v-if="item.trace_id" :to="`/trace/${item.trace_id}`" class="btn btn-ghost">
          Trace
        </RouterLink>
        <RouterLink
          v-if="item.task_id"
          :to="{ path: '/', query: { task: item.task_id } }"
          class="btn btn-ghost"
        >
          回到对话
        </RouterLink>
      </div>
    </div>

    <div class="grid-2">
      <div>
        <h3>差旅需求</h3>
        <table class="table">
          <tbody>
            <tr><th>任务</th><td class="mono small">{{ item.task_id }}</td></tr>
            <tr><th>目的地</th><td>{{ item.payload?.request?.destination_city || '—' }}</td></tr>
            <tr><th>日期</th><td>{{ item.payload?.request?.start_date || '—' }} → {{ item.payload?.request?.end_date || '—' }}</td></tr>
            <tr><th>预算</th><td>{{ item.payload?.request?.budget_limit ?? '—' }}</td></tr>
            <tr><th>住宿区域</th><td>{{ item.payload?.request?.hotel_area || '—' }}</td></tr>
            <tr><th>任务状态</th><td>{{ item.task_status || '—' }}</td></tr>
          </tbody>
        </table>
      </div>

      <div>
        <h3>超标原因</h3>
        <div v-if="item.payload?.policy_result?.violations?.length" class="event-list">
          <div
            v-for="(violation, index) in item.payload.policy_result.violations"
            :key="index"
            class="event"
          >
            <strong>{{ violation.rule_id }} · {{ violation.severity }}</strong>
            <div class="small">{{ violation.message }}</div>
            <div class="small muted">
              标准 {{ violation.limit ?? '—' }} / 实际 {{ violation.actual ?? '—' }}
            </div>
          </div>
        </div>
        <div v-else class="muted small">没有结构化违规明细</div>
      </div>
    </div>

    <h3 style="margin-top: 16px">候选方案</h3>
    <div class="grid-2">
      <div>
        <div class="small muted">机票</div>
        <table class="table">
          <tbody>
            <tr v-for="flight in (item.payload?.options?.flights || []).slice(0, 4)" :key="flight.option_id">
              <td class="mono small">{{ flight.flight_no || flight.option_id }}</td>
              <td>{{ flight.cabin }}</td>
              <td>{{ flight.price }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div>
        <div class="small muted">酒店</div>
        <table class="table">
          <tbody>
            <tr v-for="hotel in (item.payload?.options?.hotels || []).slice(0, 4)" :key="hotel.option_id">
              <td class="mono small">{{ hotel.hotel_name || hotel.option_id }}</td>
              <td>{{ hotel.area }}</td>
              <td>{{ hotel.price_per_night }}/晚</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="item.status === 'pending'" class="row" style="margin-top: 14px">
      <input
        v-model="comments[item.approval_id]"
        placeholder="审批意见（可空）"
        style="flex: 1"
      />
      <button class="btn btn-primary" @click="decide(item, 'approve')">通过</button>
      <button class="btn btn-danger" @click="decide(item, 'reject')">驳回</button>
    </div>
  </section>
</template>
