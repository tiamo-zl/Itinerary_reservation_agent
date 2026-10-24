<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { getJson, streamPost, type SSEEvent, type TaskState } from '../api'

const route = useRoute()
const user = ref('u002')
const message = ref('下周二去北京出差两天，住王府井附近，预算 1000 元')
const events = ref<SSEEvent[]>([])
const busy = ref(false)
const loadingTask = ref(false)
const errorText = ref('')
const taskId = ref('')
const traceId = ref('')
const taskStatus = ref('')
const loadTaskId = ref(String(route.query.task || ''))
const interrupt = ref<Record<string, any> | null>(null)
const showModify = ref(false)
const amended = ref({
  destination_city: '上海',
  start_date: '',
  end_date: '',
  budget_limit: '',
})

const isApproval = computed(() => interrupt.value?.kind === 'approval')
const options = computed<Array<Record<string, any>>>(() =>
  Array.isArray(interrupt.value?.options) ? interrupt.value.options : [],
)

function eventLabel(event: SSEEvent): string {
  const data = event.data || {}
  if (data.node) return `${event.type} · ${data.node}`
  if (data.status) return `${event.type} · ${data.status}`
  if (data.code) return `${event.type} · ${data.code}`
  if (data.message) return `${event.type} · ${data.message}`
  return event.type
}

function handleEvent(event: SSEEvent) {
  events.value.push(event)
  const data = event.data || {}
  if (data.task_id) taskId.value = data.task_id
  if (data.trace_id) traceId.value = data.trace_id
  if (data.status) taskStatus.value = data.status
  if (event.type === 'interrupt') {
    interrupt.value = data.human_request || null
    showModify.value = false
  }
  if (event.type === 'result' || event.type === 'error') {
    if (event.type === 'error') errorText.value = data.message || '请求失败'
    interrupt.value = null
  }
}

async function run(path: string, payload: unknown) {
  busy.value = true
  errorText.value = ''
  try {
    await streamPost(path, payload, user.value, handleEvent)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    busy.value = false
  }
}

async function send() {
  events.value = []
  taskId.value = ''
  traceId.value = ''
  taskStatus.value = ''
  interrupt.value = null
  await run('/chat', { message: message.value })
}

