<template>
  <div id="app">
    <!-- 简约导航栏 -->
    <header class="app-header">
      <router-link to="/" class="logo">
        <h1>NASSAV</h1>
      </router-link>
    </header>

    <!-- 主内容区 -->
    <main class="app-main">
      <!-- 添加keep-alive缓存列表页 -->
      <router-view v-slot="{ Component }">
        <keep-alive :include="['HomeView']">
          <component :is="Component" :key="$route.fullPath" />
        </keep-alive>
      </router-view>
    </main>

    <!-- 底部信息 -->
    <footer class="app-footer">
      <p>© 2025 NASSAV，你的NAS小姐姐助手</p>
    </footer>
  </div>
</template>

<script>
export default {
  name: 'App'
}
</script>

<style>
/* 全局基础样式 */
/* 更新全局变量为粉色系 */
:root {
  --primary-color: #ff9bb3; /* 主粉色 */
  --secondary-color: #ff6b8b; /* 深粉色 */
  --accent-color: #ffcdd8; /* 浅粉色 */
  --text-color: #5a3a4a; /* 深紫色文字 */
}

body {
  background-color: #fff5f7; /* 非常浅的粉色背景 */
}

.app-header {
  background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
  color: white;
  padding: 1.2rem 2rem;
  box-shadow: 0 4px 15px rgba(255, 107, 139, 0.2);
}

.app-footer {
  background: linear-gradient(135deg, var(--secondary-color), #ff4777);
  color: white;
  padding: 1.2rem;
  font-size: 0.9rem;
}

/* 更新过渡动画 */
.fade-enter-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.fade-leave-active {
  transition: all 0.2s cubic-bezier(0.4, 0, 1, 1);
}

.logo {
  color: white;
  text-decoration: none;
}

.logo h1 {
  font-size: 1.5rem;
  font-weight: 500;
}

/* 主内容区 */
.app-main {
  flex: 1;
  padding: 2rem;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}

/* 底部样式 */
.app-footer {
  text-align: center;
  padding: 1rem;
  background-color: var(--secondary-color);
  color: white;
}

/* 路由过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .app-main {
    padding: 1rem;
  }
  
  .video-grid {
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 15px;
  }
  
  .gallery-grid {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }
  
  .detail-container {
    padding: 1rem;
  }
}

#app {
    overflow-x: hidden; /* 防止横向溢出 */
    width: 100%;
}

* {
    box-sizing: border-box; /* 统一盒模型 */
}

@keyframes pinkPulse {
  0% { box-shadow: 0 0 0 0 rgba(255, 107, 139, 0.4); }
  70% { box-shadow: 0 0 0 10px rgba(255, 107, 139, 0); }
  100% { box-shadow: 0 0 0 0 rgba(255, 107, 139, 0); }
}

.highlight {
  animation: pinkPulse 1.5s infinite;
}

button {
  background-color: var(--primary-color);
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 50px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.3s ease;
  box-shadow: 0 2px 5px rgba(255, 107, 139, 0.3);
}

button:hover {
  background-color: var(--secondary-color);
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(255, 107, 139, 0.4);
}
</style>