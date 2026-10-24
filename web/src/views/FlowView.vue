<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  getJson,
  type ApprovalItem,
  type ChatMessage,
  type FlowEdge,
  type FlowNode,
  type FlowStep,
  type TaskState,
  type TraceFlow,
} from '../api'
import ApprovalSummary from '../components/ApprovalSummary.vue'
import ChatTranscript from '../components/ChatTranscript.vue'

const route = useRoute()
const router = useRouter()
const traceId = ref(String(route.params.traceId || ''))
const flow = ref<TraceFlow | null>(null)
const messages = ref<ChatMessage[]>([])
const approvals = ref<ApprovalItem[]>([])
const stepIndex = ref(0)
const playing = ref(false)
const errorText = ref('')
let timer: number | undefined

const POS: Record<string, { x: number; y: number }> = {
  understand: { x: 20, y: 40 },
  plan: { x: 190, y: 40 },
  search: { x: 360, y: 40 },
  policy: { x: 530, y: 40 },
  approval: { x: 530, y: 190 },
  confirm: { x: 700, y: 40 },
  book: { x: 870, y: 40 },
  respond: { x: 1040, y: 40 },
}

const NODE_WIDTH = 130
const NODE_HEIGHT = 52

const hasApprovals = computed(() => approvals.value.length > 0)

const currentStep = computed<FlowStep | null>(() => {
  if (!flow.value) return null
  return flow.value.timeline[stepIndex.value] || null
})

const visibleSteps = computed(() => {
  if (!flow.value) return [] as FlowStep[]
  return flow.value.timeline.slice(0, stepIndex.value + 1)
})

const visitedNodes = computed(() => {
  const result = new Set<string>()
  for (const step of visibleSteps.value) {
    if (step.kind === 'node') result.add(step.node)
  }
  return result
})

const visitedEdges = computed(() => {
  const result = new Set<string>()
  for (const step of visibleSteps.value) {
    if (step.kind === 'edge') result.add(step.id)
  }
  return result
})

const activeNode = computed(() => {
  const step = currentStep.value
  return step?.kind === 'node' ? step.node : null
})

const activeEdge = computed(() => {
  const step = currentStep.value
  return step?.kind === 'edge' ? step.id : null
})

function edgePath(edge: FlowEdge) {
  const source = POS[edge.source]
  const target = POS[edge.target]
  if (!source || !target) return ''
  const sx = source.x + NODE_WIDTH / 2
  const sy = source.y + NODE_HEIGHT / 2
  const tx = target.x + NODE_WIDTH / 2
  const ty = target.y + NODE_HEIGHT / 2

  if (edge.source === 'understand' && edge.target === 'respond') {
    return `M ${sx} ${source.y} C ${sx + 120} 0, ${tx - 120} 0, ${tx} ${target.y}`
  }
  if (edge.source === 'confirm' && edge.target === 'plan') {
    return `M ${sx} ${source.y + NODE_HEIGHT} C ${sx - 100} 280, ${tx + 100} 280, ${tx} ${target.y + NODE_HEIGHT}`
  }
  if (edge.source === 'confirm' && edge.target === 'respond') {
    return `M ${sx} ${source.y} C 760 0, 1050 0, ${tx} ${target.y}`
  }
  if (edge.source === 'approval' && edge.target === 'confirm') {
    return `M ${source.x + NODE_WIDTH} ${sy} C ${sx + 70} ${sy}, ${tx - 70} ${ty}, ${target.x} ${ty}`
  }
  if (edge.source === 'policy' && edge.target === 'confirm') {
    return `M ${source.x + NODE_WIDTH} ${sy} L ${target.x} ${ty}`
  }
  if (edge.source === 'policy' && edge.target === 'approval') {
    return `M ${sx} ${source.y + NODE_HEIGHT} L ${tx} ${target.y}`
  }
  return `M ${source.x + NODE_WIDTH} ${sy} L ${target.x} ${ty}`
}

function stepText(step: FlowStep | null) {
  if (!step) return '—'
  if (step.kind === 'node') return `节点：${step.label}`
  return `边：${step.source} → ${step.target}（${step.label}）`
}

function stop() {
  if (timer) window.clearInterval(timer)
  timer = undefined
  playing.value = false
}

function start() {
  if (!flow.value?.timeline.length) return
  stop()
  playing.value = true
  timer = window.setInterval(() => {
    if (!flow.value) return
    if (stepIndex.value >= flow.value.timeline.length - 1) {
      stop()
      return
    }
    stepIndex.value += 1
  }, 1000)
}

function reset() {
  stop()
  stepIndex.value = 0
}

