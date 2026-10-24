<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getJson,
  postJson,
  type HistoryItem,
  type SpanNode,
  type TraceDetail,
} from '../api'

const route = useRoute()
const router = useRouter()
const traceId = ref(String(route.params.traceId || ''))
const detail = ref<TraceDetail | null>(null)
const history = ref<HistoryItem[]>([])
const loading = ref(false)
const errorText = ref('')
const feedbackMessage = ref('')
const feedback = ref({
  category: 'plan',
  severity: 'medium',
  user_input: '',
  expected: '',
  actual: '',
  comment: '',
})

const flatSpans = computed(() => {
  const rows: Array<{ span: SpanNode; depth: number }> = []
  const walk = (nodes: SpanNode[], depth: number) => {
    for (const node of nodes) {
      rows.push({ span: node, depth })
      walk(node.children || [], depth + 1)
    }
  }
  walk(detail.value?.spans || [], 0)
  return rows
})

function layerClass(layer: string) {
  return `layer-${layer}`
}

function statusClass(status: string) {
  if (status === 'error') return 'badge-bad'
  if (status === 'blocked') return 'badge-warn'
  return 'badge-good'
}

async function load() {
  if (!traceId.value.trim()) return
  loading.value = true
  errorText.value = ''
  history.value = []
  try {
    const data = await getJson<TraceDetail>(`/traces/${traceId.value}`)
    detail.value = data
    if (data.task_id) {
      const state = await getJson<{ history: HistoryItem[] }>(
        `/tasks/${data.task_id}/history`,
      )
      history.value = state.history || []
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
    detail.value = null
  } finally {
    loading.value = false
  }
}

function openTrace() {
  router.push(`/trace/${traceId.value.trim()}`)
}

async function submitFeedback() {
  feedbackMessage.value = ''
  try {
    const result = await postJson<{ badcase_id: string }>(
      '/feedback',
      {
        trace_id: traceId.value,
        task_id: detail.value?.task_id || null,
        ...feedback.value,
      },
      'u002',
    )
    feedbackMessage.value = `已回流为 badcase：${result.badcase_id}`
  } catch (error) {
    feedbackMessage.value = error instanceof Error ? error.message : String(error)
  }
}

watch(
  () => route.params.traceId,
  (value) => {
    traceId.value = String(value || '')
    if (traceId.value) load()
  },
)

onMounted(() => {
  if (traceId.value) load()
})
</script>

<template>
  <section class="card">
    <div class="card-header">
      <h2>Trace 回放</h2>
      <span v-if="detail?.task_status" class="badge badge-accent">{{ detail.task_status }}</span>
    </div>
    <div class="row">
      <input v-model="traceId" placeholder="输入 trace_id，例如 live-p1" @keyup.enter="openTrace" />
      <button class="btn btn-primary" :disabled="loading" @click="openTrace">
        {{ loading ? '加载中…' : '加载' }}
      </button>
    </div>
    <p v-if="errorText" class="error">{{ errorText }}</p>
  </section>

  <template v-if="detail">
    <div class="grid-2">
      <section class="card">
        <div class="card-header">
          <h2>调用树</h2>
          <span class="muted small">{{ flatSpans.length }} spans</span>
        </div>
        <div
          v-for="row in flatSpans"
          :key="row.span.span_id"
          class="trace-row"
        >
          <span class="badge" :class="layerClass(row.span.layer)">{{ row.span.layer }}</span>
          <div class="trace-main">
            <strong class="mono small">{{ row.span.name }}</strong>
            <div class="small muted">{{ row.span.duration_ms.toFixed(1) }} ms</div>
            <details v-if="Object.keys(row.span.attributes).length">
              <summary>attributes</summary>
              <pre>{{ JSON.stringify(row.span.attributes, null, 2) }}</pre>
            </details>
          </div>
          <span class="badge" :class="statusClass(row.span.status)">{{ row.span.status }}</span>
        </div>
        <div v-if="!flatSpans.length" class="empty">没有 span</div>
      </section>

      <section class="card">
        <h2>Checkpoint 状态历史</h2>
        <div v-if="detail.task_id" class="small muted mono">task {{ detail.task_id }}</div>
        <div v-if="history.length" class="event-list">
          <div v-for="(item, index) in history" :key="item.checkpoint_id || index" class="event">
            <strong>#{{ history.length - index }} · {{ item.created_at || 'unknown' }}</strong>
            <div class="small">next: {{ item.next.join(', ') || '—' }}</div>
            <details>
              <summary>values</summary>
              <pre>{{ JSON.stringify(item.values, null, 2) }}</pre>
            </details>
          </div>
        </div>
        <div v-else class="empty">该 trace 没有关联任务状态，或历史为空</div>
      </section>
    </div>

    <section class="card">
      <h2>反馈 / Badcase 回流</h2>
      <div class="grid-3">
        <div class="field">
          <label for="category">问题分类</label>
          <select id="category" v-model="feedback.category">
            <option value="understand">understand</option>
            <option value="plan">plan</option>
            <option value="tool">tool</option>
            <option value="policy">policy</option>
            <option value="rag">rag</option>
            <option value="approval">approval</option>
            <option value="booking">booking</option>
            <option value="other">other</option>
          </select>
        </div>
        <div class="field">
          <label for="severity">严重程度</label>
          <select id="severity" v-model="feedback.severity">
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
        </div>
        <div class="field">
          <label for="comment">备注</label>
          <input id="comment" v-model="feedback.comment" />
        </div>
      </div>
      <div class="field">
        <label for="user-input">用户输入</label>
        <textarea id="user-input" v-model="feedback.user_input" rows="2" />
      </div>
      <div class="grid-2">
        <div class="field">
          <label for="expected">期望结果</label>
          <textarea id="expected" v-model="feedback.expected" rows="3" />
        </div>
        <div class="field">
          <label for="actual">实际结果</label>
          <textarea id="actual" v-model="feedback.actual" rows="3" />
        </div>
      </div>
      <div class="row">
        <button class="btn btn-primary" @click="submitFeedback">提交反馈</button>
        <span v-if="feedbackMessage" class="small">{{ feedbackMessage }}</span>
      </div>
    </section>
  </template>
</template>
