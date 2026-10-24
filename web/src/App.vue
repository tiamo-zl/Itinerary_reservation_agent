<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div>
        <div class="eyebrow">Itinerary Agent</div>
        <h1>差旅 Agent 控制台</h1>
      </div>
      <nav class="nav" aria-label="主导航">
        <RouterLink to="/">对话</RouterLink>
        <RouterLink to="/conversations">对话记录</RouterLink>
        <RouterLink to="/approvals">审批</RouterLink>
        <RouterLink to="/flow">流转图</RouterLink>
        <RouterLink to="/trace">Trace 回放</RouterLink>
        <RouterLink to="/overview">线上概览</RouterLink>
      </nav>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
