import { createRouter, createWebHistory } from 'vue-router'

import ChatView from './views/ChatView.vue'
import OverviewView from './views/OverviewView.vue'
import TraceView from './views/TraceView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/trace/:traceId?', name: 'trace', component: TraceView },
    { path: '/overview', name: 'overview', component: OverviewView },
  ],
  linkActiveClass: 'active',
})