async function load() {
  if (!traceId.value.trim()) return
  stop()
  errorText.value = ''
  stepIndex.value = 0
  messages.value = []
  approvals.value = []
  try {
    const data = await getJson<TraceFlow>(
      `/traces/${traceId.value.trim()}/flow`,
    )
    flow.value = data
    if (data.task_id) {
      const state = await getJson<TaskState>(`/tasks/${data.task_id}/state`)
      const sessionId = state.values?.session_id
      if (sessionId) {
        const chat = await getJson<{ messages: ChatMessage[] }>(
          `/sessions/${sessionId}/messages`,
        )
        messages.value = chat.messages || []
      }
      try {
        const approvalData = await getJson<{ approvals: ApprovalItem[] }>(
          `/tasks/${data.task_id}/approvals`, 'u002',
        )
        approvals.value = approvalData.approvals || []
      } catch {
        approvals.value = []
      }
    }
    start()
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
    flow.value = null
  }
}

function openTrace() {
  if (!traceId.value.trim()) return
  router.push(`/flow/${traceId.value.trim()}`)
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

onUnmounted(stop)
</script>

<template>
  <section class="card">
    <div class="card-header">
      <div>
        <h2>编排流转图</h2>
        <div class="muted small">输入 trace_id，每秒推进一个实际流经的节点或边。</div>
      </div>
      <div class="row">
        <RouterLink v-if="flow?.task_id" :to="{ path: '/', query: { task: flow.task_id } }" class="btn">
          回到对话
        </RouterLink>
        <RouterLink v-if="traceId" :to="`/trace/${traceId}`" class="btn">Trace 回放</RouterLink>
      </div>
    </div>
    <div class="row">
      <input v-model="traceId" placeholder="trace_id" @keyup.enter="openTrace" />
      <button class="btn btn-primary" @click="openTrace">加载</button>
      <button class="btn" :disabled="playing || !flow" @click="start">播放</button>
      <button class="btn" :disabled="!playing" @click="stop">暂停</button>
      <button class="btn" :disabled="!flow" @click="reset">重置</button>
    </div>
    <p v-if="errorText" class="error">{{ errorText }}</p>
    <p v-if="flow" class="small">
      当前：<strong>{{ stepText(currentStep) }}</strong>
      <span class="muted">（{{ stepIndex + 1 }} / {{ flow.timeline.length }}）</span>
    </p>
  </section>

  <section v-if="flow" class="card">
    <div class="flow-scroll">
      <svg viewBox="0 0 1200 300" class="flow-svg" role="img" aria-label="编排流转图">
        <defs>
          <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
        </defs>

        <g v-for="edge in flow.edges" :key="edge.id">
          <path
            :d="edgePath(edge)"
            class="flow-edge"
            :class="{
              visited: visitedEdges.has(edge.id),
              active: activeEdge === edge.id,
            }"
            marker-end="url(#flow-arrow)"
          />
        </g>

        <g
          v-for="node in flow.nodes"
          :key="node.id"
          class="flow-node"
          :class="{
            visited: visitedNodes.has(node.id),
            active: activeNode === node.id,
          }"
        >
          <rect
            :x="POS[node.id]?.x ?? 0"
            :y="POS[node.id]?.y ?? 0"
            :width="NODE_WIDTH"
            :height="NODE_HEIGHT"
            rx="10"
          />
          <text
            :x="(POS[node.id]?.x ?? 0) + NODE_WIDTH / 2"
            :y="(POS[node.id]?.y ?? 0) + 31"
            text-anchor="middle"
          >{{ node.label }}</text>
        </g>
      </svg>
    </div>

    <div class="grid-2" style="margin-top: 16px">
      <div>
        <h3>边条件</h3>
        <div class="event-list">
          <div
            v-for="edge in flow.edges"
            :key="edge.id"
            class="event"
            :class="{ 'edge-active': activeEdge === edge.id }"
          >
            <strong>{{ edge.source }} → {{ edge.target }}</strong>
            <span class="badge" style="margin-left: 8px">{{ edge.label }}</span>
            <div class="small muted">{{ edge.condition }}</div>
          </div>
        </div>
      </div>

      <div>
        <h3>时间线</h3>
        <div class="event-list">
          <div
            v-for="(step, index) in flow.timeline"
            :key="index"
            class="event"
            :class="{ 'timeline-current': index === stepIndex, 'timeline-future': index > stepIndex }"
          >
            <strong>{{ index + 1 }}. {{ stepText(step) }}</strong>
            <div class="small muted">{{ step.at }}</div>
          </div>
          <div v-if="!flow.timeline.length" class="empty">该 trace 没有编排节点 span</div>
        </div>
      </div>
    </div>
  </section>

  <div v-if="flow" class="grid-2" style="margin-top: 18px">
    <section class="card">
      <h2>聊天对话</h2>
      <div class="small muted" style="margin-bottom: 8px">
        {{ hasApprovals
          ? '该 trace 有审批记录，橙色高亮在审批信息；聊天记录不再高亮。'
          : '橙色为本 trace 对应任务的消息。' }}
      </div>
      <ChatTranscript
        :messages="messages"
        :active-task-id="hasApprovals ? null : flow.task_id"
      />
    </section>

    <section class="card">
      <h2>审批信息</h2>
      <ApprovalSummary :approvals="approvals" :highlight="hasApprovals" />
    </section>
  </div>
</template>
