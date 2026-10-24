<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  getJson,
  type ConversationDetail,
  type ConversationSummary,
} from '../api'

const route = useRoute()
const router = useRouter()
const user = ref('u002')
const conversations = ref<ConversationSummary[]>([])
const detail = ref<ConversationDetail | null>(null)
const loading = ref(false)
const loadingDetail = ref(false)
const errorText = ref('')

function statusClass(value: string | null | undefined) {
  const normalized = String(value || '').toLowerCase()
  if (['rejected', 'failed', 'cancelled'].includes(normalized)) return 'badge-bad'
  if (['waiting_approval', 'waiting_human', 'paused', 'pending'].includes(normalized)) {
    return 'badge-warn'
  }
  if (['completed', 'approved'].includes(normalized)) return 'badge-good'
  return ''
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function loadList() {
  loading.value = true
  errorText.value = ''
  try {
    const data = await getJson<{ conversations: ConversationSummary[] }>(
      '/conversations', user.value,
    )
    conversations.value = data.conversations || []
    if (detail.value && !conversations.value.some(
      (item) => item.session_id === detail.value?.session_id,
    )) {
      detail.value = null
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function loadDetail(sessionId: string) {
  loadingDetail.value = true
  errorText.value = ''
  try {
    detail.value = await getJson<ConversationDetail>(
      `/conversations/${sessionId}`, user.value,
    )
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
    detail.value = null
  } finally {
    loadingDetail.value = false
  }
}

function openConversation(item: ConversationSummary) {
  router.push(`/conversations/${item.session_id}`)
}

watch(
  () => route.params.sessionId,
  (value) => {
    if (value) loadDetail(String(value))
    else detail.value = null
  },
)

watch(user, () => {
  void loadList()
  if (detail.value) void loadDetail(detail.value.session_id)
})

onMounted(async () => {
  await loadList()
  const sessionId = route.params.sessionId
  if (sessionId) await loadDetail(String(sessionId))
})
</script>

<template>
  <section class="card">
    <div class="card-header">
      <div>
        <h2>对话记录</h2>
        <div class="muted small">审批人/管理员可查看全部会话；员工仅看自己的会话。</div>
      </div>
      <div class="row">
        <select v-model="user" style="width: auto">
          <option value="u002">u002 · 审批人（全部）</option>
          <option value="u001">u001 · 员工（仅自己）</option>
        </select>
        <button class="btn" :disabled="loading" @click="loadList">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>
    <p v-if="errorText" class="error">{{ errorText }}</p>

    <table class="table">
      <thead>
        <tr>
          <th>会话</th>
          <th>用户 / 租户</th>
          <th>最近消息</th>
          <th>消息数</th>
          <th>任务状态</th>
          <th>更新时间</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in conversations"
          :key="item.session_id"
          class="conversation-row"
          :class="{ active: item.session_id === detail?.session_id }"
          @click="openConversation(item)"
        >
          <td class="mono small">{{ item.session_id.slice(0, 16) }}</td>
          <td>
            <div>{{ item.user_id || '—' }}</div>
            <div class="small muted">{{ item.tenant_id || '—' }}</div>
          </td>
          <td class="session-preview" style="max-width: 360px">
            {{ item.last_message || '—' }}
          </td>
          <td>{{ item.message_count }}</td>
          <td>
            <span
              v-if="item.latest_task"
              class="badge"
              :class="statusClass(item.latest_task.status)"
            >
              {{ item.latest_task.status }}
            </span>
            <span v-else class="muted">—</span>
          </td>
          <td class="small muted">{{ formatTime(item.updated_at) }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="!conversations.length && !loading" class="empty">暂无对话记录</div>
  </section>

  <section v-if="detail" class="card">
    <div class="card-header">
      <div>
        <h2>对话详情</h2>
        <div class="mono small">{{ detail.session_id }}</div>
      </div>
      <div class="row">
        <RouterLink
          v-if="detail.latest_task"
          :to="{ path: '/', query: { task: detail.latest_task.task_id } }"
          class="btn btn-primary"
        >
          继续对话
        </RouterLink>
        <RouterLink
          v-if="detail.latest_task?.trace_id"
          :to="`/trace/${detail.latest_task.trace_id}`"
          class="btn"
        >
          Trace 回放
        </RouterLink>
      </div>
    </div>

    <div class="grid-2">
      <div>
        <h3>消息历史</h3>
        <div class="chat-history">
          <div
            v-for="(message, index) in detail.messages"
            :key="index"
            class="message"
            :class="message.role"
          >
            <div class="message-role">{{ message.role }}</div>
            <div class="message-content">{{ message.content }}</div>
          </div>
          <div v-if="!detail.messages.length" class="empty">没有消息</div>
        </div>
      </div>

      <div>
        <h3>任务</h3>
        <table class="table">
          <thead>
            <tr>
              <th>Task</th>
              <th>状态</th>
              <th>Revision</th>
              <th>Trace</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in detail.tasks" :key="task.task_id">
              <td class="mono small">{{ task.task_id.slice(0, 12) }}…</td>
              <td>
                <span class="badge" :class="statusClass(task.status)">{{ task.status }}</span>
              </td>
              <td>{{ task.revision }}</td>
              <td>
                <RouterLink v-if="task.trace_id" :to="`/trace/${task.trace_id}`">
                  trace
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="detail.latest_state" class="field" style="margin-top: 14px">
          <h3>当前进展</h3>
          <div class="small muted">
            next: {{ (detail.latest_state.next || []).join(', ') || '—' }}
          </div>
          <div v-if="detail.latest_state.values.approval" class="small">
            审批：
            <span class="badge" :class="statusClass(detail.latest_state.values.approval.status)">
              {{ detail.latest_state.values.approval.status }}
            </span>
          </div>
          <div
            v-if="detail.latest_state.values.pending_human?.message"
            class="small"
            style="margin-top: 8px"
          >
            待处理：{{ detail.latest_state.values.pending_human.message }}
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
