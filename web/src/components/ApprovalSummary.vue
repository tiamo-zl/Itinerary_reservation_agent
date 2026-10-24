<script setup lang="ts">
import type { ApprovalItem } from '../api'

defineProps<{
  approvals: ApprovalItem[]
  highlight?: boolean
}>()

function statusClass(status: string) {
  if (status === 'rejected') return 'badge-bad'
  if (status === 'approved') return 'badge-good'
  return 'badge-warn'
}
</script>

<template>
  <div v-if="approvals.length" class="event-list">
    <div
      v-for="item in approvals"
      :key="item.approval_id"
      class="event"
      :class="{ 'approval-highlight': highlight }"
    >
      <div class="row">
        <span class="badge" :class="statusClass(item.status)">{{ item.status }}</span>
        <span class="mono small">{{ item.approval_id }}</span>
      </div>
      <div class="small muted" style="margin-top: 6px">
        revision {{ item.revision }} · {{ item.created_at }}
      </div>
      <div v-if="item.comment" class="small">审批意见：{{ item.comment }}</div>
      <details v-if="item.payload?.policy_result?.violations?.length">
        <summary>超标明细</summary>
        <div
          v-for="(violation, index) in item.payload.policy_result.violations"
          :key="index"
          class="small"
        >
          {{ violation.rule_id }} · {{ violation.message }}
        </div>
      </details>
      <details v-if="item.payload?.request">
        <summary>差旅需求</summary>
        <pre>{{ JSON.stringify(item.payload.request, null, 2) }}</pre>
      </details>
    </div>
  </div>
  <div v-else class="empty">该任务没有审批记录</div>
</template>
