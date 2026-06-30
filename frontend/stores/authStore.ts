/**
 * 认证状态：access / refresh token + 当前用户。
 * 持久化到 localStorage（一期方案，后续可切 httpOnly cookie）。
 */
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { api, bindAuthHandlers } from '@/lib/api';
import type { TokenResponse, UserPublic } from '@/types/api';

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserPublic | null;
  hydrated: boolean;

  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  loadCurrentUser: () => Promise<void>;
  setTokens: (access: string, refresh: string) => void;
  clear: () => void;
  setHydrated: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      hydrated: false,

      setTokens: (access, refresh) => set({ accessToken: access, refreshToken: refresh }),

      clear: () => set({ accessToken: null, refreshToken: null, user: null }),

      setHydrated: () => set({ hydrated: true }),

      login: async (username, password) => {
        // FastAPI OAuth2PasswordRequestForm 要求 form 格式
        const body = new URLSearchParams({ username, password });
        const resp = await api.post<TokenResponse>('/api/auth/login', body, {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        });
        set({
          accessToken: resp.data.access_token,
          refreshToken: resp.data.refresh_token,
        });
        await get().loadCurrentUser();
      },

      logout: () => {
        set({ accessToken: null, refreshToken: null, user: null });
      },

      loadCurrentUser: async () => {
        const resp = await api.get<UserPublic>('/api/auth/me');
        set({ user: resp.data });
      },
    }),
    {
      name: 'colony-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
      // hydration 完成时一定会触发（onFinishHydration 可能因订阅晚而错过）
      onRehydrateStorage: () => (state) => {
        state?.setHydrated();
      },
    },
  ),
);

// 绑定 axios 拦截器所需的 token 访问函数（服务端 / 客户端通用，SSR 时返回 null）
bindAuthHandlers({
  getAccessToken: () => useAuthStore.getState().accessToken,
  getRefreshToken: () => useAuthStore.getState().refreshToken,
  setTokens: (access, refresh) => useAuthStore.getState().setTokens(access, refresh),
  clearAuth: () => useAuthStore.getState().clear(),
});

// 兜底：若上面的回调因 SSR / race 没触发，浏览器端再校一次
if (typeof window !== 'undefined') {
  if (useAuthStore.persist.hasHydrated()) {
    useAuthStore.getState().setHydrated();
  } else {
    const unsub = useAuthStore.persist.onFinishHydration(() => {
      useAuthStore.getState().setHydrated();
      unsub();
    });
  }

  // 多 tab 同步：当任意 tab logout / refresh token 时，其它 tab 跟进
  // 避免旧 token 继续用、或两个 tab 同时用旧 refresh_token 去 /refresh 造成双重发放
  window.addEventListener('storage', (e) => {
    if (e.key !== 'colony-auth' || e.newValue === e.oldValue) return;
    try {
      const parsed = e.newValue ? JSON.parse(e.newValue) : null;
      const state = parsed?.state;
      if (!state || !state.accessToken) {
        // 别的 tab 登出了
        useAuthStore.getState().clear();
      } else {
        // 别的 tab 拿到了新 token（比如刚刷新）→ 本 tab 同步
        const cur = useAuthStore.getState();
        if (
          state.accessToken !== cur.accessToken ||
          state.refreshToken !== cur.refreshToken
        ) {
          useAuthStore
            .getState()
            .setTokens(state.accessToken, state.refreshToken);
        }
      }
    } catch {
      // JSON parse 失败就忽略
    }
  });
}
