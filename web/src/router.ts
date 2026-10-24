import { createRouter, createWebHistory } from 'vue-router'

import ApprovalsView from './views/ApprovalsView.vue'
import ChatView from './views/ChatView.vue'
import ConversationsView from './views/ConversationsView.vue'
import OverviewView from './views/OverviewView.vue'
import TraceView from './views/TraceView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/conversations/:sessionId?', name: 'conversations', component: ConversationsView },
    { path: '/approvals', name: 'approvals', component: ApprovalsView },
    { path: '/trace/:traceId?', name: 'trace', component: TraceView },
    { path: '/overview', name: 'overview', component: OverviewView },
  ],
  linkActiveClass: 'active',
})
