import { createRouter, createWebHistory } from 'vue-router'
import { APP_PREFIX } from '@/utils/appPrefix'

const router = createRouter({
  // Use APP_PREFIX as the history base so router-link paths and the
  // browser URL bar stay aligned with the backend's mount point.
  // import.meta.env.BASE_URL is now `./` (Vite's relative-base mode),
  // which is fine for asset resolution but not a valid history base --
  // the prefix injected at runtime is what we want here.
  history: createWebHistory(APP_PREFIX || '/'),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/party/:id',
      name: 'party',
      component: () => import('@/views/PartyView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
    },
    {
      path: '/version',
      name: 'version',
      component: () => import('@/views/AboutView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
})

export default router
