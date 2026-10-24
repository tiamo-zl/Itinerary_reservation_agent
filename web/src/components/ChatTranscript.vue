<script setup lang="ts">
import type { ChatMessage } from '../api'

defineProps<{
  messages: ChatMessage[]
  activeTaskId?: string | null
}>()
</script>

<template>
  <div>
    <div v-if="messages.length" class="chat-history">
      <div
        v-for="(item, index) in messages"
        :key="index"
        class="message"
        :class="[
          item.role,
          { 'message-trace': activeTaskId && item.task_id === activeTaskId },
        ]"
      >
        <div class="message-role">
          {{ item.role }}
          <span
            v-if="activeTaskId && item.task_id === activeTaskId"
            class="badge badge-trace"
          >
            本 trace
          </span>
        </div>
        <div class="message-content">{{ item.content }}</div>
      </div>
    </div>
    <div v-else class="empty">没有聊天消息</div>
  </div>
</template>