async function loadTask() {
  if (!loadTaskId.value.trim()) return
  loadingTask.value = true
  errorText.value = ''
  try {
    const state = await getJson<TaskState>(`/tasks/${loadTaskId.value.trim()}/state`)
    taskId.value = loadTaskId.value.trim()
    traceId.value = String(state.values.trace_id || '')
    taskStatus.value = String(state.values.status || '')
    const next = state.next || []
    if (next.includes('approval')) {
      interrupt.value = {
        kind: 'approval',
        message: '该任务需要审批，请前往审批工作台处理。',
      }
    } else if (next.includes('confirm')) {
      interrupt.value = {
        type: 'confirm_option',
        message: '请确认方案后继续下单。',
        options: state.values.options?.flights || [],
      }
    } else {
      interrupt.value = null
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loadingTask.value = false
  }
}

async function resume(payload: unknown) {
  if (!taskId.value) return
  interrupt.value = null
  await run(`/tasks/${taskId.value}/resume`, payload)
}

async function confirmFirst() {
  await resume({ action: 'select' })
}

async function cancelTask() {
  await resume({ action: 'cancel' })
}

async function submitModify() {
  const request: Record<string, unknown> = {
    destination_city: amended.value.destination_city,
    start_date: amended.value.start_date || null,
    end_date: amended.value.end_date || null,
  }
  if (amended.value.budget_limit) {
    request.budget_limit = Number(amended.value.budget_limit)
  }
  await resume({ action: 'modify', amended_request: request })
}

onMounted(() => {
  if (loadTaskId.value) loadTask()
})
</script>

<template>
  <div class="grid-2">
    <section class="card">
      <div class="card-header">
        <h2>差旅助手</h2>
        <span class="badge" :class="user === 'u002' ? 'badge-accent' : ''">
          {{ user === 'u002' ? '审批人视图' : '员工视图' }}
        </span>
      </div>

      <div class="field">
        <label for="user">模拟用户</label>
        <select id="user" v-model="user" :disabled="busy">
          <option value="u001">u001 · L2 员工（会触发超标审批）</option>
          <option value="u002">u002 · L3 员工/审批人</option>
        </select>
      </div>

      <div class="field">
        <label for="message">自然语言需求</label>
        <textarea id="message" v-model="message" rows="4" :disabled="busy" />
      </div>

      <div class="row">
        <button class="btn btn-primary" :disabled="busy || !message.trim()" @click="send">
          {{ busy ? '处理中…' : '发送' }}
        </button>
        <span v-if="taskId" class="muted small mono">task {{ taskId }}</span>
      </div>

      <p v-if="errorText" class="error">{{ errorText }}</p>

      <div class="event-list" aria-live="polite">
        <div v-for="(event, index) in events" :key="index" class="event">
          <strong>{{ eventLabel(event) }}</strong>
          <div v-if="event.data?.summary" class="small">{{ event.data.summary }}</div>
        </div>
        <div v-if="!events.length" class="empty">发送一条差旅需求开始对话</div>
      </div>
    </section>

    <aside class="card">
      <h2>任务与人工决策</h2>

      <div class="field">
        <label for="load-task">按 task_id 加载（审批后回到此页时用）</label>
        <div class="row">
          <input
            id="load-task"
            v-model="loadTaskId"
            placeholder="task_id"
            style="flex: 1"
          />
          <button class="btn" :disabled="loadingTask" @click="loadTask">加载</button>
        </div>
      </div>

      <div v-if="taskId" class="field">
        <div class="small muted">当前任务</div>
        <div class="mono small">{{ taskId }}</div>
        <div v-if="taskStatus" class="row" style="margin-top: 6px">
          <span class="badge">{{ taskStatus }}</span>
          <RouterLink v-if="traceId" :to="`/trace/${traceId}`">Trace 回放 →</RouterLink>
        </div>
      </div>

      <div v-if="interrupt" class="field">
        <h3>需要处理</h3>
        <p>{{ interrupt.message }}</p>

        <template v-if="isApproval">
          <p class="muted small">
            对话与审批已分离。审批通过后，回到本页点击“加载”继续确认方案。
          </p>
          <RouterLink class="btn btn-primary" to="/approvals">前往审批工作台</RouterLink>
        </template>

        <template v-else>
          <div v-if="options.length" class="small muted">
            候选：{{ options.slice(0, 3).map((option) => option.flight_no || option.option_id).join(' / ') }}
          </div>
          <div class="row">
            <button class="btn btn-primary" :disabled="busy" @click="confirmFirst">确认第一个方案</button>
            <button class="btn btn-ghost" :disabled="busy" @click="showModify = !showModify">修改需求</button>
            <button class="btn btn-danger" :disabled="busy" @click="cancelTask">取消任务</button>
          </div>

          <div v-if="showModify" class="modify-form">
            <div class="field">
              <label for="destination">目的地</label>
              <input id="destination" v-model="amended.destination_city" />
            </div>
            <div class="field">
              <label for="start-date">出发日期</label>
              <input id="start-date" v-model="amended.start_date" placeholder="YYYY-MM-DD" />
            </div>
            <div class="field">
              <label for="end-date">结束日期</label>
              <input id="end-date" v-model="amended.end_date" placeholder="YYYY-MM-DD" />
            </div>
            <div class="field">
              <label for="budget">预算</label>
              <input id="budget" v-model="amended.budget_limit" inputmode="decimal" />
            </div>
            <button class="btn btn-primary" :disabled="busy" @click="submitModify">提交修改</button>
          </div>
        </template>
      </div>

      <p v-else-if="taskId && taskStatus === 'COMPLETED'" class="ok small">
        任务已完成。
      </p>
      <p v-else class="muted small">
        当差标超标或需要确认时，这里会出现审批/确认/修改操作。
      </p>
    </aside>
  </div>
</template>
